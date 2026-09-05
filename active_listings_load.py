# ============================================================
# SF HOUSING INTELLIGENCE
# ACTIVE MLS LISTINGS LOAD PIPELINE
# ============================================================

import os
import re
import pandas as pd
import numpy as np
import psycopg2
from io import StringIO


# ============================================================
# CONFIG 
# ============================================================

#SMETRIC
#DB_CONFIG = {
#    "dbname": "neondb",
#    "user": "neondb_owner",
#    "password": os.environ["SFMETRIC_DB_PASSWORD"],
#    "host": "ep-flat-rice-afl6klhi.c-2.us-west-2.aws.neon.tech",
#    "port": "5432",
#    "sslmode": "require"
#}

#SMETRIC-DEV
#DB_CONFIG = {
#    "dbname": "neondb",
#    "user": "neondb_owner",
#    "password": os.environ["SFMETRIC_DB_PASSWORD"],
#    "host": "ep-divine-morning-af72pc4i-pooler.c-2.us-west-2.aws.neon.tech",
#    "port": "5432",
#    "sslmode": "require"
#}

#Local Host
DB_CONFIG = {
    "dbname": "sfmetric",
    "user": "postgres",
    "password": os.environ["SFMETRIC_DB_PASSWORD"],
    "host": "localhost",
    "port": "5433",
    "sslmode": "disable"
}

# ============================================================
# FILES
# ============================================================

SFR_FILE = "SFR_active.csv"
CONDO_FILE = "Condo_active.csv"
TOWNHOUSE_FILE = "Townhomes_active.csv"


# ============================================================
# HELPERS
# ============================================================

def safe_parse_date(series):
    if series is None:
        return pd.Series(dtype="datetime64[ns]")
    return pd.to_datetime(series, errors="coerce", format="mixed")


def numeric(series):
    if series is None:
        return pd.Series(dtype="float64")
    return pd.to_numeric(series, errors="coerce")


# ============================================================
# CLEAN APN
# ============================================================

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

# ============================================================
# PROPERTY ID
# ============================================================

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


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_dataframe(df, property_type):

    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    df["property_id"] = df.apply(create_property_id, axis=1)
    df["listing_id"] = df["MLS Number"].astype(str).str.strip()
    df["mls_number"] = df["MLS Number"].astype(str).str.strip()
    df["property_type"] = property_type

    df["address"] = df.get("Address")
    df["city"] = df.get("Postal City")
    df["state"] = df.get("State")
    df["zip_code"] = df.get("Zip Code").astype(str).str.extract(r"(94\d{3})", expand=False)
    df["county"] = df.get("County")
    df["latitude"] = numeric(df.get("Latitude"))
    df["longitude"] = numeric(df.get("Longitude"))

    df["beds"] = numeric(df.get("Beds Total"))
    df["baths_full"] = numeric(df.get("Baths Full"))
    df["baths_half"] = numeric(df.get("Baths Half"))
    df["sqft"] = numeric(df.get("Sq Ft Total"))
    df["lot_size"] = numeric(df.get("Lot Size"))
    df["acres"] = numeric(df.get("Acres"))
    df["year_built"] = numeric(df.get("Year Built"))
    df["stories"] = numeric(df.get("No Of Stories"))
    df["floors"] = numeric(df.get("No Of Floors"))
    df["fireplaces"] = numeric(df.get("# of Fireplaces"))
    df["garage_spaces"] = numeric(df.get("Garage Spaces"))
    df["room_count"] = numeric(df.get("Room Count"))

    df["hoa_fee"] = numeric(df.get("HOA Fee"))
    df["hoa_amenities"] = df.get("HOA Amenities")
    df["hoa_fee_covers"] = df.get("HOA Fee Covers")
    df["hoa_name"] = df.get("HOA Name Text")
    df["hoa_phone"] = df.get("HOA Phone")

    hoa_exists = df.get("HOA Exist YN")
    if hoa_exists is not None:
        df["hoa_exists"] = hoa_exists.astype(str).str.strip().str.upper().map({"Y": True, "N": False})
    else:
        df["hoa_exists"] = None

    df["unit_number"] = df.get("Unit Number")
    df["view"] = df.get("View")

    df["listing_date"] = safe_parse_date(df.get("Listing Date"))
    df["original_list_date"] = safe_parse_date(df.get("Original List Date"))
    df["expiration_date"] = safe_parse_date(df.get("Expiration Date"))
    df["status_change_timestamp"] = safe_parse_date(df.get("Status Change Timestamp"))

    df["list_price"] = numeric(df.get("List Price"))
    df["original_list_price"] = numeric(df.get("Original List Price"))
    df["days_on_market"] = numeric(df.get("DOM"))
    df["status"] = df.get("Status")
    df["buyer_financing"] = df.get("Buyer's Financing")

    return df


# ============================================================
# BUILD PROPERTY / LISTING DATASETS
# ============================================================

def build_properties_dataframe(df):

    properties_cols = [
        "property_id", "property_type", "address", "city", "state", "zip_code", "county",
        "latitude", "longitude", "beds", "baths_full", "baths_half", "sqft", "lot_size", "acres",
        "year_built", "stories", "fireplaces", "garage_spaces", "room_count",
        "hoa_fee", "hoa_amenities", "hoa_fee_covers", "hoa_name", "hoa_phone", "hoa_exists",
        "unit_number", "view"
    ]

    existing_cols = [c for c in properties_cols if c in df.columns]
    result = df[existing_cols].copy()

    result = result[result["property_id"].notna()]
    result = result[result["property_id"].astype(str).str.strip() != ""]
    result = result.drop_duplicates(subset=["property_id"], keep="first")

    return result


def build_active_listings_dataframe(df):

    listing_cols = [
        "listing_id", "property_id", "mls_number",
        "listing_date", "original_list_date", "expiration_date",
        "list_price", "original_list_price", "days_on_market",
        "status", "status_change_timestamp", "buyer_financing"
    ]

    existing_cols = [c for c in listing_cols if c in df.columns]
    result = df[existing_cols].copy()

    result = result[result["listing_id"].notna()]
    result = result[result["listing_id"].astype(str).str.strip() != ""]
    result = result[result["property_id"].notna()]
    result = result.drop_duplicates(subset=["listing_id"], keep="last")

    return result


# ============================================================
# TYPE ENFORCEMENT
# ============================================================

def enforce_property_types(df):

    df = df.copy()

    integer_columns = ["beds", "sqft", "year_built", "fireplaces"]
    numeric_columns = [
        "baths_full", "baths_half", "lot_size", "acres",
        "stories", "garage_spaces", "room_count", "hoa_fee",
        "latitude", "longitude"
    ]

    for col in integer_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round().astype("Int64")

    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def enforce_listing_types(df):

    df = df.copy()

    df["days_on_market"] = pd.to_numeric(df["days_on_market"], errors="coerce").round().astype("Int64")
    df["list_price"] = pd.to_numeric(df["list_price"], errors="coerce")
    df["original_list_price"] = pd.to_numeric(df["original_list_price"], errors="coerce")

    return df


def prepare_for_postgres(df):
    df = df.copy()
    df = df.astype(object)
    df = df.where(pd.notna(df), None)
    return df


# ============================================================
# POSTGRES COPY / UPSERT
# ============================================================

def copy_dataframe(df, table, conn):

    if df.empty:
        print(f"⚠️ Nothing to load into {table}")
        return

    buffer = StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="")
    buffer.seek(0)

    cur = conn.cursor()
    columns = ",".join(f'"{c}"' for c in df.columns)
    sql = f"COPY {table} ({columns}) FROM STDIN WITH CSV"
    cur.copy_expert(sql, buffer)
    conn.commit()


def upsert_properties(df_properties, conn):

    print(f"🏠 Upserting {len(df_properties):,} properties...")

    copy_dataframe(df_properties, "properties_staging", conn)

    cur = conn.cursor()
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
            view = EXCLUDED.view
    """)
    conn.commit()


def upsert_active_listings(df_listings, conn):

    print(f"📋 Upserting {len(df_listings):,} active listings...")

    copy_dataframe(df_listings, "active_listings_staging", conn)

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO active_listings (
            listing_id, property_id, mls_number,
            listing_date, original_list_date, expiration_date,
            list_price, original_list_price, days_on_market,
            status, status_change_timestamp, buyer_financing
        )
        SELECT
            listing_id, property_id, mls_number,
            listing_date, original_list_date, expiration_date,
            list_price, original_list_price, days_on_market,
            status, status_change_timestamp, buyer_financing
        FROM active_listings_staging
        ON CONFLICT (listing_id) DO UPDATE SET
            property_id = EXCLUDED.property_id,
            mls_number = EXCLUDED.mls_number,
            listing_date = EXCLUDED.listing_date,
            original_list_date = EXCLUDED.original_list_date,
            expiration_date = EXCLUDED.expiration_date,
            list_price = EXCLUDED.list_price,
            original_list_price = EXCLUDED.original_list_price,
            days_on_market = EXCLUDED.days_on_market,
            status = EXCLUDED.status,
            status_change_timestamp = EXCLUDED.status_change_timestamp,
            buyer_financing = EXCLUDED.buyer_financing,
            last_updated = NOW()
    """)
    conn.commit()


def mark_stale_listings_inactive(conn):

    print("🧹 Marking stale listings as no longer active...")

    cur = conn.cursor()
    cur.execute("""
        UPDATE active_listings
        SET status = 'INACTIVE', last_updated = NOW()
        WHERE UPPER(TRIM(status)) = 'ACTIVE'
          AND listing_id NOT IN (
              SELECT listing_id FROM active_listings_staging
          )
    """)
    print(f"   Marked inactive: {cur.rowcount:,}")
    conn.commit()


def assign_neighborhoods(conn):

    print("🗺️ Assigning neighborhoods...")

    cur = conn.cursor()
    cur.execute("""
        UPDATE properties p
        SET neighborhood = n.nhood
        FROM sf_neighborhoods n
        WHERE p.latitude IS NOT NULL
          AND p.longitude IS NOT NULL
          AND ST_Contains(
              n.geom,
              ST_SetSRID(ST_MakePoint(p.longitude, p.latitude), 4326)
          )
    """)
    conn.commit()
    print(f"   Neighborhoods assigned: {cur.rowcount:,}")


# ============================================================
# MAIN DATABASE LOAD
# ============================================================

def load_to_postgres(df_properties, df_listings):

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        print("🚀 Loading to DB...")

        cur = conn.cursor()
        cur.execute("TRUNCATE properties_staging;")
        cur.execute("TRUNCATE active_listings_staging;")
        conn.commit()

        df_properties = enforce_property_types(df_properties)
        df_properties = prepare_for_postgres(df_properties)

        df_listings = enforce_listing_types(df_listings)
        df_listings = prepare_for_postgres(df_listings)

        upsert_properties(df_properties, conn)
        assign_neighborhoods(conn)
        upsert_active_listings(df_listings, conn)
        mark_stale_listings_inactive(conn)

        conn.commit()
        print("✅ ACTIVE LISTINGS LOAD COMPLETE")

    except Exception:
        conn.rollback()
        print("❌ LOAD FAILED — transaction rolled back")
        raise

    finally:
        conn.close()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("📥 Loading raw files...")

    df_sfr_raw = pd.read_csv(SFR_FILE, low_memory=False)
    df_condo_raw = pd.read_csv(CONDO_FILE, low_memory=False)
    df_town_raw = pd.read_csv(TOWNHOUSE_FILE, low_memory=False)

    print(f"   SFR:       {len(df_sfr_raw):,}")
    print(f"   CONDO:     {len(df_condo_raw):,}")
    print(f"   TOWNHOUSE: {len(df_town_raw):,}")

    print("🧹 Normalizing...")

    df_sfr = normalize_dataframe(df_sfr_raw, "SFR")
    df_condo = normalize_dataframe(df_condo_raw, "CONDO")
    df_town = normalize_dataframe(df_town_raw, "TOWNHOUSE")

    dfs = [df_sfr, df_condo, df_town]
    dfs = [df for df in dfs if df is not None and not df.empty]

    if not dfs:
        raise ValueError("No active listing data was loaded.")

    df_all = pd.concat(dfs, ignore_index=True)

    print(f"   Combined records: {len(df_all):,}")

    df_properties = build_properties_dataframe(df_all)
    df_listings = build_active_listings_dataframe(df_all)

    print(f"   Properties:       {len(df_properties):,}")
    print(f"   Active listings:  {len(df_listings):,}")

    print("🔎 Validating...")
    print("   Unique property IDs:", df_properties["property_id"].nunique())
    print("   Unique listing IDs:", df_listings["listing_id"].nunique())

    load_to_postgres(df_properties, df_listings)