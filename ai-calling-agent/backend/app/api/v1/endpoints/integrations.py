"""The integration surface a CRM plugs into.

Nothing here is CRM-specific. A key to call in, a signed webhook to be called
back on, and the existing REST API in between -- which is all any of them need.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, requires
from app.core.errors import NotFoundError
from app.core.permissions import Capability
from app.models.activity import EntityType
from app.models.integration import ApiKey, WebhookDelivery, WebhookEndpoint, WebhookEvent
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.integration import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    WebhookDeliveryRead,
    WebhookEndpointCreate,
    WebhookEndpointCreated,
    WebhookEndpointRead,
    WebhookEndpointUpdate,
)
from app.services.activity_service import safe_record
from app.services.integration_service import IntegrationService

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/events", response_model=list[str], summary="Events you can subscribe to")
async def list_events() -> list[str]:
    return [event.value for event in WebhookEvent]


# --- API keys ----------------------------------------------------------


@router.get("/keys", response_model=list[ApiKeyRead], summary="List API keys")
async def list_keys(db: DbSession, user: CurrentUser) -> list[ApiKeyRead]:
    rows = await db.execute(
        select(ApiKey)
        .where(ApiKey.organization_id == user.organization_id)
        .order_by(ApiKey.created_at.desc())
    )
    return [ApiKeyRead.model_validate(key) for key in rows.scalars()]


@router.post(
    "/keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
)
async def create_key(
    payload: ApiKeyCreate,
    db: DbSession,
    user: Annotated[User, Depends(requires(Capability.MANAGE_INTEGRATIONS))],
) -> ApiKeyCreated:
    """The plaintext key is in this response and nowhere else. Copy it now."""
    key, raw = await IntegrationService(db).create_key(user.organization_id, payload.name)
    await safe_record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="api_key.created",
        entity_type=EntityType.API_KEY,
        entity_id=key.id,
        entity_label=key.name,
        # The prefix identifies the key without being the key.
        summary=f"{user.email} created API key {key.name} ({key.prefix}…)",
    )
    return ApiKeyCreated(**ApiKeyRead.model_validate(key).model_dump(), key=raw)


@router.delete("/keys/{key_id}", response_model=MessageResponse, summary="Revoke an API key")
async def revoke_key(
    key_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(requires(Capability.MANAGE_INTEGRATIONS))],
) -> MessageResponse:
    key = await db.get(ApiKey, key_id)
    if key is None or key.organization_id != user.organization_id:
        raise NotFoundError("API key not found")
    await IntegrationService(db).revoke_key(key)
    return MessageResponse(message="Key revoked. Anything using it will stop working now.")


# --- webhooks ----------------------------------------------------------


@router.get("/webhooks", response_model=list[WebhookEndpointRead], summary="List webhooks")
async def list_webhooks(db: DbSession, user: CurrentUser) -> list[WebhookEndpointRead]:
    rows = await db.execute(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.organization_id == user.organization_id)
        .order_by(WebhookEndpoint.created_at.desc())
    )
    return [WebhookEndpointRead.model_validate(endpoint) for endpoint in rows.scalars()]


@router.post(
    "/webhooks",
    response_model=WebhookEndpointCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Register a webhook",
)
async def create_webhook(
    payload: WebhookEndpointCreate,
    db: DbSession,
    user: Annotated[User, Depends(requires(Capability.MANAGE_INTEGRATIONS))],
) -> WebhookEndpointCreated:
    endpoint = await IntegrationService(db).create_endpoint(
        user.organization_id,
        url=payload.url,
        events=[event.value for event in payload.events],
        description=payload.description,
    )
    return WebhookEndpointCreated(
        **WebhookEndpointRead.model_validate(endpoint).model_dump(), secret=endpoint.secret
    )


@router.patch(
    "/webhooks/{endpoint_id}", response_model=WebhookEndpointRead, summary="Update a webhook"
)
async def update_webhook(
    endpoint_id: uuid.UUID,
    payload: WebhookEndpointUpdate,
    db: DbSession,
    user: Annotated[User, Depends(requires(Capability.MANAGE_INTEGRATIONS))],
) -> WebhookEndpointRead:
    endpoint = await _get_endpoint(db, user, endpoint_id)
    data = payload.model_dump(exclude_unset=True)
    if "events" in data and data["events"] is not None:
        endpoint.events = [str(event) for event in data["events"]]
    if "description" in data:
        endpoint.description = data["description"]
    if data.get("is_active") is not None:
        endpoint.is_active = bool(data["is_active"])
        if endpoint.is_active:
            # Re-enabling is the operator saying the endpoint is fixed; keeping
            # the old failure count would disable it again almost immediately.
            endpoint.failure_count = 0
    await db.commit()
    await db.refresh(endpoint)
    return WebhookEndpointRead.model_validate(endpoint)


@router.delete(
    "/webhooks/{endpoint_id}", response_model=MessageResponse, summary="Delete a webhook"
)
async def delete_webhook(
    endpoint_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(requires(Capability.MANAGE_INTEGRATIONS))],
) -> MessageResponse:
    endpoint = await _get_endpoint(db, user, endpoint_id)
    url = endpoint.url
    await db.delete(endpoint)
    await db.commit()
    await safe_record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="webhook.deleted",
        entity_type=EntityType.WEBHOOK,
        entity_id=endpoint_id,
        entity_label=url,
        summary=f"{user.email} removed webhook {url}",
    )
    return MessageResponse(message="Webhook removed")


@router.post(
    "/webhooks/{endpoint_id}/test", response_model=MessageResponse, summary="Send a test event"
)
async def test_webhook(endpoint_id: uuid.UUID, db: DbSession, user: CurrentUser) -> MessageResponse:
    """Prove the plumbing before a real call depends on it."""
    endpoint = await _get_endpoint(db, user, endpoint_id)
    service = IntegrationService(db)
    db.add(
        WebhookDelivery(
            endpoint_id=endpoint.id,
            event=WebhookEvent.CALL_COMPLETED,
            payload={
                "event": "call.completed",
                "test": True,
                "data": {"message": "Test delivery from your calling agent."},
            },
        )
    )
    await db.commit()
    sent = await service.deliver_pending(limit=5)
    return MessageResponse(
        message="Test delivered." if sent else "Test queued, but the endpoint did not accept it."
    )


@router.get(
    "/webhooks/{endpoint_id}/deliveries",
    response_model=list[WebhookDeliveryRead],
    summary="Recent deliveries, for debugging",
)
async def list_deliveries(
    endpoint_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[WebhookDeliveryRead]:
    await _get_endpoint(db, user, endpoint_id)
    rows = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.endpoint_id == endpoint_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(50)
    )
    return [WebhookDeliveryRead.model_validate(row) for row in rows.scalars()]


async def _get_endpoint(db, user, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.organization_id != user.organization_id:
        raise NotFoundError("Webhook not found")
    return endpoint
