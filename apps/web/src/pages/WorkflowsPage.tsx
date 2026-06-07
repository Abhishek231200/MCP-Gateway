import { useState, useRef, useEffect, useCallback } from "react";
import { useSearchParams, useLocation } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import {
  ArrowUp, Loader2, CheckCircle2, XCircle, Clock, Zap,
  ShieldAlert, SkipForward, ShieldCheck, User, AlertTriangle,
  ChevronRight, RotateCcw,
} from "lucide-react";
import {
  useWorkflow,
  useConversation,
  useCreateWorkflow,
  useAnalyzeWorkflow,
  useWorkflowStream,
  useApproveCheckpoint,
  useRejectCheckpoint,
  type Workflow,
  type StreamEvent,
  type WorkflowStatus,
  type StepStatus,
  type AnalyzeResponse,
  type AnalyzeQuestion,
} from "@/hooks/useWorkflows";

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

const STATUS_COLOR: Record<WorkflowStatus, string> = {
  pending:           "text-slate-500",
  planning:          "text-amber-400",
  running:           "text-brand-400",
  awaiting_approval: "text-orange-400",
  completed:         "text-emerald-400",
  failed:            "text-red-400",
  cancelled:         "text-slate-500",
};

const STEP_ICON: Record<StepStatus, React.ReactNode> = {
  pending:   <Clock className="w-3.5 h-3.5 text-slate-500" />,
  running:   <Loader2 className="w-3.5 h-3.5 text-brand-400 animate-spin" />,
  completed: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
  failed:    <XCircle className="w-3.5 h-3.5 text-red-400" />,
  skipped:   <SkipForward className="w-3.5 h-3.5 text-slate-500" />,
};

function eventLabel(event: StreamEvent): string {
  switch (event.type) {
    case "status_change":       return `Status → ${event.status}`;
    case "plan_ready":          return `Plan ready — ${event.step_count} step${(event.step_count as number) !== 1 ? "s" : ""}`;
    case "step_started":        return `${event.server}.${event.tool}`;
    case "step_completed":      return `Done (${event.latency_ms}ms)`;
    case "step_failed":         return `Failed: ${event.error}`;
    case "step_denied":         return `Denied: ${event.reason}`;
    case "step_skipped":        return `Skipped — ${event.reason}`;
    case "checkpoint_reached":  return `Approval required: ${event.server}.${event.tool}`;
    case "checkpoint_approved": return `Approved — continuing`;
    case "checkpoint_rejected": return `Rejected — cancelled`;
    case "review_started":      return "Reviewing…";
    case "replanning":          return `Replanning: ${event.feedback}`;
    case "workflow_completed":  return "Completed";
    case "workflow_failed":     return `Failed: ${event.error}`;
    default:                    return event.type;
  }
}

function eventColor(e: StreamEvent): string {
  if (["workflow_completed","step_completed","checkpoint_approved"].includes(e.type)) return "text-emerald-400";
  if (["workflow_failed","step_failed","checkpoint_rejected","step_denied"].includes(e.type)) return "text-red-400";
  if (e.type === "checkpoint_reached") return "text-orange-300";
  if (e.type === "plan_ready") return "text-brand-300";
  if (["review_started","replanning"].includes(e.type)) return "text-amber-300";
  if (e.type === "step_skipped") return "text-slate-500";
  return "text-slate-500";
}

// ── Collapsible steps (like Claude "thinking") ────────────────────────────────

function CollapsibleSteps({ workflow, events, isRunning }: {
  workflow: Workflow;
  events: StreamEvent[];
  isRunning: boolean;
}) {
  const [open, setOpen] = useState(false);
  const steps = [...workflow.steps].sort((a, b) => a.step_order - b.step_order);
  const hasSteps = steps.length > 0;
  const hasLiveEvents = events.length > 0;

  if (!hasSteps && !hasLiveEvents && !isRunning) return null;

  const completedCount = steps.filter(s => s.status === "completed").length;
  const failedCount    = steps.filter(s => s.status === "failed").length;
  const totalMs        = steps.reduce((s, step) => s + (step.latency_ms ?? 0), 0);

  const summaryText = isRunning && !hasSteps
    ? "Working…"
    : hasSteps
    ? `${steps.length} tool${steps.length !== 1 ? "s" : ""} used · ${(totalMs / 1000).toFixed(1)}s`
    : "Running…";

  return (
    <div className="my-3">
      <button
        onClick={() => setOpen(v => !v)}
        className={`thinking-toggle ${open ? "open" : ""}`}
        aria-expanded={open}
      >
        {isRunning && !open ? (
          <Loader2 className="w-3.5 h-3.5 text-brand-400 animate-spin" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" />
        )}
        <span>{summaryText}</span>
        {failedCount > 0 && (
          <span className="text-red-400">· {failedCount} failed</span>
        )}
      </button>

      {open && (
        <div className="mt-2 pl-2 space-y-1.5 animate-fade-in">
          {/* Completed steps */}
          {steps.map((step) => (
            <div
              key={step.id}
              className="flex items-center gap-2.5 px-3 py-2 rounded-xl"
              style={{
                background: step.status === "failed"
                  ? "rgba(244,63,94,0.06)"
                  : step.status === "completed"
                  ? "rgba(16,185,129,0.04)"
                  : "var(--surface-3)",
                border: `1px solid ${
                  step.status === "failed"    ? "rgba(244,63,94,0.15)"
                  : step.status === "completed" ? "rgba(16,185,129,0.10)"
                  : "var(--border)"}`,
              }}
            >
              <span className="shrink-0">{STEP_ICON[step.status]}</span>
              <span className="text-xs font-medium shrink-0" style={{ color: "var(--text-high)" }}>
                {step.step_order}. {step.tool_name ?? "—"}
              </span>
              {step.server_name && (
                <span className="text-xs font-mono truncate" style={{ color: "var(--text-low)" }}>
                  {step.server_name}
                </span>
              )}
              <span className="ml-auto text-[11px] font-mono shrink-0" style={{ color: "var(--text-low)" }}>
                {step.latency_ms != null ? `${step.latency_ms}ms` : ""}
              </span>
              {step.error_message && (
                <span className="text-xs text-rose-400 truncate max-w-[160px]" title={step.error_message}>
                  {step.error_message}
                </span>
              )}
            </div>
          ))}

          {/* Live event log while running */}
          {hasLiveEvents && (
            <div className="mt-1 rounded-lg px-3 py-2 space-y-1"
              style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
              {events.slice(-6).map((e, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px] font-mono">
                  <span className="shrink-0 tabular-nums" style={{ color: "var(--text-low)" }}>
                    {e.timestamp ? new Date(e.timestamp as string).toLocaleTimeString() : "--:--"}
                  </span>
                  <span className={eventColor(e)}>{eventLabel(e)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Running dots ──────────────────────────────────────────────────────────────

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1.5 py-2 px-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-2 h-2 rounded-full animate-pulse"
          style={{
            background: "#0ea5e9",
            animationDelay: `${i * 200}ms`,
            boxShadow: "0 0 6px rgba(14,165,233,0.5)",
          }}
        />
      ))}
    </div>
  );
}

// ── Single workflow turn ──────────────────────────────────────────────────────

function ConversationView({ workflowId, onRetry }: {
  workflowId: string;
  onRetry: (task: string) => void;
}) {
  const { data: workflow, isLoading } = useWorkflow(workflowId);
  const isTerminal = workflow ? ["completed","failed","cancelled"].includes(workflow.status) : false;
  const { events, isConnected } = useWorkflowStream(isTerminal ? null : workflowId);
  const { mutate: approve, isPending: approving } = useApproveCheckpoint();
  const { mutate: reject, isPending: rejecting } = useRejectCheckpoint();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length, workflow?.status]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: "var(--text-low)" }} />
      </div>
    );
  }
  if (!workflow) return null;

  const rawAnswer = workflow.result?.answer;
  const finalAnswer = rawAnswer
    ? typeof rawAnswer === "string" ? rawAnswer : JSON.stringify(rawAnswer, null, 2)
    : undefined;

  const isRunning = ["pending","planning","running"].includes(workflow.status);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-4 animate-slide-up">

      {/* ── User message — right aligned ── */}
      <div className="flex justify-end">
        <div className="max-w-[75%]">
          <div className="px-4 py-3 rounded-2xl rounded-tr-md text-sm leading-relaxed"
            style={{
              background: "var(--surface-3)",
              border: "1px solid var(--border-mid)",
              color: "var(--text-high)",
            }}>
            {workflow.task}
          </div>
          <p className="text-[11px] mt-1 text-right" style={{ color: "var(--text-low)" }}>
            {relativeTime(workflow.created_at)}
          </p>
        </div>
      </div>

      {/* ── AI response — left aligned ── */}
      <div className="flex gap-3">
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5"
          style={{
            background: "linear-gradient(135deg,#0ea5e9,#0284c7)",
            boxShadow: "0 0 10px rgba(14,165,233,0.25)",
          }}
        >
          <ShieldCheck className="w-4 h-4 text-white" />
        </div>

        <div className="flex-1 min-w-0 pt-1">

          {/* Status pill */}
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs font-semibold ${STATUS_COLOR[workflow.status]}`}>
              {workflow.status.replace(/_/g, " ")}
            </span>
            {workflow.total_tokens_used > 0 && (
              <span className="flex items-center gap-1 text-[11px]" style={{ color: "var(--text-low)" }}>
                <Zap className="w-3 h-3" />
                {workflow.total_tokens_used.toLocaleString()}
              </span>
            )}
            {!isTerminal && isConnected && (
              <span className="flex items-center gap-1 text-[11px]" style={{ color: "#0ea5e9" }}>
                <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse" />
                live
              </span>
            )}
          </div>

          {/* Thinking / steps dropdown */}
          {isRunning && workflow.steps.length === 0
            ? <ThinkingDots />
            : <CollapsibleSteps workflow={workflow} events={events} isRunning={isRunning} />
          }

          {/* Checkpoint approval */}
          {workflow.status === "awaiting_approval" && (
            <div className="p-4 rounded-xl mb-3"
              style={{ background: "rgba(251,146,60,0.06)", border: "1px solid rgba(251,146,60,0.2)" }}>
              <div className="flex items-center gap-2 mb-2">
                <ShieldAlert className="w-4 h-4 text-orange-400 shrink-0" />
                <p className="text-sm font-semibold text-orange-300">Approval Required</p>
              </div>
              <p className="text-xs mb-3" style={{ color: "var(--text-mid)" }}>
                A write operation is queued. Review the steps above, then approve or reject.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => approve(workflow.id)}
                  disabled={approving || rejecting}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white disabled:opacity-40 transition-all"
                  style={{ background: "#10b981" }}
                >
                  {approving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                  Approve
                </button>
                <button
                  onClick={() => reject(workflow.id)}
                  disabled={approving || rejecting}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white disabled:opacity-40 transition-all"
                  style={{ background: "#f43f5e" }}
                >
                  {rejecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
                  Reject
                </button>
              </div>
            </div>
          )}

          {/* Final answer */}
          {finalAnswer && (
            <div className="mt-2 rounded-xl p-4"
              style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
              <style>{`
                .md-answer p { margin-bottom: 0.7rem; line-height: 1.65; color: var(--text-high); }
                .md-answer ul, .md-answer ol { margin-bottom: 0.7rem; padding-left: 1.25rem; }
                .md-answer li { margin-bottom: 0.25rem; color: var(--text-high); }
                .md-answer h1, .md-answer h2, .md-answer h3 { font-weight: 600; margin-bottom: 0.5rem; color: var(--text-high); }
                .md-answer h1 { font-size: 1rem; } .md-answer h2 { font-size: 0.9rem; } .md-answer h3 { font-size: 0.85rem; }
                .md-answer table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 0.75rem; }
                .md-answer th { text-align: left; color: var(--text-low); font-weight: 600; border-bottom: 1px solid var(--border-mid); padding: 6px 12px 6px 0; font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; }
                .md-answer td { padding: 6px 12px 6px 0; border-bottom: 1px solid var(--border); color: var(--text-mid); }
                .md-answer pre { background: var(--surface-1); border: 1px solid var(--border); padding: 12px; border-radius: 8px; font-size: 12px; overflow-x: auto; margin-bottom: 0.75rem; }
                .md-answer code { background: rgba(14,165,233,0.10); padding: 2px 6px; border-radius: 4px; font-size: 12px; color: #38bdf8; }
                .md-answer a { color: #38bdf8; text-decoration: underline; text-decoration-color: rgba(56,189,248,0.3); }
                .md-answer blockquote { border-left: 2px solid #0ea5e9; padding-left: 12px; color: var(--text-mid); font-style: italic; }
              `}</style>
              <div className="md-answer prose prose-invert prose-sm max-w-none text-sm">
                <ReactMarkdown>{finalAnswer}</ReactMarkdown>
              </div>
            </div>
          )}

          {/* Error */}
          {workflow.status === "failed" && workflow.error_message && !finalAnswer && (
            <div className="flex items-start gap-3 p-3.5 rounded-xl"
              style={{ background: "rgba(244,63,94,0.06)", border: "1px solid rgba(244,63,94,0.15)" }}>
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <p className="text-sm" style={{ color: "var(--text-mid)" }}>{workflow.error_message}</p>
            </div>
          )}

          {/* Retry button — shown after failure */}
          {workflow.status === "failed" && (
            <button
              onClick={() => onRetry(workflow.task)}
              className="flex items-center gap-1.5 mt-3 text-xs transition-all rounded-lg px-3 py-1.5"
              style={{ background: "var(--surface-3)", border: "1px solid var(--border)", color: "var(--text-mid)" }}
              onMouseOver={e => { e.currentTarget.style.borderColor = "rgba(14,165,233,0.25)"; e.currentTarget.style.color = "var(--text-high)"; }}
              onMouseOut={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--text-mid)"; }}
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Retry
            </button>
          )}
        </div>
      </div>

      <div ref={bottomRef} />
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

const SUGGESTIONS = [
  "List open PRs in Abhishek231200/mcp-gateway-backend and post a summary to Slack",
  "Get the active sprint issues in MGORCH and summarize their status",
  "List recent commits in mcp-gateway-backend and create a Jira ticket summarizing the changes",
];

function EmptyState({ onSuggest }: { onSuggest: (text: string) => void }) {
  return (
    <div
      className="flex flex-col items-center justify-center h-full text-center px-4 pb-24"
      style={{
        backgroundImage: "radial-gradient(rgba(14,165,233,0.06) 1px, transparent 1px)",
        backgroundSize: "28px 28px",
      }}
    >
      <div className="mb-6 animate-float">
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center"
          style={{
            background: "linear-gradient(135deg, rgba(14,165,233,0.18), rgba(2,132,199,0.08))",
            border: "1px solid rgba(14,165,233,0.22)",
            boxShadow: "0 0 40px rgba(14,165,233,0.12)",
          }}>
          <ShieldCheck className="w-8 h-8 text-brand-400" />
        </div>
      </div>

      <h2 className="text-2xl font-semibold mb-2" style={{ color: "var(--text-high)", letterSpacing: "-0.02em" }}>
        What would you like to orchestrate?
      </h2>
      <p className="text-sm max-w-sm leading-relaxed" style={{ color: "var(--text-mid)" }}>
        Describe a task and MCP Gateway will plan, execute, and review it across your connected tools.
      </p>

      <div className="flex items-center gap-2 mt-4 flex-wrap justify-center">
        {["GitHub", "Jira", "Slack", "Google Drive", "Knowledge Base"].map((t) => (
          <span key={t} className="chip text-xs">{t}</span>
        ))}
      </div>

      <div className="mt-6 flex flex-col gap-2 w-full max-w-lg">
        {SUGGESTIONS.map((hint) => (
          <button
            key={hint}
            className="text-left text-xs px-4 py-3 rounded-xl transition-all duration-150"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--text-mid)" }}
            onMouseOver={e => {
              e.currentTarget.style.background = "rgba(14,165,233,0.06)";
              e.currentTarget.style.borderColor = "rgba(14,165,233,0.2)";
              e.currentTarget.style.color = "var(--text-high)";
            }}
            onMouseOut={e => {
              e.currentTarget.style.background = "var(--surface-2)";
              e.currentTarget.style.borderColor = "var(--border)";
              e.currentTarget.style.color = "var(--text-mid)";
            }}
            onClick={() => onSuggest(hint)}
          >
            {hint}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Searchable select ─────────────────────────────────────────────────────────

interface SearchableSelectProps {
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}

function SearchableSelect({ options, value, onChange, placeholder = "Search…" }: SearchableSelectProps) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = options.find((o) => o.value === value);
  const filtered = options.filter((o) => o.label.toLowerCase().includes(search.toLowerCase()));

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false); setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={containerRef} className="relative max-w-sm">
      <div
        onClick={() => { setOpen(true); setTimeout(() => inputRef.current?.focus(), 10); }}
        className="flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer transition-all"
        style={{
          background: "var(--surface-3)",
          border: `1px solid ${open ? "rgba(14,165,233,0.35)" : "var(--border)"}`,
        }}
      >
        {selected ? (
          <>
            <span className="text-sm flex-1 truncate" style={{ color: "var(--text-high)" }}>{selected.label}</span>
            <button
              onClick={(e) => { e.stopPropagation(); onChange(""); setSearch(""); }}
              style={{ color: "var(--text-low)" }}
            >×</button>
          </>
        ) : (
          <span className="text-sm" style={{ color: "var(--text-low)" }}>{placeholder}</span>
        )}
      </div>
      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 rounded-xl shadow-2xl z-50 overflow-hidden"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border-mid)" }}>
          <div className="p-2" style={{ borderBottom: "1px solid var(--border)" }}>
            <input
              ref={inputRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search…"
              className="w-full rounded-lg px-2.5 py-1.5 text-sm focus:outline-none"
              style={{ background: "var(--surface-3)", color: "var(--text-high)" }}
            />
          </div>
          <div className="max-h-48 overflow-y-auto">
            {filtered.length === 0
              ? <p className="px-3 py-2.5 text-sm" style={{ color: "var(--text-low)" }}>No results</p>
              : filtered.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => { onChange(opt.value); setOpen(false); setSearch(""); }}
                  className="w-full text-left px-3 py-2 text-sm transition-colors"
                  style={opt.value === value
                    ? { background: "rgba(14,165,233,0.12)", color: "#38bdf8" }
                    : { color: "var(--text-mid)" }
                  }
                >
                  {opt.label}
                </button>
              ))
            }
          </div>
        </div>
      )}
    </div>
  );
}

// ── Clarification card ────────────────────────────────────────────────────────

function enrichTask(task: string, answers: Record<string, string>, analysis: AnalyzeResponse): string {
  const parts: string[] = [];
  if (answers.github_pr_number) parts.push(`PR number ${answers.github_pr_number.trim().replace(/^#/, "")}`);
  if (answers.jira_issue_key)   parts.push(`for Jira issue ${answers.jira_issue_key.trim().toUpperCase()}`);
  if (answers.jira_project)     parts.push(`use Jira project key ${answers.jira_project}`);
  if (answers.jira_priority)    parts.push(`set priority to ${answers.jira_priority}`);
  if (answers.jira_assignee) {
    const q = analysis.questions.find((q) => q.id === "jira_assignee");
    const label = q?.options.find((o) => o.value === answers.jira_assignee)?.label;
    parts.push(`assign to accountId=${answers.jira_assignee}${label ? ` (${label})` : ""}`);
  }
  if (answers.slack_channel) parts.push(`post to Slack channel #${answers.slack_channel.replace(/^#/, "")}`);
  return parts.length ? `${task}. ${parts.join(", ")}.` : task;
}

interface ClarificationCardProps {
  task: string;
  analysis: AnalyzeResponse;
  onConfirm: (enrichedTask: string) => void;
  onSkip: () => void;
}

function ClarificationCard({ task, analysis, onConfirm, onSkip }: ClarificationCardProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const setAnswer = (id: string, v: string) => setAnswers(p => ({ ...p, [id]: v }));
  const canConfirm = analysis.questions.filter(q => q.required).every(q => answers[q.id]?.trim());

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 animate-slide-up">
      {/* User message — right aligned */}
      <div className="flex justify-end mb-4">
        <div className="max-w-[75%] px-4 py-3 rounded-2xl rounded-tr-md text-sm leading-relaxed"
          style={{ background: "var(--surface-3)", border: "1px solid var(--border-mid)", color: "var(--text-high)" }}>
          {task}
        </div>
      </div>

      {/* AI clarification */}
      <div className="flex gap-3">
        <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5"
          style={{ background: "linear-gradient(135deg,#0ea5e9,#0284c7)", boxShadow: "0 0 10px rgba(14,165,233,0.25)" }}>
          <ShieldCheck className="w-4 h-4 text-white" />
        </div>
        <div className="flex-1">
          <p className="text-sm mb-5" style={{ color: "var(--text-mid)" }}>
            A few details before I start:
          </p>
          <div className="space-y-5">
            {analysis.questions.map((q: AnalyzeQuestion) => (
              <div key={q.id}>
                <label className="block text-xs font-semibold mb-0.5" style={{ color: "var(--text-high)" }}>
                  {q.label}{q.required && <span className="text-rose-400 ml-1">*</span>}
                </label>
                <p className="text-xs mb-2" style={{ color: "var(--text-low)" }}>{q.description}</p>
                {q.type === "searchable_select" ? (
                  <SearchableSelect options={q.options} value={answers[q.id] ?? ""} onChange={v => setAnswer(q.id, v)} placeholder={q.placeholder || "Search…"} />
                ) : q.type === "select" ? (
                  <div className="flex flex-wrap gap-2">
                    {q.options.map(opt => (
                      <button key={opt.value} onClick={() => setAnswer(q.id, opt.value)}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150"
                        style={answers[q.id] === opt.value
                          ? { background: "rgba(14,165,233,0.15)", border: "1px solid rgba(14,165,233,0.35)", color: "#38bdf8" }
                          : { background: "var(--surface-3)", border: "1px solid var(--border)", color: "var(--text-mid)" }
                        }
                      >{opt.label}</button>
                    ))}
                  </div>
                ) : (
                  <input value={answers[q.id] ?? ""} onChange={e => setAnswer(q.id, e.target.value)}
                    placeholder={q.placeholder} className="input max-w-sm text-sm" />
                )}
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-6">
            <button onClick={() => onConfirm(enrichTask(task, answers, analysis))} disabled={!canConfirm} className="btn-primary text-sm gap-1.5">
              <ArrowUp className="w-3.5 h-3.5" /> Confirm & Run
            </button>
            <button onClick={onSkip} className="btn-secondary text-sm">Skip & Run anyway</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Input bar ─────────────────────────────────────────────────────────────────

interface InputBarProps {
  task: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  isPending: boolean;
  error?: string;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

function InputBar({ task, onChange, onSubmit, isPending, error, inputRef }: InputBarProps) {
  const localRef = useRef<HTMLTextAreaElement>(null);
  const textareaRef = inputRef ?? localRef;
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [task]);

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value);
  }, [onChange]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      // Enter = submit (Shift+Enter = new line, falls through to default)
      e.preventDefault();
      if (!isPending && task.trim()) onSubmit();
    }
  };

  return (
    <div className="flex-none px-4 py-4" style={{ borderTop: "1px solid var(--border)", background: "var(--bg)" }}>
      <div className="max-w-3xl mx-auto">
        {error && <p className="text-xs text-rose-400 mb-2 px-1">{error}</p>}
        <div
          className="relative rounded-2xl transition-all duration-200"
          style={{
            background: "var(--surface-2)",
            border: `1px solid ${focused ? "rgba(14,165,233,0.4)" : "rgba(14,165,233,0.10)"}`,
            boxShadow: focused
              ? "0 0 0 3px rgba(14,165,233,0.07), 0 4px 20px rgba(0,0,0,0.25)"
              : "0 2px 10px rgba(0,0,0,0.2)",
          }}
        >
          <textarea
            ref={textareaRef}
            data-input
            value={task}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder="Describe a task… (Enter to send, Shift+Enter for new line)"
            rows={1}
            disabled={isPending}
            className="w-full bg-transparent resize-none px-4 pt-3.5 pb-12 text-sm focus:outline-none disabled:opacity-50 leading-relaxed"
            style={{ maxHeight: "200px", minHeight: "52px", color: "var(--text-high)" }}
          />
          <div className="absolute bottom-3 right-3 flex items-center gap-2">
            <span className="text-[11px] hidden sm:block" style={{ color: "var(--text-low)" }}>⇧↵ new line</span>
            <button
              onClick={onSubmit}
              disabled={isPending || !task.trim()}
              className="p-2 rounded-xl transition-all duration-150 disabled:opacity-30"
              style={task.trim() && !isPending
                ? { background: "linear-gradient(135deg,#0ea5e9,#0284c7)", boxShadow: "0 0 10px rgba(14,165,233,0.35)", color: "#fff" }
                : { background: "var(--surface-4)", color: "var(--text-low)" }
              }
            >
              {isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowUp className="w-4 h-4" />}
            </button>
          </div>
        </div>
        <p className="text-center text-[11px] mt-2" style={{ color: "var(--text-low)" }}>
          Review write operations before approving — MCP Gateway can make mistakes.
        </p>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function WorkflowsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();

  const [convId, setConvId] = useState<string | null>(searchParams.get("conv"));

  useEffect(() => {
    setConvId(searchParams.get("conv"));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  const { data: conversationItems } = useConversation(convId);

  const [task, setTask] = useState("");
  const [submitError, setSubmitError] = useState<string | undefined>();
  const [pendingClarification, setPendingClarification] = useState<{ task: string; analysis: AnalyzeResponse } | null>(null);
  const { mutateAsync, isPending } = useCreateWorkflow();
  const { mutateAsync: analyze, isPending: analyzing } = useAnalyzeWorkflow();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversationItems?.length]);

  const _createAndAppend = async (finalTask: string) => {
    const wf = await mutateAsync({ task: finalTask, actor: "user", conversation_id: convId });
    if (!convId) {
      setConvId(wf.id);
      setSearchParams({ conv: wf.id });
    }
  };

  const handleSubmit = async () => {
    if (!task.trim() || isPending || analyzing) return;
    setSubmitError(undefined);
    const trimmed = task.trim();
    try {
      const result = await analyze({ task: trimmed, actor: "user" });
      if (result.needs_clarification) {
        setPendingClarification({ task: trimmed, analysis: result });
        setTask("");
      } else {
        setTask("");
        await _createAndAppend(trimmed);
      }
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(detail ?? "Failed to start workflow. Check the API is running.");
    }
  };

  const handleRetry = async (retryTask: string) => {
    setSubmitError(undefined);
    try {
      await _createAndAppend(retryTask);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(detail ?? "Failed to retry.");
    }
  };

  const handleClarifyConfirm = async (enrichedTask: string) => {
    setPendingClarification(null);
    setSubmitError(undefined);
    try { await _createAndAppend(enrichedTask); }
    catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(detail ?? "Failed to start workflow.");
    }
  };

  const handleClarifySkip = async () => {
    if (!pendingClarification) return;
    const t = pendingClarification.task;
    setPendingClarification(null);
    try { await _createAndAppend(t); }
    catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(detail ?? "Failed to start workflow.");
    }
  };

  const items = conversationItems ?? [];
  const showEmpty = !convId && items.length === 0 && !pendingClarification;

  return (
    <div className="h-full flex flex-col" style={{ background: "var(--bg)" }}>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {showEmpty ? (
          <EmptyState onSuggest={(text) => { setTask(text); setTimeout(() => inputRef.current?.focus(), 50); }} />
        ) : (
          <>
            {items.map((wf, idx) => (
              <div key={wf.id}>
                <ConversationView workflowId={wf.id} onRetry={handleRetry} />
                {idx < items.length - 1 && (
                  <div className="mx-12 my-1" style={{
                    height: "1px",
                    background: "linear-gradient(90deg, transparent, rgba(14,165,233,0.12), transparent)",
                  }} />
                )}
              </div>
            ))}
            {pendingClarification && (
              <>
                {items.length > 0 && (
                  <div className="mx-12 my-1" style={{
                    height: "1px",
                    background: "linear-gradient(90deg, transparent, rgba(14,165,233,0.12), transparent)",
                  }} />
                )}
                <ClarificationCard
                  task={pendingClarification.task}
                  analysis={pendingClarification.analysis}
                  onConfirm={handleClarifyConfirm}
                  onSkip={handleClarifySkip}
                />
              </>
            )}
            <div ref={threadEndRef} className="h-4" />
          </>
        )}
      </div>

      <InputBar
        task={task}
        onChange={setTask}
        onSubmit={handleSubmit}
        isPending={isPending || analyzing}
        error={submitError}
        inputRef={inputRef}
      />
    </div>
  );
}
