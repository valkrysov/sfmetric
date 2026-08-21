# ==========================================
# SF HOUSING INTELLIGENCE — MAIN DASHBOARD
# ==========================================

import streamlit as st
import pandas as pd
import numpy as np
import psycopg2
import plotly.express as px
from db import get_engine

# ==========================================
# CONFIG
# ==========================================

st.set_page_config(
    page_title="SF Housing Intelligence",
    layout="wide"
)

#DB_CONFIG = {
#    "dbname": "sfmetric",
#    "user": "postgres",
#    "password": "Main&3&One",
#    "host": "localhost",
#    "port": "5433"
#}

# ==========================================
# DB CONNECTION
# ==========================================

engine = get_engine()

#@st.cache_resource
#def get_connection():
#    return psycopg2.connect(**DB_CONFIG)

#conn = get_connection()

# ==========================================
# HEADER
# ==========================================

st.title("🏙️ SF Housing Intelligence")
st.markdown("Live Real Estate Analytics — San Francisco")


# ==========================================
# 🔥 FILTERS (ADD HERE)
# ==========================================

st.sidebar.header("Filters")

min_price = st.sidebar.number_input(
    "Min Price",
    value=500000
)

max_price = st.sidebar.number_input(
    "Max Price",
    value=5000000
)

property_type = st.sidebar.selectbox(
    "Property Type",
    ["ALL", "SFR", "CONDO", "TOWNHOUSE"]
)


# ==========================================
# CORE QUERY FUNCTION
# ==========================================

@st.cache_data(ttl=3600)  # 1 hour — your data only refreshes monthly anyway
def run_query(query, params=None):
    return pd.read_sql(query, engine, params=params)

# ==========================================
# 1. INVENTORY BY NEIGHBORHOOD
# ==========================================

st.subheader("📊 Inventory by Neighborhood")

df_inventory = run_query("""
SELECT
    p.neighborhood,
    COUNT(*) AS listings
FROM active_listings a
JOIN properties p USING (property_id)
WHERE
    p.neighborhood IS NOT NULL
    AND a.list_price BETWEEN %s AND %s
    AND (%s = 'ALL' OR p.property_type = %s)
GROUP BY p.neighborhood
ORDER BY listings DESC
""", (min_price, max_price, property_type, property_type))

fig_inventory = px.bar(
    df_inventory.head(20),
    x="neighborhood",
    y="listings",
    title="Top 20 Neighborhoods by Active Listings"
)

st.plotly_chart(
    fig_inventory,
    use_container_width=True,
    key="inventory_by_neighborhood"
)

# ==========================================
# 2. PRICE PER SQFT
# ==========================================

st.subheader("💰 Price per SqFt (Live)")

df_psf = run_query("""
SELECT
    p.neighborhood,
    AVG(a.list_price / NULLIF(p.sqft,0)) AS price_psf
FROM active_listings a
JOIN properties p USING (property_id)
WHERE
    p.sqft > 0
    AND a.list_price BETWEEN %s AND %s
    AND (%s = 'ALL' OR p.property_type = %s)
GROUP BY p.neighborhood
ORDER BY price_psf DESC
""", (min_price, max_price, property_type, property_type))

fig_psf = px.bar(
    df_psf.head(20),
    x="neighborhood",
    y="price_psf",
    title="Top Neighborhoods by Price per SqFt"
)

st.plotly_chart(
    fig_psf,
    use_container_width=True,
    key="price_per_sqft_by_neighborhood"
)

# ==========================================
# 3. DAYS ON MARKET (DOM)
# ==========================================

st.subheader("🔥 Days on Market (Heat Indicator)")

df_dom = run_query("""
SELECT
    p.neighborhood,
    AVG(a.days_on_market) AS avg_dom
FROM active_listings a
JOIN properties p USING (property_id)
WHERE
    a.list_price BETWEEN %s AND %s
    AND (%s = 'ALL' OR p.property_type = %s)
GROUP BY p.neighborhood
ORDER BY avg_dom DESC
""", (min_price, max_price, property_type, property_type))

fig_dom = px.bar(
    df_dom.head(20),
    x="neighborhood",
    y="avg_dom",
    title="Slowest Markets (High DOM)"
)

st.plotly_chart(
    fig_dom,
    use_container_width=True,
    key="dom_by_neighborhood"
)

# ==========================================
# 4. NEW LISTINGS TREND
# ==========================================

st.subheader("📈 New Listings Trend")

df_trend = run_query("""
SELECT
    DATE_TRUNC('week', listing_date) AS week,
    COUNT(*) AS new_listings
FROM active_listings
WHERE
    list_price BETWEEN %s AND %s
GROUP BY week
ORDER BY week
""", (min_price, max_price))

fig_trend = px.line(
    df_trend,
    x="week",
    y="new_listings",
    title="Weekly New Listings"
)

st.plotly_chart(
    fig_trend,
    use_container_width=True,
    key="new_listings_trend"
)


# ==========================================
# 🗺️ NEIGHBORHOOD INTELLIGENCE MAP
# ==========================================

st.subheader("🧠 Neighborhood Intelligence Map")

# Metric selector
metric = st.selectbox(
    "Select Map Metric",
    ["listings", "avg_price", "avg_price_psf", "avg_dom"]
)

# Load aggregated data
df_neighborhood = run_query("""
SELECT
    n.nhood AS neighborhood,

    COUNT(a.*) AS listings,

    AVG(a.list_price) AS avg_price,

    AVG(a.list_price / NULLIF(p.sqft,0)) AS avg_price_psf,

    ROUND(AVG(a.days_on_market))::INT AS avg_dom

FROM sf_neighborhoods n

LEFT JOIN properties p
    ON p.neighborhood = n.nhood

LEFT JOIN active_listings a
    ON p.property_id = a.property_id
    AND UPPER(TRIM(a.status)) = 'ACTIVE'

GROUP BY n.nhood
""")

import json  # <-- add near other imports

@st.cache_data
def load_neighborhood_geojson():
    query = """
    SELECT
        nhood,
        ST_AsGeoJSON(geom) AS geometry
    FROM sf_neighborhoods
    """
    df = pd.read_sql(query, engine)

    features = []

    for _, row in df.iterrows():
        features.append({
            "type": "Feature",
            "geometry": json.loads(row["geometry"]),  # ✅ FIXED
            "properties": {
                "neighborhood": row["nhood"]
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features
    }



# Load geojson
geojson = load_neighborhood_geojson()

# Create map
fig_choro = px.choropleth_mapbox(
    df_neighborhood,
    geojson=geojson,
    locations="neighborhood",
    featureidkey="properties.neighborhood",

    color=metric,

    mapbox_style="carto-positron",
    zoom=11,
    center={"lat": 37.77, "lon": -122.43},

    opacity=0.6,

    hover_data={
        "listings": True,
        "avg_price": ":$,.0f",
        "avg_price_psf": ":$,.0f",
        "avg_dom": True
    }
)

st.plotly_chart(
    fig_choro,
    use_container_width=True,
    key="neighborhood_intelligence_map"
)



# ==========================================
# 5. 🔥 OPPORTUNITY INTELLIGENCE (WOW FEATURE)
# ==========================================

st.subheader("🚀 Underpriced Listings (Opportunity Engine)")

df_opps = run_query("""
SELECT
    a.listing_id,
    p.address,
    p.neighborhood,
    a.list_price,
    p.sqft,

    (a.list_price / NULLIF(p.sqft,0)) AS price_psf,

    AVG(a.list_price / NULLIF(p.sqft,0))
        OVER (PARTITION BY p.neighborhood) AS neighborhood_avg_psf,

    (
        (a.list_price / NULLIF(p.sqft,0)) /
        AVG(a.list_price / NULLIF(p.sqft,0))
            OVER (PARTITION BY p.neighborhood)
    ) - 1 AS discount_pct

FROM active_listings a
JOIN properties p USING (property_id)

WHERE
    p.sqft > 0
    AND a.list_price BETWEEN %s AND %s
    AND (%s = 'ALL' OR p.property_type = %s)
""", (min_price, max_price, property_type, property_type))
#df_opps = df_opps.sort_values("discount_pct").head(20)
df_opps = df_opps.sort_values("discount_pct", ascending=True).head(20)
df_opps["price_psf"] = df_opps["price_psf"].round(0)
df_opps["neighborhood_avg_psf"] = df_opps["neighborhood_avg_psf"].round(0)
df_opps["discount_pct"] = (df_opps["discount_pct"] * 100).round(1)

st.dataframe(df_opps)

# ==========================================
# 6. 🗺️ LIVE MAP — ACTIVE LISTINGS
# ==========================================
#✅ STEP 1 — Add SQL query (with filters)
st.subheader("🗺️ Live Listings Map")

df_map = run_query("""
SELECT
    p.latitude,
    p.longitude,
    p.address,
    p.neighborhood,
    a.list_price,
    p.sqft,
    p.beds,
    p.baths_full,
    a.days_on_market,
    p.property_type
FROM active_listings a
JOIN properties p USING (property_id)
WHERE
    p.latitude IS NOT NULL
    AND p.longitude IS NOT NULL
    AND a.list_price BETWEEN %s AND %s
    AND (%s = 'ALL' OR p.property_type = %s)
LIMIT 5000
""", (min_price, max_price, property_type, property_type))


#✅ STEP 2 — Clean + prepare data

df_map["price_psf"] = (
    df_map["list_price"] / df_map["sqft"]
)

# Replace bad values with NaN (NOT None)
df_map["price_psf"] = df_map["price_psf"].replace([np.inf, -np.inf], np.nan)

# Now round safely
df_map["price_psf"] = df_map["price_psf"].round(0)


#✅ STEP 3 — Build interactive map (Plotly)
fig_map = px.scatter_mapbox(
    df_map,
    lat="latitude",
    lon="longitude",

    size="list_price",
    color="property_type",

    zoom=11,
    height=650,

    hover_name="address",

    hover_data={
    "neighborhood": True,
    "list_price": ":$,.0f",
    "price_psf": ":$,.0f",
    "beds": True,
    "baths_full": True,
    "sqft": ":,.0f",
    "days_on_market": True,
    "property_type": True,

    "latitude": False,
    "longitude": False,
    }
)

#✅ STEP 4 — Map style (important for UX)
fig_map.update_layout(
    mapbox_style="carto-positron",
    margin=dict(l=0, r=0, t=0, b=0)
)

#✅ STEP 5 — Render
st.plotly_chart(
    fig_map,
    use_container_width=True,
    key="live_listings_map"
)


# ==========================================
# FOOTER
# ==========================================

st.markdown("---")
st.caption("SF Housing Intelligence • Live San Francisco Data • Built by SFMETRIC 🚀")