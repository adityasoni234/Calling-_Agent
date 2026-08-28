from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONColumn, StrEnumType


class AgentLanguage(enum.StrEnum):
    ENGLISH = "en"
    HINDI = "hi"
    HINGLISH = "hinglish"
    AUTO = "auto"


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Everything the prompt builder needs to speak as this persona.

    Stored as data rather than code so a non-engineer can change how an agent
    behaves without a deploy.
    """

    __tablename__ = "agents"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    role_title: Mapped[str] = mapped_column(String(120), default="Sales Representative")
    company_name: Mapped[str] = mapped_column(String(200), default="")
    personality: Mapped[str] = mapped_column(Text, default="Warm, concise, and respectful.")

    primary_objective: Mapped[str] = mapped_column(Text, default="")
    secondary_objectives: Mapped[list[str]] = mapped_column(JSONColumn(), default=list)

    language: Mapped[AgentLanguage] = mapped_column(
        StrEnumType(AgentLanguage, 16), default=AgentLanguage.AUTO
    )
    greeting: Mapped[str] = mapped_column(Text, default="")
    system_instructions: Mapped[str] = mapped_column(Text, default="")

    # Lists of plain strings.
    forbidden_rules: Mapped[list[str]] = mapped_column(JSONColumn(), default=list)
    qualification_questions: Mapped[list[str]] = mapped_column(JSONColumn(), default=list)
    ending_rules: Mapped[list[str]] = mapped_column(JSONColumn(), default=list)
    # [{"objection": "...", "response": "..."}]
    objection_handling: Mapped[list[dict[str, str]]] = mapped_column(JSONColumn(), default=list)
    # {"enabled": bool, "phone_number": str, "conditions": [str]}
    transfer_rules: Mapped[dict[str, Any]] = mapped_column(JSONColumn(), default=dict)
    # {"provider": "cartesia", "voice_id": "...", "speed": 1.0, "language": "hi"}
    voice_config: Mapped[dict[str, Any]] = mapped_column(JSONColumn(), default=dict)

    llm_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.6)
    max_call_seconds: Mapped[int] = mapped_column(Integer, default=420)
    silence_prompt_ms: Mapped[int] = mapped_column(Integer, default=6000)
    silence_hangup_ms: Mapped[int] = mapped_column(Integer, default=12000)
    interruptible: Mapped[bool] = mapped_column(Boolean, default=True)

    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
