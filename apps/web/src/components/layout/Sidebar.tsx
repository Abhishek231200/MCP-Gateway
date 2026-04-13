import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Server,
  GitBranch,
  ScrollText,
  ShieldCheck,
} from "lucide-react";
import { clsx } from "clsx";

const navItems = [
  { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/registry", icon: Server, label: "Registry" },
  { to: "/workflows", icon: GitBranch, label: "Workflows" },
  { to: "/audit", icon: ScrollText, label: "Audit Log" },
];

export default function Sidebar() {
  return (
    <aside className="w-56 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
      {/* Logo */}
      <div className="px-4 py-5 flex items-center gap-2 border-b border-gray-800">
        <ShieldCheck className="text-brand-500 w-6 h-6" />
        <span className="font-semibold text-white tracking-tight">MCP Gateway</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                isActive
                  ? "bg-brand-600 text-white"
                  : "text-gray-400 hover:text-white hover:bg-gray-800"
              )
            }
          >
            <Icon className="w-4 h-4 flex-shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-gray-800">
        <p className="text-xs text-gray-600">v0.1.0 · Spring 2026</p>
      </div>
    </aside>
  );
}
