"""Unit tests for cie.schemas.validator.

Test matrix:
- test_valid_dataset_metadata        — valid payload passes without error
- test_invalid_var_n_pattern         — "var_abc" pattern violation raises error
- test_additional_properties_rejected — unknown top-level field raises error
- test_schema_not_found              — unregistered schema_ref raises error
- test_missing_required_field        — missing row_count raises error
- test_metadata_type_enum            — invalid metadata_type value raises error
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from cie.core.exceptions import SchemaValidationError
from cie.schemas.validator import SchemaRegistry, load_registry

DATASET_REF = "cie://schemas/dataset.schema.json"


@pytest.fixture(scope="module")
def registry() -> SchemaRegistry:
    """Shared registry loaded from the project schemas/ directory."""
    return load_registry()


def _valid_dataset() -> dict:
    """Minimal valid dataset.schema.json payload."""
    return {
        "dataset_id": str(uuid.uuid4()),
        "execution_id": str(uuid.uuid4()),
        "metadata_type": "proxy_metadata",
        "row_count": 150,
        "column_count": 2,
        "columns": [
            {
                "var_n": "var_1",
                "inferred_type": "continuous",
                "missing_count": 0,
                "missing_rate_pct": 0.0,
            }
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def test_valid_dataset_metadata(registry: SchemaRegistry) -> None:
    """A well-formed DatasetMetadata payload passes validation without error."""
    registry.validate(_valid_dataset(), DATASET_REF)


def test_invalid_var_n_pattern(registry: SchemaRegistry) -> None:
    """A column var_n that does not match ^var_[0-9]+$ must fail validation."""
    payload = _valid_dataset()
    payload["columns"][0]["var_n"] = "var_abc"
    with pytest.raises(SchemaValidationError) as exc_info:
        registry.validate(payload, DATASET_REF)
    assert exc_info.value.validation_errors, "Expected at least one validation error"


def test_additional_properties_rejected(registry: SchemaRegistry) -> None:
    """An undeclared top-level property is rejected by additionalProperties:false."""
    payload = _valid_dataset()
    payload["undeclared_field"] = "this should not be here"
    with pytest.raises(SchemaValidationError) as exc_info:
        registry.validate(payload, DATASET_REF)
    assert exc_info.value.validation_errors, "Expected additionalProperties violation"


def test_schema_not_found(registry: SchemaRegistry) -> None:
    """Referencing an unregistered schema raises SchemaValidationError(SCHEMA_NOT_FOUND)."""
    with pytest.raises(SchemaValidationError) as exc_info:
        registry.validate({}, "cie://schemas/does-not-exist.schema.json")
    assert "SCHEMA_NOT_FOUND" in str(exc_info.value)


def test_missing_required_field(registry: SchemaRegistry) -> None:
    """Omitting a required field (row_count) must raise SchemaValidationError."""
    payload = _valid_dataset()
    del payload["row_count"]
    with pytest.raises(SchemaValidationError) as exc_info:
        registry.validate(payload, DATASET_REF)
    assert exc_info.value.validation_errors, "Expected missing required field error"


def test_metadata_type_enum(registry: SchemaRegistry) -> None:
    """A metadata_type value outside the allowed enum must fail validation."""
    payload = _valid_dataset()
    payload["metadata_type"] = "raw_data"  # not in ["proxy_metadata", "validated_structural"]
    with pytest.raises(SchemaValidationError) as exc_info:
        registry.validate(payload, DATASET_REF)
    assert exc_info.value.validation_errors, "Expected enum violation error"
