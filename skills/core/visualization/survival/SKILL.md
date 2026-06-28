# SKILL: Survival Visualization (Kaplan-Meier)
# Skill ID: visualization/survival
# Version: 1.0.0
# Consumers: visualization agent
# Knowledge references:
#   - knowledge/visualization/chart_selection_guide.md (Survival Charts)
#   - knowledge/visualization/color_palettes.md
#   - knowledge/R/ggplot2_best_practices.md (Kaplan-Meier section)

## Overview

Generates publication-ready Kaplan-Meier survival curves with risk table,
log-rank p-value annotation, and median survival reference lines.

Applies when:
- `statistical_results.method_used` includes `"kaplan_meier"`
- `intent_object.outcome_type = "survival"`

---

## Procedure

### Step 1 — Reconstruct survfit from results

```r
library(survival)
library(survminer)

time_var  <- statistical_results$time_var
event_var <- statistical_results$event_var
group_var <- names(statistical_results$kaplan_meier$median_survival)[1] |>
             (\(x) statistical_results$group_var)()

km_fit <- survival::survfit(
  as.formula(paste("Surv(", time_var, ",", event_var, ") ~", group_var)),
  data = data
)
```

### Step 2 — Build KM plot

```r
okabe_ito <- c("#E69F00", "#56B4E9", "#009E73", "#F0E442",
               "#0072B2", "#D55E00", "#CC79A7", "#000000")

n_curves <- length(levels(factor(data[[group_var]])))

cie_km_theme <- theme_classic() +
  theme(
    text            = element_text(family = "Helvetica Neue", size = 10),
    axis.title      = element_text(size = 10, face = "bold"),
    axis.text       = element_text(size = 9),
    legend.title    = element_text(size = 9, face = "bold"),
    legend.text     = element_text(size = 9),
    legend.position = "bottom"
  )

p_lr   <- statistical_results$kaplan_meier$logrank_p
n_str  <- paste(names(statistical_results$n_per_group),
                unlist(statistical_results$n_per_group),
                sep = "=", collapse = ", ")

km_plot <- ggsurvplot(
  fit           = km_fit,
  data          = data,
  pval          = FALSE,         # We add annotation manually for control
  conf.int      = TRUE,
  risk.table    = TRUE,
  palette       = okabe_ito[seq_len(n_curves)],
  xlab          = paste("Time (", time_var, ")"),
  ylab          = "Survival probability",
  legend.title  = group_var,
  ggtheme       = cie_km_theme,
  fontsize      = 3.5,
  tables.height = 0.25,
  surv.median.line = "hv"        # horizontal + vertical lines at median
)

# Add log-rank p annotation
km_plot$plot <- km_plot$plot +
  annotate("text",
           x     = max(data[[time_var]], na.rm = TRUE) * 0.05,
           y     = 0.05,
           label = paste0("Log-rank p=", format(p_lr, digits=3)),
           hjust = 0, size = 3.5)
```

### Step 3 — Build caption

```r
median_surv <- statistical_results$kaplan_meier$median_survival
med_str <- paste(
  mapply(function(grp, med) paste0(grp, ": ", round(med, 1)),
         names(median_surv), median_surv),
  collapse = "; "
)

caption_text <- paste0(
  "Kaplan-Meier survival curves. Log-rank p=", format(p_lr, digits=3),
  ". Median survival — ", med_str,
  ". n: ", n_str, "."
)
```

### Step 4 — Save output

```r
output_path <- file.path(Sys.getenv("OUTPUT_DIR"), "figure_km_curve.pdf")

pdf(output_path, width = 180/25.4, height = 160/25.4)  # mm → inches
print(km_plot)
dev.off()

figure_manifest_entry <- list(
  figure_id     = "fig_km_curve",
  chart_type    = "kaplan_meier",
  file_path     = output_path,
  caption_draft = caption_text,
  statistical_annotation = list(
    logrank_p       = p_lr,
    median_survival = median_surv
  )
)
```

---

## Validation Rules
- `risk.table = TRUE` is mandatory (CONSORT/STROBE requirement)
- `surv.median.line = "hv"` is mandatory for median survival visualization
- Caption must include: log-rank p-value, median survival per group, n per group
- Output via `pdf()` + `print()` + `dev.off()` pattern (not ggsave, due to survminer object structure)
- Output path must use `Sys.getenv("OUTPUT_DIR")`
- `conf.int = TRUE` is mandatory

---

## Examples

```json
{
  "figure_id": "fig_km_curve",
  "chart_type": "kaplan_meier",
  "caption_draft": "Kaplan-Meier survival curves. Log-rank p=0.023. Median survival — A: 24.5; B: 18.2. n: A=45, B=42."
}
```

---

## Tests

### TEST-KM01: caption contains log-rank p
```r
stopifnot(grepl("Log-rank", result$caption_draft))
stopifnot(grepl("p=", result$caption_draft))
```

### TEST-KM02: output file in OUTPUT_DIR
```r
stopifnot(startsWith(result$figure_manifest_entry$file_path,
                     Sys.getenv("OUTPUT_DIR")))
```

### TEST-KM03: median survival present for all groups
```r
n_groups <- length(levels(factor(data[[group_var]])))
stopifnot(length(result$figure_manifest_entry$statistical_annotation$median_survival) == n_groups)
```
