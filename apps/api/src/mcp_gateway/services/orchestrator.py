"""LangGraph workflow orchestrator: planner → executor → reviewer.

Graph topology:
    START → planner → executor → reviewer → END
                                    │
                                    └─(insufficient, replan_count < MAX)──► planner

State flows:
    WorkflowState is a TypedDict; each node returns a partial dict of fields to
    update.  LangGraph merges updates back into the full state before passing it
    to the next node.
"""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import openai
import structlog
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from mcp_gateway.config import settings
from mcp_gateway.models.workflow import StepStatus, Workflow, WorkflowStatus, WorkflowStep
from mcp_gateway.services.adapters import AdapterError, AdapterNotFoundError, get_adapter
from mcp_gateway.services.adapters.credentials import CredentialResolutionError
from mcp_gateway.services.registry import get_server_by_name, list_tools

logger = structlog.get_logger()

_MAX_STEPS = 10
_MAX_REPLANS = 1
_MAX_RETRIES = 2          # transient-error retries per step
_RETRY_BACKOFF = 1.0      # base backoff seconds (doubles each attempt)
_APPROVAL_TIMEOUT = 600.0 # seconds to wait for human approval before auto-reject

# Tools whose required_permission warrants human approval before execution
_APPROVAL_PERMISSIONS: set[str] = {"write", "admin"}

# ── Human-in-the-loop approval state ─────────────────────────────────────────
# Keyed by workflow_id (str). Lives in the process; cleared after decision.
_pending_approvals: dict[str, asyncio.Event] = {}
_approval_decisions: dict[str, bool] = {}


def register_approval_decision(workflow_id: str, approved: bool) -> bool:
    """Called by the router when a user approves or rejects a checkpoint.

    Returns False if there is no pending checkpoint for this workflow.
    """
    event = _pending_approvals.get(workflow_id)
    if event is None:
        return False
    _approval_decisions[workflow_id] = approved
    event.set()
    return True


# ── State definition ──────────────────────────────────────────────────────────

class WorkflowState(TypedDict):
    workflow_id: str
    task: str
    actor: str
    # Tool manifest fetched from the registry at run start
    available_tools: list[dict[str, Any]]
    # Planner output: list of {step_order, server_name, tool_name, arguments, reasoning}
    plan: list[dict[str, Any]]
    # Executor output: list of {step_order, server_name, tool_name, result, latency_ms, error}
    step_results: list[dict[str, Any]]
    # Incremented each time the reviewer asks for a replan
    replan_count: int
    # Set by reviewer on success; signals END
    final_answer: str | None
    # Set on unrecoverable failure; signals END
    error: str | None


# ── Orchestrator class ────────────────────────────────────────────────────────

class WorkflowOrchestrator:
    """Wraps a LangGraph StateGraph with DB + Redis access baked in.

    Create one instance per workflow run (each gets its own DB session).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._graph = self._build_graph()

    # ── Graph construction ────────────────────────────────────────────────────

    def _build_graph(self) -> Any:
        g: StateGraph = StateGraph(WorkflowState)
        g.add_node("planner", self._planner_node)
        g.add_node("executor", self._executor_node)
        g.add_node("reviewer", self._reviewer_node)
        g.add_edge("__start__", "planner")
        g.add_edge("planner", "executor")
        g.add_edge("executor", "reviewer")
        g.add_conditional_edges("reviewer", self._reviewer_router)
        return g.compile()

    def _reviewer_router(self, state: WorkflowState) -> str:
        """Route after reviewer: replan if insufficient and under the limit, else END."""
        if state.get("final_answer") or state.get("error"):
            return END
        if state["replan_count"] < _MAX_REPLANS:
            return "planner"
        return END

    # ── Public entry point ────────────────────────────────────────────────────

    def _llm_client(self) -> openai.AsyncOpenAI:
        """Return an OpenAI-compatible async client.

        Prefers Groq (free tier) when GROQ_API_KEY is set; falls back to OpenAI.
        """
        if settings.groq_api_key:
            return openai.AsyncOpenAI(
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            )
        return openai.AsyncOpenAI(api_key=settings.openai_api_key)

    def _llm_model(self) -> str:
        if settings.groq_api_key:
            return "llama-3.1-8b-instant"
        return "gpt-4o-mini"

    async def run(self, workflow_id: str, task: str, actor: str) -> None:
        """Build initial state, drive the graph, handle top-level failures."""
        if not settings.groq_api_key and not settings.openai_api_key:
            await self._update_workflow_status(
                workflow_id, WorkflowStatus.FAILED,
                error="No LLM API key configured (set GROQ_API_KEY or OPENAI_API_KEY)",
            )
            await self._publish_event(workflow_id, {
                "type": "workflow_failed",
                "error": "No LLM API key configured (set GROQ_API_KEY or OPENAI_API_KEY)",
            })
            return

        tool_rows = await list_tools(self._db)
        available_tools = [
            {
                "server_name": server.name,
                "tool_name": cap.tool_name,
                "description": cap.description or "",
                "input_schema": cap.input_schema,
                "required_permission": cap.required_permission,
            }
            for server, cap in tool_rows
        ]

        initial_state: WorkflowState = {
            "workflow_id": workflow_id,
            "task": task,
            "actor": actor,
            "available_tools": available_tools,
            "plan": [],
            "step_results": [],
            "replan_count": 0,
            "final_answer": None,
            "error": None,
        }

        try:
            await self._update_workflow_status(workflow_id, WorkflowStatus.PLANNING)
            await self._publish_event(workflow_id, {"type": "status_change", "status": "planning"})
            await self._graph.ainvoke(initial_state)
        except Exception as exc:
            logger.exception("orchestrator.run.fatal", workflow_id=workflow_id, error=str(exc))
            await self._update_workflow_status(
                workflow_id, WorkflowStatus.FAILED, error=str(exc)
            )
            await self._publish_event(workflow_id, {"type": "workflow_failed", "error": str(exc)})

    # ── Planner node ──────────────────────────────────────────────────────────

    async def _planner_node(self, state: WorkflowState) -> dict[str, Any]:
        """Ask Claude to decompose the task into a sequence of tool calls."""
        if state.get("error"):
            return {}

        workflow_id = state["workflow_id"]

        # Build tool manifest string
        tool_lines: list[str] = []
        for t in state["available_tools"]:
            schema_str = json.dumps(t.get("input_schema", {}), separators=(",", ":"))
            tool_lines.append(
                f"- server={t['server_name']}  tool={t['tool_name']}"
                f"  permission={t['required_permission']}\n"
                f"  description: {t['description'] or 'N/A'}\n"
                f"  input_schema: {schema_str}"
            )
        tool_manifest = "\n".join(tool_lines) or "No tools available."

        # Append previous failure context when replanning
        replan_context = ""
        if state["replan_count"] > 0 and state["step_results"]:
            failures = [r for r in state["step_results"] if r.get("error")]
            if failures:
                failure_lines = "\n".join(
                    f"  - step {r['step_order']} ({r.get('tool_name')}): {r['error']}"
                    for r in failures
                )
                replan_context = f"\n\nPrevious attempt failed. Issues to avoid:\n{failure_lines}"

        prompt = (
            f"You are a planning agent for MCP Gateway, an AI orchestration platform.\n\n"
            f"Available tools:\n{tool_manifest}\n\n"
            f"Task: {state['task']}{replan_context}\n\n"
            f"Decompose the task into a minimal sequence of tool calls. "
            f"Respond ONLY with valid JSON — no markdown, no commentary:\n"
            f'{{"reasoning": "...", "steps": [{{'
            f'"step_order": 1, "server_name": "exact-server-name", '
            f'"tool_name": "exact-tool-name", "arguments": {{}}, "reasoning": "...", '
            f'"depends_on": []}}, ...]}}\n\n'
            f"Rules:\n"
            f"- Only use server_name / tool_name values exactly as listed above\n"
            f"- Maximum {_MAX_STEPS} steps\n"
            f"- CRITICAL: Steps execute sequentially but cannot pass results to each other. "
            f"Every argument in every step must be fully known at planning time from the task description alone. "
            f"Do NOT create a step whose arguments depend on the output of a previous step. "
            f"If you do not know a required argument (e.g. 'owner', 'repo', 'number') from the task text, "
            f"do not include that step.\n"
            f"- depends_on: list of step_order integers that must succeed for this step to run. "
            f"Set this when the step only makes sense if a prior step succeeded. Leave [] if independent.\n"
            f"- Prefer broad listing tools (list_repos, list_channels) when the task asks for an overview. "
            f"Only call detail tools (get_pr, get_issue, list_issues) if the owner and repo are explicitly stated in the task.\n"
            f"- If the task cannot be accomplished, return {{\"reasoning\": \"...\", \"steps\": []}}"
        )

        client = self._llm_client()
        response = await client.chat.completions.create(
            model=self._llm_model(),
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        tokens_used = (response.usage.prompt_tokens + response.usage.completion_tokens) if response.usage else 0
        raw = (response.choices[0].message.content or "").strip()

        # Strip accidental markdown fences
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        try:
            plan_data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("planner.json_parse_error", raw=raw[:300])
            plan_data = {"reasoning": "JSON parse error — treating as no plan.", "steps": []}

        # Validate: only keep steps that reference real tools
        valid_tools = {(t["server_name"], t["tool_name"]) for t in state["available_tools"]}
        raw_steps: list[dict[str, Any]] = plan_data.get("steps", [])[:_MAX_STEPS]
        plan = [
            s for s in raw_steps
            if (s.get("server_name"), s.get("tool_name")) in valid_tools
        ]

        # Persist plan into the workflow row
        workflow = await self._get_workflow(workflow_id)
        if workflow:
            workflow.plan = plan_data
            workflow.total_tokens_used = (workflow.total_tokens_used or 0) + tokens_used
            await self._db.flush()

        # Create WorkflowStep rows for this attempt
        role_tag = "executor" if state["replan_count"] == 0 else f"executor-replan-{state['replan_count']}"
        for step in plan:
            self._db.add(WorkflowStep(
                workflow_id=uuid.UUID(workflow_id),
                step_order=step["step_order"],
                agent_role=role_tag,
                server_name=step.get("server_name"),
                tool_name=step.get("tool_name"),
                status=StepStatus.PENDING,
                input_payload=step.get("arguments", {}),
            ))
        await self._db.flush()

        await self._publish_event(workflow_id, {
            "type": "plan_ready",
            "step_count": len(plan),
            "reasoning": plan_data.get("reasoning", ""),
            "steps": [
                {
                    "step_order": s["step_order"],
                    "server_name": s.get("server_name"),
                    "tool_name": s.get("tool_name"),
                    "reasoning": s.get("reasoning", ""),
                }
                for s in plan
            ],
        })
        logger.info("orchestrator.planned", workflow_id=workflow_id, steps=len(plan))

        if not plan:
            err = "Planner produced no executable steps for this task."
            await self._update_workflow_status(workflow_id, WorkflowStatus.FAILED, error=err)
            await self._publish_event(workflow_id, {"type": "workflow_failed", "error": err})
            return {"plan": [], "error": err}

        return {"plan": plan}

    # ── Executor node ─────────────────────────────────────────────────────────

    async def _executor_node(self, state: WorkflowState) -> dict[str, Any]:
        """Execute each planned step with retry, conditional branching, and approval gates."""
        if state.get("error"):
            return {}

        workflow_id = state["workflow_id"]
        await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
        await self._publish_event(workflow_id, {"type": "status_change", "status": "running"})

        step_results: list[dict[str, Any]] = []

        for step in state["plan"]:
            step_order: int = step["step_order"]
            server_name: str = step["server_name"]
            tool_name: str = step["tool_name"]
            arguments: dict[str, Any] = step.get("arguments", {})

            # ── Conditional branch: skip if a dependency failed ───────────────
            depends_on: list[int] = step.get("depends_on", [])
            if depends_on:
                failed_deps = [
                    d for d in depends_on
                    if any(r["step_order"] == d and r.get("error") for r in step_results)
                ]
                if failed_deps:
                    ws = await self._get_step(workflow_id, step_order, state["replan_count"])
                    if ws:
                        ws.status = StepStatus.SKIPPED
                        ws.completed_at = datetime.now(UTC)
                        await self._db.flush()
                    reason = f"Dependency step(s) {failed_deps} failed."
                    step_results.append({
                        "step_order": step_order,
                        "server_name": server_name,
                        "tool_name": tool_name,
                        "result": None,
                        "latency_ms": 0,
                        "error": f"Skipped — {reason}",
                        "skipped": True,
                    })
                    await self._publish_event(workflow_id, {
                        "type": "step_skipped",
                        "step": step_order,
                        "tool": tool_name,
                        "reason": reason,
                    })
                    logger.info("orchestrator.step_skipped", workflow_id=workflow_id,
                                step=step_order, reason=reason)
                    continue

            # ── Human-in-the-loop: check if approval required ─────────────────
            tool_def = next(
                (t for t in state["available_tools"]
                 if t["server_name"] == server_name and t["tool_name"] == tool_name),
                None,
            )
            needs_approval = (
                step.get("requires_approval", False)
                or (tool_def is not None
                    and tool_def.get("required_permission") in _APPROVAL_PERMISSIONS)
            )
            if needs_approval:
                approved = await self._wait_for_approval(workflow_id, step)
                if not approved:
                    err = "Step rejected by user or approval timed out."
                    ws = await self._get_step(workflow_id, step_order, state["replan_count"])
                    if ws:
                        ws.status = StepStatus.FAILED
                        ws.error_message = err
                        ws.completed_at = datetime.now(UTC)
                        await self._db.flush()
                    step_results.append({
                        "step_order": step_order,
                        "server_name": server_name,
                        "tool_name": tool_name,
                        "result": None,
                        "latency_ms": 0,
                        "error": err,
                    })
                    await self._publish_event(workflow_id, {
                        "type": "step_failed",
                        "step": step_order,
                        "tool": tool_name,
                        "error": err,
                    })
                    continue

            # ── Mark step RUNNING ─────────────────────────────────────────────
            ws = await self._get_step(workflow_id, step_order, state["replan_count"])
            if ws:
                ws.status = StepStatus.RUNNING
                await self._db.flush()

            await self._publish_event(workflow_id, {
                "type": "step_started",
                "step": step_order,
                "server": server_name,
                "tool": tool_name,
                "arguments": arguments,
            })

            # ── Execute with retry on transient errors ────────────────────────
            t0 = time.perf_counter()
            tool_result: dict[str, Any] | None = None
            error_msg: str | None = None

            for attempt in range(_MAX_RETRIES + 1):
                try:
                    server = await get_server_by_name(self._db, server_name)
                    if server is None:
                        raise AdapterError(f"Server '{server_name}' not found in registry")
                    adapter = get_adapter(server)
                    tool_result = await adapter.invoke_tool(
                        server=server,
                        tool_name=tool_name,
                        arguments=arguments,
                        db=self._db,
                        actor=state["actor"],
                    )
                    break  # success

                except AdapterError as exc:
                    is_transient = (exc.status_code or 0) in {429, 502, 503, 504}
                    if is_transient and attempt < _MAX_RETRIES:
                        backoff = _RETRY_BACKOFF * (2 ** attempt)
                        await self._publish_event(workflow_id, {
                            "type": "step_retry",
                            "step": step_order,
                            "attempt": attempt + 1,
                            "max_retries": _MAX_RETRIES,
                            "backoff_seconds": backoff,
                        })
                        logger.info("orchestrator.step_retry", workflow_id=workflow_id,
                                    step=step_order, attempt=attempt + 1)
                        await asyncio.sleep(backoff)
                        continue
                    error_msg = str(exc)
                    break

                except (AdapterNotFoundError, CredentialResolutionError, Exception) as exc:
                    error_msg = str(exc)
                    break

            latency_ms = round((time.perf_counter() - t0) * 1000)

            # ── Record result ─────────────────────────────────────────────────
            if tool_result is not None:
                result = tool_result["result"]
                if ws:
                    ws.status = StepStatus.COMPLETED
                    ws.output_payload = result if isinstance(result, dict) else {"result": result}
                    ws.latency_ms = tool_result["latency_ms"]
                    ws.completed_at = datetime.now(UTC)
                    await self._db.flush()
                step_results.append({
                    "step_order": step_order,
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "result": result,
                    "latency_ms": tool_result["latency_ms"],
                    "error": None,
                })
                await self._publish_event(workflow_id, {
                    "type": "step_completed",
                    "step": step_order,
                    "tool": tool_name,
                    "latency_ms": tool_result["latency_ms"],
                })
            else:
                if ws:
                    ws.status = StepStatus.FAILED
                    ws.error_message = error_msg
                    ws.latency_ms = latency_ms
                    ws.completed_at = datetime.now(UTC)
                    await self._db.flush()
                step_results.append({
                    "step_order": step_order,
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "result": None,
                    "latency_ms": latency_ms,
                    "error": error_msg,
                })
                await self._publish_event(workflow_id, {
                    "type": "step_failed",
                    "step": step_order,
                    "tool": tool_name,
                    "error": error_msg,
                })
                logger.warning("orchestrator.step_failed", workflow_id=workflow_id,
                               step=step_order, tool=tool_name, error=error_msg)

        return {"step_results": step_results}

    # ── Approval gate ─────────────────────────────────────────────────────────

    async def _wait_for_approval(
        self, workflow_id: str, step: dict[str, Any]
    ) -> bool:
        """Pause the workflow and wait for a human approve/reject decision."""
        event = asyncio.Event()
        _pending_approvals[workflow_id] = event

        await self._update_workflow_status(workflow_id, WorkflowStatus.AWAITING_APPROVAL)
        await self._publish_event(workflow_id, {
            "type": "checkpoint_reached",
            "step": step["step_order"],
            "server": step.get("server_name"),
            "tool": step.get("tool_name"),
            "arguments": step.get("arguments", {}),
            "message": (
                f"Approval required before calling "
                f"{step.get('server_name')}/{step.get('tool_name')}"
            ),
        })
        logger.info("orchestrator.checkpoint_reached", workflow_id=workflow_id,
                    step=step["step_order"], tool=step.get("tool_name"))

        try:
            await asyncio.wait_for(event.wait(), timeout=_APPROVAL_TIMEOUT)
            approved = _approval_decisions.get(workflow_id, False)
        except asyncio.TimeoutError:
            approved = False
            logger.warning("orchestrator.approval_timeout", workflow_id=workflow_id)
        finally:
            _pending_approvals.pop(workflow_id, None)
            _approval_decisions.pop(workflow_id, None)

        # Resume to running status before the next step
        await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
        await self._publish_event(workflow_id, {
            "type": "checkpoint_approved" if approved else "checkpoint_rejected",
            "step": step["step_order"],
        })
        return approved

    # ── Reviewer node ─────────────────────────────────────────────────────────

    async def _reviewer_node(self, state: WorkflowState) -> dict[str, Any]:
        """Evaluate results; synthesise final answer or trigger replan."""
        if state.get("error"):
            return {}

        workflow_id = state["workflow_id"]
        await self._publish_event(workflow_id, {"type": "review_started"})

        step_results = state["step_results"]

        summary_lines: list[str] = []
        for r in step_results:
            if r.get("error"):
                summary_lines.append(
                    f"Step {r['step_order']} ({r['tool_name']}): FAILED — {r['error']}"
                )
            else:
                result_preview = json.dumps(r["result"], default=str)[:2000]
                summary_lines.append(
                    f"Step {r['step_order']} ({r['tool_name']}): SUCCESS — {result_preview}"
                )
        results_text = "\n".join(summary_lines) or "No steps were executed."

        prompt = (
            f"You are a reviewer agent for MCP Gateway.\n\n"
            f"Original task: {state['task']}\n\n"
            f"Execution results:\n{results_text}\n\n"
            f"Write a direct, human-readable answer to the task using the actual data above. "
            f"Include the real names, values, and details from the results — do NOT just say 'the results were retrieved'. "
            f"Respond ONLY with valid JSON — no markdown, no commentary:\n"
            f'{{"sufficient": true, "answer": "direct answer with actual data from results", "feedback": ""}}\n'
            f"Or if the results are empty or all steps failed:\n"
            f'{{"sufficient": false, "answer": "", "feedback": "what specifically failed"}}'
        )

        client = self._llm_client()
        response = await client.chat.completions.create(
            model=self._llm_model(),
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        tokens_used = (response.usage.prompt_tokens + response.usage.completion_tokens) if response.usage else 0
        raw = (response.choices[0].message.content or "").strip()

        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        try:
            review: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: sufficient if all steps passed
            all_passed = all(r.get("error") is None for r in step_results)
            review = {
                "sufficient": all_passed,
                "answer": results_text if all_passed else "",
                "feedback": "Reviewer response was not valid JSON.",
            }

        workflow = await self._get_workflow(workflow_id)
        if workflow:
            workflow.total_tokens_used = (workflow.total_tokens_used or 0) + tokens_used
            await self._db.flush()

        if review.get("sufficient"):
            answer = review.get("answer", "")
            if workflow:
                workflow.status = WorkflowStatus.COMPLETED
                workflow.result = {"answer": answer, "step_count": len(step_results)}
                workflow.completed_at = datetime.now(UTC)
                await self._db.flush()

            await self._publish_event(workflow_id, {
                "type": "workflow_completed",
                "answer": answer,
            })
            logger.info("orchestrator.completed", workflow_id=workflow_id)
            return {"final_answer": answer}

        # Not sufficient — try to replan if budget allows
        feedback = review.get("feedback", "Review indicated insufficient results.")
        new_replan_count = state["replan_count"] + 1

        if new_replan_count <= _MAX_REPLANS:
            await self._publish_event(workflow_id, {
                "type": "replanning",
                "feedback": feedback,
                "attempt": new_replan_count,
            })
            return {"replan_count": new_replan_count}

        # Max replans exhausted
        if workflow:
            workflow.status = WorkflowStatus.FAILED
            workflow.error_message = feedback
            workflow.completed_at = datetime.now(UTC)
            await self._db.flush()

        await self._publish_event(workflow_id, {"type": "workflow_failed", "error": feedback})
        return {"error": feedback}

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _get_workflow(self, workflow_id: str) -> Workflow | None:
        result = await self._db.execute(
            select(Workflow).where(Workflow.id == uuid.UUID(workflow_id))
        )
        return result.scalar_one_or_none()

    async def _get_step(
        self, workflow_id: str, step_order: int, replan_count: int
    ) -> WorkflowStep | None:
        role_tag = "executor" if replan_count == 0 else f"executor-replan-{replan_count}"
        result = await self._db.execute(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == uuid.UUID(workflow_id))
            .where(WorkflowStep.step_order == step_order)
            .where(WorkflowStep.agent_role == role_tag)
        )
        return result.scalar_one_or_none()

    async def _update_workflow_status(
        self,
        workflow_id: str,
        status: WorkflowStatus,
        error: str | None = None,
    ) -> None:
        workflow = await self._get_workflow(workflow_id)
        if workflow is None:
            return
        workflow.status = status
        if error:
            workflow.error_message = error
        if status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
            workflow.completed_at = datetime.now(UTC)
        await self._db.flush()

    # ── Redis event publishing ────────────────────────────────────────────────

    async def _publish_event(self, workflow_id: str, event: dict[str, Any]) -> None:
        """Publish a workflow event to the Redis pub/sub channel."""
        import redis.asyncio as aioredis

        event = {
            **event,
            "workflow_id": workflow_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.publish(
                f"workflow:{workflow_id}:events",
                json.dumps(event, default=str),
            )
        except Exception as exc:
            logger.warning("orchestrator.publish_failed", error=str(exc))
        finally:
            await r.aclose()
