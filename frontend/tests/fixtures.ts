import type { MessageResponse, RunResponse, SessionResponse, RuntimeResponse, RunEvent, TerminalEvent } from "@/lib/omt-api/contracts";
export const sessionA: SessionResponse = { session_id: "session-a", title: "项目分析", created_at: "2026-06-01 08:00:00", updated_at: "2026-06-01 08:00:00" };
export const sessionB: SessionResponse = { ...sessionA, session_id: "session-b", title: "另一个会话" };
export const completedRun: RunResponse = { session_id: sessionA.session_id, run_id: "run-1", status: "completed", answer: "分析完成", warnings: [] };
export const history: MessageResponse[] = [
  { role: "user", text: "分析项目", tool_calls: [] },
  { role: "assistant", text: "", tool_calls: [{ id: "call-1", name: "read", args: { file: "README.md" } }] },
  { role: "tool", text: "# 项目说明", name: "read", tool_call_id: "call-1", status: "success", tool_calls: [] },
  { role: "assistant", text: "分析完成", tool_calls: [] },
];
export const runtime: RuntimeResponse = {
  configured: true, ready: true, mutable: true, changing: false, busy: false, running: 0,
  thinking: { provider: "deepseek", model: "deepseek-flash", level: "none", reasoning_effort: "none", available_levels: ["none", "high", "low", "max"] },
  message: "运行环境已就绪",
};
export const terminal: TerminalEvent = { seq: 4, type: "run.completed", session_id: sessionA.session_id, run_id: "run-1", data: { status: "completed", answer: "分析完成", warnings: [] } };
export function runEvents(result: RunResponse = completedRun): RunEvent[] {
  const common = { session_id: result.session_id, run_id: result.run_id } as const;
  return [
    { ...common, seq: 1, type: "run.started", data: { thinking: runtime.thinking } },
    { ...common, seq: 2, type: "assistant.started", message_id: "m1", role: "assistant", data: {} },
    { ...common, seq: 3, type: "assistant.text.delta", message_id: "m1", role: "assistant", data: { delta: result.answer } },
    { ...common, seq: 4, type: "run.completed", data: { status: "completed", answer: result.answer, warnings: result.warnings } },
  ];
}
export function frame(event: unknown, name?: string) {
  const type = typeof event === "object" && event !== null && "type" in event ? String(event.type) : "invalid";
  return `event: ${name ?? type}\ndata: ${JSON.stringify(event)}\n\n`;
}
export function sseBody(result: RunResponse = completedRun) { return runEvents(result).map((event) => frame(event)).join(""); }
export function sseResponse(result: RunResponse = completedRun) {
  return new Response(sseBody(result), { headers: { "Content-Type": "text/event-stream" } });
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
