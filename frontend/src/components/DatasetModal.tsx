import { useRef, useState } from "react";
import { ApiError, type CieApiClient } from "../api/client";
import type { DatasetUploadResponse, ExcelInspectResponse } from "../api/types";

interface DatasetModalProps {
  client: CieApiClient;
  connected: boolean;
  /** The currently registered dataset (so re-opening keeps the summary). */
  current: DatasetUploadResponse | null;
  onClose: () => void;
  onUploaded: (info: DatasetUploadResponse) => void;
}

/** 「解析データ」入口 — CSV / Excel アップロードモーダル（§5: 参考資料入口とは分離）。
 *  CSV はファイル選択 → POST /api/dataset の一段。Excel (.xlsx/.xls) は
 *  inspect（シート名一覧）→ シート選択 → confirm の二段で、確定後は CSV と
 *  同一の集計メタが返る。**集計メタ（列名エイリアス・型・欠測）のみ**を
 *  テーブル表示する。行データ（セル値）は一切描画しない（§5, CLAUDE.md
 *  inject_raw_data_rows=False）。実列名（original_name）はAIには送信されない
 *  ローカル専用情報だが、DOMにも既定では出さず、ユーザーが明示的にトグルを
 *  押した時だけ表示する（var_nがどの実列を指すか確認できるようにしつつ、
 *  既定でDOMに列名を出さない方針は維持）。失敗は ApiError.detail を表示
 *  （無言失敗禁止 §5）。 */
export function DatasetModal({
  client,
  connected,
  current,
  onClose,
  onUploaded,
}: DatasetModalProps) {
  const [info, setInfo] = useState<DatasetUploadResponse | null>(current);
  const [busy, setBusy] = useState(false);
  // Real column names stay out of the DOM until the user explicitly asks to
  // see them (off by default on every open) — var_n is what the AI/agents
  // pipeline ever sees; this reveal is purely local so the user can verify
  // which real column a var_n reference points to.
  const [showRealNames, setShowRealNames] = useState(false);
  const [error, setError] = useState<{ message: string; detail?: string | null } | null>(
    null,
  );
  // A pending Excel upload awaiting sheet selection (null = no Excel pending).
  const [excelPending, setExcelPending] = useState<
    (ExcelInspectResponse & { fileName: string }) | null
  >(null);
  const [sheetName, setSheetName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function showError(err: unknown) {
    if (err instanceof ApiError) {
      setError({ message: err.message, detail: err.detail });
    } else {
      setError({
        message: "アップロードに失敗しました。",
        detail: String((err as Error)?.message ?? err),
      });
    }
  }

  async function upload(file: File) {
    if (busy) return;
    setError(null);
    setExcelPending(null);
    setBusy(true);
    try {
      if (/\.xlsx?$/i.test(file.name)) {
        // Excel: two-step — list sheets first, register after the user picks one.
        const res = await client.inspectExcelDataset(file);
        setExcelPending({ ...res, fileName: file.name });
        setSheetName(res.sheet_names[0] ?? "");
      } else {
        const res = await client.uploadDataset(file);
        setInfo(res);
        onUploaded(res);
      }
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
      // Allow re-selecting the same filename to re-trigger onChange.
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function confirmSheet() {
    if (busy || !excelPending || !sheetName) return;
    setError(null);
    setBusy(true);
    try {
      const res = await client.confirmExcelDataset({
        upload_id: excelPending.upload_id,
        sheet_name: sheetName,
      });
      setInfo(res);
      onUploaded(res);
      setExcelPending(null);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="modal__overlay"
      data-testid="dataset-modal"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="解析データの取り込み"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__header">
          <span>解析データ（CSV / Excel）</span>
          <button
            type="button"
            className="icon-btn"
            data-testid="dataset-close"
            aria-label="閉じる"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <div className="modal__body">
          <p className="modal__hint">
            CSV または Excel (.xlsx/.xls) を取り込むと、以降の解析で列メタ
            （型・欠測）が参照されます。Excel は取り込むシートを選択します。
            <strong>行データ（患者値）は表示・送信されません</strong>（var_n
            匿名化 / 集計のみ）。
          </p>

          <div className="confirm-row">
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv,.xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
              aria-label="CSV / Excelファイル"
              data-testid="dataset-file-input"
              disabled={busy || !connected}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void upload(f);
              }}
            />
            {busy && <span className="modal__status">アップロード中…</span>}
          </div>

          {excelPending && (
            <div className="confirm-row" data-testid="excel-sheet-select-row">
              <span className="modal__status">
                {excelPending.fileName} のシートを選択:
              </span>
              <select
                aria-label="取り込むシート"
                data-testid="excel-sheet-select"
                value={sheetName}
                disabled={busy}
                onChange={(e) => setSheetName(e.target.value)}
              >
                {excelPending.sheet_names.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="mini-btn"
                data-testid="excel-sheet-confirm"
                disabled={busy || !sheetName}
                onClick={() => void confirmSheet()}
              >
                このシートを取り込む
              </button>
            </div>
          )}

          {!connected && (
            <div className="modal__note" data-testid="dataset-need-token">
              先にチャットでセッショントークンを設定してください。
            </div>
          )}

          {error && (
            <div className="msg msg--error" data-testid="dataset-error">
              <span className="msg__role">エラー</span>
              {error.message}
              {error.detail && (
                <div style={{ marginTop: 4, fontSize: 12, opacity: 0.85 }}>
                  理由: {error.detail}
                </div>
              )}
            </div>
          )}

          {info && (
            <div className="dataset-summary" data-testid="dataset-summary">
              <div className="dataset-summary__meta">
                取り込み済み: <code>{info.dataset_id}</code> ／ 行数{" "}
                {info.row_count} ／ 列数 {info.column_count}
              </div>
              <div className="confirm-row">
                <p className="modal__hint" style={{ flex: 1, margin: 0 }}>
                  AIとのやり取りでは<code>var_n</code>で参照されます
                  （実列名はAIに送信されません）。
                </p>
                <button
                  type="button"
                  className="mini-btn"
                  data-testid="dataset-toggle-real-names"
                  onClick={() => setShowRealNames((v) => !v)}
                >
                  {showRealNames ? "🙈 実列名を隠す" : "👁 実列名を表示"}
                </button>
              </div>
              <table className="dataset-table" data-testid="dataset-columns">
                <thead>
                  <tr>
                    <th>列（AIへの参照名）</th>
                    {showRealNames && <th>元の列名</th>}
                    <th>推定型</th>
                    <th>欠測数</th>
                    <th>欠測率(%)</th>
                  </tr>
                </thead>
                <tbody>
                  {info.columns.map((c) => (
                    <tr key={c.var_n}>
                      <td>{c.var_n}</td>
                      {showRealNames && (
                        <td data-testid="dataset-real-name">{c.original_name}</td>
                      )}
                      <td>{c.inferred_type}</td>
                      <td>{c.missing_count}</td>
                      <td>{c.missing_rate_pct}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
