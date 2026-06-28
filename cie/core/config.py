"""CIE Platform — Runtime configuration.

Loads and validates global platform settings from ``spec/configuration.yaml``
using Pydantic BaseSettings.  All values are typed and documented; no business
logic lives here (PROJECT_RULES.md Section 14, Phase 1 skeleton).

Design decisions:
- ``pydantic-settings`` is used so every field can be overridden by an
  environment variable during testing or CI, supporting the
  *Configuration over hardcoding* principle.
- Default paths reference ``{USER_DOCUMENTS}`` which is resolved at
  import-time via :func:`_default_documents_dir`.
- The class is intentionally free of runtime side-effects: it only reads
  configuration; it never opens files, connects to databases, or starts
  threads.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_documents_dir() -> str:
    """Return the platform-appropriate user Documents directory.

    Follows the spec/configuration.yaml ``${USER_DOCUMENTS}`` convention.

    Returns:
        Absolute path string to the user's Documents folder.  Falls back to
        the user home directory when a Documents sub-folder does not exist.
    """
    home = Path.home()
    documents = home / "Documents"
    return str(documents) if documents.is_dir() else str(home)


def _default_database_filepath() -> str:
    """Return the default database file path.

    Returns:
        Absolute path string of the form ``<USER_DOCUMENTS>/CIE/cie_database.db``.
    """
    return str(Path(_default_documents_dir()) / "CIE" / "cie_database.db")


def _default_workspace_directory() -> str:
    """Return the default workspace directory path.

    Returns:
        Absolute path string of the form ``<USER_DOCUMENTS>/CIE/workspace``.
    """
    return str(Path(_default_documents_dir()) / "CIE" / "workspace")


class CIEConfig(BaseSettings):
    """Global runtime configuration for the CIE Platform.

    All settings map 1-to-1 to the keys declared in
    ``spec/configuration.yaml`` and can be overridden by environment
    variables prefixed with ``CIE_`` (e.g., ``CIE_OFFLINE_FIRST_MODE=false``).

    Attributes:
        database_filepath: Absolute path to the SQLite database file.
        workspace_directory: Absolute path to the user's workspace directory.
        offline_first_mode: When ``True``, the platform prefers local
            resources and treats internet access as unavailable.
        default_ui_language: BCP-47 language tag for the default UI language
            (e.g., ``"ja"`` for Japanese).
        global_minimum_pass_score: Minimum evaluation score (0–100) required
            for a workflow output to be accepted.
        enable_pii_regex_guardrail: Activates Layer 1 (regex-based) PII
            detection.
        enable_pii_statistical_detection: Activates Layer 2 (statistical)
            PII detection.
        enable_pii_ml_detection: Activates Layer 3 (ML-based) PII detection.
            Off by default.
        enable_skill_performance_monitoring: Enables ADR-0002 skill
            performance monitoring and automatic improvement proposals.
        enable_user_skill_registration: Allows users to register new User
            Skills via the SkillLifecycle process.
        active_ai_provider: Identifier of the default AI provider
            (e.g., ``"anthropic"``, ``"openai"``, ``"google_gemini"``).
    """

    model_config = SettingsConfigDict(
        env_prefix="CIE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Storage
    # -------------------------------------------------------------------------
    database_filepath: str = Field(
        default_factory=_default_database_filepath,
        description="Absolute path to the SQLite database file.",
    )
    workspace_directory: str = Field(
        default_factory=_default_workspace_directory,
        description="Absolute path to the active workspace directory.",
    )

    # -------------------------------------------------------------------------
    # Platform behaviour
    # -------------------------------------------------------------------------
    offline_first_mode: bool = Field(
        default=True,
        description=(
            "When True, the platform operates without requiring internet access "
            "(AP-012 Offline Capability)."
        ),
    )
    default_ui_language: str = Field(
        default="ja",
        description="BCP-47 language tag for the default UI language.",
    )

    # -------------------------------------------------------------------------
    # Evaluation gateways
    # -------------------------------------------------------------------------
    global_minimum_pass_score: int = Field(
        default=90,
        ge=0,
        le=100,
        description="Minimum evaluation pass score (0–100). Outputs below this are rejected.",
    )

    # -------------------------------------------------------------------------
    # Feature flags — PII detection layers
    # -------------------------------------------------------------------------
    enable_pii_regex_guardrail: bool = Field(
        default=True,
        description="Activate Layer 1 (regex-based) PII detection guardrail.",
    )
    enable_pii_statistical_detection: bool = Field(
        default=True,
        description="Activate Layer 2 (statistical) PII detection.",
    )
    enable_pii_ml_detection: bool = Field(
        default=False,
        description="Activate Layer 3 (ML-based) PII detection. Off by default.",
    )

    # -------------------------------------------------------------------------
    # Feature flags — Skills (ADR-0002)
    # -------------------------------------------------------------------------
    enable_skill_performance_monitoring: bool = Field(
        default=True,
        description="Enable ADR-0002 skill performance monitoring.",
    )
    enable_user_skill_registration: bool = Field(
        default=True,
        description="Allow registration of new User Skills (requires human approval).",
    )

    # -------------------------------------------------------------------------
    # AI provider
    # -------------------------------------------------------------------------
    active_ai_provider: str = Field(
        default="anthropic",
        description=(
            "Identifier of the active AI provider. Must be one of the providers "
            "declared in spec/configuration.yaml (AP-007 AI Provider Independence)."
        ),
    )

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------

    @field_validator("active_ai_provider")
    @classmethod
    def _validate_ai_provider(cls, value: str) -> str:
        """Ensure the provider is one of the known supported identifiers.

        Args:
            value: Raw provider string from configuration or environment.

        Returns:
            The validated provider string (unchanged).

        Raises:
            ValueError: If the provider is not in the supported list.
        """
        known_providers = {"anthropic", "openai", "google_gemini", "local_ollama"}
        if value not in known_providers:
            raise ValueError(
                f"Unknown AI provider '{value}'. "
                f"Supported values: {sorted(known_providers)}"
            )
        return value

    @field_validator("default_ui_language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        """Normalise the language tag to lowercase.

        Args:
            value: Raw language string from configuration or environment.

        Returns:
            Lowercase language tag string.
        """
        return value.lower()

    # -------------------------------------------------------------------------
    # Factory class method
    # -------------------------------------------------------------------------

    @classmethod
    def load_from_yaml(cls, path: str) -> "CIEConfig":
        """Load configuration from a YAML file.

        The YAML file is parsed and its ``platform_environment``,
        ``feature_flags``, and ``evaluation_gateways`` sections are flattened
        into the field namespace expected by :class:`CIEConfig`.

        Args:
            path: Absolute or relative path to the YAML configuration file
                (e.g., ``"spec/configuration.yaml"``).

        Returns:
            A fully validated :class:`CIEConfig` instance.

        Raises:
            FileNotFoundError: If the file does not exist at the given path.
            ValueError: If the YAML is malformed or contains invalid values.

        Example:
            >>> config = CIEConfig.load_from_yaml("spec/configuration.yaml")
            >>> config.active_ai_provider
            'anthropic'
        """
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {yaml_path.resolve()}"
            )

        with yaml_path.open(encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        overrides: dict[str, Any] = {}

        # spec/configuration.yaml → platform_environment
        env_section: dict[str, Any] = raw.get("platform_environment", {})
        storage: dict[str, Any] = env_section.get("storage_locations", {})

        if "offline_first_mode" in env_section:
            overrides["offline_first_mode"] = env_section["offline_first_mode"]
        if "default_ui_language" in env_section:
            overrides["default_ui_language"] = env_section["default_ui_language"]
        if "database_filepath" in storage:
            overrides["database_filepath"] = _resolve_path_template(
                storage["database_filepath"]
            )
        if "workspace_directory" in storage:
            overrides["workspace_directory"] = _resolve_path_template(
                storage["workspace_directory"]
            )

        # spec/configuration.yaml → ai_provider_abstraction
        ai_section: dict[str, Any] = raw.get("ai_provider_abstraction", {})
        if "active_default_provider" in ai_section:
            overrides["active_ai_provider"] = ai_section["active_default_provider"]

        # spec/configuration.yaml → evaluation_gateways
        eval_section: dict[str, Any] = raw.get("evaluation_gateways", {})
        if "global_minimum_pass_score" in eval_section:
            overrides["global_minimum_pass_score"] = eval_section[
                "global_minimum_pass_score"
            ]

        # spec/configuration.yaml → feature_flags
        flags: dict[str, Any] = raw.get("feature_flags", {})
        flag_mapping: dict[str, str] = {
            "enable_pii_regex_guardrail": "enable_pii_regex_guardrail",
            "enable_pii_statistical_detection": "enable_pii_statistical_detection",
            "enable_pii_ml_detection": "enable_pii_ml_detection",
            "enable_skill_performance_monitoring": "enable_skill_performance_monitoring",
            "enable_user_skill_registration": "enable_user_skill_registration",
        }
        for yaml_key, field_name in flag_mapping.items():
            if yaml_key in flags:
                overrides[field_name] = flags[yaml_key]

        return cls(**overrides)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_path_template(template: str) -> str:
    """Expand ``${USER_DOCUMENTS}`` and ``${OS_TEMP}`` placeholders.

    Args:
        template: Path string potentially containing ``${...}`` placeholders.

    Returns:
        Resolved absolute path string.
    """
    docs_dir = _default_documents_dir()
    temp_dir = os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))

    result = template.replace("${USER_DOCUMENTS}", docs_dir)
    result = result.replace("${OS_TEMP}", temp_dir)
    return result


__all__: list[str] = [
    "CIEConfig",
]
