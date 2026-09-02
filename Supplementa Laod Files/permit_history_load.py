# ============================================================
# SF HOUSING INTELLIGENCE
# BUILDING PERMITS LOADER
#
# Source: DataSF "Building Permits" (i98e-djp9), DBI
# Matches via block/lot — same clean matching pattern as
# assessor_tax_rolls_load.py.
# ============================================================

import os
import time
import requests
import pandas as pd
from collections import defaultdict
from io import StringIO
import psycopg2

# ============================================================
# CONFIG — LOCAL (safe, zero Neon egress)
# ============================================================

#DB_CONFIG = {
#    "dbname": "sfmetric",  # adjust if your local DB name differs
#    "user": "postgres",
#    "password": "Main&3&One",
#    "host": "localhost",
#    "port": "5433",
#    "sslmode": "disable"
#}
DB_CONFIG = {
    "dbname": "sfmetric",
    "user": "postgres",
    "password": os.environ["SFMETRIC_DB_PASSWORD"],
    "host": "localhost",
    "port": "5433",
    "sslmode": "disable"
}


DATASF_ENDPOINT = "https://data.sfgov.org/resource/i98e-djp9.json"
BLOCK_CHUNK_SIZE = 200

# Only keep permit types worth surfacing — filters out noise
# (e.g. low-value routine permits) at query time via $where,
# reducing what we fetch and normalize.
MIN_ESTIMATED_COST = 1000  # filters out trivial/administrative permits


# ============================================================
# STEP 1 — GET OUR PROPERTIES (with block/lot parsed)
# ============================================================

def get_target_properties(engine):
    query = """
    SELECT DISTINCT property_id
    FROM properties
    WHERE LEFT(property_id, 4) = 'APN_'
    """
    df = pd.read_sql(query, engine)
    print(f"   Target properties: {len(df):,}")
    return df


def parse_block_lot(property_id):
    if not str(property_id).startswith("APN_"):
        return None, None
    remainder = property_id[len("APN_"):]
    if "_UNIT_" in remainder:
        apn_part = remainder.split("_UNIT_")[0]
    else:
        apn_part = remainder
    if "-" not in apn_part:
        return None, None
    block, lot = apn_part.split("-", 1)
    return block.strip(), lot.strip()


def add_block_lot(df_targets):
    df_targets = df_targets.copy()
    parsed = df_targets["property_id"].apply(parse_block_lot)
    df_targets["block"] = parsed.apply(lambda x: x[0])
    df_targets["lot"] = parsed.apply(lambda x: x[1])
    matchable = df_targets[df_targets["block"].notna()]
    print(f"   Matchable (has block/lot): {len(matchable):,}")
    return matchable


# ============================================================
# STEP 2 — FETCH FROM DATASF, FILTERED BY BLOCK
# ============================================================

def fetch_permit_rows(blocks):
    unique_blocks = sorted(set(blocks))
    all_chunks = []

    for i in range(0, len(unique_blocks), BLOCK_CHUNK_SIZE):
        chunk = unique_blocks[i:i + BLOCK_CHUNK_SIZE]
        block_list = ",".join(f"'{b}'" for b in chunk)
        where_clause = f"block in ({block_list})"

        print(f"   Fetching blocks {i+1}-{i+len(chunk)} of {len(unique_blocks)}...")

        try:
            response = requests.get(
                DATASF_ENDPOINT,
                params={"$where": where_clause, "$limit": 50000},
                timeout=60,
            )
            response.raise_for_status()
            rows = response.json()
        except Exception as e:
            print(f"   ⚠️ Chunk failed, skipping: {e}")
            continue

        if rows:
            all_chunks.append(pd.DataFrame(rows))

        time.sleep(0.3)

    if not all_chunks:
        return pd.DataFrame()

    return pd.concat(all_chunks, ignore_index=True)


# ============================================================
# STEP 3 — MATCH TO OUR property_id
# ============================================================

def match_to_properties(df_raw, df_targets):
    if df_raw.empty:
        return pd.DataFrame()

    df_raw = df_raw.copy()
    df_raw["block"] = df_raw["block"].astype(str).str.strip()
    df_raw["lot"] = df_raw["lot"].astype(str).str.strip()

    pair_to_ids = defaultdict(list)
    for _, row in df_targets.iterrows():
        pair_to_ids[(row["block"], row["lot"])].append(row["property_id"])

    matched_rows = []
    for _, row in df_raw.iterrows():
        key = (row["block"], row["lot"])
        for property_id in pair_to_ids.get(key, []):
            new_row = row.to_dict()
            new_row["property_id"] = property_id
            matched_rows.append(new_row)

    if not matched_rows:
        return pd.DataFrame()

    return pd.DataFrame(matched_rows)


# ============================================================
# STEP 4 — NORMALIZE
# ============================================================

YN_COLS = ["adu", "site_permit", "structural_notification", "fire_only_permit"]


def normalize_permits(df):
    df = df.copy()

    keep_cols = {
        "property_id": "property_id",
        "permit_number": "permit_number",
        "permit_type_definition": "permit_type_definition",
        "description": "description",
        "status": "status",
        "filed_date": "filed_date",
        "issued_date": "issued_date",
        "completed_date": "completed_date",
        "estimated_cost": "estimated_cost",
        "existing_use": "existing_use",
        "proposed_use": "proposed_use",
        "existing_units": "existing_units",
        "proposed_units": "proposed_units",
        "adu": "adu",
        "voluntary_soft_story_retrofit": "voluntary_soft_story_retrofit",
        "structural_notification": "structural_notification",
    }

    for col in keep_cols:
        if col not in df.columns:
            df[col] = None
    df = df[list(keep_cols.keys())]

    for col in ["filed_date", "issued_date", "completed_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    df["estimated_cost"] = pd.to_numeric(df["estimated_cost"], errors="coerce")
    df = df[df["estimated_cost"].isna() | (df["estimated_cost"] > MIN_ESTIMATED_COST)]
    df["existing_units"] = pd.to_numeric(df["existing_units"], errors="coerce")       
    df["proposed_units"] = pd.to_numeric(df["proposed_units"], errors="coerce")

    for col in ["adu", "structural_notification"]:
        if col in df.columns:
            df[col] = df[col].map({"Y": True, "N": False}).fillna(False)

    if "voluntary_soft_story_retrofit" in df.columns:
        df["voluntary_soft_story_retrofit"] = df["voluntary_soft_story_retrofit"].map(
            {"Y": True, "N": False}
        ).fillna(False)

    df = df[df["property_id"].notna() & df["permit_number"].notna()]
    df = df.drop_duplicates(subset=["permit_number", "property_id"])

    df = df.astype(object)
    df = df.where(pd.notna(df), None)

    return df


# ============================================================
# STEP 5 — LOAD TO POSTGRES
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


def upsert_permits(df, conn):
    print(f"🔨 Upserting {len(df):,} permit records...")
    copy_dataframe(df, "sf_building_permits_staging", conn)

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sf_building_permits
        SELECT * FROM sf_building_permits_staging
        ON CONFLICT (permit_number, property_id) DO UPDATE SET
            status = EXCLUDED.status,
            issued_date = EXCLUDED.issued_date,
            completed_date = EXCLUDED.completed_date,
            estimated_cost = EXCLUDED.estimated_cost
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
    )
    engine = create_engine(engine_url)

    print("📥 Step 1: Getting target properties...")
    df_targets = get_target_properties(engine)
    df_targets = add_block_lot(df_targets)

    if df_targets.empty:
        raise ValueError("No matchable properties found.")

    print("🌐 Step 2: Fetching permits from DataSF...")
    df_raw = fetch_permit_rows(df_targets["block"].tolist())
    print(f"   Raw rows fetched: {len(df_raw):,}")

    print("🔎 Step 3: Matching to our property_ids...")
    df_matched = match_to_properties(df_raw, df_targets)
    print(f"   Matched rows: {len(df_matched):,}")

    if df_matched.empty:
        raise ValueError("No rows matched.")

    print("🧹 Step 4: Normalizing...")
    df_final = normalize_permits(df_matched)
    print(f"   Final rows: {len(df_final):,}")
    print(f"   Unique properties with permit history: {df_final['property_id'].nunique():,}")

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute("TRUNCATE sf_building_permits_staging;")
        conn.commit()

        print("🚀 Step 5: Loading to DB...")
        upsert_permits(df_final, conn)

        print("✅ BUILDING PERMITS LOAD COMPLETE")
    except Exception:
        conn.rollback()
        print("❌ LOAD FAILED — transaction rolled back")
        raise
    finally:
        conn.close()