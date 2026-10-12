"""Razorpay's own word on what was paid.

Until this existed, credits were allocated down exactly one path: the
customer's browser coming back from checkout and calling
`/billing/orders/{id}/confirm`. That path is fine when it runs, and it does
not run when the customer closes the tab, loses signal in a lift, or their
phone dies on the Razorpay success screen. Razorpay has the money either
way. The order sits `pending`, the credits never land, and the first anyone
hears of it is the customer asking where their balance went.

So this is the second path, and it is the one that does not depend on a
browser staying open. Razorpay retries a webhook until it is acknowledged,
which means a payment eventually lands even if our service was restarting
when the customer paid.

Unauthenticated by necessity, because Razorpay is the caller. The HMAC over
the raw body is the credential, and it is checked before the JSON is parsed
-- parsing first would mean running a parser on bytes nobody has vouched
for.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.package import Order
from app.services.order_service import OrderService
from app.services.payments.razorpay import get_payment_provider

router = APIRouter(prefix="/webhooks/payments", tags=["webhooks"])
log = get_logger(__name__)

#: Razorpay sends dozens of event types and retries anything it does not get
#: a 2xx for. Acknowledging the ones we do not act on keeps them from being
#: redelivered forever; the two here are the only ones that move credits.
_CAPTURED = "payment.captured"
_FAILED = "payment.failed"


def _entity(event: dict[str, Any], kind: str) -> dict[str, Any]:
    return dict(event.get("payload", {}).get(kind, {}).get("entity", {}) or {})


@router.post("/razorpay", summary="Payment events from Razorpay")
async def razorpay_webhook(request: Request, db: DbSession) -> JSONResponse:
    """Allocate credits for a payment Razorpay says it captured.

    Returns 200 for anything that retrying cannot fix -- an event we do not
    act on, or an order we do not recognise -- and a non-2xx only when a
    retry genuinely might succeed. Getting that backwards is how a webhook
    endpoint ends up in a redelivery loop that nobody notices until the logs
    are unreadable.
    """
    body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    provider = get_payment_provider()
    if not provider.configured:
        # Nothing can be verified without the secret, so this is not an
        # acknowledgement. Razorpay should retry once we are configured.
        log.error("payment.webhook.unconfigured")
        return JSONResponse({"error": "payment provider not configured"}, status_code=503)

    try:
        event = provider.verify_webhook(body=body, signature=signature)
    except ValueError:
        # Never 200 an unverified body: a 200 tells Razorpay we accepted it,
        # and tells an attacker their forgery was swallowed quietly.
        log.warning("payment.webhook.bad_signature", bytes=len(body))
        return JSONResponse({"error": "signature did not match"}, status_code=400)
    except AppError as exc:
        log.error("payment.webhook.verify_failed", error=str(exc))
        return JSONResponse({"error": "could not verify"}, status_code=503)

    kind = str(event.get("event", ""))
    if kind not in (_CAPTURED, _FAILED):
        return JSONResponse({"status": "ignored", "event": kind})

    payment = _entity(event, "payment")
    provider_order_id = str(payment.get("order_id") or "")
    payment_id = str(payment.get("id") or "")
    if not provider_order_id:
        log.warning("payment.webhook.no_order_id", event_type=kind, payment_id=payment_id)
        return JSONResponse({"status": "ignored", "reason": "no order id"})

    order = (
        await db.execute(select(Order).where(Order.provider_order_id == provider_order_id))
    ).scalar_one_or_none()
    if order is None:
        # Retrying will not conjure the order. This is either an event for a
        # different environment sharing the Razorpay account, or a real bug,
        # and both want a log line rather than an infinite redelivery.
        log.error(
            "payment.webhook.unknown_order",
            provider_order_id=provider_order_id,
            event_type=kind,
        )
        return JSONResponse({"status": "ignored", "reason": "unknown order"})

    service = OrderService(db)

    if kind == _FAILED:
        reason = str(payment.get("error_description") or "Razorpay reported a failed payment")
        await service.mark_failed(order, reason)
        log.info("payment.webhook.failed", reference=order.reference, reason=reason)
        return JSONResponse({"status": "recorded", "order": order.reference})

    if order.credits_allocated_at is not None:
        # The browser handback beat us here, which is the normal happy case.
        return JSONResponse({"status": "already allocated", "order": order.reference})

    # The signed event already says what was captured, but the API is the
    # only authority on payment in this codebase and that rule is worth more
    # than one round trip: it means a leaked webhook secret on its own
    # cannot mint credits.
    try:
        verified = await provider.fetch_payment(payment_id)
    except AppError as exc:
        log.error("payment.webhook.fetch_failed", reference=order.reference, error=str(exc))
        # A retry here really might succeed -- Razorpay may simply have been
        # unreachable -- so do not acknowledge.
        return JSONResponse({"error": "could not confirm with provider"}, status_code=503)

    if verified.status != "paid":
        log.warning(
            "payment.webhook.not_captured",
            reference=order.reference,
            provider_status=verified.status,
        )
        return JSONResponse({"status": "ignored", "reason": verified.status})

    try:
        await service.mark_paid(
            order,
            provider=provider.name,
            provider_payment_id=verified.provider_payment_id,
            amount_minor=verified.amount_minor,
            currency=verified.currency,
        )
    except AppError as exc:
        # An amount or currency mismatch is a refusal, not a transient
        # failure. `mark_paid` has already marked the order failed, and a
        # retry would reach the same conclusion.
        log.error("payment.webhook.rejected", reference=order.reference, error=str(exc))
        return JSONResponse({"status": "rejected", "reason": exc.code})

    log.info(
        "payment.webhook.allocated",
        reference=order.reference,
        credits=order.total_credits,
    )
    return JSONResponse({"status": "allocated", "order": order.reference})
