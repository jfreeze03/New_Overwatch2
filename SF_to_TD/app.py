"""
TD <-> SF Migration Parity Console (Streamlit).

Run:  streamlit run app.py
Default mode is cheap (inventory + schema + row counts). Fingerprints and
full-row pulls are opt-in and guarded by row-count thresholds to protect credits.
"""
import io
import pandas as pd
import streamlit as st

from core.connections import load_config, connect_teradata, connect_snowflake
from core import comparison_engine as ce

st.set_page_config(page_title="TD/SF Parity Console", layout="wide",
                   page_icon="🛰️")

st.markdown("""
<style>
  .stApp { background:#0b0d12; color:#d6dde8; }
  h1,h2,h3 { color:#e63946; font-family:'Share Tech Mono',monospace; }
  .ok    { color:#2dd4bf; } .bad { color:#e63946; } .warn { color:#f4a261; }
</style>
""", unsafe_allow_html=True)

st.title("🛰️ TD → SF MIGRATION PARITY CONSOLE")
st.caption("Schema parity · data fingerprints · row reconciliation. "
           "Procedure *output* validation is manual by design — source diffs are noise.")


# ---- connections (cached) --------------------------------------------------
@st.cache_resource(show_spinner="Connecting…")
def get_conns():
    cfg = load_config()
    return cfg, connect_teradata(cfg.td), connect_snowflake(cfg.sf)


try:
    cfg, td_conn, sf_conn = get_conns()
except Exception as e:
    st.error(f"Connection/config problem: {e}")
    st.info("Copy config/secrets.example.toml → config/secrets.toml and fill it in.")
    st.stop()

pairs = cfg.pairs  # [(td_db, "SF_DB.SF_SCHEMA"), ...]
if not pairs:
    st.error("No TD↔SF database pairs configured. Set [teradata].databases and "
             "[snowflake].schemas (positionally paired) in secrets.toml.")
    st.stop()

pair_labels = [f"{td}  →  {sf}" for td, sf in pairs]
sel = st.selectbox("Scope (TD database → SF database.schema)", pair_labels)
td_db, sf_full = pairs[pair_labels.index(sel)]
sf_db, sf_sch = sf_full.split(".", 1)


def df_download(df: pd.DataFrame, name: str):
    buf = io.StringIO(); df.to_csv(buf, index=False)
    st.download_button(f"⬇ {name}.csv", buf.getvalue(), f"{name}.csv", "text/csv")


tabs = st.tabs(["① Inventory", "② Schema parity", "③ Row counts",
                "④ Data fingerprint", "⑤ Procedures"])

# ---- ① INVENTORY -----------------------------------------------------------
with tabs[0]:
    st.subheader("Object inventory parity")
    if st.button("Run inventory compare", key="inv"):
        td_inv = ce.td_inventory(td_conn, td_db)
        sf_inv = ce.sf_inventory(sf_conn, sf_db, sf_sch)
        cmp = ce.compare_inventory(td_inv, sf_inv)
        st.session_state["inv_cmp"] = cmp
    if "inv_cmp" in st.session_state:
        cmp = st.session_state["inv_cmp"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Present both", int((cmp.status == "PRESENT_BOTH").sum()))
        c2.metric("Missing in SF", int((cmp.status == "MISSING_IN_SNOWFLAKE").sum()))
        c3.metric("Extra in SF", int((cmp.status == "EXTRA_IN_SNOWFLAKE").sum()))
        flt = st.multiselect("Filter status", cmp.status.unique().tolist(),
                             default=[s for s in cmp.status.unique()
                                      if s != "PRESENT_BOTH"])
        view = cmp[cmp.status.isin(flt)] if flt else cmp
        st.dataframe(view, use_container_width=True, height=420)
        df_download(cmp, "inventory_compare")

# ---- ② SCHEMA --------------------------------------------------------------
with tabs[1]:
    st.subheader("Column / type / nullability parity")
    st.caption("Types reduced to canonical buckets so TD VARCHAR vs "
               "SF VARCHAR(16M) doesn't false-flag. Real mismatches only.")
    if st.button("Run schema compare", key="sch"):
        tdc = ce.td_columns(td_conn, td_db)
        sfc = ce.sf_columns(sf_conn, sf_db, sf_sch)
        st.session_state["sch_cmp"] = ce.compare_columns(tdc, sfc)
    if "sch_cmp" in st.session_state:
        m = st.session_state["sch_cmp"]
        problems = m[m.status != "OK"]
        st.metric("Columns with issues", len(problems),
                  delta=f"{len(m)} columns total", delta_color="off")
        only_issues = st.toggle("Show only mismatches", value=True)
        st.dataframe(problems if only_issues else m,
                     use_container_width=True, height=420)
        df_download(m, "schema_compare")

# ---- ③ ROW COUNTS ----------------------------------------------------------
with tabs[2]:
    st.subheader("Row count reconciliation")
    st.caption("One COUNT(*) per side. Cheap. Run this before fingerprints.")
    if st.button("Run row counts", key="rc"):
        # only tables present on both sides
        if "inv_cmp" not in st.session_state:
            td_inv = ce.td_inventory(td_conn, td_db)
            sf_inv = ce.sf_inventory(sf_conn, sf_db, sf_sch)
            st.session_state["inv_cmp"] = ce.compare_inventory(td_inv, sf_inv)
        inv = st.session_state["inv_cmp"]
        tbls = inv[(inv.status == "PRESENT_BOTH") &
                   (inv.object_type_td == "TABLE")]["object_name"].tolist()
        pairs_rc = [(td_db, t, sf_db, sf_sch, t) for t in tbls]
        with st.spinner(f"Counting {len(pairs_rc)} tables…"):
            st.session_state["rc"] = ce.row_counts(td_conn, sf_conn, pairs_rc)
    if "rc" in st.session_state:
        rc = st.session_state["rc"]
        mism = rc[rc.match == False]  # noqa: E712
        st.metric("Tables out of sync", len(mism), delta=f"{len(rc)} checked",
                  delta_color="inverse")
        st.dataframe(rc.sort_values("match"), use_container_width=True, height=420)
        df_download(rc, "row_counts")

# ---- ④ FINGERPRINT ---------------------------------------------------------
with tabs[3]:
    st.subheader("Aggregate data fingerprint")
    st.caption("Per-column COUNT / SUM / MIN / MAX / NDV on both sides. "
               "Equal fingerprint ⇒ strong parity evidence. No cross-DB row hashing "
               "(unreliable). One table at a time — this scans data and costs credits.")
    if "sch_cmp" not in st.session_state:
        st.info("Run Schema compare (tab ②) first so shared columns are known.")
    else:
        m = st.session_state["sch_cmp"]
        shared = m[m.status.isin(["OK", "NULLABILITY_MISMATCH"])]
        tables = sorted(shared.object_name.unique().tolist())
        tbl = st.selectbox("Table", tables)
        if tbl and st.button("Fingerprint this table", key="fp"):
            cols = (shared[shared.object_name == tbl]
                    [["column_name", "canonical_td"]]
                    .rename(columns={"canonical_td": "canonical"})
                    .to_dict("records"))
            with st.spinner("Aggregating both sides…"):
                fp = ce.fingerprint_table(td_conn, sf_conn, td_db, sf_db, sf_sch,
                                          tbl, cols)
            bad = fp[fp.match == False]  # noqa: E712
            if bad.empty:
                st.success(f"✅ {tbl}: all {len(fp)} metrics match.")
            else:
                st.error(f"❌ {tbl}: {len(bad)} metric(s) diverge.")
            st.dataframe(fp.sort_values("match"), use_container_width=True, height=420)
            df_download(fp, f"fingerprint_{tbl}")

# ---- ⑤ PROCEDURES ----------------------------------------------------------
with tabs[4]:
    st.subheader("Procedures — manual output validation")
    st.markdown("""
**Why no automatic code diff:** TD SPL and Snowflake SQL/Snowpark/JS procedures
are different languages. Text comparison produces 100% noise and 0% signal.

**What to validate instead:** the *output* of each procedure given known inputs.
The reliable pattern (you already use `QUERY_TAG`): tag both the TD run and the
SF run, capture the result set or the affected target table, then point tabs
③/④ at that target table.

Checklist per procedure:
1. Identify the target table(s) it writes (e.g. `PLCY_RAW_VTBL`).
2. Run TD proc and SF proc on the same input window / params.
3. Compare target tables via Row counts (③) then Fingerprint (④).
4. Sign off only when fingerprints match.
""")
    if st.button("List procedures present on both sides", key="procs"):
        if "inv_cmp" not in st.session_state:
            td_inv = ce.td_inventory(td_conn, td_db)
            sf_inv = ce.sf_inventory(sf_conn, sf_db, sf_sch)
            st.session_state["inv_cmp"] = ce.compare_inventory(td_inv, sf_inv)
        inv = st.session_state["inv_cmp"]
        procs = inv[(inv.object_type_td == "PROCEDURE") |
                    (inv.object_type_sf == "PROCEDURE")]
        st.dataframe(procs[["object_name", "status"]], use_container_width=True)
