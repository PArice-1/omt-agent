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
  message_id: z.string().optional(),
  reasoning: z.string().optional(),
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

export const thinkingSchema = z.object({
  provider: z.string(), model: z.string(), level: z.string(),
  reasoning_effort: z.string(), available_levels: z.array(z.string()),
});
export const runtimeSchema = z.object({
  configured: z.boolean(), ready: z.boolean(), mutable: z.boolean(),
  changing: z.boolean(), busy: z.boolean(), running: z.number().int().nonnegative(),
  thinking: thinkingSchema.nullable(), message: z.string(),
});
export const providersSchema = z.array(z.object({ provider: z.string(), logged_in: z.boolean() }));
export const modelsSchema = z.array(z.object({
  provider: z.string(), model: z.string(), available_levels: z.array(z.string()), current: z.boolean(),
}));
export const previewSchema = z.object({
  login_id: z.string(), provider: z.string(), models: z.array(z.string()),
  from_cache: z.boolean(), expires_in: z.number().nonnegative(),
});
export const confirmationSchema = z.object({
  configuration_saved: z.boolean(), runtime_ready: z.boolean(), runtime: runtimeSchema,
  error: z.object({ code: z.string(), message: z.string() }).nullable(),
});
