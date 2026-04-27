import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";

export interface Capability {
  id: string;
  server_id: string;
  tool_name: string;
  description: string | null;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  required_permission: "read" | "write" | "admin";
  is_active: boolean;
  avg_latency_ms: number | null;
  created_at: string;
}

export interface McpServer {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  base_url: string;
  version: string;
  auth_type: "none" | "api_key" | "oauth2" | "jwt";
  health_status: "healthy" | "degraded" | "unhealthy" | "unknown";
  last_health_check: string | null;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  capabilities: Capability[];
}

export interface ServerListResponse {
  total: number;
  items: McpServer[];
}

export interface RegisterServerPayload {
  name: string;
  display_name: string;
  description?: string;
  base_url: string;
  auth_type: "none" | "api_key" | "oauth2" | "jwt";
  auth_config?: Record<string, string>;
  metadata?: Record<string, unknown>;
  capabilities?: Partial<Capability>[];
}

export interface UpdateServerPayload {
  display_name?: string;
  description?: string;
  base_url?: string;
  auth_config?: Record<string, string>;
  metadata?: Record<string, unknown>;
  is_active?: boolean;
}

export function useServers(activeOnly = true) {
  return useQuery<ServerListResponse>({
    queryKey: ["registry", "servers", { activeOnly }],
    queryFn: async () => {
      const { data } = await axios.get<ServerListResponse>("/api/registry/servers", {
        params: { active_only: activeOnly },
      });
      return data;
    },
    refetchInterval: 30_000,
  });
}

export function useRegisterServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: RegisterServerPayload) => {
      const { data } = await axios.post<McpServer>("/api/registry/servers", payload);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["registry"] }),
  });
}

export function useDeregisterServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (serverId: string) => {
      await axios.delete(`/api/registry/servers/${serverId}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["registry"] }),
  });
}

export function useUpdateServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UpdateServerPayload }) => {
      const { data: updated } = await axios.patch<McpServer>(
        `/api/registry/servers/${id}`,
        data,
      );
      return updated;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["registry"] }),
  });
}
