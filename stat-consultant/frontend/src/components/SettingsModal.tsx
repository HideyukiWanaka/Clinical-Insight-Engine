import { useEffect, useState } from "react";
import { clearApiKey, fetchKeyStatus, type KeyStatus, saveApiKey } from "../api";
import { CloseIcon } from "../icons";

interface SettingsModalProps {
  onClose: () => void;
  /** Called after any key change so the caller can refresh the model list. */
  onKeysChanged: () => void;
  onToast: (msg: string) => void;
}

/** BYOK settings: paste a provider API key → stored server-side in the OS
 *  keychain. Keys are never displayed back — only a ✓ / 未設定 status.
 *  Translated from cie LlmSettingsModal (password input, never-echo). */
export function SettingsModal({ onClose, onKeysChanged, onToast }: SettingsModalProps) {
  const [keys, setKeys] = useState<KeyStatus[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    fetchKeyStatus()
      .then(setKeys)
      .catch(() => onToast("設定の取得に失敗しました"));
  }, [onToast]);

  async function onSave(provider: string) {
    const key = (drafts[provider] || "").trim();
    if (!key || busy) return;
    setBusy(provider);
    try {
      setKeys(await saveApiKey(provider, key));
      setDrafts((d) => ({ ...d, [provider]: "" }));
      onToast("APIキーを保存しました");
      onKeysChanged();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setBusy(null);
    }
  }

  async function onClear(provider: string) {
    if (busy) return;
    setBusy(provider);
    try {
      setKeys(await clearApiKey(provider));
      onToast("APIキーを削除しました");
      onKeysChanged();
    } catch {
      onToast("削除に失敗しました");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-label="設定"
        data-testid="settings-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__header">
          <h2 className="modal__title">APIキーの設定</h2>
          <button
            type="button"
            className="modal__close"
            aria-label="閉じる"
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </div>

        <p className="modal__note">
          使いたいAIのAPIキーを貼り付けて保存してください。キーはこのPCの
          キーチェーンに保存され、画面には再表示されません。
        </p>

        <div className="modal__providers">
          {keys.map((k) => (
            <div className="provider" key={k.provider} data-testid={`provider-${k.provider}`}>
              <div className="provider__head">
                <span className="provider__label">{k.label}</span>
                <span
                  className={`provider__badge ${k.has_key ? "is-set" : "is-unset"}`}
                  data-testid={`badge-${k.provider}`}
                >
                  {k.has_key ? "✓ 設定済み" : "未設定"}
                </span>
              </div>
              <div className="provider__row">
                <input
                  type="password"
                  className="provider__input"
                  data-testid={`input-${k.provider}`}
                  placeholder={k.has_key ? "新しいキーで上書き…" : "APIキーを貼り付け…"}
                  value={drafts[k.provider] || ""}
                  onChange={(e) =>
                    setDrafts((d) => ({ ...d, [k.provider]: e.target.value }))
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      onSave(k.provider);
                    }
                  }}
                />
                <button
                  type="button"
                  className="btn btn--accent"
                  data-testid={`save-${k.provider}`}
                  disabled={busy === k.provider || !(drafts[k.provider] || "").trim()}
                  onClick={() => onSave(k.provider)}
                >
                  保存
                </button>
                {k.has_key && (
                  <button
                    type="button"
                    className="btn"
                    data-testid={`clear-${k.provider}`}
                    disabled={busy === k.provider}
                    onClick={() => onClear(k.provider)}
                  >
                    削除
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
