"use client";
import { useRef } from "react";
import { ArrowUp, LoaderCircle } from "lucide-react";
import { validateMessage } from "../model/format";

interface Props {
  value: string;
  onChange(value: string): void;
  onSend(): void;
  disabled: boolean;
  sending: boolean;
  hint: string;
}
export function Composer({ value, onChange, onSend, disabled, sending, hint }: Props) {
  const composing = useRef(false);
  const validation = value ? validateMessage(value) : null;
  return <div className="composer-region">
    <form className={`composer ${disabled ? "is-disabled" : ""}`} onSubmit={(event) => { event.preventDefault(); if (!disabled && !validateMessage(value)) onSend(); }}>
      <textarea aria-label="消息" rows={3} value={value} placeholder={disabled ? hint : "写下你的想法，剩下的交给 OMT…"} disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing) { event.preventDefault(); if (!disabled && !validateMessage(value)) onSend(); } }} />
      <div className="composer-bottom"><span>{value && validation ? validation : "Enter 发送 · Shift + Enter 换行"}</span>
        <button className="send-button" type="submit" aria-label="发送消息" disabled={disabled || Boolean(validateMessage(value))}>{sending ? <LoaderCircle size={19} className="spin" /> : <ArrowUp size={21} />}</button>
      </div>
    </form>
    <p className="composer-disclaimer"><span className="tiny-dot" />{hint} <span className="disclaimer-separator">·</span> 刷新或断开页面不会停止后端执行</p>
  </div>;
}
