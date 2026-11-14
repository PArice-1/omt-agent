import { describe, expect, it, vi } from "vitest";
import { createOmtClient } from "./client";
import { ApiError, classifyRunError } from "./errors";
import { completedRun, history, sessionA, runtime } from "../../../tests/fixtures";

function setup(body: unknown, status = 200) {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => Response.json(body, { status }));
  const client = createOmtClient({ baseUrl: "http://localhost/api/omt/", fetcher });
  return { client, fetcher };
}
describe("OMT client contract", () => {
  it("validates list responses without authentication or a GET body", async () => {
    const { client, fetcher } = setup([sessionA]);
    expect(await client.listSessions()).toEqual([sessionA]);
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe("http://localhost/api/omt/sessions");
    expect(options?.headers).toBeInstanceOf(Headers);
    const headers = new Headers(options?.headers);
    expect(headers.has("Authorization")).toBe(false);
    expect(headers.has("Content-Type")).toBe(false);
    expect(options?.body).toBeUndefined();
    expect(options?.cache).toBe("no-store");
  });
  it("sends an explicit JSON object when creating an untitled session", async () => {
    const { client, fetcher } = setup(sessionA, 201);
    await client.createSession();
    expect(fetcher.mock.calls[0][1]?.method).toBe("POST");
    expect(fetcher.mock.calls[0][1]?.body).toBe("{}");
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).get("Content-Type")).toBe("application/json");
  });
  it("preserves explicit null and title whitespace", async () => {
    const { client, fetcher } = setup(sessionA, 201);
    await client.createSession({ title: null });
    await client.createSession({ title: "  hello\n" });
    expect(fetcher.mock.calls[0][1]?.body).toBe('{"title":null}');
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ title: "  hello\n" });
  });
  it("encodes opaque session IDs and accepts optional tool fields", async () => {
    const { client, fetcher } = setup(history);
    expect(await client.getMessages("a/b ?")).toEqual(history);
    expect(fetcher.mock.calls[0][0]).toContain("/a%2Fb%20%3F/messages");
  });
  it("sends only the original current message", async () => {
    const { client, fetcher } = setup(completedRun);
    await client.run("s", "  分析\n");
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({ message: "  分析\n" });
  });
  it.each([
    { path: "/runtime", method: undefined, body: undefined, response: runtime, call: (api: ReturnType<typeof createOmtClient>) => api.getRuntime() },
    { path: "/providers", method: undefined, body: undefined, response: [{ provider: "p", logged_in: true }], call: (api: ReturnType<typeof createOmtClient>) => api.listProviders() },
    { path: "/models", method: undefined, body: undefined, response: [], call: (api: ReturnType<typeof createOmtClient>) => api.listModels() },
    { path: "/runtime/model", method: "PUT", body: { provider: "p", model: "m" }, response: runtime, call: (api: ReturnType<typeof createOmtClient>) => api.changeModel("p", "m") },
    { path: "/runtime/thinking", method: "PUT", body: { level: "high" }, response: runtime, call: (api: ReturnType<typeof createOmtClient>) => api.changeThinking("high") },
    { path: "/model-logins", method: "POST", body: { provider: "p", api_key: "fake-key" }, response: { login_id: "preview", provider: "p", models: ["m"], from_cache: false, expires_in: 600 }, call: (api: ReturnType<typeof createOmtClient>) => api.previewLogin("p", "fake-key") },
    { path: "/model-logins/a%2Fb/confirm", method: "POST", body: { model: "m" }, response: { configuration_saved: true, runtime_ready: true, runtime, error: null }, call: (api: ReturnType<typeof createOmtClient>) => api.confirmLogin("a/b", "m") },
  ])("uses the documented method, path and payload for $path", async ({ path, method, body, response, call }) => {
    const { client, fetcher } = setup(response);
    await call(client);
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe(`http://localhost/api/omt${path}`);
    expect(options?.method).toBe(method);
    expect(options?.body).toBe(body === undefined ? undefined : JSON.stringify(body));
    expect(new Headers(options?.headers).has("Authorization")).toBe(false);
  });
  it("omits api_key to reuse local credentials and retains optional history fields", async () => {
    const { client, fetcher } = setup({ login_id: "p", provider: "p", models: [], from_cache: true, expires_in: 600 });
    await client.previewLogin("p");
    expect(fetcher.mock.calls[0][1]?.body).toBe('{"provider":"p"}');
    const oldAndNew = [...history, { role: "assistant", text: "正文", message_id: "m", reasoning: "独立思考", tool_calls: [] }];
    expect(await setup(oldAndNew).client.getMessages("s")).toEqual(oldAndNew);
  });
  it("does not confuse a 200 confirmation with successful activation", async () => {
    const saved = { configuration_saved: true, runtime_ready: false, runtime: { ...runtime, ready: false, thinking: null }, error: { code: "model_change_failed", message: "启用失败" } };
    expect(await setup(saved).client.confirmLogin("p", "m")).toEqual(saved);
    await expect(setup({ configured: true }).client.getRuntime()).rejects.toMatchObject({ code: "invalid_response" });
    const failed = setup({ error: { code: "manager_busy", message: "忙碌" } }, 409);
    await expect(failed.client.changeModel("p", "m")).rejects.toMatchObject({ code: "manager_busy" });
    expect(failed.fetcher).toHaveBeenCalledTimes(1);
  });
  it("health requires no authentication", async () => {
    const { client, fetcher } = setup({ status: "ok" });
    await client.health();
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).has("Authorization")).toBe(false);
  });
  it.each([
    { body: [sessionA], call: (client: ReturnType<typeof createOmtClient>) => client.listSessions() },
    { body: sessionA, call: (client: ReturnType<typeof createOmtClient>) => client.createSession() },
    { body: history, call: (client: ReturnType<typeof createOmtClient>) => client.getMessages("s") },
    { body: completedRun, call: (client: ReturnType<typeof createOmtClient>) => client.run("s", "hello") },
  ])("omits Authorization on every business endpoint ($call)", async ({ body, call }) => {
    const { client, fetcher } = setup(body);
    await call(client);
    const headers = new Headers(fetcher.mock.calls[0][1]?.headers);
    expect(headers.has("Authorization")).toBe(false);
    expect(headers.get("Accept")).toBe("application/json");
  });
  it("keeps HTTP status, error code and run ID", async () => {
    const { client, fetcher } = setup({ error: { code: "run_failed", message: "执行失败", run_id: "r1" } }, 502);
    await expect(client.run("s", "hi")).rejects.toMatchObject({ status: 502, code: "run_failed", runId: "r1" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("never retries a failed network POST", async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("network"));
    const client = createOmtClient({ fetcher });
    await expect(client.run("s", "hi")).rejects.toThrow("network");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("handles non-JSON infrastructure responses", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    await expect(createOmtClient({ fetcher }).run("s", "hi"))
      .rejects.toMatchObject({ code: "invalid_response" });
  });
  it("rejects malformed successful responses rather than asserting a type", async () => {
    const { client } = setup({ answer: "missing fields" });
    await expect(client.run("s", "hi")).rejects.toMatchObject({ code: "invalid_response" });
  });
  it("handles unexpected error envelopes", async () => {
    const { client } = setup({ detail: "oops" }, 500);
    await expect(client.listSessions()).rejects.toMatchObject({ code: "unexpected_response", status: 500 });
  });
  it.each(["storage_unavailable", "internal_error", "proxy_unavailable", "invalid_response", "future_error"])("treats %s as uncertain, not a safe rejection", (code) => {
    expect(classifyRunError(new ApiError(503, code, "error"))).toBe("unknown");
  });
});
