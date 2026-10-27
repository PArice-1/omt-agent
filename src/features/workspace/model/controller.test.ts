import { describe, expect, it, vi } from "vitest";
import type { MessageResponse, OmtClient, TerminalEvent } from "@/lib/omt-api/contracts";
import { ApiError } from "@/lib/omt-api/errors";
import { WorkspaceController } from "./controller";
import { runtime, terminal, runEvents, deferred, history, sessionA, sessionB } from "../../../../tests/fixtures";

function setup() {
  const api = {
    getRuntime: vi.fn<OmtClient["getRuntime"]>().mockResolvedValue(runtime),
    listModels: vi.fn<OmtClient["listModels"]>().mockResolvedValue([]),
    listProviders: vi.fn<OmtClient["listProviders"]>().mockResolvedValue([]),
    previewLogin: vi.fn<OmtClient["previewLogin"]>(),
    confirmLogin: vi.fn<OmtClient["confirmLogin"]>(),
    changeModel: vi.fn<OmtClient["changeModel"]>(),
    changeThinking: vi.fn<OmtClient["changeThinking"]>(),
    health: vi.fn<OmtClient["health"]>().mockResolvedValue({ status: "ok" }),
    listSessions: vi.fn<OmtClient["listSessions"]>().mockResolvedValue([sessionA, sessionB]),
    createSession: vi.fn<OmtClient["createSession"]>().mockResolvedValue({ ...sessionA, session_id: "new" }),
    getMessages: vi.fn<OmtClient["getMessages"]>().mockImplementation(async (id) => id === "session-a" ? history : []),
    run: vi.fn<OmtClient["run"]>(),
    streamRun: vi.fn<OmtClient["streamRun"]>().mockResolvedValue(terminal),
  };
  const controller = new WorkspaceController(() => api);
  return { api, controller };
}
async function connected() {
  const result = setup();
  await result.controller.connect();
  await result.controller.loadHistory(sessionA.session_id);
  return result;
}
describe("workspace controller", () => {
  it("connects without credentials and clears cached state on disconnect", async () => {
    const { controller } = await connected();
    expect(controller.getSnapshot().connection).toBe("connected");
    expect(controller.getSnapshot().histories["session-a"].messages).toEqual(history);
    controller.disconnect();
    expect(controller.getSnapshot().sessions).toEqual([]);
    expect(controller.getSnapshot().histories).toEqual({});
  });
  it("connects without a token and prevents overlapping or implicit reconnects", async () => {
    const { api, controller } = setup();
    const pending = deferred<typeof sessionA[]>();
    api.listSessions.mockReturnValueOnce(pending.promise);
    const connecting = controller.connect();
    expect(controller.getSnapshot().connection).toBe("connecting");
    expect(await controller.connect()).toBe(false);
    expect(controller.disconnect()).toBe(false);
    pending.resolve([sessionA]);
    expect(await connecting).toBe(true);
    expect(await controller.connect()).toBe(false);
    expect(api.listSessions).toHaveBeenCalledTimes(1);
  });
  it("separates the workspace connection from the latest request failure and recovers on an explicit read", async () => {
    const { api, controller } = await connected();
    api.listSessions.mockRejectedValueOnce(new ApiError(502, "proxy_unavailable", "legacy execution warning"));
    expect(await controller.refreshSessions()).toBe(false);
    expect(controller.getSnapshot()).toMatchObject({ connection: "connected", backendStatus: "unavailable", noticeSource: "sessions" });
    expect(controller.getSnapshot().notice).not.toContain("legacy execution warning");
    expect(await controller.refreshSessions()).toBe(true);
    expect(controller.getSnapshot().backendStatus).toBe("available");
    expect(controller.getSnapshot().notice).toBeUndefined();
    expect(api.streamRun).not.toHaveBeenCalled();
  });
  it("does not let an older history success hide a newer list request failure", async () => {
    const { api, controller } = await connected();
    const pending = deferred<MessageResponse[]>();
    api.getMessages.mockReturnValueOnce(pending.promise);
    const historyRead = controller.loadHistory("session-a");
    api.listSessions.mockRejectedValueOnce(new TypeError("network"));
    await controller.refreshSessions();
    pending.resolve(history);
    await historyRead;
    expect(controller.getSnapshot().backendStatus).toBe("unavailable");
    await controller.refreshSessions();
    expect(controller.getSnapshot().backendStatus).toBe("available");
  });
  it("does not unlock an uncertain execution when closing a notification", async () => {
    const { api, controller } = await connected();
    api.streamRun.mockRejectedValue(new TypeError("network"));
    await controller.send("session-a", "分析项目");
    controller.dismissNotice();
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
    expect(controller.getSnapshot().backendStatus).toBe("unavailable");
    expect(await controller.send("session-a", "重复")).toBe(false);
    expect(api.streamRun).toHaveBeenCalledTimes(1);
  });
  it("does not call a busy business response a lost connection", async () => {
    const { api, controller } = await connected();
    api.streamRun.mockRejectedValue(new ApiError(429, "capacity_exceeded", "容量已满"));
    await controller.send("session-a", "分析项目");
    expect(controller.getSnapshot().backendStatus).toBe("available");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("rejected");
  });
  it("does not retry a failed connection and allows an explicit retry", async () => {
    const { api, controller } = setup();
    api.listSessions.mockRejectedValueOnce(new TypeError("network"));
    expect(await controller.connect()).toBe(false);
    expect(api.listSessions).toHaveBeenCalledTimes(1);
    expect(controller.getSnapshot()).toMatchObject({ connection: "disconnected", backendStatus: "unavailable" });
    expect(await controller.connect()).toBe(true);
    expect(api.listSessions).toHaveBeenCalledTimes(2);
  });
  it("deduplicates overlapping history reads", async () => {
    const { api, controller } = setup();
    const pending = deferred<MessageResponse[]>();
    api.getMessages.mockReturnValue(pending.promise);
    await controller.connect();
    const first = controller.loadHistory("session-a");
    const second = controller.loadHistory("session-a");
    expect(first).toBe(second);
    expect(api.getMessages).toHaveBeenCalledTimes(1);
    pending.resolve([]);
    await first;
  });
  it("keeps slow history responses in their original session after a switch", async () => {
    const { api, controller } = setup();
    const pending = deferred<MessageResponse[]>();
    api.getMessages.mockImplementation(async (id) => id === "session-a" ? pending.promise : []);
    await controller.connect();
    controller.selectSession("session-b");
    await controller.loadHistory("session-b");
    pending.resolve(history);
    await controller.loadHistory("session-a");
    expect(controller.getSnapshot().selectedId).toBe("session-b");
    expect(controller.getSnapshot().histories["session-b"].messages).toEqual([]);
    expect(controller.getSnapshot().histories["session-a"].messages).toEqual(history);
  });
  it("ignores old requests after disconnect and reconnect", async () => {
    const { api, controller } = setup();
    const pending = deferred<MessageResponse[]>();
    api.getMessages.mockReturnValueOnce(pending.promise).mockResolvedValue([]);
    await controller.connect();
    const old = controller.loadHistory("session-a");
    controller.disconnect();
    await controller.connect();
    await controller.loadHistory("session-a");
    pending.resolve(history);
    await old;
    expect(controller.getSnapshot().histories["session-a"].messages).toEqual([]);
  });
  it("creates exactly one session for overlapping submissions", async () => {
    const { api, controller } = await connected();
    const pending = deferred<typeof sessionA>();
    api.createSession.mockReturnValue(pending.promise);
    const first = controller.createSession();
    expect(await controller.createSession()).toBe(false);
    pending.resolve({ ...sessionA, session_id: "new" });
    expect(await first).toBe(true);
    expect(api.createSession).toHaveBeenCalledTimes(1);
    expect(controller.getSnapshot().selectedId).toBe("new");
    expect(controller.getSnapshot().histories.new.messages).toEqual([]);
  });
  it("does not automatically recreate when the response is lost", async () => {
    const { api, controller } = await connected();
    api.createSession.mockRejectedValue(new TypeError("network"));
    expect(await controller.createSession()).toBe(false);
    expect(api.createSession).toHaveBeenCalledTimes(1);
    expect(controller.getSnapshot().notice).toContain("先刷新列表");
  });
  it("locks all sends synchronously and never reads running history", async () => {
    const { api, controller } = await connected();
    const pending = deferred<TerminalEvent>();
    api.streamRun.mockReturnValue(pending.promise);
    const first = controller.send("session-a", "分析项目");
    expect(await controller.send("session-a", "重复")).toBe(false);
    await controller.loadHistory("session-a");
    expect(api.getMessages).toHaveBeenCalledTimes(1);
    expect(controller.disconnect()).toBe(false);
    expect(api.streamRun).toHaveBeenCalledTimes(1);
    pending.resolve(terminal);
    expect(await first).toBe(true);
    expect(api.getMessages).toHaveBeenCalledTimes(2);
    expect(controller.getSnapshot().histories["session-a"].messages).toEqual(history);
    expect(controller.getSnapshot().runs["session-a"].answer).toBeUndefined();
  });
  it("routes a completed answer back to its original session", async () => {
    const { api, controller } = await connected();
    const pending = deferred<TerminalEvent>();
    api.streamRun.mockReturnValue(pending.promise);
    const sending = controller.send("session-a", "分析项目");
    controller.selectSession("session-b");
    await controller.loadHistory("session-b");
    pending.resolve(terminal);
    await sending;
    expect(controller.getSnapshot().selectedId).toBe("session-b");
    expect(controller.getSnapshot().runs["session-b"]).toBeUndefined();
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("completed");
  });
  it("atomically replaces temporary output with history, never publishing both snapshots", async () => {
    const { api, controller } = setup();
    api.getMessages.mockResolvedValueOnce([]).mockResolvedValue(history);
    await controller.connect();
    await controller.loadHistory("session-a");
    const duplicateSnapshots: unknown[] = [];
    const unsubscribe = controller.subscribe(() => {
      const state = controller.getSnapshot();
      if (state.histories["session-a"]?.messages === history && state.runs["session-a"]?.items?.length) duplicateSnapshots.push(state);
    });
    await controller.send("session-a", "问题");
    unsubscribe();
    expect(controller.getSnapshot().histories["session-a"].messages).toEqual(history);
    expect(duplicateSnapshots).toEqual([]);
  });
  it("preserves success and answer when the subsequent history refresh fails", async () => {
    const { api, controller } = await connected();
    api.getMessages.mockRejectedValue(new ApiError(503, "storage_unavailable", "存储异常"));
    expect(await controller.send("session-a", "分析项目")).toBe(true);
    expect(controller.getSnapshot().runs["session-a"]).toMatchObject({ phase: "completed", answer: "分析完成" });
    expect(controller.getSnapshot().histories["session-a"].status).toBe("error");
    expect(api.streamRun).toHaveBeenCalledTimes(1);
  });
  it("does not downgrade completed execution when history reports incomplete", async () => {
    const { api, controller } = await connected();
    api.getMessages.mockRejectedValue(new ApiError(409, "session_incomplete", "历史不可读"));
    expect(await controller.send("session-a", "分析项目")).toBe(true);
    expect(controller.getSnapshot().runs["session-a"]).toMatchObject({ phase: "completed", answer: "分析完成" });
    expect(controller.getSnapshot().histories["session-a"].status).toBe("error");
  });
  it("keeps sends locked until the post-run refresh settles", async () => {
    const { api, controller } = await connected();
    const pending = deferred<typeof sessionA[]>();
    api.listSessions.mockReturnValue(pending.promise);
    const sending = controller.send("session-a", "分析项目");
    await vi.waitFor(() => expect(controller.getSnapshot().refreshing).toBe(true));
    expect(await controller.send("session-a", "重复")).toBe(false);
    expect(api.streamRun).toHaveBeenCalledTimes(1);
    pending.resolve([sessionA, sessionB]);
    await sending;
  });
  it("fetches a fresh list after a list read started during execution", async () => {
    const { api, controller } = await connected();
    const pendingRun = deferred<TerminalEvent>();
    const pendingList = deferred<typeof sessionA[]>();
    api.streamRun.mockReturnValue(pendingRun.promise);
    const sending = controller.send("session-a", "分析项目");
    api.listSessions.mockReturnValueOnce(pendingList.promise).mockResolvedValue([sessionA, sessionB]);
    const firstRefresh = controller.refreshSessions();
    pendingRun.resolve(terminal);
    await vi.waitFor(() => expect(controller.getSnapshot().runs["session-a"].phase).toBe("completed"));
    pendingList.resolve([sessionA, sessionB]);
    await firstRefresh;
    await sending;
    expect(api.listSessions).toHaveBeenCalledTimes(3);
  });
  it("preserves success when the subsequent list refresh fails", async () => {
    const { api, controller } = await connected();
    api.listSessions.mockRejectedValue(new TypeError("network"));
    expect(await controller.send("session-a", "分析项目")).toBe(true);
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("completed");
    expect(controller.getSnapshot().notice).toContain("列表刷新失败");
    expect(api.streamRun).toHaveBeenCalledTimes(1);
  });
  it("blocks uncertain runs until an explicit successful inspection and acknowledgement", async () => {
    const { api, controller } = await connected();
    api.streamRun.mockRejectedValue(new TypeError("network"));
    expect(await controller.send("session-a", "分析项目")).toBe(false);
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
    controller.acknowledgeUnknown("session-a");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
    expect(await controller.send("session-a", "重复")).toBe(false);
    await controller.loadHistory("session-a");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
    controller.acknowledgeUnknown("session-a");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("idle");
    expect(api.streamRun).toHaveBeenCalledTimes(1);
  });
  it("allows an explicit disconnect of uncertain state without retrying or claiming cancellation", async () => {
    const { api, controller } = await connected();
    api.streamRun.mockRejectedValue(new TypeError("network"));
    await controller.send("session-a", "分析项目");
    expect(controller.disconnect()).toBe(true);
    expect(controller.getSnapshot().runs).toEqual({});
    expect(api.streamRun).toHaveBeenCalledTimes(1);
  });
  it("blocks failed sessions but permits starting another session", async () => {
    const { api, controller } = await connected();
    api.streamRun.mockRejectedValue(new ApiError(502, "run_failed", "失败，有副作用", "r1"));
    await controller.send("session-a", "分析项目");
    expect(controller.getSnapshot().runs["session-a"]).toMatchObject({ phase: "needs_attention", runId: "r1" });
    expect(await controller.send("session-a", "重复")).toBe(false);
    expect(await controller.createSession("另建")).toBe(true);
  });
  it.each(["session_busy", "capacity_exceeded", "invalid_request"])("keeps %s rejected without retries", async (code) => {
    const { api, controller } = await connected();
    api.streamRun.mockRejectedValue(new ApiError(409, code, "拒绝"));
    await controller.send("session-a", "分析项目");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("rejected");
    expect(api.streamRun).toHaveBeenCalledTimes(1);
  });
  it("treats a mismatched response session as unknown", async () => {
    const { api, controller } = await connected();
    api.streamRun.mockResolvedValue({ ...terminal, session_id: "different" });
    await controller.send("session-a", "分析项目");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
  });
  it("keeps late streamed deltas scoped to the originating session and retains a run configuration snapshot", async () => {
    const { api, controller } = await connected();
    const pending = deferred<TerminalEvent>();
    api.streamRun.mockImplementation(async (_id, _message, onEvent) => {
      runEvents().slice(0, 2).forEach(onEvent);
      const result = await pending.promise;
      onEvent({ ...terminal, seq: 3, type: "assistant.reasoning.delta", message_id: "m1", role: "assistant", data: { delta: "思考" } });
      onEvent(result);
      return result;
    });
    const sending = controller.send("session-a", "问题");
    controller.selectSession("session-b");
    await controller.loadHistory("session-b");
    pending.resolve(terminal);
    await sending;
    expect(controller.getSnapshot().selectedId).toBe("session-b");
    expect(controller.getSnapshot().runs["session-b"]).toBeUndefined();
    expect(controller.getSnapshot().runs["session-a"].thinking).toEqual(runtime.thinking);
    expect(api.run).not.toHaveBeenCalled();
  });
  it.each(["run.failed", "run.cancelled"] as const)("preserves partial output on %s and blocks reexecution", async (type) => {
    const { api, controller } = await connected();
    api.streamRun.mockImplementation(async (_id, _message, onEvent) => {
      runEvents().slice(0, 3).forEach(onEvent);
      const result: TerminalEvent = { ...terminal, type, data: { code: "run_cancelled", message: "本轮结束" } };
      onEvent(result); return result;
    });
    await controller.send("session-a", "问题");
    expect(controller.getSnapshot().runs["session-a"]).toMatchObject({ phase: type === "run.failed" ? "failed" : "cancelled", receiving: false, items: [{ kind: "assistant", text: "分析完成" }] });
    expect(await controller.send("session-a", "重发")).toBe(false);
    expect(api.streamRun).toHaveBeenCalledTimes(1);
    expect(api.getMessages).toHaveBeenCalledTimes(1);
  });
  it("stops only the original request and does not claim a confirmed cancellation", async () => {
    const { api, controller } = await connected();
    api.streamRun.mockImplementation(async (_id, _message, onEvent, signal) => {
      runEvents().slice(0, 3).forEach(onEvent);
      return new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("stop", "AbortError")), { once: true }));
    });
    const sending = controller.send("session-a", "问题");
    controller.selectSession("session-b");
    controller.stop("session-b");
    expect(api.streamRun.mock.calls[0][3].aborted).toBe(false);
    controller.stop("session-a");
    await sending;
    const run = controller.getSnapshot().runs["session-a"];
    expect(run).toMatchObject({ phase: "unknown", receiving: false, stopping: true });
    expect(run.error).toContain("已停止接收");
    expect(run.items).toHaveLength(1);
    expect(await controller.send("session-b", "再次运行")).toBe(false);
    expect(api.streamRun).toHaveBeenCalledTimes(1);
  });
  it("does not turn admission into success when the stream disconnects", async () => {
    const { api, controller } = await connected();
    api.streamRun.mockImplementation(async (_id, _message, onEvent) => {
      runEvents().slice(0, 3).forEach(onEvent);
      throw new ApiError(200, "invalid_response", "没有终态");
    });
    await controller.send("session-a", "问题");
    expect(controller.getSnapshot().runs["session-a"]).toMatchObject({ phase: "unknown", runId: "run-1", items: [{ text: "分析完成" }] });
    expect(api.getMessages).toHaveBeenCalledTimes(1);
  });
  it("connects to an unconfigured backend without attempting session APIs", async () => {
    const { api, controller } = setup();
    api.getRuntime.mockResolvedValue({ ...runtime, configured: false, ready: false, thinking: null });
    expect(await controller.connect()).toBe(true);
    expect(api.listSessions).not.toHaveBeenCalled();
    expect(await controller.createSession()).toBe(false);
    expect(await controller.send("session-a", "问题")).toBe(false);
  });
  it("clears invalid selections rather than treating 404 as empty history", async () => {
    const { api, controller } = await connected();
    api.getMessages.mockRejectedValue(new ApiError(404, "session_not_found", "不存在"));
    await controller.loadHistory("session-a");
    expect(controller.getSnapshot().selectedId).toBeNull();
    expect(controller.getSnapshot().sessions).toEqual([sessionB]);
  });
  it("does not send until history is readable", async () => {
    const { api, controller } = setup();
    const pending = deferred<MessageResponse[]>();
    api.getMessages.mockReturnValue(pending.promise);
    await controller.connect();
    expect(await controller.send("session-a", "hello")).toBe(false);
    expect(api.streamRun).not.toHaveBeenCalled();
    pending.resolve([]);
    await controller.loadHistory("session-a");
  });
  it("preserves tracking for unexpected errors instead of treating them as token expiry", async () => {
    const { api, controller } = await connected();
    api.streamRun.mockRejectedValue(new ApiError(401, "unauthorized", "unexpected upstream rejection"));
    await controller.send("session-a", "分析项目");
    expect(controller.getSnapshot().connection).toBe("connected");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
    expect(controller.getSnapshot().histories["session-a"].messages).toEqual(history);
    expect(api.streamRun).toHaveBeenCalledTimes(1);
  });
});
