import { expect, test, type Page } from "@playwright/test";
import {
  figuresFrame,
  hasIntentObject,
  manuscriptFrame,
  proposalFrames,
  routeWsChat,
} from "./support/wsChat";

// Phase 11 (Dialog agent): deterministic-gated tool routing in chat. After a run
// produces statistics, explicit affordances (「📊 図を作成」「📝 原稿を作成」) route
// the turn to the visualization / reporting tool over WS /ws/chat with an
// explicit requested_tool — never inferred from free text. The tool result
// renders inline (figures / manuscript). R execution stays human-gated.

const PNG_FIXTURE = "tests/e2e/fixtures/pixel.png";

const INTENT_RESPONSE = {
  intent_object: {
    objective: "between_group_comparison",
    natural_language_summary: "男女間で収縮期血圧を比較します。",
  },
};
const INITIAL_PROPOSE = {
  analysis_proposal: {
    explanation_markdown: "Welch の t 検定を提案します。",
    code_candidates: [
      { candidate_id: "c1", label: "Welch t検定", r_code: "t.test(sbp_mmhg ~ sex, data = df)" },
    ],
    recommended_candidate_id: "c1",
  },
};
const RUN_RESPONSE = {
  execution_id: "run-p11",
  execution_result: { status: "success", exit_code: 0, duration_ms: 30 },
  statistical_results: { test: "welch_t", p_value: 0.021 },
  statistical_results_reason: null,
  generated_files: [],
  workspace_summary: null,
  error_detail: null,
};

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByTestId("open-settings-from-chat").click();
  await page.getByTestId("settings-token-input").fill("test-token-abc");
  await page.getByTestId("settings-token-save").click();
  await page.getByTestId("settings-close").click();
}

async function runInitial(page: Page): Promise<void> {
  await page.getByTestId("chat-input").fill("男女で収縮期血圧を比べたい");
  await page.getByTestId("chat-send").click();
  await page.getByTestId("confirm-propose").click();
  await expect(page.getByTestId("code-candidate")).toBeVisible();
  await page.getByTestId("candidate-run").click();
}

test.describe("Phase 11 — Dialog エージェント: 決定論ゲート付きツールルーティング", () => {
  test("図/原稿の明示アクション → requested_tool で確定ルーティング、結果を描画", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await page.routeWebSocket(/\/ws\/console/, (ws) => {
      ws.onMessage(() => {
        ws.send(JSON.stringify({ type: "exit", text: "", exit_code: 0 }));
        ws.close();
      });
    });

    // WS /ws/chat routing: an explicit requested_tool wins outright; otherwise a
    // confirm-then-proposal for the initial analysis. Install before goto.
    const chatMessages = await routeWsChat(page, (msg) => {
      if (msg.requested_tool === "visualization") {
        return [figuresFrame([{ title: "群間比較", path: "output/fig_group.png" }])];
      }
      if (msg.requested_tool === "reporting") {
        return [
          manuscriptFrame([
            { section_id: "results", text: "男性で有意に高値 (p = .021)。", is_ai_generated: true },
          ]),
        ];
      }
      if (hasIntentObject(msg)) return proposalFrames(INITIAL_PROPOSE.analysis_proposal);
      return [{ type: "confirm", intent_object: INTENT_RESPONSE.intent_object }];
    });

    await page.route("**/api/run", (r) => r.fulfill({ json: RUN_RESPONSE }));
    await page.route("**/api/files/content**", (r) =>
      r.fulfill({ contentType: "image/png", path: PNG_FIXTURE }),
    );

    await connect(page);
    await runInitial(page);

    // Tool affordances light up once statistics exist.
    await expect(page.getByTestId("tool-visualize")).toBeEnabled();
    await expect(page.getByTestId("tool-report")).toBeEnabled();

    // 📊 図を作成 → figures bubble with the image, and the request carried the
    // explicit tool + prior results (no free-text inference).
    await page.getByTestId("tool-visualize").click();
    await expect(page.getByTestId("chat-figures")).toBeVisible();
    await expect(page.getByTestId("chat-figure-img")).toBeVisible();
    await expect(page.getByTestId("chat-figures")).toContainText("群間比較");

    const vizMsg = chatMessages.find((m) => m.requested_tool === "visualization");
    expect(vizMsg).toBeTruthy();
    expect(vizMsg!.prior_statistical_results).toMatchObject({ test: "welch_t" });
    expect(vizMsg!.intent_object).toMatchObject({ objective: "between_group_comparison" });

    // 📝 原稿を作成 → manuscript sections render (copyable), AI badge present.
    await page.getByTestId("tool-report").click();
    await expect(page.getByTestId("chat-manuscript")).toBeVisible();
    const section = page.getByTestId("chat-manuscript-section");
    await expect(section).toContainText("p = .021");
    await expect(section).toContainText("AI生成");

    const repMsg = chatMessages.find((m) => m.requested_tool === "reporting");
    expect(repMsg).toBeTruthy();
    expect(repMsg!.prior_statistical_results).toMatchObject({ test: "welch_t" });

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("結果が無いうちはツールアクションが無効", async ({ page }) => {
    await routeWsChat(page, () => [
      { type: "confirm", intent_object: INTENT_RESPONSE.intent_object },
    ]);
    await connect(page);
    // Before any run there are no statistics — the tools are disabled.
    await expect(page.getByTestId("tool-visualize")).toBeDisabled();
    await expect(page.getByTestId("tool-report")).toBeDisabled();
  });
});
