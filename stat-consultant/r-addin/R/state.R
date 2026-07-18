# Package-local mutable state for the code-insertion poller (Step 6).
#
# `later`-based polling is non-blocking: callbacks run on RStudio's idle event
# loop, so the console stays free to run the inserted code. Stopping the loop
# therefore can't rely on Ctrl-C / Esc (there's no blocking call to interrupt)
# — it's driven by this `running` flag, flipped by the start / stop addins.
.state <- new.env(parent = emptyenv())
.state$running <- FALSE
