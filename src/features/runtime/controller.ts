import type { LoginConfirmation, LoginPreview, ModelsResponse, OmtClient, ProvidersResponse, RuntimeResponse } from "@/lib/omt-api/contracts";
import { errorMessage } from "@/lib/omt-api/errors";

export interface RuntimeState {
  runtime: RuntimeResponse | null;
  models: ModelsResponse;
  providers: ProvidersResponse;
  pending: "inspect" | "preview" | "confirm" | "model" | "thinking" | null;
  error?: string;
  message?: string;
}

/** Process-wide settings, deliberately independent of the selected session. */
export class RuntimeController {
  private state: RuntimeState = { runtime: null, models: [], providers: [], pending: null };
  private listeners = new Set<() => void>();
  private inspection: Promise<RuntimeResponse | null> | undefined;
  constructor(private api: OmtClient, private locallyBusy: () => boolean) {}
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private patch(patch: Partial<RuntimeState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }
  inspect = (): Promise<RuntimeResponse | null> => {
    if (this.inspection) return this.inspection;
    if (this.state.pending) return Promise.resolve(this.state.runtime);
    this.patch({ pending: "inspect", error: undefined });
    this.inspection = (async () => {
      const [runtime, models, providers] = await Promise.allSettled([
        this.api.getRuntime(), this.api.listModels(), this.api.listProviders(),
      ]);
      this.patch({
        ...(runtime.status === "fulfilled" ? { runtime: runtime.value } : {}),
        ...(models.status === "fulfilled" ? { models: models.value } : {}),
        ...(providers.status === "fulfilled" ? { providers: providers.value } : {}),
        error: [runtime, models, providers].some((result) => result.status === "rejected")
          ? "运行状态或本地目录读取失败，请手动重新检查。" : undefined,
        pending: null,
      });
      return runtime.status === "fulfilled" ? runtime.value : null;
    })().finally(() => { this.inspection = undefined; });
    return this.inspection;
  };
  private canMutate() {
    const runtime = this.state.runtime;
    return runtime?.mutable && !runtime.busy && !runtime.changing && !this.state.pending && !this.locallyBusy();
  }
  preview = async (provider: string, apiKey?: string): Promise<LoginPreview | null> => {
    if (!this.canMutate()) return null;
    this.patch({ pending: "preview", error: undefined, message: undefined });
    try { return await this.api.previewLogin(provider, apiKey); }
    catch (error) { this.patch({ error: errorMessage(error) }); return null; }
    finally { this.patch({ pending: null }); }
  };
  confirm = async (loginId: string, model: string): Promise<LoginConfirmation | null> => {
    if (!this.canMutate()) return null;
    this.patch({ pending: "confirm", error: undefined, message: undefined });
    try {
      const result = await this.api.confirmLogin(loginId, model);
      this.patch({ runtime: result.runtime, message: result.configuration_saved
        ? result.error ? `配置已保存，但启用失败：${result.error.message} 当前生效设置以运行状态为准。`
          : result.runtime_ready ? "配置已保存，运行实例已启用。" : "配置已保存，但运行实例尚未就绪。"
        : "配置未保存，请检查运行状态。" });
      return result;
    } catch (error) { this.patch({ error: `${errorMessage(error)} 保存可能存在部分写入，请重新检查配置，不要自动重试。` }); return null; }
    finally {
      this.patch({ pending: null });
      // Only reads: a consumed preview must never be confirmed a second time.
      await this.inspect();
    }
  };
  changeModel = (provider: string, model: string) => this.change("model", () => this.api.changeModel(provider, model));
  changeThinking = (level: string) => this.change("thinking", () => this.api.changeThinking(level));
  private async change(pending: "model" | "thinking", operation: () => Promise<RuntimeResponse>): Promise<boolean> {
    if (!this.canMutate() || !this.state.runtime?.ready) return false;
    this.patch({ pending, error: undefined, message: undefined });
    try {
      const runtime = await operation();
      this.patch({ runtime, message: "临时运行设置已更新；重启后恢复磁盘默认。" });
      return true;
    } catch (error) {
      this.patch({ error: `${errorMessage(error)} 未将请求的选择标为生效，可重新检查运行状态。` });
      return false;
    } finally { this.patch({ pending: null }); }
  }
}
