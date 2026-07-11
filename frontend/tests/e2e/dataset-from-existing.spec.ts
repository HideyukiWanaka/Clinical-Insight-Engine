import { expect, test, type Page } from "@playwright/test";

// ワークスペース内の既存ファイル（アップロード済み・以前の実行で生成済みなど）を
// 再アップロードなしで解析データとして選択できる（POST /api/dataset/from_existing）。
// モーダルは GET /api/files から CSV/Excel 候補を一覧し、「このファイルを使う」で
// 即登録（CSV）またはシート選択（Excel、既存の confirm フローに合流）する。
// API はスタブ（design §6）。

const FILES = [
  { path: "run_20260709.log", size_bytes: 900, modified: "2026-07-09T00:05:00+00:00", kind: "text" },
  { path: "analysis_ab12.R", size_bytes: 120, modified: "2026-07-09T00:03:00+00:00", kind: "text" },
  { path: "uploads/cohort.csv", size_bytes: 4000, modified: "2026-07-09T00:01:00+00:00", kind: "text" },
  { path: "legacy_data.xlsx", size_bytes: 5000, modified: "2026-07-08T00:00:00+00:00", kind: "other" },
];

const CSV_DATASET_RESPONSE = {
  dataset_id: "uploaded_dataset",
  source_name: "uploads/cohort.csv",
  row_count: 2,
  column_count: 2,
  columns: [
    { var_n: "var_1", original_name: "sex", inferred_type: "categorical_binary", missing_count: 0, missing_rate_pct: 0 },
    { var_n: "var_2", original_name: "age", inferred_type: "continuous", missing_count: 0, missing_rate_pct: 0 },
  ],
};

const EXCEL_INSPECT_RESPONSE = {
  upload_id: "existing-upload-1",
  sheet_names: ["Sheet1", "Sheet2"],
};

const EXCEL_CONFIRM_RESPONSE = {
  dataset_id: "uploaded_dataset",
  source_name: "legacy_data.xlsx / Sheet1",
  row_count: 10,
  column_count: 4,
  columns: [
    { var_n: "var_1", original_name: "group", inferred_type: "categorical_binary", missing_count: 0, missing_rate_pct: 0 },
  ],
};

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByTestId("open-settings-from-chat").click();
  await page.getByTestId("settings-token-input").fill("test-token-abc");
  await page.getByTestId("settings-token-save").click();
  await page.getByTestId("settings-close").click();
}

test.describe("既存ファイルを解析データとして選択（再アップロード不要）", () => {
  test("CSV: 一覧から選択→即登録され列メタが表示される", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await page.route("**/api/dataset", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: { dataset: null } });
      }
      return r.fallback();
    });
    await page.route("**/api/files", (r) => r.fulfill({ json: { files: FILES } }));
    let fromExistingBody: Record<string, unknown> | null = null;
    await page.route("**/api/dataset/from_existing", (r) => {
      fromExistingBody = r.request().postDataJSON() as Record<string, unknown>;
      return r.fulfill({ json: CSV_DATASET_RESPONSE });
    });

    await connect(page);
    await page.getByTestId("open-dataset").click();
    await expect(page.getByTestId("dataset-modal")).toBeVisible();

    // 既存ファイル一覧に CSV/Excel だけが候補として出る（ログ・Rスクリプトは出ない）。
    const existing = page.getByTestId("dataset-existing-files");
    await expect(existing).toBeVisible();
    await expect(existing).toContainText("uploads/cohort.csv");
    await expect(existing).toContainText("legacy_data.xlsx");
    await expect(existing).not.toContainText("run_20260709.log");
    await expect(existing).not.toContainText("analysis_ab12.R");

    await page
      .getByTestId("dataset-existing-path")
      .filter({ hasText: "uploads/cohort.csv" })
      .locator("..")
      .getByTestId("dataset-existing-use")
      .click();

    await expect(page.getByTestId("dataset-columns")).toBeVisible();
    await expect(page.getByTestId("dataset-summary")).toContainText("行数 2");
    expect(fromExistingBody).toEqual({ path: "uploads/cohort.csv" });

    // ヘッダーバッジにも選択したファイル名が出る。
    await page.getByTestId("dataset-close").click();
    await expect(page.getByTestId("dataset-badge")).toContainText("uploads/cohort.csv");

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("Excel: 既存ファイルを選ぶとシート選択UIに合流し、confirmで登録される", async ({
    page,
  }) => {
    await page.route("**/api/dataset", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: { dataset: null } });
      }
      return r.fallback();
    });
    await page.route("**/api/files", (r) => r.fulfill({ json: { files: FILES } }));
    await page.route("**/api/dataset/from_existing", (r) =>
      r.fulfill({ json: EXCEL_INSPECT_RESPONSE }),
    );
    let confirmBody: Record<string, unknown> | null = null;
    await page.route("**/api/dataset/excel/confirm", (r) => {
      confirmBody = r.request().postDataJSON() as Record<string, unknown>;
      return r.fulfill({ json: EXCEL_CONFIRM_RESPONSE });
    });

    await connect(page);
    await page.getByTestId("open-dataset").click();

    await page
      .getByTestId("dataset-existing-path")
      .filter({ hasText: "legacy_data.xlsx" })
      .locator("..")
      .getByTestId("dataset-existing-use")
      .click();

    // アップロード時と同じシート選択UIが出る。
    const sheetRow = page.getByTestId("excel-sheet-select-row");
    await expect(sheetRow).toBeVisible();
    await expect(sheetRow).toContainText("legacy_data.xlsx のシートを選択");
    await page.getByTestId("excel-sheet-select").selectOption("Sheet1");
    await page.getByTestId("excel-sheet-confirm").click();

    await expect(page.getByTestId("dataset-columns")).toBeVisible();
    expect(confirmBody).toEqual({
      upload_id: "existing-upload-1",
      sheet_name: "Sheet1",
    });
  });

  test("候補ファイルが無ければセクション自体が表示されない", async ({ page }) => {
    await page.route("**/api/dataset", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: { dataset: null } });
      }
      return r.fallback();
    });
    await page.route("**/api/files", (r) =>
      r.fulfill({
        json: {
          files: [
            { path: "run.log", size_bytes: 10, modified: "2026-07-09T00:00:00+00:00", kind: "text" },
          ],
        },
      }),
    );

    await connect(page);
    await page.getByTestId("open-dataset").click();
    await expect(page.getByTestId("dataset-modal")).toBeVisible();
    await expect(page.getByTestId("dataset-existing-files")).toHaveCount(0);
  });
});
