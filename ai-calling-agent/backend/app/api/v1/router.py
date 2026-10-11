"""v1 API surface."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    agents,
    analytics,
    auth,
    billing,
    calls,
    campaigns,
    health,
    integrations,
    knowledge,
    leads,
    learning,
    media,
    messaging,
    messaging_webhooks,
    platform,
    settings_api,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(billing.router)
api_router.include_router(agents.router)
api_router.include_router(leads.router)
api_router.include_router(campaigns.router)
api_router.include_router(calls.router)
api_router.include_router(knowledge.router)
api_router.include_router(analytics.router)
api_router.include_router(platform.router)
api_router.include_router(settings_api.router)
api_router.include_router(integrations.router)
api_router.include_router(learning.router)
api_router.include_router(webhooks.router)
api_router.include_router(media.router)
api_router.include_router(messaging.router)
api_router.include_router(messaging_webhooks.router)
