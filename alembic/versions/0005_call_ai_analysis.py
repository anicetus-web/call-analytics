"""add per-call qualitative AI analysis (Claude)

Beyond the 0/0.5/1 per-criterion scores, each call gets a qualitative
Claude analysis: which client pains surfaced, whether the manager drew them
out and how they were handled, product-coverage, concrete weak spots to
strengthen, and a short recommendation. Stored as JSONB so the shape can
evolve without a migration per field.

Revision ID: 0005_call_ai_analysis
Revises: 0004_manager_session
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_call_ai_analysis"
down_revision: Union[str, None] = "0004_manager_session"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("ai_analysis", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("calls", "ai_analysis")
