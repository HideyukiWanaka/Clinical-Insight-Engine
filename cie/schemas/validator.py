"""CIE Platform — JSON Schema registry and payload validator.

Every payload crossing component boundaries is validated here against the
registered JSON Schema definitions (PROJECT_RULES.md Section 13).

Schemas are loaded once at startup from ``schemas/`` and cached in memory
for the lifetime of the process (no per-call disk I/O).
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from cie.core.exceptions import SchemaValidationError


class SchemaRegistry:
    """In-memory cache of all CIE JSON Schema definitions.

    Schemas are keyed by their ``$id`` value (e.g.
    ``"cie://schemas/dataset.schema.json"``).  All agent-to-agent payloads
    must be validated through this registry before dispatch.
    """

    def __init__(self, schema_dir: Path) -> None:
        """Load all ``*.schema.json`` files from *schema_dir* into memory.

        Args:
            schema_dir: Directory containing the JSON Schema files.
        """
        self._schemas: dict[str, dict] = {}
        for schema_file in sorted(schema_dir.glob("*.schema.json")):
            with schema_file.open(encoding="utf-8") as fh:
                schema = json.load(fh)
            schema_id: str | None = schema.get("$id")
            if schema_id:
                self._schemas[schema_id] = schema

    def get_schema(self, schema_ref: str) -> dict:
        """Return the schema registered under *schema_ref*.

        Args:
            schema_ref: Schema URI, e.g. ``"cie://schemas/dataset.schema.json"``.

        Returns:
            The raw schema dict.

        Raises:
            SchemaValidationError: With error code ``SCHEMA_NOT_FOUND`` when
                *schema_ref* is not registered.
        """
        schema = self._schemas.get(schema_ref)
        if schema is None:
            raise SchemaValidationError(
                "SCHEMA_NOT_FOUND",
                schema_id=schema_ref,
            )
        return schema

    def validate(self, payload: dict, schema_ref: str) -> None:
        """Validate *payload* against the schema identified by *schema_ref*.

        Uses ``Draft202012Validator`` so ``additionalProperties: false``
        violations are detected automatically.

        Args:
            payload: The data payload to validate.
            schema_ref: Schema URI used to look up the validator.

        Raises:
            SchemaValidationError: With error code ``SCHEMA_VALIDATION_FAILED``
                when validation fails.  The ``validation_errors`` attribute
                contains the individual error messages from jsonschema.
        """
        schema = self.get_schema(schema_ref)
        validator = Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        if errors:
            raise SchemaValidationError(
                "SCHEMA_VALIDATION_FAILED",
                schema_id=schema_ref,
                validation_errors=[e.message for e in errors],
            )

    def validate_agent_output(
        self,
        agent_id: str,
        payload: dict,
        output_schema_ref: str,
    ) -> None:
        """Validate an agent output payload, embedding the agent ID in any error.

        Thin wrapper around :meth:`validate` that enriches the error message
        with *agent_id* so failures can be correlated to the producing agent.

        Args:
            agent_id: Canonical agent identifier (e.g. ``"data-quality"``).
            payload: The agent output payload to validate.
            output_schema_ref: Schema URI for the expected output contract.

        Raises:
            SchemaValidationError: Propagated from :meth:`validate` with
                *agent_id* included in the error message.
        """
        try:
            self.validate(payload, output_schema_ref)
        except SchemaValidationError as exc:
            raise SchemaValidationError(
                f"SCHEMA_VALIDATION_FAILED (agent={agent_id})",
                schema_id=exc.schema_id,
                validation_errors=exc.validation_errors,
            ) from exc


def load_registry(schema_dir: Path | None = None) -> SchemaRegistry:
    """Construct a :class:`SchemaRegistry` from the project ``schemas/`` directory.

    Args:
        schema_dir: Path to the directory containing ``*.schema.json`` files.
            Defaults to ``<project_root>/schemas/`` when ``None``.

    Returns:
        A populated :class:`SchemaRegistry` instance.
    """
    if schema_dir is None:
        schema_dir = Path(__file__).parent.parent.parent / "schemas"
    return SchemaRegistry(schema_dir)
