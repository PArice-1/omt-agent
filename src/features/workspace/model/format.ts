export function sessionTitle(title: string | null | undefined): string {
  return title?.trim() ? title : "新对话";
}

export function formatTimestamp(raw: string): string {
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(raw)) return raw;
  const date = new Date(raw.replace(" ", "T") + "Z");
  if (Number.isNaN(date.getTime())) return raw;
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

export function validateMessage(message: string): string | null {
  if (!message.trim()) return "请输入消息。";
  if (message.includes("\u0000")) return "消息不能包含 NUL 字符。";
  if (Array.from(message).length > 32000) return "消息不能超过 32000 个字符。";
  return null;
}
