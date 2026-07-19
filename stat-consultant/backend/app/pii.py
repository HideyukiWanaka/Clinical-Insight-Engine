"""PII detection for the environment sync (Step 7) — backend double-check.

Adapted (SPEC §11 "翻案") from ``cie/security/pii_detector.py`` +
``cie/security/pii_patterns.py``. Self-contained: this minimal app does not
import ``cie`` (SPEC §7 — treat ``cie/`` as reference/port source only).

The Addin already excludes PII columns before sending (SPEC §9.2); this module
is the server-side second layer. Only *structural metadata* is ever inspected.
Raw row/cell values — and category level label strings — are never sent to the
backend (the environment schema has no field for them), so the value-pattern
check here runs only when the caller passes labels, which happens Addin-side
(``r-addin/R/pii.R``) before send. Server-side, only the **column name** is
available to check.

A column is dropped when its **name** matches a name pattern, or (Addin-side)
any of its **level labels** matches a value pattern (phone/email shaped values).
"""

from __future__ import annotations

import re

# --- Column-name patterns (matched with re.search + IGNORECASE, unanchored) ---
# Transcribed from cie/security/pii_patterns.py (the non-``category_label``
# entries: the CRITICAL identifiers plus the WARNING free-text / age columns).
_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 日本語姓名
    re.compile(
        r"(氏名|患者名|名前|氏　名|患者氏名|受診者名|"
        r"姓名|フルネーム|名前フリガナ|氏名カナ)",
        re.IGNORECASE,
    ),
    # 患者・症例ID
    re.compile(
        r"(患者\s*[Ii][Dd]|patient\s*id|カルテ\s*番号|"
        r"症例\s*[Nn][Oo]|受診\s*者\s*[Ii][Dd]|"
        r"ID番号|識別\s*番号|受付\s*番号|"
        r"\b[Pp]atient[_\s]?[Nn]o\b|\b[Cc]ase[_\s]?[Ii][Dd]\b)",
        re.IGNORECASE,
    ),
    # 生年月日
    re.compile(
        r"(生年月日|誕生日|birth\s*date|dob|date_of_birth|"
        r"生\s*年\s*月\s*日|birthdate|出生年月日)",
        re.IGNORECASE,
    ),
    # 電話番号
    re.compile(
        r"(電話\s*番号|携帯\s*番号|phone|tel\b|telephone|"
        r"連絡先\s*電話|mobile|携帯電話)",
        re.IGNORECASE,
    ),
    # 住所・郵便番号
    re.compile(
        r"(住所|address|郵便\s*番号|postal_code|zip\s*code|居住地|在住|自宅)",
        re.IGNORECASE,
    ),
    # メールアドレス
    re.compile(
        r"(メール\s*アドレス|email|e-mail|mail\s*address|電子メール)",
        re.IGNORECASE,
    ),
    # 医療機関固有ID（日本）
    re.compile(
        r"(保険\s*証\s*番号|被保険者\s*番号|健康保険\s*番号|"
        r"マイナンバー|個人\s*番号|基礎年金番号)",
        re.IGNORECASE,
    ),
    # 年齢（詳細） — WARNING in source; still excluded here (identifiable detail)
    re.compile(r"(年齢\s*詳細|exact\s*age|正確な年齢|生まれ年|出生年)", re.IGNORECASE),
    # 自由記述欄 — WARNING in source; high risk of names leaking into labels
    re.compile(
        r"(備考|コメント|メモ|自由\s*記載|備考欄|note|memo|comment|"
        r"remarks|free\s*text|その他\s*特記|特記\s*事項)",
        re.IGNORECASE,
    ),
    # English identifier columns (adaptation, not in the source). The source
    # patterns target Japanese names, but real datasets and the SPEC §12
    # completion check use English "patient_name"/"patient_id" with "_"
    # separators (which the source's ``\s*`` never matches). Person-name
    # prefixes only, so "drug_name"/"gene_name"/"file_name" pass through.
    re.compile(
        r"\b(patient|full|first|last|sur|given|family)[_\s]?name\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(patient|case|subject|record|study)[_\s]?(id|no)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bmrn\b", re.IGNORECASE),
)

# --- Value patterns (matched against level labels with re.match, anchored,
#     case-sensitive — mirrors the ``category_label`` entries in the source,
#     which are compiled without IGNORECASE). ---
_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(\+?81[-\s]?|0)\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4}$"),  # phone
    re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"),  # email
)


def column_name_is_pii(col_name: str) -> bool:
    """True if *col_name* matches any column-name PII pattern."""
    return any(p.search(col_name) for p in _NAME_PATTERNS)


def level_label_is_pii(label: str) -> bool:
    """True if *label* (an aggregated category level) is a phone/email value."""
    return any(p.match(label) for p in _VALUE_PATTERNS)


def column_has_pii(col_name: str, level_labels: list[str] | None = None) -> bool:
    """Whole-column PII decision (SPEC §9.2).

    Returns True — meaning drop the entire column (name + type + n_missing +
    aggregate summary) — when the column *name* trips a name pattern, or (when
    labels are supplied, i.e. Addin-side) any *level label* trips a value pattern.
    """
    if column_name_is_pii(col_name):
        return True
    if level_labels:
        return any(level_label_is_pii(lbl) for lbl in level_labels)
    return False
