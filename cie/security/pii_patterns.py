"""CIE Platform — Layer 1 PII pattern definitions.

Pattern definitions are transcribed verbatim from
``architecture/security-pii-filter.md`` Section 3.2.

Patterns without a ``"target"`` key apply to column names.
Patterns with ``"target": "category_label"`` apply to
``SummaryStats.top_categories[].label`` values only.

Raw data row values are never passed to this module.
``inject_raw_data_rows = const: false`` (agent.schema.json) provides the
architectural guarantee; this module operates only on structural metadata.
"""

from __future__ import annotations

import re

PII_PATTERNS: dict[str, dict] = {
    # --- 日本語姓名 ---
    "jp_full_name": {
        "pattern": re.compile(
            r"(氏名|患者名|名前|氏　名|患者氏名|受診者名|"
            r"姓名|フルネーム|名前フリガナ|氏名カナ)",
            re.IGNORECASE,
        ),
        "severity": "CRITICAL",
        "description": "患者氏名を示す列名パターン",
    },

    # --- 患者・症例ID ---
    "patient_id": {
        "pattern": re.compile(
            r"(患者\s*[Ii][Dd]|patient\s*id|カルテ\s*番号|"
            r"症例\s*[Nn][Oo]|受診\s*者\s*[Ii][Dd]|"
            r"ID番号|識別\s*番号|受付\s*番号|"
            r"\b[Pp]atient[_\s]?[Nn]o\b|\b[Cc]ase[_\s]?[Ii][Dd]\b)",
            re.IGNORECASE,
        ),
        "severity": "CRITICAL",
        "description": "患者・症例識別子を示す列名パターン",
    },

    # --- 生年月日・年齢（詳細） ---
    "birth_date": {
        "pattern": re.compile(
            r"(生年月日|誕生日|birth\s*date|dob|date_of_birth|"
            r"生\s*年\s*月\s*日|birthdate|出生年月日)",
            re.IGNORECASE,
        ),
        "severity": "CRITICAL",
        "description": "生年月日を示す列名パターン",
    },

    # --- 電話番号 ---
    "phone_number": {
        "pattern": re.compile(
            r"(電話\s*番号|携帯\s*番号|phone|tel\b|telephone|"
            r"連絡先\s*電話|mobile|携帯電話)",
            re.IGNORECASE,
        ),
        "severity": "CRITICAL",
        "description": "電話番号を示す列名パターン",
    },

    # --- 住所・郵便番号 ---
    "address": {
        "pattern": re.compile(
            r"(住所|address|郵便\s*番号|postal_code|zip\s*code|"
            r"居住地|在住|自宅)",
            re.IGNORECASE,
        ),
        "severity": "CRITICAL",
        "description": "住所・位置情報を示す列名パターン",
    },

    # --- メールアドレス ---
    "email": {
        "pattern": re.compile(
            r"(メール\s*アドレス|email|e-mail|mail\s*address|"
            r"電子メール)",
            re.IGNORECASE,
        ),
        "severity": "CRITICAL",
        "description": "メールアドレスを示す列名パターン",
    },

    # --- 医療機関固有ID（日本） ---
    "medical_id_jp": {
        "pattern": re.compile(
            r"(保険\s*証\s*番号|被保険者\s*番号|健康保険\s*番号|"
            r"マイナンバー|個人\s*番号|基礎年金番号)",
            re.IGNORECASE,
        ),
        "severity": "CRITICAL",
        "description": "日本の医療・社会保障IDを示す列名パターン",
    },

    # --- カテゴリ値の正規表現（top_categories.label対象）---
    "value_phone_pattern": {
        "pattern": re.compile(
            r"^(\+?81[-\s]?|0)\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4}$"
        ),
        "severity": "CRITICAL",
        "target": "category_label",
        "description": "電話番号形式の値パターン",
    },
    "value_email_pattern": {
        "pattern": re.compile(
            r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
        ),
        "severity": "CRITICAL",
        "target": "category_label",
        "description": "メールアドレス形式の値パターン",
    },

    # --- 警告レベル（要確認・自動マスキング対象）---
    "age_detail": {
        "pattern": re.compile(
            r"(年齢\s*詳細|exact\s*age|正確な年齢|生まれ年|出生年)",
            re.IGNORECASE,
        ),
        "severity": "WARNING",
        "description": "詳細な年齢情報を示す列名（5歳階級への粗化を推奨）",
    },
    "free_text": {
        "pattern": re.compile(
            r"(備考|コメント|メモ|自由\s*記載|備考欄|note|comment|"
            r"remarks|free\s*text|その他\s*特記|特記\s*事項)",
            re.IGNORECASE,
        ),
        "severity": "WARNING",
        "description": "自由記述欄（氏名等が混入するリスクが高い）",
    },
}
