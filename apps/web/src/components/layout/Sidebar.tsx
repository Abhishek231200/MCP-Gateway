import { useState } from "react";
import { NavLink, useNavigate, useSearchParams, useLocation } from "react-router-dom";
import {
  ShieldCheck, LayoutDashboard, Server, ScrollText, Plus,
  MessageSquare, Loader2, Activity, ChevronLeft, ChevronRight,
  Search, X, LogOut,
} from "lucide-react";
import { clsx } from "clsx";
import { useWorkflows, type Workflow, type WorkflowStatus } from "@/hooks/useWorkflows";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import { useAuth } from "@/contexts/AuthContext";

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusDot(status: WorkflowStatus) {
  const map: Record<WorkflowStatus, string> = {
    pending:           "bg-gray-600",
    planning:          "bg-yellow-400",
    running:           "bg-brand-400 animate-pulse",
    awaiting_approval: "bg-orange-400 animate-pulse",
    completed:         "bg-emerald-400",
    failed:            "bg-red-400",
    cancelled:         "bg-gray-600",
  };
  return map[status] ?? "bg-gray-600";
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// ── History item ──────────────────────────────────────────────────────────────

function HistoryItem({ workflow, isSelected, onClick }: {
  workflow: Workflow;
  isSelected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "w-full text-left px-3 py-2.5 rounded-lg transition-colors",
        isSelected ? "bg-white/10 text-white" : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
      )}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className={clsx("w-1.5 h-1.5 rounded-full shrink-0", statusDot(workflow.status))} />
        <span className="text-xs truncate leading-relaxed">{workflow.task}</span>
      </div>
      <p className="text-[11px] text-gray-600 mt-0.5 pl-3.5">{relativeTime(workflow.created_at)}</p>
    </button>
  );
}

// ── Nav icon (collapsed mode) ─────────────────────────────────────────────────

function NavIcon({ to, icon: Icon, label }: { to: string; icon: React.ElementType; label: string }) {
  return (
    <NavLink
      to={to}
      title={label}
      className={({ isActive }) =>
        clsx(
          "w-9 h-9 rounded-lg flex items-center justify-center transition-colors",
          isActive ? "bg-white/10 text-white" : "text-gray-600 hover:text-gray-200 hover:bg-white/5"
        )
      }
    >
      <Icon className="w-4 h-4" />
    </NavLink>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [search, setSearch] = useState("");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { pathname } = useLocation();
  const selectedId = searchParams.get("wf");

  const { data, isLoading } = useWorkflows(50);
  const { data: health } = useHealthCheck();
  const isHealthy = health?.status === "healthy";
  const { user, logout, isAdmin } = useAuth();

  const filteredItems = search.trim()
    ? (data?.items ?? []).filter((wf) =>
        wf.task.toLowerCase().includes(search.toLowerCase())
      )
    : (data?.items ?? []);

  const handleNew = () => navigate("/workflows", { state: { fromSidebar: true } });
  const handleSelect = (id: string) =>
    navigate(`/workflows?wf=${id}`, { state: { fromSidebar: true } });

  // ── Collapsed view ──────────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <aside className="w-14 flex-shrink-0 bg-[#111111] border-r border-white/5 flex flex-col items-center h-full py-3 gap-1.5">
        <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center mb-1">
          <ShieldCheck className="w-4 h-4 text-white" />
        </div>

        <button
          onClick={() => setCollapsed(false)}
          title="Expand sidebar"
          className="w-9 h-9 rounded-lg flex items-center justify-center text-gray-600 hover:text-gray-200 hover:bg-white/5 transition-colors mb-1"
        >
          <ChevronRight className="w-4 h-4" />
        </button>

        <button
          onClick={handleNew}
          title="New Workflow"
          className={clsx(
            "w-9 h-9 rounded-lg flex items-center justify-center transition-colors",
            pathname === "/workflows" && !selectedId
              ? "bg-brand-600 text-white"
              : "bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white"
          )}
        >
          <Plus className="w-4 h-4" />
        </button>

        <div className="flex-1" />

        <NavIcon to="/dashboard" icon={LayoutDashboard} label="Dashboard" />
        {isAdmin && <NavIcon to="/registry" icon={Server} label="Registry" />}
        <NavIcon to="/audit" icon={ScrollText} label="Audit Log" />

        <div className="mt-2 pt-2 border-t border-white/5 w-full flex flex-col items-center gap-2">
          <span className={clsx("w-1.5 h-1.5 rounded-full", isHealthy ? "bg-emerald-400" : "bg-red-400")} />
          {user && (
            <button onClick={logout} title="Sign out" className="text-gray-600 hover:text-gray-300">
              <LogOut className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </aside>
    );
  }

  // ── Expanded view ───────────────────────────────────────────────────────────
  return (
    <aside className="w-64 flex-shrink-0 bg-[#111111] border-r border-white/5 flex flex-col h-full">

      {/* Header */}
      <div className="px-4 py-4 flex items-center justify-between border-b border-white/5">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-brand-600 flex items-center justify-center">
            <ShieldCheck className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="text-sm font-semibold text-white leading-none">MCP Gateway</p>
            <p className="text-[11px] text-gray-600 mt-0.5">Agentic Orchestration</p>
          </div>
        </div>
        <button
          onClick={() => setCollapsed(true)}
          className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-600 hover:text-gray-300 hover:bg-white/5 transition-colors"
          title="Collapse sidebar"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
      </div>

      {/* New workflow */}
      <div className="px-3 pt-3 pb-2">
        <button
          onClick={handleNew}
          className={clsx(
            "w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
            pathname === "/workflows" && !selectedId
              ? "bg-brand-600 text-white"
              : "bg-white/5 text-gray-300 hover:bg-white/10 hover:text-white"
          )}
        >
          <Plus className="w-4 h-4" />
          New Workflow
        </button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-600 pointer-events-none" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search workflows…"
            className="w-full bg-white/5 border border-white/5 rounded-lg pl-8 pr-7 py-1.5 text-xs text-gray-300 placeholder-gray-600 focus:outline-none focus:border-white/10"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-300"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* History */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="w-4 h-4 text-gray-600 animate-spin" />
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="px-3 py-4 text-center">
            <MessageSquare className="w-5 h-5 text-gray-700 mx-auto mb-2" />
            <p className="text-xs text-gray-600">
              {search ? "No matching workflows" : "No workflows yet"}
            </p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {filteredItems.map((wf) => (
              <HistoryItem
                key={wf.id}
                workflow={wf}
                isSelected={pathname === "/workflows" && selectedId === wf.id}
                onClick={() => handleSelect(wf.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Bottom nav */}
      <div className="border-t border-white/5 px-2 pt-2 pb-1">
        {[
          { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard", show: true },
          { to: "/registry", icon: Server, label: "Registry", show: isAdmin },
          { to: "/audit", icon: ScrollText, label: "Audit Log", show: true },
        ].filter((item) => item.show).map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors",
                isActive ? "bg-white/10 text-white font-medium" : "text-gray-500 hover:text-gray-200 hover:bg-white/5"
              )
            }
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </div>

      {/* User + footer */}
      <div className="border-t border-white/5 px-3 py-3">
        {user && (
          <div className="flex items-center gap-2.5 mb-2">
            <div className="w-7 h-7 rounded-full bg-brand-900/60 border border-brand-700/40 flex items-center justify-center shrink-0">
              <span className="text-xs font-semibold text-brand-300">
                {user.name.charAt(0).toUpperCase()}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-gray-200 truncate">{user.name}</p>
              <p className="text-[11px] text-gray-600 truncate">{user.role}</p>
            </div>
            <button
              onClick={logout}
              title="Sign out"
              className="w-6 h-6 flex items-center justify-center text-gray-600 hover:text-gray-300 transition-colors shrink-0"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
        <div className="flex items-center justify-between">
          <p className="text-[11px] text-gray-700">v0.1.0 · Spring 2026</p>
          <div className="flex items-center gap-1.5">
            <Activity className="w-3 h-3 text-gray-600" />
            <span className={clsx("w-1.5 h-1.5 rounded-full", isHealthy ? "bg-emerald-400" : "bg-red-400")} />
          </div>
        </div>
      </div>
    </aside>
  );
}
