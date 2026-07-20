# Package-local mutable state for the code-insertion poller (Step 6).
#
# `later`-based polling is non-blocking: callbacks run on RStudio's idle event
# loop, so the console stays free to run the inserted code. Stopping the loop
# therefore can't rely on Ctrl-C / Esc (there's no blocking call to interrupt)
# — it's driven by this `running` flag, flipped by the start / stop addins.
.state <- new.env(parent = emptyenv())
.state$running <- FALSE
# Signature of the last successfully synced environment snapshot (Step 7). The
# scan loop only POSTs when this changes, so an unchanged GlobalEnv doesn't spam
# the backend; NULL means "nothing synced yet" (first change always sends).
.state$last_env_sig <- NULL
# State directory as reported by GET /health (token.R). Cached so the 2s poll
# doesn't add a round-trip per tick; NULL means "not asked yet / invalidated".
# Cleared on 401, which is precisely when the backend restarted and might have
# resolved a different directory than the one we cached.
.state$state_dir <- NULL
# processx handle for a backend this session started (launch.R). NULL when the
# backend was already running — statConsultantStop() only kills what it spawned,
# since a pre-existing process may belong to another RStudio session.
.state$proc <- NULL
