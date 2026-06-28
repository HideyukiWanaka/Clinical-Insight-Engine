"""CIE Platform — PII Detection Layer 2 (statistical anomaly detection).

Implements 4 statistical heuristic signals defined in
``architecture/security-pii-filter.md`` Section 4.

Inputs are exclusively ``ColumnMetadata`` fields from
``schemas/dataset.schema.json`` and the dataset ``row_count``.
Raw data row values are **never** accessed (DQ-001 rule; agent.schema.json
``inject_raw_data_rows = const: false``).

Layer 2 limitations (Section 4.3) are accepted as design trade-offs:
false positives and false negatives cannot be eliminated by statistical
heuristics alone.  Human review provides the final safety net.
"""

from __future__ import annotations

from cie.schemas.payloads import ColumnMetadata
from cie.security.pii_detector import PIIFinding


class PIIDetectorLayer2:
    """Statistical heuristic PII detector.

    Operates on aggregated ``ColumnMetadata`` + dataset ``row_count`` only.
    Four signals are checked in order; each fires independently.
    """

    def detect(
        self,
        col_meta: ColumnMetadata,
        row_count: int,
    ) -> list[PIIFinding]:
        """Run all Layer 2 signals against a single column.

        Args:
            col_meta: Structural metadata for the column.  The ``summary_stats``
                field may be ``None`` when not yet computed; signals that
                require it are silently skipped.
            row_count: Total number of rows in the dataset.  When 0 all
                signals are skipped to avoid ``ZeroDivisionError``.

        Returns:
            List of :class:`~cie.security.pii_detector.PIIFinding` for every
            signal that fired.  Empty list when no anomaly is detected.
        """
        if row_count == 0:
            return []

        findings: list[PIIFinding] = []
        stats: dict | None = col_meta.summary_stats
        unique_count: int | None = stats.get("unique_count") if stats is not None else None
        inferred_type: str = col_meta.inferred_type
        top_cats: list[dict] = stats.get("top_categories", []) if stats is not None else []

        # ------------------------------------------------------------------
        # Signal 1: L2-HIGH-UNIQUENESS
        # Condition: inferred_type ∈ {text, unknown}
        #            AND unique_count / row_count > 0.95
        # ------------------------------------------------------------------
        if unique_count is not None and inferred_type in ("text", "unknown"):
            uniqueness_ratio = unique_count / row_count
            if uniqueness_ratio > 0.95:
                findings.append(
                    PIIFinding(
                        layer=2,
                        signal_id="L2-HIGH-UNIQUENESS",
                        pattern_id=None,
                        severity="CRITICAL",
                        target_type="column_name",
                        matched_text=col_meta.var_n,
                        description=(
                            f"列 {col_meta.var_n}: ユニーク率 {uniqueness_ratio:.1%}。"
                            "患者IDまたは識別子の可能性があります。"
                            f" [unique_count={unique_count},"
                            f" row_count={row_count},"
                            f" inferred_type={inferred_type}]"
                        ),
                    )
                )

        # ------------------------------------------------------------------
        # Signal 2: L2-DATE-TYPE
        # Condition: inferred_type == "date"
        # ------------------------------------------------------------------
        if inferred_type == "date":
            findings.append(
                PIIFinding(
                    layer=2,
                    signal_id="L2-DATE-TYPE",
                    pattern_id=None,
                    severity="WARNING",
                    target_type="column_name",
                    matched_text=col_meta.var_n,
                    description=(
                        f"列 {col_meta.var_n}: 日付型列を検出。"
                        "生年月日など個人特定につながる可能性があります。"
                    ),
                )
            )

        # ------------------------------------------------------------------
        # Signal 3: L2-FIXED-LENGTH-NUMERIC
        # Condition: top_categories labels are all digits
        #            AND all the same length
        #            AND 8 <= length <= 12
        #            AND sample_count >= 3
        # ------------------------------------------------------------------
        if top_cats:
            digit_labels = [
                str(c.get("label", ""))
                for c in top_cats
                if str(c.get("label", "")).isdigit()
            ]
            if len(digit_labels) >= 3:
                label_lengths = [len(lb) for lb in digit_labels]
                if len(set(label_lengths)) == 1 and 8 <= label_lengths[0] <= 12:
                    findings.append(
                        PIIFinding(
                            layer=2,
                            signal_id="L2-FIXED-LENGTH-NUMERIC",
                            pattern_id=None,
                            severity="CRITICAL",
                            target_type="column_name",
                            matched_text=col_meta.var_n,
                            description=(
                                f"列 {col_meta.var_n}: {label_lengths[0]}桁の固定長数字。"
                                "保険証番号・施設IDの可能性があります。"
                                f" [label_length={label_lengths[0]},"
                                f" sample_count={len(digit_labels)}]"
                            ),
                        )
                    )

        # ------------------------------------------------------------------
        # Signal 4: L2-HIGH-UNIQUENESS-CONTINUOUS
        # Condition: inferred_type == "continuous"
        #            AND unique_count / row_count > 0.99
        # ------------------------------------------------------------------
        if unique_count is not None and inferred_type == "continuous":
            uniqueness_ratio = unique_count / row_count
            if uniqueness_ratio > 0.99:
                findings.append(
                    PIIFinding(
                        layer=2,
                        signal_id="L2-HIGH-UNIQUENESS-CONTINUOUS",
                        pattern_id=None,
                        severity="WARNING",
                        target_type="column_name",
                        matched_text=col_meta.var_n,
                        description=(
                            "連続値の高ユニーク率（個人測定値の可能性）"
                            f" [unique_count={unique_count},"
                            f" row_count={row_count},"
                            f" uniqueness_ratio={uniqueness_ratio:.3f}]"
                        ),
                    )
                )

        return findings
