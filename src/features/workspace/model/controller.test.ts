import { describe, expect, it, vi } from "vitest";
import type { MessageResponse, OmtClient, RunResponse } from "@/lib/omt-api/contracts";
import { ApiError } from "@/lib/omt-api/errors";
import { WorkspaceController } from "./controller";
import { completedRun, deferred, history, sessionA, sessionB, testToken } from "../../../../tests/fixtures";

function setup() {
  const api = {
    health: vi.fn<OmtClient["health"]>().mockResolvedValue({ status: "ok" }),
    listSessions: vi.fn<OmtClient["listSessions"]>().mockResolvedValue([sessionA, sessionB]),
    createSession: vi.fn<OmtClient["createSession"]>().mockResolvedValue({ ...sessionA, session_id: "new" }),
    getMessages: vi.fn<OmtClient["getMessages"]>().mockImplementation(async (id) => id === "session-a" ? history : []),
    run: vi.fn<OmtClient["run"]>().mockResolvedValue(completedRun),
  };
  let getToken = () => "";
  const controller = new WorkspaceController((reader) => { getToken = reader; return api; });
  return { api, controller, getToken: () => getToken() };
}
async function connected() {
  const result = setup();
  await result.controller.connect(testToken);
  await result.controller.loadHistory(sessionA.session_id);
  return result;
}
describe("workspace controller", () => {
  it("stores credentials privately and clears them and caches on disconnect", async () => {
    const { controller, getToken } = await connected();
    expect(getToken()).toBe(testToken);
    expect(JSON.stringify(controller.getSnapshot())).not.toContain(testToken);
    expect(controller.getSnapshot().histories["session-a"].messages).toEqual(history);
    controller.disconnect();
    expect(getToken()).toBe("");
    expect(controller.getSnapshot().sessions).toEqual([]);
    expect(controller.getSnapshot().histories).toEqual({});
  });
  it("rejects a short token without contacting the backend", async () => {
    const { api, controller } = setup();
    expect(await controller.connect("short")).toBe(false);
    expect(api.listSessions).not.toHaveBeenCalled();
  });
  it("does not retry failed authentication", async () => {
    const { api, controller, getToken } = setup();
    api.listSessions.mockRejectedValue(new ApiError(401, "unauthorized", "无权限"));
    expect(await controller.connect(testToken)).toBe(false);
    expect(api.listSessions).toHaveBeenCalledTimes(1);
    expect(getToken()).toBe("");
  });
  it("deduplicates overlapping history reads", async () => {
    const { api, controller } = setup();
    const pending = deferred<MessageResponse[]>();
    api.getMessages.mockReturnValue(pending.promise);
    await controller.connect(testToken);
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
    await controller.connect(testToken);
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
    await controller.connect(testToken);
    const old = controller.loadHistory("session-a");
    controller.disconnect();
    await controller.connect(testToken);
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
    const pending = deferred<RunResponse>();
    api.run.mockReturnValue(pending.promise);
    const first = controller.send("session-a", "分析项目");
    expect(await controller.send("session-a", "重复")).toBe(false);
    await controller.loadHistory("session-a");
    expect(api.getMessages).toHaveBeenCalledTimes(1);
    expect(controller.disconnect()).toBe(false);
    expect(api.run).toHaveBeenCalledTimes(1);
    pending.resolve(completedRun);
    expect(await first).toBe(true);
    expect(api.getMessages).toHaveBeenCalledTimes(2);
    expect(controller.getSnapshot().histories["session-a"].messages).toEqual(history);
    expect(controller.getSnapshot().runs["session-a"].answer).toBeUndefined();
  });
  it("routes a completed answer back to its original session", async () => {
    const { api, controller } = await connected();
    const pending = deferred<RunResponse>();
    api.run.mockReturnValue(pending.promise);
    const sending = controller.send("session-a", "分析项目");
    controller.selectSession("session-b");
    await controller.loadHistory("session-b");
    pending.resolve(completedRun);
    await sending;
    expect(controller.getSnapshot().selectedId).toBe("session-b");
    expect(controller.getSnapshot().runs["session-b"]).toBeUndefined();
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("completed");
  });
  it("preserves success and answer when the subsequent history refresh fails", async () => {
    const { api, controller } = await connected();
    api.getMessages.mockRejectedValue(new ApiError(503, "storage_unavailable", "存储异常"));
    expect(await controller.send("session-a", "分析项目")).toBe(true);
    expect(controller.getSnapshot().runs["session-a"]).toMatchObject({ phase: "completed", answer: "分析完成" });
    expect(controller.getSnapshot().histories["session-a"].status).toBe("error");
    expect(api.run).toHaveBeenCalledTimes(1);
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
    expect(api.run).toHaveBeenCalledTimes(1);
    pending.resolve([sessionA, sessionB]);
    await sending;
  });
  it("fetches a fresh list after a list read started during execution", async () => {
    const { api, controller } = await connected();
    const pendingRun = deferred<RunResponse>();
    const pendingList = deferred<typeof sessionA[]>();
    api.run.mockReturnValue(pendingRun.promise);
    const sending = controller.send("session-a", "分析项目");
    api.listSessions.mockReturnValueOnce(pendingList.promise).mockResolvedValue([sessionA, sessionB]);
    const firstRefresh = controller.refreshSessions();
    pendingRun.resolve(completedRun);
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
    expect(api.run).toHaveBeenCalledTimes(1);
  });
  it("blocks uncertain runs until an explicit successful inspection and acknowledgement", async () => {
    const { api, controller } = await connected();
    api.run.mockRejectedValue(new TypeError("network"));
    expect(await controller.send("session-a", "分析项目")).toBe(false);
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
    controller.acknowledgeUnknown("session-a");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
    expect(await controller.send("session-a", "重复")).toBe(false);
    await controller.loadHistory("session-a");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
    controller.acknowledgeUnknown("session-a");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("idle");
    expect(api.run).toHaveBeenCalledTimes(1);
  });
  it("allows an explicit disconnect of uncertain state without retrying or claiming cancellation", async () => {
    const { api, controller, getToken } = await connected();
    api.run.mockRejectedValue(new TypeError("network"));
    await controller.send("session-a", "分析项目");
    expect(controller.disconnect()).toBe(true);
    expect(getToken()).toBe("");
    expect(controller.getSnapshot().runs).toEqual({});
    expect(api.run).toHaveBeenCalledTimes(1);
  });
  it("blocks failed sessions but permits starting another session", async () => {
    const { api, controller } = await connected();
    api.run.mockRejectedValue(new ApiError(502, "run_failed", "失败，有副作用", "r1"));
    await controller.send("session-a", "分析项目");
    expect(controller.getSnapshot().runs["session-a"]).toMatchObject({ phase: "needs_attention", runId: "r1" });
    expect(await controller.send("session-a", "重复")).toBe(false);
    expect(await controller.createSession("另建")).toBe(true);
  });
  it.each(["session_busy", "capacity_exceeded", "invalid_request"])("keeps %s rejected without retries", async (code) => {
    const { api, controller } = await connected();
    api.run.mockRejectedValue(new ApiError(409, code, "拒绝"));
    await controller.send("session-a", "分析项目");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("rejected");
    expect(api.run).toHaveBeenCalledTimes(1);
  });
  it("treats a mismatched response session as unknown", async () => {
    const { api, controller } = await connected();
    api.run.mockResolvedValue({ ...completedRun, session_id: "different" });
    await controller.send("session-a", "分析项目");
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("unknown");
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
    await controller.connect(testToken);
    expect(await controller.send("session-a", "hello")).toBe(false);
    expect(api.run).not.toHaveBeenCalled();
    pending.resolve([]);
    await controller.loadHistory("session-a");
  });
  it("clears invalid credentials after a rejected run", async () => {
    const { api, controller, getToken } = await connected();
    api.run.mockRejectedValue(new ApiError(401, "unauthorized", "无权限"));
    await controller.send("session-a", "分析项目");
    expect(controller.getSnapshot().connection).toBe("disconnected");
    expect(getToken()).toBe("");
  });
});
