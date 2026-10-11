"""What each role may do.

Capabilities rather than bare role checks at each call site. A reviewer can read
this one table and answer "can a viewer spend money" without grepping fifty
endpoints, and adding a role is a row here rather than an audit of the codebase.

Platform staff are deliberately absent: `is_platform_admin` is a separate flag
guarding a separate API, so no customer role can ever reach it.
"""

from __future__ import annotations

import enum

from app.models.user import UserRole


class Capability(enum.StrEnum):
    # Reading the product.
    READ = "read"

    # Things that cost money or reach a customer's phone.
    PLACE_CALLS = "place_calls"
    RUN_CAMPAIGNS = "run_campaigns"

    # Changing what the product does.
    MANAGE_AGENTS = "manage_agents"
    MANAGE_LEADS = "manage_leads"
    MANAGE_KNOWLEDGE = "manage_knowledge"

    # Commercial and security surfaces, which an operator must not touch.
    BUY_CREDITS = "buy_credits"
    VIEW_BILLING = "view_billing"
    MANAGE_BILLING = "manage_billing"
    MANAGE_INTEGRATIONS = "manage_integrations"
    MANAGE_SETTINGS = "manage_settings"

    # Messaging reaches a customer's phone and costs money per segment, so it
    # is gated like calling rather than bundled into general write access.
    SEND_MESSAGES = "send_messages"
    MANAGE_TEMPLATES = "manage_templates"
    #: Reading other people's conversations is a privacy surface of its own.
    VIEW_CONVERSATIONS = "view_conversations"
    MANAGE_TEAM = "manage_team"


#: Least privilege, built upward. A viewer can look; an operator can work the
#: phones; an admin can configure; only an owner can spend or change the team.
_VIEWER = frozenset({Capability.READ, Capability.VIEW_BILLING})

_OPERATOR = _VIEWER | {
    Capability.PLACE_CALLS,
    Capability.RUN_CAMPAIGNS,
    Capability.MANAGE_LEADS,
    # An operator's job is reaching contacts; messaging is that job by
    # another channel. Approving the templates they send is not.
    Capability.SEND_MESSAGES,
    Capability.VIEW_CONVERSATIONS,
}

#: Money, without the product. Deliberately cannot place a call, send a
#: message or read a conversation: a billing dispute is settled from the
#: ledger, not by listening to the customer's calls.
_FINANCE = _VIEWER | {
    Capability.MANAGE_BILLING,
    Capability.BUY_CREDITS,
}

#: The mirror image of finance: the widest read access on customer content,
#: and no authority over money at all.
_SUPPORT = _VIEWER | {
    Capability.VIEW_CONVERSATIONS,
    Capability.MANAGE_LEADS,
    Capability.SEND_MESSAGES,
}

#: Keeps the pipes running. Providers and settings, nothing commercial.
_OPERATIONS = _VIEWER | {
    Capability.MANAGE_INTEGRATIONS,
    Capability.MANAGE_SETTINGS,
    Capability.PLACE_CALLS,
}

_ADMIN = _OPERATOR | {
    Capability.MANAGE_AGENTS,
    Capability.MANAGE_TEMPLATES,
    Capability.MANAGE_KNOWLEDGE,
    Capability.MANAGE_INTEGRATIONS,
    Capability.MANAGE_SETTINGS,
}

_OWNER = _ADMIN | {
    Capability.BUY_CREDITS,
    Capability.MANAGE_BILLING,
    Capability.MANAGE_TEAM,
}

CAPABILITIES: dict[UserRole, frozenset[Capability]] = {
    UserRole.VIEWER: _VIEWER,
    UserRole.FINANCE_ADMIN: frozenset(_FINANCE),
    UserRole.SUPPORT_ADMIN: frozenset(_SUPPORT),
    UserRole.OPERATIONS_ADMIN: frozenset(_OPERATIONS),
    UserRole.OPERATOR: frozenset(_OPERATOR),
    UserRole.ADMIN: frozenset(_ADMIN),
    UserRole.OWNER: frozenset(_OWNER),
}


def can(role: UserRole, capability: Capability) -> bool:
    return capability in CAPABILITIES.get(role, frozenset())
