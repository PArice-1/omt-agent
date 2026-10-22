import { Agent, fetch as upstreamFetch } from "undici";

const dispatcher = new Agent({ headersTimeout: 0, bodyTimeout: 0 });
type ForwardOptions = { method: string; headers: Record<string, string>; body?: string };
type UpstreamResponse = { status: number; headers: { get(name: string): string | null }; text(): Promise<string> };
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

/** Allowlisted reverse proxy; never forward cookies or a user-controlled upstream. */
export async function proxyRequest(
  request: Request,
  path: string[],
  forwarder: Forwarder = forward,
): Promise<Response> {
  const isHealth = path.length === 1 && path[0] === "health";
  const isSessions = path.length === 3 && path.join("/") === "api/v1/sessions";
  const isSessionAction = path.length === 5 && path.slice(0, 3).join("/") === "api/v1/sessions"
    && Boolean(path[3]) && ![".", ".."].includes(path[3])
    && ["messages", "runs"].includes(path[4]);
  if (!isHealth && !isSessions && !isSessionAction)
    return jsonError(404, "http_error", "代理不支持此路径。");

  const allowed = isHealth ? ["GET"] : isSessions ? ["GET", "POST"] : path[4] === "messages" ? ["GET"] : ["POST"];
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

  const headers: Record<string, string> = { Accept: "application/json", "Cache-Control": "no-store" };
  if (!isHealth) {
    const authorization = request.headers.get("authorization");
    if (!authorization?.startsWith("Bearer ")) return jsonError(401, "unauthorized", "请提供访问令牌。");
    headers.Authorization = authorization;
  }
  let body: string | undefined;
  if (request.method === "POST") {
    if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json"))
      return jsonError(422, "invalid_request", "请求必须为 JSON。");
    body = await request.text();
    if (new TextEncoder().encode(body).byteLength > 1024 * 1024)
      return jsonError(413, "invalid_request", "请求体过大。");
    headers["Content-Type"] = "application/json";
  }

  try {
    const target = backendUrl();
    target.pathname = "/" + path.map(encodeURIComponent).join("/");
    const response = await forwarder(target, { method: request.method, headers, ...(body === undefined ? {} : { body }) });
    if (response.status >= 300 && response.status < 400)
      return jsonError(502, "proxy_invalid_response", "后端返回了重定向，代理已拒绝跟随；执行结果可能不明。");
    const responseHeaders = new Headers({ "Cache-Control": "no-store", "Content-Type": response.headers.get("content-type") ?? "application/json" });
    const challenge = response.headers.get("www-authenticate");
    if (challenge) responseHeaders.set("WWW-Authenticate", challenge);
    return new Response(await response.text(), { status: response.status, headers: responseHeaders });
  } catch {
    return jsonError(502, "proxy_unavailable", "无法取得后端响应；若已发送执行请求，结果可能不明，请勿自动重试。");
  }
}
