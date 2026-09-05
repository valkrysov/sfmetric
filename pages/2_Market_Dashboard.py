import streamlit as st
import pandas as pd
import plotly.express as px

from db import get_engine
from market_data import (
    load_market_data,
    load_active_listings,
    compute_market_signal,
    compute_opportunity_engine
)
from theme import inject_theme, render_page_header, render_section, render_kpi_row, render_status_banner

inject_theme(page_title="Market Dashboard", page_icon="📊")
render_page_header("Market Dashboard", "San Francisco · Live Market Data")

# -------------------
# DB
# -------------------
engine = get_engine()

# -------------------
# SIDEBAR
# -------------------
st.sidebar.header("Filters")

property_type = st.sidebar.selectbox(
    "Property Type",
    ["ALL", "SFR", "CONDO", "TOWNHOUSE"],
    key="property_type_filter"
)

import datetime

EARLIEST_TRUSTED_DATE = datetime.date(1993, 1, 1)

@st.cache_data(ttl=3600)
def get_data_date_range(_engine):
    query = "SELECT MIN(close_date) AS min_date, MAX(close_date) AS max_date FROM transactions"
    df = pd.read_sql(query, _engine)
    return df.iloc[0]["min_date"], df.iloc[0]["max_date"]

raw_min_date, max_date = get_data_date_range(engine)
min_date = max(raw_min_date, EARLIEST_TRUSTED_DATE)


date_range = st.sidebar.date_input(
    "Date Range",
    value=(),
    min_value=min_date,
    max_value=max_date
)
# -------------------
# LOAD DATA
# -------------------
df_all = load_market_data(
    engine,
    start_date=date_range[0] if len(date_range) == 2 else None,
    end_date=date_range[1] if len(date_range) == 2 else None,
    property_type=None if property_type == "ALL" else property_type
)

df_active = load_active_listings(
    engine,
    property_type=None if property_type == "ALL" else property_type
)

# -------------------
# ZIP CLEANING
# -------------------
def clean_zip(df):
    df = df.copy()
    df["zip_code"] = (
        df["zip_code"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )
    return df

df_all = clean_zip(df_all)
df_active = clean_zip(df_active)

# -------------------
# SF FILTER
# -------------------
SF_ZIPS = {
    "94102","94103","94104","94105","94107","94108","94109","94110",
    "94111","94112","94114","94115","94116","94117","94118","94121",
    "94122","94123","94124","94127","94129","94130","94131","94132",
    "94133","94134","94158"
}

df_all = df_all[df_all["zip_code"].isin(SF_ZIPS)]
df_active = df_active[df_active["zip_code"].isin(SF_ZIPS)]

if df_all.empty:
    st.warning("No historical data")
    st.stop()

# -------------------
# ZIP SELECTOR (ONLY ONCE)
# -------------------
zip_codes = sorted(df_all["zip_code"].dropna().unique())

selected_zip = st.sidebar.selectbox(
    "Select ZIP Code",
    ["ALL"] + list(zip_codes),
    key="zip_filter"
)

# -------------------
# DATASETS
# -------------------
df_city = df_all.copy()
df_filtered = df_all.copy()

df_active_city = df_active.copy()
df_active_filtered = df_active.copy()

if selected_zip != "ALL":
    df_filtered = df_filtered[df_filtered["zip_code"] == selected_zip]
    df_active_filtered = df_active_filtered[df_active_filtered["zip_code"] == selected_zip]

# -------------------
# CLEAN DATA
# -------------------
def clean_data(df):
    df = df.copy()
    df["sqft"] = pd.to_numeric(df["sqft"], errors="coerce")
    df["sale_price"] = pd.to_numeric(df["sale_price"], errors="coerce")

    return df[
        df["sqft"].notna() &
        df["sale_price"].notna() &
        (df["sqft"] > 500) &
        (df["sqft"] < 6000)
    ]

df_city = clean_data(df_city)
df_filtered = clean_data(df_filtered)

# -------------------
# FEATURES
# -------------------
for df in [df_city, df_filtered]:
    df["ppsf"] = df["sale_price"] / df["sqft"]
    df["diff"] = df["sale_price"] - df["list_price"]
    df["over_asking_pct"] = (
        (df["sale_price"] - df["list_price"]) / df["list_price"]
    )

# -------------------
# KPIs
# -------------------
render_section("San Francisco — Citywide", accent="#2563EB")

city_over = (df_city["sale_price"].sum() / df_city["list_price"].sum()) - 1

render_kpi_row([
    ("Median Price", f"${df_city['sale_price'].median():,.0f}", ""),
    ("Avg Price", f"${df_city['sale_price'].mean():,.0f}", ""),
    ("Avg PPSF", f"${df_city['ppsf'].mean():,.0f}", ""),
    ("% Over Asking", f"{city_over*100:.1f}%", "pos" if city_over > 0 else "neg"),
])

# -------------------
# SELECTED AREA
# -------------------
render_section(f"Selected Area — {selected_zip}", accent="#2563EB")

if not df_filtered.empty:
    filtered_over = (df_filtered["sale_price"].sum() / df_filtered["list_price"].sum()) - 1

    render_kpi_row([
        ("Median Price", f"${df_filtered['sale_price'].median():,.0f}", ""),
        ("Avg Price", f"${df_filtered['sale_price'].mean():,.0f}", ""),
        ("Avg PPSF", f"${df_filtered['ppsf'].mean():,.0f}", ""),
        ("% Over Asking", f"{filtered_over*100:.1f}%", "pos" if filtered_over > 0 else "neg"),
    ])

# ==================================================
# DEFINE CURRENT ANALYSIS SCOPE
# ==================================================

if selected_zip == "ALL":

    signal_df = df_city

    #active_signal_df = df_active_city
    active_df = df_active_city

    signal_scope = "San Francisco"

else:

    signal_df = df_filtered

    #active_signal_df = df_active_filtered
    active_df = df_active_filtered

    signal_scope = f"ZIP {selected_zip}"





# ==================================================
# MARKET SIGNAL ENGINE
# ==================================================

signal = compute_market_signal(signal_df, active_df)
components = signal["components"]
label = signal["label"]
market_score = signal["confidence"]

signal_meta = {
    "SELLER":   ("seller",   "#099250", "🔥 SELLER MARKET"),
    "BALANCED": ("balanced", "#B54708", "⚖️ BALANCED MARKET"),
}
kind, accent, banner_label = signal_meta.get(label, ("buyer", "#B42318", "📉 BUYER MARKET"))

render_section(
    "Market Signal Engine",
    caption=(
        f"Based on {components['historical_transactions']:,} historical transactions "
        f"and {components['active_listings']:,} active listings in {signal_scope}"
    ),
    accent=accent
)

render_status_banner(banner_label, f"SCORE {market_score}/100", kind=kind)

render_kpi_row([
    ("Sale / List", f"{(1 + components['over_asking']) * 100:.1f}%", ""),
    ("Historical Sales", f"{components['historical_transactions']:,}", ""),
    ("Active Listings", f"{components['active_listings']:,}", ""),
    ("Market Score", f"{market_score}/100", kind if kind != "balanced" else ""),
])


# ==================================================
# OPPORTUNITY ENGINE
# ==================================================
render_section("Opportunity Engine", caption="Underpriced active listings", accent="#099250")

df_opportunities = compute_opportunity_engine(active_df, signal_df).copy()

if df_opportunities.empty:
    st.markdown(
        f'<div class="sfm-section-caption">No qualified opportunities found in {signal_scope}.</div>',
        unsafe_allow_html=True
    )
else:
    high_conviction = len(df_opportunities[df_opportunities["opportunity_score"] >= 80])

    render_kpi_row([
        ("Active Listings", f"{len(active_df):,}", ""),
        ("Qualified Opportunities", f"{len(df_opportunities):,}", "pos"),
        ("High-Conviction", f"{high_conviction:,}", "pos"),
    ])


    # --------------------------------------------------
    # TOP N SELECTOR
    # --------------------------------------------------

    opportunity_limit = st.radio(
        "Show Top Opportunities",
        [10, 20, 30],
        horizontal=True,
        key="opportunity_limit"
    )

    df_display_opportunities = (
        df_opportunities
        .head(opportunity_limit)
        .copy()
    )

    # --------------------------------------------------
    # DISPLAY COLUMNS
    # --------------------------------------------------

    opportunity_cols = [
        "full_address",
        "zip_code",
        "property_type",
        "list_price",
        "estimated_value",
        "discount_pct",
        "list_ppsf",
        "benchmark_ppsf",
        "opportunity_score",
        "days_on_market"
    ]

    available_cols = [
        col
        for col in opportunity_cols
        if col in df_display_opportunities.columns
    ]

    display = df_display_opportunities[
        available_cols
    ].copy()

    # --------------------------------------------------
    # ADD RANK
    # --------------------------------------------------

    display.insert(
        0,
        "Rank",
        range(1, len(display) + 1)
    )

    # --------------------------------------------------
    # FRIENDLY COLUMN NAMES
    # --------------------------------------------------

    display = display.rename(
        columns={
            "full_address": "Property",
            "zip_code": "ZIP",
            "property_type": "Type",
            "list_price": "List Price",
            "estimated_value": "Estimated Value",
            "discount_pct": "Discount",
            "list_ppsf": "List PPSF",
            "benchmark_ppsf": "Comp PPSF",
            "opportunity_score": "Opportunity Score",
            "days_on_market": "DOM"
        }
    )

    # --------------------------------------------------
    # FORMAT
    # --------------------------------------------------

    if "List Price" in display.columns:
        display["List Price"] = display["List Price"].map(
            lambda x: f"${x:,.0f}"
        )

    if "Estimated Value" in display.columns:
        display["Estimated Value"] = display["Estimated Value"].map(
            lambda x: f"${x:,.0f}"
        )

    if "Discount" in display.columns:
        display["Discount"] = display["Discount"].map(
            lambda x: f"{x * 100:.1f}%"
        )

    if "List PPSF" in display.columns:
        display["List PPSF"] = display["List PPSF"].map(
            lambda x: f"${x:,.0f}"
        )

    if "Comp PPSF" in display.columns:
        display["Comp PPSF"] = display["Comp PPSF"].map(
            lambda x: f"${x:,.0f}"
        )

    if "Opportunity Score" in display.columns:
        display["Opportunity Score"] = display[
            "Opportunity Score"
        ].map(
            lambda x: f"{x:.0f}"
        )

    # --------------------------------------------------
    # OPPORTUNITY TABLE
    # --------------------------------------------------

    st.caption("👉 Click a property to open full details")

    # Build a per-row link to the Property Intelligence page, carrying
    # the property_id as a query parameter.
    display["Open"] = (
        "/Property_Intelligence?property_id="
        + df_display_opportunities["property_id"].astype(str)
    )

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Open": st.column_config.LinkColumn(
                "Open",
                display_text="View details →"
            )
        }
    )







# ==================================================
# MAP
# ==================================================
render_section("Sales Map", accent="#2563EB")

df_map = df_filtered.sample(min(len(df_filtered), 3000))

fig_map = px.scatter_mapbox(
    df_map,
    lat="latitude",
    lon="longitude",
    color="sale_price",
    size="sale_price",
    zoom=11,
    center={"lat": 37.7749, "lon": -122.4194}
)

fig_map.update_layout(mapbox_style="open-street-map")

st.plotly_chart(fig_map, use_container_width=True)

# -------------------
# CHARTS
# -------------------
col1, col2 = st.columns(2)

with col1:
    fig1 = px.histogram(
        df_filtered,
        x="sale_price",
        title="Distribution of Sale Prices"
    )
    st.plotly_chart(fig1, use_container_width=True)

with col2:
    fig2 = px.histogram(
        df_filtered,
        x="diff",
        title="Sale vs List Price Difference"
    )
    st.plotly_chart(fig2, use_container_width=True)

# -------------------
# TREND
# -------------------
render_section("Price Trend", accent="#2563EB")

monthly = (
    df_filtered
    .groupby("month")["sale_price"]
    .median()
    .reset_index()
)

fig3 = px.line(
    monthly,
    x="month",
    y="sale_price",
    title="Median Price Over Time"
)

st.plotly_chart(fig3, use_container_width=True)

# -------------------
# PRICE SEGMENTS
# -------------------
render_section("Price Segments", accent="#2563EB")

bins = [0, 1e6, 2e6, 5e6, 10e6, 1e9]
labels = ["<1M", "1-2M", "2-5M", "5-10M", "10M+"]

df_filtered["bucket"] = pd.cut(
    df_filtered["sale_price"],
    bins=bins,
    labels=labels
)

st.bar_chart(
    df_filtered["bucket"]
    .value_counts()
    .sort_index()
)

# -------------------
# RECENT SALES
# -------------------
render_section("Recent Sales", accent="#2563EB")

display_cols = [
    "full_address",
    "sale_price",
    "list_price",
    "diff",
    "sqft",
    "ppsf",
    "sale_date"
]

available_cols = [
    c for c in display_cols if c in df_filtered.columns
]

df_display = df_filtered[available_cols].copy()

# Sort BEFORE formatting
df_display = df_display.sort_values(
    by="diff",
    ascending=False
)

# Formatting
if "sale_price" in df_display:
    df_display["sale_price"] = df_display["sale_price"].map(lambda x: f"${x:,.0f}")

if "list_price" in df_display:
    df_display["list_price"] = df_display["list_price"].map(lambda x: f"${x:,.0f}")

if "diff" in df_display:
    df_display["diff"] = df_display["diff"].map(lambda x: f"${x:,.0f}")

if "sqft" in df_display:
    df_display["sqft"] = df_display["sqft"].map(lambda x: f"{int(x):,}")

if "ppsf" in df_display:
    df_display["ppsf"] = df_display["ppsf"].map(lambda x: f"${x:,.0f}")

st.dataframe(
    df_display,
    use_container_width=True,
    height=400
)
