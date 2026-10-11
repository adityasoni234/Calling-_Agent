"""The contract an email provider must satisfy.

Small on purpose. Validation, suppression, pricing, idempotency and
unsubscribe handling live in the service layer where they are tested once;
an adapter hands a message to a vendor and reports honestly what it said.

Two provider families are supported because the owner has not chosen one
and the choice should not block the build:

* **SMTP** works with Amazon SES, Mailgun, Postmark, Sendgrid and any
  corporate relay. Slower per message and needs a connection, but universal.
* **HTTP** is what Postmark and Resend prefer: a token header and a JSON
  body, with per-message ids returned immediately.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class EmailNotConfigured(Exception):
    """No usable credentials.

    Raised rather than returning a fake success. An email that silently goes
    nowhere is discovered by the customer who never got it.
    """


@dataclass
class OutboundEmail:
    """One message, already validated and priced by the service layer."""

    to_address: str
    subject: str
    text_body: str
    from_address: str
    from_name: str = ""
    html_body: str | None = None
    reply_to: str | None = None
    #: Put in List-Unsubscribe. Gmail and Yahoo require a one-click header on
    #: bulk mail, and without it a sender's reputation degrades regardless of
    #: whether the footer link works.
    unsubscribe_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class EmailDispatched:
    provider_message_id: str | None
    accepted: bool
    error_code: str | None = None
    error_message: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class EmailEvent:
    """A delivery event parsed out of a provider webhook."""

    provider_message_id: str
    #: One of our EmailStatus values.
    status: str
    to_address: str | None = None
    detail: str | None = None
    #: True for a permanent failure, which suppresses the address. A soft
    #: bounce must not: the provider retries those and suppressing on one
    #: would discard a contact over a full mailbox.
    permanent: bool = False


class EmailProvider(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    async def send(self, message: OutboundEmail) -> EmailDispatched: ...

    @abstractmethod
    def parse_webhook(self, payload: dict) -> EmailEvent | None:
        """Turn a provider callback into our shape, or None if unrecognised."""
