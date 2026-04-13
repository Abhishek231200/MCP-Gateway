import { Activity, Server, GitBranch, ShieldAlert } from "lucide-react";
import { useHealthCheck } from "@/hooks/useHealthCheck";

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

export default function DashboardPage() {
  const { data: health, isLoading } = useHealthCheck();

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
          value="—"
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

      {/* API health */}
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
  );
}
