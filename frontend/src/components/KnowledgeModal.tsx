import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type CieApiClient } from "../api/client";
import type {
  KnowledgeIngestResponse,
  KnowledgeItem,
  KnowledgeListEntry,
} from "../api/types";

interface KnowledgeModalProps {
  client: CieApiClient;
  connected: boolean;
  onClose: () => void;
}

// Enumerations kept in lock-step with cie/ui/components/knowledge_review.py so
// the React entry mirrors the Streamlit one (design §2 列挙値).
const TRUST_LEVELS = [
  "regulatory",
  "peer_reviewed",
  "institutional",
  "experimental",
] as const;
const DOMAINS = [
  "statistics",
  "clinical",
  "reporting",
  "R",
  "Python",
  "visualization",
] as const;
const TRUST_BADGE: Record<string, string> = {
  regulatory: "🟢",
  peer_reviewed: "🔵",
  institutional: "🟡",
  experimental: "🔴",
};
// Below this, an extracted item is flagged 🟡 for extra review attention.
const CONFIDENCE_THRESHOLD = 0.7;

interface UiError {
  message: string;
  detail?: string | null;
  failedChecks?: string[] | null;
  status?: number;
  errorCode?: string;
}

function toUiError(err: unknown, fallback: string): UiError {
  if (err instanceof ApiError) {
    return {
      message: err.message,
      detail: err.detail,
      failedChecks: err.failedChecks,
      status: err.status,
      errorCode: err.errorCode,
    };
  }
  return { message: fallback, detail: String((err as Error)?.message ?? err) };
}

/** 「参考資料」入口 — 知識取り込みパイプライン UI（§5: 解析データ入口とは別モーダル）。
 *  ① アップロード → ② ドラフトレビュー（人間承認/却下） → ③ レジストリ一覧（読み取り専用）。
 *  AI は提案まで・登録は必ず人間（ADR-0002/0003）。患者データ混入は 422 で拒否され、
 *  failed_checks を明示する（無言失敗禁止 §5）。バックエンドは無改修。 */
export function KnowledgeModal({ client, connected, onClose }: KnowledgeModalProps) {
  // ① upload
  const [draft, setDraft] = useState<KnowledgeIngestResponse | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [ingestError, setIngestError] = useState<UiError | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // ② draft review — selectors seeded from the extracted values, human-editable.
  const [domain, setDomain] = useState<string>(DOMAINS[0]);
  const [trustLevel, setTrustLevel] = useState<string>(TRUST_LEVELS[1]);
  const [rejectReason, setRejectReason] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [decisionError, setDecisionError] = useState<UiError | null>(null);
  const [approvedEntryId, setApprovedEntryId] = useState<string | null>(null);

  // ③ registry list + reindex
  const [entries, setEntries] = useState<KnowledgeListEntry[] | null>(null);
  const [listError, setListError] = useState<UiError | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [reindexResult, setReindexResult] = useState<string | null>(null);
  const [reindexError, setReindexError] = useState<UiError | null>(null);

  const loadEntries = useCallback(async () => {
    if (!connected) return;
    setListError(null);
    try {
      const res = await client.listKnowledge();
      setEntries(res.entries);
    } catch (err) {
      setListError(toUiError(err, "一覧の取得に失敗しました。"));
    }
  }, [client, connected]);

  // Load the read-only registry when the modal opens (承認後は再取得で反映)。
  useEffect(() => {
    void loadEntries();
  }, [loadEntries]);

  async function ingest(file: File) {
    if (ingesting) return;
    setIngestError(null);
    setApprovedEntryId(null);
    setIngesting(true);
    try {
      const res = await client.ingestKnowledge(file);
      setDraft(res);
      // Seed the selectors from the AI-extracted values (human may correct).
      if (TRUST_LEVELS.includes(res.extracted.trust_level as never)) {
        setTrustLevel(res.extracted.trust_level);
      }
      if (DOMAINS.includes(res.extracted.domain as never)) {
        setDomain(res.extracted.domain);
      }
    } catch (err) {
      setDraft(null);
      setIngestError(toUiError(err, "取り込みに失敗しました。"));
    } finally {
      setIngesting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function approve() {
    if (!draft || deciding) return;
    setDecisionError(null);
    setDeciding(true);
    try {
      const res = await client.approveKnowledge({
        draft_id: draft.draft_id,
        domain,
        trust_level: trustLevel,
      });
      setApprovedEntryId(res.entry_id);
      setDraft(null);
      setRejectReason("");
      await loadEntries();
    } catch (err) {
      setDecisionError(toUiError(err, "承認に失敗しました。"));
    } finally {
      setDeciding(false);
    }
  }

  async function reject() {
    if (!draft || deciding) return;
    if (!rejectReason.trim()) {
      setDecisionError({ message: "却下理由を入力してください。" });
      return;
    }
    setDecisionError(null);
    setDeciding(true);
    try {
      await client.rejectKnowledge({ draft_id: draft.draft_id, reason: rejectReason.trim() });
      setDraft(null);
      setRejectReason("");
    } catch (err) {
      setDecisionError(toUiError(err, "却下に失敗しました。"));
    } finally {
      setDeciding(false);
    }
  }

  async function reindex() {
    if (reindexing) return;
    setReindexError(null);
    setReindexResult(null);
    setReindexing(true);
    try {
      const res = await client.reindexKnowledge();
      setReindexResult(`再索引完了: ${res.chunks} chunks`);
    } catch (err) {
      setReindexError(toUiError(err, "再索引に失敗しました。"));
    } finally {
      setReindexing(false);
    }
  }

  return (
    <div
      className="modal__overlay"
      data-testid="knowledge-modal"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="modal knowledge-modal"
        role="dialog"
        aria-modal="true"
        aria-label="参考資料の取り込み"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__header knowledge-modal__header">
          <span>📚 参考資料（知識ベース）</span>
          <button
            type="button"
            className="icon-btn"
            data-testid="knowledge-close"
            aria-label="閉じる"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <div className="modal__body">
          <p className="modal__hint">
            論文・ガイドライン等を取り込み、AI 抽出ドラフトを
            <strong>人間がレビューして承認</strong>します（登録は人間のみ・ADR-0002/0003）。
            これは<strong>患者データではなく参考文献</strong>の入口です。患者データを混ぜると
            取り込み時に拒否されます（PIIスキャン）。
          </p>

          {!connected && (
            <div className="modal__note" data-testid="knowledge-need-token">
              先にチャットでセッショントークンを設定してください。
            </div>
          )}

          {/* ① アップロード ------------------------------------------------ */}
          <section className="knowledge-section">
            <h3 className="knowledge-section__title">① ドキュメントアップロード</h3>
            <div className="confirm-row">
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.md,.txt,.docx"
                aria-label="参考資料ファイル"
                data-testid="knowledge-file-input"
                disabled={ingesting || !connected}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void ingest(f);
                }}
              />
              {ingesting && <span className="modal__status">取り込み中…</span>}
            </div>

            {ingestError && (
              <div className="msg msg--error" data-testid="knowledge-ingest-error">
                <span className="msg__role">取り込めません</span>
                {ingestError.failedChecks && ingestError.failedChecks.length > 0
                  ? "患者データが検出されたため取り込めません。参考資料に患者データを含めないでください。"
                  : ingestError.message}
                {ingestError.failedChecks && ingestError.failedChecks.length > 0 && (
                  <div className="knowledge-failed-checks" data-testid="knowledge-failed-checks">
                    検出項目: {ingestError.failedChecks.join(", ")}
                  </div>
                )}
                {ingestError.detail && (
                  <div className="knowledge-error-detail">理由: {ingestError.detail}</div>
                )}
              </div>
            )}

            {approvedEntryId && (
              <div className="msg msg--ok" data-testid="knowledge-approve-result">
                <span className="msg__role">登録完了</span>
                エントリを登録しました: <code>{approvedEntryId}</code>
              </div>
            )}
          </section>

          {/* ② ドラフトレビュー -------------------------------------------- */}
          {draft && (
            <section className="knowledge-section" data-testid="knowledge-draft">
              <h3 className="knowledge-section__title">
                ② ドラフトレビュー: {draft.draft_id}
              </h3>

              <div className="knowledge-block" data-testid="knowledge-source-info">
                <div className="knowledge-block__label">原典情報</div>
                <div>タイトル: {String(draft.extracted.source_info.title ?? "Unknown")}</div>
                <div>発行年: {String(draft.extracted.source_info.year ?? "Unknown")}</div>
                <div>DOI: {String(draft.extracted.source_info.doi ?? "N/A")}</div>
                <div>URL: {String(draft.extracted.source_info.url ?? "N/A")}</div>
              </div>

              <div className="knowledge-block" data-testid="knowledge-items">
                <div className="knowledge-block__label">抽出済み知識エントリ</div>
                {draft.extracted.knowledge_items.map((item: KnowledgeItem, i) => {
                  const confidence =
                    typeof item.confidence === "number" ? item.confidence : 1;
                  const low = confidence < CONFIDENCE_THRESHOLD;
                  return (
                    <div className="knowledge-item" key={i} data-testid="knowledge-item">
                      <div className="knowledge-item__statement">
                        {low && (
                          <span title="確信度が低い項目（要確認）" data-testid="knowledge-low-confidence">
                            🟡{" "}
                          </span>
                        )}
                        {item.statement}
                      </div>
                      {item.direct_quote && (
                        <blockquote className="knowledge-item__quote">
                          {item.direct_quote}
                        </blockquote>
                      )}
                      <div className="knowledge-item__meta">
                        確信度: {confidence.toFixed(2)}
                      </div>
                      {item.caveats && (
                        <div className="knowledge-item__meta">注意事項: {item.caveats}</div>
                      )}
                    </div>
                  );
                })}
              </div>

              {draft.extraction_limitations.length > 0 && (
                <div className="knowledge-block" data-testid="knowledge-limitations">
                  <div className="knowledge-block__label">抽出の限界</div>
                  <ul className="knowledge-limitations">
                    {draft.extraction_limitations.map((lim, i) => (
                      <li key={i}>{lim}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="knowledge-selectors">
                <label>
                  ドメイン
                  <select
                    data-testid="knowledge-domain-select"
                    value={domain}
                    onChange={(e) => setDomain(e.target.value)}
                  >
                    {DOMAINS.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Trust Level
                  <select
                    data-testid="knowledge-trust-select"
                    value={trustLevel}
                    onChange={(e) => setTrustLevel(e.target.value)}
                  >
                    {TRUST_LEVELS.map((t) => (
                      <option key={t} value={t}>
                        {TRUST_BADGE[t]} {t}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <label className="knowledge-reject-reason">
                却下理由（却下時は必須）
                <input
                  type="text"
                  data-testid="knowledge-reject-reason"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="却下する場合は理由を入力"
                />
              </label>

              <div className="confirm-row">
                <button
                  type="button"
                  className="btn"
                  data-testid="knowledge-approve"
                  disabled={deciding}
                  onClick={() => void approve()}
                >
                  ✅ 承認
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  data-testid="knowledge-reject"
                  disabled={deciding}
                  onClick={() => void reject()}
                >
                  ❌ 却下
                </button>
                {deciding && <span className="modal__status">処理中…</span>}
              </div>

              {decisionError && (
                <div className="msg msg--error" data-testid="knowledge-decision-error">
                  <span className="msg__role">エラー</span>
                  {decisionError.message}
                  {decisionError.detail && (
                    <div className="knowledge-error-detail">理由: {decisionError.detail}</div>
                  )}
                </div>
              )}
            </section>
          )}

          {/* ③ レジストリ一覧（読み取り専用） ------------------------------ */}
          <section className="knowledge-section">
            <div className="knowledge-section__row">
              <h3 className="knowledge-section__title">③ 登録済み知識一覧（読み取り専用）</h3>
              <button
                type="button"
                className="btn btn--small"
                data-testid="knowledge-reindex"
                disabled={reindexing || !connected}
                onClick={() => void reindex()}
              >
                🔄 再索引
              </button>
            </div>

            {reindexing && <span className="modal__status">再索引中…</span>}
            {reindexResult && (
              <div className="msg msg--ok" data-testid="knowledge-reindex-result">
                {reindexResult}
              </div>
            )}
            {reindexError && (
              <div className="msg msg--error" data-testid="knowledge-reindex-error">
                <span className="msg__role">再索引できません</span>
                {reindexError.status === 501 || reindexError.errorCode === "NOT_IMPLEMENTED"
                  ? "対応 retriever が未配線のため再索引できません（承認自体は成立済みです）。"
                  : reindexError.message}
                {reindexError.detail && (
                  <div className="knowledge-error-detail">理由: {reindexError.detail}</div>
                )}
              </div>
            )}

            {listError && (
              <div className="msg msg--error" data-testid="knowledge-list-error">
                <span className="msg__role">エラー</span>
                {listError.message}
                {listError.detail && (
                  <div className="knowledge-error-detail">理由: {listError.detail}</div>
                )}
              </div>
            )}

            {entries && entries.length === 0 && !listError && (
              <div className="modal__note" data-testid="knowledge-empty">
                登録済みの知識エントリがありません。
              </div>
            )}

            {entries && entries.length > 0 && (
              <ul className="knowledge-registry" data-testid="knowledge-registry">
                {entries.map((e) => (
                  <li className="knowledge-registry__item" key={e.entry_id} data-testid="knowledge-entry">
                    <span className="knowledge-registry__badge">
                      {TRUST_BADGE[e.trust_level ?? ""] ?? "⬜"}
                    </span>
                    <span className="knowledge-registry__title">
                      {e.title ?? "(無題)"}
                    </span>
                    <span className="knowledge-registry__meta">
                      {e.domain} ／ {e.trust_level} ／ {e.status}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
