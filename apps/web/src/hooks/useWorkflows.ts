import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import axios from "axios";

// ── Analyze types ─────────────────────────────────────────────────────────────

export interface AnalyzeOption {
  value: string;
  label: string;
}

export interface AnalyzeQuestion {
  id: string;
  label: string;
  description: string;
  type: "select" | "text" | "searchable_select";
  required: boolean;
  options: AnalyzeOption[];
  placeholder: string;
}

export interface AnalyzeResponse {
  needs_clarification: boolean;
  questions: AnalyzeQuestion[];
}

// ── Types ─────────────────────────────────────────────────────────────────────

export type WorkflowStatus =
  | "pending"
  | "planning"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export type StepStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface WorkflowStep {
  id: string;
  step_order: number;
  agent_role: string;
  server_name: string | null;
  tool_name: string | null;
  status: StepStatus;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown> | null;
  error_message: string | null;
  tokens_used: number;
  latency_ms: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface Workflow {
  id: string;
  task: string;
  initiated_by: string;
  status: WorkflowStatus;
  plan: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error_message: string | null;
  total_tokens_used: number;
  conversation_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  steps: WorkflowStep[];
}

export interface WorkflowListResponse {
  total: number;
  items: Workflow[];
}

export interface StreamEvent {
  type: string;
  workflow_id: string;
  timestamp?: string;
  [key: string]: unknown;
}

// ── Terminal states that stop polling ────────────────────────────────────────

const TERMINAL_STATUSES: WorkflowStatus[] = ["completed", "failed", "cancelled"];
const TERMINAL_EVENT_TYPES = new Set(["workflow_completed", "workflow_failed"]);

// ── REST hooks ────────────────────────────────────────────────────────────────

export function useWorkflows(limit = 20, rootsOnly = false) {
  return useQuery<WorkflowListResponse>({
    queryKey: ["workflows", limit, rootsOnly],
    queryFn: async () => {
      const { data } = await axios.get<WorkflowListResponse>("/api/workflows", {
        params: { limit, roots_only: rootsOnly },
      });
      return data;
    },
    refetchInterval: 5_000,
  });
}

export function useConversation(rootId: string | null) {
  return useQuery<Workflow[]>({
    queryKey: ["conversation", rootId],
    queryFn: async () => {
      const { data } = await axios.get<WorkflowListResponse>("/api/workflows", {
        params: { conversation_root_id: rootId },
      });
      return data.items;
    },
    enabled: rootId !== null,
    refetchInterval: 3_000,
  });
}

export function useWorkflow(id: string | null) {
  return useQuery<Workflow>({
    queryKey: ["workflows", id],
    queryFn: async () => {
      const { data } = await axios.get<Workflow>(`/api/workflows/${id}`);
      return data;
    },
    enabled: id !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL_STATUSES.includes(status) ? false : 3_000;
    },
  });
}

export function useCreateWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { task: string; actor?: string; conversation_id?: string | null }) => {
      const { data } = await axios.post<Workflow>("/api/workflows", payload);
      return data;
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
      if (vars.conversation_id) {
        qc.invalidateQueries({ queryKey: ["conversation", vars.conversation_id] });
      }
    },
  });
}

export function useAnalyzeWorkflow() {
  return useMutation({
    mutationFn: async (payload: { task: string; actor?: string }) => {
      const { data } = await axios.post<AnalyzeResponse>("/api/workflows/analyze", payload);
      return data;
    },
  });
}

export function useApproveCheckpoint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (workflowId: string) => {
      const { data } = await axios.post(`/api/workflows/${workflowId}/approve`);
      return data;
    },
    onSuccess: (_data, workflowId) => {
      qc.invalidateQueries({ queryKey: ["workflows", workflowId] });
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useRejectCheckpoint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (workflowId: string) => {
      const { data } = await axios.post(`/api/workflows/${workflowId}/reject`);
      return data;
    },
    onSuccess: (_data, workflowId) => {
      qc.invalidateQueries({ queryKey: ["workflows", workflowId] });
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

// ── WebSocket stream hook ─────────────────────────────────────────────────────

export function useWorkflowStream(workflowId: string | null) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!workflowId) {
      setEvents([]);
      setIsConnected(false);
      return;
    }

    setEvents([]);

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(
      `${proto}://${window.location.host}/api/workflows/${workflowId}/stream`
    );
    wsRef.current = ws;

    ws.onopen = () => setIsConnected(true);

    ws.onmessage = (e) => {
      try {
        const event: StreamEvent = JSON.parse(e.data as string);
        setEvents((prev) => [...prev, event]);
        if (TERMINAL_EVENT_TYPES.has(event.type)) {
          ws.close();
        }
      } catch {
        // silently ignore malformed frames
      }
    };

    ws.onclose = () => setIsConnected(false);
    ws.onerror = () => setIsConnected(false);

    return () => {
      ws.close();
      setIsConnected(false);
    };
  }, [workflowId]);

  return { events, isConnected };
}
