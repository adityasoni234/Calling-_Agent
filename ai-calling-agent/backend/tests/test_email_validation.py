"""Email address validation.

The assertions that matter here are the negative ones: that nothing claims
certainty it does not have, and that a suppressed address cannot be talked
back into being sendable by a good DNS answer.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.email import (
    NEVER_SEND,
    EmailAddress,
    EmailSuppression,
    EmailSuppressionReason,
    EmailVerdict,
    ValidationMethod,
)
from app.models.organization import Organization
from app.models.user import User
from app.services.email_validation import (
    DISPOSABLE_DOMAINS,
    ROLE_ACCOUNTS,
    EmailValidator,
    check_syntax,
    normalise,
    risk_flags,
)
from tests.conftest import REGISTRATION


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


# --- normalisation ----------------------------------------------------


def test_addresses_are_normalised_so_one_person_is_one_row() -> None:
    """Local parts are case-sensitive per RFC and case-insensitive everywhere real.

    Honouring the RFC here would mail the same person twice.
    """
    for spelling in ("Aditya@Example.COM", "  aditya@example.com  ", "ADITYA@EXAMPLE.COM"):
        assert normalise(spelling) == "aditya@example.com"


# --- syntax -----------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "",
        "no-at-sign.com",
        "two@@at.com",
        "trailing.dot.@example.com",
        "double..dot@example.com",
        "a" * 65 + "@example.com",
        "nodomain@",
        "@nolocal.com",
        "spaces in@example.com",
    ],
)
def test_obvious_rubbish_is_rejected_on_syntax_alone(address: str) -> None:
    result = check_syntax(normalise(address))
    assert result is not None
    assert result.verdict is EmailVerdict.INVALID


@pytest.mark.parametrize(
    "address",
    ["aditya@example.com", "first.last+tag@sub.example.co.in", "x@y.io"],
)
def test_real_addresses_pass_syntax(address: str) -> None:
    assert check_syntax(address) is None


def test_a_disposable_provider_is_risky_not_invalid() -> None:
    """It is a working mailbox. It is just not a person who wants mail."""
    result = check_syntax("someone@mailinator.com")
    assert result is not None
    assert result.verdict is EmailVerdict.RISKY
    assert "disposable" in result.flags


def test_role_accounts_and_free_providers_are_flagged() -> None:
    assert "role_account" in risk_flags("support@acme.com")
    assert "free_provider" in risk_flags("someone@gmail.com")
    assert risk_flags("aditya@acme.com") == []
    assert "support" in ROLE_ACCOUNTS
    assert "mailinator.com" in DISPOSABLE_DOMAINS


# --- confidence is never certainty ------------------------------------


def test_no_verdict_ever_claims_full_confidence() -> None:
    """Short of a delivery nothing proves an address works.

    A screen must not be able to render 100%, because the product would then
    be promising something it cannot know.
    """
    results = [check_syntax(a) for a in ("", "bad@@x.com", "x@mailinator.com")]
    for result in results:
        assert result is not None
        assert result.confidence < 100


# --- suppression outranks everything ----------------------------------


async def test_a_suppressed_address_is_never_sendable(db_session, auth_headers) -> None:
    """A hard bounce stands however healthy the domain looks today."""
    org = await _org(db_session)
    db_session.add(
        EmailSuppression(
            organization_id=org.id,
            address="bounced@gmail.com",
            reason=EmailSuppressionReason.HARD_BOUNCE,
            detail="550 mailbox not found",
        )
    )
    await db_session.commit()

    result = await EmailValidator(db_session).validate_one(
        org.id, "Bounced@Gmail.com", check_dns=True
    )
    assert result.verdict is EmailVerdict.SUPPRESSED
    assert result.method is ValidationMethod.SUPPRESSION
    assert result.verdict in NEVER_SEND


async def test_suppression_is_checked_before_dns_is_queried(db_session, auth_headers) -> None:
    """A suppressed address is not worth a DNS lookup, and its domain is moot."""
    org = await _org(db_session)
    db_session.add(
        EmailSuppression(
            organization_id=org.id,
            address="gone@nonexistent-domain-xyz-123456.com",
            reason=EmailSuppressionReason.UNSUBSCRIBED,
        )
    )
    await db_session.commit()

    validator = EmailValidator(db_session)
    result = await validator.validate_one(org.id, "gone@nonexistent-domain-xyz-123456.com")
    assert result.verdict is EmailVerdict.SUPPRESSED
    assert validator._domains == {}  # no lookup happened


# --- batches ----------------------------------------------------------


async def test_duplicates_are_removed_before_anything_else(db_session, auth_headers) -> None:
    """The cheapest thing to find and the most expensive to send."""
    org = await _org(db_session)
    batch = await EmailValidator(db_session).validate_batch(
        org.id,
        ["a@example.com", "A@EXAMPLE.COM", " a@example.com ", "b@example.com"],
        check_dns=False,
    )
    assert batch.duplicates == 2
    assert len(batch.results) == 2


async def test_a_batch_summarises_every_verdict(db_session, auth_headers) -> None:
    org = await _org(db_session)
    db_session.add(
        EmailSuppression(
            organization_id=org.id,
            address="blocked@example.com",
            reason=EmailSuppressionReason.COMPLAINT,
        )
    )
    await db_session.commit()

    batch = await EmailValidator(db_session).validate_batch(
        org.id,
        ["good@example.com", "not-an-address", "blocked@example.com", "x@mailinator.com"],
        check_dns=False,
    )
    summary = batch.summary
    assert summary["total"] == 4
    assert summary["invalid"] == 1
    assert summary["suppressed"] == 1
    assert (
        sum(summary[k] for k in ("valid", "risky", "invalid", "suppressed", "unknown"))
        == summary["total"]
    )


async def test_a_dns_failure_is_unknown_rather_than_invalid(db_session, auth_headers) -> None:
    """A resolver timeout is our problem, not the address's.

    Marking it invalid would permanently discard a contact over a network
    blip, and the suppression that follows is not easily undone.
    """
    org = await _org(db_session)
    validator = EmailValidator(db_session)
    validator._domains["flaky.example"] = (False, "Domain lookup timed out")

    result = await validator.validate_one(org.id, "someone@flaky.example")
    assert result.verdict is EmailVerdict.UNKNOWN
    assert result.verdict not in NEVER_SEND


async def test_a_domain_that_does_not_exist_is_invalid(db_session, auth_headers) -> None:
    org = await _org(db_session)
    validator = EmailValidator(db_session)
    validator._domains["nope.example"] = (False, "Domain does not exist")

    result = await validator.validate_one(org.id, "someone@nope.example")
    assert result.verdict is EmailVerdict.INVALID


async def test_a_domain_is_looked_up_once_per_batch(db_session, auth_headers) -> None:
    """A 50,000-row list is a few hundred domains wearing many local parts."""
    org = await _org(db_session)
    validator = EmailValidator(db_session)
    validator._domains["example.com"] = (True, None)

    await validator.validate_batch(
        org.id,
        [f"user{i}@example.com" for i in range(25)],
        check_dns=True,
    )
    assert list(validator._domains) == ["example.com"]


# --- caching ----------------------------------------------------------


async def test_verdicts_are_cached_so_a_reimport_is_cheap(db_session, auth_headers) -> None:
    org = await _org(db_session)
    validator = EmailValidator(db_session)
    batch = await validator.validate_batch(org.id, ["cache@example.com", "bad@@x"], check_dns=False)
    await validator.persist(org.id, batch.results)

    rows = (
        await db_session.execute(select(EmailAddress).where(EmailAddress.organization_id == org.id))
    ).scalars()
    cached = {row.address: row for row in rows}
    assert "cache@example.com" in cached
    assert cached["cache@example.com"].checked_at is not None
    assert cached["cache@example.com"].domain == "example.com"


async def test_revalidating_updates_rather_than_duplicates(db_session, auth_headers) -> None:
    org = await _org(db_session)
    validator = EmailValidator(db_session)
    for _ in range(2):
        batch = await validator.validate_batch(org.id, ["again@example.com"], check_dns=False)
        await validator.persist(org.id, batch.results)

    rows = list(
        (
            await db_session.execute(
                select(EmailAddress).where(EmailAddress.address == "again@example.com")
            )
        ).scalars()
    )
    assert len(rows) == 1


# --- tenant isolation -------------------------------------------------


async def test_one_tenants_suppression_does_not_block_another(db_session, auth_headers) -> None:
    """A complaint to one sender is not a complaint to every sender."""
    org = await _org(db_session)
    other = Organization(name="Other Co", slug=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    await db_session.flush()
    db_session.add(
        EmailSuppression(
            organization_id=org.id,
            address="shared@example.com",
            reason=EmailSuppressionReason.COMPLAINT,
        )
    )
    await db_session.commit()

    validator = EmailValidator(db_session)
    mine = await validator.validate_one(org.id, "shared@example.com", check_dns=False)
    theirs = await validator.validate_one(other.id, "shared@example.com", check_dns=False)
    assert mine.verdict is EmailVerdict.SUPPRESSED
    assert theirs.verdict is not EmailVerdict.SUPPRESSED


# --- free-mail is ordinary, not risky ---------------------------------


async def test_a_gmail_address_is_not_treated_as_risky(db_session, auth_headers) -> None:
    """The majority of real consumer leads are on free mail.

    Flagging Gmail as risky and withholding it by default blocked most of a
    normal B2C list, which made the feature unusable for the market it was
    built for.
    """
    org = await _org(db_session)
    validator = EmailValidator(db_session)
    validator._domains["gmail.com"] = (True, None)

    result = await validator.validate_one(org.id, "someone@gmail.com")
    assert result.verdict is EmailVerdict.VALID
    # Still recorded, because "this list is 90% Gmail" is worth knowing.
    assert "free_provider" in result.flags


async def test_role_accounts_and_disposables_still_hold_a_send(db_session, auth_headers) -> None:
    org = await _org(db_session)
    validator = EmailValidator(db_session)
    validator._domains["acme.com"] = (True, None)
    validator._domains["mailinator.com"] = (True, None)

    role = await validator.validate_one(org.id, "support@acme.com")
    throwaway = await validator.validate_one(org.id, "x@mailinator.com")
    assert role.verdict is EmailVerdict.RISKY
    assert throwaway.verdict is EmailVerdict.RISKY


async def test_free_mail_passes_even_without_a_dns_check(db_session, auth_headers) -> None:
    org = await _org(db_session)
    result = await EmailValidator(db_session).validate_one(
        org.id, "someone@gmail.com", check_dns=False
    )
    assert result.verdict is not EmailVerdict.RISKY
