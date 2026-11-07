import { z } from "zod";
import { thinkingSchema } from "./schemas";

export const eventEnvelopeSchema = z.object({
  version: z.literal(1), seq: z.number().int().positive(), type: z.string(),
  session_id: z.string().min(1), run_id: z.string().min(1),
  message_id: z.string().min(1).optional(), tool_call_id: z.string().min(1).optional(),
  role: z.enum(["assistant", "tool"]).optional(), data: z.record(z.string(), z.unknown()),
});
const base = eventEnvelopeSchema.omit({ type: true, data: true });
const assistant = base.extend({ message_id: z.string().min(1), role: z.literal("assistant") });
const tool = base.extend({ tool_call_id: z.string().min(1), role: z.literal("tool") });
const failure = z.object({ code: z.string(), message: z.string() });
export const runEventSchema = z.discriminatedUnion("type", [
  base.extend({ type: z.literal("run.started"), data: z.object({ thinking: thinkingSchema.nullable() }) }),
  assistant.extend({ type: z.literal("assistant.started"), data: z.object({}) }),
  assistant.extend({ type: z.literal("assistant.text.delta"), data: z.object({ delta: z.string() }) }),
  assistant.extend({ type: z.literal("assistant.reasoning.delta"), data: z.object({ delta: z.string() }) }),
  assistant.extend({ type: z.literal("assistant.completed"), data: z.object({}) }),
  tool.extend({ type: z.literal("tool.started"), data: z.object({ name: z.string(), input: z.json() }) }),
  tool.extend({ type: z.literal("tool.delta"), data: z.object({ name: z.string(), delta: z.json() }) }),
  tool.extend({ type: z.literal("tool.completed"), data: z.union([
    z.object({ name: z.string(), text: z.string(), status: z.literal("success") }),
    z.object({ name: z.string(), output: z.json() }),
  ]) }),
  tool.extend({ type: z.literal("tool.failed"), data: z.union([
    z.object({ name: z.string(), text: z.string(), status: z.literal("error") }),
    z.object({ name: z.string(), code: z.literal("tool_failed"), message: z.string() }),
  ]) }),
  base.extend({ type: z.literal("run.completed"), data: z.object({ status: z.literal("completed"), answer: z.string(), warnings: z.array(z.string()) }) }),
  base.extend({ type: z.literal("run.failed"), data: failure }),
  base.extend({ type: z.literal("run.cancelled"), data: failure.extend({ code: z.literal("run_cancelled") }) }),
]);
export type RunEvent = z.infer<typeof runEventSchema>;
export type TerminalEvent = Extract<RunEvent, { type: "run.completed" | "run.failed" | "run.cancelled" }>;
export const knownEventTypes: ReadonlySet<string> = new Set(runEventSchema.options.map((option) => option.shape.type.value));
export function isTerminal(event: RunEvent): event is TerminalEvent {
  return event.type === "run.completed" || event.type === "run.failed" || event.type === "run.cancelled";
}
