import { ArrowUpRight, BookOpen, Code2, Lightbulb, Sparkles } from "lucide-react";
const prompts = [
  { icon: BookOpen, title: "读懂一个项目", text: "请分析当前项目的目录结构，暂时不要修改文件。" },
  { icon: Lightbulb, title: "一起梳理思路", text: "请先阅读当前项目的说明文档，帮我梳理接下来可以改进的方向。" },
  { icon: Code2, title: "解决一个问题", text: "请先了解当前项目，再和我一起定位问题；执行修改前先说明方案。" },
];
export function Welcome({ connected, hasSession, onPrompt, onConnect, onNew }: { connected: boolean; hasSession: boolean; onPrompt(text: string): void; onConnect(): void; onNew(): void }) {
  return <section className="welcome">
    <div className="welcome-symbol"><Sparkles size={35} strokeWidth={1.5} /><span className="symbol-dot" /></div>
    <span className="eyebrow">A LITTLE SPACE FOR BIG IDEAS</span>
    <h1>让想法，<span>轻盈发生。</span></h1>
    <p className="welcome-description">从一个问题开始，和 OMT 一起探索、思考、创造。<br />你的本机 Agent，简单连接，自在协作。</p>
    <div className="suggestion-grid">{prompts.map(({ icon: Icon, title, text }) => <button key={title} className="suggestion-card" onClick={() => connected ? onPrompt(text) : onConnect()}>
      <span className="suggestion-icon"><Icon size={19} /></span><span>{title}</span><ArrowUpRight size={15} /><p>{text}</p>
    </button>)}</div>
    {!connected ? <button className="welcome-link" onClick={onConnect}>连接本机后端，开始探索 <ArrowUpRight size={15} /></button> : !hasSession ? <button className="welcome-link" onClick={onNew}>先创建一个新会话 <ArrowUpRight size={15} /></button> : <p className="welcome-footnote">选择一个灵感，或在下方写下你的第一个问题。</p>}
  </section>;
}
