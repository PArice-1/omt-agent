import { QueryClient } from "@tanstack/react-query";
import { createOmtClient } from "@/lib/omt-api/client";
import type { OmtClient } from "@/lib/omt-api/contracts";
import { ApiError, classifyRunError, errorMessage } from "@/lib/omt-api/errors";
import { validateMessage } from "./format";
import type { RunState, WorkspaceState } from "./types";

const initialState = (): WorkspaceState => ({
  connection: "disconnected", sessions: [], selectedId: null,
  histories: {}, runs: {}, creating: false, refreshing: false,
});

type ClientFactory = (getToken: () => string) => OmtClient;

/** All async writes belong to both a connection generation and a session ID. */
export class WorkspaceController {
  private state = initialState();
  private listeners = new Set<() => void>();
  private token = "";
  private generation = 0;
  private historyRequests = new Map<string, Promise<void>>();
  private listRequest: Promise<boolean> | undefined;
  private client: OmtClient;
  private queries = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 }, mutations: { retry: false } },
  });

  constructor(factory: ClientFactory = (getToken) => createOmtClient({ getToken })) {
    this.client = factory(() => this.token);
  }

  getSnapshot = (): WorkspaceState => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private patch(patch: Partial<WorkspaceState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  private setRun(id: string, run: RunState) {
    this.patch({ runs: { ...this.state.runs, [id]: run } });
  }

  private isCurrent(generation: number) { return this.generation === generation; }
  private isRunning() { return Object.values(this.state.runs).some((run) => run.phase === "sending"); }
  private hasUnknown() { return Object.values(this.state.runs).some((run) => run.phase === "unknown"); }

  connect = async (token: string): Promise<boolean> => {
    if (this.state.connection === "connecting" || this.isRunning() || this.state.creating) return false;
    if (token.trim().length < 32) {
      this.patch({ connectionError: "访问令牌去除首尾空白后至少需要 32 个字符。" });
      return false;
    }
    this.generation += 1;
    const generation = this.generation;
    this.queries.clear();
    this.historyRequests.clear();
    this.listRequest = undefined;
    this.token = token;
    this.patch({ ...initialState(), connection: "connecting" });
    try {
      const sessions = await this.client.listSessions();
      if (!this.isCurrent(generation)) return false;
      const selectedId = sessions[0]?.session_id ?? null;
      this.patch({ connection: "connected", sessions, selectedId });
      if (selectedId) void this.loadHistory(selectedId);
      return true;
    } catch (error) {
      if (!this.isCurrent(generation)) return false;
      this.token = "";
      this.patch({ connection: "disconnected", connectionError: errorMessage(error) });
      return false;
    }
  };

  disconnect = (): boolean => {
    if (this.isRunning() || this.state.creating || this.state.connection === "connecting") return false;
    this.generation += 1;
    this.token = "";
    this.queries.clear();
    this.historyRequests.clear();
    this.listRequest = undefined;
    this.patch(initialState());
    return true;
  };

  private authExpired(error: unknown, generation: number): boolean {
    if (!this.isCurrent(generation)) return false;
    if (error instanceof ApiError && error.code === "unauthorized") {
      this.disconnect();
      // An unauthorized run is a definite rejection, so it is safe to forget this credential.
      if (this.state.connection === "disconnected") {
        this.patch({ connectionError: "访问令牌已失效，请重新连接。" });
      }
      return true;
    }
    return false;
  }

  refreshSessions = (): Promise<boolean> => {
    if (this.state.connection !== "connected" || this.state.creating) return Promise.resolve(false);
    if (this.listRequest) return this.listRequest;
    const generation = this.generation;
    this.patch({ refreshing: true, notice: undefined });
    const request = (async () => {
      try {
        const sessions = await this.queries.fetchQuery({
          queryKey: [generation, "sessions"], queryFn: () => this.client.listSessions(),
        });
        if (!this.isCurrent(generation)) return false;
        const selectedId = this.state.selectedId;
        const missing = selectedId !== null && !sessions.some((session) => session.session_id === selectedId);
        this.patch({ sessions, selectedId: missing ? null : selectedId,
          notice: missing ? "当前会话已不可用，请重新选择或新建会话。" : undefined });
        return true;
      } catch (error) {
        if (this.isCurrent(generation) && !this.authExpired(error, generation)) {
          this.patch({ notice: `会话列表刷新失败：${errorMessage(error)}` });
        }
        return false;
      } finally {
        if (this.isCurrent(generation)) {
          this.listRequest = undefined;
          this.patch({ refreshing: false });
        }
      }
    })();
    this.listRequest = request;
    return request;
  };

  selectSession = (id: string) => {
    if (!this.state.sessions.some((session) => session.session_id === id)) return;
    this.patch({ selectedId: id });
    if (!this.state.histories[id] && this.state.runs[id]?.phase !== "sending") void this.loadHistory(id);
  };

  loadHistory = (id: string): Promise<void> => {
    if (this.state.connection !== "connected" || this.state.runs[id]?.phase === "sending") return Promise.resolve();
    const existing = this.historyRequests.get(id);
    if (existing) return existing;
    const generation = this.generation;
    const messages = this.state.histories[id]?.messages ?? [];
    this.patch({ histories: { ...this.state.histories, [id]: { status: "loading", messages } } });
    const request = (async () => {
      try {
        const history = await this.queries.fetchQuery({
          queryKey: [generation, "messages", id], queryFn: () => this.client.getMessages(id),
        });
        if (!this.isCurrent(generation)) return;
        this.patch({ histories: { ...this.state.histories, [id]: { status: "ready", messages: history } } });
        const run = this.state.runs[id];
        if (run?.phase === "completed") this.setRun(id, { ...run, message: undefined, answer: undefined });
        if (run?.phase === "unknown") this.setRun(id, { ...run, reviewed: true });
      } catch (error) {
        if (!this.isCurrent(generation) || this.authExpired(error, generation)) return;
        this.patch({ histories: { ...this.state.histories, [id]: {
          status: "error", messages, error: errorMessage(error),
        } } });
        if (error instanceof ApiError && error.code === "session_incomplete" && this.state.runs[id]?.phase !== "completed") {
          this.setRun(id, { ...this.state.runs[id], phase: "needs_attention", error: errorMessage(error) });
        }
        if (error instanceof ApiError && error.code === "session_not_found") {
          this.patch({ selectedId: this.state.selectedId === id ? null : this.state.selectedId,
            sessions: this.state.sessions.filter((session) => session.session_id !== id),
            notice: "会话不存在或不属于当前工作目录，已清除失效选择。" });
        }
      } finally {
        if (this.isCurrent(generation)) this.historyRequests.delete(id);
      }
    })();
    this.historyRequests.set(id, request);
    return request;
  };

  createSession = async (title?: string): Promise<boolean> => {
    if (this.state.connection !== "connected" || this.state.creating || this.state.refreshing || this.isRunning() || this.hasUnknown()) return false;
    if (title !== undefined && (Array.from(title).length > 200 || title.includes("\u0000"))) {
      this.patch({ notice: "标题不能超过 200 个字符，也不能包含 NUL。" });
      return false;
    }
    const generation = this.generation;
    this.patch({ creating: true, notice: undefined });
    try {
      const session = await this.client.createSession(title === undefined ? {} : { title });
      if (!this.isCurrent(generation)) return false;
      this.patch({ sessions: [session, ...this.state.sessions], selectedId: session.session_id,
        histories: { ...this.state.histories, [session.session_id]: { status: "ready", messages: [] } } });
      return true;
    } catch (error) {
      if (this.isCurrent(generation)) {
        this.patch({ creating: false });
        if (!this.authExpired(error, generation)) this.patch({ notice:
          `创建未确认：${errorMessage(error)} 请先刷新列表检查是否已创建，不要连续重复创建。` });
      }
      return false;
    } finally {
      if (this.isCurrent(generation)) this.patch({ creating: false });
    }
  };

  send = async (id: string, message: string): Promise<boolean> => {
    const run = this.state.runs[id];
    if (this.state.connection !== "connected" || this.state.creating || this.state.refreshing || this.isRunning() || this.hasUnknown()
      || run?.phase === "needs_attention" || this.state.histories[id]?.status !== "ready") return false;
    const validation = validateMessage(message);
    if (validation) {
      this.setRun(id, { phase: "rejected", error: validation });
      return false;
    }
    const generation = this.generation;
    // Set the lock synchronously, before any await (including a double click in one render).
    this.setRun(id, { phase: "sending", message });
    try {
      const result = await this.client.run(id, message);
      if (!this.isCurrent(generation)) return false;
      if (result.session_id !== id) throw new ApiError(200, "invalid_response", "执行响应的会话 ID 不匹配，无法确认结果。");
      this.setRun(id, { phase: "completed", message, answer: result.answer,
        warnings: result.warnings, runId: result.run_id });
    } catch (error) {
      if (!this.isCurrent(generation)) return false;
      this.setRun(id, { phase: classifyRunError(error), message, error: errorMessage(error),
        runId: error instanceof ApiError ? error.runId : undefined, reviewed: false });
      this.authExpired(error, generation);
      return false;
    }
    // Read failures cannot turn a confirmed completed run into a failed run or resend it.
    // A list request begun before completion may contain stale timestamps/order.
    // Finish it first, then explicitly request a post-completion snapshot.
    const priorList = this.listRequest;
    const refreshList = async () => {
      if (priorList) await priorList;
      if (this.isCurrent(generation)) await this.refreshSessions();
    };
    await Promise.all([this.loadHistory(id), refreshList()]);
    return this.isCurrent(generation);
  };

  acknowledgeUnknown = (id: string) => {
    const run = this.state.runs[id];
    if (run?.phase === "unknown" && run.reviewed && this.state.histories[id]?.status === "ready") {
      this.setRun(id, { phase: "idle" });
    }
  };
}
