"""CIE Platform — PII Detection Layer 1 (regex / dictionary-based).

Applies the patterns defined in :mod:`cie.security.pii_patterns` to:

1. **Column names** — the original ``df.columns`` values before var_n aliasing.
2. **Category labels** — ``SummaryStats.top_categories[].label`` strings (at
   most 10 per column, per ``dataset.schema.json``).

Raw data row values are **never** passed to this module.
``inject_raw_data_rows = const: false`` (agent.schema.json) is the
architectural guarantee; this module adds an explicit enforcement layer.

Detection results (``PIIFinding``) are collected and returned to the caller.
The caller decides whether to raise ``PIIDetectedError``, log to audit, or
route to the human-approval queue per the flow defined in
``architecture/security-pii-filter.md`` Section 7.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from cie.security.pii_patterns import PII_PATTERNS


@dataclass
class PIIFinding:
    """A single PII detection result from any detection layer.

    Attributes:
        layer: Detection layer that produced this finding (1, 2, or 3).
        pattern_id: Key from ``PII_PATTERNS`` (Layer 1 only; ``None`` for
            statistical or ML findings).
        signal_id: Signal identifier for Layer 2 / Layer 3 findings (e.g.
            ``"L2-HIGH-UNIQUENESS"``); ``None`` for Layer 1.
        severity: ``"CRITICAL"`` blocks pipeline continuation.
            ``"WARNING"`` triggers advisory masking proposals.
        target_type: Whether the match was on a column name or a category value.
        matched_text: For column names the original name is recorded (column
            names are not PII themselves).  For category value matches this
            field is **always** ``"[REDACTED]"`` — the actual value is never
            stored.
        description: Human-readable description of the pattern that fired.
    """

    layer: int
    severity: Literal["CRITICAL", "WARNING"]
    target_type: Literal["column_name", "category_value"]
    matched_text: str
    description: str
    pattern_id: str | None = field(default=None)
    signal_id: str | None = field(default=None)


class PIIDetectorLayer1:
    """Regex-based PII detector for column names and category labels.

    Patterns are loaded once at construction from
    :data:`cie.security.pii_patterns.PII_PATTERNS` (already compiled).
    """

    def __init__(self) -> None:
        self._column_patterns: dict[str, dict] = {
            pid: cfg
            for pid, cfg in PII_PATTERNS.items()
            if cfg.get("target") != "category_label"
        }
        self._label_patterns: dict[str, dict] = {
            pid: cfg
            for pid, cfg in PII_PATTERNS.items()
            if cfg.get("target") == "category_label"
        }

    def detect_column_name(self, col_name: str) -> list[PIIFinding]:
        """Check *col_name* against all column-name PII patterns.

        Args:
            col_name: Original column name from ``df.columns``.

        Returns:
            List of :class:`PIIFinding` for every pattern that matched.
            Empty list when no PII signal is detected.
        """
        findings: list[PIIFinding] = []
        for pattern_id, cfg in self._column_patterns.items():
            if cfg["pattern"].search(col_name):
                findings.append(
                    PIIFinding(
                        layer=1,
                        pattern_id=pattern_id,
                        signal_id=None,
                        severity=cfg["severity"],
                        target_type="column_name",
                        matched_text=col_name,
                        description=cfg["description"],
                    )
                )
        return findings

    def detect_category_labels(
        self,
        top_categories: list[dict],
    ) -> list[PIIFinding]:
        """Check ``top_categories[].label`` values against value PII patterns.

        Args:
            top_categories: List of ``{"label": str, "count": int}`` dicts
                from ``SummaryStats.top_categories``.  Never contains raw row
                data — only aggregated category labels.

        Returns:
            List of :class:`PIIFinding` for every label that matched.
            ``matched_text`` is always ``"[REDACTED]"`` to prevent value
            leakage into audit logs.
        """
        findings: list[PIIFinding] = []
        for cat in top_categories:
            label: str = cat.get("label", "")
            for pattern_id, cfg in self._label_patterns.items():
                if cfg["pattern"].match(label):
                    findings.append(
                        PIIFinding(
                            layer=1,
                            pattern_id=pattern_id,
                            signal_id=None,
                            severity="CRITICAL",
                            target_type="category_value",
                            matched_text="[REDACTED]",
                            description=cfg["description"],
                        )
                    )
        return findings

    def detect(
        self,
        col_name: str,
        top_categories: list[dict] | None = None,
    ) -> list[PIIFinding]:
        """Run full Layer 1 detection for a single column.

        Combines :meth:`detect_column_name` and :meth:`detect_category_labels`.

        Args:
            col_name: Original column name (before var_n aliasing).
            top_categories: Optional list of ``{"label": str, "count": int}``
                dicts.  Omit or pass ``None`` when summary stats are not
                available yet.

        Returns:
            Combined list of :class:`PIIFinding` from both sub-detectors.
        """
        findings = self.detect_column_name(col_name)
        if top_categories:
            findings.extend(self.detect_category_labels(top_categories))
        return findings
