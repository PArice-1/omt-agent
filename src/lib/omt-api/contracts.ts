import type { z } from "zod";
import type { healthSchema, messageSchema, runSchema, sessionSchema, toolCallSchema, runtimeSchema, thinkingSchema, modelsSchema, providersSchema, previewSchema, confirmationSchema } from "./schemas";
import type { RunEvent, TerminalEvent } from "./events";
export type { RunEvent, TerminalEvent } from "./events";
export type RuntimeResponse = z.infer<typeof runtimeSchema>;
export type ThinkingResponse = z.infer<typeof thinkingSchema>;
export type ModelsResponse = z.infer<typeof modelsSchema>;
export type ProvidersResponse = z.infer<typeof providersSchema>;
export type LoginPreview = z.infer<typeof previewSchema>;
export type LoginConfirmation = z.infer<typeof confirmationSchema>;

export type SessionResponse = z.infer<typeof sessionSchema>;
export type MessageResponse = z.infer<typeof messageSchema>;
export type ToolCallResponse = z.infer<typeof toolCallSchema>;
export type RunResponse = z.infer<typeof runSchema>;
export type HealthResponse = z.infer<typeof healthSchema>;
export interface CreateSessionRequest { title?: string | null }
export interface OmtClient {
  health(): Promise<HealthResponse>;
  getRuntime(): Promise<RuntimeResponse>;
  listProviders(): Promise<ProvidersResponse>;
  listModels(): Promise<ModelsResponse>;
  previewLogin(provider: string, apiKey?: string): Promise<LoginPreview>;
  confirmLogin(loginId: string, model: string): Promise<LoginConfirmation>;
  changeModel(provider: string, model: string): Promise<RuntimeResponse>;
  changeThinking(level: string): Promise<RuntimeResponse>;
  streamRun(sessionId: string, message: string, onEvent: (event: RunEvent) => void, signal: AbortSignal): Promise<TerminalEvent>;
  listSessions(): Promise<SessionResponse[]>;
  createSession(input?: CreateSessionRequest): Promise<SessionResponse>;
  getMessages(sessionId: string): Promise<MessageResponse[]>;
  run(sessionId: string, message: string): Promise<RunResponse>;
}
