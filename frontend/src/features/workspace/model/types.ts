import type { MessageResponse, SessionResponse, ThinkingResponse } from "@/lib/omt-api/contracts";

export type RunPhase = "idle" | "sending" | "completed" | "rejected" | "needs_attention" | "failed" | "cancelled" | "unknown";
export type StreamItem =
  | { kind: "assistant"; id: string; text: string; reasoning: string; completed: boolean }
  | { kind: "tool"; id: string; name: string; input?: unknown; deltas: unknown[]; result?: unknown; status: "running" | "success" | "error" };
export interface RunState {
  phase: RunPhase;
  message?: string;
  answer?: string;
  error?: string;
  runId?: string;
  warnings?: string[];
  reviewed?: boolean;
  receiving?: boolean;
  stopping?: boolean;
  thinking?: ThinkingResponse | null;
  items?: StreamItem[];
}
export interface HistoryState {
  status: "loading" | "ready" | "error";
  messages: MessageResponse[];
  error?: string;
}
export interface WorkspaceState {
  connection: "disconnected" | "connecting" | "connected";
  connectionError?: string;
  backendStatus: "unknown" | "available" | "unavailable";
  sessions: SessionResponse[];
  selectedId: string | null;
  histories: Record<string, HistoryState>;
  runs: Record<string, RunState>;
  creating: boolean;
  refreshing: boolean;
  notice?: string;
  noticeSource?: "sessions" | "create" | "selection" | "input";
}
