import { useLocation } from "react-router-dom";
import { Activity } from "lucide-react";
import { useHealthCheck } from "@/hooks/useHealthCheck";

const pageTitles: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/registry": "MCP Registry",
  "/workflows": "Workflows",
  "/audit": "Audit Log",
};

export default function Topbar() {
  const { pathname } = useLocation();
  const { data: health } = useHealthCheck();

  const title = pageTitles[pathname] ?? "MCP Gateway";
  const isHealthy = health?.status === "healthy";

  return (
    <header className="h-14 flex-shrink-0 bg-gray-900 border-b border-gray-800 flex items-center justify-between px-6">
      <h1 className="text-sm font-semibold text-white">{title}</h1>

      <div className="flex items-center gap-2 text-xs text-gray-400">
        <Activity className="w-3.5 h-3.5" />
        <span>API</span>
        <span
          className={`w-2 h-2 rounded-full ${
            isHealthy ? "bg-emerald-400" : "bg-red-400"
          }`}
        />
      </div>
    </header>
  );
}
