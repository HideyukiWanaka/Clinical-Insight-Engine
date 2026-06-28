"""Unit tests for cie.runtime.r_executor.

Test matrix:
- test_validate_system_call_detected       — system('ls') → violation detected
- test_validate_install_packages_detected  — install.packages() → violation detected
- test_validate_absolute_path_detected     — /home/user/data.csv → violation detected
- test_validate_clean_script_passes        — clean script → no violations
- test_scope_check_required                — missing scope → RuntimeExecutionError
- test_timeout_handled                     — timeout → status="timeout", exit_code=-1
- test_output_artifacts_collected          — files in OUTPUT_DIR are listed
- test_forbidden_env_vars_not_passed       — only 3 env vars reach subprocess
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cie.core.exceptions import PermissionDeniedError, RuntimeExecutionError, SecurityViolationError
from cie.runtime.r_executor import LocalRExecutor, RScriptValidator
from cie.security.capability_token import CapabilityScope, CapabilityToken

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())


@pytest.fixture
def runtime_token() -> CapabilityToken:
    """Valid token granting RUNTIME_INVOKE_EXECUTION."""
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="runtime",
        bound_step_id="run_r_script",
        granted_scopes=frozenset({CapabilityScope.RUNTIME_INVOKE_EXECUTION}),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


@pytest.fixture
def no_scope_token() -> CapabilityToken:
    """Valid token that does NOT grant RUNTIME_INVOKE_EXECUTION."""
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="planner",
        bound_step_id="plan_step",
        granted_scopes=frozenset({CapabilityScope.AUDIT_WRITE_ENTRY}),
        denied_scopes=frozenset({CapabilityScope.RUNTIME_INVOKE_EXECUTION}),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


@pytest.fixture
def guard_passthrough() -> MagicMock:
    """ContextGuard mock that returns stdout unchanged (no PII in test data)."""
    guard = MagicMock()
    guard.sanitize_stdout = AsyncMock(side_effect=lambda text, eid: text)
    return guard


@pytest.fixture
def clean_script(tmp_path: Path) -> Path:
    """Minimal R script that passes static validation."""
    script = tmp_path / "clean.R"
    script.write_text("x <- 1 + 1\nprint(x)\n")
    return script


@pytest.fixture
def ok_proc() -> MagicMock:
    """Mock asyncio Process that exits successfully."""
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"[1] 2\n", b""))
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# RScriptValidator — static analysis
# ---------------------------------------------------------------------------


class TestRScriptValidator:
    """Tests for the pre-execution R script analyser."""

    def test_validate_system_call_detected(self) -> None:
        violations = RScriptValidator().validate("system('ls -la')")
        assert any("system()" in v for v in violations), violations

    def test_validate_system2_detected(self) -> None:
        violations = RScriptValidator().validate("system2('ls', '-la')")
        assert any("system2()" in v for v in violations), violations

    def test_validate_install_packages_detected(self) -> None:
        violations = RScriptValidator().validate("install.packages('ggplot2')")
        assert any("install.packages()" in v for v in violations), violations

    def test_validate_absolute_path_detected(self) -> None:
        violations = RScriptValidator().validate('data <- read.csv("/home/user/data.csv")')
        assert any("/home/" in v for v in violations), violations

    def test_validate_sys_setenv_detected(self) -> None:
        violations = RScriptValidator().validate("Sys.setenv(HOME='/tmp')")
        assert any("Sys.setenv()" in v for v in violations), violations

    def test_validate_warn_suppression_detected(self) -> None:
        violations = RScriptValidator().validate("options(warn=-1)")
        assert any("warn" in v for v in violations), violations

    def test_validate_source_detected(self) -> None:
        violations = RScriptValidator().validate("source('helpers.R')")
        assert any("source()" in v for v in violations), violations

    def test_validate_windows_absolute_path_detected(self) -> None:
        violations = RScriptValidator().validate('read.csv("C:\\\\Users\\\\data.csv")')
        assert violations, "Windows path should be detected"

    def test_validate_clean_script_passes(self) -> None:
        clean = (
            "library(tidyverse)\n"
            "data <- readRDS(file.path(Sys.getenv('WORKSPACE_DIR'), 'data.rds'))\n"
            "result <- t.test(x ~ group, data = data)\n"
            "saveRDS(result, file.path(Sys.getenv('OUTPUT_DIR'), 'result.rds'))\n"
        )
        assert RScriptValidator().validate(clean) == []

    def test_validate_returns_all_violations(self) -> None:
        """Multiple forbidden patterns produce one entry per violation."""
        bad = "system('ls')\ninstall.packages('foo')\n"
        violations = RScriptValidator().validate(bad)
        assert len(violations) >= 2


# ---------------------------------------------------------------------------
# LocalRExecutor — async execution
# ---------------------------------------------------------------------------


class TestLocalRExecutor:
    """Tests for the sandboxed R execution engine."""

    # ------------------------------------------------------------------
    # Scope / permission guard
    # ------------------------------------------------------------------

    async def test_scope_check_required(
        self,
        tmp_path: Path,
        guard_passthrough: MagicMock,
        clean_script: Path,
        no_scope_token: CapabilityToken,
    ) -> None:
        """execute() must raise when the token lacks RUNTIME_INVOKE_EXECUTION."""
        executor = LocalRExecutor(tmp_path / "ws", tmp_path / "out", guard_passthrough)
        with pytest.raises((PermissionDeniedError, SecurityViolationError)):
            await executor.execute(EXEC_ID, clean_script, no_scope_token)

    async def test_security_validation_raises_runtime_error(
        self,
        tmp_path: Path,
        guard_passthrough: MagicMock,
        runtime_token: CapabilityToken,
    ) -> None:
        """Forbidden patterns in the script raise RuntimeExecutionError before subprocess launch."""
        script = tmp_path / "bad.R"
        script.write_text("system('rm -rf /')\n")

        executor = LocalRExecutor(tmp_path / "ws", tmp_path / "out", guard_passthrough)
        with pytest.raises(RuntimeExecutionError, match="security validation"):
            await executor.execute(EXEC_ID, script, runtime_token)

    # ------------------------------------------------------------------
    # Successful execution
    # ------------------------------------------------------------------

    async def test_successful_execution_returns_result(
        self,
        tmp_path: Path,
        guard_passthrough: MagicMock,
        clean_script: Path,
        runtime_token: CapabilityToken,
        ok_proc: MagicMock,
    ) -> None:
        executor = LocalRExecutor(tmp_path / "ws", tmp_path / "out", guard_passthrough)
        (tmp_path / "ws").mkdir(exist_ok=True)
        (tmp_path / "out").mkdir(exist_ok=True)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ok_proc
            result = await executor.execute(EXEC_ID, clean_script, runtime_token)

        assert result.status == "success"
        assert result.exit_code == 0
        assert result.execution_id == EXEC_ID
        assert result.duration_ms >= 0

    # ------------------------------------------------------------------
    # Timeout handling
    # ------------------------------------------------------------------

    async def test_timeout_handled(
        self,
        tmp_path: Path,
        guard_passthrough: MagicMock,
        clean_script: Path,
        runtime_token: CapabilityToken,
    ) -> None:
        """When the process exceeds MAX_EXECUTION_SECONDS, status must be 'timeout'."""
        proc = MagicMock()
        proc.returncode = None  # not yet finished
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.kill = MagicMock()

        executor = LocalRExecutor(tmp_path / "ws", tmp_path / "out", guard_passthrough)
        (tmp_path / "ws").mkdir(exist_ok=True)
        (tmp_path / "out").mkdir(exist_ok=True)

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
        ):
            mock_exec.return_value = proc
            result = await executor.execute(EXEC_ID, clean_script, runtime_token)

        assert result.status == "timeout"
        assert result.exit_code == -1
        proc.kill.assert_called()

    # ------------------------------------------------------------------
    # Output artifact collection
    # ------------------------------------------------------------------

    async def test_output_artifacts_collected(
        self,
        tmp_path: Path,
        guard_passthrough: MagicMock,
        clean_script: Path,
        runtime_token: CapabilityToken,
        ok_proc: MagicMock,
    ) -> None:
        """Files present in OUTPUT_DIR after execution appear in output_artifacts."""
        ws = tmp_path / "ws"
        ws.mkdir()
        out = tmp_path / "out"
        out.mkdir()

        # Simulate files written by the R script
        (out / "execution_result.rds").write_bytes(b"\x00")
        (out / "plot.png").write_bytes(b"\x89PNG")

        executor = LocalRExecutor(ws, out, guard_passthrough)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ok_proc
            result = await executor.execute(EXEC_ID, clean_script, runtime_token)

        assert "execution_result.rds" in result.output_artifacts
        assert "plot.png" in result.output_artifacts
        assert len(result.output_artifacts) == 2

    # ------------------------------------------------------------------
    # Environment isolation
    # ------------------------------------------------------------------

    async def test_forbidden_env_vars_not_passed(
        self,
        tmp_path: Path,
        guard_passthrough: MagicMock,
        clean_script: Path,
        runtime_token: CapabilityToken,
        ok_proc: MagicMock,
    ) -> None:
        """The subprocess must receive exactly three env vars; no host env vars inherited."""
        ws = tmp_path / "ws"
        ws.mkdir()
        out = tmp_path / "out"
        out.mkdir()

        executor = LocalRExecutor(ws, out, guard_passthrough)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ok_proc
            await executor.execute(EXEC_ID, clean_script, runtime_token)

        _, kwargs = mock_exec.call_args
        env: dict[str, str] = kwargs["env"]

        # Host variables must not bleed through
        assert "PATH" not in env
        assert "HOME" not in env
        assert "USER" not in env
        assert "PYTHONPATH" not in env

        # Only the three CIE variables must be present
        assert set(env.keys()) == {"CIE_EXECUTION_ID", "WORKSPACE_DIR", "OUTPUT_DIR"}
        assert env["CIE_EXECUTION_ID"] == EXEC_ID
        assert env["WORKSPACE_DIR"] == str(ws)
        assert env["OUTPUT_DIR"] == str(out)

    # ------------------------------------------------------------------
    # Subprocess invocation flags
    # ------------------------------------------------------------------

    async def test_rscript_invoked_with_correct_flags(
        self,
        tmp_path: Path,
        guard_passthrough: MagicMock,
        clean_script: Path,
        runtime_token: CapabilityToken,
        ok_proc: MagicMock,
    ) -> None:
        """Rscript must be invoked with --vanilla --slave (spec/runtime.yaml)."""
        (tmp_path / "ws").mkdir(exist_ok=True)
        (tmp_path / "out").mkdir(exist_ok=True)
        executor = LocalRExecutor(tmp_path / "ws", tmp_path / "out", guard_passthrough)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ok_proc
            await executor.execute(EXEC_ID, clean_script, runtime_token)

        args, _ = mock_exec.call_args
        assert args[0] == "Rscript"
        assert "--vanilla" in args
        assert "--slave" in args

    # ------------------------------------------------------------------
    # stdout / stderr sanitization and truncation
    # ------------------------------------------------------------------

    async def test_stdout_digest_computed_from_sanitized_output(
        self,
        tmp_path: Path,
        runtime_token: CapabilityToken,
        clean_script: Path,
    ) -> None:
        """stdout_digest must be sha256 of the sanitized stdout, not raw bytes."""
        import hashlib

        raw_output = b"R output line\n"
        sanitized_output = "SANITIZED"

        guard = MagicMock()
        guard.sanitize_stdout = AsyncMock(return_value=sanitized_output)

        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(raw_output, b""))
        proc.kill = MagicMock()

        (tmp_path / "ws").mkdir(exist_ok=True)
        (tmp_path / "out").mkdir(exist_ok=True)
        executor = LocalRExecutor(tmp_path / "ws", tmp_path / "out", guard)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = proc
            result = await executor.execute(EXEC_ID, clean_script, runtime_token)

        expected_digest = hashlib.sha256(sanitized_output.encode()).hexdigest()
        assert result.stdout_digest == expected_digest

    async def test_stdout_summary_truncated_to_1000_chars(
        self,
        tmp_path: Path,
        guard_passthrough: MagicMock,
        clean_script: Path,
        runtime_token: CapabilityToken,
    ) -> None:
        """sanitized_stdout_summary must be at most 1 000 characters."""
        long_output = b"x" * 5000

        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(long_output, b""))
        proc.kill = MagicMock()

        (tmp_path / "ws").mkdir(exist_ok=True)
        (tmp_path / "out").mkdir(exist_ok=True)
        executor = LocalRExecutor(tmp_path / "ws", tmp_path / "out", guard_passthrough)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = proc
            result = await executor.execute(EXEC_ID, clean_script, runtime_token)

        assert len(result.sanitized_stdout_summary) <= 1000

    # ------------------------------------------------------------------
    # Session info parsing
    # ------------------------------------------------------------------

    def test_collect_r_session_info_parses_version(self, tmp_path: Path) -> None:
        """R version is extracted from sessionInfo() output."""
        guard = MagicMock()
        executor = LocalRExecutor(tmp_path, tmp_path, guard)
        stdout = "R version 4.3.1 (2023-06-16)\nPlatform: x86_64-pc-linux-gnu\n"
        info = executor._collect_r_session_info(stdout)
        assert info["r_version"] == "4.3.1"

    def test_collect_r_session_info_parses_packages(self, tmp_path: Path) -> None:
        """Package versions are extracted from sessionInfo() attached packages."""
        guard = MagicMock()
        executor = LocalRExecutor(tmp_path, tmp_path, guard)
        stdout = "other attached packages:\n[1] tidyverse_2.0.0 ggplot2_3.4.4\n"
        info = executor._collect_r_session_info(stdout)
        assert info["package_versions"].get("tidyverse") == "2.0.0"
        assert info["package_versions"].get("ggplot2") == "3.4.4"

    def test_extract_dataset_hash_found(self, tmp_path: Path) -> None:
        guard = MagicMock()
        executor = LocalRExecutor(tmp_path, tmp_path, guard)
        sha = "a" * 64
        result = executor._extract_dataset_hash(f"dataset_hash: {sha}")
        assert result == sha

    def test_extract_dataset_hash_not_found(self, tmp_path: Path) -> None:
        guard = MagicMock()
        executor = LocalRExecutor(tmp_path, tmp_path, guard)
        assert executor._extract_dataset_hash("no hash here") is None
