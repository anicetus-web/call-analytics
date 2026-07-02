"""baseline schema

Initial migration capturing the full current schema as the starting point.
Apply with: alembic upgrade head

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums first — Postgres requires the type to exist before the column.
    user_role = postgresql.ENUM("admin", "manager", name="userrole", create_type=False)
    call_status = postgresql.ENUM(
        "uploaded", "converting", "transcribing", "analyzing", "done", "error",
        name="callstatus", create_type=False,
    )
    metric_group_type = postgresql.ENUM(
        "required_keywords", "forbidden_keywords", "script_stages",
        name="metricgrouptype", create_type=False,
    )
    user_role.create(op.get_bind(), checkfirst=True)
    call_status.create(op.get_bind(), checkfirst=True)
    metric_group_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("login", sa.String(255), unique=True),
        sa.Column("role", user_role, nullable=False),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(role = 'admin' AND password_hash IS NOT NULL) OR "
            "(role = 'manager' AND telegram_id IS NOT NULL)",
            name="ck_user_credentials",
        ),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("project_id", "user_id"),
    )

    op.create_table(
        "metric_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("group_type", metric_group_type, nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "metric_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metric_group_id", sa.Integer(), sa.ForeignKey("metric_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("metric_group_id", "position"),
    )

    op.create_table(
        "calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        # Immutable source recording. Set once at upload, never overwritten.
        sa.Column("original_file_path", sa.String(500)),
        # Processed 16kHz mono WAV. Populated after the CONVERTING stage.
        sa.Column("file_path", sa.String(500)),
        sa.Column("original_filename", sa.String(500)),
        sa.Column("duration_seconds", sa.SmallInteger()),
        sa.Column("comment", sa.Text()),
        sa.Column("status", call_status, nullable=False, server_default=sa.text("'uploaded'")),
        sa.Column("language", sa.String(10)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_calls_project_status", "calls", ["project_id", "status"])
    op.create_index("ix_calls_user_id", "calls", ["user_id"])

    op.create_table(
        "transcriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("call_id", sa.Integer(), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("segments", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "analysis_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("call_id", sa.Integer(), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_item_id", sa.Integer(), sa.ForeignKey("metric_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("score", sa.Numeric(2, 1), nullable=False),
        sa.Column("timecode_start", sa.Numeric(7, 3)),
        sa.Column("timecode_end", sa.Numeric(7, 3)),
        sa.Column("raw_response", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("call_id", "metric_item_id"),
        sa.CheckConstraint("score IN (0.0, 0.5, 1.0)", name="ck_score_values"),
    )
    op.create_index("ix_analysis_results_metric_item_id", "analysis_results", ["metric_item_id"])

    # Trigger to keep calls.updated_at honest for raw UPDATE queries
    # (ORM onupdate doesn't fire on session.execute(update(...))).
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in ("calls", "metric_groups", "metric_items", "transcriptions"):
        op.execute(f"""
            CREATE TRIGGER set_updated_at_{table}
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
        """)


def downgrade() -> None:
    for table in ("calls", "metric_groups", "metric_items", "transcriptions"):
        op.execute(f"DROP TRIGGER IF EXISTS set_updated_at_{table} ON {table};")
    op.execute("DROP FUNCTION IF EXISTS trg_set_updated_at();")

    op.drop_index("ix_analysis_results_metric_item_id", table_name="analysis_results")
    op.drop_table("analysis_results")
    op.drop_table("transcriptions")
    op.drop_index("ix_calls_user_id", table_name="calls")
    op.drop_index("ix_calls_project_status", table_name="calls")
    op.drop_table("calls")
    op.drop_table("metric_items")
    op.drop_table("metric_groups")
    op.drop_table("project_members")
    op.drop_table("projects")
    op.drop_table("users")
    for name in ("metricgrouptype", "callstatus", "userrole"):
        op.execute(f"DROP TYPE IF EXISTS {name};")
