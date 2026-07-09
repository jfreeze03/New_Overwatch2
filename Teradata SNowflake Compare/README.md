# td_sf_compare — Teradata → Snowflake Migration Validation

Tiered comparison of structure and data between Teradata and Snowflake over your existing JDBC drivers. Cheap checks run first; expensive checks are opt-in and cost-guarded.

| Tier | What it compares | Source | Cost |
|------|-----------------|--------|------|
| 1 | Object inventory (missing/extra tables) | `DBC.TablesV` vs `INFORMATION_SCHEMA.TABLES` | Free (metadata) |
| 2 | Columns: names, canonical type buckets, nullability | `DBC.ColumnsV` vs `INFORMATION_SCHEMA.COLUMNS` | Free (metadata) |
| 3 | Exact row counts per table | `COUNT(*)` both sides | Cheap |
| 4 | Data fingerprints: SUM/MIN/MAX for numerics & dates, length-sum + distinct counts for strings | Full-table aggregates | Compute — **opt-in** |

## Setup (VS Code)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on Mac/Linux)
pip install jaydebeapi jpype1 pandas openpyxl pyyaml
```

Requires a JVM (JDK 11+) on the machine — same requirement as any JDBC client. Set `JAVA_HOME` if it isn't already.

1. Edit `config.yaml`: jar paths, JDBC URLs, and the database → schema mappings.
2. Set passwords as environment variables (never in the file):
   ```powershell
   $env:TD_PASSWORD = "..."
   $env:SF_PASSWORD = "..."
   ```
3. Run:
   ```bash
   python compare.py                                  # Tiers 1–3, all mapped tables
   python compare.py --tables PLCY_RAW_VTBL           # scope to specific tables
   python compare.py --tables PLCY_RAW_VTBL --fingerprint   # add Tier 4 data check
   ```

Output: timestamped `.xlsx` in `./reports` with a SUMMARY sheet plus one sheet per tier. Exit code is non-zero when issues exist, so it drops straight into Bitbucket Pipelines as a validation gate.

## Design decisions

**Canonical type buckets, not literal types.** `VARCHAR(50)` vs `TEXT` and `INTEGER` vs `NUMBER(38,0)` are expected migration outcomes, not defects. Types map to buckets (`STRING`, `INTEGER`, `DECIMAL`, `DATE`, ...) and known-compatible bucket pairs report as `COMPATIBLE` rather than failing. Edit `type_map.py` to tune.

**Aggregate fingerprints instead of row-level diff.** Cross-platform row hashing is unreliable (no shared hash function, collation/trailing-space semantics differ). Instead, per-column aggregates are computed with expressions chosen to be numerically identical on both platforms when data matches: `SUM(CAST(col AS DECIMAL(38,4)))`, `MIN`/`MAX`, `SUM(LENGTH(TRIM(col)))`, `COUNT(DISTINCT col)`. `TRIM` neutralizes Teradata CHAR padding. If every aggregate matches on every column, corruption is statistically implausible; if one mismatches, you know exactly which column to investigate.

**Cost guardrails.** Tier 4 skips tables over `fingerprint_max_rows` (default 50M) and caps at `fingerprint_max_cols` columns. Point the Snowflake URL at an XSMALL warehouse — these are single-pass scans. The `QUERY_TAG=TD_SF_COMPARE` in the URL makes the spend visible in OVERWATCH.

**Single JVM.** Both jars load into one JPype JVM at startup — never call `startJVM` twice.

## Known gotchas

- **Teradata FLOAT vs Snowflake FLOAT**: both IEEE 754 double, but `SUM` over floats is order-dependent. A tiny sum delta on a FLOAT column with matching COUNT/MIN/MAX is usually noise, not corruption.
- **TIMESTAMP WITH TIME ZONE**: MIN/MAX compare as strings; formatting differences can produce false mismatches. Verify manually before flagging.
- **Case-specific object names**: script uppercases everything. If any Snowflake objects were created with quoted lowercase identifiers, they'll show as missing.
- **Views**: Tier 1 only compares base tables (`TableKind IN ('T','O')`). Add `'V'` and `TABLE_TYPE = 'VIEW'` if you want view parity too.
- **DBC access**: your Teradata user needs SELECT on `DBC.TablesV` / `DBC.ColumnsV` (standard for DBA roles).
