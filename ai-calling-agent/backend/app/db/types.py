"""Column types that need to behave differently across dialects."""

from __future__ import annotations

import enum
from typing import Any, TypeVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Dialect, types
from sqlalchemy.dialects.postgresql import JSONB


class VectorType(types.TypeDecorator):
    """pgvector in Postgres, JSON everywhere else.

    The test suite runs on SQLite, which has no vector type. Similarity search
    is Postgres-only by design, so the fallback only needs to store and return
    the embedding intact.
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        super().__init__()

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())


def JSONColumn() -> Any:  # noqa: N802 - reads as a type constructor at the call site
    """JSONB on Postgres (indexable), plain JSON elsewhere."""
    return JSON().with_variant(JSONB(), "postgresql")


EnumT = TypeVar("EnumT", bound=enum.StrEnum)


class StrEnumType(types.TypeDecorator):
    """VARCHAR on the wire, enum member in Python.

    A plain `String` column returns `str`, so `value is SomeEnum.MEMBER` is
    always False -- which silently breaks identity comparisons in guard clauses.
    Stored representation is unchanged, so no migration is needed.
    """

    impl = types.String
    cache_ok = True

    def __init__(self, enum_class: type[EnumT], length: int = 32) -> None:
        self.enum_class = enum_class
        super().__init__(length=length)

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return str(value.value if isinstance(value, enum.Enum) else value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        try:
            return self.enum_class(value)
        except ValueError:
            # Unknown value written by an older revision: hand back the raw
            # string rather than failing the whole query.
            return value
