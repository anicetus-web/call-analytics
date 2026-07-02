"""backfill original_file_path from legacy file_path

For systems that ran an earlier version where `calls.file_path` held the original
upload until conversion, this migration:

  1. Adds `original_file_path` (already in baseline for fresh installs;
     guarded by IF NOT EXISTS so it is idempotent).
  2. Copies values into `original_file_path` only for rows where conversion has
     NOT yet completed (status in ('uploaded','converting')), because in those
     rows `file_path` still points at the source upload.
  3. For rows past conversion (transcribing/analyzing/done), the original key
     followed the convention "<S3_KEY_PREFIX>/<call_id>/original.<ext>" — but
     the extension was lost the moment the row's file_path was overwritten with
     the WAV. We back-fill those with NULL and log a warning: the original
     recording is recoverable only by enumerating S3 objects under the prefix.

Run this AFTER 0001_baseline on existing databases. On fresh installs it is a no-op.

Revision ID: 0002_backfill_original_file_path
Revises: 0001_baseline
"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

log = logging.getLogger("alembic.runtime.migration")


revision: str = "0002_backfill_original_file_path"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Idempotent column add: harmless on fresh installs where baseline already created it.
    conn.execute(sa.text(
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS original_file_path VARCHAR(500)"
    ))

    # Back-fill: pre-conversion rows had file_path pointing at the original upload.
    conn.execute(sa.text("""
        UPDATE calls
        SET original_file_path = file_path
        WHERE original_file_path IS NULL
          AND file_path IS NOT NULL
          AND status IN ('uploaded', 'converting')
    """))

    # Surface how many rows could NOT be back-filled so an operator notices.
    result = conn.execute(sa.text("""
        SELECT COUNT(*) FROM calls
        WHERE original_file_path IS NULL
          AND status IN ('transcribing', 'analyzing', 'done', 'error')
    """))
    orphaned = result.scalar() or 0
    if orphaned:
        log.warning(
            "[migration 0002] %d call(s) have status past conversion "
            "but no original_file_path. Their source S3 keys are unknown to the DB; "
            "if you need to recover them, list S3 objects under <S3_KEY_PREFIX>/<call_id>/.",
            orphaned,
        )


def downgrade() -> None:
    # Reversal: clear the back-filled column without dropping it
    # (dropping is handled by 0001_baseline.downgrade).
    op.execute(sa.text("UPDATE calls SET original_file_path = NULL"))
