const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");

const repoRoot = path.resolve(__dirname, "..");
const frontendRequire = createRequire(path.join(repoRoot, "frontend", "package.json"));
const { test, expect } = frontendRequire("@playwright/test");
const apiBaseUrl = process.env.PERSONAL_AGENT_API_URL || "http://127.0.0.1:8000";
const frontendUrl = process.env.PERSONAL_AGENT_FRONTEND_URL || "http://127.0.0.1:3000";
const casesPath = path.join(repoRoot, "evals", "research_quality", "frontend_e2e_cases.json");
const baselinePath = path.join(repoRoot, "evals", "research_quality", "frontend_e2e_baseline.json");
const reportPath = path.join(repoRoot, "test-results", "research-quality-frontend-e2e-report.json");

const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));
const baseline = JSON.parse(fs.readFileSync(baselinePath, "utf8"));

test.describe("Research frontend E2E golden gate", () => {
  for (const evalCase of cases) {
    test(evalCase.id, async ({ page, request }) => {
      test.setTimeout(Math.max(480000, Number(evalCase.max_latency_ms || 0) + 120000));
      await assertServerReady(request, `${apiBaseUrl}/api/health`, "backend");

      const userId = `research-e2e-${evalCase.id}-${Date.now()}`;
      const sessionId = `research-e2e-${evalCase.id}`;
      const startedAt = Date.now();

      await page.addInitScript(
        ({ userId, sessionId }) => {
          localStorage.setItem("personal-agent-user-id", userId);
          localStorage.setItem("personal-agent-session-id", sessionId);
        },
        { userId, sessionId },
      );

      const entryRequests = [];
      const entryResponses = [];
      page.on("request", (req) => {
        if (req.url().includes("/api/entry/stream")) {
          entryRequests.push(req.url());
        }
      });
      page.on("response", (res) => {
        if (res.url().includes("/api/entry/stream") || res.url().includes("/api/entry/runs")) {
          entryResponses.push({ url: res.url(), status: res.status() });
        }
      });

      await page.goto(frontendUrl, { waitUntil: "domcontentloaded" });
      const composer = page.getByPlaceholder("提问、记录想法、粘贴链接，或直接上传文件...");
      await expect(composer).toBeVisible();
      await composer.fill(evalCase.prompt);
      await page.getByRole("button", { name: "发送" }).click();

      const currentTurn = page.locator(".ask-chat-thread .chat-turn").first();
      await expect(currentTurn.locator("article").filter({ hasText: evalCase.prompt }).first()).toBeVisible();
      await expect(currentTurn.getByText("生成中").first()).not.toBeVisible({
        timeout: evalCase.max_latency_ms,
      });
      await expect(currentTurn.getByText(/已完成|出错|待确认/).first()).toBeVisible();

      const latencyMs = Date.now() - startedAt;
      const entryRun = await waitForEntryRun(request, userId, evalCase.prompt);
      const researchRun = await waitForResearchRun(request, userId, startedAt);
      const researchDetail = await fetchJson(
        request,
        `${apiBaseUrl}/api/research/runs/${encodeURIComponent(researchRun.id)}?user_id=${encodeURIComponent(userId)}`,
      );

      const output = projectOutput({
        evalCase,
        latencyMs,
        entryRun,
        researchDetail,
        entryRequests,
        entryResponses,
      });
      const scores = scoreCase(evalCase, output);
      writeReport({ cases: [{ id: evalCase.id, output, scores }], baseline });

      const failures = checkThresholds(scores, baseline);
      expect(failures, JSON.stringify({ output, scores, failures }, null, 2)).toEqual([]);
    });
  }
});

async function assertServerReady(request, url, name) {
  try {
    const response = await request.get(url, { timeout: 5000 });
    expect(response.ok(), `${name} is not ready at ${url}`).toBeTruthy();
  } catch (error) {
    throw new Error(`${name} is not reachable at ${url}. Start services with docs/deploy.md first. ${error}`);
  }
}

async function waitForEntryRun(request, userId, prompt) {
  return await poll(async () => {
    const data = await fetchJson(
      request,
      `${apiBaseUrl}/api/entry/runs?user_id=${encodeURIComponent(userId)}&limit=20`,
    );
    const match = (data.items || []).find((item) => item.entry_text === prompt);
    if (!match) return null;
    if (match.status === "completed" || match.status === "failed" || match.status === "waiting_confirmation") {
      return match;
    }
    return null;
  }, { timeoutMs: 60000, label: "entry run" });
}

async function waitForResearchRun(request, userId, startedAt) {
  return await poll(async () => {
    const data = await fetchJson(
      request,
      `${apiBaseUrl}/api/research/runs?user_id=${encodeURIComponent(userId)}&limit=20`,
    );
    const candidates = (data.items || []).filter((item) => {
      const createdAt = Date.parse(item.created_at || item.updated_at || "");
      return Number.isFinite(createdAt) && createdAt >= startedAt - 30000;
    });
    const completed = candidates.find((item) => String(item.status || "").startsWith("completed"));
    const partial = candidates.find((item) => String(item.status || "").startsWith("partial"));
    const failed = candidates.find((item) => item.status === "failed");
    return completed || partial || failed || null;
  }, { timeoutMs: 60000, label: "research run" });
}

async function poll(fn, { timeoutMs, label }) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const value = await fn();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Timed out waiting for ${label}${lastError ? `: ${lastError}` : ""}`);
}

async function fetchJson(request, url) {
  const response = await request.get(url);
  if (!response.ok()) {
    throw new Error(`GET ${url} failed: ${response.status()}`);
  }
  return await response.json();
}

function projectOutput({
  evalCase,
  latencyMs,
  entryRun,
  researchDetail,
  entryRequests,
  entryResponses,
}) {
  const researchRun = researchDetail.run || {};
  const digest = researchDetail.digest || {};
  const digestItems = digest.items || [];
  const claims = digestItems.flatMap((item) => item.claims || []);
  return {
    prompt: evalCase.prompt,
    latency_ms: latencyMs,
    ui_completed: entryRun.status === "completed",
    entry_run_id: entryRun.run_id,
    entry_status: entryRun.status,
    intents: entryRun.intents || [],
    step_tools: (entryRun.steps || []).map((step) => step.tool_name).filter(Boolean),
    execution_trace: entryRun.execution_trace || [],
    research_run_id: researchRun.id || "",
    research_status: researchRun.status || "",
    research_topic: researchRun.topic || "",
    digest_item_count: digestItems.length,
    claim_support_levels: claims.map((claim) => claim.support_level || ""),
    entry_request_count: entryRequests.length,
    entry_responses: entryResponses,
  };
}

function scoreCase(evalCase, output) {
  return {
    ui_completion_rate: output.ui_completed ? 1 : 0,
    intent_accuracy: listCoverage(output.intents, evalCase.expected_intents),
    step_tool_coverage: listCoverage(output.step_tools, evalCase.expected_step_tools),
    research_run_created_rate: output.research_run_id ? 1 : 0,
    research_status_accuracy: (evalCase.expected_research_statuses || []).includes(output.research_status) ? 1 : 0,
    topic_term_coverage: termCoverage(output.research_topic, evalCase.expected_topic_terms),
    digest_item_rate: output.digest_item_count >= Number(evalCase.min_digest_items || 0) ? 1 : 0,
    claim_support_rate: claimSupportRate(output.claim_support_levels),
    latency_within_budget_rate: output.latency_ms <= Number(evalCase.max_latency_ms || Infinity) ? 1 : 0,
  };
}

function listCoverage(actual, expected) {
  if (!expected || expected.length === 0) return 1;
  const actualSet = new Set((actual || []).map((item) => String(item).toLowerCase()));
  return expected.filter((item) => actualSet.has(String(item).toLowerCase())).length / expected.length;
}

function termCoverage(text, terms) {
  if (!terms || terms.length === 0) return 1;
  const lowered = String(text || "").toLowerCase();
  return terms.filter((term) => lowered.includes(String(term).toLowerCase())).length / terms.length;
}

function claimSupportRate(levels) {
  if (!levels || levels.length === 0) return 0;
  const supported = new Set(["supported", "partially_supported"]);
  return levels.filter((level) => supported.has(level)).length / levels.length;
}

function checkThresholds(scores, thresholds) {
  const failures = [];
  for (const [name, floor] of Object.entries(thresholds)) {
    const actual = Number(scores[name] || 0);
    if (actual < Number(floor)) {
      failures.push(`${name}=${actual.toFixed(4)} < threshold ${Number(floor).toFixed(4)}`);
    }
  }
  return failures;
}

function writeReport(report) {
  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
}
