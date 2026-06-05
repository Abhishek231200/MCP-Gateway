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
from mcp_gateway.models.audit import AuditAction
from mcp_gateway.models.workflow import StepStatus, Workflow, WorkflowStatus, WorkflowStep
from mcp_gateway.services.adapters import AdapterError, AdapterNotFoundError, get_adapter
from mcp_gateway.services.adapters.base import write_audit_log
from mcp_gateway.services.adapters.credentials import CredentialResolutionError
from mcp_gateway.services.registry import get_server_by_name, list_tools
from mcp_gateway.services.security_gateway import get_security_gateway

logger = structlog.get_logger()

_MAX_STEPS = 10
_MAX_REPLANS = 0
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
        return openai.AsyncOpenAI(api_key=settings.openai_api_key)

    def _llm_model(self) -> str:
        return "gpt-4o"

    def _is_openai(self) -> bool:
        return True

    async def run(self, workflow_id: str, task: str, actor: str) -> None:
        """Build initial state, drive the graph, handle top-level failures."""
        if not settings.openai_api_key:
            await self._update_workflow_status(
                workflow_id, WorkflowStatus.FAILED,
                error="No LLM API key configured (set OPENAI_API_KEY)",
            )
            await self._publish_event(workflow_id, {
                "type": "workflow_failed",
                "error": "No LLM API key configured (set OPENAI_API_KEY)",
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

        system_prompt = (
            "You are a planning agent for MCP Gateway. "
            "Your ONLY job is to produce a JSON execution plan. "
            "You must respond with valid JSON and nothing else — no markdown, no explanation."
        )

        user_prompt = (
            f"Available tools:\n{tool_manifest}\n\n"
            f"Task: {state['task']}{replan_context}\n\n"
            f"RULES — follow exactly:\n"
            f"1. Plan EXACTLY one step per distinct action the task requests — no more, no fewer.\n"
            f"2. For EVERY argument, read the tool's input_schema above and use the exact key names shown.\n"
            f"3. Extract arguments directly from the task text:\n"
            f"   - GitHub 'OWNER/REPO' format → split into owner='OWNER' and repo='REPO' as separate fields.\n"
            f"   - Slack '#channel' → use the channel name as-is including the # sign.\n"
            f"   - Knowledge base questions → use the 'query' tool (full RAG) not 'search'; pass the question as 'question' key.\n"
            f"   - For Slack post_message or any step that should send a summary of prior step results, "
            f"set the text/message argument to the literal string '{{{{step_results}}}}'. "
            f"The system will automatically substitute it with the actual results at execution time.\n"
            f"4. Do NOT add extra steps not mentioned in the task.\n"
            f"5. depends_on: list step_order integers that must succeed before this step runs.\n"
            f"   Set this for steps that logically require prior steps to have succeeded (e.g. a Slack post depends on the data-gathering steps).\n"
            f"6. Maximum {_MAX_STEPS} steps. If the task cannot be done, return {{\"reasoning\": \"why\", \"steps\": []}}.\n\n"
            f"Respond with this exact JSON structure:\n"
            f'{{"reasoning": "one sentence on your plan", "steps": ['
            f'{{"step_order": 1, "server_name": "...", "tool_name": "...", '
            f'"arguments": {{}}, "reasoning": "why this step", "depends_on": []}}]}}'
        )

        client = self._llm_client()
        call_kwargs: dict[str, Any] = {
            "model": self._llm_model(),
            "max_tokens": 2048,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self._is_openai():
            call_kwargs["response_format"] = {"type": "json_object"}
        response = await client.chat.completions.create(**call_kwargs)
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

    @staticmethod
    def _build_execution_waves(plan: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Group steps into waves where every step in a wave can run concurrently.

        A step enters a wave once all its depends_on steps are in earlier waves.
        """
        completed: set[int] = set()
        remaining = list(plan)
        waves: list[list[dict[str, Any]]] = []
        while remaining:
            wave = [s for s in remaining if set(s.get("depends_on") or []).issubset(completed)]
            if not wave:
                wave = [remaining[0]]  # break circular dependency
            waves.append(wave)
            for s in wave:
                completed.add(s["step_order"])
            remaining = [s for s in remaining if s not in wave]
        return waves

    def _step_permission(self, step: dict[str, Any], available_tools: list[dict[str, Any]]) -> str:
        tool_def = next(
            (t for t in available_tools
             if t["server_name"] == step["server_name"] and t["tool_name"] == step["tool_name"]),
            None,
        )
        return tool_def.get("required_permission", "read") if tool_def else "read"

    async def _executor_node(self, state: WorkflowState) -> dict[str, Any]:
        """Execute planned steps with wave-based parallel execution.

        Steps with no overlapping depends_on run concurrently; write/admin steps
        that require approval always run sequentially.
        """
        if state.get("error"):
            return {}

        workflow_id = state["workflow_id"]
        await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
        await self._db.commit()  # commit so steps appear in UI as they run
        await self._publish_event(workflow_id, {"type": "status_change", "status": "running"})

        step_results: list[dict[str, Any]] = []
        waves = self._build_execution_waves(state["plan"])

        for wave in waves:
            # Run wave in parallel only when all steps are read-only and there are multiple
            can_parallel = (
                len(wave) > 1
                and all(
                    self._step_permission(s, state["available_tools"]) not in _APPROVAL_PERMISSIONS
                    for s in wave
                )
            )
            if can_parallel:
                # Each parallel step needs its own DB session — asyncpg does not
                # allow two concurrent awaits on the same connection.
                async def _run_isolated(step: dict[str, Any]) -> dict[str, Any]:
                    from mcp_gateway.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as isolated_db:
                        result = await self._execute_step(step, state, list(step_results), db=isolated_db)
                        await isolated_db.commit()
                        return result

                wave_results = await asyncio.gather(*[_run_isolated(s) for s in wave])
                step_results.extend(wave_results)
            else:
                for step in wave:
                    result = await self._execute_step(step, state, list(step_results))
                    step_results.append(result)

        step_results.sort(key=lambda r: r["step_order"])
        return {"step_results": step_results}

    async def _execute_step(
        self,
        step: dict[str, Any],
        state: WorkflowState,
        step_results: list[dict[str, Any]],
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Execute a single planned step end-to-end and return its result dict.

        Pass db=isolated_session when running in parallel to avoid asyncpg
        concurrent-connection errors.  Sequential steps reuse self._db.
        """
        db = db or self._db
        workflow_id = state["workflow_id"]
        step_order: int = step["step_order"]
        server_name: str = step["server_name"]
        tool_name: str = step["tool_name"]
        arguments: dict[str, Any] = dict(step.get("arguments", {}))

        def _skipped(reason: str) -> dict[str, Any]:
            return {"step_order": step_order, "server_name": server_name,
                    "tool_name": tool_name, "result": None, "latency_ms": 0,
                    "error": f"Skipped — {reason}", "skipped": True}

        def _denied(reason: str, actor_role: str) -> dict[str, Any]:
            return {"step_order": step_order, "server_name": server_name,
                    "tool_name": tool_name, "result": None, "latency_ms": 0,
                    "error": f"Policy denied: {reason}", "denied": True,
                    "actor_role": actor_role}

        def _failed(error: str, latency_ms: int = 0) -> dict[str, Any]:
            return {"step_order": step_order, "server_name": server_name,
                    "tool_name": tool_name, "result": None,
                    "latency_ms": latency_ms, "error": error}

        # ── Substitute {{step_results}} template ──────────────────────────────
        if step_results and any(isinstance(v, str) and "{{step_results}}" in v for v in arguments.values()):
            formatted = await self._format_for_slack(state["task"], step_results)
            arguments = {k: v.replace("{{step_results}}", formatted) if isinstance(v, str) else v
                         for k, v in arguments.items()}

        # ── Conditional branch: skip if a dependency failed ───────────────────
        depends_on: list[int] = step.get("depends_on", [])
        if depends_on:
            failed_deps = [d for d in depends_on
                           if any(r["step_order"] == d and r.get("error") for r in step_results)]
            if failed_deps:
                ws = await self._get_step_with(db, workflow_id, step_order, state["replan_count"])
                if ws:
                    ws.status = StepStatus.SKIPPED
                    ws.completed_at = datetime.now(UTC)
                    await db.flush()
                reason = f"Dependency step(s) {failed_deps} failed."
                await self._publish_event(workflow_id, {"type": "step_skipped", "step": step_order,
                                                         "tool": tool_name, "reason": reason})
                return _skipped(reason)

        # ── Resolve permission ────────────────────────────────────────────────
        required_permission = self._step_permission(step, state["available_tools"])

        # ── OPA policy check ──────────────────────────────────────────────────
        gw = get_security_gateway()
        decision = await gw.evaluate(actor=state["actor"], server_name=server_name,
                                      tool_name=tool_name, required_permission=required_permission)
        if not decision.allow:
            ws = await self._get_step_with(db, workflow_id, step_order, state["replan_count"])
            if ws:
                ws.status = StepStatus.FAILED
                ws.error_message = f"Policy denied: {decision.reason}"
                ws.completed_at = datetime.now(UTC)
                await db.flush()
            await write_audit_log(db, workflow_id=uuid.UUID(workflow_id),
                                   action=AuditAction.TOOL_BLOCKED, actor=state["actor"],
                                   server_name=server_name, tool_name=tool_name,
                                   request_payload={"arguments": arguments}, allowed=False,
                                   policy_decision={"reason": decision.reason, "actor_role": decision.actor_role})
            await db.flush()
            await self._publish_event(workflow_id, {"type": "step_denied", "step": step_order,
                                                      "server": server_name, "tool": tool_name,
                                                      "reason": decision.reason, "actor_role": decision.actor_role})
            return _denied(decision.reason, decision.actor_role)

        # ── Approval gate ─────────────────────────────────────────────────────
        if step.get("requires_approval", False) or required_permission in _APPROVAL_PERMISSIONS:
            approved = await self._wait_for_approval(workflow_id, step)
            if not approved:
                err = "Step rejected by user or approval timed out."
                ws = await self._get_step_with(db, workflow_id, step_order, state["replan_count"])
                if ws:
                    ws.status = StepStatus.FAILED
                    ws.error_message = err
                    ws.completed_at = datetime.now(UTC)
                    await db.flush()
                await self._publish_event(workflow_id, {"type": "step_failed", "step": step_order,
                                                         "tool": tool_name, "error": err})
                return _failed(err)

        # ── Mark step RUNNING ─────────────────────────────────────────────────
        ws = await self._get_step_with(db, workflow_id, step_order, state["replan_count"])
        if ws:
            ws.status = StepStatus.RUNNING
            await db.flush()
        await self._publish_event(workflow_id, {"type": "step_started", "step": step_order,
                                                 "server": server_name, "tool": tool_name,
                                                 "arguments": arguments})

        # ── Execute with retry ────────────────────────────────────────────────
        t0 = time.perf_counter()
        tool_result: dict[str, Any] | None = None
        error_msg: str | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                server = await get_server_by_name(db, server_name)
                if server is None:
                    raise AdapterError(f"Server '{server_name}' not found in registry")
                adapter = get_adapter(server)
                tool_result = await adapter.invoke_tool(server=server, tool_name=tool_name,
                                                         arguments=arguments, db=db,
                                                         actor=state["actor"])
                break
            except AdapterError as exc:
                if (exc.status_code or 0) in {429, 502, 503, 504} and attempt < _MAX_RETRIES:
                    backoff = _RETRY_BACKOFF * (2 ** attempt)
                    await self._publish_event(workflow_id, {"type": "step_retry", "step": step_order,
                                                             "attempt": attempt + 1, "max_retries": _MAX_RETRIES,
                                                             "backoff_seconds": backoff})
                    await asyncio.sleep(backoff)
                    continue
                error_msg = str(exc)
                break
            except (AdapterNotFoundError, CredentialResolutionError, Exception) as exc:
                error_msg = str(exc)
                break

        latency_ms = round((time.perf_counter() - t0) * 1000)

        # ── Record result ─────────────────────────────────────────────────────
        if tool_result is not None:
            result = tool_result["result"]
            if ws:
                ws.status = StepStatus.COMPLETED
                ws.output_payload = result if isinstance(result, dict) else {"result": result}
                ws.latency_ms = tool_result["latency_ms"]
                ws.completed_at = datetime.now(UTC)
                await db.flush()
            await db.commit()
            await self._publish_event(workflow_id, {"type": "step_completed", "step": step_order,
                                                     "tool": tool_name, "latency_ms": tool_result["latency_ms"]})
            return {"step_order": step_order, "server_name": server_name, "tool_name": tool_name,
                    "result": result, "latency_ms": tool_result["latency_ms"], "error": None}
        else:
            if ws:
                ws.status = StepStatus.FAILED
                ws.error_message = error_msg
                ws.latency_ms = latency_ms
                ws.completed_at = datetime.now(UTC)
                await db.flush()
            await db.commit()
            await self._publish_event(workflow_id, {"type": "step_failed", "step": step_order,
                                                     "tool": tool_name, "error": error_msg})
            logger.warning("orchestrator.step_failed", workflow_id=workflow_id,
                           step=step_order, tool=tool_name, error=error_msg)
            return _failed(error_msg or "Unknown error", latency_ms)

    # ── Slack message formatter ───────────────────────────────────────────────

    async def _format_for_slack(
        self, task: str, step_results: list[dict[str, Any]]
    ) -> str:
        """Call gpt-4o-mini to format step results into a clean Slack mrkdwn message."""
        results_text = "\n\n".join(
            f"[{r['tool_name']}]: {'FAILED — ' + r['error'] if r.get('error') else json.dumps(r['result'], default=str)[:3000]}"
            for r in step_results
        )
        prompt = (
            f"Format the following data as a concise, professional Slack message using Slack mrkdwn.\n"
            f"Original task: {task}\n\n"
            f"Data from executed steps:\n{results_text}\n\n"
            f"Rules:\n"
            f"- Use *bold* for section headers and key terms\n"
            f"- Use bullet points (•) for lists\n"
            f"- Be concise — summarize, don't dump raw data\n"
            f"- Include only what's relevant to the task\n"
            f"- No markdown headers (# ## ###) — use *bold* instead\n"
            f"- Keep it under 400 words\n"
            f"Return only the formatted Slack message text, nothing else."
        )
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=600,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return (response.choices[0].message.content or "").strip()

    # ── Approval gate ─────────────────────────────────────────────────────────

    async def _wait_for_approval(
        self, workflow_id: str, step: dict[str, Any]
    ) -> bool:
        """Pause the workflow and wait for a human approve/reject decision."""
        event = asyncio.Event()
        _pending_approvals[workflow_id] = event

        await self._update_workflow_status(workflow_id, WorkflowStatus.AWAITING_APPROVAL)
        await self._db.commit()  # commit so the polling UI sees awaiting_approval + steps
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
                result = r["result"]
                # Render as readable text, not raw JSON, to avoid quote/newline
                # escaping issues when the reviewer embeds this in a JSON answer field.
                if isinstance(result, list):
                    items = "\n".join(
                        "  - " + ", ".join(f"{k}: {v}" for k, v in item.items() if v is not None)
                        if isinstance(item, dict) else f"  - {item}"
                        for item in result[:10]
                    )
                    preview = f"{len(result)} item(s):\n{items}"
                elif isinstance(result, dict):
                    preview = "\n".join(
                        f"  {k}: {str(v)[:300]}" for k, v in result.items() if v is not None
                    )[:2000]
                else:
                    preview = str(result)[:2000]
                summary_lines.append(
                    f"Step {r['step_order']} ({r['tool_name']}): SUCCESS\n{preview}"
                )
        results_text = "\n\n".join(summary_lines) or "No steps were executed."

        prompt = (
            f"You are a reviewer agent. Evaluate whether the execution results answer the task, "
            f"then synthesise a response.\n\n"
            f"Task: {state['task']}\n\n"
            f"Execution results:\n{results_text}\n\n"
            f"Your entire response must be a single JSON object with these exact keys:\n"
            f"  sufficient: true if the results answer the task, false if all steps failed or results are empty\n"
            f"  answer: a markdown-formatted string with the actual answer — "
            f"use tables for lists, bullets for summaries, prose for explanations. "
            f"Include real names and values. This MUST be a string, not an array or object.\n"
            f"  feedback: empty string if sufficient, otherwise a short description of what failed\n\n"
            f"Example of a valid response:\n"
            f'{{"sufficient": true, "answer": "## Repositories\\n| Name | Language |\\n|---|---|\\n| repo1 | Python |", "feedback": ""}}'
        )

        client = self._llm_client()
        review_kwargs: dict[str, Any] = {
            "model": self._llm_model(),
            "max_tokens": 1024,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "You are a reviewer agent. Respond with valid JSON only — no markdown, no explanation."},
                {"role": "user", "content": prompt},
            ],
        }
        if self._is_openai():
            review_kwargs["response_format"] = {"type": "json_object"}
        response = await client.chat.completions.create(**review_kwargs)
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
        return await self._get_step_with(self._db, workflow_id, step_order, replan_count)

    async def _get_step_with(
        self, db: AsyncSession, workflow_id: str, step_order: int, replan_count: int
    ) -> WorkflowStep | None:
        role_tag = "executor" if replan_count == 0 else f"executor-replan-{replan_count}"
        result = await db.execute(
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
