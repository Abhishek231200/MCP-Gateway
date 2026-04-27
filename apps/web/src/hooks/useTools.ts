import { useMutation } from "@tanstack/react-query";
import axios from "axios";

export interface InvokeToolPayload {
  server_id: string;
  tool_name: string;
  arguments?: Record<string, unknown>;
  actor?: string;
}

export interface InvokeToolResponse {
  result: unknown;
  latency_ms: number;
  server_name: string;
  tool_name: string;
  adapter_type: string;
}

export function useInvokeTool() {
  return useMutation({
    mutationFn: async (payload: InvokeToolPayload) => {
      const { data } = await axios.post<InvokeToolResponse>("/api/tools/invoke", payload);
      return data;
    },
  });
}
