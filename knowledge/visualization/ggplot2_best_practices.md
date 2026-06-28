# ggplot2 Best Practices for Clinical Figures
# Domain: R
# Version: 1.1.0
# Status: Stable
# Consumers: visualization
# Immutable during execution (AP-014)
# Last updated: ggplot2 4.0.3 compatibility review

## Purpose

Provides the Visualization Agent with ggplot2 implementation patterns
for each chart type in the chart_selection_framework. All patterns
comply with publication standards and runtime security constraints.

---

## Global Theme Standard

All figures must use this base theme:

```r
library(ggplot2)

cie_theme <- theme_classic() +
  theme(
    text          = element_text(family = "Helvetica Neue", size = 10),
    axis.title    = element_text(size = 10, face = "bold"),
    axis.text     = element_text(size = 9),
    legend.title  = element_text(size = 9, face = "bold"),
    legend.text   = element_text(size = 9),
    plot.title    = element_text(size = 11, face = "bold"),
    panel.grid.major = element_line(color = "grey90", linewidth = 0.3),
    panel.grid.minor = element_blank(),
    strip.text    = element_text(size = 9, face = "bold")
  )
```

---

## Okabe-Ito Colorblind-Safe Palette (Default)

```r
okabe_ito <- c(
  "#E69F00",  # orange
  "#56B4E9",  # sky blue
  "#009E73",  # green
  "#F0E442",  # yellow
  "#0072B2",  # blue
  "#D55E00",  # vermillion
  "#CC79A7",  # pink
  "#000000"   # black
)

# Usage:
scale_colour_manual(values = okabe_ito)
scale_fill_manual(values = okabe_ito)
```

---

## Chart Implementation Patterns

### Box Plot with Jitter (default for group comparison, continuous outcome)

```r
ggplot(data, aes(x = group_var, y = outcome_var, fill = group_var)) +
  geom_boxplot(outlier.shape = NA, alpha = 0.7, width = 0.5) +
  geom_jitter(width = 0.15, size = 1.5, alpha = 0.5, color = "grey30") +
  scale_fill_manual(values = okabe_ito) +
  labs(
    x = "[Group variable label]",
    y = "[Outcome variable label (unit)]",
    caption = "[Statistical annotation: p-value, test used, n per group]"
  ) +
  cie_theme +
  theme(legend.position = "none")
```

---

### Violin Plot (for n > 100 per group)

```r
ggplot(data, aes(x = group_var, y = outcome_var, fill = group_var)) +
  geom_violin(alpha = 0.7, trim = FALSE) +
  geom_boxplot(width = 0.1, fill = "white", outlier.shape = NA) +
  scale_fill_manual(values = okabe_ito) +
  labs(x = "[label]", y = "[label (unit)]") +
  cie_theme +
  theme(legend.position = "none")
```

---

### Kaplan-Meier Survival Curve

```r
library(survival)
library(survminer)

fit <- survfit(Surv(time_var, event_var) ~ group_var, data = data)

ggsurvplot(
  fit,
  data          = data,
  pval          = TRUE,
  conf.int      = TRUE,
  risk.table    = TRUE,
  palette       = okabe_ito[1:2],
  xlab          = "Time (days)",
  ylab          = "Survival probability",
  legend.labs   = c("[Group A label]", "[Group B label]"),
  ggtheme       = cie_theme,
  fontsize      = 3.5,
  tables.height = 0.25
)
```

---

### Scatter Plot with Regression Line (correlation)

```r
ggplot(data, aes(x = predictor_var, y = outcome_var)) +
  geom_point(alpha = 0.6, size = 2, color = okabe_ito[2]) +
  geom_smooth(method = "lm", se = TRUE, color = okabe_ito[1],
              fill = okabe_ito[1], alpha = 0.15, linewidth = 0.8) +  # linewidth replaces size for lines (≥3.4.0)
  labs(
    x = "[Predictor label (unit)]",
    y = "[Outcome label (unit)]",
    caption = paste0("r = [value], 95% CI [L, U], p = [value], n = [n]")
  ) +
  cie_theme
```

---

### Forest Plot (effect size summary)

```r
# Note: forestplot package not required — implemented in pure ggplot2
# results_df: data frame with columns: label, estimate, lower, upper

ggplot(results_df, aes(y = reorder(label, estimate),
                        x = estimate, xmin = lower, xmax = upper)) +
  geom_vline(xintercept = 1, linetype = "dashed", linewidth = 0.5, color = "grey50") +
  geom_linerange(color = okabe_ito[2], linewidth = 0.7) +  # replaces geom_errorbarh in 4.x
  geom_point(size = 3, color = okabe_ito[1]) +
  labs(x = "[Effect measure (e.g. OR, HR)]", y = NULL) +
  cie_theme
```

> **Note (ggplot2 ≥ 3.4.0):** `geom_errorbarh()` still exists but `geom_linerange()`
> with horizontal orientation via swapped aesthetics is preferred.
> The `size` aesthetic for lines is deprecated — use `linewidth` instead.

---

### QQ Plot (normality visual check)

```r
ggplot(data, aes(sample = target_var)) +
  stat_qq(color = okabe_ito[2], size = 1.5, alpha = 0.7) +
  stat_qq_line(color = okabe_ito[1], linewidth = 0.8) +
  labs(x = "Theoretical quantiles", y = "Sample quantiles") +
  cie_theme
```

---

## Figure Output Saving Standard

```r
# Save to OUTPUT_DIR only — never to absolute paths
output_path <- file.path(Sys.getenv("OUTPUT_DIR"), "figure_01.pdf")

ggsave(
  filename = output_path,
  plot     = p,
  width    = 180,   # mm — per visualization.yaml output_standards
  height   = 120,   # mm
  units    = "mm",
  dpi      = 300,
  device   = "pdf"
)
```

For PNG export (supplementary):
```r
ggsave(filename = output_path_png, plot = p,
       width = 180, height = 120, units = "mm", dpi = 300, device = "png")
```

---

## Caption Generation Template

```r
# Every figure caption must include these elements:
caption_template <- paste0(
  "Figure [N]. [Brief descriptive title]. ",
  "[Statistical annotation: test, effect size, CI, p-value, n]. ",
  "Error bars represent [SD / SE / 95% CI]. ",
  "[Color/shape coding explanation if applicable]."
)
```

---

## Common Errors to Avoid

| Error | Rule | Correct approach |
|-------|------|-----------------|
| Hard-coded file paths in ggsave | Security violation | Use `Sys.getenv("OUTPUT_DIR")` |
| `theme_bw()` as base | Non-standard | Use `cie_theme` |
| Default R color palette | Not colorblind-safe | Use `okabe_ito` |
| `size` for line width (geom_smooth, geom_line etc.) | Deprecated since 3.4.0 | Use `linewidth` instead |
| `library(viridis)` for viridis scales | Unnecessary since 3.4.0 | Use `scale_fill_viridis_c()` directly from ggplot2 |
| `geom_errorbarh()` for forest plots | Superseded pattern | Use `geom_linerange()` with x/xmin/xmax aesthetics |
| Missing axis units | Fails USB-002-B | Always include units in axis labels |
| Missing caption | Fails USB-002-A | Always include caption with statistical annotation |
| `png()` / `pdf()` device functions | Bypasses OUTPUT_DIR check | Use `ggsave()` only |
