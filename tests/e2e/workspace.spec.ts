import { expect, test, type Page } from "@playwright/test";
import { completedRun, history, sessionA, testToken } from "../fixtures";

async function connect(page: Page) {
  await page.getByRole("button", { name: "未连接" }).click();
  await page.getByLabel("访问令牌").fill(testToken);
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
  await expect(page.getByLabel("访问令牌")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

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
    expect(request.headers().authorization).toBe(`Bearer ${testToken}`);
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/runs")) {
      runs += 1;
      expect(request.postDataJSON()).toEqual({ message: "分析项目" });
      await gate;
      completed = true;
      return route.fulfill({ json: completedRun });
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
  await expect(page.getByRole("button", { name: "发送消息" })).toBeDisabled();
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
});

test("a lost run response requires inspection, not an automatic retry", async ({ page }) => {
  let runs = 0;
  await page.route("**/api/omt/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/runs")) { runs += 1; return route.abort("failed"); }
    if (path.endsWith("/messages")) return route.fulfill({ json: [] });
    return route.fulfill({ json: [sessionA] });
  });
  await page.goto("/");
  await connect(page);
  await expect(page.getByRole("textbox", { name: "消息" })).toBeEnabled();
  await page.getByRole("textbox", { name: "消息" }).fill("只执行一次");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByText("无法确认本轮结果，请勿重复发送", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "发送消息" })).toBeDisabled();
  await page.getByRole("button", { name: "读取历史，人工检查" }).click();
  await page.getByRole("button", { name: "我已检查历史，允许继续" }).click();
  await expect(page.getByRole("textbox", { name: "消息" })).toBeEnabled();
  expect(runs).toBe(1);
});
