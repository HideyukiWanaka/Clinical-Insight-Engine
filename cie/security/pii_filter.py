"""CIE Platform — Unified PII filter (Layer 1 + Layer 2).

:class:`PIIFilter` is the single entry point for all PII scanning within
the Data Quality Agent pipeline.  It orchestrates Layer 1 (regex) and
Layer 2 (statistical) detection and partitions results into critical and
warning buckets ready for the caller to act on.

Application timings (``architecture/security-pii-filter.md`` Section 6):

* **Timing 1** — before Planner Agent input: use :meth:`PIIFilter.run_on_prompt`.
* **Timing 3** — Data Quality Agent column scan: use :meth:`PIIFilter.run`.
"""

from __future__ import annotations

from cie.schemas.payloads import ColumnMetadata
from cie.security.pii_detector import PIIDetectorLayer1, PIIFinding
from cie.security.pii_detector_layer2 import PIIDetectorLayer2


class PIIFilter:
    """Orchestrates Layer 1 and Layer 2 PII detection for a single column.

    Args:
        enable_layer2: When ``False`` only Layer 1 (regex) runs.  Useful for
            lightweight scans at timing 1 / timing 2 where statistical
            metadata is not yet available.
    """

    def __init__(self, enable_layer2: bool = True) -> None:
        self._layer1 = PIIDetectorLayer1()
        self._layer2 = PIIDetectorLayer2() if enable_layer2 else None

    def run(
        self,
        col_name: str,
        col_meta: ColumnMetadata,
        row_count: int,
    ) -> tuple[list[PIIFinding], list[PIIFinding]]:
        """Scan a single column with Layer 1 + optional Layer 2.

        Layer 1 is applied to *col_name* and to any ``top_categories`` labels
        present in ``col_meta.summary_stats``.

        Layer 2 is applied to the full ``ColumnMetadata`` + ``row_count``
        (only when ``enable_layer2=True``).

        Args:
            col_name: Original column name before var_n aliasing.
            col_meta: Structural metadata for the column from
                ``dataset.schema.json``.  Raw row values are never included.
            row_count: Total dataset row count from ``DatasetMetadata``.

        Returns:
            A tuple ``(critical_findings, warning_findings)`` where each
            element is a list of :class:`~cie.security.pii_detector.PIIFinding`.
        """
        all_findings: list[PIIFinding] = []

        # Layer 1 — column name
        top_cats: list[dict] = (
            col_meta.summary_stats.get("top_categories", [])
            if col_meta.summary_stats is not None
            else []
        )
        all_findings.extend(self._layer1.detect(col_name, top_cats or None))

        # Layer 2 — statistical signals
        if self._layer2 is not None:
            all_findings.extend(self._layer2.detect(col_meta, row_count))

        critical = [f for f in all_findings if f.severity == "CRITICAL"]
        warnings = [f for f in all_findings if f.severity == "WARNING"]
        return critical, warnings

    def run_on_prompt(self, prompt_text: str) -> list[PIIFinding]:
        """Check a natural language prompt for PII patterns (Timing 1).

        Applies only the column-name regex patterns from Layer 1 to the
        full prompt string.  This guards against the user inadvertently
        including patient names or IDs in the research question they type.

        Args:
            prompt_text: The raw user natural language prompt, before it is
                passed to the Planner Agent.

        Returns:
            List of :class:`~cie.security.pii_detector.PIIFinding`.  An empty
            list means no PII signal was detected in the prompt.
        """
        return self._layer1.detect_column_name(prompt_text)
