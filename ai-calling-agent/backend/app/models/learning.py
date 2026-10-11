"""The learning engine's data: what the agent tried, and what it got back.

This is a contextual multi-armed bandit, not gradient-based RL. Claude has no
fine-tuning API, so nothing here updates model weights -- and a system that
claimed to would be lying. What it does do is genuine reinforcement learning
for this problem shape: a set of actions (what the agent says), a reward
(whether the lead qualified), and a policy that balances trying new phrasings
against using the ones already shown to work.

The unit of learning is a *variant*: one alternative phrasing of one thing the
agent says. Variants compete; the ones that produce better calls get used more.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import StrEnumType


class VariantKind(enum.StrEnum):
    """Which part of the agent's speech a variant replaces."""

    GREETING = "greeting"
    OBJECTION = "objection"
    #: An extra line appended to "How to talk" -- a style or pacing instruction.
    STYLE_RULE = "style_rule"


class VariantStatus(enum.StrEnum):
    #: Proposed by the engine, not yet approved. Never used on a live call.
    CANDIDATE = "candidate"
    #: In the rotation, competing for traffic.
    ACTIVE = "active"
    #: Lost decisively, or withdrawn by a human. Kept for the record.
    RETIRED = "retired"


class AgentVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One arm of the bandit.

    `trials` and `successes` are the Beta posterior this arm is sampled from.
    They are counts, not a score, because the policy needs to know the
    difference between "0.8 from four calls" and "0.8 from four hundred".
    """

    __tablename__ = "agent_variants"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[VariantKind] = mapped_column(StrEnumType(VariantKind, 16), index=True)
    #: For an objection variant, which objection it answers. Null otherwise, so
    #: greetings compete with greetings and not with everything at once.
    slot: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[VariantStatus] = mapped_column(
        StrEnumType(VariantStatus, 16), default=VariantStatus.CANDIDATE, index=True
    )
    #: True for the agent's own configured wording, which is the control arm.
    is_baseline: Mapped[bool] = mapped_column(default=False)

    trials: Mapped[int] = mapped_column(Integer, default=0)
    successes: Mapped[float] = mapped_column(Float, default=0.0)
    #: Why the engine proposed this, in one line, for the human approving it.
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    retired_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def mean_reward(self) -> float:
        """Posterior mean, Laplace-smoothed so a 1-for-1 arm is not 100%."""
        return (self.successes + 1.0) / (self.trials + 2.0)


class VariantTrial(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One call's use of one variant, and what it earned.

    Written when the variant is chosen and scored when the call is analysed, so
    a call that never completes still shows as a trial with no reward rather
    than silently vanishing from the denominator.
    """

    __tablename__ = "variant_trials"
    __table_args__ = (UniqueConstraint("call_id", "variant_id", name="uq_variant_trials_call"),)

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_variants.id", ondelete="CASCADE"), index=True
    )
    #: Null until the call is analysed.
    reward: Mapped[float | None] = mapped_column(Float, nullable=True)
