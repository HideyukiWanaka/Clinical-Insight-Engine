import { useEffect, useState } from "react";
import { ApiError, type CieApiClient } from "../api/client";
import type { LlmSettingsResponse } from "../api/types";

interface LlmSettingsModalProps {
  client: CieApiClient;
  connected: boolean;
  onClose: () => void;
}

/** AIプロバイダー（LLM）設定モーダル — ヘッダーの「🤖 AIモデル」から開く。
 *  「解析データ」「参考資料」と同格の常設入口で、Gemini/OpenAI/Anthropicの
 *  APIキーを入力する“唯一の正しい場所”にする（セッショントークン設定とは別物）。
 *  キーはOSキーチェーンに保存され、値そのものは一切画面に返らない
 *  （has_key の真偽のみ表示）。保存・切替は次のLLM呼び出しから即反映され、
 *  API再起動は不要。 */
export function LlmSettingsModal({ client, connected, onClose }: LlmSettingsModalProps) {
  const [settings, setSettings] = useState<LlmSettingsResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [keyDraft, setKeyDraft] = useState("");
  const [error, setError] = useState<{ message: string; detail?: string | null } | null>(
    null,
  );
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  function showError(err: unknown) {
    if (err instanceof ApiError) {
      setError({ message: err.message, detail: err.detail });
    } else {
      setError({
        message: "通信に失敗しました。",
        detail: String((err as Error)?.message ?? err),
      });
    }
  }

  async function refresh() {
    if (!connected) return;
    setError(null);
    try {
      setSettings(await client.getLlmSettings());
    } catch (err) {
      showError(err);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);

  async function switchProvider(provider: string) {
    if (busy || !settings || provider === settings.active_provider) return;
    setBusy(true);
    setError(null);
    setSavedNotice(null);
    try {
      setSettings(await client.setLlmProvider({ provider }));
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  }

  async function saveKey() {
    if (busy || !settings || !keyDraft.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await client.saveLlmApiKey({
        provider: settings.active_provider,
        api_key: keyDraft.trim(),
      });
      setSettings(res);
      setKeyDraft("");
      setSavedNotice("APIキーを保存しました。次回の解析から反映されます。");
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  }

  async function clearKey() {
    if (busy || !settings) return;
    setBusy(true);
    setError(null);
    setSavedNotice(null);
    try {
      setSettings(await client.clearLlmApiKey({ provider: settings.active_provider }));
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  }

  const active = settings?.providers.find((p) => p.provider === settings.active_provider);

  return (
    <div
      className="modal__overlay"
      data-testid="llm-settings-modal"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="AIプロバイダー設定"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__header">
          <span>AIプロバイダー設定</span>
          <button
            type="button"
            className="icon-btn"
            data-testid="llm-settings-close"
            aria-label="閉じる"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <div className="modal__body">
          {!connected && (
            <div className="modal__note" data-testid="llm-settings-need-token">
              先にセッショントークンを設定してください。
            </div>
          )}

          {connected && !settings && !error && <div className="modal__hint">読み込み中…</div>}

          {settings && (
            <>
              <p className="modal__hint">
                解析コード・原稿生成などに使う生成AIのプロバイダーとAPIキーを設定します。
                キーはOSのキーチェーンに保存され、この画面にも他のどの画面にも
                再表示されません。
              </p>

              <div className="chat__base" style={{ marginBottom: 12 }}>
                {settings.providers.map((p) => (
                  <button
                    key={p.provider}
                    type="button"
                    className={
                      "mini-btn" +
                      (p.provider === settings.active_provider
                        ? " chat__base-chip--active"
                        : "")
                    }
                    data-testid={`llm-provider-${p.provider}`}
                    disabled={busy}
                    onClick={() => void switchProvider(p.provider)}
                    title={p.has_key ? "APIキー設定済み" : "APIキー未設定"}
                  >
                    {p.provider === settings.active_provider ? "● " : "○ "}
                    {p.label}
                    {p.has_key ? " ✓" : ""}
                  </button>
                ))}
              </div>

              {active && (
                <div className="modal__note" data-testid="llm-active-key-status">
                  {active.label}: {active.has_key ? "✓ APIキー設定済み" : "⚠️ APIキー未設定"}
                </div>
              )}

              <div className="confirm-row">
                <input
                  type="password"
                  aria-label="APIキーを入力"
                  data-testid="llm-key-input"
                  value={keyDraft}
                  onChange={(e) => setKeyDraft(e.target.value)}
                  placeholder={`${active?.label ?? ""} のAPIキーを貼り付け`}
                  disabled={busy}
                  style={{ flex: 1, minWidth: 0 }}
                />
                <button
                  type="button"
                  className="btn"
                  data-testid="llm-key-save"
                  disabled={busy || !keyDraft.trim()}
                  onClick={() => void saveKey()}
                >
                  保存
                </button>
                {active?.has_key && (
                  <button
                    type="button"
                    className="btn btn--ghost"
                    data-testid="llm-key-clear"
                    disabled={busy}
                    onClick={() => void clearKey()}
                  >
                    削除
                  </button>
                )}
              </div>

              {savedNotice && (
                <div className="modal__note" data-testid="llm-key-saved">
                  {savedNotice}
                </div>
              )}
            </>
          )}

          {error && (
            <div className="msg msg--error" data-testid="llm-settings-error">
              <span className="msg__role">エラー</span>
              {error.message}
              {error.detail && (
                <div style={{ marginTop: 4, fontSize: 12, opacity: 0.85 }}>
                  理由: {error.detail}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
