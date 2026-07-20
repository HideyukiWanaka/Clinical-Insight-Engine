# Read the local shared secret the backend writes at startup (Step 6).
#
# Zero-config auth: no token is ever pasted by hand. The backend writes a fresh
# token to <state dir>/rstudio_token on every start; we re-read it on every poll
# so a backend restart self-heals within one poll interval.
#
# Locating the state dir is the delicate part. On Windows, Python's Path.home()
# (USERPROFILE) and R's path.expand("~") (R_USER/HOME) can point at different
# directories, which used to strand the Addin permanently: it would look for a
# file the backend had written elsewhere and log the same error every 2 seconds
# with no way for the user to correct it. The chain below removes the guesswork —
# GET /health reports the directory the backend actually resolved, so whoever
# started the backend, both sides agree.

# Resolution order (first hit wins):
#   1. getOption("statConsultant.home")   — manual override, mirrors baseUrl
#   2. Sys.getenv("STAT_CONSULTANT_HOME") — set when R launched the backend
#   3. state_dir from GET /health         — authoritative; backend-reported
#   4. path.expand("~/.stat-consultant")  — offline/legacy fallback
state_dir <- function() {
  opt <- getOption("statConsultant.home", "")
  if (nzchar(opt)) return(path.expand(opt))

  env <- Sys.getenv("STAT_CONSULTANT_HOME", "")
  if (nzchar(env)) return(path.expand(env))

  reported <- cached_state_dir()
  if (!is.null(reported)) return(reported)

  path.expand(file.path("~", ".stat-consultant"))
}

# The /health round-trip is cached so a 2s poll cycle doesn't add one per tick.
# Invalidated on 401 (see insert.R), which is exactly the signal that the
# backend restarted and may have resolved a different directory.
cached_state_dir <- function() {
  if (!is.null(.state$state_dir)) return(.state$state_dir)
  health <- fetch_health()
  if (is.null(health) || is.null(health$state_dir)) return(NULL)
  .state$state_dir <- path.expand(health$state_dir)
  .state$state_dir
}

forget_state_dir <- function() {
  .state$state_dir <- NULL
  invisible(NULL)
}

read_shared_secret <- function() {
  path <- file.path(state_dir(), "rstudio_token")
  if (!file.exists(path)) {
    # Either the backend isn't running, or we're holding a stale cached dir.
    # Dropping the cache makes the next cycle re-ask /health, so a backend that
    # moved (restarted with a different --state-dir) heals itself.
    forget_state_dir()
    stop(
      "Stat Consultant: 共有シークレットファイルが見つかりません。\n",
      "バックエンドが起動していることを確認してください。\n",
      "確認したパス: ", path, "\n",
      "（バックエンドが別の場所を使っている場合は、起動ログに出力される",
      "絶対パスを options(statConsultant.home = \"...\") に設定してください。）",
      call. = FALSE
    )
  }
  trimws(readLines(path, n = 1, warn = FALSE))
}
