# HTTP client for the backend pending-code queue (Step 6).
#
# httr2 (not httr, which is in maintenance mode). resp_body_json() parses JSON
# via httr2's own jsonlite dependency, so we don't declare jsonlite separately.

# Base URL is overridable via option in case the backend isn't on the default
# port; not required by SPEC, cheap escape hatch.
.base_url <- function() {
  getOption("statConsultant.baseUrl", "http://127.0.0.1:8000")
}

# Port the backend should listen on, derived from the same option that says
# where to reach it — so overriding baseUrl moves both the client and the
# process we spawn, and they can't drift apart.
.base_port <- function() {
  m <- regmatches(.base_url(), regexpr(":([0-9]+)$", .base_url()))
  if (length(m) == 0) "8000" else sub("^:", "", m)
}

.pending_url <- function() {
  paste0(.base_url(), "/api/rstudio/pending")
}

.env_sync_url <- function() {
  paste0(.base_url(), "/api/environment/sync")
}

.health_url <- function() {
  paste0(.base_url(), "/health")
}

# GET /health. Unauthenticated (it's what we call *to* locate the token), short
# timeout so a dead backend fails fast inside a 2s poll cycle. Returns the
# parsed body, or NULL on any failure — callers treat NULL as "can't ask the
# backend right now" and fall back to their own path guess.
fetch_health <- function() {
  tryCatch(
    {
      resp <- httr2::request(.health_url())
      resp <- httr2::req_timeout(resp, 2)
      resp <- httr2::req_error(resp, is_error = function(resp) FALSE)
      resp <- httr2::req_perform(resp)
      if (httr2::resp_status(resp) != 200L) return(NULL)
      httr2::resp_body_json(resp)
    },
    error = function(e) NULL
  )
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
    # A restarted backend may have resolved a different state dir than the one
    # we cached, so drop it: the next cycle re-asks /health and re-reads the
    # token from wherever this process actually wrote it.
    forget_state_dir()
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
    forget_state_dir()  # see fetch_pending: re-resolve via /health next cycle
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
