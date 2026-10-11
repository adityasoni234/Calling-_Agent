"""SQLAlchemy models.

Importing every model here is what makes `Base.metadata` complete for Alembic
autogenerate and for the test-suite schema creation.
"""

from app.db.base import Base
from app.models.activity import ActivityEvent, ActorType, EntityType
from app.models.agent import Agent, AgentLanguage
from app.models.billing import CreditEntry, CreditEntryKind, PlanTier, PlatformEvent
from app.models.call import (
    TERMINAL_STATUSES,
    Call,
    CallDirection,
    CallMode,
    CallSource,
    CallStatus,
    CallTurn,
    CallUsage,
    UsageComponent,
)
from app.models.campaign import Campaign, CampaignLead, CampaignLeadStatus, CampaignStatus
from app.models.fx import ExchangeRate
from app.models.integration import (
    ApiKey,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
    WebhookEvent,
)
from app.models.knowledge import Document, DocumentChunk, DocumentStatus, KnowledgeBase
from app.models.lead import InterestLevel, Lead, LeadStatus
from app.models.lead_list import LeadList, LeadListMember, LeadListSource
from app.models.learning import AgentVariant, VariantKind, VariantStatus, VariantTrial
from app.models.messaging import (
    BILLABLE_MESSAGE_STATUSES,
    TERMINAL_MESSAGE_STATUSES,
    Channel,
    ConsentMethod,
    ConsentRecord,
    Conversation,
    Message,
    MessageCampaign,
    MessageCampaignStatus,
    MessageDirection,
    MessageStatus,
    MessageTemplate,
    Suppression,
    SuppressionReason,
    TemplateStatus,
)
from app.models.organization import Organization
from app.models.package import CreditPackage, Order, OrderStatus, PackageKind, PaymentEvent
from app.models.price_book import (
    Billable,
    PriceBook,
    PriceBookStatus,
    PriceOverride,
    PriceRule,
    RateKind,
    Rounding,
)
from app.models.pricing import PricingRate
from app.models.provider import (
    ProviderBalance,
    ProviderConnection,
    ProviderKind,
    ProviderStatus,
    ProviderSyncRun,
    ProviderUsageRecord,
)
from app.models.refresh_token import RefreshToken
from app.models.reservation import CreditReservation, ReservationStatus
from app.models.user import User, UserRole

__all__ = [
    "TemplateStatus",
    "SuppressionReason",
    "Suppression",
    "MessageTemplate",
    "MessageStatus",
    "MessageDirection",
    "MessageCampaignStatus",
    "MessageCampaign",
    "Message",
    "Conversation",
    "ConsentRecord",
    "ConsentMethod",
    "Channel",
    "TERMINAL_MESSAGE_STATUSES",
    "BILLABLE_MESSAGE_STATUSES",
    "Rounding",
    "RateKind",
    "ProviderUsageRecord",
    "ProviderSyncRun",
    "ProviderStatus",
    "ProviderKind",
    "ProviderConnection",
    "ProviderBalance",
    "PriceRule",
    "PriceOverride",
    "PriceBookStatus",
    "PriceBook",
    "ExchangeRate",
    "Billable",
    "TERMINAL_STATUSES",
    "ActivityEvent",
    "ActorType",
    "Agent",
    "AgentVariant",
    "ApiKey",
    "AgentLanguage",
    "Base",
    "Call",
    "CreditEntry",
    "CreditPackage",
    "CreditReservation",
    "CreditEntryKind",
    "CallDirection",
    "CallMode",
    "CallSource",
    "CallStatus",
    "CallTurn",
    "CallUsage",
    "Campaign",
    "CampaignLead",
    "CampaignLeadStatus",
    "CampaignStatus",
    "Document",
    "EntityType",
    "DocumentChunk",
    "DocumentStatus",
    "InterestLevel",
    "KnowledgeBase",
    "Lead",
    "LeadList",
    "LeadListMember",
    "LeadListSource",
    "LeadStatus",
    "Order",
    "OrderStatus",
    "Organization",
    "PackageKind",
    "PaymentEvent",
    "PlanTier",
    "PlatformEvent",
    "PricingRate",
    "RefreshToken",
    "ReservationStatus",
    "UsageComponent",
    "User",
    "UserRole",
    "VariantKind",
    "VariantStatus",
    "VariantTrial",
    "WebhookDelivery",
    "WebhookDeliveryStatus",
    "WebhookEndpoint",
    "WebhookEvent",
]
