"""Workflows router — create, list, detail, and WebSocket event streaming."""

import asyncio
import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mcp_gateway.config import settings
from mcp_gateway.database import AsyncSessionLocal, get_db
from mcp_gateway.models.workflow import Workflow, WorkflowStatus
from mcp_gateway.schemas.workflows import (
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowResponse,
)
from mcp_gateway.services.orchestrator import WorkflowOrchestrator, register_approval_decision

logger = structlog.get_logger()

router = APIRouter(prefix="/workflows", tags=["workflows"])


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Create a workflow record and kick off async execution.

    Returns immediately with status=pending; use the WebSocket stream endpoint
    to receive live progress events.
    """
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="No LLM API key configured (set OPENAI_API_KEY)")

    workflow = Workflow(
        task=payload.task,
        initiated_by=payload.actor,
        status=WorkflowStatus.PENDING,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow, ["steps"])

    # Commit before scheduling background task so the task's own session can
    # find the record immediately.
    await db.commit()

    asyncio.create_task(
        _run_workflow_background(str(workflow.id), payload.task, payload.actor)
    )

    logger.info("workflows.created", workflow_id=str(workflow.id), actor=payload.actor)
    return WorkflowResponse.model_validate(workflow)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> WorkflowListResponse:
    total_result = await db.execute(select(func.count()).select_from(Workflow))
    total: int = total_result.scalar_one()

    stmt = (
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .order_by(Workflow.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    workflows = list(result.scalars().all())

    return WorkflowListResponse(
        total=total,
        items=[WorkflowResponse.model_validate(w) for w in workflows],
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    result = await db.execute(
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(selectinload(Workflow.steps))
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowResponse.model_validate(workflow)


# ── Human-in-the-loop checkpoint ─────────────────────────────────────────────

@router.post("/{workflow_id}/approve", status_code=200)
async def approve_checkpoint(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Approve a paused workflow checkpoint — resumes execution of the pending step."""
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.status != WorkflowStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow is not awaiting approval (current status: {workflow.status})",
        )
    if not register_approval_decision(str(workflow_id), approved=True):
        raise HTTPException(status_code=409, detail="No pending checkpoint found for this workflow")
    logger.info("workflows.checkpoint_approved", workflow_id=str(workflow_id))
    return {"workflow_id": str(workflow_id), "decision": "approved"}


@router.post("/{workflow_id}/reject", status_code=200)
async def reject_checkpoint(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Reject a paused workflow checkpoint — the pending step is skipped as failed."""
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.status != WorkflowStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow is not awaiting approval (current status: {workflow.status})",
        )
    if not register_approval_decision(str(workflow_id), approved=False):
        raise HTTPException(status_code=409, detail="No pending checkpoint found for this workflow")
    logger.info("workflows.checkpoint_rejected", workflow_id=str(workflow_id))
    return {"workflow_id": str(workflow_id), "decision": "rejected"}


# ── WebSocket streaming ───────────────────────────────────────────────────────

@router.websocket("/{workflow_id}/stream")
async def stream_workflow_events(
    websocket: WebSocket,
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Stream real-time workflow events over WebSocket.

    The client receives JSON event objects as the orchestrator progresses
    through planning, execution, and review.  The stream closes automatically
    when a terminal event (workflow_completed / workflow_failed) is emitted.

    If the workflow is already in a terminal state at connection time, a
    synthetic terminal event is sent immediately and the socket is closed.
    """
    await websocket.accept()

    try:
        wf_uuid = uuid.UUID(workflow_id)
    except ValueError:
        await websocket.send_text(json.dumps({"type": "error", "error": "Invalid workflow ID"}))
        await websocket.close()
        return

    # If workflow already finished, return a synthetic terminal event immediately
    result = await db.execute(
        select(Workflow).where(Workflow.id == wf_uuid)
    )
    workflow = result.scalar_one_or_none()

    if workflow is None:
        await websocket.send_text(json.dumps({"type": "error", "error": "Workflow not found"}))
        await websocket.close()
        return

    terminal_statuses = {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
    if workflow.status in terminal_statuses:
        if workflow.status == WorkflowStatus.COMPLETED:
            payload = {
                "type": "workflow_completed",
                "workflow_id": workflow_id,
                "answer": (workflow.result or {}).get("answer", ""),
            }
        else:
            payload = {
                "type": "workflow_failed",
                "workflow_id": workflow_id,
                "error": workflow.error_message or "Workflow did not complete successfully.",
            }
        await websocket.send_text(json.dumps(payload))
        await websocket.close()
        return

    # Live streaming via Redis pub/sub
    import redis.asyncio as aioredis  # local import to keep top-level clean

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()
    channel = f"workflow:{workflow_id}:events"
    await pubsub.subscribe(channel)

    terminal_event_types = {"workflow_completed", "workflow_failed"}

    async def _forward_events() -> None:
        """Read from Redis pub/sub and forward to the WebSocket client."""
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            data: str = msg["data"]
            await websocket.send_text(data)
            try:
                event = json.loads(data)
                if event.get("type") in terminal_event_types:
                    return
            except json.JSONDecodeError:
                pass

    async def _watch_disconnect() -> None:
        """Consume (and discard) any inbound client messages; exits on disconnect."""
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass

    forward_task = asyncio.create_task(_forward_events())
    watch_task = asyncio.create_task(_watch_disconnect())

    try:
        # Run until either task finishes (terminal event or disconnect) or 5-min timeout
        await asyncio.wait(
            [forward_task, watch_task],
            return_when=asyncio.FIRST_COMPLETED,
            timeout=300,
        )
    finally:
        forward_task.cancel()
        watch_task.cancel()
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass
        await r.aclose()
        try:
            await websocket.close()
        except Exception:
            pass


# ── Background runner ─────────────────────────────────────────────────────────

async def _run_workflow_background(workflow_id: str, task: str, actor: str) -> None:
    """Background asyncio task: runs the orchestrator with its own DB session."""
    async with AsyncSessionLocal() as db:
        try:
            orchestrator = WorkflowOrchestrator(db)
            await orchestrator.run(workflow_id, task, actor)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception(
                "workflows.background_error",
                workflow_id=workflow_id,
                error=str(exc),
            )
