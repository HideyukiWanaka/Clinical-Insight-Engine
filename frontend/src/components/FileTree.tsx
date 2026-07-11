import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, type CieApiClient } from "../api/client";
import type {
  DatasetUploadResponse,
  FileContentResponse,
  FileEntry,
  StorageSettingsResponse,
} from "../api/types";
import { Pane } from "./Pane";

interface FileTreeProps {
  client: CieApiClient;
  connected: boolean;
  /** Bumped by App when a run completes so the listing refreshes (§3.4). */
  refreshKey: number;
  /** The registered 解析対象 dataset — pinned as a banner at the top so the
   *  current analysis target never gets buried under generated files. */
  dataset: DatasetUploadResponse | null;
  /** Opens the 解析データ modal (register / change the dataset). */
  onOpenDataset: () => void;
}

/** Listing category — data first so logs/scripts can't bury the dataset. */
type Category = "data" | "figure" | "script" | "other";

const CATEGORY_ORDER: Category[] = ["data", "figure", "script", "other"];

const CATEGORY_META: Record<Category, { icon: string; label: string }> = {
  data: { icon: "🗂", label: "データ" },
  figure: { icon: "🖼", label: "図" },
  script: { icon: "📜", label: "スクリプト" },
  other: { icon: "🗒", label: "ログ・その他" },
};

/** dataset.csv（登録済み解析データ）と uploads/（ユーザー持ち込み）が「データ」。
 *  実行のたびに増える生成スクリプト・ログはここに混ざらない。 */
function categorize(f: FileEntry): Category {
  if (f.path === "dataset.csv" || f.path.startsWith("uploads/")) return "data";
  if (f.kind === "image") return "figure";
  if (/\.r$/i.test(f.path)) return "script";
  return "other";
}

// A loaded preview: either image bytes (object URL) or decoded text.
type Preview =
  | { kind: "image"; url: string; entry: FileEntry }
  | { kind: "text"; content: FileContentResponse; entry: FileEntry };

function fileName(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

/** csv is previewed as its first lines only (design §3.2) — the tree is a
 *  glance at generated artifacts, not a data grid. */
function clampCsv(text: string, language: string): string {
  if (language !== "csv") return text;
  const lines = text.split("\n");
  if (lines.length <= 20) return text;
  return lines.slice(0, 20).join("\n") + "\n… [先頭20行のみ表示] …";
}

/** Right-top: workspace file tree (spec/ui/ide-workbench-spec.md §3.4).
 *  Lists GET /api/files, previews via GET /api/files/content (image → <img>,
 *  text → <pre><code>), and downloads. No delete/overwrite UI (§3.4); the one
 *  write path is「＋ 追加」— POST /api/files puts a user-chosen local file
 *  under uploads/. Failures surface ApiError.detail (無言失敗禁止 §5). */
export function FileTree({
  client,
  connected,
  refreshKey,
  dataset,
  onOpenDataset,
}: FileTreeProps) {
  const [files, setFiles] = useState<FileEntry[]>([]);
  // Category filter — "all" shows every group (data first); a specific
  // category narrows the list so e.g. logs can be hidden entirely.
  const [filter, setFilter] = useState<Category | "all">("all");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<{ message: string; detail?: string | null } | null>(
    null,
  );
  const [selected, setSelected] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewErr, setPreviewErr] = useState<
    { message: string; detail?: string | null } | null
  >(null);

  // 保存先ルート（常時表示バー）— どのフォルダに保存されているか一目で分かるように。
  const [storage, setStorage] = useState<StorageSettingsResponse | null>(null);
  const [storageEditing, setStorageEditing] = useState(false);
  const [storageDraft, setStorageDraft] = useState("");
  const [storageSaving, setStorageSaving] = useState(false);
  const [storageError, setStorageError] = useState<
    { message: string; detail?: string | null } | null
  >(null);
  const [storageCopied, setStorageCopied] = useState(false);

  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    client
      .getStorageSettings()
      .then((res) => {
        if (!cancelled) setStorage(res);
      })
      .catch(() => {
        /* footer just stays hidden — the file listing itself still works */
      });
    return () => {
      cancelled = true;
    };
  }, [client, connected]);

  const copyStoragePath = useCallback(() => {
    if (!storage) return;
    void navigator.clipboard.writeText(storage.workspace_directory).then(() => {
      setStorageCopied(true);
      setTimeout(() => setStorageCopied(false), 1500);
    });
  }, [storage]);

  const saveStorageDirectory = useCallback(async () => {
    const dir = storageDraft.trim();
    if (!dir) return;
    setStorageSaving(true);
    setStorageError(null);
    try {
      const res = await client.setWorkspaceDirectory({ directory: dir });
      setStorage(res);
      setStorageEditing(false);
    } catch (err) {
      if (err instanceof ApiError) {
        setStorageError({ message: err.message, detail: err.detail });
      } else {
        setStorageError({
          message: "保存先の変更に失敗しました。",
          detail: String((err as Error)?.message ?? err),
        });
      }
    } finally {
      setStorageSaving(false);
    }
  }, [client, storageDraft]);

  // Track the live image object URL so we always revoke it before replacing
  // (same discipline as useRunner's figures).
  const objectUrlRef = useRef<string | null>(null);
  const revokePreview = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!connected) return;
    setLoading(true);
    setError(null);
    try {
      const res = await client.listFiles();
      setFiles(res.files);
    } catch (err) {
      if (err instanceof ApiError) {
        setError({ message: err.message, detail: err.detail });
      } else {
        setError({
          message: "ファイル一覧の取得に失敗しました。",
          detail: String((err as Error)?.message ?? err),
        });
      }
    } finally {
      setLoading(false);
    }
  }, [client, connected]);

  // Load on mount, on manual refresh, and whenever a run completes (refreshKey).
  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  // 「＋ 追加」: bring a local file into the workspace (uploads/), then re-list.
  const uploadLocalFile = useCallback(
    async (file: File) => {
      setUploading(true);
      setError(null);
      try {
        await client.uploadWorkspaceFile(file);
        await refresh();
      } catch (err) {
        if (err instanceof ApiError) {
          setError({ message: err.message, detail: err.detail });
        } else {
          setError({
            message: "ファイルの追加に失敗しました。",
            detail: String((err as Error)?.message ?? err),
          });
        }
      } finally {
        setUploading(false);
        // Allow re-selecting the same filename to re-trigger onChange.
        if (uploadInputRef.current) uploadInputRef.current.value = "";
      }
    },
    [client, refresh],
  );

  // Revoke any outstanding object URL on unmount.
  useEffect(() => () => revokePreview(), [revokePreview]);

  // Non-empty categories in fixed order (data → 図 → スクリプト → ログ・その他),
  // most-recent-first within each (the API already sorts by mtime).
  const groups = useMemo(
    () =>
      CATEGORY_ORDER.map((category) => ({
        category,
        items: files.filter((f) => categorize(f) === category),
      })).filter((g) => g.items.length > 0),
    [files],
  );
  const visibleGroups =
    filter === "all" ? groups : groups.filter((g) => g.category === filter);

  const openFile = useCallback(
    async (entry: FileEntry) => {
      setSelected(entry.path);
      setPreviewErr(null);
      revokePreview();
      setPreview(null);
      try {
        if (entry.kind === "image") {
          const url = await client.fetchImageObjectUrl(entry.path);
          objectUrlRef.current = url;
          setPreview({ kind: "image", url, entry });
        } else {
          const content = await client.fetchFileContent(entry.path);
          setPreview({ kind: "text", content, entry });
        }
      } catch (err) {
        if (err instanceof ApiError) {
          setPreviewErr({ message: err.message, detail: err.detail });
        } else {
          setPreviewErr({
            message: "ファイルの取得に失敗しました。",
            detail: String((err as Error)?.message ?? err),
          });
        }
      }
    },
    [client, revokePreview],
  );

  function download() {
    if (!preview) return;
    const name = fileName(preview.entry.path);
    let href: string;
    let revoke = false;
    if (preview.kind === "image") {
      href = preview.url; // already an object URL for the blob
    } else {
      const blob = new Blob([preview.content.text], { type: "text/plain" });
      href = URL.createObjectURL(blob);
      revoke = true;
    }
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    if (revoke) URL.revokeObjectURL(href);
  }

  return (
    <Pane
      title="ファイル"
      footer={
        connected && storage ? (
          <div className="storage-bar" data-testid="storage-bar">
            {!storageEditing ? (
              <>
                <span className="storage-bar__icon" aria-hidden="true">
                  💾
                </span>
                <span
                  className="storage-bar__path"
                  data-testid="storage-bar-path"
                  title={storage.workspace_directory}
                >
                  保存先: {storage.workspace_directory}
                </span>
                <button
                  type="button"
                  className="mini-btn"
                  data-testid="storage-bar-copy"
                  onClick={copyStoragePath}
                  title="パスをコピー"
                >
                  {storageCopied ? "✓ コピー済み" : "コピー"}
                </button>
                <button
                  type="button"
                  className="mini-btn"
                  data-testid="storage-bar-edit"
                  onClick={() => {
                    setStorageDraft(
                      storage.pending_workspace_directory ??
                        storage.workspace_directory,
                    );
                    setStorageError(null);
                    setStorageEditing(true);
                  }}
                  title="保存先フォルダを変更"
                >
                  変更
                </button>
              </>
            ) : (
              <>
                <input
                  className="storage-bar__input"
                  aria-label="新しい保存先フォルダの絶対パス"
                  data-testid="storage-bar-input"
                  value={storageDraft}
                  disabled={storageSaving}
                  onChange={(e) => setStorageDraft(e.target.value)}
                  placeholder="/Users/name/Documents/CIE/workspace"
                />
                <button
                  type="button"
                  className="mini-btn"
                  data-testid="storage-bar-save"
                  disabled={storageSaving || !storageDraft.trim()}
                  onClick={() => void saveStorageDirectory()}
                >
                  {storageSaving ? "保存中…" : "保存"}
                </button>
                <button
                  type="button"
                  className="mini-btn"
                  data-testid="storage-bar-cancel"
                  disabled={storageSaving}
                  onClick={() => {
                    setStorageEditing(false);
                    setStorageError(null);
                  }}
                >
                  キャンセル
                </button>
              </>
            )}
            {!storageEditing && storage.pending_workspace_directory && (
              <div
                className="storage-bar__pending"
                data-testid="storage-bar-pending"
              >
                変更を保存済み。次回起動から反映されます:{" "}
                <code>{storage.pending_workspace_directory}</code>
              </div>
            )}
            {storageError && (
              <div
                className="storage-bar__error"
                data-testid="storage-bar-error"
              >
                {storageError.message}
                {storageError.detail && <>（{storageError.detail}）</>}
              </div>
            )}
          </div>
        ) : undefined
      }
      headerExtra={
        <>
          <input
            ref={uploadInputRef}
            type="file"
            style={{ display: "none" }}
            aria-label="ワークスペースに追加するファイル"
            data-testid="files-upload-input"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void uploadLocalFile(f);
            }}
          />
          <button
            type="button"
            className="mini-btn"
            data-testid="files-upload"
            onClick={() => uploadInputRef.current?.click()}
            disabled={uploading || !connected}
            title="PC上のファイルをワークスペース（uploads/）に追加（POST /api/files）"
          >
            {uploading ? "追加中…" : "＋ 追加"}
          </button>
          <button
            type="button"
            className="mini-btn"
            data-testid="files-refresh"
            onClick={() => void refresh()}
            disabled={loading || !connected}
            title="一覧を更新（GET /api/files）"
          >
            更新
          </button>
        </>
      }
    >
      <div className="filetree" data-testid="filetree">
        {!connected && (
          <div className="placeholder" data-testid="files-need-token">
            先にセッショントークンを設定するとワークスペースのファイルが一覧されます。
          </div>
        )}

        {/* 解析対象データを常に最上部へ固定表示 — 一覧に埋もれない（§3.4改）。 */}
        {connected &&
          (dataset ? (
            <div className="filetree__dataset" data-testid="active-dataset">
              <span className="filetree__dataset-icon" aria-hidden="true">
                📌
              </span>
              <div className="filetree__dataset-meta">
                <div
                  className="filetree__dataset-name"
                  title={dataset.source_name ?? dataset.dataset_id}
                >
                  {dataset.source_name ?? dataset.dataset_id}
                </div>
                <div className="filetree__dataset-sub">
                  解析対象データ ・ {dataset.row_count}行 × {dataset.column_count}列
                </div>
              </div>
              <button
                type="button"
                className="mini-btn"
                data-testid="active-dataset-change"
                onClick={onOpenDataset}
                title="解析データを変更（列メタの確認もこちら）"
              >
                変更
              </button>
            </div>
          ) : (
            <div
              className="filetree__dataset filetree__dataset--empty"
              data-testid="active-dataset-empty"
            >
              <span className="filetree__dataset-sub">
                解析対象データは未登録です
              </span>
              <button
                type="button"
                className="mini-btn"
                data-testid="active-dataset-register"
                onClick={onOpenDataset}
              >
                取り込む
              </button>
            </div>
          ))}

        {error && (
          <div className="msg msg--error" data-testid="files-error">
            <span className="msg__role">エラー</span>
            {error.message}
            {error.detail && (
              <div style={{ marginTop: 4, fontSize: 12, opacity: 0.85 }}>
                理由: {error.detail}
              </div>
            )}
          </div>
        )}

        {connected && !error && files.length === 0 && !loading && (
          <div className="placeholder" data-testid="files-empty">
            まだファイルはありません。解析を実行すると生成物（図・スクリプト等）が
            ここに表示されます。
          </div>
        )}

        {files.length > 0 && (
          <div className="filetree__chips" data-testid="files-filter" role="group" aria-label="ファイル種別フィルタ">
            <button
              type="button"
              className={"chip" + (filter === "all" ? " chip--active" : "")}
              data-testid="files-filter-all"
              onClick={() => setFilter("all")}
            >
              すべて ({files.length})
            </button>
            {groups.map((g) => (
              <button
                key={g.category}
                type="button"
                className={"chip" + (filter === g.category ? " chip--active" : "")}
                data-testid={`files-filter-${g.category}`}
                onClick={() =>
                  setFilter((prev) => (prev === g.category ? "all" : g.category))
                }
              >
                {CATEGORY_META[g.category].icon} {CATEGORY_META[g.category].label} (
                {g.items.length})
              </button>
            ))}
          </div>
        )}

        {files.length > 0 && (
          <div className="filetree__groups" data-testid="files-list">
            {visibleGroups.map((g) => (
              <section
                key={g.category}
                className="filetree__group"
                data-testid={`files-group-${g.category}`}
              >
                <h3 className="filetree__group-title">
                  <span aria-hidden="true">{CATEGORY_META[g.category].icon}</span>{" "}
                  {CATEGORY_META[g.category].label}
                  <span className="filetree__group-count">{g.items.length}</span>
                </h3>
                <ul className="filetree__list">
                  {g.items.map((f) => (
                    <li key={f.path}>
                      <button
                        type="button"
                        className={
                          "filetree__item" +
                          (selected === f.path ? " filetree__item--active" : "")
                        }
                        data-testid="file-item"
                        title={f.path}
                        onClick={() => void openFile(f)}
                      >
                        <span className="filetree__kind" aria-hidden="true">
                          {f.kind === "image"
                            ? "🖼"
                            : f.kind === "text"
                              ? "📄"
                              : "📦"}
                        </span>
                        <span className="filetree__path">{f.path}</span>
                        {dataset && f.path === "dataset.csv" && (
                          <span
                            className="filetree__target-badge"
                            data-testid="file-target-badge"
                            title="現在の解析対象データ"
                          >
                            解析対象
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}

        {previewErr && (
          <div className="msg msg--error" data-testid="file-preview-error">
            <span className="msg__role">エラー</span>
            {previewErr.message}
            {previewErr.detail && (
              <div style={{ marginTop: 4, fontSize: 12, opacity: 0.85 }}>
                理由: {previewErr.detail}
              </div>
            )}
          </div>
        )}

        {preview && (
          <div className="filetree__preview" data-testid="file-preview">
            <div className="filetree__preview-bar">
              <span className="filetree__preview-name">
                {fileName(preview.entry.path)}
                {preview.kind === "text" && (
                  <span className="filetree__lang">{preview.content.language}</span>
                )}
              </span>
              <button
                type="button"
                className="mini-btn"
                data-testid="file-download"
                onClick={download}
                title="ダウンロード"
              >
                ⬇ 保存
              </button>
            </div>
            {preview.kind === "image" ? (
              <img
                className="filetree__image"
                src={preview.url}
                alt={preview.entry.path}
                data-testid="file-image"
              />
            ) : (
              <pre data-testid="file-text">
                <code>
                  {clampCsv(preview.content.text, preview.content.language)}
                </code>
              </pre>
            )}
          </div>
        )}
      </div>
    </Pane>
  );
}
