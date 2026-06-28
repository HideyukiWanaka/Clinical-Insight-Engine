"""CIE Platform — Core package.

Exports the primary public API of :mod:`cie.core`:
- :class:`~cie.core.config.CIEConfig` — runtime configuration.
- Exception classes from :mod:`cie.core.exceptions`.
"""

from cie.core.config import CIEConfig
from cie.core.exceptions import (
    AgentError,
    CIEError,
    HumanApprovalRequiredError,
    PIIDetectedError,
    PermissionDeniedError,
    RuntimeExecutionError,
    SchemaValidationError,
    SecurityViolationError,
    SkillError,
    WorkflowError,
)

__all__: list[str] = [
    # Config
    "CIEConfig",
    # Exceptions
    "CIEError",
    "SchemaValidationError",
    "PermissionDeniedError",
    "SecurityViolationError",
    "PIIDetectedError",
    "WorkflowError",
    "AgentError",
    "RuntimeExecutionError",
    "SkillError",
    "HumanApprovalRequiredError",
]
