# Read-only GlobalEnv scan for the transparent environment sync (Step 7).
#
# Collects AGGREGATE-ONLY metadata per data.frame (SPEC §9.1): column names,
# types, missing counts, and factor/categorical level labels+counts. Individual
# row/cell values are NEVER collected (inject_raw_data_rows = FALSE, CLAUDE.md).
# PII columns are excluded here, before anything leaves the machine (SPEC §9.2).

# Max distinct non-NA values for a character column to count as "categorical"
# (and thus have its level labels enumerated). Above this it is treated as free
# text and no labels are collected — so high-cardinality text (names, notes)
# never leaves the machine even by value.
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

# Aggregated category levels for a column, or NULL if it isn't categorical.
# Returns an unnamed list of list(label=, count=), top 10 by count — matching
# dataset.schema.json's "at most 10 per column". Labels/counts are aggregates,
# never raw rows.
category_levels <- function(col) {
  if (is.factor(col)) {
    col <- as.character(col)
  } else if (is.character(col)) {
    distinct <- unique(col[!is.na(col)])
    if (length(distinct) > .CATEGORICAL_MAX_DISTINCT) {
      return(NULL)  # high-cardinality free text: do not enumerate values
    }
  } else {
    return(NULL)  # numeric / logical / date etc. have no category levels
  }

  tab <- table(col, useNA = "no")
  if (length(tab) == 0) {
    return(NULL)
  }
  tab <- sort(tab, decreasing = TRUE)
  if (length(tab) > 10L) {
    tab <- tab[seq_len(10L)]
  }
  labels <- names(tab)
  lapply(seq_along(tab), function(i) {
    list(label = labels[i], count = unname(as.integer(tab[i])))
  })
}

# Scan one data.frame into a list of column metadata, dropping PII columns.
scan_columns <- function(df) {
  cols <- list()
  for (cn in names(df)) {
    col <- df[[cn]]
    levels <- category_levels(col)
    level_labels <- if (is.null(levels)) {
      character(0)
    } else {
      vapply(levels, function(l) l$label, character(1))
    }
    if (column_has_pii(cn, level_labels)) {
      next  # SPEC §9.2: drop the whole column (type + n_missing + levels)
    }
    entry <- list(
      name = cn,
      type = map_type(col),
      n_missing = as.integer(sum(is.na(col)))
    )
    if (!is.null(levels)) {
      entry$levels <- levels
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
# missing count / level counts) yields a different signature.
env_signature <- function(payload) {
  parts <- vapply(payload$objects, function(obj) {
    col_sigs <- vapply(obj$columns, function(col) {
      lvl <- ""
      if (!is.null(col$levels)) {
        lvl <- paste(
          vapply(col$levels, function(l) paste0(l$label, "=", l$count), character(1)),
          collapse = ","
        )
      }
      paste(col$name, col$type, col$n_missing, lvl, sep = "|")
    }, character(1))
    paste(obj$name, obj$class, obj$nrow, paste(col_sigs, collapse = ";"), sep = "#")
  }, character(1))
  paste(parts, collapse = "\n")
}
