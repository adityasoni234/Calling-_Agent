"""Provider reconciliation: the arithmetic that must not double-count."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.call import Call, CallStatus
from app.models.organization import Organization
from app.models.provider import (
    ProviderConnection,
    ProviderKind,
    ProviderUsageRecord,
)
from app.models.user import User
from app.services.provider_sync import ProviderSyncService, _parent_of
from tests.conftest import REGISTRATION


async def _connection(db_session) -> ProviderConnection:
    connection = ProviderConnection(slug="twilio", label="Twilio", kind=ProviderKind.TELEPHONY)
    db_session.add(connection)
    await db_session.commit()
    return connection


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


def _usage(connection_id, category, cost, *, parent=False, days_ago=1):
    when = datetime.now(UTC) - timedelta(days=days_ago)
    return ProviderUsageRecord(
        connection_id=connection_id,
        category=category,
        parent_category=_parent_of(category),
        is_parent=parent,
        cost=Decimal(cost),
        cost_usd=Decimal(cost),
        currency="USD",
        quantity=Decimal("1"),
        period_start=when,
        period_end=when,
        synced_at=when,
    )


def test_a_nested_category_knows_its_parent() -> None:
    assert _parent_of("calls-outbound-mobile") == "calls-outbound"
    assert _parent_of("calls-outbound") == "calls"
    assert _parent_of("calls") is None


async def test_parent_categories_are_never_summed(db_session, auth_headers) -> None:
    """Twilio nests usage; adding every row triples the same minute.

    The failure mode this prevents is the worst kind: the reconciliation
    looks catastrophically wrong in the direction suggesting we undercharge,
    which is exactly the direction someone acts on.
    """
    connection = await _connection(db_session)
    db_session.add(_usage(connection.id, "calls", "30.00", parent=True))
    db_session.add(_usage(connection.id, "calls-outbound", "30.00", parent=True))
    db_session.add(_usage(connection.id, "calls-outbound-mobile", "30.00"))
    await db_session.commit()

    result = await ProviderSyncService(db_session).reconcile(connection)
    # The leaf only, not 90.
    assert result.provider_cost == Decimal("30.000000")
    assert result.categories == 1


async def test_unattributed_usage_is_reported_as_the_expensive_direction(
    db_session, auth_headers
) -> None:
    """We paid the carrier for traffic no call accounts for."""
    connection = await _connection(db_session)
    org = await _org(db_session)
    db_session.add(_usage(connection.id, "calls-outbound-mobile", "50.00"))
    db_session.add(
        Call(
            organization_id=org.id,
            direction="outbound",
            provider="twilio",
            from_number="+10000000000",
            to_number="+919876543210",
            status=CallStatus.COMPLETED,
            duration_seconds=60,
            cost_usd=20.0,
        )
    )
    await db_session.commit()

    result = await ProviderSyncService(db_session).reconcile(connection)
    assert result.provider_cost == Decimal("50.000000")
    assert result.our_recorded_cost == Decimal("20.000000")
    assert result.difference == Decimal("30.000000")
    assert result.as_dict()["unattributed"] is True


async def test_a_matching_month_reports_no_difference(db_session, auth_headers) -> None:
    connection = await _connection(db_session)
    org = await _org(db_session)
    db_session.add(_usage(connection.id, "calls-outbound-mobile", "12.50"))
    db_session.add(
        Call(
            organization_id=org.id,
            direction="outbound",
            provider="twilio",
            from_number="+10000000000",
            to_number="+919876543210",
            status=CallStatus.COMPLETED,
            duration_seconds=60,
            cost_usd=12.5,
        )
    )
    await db_session.commit()

    result = await ProviderSyncService(db_session).reconcile(connection)
    assert result.difference == Decimal("0.000000")
    assert result.as_dict()["unattributed"] is False


async def test_a_percentage_is_not_reported_against_a_zero_total(db_session, auth_headers) -> None:
    """A percentage of nothing is not a fact."""
    connection = await _connection(db_session)
    result = await ProviderSyncService(db_session).reconcile(connection)
    assert result.difference_percent is None
    assert result.as_dict()["difference_percent"] is None


async def test_usage_outside_the_window_is_excluded(db_session, auth_headers) -> None:
    connection = await _connection(db_session)
    db_session.add(_usage(connection.id, "calls-outbound-mobile", "99.00", days_ago=90))
    db_session.add(_usage(connection.id, "sms-outbound", "1.00", days_ago=2))
    await db_session.commit()

    result = await ProviderSyncService(db_session).reconcile(connection, days=30)
    assert result.provider_cost == Decimal("1.000000")


async def test_a_sync_without_credentials_is_recorded_as_failed(db_session, auth_headers) -> None:
    """A silent stop is indistinguishable from a provider with no usage."""
    from app.models.provider import ProviderSyncRun

    connection = await _connection(db_session)
    assert await ProviderSyncService(db_session).sync_balance(connection) is None

    runs = await db_session.execute(
        select(ProviderSyncRun).where(ProviderSyncRun.connection_id == connection.id)
    )
    run = runs.scalars().first()
    assert run is not None
    assert run.status == "failed"
    assert run.error == "No credentials"


# --- the API ----------------------------------------------------------


async def test_the_sync_api_is_admin_only(client, auth_headers, db_session) -> None:
    connection = await _connection(db_session)
    assert (await client.post(f"/platform/providers/{connection.id}/sync")).status_code == 401
    assert (
        await client.post(f"/platform/providers/{connection.id}/sync", headers=auth_headers)
    ).status_code == 403


async def test_the_usage_endpoint_flags_parents_rather_than_hiding_them(
    client, auth_headers, db_session
) -> None:
    """The hierarchy is useful; mistaking rollups for extra spend is not."""
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.is_platform_admin = True
    connection = await _connection(db_session)
    db_session.add(_usage(connection.id, "calls", "30.00", parent=True))
    db_session.add(_usage(connection.id, "calls-outbound-mobile", "30.00"))
    await db_session.commit()

    body = (
        await client.get(f"/platform/providers/{connection.id}/usage", headers=auth_headers)
    ).json()
    assert len(body["items"]) == 2
    assert sum(1 for i in body["items"] if i["is_parent"]) == 1
    assert body["reconciliation"]["provider_cost_usd"] == "30.000000"


async def test_an_unknown_connection_is_a_404(client, auth_headers, db_session) -> None:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.is_platform_admin = True
    await db_session.commit()
    assert (
        await client.get(f"/platform/providers/{uuid.uuid4()}/usage", headers=auth_headers)
    ).status_code == 404


async def test_the_providers_own_total_wins_over_summed_categories(
    db_session, auth_headers
) -> None:
    """The first real reconciliation reported an 83% gap that did not exist.

    Twilio's feed mixes leaf categories with several overlapping rollups --
    `calls` and `calls-outbound`, `recordings` and `calls-recordings` -- and
    publishes its own `totalprice` row alongside them. Summing the feed
    counted the same spend roughly three times.
    """
    from app.services.provider_sync import TOTAL_CATEGORY

    connection = await _connection(db_session)
    db_session.add(_usage(connection.id, TOTAL_CATEGORY, "10.33"))
    db_session.add(_usage(connection.id, "calls", "8.75"))
    db_session.add(_usage(connection.id, "calls-outbound", "8.21"))
    db_session.add(_usage(connection.id, "recordings", "0.37"))
    db_session.add(_usage(connection.id, "calls-recordings", "0.37"))
    await db_session.commit()

    result = await ProviderSyncService(db_session).reconcile(connection)
    assert result.provider_cost == Decimal("10.330000")


async def test_overlapping_rollups_are_excluded_even_without_a_name_prefix(
    db_session, auth_headers
) -> None:
    """`recordings` duplicates `calls-recordings`, and the names do not say so."""
    from app.services.provider_sync import _is_rollup

    assert _is_rollup("recordings") is True
    assert _is_rollup("phonenumbers") is True
    assert _is_rollup("totalprice") is True
    assert _is_rollup("calls-outbound-mobile") is False


async def test_a_parent_stored_before_its_children_is_still_flagged(
    db_session, auth_headers
) -> None:
    """Computed per row during the sync, the first parent written was missed."""
    connection = await _connection(db_session)
    db_session.add(_usage(connection.id, "sms-outbound", "4.00"))
    db_session.add(_usage(connection.id, "sms-outbound-longcode", "4.00"))
    await db_session.commit()

    await ProviderSyncService(db_session)._mark_rollups(connection)
    await db_session.commit()

    rows = await db_session.execute(
        select(ProviderUsageRecord).where(ProviderUsageRecord.category == "sms-outbound")
    )
    assert rows.scalar_one().is_parent is True
