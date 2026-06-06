"""Add users table and seed initial users.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-06
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="engineer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.execute("""
        INSERT INTO users (id, name, email, role) VALUES
        (gen_random_uuid(), 'Abhishek Chavan', 'abhischavan18@gmail.com', 'admin'),
        (gen_random_uuid(), 'Arsh Advani',     'arshadvani3@gmail.com',   'engineer'),
        (gen_random_uuid(), 'Shubham Sharma',  'shubhamsharma33@gmail.com','engineer')
        ON CONFLICT (email) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
