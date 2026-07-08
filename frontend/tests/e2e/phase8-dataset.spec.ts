import { expect, test, type Page } from "@playwright/test";

// Phase 8 (R8-1): 解析データ投入口。Header「解析データ」→ モーダル → CSV アップロード
// → 集計メタ（列名エイリアス・型・欠測）のみを表示する。行データ（セル値）は DOM に
// 一切出さない（§5, CLAUDE.md inject_raw_data_rows=False）。以降の POST /api/intent に
// dataset_uploaded:true が載る。失敗（空/PII拒否）は理由を表示（無言失敗禁止 §5）。
//
// API はスタブ（design §6）。dataset.csv の中身はサーバ側で集計されるため、フロントの
// 責務は「サーバが返す集計メタだけを描画する」こと。フィクスチャに置いた SENTINEL 値が
// 画面に出ない＝アップロードした生データをフロントが echo していないことを示す。

const CSV_FIXTURE = "tests/e2e/fixtures/sample_data.csv";

// Aggregate-only response (build_dataset_context の columns 形。行値は一切含めない)。
const DATASET_RESPONSE = {
  dataset_id: "uploaded_dataset",
  row_count: 2,
  column_count: 3,
  columns: [
    { var_n: "var_1", inferred_type: "categorical_binary", missing_count: 0, missing_rate_pct: 0 },
    { var_n: "var_2", inferred_type: "continuous", missing_count: 0, missing_rate_pct: 0 },
    { var_n: "var_3", inferred_type: "continuous", missing_count: 1, missing_rate_pct: 50 },
  ],
};

const INTENT_RESPONSE = {
  execution_id: "exec-p8-1",
  intent_object: {
    objective: "between_group_comparison",
    natural_language_summary: "男女間で収縮期血圧を比較します。",
  },
  confidence_score: 0.9,
  requires_human_clarification: false,
  clarification_options: [],
};

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("セッショントークン").fill("test-token-abc");
  await page.getByRole("button", { name: "設定" }).click();
}

test.describe("Phase 8 — データセット投入（§3.1 前提 / §5）", () => {
  test("モーダルでCSVアップロード→列メタ表示、行データは出ない、intentにdataset_uploaded:true", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await connect(page);
    await page.route("**/api/dataset", (r) => r.fulfill({ json: DATASET_RESPONSE }));

    // Header「解析データ」→ モーダルが開く。
    await page.getByTestId("open-dataset").click();
    await expect(page.getByTestId("dataset-modal")).toBeVisible();

    // ファイル選択 → アップロード → 列メタ（テーブル）が出る。
    await page.getByTestId("dataset-file-input").setInputFiles(CSV_FIXTURE);
    const columns = page.getByTestId("dataset-columns");
    await expect(columns).toBeVisible();
    await expect(columns).toContainText("var_1");
    await expect(columns).toContainText("continuous");
    await expect(columns).toContainText("50"); // missing_rate_pct

    // 生データ（セル値）が DOM に一切出ない（§5）。
    await expect(page.locator("body")).not.toContainText("SECRET_PATIENT_VALUE");
    await expect(page.locator("body")).not.toContainText("sbp_mmhg"); // real col name is aliased

    // Header にバッジ、閉じる。
    await expect(page.getByTestId("dataset-badge")).toBeVisible();
    await page.getByTestId("dataset-close").click();
    await expect(page.getByTestId("dataset-modal")).toHaveCount(0);

    // 以降の intent に dataset_uploaded:true が載る。
    let intentBody: Record<string, unknown> | null = null;
    await page.route("**/api/intent", (r) => {
      intentBody = r.request().postDataJSON() as Record<string, unknown>;
      return r.fulfill({ json: INTENT_RESPONSE });
    });
    await page.getByTestId("chat-input").fill("男女で収縮期血圧を比べたい");
    await page.getByTestId("chat-send").click();
    await expect(page.getByTestId("chat-confirm")).toBeVisible();
    expect(intentBody).not.toBeNull();
    expect(intentBody!.dataset_uploaded).toBe(true);

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("空/不正CSVで 400 → 理由が画面に出る（無言失敗禁止 §5）", async ({ page }) => {
    await connect(page);
    await page.route("**/api/dataset", (r) =>
      r.fulfill({
        status: 400,
        json: {
          detail: {
            error_code: "EMPTY_DATASET",
            message: "Uploaded dataset is empty.",
            detail: "CSV に行がありません。",
          },
        },
      }),
    );

    await page.getByTestId("open-dataset").click();
    await page.getByTestId("dataset-file-input").setInputFiles(CSV_FIXTURE);

    const err = page.getByTestId("dataset-error");
    await expect(err).toBeVisible();
    await expect(err).toContainText("Uploaded dataset is empty.");
    await expect(err).toContainText("CSV に行がありません。");
    // 失敗時はバッジも付かない（未取り込み）。
    await expect(page.getByTestId("dataset-badge")).toHaveCount(0);
  });
});
