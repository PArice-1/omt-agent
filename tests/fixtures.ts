import type { MessageResponse, RunResponse, SessionResponse } from "@/lib/omt-api/contracts";
export const testToken = "local-test-token-not-a-real-secret-0000";
export const sessionA: SessionResponse = { session_id: "session-a", title: "项目分析", created_at: "2026-06-01 08:00:00", updated_at: "2026-06-01 08:00:00" };
export const sessionB: SessionResponse = { ...sessionA, session_id: "session-b", title: "另一个会话" };
export const completedRun: RunResponse = { session_id: sessionA.session_id, run_id: "run-1", status: "completed", answer: "分析完成", warnings: [] };
export const history: MessageResponse[] = [
  { role: "user", text: "分析项目", tool_calls: [] },
  { role: "assistant", text: "", tool_calls: [{ id: "call-1", name: "read", args: { file: "README.md" } }] },
  { role: "tool", text: "# 项目说明", name: "read", tool_call_id: "call-1", status: "success", tool_calls: [] },
  { role: "assistant", text: "分析完成", tool_calls: [] },
];
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
