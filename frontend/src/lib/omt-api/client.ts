import type { OmtClient } from "./contracts";
import { healthSchema, messagesSchema, runSchema, sessionSchema, sessionsSchema, runtimeSchema, providersSchema, modelsSchema, previewSchema, confirmationSchema } from "./schemas";
import { createStreamRun } from "./stream";
import { createTransport, type TransportOptions } from "./transport";

/** 创建相对于 API 根路径的业务客户端；与同源代理共用固定命名空间。 */
export function createOmtClient(options: TransportOptions = {}): OmtClient {
  const request = createTransport(options);
  const sessionPath = (id: string) => `/sessions/${encodeURIComponent(id)}`;
  return {
    health: () => request("/health", healthSchema),
    getRuntime: () => request("/runtime", runtimeSchema),
    listProviders: () => request("/providers", providersSchema),
    listModels: () => request("/models", modelsSchema),
    previewLogin: (provider, apiKey) => request("/model-logins", previewSchema, {
      method: "POST", body: JSON.stringify({ provider, ...(apiKey === undefined ? {} : { api_key: apiKey }) }),
    }),
    confirmLogin: (loginId, model) => request(`/model-logins/${encodeURIComponent(loginId)}/confirm`, confirmationSchema, {
      method: "POST", body: JSON.stringify({ model }),
    }),
    changeModel: (provider, model) => request("/runtime/model", runtimeSchema, {
      method: "PUT", body: JSON.stringify({ provider, model }),
    }),
    changeThinking: (level) => request("/runtime/thinking", runtimeSchema, {
      method: "PUT", body: JSON.stringify({ level }),
    }),
    streamRun: createStreamRun(options),
    listSessions: () => request("/sessions", sessionsSchema),
    createSession: (input = {}) => request("/sessions", sessionSchema, {
      method: "POST",
      body: JSON.stringify(input.title === undefined ? {} : { title: input.title }),
    }),
    getMessages: (id) => request(`${sessionPath(id)}/messages`, messagesSchema),
    run: (id, message) => request(`${sessionPath(id)}/runs`, runSchema, {
      method: "POST", body: JSON.stringify({ message }),
    }),
  };
}
