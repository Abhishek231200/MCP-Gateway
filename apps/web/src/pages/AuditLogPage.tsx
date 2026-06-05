import { useState, useEffect } from "react";

function useDebounce<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}
import { ShieldCheck, ShieldX, Download, Link2, Link2Off, RefreshCw } from "lucide-react";
import { useAuditLogs, useAuditStats } from "@/hooks/useAuditLogs";
import type { AuditLogEntry } from "@/hooks/useAuditLogs";

// ── Constants ─────────────────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = {
  tool_call: "Tool Call",
  tool_blocked: "Tool Blocked",
  rate_limited: "Rate Limited",
  injection_detected: "Injection Detected",
  workflow_started: "Workflow Started",
  workflow_completed: "Workflow Completed",
  workflow_failed: "Workflow Failed",
  server_registered: "Server Registered",
  server_deregistered: "Server Deregistered",
};

const ACTION_COLORS: Record<string, string> = {
  tool_call: "text-green-400 bg-green-900/30",
  tool_blocked: "text-red-400 bg-red-900/30",
  rate_limited: "text-yellow-400 bg-yellow-900/30",
  injection_detected: "text-red-400 bg-red-900/30",
  workflow_completed: "text-green-400 bg-green-900/30",
  workflow_failed: "text-red-400 bg-red-900/30",
  workflow_started: "text-blue-400 bg-blue-900/30",
  server_registered: "text-brand-400 bg-brand-900/30",
  server_deregistered: "text-gray-400 bg-gray-800",
};

const PAGE_SIZE = 50;

// ── Sub-components ────────────────────────────────────────────────────────────

function StatChip({ label, value, color = "gray" }: {
  label: string;
  value: string | number;
  color?: "gray" | "red" | "green" | "yellow";
}) {
  const colors = {
    gray: "bg-gray-800 text-gray-300",
    red: "bg-red-900/30 text-red-400",
    green: "bg-green-900/30 text-green-400",
    yellow: "bg-yellow-900/30 text-yellow-400",
  };
  return (
    <div className={`rounded-lg px-4 py-3 ${colors[color]}`}>
      <p className="text-xl font-bold">{value}</p>
      <p className="text-xs mt-0.5 opacity-70">{label}</p>
    </div>
  );
}

function AllowedBadge({ allowed }: { allowed: boolean | null }) {
  if (allowed === null) return <span className="text-gray-500 text-xs">—</span>;
  return allowed ? (
    <span className="flex items-center gap-1 text-green-400 text-xs font-medium">
      <ShieldCheck className="w-3 h-3" /> Allowed
    </span>
  ) : (
    <span className="flex items-center gap-1 text-red-400 text-xs font-medium">
      <ShieldX className="w-3 h-3" /> Denied
    </span>
  );
}

function ActionBadge({ action }: { action: string }) {
  const colorClass = ACTION_COLORS[action] ?? "text-gray-400 bg-gray-800";
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${colorClass}`}>
      {ACTION_LABELS[action] ?? action}
    </span>
  );
}

function EntryRow({ entry }: { entry: AuditLogEntry }) {
  const ts = new Date(entry.created_at);
  const reason = entry.policy_decision?.reason as string | undefined;
  return (
    <tr className="border-t border-gray-800 hover:bg-gray-800/40 transition-colors">
      <td className="px-3 py-2.5 text-xs text-gray-400 font-mono whitespace-nowrap">
        {ts.toLocaleDateString()} {ts.toLocaleTimeString()}
      </td>
      <td className="px-3 py-2.5 text-xs text-gray-200 font-mono max-w-[120px] truncate">
        {entry.actor}
      </td>
      <td className="px-3 py-2.5">
        <ActionBadge action={entry.action} />
      </td>
      <td className="px-3 py-2.5 text-xs text-gray-300">
        {entry.server_name && (
          <span className="font-mono text-brand-400">{entry.server_name}</span>
        )}
        {entry.server_name && entry.tool_name && (
          <span className="text-gray-600"> / </span>
        )}
        {entry.tool_name && <span className="font-mono">{entry.tool_name}</span>}
        {!entry.server_name && !entry.tool_name && (
          <span className="text-gray-600">—</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        <AllowedBadge allowed={entry.allowed} />
        {reason && (
          <p className="text-xs text-gray-500 mt-0.5 max-w-[200px] truncate" title={reason}>
            {reason}
          </p>
        )}
      </td>
      <td className="px-3 py-2.5 text-xs text-gray-400 font-mono text-right">
        {entry.latency_ms != null ? `${entry.latency_ms}ms` : "—"}
      </td>
    </tr>
  );
}

function Pagination({ total, offset, onOffset }: {
  total: number;
  offset: number;
  onOffset: (n: number) => void;
}) {
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between text-xs text-gray-400">
      <span>Page {page} of {totalPages} ({total.toLocaleString()} entries)</span>
      <div className="flex gap-2">
        <button
          onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0}
          className="px-3 py-1 rounded bg-gray-800 disabled:opacity-40 hover:bg-gray-700"
        >
          ← Prev
        </button>
        <button
          onClick={() => onOffset(offset + PAGE_SIZE)}
          disabled={offset + PAGE_SIZE >= total}
          className="px-3 py-1 rounded bg-gray-800 disabled:opacity-40 hover:bg-gray-700"
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

  const exportParams = new URLSearchParams();
  if (actor) exportParams.set("actor", actor);
  if (server) exportParams.set("server", server);
  if (tool) exportParams.set("tool", tool);
  if (action) exportParams.set("action", action);
  if (allowed !== "") exportParams.set("allowed", allowed);
  const exportUrl = `/api/audit-logs/export${exportParams.size > 0 ? `?${exportParams}` : ""}`;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">Audit Log</h2>
          <p className="text-sm text-gray-400 mt-1">
            Tamper-evident record of every tool invocation and security policy decision.
          </p>
        </div>
        <a
          href={exportUrl}
          download
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors"
        >
          <Download className="w-3.5 h-3.5" />
          Export CSV
        </a>
      </div>

      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatChip label="Total entries" value={stats.total.toLocaleString()} />
          <StatChip
            label="Blocked today"
            value={stats.blocked_today}
            color={stats.blocked_today > 0 ? "red" : "gray"}
          />
          <StatChip
            label="Tool calls today"
            value={stats.tool_calls_today}
            color="green"
          />
          <div className="rounded-lg px-4 py-3 bg-gray-800 text-gray-300">
            <div className="flex items-center gap-1.5">
              {stats.chain_valid ? (
                <Link2 className="w-4 h-4 text-green-400" />
              ) : (
                <Link2Off className="w-4 h-4 text-red-400" />
              )}
              <p className={`text-xl font-bold ${stats.chain_valid ? "text-green-400" : "text-red-400"}`}>
                {stats.chain_valid ? "Valid" : "Broken"}
              </p>
            </div>
            <p className="text-xs mt-0.5 opacity-70">Chain integrity</p>
            {stats.last_entry_hash && (
              <p className="text-xs font-mono text-gray-600 mt-1 truncate">
                {stats.last_entry_hash.slice(0, 16)}…
              </p>
            )}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="card flex flex-wrap gap-3 items-end">
        {[
          { label: "Actor", value: actor, setter: setActor, placeholder: "Filter by actor…" },
          { label: "Server", value: server, setter: setServer, placeholder: "Filter by server…" },
          { label: "Tool", value: tool, setter: setTool, placeholder: "Filter by tool…" },
        ].map(({ label, value, setter, placeholder }) => (
          <div key={label} className="flex-1 min-w-[130px]">
            <label className="block text-xs text-gray-400 mb-1">{label}</label>
            <input
              value={value}
              onChange={(e) => { setter(e.target.value); resetPage(); }}
              placeholder={placeholder}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-brand-500"
            />
          </div>
        ))}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Action</label>
          <select
            value={action}
            onChange={(e) => { setAction(e.target.value); resetPage(); }}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-brand-500"
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
          <label className="block text-xs text-gray-400 mb-1">Decision</label>
          <select
            value={allowed}
            onChange={(e) => { setAllowed(e.target.value as "" | "true" | "false"); resetPage(); }}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-brand-500"
          >
            <option value="">All</option>
            <option value="true">Allowed</option>
            <option value="false">Denied</option>
          </select>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {/* Table */}
      <div className="card overflow-hidden p-0">
        {isLoading ? (
          <p className="px-4 py-6 text-sm text-gray-500">Loading audit log…</p>
        ) : !data || data.items.length === 0 ? (
          <p className="px-4 py-6 text-sm text-gray-500">
            No audit log entries match the current filters.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 text-left">
                  <th className="px-3 py-2.5 font-medium">Time</th>
                  <th className="px-3 py-2.5 font-medium">Actor</th>
                  <th className="px-3 py-2.5 font-medium">Action</th>
                  <th className="px-3 py-2.5 font-medium">Server / Tool</th>
                  <th className="px-3 py-2.5 font-medium">Decision</th>
                  <th className="px-3 py-2.5 font-medium text-right">Latency</th>
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
