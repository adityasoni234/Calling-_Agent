"""Timezone normalisation at the database boundary.

Postgres hands back aware datetimes from `TIMESTAMPTZ`; SQLite, which the test
suite runs on, hands back naive ones from the same column. Comparing the two
raises, so a comparison that passes in tests can fail in production and the
other way round.

Everything stored is UTC, so a naive value read back is UTC that lost its
label. `as_utc` puts the label back.
"""

from __future__ import annotations

from datetime import UTC, datetime


def as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive datetime; convert an aware one. None passes through."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
