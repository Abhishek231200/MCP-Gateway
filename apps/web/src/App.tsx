import { Navigate, Outlet, Routes, Route } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import Layout from "@/components/layout/Layout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import RegistryPage from "@/pages/RegistryPage";
import WorkflowsPage from "@/pages/WorkflowsPage";
import AuditLogPage from "@/pages/AuditLogPage";
import { Loader2 } from "lucide-react";

function RequireAuth() {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0d0d0d] flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-gray-600 animate-spin" />
      </div>
    );
  }
  return user ? <Outlet /> : <Navigate to="/login" replace />;
}

export default function App() {
  const { user } = useAuth();

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/workflows" replace />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          {/* Registry only accessible to admins */}
          {user?.role === "admin" && (
            <Route path="/registry" element={<RegistryPage />} />
          )}
          <Route path="/audit" element={<AuditLogPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
