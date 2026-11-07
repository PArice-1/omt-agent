import { describe, expect, it, vi } from "vitest";
import { createOmtClient } from "@/lib/omt-api/client";
import type { OmtClient, RuntimeResponse } from "@/lib/omt-api/contracts";
import { ApiError } from "@/lib/omt-api/errors";
import { runtime, deferred } from "../../../tests/fixtures";
import { RuntimeController } from "./controller";

function setup() {
  const api = {
    ...createOmtClient(),
    getRuntime: vi.fn<OmtClient["getRuntime"]>().mockResolvedValue(runtime),
    listModels: vi.fn<OmtClient["listModels"]>().mockResolvedValue([{ provider: "deepseek", model: "deepseek-flash", current: true, available_levels: ["none", "high"] }]),
    listProviders: vi.fn<OmtClient["listProviders"]>().mockResolvedValue([{ provider: "deepseek", logged_in: false }]),
    previewLogin: vi.fn<OmtClient["previewLogin"]>().mockResolvedValue({ provider: "deepseek", login_id: "preview", models: ["deepseek-flash"], from_cache: false, expires_in: 600 }),
    confirmLogin: vi.fn<OmtClient["confirmLogin"]>().mockResolvedValue({ configuration_saved: true, runtime_ready: true, runtime, error: null }),
    changeModel: vi.fn<OmtClient["changeModel"]>(),
    changeThinking: vi.fn<OmtClient["changeThinking"]>(),
  };
  const controller = new RuntimeController(api, () => false);
  return { api, controller };
}

describe("process-wide runtime settings", () => {
  it("only reads state/catalogs during initialization and deduplicates reads", async () => {
    const { api, controller } = setup();
    const one = controller.inspect(); const two = controller.inspect();
    expect(one).toBe(two);
    await one;
    expect(api.getRuntime).toHaveBeenCalledTimes(1);
    expect(api.previewLogin).not.toHaveBeenCalled();
    expect(controller.getSnapshot().runtime).toEqual(runtime);
  });
  it("previews a key, then explicitly saves and enables the selected model", async () => {
    const { api, controller } = setup();
    await controller.inspect();
    const preview = await controller.preview("deepseek", "mock-key-only");
    expect(preview?.login_id).toBe("preview");
    expect(api.confirmLogin).not.toHaveBeenCalled();
    await controller.confirm("preview", "deepseek-flash");
    expect(api.previewLogin).toHaveBeenCalledWith("deepseek", "mock-key-only");
    expect(api.confirmLogin).toHaveBeenCalledWith("preview", "deepseek-flash");
    expect(controller.getSnapshot().message).toBe("配置已保存，运行实例已启用。");
    expect(JSON.stringify(controller.getSnapshot())).not.toContain("mock-key-only");
  });
  it.each([false, true])("distinguishes saved configuration from failed activation (old instance ready=%s)", async (ready) => {
    const { api, controller } = setup();
    await controller.inspect();
    const current = { ...runtime, ready, thinking: ready ? runtime.thinking : null };
    api.getRuntime.mockResolvedValue(current);
    api.confirmLogin.mockResolvedValue({ configuration_saved: true, runtime_ready: ready, runtime: current, error: { code: "model_change_failed", message: "启用失败" } });
    const result = await controller.confirm("preview", "new-model");
    expect(result?.configuration_saved).toBe(true);
    expect(controller.getSnapshot().message).toContain("配置已保存，但启用失败");
    expect(controller.getSnapshot().runtime).toEqual(current);
    expect(api.confirmLogin).toHaveBeenCalledTimes(1);
  });
  it("keeps the active model while a switch is pending and uses the returned fallback effort", async () => {
    const { api, controller } = setup();
    await controller.inspect();
    const pending = deferred<RuntimeResponse>();
    api.changeModel.mockReturnValue(pending.promise);
    const switching = controller.changeModel("other-provider", "other-model");
    expect(controller.getSnapshot().pending).toBe("model");
    expect(controller.getSnapshot().runtime).toEqual(runtime);
    expect(await controller.changeThinking("high")).toBe(false);
    const next = { ...runtime, thinking: { provider: "other-provider", model: "other-model", level: "high", reasoning_effort: "none", available_levels: ["none"] } };
    pending.resolve(next);
    expect(await switching).toBe(true);
    expect(controller.getSnapshot().runtime).toEqual(next);
    expect(api.confirmLogin).not.toHaveBeenCalled();
  });
  it.each(["manager_busy", "model_change_failed"])("retains active settings on %s without retries", async (code) => {
    const { api, controller } = setup();
    await controller.inspect();
    api.changeModel.mockRejectedValue(new ApiError(409, code, "无法切换"));
    expect(await controller.changeModel("deepseek", "new")).toBe(false);
    expect(controller.getSnapshot().runtime).toEqual(runtime);
    expect(controller.getSnapshot().error).toContain("未将请求的选择标为生效");
    expect(api.changeModel).toHaveBeenCalledTimes(1);
  });
  it("changes thinking without rewriting saved configuration", async () => {
    const { api, controller } = setup();
    await controller.inspect();
    const next = { ...runtime, thinking: { provider: "deepseek", model: "deepseek-flash", level: "high", reasoning_effort: "high", available_levels: ["none", "high"] } };
    api.changeThinking.mockResolvedValue(next);
    expect(await controller.changeThinking("high")).toBe(true);
    expect(api.changeThinking).toHaveBeenCalledWith("high");
    expect(api.confirmLogin).not.toHaveBeenCalled();
  });
  it.each([{ ...runtime, busy: true }, { ...runtime, changing: true }, { ...runtime, mutable: false }])("prevents unsupported/busy mutations", async (current) => {
    const { api, controller } = setup();
    api.getRuntime.mockResolvedValue(current);
    await controller.inspect();
    expect(await controller.changeModel("p", "m")).toBe(false);
    expect(await controller.preview("p", "mock-key")).toBeNull();
    expect(api.changeModel).not.toHaveBeenCalled();
  });
});
