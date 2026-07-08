import { expect, test, type Page } from "@playwright/test";

// Phase 9 (R9-2): レジストリ一覧（読み取り専用）＋再索引＋入口配線。
// 一覧は trust バッジ付きで閲覧のみ（REST にアーカイブ API は無い — K-3）。
// 参考資料入口は解析データ入口と視覚的に分離（§5, K-1）。再索引の結果/失敗を正しく表示、
// 501 時は「未配線」を明示し過大表現しない（K-6）。API はスタブ（design §6）。

const LIST_RESPONSE = {
  entries: [
    {
      entry_id: "inst-000001",
      domain: "clinical",
      status: "active",
      trust_level: "regulatory",
      title: "ACC/AHA Hypertension Guideline",
    },
    {
      entry_id: "inst-000002",
      domain: "statistics",
      status: "active",
      trust_level: "experimental",
      title: "A Preprint on Bayesian Adjustment",
    },
  ],
};

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("セッショントークン").fill("test-token-abc");
  await page.getByRole("button", { name: "設定" }).click();
}

test.describe("Phase 9 — レジストリ一覧・再索引・入口分離（§3.8/§3.9 / §5）", () => {
  test("参考資料入口が解析データ入口と分離し、一覧は trust バッジ付き読み取り専用", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await connect(page);
    await page.route("**/api/knowledge", (r) => r.fulfill({ json: LIST_RESPONSE }));

    // §5: 「解析データ」と「参考資料」は別ボタンとして両方存在する（入口分離）。
    await expect(page.getByTestId("open-dataset")).toBeVisible();
    await expect(page.getByTestId("open-knowledge")).toBeVisible();

    // 参考資料 → knowledge モーダル（dataset モーダルではない）。
    await page.getByTestId("open-knowledge").click();
    await expect(page.getByTestId("knowledge-modal")).toBeVisible();
    await expect(page.getByTestId("dataset-modal")).toHaveCount(0);

    // 一覧が trust バッジ付きで表示される。
    const registry = page.getByTestId("knowledge-registry");
    await expect(registry).toBeVisible();
    await expect(registry).toContainText("ACC/AHA Hypertension Guideline");
    await expect(registry).toContainText("A Preprint on Bayesian Adjustment");
    await expect(registry).toContainText("🟢"); // regulatory
    await expect(registry).toContainText("🔴"); // experimental

    // 読み取り専用: 削除/アーカイブ UI は存在しない（K-3）。
    await expect(page.getByRole("button", { name: /アーカイブ/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /削除/ })).toHaveCount(0);

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("再索引→chunks 数を表示", async ({ page }) => {
    await connect(page);
    await page.route("**/api/knowledge", (r) => r.fulfill({ json: LIST_RESPONSE }));
    await page.route("**/api/knowledge/reindex", (r) =>
      r.fulfill({ json: { status: "reindexed", chunks: 128 } }),
    );

    await page.getByTestId("open-knowledge").click();
    await page.getByTestId("knowledge-reindex").click();

    await expect(page.getByTestId("knowledge-reindex-result")).toContainText("128");
  });

  test("再索引 501→「対応retriever未配線」を明示（過大表現しない K-6）", async ({ page }) => {
    await connect(page);
    await page.route("**/api/knowledge", (r) => r.fulfill({ json: LIST_RESPONSE }));
    await page.route("**/api/knowledge/reindex", (r) =>
      r.fulfill({
        status: 501,
        json: {
          detail: {
            error_code: "NOT_IMPLEMENTED",
            message: "The wired retriever does not support reindexing.",
            detail: "Expected an EmbeddingReferenceLibrary (ADR-0005).",
          },
        },
      }),
    );

    await page.getByTestId("open-knowledge").click();
    await page.getByTestId("knowledge-reindex").click();

    const err = page.getByTestId("knowledge-reindex-error");
    await expect(err).toBeVisible();
    await expect(err).toContainText("未配線");
    // 承認自体は成立済み — 結果表示は出ない。
    await expect(page.getByTestId("knowledge-reindex-result")).toHaveCount(0);
  });
});
