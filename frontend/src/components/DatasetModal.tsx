import { useRef, useState } from "react";
import { ApiError, type CieApiClient } from "../api/client";
import type { DatasetUploadResponse } from "../api/types";

interface DatasetModalProps {
  client: CieApiClient;
  connected: boolean;
  /** The currently registered dataset (so re-opening keeps the summary). */
  current: DatasetUploadResponse | null;
  onClose: () => void;
  onUploaded: (info: DatasetUploadResponse) => void;
}

/** 「解析データ」入口 — CSV アップロードモーダル（§5: 参考資料入口とは分離）。
 *  ファイル選択 → POST /api/dataset → **集計メタ（列名エイリアス・型・欠測）のみ**を
 *  テーブル表示する。行データ（セル値）は一切描画しない（§5, CLAUDE.md
 *  inject_raw_data_rows=False）。失敗は ApiError.detail を表示（無言失敗禁止 §5）。 */
export function DatasetModal({
  client,
  connected,
  current,
  onClose,
  onUploaded,
}: DatasetModalProps) {
  const [info, setInfo] = useState<DatasetUploadResponse | null>(current);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; detail?: string | null } | null>(
    null,
  );
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const res = await client.uploadDataset(file);
      setInfo(res);
      onUploaded(res);
    } catch (err) {
      if (err instanceof ApiError) {
        setError({ message: err.message, detail: err.detail });
      } else {
        setError({
          message: "アップロードに失敗しました。",
          detail: String((err as Error)?.message ?? err),
        });
      }
    } finally {
      setBusy(false);
      // Allow re-selecting the same filename to re-trigger onChange.
      if (inputRef.current) inputRef.current.value = "";
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
          <span>解析データ（CSV）</span>
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
            CSV を取り込むと、以降の解析で列メタ（型・欠測）が参照されます。
            <strong>行データ（患者値）は表示・送信されません</strong>（var_n
            匿名化 / 集計のみ）。
          </p>

          <div className="confirm-row">
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              aria-label="CSVファイル"
              data-testid="dataset-file-input"
              disabled={busy || !connected}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void upload(f);
              }}
            />
            {busy && <span className="modal__status">アップロード中…</span>}
          </div>

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
              <table className="dataset-table" data-testid="dataset-columns">
                <thead>
                  <tr>
                    <th>列（匿名化）</th>
                    <th>推定型</th>
                    <th>欠測数</th>
                    <th>欠測率(%)</th>
                  </tr>
                </thead>
                <tbody>
                  {info.columns.map((c) => (
                    <tr key={c.var_n}>
                      <td>{c.var_n}</td>
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
