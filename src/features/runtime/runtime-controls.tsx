"use client";
import { ChevronDown, LoaderCircle } from "lucide-react";
import type { RuntimeState } from "./controller";

interface Props {
  state: RuntimeState;
  busy: boolean;
  onModel(provider: string, model: string): void;
  onThinking(level: string): void;
}
const levelLabel = (level: string) => ({ none: "None", low: "Low", high: "High", max: "Max" })[level] ?? level;

/** Compact, keyboard-native selectors composed into the message input toolbar. */
export function RuntimeControls({ state, busy, onModel, onThinking }: Props) {
  const runtime = state.runtime;
  const thinking = runtime?.thinking;
  const blocked = busy || Boolean(state.pending) || !runtime?.ready || !runtime.mutable || runtime.busy || runtime.changing;
  const value = JSON.stringify([thinking?.provider, thinking?.model]);
  const currentInDirectory = state.models.some((item) => item.provider === thinking?.provider && item.model === thinking?.model);
  const placeholder = !runtime ? "检查模型中" : !runtime.ready ? runtime.configured ? "模型未就绪" : "未配置模型" : "固定运行实例";
  return <div className="runtime-controls" role="group" aria-label="模型与思考强度" title="作用于整个 API 进程的临时设置，影响所有会话；重启恢复磁盘默认。">
    {state.pending && <LoaderCircle size={13} className="spin runtime-switching" aria-label="正在更新运行设置" />}
    <label className="runtime-select runtime-model-select" title={thinking ? `${thinking.provider} / ${thinking.model}` : placeholder}>
      <select aria-label="当前模型（本地目录）" disabled={blocked || !state.models.length} value={value} onChange={(event) => {
        const selected = state.models.find((item) => JSON.stringify([item.provider, item.model]) === event.target.value);
        if (selected) onModel(selected.provider, selected.model);
      }}>
        {!currentInDirectory && <option value={value}>{thinking ? `${thinking.provider} / ${thinking.model}` : placeholder}</option>}
        {state.models.map((item) => <option key={JSON.stringify([item.provider, item.model])} value={JSON.stringify([item.provider, item.model])}>{item.provider} / {item.model}</option>)}
      </select><ChevronDown size={13} aria-hidden="true" />
    </label>
    <label className="runtime-select runtime-thinking-select" title={thinking ? `请求思考等级：${thinking.level}；实际 reasoning_effort：${thinking.reasoning_effort}` : "思考强度不可用"}>
      <select aria-label="请求思考等级" disabled={blocked || !thinking} value={thinking?.level ?? ""} onChange={(event) => onThinking(event.target.value)}>
        {!thinking && <option value="">思考强度</option>}
        {thinking && !thinking.available_levels.includes(thinking.level) && <option value={thinking.level}>{levelLabel(thinking.level)}（已回退）</option>}
        {thinking?.available_levels.map((level) => <option key={level} value={level}>{levelLabel(level)}</option>)}
      </select><ChevronDown size={13} aria-hidden="true" />
    </label>
  </div>;
}

export function RuntimeFeedback({ state }: { state: RuntimeState }) {
  const runtime = state.runtime;
  const thinking = runtime?.thinking;
  const fallback = thinking && thinking.level !== "none" && thinking.reasoning_effort === "none";
  const status = state.pending === "model" || state.pending === "thinking" ? "正在切换，原生效设置保持不变…"
    : runtime?.changing ? "后端正在切换运行设置。" : runtime?.busy ? "后端忙碌，结束后可在左侧模型配置中重新检查。"
      : !runtime ? "运行状态待检查，请从左侧模型配置重新检查。"
        : !runtime.ready ? runtime.configured ? "配置已保存，但运行实例未就绪。请查看左侧模型配置。" : "首次使用，请从左侧「添加模型」配置厂商凭据。" : null;
  return <div className="composer-runtime-feedback">
    <span className="runtime-scope-note">全局临时设置 · 重启恢复默认{thinking ? ` · 实际 effort：${thinking.reasoning_effort}` : ""}</span>
    {status && <p role="status">{status}</p>}
    {fallback && <p className="runtime-fallback" role="status">请求 {thinking.level}，实际 none；已回退：当前模型实际不启用 reasoning。</p>}
    {state.error && <p className="field-error" role="alert">{state.error}</p>}
  </div>;
}
