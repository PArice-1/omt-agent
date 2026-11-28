import type { MessageResponse, UsageSnapshot } from "@/lib/omt-api/contracts";

/** 用当前模型窗口重算占用；累计消耗不可当作上下文，未知容量不猜默认值。 */
export function withContextWindow(usage: UsageSnapshot, window: number | null): UsageSnapshot {
  const known = usage.context_tokens !== null && window !== null;
  const used = usage.context_tokens ?? 0;
  return { ...usage, context_window: window,
    context_used_percent: known ? Math.round(used / window * 10000) / 100 : null,
    context_remaining_tokens: known ? Math.max(0, window - used) : null };
}

/** 从所选会话完整历史重建用量；只计助手消息，兼容没有统计字段的旧检查点。 */
export function usageFromHistory(messages: MessageResponse[]): UsageSnapshot {
  let snapshot: UsageSnapshot = { input_tokens: 0, output_tokens: 0, total_tokens: 0,
    context_tokens: 0, context_window: null, context_used_percent: null,
    context_remaining_tokens: null, usage_complete: true };
  for (const message of messages) {
    if (message.role !== "assistant") continue;
    if (!message.usage) {
      snapshot = { ...snapshot, usage_complete: false, context_tokens: null };
    } else {
      snapshot = { ...snapshot,
        input_tokens: snapshot.input_tokens + message.usage.input_tokens,
        output_tokens: snapshot.output_tokens + message.usage.output_tokens,
        total_tokens: snapshot.total_tokens + message.usage.total_tokens,
        context_tokens: message.usage.input_tokens + message.usage.output_tokens };
    }
  }
  return snapshot;
}

/** 十进制 k/m/b，最多一位小数；舍入到 1000 时提升单位，避免 1000k。 */
export function compactTokens(value: number): string {
  for (const [scale, suffix] of [[1e9, "b"], [1e6, "m"], [1e3, "k"]] as const) {
    if (value >= scale || (scale > 1e3 && Math.round(value / (scale / 1e3) * 10) / 10 >= 1000)) {
      return `${Math.round(value / scale * 10) / 10}${suffix}`;
    }
  }
  return String(value);
}

/** 输入框下方的紧凑显示；百分比是已使用比例，≥ 是不完整累计的已知下界。 */
export function formatUsage(usage: UsageSnapshot): string {
  const tokens = `${usage.usage_complete ? "" : "≥"}${compactTokens(usage.total_tokens)} token`;
  const percent = usage.context_used_percent === null ? "--" : Math.round(usage.context_used_percent);
  const window = usage.context_window === null ? "--" : compactTokens(usage.context_window);
  return `${tokens} ${percent}%/${window}`;
}
