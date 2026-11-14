import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { Workspace } from "./workspace";
import { WorkspaceController } from "./model/controller";
import { createOmtClient } from "@/lib/omt-api/client";
import { completedRun, sseResponse, runtime, history, sessionA, frame, runEvents, terminal } from "../../../tests/fixtures";

const base = "http://localhost/api/omt";
const server = setupServer();
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
});
beforeEach(() => server.use(
  http.get(base + "/runtime", () => HttpResponse.json(runtime)),
  http.get(base + "/models", () => HttpResponse.json([])),
  http.get(base + "/providers", () => HttpResponse.json([])),
));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

async function connect(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "未连接" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).queryByLabelText("访问令牌")).not.toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "连接本机后端" })).toBeEnabled();
  expect(within(dialog).getByRole("button", { name: "连接本机后端" })).toHaveFocus();
  await user.click(within(dialog).getByRole("button", { name: "连接本机后端" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}
function renderWorkspace() {
  const controller = new WorkspaceController(() => createOmtClient({ baseUrl: base }));
  render(<StrictMode><Workspace controller={controller} /></StrictMode>);
  return controller;
}

describe("workspace user flows with the real API client", () => {
  it("only probes runtime/catalogs on mount, waiting for explicit connection before reading sessions", async () => {
    const user = userEvent.setup();
    let reads = 0;
    let posts = 0;
    server.use(
      http.get(base + "/sessions", () => { reads += 1; return HttpResponse.json([]); }),
      http.post(base + "/*", () => { posts += 1; return HttpResponse.json({}); }),
    );
    const controller = renderWorkspace();
    expect(controller.getSnapshot().connection).toBe("disconnected");
    expect(screen.getByRole("textbox", { name: "消息" })).toBeDisabled();
    expect(reads).toBe(0);
    expect(posts).toBe(0);
    await user.click(screen.getByRole("button", { name: "未连接" }));
    expect(reads).toBe(0);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "连接本机后端" }));
    await waitFor(() => expect(controller.getSnapshot().connection).toBe("connected"));
    expect(reads).toBe(1);
    expect(posts).toBe(0);
  });

  it("connects, creates a session, sends and replaces the full history without duplicate answers", async () => {
    const user = userEvent.setup();
    let created = false;
    let completed = false;
    let runs = 0;
    server.use(
      http.get(base + "/sessions", ({ request }) => {
        expect(request.headers.has("Authorization")).toBe(false);
        return HttpResponse.json(created ? [sessionA] : []);
      }),
      http.post(base + "/sessions", async ({ request }) => {
        expect(await request.json()).toEqual({ title: "项目分析" });
        created = true;
        return HttpResponse.json(sessionA, { status: 201 });
      }),
      http.get(base + "/sessions/session-a/messages", () => HttpResponse.json(completed ? history : [])),
      http.post(base + "/sessions/session-a/runs/stream", async ({ request }) => {
        expect(await request.json()).toEqual({ message: "分析项目" });
        runs += 1; completed = true;
        return sseResponse();
      }),
    );
    renderWorkspace();
    expect(screen.getByRole("heading", { name: "让想法，轻盈发生。" })).toBeInTheDocument();
    await connect(user);
    await user.click(screen.getByRole("button", { name: /新建会话/ }));
    await user.type(screen.getByLabelText("会话名称（可选）"), "项目分析");
    await user.click(screen.getByRole("button", { name: "创建会话" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "分析项目");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await waitFor(() => expect(screen.getByText("分析完成")).toBeInTheDocument());
    expect(screen.getAllByText("分析完成")).toHaveLength(1);
    expect(screen.getByText("工具调用")).toBeInTheDocument();
    expect(screen.getByText("查看工具结果")).toBeInTheDocument();
    expect(runs).toBe(1);
    expect(screen.getByRole("textbox", { name: "消息" })).toHaveValue("");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("keeps the confirmed answer when the post-run history refresh fails", async () => {
    const user = userEvent.setup();
    let completed = false;
    let runs = 0;
    server.use(
      http.get(base + "/sessions", () => HttpResponse.json([sessionA])),
      http.get(base + "/sessions/session-a/messages", () => completed
        ? HttpResponse.json({ error: { code: "storage_unavailable", message: "存储异常" } }, { status: 503 })
        : HttpResponse.json([])),
      http.post(base + "/sessions/session-a/runs/stream", () => { completed = true; runs += 1; return sseResponse(); }),
    );
    renderWorkspace();
    await connect(user);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "分析项目");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await waitFor(() => expect(screen.getByText(/历史刷新失败，执行已成功/)).toBeInTheDocument());
    expect(screen.getByText("分析完成")).toBeInTheDocument();
    expect(screen.queryByText("本轮已完成")).not.toBeInTheDocument();
    expect(screen.getAllByText("分析完成")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "重新读取历史" }));
    expect(runs).toBe(1);
  });

  it("does not automatically resend an uncertain execution", async () => {
    const user = userEvent.setup();
    let runs = 0;
    server.use(
      http.get(base + "/sessions", () => HttpResponse.json([sessionA])),
      http.get(base + "/sessions/session-a/messages", () => HttpResponse.json([])),
      http.post(base + "/sessions/session-a/runs/stream", () => { runs += 1; return HttpResponse.error(); }),
    );
    renderWorkspace();
    await connect(user);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "执行一次");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await waitFor(() => expect(screen.getByText("结果未确认，请勿重复发送")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "连接待检查" }));
    expect(screen.getByText(/断开将丢失本页跟踪信息/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "断开连接" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "检查连接" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "本机已连接" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "关闭弹窗" }));
    await user.click(screen.getByRole("button", { name: "读取历史，人工检查" }));
    await user.click(await screen.findByRole("button", { name: "我已检查历史，允许继续" }));
    expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled();
    expect(runs).toBe(1);
  });

  it("dismisses a failed list refresh after a confirmed run and recovers on the next successful read", async () => {
    const user = userEvent.setup();
    let completed = false;
    let listReads = 0;
    let runs = 0;
    server.use(
      http.get(base + "/sessions", () => {
        listReads += 1;
        return listReads === 2
          ? HttpResponse.json({ error: { code: "proxy_unavailable", message: "无法取得后端响应；若已发送执行请求，结果可能不明，请勿自动重试。" } }, { status: 502 })
          : HttpResponse.json([sessionA]);
      }),
      http.get(base + "/sessions/session-a/messages", () => HttpResponse.json(completed ? history : [])),
      http.post(base + "/sessions/session-a/runs/stream", () => { completed = true; runs += 1; return sseResponse(); }),
    );
    renderWorkspace();
    await connect(user);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "分析项目");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByText(/会话列表刷新失败/)).toBeInTheDocument();
    expect(screen.getByText("分析完成")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "连接待检查" })).toBeInTheDocument();
    expect(screen.queryByText(/执行结果可能不明/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭提示" }));
    expect(screen.queryByText(/会话列表刷新失败/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "连接待检查" }));
    await user.click(screen.getByRole("button", { name: "检查连接" }));
    await waitFor(() => expect(listReads).toBe(3));
    await waitFor(() => expect(screen.getByRole("button", { name: "本机已连接" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "关闭弹窗" }));
    expect(screen.queryByText(/无法取得后端响应/)).not.toBeInTheDocument();
    expect(runs).toBe(1);
  });

  it("does not show a permanent completed banner for a normal answer", async () => {
    const user = userEvent.setup();
    let completed = false;
    server.use(
      http.get(base + "/sessions", () => HttpResponse.json([sessionA])),
      http.get(base + "/sessions/session-a/messages", () => HttpResponse.json(completed ? history : [])),
      http.post(base + "/sessions/session-a/runs/stream", () => { completed = true; return sseResponse(); }),
    );
    renderWorkspace();
    await connect(user);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "分析项目");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByText("分析完成")).toBeInTheDocument();
    expect(screen.queryByText("本轮已完成")).not.toBeInTheDocument();
  });

  it("keeps non-fatal warnings without restoring the completed banner or retrying", async () => {
    const user = userEvent.setup();
    let completed = false;
    let runs = 0;
    server.use(
      http.get(base + "/sessions", () => HttpResponse.json([sessionA])),
      http.get(base + "/sessions/session-a/messages", () => HttpResponse.json(completed ? history : [])),
      http.post(base + "/sessions/session-a/runs/stream", () => {
        completed = true; runs += 1;
        return sseResponse({ ...completedRun, warnings: ["session_timestamp_update_failed"] });
      }),
    );
    renderWorkspace();
    await connect(user);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "分析项目");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByText("运行提醒")).toBeInTheDocument();
    expect(screen.getByText(/会话时间更新失败，但回答已生成/)).toBeInTheDocument();
    expect(await screen.findByText("分析完成")).toBeInTheDocument();
    expect(screen.queryByText("本轮已完成")).not.toBeInTheDocument();
    expect(runs).toBe(1);
  });

  it.each([true, false])("supports explicit first configuration and distinguishes activation ready=%s", async (ready) => {
    const user = userEvent.setup();
    let configured = false;
    let previews = 0;
    let confirmations = 0;
    const current = () => configured ? { ...runtime, ready, thinking: ready ? runtime.thinking : null } : { ...runtime, configured: false, ready: false, thinking: null };
    server.use(
      http.get(base + "/runtime", () => HttpResponse.json(current())),
      http.get(base + "/providers", () => HttpResponse.json([{ provider: "deepseek", logged_in: configured }])),
      http.post(base + "/model-logins", async ({ request }) => {
        expect(await request.json()).toEqual({ provider: "deepseek", api_key: "mock-key-only" });
        previews += 1;
        return HttpResponse.json({ login_id: "preview", provider: "deepseek", models: ["deepseek-flash"], from_cache: false, expires_in: 600 }, { status: 201 });
      }),
      http.post(base + "/model-logins/preview/confirm", async ({ request }) => {
        expect(await request.json()).toEqual({ model: "deepseek-flash" });
        confirmations += 1; configured = true;
        return HttpResponse.json({ configuration_saved: true, runtime_ready: ready, runtime: current(), error: ready ? null : { code: "model_change_failed", message: "启用失败" } });
      }),
    );
    renderWorkspace();
    expect(await screen.findByText("首次使用，请从左侧「添加模型」配置厂商凭据。")).toBeInTheDocument();
    await user.click(within(screen.getByRole("complementary", { name: "会话导航" })).getByRole("button", { name: "添加模型" }));
    const input = screen.getByLabelText("API Key");
    expect(input).toHaveAttribute("type", "password");
    await user.type(input, "mock-key-only");
    await user.click(screen.getByRole("button", { name: "获取模型预览" }));
    expect(await screen.findByLabelText("选择要保存的默认模型")).toHaveValue("deepseek-flash");
    expect(previews).toBe(1); expect(confirmations).toBe(0);
    expect(screen.queryByDisplayValue("mock-key-only")).not.toBeInTheDocument();
    expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
    await user.click(screen.getByRole("button", { name: "确认保存并尝试启用" }));
    expect(await screen.findByText(ready ? "配置已保存，运行实例已启用。" : /配置已保存，但启用失败/)).toBeInTheDocument();
    expect(confirmations).toBe(1);
    expect(screen.queryByRole("button", { name: "确认保存并尝试启用" })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/API Key/)).toHaveValue("");
  });

  it("renders live reasoning and parallel tools before EOF, then replaces temporary items with history", async () => {
    const user = userEvent.setup();
    let writer: ReadableStreamDefaultController<Uint8Array> | undefined;
    let completed = false;
    const common = { session_id: "session-a", run_id: "run-1", role: "tool" } as const;
    server.use(
      http.get(base + "/sessions", () => HttpResponse.json([sessionA])),
      http.get(base + "/sessions/session-a/messages", () => HttpResponse.json(completed ? history : [])),
      http.post(base + "/sessions/session-a/runs/stream", () => new HttpResponse(new ReadableStream<Uint8Array>({ start(controller) {
        writer = controller;
        const frames = [
          ...runEvents().slice(0, 2),
          { ...terminal, seq: 3, type: "assistant.reasoning.delta", message_id: "m1", role: "assistant", data: { delta: "独立思考内容" } },
          { ...terminal, seq: 4, type: "assistant.text.delta", message_id: "m1", role: "assistant", data: { delta: "增量正文" } },
          { ...common, seq: 5, type: "tool.started", tool_call_id: "t1", data: { name: "read", input: { file: "one" } } },
          { ...common, seq: 6, type: "tool.started", tool_call_id: "t2", data: { name: "read", input: { file: "two" } } },
          { ...common, seq: 7, type: "tool.failed", tool_call_id: "t2", data: { name: "read", text: "第二调用失败", status: "error" } },
          { ...common, seq: 8, type: "tool.completed", tool_call_id: "t1", data: { name: "read", output: { count: 2 } } },
        ];
        controller.enqueue(new TextEncoder().encode(frames.map((event) => frame(event)).join("")));
      } }), { headers: { "Content-Type": "text/event-stream" } })),
    );
    const controller = renderWorkspace();
    await connect(user);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "分析项目");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByText("增量正文")).toBeInTheDocument();
    expect(screen.getByText("独立思考内容").closest("details")).not.toHaveAttribute("open");
    expect(screen.getAllByText("read")).toHaveLength(2);
    expect(controller.getSnapshot().runs["session-a"].phase).toBe("sending");
    expect(screen.getByRole("button", { name: "停止接收" })).toBeEnabled();
    await act(async () => {
      completed = true;
      writer?.enqueue(new TextEncoder().encode(frame({ ...terminal, seq: 9 })));
      writer?.close();
    });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toHaveValue(""));
    expect(screen.getAllByText("分析完成")).toHaveLength(1);
    expect(screen.queryByText("增量正文")).not.toBeInTheDocument();
    expect(screen.queryByText("独立思考内容")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "停止接收" })).not.toBeInTheDocument();
  });

  it("clears the submitted Key even when directory preview fails, without confirming or persisting it", async () => {
    const user = userEvent.setup();
    let requests = 0;
    server.use(
      http.get(base + "/providers", () => HttpResponse.json([{ provider: "deepseek", logged_in: false }])),
      http.post(base + "/model-logins", () => { requests += 1; return HttpResponse.json({ error: { code: "login_preview_failed", message: "无法获取模型预览" } }, { status: 422 }); }),
    );
    renderWorkspace();
    await waitFor(() => expect(screen.getByLabelText("请求思考等级")).toHaveValue("none"));
    await user.click(screen.getByRole("button", { name: "添加模型" }));
    const input = screen.getByLabelText("API Key");
    await user.type(input, "mock-key-only");
    await user.click(screen.getByRole("button", { name: "获取模型预览" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("无法获取模型预览");
    expect(input).toHaveValue("");
    expect(requests).toBe(1);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("uses local model shortcuts, retains active selection on busy rejection and displays actual effort fallback", async () => {
    const user = userEvent.setup();
    let changes = 0;
    const next = { ...runtime, thinking: { provider: "deepseek", model: "other-model", level: "high", reasoning_effort: "none", available_levels: ["none"] } };
    server.use(
      http.get(base + "/models", () => HttpResponse.json([
        { provider: "deepseek", model: "deepseek-flash", available_levels: ["none", "high"], current: true },
        { provider: "deepseek", model: "other-model", available_levels: ["none"], current: false },
      ])),
      http.put(base + "/runtime/model", async ({ request }) => {
        expect(await request.json()).toEqual({ provider: "deepseek", model: "other-model" });
        changes += 1;
        return changes === 1 ? HttpResponse.json({ error: { code: "manager_busy", message: "后端忙碌" } }, { status: 409 }) : HttpResponse.json(next);
      }),
    );
    renderWorkspace();
    const model = screen.getByLabelText("当前模型（本地目录）");
    await waitFor(() => expect(model).toBeEnabled());
    const composer = screen.getByRole("textbox", { name: "消息" }).closest("form");
    expect(composer).toContainElement(model);
    expect(composer).toContainElement(screen.getByLabelText("请求思考等级"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.querySelector(".runtime-bar")).toBeNull();
    await user.selectOptions(model, JSON.stringify(["deepseek", "other-model"]));
    expect(await screen.findByRole("alert")).toHaveTextContent("后端忙碌");
    expect(model).toHaveValue(JSON.stringify(["deepseek", "deepseek-flash"]));
    await user.selectOptions(model, JSON.stringify(["deepseek", "other-model"]));
    await waitFor(() => expect(model).toHaveValue(JSON.stringify(["deepseek", "other-model"])));
    expect(screen.getByLabelText("请求思考等级")).toHaveValue("high");
    expect(screen.getByText(/已回退：当前模型实际不启用 reasoning/)).toBeInTheDocument();
    expect(changes).toBe(2);
  });

  it("stops the stream from the UI without reporting a confirmed cancellation or retrying", async () => {
    const user = userEvent.setup();
    let runs = 0;
    server.use(
      http.get(base + "/sessions", () => HttpResponse.json([sessionA])),
      http.get(base + "/sessions/session-a/messages", () => HttpResponse.json([])),
      http.post(base + "/sessions/session-a/runs/stream", ({ request }) => {
        runs += 1;
        return new HttpResponse(new ReadableStream<Uint8Array>({ start(controller) {
          request.signal.addEventListener("abort", () => controller.error(new DOMException("stop", "AbortError")), { once: true });
          controller.enqueue(new TextEncoder().encode(runEvents().slice(0, 3).map((event) => frame(event)).join("")));
        } }), { headers: { "Content-Type": "text/event-stream" } });
      }),
    );
    renderWorkspace();
    await connect(user);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "只运行一次");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByText("分析完成")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "停止接收" }));
    expect(await screen.findByText("结果未确认，请勿重复发送")).toBeInTheDocument();
    expect(screen.getByText(/已停止接收，正在尝试终止/)).toBeInTheDocument();
    expect(screen.getByText("分析完成")).toBeInTheDocument();
    expect(screen.queryByText("本轮已收到取消终态")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
    expect(runs).toBe(1);
  });

  it("shows a failed connection and lets the user retry without entering credentials", async () => {
    const user = userEvent.setup();
    let reads = 0;
    server.use(http.get(base + "/sessions", () => {
      reads += 1;
      return reads === 1
        ? HttpResponse.json({ error: { code: "manager_closed", message: "服务未就绪" } }, { status: 503 })
        : HttpResponse.json([]);
    }));
    const controller = renderWorkspace();
    await user.click(screen.getByRole("button", { name: "未连接" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "连接本机后端" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("服务未就绪");
    expect(controller.getSnapshot().connection).toBe("disconnected");
    expect(reads).toBe(1);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByLabelText("访问令牌")).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "连接本机后端" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(controller.getSnapshot().connection).toBe("connected");
    expect(reads).toBe(2);
  });
});
