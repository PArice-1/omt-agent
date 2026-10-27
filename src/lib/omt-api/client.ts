import type { OmtClient } from "./contracts";
import { healthSchema, messagesSchema, runSchema, sessionSchema, sessionsSchema, runtimeSchema, providersSchema, modelsSchema, previewSchema, confirmationSchema } from "./schemas";
import { createStreamRun } from "./stream";
import { createTransport, type TransportOptions } from "./transport";

export function createOmtClient(options: TransportOptions = {}): OmtClient {
  const request = createTransport(options);
  const sessionPath = (id: string) => `/api/v1/sessions/${encodeURIComponent(id)}`;
  return {
    health: () => request("/health", healthSchema),
    getRuntime: () => request("/api/v1/runtime", runtimeSchema),
    listProviders: () => request("/api/v1/providers", providersSchema),
    listModels: () => request("/api/v1/models", modelsSchema),
    previewLogin: (provider, apiKey) => request("/api/v1/model-logins", previewSchema, {
      method: "POST", body: JSON.stringify({ provider, ...(apiKey === undefined ? {} : { api_key: apiKey }) }),
    }),
    confirmLogin: (loginId, model) => request(`/api/v1/model-logins/${encodeURIComponent(loginId)}/confirm`, confirmationSchema, {
      method: "POST", body: JSON.stringify({ model }),
    }),
    changeModel: (provider, model) => request("/api/v1/runtime/model", runtimeSchema, {
      method: "PUT", body: JSON.stringify({ provider, model }),
    }),
    changeThinking: (level) => request("/api/v1/runtime/thinking", runtimeSchema, {
      method: "PUT", body: JSON.stringify({ level }),
    }),
    streamRun: createStreamRun(options),
    listSessions: () => request("/api/v1/sessions", sessionsSchema),
    createSession: (input = {}) => request("/api/v1/sessions", sessionSchema, {
      method: "POST",
      body: JSON.stringify(input.title === undefined ? {} : { title: input.title }),
    }),
    getMessages: (id) => request(`${sessionPath(id)}/messages`, messagesSchema),
    run: (id, message) => request(`${sessionPath(id)}/runs`, runSchema, {
      method: "POST", body: JSON.stringify({ message }),
    }),
  };
}
