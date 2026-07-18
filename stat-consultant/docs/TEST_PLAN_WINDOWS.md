# stat-consultant — Windows実機テストプラン

> `docs/TEST_PLAN.md`（Mac/Linux向け実機テストプラン）の補完ドキュメント。
> Step 7-9のアプリケーションロジック自体はOS非依存なので、シナリオ本文は
> 重複させず、ここでは**Windows固有の環境構築・追加チェックポイントのみ**を
> 扱う。Step 7-9個別シナリオ本体（S7-1〜S9-4）とSPEC §12通し確認は、W1で
> パス一致が確認できてから `TEST_PLAN.md` §2〜§5 をそのまま参照して実施する。

## 0. 概要

`TEST_PLAN.md` 作成時、`rstudio_auth.py` に明記されている以下のリスクが
未検証のまま残っていた:

> Pythonの `Path.home()`（`USERPROFILE`）とRの `path.expand("~")`
> （`R_USER`/`HOME`）がWindowsでは食い違いうる

このリスクは3箇所のコードで実際に指摘されている:
- `backend/app/rstudio_auth.py:24-28`（`TOKEN_DIR = Path.home() / ".stat-consultant"`
  の直前コメント）
- `backend/app/rstudio_auth.py:45`（`chmod` はWindowsでは実質無効という注記）
- `r-addin/R/token.R:14-15`（トークンファイル未検出時のエラーメッセージで
  「Windowsでパスが食い違う場合は起動ログの絶対パスと比較を」と案内）

**重要**: 現在の実装には、この食い違いに対する回避策（パス上書きオプション等）
が一切無い。`token.R` にも `rstudio_auth.py` にも `getOption()` 相当の上書き
機構は存在しない。食い違いが実際に起きた場合、Addinは恒久的にトークン
ファイルを見つけられず、環境同期・コード挿入の両方が機能しない
（`tryCatch` で握りつぶされるためクラッシュはしないが、Rコンソールに
エラーメッセージが出続ける）。

そのため本プランは、**他のどのシナリオよりも先に「W1: トークンパス一致診断」
を単独で実施する**構成にしている。ここで不一致が出れば、それ以降の
Step 7-9シナリオは軒並り失敗しうるため、原因の切り分けとして最初に潰す。

## 1. 環境構築（Windows差分）

`TEST_PLAN.md` §1 のMac/Linux向けコマンドをWindows向けに読み替える。
それ以外（APIキー設定・テスト用サンプルデータ）は共通。

### 1.1 backend（PowerShell）

```powershell
cd stat-consultant\backend
python -m venv .venv
.venv\Scripts\pip.exe install -e .
.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

`.venv\Scripts\Activate.ps1` によるactivateは実行ポリシー
（`Set-ExecutionPolicy`）の制約を受けることがあるため必須にしない。
上記のように `.venv\Scripts\*.exe` を直接呼べばactivate不要。

確認: `curl.exe http://localhost:8000/health` → `{"status":"ok"}`
（PowerShellの `curl` エイリアスは `Invoke-WebRequest` を指すことがあるため、
`curl.exe` と明示するか `Invoke-WebRequest http://localhost:8000/health` を使う）。

### 1.2 frontend

```powershell
cd stat-consultant\frontend
npm install
npm run dev
```

Mac/Linuxと同一コマンド。Windows固有の差分は無い。

### 1.3 r-addin のインストール

```r
install.packages(c("rstudioapi", "httr2", "later"))
remotes::install_local("stat-consultant/r-addin")
```

Mac/Linuxと同一コマンド。r-addinは `src/` を持たない純Rパッケージ
（コンパイル対象コード無し）なので、通常はRtoolsのインストールなしで
動作する。依存パッケージ（`httr2`/`later`/`rstudioapi`）はCRANの
Windowsバイナリが提供されているため、通常はソースからのビルドも発生しない。
万一 `install.packages` がソースビルドを試みて失敗する場合のみ、
[Rtools](https://cran.r-project.org/bin/windows/Rtools/) の導入を検討する
（本プランではこのケースの発生有無も記録する）。

### 1.4 コンソール文字化け対策

cmd.exe / 古いPowerShellの既定コードページ（例: 日本語版Windowsの932）では、
backendが出力するUTF-8ログ（`[stat-consultant] ...`）やRの `message()` に
よる日本語出力が文字化けすることがある。テスト開始前に以下のいずれかを行う:

- PowerShell/cmdで `chcp 65001` を実行してからbackend/Rを起動する
- Windows Terminal（既定でUTF-8対応）を使う

文字化けが起きた場合、テスト結果としては「実際にはログは正しく出力
されているが表示が壊れているだけ」なのか「本当に文字化けした内容が
送信/保存されているのか」を区別できるよう、疑わしい場合はbackendの
ログファイル（あれば）やRStudioの `Console` ペインを直接確認する。

### 1.5 ファイアウォール

`uvicorn`（ポート8000）およびVite dev server（既定5173）が待受を開始する際、
Windows Defender ファイアウォールがネットワークアクセス許可のプロンプトを
出すことがある。「プライベートネットワーク」として許可する。

---

## 2. W1: トークンパス一致診断（最優先・単独で最初に実施）

`TEST_PLAN.md` の Step 7 シナリオ（S7-1以降）に進む**前に**、必ずこの診断を
単独で行う。

### 手順

1. backendを起動し、起動ログに出る以下の行の `<path>` 部分を記録する:
   ```
   [stat-consultant] RStudio shared secret written to <path>
   ```
2. RStudioのコンソール（Addinを起動する前でよい）で以下を実行し、返って
   きたパスを記録する:
   ```r
   path.expand(file.path("~", ".stat-consultant", "rstudio_token"))
   ```
3. 2つのパスを文字列として比較する（大文字小文字・区切り文字
   `\` vs `/` の違いは実質同一パスとみなしてよい。Windowsのパスは
   大文字小文字を区別しないため）。

### 期待される結果（2通りをどちらも「診断完了」として扱う）

- **(a) 一致する場合**: そのまま `TEST_PLAN.md` §2〜§5（S7-1〜S9-4、
  SPEC §12通し確認）をWindows上でも通常どおり実施できる。この結果を記録し、
  次章 W2 以降に進む。
- **(b) 不一致の場合**: これはバグではなく、現行実装の**既知の未対応制約**
  として扱う。以下のワークアラウンドを試し、結果を記録する:
  1. RStudioを一旦終了する。
  2. OSの環境変数（システム環境変数、またはユーザー環境変数）で
     `R_USER` を、手順1で記録したPython側のパスの親ディレクトリ
     （`Path.home()` が指す場所）に設定する。
  3. RStudioを再起動し、手順2の `path.expand(...)` を再実行して
     一致するか確認する。
  4. ワークアラウンドでも一致しない場合、この結果自体をフォローアップ
     課題として記録する（例:「r-addin側にbaseUrlと同様の
     `getOption("statConsultant.tokenPath")` のような上書きオプションを
     追加する」といった改善案）。本テストプランの範囲では**コード修正は
     行わない**——現象と回避策の記録までがスコープ。

### 検証基準

- ✓ 2つのパスを実際に突き合わせた記録（両方の文字列）が残っている
- ✓ 不一致だった場合、ワークアラウンド試行の結果（成功/失敗）が記録されている
- ✓ 不一致が解消できなかった場合、以降のW2章のシナリオが「未実施」または
  「失敗（既知の原因あり）」として明確に記録され、他の原因による失敗と
  混同されていない

---

## 3. W2: `TEST_PLAN.md` シナリオのWindows再実施

W1でパス一致が確認できた（またはワークアラウンドで一致させた）前提で、
`TEST_PLAN.md` の以下の章をWindows環境で**同一のサンプルデータ・同一手順**
のまま実施する:

- `TEST_PLAN.md` §2 — Step 7 シナリオ群（S7-1〜S7-7: 環境スキャン＋PII除外）
- `TEST_PLAN.md` §3 — Step 8 シナリオ（S8-1〜S8-2: 環境コンテキスト注入）
- `TEST_PLAN.md` §4 — Step 9 シナリオ（S9-1〜S9-4: 参考図→ggplot2）
- `TEST_PLAN.md` §5 — SPEC §12 受け入れ確認（3つの痛みの通し確認）

Addin名は `TEST_PLAN.md` §1.4 で確認したとおり「Stat Consultant: 開始／停止」
（Step 6時点の README.md の古い表記「コード挿入: 開始／停止」ではない）。

### Windows固有の追加チェックポイント

これらは `TEST_PLAN.md` 側の検証基準に**追加**して確認する項目であり、
既存シナリオの検証基準を置き換えるものではない。

- **W2-a（トークンファイルのアクセス権）**: `chmod 0600` はWindowsでは
  実質無効（`rstudio_auth.py:45` のコメントどおり）。そのため
  `%USERPROFILE%\.stat-consultant\rstudio_token` が既定で同一マシンの
  他ユーザーからも読める状態になりうる。個人利用・単一ユーザーPCという
  SPECの前提上は致命的ではないが、共有PCで使う場合のリスクとして記録に残す
  （このテストでは「実際にそうなっているか」の確認のみ行い、修正はしない）。
- **W2-b（クリップボードフォールバック）**: Step 5の「RStudioへ送る」
  未接続時フォールバックが、Windows版Chrome/Edgeでも同様に機能すること。
  `navigator.clipboard` は `http://localhost` をセキュアコンテキストとして
  扱うため通常問題ないはずだが、実機のブラウザで実際にクリップボードへ
  コピーされること・トーストが出ることを目視確認する。
- **W2-c（文字化けの目視確認）**: §1.4の対策後、S7〜S9で生成される
  日本語混じりのRコード・チャット応答・backendログが正しく表示されている
  ことを確認する。

---

## 4. 実行チェックリスト

### 実行前
- [ ] backend が起動し `/health` が 200 を返す（PowerShellの `curl.exe` で確認）
- [ ] frontend が `npm run dev` で起動しブラウザで開ける
- [ ] r-addin がインストール済みで、Addinsメニューに
      「Stat Consultant: 開始／停止」が出る
- [ ] **W1のトークンパス一致診断を完了している**（本チェックリストの必須項目。
      未実施のままW2に進まない）

### 実行中
- [ ] W1 の結果（一致 / 不一致＋ワークアラウンド結果）
- [ ] `TEST_PLAN.md` §2〜§5 の各シナリオの結果（Windows特有の失敗があれば
      W1不一致が原因かどうかを明記）
- [ ] W2-a・W2-b・W2-c の追加チェックポイントの結果

### 実行後
- [ ] W1で不一致が見つかった場合、フォローアップ課題として記録したか
      （パス上書きオプションの追加提案など）
- [ ] `TEST_PLAN.md` 側に記録すべきWindows特有の既知問題があれば転記したか

---

## 5. 注記

- W1でトークンパスの不一致が確認された場合、本プランでは**現象の記録と
  ワークアラウンドの試行まで**がスコープであり、パス解決を統一するための
  コード修正（例: 明示的なパス上書きオプションの追加）は別タスクとして扱う。
- LLMの応答が非決定的である点、検証基準が意味的な判定になる点は
  `TEST_PLAN.md` と同様。
- 本ドキュメントはこのセッションでは**実行されていない**（実機Windowsが
  無いため）。作成のみがスコープであり、実施と結果記録はユーザー自身が行う。
