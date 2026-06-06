import { useQuery } from "@tanstack/react-query";
import axios from "axios";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AuditLogEntry {
  id: string;
  workflow_id: string | null;
  action: string;
  actor: string;
  server_name: string | null;
  tool_name: string | null;
  allowed: boolean | null;
  policy_decision: Record<string, unknown> | null;
  response_payload: Record<string, unknown> | null;
  latency_ms: number | null;
  created_at: string;
  entry_hash: string | null;
  prev_hash: string | null;
}

export interface AuditLogListResponse {
  total: number;
  items: AuditLogEntry[];
}

export interface AuditStatsResponse {
  total: number;
  blocked_today: number;
  tool_calls_today: number;
  chain_valid: boolean;
  last_entry_hash: string | null;
}

export interface AuditLogParams {
  actor?: string;
  server?: string;
  tool?: string;
  action?: string;
  allowed?: boolean | "";
  limit?: number;
  offset?: number;
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

export function useAuditLogs(params: AuditLogParams = {}) {
  // Strip empty strings so they don't get sent as query params
  const cleaned = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== "" && v !== undefined)
  );
  return useQuery<AuditLogListResponse>({
    queryKey: ["audit-logs", cleaned],
    queryFn: async () => {
      const { data } = await axios.get<AuditLogListResponse>("/api/audit-logs", {
        params: cleaned,
      });
      return data;
    },
    refetchInterval: 10_000,
  });
}

export function useAuditStats() {
  return useQuery<AuditStatsResponse>({
    queryKey: ["audit-stats"],
    queryFn: async () => {
      const { data } = await axios.get<AuditStatsResponse>("/api/audit-logs/stats");
      return data;
    },
    refetchInterval: 30_000,
  });
}
