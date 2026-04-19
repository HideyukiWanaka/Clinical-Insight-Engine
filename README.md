# Clinical Insight Engine (CIE)

臨床研究者向けのAIパワードデータ解析・レポート自動生成プラットフォーム。

CSVデータのアップロードから、Rによる統計解析 → AI可視化 → Google Slidesへの自動差し込みまでをノーコードで実現。全ての解析はRStudioで完全再現可能。

---

## アーキテクチャ

| レイヤー | 技術スタック |
|---------|------------|
| **Frontend** | Next.js (App Router), TypeScript, TailwindCSS, Zustand |
| **Backend** | Python 3.11+, FastAPI |
| **Statistical Engine** | Dockerized R + Plumber（外部ネットワーク遮断） |
| **AI Service** | Claude API（列名・型・欠損率のメタデータのみ送信） |
| **Database** | PostgreSQL |
| **Session Storage** | Redis（臨床データはTTL付きで揮発） |
| **Integrations** | Google Workspace API, OAuth 2.0 |

---

## ローカル開発環境の起動

```bash
# 環境変数の設定
cp .env.example .env
# .env を編集して各種APIキーを設定

# 全サービスの起動
docker-compose up --build

# アクセス
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
# API Docs: http://localhost:8000/docs
```

---

## プロジェクト構成

```
clinical-insight-engine/
├── frontend/          # Next.js App Router
├── backend/           # FastAPI
├── r-engine/          # Dockerized R + Plumber
│   └── skills/        # Analysis Skills（.Rファイル）
├── docs/              # 仕様書・設計ドキュメント
│   ├── SRD_完全版.md
│   └── 実装プロンプト集.md
├── docker-compose.yml
└── .env.example
```

---

## Analysis Skills（v1）

| スキル | 用途 |
|-------|------|
| table1_generator | Table 1（記述統計表） |
| chi_square_fisher | χ²検定 / Fisher正確検定 |
| ttest_mannwhitney | t検定 / Mann-Whitney U検定 |
| normality_check | 正規性検定 + 分布確認 |
| logistic_regression | ロジスティック回帰 |
| linear_regression | 線形回帰 |
| kaplan_meier | Kaplan-Meier曲線 |
| cox_regression | Cox比例ハザード回帰 |
| correlation_analysis | 相関分析 |
| roc_auc | ROC曲線・AUC |
| forest_plot | フォレストプロット |
| sample_size_calc | サンプルサイズ計算 |

---

## セキュリティポリシー（Zero Trust）

- 臨床データ（CSV/Excel）はRedisにのみ保存（TTL: 24h、解析完了後即削除）
- LLM APIには列名・型・欠損率のメタデータのみ送信（生データ行は絶対に送信しない）
- Rコンテナはインターネットアクセス遮断
- 全解析はreproducible_script.Rとして出力（RStudioで完全再現可能）

---

## ドキュメント

- [SRD（完全版仕様書）](./docs/SRD_完全版.md)
- [実装プロンプト集](./docs/実装プロンプト集.md)

---

## License

Private Repository — All Rights Reserved
