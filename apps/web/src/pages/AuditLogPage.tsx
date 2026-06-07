import { useState, useEffect } from "react";

function useDebounce<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

import {
  ShieldCheck, ShieldX, Download, Link2, Link2Off, RefreshCw,
  ChevronDown, ChevronRight, Activity, Clock, Filter, X,
} from "lucide-react";
import { useAuditLogs, useAuditStats } from "@/hooks/useAuditLogs";
import type { AuditLogEntry } from "@/hooks/useAuditLogs";

// ── Constants ─────────────────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = {
  tool_call:            "Tool Call",
  tool_blocked:         "Tool Blocked",
  rate_limited:         "Rate Limited",
  injection_detected:   "Injection Detected",
  workflow_started:     "Workflow Started",
  workflow_completed:   "Workflow Completed",
  workflow_failed:      "Workflow Failed",
  server_registered:    "Server Registered",
  server_deregistered:  "Server Deregistered",
};

const ACTION_STYLE: Record<string, { bg: string; color: string; border: string }> = {
  tool_call:           { bg: "rgba(16,185,129,0.08)",  color: "#10b981", border: "rgba(16,185,129,0.2)"  },
  tool_blocked:        { bg: "rgba(244,63,94,0.08)",   color: "#f43f5e", border: "rgba(244,63,94,0.2)"   },
  rate_limited:        { bg: "rgba(245,158,11,0.08)",  color: "#f59e0b", border: "rgba(245,158,11,0.2)"  },
  injection_detected:  { bg: "rgba(244,63,94,0.08)",   color: "#f43f5e", border: "rgba(244,63,94,0.2)"   },
  workflow_completed:  { bg: "rgba(16,185,129,0.08)",  color: "#10b981", border: "rgba(16,185,129,0.2)"  },
  workflow_failed:     { bg: "rgba(244,63,94,0.08)",   color: "#f43f5e", border: "rgba(244,63,94,0.2)"   },
  workflow_started:    { bg: "rgba(56,189,248,0.08)",  color: "#38bdf8", border: "rgba(56,189,248,0.2)"  },
  server_registered:   { bg: "rgba(14,165,233,0.08)",  color: "#38bdf8", border: "rgba(14,165,233,0.2)"  },
  server_deregistered: { bg: "rgba(139,135,166,0.08)", color: "#8b87a6", border: "rgba(139,135,166,0.15)"},
};

const PAGE_SIZE = 50;

// ── Sub-components ────────────────────────────────────────────────────────────

function MetricTile({ label, value, accent }: {
  label: string; value: string | number; accent: string;
}) {
  return (
    <div className="card-accent p-4">
      <p className="text-2xl font-bold tracking-tight" style={{ color: accent }}>{value}</p>
      <p className="text-xs mt-1" style={{ color: "var(--text-low)" }}>{label}</p>
    </div>
  );
}

function ActionBadge({ action }: { action: string }) {
  const s = ACTION_STYLE[action] ?? { bg: "rgba(139,135,166,0.08)", color: "#8b87a6", border: "rgba(139,135,166,0.15)" };
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ background: s.bg, color: s.color, border: `1px solid ${s.border}` }}>
      {ACTION_LABELS[action] ?? action}
    </span>
  );
}

function DecisionBadge({ allowed }: { allowed: boolean | null }) {
  if (allowed === null) return <span style={{ color: "var(--text-low)", fontSize: "12px" }}>—</span>;
  return allowed ? (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400">
      <ShieldCheck className="w-3 h-3" /> Allowed
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-rose-400">
      <ShieldX className="w-3 h-3" /> Denied
    </span>
  );
}

function EntryRow({ entry }: { entry: AuditLogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const ts = new Date(entry.created_at);
  const errorMsg = entry.response_payload?.error as string | undefined;
  const reason = entry.policy_decision?.reason as string | undefined;

  return (
    <>
      <tr
        className="table-row group"
        style={expanded ? { background: "rgba(14,165,233,0.06)" } : undefined}
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="px-4 py-3">
          <div className="flex items-center gap-1.5">
            {expanded
              ? <ChevronDown className="w-3 h-3 shrink-0" style={{ color: "var(--text-low)" }} />
              : <ChevronRight className="w-3 h-3 shrink-0" style={{ color: "var(--text-low)" }} />
            }
            <span className="text-xs font-mono" style={{ color: "var(--text-mid)" }}>
              {ts.toLocaleDateString(undefined, { month: "short", day: "numeric" })}{" "}
              {ts.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          </div>
        </td>
        <td className="px-4 py-3">
          <span className="text-xs font-mono px-1.5 py-0.5 rounded"
            style={{ background: "var(--surface-3)", color: "var(--text-mid)" }}>
            {entry.actor ?? "—"}
          </span>
        </td>
        <td className="px-4 py-3">
          <ActionBadge action={entry.action} />
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-1 text-xs font-mono">
            {entry.server_name && (
              <span style={{ color: "#38bdf8" }}>{entry.server_name}</span>
            )}
            {entry.server_name && entry.tool_name && (
              <span style={{ color: "var(--text-low)" }}>/</span>
            )}
            {entry.tool_name && (
              <span style={{ color: "var(--text-mid)" }}>{entry.tool_name}</span>
            )}
            {!entry.server_name && !entry.tool_name && (
              <span style={{ color: "var(--text-low)" }}>—</span>
            )}
          </div>
          {(errorMsg || reason) && !expanded && (
            <p className="text-[11px] mt-0.5 truncate max-w-[220px]"
              style={{ color: "var(--text-low)" }}
              title={errorMsg ?? reason}>
              {errorMsg ?? reason}
            </p>
          )}
        </td>
        <td className="px-4 py-3">
          <DecisionBadge allowed={entry.allowed} />
        </td>
        <td className="px-4 py-3 text-right">
          <span className="text-xs font-mono" style={{ color: "var(--text-low)" }}>
            {entry.latency_ms != null ? `${entry.latency_ms}ms` : "—"}
          </span>
        </td>
      </tr>

      {expanded && (
        <tr style={{ background: "rgba(14,165,233,0.04)", borderBottom: "1px solid rgba(14,165,233,0.08)" }}>
          <td colSpan={6} className="px-6 py-4">
            <div className="space-y-3 text-xs font-mono animate-fade-in">
              {errorMsg && (
                <div className="p-3 rounded-lg" style={{ background: "rgba(244,63,94,0.06)", border: "1px solid rgba(244,63,94,0.15)" }}>
                  <p className="uppercase tracking-widest text-[10px] mb-1.5" style={{ color: "rgba(244,63,94,0.6)" }}>Error</p>
                  <p className="break-all whitespace-pre-wrap leading-relaxed" style={{ color: "#fca5a5" }}>{errorMsg}</p>
                </div>
              )}
              {reason && (
                <div className="p-3 rounded-lg" style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.15)" }}>
                  <p className="uppercase tracking-widest text-[10px] mb-1.5" style={{ color: "rgba(245,158,11,0.6)" }}>Policy Reason</p>
                  <p className="break-all" style={{ color: "#fcd34d" }}>{reason}</p>
                </div>
              )}
              {entry.policy_decision && Object.keys(entry.policy_decision).length > 0 && (
                <div className="p-3 rounded-lg" style={{ background: "var(--surface-3)", border: "1px solid var(--border)" }}>
                  <p className="uppercase tracking-widest text-[10px] mb-1.5" style={{ color: "var(--text-low)" }}>Policy Decision</p>
                  <pre className="text-[11px] overflow-x-auto leading-relaxed" style={{ color: "var(--text-mid)" }}>
                    {JSON.stringify(entry.policy_decision, null, 2)}
                  </pre>
                </div>
              )}
              {entry.response_payload && Object.keys(entry.response_payload).length > 0 && !errorMsg && (
                <div className="p-3 rounded-lg" style={{ background: "var(--surface-3)", border: "1px solid var(--border)" }}>
                  <p className="uppercase tracking-widest text-[10px] mb-1.5" style={{ color: "var(--text-low)" }}>Response</p>
                  <pre className="text-[11px] overflow-x-auto max-h-40 leading-relaxed" style={{ color: "var(--text-mid)" }}>
                    {JSON.stringify(entry.response_payload, null, 2)}
                  </pre>
                </div>
              )}
              <p className="text-[10px]" style={{ color: "var(--text-low)" }}>
                ID: {entry.id as string} · hash: {entry.entry_hash?.slice(0, 20) ?? "—"}
              </p>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function Pagination({ total, offset, onOffset }: {
  total: number; offset: number; onOffset: (n: number) => void;
}) {
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between text-xs" style={{ color: "var(--text-mid)" }}>
      <span>Page {page} of {totalPages} · {total.toLocaleString()} entries</span>
      <div className="flex gap-2">
        <button
          onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0}
          className="btn-secondary px-3 py-1.5 text-xs disabled:opacity-30"
        >
          ← Prev
        </button>
        <button
          onClick={() => onOffset(offset + PAGE_SIZE)}
          disabled={offset + PAGE_SIZE >= total}
          className="btn-secondary px-3 py-1.5 text-xs disabled:opacity-30"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AuditLogPage() {
  const [actor, setActor] = useState("");
  const [server, setServer] = useState("");
  const [tool, setTool] = useState("");
  const [action, setAction] = useState("");
  const [allowed, setAllowed] = useState<"" | "true" | "false">("");
  const [offset, setOffset] = useState(0);
  const [filtersOpen, setFiltersOpen] = useState(true);

  const dActor = useDebounce(actor);
  const dServer = useDebounce(server);
  const dTool = useDebounce(tool);

  const resetPage = () => setOffset(0);

  const params = {
    actor: dActor || undefined,
    server: dServer || undefined,
    tool: dTool || undefined,
    action: action || undefined,
    allowed: allowed === "" ? undefined : allowed === "true",
    limit: PAGE_SIZE,
    offset,
  };

  const { data, isLoading, refetch } = useAuditLogs(params);
  const { data: stats } = useAuditStats();

  const activeFilters = [actor, server, tool, action, allowed].filter(Boolean).length;

  const exportParams = new URLSearchParams();
  if (actor) exportParams.set("actor", actor);
  if (server) exportParams.set("server", server);
  if (tool) exportParams.set("tool", tool);
  if (action) exportParams.set("action", action);
  if (allowed !== "") exportParams.set("allowed", allowed);
  const exportUrl = `/api/audit-logs/export${exportParams.size > 0 ? `?${exportParams}` : ""}`;

  const clearFilters = () => { setActor(""); setServer(""); setTool(""); setAction(""); setAllowed(""); resetPage(); };

  return (
    <div className="space-y-5 animate-fade-in">

      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="page-title">Audit Log</h2>
          <p className="page-subtitle">Tamper-evident SHA-256 hash chain of every tool call and policy decision.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="btn-secondary text-xs gap-1.5"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
          <a href={exportUrl} download className="btn-secondary text-xs gap-1.5">
            <Download className="w-3.5 h-3.5" /> Export CSV
          </a>
        </div>
      </div>

      {/* Metric tiles */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricTile label="Total entries" value={stats.total.toLocaleString()} accent="var(--text-high)" />
          <MetricTile
            label="Blocked today"
            value={stats.blocked_today}
            accent={stats.blocked_today > 0 ? "#f43f5e" : "var(--text-mid)"}
          />
          <MetricTile label="Tool calls today" value={stats.tool_calls_today} accent="#10b981" />
          <div className="card-accent p-4">
            <div className="flex items-center gap-2 mb-1">
              {stats.chain_valid
                ? <Link2 className="w-4 h-4 text-emerald-400" />
                : <Link2Off className="w-4 h-4 text-rose-400" />
              }
              <p className="text-2xl font-bold tracking-tight"
                style={{ color: stats.chain_valid ? "#10b981" : "#f43f5e" }}>
                {stats.chain_valid ? "Valid" : "Broken"}
              </p>
            </div>
            <p className="text-xs" style={{ color: "var(--text-low)" }}>Chain integrity</p>
            {stats.last_entry_hash && (
              <p className="text-[10px] font-mono mt-1 truncate" style={{ color: "var(--text-low)" }}>
                {stats.last_entry_hash.slice(0, 16)}…
              </p>
            )}
          </div>
        </div>
      )}

      {/* Filter panel */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <button
            onClick={() => setFiltersOpen((v) => !v)}
            className="flex items-center gap-2 text-sm font-medium transition-colors"
            style={{ color: "var(--text-high)" }}
          >
            <Filter className="w-3.5 h-3.5" style={{ color: "var(--text-mid)" }} />
            Filters
            {activeFilters > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold text-white"
                style={{ background: "#0ea5e9" }}>
                {activeFilters}
              </span>
            )}
            {filtersOpen ? <ChevronDown className="w-3.5 h-3.5" style={{ color: "var(--text-low)" }} /> : <ChevronRight className="w-3.5 h-3.5" style={{ color: "var(--text-low)" }} />}
          </button>
          {activeFilters > 0 && (
            <button onClick={clearFilters} className="flex items-center gap-1 text-xs transition-colors"
              style={{ color: "var(--text-low)" }}
              onMouseOver={e => (e.currentTarget.style.color = "var(--text-high)")}
              onMouseOut={e => (e.currentTarget.style.color = "var(--text-low)")}>
              <X className="w-3 h-3" /> Clear all
            </button>
          )}
        </div>

        {filtersOpen && (
          <div className="flex flex-wrap gap-3 pt-2" style={{ borderTop: "1px solid var(--border)" }}>
            {[
              { label: "Actor", value: actor, setter: setActor, placeholder: "Filter by actor…" },
              { label: "Server", value: server, setter: setServer, placeholder: "Filter by server…" },
              { label: "Tool", value: tool, setter: setTool, placeholder: "Filter by tool…" },
            ].map(({ label, value, setter, placeholder }) => (
              <div key={label} className="flex-1 min-w-[140px]">
                <label className="block text-[11px] font-medium mb-1.5" style={{ color: "var(--text-low)" }}>{label}</label>
                <input
                  value={value}
                  onChange={(e) => { setter(e.target.value); resetPage(); }}
                  placeholder={placeholder}
                  className="input text-xs"
                />
              </div>
            ))}

            <div>
              <label className="block text-[11px] font-medium mb-1.5" style={{ color: "var(--text-low)" }}>Action</label>
              <select
                value={action}
                onChange={(e) => { setAction(e.target.value); resetPage(); }}
                className="input text-xs pr-8"
              >
                <option value="">All actions</option>
                <option value="tool_call">Tool Call</option>
                <option value="tool_blocked">Tool Blocked</option>
                <option value="workflow_completed">Workflow Completed</option>
                <option value="workflow_failed">Workflow Failed</option>
                <option value="server_registered">Server Registered</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] font-medium mb-1.5" style={{ color: "var(--text-low)" }}>Decision</label>
              <select
                value={allowed}
                onChange={(e) => { setAllowed(e.target.value as "" | "true" | "false"); resetPage(); }}
                className="input text-xs pr-8"
              >
                <option value="">All</option>
                <option value="true">Allowed</option>
                <option value="false">Denied</option>
              </select>
            </div>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="card overflow-hidden p-0">
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-12" style={{ color: "var(--text-low)" }}>
            <RefreshCw className="w-4 h-4 animate-spin" />
            <span className="text-sm">Loading…</span>
          </div>
        ) : !data || data.items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <Activity className="w-8 h-8 mb-3" style={{ color: "var(--text-low)" }} />
            <p className="text-sm font-medium" style={{ color: "var(--text-mid)" }}>No entries match your filters</p>
            <p className="text-xs mt-1" style={{ color: "var(--text-low)" }}>Try broadening your search</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="table-header">
                  <th><div className="flex items-center gap-1.5"><Clock className="w-3 h-3" />Time</div></th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Server / Tool</th>
                  <th>Decision</th>
                  <th className="text-right">Latency</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((entry) => (
                  <EntryRow key={entry.id} entry={entry} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {data && (
        <Pagination total={data.total} offset={offset} onOffset={setOffset} />
      )}
    </div>
  );
}
