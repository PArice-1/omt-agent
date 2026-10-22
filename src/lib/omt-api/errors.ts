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

export function classifyRunError(error: unknown): "rejected" | "needs_attention" | "unknown" {
  if (!(error instanceof ApiError)) return "unknown";
  if (["run_failed", "session_incomplete"].includes(error.code)) return "needs_attention";
  if (["unauthorized", "invalid_request", "session_not_found", "session_busy", "capacity_exceeded"].includes(error.code))
    return "rejected";
  return "unknown";
}
