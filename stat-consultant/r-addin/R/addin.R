#' Start the Stat Consultant poller (code insertion + environment sync)
#'
#' Begins non-blocking polling on RStudio's idle event loop (via \pkg{later}),
#' so the console stays free to run the inserted code. Each cycle does two
#' things:
#' \itemize{
#'   \item pulls queued code (\code{GET /api/rstudio/pending}) and inserts each
#'     block at the cursor of the active source document
#'     (\code{rstudioapi::insertText()});
#'   \item scans the global environment and, when it changed, pushes an
#'     aggregate-only, PII-filtered snapshot (column names/types/missing counts/
#'     category levels) to \code{POST /api/environment/sync}. No row/cell values
#'     are ever sent. This is transparent — no user action is required.
#' }
#'
#' Invoke once per RStudio session; stop with \code{statConsultantStopInsert()}
#' (the "停止" addin).
#'
#' @param interval_sec Poll interval in seconds (default 2).
#' @export
statConsultantInsertCode <- function(interval_sec = 2) {
  if (!rstudioapi::isAvailable()) {
    stop("Stat Consultant: RStudio内で実行してください。", call. = FALSE)
  }
  if (isTRUE(.state$running)) {
    message("Stat Consultant: 既にポーリング中です。")
    return(invisible(NULL))
  }
  .state$running <- TRUE
  message(
    "Stat Consultant: コード挿入と環境同期を開始しました",
    "（停止は「停止」アドイン）。"
  )
  later::later(function() poll_cycle(interval_sec), interval_sec)
  invisible(NULL)
}

#' Stop the Stat Consultant poller (code insertion + environment sync)
#'
#' Clears the running flag so the \pkg{later} poll chain ends on its next tick.
#'
#' @export
statConsultantStopInsert <- function() {
  .state$running <- FALSE
  message("Stat Consultant: コード挿入と環境同期を停止しました。")
  invisible(NULL)
}
