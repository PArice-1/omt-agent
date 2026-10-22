import type { z } from "zod";
import type { healthSchema, messageSchema, runSchema, sessionSchema, toolCallSchema } from "./schemas";

export type SessionResponse = z.infer<typeof sessionSchema>;
export type MessageResponse = z.infer<typeof messageSchema>;
export type ToolCallResponse = z.infer<typeof toolCallSchema>;
export type RunResponse = z.infer<typeof runSchema>;
export type HealthResponse = z.infer<typeof healthSchema>;
export interface CreateSessionRequest { title?: string | null }
export interface OmtClient {
  health(): Promise<HealthResponse>;
  listSessions(): Promise<SessionResponse[]>;
  createSession(input?: CreateSessionRequest): Promise<SessionResponse>;
  getMessages(sessionId: string): Promise<MessageResponse[]>;
  run(sessionId: string, message: string): Promise<RunResponse>;
}
