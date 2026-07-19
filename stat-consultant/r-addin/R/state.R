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
