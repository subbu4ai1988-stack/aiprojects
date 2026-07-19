"""Phase 8 storage and delivery integration telemetry.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    email_columns = {column["name"] for column in inspector.get_columns("email_deliveries")}
    if "attempts" not in email_columns:
        op.add_column("email_deliveries", sa.Column("attempts", sa.Integer(), server_default="1", nullable=False))
    if "error" not in email_columns:
        op.add_column("email_deliveries", sa.Column("error", sa.String(length=500), server_default="", nullable=False))

    if "integration_events" not in inspector.get_table_names():
        op.create_table(
            "integration_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("integration", sa.String(length=40), nullable=False),
            sa.Column("operation", sa.String(length=80), nullable=False),
            sa.Column("provider", sa.String(length=60), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("reference", sa.String(length=500), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("error", sa.String(length=500), nullable=False),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_integration_events_integration", "integration_events", ["integration"])
        op.create_index("ix_integration_events_operation", "integration_events", ["operation"])
        op.create_index("ix_integration_events_status", "integration_events", ["status"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "integration_events" in inspector.get_table_names():
        op.drop_index("ix_integration_events_status", table_name="integration_events")
        op.drop_index("ix_integration_events_operation", table_name="integration_events")
        op.drop_index("ix_integration_events_integration", table_name="integration_events")
        op.drop_table("integration_events")
    email_columns = {column["name"] for column in inspector.get_columns("email_deliveries")}
    if "error" in email_columns:
        op.drop_column("email_deliveries", "error")
    if "attempts" in email_columns:
        op.drop_column("email_deliveries", "attempts")