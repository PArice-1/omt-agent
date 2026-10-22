import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { Workspace } from "./workspace";
import { WorkspaceController } from "./model/controller";
import { createOmtClient } from "@/lib/omt-api/client";
import { completedRun, history, sessionA, testToken } from "../../../tests/fixtures";

const base = "http://localhost/api/omt";
const server = setupServer();
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

async function connect(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "未连接" }));
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText("访问令牌"), testToken);
  await user.click(within(dialog).getByRole("button", { name: "连接本机后端" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}
function renderWorkspace() {
  const controller = new WorkspaceController((getToken) => createOmtClient({ baseUrl: base, getToken }));
  render(<Workspace controller={controller} />);
  return controller;
}

describe("workspace user flows with the real API client", () => {
  it("connects, creates a session, sends and replaces the full history without duplicate answers", async () => {
    const user = userEvent.setup();
    let created = false;
    let completed = false;
    let runs = 0;
    server.use(
      http.get(base + "/api/v1/sessions", ({ request }) => {
        expect(request.headers.get("Authorization")).toBe(`Bearer ${testToken}`);
        return HttpResponse.json(created ? [sessionA] : []);
      }),
      http.post(base + "/api/v1/sessions", async ({ request }) => {
        expect(await request.json()).toEqual({ title: "项目分析" });
        created = true;
        return HttpResponse.json(sessionA, { status: 201 });
      }),
      http.get(base + "/api/v1/sessions/session-a/messages", () => HttpResponse.json(completed ? history : [])),
      http.post(base + "/api/v1/sessions/session-a/runs", async ({ request }) => {
        expect(await request.json()).toEqual({ message: "分析项目" });
        runs += 1; completed = true;
        return HttpResponse.json(completedRun);
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
      http.get(base + "/api/v1/sessions", () => HttpResponse.json([sessionA])),
      http.get(base + "/api/v1/sessions/session-a/messages", () => completed
        ? HttpResponse.json({ error: { code: "storage_unavailable", message: "存储异常" } }, { status: 503 })
        : HttpResponse.json([])),
      http.post(base + "/api/v1/sessions/session-a/runs", () => { completed = true; runs += 1; return HttpResponse.json(completedRun); }),
    );
    renderWorkspace();
    await connect(user);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "分析项目");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await waitFor(() => expect(screen.getByText(/历史刷新失败，执行已成功/)).toBeInTheDocument());
    expect(screen.getByText("分析完成")).toBeInTheDocument();
    expect(screen.getByText("本轮已完成")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新读取历史" }));
    expect(runs).toBe(1);
  });

  it("does not automatically resend an uncertain execution", async () => {
    const user = userEvent.setup();
    let runs = 0;
    server.use(
      http.get(base + "/api/v1/sessions", () => HttpResponse.json([sessionA])),
      http.get(base + "/api/v1/sessions/session-a/messages", () => HttpResponse.json([])),
      http.post(base + "/api/v1/sessions/session-a/runs", () => { runs += 1; return HttpResponse.error(); }),
    );
    renderWorkspace();
    await connect(user);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled());
    await user.type(screen.getByRole("textbox", { name: "消息" }), "执行一次");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await waitFor(() => expect(screen.getByText("无法确认本轮结果，请勿重复发送")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "本机已连接" }));
    expect(screen.getByText(/断开将丢失本页跟踪信息/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "断开连接" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "关闭弹窗" }));
    await user.click(screen.getByRole("button", { name: "读取历史，人工检查" }));
    await user.click(await screen.findByRole("button", { name: "我已检查历史，允许继续" }));
    expect(screen.getByRole("textbox", { name: "消息" })).toBeEnabled();
    expect(runs).toBe(1);
  });

  it("shows authentication failures without storing the credential", async () => {
    const user = userEvent.setup();
    server.use(http.get(base + "/api/v1/sessions", () => HttpResponse.json({ error: { code: "unauthorized", message: "令牌错误" } }, { status: 401 })));
    const controller = renderWorkspace();
    await user.click(screen.getByRole("button", { name: "未连接" }));
    await user.type(screen.getByLabelText("访问令牌"), testToken);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "连接本机后端" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("令牌错误");
    expect(controller.getSnapshot().connection).toBe("disconnected");
    expect(JSON.stringify(controller.getSnapshot())).not.toContain(testToken);
  });
});
