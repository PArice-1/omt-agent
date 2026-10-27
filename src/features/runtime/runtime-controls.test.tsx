import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Composer } from "@/features/workspace/components/composer";
import type { RuntimeState } from "./controller";
import { RuntimeControls, RuntimeFeedback } from "./runtime-controls";
import { runtime } from "../../../tests/fixtures";

const ready: RuntimeState = {
  runtime, pending: null, providers: [], models: [
    { provider: "deepseek", model: "deepseek-flash", current: true, available_levels: ["none", "high"] },
    { provider: "other", model: "deepseek-flash", current: false, available_levels: ["none", "high"] },
  ],
};

describe("composer model and thinking selectors", () => {
  it("switches by provider/model identity in the input toolbar without sending or clearing a draft", async () => {
    const user = userEvent.setup();
    const onModel = vi.fn(); const onThinking = vi.fn(); const onSend = vi.fn();
    render(<Composer value="尚未发送的草稿" onChange={() => {}} disabled={false} sending={false} hint="测试"
      onSend={onSend} controls={<RuntimeControls state={ready} busy={false} onModel={onModel} onThinking={onThinking} />} />);
    const input = screen.getByRole("textbox", { name: "消息" });
    const model = screen.getByLabelText("当前模型（本地目录）");
    const thinking = screen.getByLabelText("请求思考等级");
    expect(input.closest("form")).toContainElement(model);
    expect(input.closest("form")).toContainElement(thinking);
    await user.selectOptions(model, JSON.stringify(["other", "deepseek-flash"]));
    await user.selectOptions(thinking, "high");
    expect(onModel).toHaveBeenCalledWith("other", "deepseek-flash");
    expect(onThinking).toHaveBeenCalledWith("high");
    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("尚未发送的草稿");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it.each([
    { state: ready, busy: true },
    { state: { ...ready, pending: "model" } satisfies RuntimeState, busy: false },
    { state: { ...ready, pending: "thinking" } satisfies RuntimeState, busy: false },
    { state: { ...ready, runtime: { ...runtime, busy: true } }, busy: false },
    { state: { ...ready, runtime: { ...runtime, changing: true } }, busy: false },
    { state: { ...ready, runtime: { ...runtime, mutable: false } }, busy: false },
    { state: { ...ready, runtime: { ...runtime, ready: false, thinking: null } }, busy: false },
  ])("locks unsupported or pending changes without displaying an optimistic model", ({ state, busy }) => {
    render(<RuntimeControls state={state} busy={busy} onModel={vi.fn()} onThinking={vi.fn()} />);
    expect(screen.getByLabelText("当前模型（本地目录）")).toBeDisabled();
    expect(screen.getByLabelText("请求思考等级")).toBeDisabled();
    if (state.runtime?.thinking) expect(screen.getByLabelText("当前模型（本地目录）")).toHaveValue(JSON.stringify(["deepseek", "deepseek-flash"]));
  });
  it("retains an absent current model and requested level while exposing the actual fallback", () => {
    const current: RuntimeState = { ...ready, models: [], runtime: {
      ...runtime, thinking: { provider: "deepseek", model: "not-in-directory", level: "high", reasoning_effort: "none", available_levels: ["none"] },
    } };
    render(<><RuntimeControls state={current} busy={false} onModel={vi.fn()} onThinking={vi.fn()} /><RuntimeFeedback state={current} /></>);
    expect(screen.getByLabelText("当前模型（本地目录）")).toHaveValue(JSON.stringify(["deepseek", "not-in-directory"]));
    expect(screen.getByLabelText("请求思考等级")).toHaveValue("high");
    expect(screen.getByText(/实际 effort：none/)).toHaveTextContent("全局临时设置 · 重启恢复默认");
    expect(screen.getByText(/已回退：当前模型实际不启用 reasoning/)).toBeInTheDocument();
  });
  it("keeps pending and failed feedback beside the composer rather than requiring a settings dialog", () => {
    const { rerender } = render(<RuntimeFeedback state={{ ...ready, pending: "model" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("正在切换，原生效设置保持不变");
    rerender(<RuntimeFeedback state={{ ...ready, error: "后端忙碌，未切换" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("后端忙碌，未切换");
  });
});
