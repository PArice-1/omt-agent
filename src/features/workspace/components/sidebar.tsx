import { ArrowUpRight, Check, CircleAlert, LoaderCircle, MessageSquare, Plus, RefreshCw, Sparkles } from "lucide-react";
import { formatTimestamp, sessionTitle } from "../model/format";
import type { WorkspaceState } from "../model/types";

interface Props {
  state: WorkspaceState;
  expanded: boolean;
  onNew(): void;
  onSelect(id: string): void;
  onRefresh(): void;
  onConnection(): void;
}
export function Sidebar({ state, expanded, onNew, onSelect, onRefresh, onConnection }: Props) {
  const connected = state.connection === "connected";
  const connectionIssue = connected && state.backendStatus === "unavailable";
  const locked = state.creating || state.refreshing || Object.values(state.runs).some((run) => ["sending", "unknown"].includes(run.phase));
  return <aside id="session-sidebar" className={`sidebar ${expanded ? "is-expanded" : ""}`} aria-label="会话导航">
    <div className="brand" aria-label="OMT"><span className="brand-mark"><Sparkles size={23} /></span><span>omt<span className="brand-period">.</span></span><span className="brand-caption">workspace</span></div>
    <button className="new-session-button" onClick={connected ? onNew : onConnection} disabled={connected && locked}><Plus size={18} />新建会话<span>＋</span></button>
    <div className="section-heading"><span>你的会话</span><button className="icon-button" aria-label="刷新会话列表" disabled={!connected || state.refreshing || state.creating} onClick={onRefresh}><RefreshCw size={14} className={state.refreshing ? "spin" : ""} /></button></div>
    <nav className="session-list" aria-label="会话列表">
      {state.sessions.map((session) => {
        const phase = state.runs[session.session_id]?.phase;
        return <button key={session.session_id} className={`session-item ${state.selectedId === session.session_id ? "active" : ""}`} onClick={() => onSelect(session.session_id)} aria-current={state.selectedId === session.session_id ? "true" : undefined}>
          <MessageSquare size={16} /><span className="session-label"><span>{sessionTitle(session.title)}</span><time>{formatTimestamp(session.updated_at)}</time></span>
          {phase === "sending" ? <LoaderCircle size={14} className="spin" aria-label="正在执行" /> :
            phase === "unknown" || phase === "needs_attention" ? <CircleAlert size={14} className="warning-icon" aria-label="需要检查" /> :
              state.selectedId === session.session_id ? <span className="active-dot" /> : null}
        </button>;
      })}
      {!state.sessions.length && <p className="sidebar-empty">{connected ? "还没有会话。\n从一个新想法开始吧。" : "连接后，你的会话\n会出现在这里。"}</p>}
    </nav>
    <div className="sidebar-footer">
      <div className="local-note"><span className="local-note-icon"><Check size={15} /></span><div><strong>只属于你的空间</strong><span>本机运行 · 历史由后端保存</span></div></div>
      <button className="connection-button" onClick={onConnection}><span className={`status-dot ${connectionIssue ? "issue" : connected ? "connected" : ""}`} /><span>{connectionIssue ? "后端连接待检查" : connected ? "本机后端已连接" : "连接本机后端"}</span><ArrowUpRight size={15} /></button>
    </div>
  </aside>;
}
