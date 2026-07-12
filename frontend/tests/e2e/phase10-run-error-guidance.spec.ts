import { expect, test, type Page } from "@playwright/test";
import { installStandardChat } from "./support/wsChat";

// Run-error guidance: the runtime's static security validator rejects a script
// BEFORE execution with a terse, security-worded reason. Those words are opaque
// to a first-time analyst (the same guard fires for a harmless gsub("/", …) as
// for a real path traversal). The frontend must translate a matched reason into
// an actionable 原因 / 対処 (+例) so the user knows what to change — without
// weakening detection (that stays in the backend). API + WS are stubbed here.

const INTENT_RESPONSE = {
  execution_id: "exec-p10",
  intent_object: { objective: "between_group_comparison" },
  confidence_score: 0.9,
  requires_human_clarification: false,
  clarification_options: [],
};

const PROPOSE_RESPONSE = {
  execution_id: "exec-p10",
  analysis_proposal: {
    explanation_markdown: "分析コードを提案します。",
    code_candidates: [{ candidate_id: "c1", label: "候補", r_code: "options(warn=-1)" }],
    recommended_candidate_id: "c1",
  },
  r_script_provenance: { llm_generated: true, from_cache: false, reason: "" },
};

async function connectAndRunWith(page: Page, errorDetail: string) {
  await page.routeWebSocket(/\/ws\/console/, (ws) => {
    ws.onMessage(() => {
      ws.send(JSON.stringify({ type: "exit", text: "", exit_code: 1 }));
      ws.close();
    });
  });
  // Chat streams over WS /ws/chat (install before goto).
  await installStandardChat(page, {
    intent: INTENT_RESPONSE.intent_object,
    proposal: PROPOSE_RESPONSE.analysis_proposal,
    provenance: PROPOSE_RESPONSE.r_script_provenance,
  });
  await page.goto("/");
  await page.getByTestId("open-settings-from-chat").click();
  await page.getByTestId("settings-token-input").fill("test-token-abc");
  await page.getByTestId("settings-token-save").click();
  await page.getByTestId("settings-close").click();
  await page.route("**/api/run", (r) =>
    r.fulfill({
      json: {
        execution_id: "run-rej",
        execution_result: {},
        statistical_results: null,
        statistical_results_reason: null,
        generated_files: [],
        workspace_summary: null,
        error_detail: errorDetail,
      },
    }),
  );
  await page.getByTestId("chat-input").fill("分析して");
  await page.getByTestId("chat-send").click();
  await page.getByTestId("code-candidate").getByTestId("candidate-run").click();
}

test.describe("実行エラーの対処ガイド（§5 対策を明示）", () => {
  test("警告抑制 options(warn=-1) 拒否 → 原因/対処と suppressWarnings 例を明示", async ({
    page,
  }) => {
    const reason =
      "[RUNTIME_EXECUTION_ERROR] Script failed security validation: " +
      "options(warn=<negative>) — warning suppression not permitted (execution_id=x)";
    await connectAndRunWith(page, reason);

    // Raw reason is still shown verbatim (never swallowed).
    const err = page.getByTestId("result-error");
    await expect(err).toContainText("warning suppression not permitted");

    // …plus actionable guidance a first-time user can act on immediately.
    const fix = page.getByTestId("result-fix");
    await expect(fix).toBeVisible();
    await expect(fix).toContainText("警告の全体抑制は使えません");
    await expect(fix).toContainText("原因");
    await expect(fix).toContainText("対処");
    await expect(fix).toContainText("suppressWarnings");

    // The fix line is also mirrored into the console so it can't be missed.
    await expect(page.getByTestId("console-log")).toContainText("対処:");
  });

  test('"/" 文字列リテラル拒否 → 絶対パス保護の意味と修正例を明示', async ({ page }) => {
    const reason =
      "[RUNTIME_EXECUTION_ERROR] Script failed security validation: " +
      "Hard-coded Unix absolute path (string literal starting with /) (execution_id=y)";
    await connectAndRunWith(page, reason);

    const fix = page.getByTestId("result-fix");
    await expect(fix).toBeVisible();
    await expect(fix).toContainText("絶対パス保護");
    await expect(fix).toContainText("file.path");
    // before→after example is shown.
    await expect(fix).toContainText("gsub");
  });

  test("マッピングの無い一般エラーはガイドを出さず理由のみ（過剰表示しない）", async ({
    page,
  }) => {
    await connectAndRunWith(page, "Rが実行できませんでした: Rscript: command not found");
    await expect(page.getByTestId("result-error")).toContainText("command not found");
    // No fixable-pattern guidance for a plain runtime error.
    await expect(page.getByTestId("result-fix")).toHaveCount(0);
  });
});
