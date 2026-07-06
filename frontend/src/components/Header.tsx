import type { Theme } from "../theme";

interface HeaderProps {
  projectName: string;
  connected: boolean;
  apiBaseUrl: string;
  theme: Theme;
  onToggleTheme: () => void;
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
}: HeaderProps) {
  return (
    <header className="header">
      <div className="header__brand" title={projectName}>
        {projectName} <span>Workbench</span>
      </div>
      <nav className="header__menu" aria-label="メニュー">
        <button type="button">プロジェクト</button>
        <button type="button">解析データ</button>
        <button type="button">参考資料</button>
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
