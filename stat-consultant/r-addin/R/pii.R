# PII detection for the environment scan (Step 7) — Addin-side exclusion.
#
# R port (SPEC §11 "翻案") of cie/security/pii_detector.py::PIIDetectorLayer1 +
# cie/security/pii_patterns.py. Kept byte-for-byte in step with the backend's
# app/pii.py so both layers agree (SPEC §9.2: exclude Addin-side before send,
# double-check backend-side).
#
# Only column *names* and aggregated category *level labels* are inspected —
# never raw cell values. The labels inspected here are computed locally and are
# NEVER sent to the backend (only distinct counts + anonymised group sizes are);
# this value check exists so a column whose labels look like PII is dropped
# wholesale before send. A column is dropped when its name trips a name pattern
# OR any level label trips a value pattern.

# Column-name patterns — matched unanchored, case-insensitive (mirrors Python
# re.search + re.IGNORECASE). perl = TRUE so the \s / \b classes behave as PCRE.
.PII_NAME_PATTERNS <- c(
  # 日本語姓名
  "(氏名|患者名|名前|氏　名|患者氏名|受診者名|姓名|フルネーム|名前フリガナ|氏名カナ)",
  # 患者・症例ID
  paste0(
    "(患者\\s*[Ii][Dd]|patient\\s*id|カルテ\\s*番号|症例\\s*[Nn][Oo]|",
    "受診\\s*者\\s*[Ii][Dd]|ID番号|識別\\s*番号|受付\\s*番号|",
    "\\b[Pp]atient[_\\s]?[Nn]o\\b|\\b[Cc]ase[_\\s]?[Ii][Dd]\\b)"
  ),
  # 生年月日
  "(生年月日|誕生日|birth\\s*date|dob|date_of_birth|生\\s*年\\s*月\\s*日|birthdate|出生年月日)",
  # 電話番号
  "(電話\\s*番号|携帯\\s*番号|phone|tel\\b|telephone|連絡先\\s*電話|mobile|携帯電話)",
  # 住所・郵便番号
  "(住所|address|郵便\\s*番号|postal_code|zip\\s*code|居住地|在住|自宅)",
  # メールアドレス
  "(メール\\s*アドレス|email|e-mail|mail\\s*address|電子メール)",
  # 医療機関固有ID（日本）
  "(保険\\s*証\\s*番号|被保険者\\s*番号|健康保険\\s*番号|マイナンバー|個人\\s*番号|基礎年金番号)",
  # 年齢（詳細） — WARNING in source; still excluded (identifiable detail)
  "(年齢\\s*詳細|exact\\s*age|正確な年齢|生まれ年|出生年)",
  # 自由記述欄 — WARNING in source; names often leak into free text
  paste0(
    "(備考|コメント|メモ|自由\\s*記載|備考欄|note|memo|comment|remarks|",
    "free\\s*text|その他\\s*特記|特記\\s*事項)"
  ),
  # English identifier columns (adaptation, not in the source — see app/pii.py).
  # Person-name prefixes only, so "drug_name"/"gene_name"/"file_name" pass.
  "\\b(patient|full|first|last|sur|given|family)[_\\s]?name\\b",
  "\\b(patient|case|subject|record|study)[_\\s]?(id|no)\\b",
  "\\bmrn\\b"
)

# Value patterns — matched against level labels, anchored + case-sensitive
# (mirrors the source's category_label entries, compiled without IGNORECASE).
.PII_VALUE_PATTERNS <- c(
  "^(\\+?81[-\\s]?|0)\\d{1,4}[-\\s]?\\d{1,4}[-\\s]?\\d{4}$",  # phone
  "^[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}$"      # email
)

# TRUE if col_name matches any column-name PII pattern.
column_name_is_pii <- function(col_name) {
  any(vapply(
    .PII_NAME_PATTERNS,
    function(p) grepl(p, col_name, perl = TRUE, ignore.case = TRUE),
    logical(1)
  ))
}

# TRUE if any level label is a phone/email-shaped value.
levels_are_pii <- function(level_labels) {
  if (length(level_labels) == 0) {
    return(FALSE)
  }
  for (p in .PII_VALUE_PATTERNS) {
    if (any(grepl(p, level_labels, perl = TRUE))) {
      return(TRUE)
    }
  }
  FALSE
}

# Whole-column PII decision (SPEC §9.2): drop the entire column (type +
# n_missing + levels) when the name or any level label trips a pattern.
column_has_pii <- function(col_name, level_labels = character(0)) {
  column_name_is_pii(col_name) || levels_are_pii(level_labels)
}
