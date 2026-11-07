import { AlertCircle, Info, RefreshCw } from "lucide-react";
import type { HistoryState, RunState } from "../model/types";

export function RunNotice({ run, history, onInspect, onAcknowledge }: { run?: RunState; history?: HistoryState; onInspect(): void; onAcknowledge(): void }) {
  if (!run || run.phase === "idle" || run.phase === "sending") return null;
  if (run.phase === "completed") {
    if (!run.warnings?.length) return null;
    return <div className="run-notice warning-notice" role="status"><Info size={17} />
      <div><strong>运行提醒</strong>{run.warnings.map((warning, index) => <p key={index}>{warning === "session_timestamp_update_failed" ? "会话时间更新失败，但回答已生成；请勿重复发送。" : warning}</p>)}</div>
    </div>;
  }
  const unknown = run.phase === "unknown";
  return <div className={`run-notice ${unknown ? "unknown-notice" : "error-notice"}`} role="alert">
    {unknown ? <Info size={18} /> : <AlertCircle size={18} />}
    <div><strong>{unknown ? "结果未确认，请勿重复发送" : run.phase === "cancelled" ? "本轮已收到取消终态" : run.phase === "failed" ? "本轮执行失败" : run.phase === "needs_attention" ? "这个会话需要人工检查" : "本次请求未被执行"}</strong>
      <p>{run.error}</p>{unknown && <p>后端可能仍在执行，也可能已产生文件或命令副作用。可稍后读取历史并人工检查；历史可读不代表能自动确认这次请求的结果。</p>}
      {["needs_attention", "failed", "cancelled"].includes(run.phase) && <p>本轮可能已有工具副作用，不会自动重发。没有在线修复接口。请检查后端；也可以另建会话，但旧操作不会因此回滚。</p>}
      {run.runId && <span className="run-id">运行 ID：{run.runId}</span>}
      {unknown && <div className="notice-actions"><button className="text-button" onClick={onInspect} disabled={history?.status === "loading"}><RefreshCw size={14} />{history?.status === "loading" ? "正在读取…" : "读取历史，人工检查"}</button>
        {run.reviewed && history?.status === "ready" && <button className="text-button" onClick={onAcknowledge}>我已检查历史，允许继续</button>}
      </div>}
    </div>
  </div>;
}
