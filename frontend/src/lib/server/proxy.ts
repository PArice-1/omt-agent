import { Agent, fetch as upstreamFetch } from "undici";

const dispatcher = new Agent({ headersTimeout: 0, bodyTimeout: 0 });
type ForwardOptions = { method: string; headers: Record<string, string>; body?: string; signal?: AbortSignal };
type StreamBody = { getReader(): { read(): Promise<{ done: boolean; value?: Uint8Array }>; cancel(reason?: unknown): Promise<void>; releaseLock(): void } };
type UpstreamResponse = { status: number; headers: { get(name: string): string | null }; body?: StreamBody | null; text(): Promise<string> };
export type Forwarder = (url: URL, options: ForwardOptions) => Promise<UpstreamResponse>;

function jsonError(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status, headers: { "Cache-Control": "no-store" } });
}

export function backendUrl(raw = process.env.OMT_BACKEND_URL ?? "http://127.0.0.1:8000"): URL {
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)
    || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
    || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("OMT_BACKEND_URL must be a loopback HTTP(S) origin");
  }
  return url;
}

const forward: Forwarder = (url, options) => upstreamFetch(url, {
  ...options, dispatcher, redirect: "manual",
});

/** 将 /api/omt 下的白名单业务路径转发到后端同一路径；health 单独映射到 /health。
 * path 是 Next.js 解码后的相对路径段；仅允许固定本机上游，不转发浏览器凭据。
 */
export async function proxyRequest(
  request: Request,
  path: string[],
  forwarder: Forwarder = forward,
): Promise<Response> {
  const isHealth = path.length === 1 && path[0] === "health";
  const isSessions = path.length === 1 && path[0] === "sessions";
  const validId = (id: string | undefined) => Boolean(id) && id !== "." && id !== "..";
  const sessionPrefix = path[0] === "sessions" && validId(path[1]);
  const isSessionAction = path.length === 3 && sessionPrefix && ["messages", "runs"].includes(path[2]);
  const isStream = path.length === 4 && sessionPrefix && path[2] === "runs" && path[3] === "stream";
  const isRuntime = path.length === 1 && path[0] === "runtime";
  const isDirectory = path.length === 1 && ["providers", "models"].includes(path[0]);
  const isSwitch = path.length === 2 && path[0] === "runtime" && ["model", "thinking"].includes(path[1]);
  const isPreview = path.length === 1 && path[0] === "model-logins";
  const isConfirm = path.length === 3 && path[0] === "model-logins" && validId(path[1]) && path[2] === "confirm";
  if (!isHealth && !isSessions && !isSessionAction && !isStream && !isRuntime && !isDirectory && !isSwitch && !isPreview && !isConfirm)
    return jsonError(404, "http_error", "代理不支持此路径。");

  const allowed = isHealth || isRuntime || isDirectory ? ["GET"] : isSessions ? ["GET", "POST"] : isSwitch ? ["PUT"] : isSessionAction && path[2] === "messages" ? ["GET"] : ["POST"];
  if (!allowed.includes(request.method)) return jsonError(405, "http_error", "代理不支持此方法。");
  const requestUrl = new URL(request.url);
  if (requestUrl.search) return jsonError(400, "http_error", "此接口不支持查询参数。");
  // Next.js may normalize request.url to its internal localhost origin. The
  // incoming Host retains the browser's origin (e.g. 127.0.0.1:3000).
  let browserOrigin: URL;
  try {
    browserOrigin = new URL(`${requestUrl.protocol}//${request.headers.get("host") ?? requestUrl.host}`);
  } catch {
    return jsonError(403, "http_error", "无法识别本机请求来源。");
  }
  const origin = request.headers.get("origin");
  if (!["127.0.0.1", "localhost", "[::1]"].includes(browserOrigin.hostname)
    || request.headers.get("sec-fetch-site") === "cross-site"
    || (origin && origin !== browserOrigin.origin))
    return jsonError(403, "http_error", "拒绝跨来源代理请求。");

  const headers: Record<string, string> = { Accept: isStream ? "text/event-stream" : "application/json", "Cache-Control": "no-store" };
  let body: string | undefined;
  if (request.method === "POST" || request.method === "PUT") {
    if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json"))
      return jsonError(422, "invalid_request", "请求必须为 JSON。");
    body = await request.text();
    if (new TextEncoder().encode(body).byteLength > 1024 * 1024)
      return jsonError(413, "invalid_request", "请求体过大。");
    headers["Content-Type"] = "application/json";
  }

  const execution = request.method === "POST" && path[2] === "runs";
  const creating = request.method === "POST" && isSessions;
  const uncertainSuffix = execution ? "执行结果可能不明，请勿重复发送。" : creating ? "会话可能已创建，请先刷新列表确认。" : request.method !== "GET" ? "设置结果未确认，请读取运行状态检查，不要自动重复提交。" : "本次读取失败，可稍后手动刷新。";
  try {
    const target = backendUrl();
    target.pathname = (isHealth ? "/" : "/api/omt/") + path.map(encodeURIComponent).join("/");
    const response = await forwarder(target, { method: request.method, headers, ...(body === undefined ? {} : { body }),
      ...(isStream ? { signal: request.signal } : {}) });
    if (response.status >= 300 && response.status < 400)
      return jsonError(502, "proxy_invalid_response", `后端返回了重定向，代理已拒绝跟随。${uncertainSuffix}`);
    const responseHeaders = new Headers({ "Cache-Control": "no-store", "Content-Type": response.headers.get("content-type") ?? "application/json" });
    if (isStream && response.status === 200) {
      if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("text/event-stream"))
        return jsonError(502, "proxy_invalid_response", "后端没有返回可读取的事件流。执行结果可能不明，请勿重复发送。");
      responseHeaders.set("X-Accel-Buffering", "no");
      // Pass the body through with backpressure. Cancelling the downstream body
      // cancels the upstream reader; never buffer or retry a running stream.
      const reader = response.body.getReader();
      const stream = new ReadableStream<Uint8Array>({
        async pull(controller) {
          try {
            const { done, value } = await reader.read();
            if (done) { controller.close(); reader.releaseLock(); }
            else if (value) controller.enqueue(value);
          } catch (error) { controller.error(error); reader.releaseLock(); }
        },
        async cancel(reason) { try { await reader.cancel(reason); } finally { reader.releaseLock(); } },
      });
      return new Response(stream, { status: response.status, headers: responseHeaders });
    }
    return new Response(await response.text(), { status: response.status, headers: responseHeaders });
  } catch {
    return jsonError(502, "proxy_unavailable", `未取得完整后端响应。${uncertainSuffix}`);
  }
}
