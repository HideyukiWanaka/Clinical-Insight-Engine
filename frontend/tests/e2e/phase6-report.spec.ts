import { expect, test, type Page } from "@playwright/test";

// Phase 6 (R6-1): Output & Format pane — pick a reporting checklist / journal
// style / user Skill, press "原稿に変換" → POST /api/report → manuscript_sections
// render as copyable text blocks (spec/ui/ide-workbench-spec.md §3.5).
//
// The API/WS are stubbed; the ReportingAgent itself is unchanged (§3.5) and is
// covered by the Python unit tests + the real-data harness.

const INTENT_RESPONSE = {
  execution_id: "exec-p6",
  intent_object: {
    objective: "between_group_comparison",
    outcome_type: "continuous",
    study_design: "observational",
    natural_language_summary: "男女間で収縮期血圧を比較します。",
  },
  confidence_score: 0.9,
  requires_human_clarification: false,
  clarification_options: [],
};

const PROPOSE_RESPONSE = {
  execution_id: "exec-p6",
  analysis_proposal: {
    explanation_markdown: "Welch の t 検定を提案します。",
    code_candidates: [
      { candidate_id: "c1", label: "Welch t検定", r_code: "t.test(sbp ~ sex, data = df)" },
    ],
    recommended_candidate_id: "c1",
  },
  r_script_provenance: { llm_generated: true, from_cache: false, reason: "" },
};

// A run that yields statistical_results — the Output & Format pane needs them.
const RUN_RESPONSE = {
  execution_id: "run-p6",
  execution_result: { status: "success", exit_code: 0, duration_ms: 30 },
  statistical_results: { test: "welch_t", p_value: 0.034, estimate: 5.1 },
  statistical_results_reason: null,
  generated_files: [],
  workspace_summary: null,
  error_detail: null,
};

const REPORT_RESPONSE = {
  execution_id: "report-p6",
  manuscript_sections: [
    { section_id: "methods", text: "STROBE に準拠した統計手法の記述。", is_ai_generated: false },
    { section_id: "results", text: "収縮期血圧は男性で有意に高かった (p = .034)。", is_ai_generated: true },
  ],
  error_detail: null,
};

async function connectAndRun(page: Page): Promise<void> {
  await page.routeWebSocket(/\/ws\/console/, (ws) => {
    ws.onMessage(() => {
      ws.send(JSON.stringify({ type: "exit", text: "", exit_code: 0 }));
      ws.close();
    });
  });
  await page.goto("/");
  await page.getByTestId("open-settings-from-chat").click();
  await page.getByTestId("settings-token-input").fill("test-token-abc");
  await page.getByTestId("settings-token-save").click();
  await page.getByTestId("settings-close").click();
  await page.route("**/api/intent", (r) => r.fulfill({ json: INTENT_RESPONSE }));
  await page.route("**/api/propose", (r) => r.fulfill({ json: PROPOSE_RESPONSE }));
  await page.route("**/api/run", (r) => r.fulfill({ json: RUN_RESPONSE }));

  await page.getByTestId("chat-input").fill("男女で収縮期血圧を比べたい");
  await page.getByTestId("chat-send").click();
  await page.getByTestId("confirm-propose").click();
  await page.getByTestId("code-candidate").getByTestId("candidate-run").click();
}

test.describe("Phase 6 — Output & Format 原稿生成", () => {
  test("STROBE/APA を選び原稿に変換 → セクション表示 + 選択値が payload に載る", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await connectAndRun(page);

    let reportBody: Record<string, unknown> | null = null;
    await page.route("**/api/report", (r) => {
      reportBody = r.request().postDataJSON() as Record<string, unknown>;
      return r.fulfill({ json: REPORT_RESPONSE });
    });

    // Open the Output & Format tab.
    await page.getByRole("tab", { name: "Output & Format" }).click();
    const pane = page.getByTestId("format-pane");
    await expect(pane).toBeVisible();

    // Choose STROBE checklist + AMA→APA style + a user Skill override.
    await page.getByTestId("format-checklist").selectOption("STROBE");
    await page.getByRole("radio", { name: "APA" }).check();
    await page.getByTestId("format-skill").fill("my-hospital-manuscript");

    // 原稿に変換 → sections render as copyable blocks.
    await page.getByTestId("format-generate").click();
    const sections = page.getByTestId("manuscript-section");
    await expect(sections).toHaveCount(2);
    await expect(page.getByTestId("format-sections")).toContainText("p = .034");
    // AI-generated section carries the badge.
    await expect(sections.nth(1)).toContainText("AI生成");

    // The selected format + user Skill + last-run statistics reached the API.
    expect(reportBody).toMatchObject({
      reporting_checklist_id: "STROBE",
      target_journal_style: "APA",
      reporting_skill_id: "my-hospital-manuscript",
      statistical_results: { test: "welch_t", p_value: 0.034 },
      intent_object: { objective: "between_group_comparison" },
    });

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("統計結果が無ければ生成ボタンは無効", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("open-settings-from-chat").click();
    await page.getByTestId("settings-token-input").fill("test-token-abc");
    await page.getByTestId("settings-token-save").click();
    await page.getByTestId("settings-close").click();

    await page.getByRole("tab", { name: "Output & Format" }).click();
    await expect(page.getByTestId("format-generate")).toBeDisabled();
    await expect(page.getByTestId("format-nostats")).toBeVisible();
  });

  test("生成失敗の理由が表示される（無言失敗禁止 §5）", async ({ page }) => {
    await connectAndRun(page);
    await page.route("**/api/report", (r) =>
      r.fulfill({
        json: {
          execution_id: "report-err",
          manuscript_sections: [],
          error_detail: "LLM_API_KEY_NOT_CONFIGURED",
        },
      }),
    );

    await page.getByRole("tab", { name: "Output & Format" }).click();
    await page.getByTestId("format-generate").click();
    const err = page.getByTestId("format-error");
    await expect(err).toBeVisible();
    await expect(err).toContainText("LLM_API_KEY_NOT_CONFIGURED");
  });
});
