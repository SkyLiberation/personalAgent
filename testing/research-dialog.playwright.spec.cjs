const { test, expect } = require("@playwright/test");

test("trigger research_once through the frontend dialog", async ({ page }) => {
  test.setTimeout(360000);

  const events = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/entry/stream")) {
      events.push({ type: "request", url });
    }
  });
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/api/entry/stream") || url.includes("/api/entry/runs")) {
      events.push({ type: "response", url, status: response.status() });
    }
  });

  await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
  const composer = page.getByPlaceholder("提问、记录想法、粘贴链接，或直接上传文件...");
  await expect(composer).toBeVisible();

  const prompt = "调研一下 OpenAI GPT-5 mini 的最新公开动态，最多整理 1 条高可信事件。";
  await composer.fill(prompt);
  await page.getByRole("button", { name: "发送" }).click();

  const currentTurn = page.locator(".ask-chat-thread .chat-turn").first();
  await expect(currentTurn.locator("article").filter({ hasText: prompt }).first()).toBeVisible();
  await expect(currentTurn.getByText("生成中").first()).not.toBeVisible({ timeout: 300000 });
  await expect(currentTurn.getByText(/Agent 执行步骤|已完成|失败|无法/).first()).toBeVisible();

  await page.waitForTimeout(2000);
  const bodyText = await page.locator("body").innerText();
  console.log(JSON.stringify({ prompt, events, bodyText: bodyText.slice(0, 5000) }, null, 2));
});
