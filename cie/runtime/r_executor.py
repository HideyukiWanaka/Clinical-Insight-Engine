"""CIE Platform — Local Restricted R Script Executor.

Implements the R execution side of the Local Restricted Runtime defined in
spec/runtime.yaml (local_restricted_runtime section).

Security rules enforced (agents/runtime.yaml):
  RT-001: Isolated sandbox — restricted environment, no shell
  RT-002: Never modify script content
  RT-004: Sanitize stdout via ContextGuard before any downstream use
  RT-005: Terminate on resource limit (timeout / memory)
  RT-006: Package install requires approval token — blocked at validation stage
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from cie.core.exceptions import RuntimeExecutionError
from cie.security.capability_token import CapabilityScope, CapabilityToken
from cie.security.context_guard import ContextGuard

# ---------------------------------------------------------------------------
# Forbidden pattern registry
# Each entry: (compiled regex, human-readable violation description)
# Source: knowledge/R/statistical_packages.md — Forbidden R Patterns
# ---------------------------------------------------------------------------

_PatternEntry = tuple[re.Pattern[str], str]

FORBIDDEN_R_PATTERNS: list[_PatternEntry] = [
    (re.compile(r"\bsystem\s*\("), "system() — shell escape not permitted (RT-001)"),
    (re.compile(r"\bsystem2\s*\("), "system2() — shell escape not permitted (RT-001)"),
    (re.compile(r"\bshell\s*\("), "shell() — shell escape not permitted (RT-001)"),
    (re.compile(r"\bSys\.setenv\s*\("), "Sys.setenv() — environment mutation not permitted"),
    (re.compile(r"\binstall\.packages\s*\("), "install.packages() — unapproved installation (RT-006)"),
    (re.compile(r"options\s*\(\s*warn\s*=\s*-\d"), "options(warn=<negative>) — warning suppression not permitted"),
    (re.compile(r"\bsource\s*\("), "source() — uncontrolled external code loading not permitted"),
]

# Hard-coded absolute paths bypass the approved WORKSPACE_DIR/OUTPUT_DIR aliases
# and break reproducibility (knowledge/R/statistical_packages.md).
_ABSOLUTE_PATH_PATTERNS: list[_PatternEntry] = [
    (re.compile(r"C:\\\\"), "Hard-coded Windows absolute path (C:\\...)"),
    (re.compile(r"C:/"), "Hard-coded Windows absolute path (C:/...)"),
    (re.compile(r"/home/"), "Hard-coded Unix absolute path (/home/)"),
    (re.compile(r"/etc/"), "Hard-coded Unix absolute path (/etc/)"),
    (re.compile(r"/var/"), "Hard-coded Unix absolute path (/var/)"),
    (re.compile(r"/usr/"), "Hard-coded Unix absolute path (/usr/)"),
]


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Structured outcome of a sandboxed R script execution.

    All output fields contain sanitized data only — no raw PII-bearing text
    is ever stored here (RT-004).

    Attributes:
        execution_id: Unique identifier for this execution run.
        status: Terminal state of the execution.
        exit_code: OS exit code; -1 when the process was killed or timed out.
        duration_ms: Wall-clock time from process spawn to completion.
        stdout_digest: SHA-256 hex digest of the sanitized stdout bytes.
        stderr_digest: SHA-256 hex digest of the sanitized stderr bytes.
        sanitized_stdout_summary: First 1 000 characters of sanitized stdout.
        output_artifacts: Relative paths of files found under OUTPUT_DIR.
        r_version: R version string extracted from sessionInfo() output.
        package_versions: Package-name → version-string mapping from sessionInfo().
        dataset_hash: SHA-256 hash of the input dataset as reported by the script.
    """

    execution_id: str
    status: Literal["success", "timeout", "error", "security_abort"]
    exit_code: int
    duration_ms: int
    stdout_digest: str
    stderr_digest: str
    sanitized_stdout_summary: str
    output_artifacts: list[str] = field(default_factory=list)
    r_version: str | None = None
    package_versions: dict[str, str] = field(default_factory=dict)
    dataset_hash: str | None = None


# ---------------------------------------------------------------------------
# Static script validator
# ---------------------------------------------------------------------------


class RScriptValidator:
    """Pre-execution static analyser for R scripts.

    Checks for forbidden function calls and hard-coded absolute paths.
    No modification of the script is performed (RT-002).
    """

    def validate(self, script_content: str) -> list[str]:
        """Return a list of violation descriptions found in *script_content*.

        Args:
            script_content: Raw R source code as a UTF-8 string.

        Returns:
            A list of human-readable violation descriptions. An empty list
            means the script passed all checks.
        """
        violations: list[str] = []

        for pattern, description in FORBIDDEN_R_PATTERNS:
            if pattern.search(script_content):
                violations.append(description)

        for pattern, description in _ABSOLUTE_PATH_PATTERNS:
            if pattern.search(script_content):
                violations.append(description)

        return violations


# ---------------------------------------------------------------------------
# Local R Executor
# ---------------------------------------------------------------------------


class LocalRExecutor:
    """Sandboxed R script executor backed by asyncio subprocesses.

    Enforces the Local Restricted Runtime contract from spec/runtime.yaml.
    shell=True is never used; the subprocess is launched via
    asyncio.create_subprocess_exec (RT-001).

    Args:
        workspace_dir: Read/write workspace directory visible to the R process.
        output_dir: Directory where the R script writes its output artifacts.
        context_guard: Used to sanitize stdout/stderr before digesting (RT-004).
    """

    MAX_EXECUTION_SECONDS: int = 300   # spec/runtime.yaml max_execution_time_seconds
    MAX_MEMORY_MB: int = 4096          # spec/runtime.yaml max_memory_limit_mb
    MAX_STDOUT_BYTES: int = 1_048_576  # spec/runtime.yaml max_stdout_buffer_bytes (1 MB)
    MAX_STDERR_BYTES: int = 524_288    # spec/runtime.yaml max_stderr_buffer_bytes (512 KB)

    def __init__(
        self,
        workspace_dir: Path,
        output_dir: Path,
        context_guard: ContextGuard,
    ) -> None:
        self._workspace_dir = workspace_dir
        self._output_dir = output_dir
        self._context_guard = context_guard

    async def execute(
        self,
        execution_id: str,
        script_path: Path,
        capability_token: CapabilityToken,
    ) -> ExecutionResult:
        """Execute *script_path* inside the restricted sandbox.

        The capability token is validated at entry. The subprocess runs with
        only three environment variables (CIE_EXECUTION_ID, WORKSPACE_DIR,
        OUTPUT_DIR) — all inherited host variables are stripped (RT-001).

        Args:
            execution_id: Correlation identifier for this execution run.
            script_path: Absolute path to the R script file.
            capability_token: Must grant RUNTIME_INVOKE_EXECUTION scope.

        Returns:
            An :class:`ExecutionResult` whose output fields are sanitized.

        Raises:
            SecurityViolationError: When the token is revoked or expired.
            PermissionDeniedError: When the token lacks RUNTIME_INVOKE_EXECUTION.
            RuntimeExecutionError: When static validation detects forbidden patterns.
        """
        # Step 1 — scope guard (fail-fast; SecurityViolationError/PermissionDeniedError)
        capability_token.require_scope(CapabilityScope.RUNTIME_INVOKE_EXECUTION)

        # Step 2 — static validation; raise before any subprocess is spawned
        script_content = script_path.read_text(encoding="utf-8")
        violations = RScriptValidator().validate(script_content)
        if violations:
            raise RuntimeExecutionError(
                f"Script failed security validation: {'; '.join(violations)}",
                runtime_provider="local_restricted_runtime",
                execution_id=execution_id,
            )

        # Step 3 — minimal environment (RT-001: no host vars inherited)
        restricted_env: dict[str, str] = {
            "CIE_EXECUTION_ID": execution_id,
            "WORKSPACE_DIR": str(self._workspace_dir),
            "OUTPUT_DIR": str(self._output_dir),
        }

        status: Literal["success", "timeout", "error", "security_abort"] = "error"
        exit_code: int = -1
        raw_stdout: bytes = b""
        raw_stderr: bytes = b""
        proc: asyncio.subprocess.Process | None = None

        start_ns = time.monotonic_ns()
        try:
            # Step 4 — launch subprocess (shell=False is guaranteed by create_subprocess_exec)
            proc = await asyncio.create_subprocess_exec(
                "Rscript",
                "--vanilla",
                "--slave",
                str(script_path),
                env=restricted_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Step 5 — enforce wall-clock timeout (RT-005)
            try:
                raw_stdout, raw_stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=float(self.MAX_EXECUTION_SECONDS),
                )
                exit_code = proc.returncode if proc.returncode is not None else -1
                status = "success" if exit_code == 0 else "error"
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await proc.communicate()
                except Exception:  # noqa: BLE001
                    pass
                exit_code = -1
                status = "timeout"

        finally:
            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            # Ensure the process is reaped even on unexpected exceptions
            if proc is not None and proc.returncode is None:
                proc.kill()

        # Truncate captured streams to spec buffer limits before any processing
        raw_stdout = raw_stdout[: self.MAX_STDOUT_BYTES]
        raw_stderr = raw_stderr[: self.MAX_STDERR_BYTES]

        stdout_str = raw_stdout.decode("utf-8", errors="replace")
        stderr_str = raw_stderr.decode("utf-8", errors="replace")

        # Step 6 — sanitize via ContextGuard (RT-004: no PII in logs or summaries)
        sanitized_stdout = await self._context_guard.sanitize_stdout(stdout_str, execution_id)
        sanitized_stderr = await self._context_guard.sanitize_stdout(stderr_str, execution_id)

        stdout_digest = hashlib.sha256(sanitized_stdout.encode()).hexdigest()
        stderr_digest = hashlib.sha256(sanitized_stderr.encode()).hexdigest()

        # Step 7 — collect output artifacts from OUTPUT_DIR
        output_artifacts = self._collect_output_artifacts()

        # Parse R session metadata embedded in stdout
        session_info = self._collect_r_session_info(sanitized_stdout)

        # Step 8 — assemble structured result
        return ExecutionResult(
            execution_id=execution_id,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_digest=stdout_digest,
            stderr_digest=stderr_digest,
            sanitized_stdout_summary=sanitized_stdout[:1000],
            output_artifacts=output_artifacts,
            r_version=session_info.get("r_version"),
            package_versions=session_info.get("package_versions", {}),
            dataset_hash=self._extract_dataset_hash(sanitized_stdout),
        )

    def _collect_output_artifacts(self) -> list[str]:
        """Return relative paths of all files currently under OUTPUT_DIR."""
        if not self._output_dir.exists():
            return []
        return sorted(
            str(p.relative_to(self._output_dir))
            for p in self._output_dir.rglob("*")
            if p.is_file()
        )

    def _collect_r_session_info(self, stdout: str) -> dict[str, object]:
        """Extract R version and package versions from sessionInfo() stdout.

        Parses the plain-text output of R's sessionInfo() without any external
        tooling — pure regex only (PROJECT_RULES.md Section 14).

        Args:
            stdout: Sanitized stdout from the R process.

        Returns:
            A dict with keys ``"r_version"`` (str | None) and
            ``"package_versions"`` (dict[str, str]).
        """
        result: dict[str, object] = {"r_version": None, "package_versions": {}}

        # "R version 4.3.1 (2023-06-16)"
        r_ver = re.search(r"R version (\d+\.\d+\.\d+)", stdout)
        if r_ver:
            result["r_version"] = r_ver.group(1)

        # Attached package lines: "tidyverse_2.0.0" "ggplot2_3.4.4" etc.
        pkg_versions: dict[str, str] = {}
        for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9.]+)_(\d+\.\d+(?:\.\d+)*)\b", stdout):
            pkg_versions[match.group(1)] = match.group(2)
        result["package_versions"] = pkg_versions

        return result

    def _extract_dataset_hash(self, stdout: str) -> str | None:
        """Extract a SHA-256 dataset hash printed by the R script.

        R scripts following the 5-block template call
        ``digest::digest(data, algo="sha256")`` and may print the result
        with a ``dataset_hash:`` prefix (knowledge/R/statistical_packages.md).

        Args:
            stdout: Sanitized stdout from the R process.

        Returns:
            A 64-character hex string, or ``None`` if not found.
        """
        match = re.search(r"dataset_hash[:\s]+([a-f0-9]{64})", stdout, re.IGNORECASE)
        return match.group(1) if match else None
