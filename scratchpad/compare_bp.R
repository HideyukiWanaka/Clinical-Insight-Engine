# ============================================================
# Block 1: Environment Setup
# ============================================================
set.seed(42)
# ロケールの設定（日本語対応）
if (.Platform$OS.type == "unix") {
  Sys.setlocale("LC_ALL", "ja_JP.UTF-8")
}

# ============================================================
# Block 2: Data Loading
# ============================================================
csv_path <- "/Users/wanakahideyuki/Desktop/health_screening_japan.csv"
data <- read.csv(csv_path, fileEncoding = "UTF-8", stringsAsFactors = FALSE)

# 必要な列の抽出とクリーニング
# 性別, 収縮期血圧_mmHg, 拡張期血圧_mmHg
data <- data[!is.na(data$性別) & data$性別 %in% c("男性", "女性"), ]
data$性別 <- factor(data$性別)

compare_groups <- function(outcome_var) {
  # 欠損値の除去
  sub_data <- data[!is.na(data[[outcome_var]]), ]
  
  groups <- levels(sub_data$性別)
  grp1 <- sub_data[[outcome_var]][sub_data$性別 == groups[1]]
  grp2 <- sub_data[[outcome_var]][sub_data$性別 == groups[2]]
  
  # 1. 正規性検定 (Shapiro-Wilk)
  sw1 <- if (length(grp1) >= 3) shapiro.test(grp1)$p.value else NA
  sw2 <- if (length(grp2) >= 3) shapiro.test(grp2)$p.value else NA
  
  normality_passed <- (!is.na(sw1) && sw1 > 0.05) && (!is.na(sw2) && sw2 > 0.05)
  
  # 2. 統計検定の実行
  if (normality_passed) {
    res <- t.test(sub_data[[outcome_var]] ~ sub_data$性別, var.equal = FALSE)
    method <- "Welch Two Sample t-test"
    p_val <- res$p.value
    stat <- res$statistic
    ci <- res$conf.int
    estimate <- res$estimate
    
    # Cohen's d の計算
    n1 <- length(grp1); n2 <- length(grp2)
    sd1 <- sd(grp1); sd2 <- sd(grp2)
    pooled_sd <- sqrt(((n1-1)*sd1^2 + (n2-1)*sd2^2) / (n1+n2-2))
    es <- abs(diff(estimate)) / pooled_sd
    es_name <- "Cohen's d"
  } else {
    res <- wilcox.test(sub_data[[outcome_var]] ~ sub_data$性別, conf.int = TRUE)
    method <- "Mann-Whitney U test (Wilcoxon rank-sum test)"
    p_val <- res$p.value
    stat <- res$statistic
    ci <- res$conf.int
    estimate <- c(median(grp1), median(grp2))
    names(estimate) <- paste("median of", groups)
    
    # 効果量 r = Z / sqrt(N)
    n1 <- length(grp1); n2 <- length(grp2)
    # 近似値計算
    mu_W <- (n1 * n2) / 2
    sd_W <- sqrt((n1 * n2 * (n1 + n2 + 1)) / 12)
    Z <- (stat - mu_W) / sd_W
    es <- abs(Z) / sqrt(n1 + n2)
    es_name <- "Rank-biserial correlation r"
  }
  
  cat(sprintf("\n=== Comparison for %s ===\n", outcome_var))
  cat(sprintf("Method: %s\n", method))
  cat(sprintf("Normality check p-values: %s = %.4f, %s = %.4f (Passed: %s)\n", 
              groups[1], sw1, groups[2], sw2, normality_passed))
  cat(sprintf("Group 1 (%s) N=%d, Mean/Median=%.2f\n", groups[1], length(grp1), estimate[1]))
  cat(sprintf("Group 2 (%s) N=%d, Mean/Median=%.2f\n", groups[2], length(grp2), estimate[2]))
  cat(sprintf("Test Statistic: %.4f, p-value: %.4g\n", stat, p_val))
  if (!is.null(ci)) {
    cat(sprintf("95%% Confidence Interval: [%.4f, %.4f]\n", ci[1], ci[2]))
  }
  cat(sprintf("Effect Size (%s): %.4f\n", es_name, es))
}

compare_groups("収縮期血圧_mmHg")
compare_groups("拡張期血圧_mmHg")
