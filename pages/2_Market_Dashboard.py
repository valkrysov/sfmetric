import streamlit as st
import pandas as pd
import plotly.express as px
#from sqlalchemy import create_engine
from db import get_engine
from market_data import load_market_data


st.markdown("""
<style>
/* Fix date picker popup position */
div[data-baseweb="popover"] {
    transform: translateY(40px) !important;
}
</style>
""", unsafe_allow_html=True)

# -------------------
# CONFIG
# -------------------
#st.set_page_config(layout="wide")
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
    ["ALL", "SFR", "CONDO", "TOWNHOUSE"]
)

#date_range = st.sidebar.date_input("Date Range", [])
date_range = st.sidebar.date_input(
    "Date Range",
    value=[],
    min_value=pd.to_datetime("2005-01-01"),
    max_value=pd.to_datetime("today")
)

# -------------------
# LOAD DATA
# -------------------
df_all = load_market_data(
    engine,
    start_date=date_range[0] if len(date_range) == 2 else None,
    end_date=date_range[1] if len(date_range) == 2 else None,
    property_type=None if property_type == "ALL" else property_type
).copy(deep=True)



#✅ CLEAN SOLUTION (drop-in fix)
#🔧 Add this RIGHT AFTER loading df_all
def clean_zip_codes(df):
    df = df.copy()

    # Convert to string
    df["zip_code"] = df["zip_code"].astype(str)

    # Remove spaces and decimals (e.g., '94110.0')
    df["zip_code"] = df["zip_code"].str.strip().str.replace(r"\.0$", "", regex=True)

    # Keep only 5-digit numeric ZIPs
    df = df[df["zip_code"].str.match(r"^\d{5}$")]

    # Keep only SF ZIP codes (94XXX)
    df = df[df["zip_code"].str.startswith("94")]

    return df

SF_ZIPS = {
    "94102","94103","94104","94105","94107","94108","94109","94110",
    "94111","94112","94114","94115","94116","94117","94118","94121",
    "94122","94123","94124","94127","94129","94130","94131","94132",
    "94133","94134","94158"
}

df_all = df_all[df_all["zip_code"].isin(SF_ZIPS)]

#✅ Apply it:
#df_all = clean_zip_codes(df_all)

min_date = pd.to_datetime(df_all["sale_date"]).min()
max_date = pd.to_datetime(df_all["sale_date"]).max()

df_all.reset_index(drop=True, inplace=True)

if df_all.empty:
    st.warning("No data")
    st.stop()

# -------------------
# LOCATION FILTERS
# -------------------
zip_codes = sorted(df_all["zip_code"].dropna().unique())

selected_zip = st.sidebar.selectbox(
    "Select ZIP Code",
    ["ALL"] + list(zip_codes)
)

# -------------------
# DATASETS (CRITICAL SEPARATION)
# -------------------

# CITY (NEVER FILTERED)
df_city = df_all.copy()

# FILTERED (USER SELECTION ONLY)
df_filtered = df_all.copy()

if selected_zip != "ALL":
    df_filtered = df_filtered[df_filtered["zip_code"] == selected_zip]

# -------------------
# CLEAN DATA (IMPORTANT FOR PPSF)
# -------------------

def clean_data(df):
    df = df.copy()

    df["sqft"] = pd.to_numeric(df["sqft"], errors="coerce")
    df["sale_price"] = pd.to_numeric(df["sale_price"], errors="coerce")

    df = df[
        df["sqft"].notnull() &
        df["sale_price"].notnull() &
        (df["sqft"] > 500) &
        (df["sqft"] < 6000) &
        (df["sale_price"] > 100000) &
        (df["sale_price"] < 10000000)
    ]

    return df

df_city = clean_data(df_city)
df_filtered = clean_data(df_filtered)

# -------------------
# FEATURES (STRICT SEPARATION)
# -------------------

df_city = df_city.copy()
df_filtered = df_filtered.copy()

# CITY
df_city["ppsf"] = df_city["sale_price"] / df_city["sqft"]
df_city["diff"] = df_city["sale_price"] - df_city["list_price"]
df_city["over_asking_pct"] = (
    (df_city["sale_price"] - df_city["list_price"]) /
    df_city["list_price"]
)

# FILTERED
df_filtered["ppsf"] = df_filtered["sale_price"] / df_filtered["sqft"]
df_filtered["diff"] = df_filtered["sale_price"] - df_filtered["list_price"]
df_filtered["over_asking_pct"] = (
    (df_filtered["sale_price"] - df_filtered["list_price"]) /
    df_filtered["list_price"]
)

df_city = df_city[
    (df_city["list_price"] > 100000) &
    (df_city["sale_price"] > 100000)
]

df_filtered = df_filtered[
    (df_filtered["list_price"] > 100000) &
    (df_filtered["sale_price"] > 100000)
]



df_city = df_city[
    (df_city["over_asking_pct"] > -0.5) &
    (df_city["over_asking_pct"] < 0.5)
]

df_filtered = df_filtered[
    (df_filtered["over_asking_pct"] > -0.5) &
    (df_filtered["over_asking_pct"] < 0.5)
]

# -------------------
# KPIs
# -------------------
#col1, col2, col3, col4 = st.columns(4)


# -------------------
# CITY KPIs (STATIC)
# -------------------
st.subheader("🌉 San Francisco — Citywide")

col1, col2, col3, col4 = st.columns(4)

city_ppsf = df_city["ppsf"].mean()
filtered_ppsf = df_filtered["ppsf"].mean()

col1.metric("Median Price", f"${df_city['sale_price'].median():,.0f}")
col2.metric("Avg Price", f"${df_city['sale_price'].mean():,.0f}")
col3.metric("Avg PPSF", f"${city_ppsf:,.0f}")
#city_over_asking = (
#    (df_city["sale_price"].sum() - df_city["list_price"].sum())
#    / df_city["list_price"].sum()
#)

#col4.metric(
#    "% Over Asking",
#    f"{city_over_asking * 100:.1f}%"
#)

city_over_asking = (
    df_city["sale_price"].sum() /
    df_city["list_price"].sum()
) - 1

col4.metric("% Over Asking", f"{city_over_asking*100:.1f}%")

# -------------------
# FILTERED KPIs (DYNAMIC)
# -------------------
st.subheader(f"📍 Selected Area: {selected_zip}")

if not df_filtered.empty:

    col1, col2, col3, col4 = st.columns(4)

    #filtered_ppsf = df_filtered["sale_price"].sum() / df_filtered["sqft"].sum()

    col1.metric("Median Price", f"${df_filtered['sale_price'].median():,.0f}")
    col2.metric("Avg Price", f"${df_filtered['sale_price'].mean():,.0f}")
    col3.metric("Avg PPSF", f"${filtered_ppsf:,.0f}")
    filtered_over_asking = (
    (df_filtered["sale_price"].sum() - df_filtered["list_price"].sum())
    / df_filtered["list_price"].sum()
    )

    col4.metric(
    "% Over Asking",
    f"{filtered_over_asking * 100:.1f}%"
    )
else:
    st.warning("No data for selected ZIP")

# -------------------
# MAP
# -------------------
st.subheader("Sales Map")

df_map = df_filtered.sample(min(len(df_filtered), 3000))

fig_map = px.scatter_mapbox(
    df_map,
    lat="latitude",
    lon="longitude",
    color="sale_price",
    size="sale_price",
    hover_name="full_address",
    hover_data=["zip_code", "sale_price"],
    zoom=11
)

if selected_zip != "ALL":
    df_highlight = df_filtered.copy()

    fig_map.add_scattermapbox(
        lat=df_highlight["latitude"],
        lon=df_highlight["longitude"],
        mode="markers",
        marker=dict(size=10, color="red"),
        name="Selected ZIP"
    )

fig_map.update_layout(mapbox_style="open-street-map")

st.plotly_chart(fig_map, use_container_width=True, key="main_map")



# -------------------
# CHARTS
# -------------------
col1, col2 = st.columns(2)


with col1:
    fig1 = px.histogram(df_filtered, x="sale_price")
    st.plotly_chart(fig1, use_container_width=True, key="price_hist")

with col2:
    fig2 = px.histogram(df_filtered, x="diff")
    st.plotly_chart(fig2, use_container_width=True, key="diff_hist")

# -------------------
# TREND
# -------------------

monthly = df_filtered.groupby("month")["sale_price"].median().reset_index()

fig3 = px.line(monthly, x="month", y="sale_price")
st.plotly_chart(fig3, use_container_width=True)


# -------------------
# PRICE SEGMENTS
# -------------------
st.subheader("Price Segments")

bins = [0, 1e6, 2e6, 5e6, 10e6, 1e9]
labels = ["<1M", "1-2M", "2-5M", "5-10M", "10M+"]

df_filtered["bucket"] = pd.cut(df_filtered["sale_price"], bins=bins, labels=labels)
st.bar_chart(df_filtered["bucket"].value_counts().sort_index())


# -------------------
# TABLE
# -------------------
st.subheader("Recent Sales")

# -------------------
# PREP DISPLAY
# -------------------
display_cols = ["full_address", "sale_price", "list_price", "diff", "sqft", "ppsf", "sale_date"]

df_display = df_filtered[display_cols].copy()

# ✅ SORT FIRST (numeric)
df_display = df_display.sort_values(by="diff", ascending=False)

# -------------------
# FORMATTING (after sorting)
# -------------------
df_display["sale_price"] = df_display["sale_price"].map(lambda x: f"${x:,.0f}")
df_display["list_price"] = df_display["list_price"].map(lambda x: f"${x:,.0f}")
df_display["diff"] = df_display["diff"].map(lambda x: f"${x:,.0f}")
df_display["sqft"] = df_display["sqft"].map(lambda x: f"{int(x):,}")
df_display["ppsf"] = df_display["ppsf"].map(lambda x: f"${x:,.0f}")

st.dataframe(
    df_display,
    use_container_width=True
)
