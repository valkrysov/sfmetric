import streamlit as st
import pandas as pd
import numpy as np
import re
from sqlalchemy import create_engine
from db import get_engine
import folium
from streamlit_folium import st_folium

from your_module import get_subject, get_ranked_comps, get_comparables
from market_data import get_property_sales_history, get_neighborhood_stats, get_assessor_history, get_eviction_history, get_permit_history
from theme import inject_theme, render_page_header, render_section

inject_theme(page_title="Property Intelligence", page_icon="🏡")
# ALL YOUR EXISTING CODE HERE (unchanged)

# =========================
# 🔌 DATABASE CONNECTION
# =========================

engine = get_engine()


# =========================
# 🆕 ADD HELPER HERE 👇
# =========================

def _exact_property_id_match(candidate, engine):
    """
    Look up a candidate string against both properties and active_listings,
    tolerant of case and stray whitespace (common in multi-batch CSV loads).
    Returns the CANONICAL value as actually stored in the DB.
    """
    query = """
    SELECT property_id FROM properties
    WHERE UPPER(TRIM(property_id)) = UPPER(TRIM(%s))
    UNION
    SELECT property_id FROM active_listings
    WHERE UPPER(TRIM(property_id)) = UPPER(TRIM(%s))
    LIMIT 1
    """
    df = pd.read_sql(query, engine, params=(candidate, candidate))
    if df.empty:
        return None
    return df.iloc[0]["property_id"]

def resolve_property_id(input_value, engine):
    input_value = input_value.strip()

    # -----------------------------------------------------
    # 1) EXACT MATCH FIRST — handles canonical IDs untouched
    #    (e.g. "APN_7159-012", "ADDR_960 MARKET STREET_94102")
    #    This is what click-throughs from the Opportunity
    #    Engine / Market Dashboard always send.
    # -----------------------------------------------------
    exact = _exact_property_id_match(input_value, engine)
    if exact is not None:
        return exact

    # -----------------------------------------------------
    # 2) TRY APN VARIANTS (with / without "APN_" prefix)
    #    Handles inconsistent prefixing between tables and
    #    users manually typing "3627-025" or "APN_3627-025".
    # -----------------------------------------------------
    stripped = input_value.replace("APN_", "").strip()

    if "-" in stripped and stripped.replace("-", "").isdigit():
        for candidate in (stripped, f"APN_{stripped}"):
            match = _exact_property_id_match(candidate, engine)
            if match is not None:
                return match

    # -----------------------------------------------------
    # 3) FUZZY ADDRESS SEARCH (fallback for free-typed input)
    # -----------------------------------------------------
    unit_match = re.search(r"(#|unit|apt)\s*([A-Za-z0-9\-]+)", input_value, re.IGNORECASE)

    unit = None
    base_address = input_value

    if unit_match:
        unit = unit_match.group(2)
        base_address = re.sub(r"(#|unit|apt)\s*[A-Za-z0-9\-]+", "", input_value, flags=re.IGNORECASE).strip()

    if unit:
        query = """
        SELECT property_id
        FROM properties
        WHERE LOWER(address) LIKE LOWER(%s)
        AND CAST(unit_number AS TEXT) ILIKE %s
        LIMIT 1
        """
        params = (f"%{base_address}%", f"%{unit}%")
    else:
        query = """
        SELECT property_id
        FROM properties
        WHERE LOWER(address) LIKE LOWER(%s)
        LIMIT 1
        """
        params = (f"%{base_address}%",)

    df = pd.read_sql(query, engine, params=params)

    if df.empty:
        return None

    return df.iloc[0]["property_id"]

# =========================
# 📦 IMPORT YOUR FUNCTIONS
# =========================
from your_module import get_subject, get_ranked_comps, get_comparables

# =========================
# 🗺️ MAP FUNCTION
# =========================
def plot_comps_map(subject, comps):

    m = folium.Map(
        location=[subject["latitude"], subject["longitude"]],
        zoom_start=14
    )

    # SUBJECT
    folium.Marker(
        [subject["latitude"], subject["longitude"]],
        popup=f"""
        <b>SUBJECT</b><br>
        {subject['full_address']}<br>
        Price: ${subject['sale_price']:,.0f}<br>
        Sqft: {subject['sqft']}
        """,
        icon=folium.Icon(color="red", icon="home")
    ).add_to(m)

    # COMPS
    for _, row in comps.iterrows():
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=6,
            popup=f"""
	    <b>{row.get('full_address', row['address'])}</b><br>
	    Price: ${row['sale_price']:,.0f}<br>
	    Sqft: {row['sqft']}<br>
	    Distance: {row['distance']:.2f} mi<br>
	    Score: {row['score']:.2f}
	    """,
            color="blue",
            fill=True,
            fill_opacity=0.7
        ).add_to(m)

    return m

render_page_header("Property Intelligence", "AI-powered valuation for San Francisco properties")

# =========================
# 🔍 INPUT
# =========================

# -----------------------
# INITIALIZE PERSISTENT WIDGET STATE
# -----------------------
if "property_id" not in st.session_state:
    st.session_state.property_id = ""

# -----------------------
# PRE-FILL FROM OPPORTUNITY ENGINE LINK CLICK (via URL query param)
# -----------------------
query_property_id = st.query_params.get("property_id")

if query_property_id:
    st.session_state.property_id = str(query_property_id)
    st.session_state.run_analysis = True
    st.query_params.clear()

# -----------------------
# PRE-FILL FROM SESSION STATE (kept for backward compatibility)
# -----------------------
elif "selected_property_id" in st.session_state:
    st.session_state.property_id = str(st.session_state.pop("selected_property_id"))
    st.session_state.run_analysis = True

col1, col2 = st.columns([2, 1])

with col1:
    st.text_input(
        "Enter APN or Address",
        key="property_id",
        placeholder="e.g. 3627-025 or APN_3627-025 or 2760 19th Avenue"
    )

with col2:
    if "run_analysis" not in st.session_state:
        st.session_state.run_analysis = False

    if st.button("Analyze"):
        st.session_state.run_analysis = True

property_id = st.session_state.property_id


# =========================
# 🚀 MAIN LOGIC
# =========================
if st.session_state.run_analysis and property_id:

    try:
        # -----------------------
        # RESOLVE INPUT
        # -----------------------
        resolved_id = resolve_property_id(property_id, engine)

        if resolved_id is None:
            st.error("Property not found (APN or address)")
            st.stop()

        property_id = resolved_id

        # -----------------------
        # LOAD DATA
        # -----------------------
        with st.spinner("Analyzing property..."):
            subject = get_subject(property_id, engine)

            comps, price, low, high, median, confidence = get_ranked_comps(
                property_id, engine
            )

        # -----------------------
        # SAFETY
        # -----------------------
        if subject is None:
            st.error("Property not found")
            st.stop()

        if comps is None or len(comps) == 0:
            st.warning("No comparable properties found")
            st.stop()

    except Exception as e:
        import traceback
        st.error(traceback.format_exc())
        st.stop()

    # =========================
    # 📊 METRICS
    # =========================
       
    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("Estimated", f"${price:,.0f}")
    col2.metric("Median", f"${median:,.0f}")
    col3.metric("Range Low", f"${low:,.0f}")
    col4.metric("Range High", f"${high:,.0f}")
    col5.metric("Confidence", f"{confidence:.2f}")




    # =========================
    # 🆕 LAST SALE (CORRECT PLACE)
    # =========================
    render_section("Last Transaction", accent="#2563EB")

    col1, col2 = st.columns(2)

    col1.metric(
        "Last Sale Price",
        f"${int(subject['sale_price']):,}" if pd.notna(subject["sale_price"]) else "N/A"
    )

    col2.metric(
        "Last Sale Date",
        str(subject["sale_date"]) if pd.notna(subject["sale_date"]) else "N/A"
    )

    # =========================
    # 📉 DEAL SIGNAL
    # =========================
    if median and median > 0 and pd.notna(subject["sale_price"]):
       deal_score = (median - subject["sale_price"]) / median
    else:
       deal_score = 0

    if deal_score > 0.05:
        st.success("💰 UNDERPRICED opportunity")
    elif deal_score < -0.05:
        st.warning("⚠️ Overpriced vs comps")
    else:
        st.info("≈ Fairly priced")

    # =========================
    # 🧾 SUBJECT (CLEAN)
    # =========================
    render_section("Subject Property", accent="#2563EB")

    col1, col2, col3 = st.columns(3)
    
    col1.metric(
    "Address",
    subject.get("full_address", subject["address"])
    )
    col2.metric("Sale Price", f"${int(subject['sale_price']):,}")
    col3.metric("Sqft", f"{int(subject['sqft']):,}" if pd.notna(subject["sqft"]) else "N/A")

    col4, col5, col6 = st.columns(3)

    col4.metric("Beds", int(subject["beds"]) if pd.notna(subject["beds"]) else "N/A")
    col5.metric("Baths", int(subject["baths_full"]) if pd.notna(subject["baths_full"]) else "N/A")
    col6.metric("Zip", subject["zip_code"])

    # =========================
    # 🗺️ MAP
    # =========================
    render_section("Map", accent="#2563EB")

    try:
        m = plot_comps_map(subject, comps)
        st_folium(m, width=900, height=500)
    except Exception as e:
        st.warning(f"Map failed: {e}")

    # =========================
    # 📋 COMPS TABLE
    # =========================
    render_section("Top Comparables", accent="#2563EB")

    display_cols = ["full_address", "sale_price", "sqft", "distance", "score"]

    comps_display = comps[display_cols].copy()

    # Format values
    comps_display["sale_price"] = comps_display["sale_price"].fillna(0).map(lambda x: f"${x:,.0f}")
    comps_display["sqft"] = comps_display["sqft"].fillna(0).map(lambda x: f"{int(x):,}")
    comps_display["distance"] = comps_display["distance"].round(2).map(lambda x: f"{x}")
    comps_display["score"] = comps_display["score"].round(2).map(lambda x: f"{x}")

    # ✅ FORCE ALL TO STRING → fixes alignment
    comps_display = comps_display.astype(str)

    st.dataframe(comps_display, use_container_width=True)
    # =========================
    # 📜 HISTORICAL SALES (this property)
    # =========================
    render_section("Historical Sales", accent="#2563EB")

    sales_history = get_property_sales_history(property_id, engine)

    if sales_history.empty:
        st.info("No prior sales on record for this property — it appears to be new to market.")
    else:
        hist_display = sales_history.copy()
        hist_display["sale_date"] = hist_display["sale_date"].dt.strftime("%Y-%m-%d")
        hist_display["sale_price"] = hist_display["sale_price"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
        )
        hist_display["list_price"] = hist_display["list_price"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
        )
        hist_display = hist_display.rename(columns={
            "sale_date": "Sale Date",
            "sale_price": "Sale Price",
            "list_price": "List Price",
            "days_on_market": "DOM"
        })
        st.dataframe(hist_display, use_container_width=True, hide_index=True)

    # =========================
    # 🏘️ NEIGHBORHOOD STATISTICS
    # =========================
    render_section("Neighborhood Statistics", accent="#2563EB")

    neighborhood_stats = get_neighborhood_stats(
        subject["zip_code"],
        subject["property_type"],
        engine
    )

    if neighborhood_stats is None:
        st.info("Not enough recent sales in this ZIP code to compute neighborhood statistics.")
    else:
        n1, n2, n3, n4 = st.columns(4)

        n1.metric("Median Sale Price", f"${neighborhood_stats['median_price']:,.0f}")
        n2.metric("Avg PPSF", f"${neighborhood_stats['avg_ppsf']:,.0f}")
        n3.metric("% Sold Over Asking", f"{neighborhood_stats['pct_over_asking']*100:.0f}%")
        n4.metric("Sales (24mo)", f"{int(neighborhood_stats['sale_count']):,}")

        
        # =========================
        # 🏛️ ASSESSOR TAX ROLL HISTORY
        # =========================
        render_section(
            "Assessor Tax Roll History",
            caption="Annual assessed value, from SF Office of the Assessor-Recorder (public record)",
            accent="#667085"
        )

        assessor_history = get_assessor_history(property_id, engine)

        if assessor_history.empty:
            st.info("No assessor tax roll history available for this property.")
        else:
            chart_df = assessor_history.set_index("closed_roll_year")[
                ["assessed_land_value", "assessed_improvement_value"]
            ]
            chart_df.columns = ["Land Value", "Improvement Value"]
            st.line_chart(chart_df)

            table_display = assessor_history.copy()
            table_display["current_sales_date"] = pd.to_datetime(
                table_display["current_sales_date"], errors="coerce"
            ).dt.strftime("%Y-%m-%d")
            table_display["assessed_land_value"] = table_display["assessed_land_value"].map(
                lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
            )
            table_display["assessed_improvement_value"] = table_display["assessed_improvement_value"].map(
                lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
            )
            table_display["total_assessed_value"] = table_display["total_assessed_value"].map(
                lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
            )
            table_display = table_display.rename(columns={
                "closed_roll_year": "Roll Year",
                "current_sales_date": "Last Recorded Sale",
                "assessed_land_value": "Land Value",
                "assessed_improvement_value": "Improvement Value",
                "total_assessed_value": "Total Assessed",
                "year_property_built": "Year Built",
                "number_of_bedrooms": "Beds (Assessor)",
                "number_of_bathrooms": "Baths (Assessor)",
                "property_area": "Sqft (Assessor)"
            })

            display_cols = [
                "Roll Year", "Total Assessed", "Land Value", "Improvement Value", "Last Recorded Sale"
            ]
            display_cols = [c for c in display_cols if c in table_display.columns]

            st.dataframe(
                table_display[display_cols].sort_values("Roll Year", ascending=False),
                use_container_width=True,
                hide_index=True
            )
       
        
        # =========================
        # 🏚️ EVICTION NOTICE HISTORY
        # =========================
        render_section(
            "Eviction Notice History",
            caption="Rent Board filings recorded nearby (within ~60m) — source: SF Rent Arbitration Board (public record)",
            accent="#B42318"
        )

        eviction_history = get_eviction_history(property_id, engine)

        if eviction_history.empty:
            st.info("No eviction notice filings recorded within proximity of this property.")
        else:
            st.warning(
                f"⚠️ {len(eviction_history)} eviction notice filing(s) recorded nearby. "
                f"**A notice does not confirm a tenant was actually evicted or that this specific unit was involved** — "
                f"source data is block-level, not unit-precise. Consult a real estate attorney for tenancy or "
                f"disclosure questions."
            )

            table_display = eviction_history.copy()
            table_display["file_date"] = table_display["file_date"].dt.strftime("%Y-%m-%d")
            table_display["match_distance_meters"] = table_display["match_distance_meters"].map(
                lambda x: f"{x:.0f}m away" if pd.notna(x) else "N/A"
            )
            table_display = table_display.rename(columns={
                "file_date": "Filing Date",
                "match_distance_meters": "Proximity",
                "reasons": "Stated Reason(s)"
            })

            st.dataframe(
                table_display[["Filing Date", "Proximity", "Stated Reason(s)"]],
                use_container_width=True,
                hide_index=True
            )                

        
        # =========================
        # 🔨 BUILDING PERMIT HISTORY
        # =========================
        render_section(
            "Building Permit History",
            caption="Permits filed with SF Dept. of Building Inspection (public record)",
            accent="#099250"
        )

        permit_history = get_permit_history(property_id, engine)

        if permit_history.empty:
            st.info("No building permit history found for this property.")
        else:
            has_adu = permit_history["adu"].any()
            has_retrofit = permit_history["voluntary_soft_story_retrofit"].any()

            if has_adu:
                st.success("🏠 Accessory Dwelling Unit (ADU) permit found — potential legal secondary unit.")
            if has_retrofit:
                st.success("🏗️ Voluntary soft-story seismic retrofit permit on record.")

            latest_major = permit_history[permit_history["estimated_cost"] >= 25000].head(1)
            if not latest_major.empty:
                row = latest_major.iloc[0]
                year = row["filed_date"].year if pd.notna(row["filed_date"]) else "unknown year"
                st.caption(
                    f"Most recent major permit (${row['estimated_cost']:,.0f}+): "
                   f"{row['permit_type_definition']} filed {year}"
                )

            table_display = permit_history.copy()
            table_display["filed_date"] = table_display["filed_date"].dt.strftime("%Y-%m-%d")
            table_display["estimated_cost"] = table_display["estimated_cost"].map(
                lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
            )
            table_display = table_display.rename(columns={
                "filed_date": "Filed",
                "permit_type_definition": "Type",
                "description": "Description",
                "status": "Status",
                "estimated_cost": "Est. Cost"
            })

            display_cols = ["Filed", "Type", "Description", "Status", "Est. Cost"]
            display_cols = [c for c in display_cols if c in table_display.columns]

            st.dataframe(
                table_display[display_cols],
                use_container_width=True,
                hide_index=True
            )



    # =========================
    # 🤖 AI OPPORTUNITY EXPLANATION
    # =========================
    render_section("🤖 Why This Is (or Isn't) an Opportunity", accent="#099250")

    # ---- Compute the comparison metrics we already have ----
    comps_ppsf_median = comps["ppsf"].median() if "ppsf" in comps.columns and not comps.empty else None
    subject_sqft = subject.get("sqft")
    subject_ppsf = (
        subject["sale_price"] / subject_sqft
        if pd.notna(subject.get("sale_price")) and pd.notna(subject_sqft) and subject_sqft > 0
        else None
    )

    price_discount_pct = (
        (median - subject["sale_price"]) / median
        if median and median > 0 and pd.notna(subject["sale_price"])
        else None
)

    ppsf_discount_pct = (
        (comps_ppsf_median - subject_ppsf) / comps_ppsf_median
        if comps_ppsf_median and subject_ppsf
        else None
    )

    dom = subject.get("days_on_market")
    dom = int(dom) if pd.notna(dom) else None

    # ---- Build the explanation sentence by sentence ----
    explanation_parts = []

    if price_discount_pct is not None:
        if price_discount_pct > 0.03:
            explanation_parts.append(
                f"Asking price is approximately {price_discount_pct*100:.1f}% below the "
                f"estimated neighborhood-adjusted value, based on {len(comps)} comparable "
                f"recent sales."
            )
        elif price_discount_pct < -0.03:
            explanation_parts.append(
                f"Asking price is approximately {abs(price_discount_pct)*100:.1f}% above the "
                f"estimated neighborhood-adjusted value based on comparable sales."
            )
        else:
            explanation_parts.append(
                "Asking price is roughly in line with the estimated neighborhood-adjusted value."
            )

    if ppsf_discount_pct is not None:
        if ppsf_discount_pct > 0.03:
            explanation_parts.append(
                f"The property is also priced {ppsf_discount_pct*100:.1f}% below the median "
                f"price-per-square-foot of comparable properties."
            )
        elif ppsf_discount_pct < -0.03:
            explanation_parts.append(
                f"However, its price per square foot runs {abs(ppsf_discount_pct)*100:.1f}% "
                f"above comparable properties."
            )

    if neighborhood_stats is not None and pd.notna(neighborhood_stats["pct_over_asking"]):
        pct_over = neighborhood_stats["pct_over_asking"]
        if pct_over > 0.5:
            explanation_parts.append(
                f"Despite this, {pct_over*100:.0f}% of comparable homes in this ZIP code have "
                f"recently sold above asking, suggesting a potential pricing inefficiency."
            )
        else:
            explanation_parts.append(
                f"Only {pct_over*100:.0f}% of comparable homes in this ZIP code have recently "
                f"sold above asking, consistent with a more balanced or buyer-favorable market."
            )

    if dom is not None:
        explanation_parts.append(f"This property has been on the market for {dom} days.")

    if explanation_parts:
        st.markdown(" ".join(explanation_parts))
    else:
        st.info("Not enough data available to generate an opportunity explanation.")
# =========================
# FOOTER
# =========================
st.markdown("---")
st.caption("SF Housing Intelligence · Prototype v1")

