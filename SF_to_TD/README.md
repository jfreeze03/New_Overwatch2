# TD → SF Migration Parity Console

A VS Code project that connects to Teradata and Snowflake and validates a
migration by **output parity**, not source-code diffing.

## What it actually checks
| Tier | What | Cost |
|------|------|------|
| ① Inventory | Object exists on both sides (tables, views, procs, macros, funcs) | metadata only |
| ② Schema | Column names, canonical type match, nullability | metadata only |
| ③ Row counts | `COUNT(*)` both sides per shared table | 1 pass / table |
| ④ Fingerprint | Per-column COUNT/SUM/MIN/MAX/NDV both sides | scans data — opt-in |
| ⑤ Procedures | **Manual** output validation workflow (by design) | — |

### Why procedures aren't auto-diffed
TD SPL ≠ Snowflake SQL/Snowpark/JS. Comparing source text yields 100% noise.
You validate a procedure by comparing the **target tables it writes** after
running both versions on the same inputs (tabs ③/④). Use `QUERY_TAG` to anchor
each run, consistent with your existing attribution approach.

### Why aggregate fingerprints, not row hashes
TD `HASHROW` and SF `HASH`/`MD5` use different algorithms and normalization, so
cross-system row hashes never match even on identical data. Comparable
aggregates (count/sum/min/max/distinct) match iff the data matches, and a
mismatch tells you the exact column that diverged.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config/secrets.example.toml config/secrets.toml  # then fill it in
streamlit run app.py
```

`config/secrets.toml` is gitignored. Prefer Snowflake **key-pair auth** for
service accounts (uncomment `private_key_path`). TD `logmech` may need `LDAP`.

## Cost control
- Default workflow is metadata-only + row counts. Fingerprints are one table at
  a time and opt-in.
- Keep the Snowflake `warehouse` small (XS/S) — set in `secrets.toml`.
- `row_count_guard` / `fingerprint_guard` in `[options]` exclude oversized
  tables from heavy ops; raise deliberately.

## Layout
```
td_sf_compare/
├─ app.py                 # Streamlit UI (5 tabs)
├─ core/
│  ├─ connections.py      # TD + SF connection factories, config loader
│  ├─ type_mapping.py     # TD code decode + canonical type buckets
│  └─ comparison_engine.py# inventory / schema / row count / fingerprint
├─ config/secrets.example.toml
└─ requirements.txt
```

## Known limits (read before trusting output)
- Fingerprint compares aggregates, not every row. Equal aggregates are *strong*
  but not *absolute* proof (a swap of two rows' values in the same column nets
  to the same SUM). For absolute proof on critical tables, do a keyed full-row
  pull on a sample and `pandas.merge` — add as a tier ⑥ if you need it.
- `INFORMATION_SCHEMA` in Snowflake reflects current state; for historical/dropped
  objects switch reads to `ACCOUNT_USAGE` (has latency).
- View/proc DDL not deep-parsed; only existence + (for views) output via ④.
