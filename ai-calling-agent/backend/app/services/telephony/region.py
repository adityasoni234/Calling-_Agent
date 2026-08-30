"""Destination country for a phone number.

Used only for pricing: telephony rates differ by more than 6x between
countries, so a call cannot be costed without knowing where it went.
"""

from __future__ import annotations

from functools import lru_cache

import phonenumbers


@lru_cache(maxsize=4096)
def region_of(phone_number: str | None) -> str | None:
    """ISO-3166 alpha-2 for an E.164 number, or None if it cannot be parsed."""
    if not phone_number:
        return None
    try:
        parsed = phonenumbers.parse(phone_number, None)
    except phonenumbers.NumberParseException:
        return None
    return phonenumbers.region_code_for_number(parsed)
