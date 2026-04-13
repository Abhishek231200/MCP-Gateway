import { useQuery } from "@tanstack/react-query";
import axios from "axios";

interface DependencyStatus {
  status: string;
  latency_ms?: number;
  detail?: string;
}

interface HealthResponse {
  status: string;
  version: string;
  environment: string;
  uptime_seconds: number;
  dependencies: Record<string, DependencyStatus>;
}

export function useHealthCheck() {
  return useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: async () => {
      const { data } = await axios.get<HealthResponse>("/api/health");
      return data;
    },
    refetchInterval: 30_000,
    retry: false,
  });
}
