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
        p.view,

        CASE 
            WHEN p.unit_number IS NOT NULL 
            THEN p.address || ' #' || p.unit_number
            ELSE p.address
        END AS full_address

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

    # -----------------------------------------------------
    # DEDUPE: keep only the most recent listing per property.
    # Source data can contain multiple snapshot rows per
    # listing (e.g. price-change history), which otherwise
    # shows the same address multiple times downstream.
    # -----------------------------------------------------
    if "property_id" in df.columns and "listing_date" in df.columns:
        df["listing_date"] = pd.to_datetime(df["listing_date"], errors="coerce")
        df = (
            df.sort_values("listing_date", ascending=False)
              .drop_duplicates(subset="property_id", keep="first")
              .reset_index(drop=True)
        )



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


# ============================================================
# OPPORTUNITY ENGINE
# ============================================================

def compute_opportunity_engine(df_active, df_history):
    """
    SFMetric Opportunity Engine

    Compares ACTIVE listings against relevant HISTORICAL SALES.

    The engine uses:
        1. Property type
        2. ZIP code
        3. Square footage similarity
        4. Recent historical sales
        5. Historical sale PPSF
        6. ZIP/property-type benchmark
        7. Days on market

    Returns:
        DataFrame containing ranked opportunities.

    Important:
        This is a quantitative screening engine.
        AI explanation will be added later on the
        Property Intelligence page.
    """

    # ========================================================
    # COPY INPUTS
    # ========================================================

    active = df_active.copy()
    history = df_history.copy()

    if active.empty or history.empty:
        return pd.DataFrame()

    # ========================================================
    # NUMERIC CLEANUP
    # ========================================================

    numeric_active = [
        "list_price",
        "sqft",
        "days_on_market"
    ]

    for col in numeric_active:

        if col in active.columns:

            active[col] = pd.to_numeric(
                active[col],
                errors="coerce"
            )

    numeric_history = [
        "sale_price",
        "list_price",
        "sqft"
    ]

    for col in numeric_history:

        if col in history.columns:

            history[col] = pd.to_numeric(
                history[col],
                errors="coerce"
            )

    # ========================================================
    # STANDARDIZE ZIP
    # ========================================================

    active["zip_code"] = (
        active["zip_code"]
        .astype(str)
        .str.strip()
        .str.replace(
            r"\.0$",
            "",
            regex=True
        )
    )

    history["zip_code"] = (
        history["zip_code"]
        .astype(str)
        .str.strip()
        .str.replace(
            r"\.0$",
            "",
            regex=True
        )
    )

    # ========================================================
    # STANDARDIZE PROPERTY TYPE
    # ========================================================

    active["property_type"] = (
        active["property_type"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    history["property_type"] = (
        history["property_type"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    # ========================================================
    # VALID ACTIVE LISTINGS
    # ========================================================

    active = active[
        active["list_price"].notna()
        &
        active["sqft"].notna()
        &
        (active["list_price"] > 100000)
        &
        (active["sqft"] > 500)
        &
        (active["sqft"] < 10000)
    ].copy()

    if active.empty:
        return pd.DataFrame()

    # ========================================================
    # VALID HISTORICAL SALES
    # ========================================================

    history = history[
        history["sale_price"].notna()
        &
        history["sqft"].notna()
        &
        (history["sale_price"] > 100000)
        &
        (history["sqft"] > 500)
        &
        (history["sqft"] < 10000)
    ].copy()

    if history.empty:
        return pd.DataFrame()

    # ========================================================
    # HISTORICAL PPSF
    # ========================================================

    history["sale_ppsf"] = (
        history["sale_price"] /
        history["sqft"]
    )

    # ========================================================
    # REMOVE EXTREME PPSF OUTLIERS
    # ========================================================

    history = history[
        history["sale_ppsf"].between(
            300,
            3000
        )
    ].copy()

    if history.empty:
        return pd.DataFrame()

    # ========================================================
    # SALE DATE
    # ========================================================

    history["sale_date"] = pd.to_datetime(
        history["sale_date"],
        errors="coerce"
    )

    # ========================================================
    # RECENT SALES
    #
    # We don't want a 2006 sale to have the same importance
    # as a 2026 sale.
    #
    # Keep the most recent 5 years where possible.
    # ========================================================

    max_sale_date = history["sale_date"].max()

    if pd.notna(max_sale_date):

        cutoff_date = (
            max_sale_date -
            pd.DateOffset(years=5)
        )

        recent_history = history[
            history["sale_date"] >= cutoff_date
        ].copy()

        # If there aren't enough recent sales,
        # fall back to the full history.
        if len(recent_history) >= 100:

            history = recent_history

    # ========================================================
    # CITY / SCOPE BENCHMARK
    #
    # Used as a fallback when we don't have enough
    # comparable ZIP/type transactions.
    # ========================================================

    scope_benchmark = (
        history["sale_ppsf"].median()
    )

    # ========================================================
    # CREATE RESULT COLUMNS
    # ========================================================

    results = []

    # ========================================================
    # PROCESS EACH ACTIVE LISTING
    # ========================================================

    for idx, listing in active.iterrows():

        list_price = listing["list_price"]
        sqft = listing["sqft"]
        zip_code = listing["zip_code"]
        property_type = listing["property_type"]

        # ----------------------------------------------------
        # MATCH HISTORICAL SALES
        #
        # Priority:
        #
        # 1. Same ZIP + same property type
        # 2. Same ZIP
        # 3. Same property type
        # 4. Overall market
        # ----------------------------------------------------

        comparable = history[
            (history["zip_code"] == zip_code)
            &
            (history["property_type"] == property_type)
        ].copy()

        benchmark_source = "ZIP + PROPERTY TYPE"

        if len(comparable) < 10:

            comparable = history[
                history["zip_code"] == zip_code
            ].copy()

            benchmark_source = "ZIP"

        if len(comparable) < 10:

            comparable = history[
                history["property_type"] == property_type
            ].copy()

            benchmark_source = "PROPERTY TYPE"

        if len(comparable) < 10:

            comparable = history.copy()

            benchmark_source = "CITY"

        # ----------------------------------------------------
        # SQUARE FOOTAGE COMPARABLES
        #
        # Prefer properties within +/- 30% of subject size.
        # ----------------------------------------------------

        size_low = sqft * 0.70
        size_high = sqft * 1.30

        size_comps = comparable[
            comparable["sqft"].between(
                size_low,
                size_high
            )
        ].copy()

        # ----------------------------------------------------
        # If enough size comps exist, use them.
        # Otherwise use broader comps.
        # ----------------------------------------------------

        if len(size_comps) >= 5:

            comparable = size_comps

        # ----------------------------------------------------
        # REMOVE EXTREME PPSF VALUES AGAIN
        # ----------------------------------------------------

        comparable = comparable[
            comparable["sale_ppsf"].between(
                300,
                3000
            )
        ]

        if comparable.empty:

            benchmark_ppsf = scope_benchmark
            comparable_count = 0

        else:

            # ------------------------------------------------
            # Median PPSF is more robust than mean.
            # ------------------------------------------------

            benchmark_ppsf = (
                comparable["sale_ppsf"]
                .median()
            )

            comparable_count = len(comparable)

        # ----------------------------------------------------
        # ESTIMATED MARKET VALUE
        # ----------------------------------------------------

        estimated_value = (
            sqft *
            benchmark_ppsf
        )

        # ----------------------------------------------------
        # DISCOUNT
        #
        # Positive = listing is below benchmark.
        # ----------------------------------------------------

        discount_pct = (
            estimated_value -
            list_price
        ) / estimated_value

        # ----------------------------------------------------
        # LISTING PPSF
        # ----------------------------------------------------

        list_ppsf = (
            list_price /
            sqft
        )

        # ----------------------------------------------------
        # PPSF DISCOUNT
        # ----------------------------------------------------

        ppsf_discount_pct = (
            benchmark_ppsf -
            list_ppsf
        ) / benchmark_ppsf

        # ----------------------------------------------------
        # DAYS ON MARKET
        # ----------------------------------------------------

        dom = listing.get(
            "days_on_market",
            0
        )

        if pd.isna(dom):

            dom = 0

        # ----------------------------------------------------
        # DOM SCORE
        #
        # A property sitting longer can indicate pricing
        # pressure, but very long DOM can also indicate
        # property-specific problems.
        #
        # We therefore give moderate DOM a small advantage.
        # ----------------------------------------------------

        if dom <= 7:

            dom_score = 0.40

        elif dom <= 30:

            dom_score = 0.70

        elif dom <= 60:

            dom_score = 1.00

        elif dom <= 90:

            dom_score = 0.60

        else:

            dom_score = 0.30

        # ----------------------------------------------------
        # DISCOUNT SCORE
        #
        # 0% discount = 0
        # 20%+ discount = 1
        # ----------------------------------------------------

        discount_score = (
            discount_pct / 0.20
        )

        discount_score = min(
            max(discount_score, 0),
            1
        )

        # ----------------------------------------------------
        # PPSF SCORE
        # ----------------------------------------------------

        ppsf_score = (
            ppsf_discount_pct / 0.20
        )

        ppsf_score = min(
            max(ppsf_score, 0),
            1
        )

        # ----------------------------------------------------
        # COMPARABLE CONFIDENCE
        # ----------------------------------------------------

        if comparable_count >= 30:

            confidence_score = 1.00

        elif comparable_count >= 20:

            confidence_score = 0.85

        elif comparable_count >= 10:

            confidence_score = 0.70

        elif comparable_count >= 5:

            confidence_score = 0.50

        else:

            confidence_score = 0.25

        # ----------------------------------------------------
        # FINAL OPPORTUNITY SCORE
        #
        # Discount       40%
        # PPSF advantage 30%
        # DOM             10%
        # Confidence      20%
        # ----------------------------------------------------

        opportunity_score = (

            discount_score * 0.40

            +

            ppsf_score * 0.30

            +

            dom_score * 0.10

            +

            confidence_score * 0.20

        ) * 100

        # ----------------------------------------------------
        # QUALIFICATION
        #
        # We don't want every listing to be an opportunity.
        #
        # Require:
        #
        #   >= 5% estimated discount
        # OR
        #   >= 5% PPSF advantage
        #
        # AND a minimum confidence level.
        # ----------------------------------------------------

        qualifies = (

            (
                discount_pct >= 0.05
            )

            or

            (
                ppsf_discount_pct >= 0.05
            )

        ) and comparable_count >= 5

        # ----------------------------------------------------
        # STORE RESULT
        # ----------------------------------------------------

        row = listing.to_dict()

        row.update({

            "benchmark_ppsf":
                benchmark_ppsf,

            "benchmark_source":
                benchmark_source,

            "comparable_count":
                comparable_count,

            "estimated_value":
                estimated_value,

            "list_ppsf":
                list_ppsf,

            "discount_pct":
                discount_pct,

            "ppsf_discount_pct":
                ppsf_discount_pct,

            "dom_score":
                dom_score,

            "confidence_score":
                confidence_score,

            "opportunity_score":
                opportunity_score,

            "qualifies":
                qualifies
        })

        results.append(row)

    # ========================================================
    # BUILD DATAFRAME
    # ========================================================

    if not results:

        return pd.DataFrame()

    opportunities = pd.DataFrame(
        results
    )

    # ========================================================
    # KEEP ONLY QUALIFIED OPPORTUNITIES
    # ========================================================

    opportunities = opportunities[
        opportunities["qualifies"] == True
    ].copy()

    # ========================================================
    # SORT
    # ========================================================

    opportunities = opportunities.sort_values(
        "opportunity_score",
        ascending=False
    )

    # ========================================================
    # FINAL RANK
    # ========================================================

    opportunities["opportunity_rank"] = (
        range(
            1,
            len(opportunities) + 1
        )
    )

    # ========================================================
    # RESET INDEX
    # ========================================================

    opportunities.reset_index(
        drop=True,
        inplace=True
    )

    return opportunities


#============================================================
#PROPERTY SALES HISTORY (single property)
#============================================================

def get_property_sales_history(property_id, engine):
    """
    All historical transactions for one specific property_id,
    most recent first.
    """
    query = """
    SELECT
        sale_date,
        sale_price,
        list_price,
        days_on_market
    FROM transactions
    WHERE property_id = %s
    ORDER BY sale_date DESC
    """

    df = pd.read_sql(query, engine, params=(property_id,))

    if df.empty:
        return df

    df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
    df["sale_price"] = pd.to_numeric(df["sale_price"], errors="coerce")
    df["list_price"] = pd.to_numeric(df["list_price"], errors="coerce")

    return df


#============================================================
#NEIGHBORHOOD STATISTICS (ZIP + property type, last 24 months)
#============================================================

def get_neighborhood_stats(zip_code, property_type, engine):
    """
    Aggregate market stats for a ZIP code + property type,
    computed directly in SQL (no large dataframe pulled into Python).
    Returns a single pandas Series, or None if no data.
    """
    query = """
    SELECT
        COUNT(*) AS sale_count,
        AVG(t.sale_price) AS avg_price,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t.sale_price) AS median_price,
        AVG(t.sale_price / NULLIF(p.sqft, 0)) AS avg_ppsf,
        AVG(
            CASE WHEN t.sale_price > t.list_price THEN 1.0 ELSE 0.0 END
        ) AS pct_over_asking,
        AVG(t.days_on_market) AS avg_dom
    FROM transactions t
    JOIN properties p ON t.property_id = p.property_id
    WHERE p.zip_code = %s
      AND p.property_type = %s
      AND t.sale_date >= CURRENT_DATE - INTERVAL '24 months'
      AND t.sale_price IS NOT NULL
      AND t.list_price IS NOT NULL
    """

    df = pd.read_sql(query, engine, params=(zip_code, property_type))

    if df.empty or pd.isna(df.iloc[0]["sale_count"]) or df.iloc[0]["sale_count"] == 0:
        return None

    return df.iloc[0]