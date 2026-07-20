# Read-only GlobalEnv scan for the transparent environment sync (Step 7).
#
# Collects AGGREGATE-ONLY metadata per data.frame (SPEC §9.1): column names,
# types, missing counts, and — for categorical columns — the DISTINCT COUNT and
# the anonymised group sizes (top-10 counts). Category *label strings* are NEVER
# put in the payload: they are raw cell values (e.g. a patient ID kept as a
# factor level), and column-name heuristics alone cannot be trusted to catch
# them. Labels are computed locally only to decide whether to drop a column as
# PII; they never leave the machine. Individual row/cell values are likewise
# never collected. PII columns are excluded here before anything is sent
# (SPEC §9.2).

# Max distinct non-NA values for a *character* column to count as "categorical"
# (and thus be summarised). Above this it is treated as free text and no summary
# is collected. Factors are always summarised (counts only) regardless of
# cardinality — since only counts leave, a high-cardinality factor no longer
# leaks its level strings.
.CATEGORICAL_MAX_DISTINCT <- 10L

# Map an R column to a coarse type label for the payload.
map_type <- function(col) {
  if (is.factor(col)) {
    return("factor")
  }
  if (inherits(col, "Date")) {
    return("date")
  }
  if (is.integer(col)) {
    return("integer")
  }
  if (is.numeric(col)) {
    return("numeric")
  }
  if (is.logical(col)) {
    return("logical")
  }
  if (is.character(col)) {
    return("character")
  }
  class(col)[1]
}

# Categorical summary for a column, or NULL if it isn't categorical.
# Returns list(labels=, n_distinct=, counts=) where:
#   labels     — top-10 level strings, sorted by count. Used ONLY locally for
#                the PII decision; NEVER placed in the payload.
#   n_distinct — the true number of distinct non-NA values (not capped).
#   counts     — the top-10 group sizes (integers, sorted desc). Anonymous
#                aggregates (no labels attached), safe to send.
# Factors are always summarised; character columns only when low-cardinality
# (above .CATEGORICAL_MAX_DISTINCT they are free text — no summary).
category_summary <- function(col) {
  if (is.factor(col)) {
    col <- as.character(col)
  } else if (is.character(col)) {
    distinct <- unique(col[!is.na(col)])
    if (length(distinct) > .CATEGORICAL_MAX_DISTINCT) {
      return(NULL)  # high-cardinality free text: not categorical
    }
  } else {
    return(NULL)  # numeric / logical / date etc. have no category levels
  }

  tab <- table(col, useNA = "no")
  if (length(tab) == 0) {
    return(NULL)
  }
  n_distinct <- length(tab)
  tab <- sort(tab, decreasing = TRUE)
  if (length(tab) > 10L) {
    tab <- tab[seq_len(10L)]
  }
  list(
    labels = names(tab),                     # local PII check only, not sent
    n_distinct = as.integer(n_distinct),
    counts = unname(as.integer(tab))         # anonymised top-10 group sizes
  )
}

# Scan one data.frame into a list of column metadata, dropping PII columns.
scan_columns <- function(df) {
  cols <- list()
  for (cn in names(df)) {
    col <- df[[cn]]
    summary <- category_summary(col)
    level_labels <- if (is.null(summary)) character(0) else summary$labels
    if (column_has_pii(cn, level_labels)) {
      next  # SPEC §9.2: drop the whole column (type + n_missing + summary)
    }
    entry <- list(
      name = cn,
      type = map_type(col),
      n_missing = as.integer(sum(is.na(col)))
    )
    if (!is.null(summary)) {
      # Only aggregates leave: distinct count + anonymised group sizes. The
      # level label strings (summary$labels) are deliberately dropped here.
      entry$n_distinct <- summary$n_distinct
      entry$level_counts <- summary$counts
    }
    cols[[length(cols) + 1L]] <- entry
  }
  cols
}

# Build the full §9.1 payload from the GlobalEnv. Only data.frame-like objects
# are included (columns are meaningless for other objects).
build_env_payload <- function() {
  objects <- list()
  for (nm in ls(envir = .GlobalEnv)) {
    obj <- tryCatch(get(nm, envir = .GlobalEnv), error = function(e) NULL)
    if (is.null(obj) || !is.data.frame(obj)) {
      next
    }
    objects[[length(objects) + 1L]] <- list(
      name = nm,
      class = class(obj)[1],
      nrow = as.integer(nrow(obj)),
      columns = scan_columns(obj)
    )
  }
  list(objects = objects)
}

# Cheap deterministic signature of a payload for change detection — avoids
# re-POSTing an unchanged environment every poll cycle. Plain paste, so no extra
# package dependency. Any change (new object, new derived column, changed
# missing count / distinct count / group sizes) yields a different signature.
env_signature <- function(payload) {
  parts <- vapply(payload$objects, function(obj) {
    col_sigs <- vapply(obj$columns, function(col) {
      lvl <- ""
      if (!is.null(col$n_distinct)) {
        lvl <- paste0(col$n_distinct, ":", paste(col$level_counts, collapse = ","))
      }
      paste(col$name, col$type, col$n_missing, lvl, sep = "|")
    }, character(1))
    paste(obj$name, obj$class, obj$nrow, paste(col_sigs, collapse = ";"), sep = "#")
  }, character(1))
  paste(parts, collapse = "\n")
}
