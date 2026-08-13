import pandas as pd
import numpy as np

# -------------------
# SUBJECT
# -------------------
def get_subject(property_id, engine):
    property_id = str(property_id).replace("APN_", "").strip()

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
    WHERE p.property_id = %s
    ORDER BY t.sale_date DESC
    LIMIT 1
    """

    df = pd.read_sql(query, engine, params=(property_id,))  # ✅ FIXED

    if df.empty:
        return None
    return df.iloc[0]   # ✅ nothing else needed
  
# -------------------
# COMPARABLES
# -------------------
def get_comparables(property_id, engine):
    property_id = str(property_id).replace("APN_", "").strip()

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
def similarity_score(row, subject):
    score = 0

    score += 5 * (1 - abs(row["ppsf"] - subject["ppsf"]) / subject["ppsf"])
    score += 2 * (1 - abs(row["sqft"] - subject["sqft"]) / subject["sqft"])
    score -= row["distance"] * 2

    if row["zip_code"] == subject["zip_code"]:
        score += 2

    return score


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

    subject["ppsf"] = subject["sale_price"] / subject["sqft"]
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