import { expect, test, type Page } from "@playwright/test";

// 解析対象データの可視化 + ファイル一覧のカテゴリ分け。
// 1) 登録済みデータセットは GET /api/dataset で復元され、ファイルペイン最上部の
//    バナー（📌 解析対象データ）とヘッダバッジ（ファイル名）に常時表示される。
// 2) 一覧はデータ/図/スクリプト/ログ・その他にグループ化され、データが常に先頭。
//    フィルタチップで種別を絞り込める（ログ増殖でデータが埋もれる問題への対処）。
// API はスタブ（design §6）。

const DATASET = {
  dataset_id: "uploaded_dataset",
  source_name: "clinical_trial_2026.csv",
  registered_at: "2026-07-09T00:00:00+00:00",
  row_count: 150,
  column_count: 5,
  columns: [
    {
      var_n: "var_1",
      original_name: "sex",
      inferred_type: "categorical_binary",
      missing_count: 0,
      missing_rate_pct: 0,
    },
  ],
};

const FILES = [
  { path: "run_20260709.log", size_bytes: 900, modified: "2026-07-09T00:05:00+00:00", kind: "text" },
  { path: "r_output/result.json", size_bytes: 300, modified: "2026-07-09T00:04:00+00:00", kind: "text" },
  { path: "analysis_ab12.R", size_bytes: 120, modified: "2026-07-09T00:03:00+00:00", kind: "text" },
  { path: "viz_output/fig1.png", size_bytes: 69, modified: "2026-07-09T00:02:00+00:00", kind: "image" },
  { path: "dataset.csv", size_bytes: 4000, modified: "2026-07-09T00:01:00+00:00", kind: "text" },
  { path: "uploads/protocol_memo.txt", size_bytes: 50, modified: "2026-07-09T00:00:30+00:00", kind: "text" },
];

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByTestId("open-settings-from-chat").click();
  await page.getByTestId("settings-token-input").fill("test-token-abc");
  await page.getByTestId("settings-token-save").click();
  await page.getByTestId("settings-close").click();
}

test.describe("解析対象データの明示とファイル一覧のグループ化", () => {
  test("GET /api/dataset で復元 → バナー＋ヘッダバッジ＋解析対象バッジが出る", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await page.route("**/api/dataset", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: { dataset: DATASET } });
      }
      return r.fallback();
    });
    await page.route("**/api/files", (r) => r.fulfill({ json: { files: FILES } }));

    await connect(page);

    // バナー: ファイル名＋行×列が最上部に固定表示。
    const banner = page.getByTestId("active-dataset");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("clinical_trial_2026.csv");
    await expect(banner).toContainText("150行 × 5列");

    // ヘッダバッジもファイル名を表示（「取り込み済み」ではなくどのファイルか）。
    await expect(page.getByTestId("dataset-badge")).toContainText(
      "clinical_trial_2026.csv",
    );

    // 一覧内の dataset.csv 行に「解析対象」バッジ。
    await expect(page.getByTestId("file-target-badge")).toBeVisible();

    // バナーの「変更」ボタン → 解析データモーダルが開く。
    await page.getByTestId("active-dataset-change").click();
    await expect(page.getByTestId("dataset-modal")).toBeVisible();
    await page.getByTestId("dataset-close").click();

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("未登録なら未登録バナー → 「取り込む」でモーダルが開く", async ({ page }) => {
    await page.route("**/api/dataset", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: { dataset: null } });
      }
      return r.fallback();
    });
    await page.route("**/api/files", (r) => r.fulfill({ json: { files: [] } }));

    await connect(page);

    const empty = page.getByTestId("active-dataset-empty");
    await expect(empty).toBeVisible();
    await expect(empty).toContainText("解析対象データは未登録です");
    await page.getByTestId("active-dataset-register").click();
    await expect(page.getByTestId("dataset-modal")).toBeVisible();
  });

  test("一覧がデータ→図→スクリプト→ログにグループ化され、チップで絞り込める", async ({
    page,
  }) => {
    await page.route("**/api/dataset", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: { dataset: DATASET } });
      }
      return r.fallback();
    });
    await page.route("**/api/files", (r) => r.fulfill({ json: { files: FILES } }));

    await connect(page);
    const list = page.getByTestId("files-list");
    await expect(list).toBeVisible();

    // グループが固定順で並ぶ（mtime 最新のログが先頭に来ても、データが最上位）。
    const groups = page.locator(".filetree__group");
    await expect(groups).toHaveCount(4);
    await expect(groups.nth(0)).toContainText("データ");
    await expect(groups.nth(0)).toContainText("dataset.csv");
    await expect(groups.nth(0)).toContainText("uploads/protocol_memo.txt");
    await expect(groups.nth(1)).toContainText("図");
    await expect(groups.nth(2)).toContainText("スクリプト");
    await expect(groups.nth(3)).toContainText("ログ・その他");
    await expect(groups.nth(3)).toContainText("run_20260709.log");

    // 「データ」チップで絞り込み → データ以外が消える。
    await page.getByTestId("files-filter-data").click();
    await expect(page.locator(".filetree__group")).toHaveCount(1);
    await expect(list).toContainText("dataset.csv");
    await expect(list).not.toContainText("run_20260709.log");

    // 同じチップをもう一度 → 全件表示に戻る。
    await page.getByTestId("files-filter-data").click();
    await expect(page.locator(".filetree__group")).toHaveCount(4);
  });
});
