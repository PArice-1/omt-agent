import type { OmtClient } from "./contracts";
import { healthSchema, messagesSchema, runSchema, sessionSchema, sessionsSchema } from "./schemas";
import { createTransport, type TransportOptions } from "./transport";

export function createOmtClient(options: TransportOptions): OmtClient {
  const request = createTransport(options);
  const sessionPath = (id: string) => `/api/v1/sessions/${encodeURIComponent(id)}`;
  return {
    health: () => request("/health", healthSchema, {}, false),
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
