# Python Utilities Reference
# Domain: Python
# Version: 2.0.0
# Status: Stable
# Consumers: runtime, statistics
# Immutable during execution (AP-014)
# Package versions: pandas ≥ 2.0 (pandas 3.0 compatible)
# Source: pandas.pydata.org/docs/whatsnew/v2.0.0, v2.2.0, v3.0.0 (January 2026)

## Purpose

Defines the approved Python package catalogue and implementation patterns
for CIE platform tasks. Python is used for data preprocessing, file format
conversion, metadata extraction, and schema validation — not for primary
statistical analysis (which is R-exclusive).

---

## Role of Python in the CIE Platform

| Role | Owner | Tool |
|------|-------|------|
| Primary statistical analysis | Statistics Agent | R |
| Data preprocessing / cleaning | Data Quality Agent support | Python |
| Dataset structural metadata extraction | Data Quality Agent support | Python |
| File format conversion (CSV → RDS, Excel → CSV) | Runtime Agent | Python |
| Schema validation of JSON payloads | Runtime / Orchestrator | Python |
| Output file management | Runtime Agent | Python |

---

## Approved Package Catalogue

### Data Handling

| Package | Version (min) | Primary use | Key functions |
|---------|--------------|------------|---------------|
| `pandas` | ≥ 2.0 | Tabular data handling | `read_csv()`, `read_excel()`, `DataFrame`, `describe()` |
| `numpy` | ≥ 1.24 | Numerical operations | `array()`, `nanmean()`, `nanstd()` |
| `openpyxl` | ≥ 3.1 | Excel file I/O | Used via `pandas.read_excel()` |

### Statistical Support

| Package | Version (min) | Primary use | Key functions |
|---------|--------------|------------|---------------|
| `scipy` | ≥ 1.11 | Statistical tests (secondary validation only) | `scipy.stats.shapiro()`, `scipy.stats.chi2_contingency()` |

### Schema and Validation

| Package | Version (min) | Primary use |
|---------|--------------|------------|
| `jsonschema` | ≥ 4.19 | JSON schema validation against CIE schemas |
| `pydantic` | ≥ 2.0 | Data model validation and serialization |

### Utilities

| Package | Version (min) | Primary use |
|---------|--------------|------------|
| `hashlib` | stdlib | SHA-256 file hashing for reproducibility |
| `pathlib` | stdlib | Path handling (never hard-coded paths) |
| `json` | stdlib | JSON serialization |
| `logging` | stdlib | Structured logging (PII-safe) |

---

## Dataset Metadata Extraction Pattern

Standard procedure for extracting `dataset_structural_metadata` from uploaded files.
Updated for pandas 2.0+ / 3.0 compatibility (Copy-on-Write, string dtype changes):

```python
import pandas as pd
import numpy as np
import hashlib
import json
from pathlib import Path

def extract_structural_metadata(file_path: str, execution_id: str) -> dict:
    """
    Extracts structural metadata only — never returns row content.
    Conforms to dataset.schema.json metadata_type: proxy_metadata.
    Compatible with pandas 2.0+ and 3.0 (Copy-on-Write default).
    """
    path = Path(file_path)

    # Load with low_memory=False for type inference accuracy
    df = pd.read_csv(path, low_memory=False)

    # Compute file hash for reproducibility audit
    with open(path, "rb") as f:
        file_hash = f"sha256:{hashlib.sha256(f.read()).hexdigest()}"

    columns = []
    for i, col in enumerate(df.columns):
        var_n = f"var_{i + 1}"  # Alias — original name never exposed downstream

        col_data = df[col]
        missing_count = int(col_data.isna().sum())
        missing_rate = round(missing_count / len(df) * 100, 2)

        # Infer statistical type
        # NOTE: Use pd.api.types functions — do NOT check dtype == object
        # (object dtype check breaks in pandas 3.0 where strings → str dtype)
        if pd.api.types.is_numeric_dtype(col_data):
            inferred_type = "continuous"
            not_all_missing = not col_data.isna().all()
            summary = {
                "min":       float(col_data.min())    if not_all_missing else None,
                "max":       float(col_data.max())    if not_all_missing else None,
                "mean":      float(col_data.mean())   if not_all_missing else None,
                "median":    float(col_data.median()) if not_all_missing else None,
                "std_dev":   float(col_data.std())    if not_all_missing else None,
                "unique_count": int(col_data.nunique())
            }
        else:
            # Handles both object dtype (pandas 2.x) and str dtype (pandas 3.0)
            unique_vals = int(col_data.nunique())
            inferred_type = "categorical_binary" if unique_vals == 2 else "categorical_nominal"
            top_cats = col_data.value_counts().head(10)
            summary = {
                "unique_count": unique_vals,
                "top_categories": [
                    {"label": str(k), "count": int(v)}
                    for k, v in top_cats.items()
                ]
            }

        columns.append({
            "var_n":             var_n,
            "inferred_type":     inferred_type,
            "missing_count":     missing_count,
            "missing_rate_pct":  missing_rate,
            "summary_stats":     summary
        })

    return {
        "execution_id":      execution_id,
        "metadata_type":     "proxy_metadata",
        "source_file_hash":  file_hash,
        "row_count":         len(df),
        "column_count":      len(df.columns),
        "columns":           columns
    }
    # Note: var_n_alias_map (original column names) is held securely
    # and NOT included in this output. It is stored separately and
    # accessed only via Security Agent r_code.restore_variables permission.
```

---

## Schema Validation Pattern

```python
import json
import jsonschema
from pathlib import Path

def validate_payload(payload: dict, schema_path: str) -> dict:
    """
    Validates a payload against a CIE JSON schema.
    Returns {"valid": True} or {"valid": False, "errors": [...]}
    """
    schema = json.loads(Path(schema_path).read_text())
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(payload))

    if not errors:
        return {"valid": True}
    return {
        "valid": False,
        "errors": [
            {
                "path": ".".join(str(p) for p in e.absolute_path),
                "message": e.message,
                "schema_path": ".".join(str(p) for p in e.absolute_schema_path)
            }
            for e in errors
        ]
    }
```

---

## Security Rules for Python Scripts

Per spec/runtime.yaml and PROJECT_RULES.md:

| Forbidden pattern | Reason | Alternative |
|------------------|--------|-------------|
| `os.system(...)` | Shell escape | Not permitted |
| `subprocess.run(...)` | Shell execution | Not permitted |
| Hard-coded absolute paths | Breaks reproducibility | Use `pathlib.Path(os.environ["WORKSPACE_DIR"])` |
| `open("/etc/...")` | Denied path | Blocked by filesystem policy |
| `requests.get(...)` | Network access denied | Not permitted |
| `urllib.request.urlopen(...)` | Network access denied | Not permitted |
| Logging raw data values | PII risk | Log only counts and types |
| `df[condition]["col"] = value` | Chained assignment — silently fails in pandas 2.x, error in 3.0 | Use `df.loc[condition, "col"] = value` |
| `df["col"][mask] = value` | Chained assignment | Use `df.loc[mask, "col"] = value` |
| `col_data.dtype == object` for string check | Breaks in pandas 3.0 (str dtype) | Use `pd.api.types.is_string_dtype(col_data)` |
| `df.groupby("cat_col").agg(...)` without `observed=` | FutureWarning in pandas 2.x | Add `observed=True` explicitly |

---

## pandas Version Compatibility (Breaking Changes)

### CRITICAL: pandas 3.0 (January 2026) — Copy-on-Write is now the DEFAULT

In pandas 3.0, every indexing step behaves as a copy. Chained assignment
will no longer work. `SettingWithCopyWarning` is removed and defensive
`.copy()` calls to silence it are no longer needed.

#### Chained Assignment — FORBIDDEN in pandas 3.0+

```python
# WRONG — raises ChainedAssignmentError in pandas 3.0
df[df["group"] == "A"]["value"] = 0          # silently fails
df["col"][df["flag"] == True] = "corrected"   # silently fails

# CORRECT — single-step assignment with .loc
df.loc[df["group"] == "A", "value"] = 0
df.loc[df["flag"] == True, "col"] = "corrected"
```

#### Filtering then modifying — always use .loc

```python
# WRONG — modifies a copy, not the original DataFrame
subset = df[df["missing_rate_pct"] > 20]
subset["flag"] = "critical"   # does NOT modify df

# CORRECT — reassign or use .loc on df directly
df.loc[df["missing_rate_pct"] > 20, "flag"] = "critical"
```

#### Explicit copy when independence is needed

```python
# If you genuinely need an independent copy:
subset = df[df["group"] == "A"].copy()   # explicit copy — safe to modify
subset["new_col"] = "value"              # modifies only subset, not df
```

---

### pandas 3.0 — String dtype change

Starting with pandas 3.0, string columns are inferred as a new `str`
dtype (backed by PyArrow if installed, otherwise NumPy) instead of
`object`. Code that checks `dtype == object` will break.

```python
# WRONG — breaks in pandas 3.0 when string columns become str dtype
if col_data.dtype == object:
    inferred_type = "categorical_nominal"

# CORRECT — use pandas API type checks
import pandas as pd
if pd.api.types.is_string_dtype(col_data):
    inferred_type = "categorical_nominal"
elif pd.api.types.is_numeric_dtype(col_data):
    inferred_type = "continuous"
```

---

### pandas 2.0 — Removed APIs

`Int64Index`, `UInt64Index`, and `Float64Index` were removed in pandas 2.0.
Use `pd.Index` directly instead.

```python
# WRONG — removed in pandas 2.0
pd.Int64Index([1, 2, 3])

# CORRECT
pd.Index([1, 2, 3], dtype="int64")
```

`infer_datetime_format` argument in `read_csv()` and `to_datetime()` is deprecated.
The strict version is now the default — remove this argument entirely.

```python
# WRONG — deprecated, will be removed
df = pd.read_csv(path, infer_datetime_format=True)

# CORRECT
df = pd.read_csv(path)
```

---

### pandas groupby — observed argument for Categoricals

In pandas 3.0, `groupby()` with categorical columns now correctly passes
unobserved groups to aggregation functions across all scenarios.
Always set `observed=True` explicitly to include only observed categories
and suppress `FutureWarning` in pandas 2.x.

```python
# pandas 2.x — triggers FutureWarning if observed not specified
df.groupby("categorical_col").agg({"value": "mean"})

# CORRECT — explicit for both pandas 2.x and 3.0
df.groupby("categorical_col", observed=True).agg({"value": "mean"})
```

---

## Path Handling Standard

```python
import os
from pathlib import Path

# Always use environment variables — never hard-coded paths
workspace_dir = Path(os.environ["WORKSPACE_DIR"])
output_dir    = Path(os.environ["OUTPUT_DIR"])

# Write only to output_dir
output_file = output_dir / "metadata.json"
output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
```

---

## Logging Standard (PII-Safe)

```python
import logging

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cie")

# CORRECT — log only structural information
logger.info(f"Extracted metadata: {len(columns)} columns, {row_count} rows")

# FORBIDDEN — never log cell values or column names
# logger.info(f"Column 'patient_name' has values: {df['patient_name'].tolist()}")
```
