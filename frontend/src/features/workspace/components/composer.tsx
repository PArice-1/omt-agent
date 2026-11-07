"use client";
import { useRef, type ReactNode } from "react";
import { ArrowUp, LoaderCircle, Square } from "lucide-react";
import { validateMessage } from "../model/format";

interface Props {
  value: string;
  onChange(value: string): void;
  onSend(): void;
  disabled: boolean;
  sending: boolean;
  stopping?: boolean;
  onStop?(): void;
  hint: string;
  controls?: ReactNode;
  settingsFeedback?: ReactNode;
}
export function Composer({ value, onChange, onSend, disabled, sending, stopping, onStop, hint, controls, settingsFeedback }: Props) {
  const composing = useRef(false);
  const validation = value ? validateMessage(value) : null;
  return <div className="composer-region">
    <form className={`composer ${disabled ? "is-disabled" : ""}`} onSubmit={(event) => { event.preventDefault(); if (!disabled && !validateMessage(value)) onSend(); }}>
      <textarea aria-label="消息" rows={3} value={value} placeholder={disabled ? hint : "写下你的想法，剩下的交给 OMT…"} disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing) { event.preventDefault(); if (!disabled && !validateMessage(value)) onSend(); } }} />
      <div className="composer-bottom"><span className={`composer-keyboard-hint ${value && validation ? "has-validation" : ""}`}>{value && validation ? validation : "Enter 发送 · Shift + Enter 换行"}</span>
        <div className="composer-actions">{controls}
        {sending ? <button className="send-button" type="button" aria-label={stopping ? "正在终止" : "停止接收"} disabled={stopping} onClick={onStop}>{stopping ? <LoaderCircle size={19} className="spin" /> : <Square size={17} />}</button>
          : <button className="send-button" type="submit" aria-label="发送消息" disabled={disabled || Boolean(validateMessage(value))}><ArrowUp size={21} /></button>}
        </div>
      </div>
    </form>
    {settingsFeedback}
    <p className="composer-disclaimer"><span className="tiny-dot" />{hint} <span className="disclaimer-separator">·</span> 停止接收后会尝试终止；不保证工具立即停止或副作用回滚</p>
  </div>;
}
