"use client";
import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
export function NewSessionDialog({ busy, error, onCreate, onClose }: { busy: boolean; error?: string; onCreate(title?: string): Promise<boolean>; onClose(): void }) {
  const [title, setTitle] = useState("");
  return <Dialog title="开始一段新会话" description="给这个想法起个名字，也可以留空，稍后直接开始。" busy={busy} onClose={onClose}>
    <form onSubmit={async (event) => { event.preventDefault(); if (await onCreate(title === "" ? undefined : title)) onClose(); }}>
      <label className="field-label" htmlFor="session-title">会话名称（可选）</label>
      <input autoFocus id="session-title" value={title} onChange={(event) => setTitle(event.target.value)} disabled={busy} placeholder="例如：梳理项目思路" />
      <p className="field-help">最多 200 个字符，创建后会立即保存到后端。</p>
      {error && <p className="field-error" role="alert">{error}</p>}
      <button className="button primary full-width" disabled={busy || Array.from(title).length > 200} type="submit">{busy ? "正在创建…" : "创建会话"}</button>
    </form>
  </Dialog>;
}
