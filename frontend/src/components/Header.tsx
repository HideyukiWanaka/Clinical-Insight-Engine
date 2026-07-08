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
}: HeaderProps) {
  return (
    <header className="header">
      <div className="header__brand" title={projectName}>
        {projectName} <span>Workbench</span>
      </div>
      <nav className="header__menu" aria-label="メニュー">
        <button type="button">プロジェクト</button>
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
      </nav>
      <div className="header__spacer" />

      <span
        className="status"
        title={`API: ${apiBaseUrl}`}
        data-testid="status-connection"
      >
        <span
          className={"status__dot " + (connected ? "status__dot--ok" : "status__dot--warn")}
        />
        {connected ? "API接続済み" : "APIトークン未設定"}
      </span>

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
