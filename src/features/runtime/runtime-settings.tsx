"use client";
import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import type { LoginPreview, ThinkingResponse } from "@/lib/omt-api/contracts";
import type { RuntimeController, RuntimeState } from "./controller";

export function ThinkingSummary({ thinking }: { thinking: ThinkingResponse | null }) {
  if (!thinking) return <span>运行配置不可用（固定运行实例可能不提供配置）</span>;
  return <span>{thinking.provider} / {thinking.model} · 请求 {thinking.level} · 实际 {thinking.reasoning_effort}
    {thinking.level !== "none" && thinking.reasoning_effort === "none" ? <strong className="runtime-fallback">（已回退：当前模型实际不启用 reasoning）</strong>
      : thinking.level !== thinking.reasoning_effort && <span>（请求等级经模型映射，以实际 effort 为准）</span>}</span>;
}

export function RuntimeSettings({ state, controller, busy, onClose, onConfigured }: {
  state: RuntimeState; controller: RuntimeController; busy: boolean; onClose(): void; onConfigured(): void;
}) {
  const [provider, setProvider] = useState("");
  const [key, setKey] = useState("");
  const [preview, setPreview] = useState<LoginPreview | null>(null);
  const [model, setModel] = useState("");
  const runtime = state.runtime;
  const blocked = busy || Boolean(state.pending) || !runtime?.mutable || runtime.busy || runtime.changing;
  const selectedProvider = provider || state.providers[0]?.provider || "";
  const savedKey = state.providers.find((item) => item.provider === selectedProvider)?.logged_in;
  return <Dialog title="添加模型与厂商配置" description="厂商凭据配置，不是账号登录。仅供可信本机使用。" onClose={onClose} busy={Boolean(state.pending && state.pending !== "inspect")}>
    <div className="runtime-status" role="status"><strong>{!runtime ? "尚未取得运行状态" : runtime.changing ? "正在切换" : runtime.busy ? `后端忙碌 · ${runtime.running} 轮运行中` : runtime.ready ? "运行实例可用" : runtime.configured ? "配置已保存，但运行实例未就绪" : "尚未配置模型"}</strong>
      <p>{runtime?.message}</p>{runtime && <p><ThinkingSummary thinking={runtime.thinking} /></p>}
    </div>
    <p className="field-help">设置作用于整个 API 进程，影响所有会话的后续运行。快捷切换不保存为重启默认值。每轮聊天以 run.started 返回的快照为准。</p>
    <button className="button secondary full-width" disabled={Boolean(state.pending)} onClick={() => { void controller.inspect(); }}>{state.pending === "inspect" ? "正在检查…" : "重新检查运行状态与本地目录"}</button>
    {runtime?.mutable && <section className="runtime-section" aria-label="厂商配置">
      <h3>厂商凭据与重启默认模型</h3>
      {!preview ? <form onSubmit={async (event) => {
        event.preventDefault();
        if (blocked || !selectedProvider || (!key && !savedKey)) return;
        const submittedKey = key || undefined;
        setKey(""); // Never retain a submitted credential in component state.
        const result = await controller.preview(selectedProvider, submittedKey);
        if (result) { setPreview(result); setModel(result.models[0] ?? ""); }
      }}>
        <label className="field-label" htmlFor="model-provider">厂商</label>
        <select id="model-provider" value={selectedProvider} disabled={blocked} onChange={(event) => { setProvider(event.target.value); setKey(""); }}>
          {!state.providers.length && <option value="">暂无注册厂商，请检查目录</option>}
          {state.providers.map((item) => <option key={item.provider} value={item.provider}>{item.provider}{item.logged_in ? "（已有本地凭据）" : ""}</option>)}
        </select>
        <label className="field-label" htmlFor="model-api-key">API Key{savedKey ? "（留空复用已保存凭据）" : ""}</label>
        <input id="model-api-key" type="password" autoComplete="off" value={key} disabled={blocked} onChange={(event) => setKey(event.target.value)} />
        <p className="field-help">仅提交给本机后端用于目录预览；此步不保存配置。提交后清空输入，不写入浏览器存储。</p>
        <button className="button secondary full-width" disabled={blocked || !selectedProvider || (!key && !savedKey)} type="submit">{state.pending === "preview" ? "正在获取预览…" : "获取模型预览"}</button>
      </form> : <div>
        <p className="field-help">{preview.provider} · {preview.from_cache ? "使用本地缓存目录" : "已查询厂商目录"} · 预览有效期 {preview.expires_in} 秒，到期需重新获取。</p>
        <label className="field-label" htmlFor="preview-model">选择要保存的默认模型</label>
        <select id="preview-model" value={model} disabled={blocked} onChange={(event) => setModel(event.target.value)}>{preview.models.map((id) => <option key={id} value={id}>{id}</option>)}</select>
        {!preview.models.length && <p className="field-help">预览没有可选模型，请重新获取或选择其他厂商。</p>}
        <p className="field-help">明确确认后才保存 Key、完整厂商目录及默认模型，并尝试启用。保存和启用分别报告结果。</p>
        <button className="button primary full-width" disabled={blocked || !model} onClick={async () => {
          const result = await controller.confirm(preview.login_id, model);
          // A saved preview is consumed even when activation fails.
          if (result?.configuration_saved) setPreview(null);
          if (result?.runtime.ready) onConfigured();
        }}>{state.pending === "confirm" ? "正在保存并启用…" : "确认保存并尝试启用"}</button>
        <button className="text-button" disabled={Boolean(state.pending)} onClick={() => setPreview(null)}>重新选择厂商 / 获取预览</button>
      </div>}
    </section>}
    {runtime && !runtime.mutable && <p className="field-help">后端使用固定运行实例，不支持配置或切换；仍可聊天。</p>}
    {busy && <p className="field-help">本页正在执行操作，结束后才能更改配置。</p>}
    {state.pending && state.pending !== "inspect" && <p role="status" className="field-help">请求处理中，以服务端返回结果为准；原生效设置保持显示。</p>}
    {state.error && <p className="field-error" role="alert">{state.error}</p>}
    {state.message && <p className="runtime-result" role="status">{state.message}</p>}
  </Dialog>;
}

