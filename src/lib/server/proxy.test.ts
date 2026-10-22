// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { backendUrl, proxyRequest, type Forwarder } from "./proxy";

const token = "local-placeholder-token";
function request(path: string, method = "GET", headers: Record<string, string> = {}) {
  return new Request("http://127.0.0.1:3000/api/omt/" + path, {
    method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...headers },
    ...(method === "POST" ? { body: JSON.stringify({ message: "hello" }) } : {}),
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
    expect(upstream.mock.calls[0][1].headers.Authorization).toBe(`Bearer ${token}`);
    expect(upstream.mock.calls[0][1].headers.Cookie).toBeUndefined();
  });
  it("forwards POST body unchanged", async () => {
    const upstream = forward();
    await proxyRequest(request("api/v1/sessions/s/runs", "POST"), ["api", "v1", "sessions", "s", "runs"], upstream);
    expect(upstream.mock.calls[0][1]).toMatchObject({ method: "POST", body: '{"message":"hello"}' });
  });
  it("does not forward Bearer to health", async () => {
    const upstream = forward(200, '{"status":"ok"}');
    await proxyRequest(request("health"), ["health"], upstream);
    expect(upstream.mock.calls[0][1].headers.Authorization).toBeUndefined();
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
        Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
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
  it("preserves business errors and WWW-Authenticate", async () => {
    const upstream = vi.fn<Forwarder>().mockResolvedValue({ status: 401,
      headers: new Headers({ "www-authenticate": "Bearer" }), text: async () => '{"error":{"code":"unauthorized","message":"no"}}' });
    const response = await proxyRequest(request("api/v1/sessions"), ["api", "v1", "sessions"], upstream);
    expect(response.status).toBe(401);
    expect(response.headers.get("www-authenticate")).toBe("Bearer");
    expect(await response.json()).toMatchObject({ error: { code: "unauthorized" } });
  });
});
