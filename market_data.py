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