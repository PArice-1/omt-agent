import type { MessageResponse, SessionResponse } from "@/lib/omt-api/contracts";

export type RunPhase = "idle" | "sending" | "completed" | "rejected" | "needs_attention" | "unknown";
export interface RunState {
  phase: RunPhase;
  message?: string;
  answer?: string;
  error?: string;
  runId?: string;
  warnings?: string[];
  reviewed?: boolean;
}
export interface HistoryState {
  status: "loading" | "ready" | "error";
  messages: MessageResponse[];
  error?: string;
}
export interface WorkspaceState {
  connection: "disconnected" | "connecting" | "connected";
  connectionError?: string;
  sessions: SessionResponse[];
  selectedId: string | null;
  histories: Record<string, HistoryState>;
  runs: Record<string, RunState>;
  creating: boolean;
  refreshing: boolean;
  notice?: string;
}
