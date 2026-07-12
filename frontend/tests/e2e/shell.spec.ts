import { expect, test } from "@playwright/test";
import { hasIntentObject, proposalFrames, routeWsChat } from "./support/wsChat";

const INTENT_RESPONSE = {
  execution_id: "exec-e2e-1",
  intent_object: {
    objective: "between_group_comparison",
    outcome_type: "continuous",
    predictor_type: "categorical_binary",
    natural_language_summary: "男女間で収縮期血圧を比較します。",
  },
  confidence_score: 0.91,
  requires_human_clarification: false,
  clarification_options: [],
};

const PROPOSE_RESPONSE = {
  execution_id: "exec-e2e-1",
  analysis_proposal: {
    explanation_markdown:
      "2群の平均差を評価するため Welch の t 検定を提案します。",
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

test.describe("CIE Workbench shell", () => {
  test("4ペイン表示 + intent→propose のチャット疎通", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    // Chat streams over WS /ws/chat. A low-confidence prompt asks to confirm;
    // confirming (an intent_object turn) streams the proposal. Install before
    // goto (routeWebSocket adds a page init script).
    await routeWsChat(page, (msg) =>
      hasIntentObject(msg)
        ? proposalFrames(
            PROPOSE_RESPONSE.analysis_proposal,
            PROPOSE_RESPONSE.r_script_provenance,
          )
        : [{ type: "confirm", intent_object: INTENT_RESPONSE.intent_object }],
    );

    await page.goto("/");

    // Header + four panes present (spec §2).
    await expect(
      page.getByRole("banner").getByText("Workbench", { exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("chat-log")).toBeVisible();
    await expect(page.getByTestId("editor-host")).toBeVisible();
    await expect(page.getByRole("region", { name: "スクリプト" })).toBeVisible();
    await expect(page.getByRole("region", { name: "コンソール" })).toBeVisible();
    await expect(page.getByRole("region", { name: "ファイル" })).toBeVisible();
    await expect(page.getByRole("region", { name: "ワークスペース" })).toBeVisible();

    // Set a session token → header flips to connected.
    await expect(page.getByTestId("status-connection")).toContainText(
      "APIトークン未設定",
    );
    await page.getByTestId("open-settings-from-chat").click();
    await page.getByTestId("settings-token-input").fill("test-token-abc");
    await page.getByTestId("settings-token-save").click();
    await page.getByTestId("settings-close").click();
    await expect(page.getByTestId("status-connection")).toContainText(
      "API接続済み",
    );

    // Type a research question → intent → confirm bubble.
    await page.getByTestId("chat-input").fill("男女で収縮期血圧を比べたい");
    await page.getByTestId("chat-send").click();

    const confirm = page.getByTestId("chat-confirm");
    await expect(confirm).toBeVisible();
    await expect(confirm).toContainText("収縮期血圧");

    // Confirm → propose → explanation bubble + code candidate block.
    await page.getByTestId("confirm-propose").click();

    await expect(page.getByTestId("proposal-explanation")).toContainText(
      "t 検定",
    );
    const candidate = page.getByTestId("code-candidate");
    await expect(candidate).toBeVisible();
    await expect(candidate).toContainText("t.test(sbp_mmhg ~ sex");
    // Insert/Run are wired in Phase 3 → both enabled.
    await expect(candidate.getByTestId("candidate-insert")).toBeEnabled();
    await expect(candidate.getByTestId("candidate-run")).toBeEnabled();

    await page.screenshot({ path: "test-results/shell.png", fullPage: true });

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual(
      [],
    );
  });

  test("生成失敗の理由がチャットに表示される（無言失敗禁止 §5）", async ({
    page,
  }) => {
    // The Planner confirms, then proposal generation fails — the stream ends
    // with an `error` frame whose reason is surfaced (never silent, §5).
    await routeWsChat(page, (msg) =>
      hasIntentObject(msg)
        ? [{ type: "error", reason: "LLM_API_KEY_NOT_CONFIGURED" }]
        : [{ type: "confirm", intent_object: INTENT_RESPONSE.intent_object }],
    );

    await page.goto("/");
    await page.getByTestId("open-settings-from-chat").click();
    await page.getByTestId("settings-token-input").fill("test-token-abc");
    await page.getByTestId("settings-token-save").click();
    await page.getByTestId("settings-close").click();

    await page.getByTestId("chat-input").fill("男女で収縮期血圧を比べたい");
    await page.getByTestId("chat-send").click();
    await page.getByTestId("confirm-propose").click();

    const err = page.getByTestId("chat-error");
    await expect(err).toBeVisible();
    await expect(err).toContainText("LLM_API_KEY_NOT_CONFIGURED");
  });
});
