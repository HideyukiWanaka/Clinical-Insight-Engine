import { expect, test, type Page } from "@playwright/test";

// Phase 3 (R3-1): insert → run → console/result/output, and no silent failure.
// The API + WS are stubbed here (the real-R E2E is run against a live backend);
// what we prove is the frontend wiring described in spec/ui/ide-workbench-spec.md
// §3.1–§3.3 / §4 and the "無言失敗禁止" guarantee (rest-api-contract §5).
//
// NOTE: page.routeWebSocket installs a page init script, so it must be set up
// BEFORE page.goto() — otherwise the already-loaded page creates a real socket.

const INTENT_RESPONSE = {
  execution_id: "exec-p3-1",
  intent_object: {
    objective: "between_group_comparison",
    outcome_type: "continuous",
    natural_language_summary: "男女間で収縮期血圧を比較します。",
  },
  confidence_score: 0.9,
  requires_human_clarification: false,
  clarification_options: [],
};

const PROPOSE_RESPONSE = {
  execution_id: "exec-p3-1",
  analysis_proposal: {
    explanation_markdown: "Welch の t 検定を提案します。",
    code_candidates: [
      {
        candidate_id: "c1",
        label: "Welch t検定",
        r_code: "t.test(sbp_mmhg ~ sex, data = df)",
      },
    ],
    recommended_candidate_id: "c1",
  },
  r_script_provenance: { llm_generated: true, from_cache: false, reason: "" },
};

// 1x1 PNG fixture the figure path resolves to via /api/files/content. Served
// from a file (via fulfill `path`) so the test stays free of Node's Buffer type.
const PNG_FIXTURE = "tests/e2e/fixtures/pixel.png";

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("セッショントークン").fill("test-token-abc");
  await page.getByRole("button", { name: "設定" }).click();
  await page.route("**/api/intent", (r) => r.fulfill({ json: INTENT_RESPONSE }));
  await page.route("**/api/propose", (r) => r.fulfill({ json: PROPOSE_RESPONSE }));
}

async function getCandidate(page: Page) {
  await page.getByTestId("chat-input").fill("男女で収縮期血圧を比べたい");
  await page.getByTestId("chat-send").click();
  await page.getByTestId("confirm-propose").click();
  const candidate = page.getByTestId("code-candidate");
  await expect(candidate).toBeVisible();
  return candidate;
}

test.describe("Phase 3 — 挿入 / 実行 / コンソール / 結果 / 図", () => {
  test("候補を挿入→エディタに入る、▶実行→Console/Result/Output/Workspace に反映", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    // WS console stream: sanitized stdout then an exit frame (set up pre-goto).
    await page.routeWebSocket(/\/ws\/console/, (ws) => {
      ws.onMessage(() => {
        ws.send(JSON.stringify({ type: "stdout", text: "> t.test(sbp_mmhg ~ sex)", exit_code: null }));
        ws.send(JSON.stringify({ type: "stdout", text: "Welch Two Sample t-test", exit_code: null }));
        ws.send(JSON.stringify({ type: "exit", text: "", exit_code: 0 }));
        ws.close();
      });
    });

    await connect(page);

    // Successful run stubs: run → stats + files + workspace; visualize → figure.
    await page.route("**/api/run", (r) =>
      r.fulfill({
        json: {
          execution_id: "run-1",
          execution_result: { status: "success", exit_code: 0, duration_ms: 42 },
          statistical_results: { test: "welch_t", p_value: 0.023, statistic: 2.31 },
          statistical_results_reason: null,
          generated_files: ["output/fig_group.png"],
          workspace_summary: { df: "data.frame (200 obs, 3 variables)" },
          error_detail: null,
        },
      }),
    );
    await page.route("**/api/visualize", (r) =>
      r.fulfill({
        json: {
          execution_id: "viz-1",
          figures: [{ title: "群間比較", path: "output/fig_group.png" }],
          error_detail: null,
        },
      }),
    );
    await page.route("**/api/files/content**", (r) =>
      r.fulfill({ contentType: "image/png", path: PNG_FIXTURE }),
    );

    const candidate = await getCandidate(page);

    // ✓ 挿入 → the code lands in the editor (insert, no run).
    await candidate.getByTestId("candidate-insert").click();
    await expect(page.getByTestId("editor-host")).toContainText("t.test(sbp_mmhg ~ sex");

    // ▶ 実行 → run without inserting again.
    await candidate.getByTestId("candidate-run").click();

    // Console streams the sanitized log.
    await expect(page.getByTestId("console-log")).toContainText("Welch Two Sample t-test");

    // Result tab shows the statistics (auto-selected once the result lands).
    await expect(page.getByTestId("result-stats")).toContainText("p_value");
    await expect(page.getByTestId("result-stats")).toContainText("0.023");

    // Workspace shows the generated variable + file.
    await expect(page.getByTestId("workspace-data")).toContainText("data.frame");
    await expect(page.getByTestId("workspace-data")).toContainText("output/fig_group.png");

    // Output tab shows the figure.
    await page.getByRole("tab", { name: "Output", exact: true }).click();
    await expect(page.getByTestId("figure-output").locator("img")).toBeVisible();

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("Rscript 未導入でも理由が Console と Result に出る（無言失敗禁止 §5）", async ({
    page,
  }) => {
    await page.routeWebSocket(/\/ws\/console/, (ws) => {
      ws.onMessage(() => {
        ws.send(JSON.stringify({ type: "stderr", text: "execution failed", exit_code: null }));
        ws.send(JSON.stringify({ type: "exit", text: "", exit_code: 1 }));
        ws.close();
      });
    });

    await connect(page);

    // Backend reports the missing interpreter in error_detail (never silent).
    await page.route("**/api/run", (r) =>
      r.fulfill({
        json: {
          execution_id: "run-err",
          execution_result: { status: "execution_failed", exit_code: 127, detail: "Rscript: command not found" },
          statistical_results: null,
          statistical_results_reason: null,
          generated_files: [],
          workspace_summary: null,
          error_detail: "Rが実行できませんでした: Rscript: command not found",
        },
      }),
    );

    const candidate = await getCandidate(page);
    await candidate.getByTestId("candidate-run").click();

    // The reason shows in the Result pane and is mirrored into the console.
    const resultError = page.getByTestId("result-error");
    await expect(resultError).toBeVisible();
    await expect(resultError).toContainText("Rscript: command not found");
    await expect(page.getByTestId("console-log")).toContainText("Rscript: command not found");
  });
});
