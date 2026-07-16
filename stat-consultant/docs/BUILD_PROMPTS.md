# Stat Consultant — 実装指示プロンプト集

> このファイルは、実装を **1指示＝1検証可能な単位** に分割したプロンプト列です。
> AIの混乱・指示漏れを防ぐため、各プロンプトは自己完結しており、次の4項目を必ず含みます:
> **【前提】直前ステップの完了物 / 【作るもの】 / 【作らないもの】 / 【完了の確認】**
>
> ## 使い方
> - 上から順に、**1回につき1ステップだけ** をコピペしてAIに渡す。
> - 各ステップの【完了の確認】が通ってから次へ進む（通らなければそのステップ内で直す）。
> - すべてのステップは正典 `docs/SPEC.md` に従う。矛盾を感じたら SPEC を優先し、確認する。
> - 各プロンプト冒頭で「まず `docs/SPEC.md` を読んでから着手して」と促すこと。

---

## Step 0 — 土台（足場のみ）

```
docs/SPEC.md を読んでから着手してください。今回は Step 0 のみを行います。

【前提】stat-consultant/docs/ に SPEC.md と本プロンプト集がある状態。

【作るもの】
- stat-consultant/backend/: Python の FastAPI + uvicorn プロジェクト最小構成
  （pyproject.toml か requirements.txt、起動エントリ、GET /health が {"status":"ok"} を返すだけ）。
- stat-consultant/frontend/: Vite + React + TypeScript の最小構成（`npm create vite` 相当）。
  デフォルト画面が表示できればよい。
- stat-consultant/r-addin/: R パッケージの空の骨格（DESCRIPTION、inst/rstudio/addins.dcf の
  プレースホルダのみ。中身の関数は空でよい）。
- ルートに、各サブプロジェクトの起動方法を書いた短い README。

【作らないもの】
- アプリのロジック（チャット・LLM呼び出し・UI部品）は一切書かない。
- 既存の cie/ や リポジトリ直下の frontend/ には一切触れない。

【完了の確認】
- backend: uvicorn 起動 → `curl localhost:8000/health` が {"status":"ok"}。
- frontend: `npm run dev` 起動 → ブラウザにViteの初期画面が出る。
```

---

## Step 1 — バックエンド: 最小チャットWebSocket

```
docs/SPEC.md を読んでから着手してください。今回は Step 1 のみを行います。

【前提】Step 0 完了（backend が起動し /health が通る）。

【作るもの】
- WebSocket エンドポイント `/ws/consult` を1本。
- 会話履歴の保持（cie/api/conversation.py の ConversationStore を翻案してよい。移植元は
  触らず、backend 内に新規で置く）。
- 統計相談員ペルソナのシステムプロンプト（SPEC 第2〜3節のトーン: 気軽に相談できる統計の
  専門家。雑談も許容。情報が足りなければ質問を返してよい。1メッセージで完結させる縛りは無い）。
- クラウドLLM（Claude）を呼び、応答をテキストとしてストリーム送信する。

【作らないもの】
- コード/理由の構造化（Step 2で行う）。今はプレーンテキスト応答でよい。
- 環境コンテキスト、参考資料、画像、RStudio連携（後続ステップ）。

【完了の確認】
- websocat 等で /ws/consult に接続し「t検定のコードを教えて」と送ると、
  会話が成立するテキスト応答がストリームで返る。2往復目に文脈が引き継がれる。
```

---

## Step 2 — バックエンド: コード＋理由の構造化出力

```
docs/SPEC.md を読んでから着手してください。今回は Step 2 のみを行います。

【前提】Step 1 完了（/ws/consult が会話できる）。

【作るもの】
- 応答を SPEC 4.4 のメッセージ種別に構造化してストリームする:
  assistant_text（一言理由＋折りたたみ用の詳細を別フィールド）と assistant_code（コード本体）。
- 1つの応答に複数の assistant_code ブロックが含まれてよい。
- skills/core/statistics/*/SKILL.md から Rコード事例を抽出し few-shot としてシステム
  プロンプトに埋め込む（intent_object / skill_result のスキーマ部分は捨てる）。
- 生成コードには必ず一言の理由・前提（例:「対応のないt検定／正規性を仮定」）を添える。

【作らないもの】
- フロント表示（Step 3）。環境・参考資料・画像（後続）。

【完了の確認】
- /ws/consult に統計質問を送ると、{assistant_text: 理由＋詳細, assistant_code: Rコード} の
  構造化フレームが返る。理由が常に付与されている。
```

---

## Step 3 — フロントエンド: チャット3要素の骨格

```
docs/SPEC.md を読んでから着手してください。今回は Step 3 のみを行います。

【前提】Step 2 完了（構造化フレームが返る）。

【作るもの】
- frontend に最小SPA: メッセージ列 / 入力欄 / 送信（Enter送信ショートカット）。
  cie 直下の frontend/src/components/ChatPane.tsx の入力欄・WS接続・送信処理を翻案してよい。
- assistant_text を表示し、詳細は折りたたみ（クリックで展開）。
- assistant_code をシンタックスハイライト付きカードで表示。
- 各コードカードに「RStudioへ送る」ボタンを置く（見た目のみ。配線は Step 5）。
- SPEC 4.1/4.2 の外観を適用: アプリモードウィンドウ前提のレイアウト、Light & Clean、
  Deep Teal アクセント1色（送信・「RStudioへ送る」ボタンのみ）。

【作らないもの】
- 添付ボタン（Step 4）、ボタンの実配線（Step 5）。
- 会話履歴サイドバー/モデル選択/設定/認証UI（SPEC 4.5、恒久的に作らない）。

【完了の確認】
- npm run dev → ブラウザで質問送信 → 理由（折りたたみ）＋ハイライトされたコード＋
  「RStudioへ送る」ボタンが描画される。外観が SPEC の確定案に沿う。
```

---

## Step 4 — 参考資料アップロード（← Phase 1 完了）

```
docs/SPEC.md を読んでから着手してください。今回は Step 4 のみを行います。

【前提】Step 3 完了（ブラウザでチャットが成立）。

【作るもの】
- backend: `POST /api/references`。Markdown/テキストを単一フォルダ
  （例 stat-consultant/backend/user_references/）に保存するだけ。承認フロー・階層区別なし。
  保存後、cie/knowledge/reference_library.py の MarkdownReferenceLibrary を翻案した
  検索器へ反映（ディレクトリ再読み込みで足りる）。
- backend: チャット応答生成時、直近のユーザー発言のキーワードで retrieve(query_terms, top_k=2)
  を呼び、ヒット抜粋をプロンプトへ含める。
- frontend: 添付ボタン1つ。ファイル種別で自動判別（Markdown/テキスト → /api/references）。
  添付直後にトースト「参考資料として保存しました」。

【作らないもの】
- 画像添付の Vision 処理（Step 9）。今は Markdown/テキストのみ扱い、画像は Step 9 で。
- 添付ボタンを2つに増やさない。

【完了の確認】
- 参考資料 .md をアップロード → トースト表示 → 次の質問で、その資料の内容が回答に
  反映される（資料内の固有表現を含めて確認）。
```

---

## Step 5 — RStudio送信の配管＋クリップボードfallback

```
docs/SPEC.md を読んでから着手してください。今回は Step 5 のみを行います。

【前提】Step 4 完了（Phase 1 が動作）。

【作るもの】
- backend: `POST /api/rstudio/insert {code}`（送信対象コードをキュー）と
  `GET /api/rstudio/pending`（挿入待ちコードを返す。またはローカルWS push）。
- frontend: 「RStudioへ送る」ボタンを配線。押下で /api/rstudio/insert を呼ぶ。
- frontend: Addin未接続を検知した場合は自動でクリップボードにコピーし
  「コピーしました」とトースト（Phase 1 の代用策を恒久フォールバックに格上げ）。

【作らないもの】
- Addin本体（Step 6）。環境スキャン（Step 7）。

【完了の確認】
- ボタン押下で /api/rstudio/insert にコードがキューされる（/pending で確認）。
- Addin未接続状態でボタンを押すと、クリップボードにコードが入りトーストが出る。
```

---

## Step 6 — RStudio Addin: コード挿入（← Phase 2 完了）

```
docs/SPEC.md を読んでから着手してください。今回は Step 6 のみを行います。

【前提】Step 5 完了（/api/rstudio/insert と /pending が動く）。

【作るもの】
- r-addin: addins.dcf に「コード挿入」アドインを登録。
- /api/rstudio/pending をポーリング（or ローカルWS購読）し、取得したコードを
  rstudioapi::insertText() でアクティブドキュメントのカーソル位置へ挿入。
- 認証: バックエンド起動時に生成されるローカル共有シークレットファイルを Addin が
  既知パスから読むゼロコンフィグ方式（トークン手貼りなし）。backend 側もそのファイルを生成。

【作らないもの】
- 環境スキャン（Step 7）。トークンをUIで貼らせる仕組み（作らない）。

【完了の確認】
- 実RStudioに Addin をインストール → チャットの「RStudioへ送る」を押すと、
  開いているスクリプトのカーソル位置に該当コードが挿入される。
```

---

## Step 7 — RStudio Addin: 環境スキャン＋PII除外

```
docs/SPEC.md を読んでから着手してください。今回は Step 7 のみを行います。

【前提】Step 6 完了（コード挿入が動く）。

【作るもの】
- r-addin: Addin起動中、チャット送信の裏で自動的に ls(.GlobalEnv) を走査し、各オブジェクトの
  class / 列名 / 型 / n_missing（欠損数）/ カテゴリ・factor列の水準ラベルと件数を収集
  （SPEC 9.1 のペイロード形）。集計のみ。行データ（セル値）は絶対に含めない。
- PII除外: cie/security/pii_detector.py の PIIDetectorLayer1.detect を翻案し、列名または
  水準ラベルにPII所見が出た列は型・欠損・水準を丸ごと除外してから送信（SPEC 9.2）。
- `POST /api/environment/sync` に送信。ユーザー操作は不要（透明な同期。手動更新ボタンなし）。

【作らないもの】
- バックエンドでのコンテキスト注入（Step 8）。全列一律の var_n 匿名化（しない）。

【完了の確認】
- RStudioで data.frame を読み込む → 少し後に /api/environment/sync に列名・型・欠損・
  群の件数が届く（サーバーログで確認）。patient_name 等の識別子列は除外されている。
- df$new <- ... で作った派生列も次回同期で現れる。
```

---

## Step 8 — バックエンド: 環境コンテキスト注入（← Phase 3 完了）

```
docs/SPEC.md を読んでから着手してください。今回は Step 8 のみを行います。

【前提】Step 7 完了（/api/environment/sync に集計が届く）。

【作るもの】
- backend: セッション毎に最新の環境スナップショットを保持。
- チャット応答生成時、そのスナップショット（実列名・型・群数・欠損）をプロンプトへ注入。
- これにより「この検定で合ってる？」に対し、実データに基づく前提条件チェックと手法提案が返る
  （例:「group は3水準なので一元配置分散分析が候補。血圧に欠損15件、除外か多重代入か」）。

【作らないもの】
- 画像/Vision（Step 9）。

【完了の確認】
- 3群のデータを読み込んだ状態で「群間比較したい」→ 回答が「3群」に言及し ANOVA 系を提案。
- 欠損のある列について尋ねると、欠損数に触れた助言が返る。
```

---

## Step 9 — 参考図→ggplot2（Vision）（← Phase 4 完了）

```
docs/SPEC.md を読んでから着手してください。今回は Step 9 のみを行います。

【前提】Step 8 完了（環境コンテキストが効いている）。

【作るもの】
- frontend: 添付ボタンで画像を選ぶと「その場限りの参考図」として扱い、そのターンだけ
  送信する（永続保存しない）。添付時トースト「今回の参考図として送信します」。
- backend: 画像添付時は Vision 対応のLLM呼び出しに切り替え、図のスタイル要素（種別・軸・
  色・レイアウト等）を解析し、同期済みの実データ列にマッピングした ggplot2 コードを生成。

【作らないもの】
- RStudio Plotペインのキャプチャ／自己修正ループ（作らない。参考図起点の生成のみ）。

【完了の確認】
- 論文の図（例: 群別箱ひげ図）を添付 → 実データの列にマッピングされた ggplot2 コードが
  生成され、「RStudioへ送る」で挿入できる。
```

---

## 付録: 全体の検証（全ステップ完了後）

3つの痛みを通しで確認する（SPEC 第12節の受け入れ確認）:
1. 「〇〇群と△△群を比較したい」→ コード＋理由が返り、RStudioに1クリックで挿入される。
2. 「この検定で合ってる？」→ 実データの型・群数・欠損に基づく前提説明が返る。
3. 論文の図を添付 → 実データ列にマッピングされたggplot2コードが生成される。
