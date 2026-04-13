import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/layout/Layout";
import DashboardPage from "@/pages/DashboardPage";
import RegistryPage from "@/pages/RegistryPage";
import WorkflowsPage from "@/pages/WorkflowsPage";
import AuditLogPage from "@/pages/AuditLogPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/registry" element={<RegistryPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/audit" element={<AuditLogPage />} />
      </Route>
    </Routes>
  );
}
