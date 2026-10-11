"""Decimal money.

Floats cannot represent 0.1, so a ledger built on them drifts: add a tenth of
a cent ten thousand times and the balance is wrong by an amount no one can
account for. Every monetary value on the platform is a `Decimal`, and the
database columns behind them are NUMERIC rather than DOUBLE PRECISION.

Two scales are in use and they are not interchangeable:

* **Currency amounts** (what a customer is charged, what we paid) use 2 or 6
  decimal places depending on whether a human reads them. Provider usage is
  priced in millionths of a dollar -- a Deepgram second costs $0.000128 -- so
  truncating cost to cents would price most calls at zero.
* **Rates** (per minute, per 1k tokens) keep 8 places, because a rate is
  multiplied by a large quantity before anyone rounds it.

Rounding is always explicit. `ROUND_HALF_UP` is what an invoice reader
expects; Python's default banker's rounding is not.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Numeric
from sqlalchemy.types import TypeDecorator

#: Money a human reads on an invoice.
CENTS = Decimal("0.01")
#: Provider cost and anything multiplied before display. Six places is enough
#: for a per-second AI charge and still exact in NUMERIC.
MICROS = Decimal("0.000001")

ZERO = Decimal("0")


def to_decimal(value: Any) -> Decimal:
    """Coerce anything money-shaped to Decimal without going through float.

    Passing a float here is a bug at the call site, but raising would turn a
    display path into a 500. Floats are routed through `repr` so that 0.07
    becomes Decimal("0.07") rather than Decimal("0.070000000000000006").
    """
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    if isinstance(value, float):
        return Decimal(repr(value))
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def quantize_money(value: Any, exp: Decimal = CENTS) -> Decimal:
    """Round to a fixed number of places, the way an invoice reader expects."""
    return to_decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def quantize_cost(value: Any) -> Decimal:
    """Provider cost, to the millionth. Never rounds a real charge to zero."""
    return quantize_money(value, MICROS)


def billable_minutes(seconds: int | None, *, increment_seconds: int = 60) -> Decimal:
    """Connected seconds as the units a carrier actually bills.

    Carriers round a partial minute up to a whole one, so a 17-second call
    costs a full minute. Billing the customer per-second while paying per
    minute is how a platform discovers it is losing money on short calls --
    and short calls are most of them.
    """
    if not seconds or seconds <= 0:
        return ZERO
    increment = Decimal(increment_seconds)
    return (Decimal(seconds) / increment).quantize(Decimal("1"), rounding=ROUND_CEILING)


def margin_percent(charge: Decimal, cost: Decimal) -> Decimal | None:
    """Gross margin as a percentage, or None when it cannot be stated.

    A zero charge has no margin -- not 0%, not 100%. Returning None forces the
    caller to say "not applicable" instead of printing a number that reads as
    a fact.
    """
    charge = to_decimal(charge)
    if charge <= ZERO:
        return None
    return quantize_money((charge - to_decimal(cost)) / charge * Decimal(100))


class Money(TypeDecorator):
    """NUMERIC column that always hands Python a Decimal.

    SQLite (used by the test suite) has no native decimal type and returns
    floats for NUMERIC, which would let float drift back in through the one
    door this module exists to close. The result processor coerces on the way
    out, so tests exercise the same Decimal semantics as Postgres.
    """

    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int = 18, scale: int = 6, **kwargs: Any) -> None:
        super().__init__(precision=precision, scale=scale, asdecimal=True, **kwargs)

    def process_bind_param(self, value: Any, dialect: Any) -> Decimal | None:
        return None if value is None else to_decimal(value)

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        return None if value is None else to_decimal(value)


#: Amounts shown to people: balances, charges, invoice lines.
MoneyAmount = Money(precision=18, scale=6)
#: Rates multiplied by quantity before display.
MoneyRate = Money(precision=18, scale=8)
