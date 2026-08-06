from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from wildfireops.persistence.base import Base
from wildfireops.persistence.decision_models import IdempotencyKeyModel  # noqa: F401


class ExerciseSessionModel(Base):
    __tablename__ = "exercise_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'expired')",
            name="ck_exercise_sessions_status",
        ),
        CheckConstraint("version >= 1", name="ck_exercise_sessions_version"),
        CheckConstraint(
            "checkpoint_index BETWEEN 0 AND 2",
            name="ck_exercise_sessions_checkpoint",
        ),
        Index("ix_exercise_sessions_expiry", "status", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    exercise_id: Mapped[str] = mapped_column(String(255), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(255), nullable=False)
    definition_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    callsign: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    checkpoint_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    objective: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        server_default=text("'active'"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    consequences: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ExercisePlanRunModel(Base):
    __tablename__ = "exercise_plan_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key_id", name="uq_exercise_plan_idempotency"),
        Index(
            "ix_exercise_plan_runs_session_checkpoint",
            "session_id",
            "checkpoint_key",
            "insertion_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    insertion_order: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("exercise_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    checkpoint_key: Mapped[str] = mapped_column(String(80), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    output_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    versions: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    idempotency_key_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("idempotency_keys.id", ondelete="RESTRICT"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExerciseEventModel(Base):
    __tablename__ = "exercise_events"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "resulting_session_version",
            name="uq_exercise_event_session_version",
        ),
        Index("ix_exercise_events_session_time", "session_id", "occurred_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("exercise_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_callsign: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    expected_session_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_session_version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_state: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    after_state: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    inputs: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
