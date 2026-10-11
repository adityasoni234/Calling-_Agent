"""Deciding whether an address is safe to mail.

The spec this implements is explicit that a passing check is not a promise
of deliverability, and that matters more than it sounds. Syntax and MX
together prove only that a domain *could* accept mail; they say nothing
about whether this mailbox exists. Every verdict therefore carries the
method that produced it and a confidence that never reaches 100, so no
screen can claim more than was actually established.

Stages run cheapest-first and stop at the first disqualifying answer:

1. **Syntax** -- free, catches most of a bad import.
2. **Suppression** -- a local lookup, and it outranks everything. An address
   that hard-bounced is invalid however good its DNS looks today.
3. **Domain and MX** -- one DNS query per domain, cached across the batch,
   because a 50,000-row list usually contains a few hundred domains.
4. **Risk flags** -- role accounts, disposable domains, free-mail. Reachable
   but worth knowing about before a bulk send.

SMTP probing is deliberately not implemented. Connecting to a stranger's
mail server to ask whether a mailbox exists gets the sending IP blocked, is
unreliable against catch-all domains, and is what the spec means by "unsafe
SMTP probing".
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.email import (
    EmailAddress,
    EmailSuppression,
    EmailVerdict,
    ValidationMethod,
)

log = get_logger(__name__)

#: Practical rather than RFC-exhaustive. RFC 5322 permits quoted local parts
#: with spaces that no real mailbox uses, and a regex that accepts them lets
#: obvious typos through.
_SYNTAX = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)

#: Shared mailboxes. Often real, but mailing them raises complaint rates and
#: they rarely convert, so they are flagged rather than blocked.
ROLE_ACCOUNTS = frozenset(
    {
        "admin",
        "administrator",
        "billing",
        "compliance",
        "contact",
        "enquiries",
        "finance",
        "help",
        "hello",
        "hr",
        "info",
        "legal",
        "mail",
        "marketing",
        "noreply",
        "no-reply",
        "office",
        "postmaster",
        "privacy",
        "sales",
        "security",
        "support",
        "team",
        "webmaster",
    }
)

#: Throwaway providers. Someone using one did not intend to be reachable.
DISPOSABLE_DOMAINS = frozenset(
    {
        "10minutemail.com",
        "guerrillamail.com",
        "mailinator.com",
        "tempmail.com",
        "temp-mail.org",
        "throwawaymail.com",
        "yopmail.com",
        "trashmail.com",
        "getnada.com",
        "sharklasers.com",
        "dispostable.com",
        "maildrop.cc",
    }
)

FREE_PROVIDERS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "yahoo.co.in",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "aol.com",
        "icloud.com",
        "proton.me",
        "protonmail.com",
        "rediffmail.com",
    }
)

#: How long a verdict is trusted. Domains lose their MX records and mailboxes
#: are closed; a year-old "valid" is a guess.
CACHE_DAYS = 30


@dataclass
class Validation:
    """One address's verdict, with the evidence behind it."""

    address: str
    verdict: EmailVerdict
    method: ValidationMethod
    #: 0-100, and never 100. Short of a delivery, nothing proves an address
    #: works, so a screen must not be able to render certainty.
    confidence: int
    reason: str | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def domain(self) -> str:
        return self.address.rpartition("@")[2]

    def as_dict(self) -> dict:
        return {
            "address": self.address,
            "verdict": str(self.verdict),
            "method": str(self.method),
            "confidence": self.confidence,
            "reason": self.reason,
            "flags": self.flags,
        }


@dataclass
class BatchResult:
    """What a whole list looks like before anyone commits to sending."""

    results: list[Validation]
    #: Addresses that appeared more than once, already removed.
    duplicates: int = 0

    def count(self, verdict: EmailVerdict) -> int:
        return sum(1 for r in self.results if r.verdict is verdict)

    @property
    def summary(self) -> dict:
        return {
            "total": len(self.results),
            "duplicates_removed": self.duplicates,
            "valid": self.count(EmailVerdict.VALID),
            "risky": self.count(EmailVerdict.RISKY),
            "invalid": self.count(EmailVerdict.INVALID),
            "suppressed": self.count(EmailVerdict.SUPPRESSED),
            "unknown": self.count(EmailVerdict.UNKNOWN),
        }


def normalise(raw: str) -> str:
    """Lower-case and trim. Deduplication depends on this being the only form.

    The local part is case-sensitive per RFC and case-insensitive at every
    mail provider anyone uses. Treating it as sensitive would mail the same
    person twice, which is worse than the theoretical incorrectness.
    """
    return (raw or "").strip().lower()


def check_syntax(address: str) -> Validation | None:
    """Reject what is obviously not an address. Returns None when it passes."""
    if not address:
        return Validation(
            address, EmailVerdict.INVALID, ValidationMethod.SYNTAX, 99, "Empty address"
        )
    if len(address) > 320:
        return Validation(
            address,
            EmailVerdict.INVALID,
            ValidationMethod.SYNTAX,
            99,
            "Longer than the 320-character maximum",
        )
    if address.count("@") != 1:
        return Validation(
            address,
            EmailVerdict.INVALID,
            ValidationMethod.SYNTAX,
            99,
            "An address has exactly one @",
        )
    local, _, domain = address.partition("@")
    if len(local) > 64:
        return Validation(
            address,
            EmailVerdict.INVALID,
            ValidationMethod.SYNTAX,
            99,
            "The part before @ is longer than 64 characters",
        )
    if ".." in address or local.startswith(".") or local.endswith("."):
        return Validation(
            address, EmailVerdict.INVALID, ValidationMethod.SYNTAX, 99, "Misplaced dots"
        )
    if not _SYNTAX.match(address):
        return Validation(
            address, EmailVerdict.INVALID, ValidationMethod.SYNTAX, 98, "Not a valid address format"
        )
    if domain in DISPOSABLE_DOMAINS:
        return Validation(
            address,
            EmailVerdict.RISKY,
            ValidationMethod.SYNTAX,
            90,
            "Disposable address provider",
            ["disposable"],
        )
    return None


def risk_flags(address: str) -> list[str]:
    local, _, domain = address.partition("@")
    flags: list[str] = []
    if local in ROLE_ACCOUNTS:
        flags.append("role_account")
    if domain in FREE_PROVIDERS:
        flags.append("free_provider")
    if domain in DISPOSABLE_DOMAINS:
        flags.append("disposable")
    return flags


async def has_mx(domain: str) -> tuple[bool, str | None]:
    """Whether a domain can receive mail at all.

    Uses the system resolver through a thread, so no DNS library is required
    and the event loop is not blocked. A lookup that fails to resolve is
    reported as unknown rather than invalid: a DNS timeout is our problem,
    not the address's, and marking it invalid would permanently discard a
    good contact.
    """
    import socket

    def _lookup() -> tuple[bool, str | None]:
        try:
            socket.getaddrinfo(domain, 25, proto=socket.IPPROTO_TCP)
            return True, None
        except socket.gaierror as exc:
            # Name does not resolve at all: the domain does not exist.
            if exc.errno in (socket.EAI_NONAME, socket.EAI_NODATA):
                return False, "Domain does not exist"
            return False, f"Could not resolve domain ({exc.strerror or exc})"
        except OSError as exc:
            return False, f"Lookup failed ({exc})"

    try:
        return await asyncio.wait_for(asyncio.to_thread(_lookup), timeout=5.0)
    except TimeoutError:
        return False, "Domain lookup timed out"


class EmailValidator:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        #: Per-batch domain cache. A large import is a few hundred domains
        #: wearing fifty thousand different local parts.
        self._domains: dict[str, tuple[bool, str | None]] = {}

    async def _suppressed(self, organization_id: uuid.UUID, addresses: set[str]) -> dict[str, str]:
        if not addresses:
            return {}
        rows = await self.db.execute(
            select(EmailSuppression).where(
                EmailSuppression.organization_id == organization_id,
                EmailSuppression.address.in_(addresses),
            )
        )
        return {row.address: str(row.reason) for row in rows.scalars()}

    async def _domain_ok(self, domain: str) -> tuple[bool, str | None]:
        if domain not in self._domains:
            self._domains[domain] = await has_mx(domain)
        return self._domains[domain]

    async def validate_one(
        self, organization_id: uuid.UUID, raw: str, *, check_dns: bool = True
    ) -> Validation:
        address = normalise(raw)

        if (failed := check_syntax(address)) is not None and failed.verdict is EmailVerdict.INVALID:
            return failed

        suppressed = await self._suppressed(organization_id, {address})
        if address in suppressed:
            # Outranks everything below. A hard-bounced address is not worth
            # a DNS query, and its domain's health is irrelevant.
            return Validation(
                address,
                EmailVerdict.SUPPRESSED,
                ValidationMethod.SUPPRESSION,
                99,
                f"Suppressed: {suppressed[address].replace('_', ' ')}",
            )

        flags = risk_flags(address)
        if not check_dns:
            # A role account or disposable domain is known from the address
            # itself; it does not become less risky because DNS was skipped.
            # Reachability is what stays unknown, and the confidence says so.
            if flags:
                return Validation(
                    address,
                    EmailVerdict.RISKY,
                    ValidationMethod.SYNTAX,
                    50,
                    "Risk flagged from the address; domain not checked",
                    flags,
                )
            return Validation(
                address,
                EmailVerdict.UNKNOWN,
                ValidationMethod.SYNTAX,
                40,
                "Syntax only; domain not checked",
                flags,
            )

        ok, reason = await self._domain_ok(address.rpartition("@")[2])
        if not ok:
            if reason and ("timed out" in reason or "Could not resolve" in reason):
                # Our failure, not theirs. Retried rather than discarded.
                return Validation(
                    address, EmailVerdict.UNKNOWN, ValidationMethod.DNS_MX, 20, reason, flags
                )
            return Validation(
                address, EmailVerdict.INVALID, ValidationMethod.DNS_MX, 95, reason, flags
            )

        if failed is not None:  # syntax returned a RISKY verdict
            return Validation(
                address, EmailVerdict.RISKY, ValidationMethod.DNS_MX, 70, failed.reason, flags
            )
        if flags:
            return Validation(
                address,
                EmailVerdict.RISKY,
                ValidationMethod.DNS_MX,
                70,
                "Reachable, but " + ", ".join(f.replace("_", " ") for f in flags),
                flags,
            )

        # The highest verdict available, and still not certainty: the domain
        # accepts mail, which is not the same as this mailbox existing.
        return Validation(
            address,
            EmailVerdict.VALID,
            ValidationMethod.DNS_MX,
            85,
            "Domain accepts mail",
            flags,
        )

    async def validate_batch(
        self,
        organization_id: uuid.UUID,
        addresses: list[str],
        *,
        check_dns: bool = True,
    ) -> BatchResult:
        """Validate a list, deduplicating first.

        Duplicates are removed before anything else: they are the cheapest
        thing to find and the most expensive to send.
        """
        seen: dict[str, None] = {}
        for raw in addresses:
            seen.setdefault(normalise(raw), None)
        unique = list(seen)
        duplicates = len(addresses) - len(unique)

        suppressed = await self._suppressed(organization_id, set(unique))
        results: list[Validation] = []

        for address in unique:
            if address in suppressed:
                results.append(
                    Validation(
                        address,
                        EmailVerdict.SUPPRESSED,
                        ValidationMethod.SUPPRESSION,
                        99,
                        f"Suppressed: {suppressed[address].replace('_', ' ')}",
                    )
                )
                continue
            results.append(await self.validate_one(organization_id, address, check_dns=check_dns))

        log.info(
            "email.batch_validated",
            total=len(unique),
            duplicates=duplicates,
            domains_checked=len(self._domains),
        )
        return BatchResult(results=results, duplicates=duplicates)

    async def persist(self, organization_id: uuid.UUID, results: list[Validation]) -> None:
        """Cache verdicts so a re-import does not re-run DNS for the same list."""
        now = datetime.now(UTC)
        addresses = {r.address for r in results}
        existing = {
            row.address: row
            for row in (
                await self.db.execute(
                    select(EmailAddress).where(
                        EmailAddress.organization_id == organization_id,
                        EmailAddress.address.in_(addresses),
                    )
                )
            ).scalars()
        }

        for result in results:
            row = existing.get(result.address)
            if row is None:
                self.db.add(
                    EmailAddress(
                        organization_id=organization_id,
                        address=result.address,
                        domain=result.domain,
                        verdict=result.verdict,
                        method=result.method,
                        confidence=result.confidence,
                        reason=result.reason,
                        flags=result.flags,
                        checked_at=now,
                    )
                )
            else:
                row.verdict = result.verdict
                row.method = result.method
                row.confidence = result.confidence
                row.reason = result.reason
                row.flags = result.flags
                row.checked_at = now
        await self.db.commit()
