import { expect, test, type Page } from "@playwright/test";

// Phase 9 (R9-1): 参考資料の取り込み〜人間承認フロー。Header「参考資料」→ 別モーダル →
// ① アップロード → ② ドラフトレビュー → [承認]/[却下]。AI は提案まで・登録は必ず人間
// （ADR-0002/0003）。患者データ混入は 422 で拒否され、failed_checks を明示する
// （無言失敗禁止 §5）。API はスタブ（design §6）、フロントの責務は契約の配線と表示。

const REF_FIXTURE = "tests/e2e/fixtures/reference_paper.md";

const INGEST_RESPONSE = {
  draft_id: "draft-p9-1",
  extracted: {
    source_info: {
      title: "Effect of Intensive Blood-Pressure Control",
      year: 2015,
      doi: "10.1056/NEJMoa1511939",
      url: "https://example.org/sprint",
    },
    domain: "clinical",
    trust_level: "peer_reviewed",
    knowledge_items: [
      {
        statement: "Intensive SBP targeting below 120 mmHg reduces CV events.",
        direct_quote: "targeting a systolic pressure of less than 120 mm Hg",
        confidence: 0.92,
        caveats: "Higher rates of some adverse events.",
      },
      {
        // 低確信度 → 🟡 で強調される項目（design §2 閾値 0.7）。
        statement: "Applies broadly to all hypertensive populations.",
        direct_quote: "",
        confidence: 0.5,
        caveats: "Extrapolation beyond trial population.",
      },
    ],
  },
  extraction_limitations: ["OCR は未対応。図表内の数値は抽出されません。"],
};

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByTestId("open-settings-from-chat").click();
  await page.getByTestId("settings-token-input").fill("test-token-abc");
  await page.getByTestId("settings-token-save").click();
  await page.getByTestId("settings-close").click();
}

test.describe("Phase 9 — 参考資料 取り込み〜人間承認（§3.8 / §5）", () => {
  test("アップロード→ドラフトレビュー（原典/知識/限界/🟡）→承認で選択値送信・entry_id受領", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await connect(page);
    // 一覧は開いた時点で取得される（初期は空）。
    await page.route("**/api/knowledge", (r) => r.fulfill({ json: { entries: [] } }));
    await page.route("**/api/knowledge/ingest", (r) => r.fulfill({ json: INGEST_RESPONSE }));

    // Header「参考資料」→ 別モーダルが開く（解析データとは別入口）。
    await page.getByTestId("open-knowledge").click();
    await expect(page.getByTestId("knowledge-modal")).toBeVisible();

    // ① アップロード → ② ドラフトレビュー。
    await page.getByTestId("knowledge-file-input").setInputFiles(REF_FIXTURE);
    const draft = page.getByTestId("knowledge-draft");
    await expect(draft).toBeVisible();

    // 原典情報 / 知識項目 / 抽出の限界。
    await expect(page.getByTestId("knowledge-source-info")).toContainText(
      "Effect of Intensive Blood-Pressure Control",
    );
    await expect(page.getByTestId("knowledge-source-info")).toContainText("10.1056/NEJMoa1511939");
    await expect(page.getByTestId("knowledge-items")).toContainText("Intensive SBP targeting");
    await expect(page.getByTestId("knowledge-limitations")).toContainText("OCR は未対応");
    // confidence < 0.7 の項目に 🟡 が付く。
    await expect(page.getByTestId("knowledge-low-confidence").first()).toBeVisible();

    // 抽出値がセレクタの初期選択に反映される（人間が修正可）。
    await expect(page.getByTestId("knowledge-domain-select")).toHaveValue("clinical");
    await expect(page.getByTestId("knowledge-trust-select")).toHaveValue("peer_reviewed");

    // domain/trust_level を人間が修正して承認 → body に選択値が載る。
    await page.getByTestId("knowledge-domain-select").selectOption("statistics");
    await page.getByTestId("knowledge-trust-select").selectOption("regulatory");

    let approveBody: Record<string, unknown> | null = null;
    await page.route("**/api/knowledge/approve", (r) => {
      approveBody = r.request().postDataJSON() as Record<string, unknown>;
      return r.fulfill({ json: { entry_id: "inst-000042" } });
    });
    // 承認後の一覧再取得では登録済みエントリが返る。
    await page.unroute("**/api/knowledge");
    await page.route("**/api/knowledge", (r) =>
      r.fulfill({
        json: {
          entries: [
            {
              entry_id: "inst-000042",
              domain: "statistics",
              status: "active",
              trust_level: "regulatory",
              title: "Effect of Intensive Blood-Pressure Control",
            },
          ],
        },
      }),
    );

    await page.getByTestId("knowledge-approve").click();

    // approve body に人間の選択値が載る。approved_by_human は送らない（サーバが付与）。
    await expect(page.getByTestId("knowledge-approve-result")).toContainText("inst-000042");
    expect(approveBody).not.toBeNull();
    expect(approveBody!.draft_id).toBe("draft-p9-1");
    expect(approveBody!.domain).toBe("statistics");
    expect(approveBody!.trust_level).toBe("regulatory");
    expect(approveBody).not.toHaveProperty("approved_by_human");

    // 承認後、ドラフトは消え、一覧に反映される。
    await expect(page.getByTestId("knowledge-draft")).toHaveCount(0);
    await expect(page.getByTestId("knowledge-registry")).toContainText(
      "Effect of Intensive Blood-Pressure Control",
    );

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });

  test("患者データ混入→422→failed_checks を明示し、ドラフトに進まない（無言失敗禁止 §5）", async ({
    page,
  }) => {
    await connect(page);
    await page.route("**/api/knowledge", (r) => r.fulfill({ json: { entries: [] } }));
    await page.route("**/api/knowledge/ingest", (r) =>
      r.fulfill({
        status: 422,
        json: {
          detail: {
            error_code: "PII_DETECTED",
            message: "PII detected in reference document.",
            failed_checks: ["patient_name_scan", "mrn_scan"],
          },
        },
      }),
    );

    await page.getByTestId("open-knowledge").click();
    await page.getByTestId("knowledge-file-input").setInputFiles(REF_FIXTURE);

    const err = page.getByTestId("knowledge-ingest-error");
    await expect(err).toBeVisible();
    await expect(err).toContainText("患者データが検出されたため取り込めません");
    await expect(page.getByTestId("knowledge-failed-checks")).toContainText("patient_name_scan");
    await expect(page.getByTestId("knowledge-failed-checks")).toContainText("mrn_scan");
    // ドラフトには進まない。
    await expect(page.getByTestId("knowledge-draft")).toHaveCount(0);
  });

  test("却下は理由必須→理由入力後 rejected を確認（無言失敗禁止 §5）", async ({ page }) => {
    await connect(page);
    await page.route("**/api/knowledge", (r) => r.fulfill({ json: { entries: [] } }));
    await page.route("**/api/knowledge/ingest", (r) => r.fulfill({ json: INGEST_RESPONSE }));

    await page.getByTestId("open-knowledge").click();
    await page.getByTestId("knowledge-file-input").setInputFiles(REF_FIXTURE);
    await expect(page.getByTestId("knowledge-draft")).toBeVisible();

    // 理由未入力で却下 → 理由必須のメッセージ（API は呼ばれない）。
    await page.getByTestId("knowledge-reject").click();
    await expect(page.getByTestId("knowledge-decision-error")).toContainText(
      "却下理由を入力してください",
    );
    await expect(page.getByTestId("knowledge-draft")).toBeVisible();

    // 理由を入力して却下 → rejected、ドラフトが消える。
    let rejectBody: Record<string, unknown> | null = null;
    await page.route("**/api/knowledge/reject", (r) => {
      rejectBody = r.request().postDataJSON() as Record<string, unknown>;
      return r.fulfill({ json: { draft_id: "draft-p9-1", status: "rejected" } });
    });
    await page.getByTestId("knowledge-reject-reason").fill("出典が不明確なため");
    await page.getByTestId("knowledge-reject").click();

    await expect(page.getByTestId("knowledge-draft")).toHaveCount(0);
    expect(rejectBody).not.toBeNull();
    expect(rejectBody!.draft_id).toBe("draft-p9-1");
    expect(rejectBody!.reason).toBe("出典が不明確なため");
  });
});
