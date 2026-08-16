import pandas as pd


# ============================================================
# HISTORICAL SALES
# ============================================================

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
        t.days_on_market,

        CASE 
            WHEN p.unit_number IS NOT NULL 
            THEN p.address || ' #' || p.unit_number
            ELSE p.address
        END AS full_address

    FROM properties p
    JOIN transactions t 
        ON p.property_id = t.property_id

    WHERE t.sale_price IS NOT NULL
    """

    params = []

    if start_date:
        query += " AND t.sale_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND t.sale_date <= %s"
        params.append(end_date)

    if property_type:
        query += " AND p.property_type = %s"
        params.append(property_type)

    df = pd.read_sql(
        query,
        engine,
        params=tuple(params) if params else None
    )

    if df.empty:
        return df

    df["sale_price"] = pd.to_numeric(
        df["sale_price"],
        errors="coerce"
    )

    df["list_price"] = pd.to_numeric(
        df["list_price"],
        errors="coerce"
    )

    df["sqft"] = pd.to_numeric(
        df["sqft"],
        errors="coerce"
    )

    df["ppsf"] = (
        df["sale_price"] / df["sqft"]
    )

    df["diff"] = (
        df["sale_price"] - df["list_price"]
    )

    df["month"] = (
        pd.to_datetime(df["sale_date"])
        .dt.to_period("M")
        .astype(str)
    )

    return df


# ============================================================
# ACTIVE LISTINGS
# ============================================================

def load_active_listings(engine, property_type=None):

    query = """
    SELECT
        a.listing_id,
        a.property_id,
        a.mls_number,
        a.listing_date,
        a.original_list_date,
        a.expiration_date,
        a.list_price,
        a.original_list_price,
        a.days_on_market,
        a.status,
        a.status_change_timestamp,

        p.property_type,
        p.address,
        p.unit_number,
        p.city,
        p.state,
        p.zip_code,
        p.neighborhood,
        p.latitude,
        p.longitude,
        p.beds,
        p.baths_full,
        p.baths_half,
        p.sqft,
        p.lot_size,
        p.acres,
        p.year_built,
        p.stories,
        p.garage_spaces,
        p.fireplaces,
        p.hoa_fee,
        p.view

    FROM active_listings a

    JOIN properties p
        ON a.property_id = p.property_id

    WHERE UPPER(TRIM(a.status)) = 'ACTIVE'
    """

    params = []

    if property_type:
        query += """
        AND p.property_type = %s
        """
        params.append(property_type)

    df = pd.read_sql(
        query,
        engine,
        params=tuple(params) if params else None
    )

    if df.empty:
        return df

    # Numeric cleanup
    df["list_price"] = pd.to_numeric(
        df["list_price"],
        errors="coerce"
    )

    df["original_list_price"] = pd.to_numeric(
        df["original_list_price"],
        errors="coerce"
    )

    df["sqft"] = pd.to_numeric(
        df["sqft"],
        errors="coerce"
    )

    df["days_on_market"] = pd.to_numeric(
        df["days_on_market"],
        errors="coerce"
    )

    # Current asking price per square foot
    df["list_ppsf"] = (
        df["list_price"] / df["sqft"]
    )

    return df


# ============================================================
# MARKET SIGNAL
# ============================================================

def compute_market_signal(signal_df, active_df):
    """
    Calculate a Buyer / Balanced / Seller market signal.

    signal_df:
        Historical sales for either San Francisco or selected ZIP.

    active_df:
        Current active listings for the same geographic scope.

    Returns:
        label
        score
        confidence
        components
    """

    # --------------------------------------------------
    # CLEAN HISTORICAL SALES
    # --------------------------------------------------

    data = signal_df.copy()

    data["sale_price"] = pd.to_numeric(
        data["sale_price"],
        errors="coerce"
    )

    data["list_price"] = pd.to_numeric(
        data["list_price"],
        errors="coerce"
    )

    data = data[
        data["sale_price"].notna()
        & data["list_price"].notna()
        & (data["sale_price"] > 0)
        & (data["list_price"] > 0)
    ].copy()

    # --------------------------------------------------
    # CLEAN ACTIVE LISTINGS
    # --------------------------------------------------

    active = active_df.copy()

    active["list_price"] = pd.to_numeric(
        active["list_price"],
        errors="coerce"
    )

    active = active[
        active["list_price"].notna()
        & (active["list_price"] > 0)
    ].copy()

    # --------------------------------------------------
    # NO HISTORICAL DATA
    # --------------------------------------------------

    if data.empty:

        return {
            "label": "NO DATA",
            "score": 0,
            "confidence": 0,
            "components": {
                "over_asking": 0,
                "historical_transactions": 0,
                "active_listings": len(active),
                "inventory_pressure": 0
            }
        }

    # --------------------------------------------------
    # HISTORICAL SALE / LIST RATIO
    # --------------------------------------------------

    over_asking = (
        data["sale_price"].sum()
        / data["list_price"].sum()
    ) - 1

    historical_transactions = len(data)

    # --------------------------------------------------
    # ACTIVE INVENTORY
    # --------------------------------------------------

    active_listings = len(active)

    # --------------------------------------------------
    # DEMAND SCORE
    #
    # +15% over asking = maximum seller pressure
    #  0%            = neutral
    # negative       = buyer pressure
    # --------------------------------------------------

    demand_score = (
        (over_asking + 0.10) / 0.25
    )

    demand_score = min(
        max(demand_score, 0),
        1
    )

    # --------------------------------------------------
    # INVENTORY PRESSURE
    #
    # More active listings = more buyer leverage.
    #
    # 100 listings or fewer = strong seller pressure
    # 600+ listings        = strong buyer pressure
    # --------------------------------------------------

    inventory_score = (
        1 -
        min(
            max((active_listings - 100) / 500, 0),
            1
        )
    )

    # --------------------------------------------------
    # FINAL MARKET SCORE
    # --------------------------------------------------

    score = (
        demand_score * 0.65
        +
        inventory_score * 0.35
    )

    # --------------------------------------------------
    # CLASSIFICATION
    # --------------------------------------------------

    if score >= 0.65:

        label = "SELLER"

    elif score >= 0.40:

        label = "BALANCED"

    else:

        label = "BUYER"

    # --------------------------------------------------
    # SCORE / CONFIDENCE
    # --------------------------------------------------

    market_score = int(
        round(score * 100)
    )

    return {

        "label": label,

        "score": score,

        "confidence": market_score,

        "components": {

            "over_asking": over_asking,

            "historical_transactions":
                historical_transactions,

            "active_listings":
                active_listings,

            "demand_score":
                demand_score,

            "inventory_score":
                inventory_score,

            "score":
                score
        }
    }


def compute_opportunity_engine(df_active, df_history):
    """
    Compare active listings against historical sold-market PPSF.

    Returns active listings with:
    - estimated_value
    - discount_pct
    - opportunity_score
    """

    active = df_active.copy()
    history = df_history.copy()

    # -------------------------
    # CLEAN NUMERIC FIELDS
    # -------------------------

    active["list_price"] = pd.to_numeric(
        active["list_price"],
        errors="coerce"
    )

    active["sqft"] = pd.to_numeric(
        active["sqft"],
        errors="coerce"
    )

    history["sale_price"] = pd.to_numeric(
        history["sale_price"],
        errors="coerce"
    )

    history["sqft"] = pd.to_numeric(
        history["sqft"],
        errors="coerce"
    )

    # -------------------------
    # REMOVE INVALID DATA
    # -------------------------

    active = active[
        active["list_price"].notna() &
        active["sqft"].notna() &
        (active["list_price"] > 0) &
        (active["sqft"] > 500)
    ].copy()

    history = history[
        history["sale_price"].notna() &
        history["sqft"].notna() &
        (history["sale_price"] > 0) &
        (history["sqft"] > 500)
    ].copy()

    # -------------------------
    # HISTORICAL PPSF
    # -------------------------

    history["sale_ppsf"] = (
        history["sale_price"] /
        history["sqft"]
    )

    # Remove extreme outliers
    history = history[
        history["sale_ppsf"].between(300, 3000)
    ].copy()

    # -------------------------
    # CITY MEDIAN PPSF
    # -------------------------

    benchmark_ppsf = history["sale_ppsf"].median()

    active["benchmark_ppsf"] = benchmark_ppsf


    # -------------------------
    # ESTIMATED VALUE
    # -------------------------

    active["estimated_value"] = (
    active["sqft"] *
    active["benchmark_ppsf"]
    )

    # -------------------------
    # DISCOUNT
    # -------------------------

    active["discount_pct"] = (
        active["estimated_value"] -
        active["list_price"]
    ) / active["estimated_value"]

    # -------------------------
    # OPPORTUNITY SCORE
    # -------------------------

    active["opportunity_score"] = (
        active["discount_pct"] * 100
    ).clip(lower=0, upper=100)

    # -------------------------
    # SORT
    # -------------------------

    active = active.sort_values(
        "opportunity_score",
        ascending=False
    )

    return active
