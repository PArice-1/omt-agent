"use client";
import { useState } from "react";
import { KeyRound, ShieldCheck, Unplug } from "lucide-react";
import { Dialog } from "@/components/ui/dialog";
import type { WorkspaceState } from "@/features/workspace/model/types";

interface Props {
  state: WorkspaceState;
  busy: boolean;
  onConnect(token: string): Promise<boolean>;
  onDisconnect(): boolean;
  onClose(): void;
}
export function ConnectionDialog({ state, busy, onConnect, onDisconnect, onClose }: Props) {
  const [token, setToken] = useState("");
  const connecting = state.connection === "connecting";
  const connected = state.connection === "connected";
  return <Dialog title={connected ? "连接设置" : "连接你的 OMT"} description="连接本机后端，开始一个属于你的工作空间。" onClose={onClose} busy={connecting}>
    <div className="endpoint"><span className="status-dot" />同源代理 → 本机 OMT 后端</div>
    {connected ? <div className="connected-info">
      <ShieldCheck size={30} /><h3>已连接，准备就绪</h3>
      <p>令牌仅保存在本页面内存中。断开会清除当前界面数据，但不会删除后端会话，也不会停止后端执行。</p>
      {Object.values(state.runs).some((run) => run.phase === "unknown") && <p className="field-error" role="alert">存在结果不明的执行。断开将丢失本页跟踪信息，不代表后端已停止；重新连接也无法自动恢复该执行状态。</p>}
      <button className="button secondary full-width" disabled={busy} onClick={() => { if (onDisconnect()) onClose(); }}><Unplug size={16} />断开连接</button>
      {busy && <p className="subtle">请先等待当前操作完成。</p>}
    </div> : <form onSubmit={async (event) => {
      event.preventDefault();
      if (await onConnect(token)) { setToken(""); onClose(); }
    }}>
      <label className="field-label" htmlFor="access-token"><KeyRound size={15} />访问令牌</label>
      <input id="access-token" type="password" autoComplete="off" autoFocus spellCheck={false}
        value={token} onChange={(event) => setToken(event.target.value)} placeholder="输入后端的 Bearer 访问令牌" disabled={connecting} required />
      <p className="field-help">使用后端访问令牌，不是模型 API Key。</p>
      {state.connectionError && <p className="field-error" role="alert">{state.connectionError}</p>}
      <div className="privacy-note"><ShieldCheck size={18} /><span>只存内存，不写入浏览器存储。刷新页面后需要重新输入。</span></div>
      <button className="button primary full-width" disabled={connecting || !token.trim()} type="submit">{connecting ? "正在验证连接…" : "连接本机后端"}</button>
    </form>}
  </Dialog>;
}
