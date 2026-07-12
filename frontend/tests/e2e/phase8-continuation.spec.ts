import { expect, test, type Page } from "@playwright/test";
import { hasIntentObject, proposalFrames, routeWsChat } from "./support/wsChat";

// Phase 8 (R8-3): 追加対話（会話継続 §3.1/§3.2/§4 step5）。実行後に統計結果が有る間は
// 送信を既定で継続（continuation_query + prior_*）として往復する。話題変更時のみ
// 「＋ 新しい解析」で intent に戻す。土台チップが現在の基準を常時可視化する。
// 生成失敗時は reason を表示（無言失敗禁止 §5）。
//
// Phase 2 以降、チャットは WS /ws/chat をストリーミングする。継続ターンは系譜 intent と
// continuation_query + prior_* を載せ、Planner を経ずに提案をストリームする。ここでは
// その WS プロトコルをモックして往復を検証する（design §6）。

const INTENT_RESPONSE = {
  execution_id: "exec-p8-3",
  intent_object: {
    objective: "between_group_comparison",
    natural_language_summary: "男女間で収縮期血圧を比較します。",
  },
  confidence_score: 0.9,
  requires_human_clarification: false,
  clarification_options: [],
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
const CONTINUATION_PROPOSE = {
  analysis_proposal: {
    explanation_markdown: "図のタイトルを差し替えた版です。",
    code_candidates: [
      { candidate_id: "c2", label: "タイトル変更", r_code: "# retitled\nplot(main = 'New')" },
    ],
    recommended_candidate_id: "c2",
  },
};
const RUN_RESPONSE = {
  execution_id: "run-p8-3",
  execution_result: { status: "success", exit_code: 0, duration_ms: 30 },
  statistical_results: { test: "welch_t", p_value: 0.023 },
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

// The initial turn: a fresh prompt confirms, confirming streams the proposal,
// then run it so statistics land (continuation becomes the default).
async function runInitial(page: Page): Promise<void> {
  await page.getByTestId("chat-input").fill("男女で収縮期血圧を比べたい");
  await page.getByTestId("chat-send").click();
  await page.getByTestId("confirm-propose").click();
  await expect(page.getByTestId("code-candidate")).toBeVisible();
  await page.getByTestId("candidate-run").click();
}

test.describe("Phase 8 — 追加対話（継続既定 + 新しい解析リセット）", () => {
  test("実行後は無操作で継続、prior_* が載る、土台チップ更新、リセットで intent に戻る", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await page.routeWebSocket(/\/ws\/console/, (ws) => {
      ws.onMessage(() => {
        ws.send(JSON.stringify({ type: "stdout", text: "Welch Two Sample t-test", exit_code: null }));
        ws.send(JSON.stringify({ type: "exit", text: "", exit_code: 0 }));
        ws.close();
      });
    });

    // WS /ws/chat: a fresh prompt asks to confirm; a confirm follow-through
    // (intent_object) streams the initial proposal; a follow-up
    // (continuation_query + prior_*) streams the continuation proposal WITHOUT
    // re-planning. Install before goto.
    const chatMessages = await routeWsChat(page, (msg) => {
      if (msg.continuation_query) {
        return proposalFrames(CONTINUATION_PROPOSE.analysis_proposal);
      }
      if (hasIntentObject(msg)) {
        return proposalFrames(INITIAL_PROPOSE.analysis_proposal);
      }
      return [{ type: "confirm", intent_object: INTENT_RESPONSE.intent_object }];
    });

    await page.route("**/api/run", (r) => r.fulfill({ json: RUN_RESPONSE }));
    await page.route("**/api/visualize", (r) =>
      r.fulfill({ json: { execution_id: "viz", figures: [], error_detail: null } }),
    );

    await connect(page);
    await runInitial(page);

    // 土台チップに要約 + 直近検定名が出る（継続が既定に）。
    const chip = page.getByTestId("base-chip");
    await expect(chip).toContainText("土台:");
    await expect(chip).toContainText("収縮期血圧");
    await expect(chip).toContainText("welch_t");

    // 無操作で継続: 送信ボタンが「継続送信」に切り替わる。
    await expect(page.getByTestId("chat-send")).toContainText("継続送信");

    // 追加送信 → WS に continuation_query + prior_* が載る。
    await page.getByTestId("chat-input").fill("図のタイトルを変えて");
    await page.getByTestId("chat-send").click();

    // 新しい候補が描画される（既存 proposal 描画の再利用）。
    await expect(page.getByText("図のタイトルを差し替えた版です。")).toBeVisible();
    const contMsg = chatMessages.find((m) => m.continuation_query);
    expect(contMsg).toBeTruthy();
    expect(contMsg!.continuation_query).toBe("図のタイトルを変えて");
    expect(contMsg!.prior_statistical_results).toMatchObject({
      test: "welch_t",
      p_value: 0.023,
    });
    expect(String(contMsg!.prior_r_script)).toContain("t.test(sbp_mmhg ~ sex");
    // 継続は系譜 intent を再利用する＝Planner を呼ばない。
    expect(contMsg!.intent_object).toMatchObject({ objective: "between_group_comparison" });

    // 「＋ 新しい解析」→ 次の1通は intent に戻る（文脈リセット）。
    await page.getByTestId("new-analysis").click();
    await expect(chip).toContainText("新しい解析");
    await expect(page.getByTestId("chat-send")).toContainText("送信");

    await page.getByTestId("chat-input").fill("別の解析をしたい");
    await page.getByTestId("chat-send").click();
    // intent フローに戻ると新たな confirm バブルが出る（継続なら proposal 直行）。
    // 初回の confirm と合わせて 2 個になるのを待つ＝intent 経路を確定的に検証。
    await expect(page.getByTestId("chat-confirm")).toHaveCount(2);
    // 新規ターンは prompt のみ（intent_object も continuation_query も持たない）。
    const lastMsg = chatMessages[chatMessages.length - 1];
    expect(lastMsg.continuation_query ?? "").toBe("");
    expect(hasIntentObject(lastMsg)).toBe(false);

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("継続生成の失敗時に reason が表示される（無言失敗禁止 §5）", async ({ page }) => {
    await page.routeWebSocket(/\/ws\/console/, (ws) => {
      ws.onMessage(() => {
        ws.send(JSON.stringify({ type: "exit", text: "", exit_code: 0 }));
        ws.close();
      });
    });

    // The follow-up turn streams an error frame (never silent, §5).
    await routeWsChat(page, (msg) => {
      if (msg.continuation_query) {
        return [{ type: "error", reason: "CONTINUATION_LLM_UNAVAILABLE" }];
      }
      if (hasIntentObject(msg)) {
        return proposalFrames(INITIAL_PROPOSE.analysis_proposal);
      }
      return [{ type: "confirm", intent_object: INTENT_RESPONSE.intent_object }];
    });
    await page.route("**/api/run", (r) => r.fulfill({ json: RUN_RESPONSE }));
    await page.route("**/api/visualize", (r) =>
      r.fulfill({ json: { execution_id: "viz", figures: [], error_detail: null } }),
    );

    await connect(page);
    await runInitial(page);
    await expect(page.getByTestId("base-chip")).toContainText("welch_t");

    await page.getByTestId("chat-input").fill("タイトルを変えて");
    await page.getByTestId("chat-send").click();

    const err = page.getByTestId("chat-error");
    await expect(err).toBeVisible();
    await expect(err).toContainText("CONTINUATION_LLM_UNAVAILABLE");
  });
});
