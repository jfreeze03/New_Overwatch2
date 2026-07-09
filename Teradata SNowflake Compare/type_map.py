"""Canonical type buckets.

Cross-platform type comparison is meaningless at the literal level
(Teradata 'CV' vs Snowflake 'TEXT'), so both sides are mapped into
canonical buckets and the buckets are compared. A bucket match with a
precision note is a PASS-with-note; a bucket mismatch is a FAIL.
"""

# Teradata DBC.ColumnsV.ColumnType codes -> bucket
TERADATA_TYPE_BUCKETS = {
    "CF": "STRING",   # CHAR
    "CV": "STRING",   # VARCHAR
    "CO": "STRING",   # CLOB
    "JN": "VARIANT",  # JSON
    "I1": "INTEGER",  # BYTEINT
    "I2": "INTEGER",  # SMALLINT
    "I":  "INTEGER",  # INTEGER
    "I8": "INTEGER",  # BIGINT
    "D":  "DECIMAL",  # DECIMAL/NUMERIC
    "N":  "DECIMAL",  # NUMBER
    "F":  "FLOAT",    # FLOAT/REAL/DOUBLE
    "DA": "DATE",
    "AT": "TIME",
    "TZ": "TIME",     # TIME WITH TZ
    "TS": "TIMESTAMP",
    "SZ": "TIMESTAMP_TZ",  # TIMESTAMP WITH TZ
    "BO": "BINARY",   # BLOB
    "BF": "BINARY",   # BYTE
    "BV": "BINARY",   # VARBYTE
    "PD": "DATE",     # PERIOD(DATE) — flag manually
    "PT": "TIMESTAMP",
    "PS": "TIMESTAMP",
    "PM": "TIMESTAMP",
    "YR": "INTERVAL", "YM": "INTERVAL", "MO": "INTERVAL", "DY": "INTERVAL",
    "DH": "INTERVAL", "DM": "INTERVAL", "DS": "INTERVAL", "HR": "INTERVAL",
    "HM": "INTERVAL", "HS": "INTERVAL", "MI": "INTERVAL", "MS": "INTERVAL",
    "SC": "INTERVAL",
    "XM": "VARIANT",  # XML
}

# Snowflake INFORMATION_SCHEMA.COLUMNS.DATA_TYPE -> bucket
SNOWFLAKE_TYPE_BUCKETS = {
    "TEXT": "STRING",
    "NUMBER": "DECIMAL",     # refined to INTEGER below when scale = 0
    "FLOAT": "FLOAT",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIMESTAMP_NTZ": "TIMESTAMP",
    "TIMESTAMP_LTZ": "TIMESTAMP_TZ",
    "TIMESTAMP_TZ": "TIMESTAMP_TZ",
    "BINARY": "BINARY",
    "VARIANT": "VARIANT",
    "OBJECT": "VARIANT",
    "ARRAY": "VARIANT",
    "GEOGRAPHY": "VARIANT",
}

# Buckets considered interchangeable (bucket-level PASS with note)
COMPATIBLE_BUCKETS = {
    frozenset({"INTEGER", "DECIMAL"}),    # TD INT often lands as NUMBER(38,0)
    frozenset({"TIMESTAMP", "TIMESTAMP_TZ"}),
    frozenset({"INTERVAL", "STRING"}),    # intervals usually migrated as VARCHAR
}


def td_bucket(column_type: str) -> str:
    return TERADATA_TYPE_BUCKETS.get((column_type or "").strip(), f"UNKNOWN({column_type})")


def sf_bucket(data_type: str, numeric_scale) -> str:
    b = SNOWFLAKE_TYPE_BUCKETS.get((data_type or "").strip().upper(), f"UNKNOWN({data_type})")
    if b == "DECIMAL" and numeric_scale in (0, "0"):
        return "INTEGER"
    return b


def buckets_match(td_b: str, sf_b: str) -> str:
    """Return 'MATCH', 'COMPATIBLE', or 'MISMATCH'."""
    if td_b == sf_b:
        return "MATCH"
    if frozenset({td_b, sf_b}) in COMPATIBLE_BUCKETS:
        return "COMPATIBLE"
    return "MISMATCH"
