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
"""

from __future__ import annotations

FEWSHOT = r"""
# R手法リファレンス（検証済みテンプレート集の要点）

以下は臨床統計でよく使う手法の「選択ルール」と「正しいRの呼び出し方」。
実データの列名・型・群数・欠損に応じて、適切な分岐を選び、列名は実際のものに置き換えること。

## 2群比較（連続アウトカム）— statistics/t-test
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
"""
