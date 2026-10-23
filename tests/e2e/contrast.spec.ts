import { expect, test, type Page } from "@playwright/test";
import { completedRun, history, sessionA } from "../fixtures";

test.use({ reducedMotion: "reduce" });

/** Measure resolved text colors against their composited CSS background. */
async function expectReadable(page: Page, selector: string, pseudo?: "::placeholder") {
  const measurements = await page.locator(selector).evaluateAll((elements, pseudoElement) => {
    type RGB = [number, number, number];
    function rgba(value: string): [number, number, number, number] {
      const channels = value.match(/[\d.]+/g)?.map(Number) ?? [];
      if (channels.length < 3) throw new Error(`Unsupported color: ${value}`);
      return [channels[0], channels[1], channels[2], channels[3] ?? 1];
    }
    function composite(foreground: [number, number, number, number], background: RGB): RGB {
      const channel = (index: number) => foreground[index] * foreground[3] + background[index] * (1 - foreground[3]);
      return [channel(0), channel(1), channel(2)];
    }
    function luminance(color: RGB) {
      const linear = color.map((value) => value / 255).map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
      return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
    }
    return elements.filter((element) => element.getClientRects().length > 0).map((element) => {
      const ancestors: Element[] = [];
      for (let node: Element | null = element; node; node = node.parentElement) ancestors.unshift(node);
      let background: RGB = [255, 255, 255];
      for (const ancestor of ancestors) {
        const style = getComputedStyle(ancestor);
        if (style.backgroundImage !== "none") throw new Error("Gradient text backgrounds need pixel-based contrast testing");
        if (Number(style.opacity) !== 1) throw new Error("Text must not be faded by ancestor opacity");
        background = composite(rgba(style.backgroundColor), background);
      }
      const foreground = composite(rgba(getComputedStyle(element, pseudoElement).color), background);
      const a = luminance(foreground);
      const b = luminance(background);
      return { text: element.textContent?.trim().slice(0, 60) || pseudoElement || element.tagName, ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
    });
  }, pseudo);
  expect(measurements.length, `No visible elements matched ${selector}`).toBeGreaterThan(0);
  for (const measurement of measurements) expect(measurement.ratio, `${selector}: ${measurement.text}`).toBeGreaterThanOrEqual(4.5);
}

test("welcome, disabled composer and connection dialog keep readable contrast", async ({ page }) => {
  await page.goto("/");
  await expectReadable(page, ".welcome h1, .welcome h1 span, .welcome-description, .eyebrow, .suggestion-card > span:nth-child(2), .suggestion-card p, .welcome-link, .sidebar-empty, .section-heading > span, .brand-caption, .local-note strong, .local-note div > span, .connection-pill, .connection-button, .workspace-label, .current-title, .composer-bottom > span, .composer-disclaimer");
  await expectReadable(page, ".composer textarea", "::placeholder");
  await page.locator(".suggestion-card").first().hover();
  await expectReadable(page, ".suggestion-card > span:nth-child(2), .suggestion-card p");
  await page.getByRole("button", { name: "未连接" }).click();
  await expectReadable(page, ".dialog h2, .dialog-description, .endpoint, .field-help, .privacy-note, .button.primary");
  await expect(page.getByRole("dialog").locator("input")).toHaveCount(0);
  await expectReadable(page, ".button.primary");
  await page.locator(".button.primary").hover();
  await expectReadable(page, ".button.primary");
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  await expectReadable(page, ".welcome-description, .suggestion-card > span:nth-child(2), .connection-pill, .composer-disclaimer, .composer-bottom > span");
});

test("session, message, tool and non-fatal warning text stay readable", async ({ page }) => {
  let completed = false;
  await page.route("**/api/omt/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/runs")) { completed = true; return route.fulfill({ json: { ...completedRun, warnings: ["session_timestamp_update_failed"] } }); }
    if (path.endsWith("/messages")) return route.fulfill({ json: completed ? history : [] });
    return route.fulfill({ json: [sessionA] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "未连接" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "连接本机后端" }).click();
  await expect(page.getByRole("textbox", { name: "消息" })).toBeEnabled();
  await expectReadable(page, ".new-session-button, .session-label > span, .session-label time, .text-button, .connection-pill");
  await page.getByRole("textbox", { name: "消息" }).fill("分析项目");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByText("分析完成", { exact: true })).toHaveCount(1);
  await expectReadable(page, ".warning-notice strong, .warning-notice p, .message-author, .user-text, .markdown, .tool-card summary, .tool-call-caption, .tool-status");
  await page.getByText("查看工具结果", { exact: true }).click();
  await expectReadable(page, ".tool-detail pre, .tool-reference");
});
