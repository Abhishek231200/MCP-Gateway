import { useState, useRef, useEffect } from "react";
import { GitBranch, Play, Loader2, CheckCircle2, XCircle, Clock, Zap, RefreshCw, ShieldAlert, SkipForward } from "lucide-react";
import {
  useWorkflows,
  useWorkflow,
  useCreateWorkflow,
  useWorkflowStream,
  useApproveCheckpoint,
  useRejectCheckpoint,
  type Workflow,
  type StreamEvent,
  type WorkflowStatus,
  type StepStatus,
} from "@/hooks/useWorkflows";

// ── Status helpers ────────────────────────────────────────────────────────────

const STATUS_BADGE: Record<WorkflowStatus, string> = {
  pending:           "badge-unknown",
  planning:          "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-900/50 text-yellow-300 border border-yellow-800",
  running:           "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-brand-900/50 text-brand-300 border border-brand-800",
  awaiting_approval: "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-orange-900/50 text-orange-300 border border-orange-800",
  completed:         "badge-healthy",
  failed:            "badge-unhealthy",
  cancelled:         "badge-unknown",
};

const STEP_STATUS_ICON: Record<StepStatus, React.ReactNode> = {
  pending:   <Clock className="w-3.5 h-3.5 text-gray-500" />,
  running:   <Loader2 className="w-3.5 h-3.5 text-brand-400 animate-spin" />,
  completed: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
  failed:    <XCircle className="w-3.5 h-3.5 text-red-400" />,
  skipped:   <SkipForward className="w-3.5 h-3.5 text-gray-500" />,
};

function statusDot(status: WorkflowStatus) {
  const map: Record<WorkflowStatus, string> = {
    pending:           "◌",
    planning:          "◐",
    running:           "●",
    awaiting_approval: "◑",
    completed:         "●",
    failed:            "●",
    cancelled:         "◌",
  };
  return map[status] ?? "◌";
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

// ── Event stream log ──────────────────────────────────────────────────────────

function eventLabel(event: StreamEvent): string {
  switch (event.type) {
    case "status_change":        return `Status → ${event.status}`;
    case "plan_ready":           return `Plan ready — ${event.step_count} step${(event.step_count as number) !== 1 ? "s" : ""}`;
    case "step_started":         return `Step ${event.step} started: ${event.server}.${event.tool}`;
    case "step_completed":       return `Step ${event.step} completed (${event.latency_ms}ms)`;
    case "step_failed":          return `Step ${event.step} failed: ${event.error}`;
    case "step_skipped":         return `Step ${event.step} skipped — ${event.reason}`;
    case "step_retry":           return `Step ${event.step} retrying (attempt ${event.attempt}/${event.max_retries}, backoff ${event.backoff_seconds}s)`;
    case "checkpoint_reached":   return `Checkpoint: approval required for step ${event.step} (${event.server}.${event.tool})`;
    case "checkpoint_approved":  return `Checkpoint approved — step ${event.step} proceeding`;
    case "checkpoint_rejected":  return `Checkpoint rejected — step ${event.step} cancelled`;
    case "review_started":       return "Reviewer evaluating results…";
    case "replanning":           return `Replanning (attempt ${event.attempt}): ${event.feedback}`;
    case "workflow_completed":   return "Workflow completed";
    case "workflow_failed":      return `Workflow failed: ${event.error}`;
    default:                     return event.type;
  }
}

function eventColor(event: StreamEvent): string {
  if (event.type === "workflow_completed" || event.type === "step_completed" || event.type === "checkpoint_approved") return "text-emerald-400";
  if (event.type === "workflow_failed" || event.type === "step_failed" || event.type === "checkpoint_rejected")       return "text-red-400";
  if (event.type === "checkpoint_reached")                                                                            return "text-orange-300";
  if (event.type === "step_skipped")                                                                                  return "text-gray-500";
  if (event.type === "step_retry")                                                                                    return "text-yellow-400";
  if (event.type === "plan_ready")                                                                                    return "text-brand-300";
  if (event.type === "review_started" || event.type === "replanning")                                                 return "text-yellow-300";
  return "text-gray-400";
}

interface EventLogProps {
  events: StreamEvent[];
  isConnected: boolean;
}

function EventLog({ events, isConnected }: EventLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div className="text-xs text-gray-600 italic py-2">
        {isConnected ? "Connected — waiting for events…" : "No events yet."}
      </div>
    );
  }

  return (
    <div className="space-y-1 max-h-56 overflow-y-auto pr-1">
      {events.map((e, i) => (
        <div key={i} className="flex items-start gap-2 text-xs font-mono">
          <span className="text-gray-600 shrink-0 tabular-nums">
            {e.timestamp ? new Date(e.timestamp as string).toLocaleTimeString() : "--:--:--"}
          </span>
          <span className={eventColor(e)}>{eventLabel(e)}</span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

// ── Step timeline ─────────────────────────────────────────────────────────────

interface StepTimelineProps {
  workflow: Workflow;
}

function StepTimeline({ workflow }: StepTimelineProps) {
  if (workflow.steps.length === 0) {
    const planSteps = (workflow.plan as { steps?: unknown[] })?.steps;
    if (!planSteps || planSteps.length === 0) {
      return (
        <p className="text-xs text-gray-600 italic">
          {workflow.status === "planning" ? "Planner running…" : "No steps yet."}
        </p>
      );
    }
  }

  const steps = [...workflow.steps].sort((a, b) => a.step_order - b.step_order);

  return (
    <div className="space-y-2">
      {steps.map((step) => (
        <div key={step.id} className="flex items-start gap-3 p-2.5 rounded-lg bg-gray-800/60 border border-gray-700/60">
          {/* Step status icon */}
          <div className="mt-0.5 shrink-0">{STEP_STATUS_ICON[step.status]}</div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-semibold text-gray-200">
                {step.step_order}. {step.tool_name ?? "—"}
              </span>
              {step.server_name && (
                <span className="text-xs text-gray-500 font-mono">{step.server_name}</span>
              )}
              {step.latency_ms != null && (
                <span className="text-xs text-gray-600 font-mono ml-auto">{step.latency_ms}ms</span>
              )}
            </div>

            {step.error_message && (
              <p className="text-xs text-red-400 mt-1 truncate" title={step.error_message}>
                {step.error_message}
              </p>
            )}

            {step.output_payload && !step.error_message && (
              <p className="text-xs text-gray-500 mt-1 truncate font-mono">
                {JSON.stringify(step.output_payload).slice(0, 120)}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Workflow detail panel ─────────────────────────────────────────────────────

interface DetailPanelProps {
  workflowId: string;
}

function DetailPanel({ workflowId }: DetailPanelProps) {
  const { data: workflow, isLoading } = useWorkflow(workflowId);
  const isTerminalWorkflow = workflow ? ["completed", "failed", "cancelled"].includes(workflow.status) : false;
  // Don't open a WS for already-terminal workflows — events are ephemeral (Redis pub/sub)
  const { events, isConnected } = useWorkflowStream(isTerminalWorkflow ? null : workflowId);
  const { mutate: approve, isPending: approving } = useApproveCheckpoint();
  const { mutate: reject,  isPending: rejecting  } = useRejectCheckpoint();

  if (isLoading) {
    return (
      <div className="card h-full flex items-center justify-center">
        <Loader2 className="w-5 h-5 text-gray-500 animate-spin" />
      </div>
    );
  }

  if (!workflow) return null;

  const finalAnswer = workflow.result?.answer as string | undefined;
  const isTerminal = ["completed", "failed", "cancelled"].includes(workflow.status);

  return (
    <div className="card space-y-4 overflow-y-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-gray-500 font-mono mb-1">
            {workflow.id.slice(0, 8)}… · {relativeTime(workflow.created_at)}
          </p>
          <h3 className="text-sm font-semibold text-white leading-snug">{workflow.task}</h3>
        </div>
        <span className={STATUS_BADGE[workflow.status]}>
          {statusDot(workflow.status)} {workflow.status}
        </span>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <Zap className="w-3.5 h-3.5" />
          {workflow.total_tokens_used.toLocaleString()} tokens
        </span>
        <span>{workflow.steps.length} step{workflow.steps.length !== 1 ? "s" : ""}</span>
        {!isTerminal && isConnected && (
          <span className="flex items-center gap-1 text-brand-400">
            <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse" />
            live
          </span>
        )}
      </div>

      {/* Checkpoint approval panel */}
      {workflow.status === "awaiting_approval" && (
        <div className="p-3 rounded-lg bg-orange-900/20 border border-orange-700/60">
          <div className="flex items-center gap-2 mb-2">
            <ShieldAlert className="w-4 h-4 text-orange-400" />
            <p className="text-xs font-semibold text-orange-400">Awaiting Your Approval</p>
          </div>
          <p className="text-sm text-gray-300 mb-3">
            The next step requires a write operation. Review the planned action in the event stream, then approve or reject.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => approve(workflow.id)}
              disabled={approving || rejecting}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs font-medium rounded-lg transition-colors"
            >
              {approving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              Approve
            </button>
            <button
              onClick={() => reject(workflow.id)}
              disabled={approving || rejecting}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-800 hover:bg-red-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs font-medium rounded-lg transition-colors"
            >
              {rejecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
              Reject
            </button>
          </div>
        </div>
      )}

      {/* Final answer */}
      {finalAnswer && (
        <div className="p-3 rounded-lg bg-emerald-900/20 border border-emerald-800/50">
          <p className="text-xs font-semibold text-emerald-400 mb-1">Answer</p>
          <p className="text-sm text-gray-200 whitespace-pre-wrap">{finalAnswer}</p>
        </div>
      )}

      {/* Error */}
      {workflow.status === "failed" && workflow.error_message && !finalAnswer && (
        <div className="p-3 rounded-lg bg-red-900/20 border border-red-800/50">
          <p className="text-xs font-semibold text-red-400 mb-1">Error</p>
          <p className="text-sm text-gray-300">{workflow.error_message}</p>
        </div>
      )}

      {/* Step timeline */}
      <div>
        <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wide">Steps</p>
        <StepTimeline workflow={workflow} />
      </div>

      {/* Event stream */}
      <div>
        <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wide">Event Stream</p>
        {isTerminalWorkflow && events.length === 0 ? (
          <p className="text-xs text-gray-600 italic py-2">
            Events are streamed live — open a workflow while it's running to see real-time updates.
          </p>
        ) : (
          <EventLog events={events} isConnected={isConnected} />
        )}
      </div>
    </div>
  );
}

// ── Workflow list item ────────────────────────────────────────────────────────

interface WorkflowRowProps {
  workflow: Workflow;
  isSelected: boolean;
  onSelect: () => void;
}

function WorkflowRow({ workflow, isSelected, onSelect }: WorkflowRowProps) {
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left p-3 rounded-lg border transition-colors ${
        isSelected
          ? "bg-brand-900/30 border-brand-700"
          : "bg-gray-800/40 border-gray-700/60 hover:bg-gray-800 hover:border-gray-600"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-mono text-gray-500">{workflow.id.slice(0, 8)}…</p>
        <span className={STATUS_BADGE[workflow.status]}>
          {statusDot(workflow.status)} {workflow.status}
        </span>
      </div>
      <p className="text-sm text-gray-200 mt-1 line-clamp-2 leading-snug">{workflow.task}</p>
      <p className="text-xs text-gray-600 mt-1">{relativeTime(workflow.created_at)}</p>
    </button>
  );
}

// ── Submit form ───────────────────────────────────────────────────────────────

interface SubmitFormProps {
  onCreated: (id: string) => void;
}

function SubmitForm({ onCreated }: SubmitFormProps) {
  const [task, setTask] = useState("");
  const { mutateAsync, isPending, error } = useCreateWorkflow();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!task.trim()) return;
    try {
      const wf = await mutateAsync({ task: task.trim(), actor: "user" });
      setTask("");
      onCreated(wf.id);
    } catch {
      // error displayed below
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <textarea
        value={task}
        onChange={(e) => setTask(e.target.value)}
        placeholder="Describe a task, e.g. 'List all open PRs in my repos and post a summary to Slack #dev'"
        rows={3}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-brand-500 resize-none"
        disabled={isPending}
      />
      {error && (
        <p className="text-xs text-red-400">
          {(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to create workflow."}
        </p>
      )}
      <button
        type="submit"
        disabled={isPending || !task.trim()}
        className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors"
      >
        {isPending ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Play className="w-4 h-4" />
        )}
        {isPending ? "Starting…" : "Run Workflow"}
      </button>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function WorkflowsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data, isLoading, refetch } = useWorkflows();

  return (
    <div className="space-y-4 h-full flex flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <GitBranch className="w-5 h-5 text-brand-400" />
            Workflows
          </h2>
          <p className="text-sm text-gray-400 mt-0.5">
            LangGraph-powered multi-tool executions — planner → executor → reviewer
          </p>
        </div>
        <button
          onClick={() => void refetch()}
          className="p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Main two-panel layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0">

        {/* Left: submit + list */}
        <div className="space-y-4 overflow-y-auto">
          {/* Submit form */}
          <div className="card">
            <h3 className="text-sm font-semibold text-white mb-3">New Workflow</h3>
            <SubmitForm onCreated={(id) => setSelectedId(id)} />
          </div>

          {/* Workflow list */}
          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-white">Recent Workflows</h3>
              {data && (
                <span className="text-xs text-gray-500">{data.total} total</span>
              )}
            </div>

            {isLoading ? (
              <div className="flex items-center justify-center py-6">
                <Loader2 className="w-5 h-5 text-gray-500 animate-spin" />
              </div>
            ) : !data || data.items.length === 0 ? (
              <p className="text-sm text-gray-600 text-center py-4">
                No workflows yet — submit one above.
              </p>
            ) : (
              <div className="space-y-2">
                {data.items.map((wf) => (
                  <WorkflowRow
                    key={wf.id}
                    workflow={wf}
                    isSelected={selectedId === wf.id}
                    onSelect={() => setSelectedId(wf.id)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: detail panel */}
        <div className="min-h-0">
          {selectedId ? (
            <DetailPanel workflowId={selectedId} />
          ) : (
            <div className="card h-full flex flex-col items-center justify-center text-center gap-3 py-12">
              <GitBranch className="w-10 h-10 text-gray-700" />
              <div>
                <p className="text-sm font-medium text-gray-500">No workflow selected</p>
                <p className="text-xs text-gray-600 mt-1">
                  Submit a task or click a workflow from the list to view details.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
