"""Connecting a customer's own Gmail or Outlook mailbox.

OAuth only. The customer approves access in Google's or Microsoft's own
dialog and we store what they hand back; nobody types a password or pastes
an API token into our forms. That is a security property, not a convenience
one -- a form that accepts a credential is a form that can leak one, and a
support person can be talked into reading one back.

The send goes through the provider's own API using that grant, so mail
leaves from the customer's address with their provider's reputation behind
it, and costs this platform nothing.

What this honestly cannot do: bulk. Gmail allows about 500 recipients a day
on a personal account and 2,000 on Workspace, and exceeding it suspends
sending for twenty-four hours. The limit is tracked and refused against
rather than discovered the hard way.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr

import httpx

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.email_account import EmailAccount, MailboxProvider, MailboxStatus
from app.services.email.base import (
    EmailDispatched,
    EmailEvent,
    EmailNotConfigured,
    EmailProvider,
    OutboundEmail,
)

log = get_logger(__name__)

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GMAIL_SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"

MS_AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_SEND = "https://graph.microsoft.com/v1.0/me/sendMail"
MS_ME = "https://graph.microsoft.com/v1.0/me"

#: The narrowest scope that can send. `gmail.send` cannot read the mailbox,
#: which matters both for the customer's trust and for Google's review:
#: asking for full mail access would need a far heavier assessment.
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "email",
    "profile",
)
MS_SCOPES = ("Mail.Send", "User.Read", "offline_access")

#: Gmail's published ceilings. Personal accounts are far lower than people
#: expect, which is the single most common surprise in this feature.
DAILY_LIMITS = {"gmail.com": 500, "googlemail.com": 500}
WORKSPACE_LIMIT = 2000
OUTLOOK_LIMIT = 300


@dataclass
class MailboxGrant:
    provider: MailboxProvider
    address: str
    display_name: str
    access_token: str
    refresh_token: str
    expires_at: datetime | None
    scopes: list[str]
    daily_limit: int


def google_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def microsoft_configured() -> bool:
    return bool(settings.microsoft_client_id and settings.microsoft_client_secret)


def new_state() -> str:
    return secrets.token_urlsafe(32)


def authorize_url(provider: MailboxProvider, state: str, redirect_uri: str) -> str:
    from urllib.parse import urlencode

    if provider is MailboxProvider.GMAIL:
        if not google_configured():
            raise AppError(
                "Gmail connection is not set up on this platform yet.",
                code="gmail_unconfigured",
            )
        return f"{GOOGLE_AUTH}?" + urlencode(
            {
                "client_id": settings.google_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(GOOGLE_SCOPES),
                "state": state,
                # Google issues a refresh token only on the first consent
                # unless forced. Without it a connection silently stops
                # working an hour later.
                "access_type": "offline",
                "prompt": "consent",
            }
        )

    if not microsoft_configured():
        raise AppError(
            "Outlook connection is not set up on this platform yet.",
            code="outlook_unconfigured",
        )
    return f"{MS_AUTH}?" + urlencode(
        {
            "client_id": settings.microsoft_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(MS_SCOPES),
            "state": state,
            "response_mode": "query",
        }
    )


async def exchange_code(provider: MailboxProvider, code: str, redirect_uri: str) -> MailboxGrant:
    """Trade the one-time code for tokens, then read whose mailbox it is.

    The address comes from the provider rather than from a form, so it
    cannot disagree with what the mailbox will actually accept as a sender.
    """
    is_google = provider is MailboxProvider.GMAIL
    token_url = GOOGLE_TOKEN if is_google else MS_TOKEN
    data = {
        "code": code,
        "client_id": settings.google_client_id if is_google else settings.microsoft_client_id,
        "client_secret": settings.google_client_secret
        if is_google
        else settings.microsoft_client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(token_url, data=data)
        if response.status_code >= 400:
            raise AppError(_error(response), code="oauth_failed")
        payload = response.json()

        access = payload.get("access_token", "")
        refresh = payload.get("refresh_token", "")
        if not refresh:
            # Without it the grant lasts an hour. Better to say so now than
            # to have sending stop after lunch with no explanation.
            raise AppError(
                "The provider did not return a refresh token. Remove this "
                "app's access in your account settings and connect again.",
                code="no_refresh_token",
            )

        if is_google:
            profile = await client.get(
                GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"}
            )
            info = profile.json() if profile.status_code < 400 else {}
            address = info.get("email", "")
            name = info.get("name", "")
        else:
            profile = await client.get(MS_ME, headers={"Authorization": f"Bearer {access}"})
            info = profile.json() if profile.status_code < 400 else {}
            address = info.get("mail") or info.get("userPrincipalName") or ""
            name = info.get("displayName", "")

    if not address:
        raise AppError(
            "Could not read the mailbox address from the provider.",
            code="no_address",
        )

    domain = address.rpartition("@")[2].lower()
    limit = DAILY_LIMITS.get(domain, WORKSPACE_LIMIT) if is_google else OUTLOOK_LIMIT

    return MailboxGrant(
        provider=provider,
        address=address.lower(),
        display_name=name,
        access_token=access,
        refresh_token=refresh,
        expires_at=(
            datetime.now(UTC) + timedelta(seconds=int(payload["expires_in"]))
            if payload.get("expires_in")
            else None
        ),
        scopes=str(payload.get("scope", "")).split(),
        daily_limit=limit,
    )


def _error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"The provider returned HTTP {response.status_code}"
    return (
        payload.get("error_description") or (payload.get("error") or {}).get("message")
        if isinstance(payload.get("error"), dict)
        else payload.get("error_description")
        or str(payload.get("error"))
        or f"HTTP {response.status_code}"
    )


async def refresh_access_token(account: EmailAccount) -> str:
    """Swap the refresh token for a fresh access token.

    Access tokens last an hour, so almost every send needs this. A refresh
    that fails means the customer revoked access, and the account is marked
    expired rather than retried -- only they can fix it.
    """
    is_google = account.provider is MailboxProvider.GMAIL
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GOOGLE_TOKEN if is_google else MS_TOKEN,
            data={
                "refresh_token": decrypt(account.refresh_token),
                "client_id": settings.google_client_id
                if is_google
                else settings.microsoft_client_id,
                "client_secret": settings.google_client_secret
                if is_google
                else settings.microsoft_client_secret,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code >= 400:
        account.status = MailboxStatus.EXPIRED
        account.status_detail = (
            "Access was revoked or expired. Reconnect the mailbox to resume sending."
        )
        raise EmailNotConfigured(account.status_detail)

    payload = response.json()
    token = payload["access_token"]
    account.access_token = encrypt(token)
    if payload.get("expires_in"):
        account.token_expires_at = datetime.now(UTC) + timedelta(seconds=int(payload["expires_in"]))
    return token


class MailboxEmail(EmailProvider):
    """Sends through a customer's own connected mailbox."""

    def __init__(self, account: EmailAccount, access_token: str) -> None:
        self.account = account
        self.token = access_token
        self.name = str(account.provider)

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _mime(self, message: OutboundEmail) -> MimeMessage:
        mime = MimeMessage()
        # The From is the connected mailbox, not whatever was typed: Gmail
        # rejects a mismatched sender, and silently rewriting it would be
        # worse than refusing.
        mime["From"] = (
            formataddr((self.account.display_name, self.account.address))
            if self.account.display_name
            else self.account.address
        )
        mime["To"] = message.to_address
        mime["Subject"] = message.subject
        if message.reply_to:
            mime["Reply-To"] = message.reply_to
        if message.unsubscribe_url:
            mime["List-Unsubscribe"] = f"<{message.unsubscribe_url}>"
            mime["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        mime.set_content(message.text_body)
        if message.html_body:
            mime.add_alternative(message.html_body, subtype="html")
        return mime

    async def send(self, message: OutboundEmail) -> EmailDispatched:
        if self.account.remaining_today <= 0:
            # Refused here rather than attempted: exceeding the provider's
            # ceiling suspends the whole mailbox for a day, which costs far
            # more than the one message.
            return EmailDispatched(
                provider_message_id=None,
                accepted=False,
                error_code="daily_limit",
                error_message=(
                    f"{self.account.address} has used its daily limit of "
                    f"{self.account.daily_limit}. It resets in 24 hours."
                ),
            )

        mime = self._mime(message)
        try:
            if self.account.provider is MailboxProvider.GMAIL:
                body = {"raw": base64.urlsafe_b64encode(mime.as_bytes()).decode()}
                url, payload = GMAIL_SEND, {"json": body}
            else:
                url, payload = (
                    MS_SEND,
                    {
                        "json": {
                            "message": {
                                "subject": message.subject,
                                "body": {
                                    "contentType": "HTML" if message.html_body else "Text",
                                    "content": message.html_body or message.text_body,
                                },
                                "toRecipients": [{"emailAddress": {"address": message.to_address}}],
                            },
                            "saveToSentItems": True,
                        }
                    },
                )

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url, headers={"Authorization": f"Bearer {self.token}"}, **payload
                )
        except httpx.HTTPError as exc:
            return EmailDispatched(
                provider_message_id=None,
                accepted=False,
                error_code="transport_error",
                error_message=str(exc),
            )

        if response.status_code >= 400:
            detail = _error(response)
            log.warning("mailbox.send_failed", status=response.status_code)
            return EmailDispatched(
                provider_message_id=None,
                accepted=False,
                error_code=str(response.status_code),
                error_message=detail,
            )

        sent_id = (
            response.json().get("id")
            if response.content and response.status_code != 202
            else mime.get("Message-ID") or "accepted"
        )
        self.account.sent_today += 1
        self.account.last_sent_at = datetime.now(UTC)
        return EmailDispatched(provider_message_id=str(sent_id), accepted=True)

    def parse_webhook(self, payload: dict) -> EmailEvent | None:
        """Neither provider pushes delivery events for sent mail.

        A bounce comes back as a new message in the customer's own inbox,
        which `gmail.send` deliberately cannot read. Returning None is
        honest; claiming delivery confirmation we do not have would not be.
        """
        return None
