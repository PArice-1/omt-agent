import { AlertCircle, CheckCircle2, Info, RefreshCw } from "lucide-react";
import type { HistoryState, RunState } from "../model/types";

export function RunNotice({ run, history, onInspect, onAcknowledge }: { run?: RunState; history?: HistoryState; onInspect(): void; onAcknowledge(): void }) {
  if (!run || run.phase === "idle" || run.phase === "sending") return null;
  if (run.phase === "completed") return <div className="run-notice success-notice" role="status">
    <CheckCircle2 size={17} /><div><strong>本轮已完成</strong>{run.warnings?.map((warning, index) => <p key={index}>{warning === "session_timestamp_update_failed" ? "会话时间更新失败，但本轮已成功；请勿重复发送。" : warning}</p>)}
      {run.runId && <span className="run-id">运行 ID：{run.runId}</span>}
      {history?.status === "error" && <p>执行已成功，但历史刷新失败。下方保留最终回答，重读历史不会重新执行。</p>}
    </div>
  </div>;
  const unknown = run.phase === "unknown";
  return <div className={`run-notice ${unknown ? "unknown-notice" : "error-notice"}`} role="alert">
    {unknown ? <Info size={18} /> : <AlertCircle size={18} />}
    <div><strong>{unknown ? "无法确认本轮结果，请勿重复发送" : run.phase === "needs_attention" ? "这个会话需要人工检查" : "本次请求未被执行"}</strong>
      <p>{run.error}</p>{unknown && <p>后端可能仍在执行，也可能已产生文件或命令副作用。可稍后读取历史并人工检查；历史可读不代表能自动确认这次请求的结果。</p>}
      {run.phase === "needs_attention" && <p>没有在线修复接口。请检查后端；也可以另建会话，但旧操作不会因此回滚。</p>}
      {run.runId && <span className="run-id">运行 ID：{run.runId}</span>}
      {unknown && <div className="notice-actions"><button className="text-button" onClick={onInspect} disabled={history?.status === "loading"}><RefreshCw size={14} />{history?.status === "loading" ? "正在读取…" : "读取历史，人工检查"}</button>
        {run.reviewed && history?.status === "ready" && <button className="text-button" onClick={onAcknowledge}>我已检查历史，允许继续</button>}
      </div>}
    </div>
  </div>;
}
