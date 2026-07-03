"""add manager Telegram-bot session tracking columns

The bot now has a "session" concept (see bot/handlers.py: /start, /switch_project,
/finish) — which project a manager is actively uploading calls for. It previously
lived only in the bot's in-memory FSM storage, invisible to the admin panel. These
columns persist it so the panel can show "session active / no session" per manager.

session_started_at NULL means "no active session" — session_project_id may be
stale in that case and must not be trusted on its own.

Revision ID: 0004_manager_session
Revises: 0003_fix_calls_index
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_manager_session"
down_revision: Union[str, None] = "0003_fix_calls_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("session_project_id", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "users_session_project_id_fkey",
        "users", "projects",
        ["session_project_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("users_session_project_id_fkey", "users", type_="foreignkey")
    op.drop_column("users", "session_started_at")
    op.drop_column("users", "session_project_id")
