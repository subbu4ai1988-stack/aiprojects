"""Add candidate privacy lifecycle and audit records.

Revision ID: 0002
Revises: 0001
"""
from datetime import datetime, timedelta
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_privacy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consent_status", sa.String(30), nullable=False, server_default="granted"),
        sa.Column("legal_basis", sa.String(60), nullable=False, server_default="recruitment"),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_at", sa.DateTime(), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("candidate_id"),
    )
    op.create_index("ix_candidate_privacy_candidate_id", "candidate_privacy", ["candidate_id"])
    op.create_index("ix_candidate_privacy_retention_expires_at", "candidate_privacy", ["retention_expires_at"])
    op.create_table(
        "privacy_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_email", sa.String(255), nullable=False, server_default="system"),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("subject_ref", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_privacy_audit_logs_action", "privacy_audit_logs", ["action"])
    op.create_index("ix_privacy_audit_logs_subject_ref", "privacy_audit_logs", ["subject_ref"])
    now = datetime.utcnow()
    expires = now + timedelta(days=365)
    candidate_privacy = sa.table(
        "candidate_privacy",
        sa.column("candidate_id", sa.Integer),
        sa.column("consent_status", sa.String),
        sa.column("legal_basis", sa.String),
        sa.column("legal_hold", sa.Boolean),
        sa.column("consent_at", sa.DateTime),
        sa.column("retention_expires_at", sa.DateTime),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    candidate_ids = [row[0] for row in op.get_bind().execute(sa.text("SELECT id FROM candidates"))]
    if candidate_ids:
        op.bulk_insert(candidate_privacy, [
            {
                "candidate_id": candidate_id,
                "consent_status": "granted",
                "legal_basis": "recruitment",
                "legal_hold": False,
                "consent_at": now,
                "retention_expires_at": expires,
                "created_at": now,
                "updated_at": now,
            }
            for candidate_id in candidate_ids
        ])


def downgrade() -> None:
    op.drop_index("ix_privacy_audit_logs_subject_ref", table_name="privacy_audit_logs")
    op.drop_index("ix_privacy_audit_logs_action", table_name="privacy_audit_logs")
    op.drop_table("privacy_audit_logs")
    op.drop_index("ix_candidate_privacy_retention_expires_at", table_name="candidate_privacy")
    op.drop_index("ix_candidate_privacy_candidate_id", table_name="candidate_privacy")
    op.drop_table("candidate_privacy")
