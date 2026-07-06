"""CIE Platform — R workspace-persistence wrapper (upstream script layer).

Implements ``spec/runtime-workspace-persistence.md`` §2. Persistence of R
variables *across executions* is achieved by wrapping the user script with an
explicit ``load()`` preamble and a ``save.image()`` epilogue that read/write a
**visible** ``.RData`` file under ``OUTPUT_DIR`` — not a resident R process
(ADR-0005 Principle 2). Because a user-inspectable, deletable file is not
"hidden state" (PROJECT_RULES.md Section 6 footnote), this is compliant.

Why this lives *upstream* of the executor
------------------------------------------
``cie/runtime/r_executor.py`` must never modify script content (RT-002). The
``load()``/``save.image()`` injection therefore happens here, in the
script-generation/wrapper layer, and the executor runs the already-wrapped
script verbatim.

Constraints honoured (kept in lock-step with the executor's static validator):
- ``--vanilla`` disables R's automatic ``.RData`` restore/save, so an
  **explicit** ``load()``/``save.image()`` is mandatory (spec §2.2).
- Paths are built only via ``file.path(Sys.getenv("OUTPUT_DIR"), ...)`` — no
  hard-coded absolute path, and ``Sys.setenv`` is never used (both are
  forbidden patterns in ``RScriptValidator``). ``Sys.getenv`` is read-only and
  permitted.
- ``load(`` / ``save.image(`` are not in the forbidden list, so the wrapped
  script still passes static validation (``source(`` is forbidden and is never
  emitted here).
"""

from __future__ import annotations

# Name of the workspace image + summary files written under OUTPUT_DIR.
RDATA_FILENAME = ".RData"
WORKSPACE_SUMMARY_FILENAME = "workspace_summary.json"

# Restore any previously-saved workspace image (spec §2.1, top). Dot-prefixed
# helper names (.cie_*) are excluded from ls() so they never appear in the
# variable summary presented to the user.
_PREAMBLE = (
    "# --- CIE workspace persistence: restore (injected, RT-002-safe) ---\n"
    '.cie_img <- file.path(Sys.getenv("OUTPUT_DIR"), ".RData")\n'
    "if (file.exists(.cie_img)) load(.cie_img)\n"
    "# --- end CIE restore ---\n"
)

# Persist the workspace image and emit the variable summary (spec §2.1, bottom).
# Runs only if the user script above completed without error (R halts a script
# on an uncaught error), so a failed run does not overwrite a good image.
_EPILOGUE = (
    "\n# --- CIE workspace persistence: save + summary (injected, RT-002-safe) ---\n"
    'save.image(file.path(Sys.getenv("OUTPUT_DIR"), ".RData"))\n'
    ".cie_ws <- lapply(ls(), function(n) {\n"
    "  obj <- get(n)\n"
    "  list(name=n, class=class(obj)[1],\n"
    "    summary=tryCatch(paste(capture.output(str(obj, max.level=0)), collapse=\" \"),\n"
    "                     error=function(e) \"\"))\n"
    "})\n"
    "jsonlite::write_json(.cie_ws,\n"
    '  file.path(Sys.getenv("OUTPUT_DIR"), "workspace_summary.json"), auto_unbox=TRUE)\n'
    "# --- end CIE save + summary ---\n"
)


def wrap_with_workspace_persistence(script_content: str) -> str:
    """Return *script_content* wrapped with load()/save.image()/summary code.

    The wrapper is prepended and appended verbatim; the user's script body is
    left untouched between them (RT-002 is a property of the executor, but the
    body is preserved here too so audit logs show exactly what the user wrote).

    Args:
        script_content: The user-authored / upstream-generated R source.

    Returns:
        The persistence-wrapped R source, ready to be written to a script file
        and executed. Still passes ``RScriptValidator`` static checks.
    """
    return f"{_PREAMBLE}\n{script_content.rstrip()}\n{_EPILOGUE}"
