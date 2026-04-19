# =========================================================
# plumber.R — CIE R Engine API Router
# Auto-scans skills/ directory and mounts each skill's
# endpoints. New skills need only drop a .R file here.
# =========================================================

library(plumber)
library(logger)

log_threshold(INFO)
log_info("CIE R Engine starting — scanning skills directory...")

# ── Health Check ──────────────────────────────────────────
#* @get /health
#* @serializer json
#* @tag system
function(res) {
  res$status <- 200L
  list(
    status  = "ok",
    service = "r-engine",
    version = "1.0.0",
    time    = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    internet_access = tryCatch({
      con <- url("https://example.com", open = "rb", timeout = 3)
      close(con)
      "UNEXPECTED: internet reachable — check network isolation"
    }, error = function(e) "blocked (expected)")
  )
}

# ── Skills Auto-mount ─────────────────────────────────────
skills_dir <- file.path(dirname(sys.frame(1)$ofile %||% "/app"), "skills")
if (!dir.exists(skills_dir)) skills_dir <- "/app/skills"

skill_files <- list.files(skills_dir, pattern = "\\.R$", full.names = TRUE)
log_info("Found {length(skill_files)} skill(s): {paste(basename(skill_files), collapse=', ')}")

# Each skill file is sourced; they register their own Plumber endpoints
# via @get / @post annotations, accessed at /skills/{skill_id}/...
for (skill_file in skill_files) {
  skill_id <- tools::file_path_sans_ext(basename(skill_file))
  tryCatch({
    source(skill_file, local = TRUE)
    log_info("Skill loaded: {skill_id}")
  }, error = function(e) {
    log_error("Failed to load skill '{skill_id}': {conditionMessage(e)}")
  })
}

# Helper (base R has no %||%)
`%||%` <- function(a, b) if (!is.null(a)) a else b
