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

st.title("📊 San Francisco Market Dashboard")

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

date_range = st.sidebar.date_input(
    "Date Range",
    value=[],
    min_value=pd.to_datetime("2005-01-01"),
    max_value=pd.to_datetime("today"),
    key="date_range_filter"
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
st.subheader("🌉 San Francisco — Citywide")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Median Price", f"${df_city['sale_price'].median():,.0f}")
col2.metric("Avg Price", f"${df_city['sale_price'].mean():,.0f}")
col3.metric("Avg PPSF", f"${df_city['ppsf'].mean():,.0f}")

city_over = (
    df_city["sale_price"].sum() /
    df_city["list_price"].sum()
) - 1

col4.metric("% Over Asking", f"{city_over*100:.1f}%")

# -------------------
# SELECTED AREA
# -------------------
st.subheader(f"📍 Selected Area: {selected_zip}")

if not df_filtered.empty:
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Median Price", f"${df_filtered['sale_price'].median():,.0f}")
    col2.metric("Avg Price", f"${df_filtered['sale_price'].mean():,.0f}")
    col3.metric("Avg PPSF", f"${df_filtered['ppsf'].mean():,.0f}")

    filtered_over = (
        df_filtered["sale_price"].sum() /
        df_filtered["list_price"].sum()
    ) - 1

    col4.metric("% Over Asking", f"{filtered_over*100:.1f}%")

# ==================================================
# MARKET SIGNAL
# ==================================================
#st.markdown("### 🧠 Market Signal Engine")

#signal_df = df_city if selected_zip == "ALL" else df_filtered
#active_df = df_active_city if selected_zip == "ALL" else df_active_filtered

#signal = compute_market_signal(signal_df, active_df)

#label = signal["label"]
#score = signal["confidence"]

#if label == "SELLER":
#    st.success(f"🔥 SELLER MARKET — {score}/100")
#elif label == "BALANCED":
#    st.info(f"⚖️ BALANCED MARKET — {score}/100")
#else:
#    st.warning(f"📉 BUYER MARKET — {score}/100")


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

st.markdown("### 🧠 Market Signal Engine")
#signal_df = df_city if selected_zip == "ALL" else df_filtered
#active_df = df_active_city if selected_zip == "ALL" else df_active_filtered

signal = compute_market_signal(
    signal_df,
    #active_signal_df
    active_df 	
)


components = signal["components"]

label = signal["label"]

market_score = signal["confidence"]


st.caption(
    f"Market conditions for {signal_scope} "
    f"based on "
    f"{components['historical_transactions']:,} "
    f"historical transactions and "
    f"{components['active_listings']:,} "
    f"active listings"
)


if label == "SELLER":

    st.success(
        f"🔥 SELLER MARKET — Market Score: {market_score}/100"
    )

elif label == "BALANCED":

    st.info(
        f"⚖️ BALANCED MARKET — Market Score: {market_score}/100"
    )

else:

    st.warning(
        f"📉 BUYER MARKET — Market Score: {market_score}/100"
    )


# -------------------
# SIGNAL KPIs
# -------------------

col1, col2, col3, col4 = st.columns(4)


col1.metric(
    "Sale / List",
    f"{(1 + components['over_asking']) * 100:.1f}%"
)


col2.metric(
    "Historical Sales",
    f"{components['historical_transactions']:,}"
)


col3.metric(
    "Active Listings",
    f"{components['active_listings']:,}"
)


col4.metric(
    "Market Score",
    f"{market_score}/100"
)









# ==================================================
# OPPORTUNITY ENGINE (RIGHT PLACE)
# ==================================================
st.markdown("### 🚀 Opportunity Engine")

df_opportunities = compute_opportunity_engine(active_df, signal_df)

st.caption(f"Top opportunities: {len(df_opportunities):,}")

if not df_opportunities.empty:

    df_display = (
        df_opportunities
        .sort_values("opportunity_score", ascending=False)
        .head(20)
    )

    st.dataframe(
        df_display[[
            "address",
            "zip_code",
            "property_type",
            "list_price",
            "list_ppsf",
            "estimated_value",
            "discount_pct",
            "opportunity_score"
        ]],
        use_container_width=True,
        hide_index=True
    )

# ==================================================
# MAP
# ==================================================
st.subheader("Sales Map")

df_map = df_filtered.sample(min(len(df_filtered), 3000))

fig_map = px.scatter_mapbox(
    df_map,
    lat="latitude",
    lon="longitude",
    color="sale_price",
    size="sale_price",
    zoom=11
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
st.subheader("📈 Price Trend")

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
st.subheader("📦 Price Segments")

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
st.subheader("📋 Recent Sales")

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
