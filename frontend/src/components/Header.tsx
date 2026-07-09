import type { Theme } from "../theme";

interface HeaderProps {
  projectName: string;
  connected: boolean;
  apiBaseUrl: string;
  theme: Theme;
  onToggleTheme: () => void;
  /** Open the 解析データ (dataset upload) modal (§5 別入口). */
  onOpenDataset: () => void;
  /** True once a dataset is registered — shows a small "取り込み済み" badge. */
  datasetUploaded: boolean;
  /** Open the 参考資料 (knowledge ingestion) modal — a separate 入口 (§5). */
  onOpenKnowledge: () => void;
  /** Open the セッショントークン設定 modal (local browser↔API auth only). */
  onOpenSettings: () => void;
  /** Open the AIプロバイダー設定 modal (provider + API key — the screen people
   *  actually mean by "API設定"). */
  onOpenLlmSettings: () => void;
}

/** Top bar: project name / menu / connection status / security status
 *  (spec/ui/ide-workbench-spec.md §2, §5). Security is surfaced here per the
 *  UP-004 "make security visible" principle carried over from Streamlit. */
export function Header({
  projectName,
  connected,
  apiBaseUrl,
  theme,
  onToggleTheme,
  onOpenDataset,
  datasetUploaded,
  onOpenKnowledge,
  onOpenSettings,
  onOpenLlmSettings,
}: HeaderProps) {
  return (
    <header className="header">
      <div className="header__brand" title={projectName}>
        {projectName} <span>Workbench</span>
      </div>
      <nav className="header__menu" aria-label="メニュー">
        {/* 解析データ入口（患者データ）— §5 で参考資料入口と視覚的に峻別。 */}
        <button
          type="button"
          className="header__entry header__entry--data"
          data-testid="open-dataset"
          onClick={onOpenDataset}
          title="患者データ（CSV）の取り込み"
        >
          <span aria-hidden="true">🗂️</span> 解析データ
          {datasetUploaded && (
            <span className="header__badge" data-testid="dataset-badge">
              取り込み済み
            </span>
          )}
        </button>
        {/* 参考資料入口（文献）— 別アイコン・別配色で解析データと区別（§5, K-1）。 */}
        <button
          type="button"
          className="header__entry header__entry--knowledge"
          data-testid="open-knowledge"
          onClick={onOpenKnowledge}
          title="参考文献・ガイドラインの取り込み（患者データではありません）"
        >
          <span aria-hidden="true">📚</span> 参考資料
        </button>
        {/* AIプロバイダー設定 — Gemini/OpenAI/AnthropicのAPIキーを入れる場所は
            ここだけ、と一目でわかる常設入口（解析データ/参考資料と同格）。 */}
        <button
          type="button"
          className="header__entry"
          data-testid="open-llm-settings"
          onClick={onOpenLlmSettings}
          title="生成AI（Gemini/OpenAI/Anthropic）のプロバイダー・APIキー設定"
        >
          <span aria-hidden="true">🤖</span> AIモデル
        </button>
      </nav>
      <div className="header__spacer" />

      {/* セッショントークン（ブラウザ↔ローカルAPI間の認証）は起動スクリプトで
          自動設定されるため、接続済みなら操作不要 — 非クリックの状態表示のみに
          して混同を避ける。未接続時だけクリックで設定画面を開けるようにする
          （トラブルシューティング用の控えめな入口）。 */}
      {connected ? (
        <span
          className="status"
          title={`API: ${apiBaseUrl}`}
          data-testid="status-connection"
        >
          <span className="status__dot status__dot--ok" />
          API接続済み
        </span>
      ) : (
        <button
          type="button"
          className="status status--clickable"
          title={`API: ${apiBaseUrl} — クリックでセッショントークン設定を開く`}
          data-testid="status-connection"
          onClick={onOpenSettings}
        >
          <span className="status__dot status__dot--warn" />
          APIトークン未設定
          <span aria-hidden="true" style={{ opacity: 0.7 }}>
            ⚙
          </span>
        </button>
      )}

      <span className="status" data-testid="status-security" title="生データはUIに出ません（var_n匿名化）">
        <span className="status__dot status__dot--secure" />
        匿名化 / オフライン
      </span>

      <button
        type="button"
        className="icon-btn"
        onClick={onToggleTheme}
        aria-label="テーマ切り替え"
        title="ライト / ダーク切り替え"
      >
        {theme === "dark" ? "☀" : "☾"}
      </button>
    </header>
  );
}
