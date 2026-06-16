"""
Teradata -> Snowflake type mapping + TD ColumnType code decoder.

Two jobs:
  1. decode_td_type(): turn DBC.ColumnsV cryptic codes ('CV','I8','DA'...) into
     a normalized canonical type string.
  2. canonical_*: reduce both TD and SF declared types to a small canonical set so
     schema comparison flags REAL mismatches, not cosmetic ones (TD VARCHAR vs SF
     VARCHAR(16777216), TD DECIMAL vs SF NUMBER, etc.).

Canonical buckets: INT, DECIMAL, FLOAT, STRING, DATE, TIME, TIMESTAMP, BOOLEAN,
BINARY, VARIANT, OTHER. Length/precision are compared separately and softly.
"""

# TD DBC.ColumnsV ColumnType -> canonical
TD_TYPE_CODES = {
    "I1": "INT",        # byteint
    "I2": "INT",        # smallint
    "I":  "INT",        # integer
    "I8": "INT",        # bigint
    "D":  "DECIMAL",    # decimal/numeric
    "N":  "DECIMAL",    # number
    "F":  "FLOAT",      # float/real/double
    "DA": "DATE",
    "AT": "TIME",
    "TS": "TIMESTAMP",
    "TZ": "TIME",       # time with zone
    "SZ": "TIMESTAMP",  # timestamp with zone
    "CF": "STRING",     # char fixed
    "CV": "STRING",     # varchar
    "CO": "STRING",     # clob
    "BF": "BINARY",     # byte fixed
    "BV": "BINARY",     # varbyte
    "BO": "BINARY",     # blob
    "JN": "VARIANT",    # json
    "XM": "VARIANT",    # xml
    "PD": "OTHER", "PM": "OTHER", "PS": "OTHER", "PT": "OTHER", "PZ": "OTHER",  # periods
    "YR": "OTHER", "MO": "OTHER", "DY": "OTHER", "HR": "OTHER", "MI": "OTHER", "SC": "OTHER",  # intervals
}

# Recommended SF target for each canonical TD type (informational, shown in UI)
TD_TO_SF_RECOMMENDED = {
    "INT": "NUMBER(38,0)",
    "DECIMAL": "NUMBER(p,s)",
    "FLOAT": "FLOAT",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIMESTAMP": "TIMESTAMP_NTZ",
    "STRING": "VARCHAR",
    "BINARY": "BINARY",
    "VARIANT": "VARIANT",
    "OTHER": "VARCHAR (review manually)",
}


def decode_td_type(code: str) -> str:
    if code is None:
        return "OTHER"
    return TD_TYPE_CODES.get(code.strip().upper(), "OTHER")


def canonical_sf_type(data_type: str) -> str:
    if not data_type:
        return "OTHER"
    t = data_type.strip().upper()
    if t in ("NUMBER", "DECIMAL", "NUMERIC"):
        return "DECIMAL"
    if t in ("INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "BYTEINT"):
        return "INT"
    if t in ("FLOAT", "FLOAT4", "FLOAT8", "DOUBLE", "DOUBLE PRECISION", "REAL"):
        return "FLOAT"
    if t in ("VARCHAR", "CHAR", "CHARACTER", "STRING", "TEXT", "NVARCHAR", "NCHAR"):
        return "STRING"
    if t == "BOOLEAN":
        return "BOOLEAN"
    if t == "DATE":
        return "DATE"
    if t in ("TIME",):
        return "TIME"
    if t.startswith("TIMESTAMP") or t == "DATETIME":
        return "TIMESTAMP"
    if t in ("BINARY", "VARBINARY"):
        return "BINARY"
    if t in ("VARIANT", "OBJECT", "ARRAY"):
        return "VARIANT"
    return "OTHER"


def canonical_sf_number(canonical: str, precision, scale) -> str:
    """SF NUMBER with scale 0 is really an integer; normalize so it can match TD INT."""
    if canonical == "DECIMAL" and (scale in (0, None)):
        return "INT"
    return canonical


# numeric-ish buckets used to decide which aggregates to run in fingerprints
NUMERIC_CANON = {"INT", "DECIMAL", "FLOAT"}
TEMPORAL_CANON = {"DATE", "TIME", "TIMESTAMP"}
STRING_CANON = {"STRING"}
