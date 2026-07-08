import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type CieApiClient } from "../api/client";
import type { FileContentResponse, FileEntry } from "../api/types";
import { Pane } from "./Pane";

interface FileTreeProps {
  client: CieApiClient;
  connected: boolean;
  /** Bumped by App when a run completes so the listing refreshes (§3.4). */
  refreshKey: number;
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

/** Right-top: read-only workspace file tree (spec/ui/ide-workbench-spec.md §3.4).
 *  Lists GET /api/files, previews via GET /api/files/content (image → <img>,
 *  text → <pre><code>), and downloads. Read-only: no delete UI (§3.4). Failures
 *  surface ApiError.detail (無言失敗禁止 §5). */
export function FileTree({ client, connected, refreshKey }: FileTreeProps) {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ message: string; detail?: string | null } | null>(
    null,
  );
  const [selected, setSelected] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewErr, setPreviewErr] = useState<
    { message: string; detail?: string | null } | null
  >(null);

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

  // Revoke any outstanding object URL on unmount.
  useEffect(() => () => revokePreview(), [revokePreview]);

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
      headerExtra={
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
      }
    >
      <div className="filetree" data-testid="filetree">
        {!connected && (
          <div className="placeholder" data-testid="files-need-token">
            先にセッショントークンを設定するとワークスペースのファイルが一覧されます。
          </div>
        )}

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
          <ul className="filetree__list" data-testid="files-list">
            {files.map((f) => (
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
                    {f.kind === "image" ? "🖼" : f.kind === "text" ? "📄" : "📦"}
                  </span>
                  <span className="filetree__path">{f.path}</span>
                </button>
              </li>
            ))}
          </ul>
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
