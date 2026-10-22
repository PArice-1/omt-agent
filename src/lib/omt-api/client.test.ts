import { describe, expect, it, vi } from "vitest";
import { createOmtClient } from "./client";
import { ApiError, classifyRunError } from "./errors";
import { completedRun, history, sessionA, testToken } from "../../../tests/fixtures";

function setup(body: unknown, status = 200) {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => Response.json(body, { status }));
  const client = createOmtClient({ baseUrl: "http://localhost/api/omt/", getToken: () => testToken, fetcher });
  return { client, fetcher };
}
describe("OMT client contract", () => {
  it("validates list responses and sends Bearer without a GET body", async () => {
    const { client, fetcher } = setup([sessionA]);
    expect(await client.listSessions()).toEqual([sessionA]);
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe("http://localhost/api/omt/api/v1/sessions");
    expect(options?.headers).toBeInstanceOf(Headers);
    const headers = new Headers(options?.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${testToken}`);
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
  it("health does not expose the token", async () => {
    const { client, fetcher } = setup({ status: "ok" });
    await client.health();
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).has("Authorization")).toBe(false);
  });
  it("gets the current token on each request", async () => {
    let token = "first";
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => Response.json([]));
    const client = createOmtClient({ getToken: () => token, fetcher });
    await client.listSessions();
    token = "second";
    await client.listSessions();
    expect(new Headers(fetcher.mock.calls[1][1]?.headers).get("Authorization")).toBe("Bearer second");
  });
  it("keeps HTTP status, error code and run ID", async () => {
    const { client, fetcher } = setup({ error: { code: "run_failed", message: "执行失败", run_id: "r1" } }, 502);
    await expect(client.run("s", "hi")).rejects.toMatchObject({ status: 502, code: "run_failed", runId: "r1" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("never retries a failed network POST", async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("network"));
    const client = createOmtClient({ getToken: () => testToken, fetcher });
    await expect(client.run("s", "hi")).rejects.toThrow("network");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("handles non-JSON infrastructure responses", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    await expect(createOmtClient({ getToken: () => testToken, fetcher }).run("s", "hi"))
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
