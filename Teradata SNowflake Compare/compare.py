"""td_sf_compare — tiered Teradata -> Snowflake migration validation.

Tier 1  Object inventory   : tables present on both sides, missing/extra
Tier 2  Schema diff        : column names, canonical type buckets, nullability
Tier 3  Row counts         : exact count reconciliation per table
Tier 4  Data fingerprints  : per-column aggregates (opt-in, cost-guarded)

Usage:
    python compare.py                      # uses ./config.yaml
    python compare.py --config prod.yaml
    python compare.py --tables PLCY_RAW_VTBL,SP_ACCTBLY_DTL
"""

import argparse
import datetime as dt
import os
import sys

import pandas as pd
import yaml

from connections import connect_all, fetch
from type_map import td_bucket, sf_bucket, buckets_match

# ---------------------------------------------------------------- helpers

def q(s: str) -> str:
    """Escape a single-quoted SQL literal."""
    return s.replace("'", "''")


def norm(name) -> str:
    return str(name).strip().upper()


# ---------------------------------------------------------------- tier 1

def tier1_inventory(td, sf, m, include, exclude):
    td_sql = f"""
        SELECT TRIM(TableName)
        FROM DBC.TablesV
        WHERE DatabaseName = '{q(m['teradata_db'])}'
          AND TableKind IN ('T','O')   -- tables + NoPI tables (views compared separately if needed)
    """
    sf_sql = f"""
        SELECT TABLE_NAME
        FROM {m['snowflake_db']}.INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = '{q(m['snowflake_schema'])}'
          AND TABLE_TYPE = 'BASE TABLE'
    """
    td_tables = {norm(r[0]) for r in fetch(td, td_sql)}
    sf_tables = {norm(r[0]) for r in fetch(sf, sf_sql)}

    if include:
        keep = {norm(t) for t in include}
        td_tables &= keep
        sf_tables &= keep
    if exclude:
        drop = {norm(t) for t in exclude}
        td_tables -= drop
        sf_tables -= drop

    common = sorted(td_tables & sf_tables)
    rows = []
    for t in sorted(td_tables | sf_tables):
        rows.append({
            "mapping": f"{m['teradata_db']} -> {m['snowflake_db']}.{m['snowflake_schema']}",
            "table": t,
            "in_teradata": t in td_tables,
            "in_snowflake": t in sf_tables,
            "status": "OK" if (t in td_tables and t in sf_tables)
                      else ("MISSING_IN_SNOWFLAKE" if t in td_tables else "EXTRA_IN_SNOWFLAKE"),
        })
    return pd.DataFrame(rows), common


# ---------------------------------------------------------------- tier 2

def tier2_schema(td, sf, m, tables):
    td_sql = f"""
        SELECT TRIM(TableName), TRIM(ColumnName), TRIM(ColumnType),
               Nullable, ColumnLength, DecimalTotalDigits, DecimalFractionalDigits
        FROM DBC.ColumnsV
        WHERE DatabaseName = '{q(m['teradata_db'])}'
    """
    sf_sql = f"""
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE,
               CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE
        FROM {m['snowflake_db']}.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{q(m['snowflake_schema'])}'
    """
    td_cols, sf_cols = {}, {}
    for tab, col, ctype, nullable, clen, prec, scale in fetch(td, td_sql):
        td_cols.setdefault(norm(tab), {})[norm(col)] = {
            "type": ctype, "bucket": td_bucket(ctype),
            "nullable": str(nullable).strip().upper() == "Y",
            "len": clen, "prec": prec, "scale": scale,
        }
    for tab, col, dtype, nullable, clen, prec, scale in fetch(sf, sf_sql):
        sf_cols.setdefault(norm(tab), {})[norm(col)] = {
            "type": dtype, "bucket": sf_bucket(dtype, scale),
            "nullable": str(nullable).strip().upper() == "YES",
            "len": clen, "prec": prec, "scale": scale,
        }

    rows = []
    for t in tables:
        tcols, scols = td_cols.get(t, {}), sf_cols.get(t, {})
        for c in sorted(set(tcols) | set(scols)):
            tc, sc = tcols.get(c), scols.get(c)
            if tc and sc:
                verdict = buckets_match(tc["bucket"], sc["bucket"])
                null_note = "" if tc["nullable"] == sc["nullable"] else "NULLABILITY_DIFFERS"
                status = "OK" if verdict == "MATCH" else verdict
            elif tc:
                verdict, null_note, status = "", "", "MISSING_IN_SNOWFLAKE"
            else:
                verdict, null_note, status = "", "", "EXTRA_IN_SNOWFLAKE"
            rows.append({
                "table": t, "column": c,
                "td_type": tc["type"] if tc else None,
                "td_bucket": tc["bucket"] if tc else None,
                "sf_type": sc["type"] if sc else None,
                "sf_bucket": sc["bucket"] if sc else None,
                "type_verdict": verdict,
                "nullability_note": null_note,
                "status": status,
            })
    df = pd.DataFrame(rows)
    return df, td_cols, sf_cols


# ---------------------------------------------------------------- tier 3

def tier3_rowcounts(td, sf, m, tables):
    rows = []
    for t in tables:
        try:
            td_cnt = fetch(td, f'SELECT COUNT(*) FROM "{m["teradata_db"]}"."{t}"')[0][0]
        except Exception as e:
            td_cnt, err_td = None, str(e)[:120]
        else:
            err_td = None
        try:
            sf_cnt = fetch(sf, f'SELECT COUNT(*) FROM {m["snowflake_db"]}.{m["snowflake_schema"]}."{t}"')[0][0]
        except Exception as e:
            sf_cnt, err_sf = None, str(e)[:120]
        else:
            err_sf = None

        diff = (td_cnt - sf_cnt) if (td_cnt is not None and sf_cnt is not None) else None
        rows.append({
            "table": t,
            "td_rows": td_cnt, "sf_rows": sf_cnt, "diff": diff,
            "status": "OK" if diff == 0 else ("ERROR" if diff is None else "COUNT_MISMATCH"),
            "error": err_td or err_sf,
        })
        print(f"  Tier3 {t}: TD={td_cnt} SF={sf_cnt} -> {'OK' if diff == 0 else 'MISMATCH'}")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- tier 4

FINGERPRINT_BUCKETS = {"INTEGER", "DECIMAL", "FLOAT", "DATE", "TIMESTAMP", "TIMESTAMP_TZ", "STRING"}


def _fp_exprs(colname: str, bucket: str, platform: str) -> list[tuple[str, str]]:
    """Return (metric_name, sql_expr) pairs. Expressions chosen to be
    numerically identical across both platforms when data matches."""
    c = f'"{colname}"'
    exprs = [("count_nonnull", f"COUNT({c})")]
    if bucket in ("INTEGER", "DECIMAL", "FLOAT"):
        exprs += [
            ("sum", f"SUM(CAST({c} AS DECIMAL(38,4)))"),
            ("min", f"MIN({c})"),
            ("max", f"MAX({c})"),
        ]
    elif bucket in ("DATE", "TIMESTAMP", "TIMESTAMP_TZ"):
        exprs += [("min", f"MIN({c})"), ("max", f"MAX({c})")]
    elif bucket == "STRING":
        length_fn = "CHARACTER_LENGTH" if platform == "td" else "LENGTH"
        exprs += [
            ("sum_len", f"SUM(CAST({length_fn}(TRIM({c})) AS DECIMAL(38,0)))"),
            ("count_distinct", f"COUNT(DISTINCT {c})"),
        ]
    return exprs


def tier4_fingerprint(td, sf, m, tables, td_cols, rowcounts_df, cfg):
    max_rows = cfg["tiers"].get("fingerprint_max_rows", 50_000_000)
    max_cols = cfg["tiers"].get("fingerprint_max_cols", 40)
    counts = dict(zip(rowcounts_df["table"], rowcounts_df["td_rows"]))
    rows = []

    for t in tables:
        n = counts.get(t)
        if n is None or n > max_rows:
            rows.append({"table": t, "column": None, "metric": None,
                         "td_value": None, "sf_value": None,
                         "status": f"SKIPPED (rows={n} > guardrail {max_rows})" if n else "SKIPPED (no count)"})
            continue

        cols = [(c, meta["bucket"]) for c, meta in td_cols.get(t, {}).items()
                if meta["bucket"] in FINGERPRINT_BUCKETS][:max_cols]
        if not cols:
            continue

        td_sel, sf_sel, labels = [], [], []
        for c, b in cols:
            for metric, expr in _fp_exprs(c, b, "td"):
                td_sel.append(expr)
                labels.append((c, metric))
            for _, expr in _fp_exprs(c, b, "sf"):
                sf_sel.append(expr)

        try:
            td_vals = fetch(td, f'SELECT {", ".join(td_sel)} FROM "{m["teradata_db"]}"."{t}"')[0]
            sf_vals = fetch(sf, f'SELECT {", ".join(sf_sel)} FROM {m["snowflake_db"]}.{m["snowflake_schema"]}."{t}"')[0]
        except Exception as e:
            rows.append({"table": t, "column": None, "metric": "ERROR",
                         "td_value": None, "sf_value": None, "status": str(e)[:150]})
            continue

        for (c, metric), tv, sv in zip(labels, td_vals, sf_vals):
            match = str(tv) == str(sv)
            rows.append({"table": t, "column": c, "metric": metric,
                         "td_value": tv, "sf_value": sv,
                         "status": "OK" if match else "VALUE_MISMATCH"})
        bad = sum(1 for r in rows if r["table"] == t and r["status"] == "VALUE_MISMATCH")
        print(f"  Tier4 {t}: {len(labels)} metrics, {bad} mismatches")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- report

def write_report(out_dir, frames: dict):
    os.makedirs(out_dir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"td_sf_compare_{stamp}.xlsx")

    summary = []
    for name, df in frames.items():
        if df is None or df.empty:
            continue
        total = len(df)
        ok = int((df.get("status") == "OK").sum()) if "status" in df else total
        summary.append({"tier": name, "checks": total, "ok": ok, "issues": total - ok})
    summary_df = pd.DataFrame(summary)

    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        summary_df.to_excel(xl, sheet_name="SUMMARY", index=False)
        for name, df in frames.items():
            if df is not None and not df.empty:
                df.to_excel(xl, sheet_name=name[:31], index=False)
    return path, summary_df


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Teradata -> Snowflake tiered comparison")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--tables", help="comma-separated table list (overrides include_tables)")
    ap.add_argument("--fingerprint", action="store_true", help="force Tier 4 on")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    include = ([t.strip() for t in args.tables.split(",")] if args.tables
               else cfg.get("include_tables") or [])
    exclude = cfg.get("exclude_tables") or []
    tiers = cfg["tiers"]
    if args.fingerprint:
        tiers["run_fingerprint"] = True

    print("Connecting (single JVM, both JDBC jars)...")
    td, sf = connect_all(cfg["teradata"], cfg["snowflake"])

    inv_all, sch_all, cnt_all, fp_all = [], [], [], []
    try:
        for m in cfg["mappings"]:
            print(f"\n=== {m['teradata_db']} -> {m['snowflake_db']}.{m['snowflake_schema']} ===")

            inv_df, common = tier1_inventory(td, sf, m, include, exclude)
            inv_all.append(inv_df)
            print(f"  Tier1: {len(common)} common tables, "
                  f"{int((inv_df['status'] != 'OK').sum())} inventory issues")

            td_cols = {}
            if tiers.get("run_schema"):
                sch_df, td_cols, _ = tier2_schema(td, sf, m, common)
                sch_all.append(sch_df)
                print(f"  Tier2: {int((sch_df['status'] != 'OK').sum())} column issues "
                      f"across {len(common)} tables")

            cnt_df = pd.DataFrame()
            if tiers.get("run_rowcounts"):
                cnt_df = tier3_rowcounts(td, sf, m, common)
                cnt_all.append(cnt_df)

            if tiers.get("run_fingerprint"):
                fp_all.append(tier4_fingerprint(td, sf, m, common, td_cols, cnt_df, cfg))
    finally:
        td.close()
        sf.close()

    frames = {
        "T1_INVENTORY": pd.concat(inv_all, ignore_index=True) if inv_all else None,
        "T2_SCHEMA": pd.concat(sch_all, ignore_index=True) if sch_all else None,
        "T3_ROWCOUNTS": pd.concat(cnt_all, ignore_index=True) if cnt_all else None,
        "T4_FINGERPRINT": pd.concat(fp_all, ignore_index=True) if fp_all else None,
    }
    path, summary = write_report(cfg.get("output_dir", "./reports"), frames)
    print("\n" + summary.to_string(index=False))
    print(f"\nReport written: {path}")
    issues = int(summary["issues"].sum()) if not summary.empty else 0
    sys.exit(1 if issues else 0)   # non-zero exit -> CI-friendly


if __name__ == "__main__":
    main()
