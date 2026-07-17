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


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
