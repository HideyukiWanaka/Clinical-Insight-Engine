"""Unit tests for cie.runtime.workspace_wrapper.

The wrapper injects the .RData load()/save.image()/summary code *upstream* of
the executor (spec/runtime-workspace-persistence.md §2). These tests pin the two
invariants the spec cares about:

- The wrapped script still passes the executor's static validator (no absolute
  path, no Sys.setenv, no source()) — spec §2.2 / §5.
- The user's original body is preserved verbatim between preamble and epilogue
  (audit reproducibility — the executed script is what gets logged).
"""

from __future__ import annotations

from cie.runtime.r_executor import RScriptValidator
from cie.runtime.workspace_wrapper import (
    RDATA_FILENAME,
    WORKSPACE_SUMMARY_FILENAME,
    wrap_with_workspace_persistence,
)


def test_constants() -> None:
    assert RDATA_FILENAME == ".RData"
    assert WORKSPACE_SUMMARY_FILENAME == "workspace_summary.json"


def test_wrapped_contains_explicit_load_and_save() -> None:
    """--vanilla disables auto restore/save, so both must be explicit (§2.2)."""
    wrapped = wrap_with_workspace_persistence("x <- 1\n")
    assert "load(.cie_img)" in wrapped
    assert "save.image(" in wrapped
    assert "jsonlite::write_json(" in wrapped


def test_wrapped_preserves_user_body() -> None:
    body = "data$bmi_cat <- cut(data$bmi, c(0,18.5,25,30,100))"
    wrapped = wrap_with_workspace_persistence(body)
    assert body in wrapped


def test_wrapped_uses_only_output_dir_relative_paths() -> None:
    """Paths must be file.path(Sys.getenv('OUTPUT_DIR'), ...) — never absolute."""
    wrapped = wrap_with_workspace_persistence("y <- 2")
    assert 'file.path(Sys.getenv("OUTPUT_DIR"), ".RData")' in wrapped
    # Sys.getenv (read) is allowed; Sys.setenv (mutate) is forbidden and absent.
    assert "Sys.setenv" not in wrapped


def test_wrapped_passes_static_validation() -> None:
    """Wrapping must not introduce any forbidden pattern (§5)."""
    body = (
        'data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"),"dataset.csv"))\n'
        "data$bmi_cat <- cut(data$bmi, c(0,18.5,25,30,100))\n"
    )
    wrapped = wrap_with_workspace_persistence(body)
    violations = RScriptValidator().validate(wrapped)
    assert violations == []


def test_wrapper_does_not_emit_forbidden_source() -> None:
    wrapped = wrap_with_workspace_persistence("z <- 3")
    assert "source(" not in wrapped
