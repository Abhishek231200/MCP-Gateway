"""Initial schema: mcp_servers, server_capabilities, workflows, workflow_steps, audit_logs.

Revision ID: 0001
Revises:
Create Date: 2025-04-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Enum types ─────────────────────────────────────────────────────────────
    auth_type = postgresql.ENUM(
        "none", "api_key", "oauth2", "jwt", name="authtype", create_type=False
    )
    health_status = postgresql.ENUM(
        "healthy", "degraded", "unhealthy", "unknown", name="healthstatus", create_type=False
    )
    workflow_status = postgresql.ENUM(
        "pending", "planning", "running", "awaiting_approval",
        "completed", "failed", "cancelled",
        name="workflowstatus", create_type=False,
    )
    step_status = postgresql.ENUM(
        "pending", "running", "completed", "failed", "skipped",
        name="stepstatus", create_type=False,
    )
    audit_action = postgresql.ENUM(
        "tool_call", "tool_blocked", "rate_limited", "injection_detected",
        "workflow_started", "workflow_completed", "workflow_failed",
        "server_registered", "server_deregistered",
        name="auditaction", create_type=False,
    )

    for enum_type in [auth_type, health_status, workflow_status, step_status, audit_action]:
        enum_type.create(op.get_bind(), checkfirst=True)

    # ── mcp_servers ────────────────────────────────────────────────────────────
    op.create_table(
        "mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("auth_type", sa.Enum("none", "api_key", "oauth2", "jwt", name="authtype"), nullable=False),
        sa.Column("auth_config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "health_status",
            sa.Enum("healthy", "degraded", "unhealthy", "unknown", name="healthstatus"),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_mcp_servers_name", "mcp_servers", ["name"], unique=True)
    op.create_index("ix_mcp_servers_health_status", "mcp_servers", ["health_status"])
    op.create_index("ix_mcp_servers_is_active", "mcp_servers", ["is_active"])

    # ── server_capabilities ────────────────────────────────────────────────────
    op.create_table(
        "server_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("input_schema", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("output_schema", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("required_permission", sa.String(32), nullable=False, server_default="read"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("avg_latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_server_capabilities_server_id", "server_capabilities", ["server_id"])
    op.create_index("ix_server_capabilities_tool_name", "server_capabilities", ["tool_name"])
    op.create_index("ix_server_capabilities_required_permission", "server_capabilities", ["required_permission"])

    # ── workflows ──────────────────────────────────────────────────────────────
    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task", sa.Text, nullable=False),
        sa.Column("initiated_by", sa.String(256), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "planning", "running", "awaiting_approval",
                "completed", "failed", "cancelled",
                name="workflowstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("plan", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("total_tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflows_status", "workflows", ["status"])
    op.create_index("ix_workflows_initiated_by", "workflows", ["initiated_by"])
    op.create_index("ix_workflows_created_at", "workflows", ["created_at"])

    # ── workflow_steps ─────────────────────────────────────────────────────────
    op.create_table(
        "workflow_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("agent_role", sa.String(64), nullable=False),
        sa.Column("server_name", sa.String(128), nullable=True),
        sa.Column("tool_name", sa.String(256), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", "skipped", name="stepstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("input_payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("output_payload", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_steps_workflow_id", "workflow_steps", ["workflow_id"])
    op.create_index("ix_workflow_steps_status", "workflow_steps", ["status"])

    # ── audit_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "action",
            sa.Enum(
                "tool_call", "tool_blocked", "rate_limited", "injection_detected",
                "workflow_started", "workflow_completed", "workflow_failed",
                "server_registered", "server_deregistered",
                name="auditaction",
            ),
            nullable=False,
        ),
        sa.Column("actor", sa.String(256), nullable=False),
        sa.Column("server_name", sa.String(128), nullable=True),
        sa.Column("tool_name", sa.String(256), nullable=True),
        sa.Column("request_payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("response_payload", postgresql.JSONB, nullable=True),
        sa.Column("allowed", sa.Boolean, nullable=True),
        sa.Column("policy_decision", postgresql.JSONB, nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_audit_logs_workflow_id", "audit_logs", ["workflow_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"])
    op.create_index("ix_audit_logs_server_name", "audit_logs", ["server_name"])
    op.create_index("ix_audit_logs_tool_name", "audit_logs", ["tool_name"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # ── updated_at trigger ─────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    for table in ("mcp_servers", "workflows"):
        op.execute(f"""
            CREATE TRIGGER trigger_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    for table in ("workflows", "mcp_servers"):
        op.execute(f"DROP TRIGGER IF EXISTS trigger_{table}_updated_at ON {table};")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")

    op.drop_table("audit_logs")
    op.drop_table("workflow_steps")
    op.drop_table("workflows")
    op.drop_table("server_capabilities")
    op.drop_table("mcp_servers")

    for enum_name in ["authtype", "healthstatus", "workflowstatus", "stepstatus", "auditaction"]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name};")
