"use client";
import { memo, useId } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bot, ChevronDown, LoaderCircle, Terminal, User } from "lucide-react";
import type { MessageResponse } from "@/lib/omt-api/contracts";
import type { RunState } from "../model/types";
import { useMessageScroll } from "../hooks/use-message-scroll";
import { ThinkingSummary } from "@/features/runtime/runtime-settings";

const Markdown = memo(function Markdown({ text }: { text: string }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
    a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
    img: ({ alt }) => <span className="external-image">[外部图片：{alt || "未命名"}，未自动加载]</span>,
  }}>{text}</ReactMarkdown></div>;
});

function Reasoning({ text }: { text?: string }) {
  return text ? <details className="tool-card reasoning-card"><summary><span>独立 reasoning · 思考过程</span><ChevronDown size={14} /></summary><div className="tool-detail"><pre>{text}</pre></div></details> : null;
}
function printable(value: unknown) { return typeof value === "string" ? value : JSON.stringify(value, null, 2); }

export function Messages({ messages, run }: { messages: MessageResponse[]; run?: RunState }) {
  const prefix = useId();
  const { root, content, onScroll } = useMessageScroll(messages, run);
  const targets = new Map<string, string>();
  messages.forEach((message, index) => message.tool_calls.forEach((call, callIndex) => {
    if (call.id && !targets.has(call.id)) targets.set(call.id, `${prefix}-call-${index}-${callIndex}`);
  }));
  const provisional = run?.message !== undefined && !["idle", "rejected"].includes(run.phase);
  return <div className="message-scroll" ref={root} onScroll={onScroll}>
    <div className="message-content" ref={content}>
      {messages.map((message, index) => <article key={index} className={`message message-${message.role}`}>
        <div className="message-avatar" aria-hidden="true">{message.role === "user" ? <User size={17} /> : message.role === "tool" ? <Terminal size={16} /> : <Bot size={18} />}</div>
        <div className="message-body"><div className="message-author">{message.role === "user" ? "你" : message.role === "tool" ? message.name || "工具结果" : "OMT"}{message.role === "tool" && message.status && <span className={`tool-status ${message.status}`}>{message.status === "success" ? "工具返回成功" : "工具返回错误"}</span>}</div>
          {message.role === "assistant" && <Reasoning text={message.reasoning} />}
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
      {run?.thinking !== undefined && <div className="run-snapshot"><strong>本轮运行快照</strong><ThinkingSummary thinking={run.thinking} /></div>}
      {run?.items?.map((item) => item.kind === "assistant" ? <article key={`assistant:${item.id}`} className="message message-assistant" data-message-id={item.id}>
        <div className="message-avatar"><Bot size={18} /></div><div className="message-body"><div className="message-author">OMT <span className="provisional-label">{!item.completed && run.receiving ? "正在生成" : "本轮输出"}</span></div><Reasoning text={item.reasoning} />{item.text && <Markdown text={item.text} />}</div>
      </article> : <article key={`tool:${item.id}`} className="message message-tool" data-tool-call-id={item.id}>
        <div className="message-avatar"><Terminal size={16} /></div><div className="message-body"><div className="message-author">{item.name}<span className={`tool-status ${item.status === "error" ? "error" : ""}`}>{item.status === "success" ? "工具返回成功" : item.status === "error" ? "工具返回错误" : run.receiving ? "执行中" : "未收到工具终态"}</span></div>
          <details className="tool-card"><summary><Terminal size={14} /><span>查看调用与输出</span><ChevronDown size={14} /></summary><div className="tool-detail"><p className="subtle">调用 ID：{item.id}</p>
            {item.input !== undefined && <><strong>输入</strong><pre>{printable(item.input)}</pre></>}
            {item.deltas.map((delta, index) => <pre key={index}>{printable(delta)}</pre>)}
            {item.result !== undefined && <><strong>输出</strong><pre>{printable(item.result)}</pre></>}
          </div></details>
        </div>
      </article>)}
      {run?.receiving && <div className="execution-wait" role="status"><span className="waiting-orbit"><LoaderCircle size={18} className="spin" /></span><div><strong>{run.stopping ? "已停止接收 / 正在终止" : "OMT 正在执行"}</strong><p>{run.stopping ? "不保证工具已经停止或副作用已回滚。" : "正在增量接收正文、reasoning 和工具状态，等待运行终态。"}</p></div></div>}
      {run?.phase === "completed" && !run.items?.length && run.answer !== undefined && <article className="message message-assistant"><div className="message-avatar"><Bot size={18} /></div><div className="message-body"><div className="message-author">OMT <span className="provisional-label">正在同步历史</span></div>{run.answer ? <Markdown text={run.answer} /> : <p className="subtle">本轮回答为空，请查看完整历史。</p>}</div></article>}
    </div>
  </div>;
}
