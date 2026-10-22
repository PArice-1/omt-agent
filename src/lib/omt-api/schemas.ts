import { z } from "zod";

export const sessionSchema = z.object({
  session_id: z.string(),
  title: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export const toolCallSchema = z.object({
  id: z.string().optional(),
  name: z.string(),
  args: z.record(z.string(), z.unknown()),
});
export const messageSchema = z.object({
  role: z.enum(["user", "assistant", "tool"]),
  text: z.string(),
  tool_calls: z.array(toolCallSchema),
  tool_call_id: z.string().optional(),
  name: z.string().optional(),
  status: z.enum(["success", "error"]).optional(),
});
export const runSchema = z.object({
  session_id: z.string(),
  run_id: z.string(),
  status: z.literal("completed"),
  answer: z.string(),
  warnings: z.array(z.string()),
});
export const errorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string(), run_id: z.string().optional() }),
});
export const healthSchema = z.object({ status: z.literal("ok") });
export const sessionsSchema = z.array(sessionSchema);
export const messagesSchema = z.array(messageSchema);
