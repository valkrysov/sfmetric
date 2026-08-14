import pandas as pd

def load_market_data(engine, start_date=None, end_date=None, property_type=None):

    query = """
    SELECT 
        p.property_type,
        p.latitude,
        p.longitude,
        p.sqft,
        p.zip_code,
        p.address,
        p.unit_number,

        t.sale_price,
        t.list_price,
        t.sale_date,

        -- FULL ADDRESS (VERY IMPORTANT)
        CASE 
            WHEN p.unit_number IS NOT NULL 
            THEN p.address || ' #' || p.unit_number
            ELSE p.address
        END AS full_address

    FROM properties p
    JOIN transactions t ON p.property_id = t.property_id
    WHERE t.sale_price IS NOT NULL
    """

    params = []

    # -------------------
    # FILTERS
    # -------------------
    if start_date:
        query += " AND t.sale_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND t.sale_date <= %s"
        params.append(end_date)

    if property_type:
        query += " AND p.property_type = %s"
        params.append(property_type)

    df = pd.read_sql(query, engine, params=tuple(params) if params else None)

    if df.empty:
        return df

    # -------------------
    # DERIVED FEATURES
    # -------------------
    df["ppsf"] = df["sale_price"] / df["sqft"]
    df["diff"] = df["sale_price"] - df["list_price"]
    df["month"] = pd.to_datetime(df["sale_date"]).dt.to_period("M").astype(str)

    return df

def compute_market_signal(df):
    """
    Calculate a market signal from transaction data.

    Uses:
        - % over asking
        - transaction count

    Returns:
        label
        confidence
        components
    """

    if df is None or df.empty:
        return {
            "label": "NO DATA",
            "confidence": 0,
            "components": {
                "over_asking": 0,
                "transactions": 0,
                "score": 0
            }
        }

    # -------------------
    # CLEAN NUMERIC DATA
    # -------------------

    data = df.copy()

    data["sale_price"] = pd.to_numeric(
        data["sale_price"],
        errors="coerce"
    )

    data["list_price"] = pd.to_numeric(
        data["list_price"],
        errors="coerce"
    )

    data = data[
        data["sale_price"].notna() &
        data["list_price"].notna() &
        (data["sale_price"] > 0) &
        (data["list_price"] > 0)
    ]

    if data.empty:
        return {
            "label": "NO DATA",
            "confidence": 0,
            "components": {
                "over_asking": 0,
                "transactions": 0,
                "score": 0
            }
        }

    # -------------------
    # OVER ASKING
    # -------------------

    over_asking = (
        data["sale_price"].sum() /
        data["list_price"].sum()
    ) - 1

    # -------------------
    # TRANSACTION COUNT
    # -------------------

    transactions = len(data)

    # -------------------
    # NORMALIZE OVER ASKING
    # -------------------

    # 0% = neutral
    # +15% = maximum seller pressure

    over_score = min(
        max(over_asking / 0.15, 0),
        1
    )

    # -------------------
    # SCORE
    # -------------------

    # For now, use over-asking as the
    # primary market-demand indicator.

    score = over_score

    # -------------------
    # MARKET CLASSIFICATION
    # -------------------

    if score >= 0.65:
        label = "SELLER"

    elif score >= 0.30:
        label = "BALANCED"

    else:
        label = "BUYER"

    confidence = int(
        min(max(score * 100, 0), 100)
    )

    return {
        "label": label,
        "confidence": confidence,
        "components": {
            "over_asking": over_asking,
            "transactions": transactions,
            "score": score
        }
    }
