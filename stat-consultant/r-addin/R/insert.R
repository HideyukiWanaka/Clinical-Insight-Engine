# Poll loop internals (Step 6 code insertion + Step 7 environment sync).
#
# poll_cycle() re-schedules itself via `later` until the `running` flag clears
# (non-blocking; the console stays usable). Each cycle does two independent
# round-trips: poll_once() pulls queued code to insert, env_scan_once() pushes
# an environment snapshot. They are separate because env sync must run even when
# no source document is open (code insertion can't).

poll_cycle <- function(interval_sec) {
  if (!isTRUE(.state$running)) {
    return(invisible(NULL))  # stop addin cleared the flag: end the chain
  }
  poll_once()
  env_scan_once()
  later::later(function() poll_cycle(interval_sec), interval_sec)
  invisible(NULL)
}

# One environment-sync round-trip (Step 7). Scans the GlobalEnv, and POSTs the
# PII-filtered §9.1 snapshot only when it changed since the last successful sync.
# Runs regardless of whether a source document is open (unlike poll_once). Any
# error (scan, network, backend down) is logged and swallowed so the loop lives.
env_scan_once <- function() {
  tryCatch(
    {
      payload <- build_env_payload()
      sig <- env_signature(payload)
      # Unchanged environment: skip the POST (avoids per-cycle spam).
      if (!is.null(.state$last_env_sig) && identical(sig, .state$last_env_sig)) {
        return(invisible(NULL))
      }
      token <- read_shared_secret()
      post_environment(token, payload)
      # Record the signature ONLY after a successful POST, so a failed sync
      # retries on the next cycle rather than being silently marked as sent.
      .state$last_env_sig <- sig
    },
    error = function(e) {
      message("Stat Consultant: 環境同期中にエラー: ", conditionMessage(e))
    }
  )
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
