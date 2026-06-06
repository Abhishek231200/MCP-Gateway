import { useLocation, Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";

export default function Layout() {
  const { pathname } = useLocation();
  const isWorkflows = pathname === "/workflows";

  return (
    <div className="flex h-screen overflow-hidden bg-[#0d0d0d]">
      <Sidebar />
      <main className="flex-1 min-w-0 overflow-hidden">
        {isWorkflows ? (
          <Outlet />
        ) : (
          <div className="h-full overflow-y-auto">
            <div className="max-w-5xl mx-auto px-8 py-8">
              <Outlet />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
