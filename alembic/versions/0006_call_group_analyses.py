"""per-metric-group qualitative AI analysis

Replaces the single calls.ai_analysis JSONB blob (0005) — one qualitative
read for the whole call, blending every metric group together — with a
dedicated call_group_analyses table: one row per (call, metric_group), so
"pains found" / "weak spots" etc. are read in that specific group's own
terms (a sales checklist and a forbidden-words group need very different
qualitative commentary).

Revision ID: 0006_call_group_analyses
Revises: 0005_call_ai_analysis
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_call_group_analyses"
down_revision: Union[str, None] = "0005_call_ai_analysis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("calls", "ai_analysis")

    op.create_table(
        "call_group_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("call_id", sa.Integer(), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_group_id", sa.Integer(), sa.ForeignKey("metric_groups.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pains_found", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("pains_addressed", sa.Text(), nullable=False, server_default=""),
        sa.Column("weak_spots", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("call_id", "metric_group_id", name="uq_call_group_analyses_call_group"),
    )
    op.create_index(
        "ix_call_group_analyses_metric_group_id", "call_group_analyses", ["metric_group_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_call_group_analyses_metric_group_id", table_name="call_group_analyses")
    op.drop_table("call_group_analyses")
    op.add_column("calls", sa.Column("ai_analysis", postgresql.JSONB(), nullable=True))
