import { expect, test } from "@playwright/test";
import { sseBody, history, sessionA } from "../fixtures";

import { fulfillRuntime } from "./mock-runtime";

test("a failed post-run list refresh can be dismissed and checked without rerunning", async ({ page }) => {
  let completed = false;
  let listReads = 0;
  let runs = 0;
  await page.route("**/api/omt/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (await fulfillRuntime(route)) return;
    if (path.endsWith("/runs/stream")) { runs += 1; completed = true; return route.fulfill({ contentType: "text/event-stream", body: sseBody() }); }
    if (path.endsWith("/messages")) return route.fulfill({ json: completed ? history : [] });
    listReads += 1;
    return listReads === 2 ? route.fulfill({ status: 502, json: { error: { code: "proxy_unavailable", message: "legacy execution warning" } } })
      : route.fulfill({ json: [sessionA] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "未连接" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "连接本机后端" }).click();
  await expect(page.getByRole("textbox", { name: "消息" })).toBeEnabled();
  await page.getByRole("textbox", { name: "消息" }).fill("分析项目");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByText("分析完成", { exact: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "连接待检查", exact: true })).toBeVisible();
  const notice = page.locator(".global-notice[role=alert]");
  await expect(notice).toContainText("会话列表刷新失败");
  await expect(notice).not.toContainText("执行结果可能不明");
  await expect(page.getByText("本轮已完成", { exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "关闭提示" })).toBeInViewport();
  await page.getByRole("button", { name: "关闭提示" }).click();
  await expect(notice).toHaveCount(0);
  await page.getByRole("button", { name: "连接待检查", exact: true }).click();
  await page.getByRole("button", { name: "检查连接", exact: true }).click();
  await expect(page.getByRole("button", { name: "本机已连接", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "关闭弹窗" }).click();
  await expect(page.getByText("分析完成", { exact: true })).toHaveCount(1);
  expect(runs).toBe(1);
  expect(listReads).toBe(3);
});
