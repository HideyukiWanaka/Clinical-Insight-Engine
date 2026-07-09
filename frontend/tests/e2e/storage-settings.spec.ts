import { expect, test, type Page } from "@playwright/test";

// 保存先ルート（workspace_directory）の常時表示 + 変更UI。
// ファイルペイン下部に固定バーで保存先パスを表示（GET /api/settings/storage）。
// 変更は .env に永続化されるのみ — 実行中プロセスは再起動まで現在のパスを使い続ける
// （build_dataset_context の split-brain 回避のため）。UIはその旨を明示する。
// API はスタブ（design §6）。

const STORAGE = {
  workspace_directory: "/home/user/Documents/CIE/workspace",
  database_filepath: "/home/user/Documents/CIE/cie_database.db",
  pending_workspace_directory: null,
};

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByTestId("open-settings-from-chat").click();
  await page.getByTestId("settings-token-input").fill("test-token-abc");
  await page.getByTestId("settings-token-save").click();
  await page.getByTestId("settings-close").click();
}

test.describe("保存先ルートの常時表示と変更（再起動で反映）", () => {
  test("ファイルペイン下部に保存先パスが常時表示される", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await page.route("**/api/settings/storage", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: STORAGE });
      }
      return r.fallback();
    });
    await page.route("**/api/files", (r) => r.fulfill({ json: { files: [] } }));
    await page.route("**/api/dataset", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: { dataset: null } });
      }
      return r.fallback();
    });

    await connect(page);

    const bar = page.getByTestId("storage-bar");
    await expect(bar).toBeVisible();
    await expect(page.getByTestId("storage-bar-path")).toContainText(
      "/home/user/Documents/CIE/workspace",
    );

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("変更→保存すると「次回起動から反映」の注記が出て、現在のパス表示は変わらない", async ({
    page,
  }) => {
    await page.route("**/api/files", (r) => r.fulfill({ json: { files: [] } }));
    await page.route("**/api/dataset", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: { dataset: null } });
      }
      return r.fallback();
    });

    let stored: {
      workspace_directory: string;
      database_filepath: string;
      pending_workspace_directory: string | null;
    } = { ...STORAGE };
    await page.route("**/api/settings/storage", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: stored });
      }
      return r.fallback();
    });
    await page.route("**/api/settings/storage/workspace_directory", (r) => {
      const body = r.request().postDataJSON() as { directory: string };
      stored = { ...stored, pending_workspace_directory: body.directory };
      return r.fulfill({ json: stored });
    });

    await connect(page);
    await expect(page.getByTestId("storage-bar")).toBeVisible();

    await page.getByTestId("storage-bar-edit").click();
    const input = page.getByTestId("storage-bar-input");
    await input.fill("/home/user/Documents/CIE-new/workspace");
    await page.getByTestId("storage-bar-save").click();

    // 現在アクティブなパスは変わらない。
    await expect(page.getByTestId("storage-bar-path")).toContainText(
      "/home/user/Documents/CIE/workspace",
    );
    // 「次回起動から反映」の注記に新パスが出る。
    const pending = page.getByTestId("storage-bar-pending");
    await expect(pending).toBeVisible();
    await expect(pending).toContainText("/home/user/Documents/CIE-new/workspace");
    await expect(pending).toContainText("次回起動");
  });

  test("不正なパス（相対パス等）→400の理由が表示される（無言失敗禁止 §5）", async ({
    page,
  }) => {
    await page.route("**/api/files", (r) => r.fulfill({ json: { files: [] } }));
    await page.route("**/api/dataset", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: { dataset: null } });
      }
      return r.fallback();
    });
    await page.route("**/api/settings/storage", (r) => {
      if (r.request().method() === "GET") {
        return r.fulfill({ json: STORAGE });
      }
      return r.fallback();
    });
    await page.route("**/api/settings/storage/workspace_directory", (r) =>
      r.fulfill({
        status: 400,
        json: {
          detail: {
            error_code: "RELATIVE_PATH_REJECTED",
            message: "絶対パスを指定してください。",
            detail: "received='relative/path'",
          },
        },
      }),
    );

    await connect(page);
    await page.getByTestId("storage-bar-edit").click();
    await page.getByTestId("storage-bar-input").fill("relative/path");
    await page.getByTestId("storage-bar-save").click();

    const err = page.getByTestId("storage-bar-error");
    await expect(err).toBeVisible();
    await expect(err).toContainText("絶対パスを指定してください。");
  });
});
