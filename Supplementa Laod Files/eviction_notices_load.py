# ============================================================
# SF HOUSING INTELLIGENCE
# EVICTION NOTICES LOADER
#
# Source: DataSF "Eviction Notices" (5cei-gny5)
# Matches by geographic proximity (block-level address privacy
# in the source data means text matching isn't viable).
#
# IMPORTANT: Source addresses are deliberately block-level
# ("0 Block Of Leo Street"), not exact street numbers. Matches
# should be understood/displayed as "block-level" context, not
# proof of activity at the exact unit.
# ============================================================

import os
import time
import requests
import pandas as pd
import numpy as np
import psycopg2
from io import StringIO

# ============================================================
# CONFIG — NEON
# ============================================================
# Neon DB config
#DB_CONFIG = {
#    "dbname": "neondb",
#    "user": "neondb_owner",
#    "password": os.environ["SFMETRIC_DB_PASSWORD"],
#    "host": "ep-flat-rice-afl6klhi.c-2.us-west-2.aws.neon.tech",
#    "port": "5432",
#    "sslmode": "require"
#}

#Local DB Config
DB_CONFIG = {
    "dbname": "sfmetric",  # replace with your actual local DB name if different
    "user": "postgres",
    "password": "Main&3&One",  # your local Postgres password
    "host": "localhost",
    "port": "5433",
    "sslmode": "disable"
}

DATASF_ENDPOINT = "https://data.sfgov.org/resource/5cei-gny5.json"
MATCH_RADIUS_METERS = 60  # block-level tolerance, deliberately generous
PAGE_SIZE = 50000  # 🧪 TEMPORARY: small test run — change back to 50000 for full load


# ============================================================
# STEP 1 — FETCH ALL EVICTION NOTICES (dataset is small; no chunking needed)
# ============================================================

def fetch_all_evictions():
    all_rows = []
    offset = 0
    MAX_TOTAL_ROWS = None  # set to e.g. 50 for a small test run, None for unlimited

    while True:
        print(f"   Fetching offset {offset}...")
        response = requests.get(
            DATASF_ENDPOINT,
            params={"$limit": PAGE_SIZE, "$offset": offset, "$order": "eviction_id"},
            timeout=60,
        )
        response.raise_for_status()
        rows = response.json()

        if not rows:
            break

        all_rows.extend(rows)
        offset += PAGE_SIZE
        time.sleep(0.5)

        if len(rows) < PAGE_SIZE:
            break

        if MAX_TOTAL_ROWS is not None and len(all_rows) >= MAX_TOTAL_ROWS:
            break

    return pd.DataFrame(all_rows)


# ============================================================
# STEP 2 — NORMALIZE
# ============================================================

REASON_COLS = [
    "non_payment", "breach", "nuisance", "illegal_use",
    "failure_to_sign_renewal", "access_denial", "unapproved_subtenant",
    "owner_move_in", "demolition", "capital_improvement",
    "substantial_rehab", "ellis_act_withdrawal", "condo_conversion",
    "roommate_same_unit", "other_cause", "late_payments",
    "lead_remediation", "development", "good_samaritan_ends"
]


def extract_lat_lon(loc):
    if not isinstance(loc, dict):
        return None, None
    try:
        lat = float(loc.get("latitude"))
        lon = float(loc.get("longitude"))
        if lat == 0 or lon == 0:
            return None, None
        return lat, lon
    except (TypeError, ValueError):
        return None, None


def normalize_evictions(df):
    df = df.copy()

    latlon = df["client_location"].apply(extract_lat_lon)
    df["latitude"] = latlon.apply(lambda x: x[0])
    df["longitude"] = latlon.apply(lambda x: x[1])

    df = df[df["latitude"].notna() & df["longitude"].notna()]

    df["file_date"] = pd.to_datetime(df["file_date"], errors="coerce")

    for col in REASON_COLS:
        if col not in df.columns:
            df[col] = False
        df[col] = df[col].fillna(False).astype(bool)

    keep_cols = [
        "eviction_id", "address", "zip", "file_date",
        "latitude", "longitude", "neighborhood", "supervisor_district"
    ] + REASON_COLS

    df = df[keep_cols].drop_duplicates(subset=["eviction_id"])

    return df


# ============================================================
# STEP 3 — PROXIMITY MATCH AGAINST OUR PROPERTIES
# ============================================================

def haversine_meters(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius in meters
    lat1r, lon1r, lat2r, lon2r = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c


def get_our_properties(engine):
    query = """
    SELECT property_id, latitude, longitude
    FROM properties
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """
    df = pd.read_sql(query, engine)
    print(f"   Our properties with coordinates: {len(df):,}")
    return df


def match_evictions_to_properties(df_evictions, df_properties):
    """
    For each eviction, find the nearest property within MATCH_RADIUS_METERS.
    Uses a coarse grid pre-filter (round to ~0.001 deg, ~100m) before the
    precise haversine check, to avoid an O(n*m) full cross join.
    """
    df_properties = df_properties.copy()
    df_properties["lat_bucket"] = (df_properties["latitude"] * 200).round().astype(int)
    df_properties["lon_bucket"] = (df_properties["longitude"] * 200).round().astype(int)

    bucket_index = {}
    for _, row in df_properties.iterrows():
        key = (row["lat_bucket"], row["lon_bucket"])
        bucket_index.setdefault(key, []).append(row)

    matched_rows = []

    for _, ev in df_evictions.iterrows():
        lat_b = round(ev["latitude"] * 200)
        lon_b = round(ev["longitude"] * 200)

        candidates = []
        for db in (-1, 0, 1):
            for dl in (-1, 0, 1):
                candidates.extend(bucket_index.get((lat_b + db, lon_b + dl), []))

        if not candidates:
            continue

        best_property_id = None
        best_distance = None

        for cand in candidates:
            dist = haversine_meters(ev["latitude"], ev["longitude"], cand["latitude"], cand["longitude"])
            if dist <= MATCH_RADIUS_METERS and (best_distance is None or dist < best_distance):
                best_distance = dist
                best_property_id = cand["property_id"]

        if best_property_id is not None:
            row = ev.to_dict()
            row["property_id"] = best_property_id
            row["match_distance_meters"] = round(best_distance, 1)
            matched_rows.append(row)

    return pd.DataFrame(matched_rows)


# ============================================================
# STEP 4 — LOAD TO POSTGRES
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
    cur.copy_expert(f"COPY {table} ({columns}) FROM STDIN WITH CSV", buffer)
    conn.commit()


def upsert_evictions(df, conn):
    print(f"🏚️ Upserting {len(df):,} eviction notice matches...")
    copy_dataframe(df, "sf_eviction_notices_staging", conn)

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sf_eviction_notices
        SELECT * FROM sf_eviction_notices_staging
        ON CONFLICT (eviction_id, property_id) DO UPDATE SET
            match_distance_meters = EXCLUDED.match_distance_meters
    """)
    conn.commit()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    engine_url = URL.create(
        drivername="postgresql+psycopg2",
        username=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        host=DB_CONFIG["host"],
        port=int(DB_CONFIG["port"]),
        database=DB_CONFIG["dbname"],
        query={"sslmode": DB_CONFIG["sslmode"]},
    )
    
    engine = create_engine(engine_url)

    print("📥 Step 1: Fetching eviction notices from DataSF...")
    df_raw = fetch_all_evictions()
    print(f"   Raw rows fetched: {len(df_raw):,}")

    print("🧹 Step 2: Normalizing...")
    df_clean = normalize_evictions(df_raw)
    print(f"   Rows with valid location: {len(df_clean):,}")

    print("📍 Step 3: Getting our properties...")
    df_properties = get_our_properties(engine)

    print("🔎 Step 4: Proximity matching (this may take a few minutes)...")
    df_matched = match_evictions_to_properties(df_clean, df_properties)
    print(f"   Matched rows: {len(df_matched):,}")
    print(f"   Unique properties with eviction history: {df_matched['property_id'].nunique():,}")

    if df_matched.empty:
        raise ValueError("No matches found — check coordinates/radius.")

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute("TRUNCATE sf_eviction_notices_staging;")
        conn.commit()

        print("🚀 Step 5: Loading to DB...")
        upsert_evictions(df_matched, conn)

        print("✅ EVICTION NOTICES LOAD COMPLETE")
    except Exception:
        conn.rollback()
        print("❌ LOAD FAILED — transaction rolled back")
        raise
    finally:
        conn.close()