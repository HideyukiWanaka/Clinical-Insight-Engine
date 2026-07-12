import { expect, test, type Page } from "@playwright/test";
import { installStandardChat } from "./support/wsChat";

// Phase 8 (R8-2): ファイルツリー（§3.4 読み取り専用）。GET /api/files の一覧、
// GET /api/files/content のプレビュー（text→<pre><code> / image→<img>）、
// ダウンロード。削除UIは置かない（§3.4）。run 後に一覧が更新される（refreshKey）。
// 取得失敗は理由を表示（無言失敗禁止 §5）。API はスタブ（design §6）。

const PNG_FIXTURE = "tests/e2e/fixtures/pixel.png";

const INTENT_RESPONSE = {
  execution_id: "exec-p8-2",
  intent_object: { objective: "between_group_comparison" },
  confidence_score: 0.9,
  requires_human_clarification: false,
  clarification_options: [],
};
const PROPOSE_RESPONSE = {
  execution_id: "exec-p8-2",
  analysis_proposal: {
    explanation_markdown: "t検定を提案します。",
    code_candidates: [
      { candidate_id: "c1", label: "Welch t検定", r_code: "t.test(sbp_mmhg ~ sex, data = df)" },
    ],
    recommended_candidate_id: "c1",
  },
  r_script_provenance: { llm_generated: true, from_cache: false, reason: "" },
};
const RUN_RESPONSE = {
  execution_id: "run-p8-2",
  execution_result: { status: "success", exit_code: 0, duration_ms: 30 },
  statistical_results: { test: "welch_t", p_value: 0.03 },
  statistical_results_reason: null,
  generated_files: ["output/fig_group.png"],
  workspace_summary: null,
  error_detail: null,
};

async function connect(page: Page): Promise<void> {
  // Chat streams over WS /ws/chat (install before goto). High confidence →
  // intent echo + proposal directly.
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
}

test.describe("Phase 8 — ファイルツリー（§3.4）", () => {
  test("一覧→text/imageプレビュー→DL、削除UIなし、run後に更新", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    // File listing grows after the run (proves refreshKey re-fetch).
    let listCalls = 0;
    await page.route("**/api/files", (r) => {
      listCalls += 1;
      const files = [
        { path: "analysis.R", size_bytes: 120, modified: "2026-07-08T00:00:00+00:00", kind: "text" },
      ];
      if (listCalls > 1) {
        files.unshift({
          path: "output/fig_group.png",
          size_bytes: 69,
          modified: "2026-07-08T00:01:00+00:00",
          kind: "image",
        });
      }
      return r.fulfill({ json: { files } });
    });
    await page.route("**/api/files/content**", (r) => {
      const url = new URL(r.request().url());
      const p = url.searchParams.get("path") ?? "";
      if (p.endsWith(".png")) {
        return r.fulfill({ contentType: "image/png", path: PNG_FIXTURE });
      }
      return r.fulfill({ json: { text: "t.test(sbp_mmhg ~ sex, data = df)", language: "r" } });
    });

    await connect(page);

    // Mount + connected → listing appears.
    const list = page.getByTestId("files-list");
    await expect(list).toBeVisible();
    await expect(list).toContainText("analysis.R");

    // 削除UIが無い（§3.4 read-only）。
    await expect(page.getByTestId("file-delete")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "削除" })).toHaveCount(0);

    // text をクリック → コードプレビュー。
    await page.getByTestId("file-item").first().click();
    await expect(page.getByTestId("file-text")).toContainText("t.test(sbp_mmhg ~ sex");

    // ダウンロードボタンが機能する。
    const dl = page.waitForEvent("download");
    await page.getByTestId("file-download").click();
    await dl;

    // run で図を生成 → refreshKey で一覧が更新され png が現れる。
    await page.route("**/api/run", (r) => r.fulfill({ json: RUN_RESPONSE }));
    await page.route("**/api/visualize", (r) =>
      r.fulfill({ json: { execution_id: "viz", figures: [], error_detail: null } }),
    );

    await page.getByTestId("chat-input").fill("男女で収縮期血圧を比べたい");
    await page.getByTestId("chat-send").click();
    await page.getByTestId("candidate-run").click();

    await expect(page.getByTestId("files-list")).toContainText("output/fig_group.png");

    // png をクリック → 画像表示（ファイルツリー内に限定）。
    await page
      .getByTestId("files-list")
      .getByRole("button", { name: "output/fig_group.png" })
      .click();
    await expect(page.getByTestId("file-image")).toBeVisible();

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("content 取得が 400（パス不正等）→ 理由表示（無言失敗禁止 §5）", async ({ page }) => {
    await page.route("**/api/files", (r) =>
      r.fulfill({
        json: {
          files: [
            { path: "bad.txt", size_bytes: 10, modified: "2026-07-08T00:00:00+00:00", kind: "text" },
          ],
        },
      }),
    );
    await page.route("**/api/files/content**", (r) =>
      r.fulfill({
        status: 400,
        json: {
          detail: {
            error_code: "PATH_TRAVERSAL",
            message: "Path escapes the workspace directory.",
            detail: "../etc は許可されていません。",
          },
        },
      }),
    );

    await connect(page);
    await page.getByTestId("file-item").first().click();

    const err = page.getByTestId("file-preview-error");
    await expect(err).toBeVisible();
    await expect(err).toContainText("Path escapes the workspace directory.");
  });
});
