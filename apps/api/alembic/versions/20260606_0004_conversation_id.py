"""Add conversation_id to workflows for multi-turn grouping.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_workflows_conversation_id", "workflows", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_workflows_conversation_id", table_name="workflows")
    op.drop_column("workflows", "conversation_id")
