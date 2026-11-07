"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import { RuntimeSettings } from "@/features/runtime/runtime-settings";
import { RuntimeControls, RuntimeFeedback } from "@/features/runtime/runtime-controls";
import { ArrowUpRight, CircleAlert, Menu, RefreshCw, Sparkles, X } from "lucide-react";
import { ConnectionDialog } from "@/features/connection/connection-dialog";
import { WorkspaceController } from "./model/controller";
import { sessionTitle } from "./model/format";
import { Sidebar } from "./components/sidebar";
import { Welcome } from "./components/welcome";
import { Composer } from "./components/composer";
import { Messages } from "./components/messages";
import { RunNotice } from "./components/run-notice";
import { NewSessionDialog } from "./components/new-session-dialog";

export function Workspace({ controller: provided }: { controller?: WorkspaceController }) {
  const [controller] = useState(() => provided ?? new WorkspaceController());
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  const runtimeState = useSyncExternalStore(controller.runtime.subscribe, controller.runtime.getSnapshot, controller.runtime.getSnapshot);
  useEffect(() => { void controller.runtime.inspect(); }, [controller]);
  const [runtimeOpen, setRuntimeOpen] = useState(false);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const id = state.selectedId;
  const draftKey = id ?? "__new";
  const connected = state.connection === "connected";
  const connectionIssue = connected && state.backendStatus === "unavailable";
  const selected = state.sessions.find((session) => session.session_id === id);
  const history = id ? state.histories[id] : undefined;
  const run = id ? state.runs[id] : undefined;
  const running = Object.values(state.runs).some((item) => item.phase === "sending" || item.receiving);
  const unknown = Object.values(state.runs).some((item) => item.phase === "unknown");
  const protectedRun = ["needs_attention", "failed", "cancelled"].includes(run?.phase ?? "");
  const disabled = !connected || !id || running || unknown || state.creating || state.refreshing || history?.status !== "ready" || protectedRun || !runtimeState.runtime?.ready || Boolean(runtimeState.pending) || runtimeState.runtime.changing || runtimeState.runtime.busy;
  const hint = !runtimeState.runtime?.ready ? "请先配置模型并确认运行实例就绪" : runtimeState.pending || runtimeState.runtime.changing ? "正在读取或切换全局运行设置" : runtimeState.runtime.busy ? "后端忙碌，可重新检查运行状态" : !connected ? "连接本机后端后即可开始" : running ? "正在增量接收本轮输出，不会自动重试" : unknown ? "请先检查结果不明的会话" : protectedRun ? "当前会话需要人工检查" : !id ? "先新建或选择一个会话" : history?.status === "error" ? "请先重新读取历史" : history?.status === "loading" ? "正在加载历史" : state.refreshing ? "正在刷新会话列表" : connectionIssue ? "最近请求异常，可在连接设置中检查" : "SSE 增量输出 · 成功后同步完整历史";
  const hasMessages = Boolean(history?.messages.length || run?.message !== undefined || run?.items?.length);
  const setDraft = (text: string) => setDrafts((previous) => ({ ...previous, [draftKey]: text }));
  const openNew = () => {
    if (!runtimeState.runtime?.ready) setRuntimeOpen(true);
    else if (!connected) setConnectionOpen(true);
    else if (!running && !unknown && !runtimeState.pending) setNewOpen(true);
  };

  return <div className="app-shell">
    <Sidebar state={state} expanded={sidebarExpanded} sessionReady={runtimeState.runtime?.ready ?? false} settingsBusy={Boolean(runtimeState.pending)} onNew={openNew} onSelect={(sessionId) => { controller.selectSession(sessionId); setSidebarExpanded(false); }}
      onRefresh={() => { void controller.refreshSessions(); }} onConnection={() => setConnectionOpen(true)} onModels={() => { setRuntimeOpen(true); setSidebarExpanded(false); }} />
    <main className="main-panel">
      <header className="topbar">
        <div className="topbar-left"><button className="icon-button mobile-menu" aria-label="展开会话导航" aria-expanded={sidebarExpanded} aria-controls="session-sidebar" onClick={() => setSidebarExpanded(!sidebarExpanded)}><Menu size={20} /></button>
          <span className="workspace-label">工作空间</span><span className="breadcrumb-slash">/</span><span className="current-title">{selected ? sessionTitle(selected.title) : "新的开始"}</span>
        </div>
        <button className={`connection-pill ${connectionIssue ? "has-issue" : ""}`} title={connectionIssue ? "之前连接成功，但最近请求未取得有效响应；不代表执行已取消。" : connected ? "最近请求已通过，不代表后续请求一定成功。" : "无需令牌，连接本机后端"} onClick={() => setConnectionOpen(true)}><span className={`status-dot ${connectionIssue ? "issue" : connected ? "connected" : ""}`} />{connectionIssue ? "连接待检查" : connected ? "本机已连接" : "未连接"}<ArrowUpRight size={13} /></button>
      </header>
      {(state.notice || !connected && state.connectionError && !connectionOpen) && <div className="global-notice" role="alert"><CircleAlert size={17} /><span>{state.notice || state.connectionError}</span>{!connected && <button className="text-button" onClick={() => setConnectionOpen(true)}>重新连接</button>}<button type="button" className="icon-button" aria-label="关闭提示" onClick={controller.dismissNotice}><X size={17} /></button></div>}
      <div className="conversation">
        {id && <div className="conversation-toolbar"><span><Sparkles size={14} />{sessionTitle(selected?.title)}</span><button className="text-button" disabled={run?.phase === "sending" || run?.receiving || history?.status === "loading"} onClick={() => { void controller.loadHistory(id); }}><RefreshCw size={13} className={history?.status === "loading" ? "spin" : ""} />{history?.status === "loading" ? "正在读取" : "刷新历史"}</button></div>}
        <div className="notice-region"><RunNotice run={run} history={history} onInspect={() => { if (id) void controller.loadHistory(id); }} onAcknowledge={() => { if (id) controller.acknowledgeUnknown(id); }} />
          {history?.status === "error" && <div className="history-error" role="alert"><CircleAlert size={17} /><span>{run?.phase === "completed" ? "历史刷新失败，执行已成功。" : "历史读取失败，不代表空会话。"} {history.error}</span><button className="text-button" onClick={() => { if (id) void controller.loadHistory(id); }}>重新读取历史</button></div>}
        </div>
        {hasMessages ? <Messages key={id} messages={history?.messages ?? []} run={run} /> : history?.status === "loading" ? <div className="loading-history" role="status"><RefreshCw size={22} className="spin" />正在读取会话历史…</div> :
          history?.status === "error" || run?.phase === "needs_attention" ? <div className="empty-error"><CircleAlert size={34} /><h2>暂时无法展示这段历史</h2><p>请查看上方提示，检查后端或稍后手动重试。</p></div> :
            <Welcome connected={connected} hasSession={Boolean(id)} onConnect={() => setConnectionOpen(true)} onNew={openNew}
              onPrompt={(text) => { setDraft(text); if (!id) openNew(); }} />}
        <Composer controls={<RuntimeControls state={runtimeState} busy={running || state.creating} onModel={(provider, model) => { void controller.runtime.changeModel(provider, model); }} onThinking={(level) => { void controller.runtime.changeThinking(level); }} />}
          settingsFeedback={!runtimeOpen && <RuntimeFeedback state={runtimeState} />} value={drafts[draftKey] ?? ""} onChange={setDraft} disabled={disabled} sending={Boolean(run?.receiving)} stopping={run?.stopping} onStop={() => { if (id) controller.stop(id); }} hint={hint} onSend={() => {
          if (!id) return;
          const text = drafts[id] ?? "";
          void controller.send(id, text).then((success) => {
            if (success) setDrafts((previous) => previous[id] === text ? { ...previous, [id]: "" } : previous);
          });
        }} />
      </div>
    </main>
    {runtimeOpen && <RuntimeSettings state={runtimeState} controller={controller.runtime} busy={running || state.creating} onClose={() => setRuntimeOpen(false)} onConfigured={() => { if (connected) void controller.refreshSessions(); }} />}
    {connectionOpen && <ConnectionDialog state={state} busy={running || state.creating} onConnect={async () => { const success = await controller.connect(); if (success) setDrafts({}); return success; }} onCheck={async () => { const runtime = await controller.runtime.inspect(); return runtime?.ready ? controller.refreshSessions() : Boolean(runtime); }} onDisconnect={() => { const success = controller.disconnect(); if (success) setDrafts({}); return success; }} onClose={() => setConnectionOpen(false)} />}
    {newOpen && <NewSessionDialog busy={state.creating} error={state.notice} onClose={() => setNewOpen(false)} onCreate={async (title) => {
      const success = await controller.createSession(title);
      const selectedId = controller.getSnapshot().selectedId;
      if (success && selectedId && drafts.__new) setDrafts((previous) => ({ ...previous, [selectedId]: previous.__new, __new: "" }));
      return success;
    }} />}
  </div>;
}
