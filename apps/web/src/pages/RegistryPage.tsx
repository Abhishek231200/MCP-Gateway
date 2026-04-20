import { useState } from "react";
import {
  useServers,
  useRegisterServer,
  useDeregisterServer,
} from "@/hooks/useRegistry";
import type { Capability, McpServer, RegisterServerPayload } from "@/hooks/useRegistry";

// ── Shared atoms ──────────────────────────────────────────────────────────────

const PERMISSION_CLS: Record<string, string> = {
  read: "bg-emerald-900/50 text-emerald-400 border-emerald-800",
  write: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
  admin: "bg-red-900/50 text-red-400 border-red-800",
};

const AUTH_LABELS: Record<string, string> = {
  none: "No auth",
  api_key: "API Key",
  oauth2: "OAuth 2",
  jwt: "JWT",
};

function HealthBadge({ status }: { status: string }) {
  const cls =
    status === "healthy"
      ? "badge-healthy"
      : status === "degraded"
        ? "badge-degraded"
        : status === "unhealthy"
          ? "badge-unhealthy"
          : "badge-unknown";
  const dot = status === "healthy" ? "●" : status === "unhealthy" ? "●" : "◐";
  return (
    <span className={cls}>
      {dot} {status}
    </span>
  );
}

function PermissionBadge({ permission }: { permission: string }) {
  const cls = PERMISSION_CLS[permission] ?? PERMISSION_CLS.read;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${cls}`}
    >
      {permission}
    </span>
  );
}

// ── Capability table ──────────────────────────────────────────────────────────

function CapabilityTable({ capabilities }: { capabilities: Capability[] }) {
  return (
    <div className="mt-3 rounded-lg overflow-hidden border border-gray-800">
      <table className="w-full text-sm">
        <thead className="bg-gray-800/60">
          <tr className="text-xs text-gray-500 uppercase tracking-wide">
            <th className="text-left px-3 py-2 font-medium">Tool</th>
            <th className="text-left px-3 py-2 font-medium">Description</th>
            <th className="text-left px-3 py-2 font-medium">Permission</th>
            <th className="text-right px-3 py-2 font-medium">Latency</th>
          </tr>
        </thead>
        <tbody>
          {capabilities.map((cap) => (
            <tr key={cap.id} className="border-t border-gray-800 hover:bg-gray-800/30">
              <td className="px-3 py-2 font-mono text-blue-300">{cap.tool_name}</td>
              <td className="px-3 py-2 text-gray-400">{cap.description ?? "—"}</td>
              <td className="px-3 py-2">
                <PermissionBadge permission={cap.required_permission} />
              </td>
              <td className="px-3 py-2 text-right text-gray-500">
                {cap.avg_latency_ms != null ? `${cap.avg_latency_ms} ms` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Server card ───────────────────────────────────────────────────────────────

function ServerCard({ server }: { server: McpServer }) {
  const [expanded, setExpanded] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const deregister = useDeregisterServer();

  return (
    <div className="card space-y-3">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-white">{server.display_name}</span>
            <span className="text-xs text-gray-500 font-mono bg-gray-800 px-1.5 py-0.5 rounded">
              {server.name}
            </span>
            <span className="text-xs text-gray-600 border border-gray-700 rounded px-1.5 py-0.5">
              v{server.version}
            </span>
          </div>
          <p className="text-sm text-gray-400 mt-1 truncate" title={server.base_url}>
            {server.base_url}
          </p>
          {server.description && (
            <p className="text-xs text-gray-500 mt-0.5">{server.description}</p>
          )}
        </div>
        <HealthBadge status={server.health_status} />
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-4 text-xs text-gray-500">
        <span>
          Auth:{" "}
          <span className="text-gray-300">{AUTH_LABELS[server.auth_type]}</span>
        </span>
        {server.last_health_check && (
          <span>
            Last checked:{" "}
            {new Date(server.last_health_check).toLocaleTimeString()}
          </span>
        )}
        {server.capabilities.length > 0 && (
          <button
            onClick={() => setExpanded((e) => !e)}
            className="ml-auto text-blue-400 hover:text-blue-300 transition-colors"
          >
            {expanded ? "▲" : "▼"} {server.capabilities.length} tool
            {server.capabilities.length !== 1 ? "s" : ""}
          </button>
        )}
      </div>

      {/* Capabilities */}
      {expanded && server.capabilities.length > 0 && (
        <CapabilityTable capabilities={server.capabilities} />
      )}

      {/* Footer */}
      <div className="flex justify-end pt-1 border-t border-gray-800">
        {confirming ? (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-400 text-xs">Remove this server?</span>
            <button
              onClick={() => setConfirming(false)}
              className="text-gray-400 hover:text-gray-200 px-2 py-1 text-xs"
            >
              Cancel
            </button>
            <button
              onClick={() => deregister.mutate(server.id)}
              disabled={deregister.isPending}
              className="text-red-400 hover:text-red-300 px-2 py-1 text-xs disabled:opacity-50"
            >
              {deregister.isPending ? "Removing…" : "Confirm"}
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="text-xs text-red-500/70 hover:text-red-400 transition-colors px-2 py-1"
          >
            Deregister
          </button>
        )}
      </div>
    </div>
  );
}

// ── Register form ─────────────────────────────────────────────────────────────

const EMPTY: RegisterServerPayload = {
  name: "",
  display_name: "",
  base_url: "",
  auth_type: "none",
  description: "",
};

function RegisterForm({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState<RegisterServerPayload>(EMPTY);
  const register = useRegisterServer();

  const field = (key: keyof RegisterServerPayload) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const payload = { ...form, description: form.description || undefined };
    register.mutate(payload, { onSuccess: onClose });
  };

  const input =
    "w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors";
  const label = "block text-xs text-gray-400 mb-1";

  return (
    <form onSubmit={onSubmit} className="card space-y-4 border-blue-900/50">
      <h3 className="text-sm font-semibold text-white">Register MCP Server</h3>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className={label}>
            Name{" "}
            <span className="text-gray-600">(slug — lowercase, hyphens ok)</span>
          </label>
          <input
            className={input}
            placeholder="github-mcp"
            value={form.name}
            onChange={field("name")}
            pattern="^[a-z0-9][a-z0-9_-]*$"
            required
          />
        </div>
        <div>
          <label className={label}>Display Name</label>
          <input
            className={input}
            placeholder="GitHub MCP"
            value={form.display_name}
            onChange={field("display_name")}
            required
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className={label}>Base URL</label>
          <input
            className={input}
            placeholder="http://github-mcp:3000"
            value={form.base_url}
            onChange={field("base_url")}
            required
          />
        </div>
        <div>
          <label className={label}>Auth Type</label>
          <select
            className={input}
            value={form.auth_type}
            onChange={field("auth_type")}
          >
            <option value="none">None</option>
            <option value="api_key">API Key</option>
            <option value="oauth2">OAuth 2</option>
            <option value="jwt">JWT</option>
          </select>
        </div>
      </div>

      <div>
        <label className={label}>Description (optional)</label>
        <input
          className={input}
          placeholder="What does this server do?"
          value={form.description}
          onChange={field("description")}
        />
      </div>

      {register.isError && (
        <p className="text-sm text-red-400">
          {(register.error as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail ?? "Registration failed."}
        </p>
      )}

      <div className="flex justify-end gap-3 pt-1">
        <button
          type="button"
          onClick={onClose}
          className="text-sm text-gray-400 hover:text-gray-200 px-3 py-2 transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={register.isPending}
          className="text-sm bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg transition-colors"
        >
          {register.isPending ? "Registering…" : "Register"}
        </button>
      </div>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RegistryPage() {
  const [showForm, setShowForm] = useState(false);
  const { data, isLoading, isError } = useServers();

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">MCP Registry</h2>
          <p className="text-sm text-gray-400 mt-1">
            Registered MCP servers and their capabilities.
          </p>
        </div>
        <button
          onClick={() => setShowForm((f) => !f)}
          className="text-sm bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg transition-colors shrink-0"
        >
          {showForm ? "Cancel" : "+ Register Server"}
        </button>
      </div>

      {showForm && <RegisterForm onClose={() => setShowForm(false)} />}

      {/* States */}
      {isLoading && (
        <div className="card text-sm text-gray-500">Loading servers…</div>
      )}
      {isError && (
        <div className="card text-sm text-red-400">
          Failed to load registry. Is the API running?
        </div>
      )}
      {data && data.total === 0 && !showForm && (
        <div className="card text-sm text-gray-500 text-center py-10">
          No servers registered yet.{" "}
          <button
            onClick={() => setShowForm(true)}
            className="text-blue-400 hover:text-blue-300"
          >
            Register one
          </button>
          .
        </div>
      )}

      {/* Server list */}
      {data?.items.map((server) => (
        <ServerCard key={server.id} server={server} />
      ))}

      {data && data.total > 0 && (
        <p className="text-xs text-gray-600 text-right">
          {data.total} server{data.total !== 1 ? "s" : ""} registered
        </p>
      )}
    </div>
  );
}
