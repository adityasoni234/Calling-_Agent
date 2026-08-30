"""OmniDimension adapter.

Unlike the other carriers, OmniDimension is a *hosted agent* platform: it owns
the audio loop, so there is no media WebSocket for our conversation manager to
attach to, and prompts, barge-in and the state machine live on their side.

It is here because it sells Indian numbers instantly -- the one thing Twilio,
Telnyx and Plivo all gate behind KYC or an account upgrade. The platform keeps
everything above the audio loop: leads, campaigns, concurrency, transcripts,
summarisation, lead scoring and cost.

Swap back to `plivo` once you hold your own Indian DID and the full pipeline
(and its much cheaper unit economics) returns with an env change.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.models.call import CallStatus
from app.services.base import ProviderError
from app.services.telephony.base import (
    OriginateResult,
    TelephonyEvent,
    TelephonyEventType,
    TelephonyProvider,
)

log = get_logger(__name__)
API_BASE = "https://omnidim.io/api/v1"

STATUS_MAP = {
    "completed": CallStatus.COMPLETED,
    "answered": CallStatus.COMPLETED,
    "no_answer": CallStatus.NO_ANSWER,
    "no-answer": CallStatus.NO_ANSWER,
    "busy": CallStatus.BUSY,
    "failed": CallStatus.FAILED,
    "canceled": CallStatus.CANCELED,
    "cancelled": CallStatus.CANCELED,
}


class OmniDimensionTelephonyProvider(TelephonyProvider):
    name = "omnidimension"
    answers_with_document = False
    runs_own_conversation = True

    def _headers(self) -> dict[str, str]:
        if not settings.omnidimension_api_key:
            raise ProviderError(self.name, "OMNIDIMENSION_API_KEY is not set")
        return {
            "Authorization": f"Bearer {settings.omnidimension_api_key}",
            "Content-Type": "application/json",
        }

    # --- lifecycle -----------------------------------------------------

    async def originate(
        self,
        *,
        to_number: str,
        from_number: str,
        answer_url: str,
        status_url: str,
        call_id: str,
        record: bool = False,
    ) -> OriginateResult:
        if not settings.omnidimension_agent_id:
            raise ProviderError(self.name, "OMNIDIMENSION_AGENT_ID is not set")

        body: dict[str, Any] = {
            "agent_id": int(settings.omnidimension_agent_id),
            "to_number": to_number,
            # Echoed back on their post-call webhook, which is how their call
            # gets matched to ours.
            "metadata": {"platform_call_id": call_id},
        }
        if settings.omnidimension_from_number_id:
            body["from_number_id"] = int(settings.omnidimension_from_number_id)

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                response = await client.post(
                    f"{API_BASE}/calls/dispatch", headers=self._headers(), json=body
                )
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

        if response.status_code >= 400:
            raise ProviderError(self.name, f"{response.status_code}: {response.text[:300]}")

        payload = response.json()
        provider_call_id = str(
            payload.get("call_log_id")
            or payload.get("id")
            or payload.get("request_id")
            or payload.get("session_id")
            or ""
        )
        log.info("telephony.originated", provider=self.name, provider_call_id=provider_call_id)
        return OriginateResult(provider_call_id=provider_call_id, status=CallStatus.INITIATED)

    async def hangup(self, provider_call_id: str) -> None:
        # Their API exposes no hang-up command; the agent ends the call from its
        # own end-call conditions. Log rather than pretend it worked.
        log.warning("telephony.hangup_unsupported", provider=self.name, call=provider_call_id)

    async def transfer(self, provider_call_id: str, to_number: str) -> None:
        raise ProviderError(
            self.name, "transfer is configured on the OmniDimension agent, not per call"
        )

    def answer_document(self, *, websocket_url: str) -> tuple[str, str]:
        return ("{}", "application/json")

    # --- webhooks ------------------------------------------------------

    def parse_webhook(self, payload: dict[str, Any]) -> TelephonyEvent:
        """Parse their post-call notification.

        It arrives once, after the call, so there is no ringing/answered
        progression to report -- only the outcome.
        """
        body = payload.get("call") or payload.get("call_log") or payload
        raw_status = str(body.get("call_status") or body.get("status") or "").lower()
        status = STATUS_MAP.get(raw_status)

        duration = body.get("call_duration_in_seconds") or body.get("duration")
        recording = body.get("recording_url")
        if recording is False:
            recording = None

        return TelephonyEvent(
            type=TelephonyEventType.COMPLETED
            if status is CallStatus.COMPLETED
            else TelephonyEventType.FAILED
            if status
            else TelephonyEventType.UNKNOWN,
            provider_call_id=str(body.get("id") or body.get("call_log_id") or ""),
            status=status,
            duration_seconds=int(duration) if duration else None,
            recording_url=recording if isinstance(recording, str) else None,
            raw=payload,
        )

    def platform_call_id(self, payload: dict[str, Any]) -> str | None:
        """Our own call id, echoed back through their `metadata`."""
        metadata = payload.get("metadata") or (payload.get("call") or {}).get("metadata") or {}
        value = metadata.get("platform_call_id")
        return str(value) if value else None

    async def fetch_call_log(self, provider_call_id: str) -> dict[str, Any]:
        """Pull the finished call, for its transcript and duration."""
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                response = await client.get(
                    f"{API_BASE}/calls/logs/{provider_call_id}", headers=self._headers()
                )
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, str(exc), retryable=True) from exc

        if response.status_code >= 400:
            raise ProviderError(self.name, f"{response.status_code}: {response.text[:300]}")

        rows = response.json().get("call_log_data") or []
        return rows[0] if rows else {}

    # --- media (not applicable) ----------------------------------------

    def decode_media(self, message: dict[str, Any]) -> bytes | None:
        return None

    def encode_media(self, audio: bytes, stream_id: str | None) -> dict[str, Any]:
        raise ProviderError(self.name, "OmniDimension runs its own audio loop")

    def clear_message(self, stream_id: str | None) -> dict[str, Any] | None:
        return None
