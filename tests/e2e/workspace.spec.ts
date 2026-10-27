import { expect, test, type Page } from "@playwright/test";
import { sseBody, history, sessionA } from "../fixtures";

import { fulfillRuntime } from "./mock-runtime";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/omt/**", async (route) => { if (!await fulfillRuntime(route)) await route.abort(); });
});

async function connect(page: Page) {
  await page.getByRole("button", { name: "未连接" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "连接本机后端" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

test("light blue welcome is usable on desktop and mobile", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "让想法，轻盈发生。" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("welcome-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "未连接" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("welcome-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "展开会话导航" }).click();
  await expect(page.getByRole("complementary", { name: "会话导航" })).toBeVisible();
  await page.getByRole("button", { name: "展开会话导航" }).click();
  await connectDialogKeyboardCheck(page);
});

async function connectDialogKeyboardCheck(page: Page) {
  await page.getByRole("button", { name: "未连接" }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "连接本机后端" })).toBeFocused();
  await expect(page.getByLabel("访问令牌")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

test("model and thinking selectors stay in the composer while model configuration lives in the sidebar", async ({ page }) => {
  await page.goto("/");
  const composer = page.locator(".composer");
  const model = composer.getByLabel("当前模型（本地目录）");
  const thinking = composer.getByLabel("请求思考等级");
  await expect(model).toBeVisible();
  await expect(thinking).toHaveValue("none");
  await expect(page.locator(".runtime-bar")).toHaveCount(0);
  await expect(page.getByRole("main").getByRole("button", { name: "添加模型" })).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "会话导航" }).getByRole("button", { name: "添加模型" })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(model).toBeInViewport();
  await expect(thinking).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "展开会话导航" }).click();
  await page.getByRole("complementary", { name: "会话导航" }).getByRole("button", { name: "添加模型" }).click();
  await expect(page.getByRole("dialog", { name: "添加模型与厂商配置" })).toBeVisible();
  await expect(page.getByRole("dialog").getByLabel("当前模型（本地目录）")).toHaveCount(0);
  await page.getByRole("button", { name: "关闭弹窗" }).click();
  await expect(page.getByRole("complementary", { name: "会话导航" })).toBeHidden();
});

test("create → send → inspect tool history, without duplicate runs or answers", async ({ page }, testInfo) => {
  let created = false;
  let completed = false;
  let runs = 0;
  let release = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/omt/**", async (route) => {
    const request = route.request();
    expect(request.headers().authorization).toBeUndefined();
    const path = new URL(request.url()).pathname;
    if (await fulfillRuntime(route)) return;
    if (path.endsWith("/runs/stream")) {
      runs += 1;
      expect(request.postDataJSON()).toEqual({ message: "分析项目" });
      await gate;
      completed = true;
      return route.fulfill({ contentType: "text/event-stream", body: sseBody() });
    }
    if (path.endsWith("/messages")) return route.fulfill({ json: completed ? history : [] });
    if (request.method() === "POST") {
      created = true;
      return route.fulfill({ status: 201, json: sessionA });
    }
    return route.fulfill({ json: created ? [sessionA] : [] });
  });
  await page.goto("/");
  await connect(page);
  await page.getByRole("button", { name: /新建会话/ }).click();
  await page.getByLabel("会话名称（可选）").fill("项目分析");
  await page.getByRole("button", { name: "创建会话", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("textbox", { name: "消息" }).fill("分析项目");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByText("OMT 正在执行", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "停止接收" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "发送消息" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "刷新历史", exact: true })).toBeDisabled();
  release();
  await expect(page.getByText("分析完成", { exact: true })).toHaveCount(1);
  await expect(page.getByText("工具调用", { exact: true })).toBeVisible();
  await page.getByText("查看工具结果", { exact: true }).click();
  await expect(page.getByText("# 项目说明", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "查看对应调用" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "消息" })).toBeEmpty();
  await page.screenshot({ path: testInfo.outputPath("conversation-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("textbox", { name: "消息" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("conversation-mobile.png"), fullPage: true });
  expect(runs).toBe(1);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  await page.reload();
  await expect(page.getByRole("button", { name: "未连接" })).toBeVisible();
  await connect(page);
  await expect(page.getByText("分析完成", { exact: true })).toHaveCount(1);
  expect(runs).toBe(1);
});

test("a lost run response requires inspection, not an automatic retry", async ({ page }) => {
  let runs = 0;
  await page.route("**/api/omt/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (await fulfillRuntime(route)) return;
    if (path.endsWith("/runs/stream")) { runs += 1; return route.abort("failed"); }
    if (path.endsWith("/messages")) return route.fulfill({ json: [] });
    return route.fulfill({ json: [sessionA] });
  });
  await page.goto("/");
  await connect(page);
  await expect(page.getByRole("textbox", { name: "消息" })).toBeEnabled();
  await page.getByRole("textbox", { name: "消息" }).fill("只执行一次");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByText("结果未确认，请勿重复发送", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "发送消息" })).toBeDisabled();
  await page.getByRole("button", { name: "读取历史，人工检查" }).click();
  await page.getByRole("button", { name: "我已检查历史，允许继续" }).click();
  await expect(page.getByRole("textbox", { name: "消息" })).toBeEnabled();
  expect(runs).toBe(1);
});
