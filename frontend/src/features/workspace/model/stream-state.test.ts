import { describe, expect, it } from "vitest";
import type { RunEvent } from "@/lib/omt-api/contracts";
import { applyRunEvent } from "./stream-state";
import type { RunState } from "./types";
import { runEvents, terminal } from "../../../../tests/fixtures";

const common = { session_id: "session-a", run_id: "run-1" } as const;
export const interleaved: RunEvent[] = [
  ...runEvents().slice(0, 2),
  { ...common, seq: 3, type: "assistant.reasoning.delta", message_id: "m1", role: "assistant", data: { delta: "独立思考" } },
  { ...common, seq: 4, type: "assistant.text.delta", message_id: "m1", role: "assistant", data: { delta: "先查资料" } },
  { ...common, seq: 5, type: "assistant.completed", message_id: "m1", role: "assistant", data: {} },
  { ...common, seq: 6, type: "tool.started", tool_call_id: "t1", role: "tool", data: { name: "read", input: { file: "one" } } },
  { ...common, seq: 7, type: "tool.started", tool_call_id: "t2", role: "tool", data: { name: "read", input: { file: "two" } } },
  { ...common, seq: 8, type: "tool.delta", tool_call_id: "t2", role: "tool", data: { name: "read", delta: { progress: 50 } } },
  { ...common, seq: 9, type: "tool.failed", tool_call_id: "t2", role: "tool", data: { name: "read", code: "tool_failed", message: "读取失败" } },
  { ...common, seq: 10, type: "tool.completed", tool_call_id: "t1", role: "tool", data: { name: "read", output: { rows: [1, 2] } } },
  { ...common, seq: 11, type: "assistant.started", message_id: "m2", role: "assistant", data: {} },
  { ...common, seq: 12, type: "assistant.text.delta", message_id: "m2", role: "assistant", data: { delta: "不完整答案" } },
  { ...terminal, seq: 13 },
];
const initial: RunState = { phase: "sending", message: "问题", items: [], receiving: true };

describe("run event projection", () => {
  it("separates assistant messages/reasoning and parallel tools sharing a name", () => {
    const before = interleaved.slice(0, 10).reduce(applyRunEvent, initial);
    expect(before.phase).toBe("sending"); // assistant.completed/tool.failed cannot complete a run
    expect(before.items).toEqual([
      { kind: "assistant", id: "m1", text: "先查资料", reasoning: "独立思考", completed: true },
      { kind: "tool", id: "t1", name: "read", input: { file: "one" }, deltas: [], result: { rows: [1, 2] }, status: "success" },
      { kind: "tool", id: "t2", name: "read", input: { file: "two" }, deltas: [{ progress: 50 }], result: { code: "tool_failed", message: "读取失败" }, status: "error" },
    ]);
    const final = interleaved.reduce(applyRunEvent, initial);
    expect(final.phase).toBe("completed"); // tool failure can be recovered by the model
    expect(final.items).toHaveLength(4);
    expect(final.items?.[3]).toMatchObject({ id: "m2", text: "分析完成", reasoning: "" });
    expect(initial.items).toEqual([]);
  });
  it("does not overwrite a planning message when the final answer has no deltas", () => {
    const result = [...interleaved.slice(0, 10), { ...terminal, seq: 11 }].reduce(applyRunEvent, initial);
    expect(result.items).toHaveLength(4);
    expect(result.items?.[0]).toMatchObject({ text: "先查资料" });
    expect(result.items?.[3]).toMatchObject({ text: "分析完成" });
  });
  it("accepts text/status tool results and preserves process information on terminal failure", () => {
    const list: RunEvent[] = [
      { ...common, seq: 1, type: "tool.completed", tool_call_id: "t", role: "tool", data: { name: "bash", text: "exit 1", status: "success" } },
      { ...common, seq: 2, type: "tool.failed", tool_call_id: "t2", role: "tool", data: { name: "bash", text: "error output", status: "error" } },
      { ...common, seq: 3, type: "run.failed", data: { code: "run_failed", message: "执行失败" } },
    ];
    const result = list.reduce(applyRunEvent, initial);
    expect(result.phase).toBe("failed");
    expect(result.items?.[0]).toMatchObject({ result: "exit 1", status: "success" });
    expect(result.items?.[1]).toMatchObject({ result: "error output", status: "error" });
  });
});
