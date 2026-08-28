from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentLanguage


class ObjectionPair(BaseModel):
    objection: str = Field(min_length=1, max_length=300)
    response: str = Field(min_length=1, max_length=1000)


class TransferRules(BaseModel):
    enabled: bool = False
    phone_number: str = Field(default="", max_length=32)
    conditions: list[str] = Field(default_factory=list)


class VoiceConfig(BaseModel):
    provider: str | None = Field(default=None, max_length=32)
    voice_id: str = Field(default="", max_length=120)
    model: str = Field(default="", max_length=120)
    language: str = Field(default="en", max_length=16)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role_title: str = Field(default="Sales Representative", max_length=120)
    company_name: str = Field(default="", max_length=200)
    personality: str = Field(default="Warm, concise, and respectful.", max_length=2000)
    primary_objective: str = Field(default="", max_length=2000)
    secondary_objectives: list[str] = Field(default_factory=list)
    language: AgentLanguage = AgentLanguage.AUTO
    greeting: str = Field(default="", max_length=1000)
    system_instructions: str = Field(default="", max_length=8000)
    forbidden_rules: list[str] = Field(default_factory=list)
    qualification_questions: list[str] = Field(default_factory=list)
    ending_rules: list[str] = Field(default_factory=list)
    objection_handling: list[ObjectionPair] = Field(default_factory=list)
    transfer_rules: TransferRules = Field(default_factory=TransferRules)
    voice_config: VoiceConfig = Field(default_factory=VoiceConfig)
    llm_model: str | None = Field(default=None, max_length=120)
    temperature: float = Field(default=0.6, ge=0.0, le=1.5)
    max_call_seconds: int = Field(default=420, ge=30, le=3600)
    silence_prompt_ms: int = Field(default=6000, ge=1500, le=30000)
    silence_hangup_ms: int = Field(default=12000, ge=3000, le=60000)
    interruptible: bool = True
    knowledge_base_id: uuid.UUID | None = None
    is_active: bool = True


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    role_title: str | None = None
    company_name: str | None = None
    personality: str | None = None
    primary_objective: str | None = None
    secondary_objectives: list[str] | None = None
    language: AgentLanguage | None = None
    greeting: str | None = None
    system_instructions: str | None = None
    forbidden_rules: list[str] | None = None
    qualification_questions: list[str] | None = None
    ending_rules: list[str] | None = None
    objection_handling: list[ObjectionPair] | None = None
    transfer_rules: TransferRules | None = None
    voice_config: VoiceConfig | None = None
    llm_model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=1.5)
    max_call_seconds: int | None = Field(default=None, ge=30, le=3600)
    silence_prompt_ms: int | None = Field(default=None, ge=1500, le=30000)
    silence_hangup_ms: int | None = Field(default=None, ge=3000, le=60000)
    interruptible: bool | None = None
    knowledge_base_id: uuid.UUID | None = None
    is_active: bool | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    role_title: str
    company_name: str
    personality: str
    primary_objective: str
    secondary_objectives: list[str]
    language: AgentLanguage
    greeting: str
    system_instructions: str
    forbidden_rules: list[str]
    qualification_questions: list[str]
    ending_rules: list[str]
    objection_handling: list[dict[str, Any]]
    transfer_rules: dict[str, Any]
    voice_config: dict[str, Any]
    llm_model: str | None
    temperature: float
    max_call_seconds: int
    silence_prompt_ms: int
    silence_hangup_ms: int
    interruptible: bool
    knowledge_base_id: uuid.UUID | None
    is_active: bool
    created_at: datetime


class PromptPreview(BaseModel):
    system_prompt: str
    greeting: str
    estimated_tokens: int
