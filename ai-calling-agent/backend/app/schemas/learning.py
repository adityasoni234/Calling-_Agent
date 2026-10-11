"""Schemas for the learning engine."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    kind: str
    slot: str | None
    content: str
    status: str
    is_baseline: bool
    trials: int
    successes: float
    rationale: str | None
    retired_reason: str | None
    last_used_at: datetime | None
    created_at: datetime
    #: Laplace-smoothed posterior mean, so a 1-for-1 arm does not read as 100%.
    mean_reward: float


class VariantDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: approve puts it in the rotation; reject retires it unused.
    decision: str = Field(pattern="^(approve|reject)$")


class LearningSummary(BaseModel):
    """What the engine has learned for one agent."""

    agent_id: uuid.UUID
    agent_name: str
    active_variants: int
    candidates: int
    retired: int
    scored_calls: int
    #: Mean reward over scored calls, or None before anything has been scored.
    average_reward: float | None
    best: VariantRead | None
    baseline: VariantRead | None
