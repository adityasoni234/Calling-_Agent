"""Shared vocabulary for every external-service adapter."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.call import UsageComponent


class ProviderError(RuntimeError):
    """Raised by an adapter when the upstream vendor fails."""

    def __init__(self, provider: str, message: str, *, retryable: bool = False) -> None:
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"[{provider}] {message}")


@dataclass(slots=True)
class UsageRecord:
    """What an adapter consumed. Priced later, never priced by the adapter.

    Cost accounting is part of the provider interface rather than something
    bolted on afterwards -- an adapter that doesn't report usage cannot be
    costed, and would silently break the unit economics.
    """

    component: UsageComponent
    provider: str
    unit: str
    quantity: float
    model: str | None = None
    # ISO country of the destination. Telephony rates vary by an order of
    # magnitude between countries, so a worldwide operation cannot price a
    # call without knowing where it went.
    region: str | None = None


@dataclass(slots=True)
class UsageBag:
    """Accumulates usage across one call."""

    records: list[UsageRecord] = field(default_factory=list)

    def add(self, record: UsageRecord) -> None:
        self.records.append(record)

    def extend(self, records: list[UsageRecord]) -> None:
        self.records.extend(records)
