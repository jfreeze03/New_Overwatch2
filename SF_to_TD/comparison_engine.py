"""
Comparison engine. Each function returns a pandas DataFrame so the UI can render
and export directly. Designed cheap-first: inventory + schema + row counts are
metadata-only or single-pass COUNTs. Fingerprints and full-row pulls are opt-in.

Cross-DB note: we do NOT compare row hashes across systems (TD HASHROW != SF MD5).
We compare COMPARABLE aggregates (count/sum/min/max/distinct) per column, which
match iff the data matches. Equal fingerprints are strong evidence of parity;
a mismatch tells you exactly which column diverged.
"""
from __future__ import annotations
import pandas as pd
from .type_mapping import (
    decode_td_type, canonical_sf_type, canonical_sf_number,
    NUMERIC_CANON, TEMPORAL_CANON, STRING_CANON,
)

# ---- low-level fetch -------------------------------------------------------

def _df(cur, sql, params=None) -> pd.DataFrame:
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


# ---- 1. OBJECT INVENTORY ---------------------------------------------------

def td_inventory(td_conn, database: str) -> pd.DataFrame:
    sql = """
        SELECT TRIM(TableName) AS object_name,
               CASE TableKind WHEN 'T' THEN 'TABLE'
                              WHEN 'O' THEN 'TABLE'
                              WHEN 'V' THEN 'VIEW'
                              WHEN 'P' THEN 'PROCEDURE'
                              WHEN 'E' THEN 'PROCEDURE'
                              WHEN 'M' THEN 'MACRO'
                              WHEN 'F' THEN 'FUNCTION'
                              ELSE TableKind END AS object_type
        FROM DBC.TablesV
        WHERE DatabaseName = ?
          AND TableKind IN ('T','O','V','P','E','M','F')
    """
    cur = td_conn.cursor()
    df = _df(cur, sql, [database])
    df["object_name"] = df["object_name"].str.upper()
    return df


def sf_inventory(sf_conn, database: str, schema: str) -> pd.DataFrame:
    cur = sf_conn.cursor()
    cur.execute(f'USE DATABASE "{database}"')
    tables = _df(cur, """
        SELECT table_name AS object_name,
               CASE table_type WHEN 'BASE TABLE' THEN 'TABLE'
                               WHEN 'VIEW' THEN 'VIEW'
                               ELSE table_type END AS object_type
        FROM INFORMATION_SCHEMA.TABLES
        WHERE table_schema = %s
    """, [schema])
    procs = _df(cur, """
        SELECT procedure_name AS object_name, 'PROCEDURE' AS object_type
        FROM INFORMATION_SCHEMA.PROCEDURES
        WHERE procedure_schema = %s
    """, [schema])
    df = pd.concat([tables, procs], ignore_index=True)
    df["object_name"] = df["object_name"].str.upper()
    return df


def compare_inventory(td_inv: pd.DataFrame, sf_inv: pd.DataFrame) -> pd.DataFrame:
    m = td_inv.merge(sf_inv, on="object_name", how="outer",
                     suffixes=("_td", "_sf"), indicator=True)
    status = {
        "left_only": "MISSING_IN_SNOWFLAKE",
        "right_only": "EXTRA_IN_SNOWFLAKE",
        "both": "PRESENT_BOTH",
    }
    m["status"] = m["_merge"].map(status)
    m["type_mismatch"] = (
        (m["_merge"] == "both") & (m["object_type_td"] != m["object_type_sf"])
    )
    return m.drop(columns="_merge").sort_values(
        ["status", "object_name"]).reset_index(drop=True)


# ---- 2. SCHEMA / COLUMN PARITY --------------------------------------------

def td_columns(td_conn, database: str) -> pd.DataFrame:
    sql = """
        SELECT TRIM(TableName)  AS object_name,
               TRIM(ColumnName) AS column_name,
               ColumnId         AS ordinal,
               ColumnType       AS td_code,
               ColumnLength     AS length,
               DecimalTotalDigits AS precision,
               DecimalFractionalDigits AS scale,
               Nullable         AS nullable
        FROM DBC.ColumnsV
        WHERE DatabaseName = ?
    """
    cur = td_conn.cursor()
    df = _df(cur, sql, [database])
    df["object_name"] = df["object_name"].str.upper()
    df["column_name"] = df["column_name"].str.upper()
    df["canonical"] = df["td_code"].apply(decode_td_type)
    # TD decimal with scale 0 is integer-equivalent
    df.loc[(df["canonical"] == "DECIMAL") & (df["scale"].fillna(0) == 0),
           "canonical"] = "INT"
    df["nullable"] = df["nullable"].astype(str).str.upper().map(
        {"Y": True, "N": False}).fillna(True)
    return df


def sf_columns(sf_conn, database: str, schema: str) -> pd.DataFrame:
    cur = sf_conn.cursor()
    cur.execute(f'USE DATABASE "{database}"')
    df = _df(cur, """
        SELECT table_name  AS object_name,
               column_name AS column_name,
               ordinal_position AS ordinal,
               data_type   AS sf_type,
               character_maximum_length AS length,
               numeric_precision AS precision,
               numeric_scale AS scale,
               is_nullable AS nullable
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE table_schema = %s
    """, [schema])
    df["object_name"] = df["object_name"].str.upper()
    df["column_name"] = df["column_name"].str.upper()
    df["canonical"] = df.apply(
        lambda r: canonical_sf_number(
            canonical_sf_type(r["sf_type"]), r["precision"], r["scale"]), axis=1)
    df["nullable"] = df["nullable"].astype(str).str.upper().map(
        {"YES": True, "NO": False}).fillna(True)
    return df


def compare_columns(td_cols: pd.DataFrame, sf_cols: pd.DataFrame) -> pd.DataFrame:
    key = ["object_name", "column_name"]
    m = td_cols.merge(sf_cols, on=key, how="outer",
                      suffixes=("_td", "_sf"), indicator=True)
    def row_status(r):
        if r["_merge"] == "left_only":
            return "COLUMN_MISSING_IN_SF"
        if r["_merge"] == "right_only":
            return "COLUMN_EXTRA_IN_SF"
        if r["canonical_td"] != r["canonical_sf"]:
            return "TYPE_MISMATCH"
        if bool(r["nullable_td"]) != bool(r["nullable_sf"]):
            return "NULLABILITY_MISMATCH"
        return "OK"
    m["status"] = m.apply(row_status, axis=1)
    return m.drop(columns="_merge").sort_values(
        ["status", "object_name", "column_name"]).reset_index(drop=True)


# ---- 3. ROW COUNTS ---------------------------------------------------------

def row_counts(td_conn, sf_conn, table_pairs) -> pd.DataFrame:
    """table_pairs: list of (td_db, td_table, sf_db, sf_schema, sf_table)."""
    rows = []
    tcur, scur = td_conn.cursor(), sf_conn.cursor()
    for td_db, td_tbl, sf_db, sf_sch, sf_tbl in table_pairs:
        try:
            tcur.execute(f'SELECT COUNT(*) FROM "{td_db}"."{td_tbl}"')
            tc = tcur.fetchone()[0]
        except Exception as e:
            tc = f"ERR: {e}"
        try:
            scur.execute(f'SELECT COUNT(*) FROM "{sf_db}"."{sf_sch}"."{sf_tbl}"')
            sc = scur.fetchone()[0]
        except Exception as e:
            sc = f"ERR: {e}"
        match = isinstance(tc, int) and isinstance(sc, int) and tc == sc
        diff = (tc - sc) if (isinstance(tc, int) and isinstance(sc, int)) else None
        rows.append(dict(table=td_tbl, td_rows=tc, sf_rows=sc, diff=diff, match=match))
    return pd.DataFrame(rows)


# ---- 4. AGGREGATE FINGERPRINT ---------------------------------------------

def _td_agg_sql(db, tbl, cols):
    parts = ['COUNT(*) AS "_row_count"']
    for c in cols:
        canon, name = c["canonical"], c["column_name"]
        q = f'"{name}"'
        parts.append(f'COUNT({q}) AS "{name}__cnt"')
        if canon in NUMERIC_CANON:
            parts.append(f'CAST(SUM({q}) AS DECIMAL(38,4)) AS "{name}__sum"')
            parts.append(f'MIN({q}) AS "{name}__min"')
            parts.append(f'MAX({q}) AS "{name}__max"')
        elif canon in TEMPORAL_CANON:
            parts.append(f'MIN({q}) AS "{name}__min"')
            parts.append(f'MAX({q}) AS "{name}__max"')
        elif canon in STRING_CANON:
            parts.append(f'COUNT(DISTINCT {q}) AS "{name}__ndv"')
    return f'SELECT {", ".join(parts)} FROM "{db}"."{tbl}"'


def _sf_agg_sql(db, sch, tbl, cols):
    parts = ['COUNT(*) AS "_row_count"']
    for c in cols:
        canon, name = c["canonical"], c["column_name"]
        q = f'"{name}"'
        parts.append(f'COUNT({q}) AS "{name}__cnt"')
        if canon in NUMERIC_CANON:
            parts.append(f'CAST(SUM({q}) AS NUMBER(38,4)) AS "{name}__sum"')
            parts.append(f'MIN({q}) AS "{name}__min"')
            parts.append(f'MAX({q}) AS "{name}__max"')
        elif canon in TEMPORAL_CANON:
            parts.append(f'MIN({q}) AS "{name}__min"')
            parts.append(f'MAX({q}) AS "{name}__max"')
        elif canon in STRING_CANON:
            parts.append(f'COUNT(DISTINCT {q}) AS "{name}__ndv"')
    return f'SELECT {", ".join(parts)} FROM "{db}"."{sch}"."{tbl}"'


def fingerprint_table(td_conn, sf_conn, td_db, sf_db, sf_sch, table,
                      shared_cols) -> pd.DataFrame:
    """shared_cols: list of dicts {column_name, canonical} present on BOTH sides."""
    tcur, scur = td_conn.cursor(), sf_conn.cursor()
    tcur.execute(_td_agg_sql(td_db, table, shared_cols))
    td_vals = dict(zip([d[0] for d in tcur.description], tcur.fetchone()))
    scur.execute(_sf_agg_sql(sf_db, sf_sch, table, shared_cols))
    sf_vals = dict(zip([d[0] for d in scur.description], scur.fetchone()))

    out = []
    for k in td_vals:
        tv, sv = td_vals[k], sf_vals.get(k)
        # normalize numbers so 10 == 10.0000
        tvn = float(tv) if isinstance(tv, (int, float)) else tv
        svn = float(sv) if isinstance(sv, (int, float)) else sv
        out.append(dict(metric=k, td_value=str(tv), sf_value=str(sv),
                        match=(tvn == svn)))
    return pd.DataFrame(out)
