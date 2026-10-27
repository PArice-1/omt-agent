// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { backendUrl, proxyRequest, type Forwarder } from "./proxy";

function request(path: string, method = "GET", headers: Record<string, string> = {}) {
  return new Request("http://127.0.0.1:3000/api/omt/" + path, {
    method, headers: { "Content-Type": "application/json", ...headers },
    ...(["POST", "PUT"].includes(method) ? { body: JSON.stringify({ message: "hello" }) } : {}),
  });
}
function forward(status = 200, body = "[]") {
  return vi.fn<Forwarder>().mockResolvedValue({ status, headers: new Headers({ "content-type": "application/json" }), text: async () => body });
}
afterEach(() => vi.unstubAllEnvs());

describe("local allowlisted proxy", () => {
  it("forwards one request to the fixed upstream, not browser cookies", async () => {
    vi.stubEnv("OMT_BACKEND_URL", "http://127.0.0.1:8000");
    const upstream = forward();
    const response = await proxyRequest(request("api/v1/sessions", "GET", { Cookie: "secret=value" }), ["api", "v1", "sessions"], upstream);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(upstream).toHaveBeenCalledTimes(1);
    expect(String(upstream.mock.calls[0][0])).toBe("http://127.0.0.1:8000/api/v1/sessions");
    expect(upstream.mock.calls[0][1].headers.Authorization).toBeUndefined();
    expect(upstream.mock.calls[0][1].headers.Cookie).toBeUndefined();
  });
  it("forwards POST body unchanged", async () => {
    const upstream = forward();
    await proxyRequest(request("api/v1/sessions/s/runs", "POST"), ["api", "v1", "sessions", "s", "runs"], upstream);
    expect(upstream.mock.calls[0][1]).toMatchObject({ method: "POST", body: '{"message":"hello"}' });
  });
  it.each([
    { method: "GET", path: ["health"] },
    { method: "GET", path: ["api", "v1", "runtime"] },
    { method: "GET", path: ["api", "v1", "providers"] },
    { method: "GET", path: ["api", "v1", "models"] },
    { method: "POST", path: ["api", "v1", "model-logins"] },
    { method: "POST", path: ["api", "v1", "model-logins", "p", "confirm"] },
    { method: "PUT", path: ["api", "v1", "runtime", "model"] },
    { method: "PUT", path: ["api", "v1", "runtime", "thinking"] },
    { method: "GET", path: ["api", "v1", "sessions"] },
    { method: "POST", path: ["api", "v1", "sessions"] },
    { method: "GET", path: ["api", "v1", "sessions", "s", "messages"] },
    { method: "POST", path: ["api", "v1", "sessions", "s", "runs"] },
  ])("accepts $method $path without authentication and strips incoming credentials", async ({ method, path }) => {
    const upstream = forward();
    const unauthenticated = await proxyRequest(request(path.join("/"), method), path, upstream);
    expect(unauthenticated.status).toBe(200);
    const credentialed = await proxyRequest(request(path.join("/"), method, {
      Authorization: "Bearer ignored-test-value", Cookie: "ignored=value",
    }), path, upstream);
    expect(credentialed.status).toBe(200);
    expect(upstream).toHaveBeenCalledTimes(2);
    for (const [, options] of upstream.mock.calls) {
      const headers = new Headers(options.headers);
      expect(headers.has("Authorization")).toBe(false);
      expect(headers.has("Cookie")).toBe(false);
    }
  });
  it.each(["https://example.com", "file:///etc/passwd", "http://127.0.0.1:8000/path", "http://user:pass@localhost", "http://localhost/?x=1"])("rejects unsafe backend configuration %s", (url) => {
    expect(() => backendUrl(url)).toThrow();
  });
  it.each([
    ["api", "v1", "secrets"],
    ["api", "v1", "sessions", "..", "runs"],
    ["api", "v1", "sessions", "s", "delete"],
    ["http:", "evil.test"],
  ])("rejects paths outside the contract: %j", async (...path) => {
    const upstream = forward();
    expect((await proxyRequest(request("bad"), path, upstream)).status).toBe(404);
    expect(upstream).not.toHaveBeenCalled();
  });
  it("enforces the method per endpoint", async () => {
    const upstream = forward();
    const response = await proxyRequest(request("api/v1/sessions/s/messages", "POST"), ["api", "v1", "sessions", "s", "messages"], upstream);
    expect(response.status).toBe(405);
    expect(upstream).not.toHaveBeenCalled();
  });
  it("accepts a same-origin browser Host when Next normalizes its internal URL", async () => {
    const upstream = forward();
    const incoming = new Request("http://localhost:3000/api/omt/api/v1/sessions", {
      method: "POST", body: "{}", headers: { Host: "127.0.0.1:3000", Origin: "http://127.0.0.1:3000",
        "Content-Type": "application/json" },
    });
    expect((await proxyRequest(incoming, ["api", "v1", "sessions"], upstream)).status).toBe(200);
    expect(upstream).toHaveBeenCalledTimes(1);
  });
  it("rejects non-loopback Host headers to guard local DNS rebinding", async () => {
    const upstream = forward();
    const incoming = request("api/v1/sessions", "POST", { Host: "foreign.test:3000", Origin: "http://foreign.test:3000" });
    expect((await proxyRequest(incoming, ["api", "v1", "sessions"], upstream)).status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });
  it("rejects foreign origins before forwarding any operation", async () => {
    const upstream = forward();
    const response = await proxyRequest(request("api/v1/sessions", "POST", { Origin: "https://evil.test" }), ["api", "v1", "sessions"], upstream);
    expect(response.status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });
  it("rejects query parameters instead of silently inventing pagination", async () => {
    const upstream = forward();
    const response = await proxyRequest(request("api/v1/sessions?page=2"), ["api", "v1", "sessions"], upstream);
    expect(response.status).toBe(400);
    expect(upstream).not.toHaveBeenCalled();
  });
  it("does not follow redirects or expose their headers", async () => {
    const upstream = forward(302);
    expect((await proxyRequest(request("health"), ["health"], upstream)).status).toBe(502);
    expect(upstream).toHaveBeenCalledTimes(1);
  });
  it("never retries upstream network failures and marks uncertainty", async () => {
    const upstream = vi.fn<Forwarder>().mockRejectedValue(new TypeError("network"));
    const response = await proxyRequest(request("api/v1/sessions/s/runs", "POST"), ["api", "v1", "sessions", "s", "runs"], upstream);
    expect(await response.json()).toMatchObject({ error: { code: "proxy_unavailable" } });
    expect(upstream).toHaveBeenCalledTimes(1);
  });
  it.each([
    { method: "GET", path: ["api", "v1", "sessions"], feedback: "本次读取失败" },
    { method: "POST", path: ["api", "v1", "sessions"], feedback: "会话可能已创建" },
    { method: "POST", path: ["api", "v1", "sessions", "s", "runs"], feedback: "执行结果可能不明" },
  ])("explains the failed operation for $method $path without conflating reads with runs", async ({ method, path, feedback }) => {
    const upstream = vi.fn<Forwarder>().mockRejectedValue(new TypeError("network"));
    const response = await proxyRequest(request(path.join("/"), method), path, upstream);
    const body: unknown = await response.json();
    expect(body).toMatchObject({ error: { code: "proxy_unavailable", message: expect.stringContaining(feedback) } });
    if (method === "GET") expect(JSON.stringify(body)).not.toContain("执行结果可能不明");
    expect(upstream).toHaveBeenCalledTimes(1);
  });
  it("forwards stream chunks without waiting for the whole body, and propagates cancellation", async () => {
    let writer: ReadableStreamDefaultController<Uint8Array> | undefined;
    const cancelled = vi.fn();
    const stream = new ReadableStream<Uint8Array>({ start(controller) { writer = controller; }, cancel: cancelled });
    const text = vi.fn();
    const upstream = vi.fn<Forwarder>().mockResolvedValue({ status: 200, headers: new Headers({ "Content-Type": "text/event-stream" }), body: stream, text });
    const incoming = request("api/v1/sessions/s/runs/stream", "POST");
    const response = await proxyRequest(incoming, ["api", "v1", "sessions", "s", "runs", "stream"], upstream);
    expect(text).not.toHaveBeenCalled();
    expect(response.headers.get("X-Accel-Buffering")).toBe("no");
    expect(upstream.mock.calls[0][1].signal).toBe(incoming.signal);
    expect(upstream.mock.calls[0][1].headers.Accept).toBe("text/event-stream");
    const reader = response.body?.getReader();
    writer?.enqueue(new TextEncoder().encode(": heartbeat\n\n"));
    expect(new TextDecoder().decode((await reader?.read())?.value)).toBe(": heartbeat\n\n");
    await reader?.cancel();
    expect(cancelled).toHaveBeenCalledTimes(1);
  });
  it("leaves pre-admission streaming errors as HTTP JSON", async () => {
    const upstream = forward(409, '{"error":{"code":"session_incomplete","message":"需检查"}}');
    const response = await proxyRequest(request("api/v1/sessions/s/runs/stream", "POST"), ["api", "v1", "sessions", "s", "runs", "stream"], upstream);
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ error: { code: "session_incomplete" } });
    expect(upstream).toHaveBeenCalledTimes(1);
  });
  it("preserves business error status and body", async () => {
    const upstream = forward(409, '{"error":{"code":"session_busy","message":"busy"}}');
    const response = await proxyRequest(request("api/v1/sessions/s/messages"), ["api", "v1", "sessions", "s", "messages"], upstream);
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ error: { code: "session_busy", message: "busy" } });
  });
});
