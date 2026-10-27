"use client";
import { useEffect, useRef } from "react";
import { ShieldCheck, Unplug } from "lucide-react";
import { Dialog } from "@/components/ui/dialog";
import type { WorkspaceState } from "@/features/workspace/model/types";

interface Props {
  state: WorkspaceState;
  busy: boolean;
  onConnect(): Promise<boolean>;
  onDisconnect(): boolean;
  onCheck(): Promise<boolean>;
  onClose(): void;
}
export function ConnectionDialog({ state, busy, onConnect, onDisconnect, onCheck, onClose }: Props) {
  const connectButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    // Dialog enters the top layer in its child effect before this focus runs.
    connectButton.current?.focus();
  }, []);
  const connecting = state.connection === "connecting";
  const connected = state.connection === "connected";
  const connectionIssue = connected && state.backendStatus === "unavailable";
  return <Dialog title={connected ? "连接设置" : "连接你的 OMT"} description="连接本机后端，开始一个属于你的工作空间。" onClose={onClose} busy={connecting}>
    <div className="endpoint"><span className="status-dot" />同源代理 → 本机 OMT 后端</div>
    {connected ? <div className="connected-info">
      <ShieldCheck size={30} /><h3>{connectionIssue ? "最近请求异常，连接待检查" : "本机后端连接成功"}</h3>
      <p>{connectionIssue ? "之前验证成功不代表每次请求都能成功。可以检查当前连接；这不会重发消息，也不能确认丢失响应的执行结果。" : "这里只记录最近请求的结果，不是持续在线检测。"}</p>
      <p>断开会清除当前界面数据，但不会删除后端会话，也不会停止后端执行。</p>
      {Object.values(state.runs).some((run) => run.phase === "unknown") && <p className="field-error" role="alert">存在结果不明的执行。断开将丢失本页跟踪信息，不代表后端已停止；重新连接也无法自动恢复该执行状态。</p>}
      <button className="button secondary full-width connection-check" disabled={state.refreshing || state.creating} onClick={() => { void onCheck(); }}>{state.refreshing ? "正在检查连接…" : "检查连接"}</button>
      <button className="button secondary full-width" disabled={busy} onClick={() => { if (onDisconnect()) onClose(); }}><Unplug size={16} />断开连接</button>
      {busy && <p className="subtle">请先等待当前操作完成。</p>}
    </div> : <form onSubmit={async (event) => {
      event.preventDefault();
      if (await onConnect()) onClose();
    }}>
      <p className="field-help">当前后端无需访问令牌。点击连接后检查运行状态；就绪后读取会话列表，不会执行模型或工具。</p>
      {state.connectionError && <p className="field-error" role="alert">{state.connectionError}</p>}
      <div className="privacy-note"><ShieldCheck size={18} /><span>仅供可信本机使用，请勿向公网或不可信网络开放。</span></div>
      <button ref={connectButton} className="button primary full-width" disabled={connecting} type="submit">{connecting ? "正在连接…" : "连接本机后端"}</button>
    </form>}
  </Dialog>;
}
