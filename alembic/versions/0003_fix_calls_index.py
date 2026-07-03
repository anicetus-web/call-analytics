"""fix calls project/status/date index to match the ORM model

The baseline migration created ix_calls_project_status as (project_id, status)
only, but database/models.py declares ix_calls_project_status_date as
(project_id, status, created_at) — the third column is what makes the index
actually cover the main analytics/listing query pattern ("calls for project X
with status Y ordered/filtered by created_at"). This drift meant
`alembic revision --autogenerate` would immediately flag an out-of-sync model,
and the intended index optimization silently did not exist in the deployed
schema.

Revision ID: 0003_fix_calls_index
Revises: 0002_backfill_original_file_path
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_fix_calls_index"
down_revision: Union[str, None] = "0002_backfill_original_file_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_calls_project_status", table_name="calls")
    op.create_index(
        "ix_calls_project_status_date",
        "calls",
        ["project_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_calls_project_status_date", table_name="calls")
    op.create_index("ix_calls_project_status", "calls", ["project_id", "status"])
