"""Pulling what the provider says we used, and comparing it to our own books.

This is the reconciliation side of the ledger. Our records say what we
charged customers and what we believe each call cost; Twilio's say what they
are actually going to invoice. A gap between them means one of two things,
and both cost money:

* usage we never attributed to a call -- someone else's traffic on the
  account, a failed call still billed, a number rental nobody tracked;
* calls we billed a customer for that the carrier has no record of.

Three things make this safe to run repeatedly.

**Parent categories are stored but never summed.** Twilio nests usage:
`calls` contains `calls-outbound`, which contains `calls-outbound-mobile`.
Adding every row returned would count the same minute three times and make
the reconciliation look catastrophically wrong in the direction that
suggests we are under-charging.

**Writes are idempotent** on (connection, category, period), so a re-run
updates rather than duplicating.

**A failed run is recorded, not swallowed.** A sync that silently stops is
indistinguishable from a provider with no usage, and the second is what an
operator will assume.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.money import ZERO, quantize_cost, to_decimal
from app.models.call import Call
from app.models.provider import (
    ProviderBalance,
    ProviderConnection,
    ProviderSyncRun,
    ProviderUsageRecord,
)

log = get_logger(__name__)

API = "https://api.twilio.com/2010-04-01/Accounts"


#: Twilio's own grand total for the period. It is the authoritative answer
#: to "what did this cost", and it is also a row in the same feed as every
#: category -- so summing the feed counts everything roughly twice.
TOTAL_CATEGORY = "totalprice"

#: Categories that overlap others without sharing a name prefix. Twilio
#: reports recordings both under `recordings` and under `calls-recordings`,
#: and phone numbers under both `phonenumbers` and `phonenumbers-local`.
#: The hyphen rule below cannot see these, so they are named.
OVERLAPPING_ROLLUPS = frozenset({"recordings", "phonenumbers", "calls", "sms", "mms"})


def _parent_of(category: str) -> str | None:
    """`calls-outbound-mobile` -> `calls-outbound`. Top level returns None."""
    if "-" not in category:
        return None
    return category.rsplit("-", 1)[0]


def _is_rollup(category: str) -> bool:
    """Whether this row double-counts spend reported elsewhere."""
    return category == TOTAL_CATEGORY or category in OVERLAPPING_ROLLUPS


@dataclass
class Reconciliation:
    """What the provider says against what we recorded."""

    provider_cost: Decimal
    our_recorded_cost: Decimal
    period_start: datetime
    period_end: datetime
    categories: int

    @property
    def difference(self) -> Decimal:
        return quantize_cost(self.provider_cost - self.our_recorded_cost)

    @property
    def difference_percent(self) -> Decimal | None:
        if self.provider_cost <= ZERO:
            return None
        return quantize_cost(self.difference / self.provider_cost * 100)

    def as_dict(self) -> dict:
        return {
            "provider_cost_usd": str(self.provider_cost),
            "our_recorded_cost_usd": str(self.our_recorded_cost),
            "difference_usd": str(self.difference),
            "difference_percent": (
                None if self.difference_percent is None else str(self.difference_percent)
            ),
            "categories": self.categories,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            #: Unattributed usage is the expensive direction: we paid for it
            #: and charged nobody.
            "unattributed": self.difference > ZERO,
        }


class ProviderSyncService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _run(self, connection_id: uuid.UUID, kind: str) -> ProviderSyncRun:
        run = ProviderSyncRun(
            connection_id=connection_id,
            kind=kind,
            status="running",
            started_at=datetime.now(UTC),
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def sync_balance(self, connection: ProviderConnection) -> ProviderBalance | None:
        """Record the account balance as the provider reports it.

        Stored as a series rather than one mutable column, so "we ran out at
        2am" stays answerable afterwards.
        """
        from app.services.credentials import resolve

        run = await self._run(connection.id, "balance")
        creds = await resolve(connection.slug)
        sid, token = creds.get("account_sid", ""), creds.get("auth_token", "")
        if not (sid and token):
            run.status, run.error = "failed", "No credentials"
            run.finished_at = datetime.now(UTC)
            await self.db.commit()
            return None

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(f"{API}/{sid}/Balance.json", auth=(sid, token))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            run.status, run.error = "failed", str(exc)
            run.finished_at = datetime.now(UTC)
            await self.db.commit()
            log.warning("provider.balance_sync_failed", error=str(exc))
            return None

        payload = response.json()
        balance = ProviderBalance(
            connection_id=connection.id,
            balance=to_decimal(payload.get("balance")),
            currency=payload.get("currency", "USD"),
            observed_at=datetime.now(UTC),
            raw=payload,
        )
        self.db.add(balance)
        connection.last_synced_at = datetime.now(UTC)
        run.status, run.records, run.finished_at = "ok", 1, datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(balance)
        return balance

    async def sync_usage(self, connection: ProviderConnection, *, days: int = 30) -> int:
        """Pull daily usage records and store them, parents flagged.

        Paginated: Twilio caps a page at 1000 and a busy month exceeds that
        easily, so a single-page fetch would silently under-report.
        """
        from app.services.credentials import resolve

        run = await self._run(connection.id, "usage")
        creds = await resolve(connection.slug)
        sid, token = creds.get("account_sid", ""), creds.get("auth_token", "")
        if not (sid and token):
            run.status, run.error = "failed", "No credentials"
            run.finished_at = datetime.now(UTC)
            await self.db.commit()
            return 0

        start = (datetime.now(UTC) - timedelta(days=days)).date()
        url: str | None = (
            f"{API}/{sid}/Usage/Records/Daily.json?StartDate={start.isoformat()}&PageSize=200"
        )
        stored = 0

        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                while url:
                    response = await client.get(url, auth=(sid, token))
                    response.raise_for_status()
                    payload = response.json()

                    for row in payload.get("usage_records", []):
                        stored += await self._store(connection, row)

                    nxt = payload.get("next_page_uri")
                    url = f"https://api.twilio.com{nxt}" if nxt else None
        except httpx.HTTPError as exc:
            run.status, run.error = "failed", str(exc)
            run.records, run.finished_at = stored, datetime.now(UTC)
            await self.db.commit()
            log.warning("provider.usage_sync_failed", error=str(exc), stored=stored)
            return stored

        await self._mark_rollups(connection)
        connection.last_synced_at = datetime.now(UTC)
        run.status, run.records, run.finished_at = "ok", stored, datetime.now(UTC)
        await self.db.commit()
        return stored

    async def _mark_rollups(self, connection: ProviderConnection) -> None:
        """Second pass: flag every row that something else sits beneath.

        Has to run after the whole feed is stored. Done per row during the
        sync, a parent written before its children is never flagged, and the
        sum then includes both.
        """
        rows = await self.db.execute(
            select(ProviderUsageRecord).where(ProviderUsageRecord.connection_id == connection.id)
        )
        records = list(rows.scalars())
        parents = {r.parent_category for r in records if r.parent_category}
        for record in records:
            record.is_parent = record.category in parents or _is_rollup(record.category)

    async def _store(self, connection: ProviderConnection, row: dict) -> int:
        category = row.get("category", "")
        if not category:
            return 0

        def _parse(value: str | None) -> datetime:
            if not value:
                return datetime.now(UTC)
            return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=UTC)

        period_start, period_end = _parse(row.get("start_date")), _parse(row.get("end_date"))
        parent = _parent_of(category)

        existing = await self.db.execute(
            select(ProviderUsageRecord).where(
                ProviderUsageRecord.connection_id == connection.id,
                ProviderUsageRecord.category == category,
                ProviderUsageRecord.period_start == period_start,
                ProviderUsageRecord.period_end == period_end,
            )
        )
        record = existing.scalars().first()
        price = quantize_cost(abs(to_decimal(row.get("price"))))

        if record is None:
            record = ProviderUsageRecord(
                connection_id=connection.id,
                category=category,
                period_start=period_start,
                period_end=period_end,
            )
            self.db.add(record)

        record.description = row.get("description")
        record.parent_category = parent
        # A row is a parent when the feed also contains something beneath it.
        # Marked here and excluded from every sum.
        record.is_parent = bool(
            await self.db.scalar(
                select(func.count())
                .select_from(ProviderUsageRecord)
                .where(
                    ProviderUsageRecord.connection_id == connection.id,
                    ProviderUsageRecord.parent_category == category,
                )
            )
        )
        record.quantity = to_decimal(row.get("count") or row.get("usage"))
        record.unit = row.get("usage_unit") or row.get("count_unit")
        record.cost = price
        record.currency = row.get("price_unit", "USD").upper()
        # Twilio invoices in USD, so no conversion is needed; the field is
        # kept distinct anyway, because assuming they are the same is exactly
        # the mistake that put INR into USD columns elsewhere.
        record.cost_usd = price if record.currency == "USD" else None
        record.synced_at = datetime.now(UTC)
        record.raw = row
        return 1

    async def reconcile(self, connection: ProviderConnection, *, days: int = 30) -> Reconciliation:
        """Compare the provider's own total against what we recorded.

        Leaf categories only. Including parents would triple-count minutes
        and report a gap that does not exist.
        """
        since = datetime.now(UTC) - timedelta(days=days)

        # Twilio publishes its own total for the period. Trust it over a sum
        # of categories: the feed mixes leaves with several overlapping
        # rollups, and reconstructing the total from the parts is how the
        # same minute gets counted three times.
        total = await self.db.scalar(
            select(func.coalesce(func.sum(ProviderUsageRecord.cost_usd), 0)).where(
                ProviderUsageRecord.connection_id == connection.id,
                ProviderUsageRecord.period_start >= since,
                ProviderUsageRecord.category == TOTAL_CATEGORY,
            )
        )

        rows = await self.db.execute(
            select(
                func.coalesce(func.sum(ProviderUsageRecord.cost_usd), 0),
                func.count(),
            ).where(
                ProviderUsageRecord.connection_id == connection.id,
                ProviderUsageRecord.period_start >= since,
                ProviderUsageRecord.is_parent.is_(False),
            )
        )
        summed, categories = rows.one()
        # Fall back to the summed leaves only when the provider gave us no
        # total, which happens on an account with no usage at all.
        provider_cost = total if to_decimal(total) > ZERO else summed

        ours = await self.db.scalar(
            select(func.coalesce(func.sum(Call.cost_usd), 0.0)).where(Call.created_at >= since)
        )

        return Reconciliation(
            provider_cost=quantize_cost(provider_cost),
            our_recorded_cost=quantize_cost(ours),
            period_start=since,
            period_end=datetime.now(UTC),
            categories=int(categories or 0),
        )
