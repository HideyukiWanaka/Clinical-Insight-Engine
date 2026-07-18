# Poll loop internals for the code-insertion addin (Step 6).
#
# poll_cycle() re-schedules itself via `later` until the `running` flag clears
# (non-blocking; the console stays usable). poll_once() does one round-trip.

poll_cycle <- function(interval_sec) {
  if (!isTRUE(.state$running)) {
    return(invisible(NULL))  # stop addin cleared the flag: end the chain
  }
  poll_once()
  later::later(function() poll_cycle(interval_sec), interval_sec)
  invisible(NULL)
}

poll_once <- function() {
  tryCatch(
    {
      ctx <- rstudioapi::getSourceEditorContext()
      # No open source document: do NOT call /pending. The queue drains on
      # read, so fetching now would consume code we then couldn't insert,
      # losing it. Leave it queued for a later cycle.
      if (is.null(ctx)) {
        return(invisible(NULL))
      }

      token <- read_shared_secret()
      items <- fetch_pending(token)
      if (length(items) == 0) {
        return(invisible(NULL))
      }

      # Multiple queued blocks insert in order, blank-line separated, as one
      # insertText call (a single editor undo step).
      code_text <- paste(
        vapply(items, function(it) it[["code"]], character(1)),
        collapse = "\n\n"
      )
      rstudioapi::insertText(text = code_text, id = ctx$id)  # location omitted = cursor
    },
    error = function(e) {
      # Network hiccup, backend down, doc closed mid-cycle: log and keep going.
      message("Stat Consultant: ポーリング中にエラー: ", conditionMessage(e))
    }
  )
  invisible(NULL)
}
