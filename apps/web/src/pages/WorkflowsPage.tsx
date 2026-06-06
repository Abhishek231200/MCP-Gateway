import { useState, useRef, useEffect, useCallback } from "react";
import { useSearchParams, useNavigate, useLocation } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import {
  ArrowUp, Loader2, CheckCircle2, XCircle, Clock, Zap,
  ShieldAlert, SkipForward, ShieldCheck, User, AlertTriangle,
} from "lucide-react";
import {
  useWorkflow,
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
  pending:           "text-gray-500",
  planning:          "text-yellow-400",
  running:           "text-brand-400",
  awaiting_approval: "text-orange-400",
  completed:         "text-emerald-400",
  failed:            "text-red-400",
  cancelled:         "text-gray-500",
};

const STEP_ICON: Record<StepStatus, React.ReactNode> = {
  pending:   <Clock className="w-3.5 h-3.5 text-gray-600" />,
  running:   <Loader2 className="w-3.5 h-3.5 text-brand-400 animate-spin" />,
  completed: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
  failed:    <XCircle className="w-3.5 h-3.5 text-red-400" />,
  skipped:   <SkipForward className="w-3.5 h-3.5 text-gray-600" />,
};

function eventLabel(event: StreamEvent): string {
  switch (event.type) {
    case "status_change":       return `Status → ${event.status}`;
    case "plan_ready":          return `Plan ready — ${event.step_count} step${(event.step_count as number) !== 1 ? "s" : ""}`;
    case "step_started":        return `Step ${event.step}: ${event.server}.${event.tool}`;
    case "step_completed":      return `Step ${event.step} done (${event.latency_ms}ms)`;
    case "step_failed":         return `Step ${event.step} failed: ${event.error}`;
    case "step_denied":         return `Step ${event.step} denied: ${event.reason}`;
    case "step_skipped":        return `Step ${event.step} skipped — ${event.reason}`;
    case "checkpoint_reached":  return `Approval required: step ${event.step} (${event.server}.${event.tool})`;
    case "checkpoint_approved": return `Checkpoint approved — proceeding`;
    case "checkpoint_rejected": return `Checkpoint rejected — cancelled`;
    case "review_started":      return "Reviewing results…";
    case "replanning":          return `Replanning: ${event.feedback}`;
    case "workflow_completed":  return "Completed";
    case "workflow_failed":     return `Failed: ${event.error}`;
    default:                    return event.type;
  }
}

function eventColor(e: StreamEvent): string {
  if (e.type === "workflow_completed" || e.type === "step_completed" || e.type === "checkpoint_approved") return "text-emerald-400";
  if (e.type === "workflow_failed" || e.type === "step_failed" || e.type === "checkpoint_rejected" || e.type === "step_denied") return "text-red-400";
  if (e.type === "checkpoint_reached") return "text-orange-300";
  if (e.type === "plan_ready") return "text-brand-300";
  if (e.type === "review_started" || e.type === "replanning") return "text-yellow-300";
  if (e.type === "step_skipped") return "text-gray-600";
  return "text-gray-500";
}

// ── Step timeline ─────────────────────────────────────────────────────────────

function StepList({ workflow }: { workflow: Workflow }) {
  const steps = [...workflow.steps].sort((a, b) => a.step_order - b.step_order);

  if (steps.length === 0) {
    const planSteps = (workflow.plan as { steps?: unknown[] })?.steps;
    if (!planSteps?.length) return null;
  }

  return (
    <div className="space-y-1.5 my-3">
      {steps.map((step) => (
        <div
          key={step.id}
          className="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/5"
        >
          <span className="shrink-0">{STEP_ICON[step.status]}</span>
          <span className="text-xs font-medium text-gray-300 shrink-0">
            {step.step_order}. {step.tool_name ?? "—"}
          </span>
          {step.server_name && (
            <span className="text-xs text-gray-600 font-mono truncate">{step.server_name}</span>
          )}
          <span className="ml-auto text-[11px] text-gray-700 font-mono shrink-0">
            {step.latency_ms != null ? `${step.latency_ms}ms` : ""}
          </span>
          {step.error_message && (
            <span className="text-xs text-red-400 truncate max-w-[200px]" title={step.error_message}>
              {step.error_message}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Running indicator ─────────────────────────────────────────────────────────

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-gray-600 animate-pulse"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </div>
  );
}

// ── Main conversation view ────────────────────────────────────────────────────

function ConversationView({ workflowId }: { workflowId: string }) {
  const { data: workflow, isLoading } = useWorkflow(workflowId);
  const isTerminal = workflow ? ["completed", "failed", "cancelled"].includes(workflow.status) : false;
  const { events, isConnected } = useWorkflowStream(isTerminal ? null : workflowId);
  const { mutate: approve, isPending: approving } = useApproveCheckpoint();
  const { mutate: reject, isPending: rejecting } = useRejectCheckpoint();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length, workflow?.status]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-5 h-5 text-gray-600 animate-spin" />
      </div>
    );
  }

  if (!workflow) return null;

  const rawAnswer = workflow.result?.answer;
  const finalAnswer = rawAnswer
    ? typeof rawAnswer === "string" ? rawAnswer : JSON.stringify(rawAnswer, null, 2)
    : undefined;

  const isRunning = ["pending", "planning", "running"].includes(workflow.status);

  return (
    <div className="max-w-3xl mx-auto px-4 pt-8 pb-4">

      {/* User message */}
      <div className="flex gap-3 mb-6">
        <div className="w-8 h-8 rounded-full bg-[#2a2a2a] border border-white/10 flex items-center justify-center shrink-0 mt-0.5">
          <User className="w-4 h-4 text-gray-400" />
        </div>
        <div className="flex-1 min-w-0 pt-1">
          <p className="text-sm text-gray-200 leading-relaxed">{workflow.task}</p>
          <p className="text-[11px] text-gray-700 mt-1.5">{relativeTime(workflow.created_at)}</p>
        </div>
      </div>

      {/* Assistant response */}
      <div className="flex gap-3">
        <div className="w-8 h-8 rounded-full bg-brand-900/40 border border-brand-700/30 flex items-center justify-center shrink-0 mt-0.5">
          <ShieldCheck className="w-4 h-4 text-brand-400" />
        </div>

        <div className="flex-1 min-w-0 pt-1">

          {/* Status line */}
          <div className="flex items-center gap-2 mb-2">
            <span className={`text-xs font-medium ${STATUS_COLOR[workflow.status]}`}>
              {workflow.status.replace("_", " ")}
            </span>
            {workflow.total_tokens_used > 0 && (
              <span className="flex items-center gap-1 text-[11px] text-gray-700">
                <Zap className="w-3 h-3" />
                {workflow.total_tokens_used.toLocaleString()} tokens
              </span>
            )}
            {!isTerminal && isConnected && (
              <span className="flex items-center gap-1 text-[11px] text-brand-500">
                <span className="w-1.5 h-1.5 rounded-full bg-brand-500 animate-pulse" />
                live
              </span>
            )}
          </div>

          {/* Thinking indicator */}
          {isRunning && workflow.steps.length === 0 && <ThinkingDots />}

          {/* Steps */}
          <StepList workflow={workflow} />

          {/* Checkpoint approval */}
          {workflow.status === "awaiting_approval" && (
            <div className="p-3.5 rounded-xl bg-orange-500/5 border border-orange-500/20 mb-3">
              <div className="flex items-center gap-2 mb-2">
                <ShieldAlert className="w-4 h-4 text-orange-400 shrink-0" />
                <p className="text-sm font-medium text-orange-300">Approval Required</p>
              </div>
              <p className="text-xs text-gray-400 mb-3">
                The next step is a write operation. Review the planned action in the event log, then approve or reject.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => approve(workflow.id)}
                  disabled={approving || rejecting}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-xs font-medium rounded-lg transition-colors"
                >
                  {approving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                  Approve
                </button>
                <button
                  onClick={() => reject(workflow.id)}
                  disabled={approving || rejecting}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-red-700 hover:bg-red-600 disabled:opacity-40 text-white text-xs font-medium rounded-lg transition-colors"
                >
                  {rejecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
                  Reject
                </button>
              </div>
            </div>
          )}

          {/* Final answer */}
          {finalAnswer && (
            <div className="prose prose-invert prose-sm max-w-none text-sm text-gray-200
              [&>p]:mb-3 [&>p]:leading-relaxed
              [&>ul]:mb-3 [&>ul]:pl-5 [&>ul>li]:list-disc [&>ul>li]:mb-1
              [&>ol]:mb-3 [&>ol]:pl-5 [&>ol>li]:list-decimal [&>ol>li]:mb-1
              [&>h1]:text-base [&>h2]:text-sm [&>h3]:text-sm
              [&>h1]:font-semibold [&>h2]:font-semibold [&>h3]:font-semibold [&>h1]:mb-2 [&>h2]:mb-2 [&>h3]:mb-1
              [&>table]:w-full [&>table]:text-xs [&>table]:border-collapse [&>table]:mb-3
              [&_th]:text-left [&_th]:text-gray-500 [&_th]:border-b [&_th]:border-white/10 [&_th]:pb-1.5 [&_th]:pr-4 [&_th]:font-medium
              [&_td]:py-1.5 [&_td]:pr-4 [&_td]:border-b [&_td]:border-white/5 [&_td]:text-gray-300
              [&>pre]:bg-[#1a1a1a] [&>pre]:border [&>pre]:border-white/5 [&>pre]:p-3 [&>pre]:rounded-lg [&>pre]:text-xs [&>pre]:overflow-x-auto [&>pre]:mb-3
              [&>code]:bg-white/5 [&>code]:px-1.5 [&>code]:py-0.5 [&>code]:rounded [&>code]:text-xs [&>code]:font-mono
              [&>blockquote]:border-l-2 [&>blockquote]:border-brand-500 [&>blockquote]:pl-3 [&>blockquote]:text-gray-400 [&>blockquote]:italic">
              <ReactMarkdown>{finalAnswer}</ReactMarkdown>
            </div>
          )}

          {/* Error */}
          {workflow.status === "failed" && workflow.error_message && !finalAnswer && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/5 border border-red-500/20">
              <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
              <p className="text-sm text-gray-300">{workflow.error_message}</p>
            </div>
          )}

          {/* Live event log */}
          {events.length > 0 && (
            <div className="mt-4 space-y-1 border-t border-white/5 pt-3">
              {events.slice(-8).map((e, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px] font-mono">
                  <span className="text-gray-700 shrink-0 tabular-nums">
                    {e.timestamp ? new Date(e.timestamp as string).toLocaleTimeString() : "--:--"}
                  </span>
                  <span className={eventColor(e)}>{eventLabel(e)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div ref={bottomRef} />
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

// ── Searchable select dropdown ────────────────────────────────────────────────

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
  const filtered = options.filter((o) =>
    o.label.toLowerCase().includes(search.toLowerCase())
  );

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleOpen = () => {
    setOpen(true);
    setTimeout(() => inputRef.current?.focus(), 10);
  };

  return (
    <div ref={containerRef} className="relative max-w-sm">
      {/* Trigger */}
      <div
        onClick={handleOpen}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/5 border border-white/10 cursor-pointer hover:border-white/20 transition-colors"
      >
        {selected ? (
          <>
            <span className="text-sm text-gray-200 flex-1 truncate">{selected.label}</span>
            <button
              onClick={(e) => { e.stopPropagation(); onChange(""); setSearch(""); }}
              className="text-gray-600 hover:text-gray-300 shrink-0"
            >
              ×
            </button>
          </>
        ) : (
          <span className="text-sm text-gray-600">{placeholder}</span>
        )}
      </div>

      {/* Dropdown */}
      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-[#1e1e1e] border border-white/10 rounded-lg shadow-2xl z-50 overflow-hidden">
          <div className="p-2 border-b border-white/5">
            <input
              ref={inputRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search members…"
              className="w-full bg-white/5 rounded-md px-2.5 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none"
            />
          </div>
          <div className="max-h-48 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="px-3 py-2.5 text-sm text-gray-600">No results</p>
            ) : (
              filtered.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => { onChange(opt.value); setOpen(false); setSearch(""); }}
                  className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                    opt.value === value
                      ? "bg-brand-600/20 text-brand-300"
                      : "text-gray-300 hover:bg-white/5"
                  }`}
                >
                  {opt.label}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Clarification card ────────────────────────────────────────────────────────

function enrichTask(
  task: string,
  answers: Record<string, string>,
  analysis: AnalyzeResponse,
): string {
  const parts: string[] = [];
  if (answers.jira_project) parts.push(`Use Jira project key ${answers.jira_project}`);
  if (answers.jira_priority) parts.push(`set priority to ${answers.jira_priority}`);
  if (answers.jira_assignee) {
    // Pass accountId (Jira requires it), but also note the display name for the planner
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

  const setAnswer = (id: string, value: string) =>
    setAnswers((prev) => ({ ...prev, [id]: value }));

  const canConfirm = analysis.questions
    .filter((q) => q.required)
    .every((q) => answers[q.id]?.trim());

  return (
    <div className="max-w-3xl mx-auto px-4 pt-8 pb-4">
      {/* User message */}
      <div className="flex gap-3 mb-6">
        <div className="w-8 h-8 rounded-full bg-[#2a2a2a] border border-white/10 flex items-center justify-center shrink-0 mt-0.5">
          <User className="w-4 h-4 text-gray-400" />
        </div>
        <p className="flex-1 text-sm text-gray-200 leading-relaxed pt-1">{task}</p>
      </div>

      {/* Clarification */}
      <div className="flex gap-3">
        <div className="w-8 h-8 rounded-full bg-brand-900/40 border border-brand-700/30 flex items-center justify-center shrink-0 mt-0.5">
          <ShieldCheck className="w-4 h-4 text-brand-400" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-300 mb-4">
            A few details before I start — this helps me run the right tools with the right parameters.
          </p>
          <div className="space-y-4">
            {analysis.questions.map((q: AnalyzeQuestion) => (
              <div key={q.id}>
                <label className="block text-xs font-medium text-gray-300 mb-1">
                  {q.label}
                  {q.required && <span className="text-red-400 ml-1">*</span>}
                </label>
                <p className="text-xs text-gray-600 mb-1.5">{q.description}</p>
                {q.type === "searchable_select" ? (
                  <SearchableSelect
                    options={q.options}
                    value={answers[q.id] ?? ""}
                    onChange={(v) => setAnswer(q.id, v)}
                    placeholder={q.placeholder || "Search…"}
                  />
                ) : q.type === "select" ? (
                  <div className="flex flex-wrap gap-2">
                    {q.options.map((opt) => (
                      <button
                        key={opt.value}
                        onClick={() => setAnswer(q.id, opt.value)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                          answers[q.id] === opt.value
                            ? "bg-brand-600 border-brand-500 text-white"
                            : "bg-white/5 border-white/10 text-gray-400 hover:bg-white/10 hover:text-gray-200"
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                ) : (
                  <input
                    value={answers[q.id] ?? ""}
                    onChange={(e) => setAnswer(q.id, e.target.value)}
                    placeholder={q.placeholder}
                    className="w-full max-w-sm bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-white/20"
                  />
                )}
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-5">
            <button
              onClick={() => onConfirm(enrichTask(task, answers, analysis))}
              disabled={!canConfirm}
              className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:bg-white/5 disabled:text-gray-600 text-white text-sm font-medium rounded-lg transition-colors"
            >
              <ArrowUp className="w-3.5 h-3.5" />
              Confirm & Run
            </button>
            <button
              onClick={onSkip}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-gray-200 text-sm rounded-lg transition-colors"
            >
              Skip & Run anyway
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const SUGGESTIONS = [
  "List open PRs in Abhishek231200/mcp-gateway-backend and post a summary to the engineering Slack channel",
  "Get the active sprint issues in MGORCH project and summarize their status",
  "List recent commits in Abhishek231200/mcp-gateway-backend and create a Jira ticket in MGORCH summarizing the changes",
];

function EmptyState({ onSuggest }: { onSuggest: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4 pb-24">
      <div className="w-14 h-14 rounded-2xl bg-brand-600/20 border border-brand-500/20 flex items-center justify-center mb-5">
        <ShieldCheck className="w-7 h-7 text-brand-400" />
      </div>
      <h2 className="text-xl font-semibold text-white mb-2">What would you like to orchestrate?</h2>
      <p className="text-sm text-gray-500 max-w-md leading-relaxed">
        Describe a task and MCP Gateway will plan, execute, and review it across your connected tools — GitHub, Jira, Slack, and more.
      </p>
      <div className="mt-6 flex flex-wrap gap-2 justify-center max-w-lg">
        {SUGGESTIONS.map((hint) => (
          <button
            key={hint}
            className="text-xs text-gray-500 border border-white/5 rounded-lg px-3 py-1.5 hover:bg-white/5 hover:text-gray-300 transition-colors text-left"
            onClick={() => onSuggest(hint)}
          >
            {hint}
          </button>
        ))}
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

  // Resize whenever task changes (including programmatic sets from suggestion chips)
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
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (!isPending && task.trim()) onSubmit();
    }
  };

  return (
    <div className="flex-none border-t border-white/5 bg-[#0d0d0d] px-4 py-4">
      <div className="max-w-3xl mx-auto">
        {error && (
          <p className="text-xs text-red-400 mb-2 px-1">{error}</p>
        )}
        <div className="relative rounded-2xl border border-white/10 bg-[#1c1c1c] shadow-xl focus-within:border-white/20 transition-colors">
          <textarea
            ref={textareaRef}
            data-input
            value={task}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Describe a task across your connected tools…"
            rows={1}
            disabled={isPending}
            className="w-full bg-transparent resize-none px-4 pt-3.5 pb-12 text-sm text-gray-100 placeholder-gray-600 focus:outline-none disabled:opacity-50 leading-relaxed"
            style={{ maxHeight: "200px", minHeight: "52px" }}
          />
          <div className="absolute bottom-3 right-3 flex items-center gap-2">
            <span className="text-[11px] text-gray-700 hidden sm:block">⌘↵</span>
            <button
              onClick={onSubmit}
              disabled={isPending || !task.trim()}
              className="p-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 disabled:bg-white/5 disabled:text-gray-600 text-white transition-colors"
            >
              {isPending
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <ArrowUp className="w-4 h-4" />
              }
            </button>
          </div>
        </div>
        <p className="text-center text-[11px] text-gray-700 mt-2">
          MCP Gateway can make mistakes. Review tool calls before approving write operations.
        </p>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function WorkflowsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  // URL encodes the full conversation as ?wf=id1,id2,id3 (comma-separated).
  // Sidebar navigation always passes a single ID; multi-turn appends to it.
  const rawWf = searchParams.get("wf") ?? "";
  const urlIds = rawWf ? rawWf.split(",").filter(Boolean) : [];

  const [conversationIds, setConversationIds] = useState<string[]>(urlIds);

  const [task, setTask] = useState("");
  const [submitError, setSubmitError] = useState<string | undefined>();
  const [pendingClarification, setPendingClarification] = useState<{ task: string; analysis: AnalyzeResponse } | null>(null);
  const { mutateAsync, isPending } = useCreateWorkflow();
  const { mutateAsync: analyze, isPending: analyzing } = useAnalyzeWorkflow();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);

  // On every navigation (location.key changes), sync from URL.
  // Sidebar always passes a clean single-ID URL so it resets to one workflow.
  useEffect(() => {
    const ids = (searchParams.get("wf") ?? "").split(",").filter(Boolean);
    setConversationIds(ids);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  // Scroll to bottom when conversation grows
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversationIds.length]);

  const _createAndAppend = async (finalTask: string) => {
    const wf = await mutateAsync({ task: finalTask, actor: "user" });
    const nextIds = [...conversationIds, wf.id];
    setConversationIds(nextIds);
    setSearchParams({ wf: nextIds.join(",") });
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

  const handleClarifyConfirm = async (enrichedTask: string) => {
    setPendingClarification(null);
    setSubmitError(undefined);
    try {
      await _createAndAppend(enrichedTask);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(detail ?? "Failed to start workflow.");
    }
  };

  const handleClarifySkip = async () => {
    if (!pendingClarification) return;
    const t = pendingClarification.task;
    setPendingClarification(null);
    try {
      await _createAndAppend(t);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setSubmitError(detail ?? "Failed to start workflow.");
    }
  };

  const showEmpty = conversationIds.length === 0 && !pendingClarification;

  return (
    <div className="h-full flex flex-col bg-[#0d0d0d]">
      {/* Chat thread */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {showEmpty ? (
          <EmptyState onSuggest={(text) => {
            setTask(text);
            setTimeout(() => inputRef.current?.focus(), 50);
          }} />
        ) : (
          <>
            {conversationIds.map((id, idx) => (
              <div key={id}>
                <ConversationView workflowId={id} />
                {idx < conversationIds.length - 1 && (
                  <div className="border-t border-white/5 mx-8 my-1" />
                )}
              </div>
            ))}
            {pendingClarification && (
              <>
                {conversationIds.length > 0 && <div className="border-t border-white/5 mx-8 my-1" />}
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

      {/* Input */}
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
