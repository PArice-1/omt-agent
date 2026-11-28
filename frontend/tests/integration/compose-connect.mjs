import assert from 'node:assert/strict';
import { chromium, expect } from '@playwright/test';

// 验证已启动的隔离 Compose 实例在无模型时仍能手动连接。参数是宿主机回环端口，默认 3000。
const port = Number(process.argv[2] ?? '3000');
assert(Number.isInteger(port) && port >= 1 && port <= 65535, '请传入有效端口（1–65535）。');

const browser = await chromium.launch();
try {
  for (const host of ['127.0.0.1', 'localhost']) {
    const page = await browser.newPage();
    page.setDefaultTimeout(7000);
    const origin = `http://${host}:${port}`;
    const sessionRequests = [];
    let runtimeResponse;
    page.on('response', (response) => {
      if (response.url() === `${origin}/api/omt/runtime`) runtimeResponse = response;
    });
    await page.route('**/api/omt/**', async (route) => {
      const request = route.request();
      if (new URL(request.url()).pathname.startsWith('/api/omt/sessions')) sessionRequests.push(request.method());
      // 只允许只读请求，不保存配置、创建会话或调用模型。
      if (request.method() === 'GET') await route.continue();
      else await route.abort();
    });
    console.log(`检查 ${origin} 的手动连接…`);
    await page.goto(origin);
    await page.getByRole('button', { name: '未连接', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '连接本机后端' }).click();
    await expect(page.getByRole('button', { name: '本机已连接', exact: true })).toBeVisible();
    assert.equal(runtimeResponse?.status(), 200, `${origin} 运行状态接口不可用`);
    assert.equal((await runtimeResponse.json()).ready, false, '请使用未就绪的独立测试实例。');
    assert.deepEqual(sessionRequests, [], '未就绪时不应请求会话列表。');
    console.log(`PASS ${origin}: 无模型也能手动连接，且未请求会话列表。`);
    await page.close();
  }
} finally {
  await browser.close();
}
