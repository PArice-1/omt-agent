import type { RunEvent } from "@/lib/omt-api/contracts";
import type { RunState, StreamItem } from "./types";

/** Pure projection: all calls belong to one session/run; IDs, never names, are keys. */
export function applyRunEvent(run: RunState, event: RunEvent): RunState {
  const next = { ...run, runId: event.run_id };
  const items = [...(run.items ?? [])];
  if (event.type === "run.started") return { ...next, thinking: event.data.thinking };
  if (event.type === "run.completed") {
    // The final answer belongs to the last assistant message, not a new bubble
    // and not a concatenation of earlier planning messages.
    let last = -1;
    for (let index = items.length - 1; index >= 0; index--) {
      if (items[index].kind === "assistant") { last = index; break; }
    }
    const final = items[last];
    const toolsAfter = items.slice(last + 1).some((item) => item.kind === "tool");
    if (final?.kind === "assistant" && !toolsAfter) items[last] = { ...final, text: event.data.answer, completed: true };
    else if (event.data.answer) items.push({ kind: "assistant", id: `${event.run_id}:answer`, text: event.data.answer, reasoning: "", completed: true });
    return { ...next, phase: "completed", answer: event.data.answer, warnings: event.data.warnings, items };
  }
  if (event.type === "run.failed" || event.type === "run.cancelled") return {
    ...next, phase: event.type === "run.failed" ? "failed" : "cancelled", error: `${event.data.message} (${event.data.code})`,
  };
  if (event.type === "assistant.started" || event.type === "assistant.text.delta" || event.type === "assistant.reasoning.delta" || event.type === "assistant.completed") {
    const id = event.message_id;
    const index = items.findIndex((item) => item.kind === "assistant" && item.id === id);
    const found = items[index];
    const item: Extract<StreamItem, { kind: "assistant" }> = found?.kind === "assistant" ? { ...found }
      : { kind: "assistant", id, text: "", reasoning: "", completed: false };
    if (event.type === "assistant.text.delta") item.text += event.data.delta;
    if (event.type === "assistant.reasoning.delta") item.reasoning += event.data.delta;
    if (event.type === "assistant.completed") item.completed = true;
    if (index < 0) items.push(item); else items[index] = item;
  } else {
    const id = event.tool_call_id;
    const index = items.findIndex((item) => item.kind === "tool" && item.id === id);
    const found = items[index];
    const item: Extract<StreamItem, { kind: "tool" }> = found?.kind === "tool" ? { ...found }
      : { kind: "tool", id, name: event.data.name, deltas: [], status: "running" };
    if (event.type === "tool.started") item.input = event.data.input;
    if (event.type === "tool.delta") item.deltas = [...item.deltas, event.data.delta];
    if (event.type === "tool.completed") {
      item.status = "success";
      item.result = "output" in event.data ? event.data.output : event.data.text;
    }
    if (event.type === "tool.failed") {
      item.status = "error";
      item.result = "text" in event.data ? event.data.text : { code: event.data.code, message: event.data.message };
    }
    if (index < 0) items.push(item); else items[index] = item;
  }
  return { ...next, items };
}
