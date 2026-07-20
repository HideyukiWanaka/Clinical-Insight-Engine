"""R method-selection few-shot, extracted from skills/core/statistics/*/SKILL.md.

Per SPEC §11 and BUILD_PROMPTS Step 2: pull the *R code idioms and selection
rules* out of the five statistics SKILLs and keep them; drop the schema
scaffolding (``intent_object`` / ``skill_result <- list(...)`` / ``var_n``
placeholders). This is a self-contained distillation placed inside the backend
(the source ``skills/`` tree is not touched and is not read at runtime), so the
backend does not depend on the repo layout outside ``stat-consultant/``.

Placeholder names (``outcome``, ``group``, ``x``, …) stand in for real column
names — the model substitutes the user's actual, synced column names. We
deliberately avoid the ``var_n`` anonymisation (SPEC §9.2) so natural references
like 「血圧」 survive.

Source skills: statistics/t-test, /anova, /correlation, /regression, /survival.

The visualization section below is not extracted from a skills/ SKILL.md (no
stat-consultant-shaped visualization skill exists in skills/core/visualization/
— those are output-pipeline-oriented for a different agent, with
OUTPUT_DIR/figure_manifest scaffolding that doesn't fit a chat code snippet).
Instead it distills recurring mistakes found during real-machine testing
(docs/TEST_FINDINGS.md) against official/authoritative sources:
- geom_bar()/geom_col() semantics (stat_count vs stat_identity) and
  position_stack()/position_fill() stacking-per-row behaviour:
  https://ggplot2.tidyverse.org/reference/geom_bar.html
- canonical group_by()+summarise()+geom_col(position="fill") percent-stacked-bar
  pattern: https://r-graph-gallery.com/48-grouped-barplot-with-ggplot2
- droplevels() after subsetting a factor:
  https://stat.ethz.ch/R-manual/R-devel/library/base/html/droplevels.html
- cross-platform CJK text rendering (showtext, CRAN):
  https://cran.rstudio.com/web/packages/showtext/vignettes/introduction.html
"""

from __future__ import annotations

FEWSHOT = r"""
# R手法リファレンス（検証済みテンプレート集の要点）

以下は臨床統計でよく使う手法の「選択ルール」と「正しいRの呼び出し方」。
実データの列名・型・群数・欠損に応じて、適切な分岐を選び、列名は実際のものに置き換えること。

## ユーザーがRのエラーメッセージを貼ってきたとき
実行はユーザーがRStudioで行うので、失敗したらエラー文を貼ってくることがある。そのときは:
- エラー文と、直前に提案した自分のコード、そして「ユーザーのRStudio環境」セクションの
  同期スキーマ（列名・型・水準数）を突き合わせて原因を特定する（例: 列名の綴り違い、
  factorに未使用水準が残っている、パッケージ未インストール、群ごとの有効データ不足）。
- 推測で「たぶんこれ」と別の全く新しいコードに飛ばさず、原因を一言（reason）で述べてから
  最小限の修正版を code ブロックで返す。原因がスキーマから確定できないときは、確認のために
  必要な情報（例: `str(df)` の結果）を質問する。

## 2群比較（連続アウトカム）— statistics/t-test
- **ユーザーが2群比較を頼んできても、まずgroup変数の同期済み水準数を確認すること。**
  「ユーザーのRStudio環境」セクションでgroup変数（や群を表す列）に3水準以上あると
  分かっている場合は、それに気づかずコードだけ出してはいけない。text ブロックの
  reason または detail で必ず一言触れる（例:「実際は◯水準（Placebo/DrugA/DrugB）
  あるが、今回はPlaceboとDrugAの2群比較でよいか。全体の差を見たいなら一元配置分散
  分析（ANOVA）やKruskal-Wallis検定も候補」）。2水準しかないと確認できた場合のみ、
  この指摘は不要。
- 正規性は各群で shapiro.test() で確認（n<3 は判定不能）。
- 独立・正規 → Welchのt検定:
    t.test(outcome ~ group, data = df, var.equal = FALSE)
    # 効果量 Cohen's d（プールSDで算出）
- 独立・非正規 → Mann-WhitneyのU検定:
    wilcox.test(outcome ~ group, data = df, exact = FALSE)
- 対応あり・正規 → 対応のあるt検定（式ではなくベクトルで渡す）:
    t.test(pre, post, paired = TRUE)
- 対応あり・非正規 → Wilcoxon符号順位検定:
    wilcox.test(pre, post, paired = TRUE, exact = FALSE)
- 対応ありは差の正規性（shapiro.test(pre - post)）で判定する。
- group が3水準以上あり、そのうち2水準だけを比較する場合、`subset=`や行フィルタ
  だけでは未使用水準がfactorに残り「grouping factor must have exactly 2 levels」
  エラーになる。必ず droplevels() で絞り込んでから式インターフェースに渡すこと:
    df2 <- droplevels(df[df$group %in% c("A", "B"), ])
    t.test(outcome ~ group, data = df2, var.equal = FALSE)
  - なお、比較対象の群でoutcomeの有効値（非欠損）が極端に少ない／ゼロの場合も
    同じエラー文言（"grouping factor must have exactly 2 levels"）が出ることがある
    （NAを含む行は検定前に自動的に除外されるため）。列単位の欠損数しか分からない
    場合は、コードを毎回増やす必要はないので、text ブロックの detail で「群ごとの
    有効データ数が極端に少ないとこのエラーが出ることがある」と一言注意を添えておく。

## 多群比較（連続アウトカム, 3群以上）— statistics/anova
- 正規性は各群 shapiro.test()、等分散は car::leveneTest() で確認。
- 独立・正規・等分散 → 一元配置分散分析:
    m <- aov(outcome ~ group, data = df); summary(m)
    # 事後検定（omnibus p<0.05 のときのみ）: TukeyHSD(m)
- 独立・正規・不等分散 → WelchのANOVA:
    oneway.test(outcome ~ group, data = df, var.equal = FALSE)
    # 事後検定: rstatix::games_howell_test(df, outcome ~ group)
- 独立・非正規 → Kruskal-Wallis検定:
    kruskal.test(outcome ~ group, data = df)
    # 事後検定: rstatix::dunn_test(df, outcome ~ group, p.adjust.method = "holm")
- 反復測定・正規 → 反復測定分散分析:
    aov(outcome ~ group + Error(subject/group), data = df)
    # 事後検定: pairwise.t.test(df$outcome, df$group, paired = TRUE, p.adjust.method = "holm")
- 反復測定・非正規 → Friedman検定:
    friedman.test(outcome ~ group | subject, data = df)
- 事後検定は omnibus p < 0.05 のときだけ行う。

## 相関（連続×連続）— statistics/correlation
- 両変数の正規性を shapiro.test() で確認。
- 両方正規 → Pearson:
    cor.test(x, y, method = "pearson")   # CIは直接得られる
- どちらか非正規 → Spearman:
    cor.test(x, y, method = "spearman", exact = FALSE)
    # SpearmanのCIはブートストラップで（set.seed(42) を必ず置く）

## 回帰（多変量）— statistics/regression
- 連続アウトカム → 線形回帰:
    m <- lm(outcome ~ x1 + x2 + x3, data = df); summary(m); confint(m)
    # 残差正規性 shapiro.test(residuals(m))、多重共線性 car::vif(m)（VIF<5が目安）
- 二値アウトカム → ロジスティック回帰:
    m <- glm(outcome ~ x1 + x2, data = df, family = binomial(link = "logit"))
    exp(cbind(OR = coef(m), confint(m)))   # オッズ比とCI
    # イベント数/予測変数 < 10 のときは Firth: logistf::logistf(outcome ~ x1 + x2, data = df)

## 生存時間解析 — statistics/survival
- time>0、event は 0/1 で符号化されていることを確認。
    library(survival)
    fit <- survfit(Surv(time, event) ~ group, data = df)   # Kaplan-Meier
    survdiff(Surv(time, event) ~ group, data = df)          # log-rank検定
    cox <- coxph(Surv(time, event) ~ group + covariate, data = df, x = TRUE)
    summary(cox)                                            # HR = exp(coef)
    cox.zph(cox)   # 比例ハザード性の確認（違反時は strata() を検討）

## 可視化（ggplot2）でよくある落とし穴
- 積み上げ棒グラフ／100%積み上げ棒グラフ（構成比の可視化）:
  geom_bar() は「行数（ケース数）」を自動集計する（stat_count）。geom_col() は
  既に集計済みの値をそのまま高さにする（stat_identity）。同じ x + fill の組み
  合わせに複数行が対応する生データを、集計せずそのまま geom_col(position =
  "fill") / geom_bar(stat = "identity", position = "fill") に渡すと、行数分の
  細いセグメントに分割されて積み上がってしまう（1行=1スライス）。
  必ず先に group_by() + summarise()（合計または平均）で「x × fill の組み合わせ
  ごとに1行」まで集計してから渡すこと:
    df_summary <- df_long %>%
      group_by(group, category) %>%
      summarise(value = mean(value, na.rm = TRUE), .groups = "drop")
    ggplot(df_summary, aes(x = group, y = value, fill = category)) +
      geom_col(position = "fill") +
      scale_y_continuous(labels = scales::percent_format())
- 日本語・CJK文字を含む列名/ラベルの描画:
  RStudioのグラフィックデバイス（AGG等）は日本語グリフに対応するフォントを
  デフォルトで持たないため、軸ラベルや凡例の日本語が文字化けすることがある。
  base_family にOS固有のフォント名（例: macOSの "HiraginoSans-W3"）を
  ハードコードしない — Windows/Linuxや別マシンでは存在せず同じ問題が再発する。
  代わりに showtext パッケージ（CRAN公式、クロスプラットフォーム）を使う:
    library(showtext)
    showtext_auto()
    # 以降の ggplot2 出力は自動的にCJKグリフを正しく描画する
  showtext が未インストールの場合は install.packages("showtext") を一言案内する。
"""
