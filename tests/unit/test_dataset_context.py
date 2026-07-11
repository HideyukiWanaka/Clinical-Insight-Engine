"""Unit tests for cie.api.dataset.build_dataset_context.

Test matrix:
- test_dataset_structural_metadata_keyed_by_var_n — keys match ^var_[0-9]+$,
  not the raw (e.g. Japanese) column headers.
- test_var_n_alias_map_matches_metadata_keys       — var_n_alias_map covers
  exactly the same var_n set as dataset_structural_metadata, in column order.
- test_dq_columns_original_name_matches_alias_map  — dq_columns[].original_name
  agrees with var_n_alias_map for the same var_n.
- test_empty_csv_bytes_returns_empty_dict           — no upload → {}.
"""

from __future__ import annotations

import re

from cie.api.dataset import build_dataset_context

_VAR_N_RE = re.compile(r"^var_[0-9]+$")

_CSV_BYTES = (
    "収縮期血圧_mmHg,拡張期血圧_mmHg,性別\n"
    "120,80,male\n"
    "130,85,female\n"
).encode("utf-8")


def test_dataset_structural_metadata_keyed_by_var_n(tmp_path) -> None:
    context = build_dataset_context(_CSV_BYTES, workspace_dir=tmp_path)
    metadata = context["dataset_structural_metadata"]

    assert metadata, "expected non-empty structural metadata"
    for key in metadata:
        assert _VAR_N_RE.match(key), f"key {key!r} is not a var_n alias"
    raw_headers = {"収縮期血圧_mmHg", "拡張期血圧_mmHg", "性別"}
    assert not (set(metadata.keys()) & raw_headers)


def test_var_n_alias_map_matches_metadata_keys(tmp_path) -> None:
    context = build_dataset_context(_CSV_BYTES, workspace_dir=tmp_path)
    metadata = context["dataset_structural_metadata"]
    alias_map = context["var_n_alias_map"]

    assert set(metadata.keys()) == set(alias_map.keys())
    assert set(alias_map.values()) == {"収縮期血圧_mmHg", "拡張期血圧_mmHg", "性別"}


def test_dq_columns_original_name_matches_alias_map(tmp_path) -> None:
    context = build_dataset_context(_CSV_BYTES, workspace_dir=tmp_path)
    alias_map = context["var_n_alias_map"]

    for col in context["columns"]:
        assert alias_map[col["var_n"]] == col["original_name"]


def test_empty_csv_bytes_returns_empty_dict(tmp_path) -> None:
    assert build_dataset_context(None, workspace_dir=tmp_path) == {}
