import { describe, expect, it } from "vitest";
import type { MessageResponse } from "@/lib/omt-api/contracts";
import { usageSchema } from "@/lib/omt-api/schemas";
import { compactTokens, formatUsage, usageFromHistory, withContextWindow } from "./usage";

const messages: MessageResponse[] = [
  { role: "user", text: "查询", tool_calls: [] },
  { role: "assistant", text: "", tool_calls: [{ id: "t", name: "read", args: {} }],
    usage: { input_tokens: 20000, output_tokens: 1000, total_tokens: 21000 } },
  { role: "tool", text: "结果", tool_calls: [], tool_call_id: "t" },
  { role: "assistant", text: "完成", tool_calls: [],
    usage: { input_tokens: 25000, output_tokens: 2200, total_tokens: 27200 } },
];

describe("会话 token 与上下文展示", () => {
  it.each([[0, "0"], [100, "100"], [999, "999"], [1000, "1k"], [12500, "12.5k"],
    [999999, "1m"], [1000000, "1m"], [1250000, "1.3m"], [1000000000, "1b"]])("缩写 %s 为 %s", (value, expected) => {
    expect(compactTokens(Number(value))).toBe(expected);
  });
  it("首次连接即显示窗口，新会话不需要先发送一次请求", () => {
    const snapshot = withContextWindow(usageFromHistory([]), 272000);
    expect(formatUsage(snapshot)).toBe("0 token 0%/272k");
    expect(snapshot.context_remaining_tokens).toBe(272000);
  });
  it("恢复历史时包括纯工具请求，累计消耗不当作上下文占用", () => {
    const snapshot = withContextWindow(usageFromHistory(messages), 272000);
    expect(snapshot).toMatchObject({ input_tokens: 45000, output_tokens: 3200, total_tokens: 48200,
      context_tokens: 27200, context_used_percent: 10, context_remaining_tokens: 244800, usage_complete: true });
    expect(formatUsage(snapshot)).toBe("48.2k token 10%/272k");
    const switched = withContextWindow(snapshot, 544000);
    expect(formatUsage(switched)).toBe("48.2k token 5%/544k");
  });
  it("旧历史缺失用量显示已知下界，最后一次用量未知不沿用旧占用", () => {
    const snapshot = withContextWindow(usageFromHistory([...messages, { role: "assistant", text: "旧消息", tool_calls: [] }]), 272000);
    expect(formatUsage(snapshot)).toBe("≥48.2k token --%/272k");
    expect(snapshot.context_remaining_tokens).toBeNull();
    expect(formatUsage(withContextWindow(snapshot, null))).toBe("≥48.2k token --%/--");
  });
  it("超限保留实际百分比但剩余不为负，未知容量不猜默认值", () => {
    const snapshot = withContextWindow(usageFromHistory(messages), 13600);
    expect(snapshot.context_used_percent).toBe(200);
    expect(snapshot.context_remaining_tokens).toBe(0);
    expect(withContextWindow(snapshot, null).context_used_percent).toBeNull();
  });
  it.each([{ total_tokens: -1 }, { context_window: 0 }, { context_tokens: -2 }, { context_used_percent: "10" }])("拒绝非法统计字段 %j", (change) => {
    expect(usageSchema.safeParse({ ...usageFromHistory(messages), ...change }).success).toBe(false);
  });
});
