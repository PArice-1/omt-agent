export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly runId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "连接中断或服务不可达，请检查本机后端与代理。";
}

export function isConnectionFailure(error: unknown): boolean {
  return !(error instanceof ApiError) || ["proxy_unavailable", "proxy_invalid_response", "invalid_response", "unexpected_response"].includes(error.code);
}

/** Read failures do not imply that an already-confirmed run is uncertain. */
export function readErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "invalid_response")
    return "本次读取返回的数据格式异常，请检查后端或代理。";
  if (isConnectionFailure(error))
    return "本次读取未取得有效后端响应，请检查本机后端或代理连接。";
  return errorMessage(error);
}

export function classifyRunError(error: unknown): "rejected" | "needs_attention" | "unknown" {
  if (!(error instanceof ApiError)) return "unknown";
  if (["run_failed", "session_incomplete"].includes(error.code)) return "needs_attention";
  if (["invalid_request", "session_not_found", "session_busy", "capacity_exceeded"].includes(error.code))
    return "rejected";
  return "unknown";
}
