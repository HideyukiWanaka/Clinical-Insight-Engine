# SKILL: Group Comparison Visualization
# Skill ID: visualization/group-comparison
# Version: 2.0.0
# Consumers: visualization agent
# Knowledge references:
#   - knowledge/official/visualization/chart_selection_guide.md (Group Comparison Charts)
#   - knowledge/official/visualization/color_palettes.md (Okabe-Ito)
#   - knowledge/official/R/ggplot2_best_practices.md

## Overview

Reusable procedure for generating publication-ready figures for group comparisons
of continuous outcomes. Selects chart type based on design (paired/independent),
n per group, and number of groups.

Applies when:
- `statistical_results.method_used ∈ {"welch_t_test", "mann_whitney_u",
   "paired_t_test", "wilcoxon_signed_rank",
   "one_way_anova", "welch_anova", "kruskal_wallis",
   "repeated_measures_anova", "friedman"}`
- `intent_object.outcome_type = "continuous"`

---

## Design Branch

```
statistical_results.design
    │
    ├─ "independent"
    │     n_min_per_group > 500 → raincloud (fallback: violin)
    │     n_min_per_group > 100 → violin
    │     default               → boxplot_jitter
    │
    └─ "paired"
          n_groups = 2          → slopegraph (paired_boxplot for large n)
          n_groups ≥ 3          → repeated_boxplot (connected lines per subject)
```

---

## Procedure

### Step 1 — Determine design and select chart type

```r
design      <- statistical_results$design     # "independent" or "paired"
n_min       <- min(unlist(statistical_results$n_per_group))
n_groups    <- statistical_results$n_groups
outcome_var <- statistical_results$outcome_var
group_var   <- statistical_results$group_var
subject_id_var <- statistical_results$subject_id_var  # NULL for independent

if (design == "independent") {
  chart_type <- dplyr::case_when(
    n_min > 500 ~ "violin",
    n_min > 100 ~ "violin",
    TRUE        ~ "boxplot_jitter"
  )
} else {
  # Paired design
  # 2 groups  → slopegraph: individual lines + mean line connecting 2 points
  # ≥3 groups → line_chart_repeated: mean ± SE line graph + individual trajectories
  chart_type <- if (n_groups == 2) "slopegraph" else "line_chart_repeated"
}
```

### Step 2 — Build base plot

```r
library(ggplot2)
okabe_ito <- c("#E69F00","#56B4E9","#009E73","#F0E442",
               "#0072B2","#D55E00","#CC79A7","#000000")

cie_theme <- theme_classic() +
  theme(
    text             = element_text(family = "Helvetica Neue", size = 10),
    axis.title       = element_text(size = 10, face = "bold"),
    axis.text        = element_text(size = 9),
    legend.position  = "none",
    panel.grid.major = element_line(color = "grey90", linewidth = 0.3)
  )

if (chart_type == "boxplot_jitter") {
  # --- Independent, small/medium n ---
  p <- ggplot(data, aes(x = .data[[group_var]],
                         y = .data[[outcome_var]],
                         fill = .data[[group_var]])) +
    geom_boxplot(outlier.shape = NA, alpha = 0.7, width = 0.5) +
    geom_jitter(width = 0.15, size = 1.5, alpha = 0.5, color = "grey30") +
    scale_fill_manual(values = okabe_ito[seq_len(n_groups)]) +
    cie_theme

} else if (chart_type == "violin") {
  # --- Independent, large n ---
  p <- ggplot(data, aes(x = .data[[group_var]],
                         y = .data[[outcome_var]],
                         fill = .data[[group_var]])) +
    geom_violin(alpha = 0.7, trim = FALSE) +
    geom_boxplot(width = 0.1, fill = "white", outlier.shape = NA) +
    scale_fill_manual(values = okabe_ito[seq_len(n_groups)]) +
    cie_theme

} else if (chart_type == "slopegraph") {
  # --- Paired, 2 groups: individual lines + mean line connecting 2 time points ---
  # Layer order: individual lines (background) → mean line (foreground)
  stopifnot(!is.null(subject_id_var))

  p <- ggplot(data, aes(x = .data[[group_var]],
                         y = .data[[outcome_var]])) +
    # Layer 1: individual subject trajectories (grey, subtle)
    geom_line(aes(group = .data[[subject_id_var]]),
              alpha = 0.35, color = "grey60", linewidth = 0.4) +
    # Layer 2: individual data points colored by group
    geom_point(aes(color = .data[[group_var]]),
               alpha = 0.6, size = 2) +
    # Layer 3: mean ± SE error bars at each time point
    stat_summary(aes(group = 1),
                 fun.data = mean_se, geom = "errorbar",
                 color = okabe_ito[1], linewidth = 0.9, width = 0.08) +
    # Layer 4: mean LINE connecting the two time points (the key element)
    stat_summary(aes(group = 1),
                 fun = mean, geom = "line",
                 color = okabe_ito[1], linewidth = 1.4) +
    # Layer 5: mean points (diamond shape)
    stat_summary(aes(group = 1),
                 fun = mean, geom = "point",
                 color = okabe_ito[1], size = 4, shape = 18) +
    scale_color_manual(values = okabe_ito[seq_len(n_groups)]) +
    cie_theme

} else if (chart_type == "line_chart_repeated") {
  # --- Paired, ≥3 time points ---
  # PRIMARY: mean ± SE LINE GRAPH across time points
  # SECONDARY: individual subject trajectories (faint, behind)
  # This is the standard format for repeated-measures data in clinical research
  stopifnot(!is.null(subject_id_var))

  p <- ggplot(data, aes(x = .data[[group_var]],
                         y = .data[[outcome_var]])) +
    # Layer 1 (background): individual subject trajectories — faint grey lines
    geom_line(aes(group = .data[[subject_id_var]]),
              alpha = 0.20, color = "grey60", linewidth = 0.35) +
    # Layer 2: SE ribbon around the mean line
    stat_summary(aes(group = 1),
                 fun.data = mean_se, geom = "ribbon",
                 fill = okabe_ito[1], alpha = 0.15) +
    # Layer 3 (PRIMARY): mean line connecting all time points
    stat_summary(aes(group = 1),
                 fun = mean, geom = "line",
                 color = okabe_ito[1], linewidth = 1.4) +
    # Layer 4: mean points at each time point
    stat_summary(aes(group = 1),
                 fun = mean, geom = "point",
                 color = okabe_ito[1], size = 3.5, shape = 16) +
    # Layer 5: SE error bars at each time point
    stat_summary(aes(group = 1),
                 fun.data = mean_se, geom = "errorbar",
                 color = okabe_ito[1], linewidth = 0.9, width = 0.15) +
    scale_x_discrete() +   # Ensure time points treated as discrete categories
    cie_theme +
    theme(legend.position = "none")
}
```

### Step 3 — Statistical annotation

```r
p_val    <- statistical_results$primary_result$p_value
method   <- statistical_results$method_used
es_val   <- round(statistical_results$effect_size$value, 2)
es_msr   <- statistical_results$effect_size$measure
es_interp <- statistical_results$effect_size$interpretation
n_str    <- paste(names(statistical_results$n_per_group),
                  unlist(statistical_results$n_per_group),
                  sep = "=", collapse = ", ")

# Design-specific annotation prefix
design_label <- if (design == "paired") "Paired analysis" else ""

caption_text <- paste0(
  if (nchar(design_label) > 0) paste0(design_label, ". "),
  method, ": p=", format(p_val, digits=3),
  "; ", es_msr, "=", es_val,
  " (", es_interp, ")",
  "; n: ", n_str
)

p <- p +
  labs(
    x       = group_var,
    y       = outcome_var,
    caption = caption_text
  )
```

### Step 4 — Save output

```r
fig_name    <- paste0("figure_", chart_type, "_", design, ".pdf")
output_path <- file.path(Sys.getenv("OUTPUT_DIR"), fig_name)

ggsave(
  filename = output_path,
  plot     = p,
  width    = 180, height = 130, units = "mm",
  dpi      = 300, device  = "pdf"
)

figure_manifest_entry <- list(
  figure_id   = paste0("fig_", chart_type),
  chart_type  = chart_type,
  design      = design,
  file_path   = output_path,
  caption_draft = caption_text,
  statistical_annotation = list(
    method      = method,
    p_value     = p_val,
    effect_size = es_val,
    measure     = es_msr
  )
)
```

---

## Validation Rules
- `design` must be read from `statistical_results$design`, never assumed
- `chart_type = "slopegraph"` → n_groups must be 2; requires `subject_id_var`
- `chart_type = "line_chart_repeated"` → n_groups must be ≥ 3; requires `subject_id_var`
- `slopegraph`: mean line (`stat_summary geom="line"`) is mandatory — not optional
- `line_chart_repeated`: mean line is the PRIMARY layer; individual lines are SECONDARY (α ≤ 0.25)
- Caption must contain "Paired analysis" label for all paired designs
- Caption must include method, p-value, effect size, n
- Output must be written to `OUTPUT_DIR` only
- `scale_color_manual` / `scale_fill_manual` must use `okabe_ito`

---

## Chart Type Decision Summary

| design | n_groups | n_min | chart_type | Primary visual element |
|--------|---------|-------|-----------|----------------------|
| independent | 2 or ≥3 | ≤100 | boxplot_jitter | Box plot + jittered points |
| independent | 2 or ≥3 | >100 | violin | Violin + inner box |
| paired | 2 | any | **slopegraph** | Individual lines + **mean line** (bold) |
| paired | ≥3 | any | **line_chart_repeated** | **Mean ± SE line graph** + individual trajectories (faint) |

**Design principle:** For repeated-measures data, the mean trajectory (line graph)
is always the primary element. Individual subject lines are secondary context.

---

## Examples

```json
{
  "independent/boxplot":  {"chart_type": "boxplot_jitter",     "design": "independent"},
  "paired/slopegraph":    {"chart_type": "slopegraph",         "design": "paired", "n_groups": 2},
  "paired/line_repeated": {"chart_type": "line_chart_repeated", "design": "paired", "n_groups": 4}
}
```

---

## Tests

### TEST-V01: Slopegraph selected for paired 2-group
```r
stopifnot(result$chart_type == "slopegraph")
```

### TEST-V02: line_chart_repeated for paired ≥3 groups
```r
stopifnot(result$chart_type == "line_chart_repeated")
```

### TEST-V03: Paired charts error when subject_id_var=NULL
```r
err <- tryCatch(run_skill(design="paired", subject_id_var=NULL, ...),
                error=function(e) conditionMessage(e))
stopifnot(grepl("subject_id_var", err))
```
```

### TEST-V04: caption contains "Paired analysis" for paired design
```r
if (result$design == "paired") {
  stopifnot(grepl("Paired analysis", result$caption_draft))
}
```

### TEST-V05: output file in OUTPUT_DIR
```r
stopifnot(startsWith(result$figure_manifest_entry$file_path,
                     Sys.getenv("OUTPUT_DIR")))
```

### TEST-V06: Independent design → no subject lines
```r
# chart_type must be boxplot_jitter or violin for independent design
stopifnot(result$chart_type %in% c("boxplot_jitter", "violin"))
```
