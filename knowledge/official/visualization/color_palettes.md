# Color Palettes for Clinical Figures
# Domain: visualization
# Version: 1.0.0
# Status: Stable
# Consumers: visualization
# Immutable during execution (AP-014)

## Purpose

Defines the approved color palette system for all CIE platform figures.
Ensures colorblind accessibility, print compatibility, and visual consistency
across all generated figures. Implements visualization.yaml rule VZ-003.

---

## Default Palette — Okabe-Ito (Mandatory)

The Okabe-Ito palette is the platform default for all figures.
It is safe for the three most common forms of color vision deficiency
(deuteranopia, protanopia, tritanopia) and prints clearly in greyscale.

```r
okabe_ito <- c(
  "orange"     = "#E69F00",
  "sky_blue"   = "#56B4E9",
  "green"      = "#009E73",
  "yellow"     = "#F0E442",
  "blue"       = "#0072B2",
  "vermillion" = "#D55E00",
  "pink"       = "#CC79A7",
  "black"      = "#000000"
)
```

### Recommended Assignment by Group Count

| n groups | Colors to use (in order) |
|----------|-------------------------|
| 2 | orange (#E69F00), blue (#0072B2) |
| 3 | orange, blue, green (#009E73) |
| 4 | orange, blue, green, vermillion (#D55E00) |
| 5 | orange, blue, green, vermillion, sky_blue (#56B4E9) |
| 6 | All except yellow and black |
| 7–8 | Full palette |
| > 8 | Use sequential palette or faceting — avoid >8 categories in one figure |

---

## Sequential Palettes (for ordered/continuous data)

For heatmaps, gradient fills, or ordered categorical variables:

### Blue Sequential (preferred for continuous scales)
```r
scale_fill_gradient(low = "#DEEBF7", high = "#08306B")
```

### Diverging (for correlation matrices, before/after comparisons)
```r
scale_fill_gradient2(
  low  = "#2166AC",   # blue
  mid  = "#FFFFFF",   # white
  high = "#B2182B",   # red
  midpoint = 0
)
```

### Colorblind-safe continuous alternative (viridis)
```r
library(viridis)
scale_fill_viridis_c(option = "viridis")   # green-yellow
scale_fill_viridis_c(option = "plasma")    # purple-orange
```

---

## Greyscale Compatibility Rules

All figures must be interpretable in greyscale (for print journals).
Test greyscale rendering before finalizing any figure.

### Greyscale-compatible strategies

| Strategy | When to use |
|----------|-------------|
| Different shapes (pch) in addition to color | Scatter plots with groups |
| Different line types (dashed, dotted, solid) | Line plots, KM curves |
| Different fill patterns | Bar charts (use sparingly) |
| Text labels directly on elements | When ≤ 4 categories |

```r
# Shape mapping for greyscale compatibility
scale_shape_manual(values = c(16, 17, 15, 18))  # circle, triangle, square, diamond

# Line type mapping for KM curves
scale_linetype_manual(values = c("solid", "dashed", "dotted", "longdash"))
```

---

## Context-Specific Color Rules

### Survival Curves
- Two groups: orange (#E69F00) and blue (#0072B2)
- Confidence intervals: same hue at 20% opacity (`alpha=0.2`)
- Censoring tick marks: same color as the group line

### Forest Plots
- Effect estimate point: blue (#0072B2)
- Confidence interval line: blue (#0072B2)
- Null line (OR=1 or HR=1): grey (#999999), dashed
- Subgroups with significant results: vermillion (#D55E00)

### Box Plots
- Box fill: group color at 70% opacity (`alpha=0.7`)
- Jitter points: grey30 (`#4D4D4D`) at 50% opacity
- Median line: always black

### Heatmaps (correlation matrix)
- Use diverging palette (blue–white–red)
- Midpoint at 0 for correlation matrices

---

## Journal Override Rules

When `journal_figure_guidelines` specify different color requirements:

1. Apply journal-specified palette to `scale_colour_manual()` and `scale_fill_manual()`.
2. Override Okabe-Ito defaults only if journal requires it.
3. Verify colorblind accessibility of journal palette; if not accessible, document in advisory_findings.
4. Document override in figure_specification with reference to journal guideline.

```yaml
color_palette_override:
  source: "journal_figure_guidelines"
  journal: "[Journal name]"
  palette_applied: "[palette name]"
  colorblind_safe: false
  advisory_note: "Journal-specified palette is not fully colorblind-safe. Documented per VZ-003."
```

---

## Accessibility Verification Checklist

Before finalizing any figure, confirm:

| Check | Tool / Method |
|-------|--------------|
| Colorblind simulation (deuteranopia) | `colorBlindness::cvdPlot()` or manual inspection |
| Colorblind simulation (protanopia) | Same tool |
| Greyscale readability | Export as greyscale PDF and review |
| Sufficient contrast ratio | Foreground vs background ≥ 4.5:1 (WCAG AA) |
| Text size ≥ 8pt in final output | Verify after ggsave at target dimensions |
