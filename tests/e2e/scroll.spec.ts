import { expect, test } from "@playwright/test";
import type { MessageResponse } from "../../src/lib/omt-api/contracts";
import { completedRun, sessionA } from "../fixtures";

test("sending and new output scroll to the latest message even after reading older history", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const previous: MessageResponse[] = Array.from({ length: 35 }, (_, index) => ({
    role: "assistant", text: `历史段落 ${index + 1}\n\n这是一段已有历史，用于验证滚动位置。`, tool_calls: [],
  }));
  const answer = Array.from({ length: 28 }, (_, index) => `输出段落 ${index + 1}`).join("\n\n") + "\n\n最新输出结束";
  let completed = false;
  let runs = 0;
  let releaseRun = () => {};
  let releaseHistory = () => {};
  const runGate = new Promise<void>((resolve) => { releaseRun = resolve; });
  const historyGate = new Promise<void>((resolve) => { releaseHistory = resolve; });
  await page.route("**/api/omt/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/runs")) {
      runs += 1;
      await runGate;
      completed = true;
      return route.fulfill({ json: { ...completedRun, answer } });
    }
    if (path.endsWith("/messages")) {
      if (!completed) return route.fulfill({ json: previous });
      await historyGate;
      return route.fulfill({ json: [...previous,
        { role: "user", text: "继续输出", tool_calls: [] },
        { role: "assistant", text: answer, tool_calls: [] },
      ] });
    }
    return route.fulfill({ json: [sessionA] });
  });
  try {
    await page.goto("/");
    await page.getByRole("button", { name: "未连接" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "连接本机后端" }).click();
    await expect(page.getByRole("textbox", { name: "消息" })).toBeEnabled();
    const scroller = page.locator(".message-scroll");
    const scrollUp = () => scroller.evaluate((element) => { element.scrollTop = 0; element.dispatchEvent(new Event("scroll")); });
    const bottomDistance = () => scroller.evaluate((element) => element.scrollHeight - element.scrollTop - element.clientHeight);
    await scrollUp();
    await page.getByRole("textbox", { name: "消息" }).fill("继续输出");
    await page.getByRole("button", { name: "发送消息" }).click();
    await expect.poll(bottomDistance).toBeLessThanOrEqual(3);
    await scrollUp();
    releaseRun();
    await expect(page.getByText("最新输出结束", { exact: true })).toBeInViewport();
    await expect.poll(bottomDistance).toBeLessThanOrEqual(3);
    await scrollUp();
    releaseHistory();
    await expect(page.getByRole("textbox", { name: "消息" })).toBeEnabled();
    await expect(page.getByText("最新输出结束", { exact: true })).toBeInViewport();
    await expect.poll(bottomDistance).toBeLessThanOrEqual(3);
    await expect(page.getByText("本轮已完成", { exact: true })).toHaveCount(0);
    await scrollUp();
    await page.getByRole("button", { name: "本机已连接" }).click();
    await page.getByRole("button", { name: "关闭弹窗" }).click();
    await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBe(0);
    expect(runs).toBe(1);
  } finally {
    releaseRun();
    releaseHistory();
  }
});
