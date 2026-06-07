import { Activity, Server, GitBranch, ShieldAlert, TrendingUp, CheckCircle, AlertCircle, Minus } from "lucide-react";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import { useServers } from "@/hooks/useRegistry";
import { useWorkflows } from "@/hooks/useWorkflows";
import { useAuditStats } from "@/hooks/useAuditLogs";
import type { McpServer } from "@/hooks/useRegistry";

// ── Stat card ─────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
  accent: string;
  glow: string;
}

function StatCard({ label, value, icon: Icon, description, accent, glow }: StatCardProps) {
  return (
    <div className="card-accent p-5 group">
      <div className="flex items-start justify-between mb-4">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: `${accent}18`, border: `1px solid ${accent}30` }}>
          <Icon className="w-4.5 h-4.5" style={{ color: accent }} />
        </div>
        <TrendingUp className="w-3.5 h-3.5 opacity-0 group-hover:opacity-40 transition-opacity" style={{ color: accent }} />
      </div>
      <p className="text-2xl font-bold tracking-tight mb-0.5" style={{ color: "var(--text-high)" }}>
        {value}
      </p>
      <p className="text-sm font-medium mb-1" style={{ color: "var(--text-high)" }}>{label}</p>
      <p className="text-xs" style={{ color: "var(--text-low)" }}>{description}</p>
    </div>
  );
}

// ── Adapter health ────────────────────────────────────────────────────────────

const ADAPTER_META: Record<string, { label: string; color: string }> = {
  github:  { label: "GitHub",         color: "#f0f0f0" },
  slack:   { label: "Slack",          color: "#4a154b" },
  gdrive:  { label: "Google Drive",   color: "#4285f4" },
  kb:      { label: "Knowledge Base", color: "#0ea5e9" },
  jira:    { label: "Jira",           color: "#0052cc" },
};

function AdapterRow({ server }: { server: McpServer }) {
  const adapterType = typeof server.metadata?.adapter_type === "string"
    ? server.metadata.adapter_type : "unknown";
  const meta = ADAPTER_META[adapterType] ?? { label: adapterType, color: "#8b87a6" };

  const statusConfig = {
    healthy:  { dot: "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]", badge: "badge-healthy", label: "Healthy" },
    degraded: { dot: "bg-amber-400",   badge: "badge-degraded", label: "Degraded" },
    unhealthy:{ dot: "bg-rose-500",    badge: "badge-unhealthy", label: "Unhealthy" },
    unknown:  { dot: "bg-[#4a4769]",   badge: "badge-unknown",   label: "Unknown" },
  }[server.health_status ?? "unknown"] ?? { dot: "bg-[#4a4769]", badge: "badge-unknown", label: "Unknown" };

  return (
    <div className="flex items-center justify-between py-3 transition-colors"
      style={{ borderBottom: "1px solid rgba(14,165,233,0.06)" }}>
      <div className="flex items-center gap-3 min-w-0">
        <span className={`w-2 h-2 rounded-full shrink-0 ${statusConfig.dot}`} />
        <div className="min-w-0">
          <p className="text-sm font-medium" style={{ color: "var(--text-high)" }}>{meta.label}</p>
          <p className="text-xs font-mono" style={{ color: "var(--text-low)" }}>
            {server.name}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        {server.avg_latency_ms != null && (
          <span className="text-xs font-mono" style={{ color: "var(--text-low)" }}>
            {Math.round(server.avg_latency_ms)}ms
          </span>
        )}
        <span className={statusConfig.badge}>{statusConfig.label}</span>
      </div>
    </div>
  );
}

function AdapterHealthCard() {
  const { data, isLoading } = useServers(false);

  return (
    <div className="card h-full">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold" style={{ color: "var(--text-high)" }}>
          Connected Adapters
        </h3>
        {data && (
          <span className="chip">{data.total} server{data.total !== 1 ? "s" : ""}</span>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1,2,3].map(i => (
            <div key={i} className="h-10 rounded-lg animate-pulse" style={{ background: "var(--surface-3)" }} />
          ))}
        </div>
      ) : !data || data.total === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <Server className="w-8 h-8 mb-2" style={{ color: "var(--text-low)" }} />
          <p className="text-sm" style={{ color: "var(--text-low)" }}>No servers registered</p>
        </div>
      ) : (
        <div className="divide-y-0">
          {data.items.map((s) => <AdapterRow key={s.id} server={s} />)}
        </div>
      )}
    </div>
  );
}

// ── Dependency health ─────────────────────────────────────────────────────────

function DependencyRow({ name, dep }: { name: string; dep: { status: string; latency_ms?: number | null } }) {
  const icon = dep.status === "healthy"
    ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
    : dep.status === "degraded"
    ? <AlertCircle className="w-3.5 h-3.5 text-amber-400" />
    : dep.status === "unhealthy"
    ? <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
    : <Minus className="w-3.5 h-3.5" style={{ color: "var(--text-low)" }} />;

  return (
    <div className="flex items-center justify-between py-3 transition-colors"
      style={{ borderBottom: "1px solid rgba(14,165,233,0.06)" }}>
      <div className="flex items-center gap-3">
        {icon}
        <span className="text-sm capitalize" style={{ color: "var(--text-high)" }}>{name}</span>
      </div>
      <div className="flex items-center gap-3">
        {dep.latency_ms != null && (
          <span className="text-xs font-mono" style={{ color: "var(--text-low)" }}>{dep.latency_ms}ms</span>
        )}
        <span className={`badge-${dep.status}`}>{dep.status}</span>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { data: health, isLoading: healthLoading } = useHealthCheck();
  const { data: registry } = useServers();
  const { data: workflowsData } = useWorkflows(100);
  const { data: auditStats } = useAuditStats();

  const todayMs = 24 * 60 * 60 * 1000;

  const workflowsToday = workflowsData?.items.filter((wf) =>
    Date.now() - new Date(wf.created_at).getTime() < todayMs
  ).length ?? "—";

  const toolCallsToday = workflowsData?.items.reduce((total, wf) => {
    if (Date.now() - new Date(wf.created_at).getTime() >= todayMs) return total;
    return total + wf.steps.length;
  }, 0) ?? "—";

  const completedToday = workflowsData?.items.filter((wf) =>
    Date.now() - new Date(wf.created_at).getTime() < todayMs && wf.status === "completed"
  ).length ?? "—";

  return (
    <div className="space-y-6 animate-fade-in">

      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="page-title">System Overview</h2>
          <p className="page-subtitle">Real-time status of your MCP Gateway deployment.</p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl"
          style={{ background: "var(--surface-3)", border: "1px solid var(--border)" }}>
          <span className={`w-2 h-2 rounded-full ${health?.status === "healthy" ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]" : "bg-rose-500"}`} />
          <span className="text-xs" style={{ color: "var(--text-mid)" }}>
            {healthLoading ? "Checking…" : health?.status === "healthy" ? "All systems operational" : "System issue detected"}
          </span>
        </div>
      </div>

      {/* Divider with gradient */}
      <div className="divider" />

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          label="Registered Servers"
          value={registry?.total ?? "—"}
          icon={Server}
          description="Active MCP servers in registry"
          accent="#0ea5e9"
          glow="rgba(168,85,247,0.2)"
        />
        <StatCard
          label="Workflows Today"
          value={workflowsToday}
          icon={GitBranch}
          description="Executions in last 24h"
          accent="#38bdf8"
          glow="rgba(56,189,248,0.2)"
        />
        <StatCard
          label="Tool Calls Today"
          value={toolCallsToday}
          icon={Activity}
          description="Total tool invocations"
          accent="#10b981"
          glow="rgba(16,185,129,0.2)"
        />
        <StatCard
          label="Blocked Actions"
          value={auditStats?.blocked_today ?? "—"}
          icon={ShieldAlert}
          description="Security gateway blocks"
          accent="#f43f5e"
          glow="rgba(244,63,94,0.2)"
        />
      </div>

      {/* Two column: adapters + deps */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AdapterHealthCard />

        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold" style={{ color: "var(--text-high)" }}>
              Infrastructure Health
            </h3>
            {health && (
              <span className={`badge-${health.status}`}>{health.status}</span>
            )}
          </div>

          {healthLoading ? (
            <div className="space-y-3">
              {[1,2,3].map(i => (
                <div key={i} className="h-10 rounded-lg animate-pulse" style={{ background: "var(--surface-3)" }} />
              ))}
            </div>
          ) : health ? (
            <div>
              {Object.entries(health.dependencies).map(([name, dep]) => (
                <DependencyRow key={name} name={name} dep={dep} />
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2 py-4">
              <AlertCircle className="w-4 h-4 text-rose-400" />
              <p className="text-sm text-rose-400">API unreachable</p>
            </div>
          )}
        </div>
      </div>

      {/* Audit chain card */}
      {auditStats && (
        <div className="card">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ background: auditStats.chain_valid ? "rgba(16,185,129,0.1)" : "rgba(244,63,94,0.1)", border: `1px solid ${auditStats.chain_valid ? "rgba(16,185,129,0.2)" : "rgba(244,63,94,0.2)"}` }}>
              <Activity className="w-5 h-5" style={{ color: auditStats.chain_valid ? "#10b981" : "#f43f5e" }} />
            </div>
            <div className="flex-1">
              <p className="text-sm font-semibold" style={{ color: "var(--text-high)" }}>
                Audit Chain Integrity
              </p>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-mid)" }}>
                {auditStats.chain_valid
                  ? "SHA-256 hash chain verified — no tampering detected"
                  : "Hash chain integrity check failed — potential tampering"}
              </p>
            </div>
            <div className="text-right shrink-0">
              <p className="text-xl font-bold" style={{ color: auditStats.chain_valid ? "#10b981" : "#f43f5e" }}>
                {auditStats.chain_valid ? "Valid" : "Broken"}
              </p>
              {auditStats.last_entry_hash && (
                <p className="text-[10px] font-mono mt-0.5" style={{ color: "var(--text-low)" }}>
                  {auditStats.last_entry_hash.slice(0, 20)}…
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
