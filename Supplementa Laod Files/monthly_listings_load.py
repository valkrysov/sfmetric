# ==========================================
# SF HISTORICAL / MONTHLY DATA LOAD SCRIPT
# ==========================================

import re
import os
import pandas as pd
import numpy as np
import psycopg2
from io import StringIO

# ==========================================
# CONFIG — SUPABASE
# ==========================================
#DB_CONFIG = {
#    "dbname": "neondb",
#    "user": "neondb_owner",
#    "password": os.environ["SFMETRIC_DB_PASSWORD"],
#    "host": "ep-flat-rice-afl6klhi.c-2.us-west-2.aws.neon.tech",
#    "port": "5432",
#    "sslmode": "require"
#}

DB_CONFIG = {
    "dbname": "sfmetric",
    "user": "postgres",
    "password": os.environ["SFMETRIC_DB_PASSWORD"],
    "host": "localhost",
    "port": "5433",
    "sslmode": "disable"
}

# ==========================================
# FILES
# (For a monthly sales update, point these
#  at single month's files.)
# ==========================================
SFR_FILE = "SFR_July_2026.csv"
CONDO_FILE = "CONDO_July_2026.csv"
TOWNHOUSE_FILE = "TOWNHOMES_July_2026.csv"

# ==========================================
# HELPERS
# ==========================================
def safe_parse_date(series):
    return pd.to_datetime(series, errors="coerce", format="mixed")


# ==========================================
# CLEAN APN
# (Matches active_listings_load.py exactly —
#  MUST stay in sync with that script.)
# ==========================================
def clean_apn(apn):
    if pd.isna(apn):
        return None

    apn = str(apn).strip()

    if not apn:
        return None

    if "new" in apn.lower():
        return None

    if "construct" in apn.lower():
        return None

    # Preserve trailing letter suffixes on the lot (e.g. "1625-005C"),
    # since these represent legally distinct subdivided parcels —
    # NOT the same physical property as the unsuffixed base lot.
    apn_clean = re.sub(r"[^0-9\-A-Za-z]", "", apn)

    digits_only = re.sub(r"[^0-9]", "", apn_clean)

    if len(digits_only) < 6:
        return None

    if digits_only == "" or int(digits_only) == 0:
        return None

    return apn_clean.upper()

# ==========================================
# CREATE PROPERTY_ID
# (Matches active_listings_load.py exactly —
#  MUST stay in sync with that script.)
# ==========================================
def create_property_id(row):
    apn_clean = clean_apn(row.get("Parcel Number"))

    unit = str(row.get("Unit Number", "")).strip().upper()
    has_unit = unit not in ("", "NAN", "NONE")

    if apn_clean:
        if has_unit:
            return f"APN_{apn_clean}_UNIT_{unit}"
        return f"APN_{apn_clean}"

    address = str(row.get("Address", "")).strip().upper()
    zip_code = str(row.get("Zip Code", "")).strip()

    if has_unit:
        return f"ADDR_{address}_UNIT_{unit}_{zip_code}"

    return f"ADDR_{address}_{zip_code}"


# ==========================================
# SCHEMA ENFORCEMENT
# ==========================================
def enforce_schema_types(df):

    df = df.copy()

    int_cols = ["beds", "sqft", "year_built", "fireplaces"]

    float_cols = [
        "baths_full", "baths_half",
        "lot_size", "acres",
        "garage_spaces", "room_count"
    ]

    for col in int_cols:
        if col in df.columns:
            df[col] = (
                pd.to_numeric(df[col], errors="coerce")
                .fillna(0)
                .round()
                .astype(int)
            )

    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# ==========================================
# NORMALIZATION
# ==========================================
def normalize_dataframe(df, property_type):

    df = df.copy()
    df.columns = df.columns.str.strip()

    df = df.drop(columns=["Owner Name", "Property Tax"], errors="ignore")

    df["property_type"] = property_type

    df["property_id"] = df.apply(create_property_id, axis=1)

    df["address"] = df.get("Address")
    df["city"] = df.get("Postal City")
    df["state"] = df.get("State")

    df["zip_code"] = (
        df.get("Zip Code")
        .astype(str)
        .str.extract(r"(94\d{3})")
    )

    df["county"] = df.get("County")

    df["latitude"] = df.get("Latitude")
    df["longitude"] = df.get("Longitude")

    df["beds"] = df.get("Beds Total")
    df["baths_full"] = df.get("Baths Full")
    df["baths_half"] = df.get("Baths Half")

    df["sqft"] = df.get("Sq Ft Total")
    df["lot_size"] = df.get("Lot Size")
    df["acres"] = df.get("Acres")

    df["year_built"] = df.get("Year Built")
    df["stories"] = df.get("No Of Stories")
    df["fireplaces"] = df.get("# of Fireplaces")
    df["garage_spaces"] = df.get("Garage Spaces")
    df["room_count"] = df.get("Room Count")

    df["hoa_fee"] = df.get("HOA Fee")
    df["hoa_amenities"] = df.get("HOA Amenities")
    df["hoa_fee_covers"] = df.get("HOA Fee Covers")
    df["hoa_name"] = df.get("HOA Name Text")
    df["hoa_phone"] = df.get("HOA Phone")

    hoa_exists = df.get("HOA Exist YN")
    if hoa_exists is not None:
        df["hoa_exists"] = hoa_exists.map({"Y": True, "N": False})
    else:
        df["hoa_exists"] = None

    df["unit_number"] = df.get("Unit Number")
    df["view"] = df.get("View")

    # TRANSACTIONS
    df["mls_number"] = df.get("MLS Number")

    df["listing_date"] = safe_parse_date(df.get("Listing Date"))
    df["original_list_date"] = safe_parse_date(df.get("Original List Date"))
    df["expiration_date"] = safe_parse_date(df.get("Expiration Date"))
    df["sale_date"] = safe_parse_date(df.get("Sale Date"))
    df["close_date"] = safe_parse_date(df.get("Close Date"))
    df["status_change_timestamp"] = safe_parse_date(df.get("Status Change Timestamp"))

    df["list_price"] = df.get("List Price")
    df["original_list_price"] = df.get("Original List Price")
    df["sale_price"] = df.get("Sale Price")

    df["days_on_market"] = df.get("DOM")
    df["status"] = df.get("Status")
    df["buyer_financing"] = df.get("Buyer's Financing")

    return df


# ==========================================
# SPLIT
# ==========================================
def split_dataframes(df):

    properties_cols = [
        "property_id", "property_type",
        "address", "city", "state", "zip_code", "county",
        "latitude", "longitude",
        "beds", "baths_full", "baths_half",
        "sqft", "lot_size", "acres",
        "year_built", "stories",
        "fireplaces", "garage_spaces", "room_count",
        "hoa_fee", "hoa_amenities", "hoa_fee_covers",
        "hoa_name", "hoa_phone", "hoa_exists",
        "unit_number", "view"
    ]

    transactions_cols = [
        "property_id",
        "mls_number",
        "listing_date", "original_list_date",
        "expiration_date", "sale_date", "close_date",
        "list_price", "original_list_price", "sale_price",
        "days_on_market",
        "status", "status_change_timestamp",
        "buyer_financing"
    ]

    properties_cols = [c for c in properties_cols if c in df.columns]
    transactions_cols = [c for c in transactions_cols if c in df.columns]

    df_properties = df[properties_cols].copy()
    df_transactions = df[transactions_cols].copy()

    df_properties = df_properties[df_properties["property_id"].notna()]
    df_transactions = df_transactions[df_transactions["property_id"].notna()]

    df_properties = df_properties.drop_duplicates(subset="property_id")

    return df_properties, df_transactions


# ==========================================
# COPY
# ==========================================
def copy_dataframe_to_table(df, table, conn):

    if df.empty:
        print(f"⚠️ Nothing to load into {table}")
        return

    buffer = StringIO()
    df.to_csv(buffer, index=False, header=False)
    buffer.seek(0)

    cursor = conn.cursor()
    columns = ",".join(f'"{c}"' for c in df.columns)

    cursor.copy_expert(
        f"COPY {table} ({columns}) FROM STDIN WITH CSV",
        buffer
    )
    conn.commit()


# ==========================================
# LOAD
# ==========================================
def load_to_postgres(df_all):

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    df_properties, df_transactions = split_dataframes(df_all)

    df_properties = enforce_schema_types(df_properties)

    df_properties = df_properties.replace({np.nan: None})
    df_transactions = df_transactions.replace({np.nan: None})

    cur.execute("TRUNCATE properties_staging;")
    cur.execute("TRUNCATE transactions_staging;")
    conn.commit()

    print(f"🏠 Staging {len(df_properties):,} properties...")
    copy_dataframe_to_table(df_properties, "properties_staging", conn)

    print(f"💰 Staging {len(df_transactions):,} transactions...")
    copy_dataframe_to_table(df_transactions, "transactions_staging", conn)

    cur.execute("""
    INSERT INTO properties
    SELECT * FROM properties_staging
    ON CONFLICT (property_id) DO UPDATE SET
        property_type = EXCLUDED.property_type,
        address = EXCLUDED.address,
        city = EXCLUDED.city,
        state = EXCLUDED.state,
        zip_code = EXCLUDED.zip_code,
        county = EXCLUDED.county,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        beds = EXCLUDED.beds,
        baths_full = EXCLUDED.baths_full,
        baths_half = EXCLUDED.baths_half,
        sqft = EXCLUDED.sqft,
        lot_size = EXCLUDED.lot_size,
        acres = EXCLUDED.acres,
        year_built = EXCLUDED.year_built,
        stories = EXCLUDED.stories,
        fireplaces = EXCLUDED.fireplaces,
        garage_spaces = EXCLUDED.garage_spaces,
        room_count = EXCLUDED.room_count,
        hoa_fee = EXCLUDED.hoa_fee,
        hoa_amenities = EXCLUDED.hoa_amenities,
        hoa_fee_covers = EXCLUDED.hoa_fee_covers,
        hoa_name = EXCLUDED.hoa_name,
        hoa_phone = EXCLUDED.hoa_phone,
        hoa_exists = EXCLUDED.hoa_exists,
        unit_number = EXCLUDED.unit_number,
        view = EXCLUDED.view;
    """)

    cur.execute("""
    INSERT INTO transactions (
        property_id, mls_number,
        listing_date, original_list_date,
        expiration_date, sale_date, close_date,
        list_price, original_list_price, sale_price,
        days_on_market,
        status, status_change_timestamp,
        buyer_financing
    )
    SELECT DISTINCT * FROM transactions_staging
    ON CONFLICT DO NOTHING;
    """)

    conn.commit()
    conn.close()

    print("✅ LOAD COMPLETE")


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":

    print("📥 Loading raw files...")

    df_sfr_raw = pd.read_csv(SFR_FILE)
    df_condo_raw = pd.read_csv(CONDO_FILE)
    df_town_raw = pd.read_csv(TOWNHOUSE_FILE)

    print(f"   SFR:       {len(df_sfr_raw):,}")
    print(f"   CONDO:     {len(df_condo_raw):,}")
    print(f"   TOWNHOUSE: {len(df_town_raw):,}")

    print("🧹 Normalizing...")

    df_sfr = normalize_dataframe(df_sfr_raw, "SFR")
    df_condo = normalize_dataframe(df_condo_raw, "CONDO")
    df_town = normalize_dataframe(df_town_raw, "TOWNHOUSE")

    dfs = [df_sfr, df_condo, df_town]
    dfs = [df for df in dfs if df is not None and not df.empty]
    dfs = [df.dropna(axis=1, how="all") for df in dfs]

    if not dfs:
        raise ValueError("No data was loaded from the source files.")

    df_all = pd.concat(dfs, ignore_index=True)

    print(f"   Combined records: {len(df_all):,}")

    print("🚀 Loading to DB...")

    load_to_postgres(df_all)