"""Encryption for provider credentials at rest.

A Twilio auth token in a database column is a token in every backup, every
replica, and every `pg_dump` someone emails themselves. These are encrypted
with Fernet (AES-128-CBC with an HMAC), keyed from `secret_key`, so reading
the table is not enough to place calls on the owner's account.

What this does **not** defend against: an attacker who has both the database
and the application's environment. A real KMS or Vault would separate those,
and `encrypt`/`decrypt` are the two functions a migration to one would
replace. That trade is deliberate and worth stating plainly rather than
implying the secrets are safe against any adversary.

Nothing here ever returns a plaintext secret to an API response. The only
caller of `decrypt` is the provider adapter layer, at the moment it builds a
client.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretUnreadable(Exception):
    """A stored secret could not be decrypted.

    Almost always means `secret_key` changed. Raised rather than returning
    None so a rotation does not silently turn into calls placed with no
    credentials, which fail far away from the cause.
    """


def _fernet() -> Fernet:
    """Derive a Fernet key from the app secret.

    SHA-256 of the secret gives the 32 bytes Fernet wants from a secret of any
    length, so operators are not asked to generate a second key in a specific
    format -- an instruction that in practice produces a key committed to the
    repository.
    """
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    """Encrypt a credential for storage. Empty stays empty, not an encrypted blob."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise SecretUnreadable(
            "Stored credential could not be decrypted. This usually means "
            "SECRET_KEY changed since it was saved; re-enter the credential."
        ) from exc


def mask(plaintext: str, *, keep: int = 4) -> str:
    """A hint at which credential this is, safe to show and to log.

    Shows only the tail: the leading characters of a Twilio SID or an API key
    are a fixed vendor prefix and identify nothing, while the tail is what an
    operator compares against their provider dashboard.
    """
    if not plaintext:
        return ""
    if len(plaintext) <= keep:
        return "•" * len(plaintext)
    return "•" * min(len(plaintext) - keep, 12) + plaintext[-keep:]
