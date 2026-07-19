# HTTP client for the backend pending-code queue (Step 6).
#
# httr2 (not httr, which is in maintenance mode). resp_body_json() parses JSON
# via httr2's own jsonlite dependency, so we don't declare jsonlite separately.

# Base URL is overridable via option in case the backend isn't on the default
# port; not required by SPEC, cheap escape hatch.
.base_url <- function() {
  getOption("statConsultant.baseUrl", "http://127.0.0.1:8000")
}

.pending_url <- function() {
  paste0(.base_url(), "/api/rstudio/pending")
}

.env_sync_url <- function() {
  paste0(.base_url(), "/api/environment/sync")
}

# GET /api/rstudio/pending with the shared-secret header. Returns the `items`
# list (possibly empty). Raises on auth/HTTP failure; the caller's poll loop
# catches and logs so a single failure never stops polling.
fetch_pending <- function(token) {
  resp <- httr2::request(.pending_url())
  resp <- httr2::req_headers(resp, `X-Stat-Consultant-Token` = token)
  # Don't let httr2 throw on non-2xx; we branch on the status ourselves.
  resp <- httr2::req_error(resp, is_error = function(resp) FALSE)
  resp <- httr2::req_perform(resp)

  status <- httr2::resp_status(resp)
  if (status == 401L) {
    stop(
      "Stat Consultant: 認証に失敗しました。バックエンドが再起動された場合、",
      "次のポーリングで自動的に復帰します。",
      call. = FALSE
    )
  }
  if (status >= 400L) {
    stop(
      sprintf("Stat Consultant: pending取得に失敗しました (HTTP %d)", status),
      call. = FALSE
    )
  }
  httr2::resp_body_json(resp)$items
}

# POST the environment snapshot (SPEC §9.1) to /api/environment/sync with the
# shared-secret header. req_body_json() serialises via httr2's own jsonlite
# (auto_unbox = TRUE): scalars stay scalars, `objects`/`columns`/`levels` become
# JSON arrays. Raises on auth/HTTP failure; the caller's scan loop catches, logs,
# and keeps polling so one failure never stops the loop.
post_environment <- function(token, payload) {
  resp <- httr2::request(.env_sync_url())
  resp <- httr2::req_headers(resp, `X-Stat-Consultant-Token` = token)
  resp <- httr2::req_body_json(resp, payload, auto_unbox = TRUE)
  resp <- httr2::req_error(resp, is_error = function(resp) FALSE)
  resp <- httr2::req_perform(resp)

  status <- httr2::resp_status(resp)
  if (status == 401L) {
    stop(
      "Stat Consultant: 環境同期の認証に失敗しました。バックエンド再起動時は",
      "次回サイクルで自動復帰します。",
      call. = FALSE
    )
  }
  if (status >= 400L) {
    stop(
      sprintf("Stat Consultant: 環境同期に失敗しました (HTTP %d)", status),
      call. = FALSE
    )
  }
  invisible(NULL)
}
