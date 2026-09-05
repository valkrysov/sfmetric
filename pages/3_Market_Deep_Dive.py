import streamlit as st
import pandas as pd
from db import get_engine

from market_data import load_market_data

# -------------------
# CONFIG
# -------------------
from theme import inject_theme, render_page_header, render_section, render_kpi_row

inject_theme(page_title="Market Deep Dive", page_icon="🧠")
render_page_header("Market Deep Dive", "San Francisco · Detailed Market Analysis")

# -------------------
# DB
# -------------------

engine = get_engine()

# -------------------
# FILTERS
# -------------------
st.sidebar.header("Deep Filters")

property_type = st.sidebar.selectbox(
    "Property Type",
    ["ALL", "SFR", "CONDO", "TOWNHOUSE"]
)

import datetime

EARLIEST_TRUSTED_DATE = datetime.date(1993, 1, 1)

@st.cache_data(ttl=3600)
def get_data_date_range(_engine):
    query = "SELECT MIN(close_date) AS min_date, MAX(close_date) AS max_date FROM transactions"
    df_range = pd.read_sql(query, _engine)
    return df_range.iloc[0]["min_date"], df_range.iloc[0]["max_date"]

raw_min_date, max_date = get_data_date_range(engine)
min_date = max(raw_min_date, EARLIEST_TRUSTED_DATE)

date_range = st.sidebar.date_input(
    "Date Range",
    value=[],
    min_value=min_date,
    max_value=max_date
)


# -------------------
# LOAD DATA
# -------------------
df = load_market_data(
    engine,
    start_date=date_range[0] if len(date_range) == 2 else None,
    end_date=date_range[1] if len(date_range) == 2 else None,
    property_type=None if property_type == "ALL" else property_type
)

# =========================
# SAFETY: ALWAYS CREATE DERIVED FIELDS
# =========================
df = df[df["sqft"] > 0]

df["ppsf"] = df["sale_price"] / df["sqft"]
df["diff"] = df["sale_price"] - df["list_price"]

if df.empty:
    st.warning("No data")
    st.stop()


SF_ZIPS = {
    "94102","94103","94104","94105","94107","94108","94109","94110",
    "94111","94112","94114","94115","94116","94117","94118","94121",
    "94122","94123","94124","94127","94129","94130","94131","94132",
    "94133","94134","94158"
}

df["zip_code"] = (
    df["zip_code"]
    .astype(str)
    .str[:5]              # remove 94127-2406 → 94127
)

df = df[df["zip_code"].isin(SF_ZIPS)]

numeric_cols = ["sale_price", "list_price", "sqft"]

for col in numeric_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df = df.dropna(subset=numeric_cols)
df = df[df["sqft"] > 0]

df["diff"] = df["sale_price"] - df["list_price"]
df["ppsf"] = df["sale_price"] / df["sqft"]

def display_table(df, columns, sort_by=None, ascending=True, top_n=50):
    df_display = df.copy()

    # ensure numeric for sorting
    for col in ["sale_price", "list_price", "diff", "ppsf", "sqft",
                "median_price", "avg_price", "avg_ppsf", "sales"]:
        if col in df_display:
            df_display[col] = pd.to_numeric(df_display[col], errors="coerce")

    if sort_by:
        df_display = df_display.sort_values(by=sort_by, ascending=ascending)

    df_display = df_display.head(top_n)
    df_display = df_display[columns]

    # 🔥 FORMAT + FORCE LEFT ALIGN (convert to string ONLY here)
    for col in df_display.columns:
        if col in ["sale_price", "list_price", "median_price", "avg_price"]:
            df_display[col] = df_display[col].map(lambda x: f"${x:,.0f}")
        elif col == "diff":
            df_display[col] = df_display[col].map(lambda x: f"${x:,.0f}")
        elif col == "ppsf" or col == "avg_ppsf":
            df_display[col] = df_display[col].map(lambda x: f"${x:,.0f}")
        elif col == "sqft":
            df_display[col] = df_display[col].map(lambda x: f"{x:,.0f}")
        else:
            df_display[col] = df_display[col].astype(str)

    st.dataframe(df_display, use_container_width=True)
# -------------------
# 🔥 1. OVER / UNDER ASKING
# -------------------
render_section("Market Behavior", accent="#2563EB")

over = (df["diff"] > 0).sum()
under = (df["diff"] < 0).sum()
equal = (df["diff"] == 0).sum()

render_kpi_row([
    ("Over Asking", f"{over:,}", "pos"),
    ("Under Asking", f"{under:,}", "neg"),
    ("At Asking", f"{equal:,}", ""),
])

# -------------------
# 🔥 2. TOP DEALS (UNDERPRICED)
# -------------------
render_section("💰 Most Underpriced Deals", accent="#099250")

# 🔥 TRUE UNDERPRICED LOGIC
df["deal_score"] = df["diff"] / df["list_price"]

top_n = st.selectbox("Show top deals", [20, 50, 100], index=1)

df_display = (
    df.sort_values(by="deal_score", ascending=True)  # ✅ MOST NEGATIVE FIRST
      .head(top_n)
      .copy()
)

df_display = df_display[
    ["full_address", "sale_price", "list_price", "diff", "sqft", "ppsf"]
]

display_table(
    df=df_display,
    columns=df_display.columns.tolist()
)
# -------------------
# 🔥 3. MOST OVERPRICED
# -------------------
render_section("⚠️ Most Overpriced Sales", accent="#B42318")

display_table(
    df=df,
    columns=["full_address", "sale_price", "list_price", "diff", "sqft", "ppsf"],
    sort_by="diff",
    ascending=False   # MOST overpriced = biggest positive diff
)


# -------------------
# 🔥 4. ZIP CODE ANALYSIS
# -------------------
render_section("📍 Zip Code Breakdown", accent="#2563EB")

zip_stats = (
    df.groupby("zip_code")
      .agg(
          sales=("sale_price", "count"),
          median_price=("sale_price", "median"),
          avg_price=("sale_price", "mean"),
          avg_ppsf=("ppsf", "mean")
      )
      .reset_index()
)

display_table(
    df=zip_stats,
    columns=["zip_code", "sales", "median_price", "avg_price", "avg_ppsf"],
    sort_by="median_price",
    ascending=False
)


# -------------------
# 🔥 5. PRICE SEGMENTS
# -------------------
render_section("🏷️ Market Segments", accent="#2563EB")

bins = [0, 1e6, 2e6, 5e6, 10e6, 1e9]
labels = ["<1M", "1-2M", "2-5M", "5-10M", "10M+"]

df["segment"] = pd.cut(df["sale_price"], bins=bins, labels=labels)

segment_stats = df.groupby("segment")["sale_price"].count()

st.bar_chart(segment_stats)

# -------------------
# 🔥 6. LUXURY MARKET
# -------------------
render_section("💎 Luxury Market (Top 5%)", accent="#2563EB")

threshold = df["sale_price"].quantile(0.95)

luxury = df[df["sale_price"] >= threshold]

render_kpi_row([
    ("Luxury Threshold", f"${threshold:,.0f}", ""),
])

display_cols = ["full_address", "sale_price", "list_price", "diff", "sqft", "ppsf"]

df_display = luxury[display_cols].copy()

# -------------------
# FORMAT (forces LEFT ALIGN)
# -------------------

display_table(
    df=luxury,
    columns=["full_address", "sale_price", "list_price", "diff", "sqft", "ppsf"],
    sort_by="diff",
    ascending=False   # biggest overpay first
)
