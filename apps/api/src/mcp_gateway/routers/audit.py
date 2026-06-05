"""Audit logs router — query, stats, CSV export, and chain verification."""

import csv
import io
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_gateway.database import get_db
from mcp_gateway.models.audit import AuditAction, AuditLog
from mcp_gateway.schemas.audit import AuditLogListResponse, AuditLogResponse, AuditStatsResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/audit-logs", tags=["audit"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_filters(
    stmt: any,
    actor: str | None,
    server: str | None,
    tool: str | None,
    action: str | None,
    allowed: bool | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
) -> any:
    if actor:
        stmt = stmt.where(AuditLog.actor.ilike(f"%{actor}%"))
    if server:
        stmt = stmt.where(AuditLog.server_name.ilike(f"%{server}%"))
    if tool:
        stmt = stmt.where(AuditLog.tool_name.ilike(f"%{tool}%"))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if allowed is not None:
        stmt = stmt.where(AuditLog.allowed == allowed)
    if from_ts:
        stmt = stmt.where(AuditLog.created_at >= from_ts)
    if to_ts:
        stmt = stmt.where(AuditLog.created_at <= to_ts)
    return stmt


def _verify_chain(rows: list) -> bool:
    """Verify hash chain integrity for a time-ordered sequence of entries."""
    prev = None
    for row in rows:
        if row.entry_hash is None or row.prev_hash is None:
            prev = row
            continue
        if prev is not None and prev.entry_hash is not None:
            if row.prev_hash != prev.entry_hash:
                return False
        prev = row
    return True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    actor: str | None = None,
    server: str | None = None,
    tool: str | None = None,
    action: str | None = None,
    allowed: bool | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    base = select(AuditLog)
    base = _apply_filters(base, actor, server, tool, action, allowed, from_ts, to_ts)

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    result = await db.execute(
        base.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    )
    items = list(result.scalars().all())

    return AuditLogListResponse(
        total=total,
        items=[AuditLogResponse.model_validate(item) for item in items],
    )


@router.get("/stats", response_model=AuditStatsResponse)
async def get_audit_stats(db: AsyncSession = Depends(get_db)) -> AuditStatsResponse:
    yesterday = datetime.now(UTC) - timedelta(hours=24)

    total = (await db.execute(select(func.count(AuditLog.id)))).scalar_one()

    blocked_today = (
        await db.execute(
            select(func.count(AuditLog.id))
            .where(AuditLog.allowed == False)  # noqa: E712
            .where(AuditLog.created_at >= yesterday)
        )
    ).scalar_one()

    tool_calls_today = (
        await db.execute(
            select(func.count(AuditLog.id))
            .where(AuditLog.action == AuditAction.TOOL_CALL)
            .where(AuditLog.created_at >= yesterday)
        )
    ).scalar_one()

    last_hash = (
        await db.execute(
            select(AuditLog.entry_hash).order_by(AuditLog.created_at.desc()).limit(1)
        )
    ).scalar()

    # Verify last 200 entries for chain integrity
    chain_rows = (
        await db.execute(
            select(AuditLog.id, AuditLog.entry_hash, AuditLog.prev_hash, AuditLog.created_at)
            .order_by(AuditLog.created_at.asc())
            .limit(200)
        )
    ).all()

    return AuditStatsResponse(
        total=total,
        blocked_today=blocked_today,
        tool_calls_today=tool_calls_today,
        chain_valid=_verify_chain(chain_rows),
        last_entry_hash=last_hash,
    )


@router.get("/export")
async def export_audit_logs(
    actor: str | None = None,
    server: str | None = None,
    tool: str | None = None,
    action: str | None = None,
    allowed: bool | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    base = select(AuditLog)
    base = _apply_filters(base, actor, server, tool, action, allowed, from_ts, to_ts)

    result = await db.execute(
        base.order_by(AuditLog.created_at.desc()).limit(5_000)
    )
    items = list(result.scalars().all())

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id", "created_at", "actor", "action", "server_name", "tool_name",
            "allowed", "latency_ms", "workflow_id", "policy_decision", "entry_hash",
        ],
    )
    writer.writeheader()
    for item in items:
        writer.writerow({
            "id": str(item.id),
            "created_at": item.created_at.isoformat() if item.created_at else "",
            "actor": item.actor,
            "action": item.action,
            "server_name": item.server_name or "",
            "tool_name": item.tool_name or "",
            "allowed": item.allowed,
            "latency_ms": item.latency_ms or 0,
            "workflow_id": str(item.workflow_id) if item.workflow_id else "",
            "policy_decision": str(item.policy_decision or ""),
            "entry_hash": item.entry_hash or "",
        })

    output.seek(0)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_log_{timestamp}.csv"
        },
    )
