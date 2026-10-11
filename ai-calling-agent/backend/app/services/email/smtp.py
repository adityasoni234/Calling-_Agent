"""SMTP delivery.

One adapter for Amazon SES, Mailgun, Postmark, Sendgrid and any corporate
relay, because all of them speak SMTP and the owner has not yet chosen. It
is the slower option -- a connection per batch rather than a JSON POST --
but it means the build does not wait on a purchasing decision.

The message is assembled as multipart/alternative with both a plain-text
and an HTML part. Sending HTML alone scores worse in every spam filter
that exists, so the service layer requires the text part and this refuses
to invent one.
"""

from __future__ import annotations

import uuid
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, make_msgid

import aiosmtplib
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.services.email.base import (
    EmailDispatched,
    EmailEvent,
    EmailNotConfigured,
    EmailProvider,
    OutboundEmail,
)

log = get_logger(__name__)


class SmtpEmail(EmailProvider):
    name = "smtp"

    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        creds = credentials or {}
        self.host = creds.get("host") or settings.smtp_host
        self.port = int(creds.get("port") or settings.smtp_port or 587)
        self.username = creds.get("username") or settings.smtp_username
        self.password = creds.get("password") or settings.smtp_password

    @property
    def configured(self) -> bool:
        return bool(self.host and self.username and self.password)

    def _build(self, message: OutboundEmail) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = (
            formataddr((message.from_name, message.from_address))
            if message.from_name
            else message.from_address
        )
        mime["To"] = message.to_address
        mime["Subject"] = message.subject
        # Generated here so the id is known before the send and can be
        # matched against a bounce that arrives minutes later.
        mime["Message-ID"] = make_msgid()
        if message.reply_to:
            mime["Reply-To"] = message.reply_to

        if message.unsubscribe_url:
            # Gmail and Yahoo require one-click unsubscribe on bulk mail.
            # Without both headers a sender's reputation degrades whatever
            # the footer link does.
            mime["List-Unsubscribe"] = f"<{message.unsubscribe_url}>"
            mime["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        for key, value in message.headers.items():
            mime[key] = value

        mime.set_content(message.text_body)
        if message.html_body:
            mime.add_alternative(message.html_body, subtype="html")
        return mime

    async def send(self, message: OutboundEmail) -> EmailDispatched:
        if not self.configured:
            raise EmailNotConfigured(
                "No SMTP credentials. Add a host, username and password in "
                "provider settings; nothing will be sent until they exist."
            )

        mime = self._build(message)
        try:
            await aiosmtplib.send(
                mime,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                # 587 is submission with STARTTLS; 465 is implicit TLS.
                start_tls=self.port == 587,
                use_tls=self.port == 465,
                timeout=30,
            )
        except aiosmtplib.SMTPRecipientsRefused as exc:
            # The server rejected the address outright. Permanent, and the
            # service layer suppresses on it.
            return EmailDispatched(
                provider_message_id=None,
                accepted=False,
                error_code="recipient_refused",
                error_message=str(exc),
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            # A relay or network failure is not a bad address. Reported as
            # failed with the reason, never swallowed into a fake success
            # and never treated as grounds for suppression.
            log.warning("email.smtp_failed", error=str(exc))
            return EmailDispatched(
                provider_message_id=None,
                accepted=False,
                error_code="transport_error",
                error_message=str(exc),
            )

        return EmailDispatched(provider_message_id=mime["Message-ID"], accepted=True)

    def parse_webhook(self, payload: dict) -> EmailEvent | None:
        """SMTP has no webhooks of its own.

        Bounces arrive at whatever the provider in front of it offers, so
        the concrete providers below parse those. Returning None here means
        "not mine" rather than "nothing happened".
        """
        return None


class PostmarkEmail(EmailProvider):
    """Postmark's HTTP API.

    Included alongside SMTP because its webhooks are the clearest of the
    common providers: one JSON body per event with an explicit record type,
    so a hard bounce can be told from a soft one without guesswork.
    """

    name = "postmark"
    API = "https://api.postmarkapp.com/email"

    #: Postmark's own vocabulary. Only HardBounce and SpamComplaint suppress;
    #: a Transient bounce is a full mailbox and the provider retries it.
    _EVENTS = {
        "Delivery": ("delivered", False),
        "Open": ("opened", False),
        "Click": ("clicked", False),
        "HardBounce": ("bounced", True),
        "Transient": ("deferred", False),
        "SoftBounce": ("deferred", False),
        "SpamComplaint": ("complained", True),
        "SubscriptionChange": ("unsubscribed", True),
    }

    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        self.token = (credentials or {}).get("server_token") or settings.postmark_token

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def send(self, message: OutboundEmail) -> EmailDispatched:
        if not self.configured:
            raise EmailNotConfigured("No Postmark server token is configured.")

        body: dict[str, object] = {
            "From": (
                f"{message.from_name} <{message.from_address}>"
                if message.from_name
                else message.from_address
            ),
            "To": message.to_address,
            "Subject": message.subject,
            "TextBody": message.text_body,
            "MessageStream": "broadcast",
        }
        if message.html_body:
            body["HtmlBody"] = message.html_body
        if message.reply_to:
            body["ReplyTo"] = message.reply_to
        if message.unsubscribe_url:
            body["Headers"] = [
                {"Name": "List-Unsubscribe", "Value": f"<{message.unsubscribe_url}>"},
                {
                    "Name": "List-Unsubscribe-Post",
                    "Value": "List-Unsubscribe=One-Click",
                },
            ]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.API,
                    json=body,
                    headers={
                        "X-Postmark-Server-Token": self.token,
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            return EmailDispatched(
                provider_message_id=None,
                accepted=False,
                error_code="transport_error",
                error_message=str(exc),
            )

        data = response.json() if response.content else {}
        if response.status_code >= 400:
            return EmailDispatched(
                provider_message_id=None,
                accepted=False,
                error_code=str(data.get("ErrorCode") or response.status_code),
                error_message=data.get("Message") or "Postmark rejected the message",
                raw=data,
            )
        return EmailDispatched(provider_message_id=data.get("MessageID"), accepted=True, raw=data)

    def parse_webhook(self, payload: dict) -> EmailEvent | None:
        record = payload.get("RecordType")
        if not record or record not in self._EVENTS:
            return None
        message_id = payload.get("MessageID")
        if not message_id:
            return None
        status, permanent = self._EVENTS[record]
        return EmailEvent(
            provider_message_id=str(message_id),
            status=status,
            to_address=payload.get("Recipient") or payload.get("Email"),
            detail=payload.get("Description") or payload.get("Details"),
            permanent=permanent,
        )


class UnconfiguredEmail(EmailProvider):
    """Stands in when nothing is set up, and says so.

    No "pretend it worked" path: a simulated success would show a delivered
    campaign to a customer whose recipients received nothing.
    """

    name = "none"

    @property
    def configured(self) -> bool:
        return False

    async def send(self, message: OutboundEmail) -> EmailDispatched:
        raise EmailNotConfigured(
            "No email provider is configured. Add SMTP credentials or a "
            "Postmark token in provider settings to start sending."
        )

    def parse_webhook(self, payload: dict) -> EmailEvent | None:
        return None


async def get_email_provider(
    organization_id: uuid.UUID | None = None, db: AsyncSession | None = None
) -> EmailProvider:
    """The provider this send should go through.

    Customer-owned mailboxes come first: when an organization has connected
    their own Gmail or Outlook, their mail leaves from their address at
    their cost. The platform-wide options stay for a deployment that would
    rather carry sending centrally.

    Selection is explicit rather than "whichever has keys", so a developer
    with real credentials in their environment cannot start mailing real
    people because a fixture forgot to opt out.
    """
    choice = settings.email_provider
    if choice == "mock":
        from app.services.email.mock import MockEmail

        return MockEmail()

    if choice == "mailbox":
        if organization_id is None or db is None:
            return UnconfiguredEmail()
        from app.models.email_account import EmailAccount, MailboxStatus
        from app.services.email.mailbox import MailboxEmail, refresh_access_token

        rows = await db.execute(
            select(EmailAccount).where(
                EmailAccount.organization_id == organization_id,
                EmailAccount.status == MailboxStatus.CONNECTED,
            )
        )
        accounts = sorted(rows.scalars(), key=lambda a: not a.is_default)
        if not accounts:
            return UnconfiguredEmail()

        account = accounts[0]
        try:
            # Access tokens last an hour, so almost every send refreshes.
            token = await refresh_access_token(account)
        except EmailNotConfigured:
            await db.commit()  # persist the expired status
            return UnconfiguredEmail()
        await db.commit()
        return MailboxEmail(account, token)

    from app.services.credentials import resolve

    if choice == "postmark":
        provider: EmailProvider = PostmarkEmail(await resolve("postmark"))
    else:
        provider = SmtpEmail(await resolve("smtp"))
    return provider if provider.configured else UnconfiguredEmail()
