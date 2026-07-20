# One-click launch (Phase 3 of the distribution work).
#
# The user installs this R package and nothing else: the Python backend ships as
# a self-contained binary alongside it, and the built frontend is served by that
# same binary on one port. So "start the app" means: find the binary, start it if
# it isn't already up, wait for it to answer, open the browser, begin polling.
#
# Starting the backend from R also removes the last source of path ambiguity —
# we pass our own resolved state directory with --state-dir, so both sides agree
# by construction rather than by both guessing at "~" (see token.R).

# Where the backend binary lives. The installer (install.R) records the path in
# config.json, so in the normal case nothing needs to be set by hand; the option
# and env var exist for dev and for unusual install locations.
.backend_exe_name <- function() {
  if (.Platform$OS.type == "windows") {
    "stat-consultant-backend.exe"
  } else {
    "stat-consultant-backend"
  }
}

.config_path <- function() {
  file.path(state_dir(), "config.json")
}

.config_backend_path <- function() {
  path <- .config_path()
  if (!file.exists(path)) return(NULL)
  cfg <- tryCatch(
    jsonlite::fromJSON(path),
    error = function(e) NULL
  )
  if (is.null(cfg) || is.null(cfg$backend_path)) return(NULL)
  cfg$backend_path
}

.conventional_dirs <- function() {
  exe <- .backend_exe_name()
  if (.Platform$OS.type == "windows") {
    roots <- c(Sys.getenv("LOCALAPPDATA", ""), Sys.getenv("PROGRAMFILES", ""))
    roots <- roots[nzchar(roots)]
    file.path(roots, "StatConsultant", "stat-consultant-backend", exe)
  } else {
    c(
      path.expand(file.path("~", "Applications", "StatConsultant",
                            "stat-consultant-backend", exe)),
      file.path("/Applications", "StatConsultant",
                "stat-consultant-backend", exe)
    )
  }
}

# Resolution order mirrors token.R's: explicit override, then env, then the
# installer's record, then the conventional install location.
find_backend <- function() {
  opt <- getOption("statConsultant.backendPath", "")
  if (nzchar(opt) && file.exists(opt)) return(normalizePath(opt))

  env <- Sys.getenv("STAT_CONSULTANT_BACKEND", "")
  if (nzchar(env) && file.exists(env)) return(normalizePath(env))

  cfg <- .config_backend_path()
  if (!is.null(cfg) && file.exists(cfg)) return(normalizePath(cfg))

  for (candidate in .conventional_dirs()) {
    if (file.exists(candidate)) return(normalizePath(candidate))
  }

  stop(
    "Stat Consultant: バックエンドの実行ファイルが見つかりません。\n",
    "インストーラ(install.R)を実行したか確認してください。\n",
    "手動で指定する場合: ",
    "options(statConsultant.backendPath = \"<パス>\")",
    call. = FALSE
  )
}

backend_alive <- function() {
  !is.null(fetch_health())
}

# Poll /health rather than sleeping a fixed amount: a cold start (first launch
# after an update, or a slow disk) can take several seconds, and a fixed wait
# either wastes time or opens the browser too early on a "can't connect" page.
wait_for_health <- function(timeout_sec = 30) {
  deadline <- Sys.time() + timeout_sec
  repeat {
    if (backend_alive()) return(TRUE)
    if (Sys.time() > deadline) return(FALSE)
    Sys.sleep(0.5)
  }
}

#' Start Stat Consultant (backend + browser + poller)
#'
#' The single entry point for normal use. Starts the bundled backend if it is
#' not already running, waits for it to become healthy, opens the chat UI in the
#' default browser, and begins the code-insertion / environment-sync poller.
#'
#' Safe to invoke repeatedly: an already-running backend is reused rather than
#' started twice.
#'
#' @param interval_sec Poll interval in seconds, passed to
#'   \code{statConsultantInsertCode()}.
#' @param open_browser Whether to open the chat UI (set \code{FALSE} if the tab
#'   is already open).
#' @export
statConsultantStart <- function(interval_sec = 2, open_browser = TRUE) {
  if (!rstudioapi::isAvailable()) {
    stop("Stat Consultant: RStudio内で実行してください。", call. = FALSE)
  }

  if (backend_alive()) {
    message("Stat Consultant: 起動中のバックエンドに接続しました。")
  } else {
    exe <- find_backend()
    dir <- state_dir()
    # The backend creates this directory itself, but processx opens the log file
    # before the backend runs — so on a first launch the redirect would fail
    # with ENOENT, which surfaces confusingly as "cannot start process <exe>".
    if (!dir.exists(dir)) {
      dir.create(dir, recursive = TRUE, mode = "0700")
    }
    log_path <- file.path(dir, "backend.log")
    message("Stat Consultant: バックエンドを起動しています…")
    # processx over system2: we need the console window hidden on Windows, the
    # output captured to a log (the only diagnostic channel a non-technical user
    # can send us), and a handle to check liveness. cleanup = FALSE so closing
    # RStudio doesn't kill a chat the user is still reading.
    .state$proc <- processx::process$new(
      exe,
      c("--port", .base_port(), "--state-dir", dir),
      stdout = log_path,
      stderr = "2>&1",
      windows_hide_window = TRUE,
      cleanup = FALSE
    )
    # The backend rewrites the token on start, so anything cached is stale.
    forget_state_dir()
    if (!wait_for_health(30)) {
      stop(
        "Stat Consultant: バックエンドが応答しません（30秒待機）。\n",
        "ログを確認してください: ", log_path,
        call. = FALSE
      )
    }
    message("Stat Consultant: バックエンドが起動しました。")
  }

  if (isTRUE(open_browser)) {
    utils::browseURL(.base_url())
  }
  statConsultantInsertCode(interval_sec)
}

#' Stop Stat Consultant (poller and backend)
#'
#' Stops the poller, and shuts down the backend if this session started it.
#' A backend that was already running when \code{statConsultantStart()} was
#' called is left alone — it may belong to another session.
#'
#' @export
statConsultantStop <- function() {
  statConsultantStopInsert()
  proc <- .state$proc
  if (!is.null(proc) && proc$is_alive()) {
    proc$kill()
    message("Stat Consultant: バックエンドを停止しました。")
  }
  .state$proc <- NULL
  forget_state_dir()
  invisible(NULL)
}
