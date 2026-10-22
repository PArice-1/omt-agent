import { z } from "zod";
import { ApiError } from "./errors";
import { errorSchema } from "./schemas";

export interface TransportOptions {
  baseUrl?: string;
  getToken: () => string;
  fetcher?: typeof fetch;
}

export function createTransport({ baseUrl = "/api/omt", getToken, fetcher = fetch }: TransportOptions) {
  const base = baseUrl.replace(/\/+$/, "");
  return async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    init: RequestInit = {},
    authenticated = true,
  ): Promise<T> {
    const headers = new Headers({ Accept: "application/json" });
    if (authenticated) headers.set("Authorization", `Bearer ${getToken()}`);
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    // No automatic retries or short timeout: POST may already have tool side effects.
    const response = await fetcher(`${base}${path}`, { ...init, headers, cache: "no-store" });
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new ApiError(response.status, "invalid_response", "服务或代理返回了无法解析的响应。");
    }
    if (!response.ok) {
      const parsed = errorSchema.safeParse(body);
      if (parsed.success) {
        const error = parsed.data.error;
        throw new ApiError(response.status, error.code, error.message, error.run_id);
      }
      throw new ApiError(response.status, "unexpected_response", "服务或代理返回了异常响应。");
    }
    const parsed = schema.safeParse(body);
    if (!parsed.success) throw new ApiError(response.status, "invalid_response", "响应格式与接口契约不一致。");
    return parsed.data;
  };
}
