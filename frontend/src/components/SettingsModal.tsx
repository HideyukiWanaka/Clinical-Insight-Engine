import { useMemo, useState } from "react";
import type { CieApiClient } from "../api/client";

interface SettingsModalProps {
  client: CieApiClient;
  connected: boolean;
  onClose: () => void;
  /** Notify the app that the token (and thus the header status) changed. */
  onConnectedChange: () => void;
}

// Common AI-provider API key prefixes. If a pasted value matches one of
// these, it's almost certainly NOT the local session token — someone
// confused this field with the AI provider key (which belongs in the
// project-root .env, not here). Warn instead of silently accepting garbage
// that would just produce 401s on every request.
const PROVIDER_KEY_PATTERN = /^(AIza|sk-ant-|sk-proj-|sk-)/;

/** セッショントークン設定モーダル — ヘッダーの接続ステータスから開く（発見性のための常設入口）。
 *  これはブラウザ↔ローカルAPI間の認証トークン専用。Gemini/OpenAI/Anthropicなど
 *  生成AIプロバイダーのAPIキーとは別物（そちらはプロジェクトルートの .env で設定し、
 *  API再起動が必要）。混同を防ぐため、プロバイダーキーらしき値の貼り付けは警告する。
 *  トークンは localStorage に保存され、リロード後も接続が維持される。 */
export function SettingsModal({
  client,
  connected,
  onClose,
  onConnectedChange,
}: SettingsModalProps) {
  const [tokenDraft, setTokenDraft] = useState("");
  const [saved, setSaved] = useState(false);

  const looksLikeProviderKey = useMemo(
    () => PROVIDER_KEY_PATTERN.test(tokenDraft.trim()),
    [tokenDraft],
  );

  function save() {
    const t = tokenDraft.trim();
    if (!t) return;
    client.setToken(t);
    setTokenDraft("");
    setSaved(true);
    onConnectedChange();
  }

  return (
    <div
      className="modal__overlay"
      data-testid="settings-modal"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="セッショントークン設定"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__header">
          <span>セッショントークン設定（ローカル接続用）</span>
          <button
            type="button"
            className="icon-btn"
            data-testid="settings-close"
            aria-label="閉じる"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <div className="modal__body">
          <p className="modal__hint">
            接続先API: <code>{client.getBaseUrl()}</code>
            <br />
            状態:{" "}
            {connected ? (
              <strong>接続済み（トークン設定済み）</strong>
            ) : (
              <strong>未接続（トークン未設定）</strong>
            )}
          </p>

          <p className="modal__hint">
            セッショントークンはAPI起動時にターミナルへ{" "}
            <code>[CIE-API] X-CIE-Token=…</code> の形式で表示されます。
            起動スクリプト（scripts/dev.sh）を使った場合は自動設定されるため、
            通常この画面での入力は不要です。
          </p>

          <div className="modal__note" data-testid="settings-not-provider-key">
            ⚠️ ここは<strong>Gemini / OpenAI / Anthropic などAIプロバイダーの
            APIキーを入れる欄ではありません。</strong>
            プロバイダーキーはプロジェクトルートの <code>.env</code> の{" "}
            <code>GOOGLE_GEMINI_API_KEY</code> 等で設定し、設定変更後はAPIの
            再起動が必要です。この欄は、あくまでブラウザとローカルAPIの間だけで
            使う接続用トークンです。
          </div>

          <div className="confirm-row">
            <input
              aria-label="セッショントークン"
              data-testid="settings-token-input"
              value={tokenDraft}
              onChange={(e) => {
                setTokenDraft(e.target.value);
                setSaved(false);
              }}
              placeholder="X-CIE-Token の値を貼り付け"
              style={{ flex: 1, minWidth: 0 }}
            />
            <button
              type="button"
              className="btn"
              data-testid="settings-token-save"
              disabled={!tokenDraft.trim()}
              onClick={save}
            >
              保存
            </button>
          </div>

          {looksLikeProviderKey && (
            <div className="msg msg--error" data-testid="settings-provider-key-warning">
              <span className="msg__role">確認</span>
              入力された値はAIプロバイダーのAPIキーの形式に見えます。
              このままではセッショントークンとして保存され、接続エラー（401）の
              原因になります。プロバイダーキーは <code>.env</code> に設定して
              ください。
            </div>
          )}

          {saved && (
            <div className="modal__note" data-testid="settings-saved">
              トークンを保存しました（リロード後も維持されます）。
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
