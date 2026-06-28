"""CIE Platform — var_n alias system for patient column name protection.

Column names that may identify patients are replaced with anonymous aliases
(``var_1``, ``var_2``, …) immediately after structural metadata extraction.
The original names are held in a :class:`VarNAliasMap` that is only
accessible to the Security Agent via ``r_code.restore_variables``.

References:
- ``architecture/security-model.md`` — var_n Alias System
- ``architecture/security-pii-filter.md`` — Section 8
- ``spec/permissions.yaml``  — ``r_code.restore_variables`` (security agent only)
"""

from __future__ import annotations

from cie.core.exceptions import CIEError, PermissionDeniedError
from cie.security.capability_token import CapabilityScope, CapabilityToken


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class VarNAlreadyRegisteredError(CIEError):
    """Raised when :meth:`VarNAliasMap.register` is called more than once."""

    error_code: str = "VAR_N_ALREADY_REGISTERED"


class AlreadyRestoredError(CIEError):
    """Raised when :meth:`VarNAliasMap.restore` is called a second time."""

    error_code: str = "ALREADY_RESTORED"


# ---------------------------------------------------------------------------
# VarNAliasMap
# ---------------------------------------------------------------------------


class VarNAliasMap:
    """Maps original column names to ``var_n`` aliases for a single execution.

    Only the Security Agent may call :meth:`restore` — it requires a
    capability token that carries ``r_code.restore_variables`` scope.

    Attributes are private; external code uses the public methods only.
    """

    def __init__(self) -> None:
        self._map: dict[str, str] = {}      # var_n → original_name
        self._reverse: dict[str, str] = {}  # original_name → var_n
        self._locked: bool = False

    def register(self, original_col_names: list[str]) -> dict[str, str]:
        """Assign ``var_1``, ``var_2``, … aliases to *original_col_names*.

        Args:
            original_col_names: Ordered list of original column names from
                ``df.columns``.  Order determines alias numbering.

        Returns:
            Dict mapping ``{var_n: original_name}`` for all registered columns.

        Raises:
            VarNAlreadyRegisteredError: When this map already has registered
                columns (double-registration is not permitted).
        """
        if self._map:
            raise VarNAlreadyRegisteredError(
                "Column aliases are already registered for this execution. "
                "Call register() only once per VarNAliasMap instance."
            )
        for idx, name in enumerate(original_col_names, start=1):
            var_n = f"var_{idx}"
            self._map[var_n] = name
            self._reverse[name] = var_n
        return dict(self._map)

    def get_var_n(self, original_name: str) -> str:
        """Return the ``var_n`` alias for *original_name*.

        Args:
            original_name: The original column name.

        Returns:
            The corresponding ``var_n`` alias (e.g. ``"var_3"``).

        Raises:
            KeyError: When *original_name* has not been registered.
        """
        return self._reverse[original_name]

    def restore(self, token: CapabilityToken) -> dict[str, str]:
        """Return the full ``{var_n: original_name}`` mapping.

        Requires a valid capability token carrying
        :attr:`~cie.security.capability_token.CapabilityScope.R_CODE_RESTORE_VARIABLES`.
        After the first call the map is locked; subsequent calls raise
        :class:`AlreadyRestoredError`.

        Args:
            token: Must carry ``r_code.restore_variables`` scope.
                Only the Security Agent's token can satisfy this requirement.

        Returns:
            A copy of the ``{var_n: original_name}`` mapping.

        Raises:
            PermissionDeniedError: When *token* does not carry the required
                scope.
            AlreadyRestoredError: When ``restore()`` has already been called
                on this instance.
        """
        if self._locked:
            raise AlreadyRestoredError(
                "This alias map has already been restored. "
                "restore() may be called only once per execution."
            )
        token.require_scope(CapabilityScope.R_CODE_RESTORE_VARIABLES)
        self._locked = True
        return dict(self._map)

    def to_proxy_metadata(self) -> dict[str, str]:
        """Return var_n keys with masked values (``"---"``).

        Used by upstream agents that need to know which var_n aliases exist
        but must never see the original column names.

        Returns:
            Dict ``{var_n: "---"}`` for every registered alias.
        """
        return {var_n: "---" for var_n in self._map}


# ---------------------------------------------------------------------------
# AliasStore
# ---------------------------------------------------------------------------


class AliasStore:
    """Manages one :class:`VarNAliasMap` per execution context.

    The Orchestrator calls :meth:`create` when starting an execution and
    :meth:`drop` when it completes to free memory.
    """

    def __init__(self) -> None:
        self._store: dict[str, VarNAliasMap] = {}

    def create(self, execution_id: str) -> VarNAliasMap:
        """Create and register a new :class:`VarNAliasMap` for *execution_id*.

        Args:
            execution_id: Unique execution context identifier.

        Returns:
            The newly created :class:`VarNAliasMap` instance.
        """
        alias_map = VarNAliasMap()
        self._store[execution_id] = alias_map
        return alias_map

    def get(self, execution_id: str) -> VarNAliasMap:
        """Return the :class:`VarNAliasMap` for *execution_id*.

        Args:
            execution_id: Execution context identifier.

        Returns:
            The registered :class:`VarNAliasMap`.

        Raises:
            KeyError: When *execution_id* has no registered map.
        """
        return self._store[execution_id]

    def drop(self, execution_id: str) -> None:
        """Remove the alias map for *execution_id* from memory.

        Args:
            execution_id: Execution context whose map should be deleted.
                No-op if *execution_id* is not registered.
        """
        self._store.pop(execution_id, None)
