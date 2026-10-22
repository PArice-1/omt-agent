"use client";
import { useEffect, useId, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bot, ChevronDown, LoaderCircle, Terminal, User } from "lucide-react";
import type { MessageResponse } from "@/lib/omt-api/contracts";
import type { RunState } from "../model/types";

function Markdown({ text }: { text: string }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
    a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
    img: ({ alt }) => <span className="external-image">[外部图片：{alt || "未命名"}，未自动加载]</span>,
  }}>{text}</ReactMarkdown></div>;
}

export function Messages({ messages, run }: { messages: MessageResponse[]; run?: RunState }) {
  const prefix = useId();
  const end = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const shouldScroll = useRef(true);
  const targets = new Map<string, string>();
  messages.forEach((message, index) => message.tool_calls.forEach((call, callIndex) => {
    if (call.id && !targets.has(call.id)) targets.set(call.id, `${prefix}-call-${index}-${callIndex}`);
  }));
  useEffect(() => {
    if (shouldScroll.current) end.current?.scrollIntoView?.({ block: "end", behavior: "instant" });
  }, [messages, run]);
  const provisional = run?.message !== undefined && ["sending", "completed", "unknown"].includes(run.phase);
  return <div className="message-scroll" ref={root} onScroll={() => {
    const node = root.current;
    if (node) shouldScroll.current = node.scrollHeight - node.scrollTop - node.clientHeight < 140;
  }}>
    <div className="message-content">
      {messages.map((message, index) => <article key={index} className={`message message-${message.role}`}>
        <div className="message-avatar" aria-hidden="true">{message.role === "user" ? <User size={17} /> : message.role === "tool" ? <Terminal size={16} /> : <Bot size={18} />}</div>
        <div className="message-body"><div className="message-author">{message.role === "user" ? "你" : message.role === "tool" ? message.name || "工具结果" : "OMT"}{message.role === "tool" && message.status && <span className={`tool-status ${message.status}`}>{message.status === "success" ? "工具返回成功" : "工具返回错误"}</span>}</div>
          {message.role === "tool" ? <details className="tool-card result"><summary><Terminal size={14} /><span>查看工具结果</span><ChevronDown size={14} /></summary><div className="tool-detail">
            {message.tool_call_id && targets.has(message.tool_call_id) && <a className="tool-reference" href={`#${targets.get(message.tool_call_id)}`}>查看对应调用</a>}
            <pre>{message.text}</pre>
          </div></details> : message.text ? message.role === "user" ? <p className="user-text">{message.text}</p> : <Markdown text={message.text} /> : null}
          {message.tool_calls.map((call, callIndex) => <details key={callIndex} className="tool-card" id={`${prefix}-call-${index}-${callIndex}`}>
            <summary><Terminal size={14} /><span>{call.name}</span><span className="tool-call-caption">工具调用</span><ChevronDown size={14} /></summary>
            <div className="tool-detail"><pre>{JSON.stringify(call.args, null, 2)}</pre></div>
          </details>)}
        </div>
      </article>)}
      {provisional && <article className="message message-user provisional"><div className="message-avatar"><User size={17} /></div><div className="message-body"><div className="message-author">你 <span className="provisional-label">{run.phase === "unknown" ? "结果待确认 · 本地输入" : "本轮输入"}</span></div><p className="user-text">{run.message}</p></div></article>}
      {run?.phase === "sending" && <div className="execution-wait" role="status"><span className="waiting-orbit"><LoaderCircle size={18} className="spin" /></span><div><strong>OMT 正在执行</strong><p>等待本轮最终结果，工具记录将在完成后加载。</p></div></div>}
      {run?.phase === "completed" && run.answer !== undefined && <article className="message message-assistant"><div className="message-avatar"><Bot size={18} /></div><div className="message-body"><div className="message-author">OMT <span className="provisional-label">本轮已完成 · 等待历史同步</span></div>{run.answer ? <Markdown text={run.answer} /> : <p className="subtle">本轮回答为空，请查看完整历史。</p>}</div></article>}
      <div ref={end} />
    </div>
  </div>;
}
