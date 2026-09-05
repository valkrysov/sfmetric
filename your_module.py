import pandas as pd
import numpy as np

# -------------------
# SUBJECT
# -------------------
def get_subject(property_id, engine):
    property_id = str(property_id).strip()   # ✅ no more .replace("APN_", "")
    ...
    # -----------------------------------------------------
    # 1) TRY HISTORICAL SALE FIRST
    # -----------------------------------------------------
    query_sold = """
    SELECT 
        p.*,
        t.sale_price,
        t.sale_date,
        t.days_on_market,
        CASE 
            WHEN p.unit_number IS NOT NULL 
            THEN p.address || ' #' || p.unit_number
            ELSE p.address
        END AS full_address
    FROM properties p
    JOIN transactions t ON p.property_id = t.property_id
    WHERE p.property_id = %s
    ORDER BY t.sale_date DESC
    LIMIT 1
    """

    df = pd.read_sql(query_sold, engine, params=(property_id,))

    if not df.empty:
        subject = df.iloc[0].copy()
        subject["is_active_listing"] = False
        return subject

    # -----------------------------------------------------
    # 2) FALL BACK TO ACTIVE LISTING (no prior sale on record)
    # -----------------------------------------------------
    query_active = """
    SELECT 
        p.*,
        a.list_price,
        a.listing_date,
        a.days_on_market,
        CASE 
            WHEN p.unit_number IS NOT NULL 
            THEN p.address || ' #' || p.unit_number
            ELSE p.address
        END AS full_address
    FROM properties p
    JOIN active_listings a ON p.property_id = a.property_id
    WHERE p.property_id = %s
    ORDER BY a.listing_date DESC
    LIMIT 1
    """

    df_active = pd.read_sql(query_active, engine, params=(property_id,))

    if df_active.empty:
        return None

    subject = df_active.iloc[0].copy()
    subject["sale_price"] = subject["list_price"]      # use list price as reference
    subject["sale_date"] = subject["listing_date"]      # use listing date as reference
    subject["is_active_listing"] = True
    return subject  
# -------------------
# COMPARABLES
# -------------------
def get_comparables(property_id, engine):
    property_id = str(property_id).strip()   # ✅ no more .replace("APN_", "")
    ...
    query = """
    SELECT
    p.*,
    t.sale_price,
    t.sale_date,
    CASE
        WHEN p.unit_number IS NOT NULL
        THEN p.address || ' #' || p.unit_number
        ELSE p.address
    END AS full_address
    FROM properties p
    JOIN transactions t ON p.property_id = t.property_id
    WHERE p.property_id != %s
    AND p.property_type = (
        SELECT property_type
        FROM properties
        WHERE property_id = %s
    )
    AND t.sale_date >= CURRENT_DATE - INTERVAL '24 months'
    AND p.latitude BETWEEN 37.6 AND 37.9
    AND p.longitude BETWEEN -122.6 AND -122.3
    """

    return pd.read_sql(query, engine, params=(property_id, property_id))

# -------------------
# DISTANCE
# -------------------
def compute_distance_vectorized(df, subject):
    lat1 = np.radians(subject["latitude"])
    lon1 = np.radians(subject["longitude"])

    lat2 = np.radians(df["latitude"])
    lon2 = np.radians(df["longitude"])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

    return 3958.8 * c


# -------------------
# SCORE
# -------------------
import pandas as pd

STALE_SALE_YEARS = 3  # beyond this, don't trust the subject's own price for scoring

def similarity_score(row, subject):
    score = 0

    sale_date = subject.get("sale_date")
    is_stale = False
    if sale_date is not None:
        sale_date = pd.Timestamp(sale_date)
        years_since_sale = (pd.Timestamp.now() - sale_date).days / 365.25
        is_stale = years_since_sale > STALE_SALE_YEARS

    subject_ppsf = subject.get("ppsf")
    if not is_stale and subject_ppsf and subject_ppsf > 0:
        score += 5 * (1 - abs(row["ppsf"] - subject_ppsf) / subject_ppsf)

    subject_sqft = subject.get("sqft")
    if subject_sqft and subject_sqft > 0:
        score += 2 * (1 - abs(row["sqft"] - subject_sqft) / subject_sqft)

    score -= row["distance"] * 2

    if row["zip_code"] == subject["zip_code"]:
        score += 2

    return score

def debug_comps_pipeline(property_id, engine):
    """TEMPORARY — remove after diagnosing 211 Lake Merced Hills issue."""
    subject = get_subject(property_id, engine)
    if subject is None:
        return {"error": "subject not found"}

    comps = get_comparables(property_id, engine)
    comps["distance"] = compute_distance_vectorized(comps, subject)

    stage1 = len(comps)
    comps = comps[(comps["sqft"] > 0) & (comps["sale_price"] > 0)]
    stage2 = len(comps)
    comps = comps.nsmallest(50, "distance")
    stage3 = len(comps)

    subject["ppsf"] = (
        subject["sale_price"] / subject["sqft"]
        if subject["sqft"] and subject["sqft"] > 0
        else None
    )
    comps["ppsf"] = comps["sale_price"] / comps["sqft"]
    comps["score"] = comps.apply(lambda x: similarity_score(x, subject), axis=1)

    stage4 = len(comps.dropna(subset=["score"]))
    comps_scored = comps.dropna(subset=["score"])
    positive_scores = len(comps_scored[comps_scored["score"] > 0])

    return {
        "subject_ppsf": subject.get("ppsf"),
        "subject_sqft": subject.get("sqft"),
        "stage1_raw_comps": stage1,
        "stage2_after_sqft_filter": stage2,
        "stage3_after_nsmallest50": stage3,
        "stage4_after_dropna": stage4,
        "positive_score_count": positive_scores,
        "distance_range": (comps["distance"].min(), comps["distance"].max()) if len(comps) > 0 else None,
        "score_range": (comps_scored["score"].min(), comps_scored["score"].max()) if len(comps_scored) > 0 else None,
        "sample": comps_scored[["address", "distance", "sqft", "ppsf", "score"]].sort_values("score", ascending=False).head(10).to_dict("records") if len(comps_scored) > 0 else [],
    }

# -------------------
# MAIN
# -------------------
def get_ranked_comps(property_id, engine):

    subject = get_subject(property_id, engine)

    if subject is None:
        return None, None, None, None, None, None

    comps = get_comparables(property_id, engine)

    comps["distance"] = compute_distance_vectorized(comps, subject)

    comps = comps[(comps["sqft"] > 0) & (comps["sale_price"] > 0)]
    comps = comps.nsmallest(50, "distance")
    subject["ppsf"] = (
        subject["sale_price"] / subject["sqft"]
        if subject["sqft"] and subject["sqft"] > 0
        else None
    )
    comps["ppsf"] = comps["sale_price"] / comps["sqft"]
    comps["score"] = comps.apply(lambda x: similarity_score(x, subject), axis=1)
    comps = comps.dropna(subset=["score"])
    comps = comps[comps["score"] > 0]
    if len(comps) == 0:
        return None, None, None, None, None, None

    comps = comps.sort_values(by="score", ascending=False)

    # estimates
    est_price = np.average(comps["sale_price"], weights=comps["score"])
    median_price = comps["sale_price"].median()

    low = np.percentile(comps["sale_price"], 25)
    high = np.percentile(comps["sale_price"], 75)

    confidence = min(1, len(comps) / 10)

    return comps.head(10), est_price, low, high, median_price, confidence