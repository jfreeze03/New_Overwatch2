import os
import re
from datetime import date, timedelta
import pandas as pd
import altair as alt
import streamlit as st

st.set_page_config(
    page_title="Snowflake Cost & Performance Dashboard",
    layout="wide"
)

conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))

DB = "TRXS_EDW_DEV"
SCHEMA = '"SnowflakeCosts"'


def _fqn(view):
    return f'{DB}.{SCHEMA}."{view}"'


# ---------------------------------------------------------------------------
# Data loaders — all have LIMIT or date bounds for performance
# ---------------------------------------------------------------------------

@st.cache_data(ttl=600)
def load_cost_by_day(start_date: str, end_date: str):
    return conn.query(
        f"""
        SELECT
            "StartDate",
            "WarehouseName",
            "TotalCredits",
            "EstimatedCost",
            SUM("EstimatedCost") OVER (
                PARTITION BY "WarehouseName"
                ORDER BY "StartDate"
                ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
            ) / NULLIF(
                COUNT("EstimatedCost") OVER (
                    PARTITION BY "WarehouseName"
                    ORDER BY "StartDate"
                    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
                ), 0
            ) AS "Rolling7DayAvg"
        FROM {_fqn('vwCostByWarehouseByDay')}
        WHERE "StartDate" >= '{start_date}' AND "StartDate" <= '{end_date}'
        ORDER BY "StartDate" DESC
        """
    )


@st.cache_data(ttl=600)
def load_cost_by_day_simple(start_date: str, end_date: str):
    return conn.query(
        f"""
        SELECT "StartDate", "WarehouseName", "TotalCredits", "EstimatedCost"
        FROM {_fqn('vwCostByWarehouseByDay')}
        WHERE "StartDate" >= '{start_date}' AND "StartDate" <= '{end_date}'
        ORDER BY "StartDate" DESC
        """
    )


@st.cache_data(ttl=600)
def load_cost_by_month():
    return conn.query(
        f"""
        SELECT "YearMonth", "WarehouseName", "TotalCredits", "EstimatedCost"
        FROM {_fqn('vwCostByWarehouseByMonth')}
        ORDER BY "YearMonth" DESC
        LIMIT 120
        """
    )


@st.cache_data(ttl=600)
def load_hourly_cost():
    return conn.query(
        f"""
        SELECT "YearMonth", "Hour", "WarehouseName", "CreditsUsed", "EstimatedCost"
        FROM {_fqn('vwWarehouseCostByHour')}
        ORDER BY "YearMonth" DESC, "Hour"
        LIMIT 5000
        """
    )


@st.cache_data(ttl=600)
def load_chargeback():
    return conn.query(
        f"""
        SELECT
            "QueryID",
            "WarehouseName",
            "RoleName",
            "UserName",
            "ElapsedSeconds",
            "EstimatedCredits",
            "EstimatedCost",
            "StartTime"
        FROM {_fqn('vwQueryEstimateCostMostExpensiveQueries')}
        ORDER BY "EstimatedCost" DESC
        LIMIT 500
        """
    )


@st.cache_data(ttl=600)
def load_cost_by_role():
    return conn.query(
        f"""
        SELECT "RoleName", "TotalEstimatedCredits", "TotalEstimatedCost"
        FROM {_fqn('vwQueryEstimateCostByRole')}
        ORDER BY "TotalEstimatedCost" DESC
        LIMIT 100
        """
    )


@st.cache_data(ttl=600)
def load_cost_by_schema():
    return conn.query(
        f"""
        SELECT "DatabaseName", "SchemaName", "TotalEstimatedCredits", "TotalEstimatedCost"
        FROM {_fqn('vwQueryEstimateCostBySchemaByDatabase')}
        ORDER BY "TotalEstimatedCost" DESC
        LIMIT 100
        """
    )


@st.cache_data(ttl=600)
def load_expensive_queries():
    return conn.query(
        f"""
        SELECT
            "QueryID", "WarehouseName", "RoleName", "UserName", "QueryText",
            "ElapsedSeconds", "EstimatedCredits", "EstimatedCost", "StartTime", "EndTime"
        FROM {_fqn('vwQueryEstimateCostMostExpensiveQueries')}
        ORDER BY "EstimatedCost" DESC
        LIMIT 50
        """
    )


@st.cache_data(ttl=600)
def load_heavy_queries():
    return conn.query(
        f"""
        SELECT
            "QueryID", "WarehouseName", "UserName", "QueryText",
            "ElapsedSeconds", "BytesScanned", "BytesWritten",
            "StartTime", "EndTime", "RoleName"
        FROM {_fqn('vwHeavyQueriesTimesLast30Days')}
        ORDER BY "ElapsedSeconds" DESC
        LIMIT 50
        """
    )


def clear_all_caches():
    load_cost_by_day.clear()
    load_cost_by_day_simple.clear()
    load_cost_by_month.clear()
    load_hourly_cost.clear()
    load_chargeback.clear()
    load_cost_by_role.clear()
    load_cost_by_schema.clear()
    load_expensive_queries.clear()
    load_heavy_queries.clear()


# ---------------------------------------------------------------------------
# Cleaners
# ---------------------------------------------------------------------------

def clean_daily(df):
    df = df.copy()
    df["StartDate"] = pd.to_datetime(df["StartDate"]).dt.date
    for col in ["TotalCredits", "EstimatedCost", "Rolling7DayAvg"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["WarehouseName"] = df["WarehouseName"].astype(str)
    return df


def clean_daily_simple(df):
    df = df.copy()
    df["StartDate"] = pd.to_datetime(df["StartDate"]).dt.date
    for col in ["TotalCredits", "EstimatedCost"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["WarehouseName"] = df["WarehouseName"].astype(str)
    return df


def clean_monthly(df):
    df = df.copy()
    df["YearMonth"] = df["YearMonth"].astype(str)
    df["TotalCredits"] = pd.to_numeric(df["TotalCredits"], errors="coerce").fillna(0)
    df["EstimatedCost"] = pd.to_numeric(df["EstimatedCost"], errors="coerce").fillna(0)
    df["WarehouseName"] = df["WarehouseName"].astype(str)
    return df


def clean_hourly(df):
    df = df.copy()
    df["YearMonth"] = df["YearMonth"].astype(str)
    df["Hour"] = pd.to_numeric(df["Hour"], errors="coerce").fillna(0).astype(int)
    df["CreditsUsed"] = pd.to_numeric(df["CreditsUsed"], errors="coerce").fillna(0)
    df["EstimatedCost"] = pd.to_numeric(df["EstimatedCost"], errors="coerce").fillna(0)
    df["WarehouseName"] = df["WarehouseName"].astype(str)
    return df


def clean_query_cost(df):
    df = df.copy()
    for col in ["ElapsedSeconds", "EstimatedCredits", "EstimatedCost"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "StartTime" in df.columns:
        df["StartTime"] = pd.to_datetime(df["StartTime"], errors="coerce")
    if "EndTime" in df.columns:
        df["EndTime"] = pd.to_datetime(df["EndTime"], errors="coerce")
    return df


def clean_heavy(df):
    df = df.copy()
    for col in ["ElapsedSeconds", "BytesScanned", "BytesWritten"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "StartTime" in df.columns:
        df["StartTime"] = pd.to_datetime(df["StartTime"], errors="coerce")
    if "EndTime" in df.columns:
        df["EndTime"] = pd.to_datetime(df["EndTime"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def format_currency(value):
    return f"${float(value or 0):,.2f}"


def format_number(value):
    return f"{float(value or 0):,.2f}"


def format_seconds(seconds):
    seconds = float(seconds or 0)
    if seconds < 60:
        return f"{seconds:,.1f}s"
    if seconds < 3600:
        return f"{seconds / 60:,.1f} min"
    return f"{seconds / 3600:,.1f} hrs"


def format_bytes(num):
    num = float(num or 0)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num) < 1024:
            return f"{num:,.2f} {unit}"
        num /= 1024
    return f"{num:,.2f} PB"


def format_pct_delta(current, prior):
    if prior == 0:
        return None
    pct = ((current - prior) / prior) * 100
    return f"{pct:+.1f}%"


def normalize_query(sql_text):
    if not sql_text:
        return ""
    s = str(sql_text).strip()[:200]
    s = re.sub(r"'[^']*'", "'?'", s)
    s = re.sub(r"\b\d+\b", "?", s)
    s = re.sub(r"\s+", " ", s)
    return s.upper()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def metric_row(metrics):
    cols = st.columns(len(metrics))
    for col, metric in zip(cols, metrics):
        if len(metric) == 3:
            label, value, delta = metric
            col.metric(label, value, delta=delta)
        else:
            label, value = metric
            col.metric(label, value)


def filter_warehouses(df, key):
    if df.empty or "WarehouseName" not in df.columns:
        return df
    warehouses = sorted(df["WarehouseName"].dropna().unique().tolist())
    selected = st.multiselect("🏢 Filter Warehouses", warehouses, default=warehouses, key=key)
    return df[df["WarehouseName"].isin(selected)]


def show_spend_health(total_cost, warn_threshold, critical_threshold):
    if total_cost < warn_threshold:
        st.success("🟢 Spend is within a healthy range.")
    elif total_cost < critical_threshold:
        st.warning("🟡 Spend is trending higher. Review top cost drivers.")
    else:
        st.error("🔴 Spend is elevated. Optimization review recommended.")


def show_query_drilldown(df, key_prefix):
    if df.empty:
        st.info("No query data available.")
        return
    query_ids = df["QueryID"].dropna().tolist()
    selected_query = st.selectbox("🔎 Select a Query ID to inspect", query_ids, key=f"{key_prefix}_qsel")
    row = df[df["QueryID"] == selected_query].iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🏢 Warehouse", row.get("WarehouseName", "N/A"))
    c2.metric("👤 User", row.get("UserName", "N/A"))
    c3.metric("👥 Role", row.get("RoleName", "N/A"))
    c4.metric("⏱️ Runtime", format_seconds(row.get("ElapsedSeconds", 0)))
    if "EstimatedCost" in df.columns:
        c5, c6 = st.columns(2)
        c5.metric("💰 Query Spend", format_currency(row.get("EstimatedCost", 0)))
        c6.metric("⚡ Credits Used", format_number(row.get("EstimatedCredits", 0)))
    if "BytesScanned" in df.columns:
        c5, c6 = st.columns(2)
        c5.metric("📦 Data Scanned", format_bytes(row.get("BytesScanned", 0)))
        c6.metric("✍️ Data Written", format_bytes(row.get("BytesWritten", 0)))
    st.caption(f"🕒 Start: {row.get('StartTime', 'N/A')} | End: {row.get('EndTime', 'N/A')}")
    st.code(row.get("QueryText", ""), language="sql")


def warehouse_sizing_recommendations(df_heavy):
    if df_heavy.empty:
        return
    wh_stats = (
        df_heavy.groupby("WarehouseName", as_index=False)
        .agg(
            AvgRuntime=("ElapsedSeconds", "mean"),
            MaxRuntime=("ElapsedSeconds", "max"),
            AvgBytesScanned=("BytesScanned", "mean"),
            QueryCount=("QueryID", "count")
        )
    )
    recommendations = []
    for _, row in wh_stats.iterrows():
        wh = row["WarehouseName"]
        if row["AvgRuntime"] < 5 and row["QueryCount"] > 20:
            recommendations.append(
                f"🏢 **{wh}**: Many short queries (avg {row['AvgRuntime']:.1f}s, {row['QueryCount']} queries). "
                f"Consider **downsizing**."
            )
        elif row["MaxRuntime"] > 600 and row["AvgBytesScanned"] > 50 * 1024**3:
            recommendations.append(
                f"🏢 **{wh}**: Queries >10 min scanning >50 GB avg. Consider **upsizing**."
            )
        elif row["MaxRuntime"] > 300:
            recommendations.append(
                f"🏢 **{wh}**: Some queries >5 min (max {format_seconds(row['MaxRuntime'])}). "
                f"Monitor for spilling."
            )
    if recommendations:
        with st.expander("💡 Warehouse Sizing Recommendations"):
            for r in recommendations:
                st.info(r)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def daily_spend_trend_chart(df):
    daily = (
        df.groupby("StartDate", as_index=False)
        .agg(Spend=("EstimatedCost", "sum"), Credits=("TotalCredits", "sum"), Rolling7DayAvg=("Rolling7DayAvg", "mean"))
        .sort_values("StartDate")
    )
    base = alt.Chart(daily).encode(x=alt.X("StartDate:T", title="Date"))
    bars = base.mark_bar(opacity=0.55).encode(
        y=alt.Y("Spend:Q", title="Daily Spend", axis=alt.Axis(format="$,.0f")),
        tooltip=[alt.Tooltip("StartDate:T", title="Date"), alt.Tooltip("Spend:Q", title="Spend", format="$,.2f")]
    )
    line = base.mark_line(strokeWidth=3, color="#ff6b35").encode(
        y=alt.Y("Rolling7DayAvg:Q"),
        tooltip=[alt.Tooltip("StartDate:T", title="Date"), alt.Tooltip("Rolling7DayAvg:Q", title="7-Day Avg", format="$,.2f")]
    )
    return alt.layer(bars, line).resolve_scale(y="shared").properties(height=380)


def warehouse_spend_chart(df):
    data = (
        df.groupby("WarehouseName", as_index=False)
        .agg(Spend=("EstimatedCost", "sum"))
        .sort_values("Spend", ascending=False)
    )
    return (
        alt.Chart(data).mark_bar()
        .encode(
            x=alt.X("Spend:Q", title="Spend", axis=alt.Axis(format="$,.0f")),
            y=alt.Y("WarehouseName:N", title="Warehouse", sort="-x"),
            tooltip=[alt.Tooltip("WarehouseName:N"), alt.Tooltip("Spend:Q", format="$,.2f")]
        )
        .properties(height=300)
    )


def monthly_spend_chart(df):
    data = (
        df.groupby(["YearMonth", "WarehouseName"], as_index=False)
        .agg(Spend=("EstimatedCost", "sum"))
        .sort_values("YearMonth")
    )
    return (
        alt.Chart(data).mark_bar()
        .encode(
            x=alt.X("YearMonth:N", title="Month", sort=list(data["YearMonth"].unique())),
            y=alt.Y("Spend:Q", title="Spend", axis=alt.Axis(format="$,.0f")),
            color=alt.Color("WarehouseName:N", title="Warehouse"),
            tooltip=[alt.Tooltip("YearMonth:N"), alt.Tooltip("WarehouseName:N"), alt.Tooltip("Spend:Q", format="$,.2f")]
        )
        .properties(height=400)
    )


def hourly_heatmap_chart(df):
    data = (
        df.groupby(["Hour", "WarehouseName"], as_index=False)
        .agg(Spend=("EstimatedCost", "sum"))
    )
    return (
        alt.Chart(data).mark_rect()
        .encode(
            x=alt.X("Hour:O", title="Hour of Day"),
            y=alt.Y("WarehouseName:N", title="Warehouse"),
            color=alt.Color("Spend:Q", title="Spend", scale=alt.Scale(scheme="orangered")),
            tooltip=[alt.Tooltip("Hour:O"), alt.Tooltip("WarehouseName:N"), alt.Tooltip("Spend:Q", format="$,.2f")]
        )
        .properties(height=280)
    )


def horizontal_bar(df, x_col, y_col, x_title="Spend", y_title=None):
    return (
        alt.Chart(df).mark_bar()
        .encode(
            x=alt.X(f"{x_col}:Q", title=x_title, axis=alt.Axis(format="$,.0f")),
            y=alt.Y(f"{y_col}:N", title=y_title or y_col, sort="-x"),
            tooltip=[alt.Tooltip(f"{y_col}:N"), alt.Tooltip(f"{x_col}:Q", format="$,.2f")]
        )
        .properties(height=400)
    )


# ===========================================================================
# LAYOUT
# ===========================================================================

st.title("❄️ Snowflake Cost & Performance Dashboard")
st.caption("Monitor spend, identify costly workloads, and uncover optimization opportunities.")

# ---------------------------------------------------------------------------
# Sidebar: Controls, Date Range, Thresholds
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Controls")
    st.button("🔄 Refresh Data", on_click=clear_all_caches)
    st.divider()

    st.subheader("📅 Date Range")
    today = date.today()
    default_start = today - timedelta(days=30)
    global_start = st.date_input("Start Date", value=default_start, key="global_start")
    global_end = st.date_input("End Date", value=today, key="global_end")

    st.divider()
    st.subheader("🚨 Alert Thresholds")
    warn_threshold = st.number_input("🟡 Warning ($)", min_value=0, value=5000, step=500, key="warn_thresh")
    critical_threshold = st.number_input("🔴 Critical ($)", min_value=0, value=10000, step=500, key="crit_thresh")

    st.divider()
    st.caption("Data cached 10 min. Click Refresh to reload.")

period_days = (global_end - global_start).days
prior_start = global_start - timedelta(days=period_days)
prior_end = global_start - timedelta(days=1)


# ---------------------------------------------------------------------------
# 5 TABS (consolidated from 10)
# ---------------------------------------------------------------------------

tab_overview, tab_monthly, tab_hourly, tab_chargeback, tab_queries = st.tabs([
    "📊 Overview",
    "📆 Monthly Spend",
    "🕐 Hourly Usage",
    "💳 Chargeback",
    "🔍 Query Analysis"
])


# ---------------------------------------------------------------------------
# TAB 1: Overview (merged Overview + Daily Spend)
# Only loads data when this tab renders (lazy via @st.fragment)
# ---------------------------------------------------------------------------

@st.fragment
def render_overview():
    with st.spinner("Loading spend data..."):
        df_current = clean_daily(load_cost_by_day(str(global_start), str(global_end)))
        df_prior = clean_daily_simple(load_cost_by_day_simple(str(prior_start), str(prior_end)))

    if df_current.empty:
        st.info("No spend data for selected period.")
        return

    filtered = filter_warehouses(df_current, "overview_wh")
    current_total = filtered["EstimatedCost"].sum()
    current_credits = filtered["TotalCredits"].sum()
    prior_total = df_prior["EstimatedCost"].sum() if not df_prior.empty else 0
    spend_delta = format_pct_delta(current_total, prior_total)

    daily_agg = filtered.groupby("StartDate", as_index=False).agg(Spend=("EstimatedCost", "sum")).sort_values("StartDate")
    avg_daily = daily_agg["Spend"].mean() if not daily_agg.empty else 0
    peak_day = daily_agg["Spend"].max() if not daily_agg.empty else 0

    top_wh = filtered.groupby("WarehouseName", as_index=False)["EstimatedCost"].sum().sort_values("EstimatedCost", ascending=False)
    top_warehouse = top_wh.iloc[0]["WarehouseName"] if not top_wh.empty else "N/A"

    metric_row([
        ("💰 Total Spend", format_currency(current_total), spend_delta),
        ("📊 Avg Daily", format_currency(avg_daily)),
        ("📈 Peak Day", format_currency(peak_day)),
        ("⚡ Credits", format_number(current_credits)),
        ("🏆 Top Warehouse", top_warehouse),
    ])

    show_spend_health(current_total, warn_threshold, critical_threshold)

    if prior_total > 0:
        st.caption(f"📈 Prior period ({prior_start} to {prior_end}): **{format_currency(prior_total)}** → Current: **{format_currency(current_total)}** ({spend_delta})")

    st.subheader("📈 Spend Trend (7-day rolling avg)")
    st.altair_chart(daily_spend_trend_chart(filtered), use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🏢 Warehouse Ranking")
        st.altair_chart(warehouse_spend_chart(filtered), use_container_width=True)
    with col2:
        st.subheader("📅 Per-Warehouse Trend")
        wh_daily = (
            filtered.groupby(["StartDate", "WarehouseName"], as_index=False)
            .agg(Spend=("EstimatedCost", "sum"))
            .sort_values("StartDate")
        )
        chart = (
            alt.Chart(wh_daily).mark_line(point=True)
            .encode(
                x=alt.X("StartDate:T", title="Date"),
                y=alt.Y("Spend:Q", title="Spend", axis=alt.Axis(format="$,.0f")),
                color=alt.Color("WarehouseName:N", title="Warehouse"),
                tooltip=[alt.Tooltip("StartDate:T"), alt.Tooltip("WarehouseName:N"), alt.Tooltip("Spend:Q", format="$,.2f")]
            )
            .properties(height=300)
        )
        st.altair_chart(chart, use_container_width=True)

    with st.expander("📄 Raw Daily Data"):
        st.dataframe(filtered, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Download CSV", filtered.to_csv(index=False), file_name="daily_spend.csv", mime="text/csv", key="dl_daily")


# ---------------------------------------------------------------------------
# TAB 2: Monthly Spend
# ---------------------------------------------------------------------------

@st.fragment
def render_monthly():
    with st.spinner("Loading monthly spend..."):
        df = clean_monthly(load_cost_by_month())

    if df.empty:
        st.info("No monthly spend data available.")
        return

    filtered = filter_warehouses(df, "monthly_wh")
    total_spend = filtered["EstimatedCost"].sum()
    total_credits = filtered["TotalCredits"].sum()

    monthly_totals = filtered.groupby("YearMonth", as_index=False)["EstimatedCost"].sum().sort_values("YearMonth", ascending=False)
    mom_delta = None
    if len(monthly_totals) >= 2:
        mom_delta = format_pct_delta(monthly_totals.iloc[0]["EstimatedCost"], monthly_totals.iloc[1]["EstimatedCost"])

    metric_row([
        ("💰 Total Spend", format_currency(total_spend), mom_delta),
        ("⚡ Credits", format_number(total_credits)),
        ("🏢 Warehouses", f"{filtered['WarehouseName'].nunique():,}"),
    ])

    st.altair_chart(monthly_spend_chart(filtered), use_container_width=True)

    with st.expander("📄 Raw Data"):
        st.dataframe(filtered, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Download CSV", filtered.to_csv(index=False), file_name="monthly_spend.csv", mime="text/csv", key="dl_monthly")


# ---------------------------------------------------------------------------
# TAB 3: Hourly Usage (with heatmap)
# ---------------------------------------------------------------------------

@st.fragment
def render_hourly():
    with st.spinner("Loading hourly usage..."):
        df = clean_hourly(load_hourly_cost())

    if df.empty:
        st.info("No hourly data available.")
        return

    months = sorted(df["YearMonth"].dropna().unique().tolist(), reverse=True)
    selected_month = st.selectbox("📆 Select Month", months, key="hourly_month")
    month_data = df[df["YearMonth"] == selected_month]
    month_data = filter_warehouses(month_data, "hourly_wh")

    total_spend = month_data["EstimatedCost"].sum()
    peak_hour_spend = month_data.groupby("Hour")["EstimatedCost"].sum().max() if not month_data.empty else 0

    metric_row([
        ("💰 Month Spend", format_currency(total_spend)),
        ("⚡ Credits", format_number(month_data["CreditsUsed"].sum())),
        ("📈 Peak Hour", format_currency(peak_hour_spend)),
    ])

    st.subheader("🗺️ Hour × Warehouse Heatmap")
    st.altair_chart(hourly_heatmap_chart(month_data), use_container_width=True)

    st.subheader("📊 Hourly Breakdown")
    hourly_agg = month_data.groupby(["Hour", "WarehouseName"], as_index=False).agg(Spend=("EstimatedCost", "sum"))
    hourly_bar = (
        alt.Chart(hourly_agg).mark_bar()
        .encode(
            x=alt.X("Hour:O", title="Hour of Day"),
            y=alt.Y("Spend:Q", title="Spend", axis=alt.Axis(format="$,.0f")),
            color=alt.Color("WarehouseName:N", title="Warehouse"),
            tooltip=[alt.Tooltip("Hour:O"), alt.Tooltip("WarehouseName:N"), alt.Tooltip("Spend:Q", format="$,.2f")]
        )
        .properties(height=320)
    )
    st.altair_chart(hourly_bar, use_container_width=True)

    with st.expander("📄 Raw Data"):
        st.dataframe(month_data, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Download CSV", month_data.to_csv(index=False), file_name="hourly.csv", mime="text/csv", key="dl_hourly")


# ---------------------------------------------------------------------------
# TAB 4: Chargeback (merged Role + Schema + Chargeback)
# ---------------------------------------------------------------------------

@st.fragment
def render_chargeback():
    st.caption("Assign costs by warehouse, role, user, or schema.")

    view_mode = st.radio(
        "🔀 View",
        ["By Role", "By Schema", "By Query (Warehouse/Role/User)"],
        horizontal=True,
        key="cb_mode"
    )

    if view_mode == "By Role":
        with st.spinner("Loading..."):
            df = load_cost_by_role()
            df["TotalEstimatedCost"] = pd.to_numeric(df["TotalEstimatedCost"], errors="coerce").fillna(0)
            df["TotalEstimatedCredits"] = pd.to_numeric(df["TotalEstimatedCredits"], errors="coerce").fillna(0)

        if df.empty:
            st.info("No role data.")
            return

        metric_row([
            ("💰 Total Spend", format_currency(df["TotalEstimatedCost"].sum())),
            ("⚡ Credits", format_number(df["TotalEstimatedCredits"].sum())),
            ("👥 Roles", f"{df['RoleName'].nunique():,}"),
        ])
        chart_data = df.head(20).rename(columns={"TotalEstimatedCost": "Spend"})
        st.altair_chart(horizontal_bar(chart_data, "Spend", "RoleName", "Spend", "Role"), use_container_width=True)
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Download CSV", df.to_csv(index=False), file_name="spend_by_role.csv", mime="text/csv", key="dl_role")

    elif view_mode == "By Schema":
        with st.spinner("Loading..."):
            df = load_cost_by_schema()
            df["TotalEstimatedCost"] = pd.to_numeric(df["TotalEstimatedCost"], errors="coerce").fillna(0)
            df["TotalEstimatedCredits"] = pd.to_numeric(df["TotalEstimatedCredits"], errors="coerce").fillna(0)
            df["FullName"] = df["DatabaseName"].astype(str) + "." + df["SchemaName"].astype(str)

        if df.empty:
            st.info("No schema data.")
            return

        metric_row([
            ("💰 Total Spend", format_currency(df["TotalEstimatedCost"].sum())),
            ("⚡ Credits", format_number(df["TotalEstimatedCredits"].sum())),
            ("🗄️ Schemas", f"{df['FullName'].nunique():,}"),
        ])
        chart_data = df.head(20).rename(columns={"TotalEstimatedCost": "Spend"})
        st.altair_chart(horizontal_bar(chart_data, "Spend", "FullName", "Spend", "Database.Schema"), use_container_width=True)
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Download CSV", df.to_csv(index=False), file_name="spend_by_schema.csv", mime="text/csv", key="dl_schema")

    else:
        with st.spinner("Loading..."):
            df = clean_query_cost(load_chargeback())

        if df.empty:
            st.info("No chargeback data.")
            return

        pivot_by = st.radio("Group by", ["WarehouseName", "RoleName", "UserName"], horizontal=True, key="cb_pivot")
        grouped = (
            df.groupby(pivot_by, as_index=False)
            .agg(TotalSpend=("EstimatedCost", "sum"), TotalCredits=("EstimatedCredits", "sum"), QueryCount=("QueryID", "count"), AvgRuntime=("ElapsedSeconds", "mean"))
            .sort_values("TotalSpend", ascending=False)
        )

        metric_row([
            ("💰 Total Spend", format_currency(grouped["TotalSpend"].sum())),
            ("📝 Queries", f"{grouped['QueryCount'].sum():,}"),
            ("🏷️ Groups", f"{len(grouped):,}"),
        ])
        st.altair_chart(horizontal_bar(grouped.head(20), "TotalSpend", pivot_by, "Total Spend", pivot_by), use_container_width=True)
        st.dataframe(grouped, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Download CSV", grouped.to_csv(index=False), file_name="chargeback.csv", mime="text/csv", key="dl_cb")


# ---------------------------------------------------------------------------
# TAB 5: Query Analysis (merged Costliest + Long Running + Patterns)
# ---------------------------------------------------------------------------

@st.fragment
def render_queries():
    st.caption("Inspect costly queries, long-running queries, and repeated query patterns.")

    view_mode = st.radio(
        "🔀 View",
        ["🔥 Costliest", "⏱️ Long Running", "🔁 Patterns"],
        horizontal=True,
        key="qa_mode"
    )

    if view_mode == "🔥 Costliest":
        with st.spinner("Loading..."):
            df = clean_query_cost(load_expensive_queries())

        if df.empty:
            st.info("No costly query data.")
            return

        filtered = filter_warehouses(df, "exp_wh")
        top_user = filtered.groupby("UserName", as_index=False)["EstimatedCost"].sum().sort_values("EstimatedCost", ascending=False).head(1)
        top_user_name = top_user.iloc[0]["UserName"] if not top_user.empty else "N/A"

        metric_row([
            ("💰 Total Spend", format_currency(filtered["EstimatedCost"].sum())),
            ("🔥 Highest Query", format_currency(filtered["EstimatedCost"].max())),
            ("⏱️ Avg Runtime", format_seconds(filtered["ElapsedSeconds"].mean())),
            ("👤 Top Spender", top_user_name),
        ])

        show_query_drilldown(filtered, "exp")

        st.dataframe(
            filtered[["QueryID", "WarehouseName", "RoleName", "UserName", "ElapsedSeconds", "EstimatedCost", "StartTime"]],
            hide_index=True, use_container_width=True
        )
        st.download_button("⬇️ Download CSV", filtered.to_csv(index=False), file_name="expensive_queries.csv", mime="text/csv", key="dl_exp")

    elif view_mode == "⏱️ Long Running":
        with st.spinner("Loading..."):
            df = clean_heavy(load_heavy_queries())

        if df.empty:
            st.info("No long running query data.")
            return

        filtered = filter_warehouses(df, "hvy_wh").copy()
        filtered["BytesScannedReadable"] = filtered["BytesScanned"].apply(format_bytes)
        filtered["BytesWrittenReadable"] = filtered["BytesWritten"].apply(format_bytes)

        metric_row([
            ("⏱️ Avg Runtime", format_seconds(filtered["ElapsedSeconds"].mean())),
            ("🐢 Longest", format_seconds(filtered["ElapsedSeconds"].max())),
            ("📦 Total Scanned", format_bytes(filtered["BytesScanned"].sum())),
            ("👤 Users", f"{filtered['UserName'].nunique():,}"),
        ])

        warehouse_sizing_recommendations(filtered)
        show_query_drilldown(filtered, "hvy")

        st.dataframe(
            filtered[["QueryID", "WarehouseName", "RoleName", "UserName", "ElapsedSeconds", "BytesScannedReadable", "StartTime"]],
            hide_index=True, use_container_width=True
        )
        st.download_button("⬇️ Download CSV", filtered.to_csv(index=False), file_name="heavy_queries.csv", mime="text/csv", key="dl_hvy")

    else:
        with st.spinner("Loading..."):
            df = clean_query_cost(load_expensive_queries())

        if df.empty:
            st.info("No query data.")
            return

        df["Pattern"] = df["QueryText"].apply(normalize_query)
        pattern_stats = (
            df.groupby("Pattern", as_index=False)
            .agg(
                Executions=("QueryID", "count"),
                TotalSpend=("EstimatedCost", "sum"),
                AvgSpend=("EstimatedCost", "mean"),
                AvgRuntime=("ElapsedSeconds", "mean"),
                TopUser=("UserName", lambda x: x.mode().iloc[0] if not x.mode().empty else "N/A")
            )
            .sort_values("TotalSpend", ascending=False)
        )

        metric_row([
            ("🔁 Unique Patterns", f"{len(pattern_stats):,}"),
            ("💰 Top Pattern Spend", format_currency(pattern_stats.iloc[0]["TotalSpend"]) if not pattern_stats.empty else "$0"),
            ("📝 Most Repeated", f"{pattern_stats['Executions'].max():,}x" if not pattern_stats.empty else "0"),
        ])

        st.info("💡 One cheap query run thousands of times can cost more than a single expensive query.")

        st.dataframe(
            pattern_stats.head(30).rename(columns={"TotalSpend": "Total Spend ($)", "AvgSpend": "Avg Spend ($)", "AvgRuntime": "Avg Runtime (s)"}),
            hide_index=True, use_container_width=True
        )
        st.download_button("⬇️ Download CSV", pattern_stats.to_csv(index=False), file_name="query_patterns.csv", mime="text/csv", key="dl_pat")


# ---------------------------------------------------------------------------
# Render — lazy: only active tab executes its fragment on interaction
# ---------------------------------------------------------------------------

with tab_overview:
    render_overview()

with tab_monthly:
    render_monthly()

with tab_hourly:
    render_hourly()

with tab_chargeback:
    render_chargeback()

with tab_queries:
    render_queries()
