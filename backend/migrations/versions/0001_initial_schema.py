"""Create the RecruitAI production schema.

Revision ID: 0001
Revises:
"""
from typing import Sequence

from alembic import op

from backend.app import admin_models, models  # noqa: F401
from backend.app.database import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PHASE_6_TABLES = (
    "users",
    "jobs",
    "candidates",
    "applications",
    "interviews",
    "feedback",
    "job_postings",
    "email_deliveries",
    "ai_request_logs",
    "ai_tasks",
    "job_assignments",
)


def phase_6_tables():
    return [Base.metadata.tables[name] for name in PHASE_6_TABLES]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=phase_6_tables())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=phase_6_tables())
