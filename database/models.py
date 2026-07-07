from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional, Any
from sqlalchemy import (
    Integer, BigInteger, SmallInteger, String, Text, Numeric, Boolean,
    DateTime, ForeignKey, UniqueConstraint, Index, CheckConstraint,
    func, Enum as SAEnum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from database.base import Base


class UserRole(str, PyEnum):
    ADMIN = "admin"
    MANAGER = "manager"


class CallStatus(str, PyEnum):
    UPLOADED = "uploaded"
    CONVERTING = "converting"      # FFmpeg conversion in progress
    TRANSCRIBING = "transcribing"  # Whisper API in progress
    ANALYZING = "analyzing"        # LLM analysis in progress
    DONE = "done"
    ERROR = "error"


class MetricGroupType(str, PyEnum):
    REQUIRED_KEYWORDS = "required_keywords"
    FORBIDDEN_KEYWORDS = "forbidden_keywords"
    SCRIPT_STAGES = "script_stages"


class User(Base):
    __tablename__ = "users"
    __repr_fields__ = ("id", "name", "role")
    __table_args__ = (
        # Admin must authenticate via password; manager via Telegram ID.
        # Having both fields on one user is allowed (e.g. manager promoted to admin).
        CheckConstraint(
            "(role = 'admin' AND password_hash IS NOT NULL) OR "
            "(role = 'manager' AND telegram_id IS NOT NULL)",
            name="ck_user_credentials",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # login is used for admin web UI authentication; NULL for managers (they use Telegram)
    login: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Telegram bot "session" (see bot/handlers.py): set when a manager runs
    # /start (or picks a project via /switch_project), cleared on /finish.
    # Both are NULL together or set together — session_started_at NULL means
    # "no active session", regardless of session_project_id's stale value.
    # ondelete="SET NULL": if the project is later archived/deleted, don't
    # block that on a manager's leftover session pointer.
    session_project_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL")
    )
    session_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    project_members: Mapped[list["ProjectMember"]] = relationship(back_populates="user")
    calls: Mapped[list["Call"]] = relationship(back_populates="user")
    created_projects: Mapped[list["Project"]] = relationship(
        back_populates="creator", foreign_keys="[Project.created_by]"
    )


class Project(Base):
    __tablename__ = "projects"
    __repr_fields__ = ("id", "name", "is_active")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Projects cannot be hard-deleted while calls exist (RESTRICT on Call.project_id FK).
    # Set is_active=False to archive a project instead of deleting it.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    creator: Mapped["User"] = relationship(back_populates="created_projects", foreign_keys=[created_by])
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project")
    metric_groups: Mapped[list["MetricGroup"]] = relationship(back_populates="project")
    calls: Mapped[list["Call"]] = relationship(back_populates="project")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __repr_fields__ = ("id", "project_id", "user_id")
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # CASCADE safety net: in practice projects use soft-delete (is_active),
    # but if a project is ever hard-deleted this prevents orphaned membership rows.
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))

    project: Mapped["Project"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="project_members")


class MetricGroup(Base):
    __tablename__ = "metric_groups"
    __repr_fields__ = ("id", "name", "group_type")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # CASCADE safety net — same reasoning as ProjectMember.project_id.
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Named group_type to avoid shadowing Python builtin 'type'
    group_type: Mapped[MetricGroupType] = mapped_column(
        SAEnum(MetricGroupType, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Server-side: a Postgres trigger (trg_set_updated_at) keeps this current on
    # any UPDATE, including bulk session.execute(). onupdate is belt-and-suspenders
    # for dev environments without the trigger applied.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="metric_groups")
    items: Mapped[list["MetricItem"]] = relationship(back_populates="group", order_by="MetricItem.position")


class MetricItem(Base):
    __tablename__ = "metric_items"
    __repr_fields__ = ("id", "name", "position", "is_active")
    __table_args__ = (UniqueConstraint("metric_group_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_group_id: Mapped[int] = mapped_column(Integer, ForeignKey("metric_groups.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # Soft delete: set is_active=False instead of deleting.
    # RESTRICT on AnalysisResult.metric_item_id prevents hard deletion while results exist.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Server-side: a Postgres trigger (trg_set_updated_at) keeps this current on
    # any UPDATE, including bulk session.execute(). onupdate is belt-and-suspenders
    # for dev environments without the trigger applied.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    group: Mapped["MetricGroup"] = relationship(back_populates="items")
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(back_populates="metric_item")


class Call(Base):
    __tablename__ = "calls"
    __repr_fields__ = ("id", "status", "project_id", "user_id")
    __table_args__ = (
        # Covers the primary analytics query:
        # "all calls for project X with status done after date Y"
        # WHERE project_id = ? AND status = ? AND created_at > ?
        Index("ix_calls_project_status_date", "project_id", "status", "created_at"),
        # Covers "all calls by manager X" query
        Index("ix_calls_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # RESTRICT: a project cannot be hard-deleted while calls exist (use is_active instead).
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    # RESTRICT: a user cannot be deleted while their calls exist (audit trail preservation).
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # All paths below store the S3 object KEY only (e.g. "calls/42/audio.wav"), not the full URL.
    # Full URL = settings.S3_ENDPOINT + "/" + settings.S3_BUCKET + "/" + key
    # Key-only storage means bucket changes require no DB migration.
    #
    # original_file_path: the raw uploaded file as received (e.g. "calls/42/original.ogg").
    #   Set once at upload, NEVER overwritten — guarantees the source is never lost.
    original_file_path: Mapped[Optional[str]] = mapped_column(String(500))
    # file_path: the processed 16kHz mono audio that Whisper transcribes
    #   (audio.ogg for new calls; legacy rows may still point at audio.wav).
    #   None until FFmpeg conversion completes and the file is uploaded to S3.
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    original_filename: Mapped[Optional[str]] = mapped_column(String(500))
    # Set by FFmpeg during the CONVERTING stage.
    # SmallInteger: max 32767 sec ≈ 9 hours, sufficient for any sales call.
    duration_seconds: Mapped[Optional[int]] = mapped_column(SmallInteger)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    # WARNING: if CallStatus enum values are renamed, update this server_default manually
    # and write an Alembic migration to update the PG enum type.
    status: Mapped[CallStatus] = mapped_column(
        SAEnum(CallStatus, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
        server_default=CallStatus.UPLOADED.value,
    )
    language: Mapped[Optional[str]] = mapped_column(String(10))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    # Qualitative Claude analysis, separate from the 0/0.5/1 per-criterion scores:
    # {"pains": [...], "pains_addressed": "...", "weak_spots": [...], "summary": "..."}.
    # JSONB (not columns) so the shape can evolve without a migration per field.
    ai_analysis: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Server-side: a Postgres trigger (trg_set_updated_at) keeps this current on
    # any UPDATE, including bulk session.execute(). onupdate is belt-and-suspenders
    # for dev environments without the trigger applied.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="calls")
    user: Mapped["User"] = relationship(back_populates="calls")
    transcription: Mapped[Optional["Transcription"]] = relationship(back_populates="call", uselist=False)
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(back_populates="call")


class Transcription(Base):
    __tablename__ = "transcriptions"
    __repr_fields__ = ("id", "call_id")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # unique=True creates an implicit unique index — intentional, not coincidence.
    call_id: Mapped[int] = mapped_column(Integer, ForeignKey("calls.id", ondelete="CASCADE"), unique=True)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    # list[{"start": float, "end": float, "text": str}] — Whisper API segment format
    segments: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Re-transcription strategy: UPDATE full_text + segments in place (same row).
    # updated_at tracks when the last transcription occurred.
    # Server-side: a Postgres trigger (trg_set_updated_at) keeps this current on
    # any UPDATE, including bulk session.execute(). onupdate is belt-and-suspenders
    # for dev environments without the trigger applied.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    call: Mapped["Call"] = relationship(back_populates="transcription")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    __repr_fields__ = ("id", "call_id", "metric_item_id", "score")
    __table_args__ = (
        # UniqueConstraint works correctly because metric_item_id is NOT NULL (RESTRICT FK).
        # NULL != NULL in SQL, so nullable FKs break unique constraints — avoided by design.
        # On retry: UPDATE existing row instead of INSERT.
        UniqueConstraint("call_id", "metric_item_id"),
        CheckConstraint("score IN (0.0, 0.5, 1.0)", name="ck_score_values"),
        # Covers "average score per metric" analytics queries: WHERE metric_item_id = ?
        # (call_id, metric_item_id) from UniqueConstraint covers the reverse direction.
        Index("ix_analysis_results_metric_item_id", "metric_item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(Integer, ForeignKey("calls.id", ondelete="CASCADE"))
    # RESTRICT: metric items use soft-delete (is_active=False) to preserve historical results.
    # Hard deletion of a metric item is blocked while analysis results reference it.
    metric_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("metric_items.id", ondelete="RESTRICT"), nullable=False
    )
    # Numeric(2,1) to avoid IEEE 754 rounding — returns Decimal, not float.
    score: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False)
    # Numeric(7,3): up to 9999.999 sec ≈ 2.7 hours — sufficient for any call timecode.
    timecode_start: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 3))
    timecode_end: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 3))
    raw_response: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    call: Mapped["Call"] = relationship(back_populates="analysis_results")
    metric_item: Mapped["MetricItem"] = relationship(back_populates="analysis_results")
