// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { createOmtClient } from "./client";
import { classifyRunError } from "./errors";
import { readRunStream } from "./stream";
import { frame, runEvents, sessionA, terminal } from "../../../tests/fixtures";
import type { RunEvent } from "./events";

const sid = sessionA.session_id;
function response(chunks: Uint8Array[]) {
  return new Response(new ReadableStream<Uint8Array>({ start(controller) {
    chunks.forEach((chunk) => controller.enqueue(chunk)); controller.close();
  } }), { headers: { "Content-Type": "text/event-stream; charset=utf-8" } });
}
const encode = (text: string) => new TextEncoder().encode(text);
const events = runEvents();
const wire = events.map((event) => frame(event)).join("");

describe("incremental OMT v1 SSE", () => {
  it("handles every byte as a chunk, including half UTF-8 characters and frames", async () => {
    const received: RunEvent[] = [];
    const bytes = encode(wire);
    const result = await readRunStream(response(Array.from(bytes, (byte) => new Uint8Array([byte]))), sid, (event) => received.push(event));
    expect(received).toEqual(events);
    expect(result).toEqual(terminal);
  });
  it("handles several frames in one read, CRLF, comment heartbeats, unknown types and non-contiguous seq", async () => {
    const unknown = { ...terminal, type: "future.event", seq: 3, data: { any: "value" } };
    const data = frame(events[0]) + ": heartbeat\n\n" + frame(unknown) + frame({ ...terminal, seq: 9 });
    const received = vi.fn();
    await readRunStream(response([encode(data.replaceAll("\n", "\r\n"))]), sid, received);
    expect(received).toHaveBeenCalledTimes(2);
    expect(received.mock.calls[1][0]).toMatchObject({ seq: 9, type: "run.completed" });
  });
  it("delivers a delta before EOF or the final event is available", async () => {
    let writer: ReadableStreamDefaultController<Uint8Array> | undefined;
    const body = new ReadableStream<Uint8Array>({ start(controller) { writer = controller; } });
    const received = vi.fn();
    const reading = readRunStream(new Response(body, { headers: { "Content-Type": "text/event-stream" } }), sid, received);
    writer?.enqueue(encode(events.slice(0, 3).map((event) => frame(event)).join("")));
    await vi.waitFor(() => expect(received).toHaveBeenCalledTimes(3));
    expect(received.mock.calls[2][0].type).toBe("assistant.text.delta");
    writer?.enqueue(encode(frame(terminal))); writer?.close();
    await expect(reading).resolves.toEqual(terminal);
  });
  it.each([
    { version: 2 }, { seq: 1 }, { session_id: "other" }, { run_id: "other" },
    { type: "assistant.text.delta", message_id: "m", role: "assistant", data: { delta: { invalid: true } } },
  ])("rejects invalid version, sequence, IDs and known event data: %j", async (change) => {
    const text = frame(events[0]) + frame({ ...terminal, ...change });
    await expect(readRunStream(response([encode(text)]), sid, () => undefined)).rejects.toMatchObject({ code: "invalid_response" });
  });
  it.each([
    ": heartbeat\n\n", frame(events[0]), wire.slice(0, -1),
    frame(terminal), frame(events[0], "wrong"), frame(events[0]) + "data: [DONE]\n\n",
  ])("does not confuse EOF, partial frames, wrong names, [DONE] or missing start with success", async (text) => {
    await expect(readRunStream(response([encode(text)]), sid, () => undefined)).rejects.toMatchObject({ code: "invalid_response" });
  });
  it("stops rather than silently truncating oversized frames or transmissions", async () => {
    const oversizedFrame = frame({ ...terminal, data: { ...terminal.data, answer: "x".repeat(2 * 1024 * 1024) } });
    await expect(readRunStream(response([encode(frame(events[0]) + oversizedFrame)]), sid, () => undefined)).rejects.toMatchObject({ code: "invalid_response" });
    const oversizedUtf8 = frame({ ...terminal, data: { ...terminal.data, answer: "思".repeat(800000) } });
    await expect(readRunStream(response([encode(frame(events[0]) + oversizedUtf8)]), sid, () => undefined)).rejects.toMatchObject({ code: "invalid_response" });
    await expect(readRunStream(response([new Uint8Array(16 * 1024 * 1024 + 1)]), sid, () => undefined)).rejects.toThrow("接收上限");
  });
  it("rejects invalid UTF-8 and post-terminal events", async () => {
    await expect(readRunStream(response([new Uint8Array([0xff])]), sid, () => undefined)).rejects.toMatchObject({ code: "invalid_response" });
    await expect(readRunStream(response([encode(wire + frame({ ...terminal, seq: 5 }))]), sid, () => undefined)).rejects.toMatchObject({ code: "invalid_response" });
  });
  it.each(["run.failed", "run.cancelled"] as const)("returns %s as a terminal, not an HTTP failure", async (type) => {
    const end: RunEvent = { ...terminal, type, data: { code: "run_cancelled", message: "结束" } };
    await expect(readRunStream(response([encode(frame(events[0]) + frame(end))]), sid, () => undefined)).resolves.toEqual(end);
  });
  it("parses pre-admission HTTP JSON errors and never retries", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ error: { code: "session_incomplete", message: "需检查", run_id: "r" } }, { status: 409 }));
    const client = createOmtClient({ fetcher });
    const aborter = new AbortController();
    await expect(client.streamRun("a/b", "  本轮\n", () => undefined, aborter.signal)).rejects.toMatchObject({ status: 409, code: "session_incomplete", runId: "r" });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe("/api/omt/api/v1/sessions/a%2Fb/runs/stream");
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ message: "  本轮\n" }), signal: aborter.signal });
    const headers = new Headers(fetcher.mock.calls[0][1]?.headers);
    expect(headers.get("Accept")).toBe("text/event-stream");
    expect(headers.has("Authorization")).toBe(false);
  });
  it.each([
    { code: "storage_unavailable", phase: "rejected" },
    { code: "internal_error", phase: "rejected" },
    { code: "session_incomplete", phase: "needs_attention" },
    { code: "proxy_unavailable", phase: "unknown" },
    { code: "future_error", phase: "unknown" },
  ])("distinguishes backend admission error $code from an uncertain proxy/transport failure", async ({ code, phase }) => {
    const rejected = Response.json({ error: { code, message: "safe error" } }, { status: 503 });
    const error: unknown = await readRunStream(rejected, sid, () => undefined).catch((error: unknown) => error);
    expect(classifyRunError(error)).toBe(phase);
  });
  it("passes a per-request abort signal to fetch", async () => {
    const aborter = new AbortController();
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, options) => new Promise<Response>((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    }));
    const promise = createOmtClient({ fetcher }).streamRun(sid, "once", () => undefined, aborter.signal);
    const assertion = expect(promise).rejects.toMatchObject({ name: "AbortError" });
    aborter.abort(); await assertion;
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
