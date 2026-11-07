import { ApiError, RunAdmissionError } from "./errors";
import { errorSchema } from "./schemas";
import { eventEnvelopeSchema, isTerminal, knownEventTypes, runEventSchema, type RunEvent, type TerminalEvent } from "./events";
import type { TransportOptions } from "./transport";

const invalid = () => new ApiError(200, "invalid_response", "流式事件格式、关联或顺序异常，运行结果未确认。");
// Bound browser memory independently of the server's queue. Exceeding this limit
// stops reception; it must never silently truncate a successful answer.
const MAX_FRAME = 2 * 1024 * 1024;
const MAX_STREAM = 16 * 1024 * 1024;
const admissionCodes = new Set([
  "session_not_found", "session_busy", "session_incomplete", "manager_busy", "configuration_invalid",
  "invalid_request", "capacity_exceeded", "storage_unavailable", "manager_closed", "runtime_not_ready", "internal_error",
]);

export async function readRunStream(response: Response, sessionId: string, onEvent: (event: RunEvent) => void): Promise<TerminalEvent> {
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const parsed = errorSchema.safeParse(body);
    if (parsed.success) {
      const error = parsed.data.error;
      // Proxy failures may hide an already-admitted run. Only documented
      // backend admission errors prove this POST did not start a new model run.
      const ErrorType = admissionCodes.has(error.code) ? RunAdmissionError : ApiError;
      throw new ErrorType(response.status, error.code, error.message, error.run_id);
    }
    throw new ApiError(response.status, "unexpected_response", "服务或代理返回了异常响应。");
  }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("text/event-stream") || !response.body) throw invalid();
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const encoder = new TextEncoder();
  let buffer = "";
  let bytes = 0;
  let previousSeq = 0;
  let runId: string | undefined;
  let started = false;
  let terminal: TerminalEvent | undefined;
  try {
    while (true) {
      const { value, done } = await reader.read();
      bytes += value?.byteLength ?? 0;
      if (bytes > MAX_STREAM) throw new ApiError(200, "invalid_response", "本轮内容超过浏览器接收上限，结果未确认；请检查历史，不要重发。");
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      // Normalize CRLF only once both characters are available across reads.
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        if (boundary > MAX_FRAME) throw invalid();
        const frame = buffer.slice(0, boundary);
        if (encoder.encode(frame).byteLength > MAX_FRAME) throw invalid();
        buffer = buffer.slice(boundary + 2);
        let name: string | undefined;
        const data: string[] = [];
        for (const line of frame.split("\n")) {
          if (!line || line.startsWith(":")) continue;
          const colon = line.indexOf(":");
          const field = colon < 0 ? line : line.slice(0, colon);
          const raw = colon < 0 ? "" : line.slice(colon + 1);
          const value = raw.startsWith(" ") ? raw.slice(1) : raw;
          if (field === "event") name = value;
          if (field === "data") data.push(value);
        }
        if (!data.length) continue;
        const decoded: unknown = JSON.parse(data.join("\n"));
        const parsed = eventEnvelopeSchema.safeParse(decoded);
        if (!parsed.success) throw invalid();
        const envelope = parsed.data;
        if (name !== envelope.type || envelope.session_id !== sessionId || terminal
          || envelope.seq <= previousSeq || (runId !== undefined && envelope.run_id !== runId)) throw invalid();
        runId = envelope.run_id;
        previousSeq = envelope.seq;
        if (!knownEventTypes.has(envelope.type)) continue;
        const result = runEventSchema.safeParse(envelope);
        if (!result.success) throw invalid();
        const event = result.data;
        if (event.type === "run.started") {
          if (started) throw invalid();
          started = true;
        } else if (!started) throw invalid();
        onEvent(event);
        if (isTerminal(event)) terminal = event;
      }
      if (buffer.length > MAX_FRAME || encoder.encode(buffer).byteLength > MAX_FRAME) throw invalid();
      if (done) break;
    }
    if (buffer.trim() || !terminal) throw new ApiError(200, "invalid_response", "连接结束但没有完整运行终态，结果未确认；请勿重复发送。");
    return terminal;
  } catch (error) {
    if (error instanceof ApiError || (error instanceof Error && error.name === "AbortError")) throw error;
    throw invalid();
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export function createStreamRun({ baseUrl = "/api/omt", fetcher = fetch }: TransportOptions) {
  return async (sessionId: string, message: string, onEvent: (event: RunEvent) => void, signal: AbortSignal) => {
    const response = await fetcher(`${baseUrl.replace(/\/+$/, "")}/api/v1/sessions/${encodeURIComponent(sessionId)}/runs/stream`, {
      method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message }), signal, cache: "no-store",
    });
    return readRunStream(response, sessionId, onEvent);
  };
}
