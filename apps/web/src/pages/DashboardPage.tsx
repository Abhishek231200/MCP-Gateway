import { Activity, Server, GitBranch, ShieldAlert } from "lucide-react";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import { useServers } from "@/hooks/useRegistry";
import type { McpServer } from "@/hooks/useRegistry";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}

function StatCard({ label, value, icon: Icon, description }: StatCardProps) {
  return (
    <div className="card flex items-start gap-4">
      <div className="p-2 bg-brand-900/50 rounded-lg border border-brand-800">
        <Icon className="w-5 h-5 text-brand-400" />
      </div>
      <div>
        <p className="text-2xl font-bold text-white">{value}</p>
        <p className="text-sm font-medium text-gray-300 mt-0.5">{label}</p>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </div>
    </div>
  );
}

// ── Adapter health widget ─────────────────────────────────────────────────────

const ADAPTER_LABELS: Record<string, string> = {
  github: "GitHub",
  slack: "Slack",
  gdrive: "Google Drive",
  kb: "Knowledge Base",
};

const ADAPTER_ICONS: Record<string, string> = {
  github: "⚙",
  slack: "💬",
  gdrive: "📁",
  kb: "🔍",
};

interface AdapterStat {
  type: string;
  label: string;
  icon: string;
  total: number;
  healthy: number;
  degraded: number;
  unhealthy: number;
}

function buildAdapterStats(servers: McpServer[]): AdapterStat[] {
  const map = new Map<string, AdapterStat>();

  for (const s of servers) {
    const type =
      typeof s.metadata?.adapter_type === "string"
        ? s.metadata.adapter_type
        : "unknown";

    if (!map.has(type)) {
      map.set(type, {
        type,
        label: ADAPTER_LABELS[type] ?? type,
        icon: ADAPTER_ICONS[type] ?? "◈",
        total: 0,
        healthy: 0,
        degraded: 0,
        unhealthy: 0,
      });
    }

    const stat = map.get(type)!;
    stat.total += 1;
    if (s.health_status === "healthy") stat.healthy += 1;
    else if (s.health_status === "degraded") stat.degraded += 1;
    else stat.unhealthy += 1;
  }

  return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label));
}

function AdapterHealthWidget() {
  const { data, isLoading } = useServers(false);

  if (isLoading) {
    return (
      <div className="card">
        <h3 className="text-sm font-semibold text-white mb-3">Adapter Health</h3>
        <p className="text-sm text-gray-500">Loading…</p>
      </div>
    );
  }

  if (!data || data.total === 0) {
    return (
      <div className="card">
        <h3 className="text-sm font-semibold text-white mb-3">Adapter Health</h3>
        <p className="text-sm text-gray-500">No servers registered yet.</p>
      </div>
    );
  }

  const stats = buildAdapterStats(data.items);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-white">Adapter Health</h3>
        <span className="text-xs text-gray-500">{data.total} server{data.total !== 1 ? "s" : ""} total</span>
      </div>

      <div className="space-y-2">
        {stats.map((s) => (
          <div
            key={s.type}
            className="flex items-center justify-between py-2 border-t border-gray-800 first:border-t-0"
          >
            {/* Adapter name */}
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-base">{s.icon}</span>
              <div>
                <p className="text-sm text-gray-200">{s.label}</p>
                <p className="text-xs text-gray-500 font-mono">{s.type}</p>
              </div>
            </div>

            {/* Health dots */}
            <div className="flex items-center gap-3 text-xs shrink-0">
              {s.healthy > 0 && (
                <span className="badge-healthy">● {s.healthy} healthy</span>
              )}
              {s.degraded > 0 && (
                <span className="badge-degraded">◐ {s.degraded} degraded</span>
              )}
              {s.unhealthy > 0 && (
                <span className="badge-unhealthy">● {s.unhealthy} unhealthy</span>
              )}
              {s.healthy === 0 && s.degraded === 0 && s.unhealthy === 0 && (
                <span className="badge-unknown">◌ unknown</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { data: health, isLoading } = useHealthCheck();
  const { data: registry } = useServers();

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-white">System Overview</h2>
        <p className="text-sm text-gray-400 mt-1">
          Real-time status of your MCP Gateway deployment.
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          label="Registered Servers"
          value={registry?.total ?? "—"}
          icon={Server}
          description="Active MCP servers in registry"
        />
        <StatCard
          label="Workflows Today"
          value="—"
          icon={GitBranch}
          description="Workflow executions in last 24h"
        />
        <StatCard
          label="Tool Calls"
          value="—"
          icon={Activity}
          description="Total tool invocations today"
        />
        <StatCard
          label="Blocked Actions"
          value="—"
          icon={ShieldAlert}
          description="Security gateway blocks today"
        />
      </div>

      {/* Adapter health + dependency health side by side on wide screens */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AdapterHealthWidget />

        {/* API / infra health */}
        <div className="card">
          <h3 className="text-sm font-semibold text-white mb-3">Dependency Health</h3>
          {isLoading ? (
            <p className="text-sm text-gray-500">Checking…</p>
          ) : health ? (
            <div className="space-y-2">
              {Object.entries(health.dependencies).map(([name, dep]) => (
                <div key={name} className="flex items-center justify-between text-sm">
                  <span className="text-gray-300 capitalize">{name}</span>
                  <div className="flex items-center gap-3">
                    {dep.latency_ms != null && (
                      <span className="text-xs text-gray-500 font-mono">{dep.latency_ms}ms</span>
                    )}
                    <span className={`badge-${dep.status}`}>
                      <span className="w-1.5 h-1.5 rounded-full bg-current" />
                      {dep.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-red-400">API unreachable</p>
          )}
        </div>
      </div>
    </div>
  );
}
