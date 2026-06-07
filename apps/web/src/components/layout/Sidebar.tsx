import { useState } from "react";
import { NavLink, useNavigate, useSearchParams, useLocation } from "react-router-dom";
import {
  ShieldCheck, LayoutDashboard, Server, ScrollText, Plus,
  MessageSquare, Loader2, Activity, ChevronLeft, ChevronRight,
  Search, X, LogOut, Zap,
} from "lucide-react";
import { clsx } from "clsx";
import { useWorkflows, type Workflow, type WorkflowStatus } from "@/hooks/useWorkflows";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import { useAuth } from "@/contexts/AuthContext";

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusDot(status: WorkflowStatus) {
  const map: Record<WorkflowStatus, string> = {
    pending:           "bg-[#3d5068]",
    planning:          "bg-amber-400",
    running:           "bg-brand-400 animate-pulse shadow-[0_0_6px_rgba(192,132,252,0.7)]",
    awaiting_approval: "bg-orange-400 animate-pulse",
    completed:         "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]",
    failed:            "bg-rose-500",
    cancelled:         "bg-[#3d5068]",
  };
  return map[status] ?? "bg-[#3d5068]";
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
        "w-full text-left px-3 py-2.5 rounded-lg transition-all duration-150 group",
        isSelected
          ? "bg-brand-600/15 text-[#dde6f0] shadow-[inset_2px_0_0_#0ea5e9]"
          : "text-[#7b90aa] hover:bg-white/[0.04] hover:text-[#dde6f0]"
      )}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className={clsx("w-1.5 h-1.5 rounded-full shrink-0 transition-all", statusDot(workflow.status))} />
        <span className="text-xs truncate leading-relaxed">{workflow.task}</span>
      </div>
      <p className={clsx("text-[11px] mt-0.5 pl-3.5 transition-colors", isSelected ? "text-brand-400/60" : "text-[#3d5068] group-hover:text-[#7b90aa]")}>
        {relativeTime(workflow.created_at)}
      </p>
    </button>
  );
}

// ── Collapsed nav icon ────────────────────────────────────────────────────────

function NavIcon({ to, icon: Icon, label }: { to: string; icon: React.ElementType; label: string }) {
  return (
    <NavLink
      to={to}
      title={label}
      className={({ isActive }) =>
        clsx(
          "w-9 h-9 rounded-lg flex items-center justify-center transition-all duration-150",
          isActive
            ? "bg-brand-600/15 text-brand-400 shadow-[inset_1px_0_0_#0ea5e9]"
            : "text-[#3d5068] hover:text-[#dde6f0] hover:bg-white/[0.04]"
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
  const selectedId = searchParams.get("conv");

  const { data, isLoading } = useWorkflows(50, true);
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
    navigate(`/workflows?conv=${id}`, { state: { fromSidebar: true } });

  // ── Collapsed view ──────────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <aside className="w-14 flex-shrink-0 flex flex-col items-center h-full py-3 gap-1.5"
        style={{ background: "var(--surface-1)", borderRight: "1px solid var(--border)" }}>

        {/* Logo mark */}
        <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-1"
          style={{ background: "linear-gradient(135deg,#0ea5e9,#0284c7)", boxShadow: "0 0 14px rgba(14,165,233,0.35)" }}>
          <ShieldCheck className="w-4 h-4 text-white" />
        </div>

        <button
          onClick={() => setCollapsed(false)}
          title="Expand sidebar"
          className="w-9 h-9 rounded-lg flex items-center justify-center transition-all duration-150 mb-1"
          style={{ color: "var(--text-low)" }}
          onMouseOver={e => (e.currentTarget.style.color = "var(--text-high)")}
          onMouseOut={e => (e.currentTarget.style.color = "var(--text-low)")}
        >
          <ChevronRight className="w-4 h-4" />
        </button>

        <button
          onClick={handleNew}
          title="New Workflow"
          className={clsx(
            "w-9 h-9 rounded-lg flex items-center justify-center transition-all duration-150",
            pathname === "/workflows" && !selectedId
              ? "text-white shadow-[0_0_12px_rgba(14,165,233,0.3)]"
              : "text-[#7b90aa] hover:text-[#dde6f0]"
          )}
          style={pathname === "/workflows" && !selectedId
            ? { background: "linear-gradient(135deg,#0ea5e9,#0284c7)" }
            : { background: "rgba(255,255,255,0.04)" }
          }
        >
          <Plus className="w-4 h-4" />
        </button>

        <div className="flex-1" />

        <NavIcon to="/dashboard" icon={LayoutDashboard} label="Dashboard" />
        {isAdmin && <NavIcon to="/registry" icon={Server} label="Registry" />}
        <NavIcon to="/audit" icon={ScrollText} label="Audit Log" />

        <div className="mt-2 pt-2 w-full flex flex-col items-center gap-2"
          style={{ borderTop: "1px solid var(--border)" }}>
          <span className={clsx(
            "w-2 h-2 rounded-full",
            isHealthy ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]" : "bg-rose-500"
          )} />
          {user && (
            <button onClick={logout} title="Sign out" className="text-[#3d5068] hover:text-[#7b90aa] transition-colors">
              <LogOut className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </aside>
    );
  }

  // ── Expanded view ───────────────────────────────────────────────────────────
  return (
    <aside className="w-64 flex-shrink-0 flex flex-col h-full"
      style={{ background: "var(--surface-1)", borderRight: "1px solid var(--border)" }}>

      {/* Header */}
      <div className="px-4 py-4 flex items-center justify-between"
        style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: "linear-gradient(135deg,#0ea5e9,#0284c7)", boxShadow: "0 0 16px rgba(14,165,233,0.35)" }}>
            <ShieldCheck className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="text-sm font-semibold leading-none" style={{ color: "var(--text-high)" }}>
              MCP Gateway
            </p>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--text-low)" }}>
              Agentic Orchestration
            </p>
          </div>
        </div>
        <button
          onClick={() => setCollapsed(true)}
          className="w-6 h-6 rounded-md flex items-center justify-center transition-all duration-150"
          style={{ color: "var(--text-low)" }}
          onMouseOver={e => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; e.currentTarget.style.color = "var(--text-high)"; }}
          onMouseOut={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-low)"; }}
          title="Collapse"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* New workflow button */}
      <div className="px-3 pt-3 pb-2">
        <button
          onClick={handleNew}
          className={clsx(
            "w-full flex items-center gap-2 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-150",
          )}
          style={
            pathname === "/workflows" && !selectedId
              ? {
                  background: "linear-gradient(135deg,#0ea5e9,#0284c7)",
                  color: "#fff",
                  boxShadow: "0 0 16px rgba(14,165,233,0.3)",
                }
              : {
                  background: "rgba(14,165,233,0.08)",
                  border: "1px solid rgba(14,165,233,0.15)",
                  color: "#38bdf8",
                }
          }
        >
          <Plus className="w-3.5 h-3.5" />
          New Workflow
        </button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 pointer-events-none" style={{ color: "var(--text-low)" }} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…"
            className="w-full rounded-lg pl-8 pr-7 py-1.5 text-xs focus:outline-none transition-all"
            style={{
              background: "var(--surface-3)",
              border: "1px solid var(--border)",
              color: "var(--text-high)",
            }}
            onFocus={e => (e.currentTarget.style.borderColor = "rgba(14,165,233,0.35)")}
            onBlur={e => (e.currentTarget.style.borderColor = "var(--border)")}
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2"
              style={{ color: "var(--text-low)" }}
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      {/* Section label */}
      {filteredItems.length > 0 && (
        <div className="px-4 pb-1">
          <p className="section-label">Recent</p>
        </div>
      )}

      {/* History */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="w-4 h-4 animate-spin" style={{ color: "var(--text-low)" }} />
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <div className="w-8 h-8 rounded-lg mx-auto mb-2 flex items-center justify-center"
              style={{ background: "var(--surface-3)" }}>
              <MessageSquare className="w-4 h-4" style={{ color: "var(--text-low)" }} />
            </div>
            <p className="text-xs" style={{ color: "var(--text-low)" }}>
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
      <div className="px-2 pt-2 pb-1" style={{ borderTop: "1px solid var(--border)" }}>
        <p className="section-label px-3 mb-1.5">Tools</p>
        {[
          { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard", show: true },
          { to: "/registry", icon: Server, label: "Registry", show: isAdmin },
          { to: "/audit", icon: ScrollText, label: "Audit Log", show: true },
        ].filter((item) => item.show).map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx("nav-item", isActive && "active")
            }
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </div>

      {/* User footer */}
      <div className="px-3 py-3" style={{ borderTop: "1px solid var(--border)" }}>
        {user && (
          <div className="flex items-center gap-2.5 mb-2">
            <div className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold text-white"
              style={{ background: "linear-gradient(135deg,#0ea5e9,#0284c7)" }}>
              {user.name.charAt(0).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium truncate" style={{ color: "var(--text-high)" }}>{user.name}</p>
              <p className="text-[11px] truncate" style={{ color: "var(--text-low)" }}>
                {user.role === "admin" ? "✦ admin" : user.role}
              </p>
            </div>
            <button
              onClick={logout}
              title="Sign out"
              className="w-6 h-6 flex items-center justify-center transition-colors rounded-md"
              style={{ color: "var(--text-low)" }}
              onMouseOver={e => (e.currentTarget.style.color = "var(--text-high)")}
              onMouseOut={e => (e.currentTarget.style.color = "var(--text-low)")}
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
        <div className="flex items-center justify-between">
          <p className="text-[11px]" style={{ color: "var(--text-low)" }}>v0.1 · Spring 2026</p>
          <div className="flex items-center gap-1.5">
            <Activity className="w-3 h-3" style={{ color: "var(--text-low)" }} />
            <span className={clsx(
              "w-1.5 h-1.5 rounded-full",
              isHealthy ? "bg-emerald-400 shadow-[0_0_4px_rgba(52,211,153,0.6)]" : "bg-rose-500"
            )} />
          </div>
        </div>
      </div>
    </aside>
  );
}
