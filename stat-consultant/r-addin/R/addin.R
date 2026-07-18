#' Start the Stat Consultant code-insertion poller
#'
#' Begins non-blocking polling of the backend's pending-code queue
#' (\code{GET /api/rstudio/pending}). Each queued code block is inserted at the
#' cursor position of the active source document via
#' \code{rstudioapi::insertText()}. Polling runs on RStudio's idle event loop
#' (via \pkg{later}), so the console stays free to run the inserted code.
#'
#' Invoke once per RStudio session; stop with \code{statConsultantStopInsert()}
#' (the "コード挿入: 停止" addin).
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
    "Stat Consultant: コード挿入を開始しました",
    "（停止は「コード挿入: 停止」アドイン）。"
  )
  later::later(function() poll_cycle(interval_sec), interval_sec)
  invisible(NULL)
}

#' Stop the Stat Consultant code-insertion poller
#'
#' Clears the running flag so the \pkg{later} poll chain ends on its next tick.
#'
#' @export
statConsultantStopInsert <- function() {
  .state$running <- FALSE
  message("Stat Consultant: コード挿入を停止しました。")
  invisible(NULL)
}
