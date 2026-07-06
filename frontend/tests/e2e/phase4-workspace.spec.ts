import { expect, test, type Page } from "@playwright/test";

// Phase 4 (R4-1): Workspace/Data pane renders the persisted R variables
// (name・型・要約) from workspace_summary, and "ワークスペースをリセット" clears
// the persisted .RData via POST /api/workspace/reset
// (spec/runtime-workspace-persistence.md §2, §3).
//
// API/WS are stubbed; the real-R persistence path is covered by
// scratchpad/harness_workspace_persist.py against a live backend.

const INTENT_RESPONSE = {
  execution_id: "exec-p4-1",
  intent_object: { objective: "between_group_comparison" },
  confidence_score: 0.9,
  requires_human_clarification: false,
  clarification_options: [],
};

const PROPOSE_RESPONSE = {
  execution_id: "exec-p4-1",
  analysis_proposal: {
    explanation_markdown: "派生列を作る提案です。",
    code_candidates: [
      { candidate_id: "c1", label: "bmi_cat", r_code: "data$bmi_cat <- cut(data$bmi, c(0,25,100))" },
    ],
    recommended_candidate_id: "c1",
  },
  r_script_provenance: { llm_generated: true, from_cache: false, reason: "" },
};

// workspace_summary uses the name → {class, summary} shape the runtime agent
// flattens from workspace_summary.json (spec §2.1).
const RUN_RESPONSE = {
  execution_id: "run-p4",
  execution_result: { status: "success", exit_code: 0, duration_ms: 40 },
  statistical_results: null,
  statistical_results_reason: null,
  generated_files: [],
  workspace_summary: {
    data: { class: "data.frame", summary: "'data.frame': 191 obs. of 9 variables" },
  },
  error_detail: null,
};

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("セッショントークン").fill("test-token-abc");
  await page.getByRole("button", { name: "設定" }).click();
  await page.route("**/api/intent", (r) => r.fulfill({ json: INTENT_RESPONSE }));
  await page.route("**/api/propose", (r) => r.fulfill({ json: PROPOSE_RESPONSE }));
}

async function runCandidate(page: Page): Promise<void> {
  await page.getByTestId("chat-input").fill("BMIカテゴリを作りたい");
  await page.getByTestId("chat-send").click();
  await page.getByTestId("confirm-propose").click();
  const candidate = page.getByTestId("code-candidate");
  await expect(candidate).toBeVisible();
  await candidate.getByTestId("candidate-run").click();
}

test.describe("Phase 4 — ワークスペース永続化の可視化 / リセット", () => {
  test("run→ 変数一覧（名前・型・要約）を表示、リセットで消える", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await page.routeWebSocket(/\/ws\/console/, (ws) => {
      ws.onMessage(() => {
        ws.send(JSON.stringify({ type: "exit", text: "", exit_code: 0 }));
        ws.close();
      });
    });

    await connect(page);

    // Assert the run request opts into persistence (persist_workspace: true).
    let persistFlag: unknown = undefined;
    await page.route("**/api/run", (r) => {
      persistFlag = (r.request().postDataJSON() as { persist_workspace?: boolean })
        .persist_workspace;
      return r.fulfill({ json: RUN_RESPONSE });
    });

    let resetCalled = false;
    await page.route("**/api/workspace/reset", (r) => {
      resetCalled = true;
      return r.fulfill({ json: { removed: [".RData", "workspace_summary.json"] } });
    });

    await runCandidate(page);

    // Workspace/Data shows the variable name, its R type, and the str() summary.
    const ws = page.getByTestId("workspace-data");
    await expect(ws).toContainText("data");
    await expect(ws).toContainText("data.frame");
    await expect(ws).toContainText("191 obs");
    expect(persistFlag).toBe(true);

    // リセット → endpoint hit, pane returns to the empty placeholder.
    await page.getByTestId("workspace-reset").click();
    await expect(page.getByTestId("workspace-empty")).toBeVisible();
    expect(resetCalled).toBe(true);

    expect(pageErrors, `uncaught page errors: ${pageErrors.join("\n")}`).toEqual([]);
  });
});
