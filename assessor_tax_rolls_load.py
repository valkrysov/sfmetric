# ============================================================
# SF HOUSING INTELLIGENCE
# ASSESSOR HISTORICAL TAX ROLLS LOADER
#
# Pulls DataSF's "Assessor Historical Secured Property Tax
# Rolls" (wv5m-vpq2), filtered to only the block/lot pairs
# that correspond to properties already in our own database.
#
# V1 SCOPE: only properties that are currently active listings
# or have sold in the last 24 months — keeps the initial pull
# small and fast to validate end-to-end before scaling up.
#
# LIMITATION: our own property_id generation strips letter
# suffixes from lot numbers (e.g. "005H" -> "005"), so a small
# number of suffixed-lot properties won't match. Acceptable
# for v1 — they simply won't show assessor history.
# ============================================================

import os
import pandas as pd
from io import StringIO
from collections import defaultdict
import psycopg2

# ============================================================
# CONFIG — NEON
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


DATASF_ENDPOINT = "https://data.sfgov.org/resource/wv5m-vpq2.json"
BLOCK_CHUNK_SIZE = 200


# ============================================================
# STEP 1 — GET OUR OWN TARGET PROPERTIES
# ============================================================

def get_target_properties(engine):
    query = """
    SELECT DISTINCT p.property_id
    FROM properties p
    WHERE LEFT(p.property_id, 4) = 'APN_'
    """
    df = pd.read_sql(query, engine)
    print(f"   Target properties: {len(df):,}")
    return df


def parse_block_lot(property_id):
    """
    APN_0732-074            -> ("0732", "074")
    APN_0732-074_UNIT_610   -> ("0732", "074")
    ADDR_... (no APN)       -> (None, None) — not matchable
    """
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

def fetch_assessor_rows(blocks):
    import requests

    unique_blocks = sorted(set(blocks))

    all_chunks = []

    import time

    for i in range(0, len(unique_blocks), BLOCK_CHUNK_SIZE):
        chunk = unique_blocks[i:i + BLOCK_CHUNK_SIZE]
        block_list = ",".join(f"'{b}'" for b in chunk)
        where_clause = f"block in ({block_list})"

        print(f"   Fetching blocks {i+1}-{i+len(chunk)} of {len(unique_blocks)}...")

        time.sleep(0.5)


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

    if not all_chunks:
        return pd.DataFrame()

    return pd.concat(all_chunks, ignore_index=True)

# ============================================================
# STEP 3 — FILTER TO EXACT BLOCK+LOT MATCHES, MAP TO property_id
# ============================================================

def match_to_properties(df_raw, df_targets):
    if df_raw.empty:
        return pd.DataFrame()

    pair_to_ids = defaultdict(list)
    for _, row in df_targets.iterrows():
        pair_to_ids[(row["block"], row["lot"])].append(row["property_id"])

    df_raw = df_raw.copy()
    df_raw["block"] = df_raw["block"].astype(str).str.strip()
    df_raw["lot"] = df_raw["lot"].astype(str).str.strip()

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
# STEP 4 — NORMALIZE FOR OUR SCHEMA
# ============================================================

def normalize_assessor_df(df):
    df = df.copy()

    keep_cols = {
        "property_id": "property_id",
        "closed_roll_year": "closed_roll_year",
        "block": "block",
        "lot": "lot",
        "use_definition": "use_definition",
        "property_class_code_definition": "property_class_code_definition",
        "year_property_built": "year_property_built",
        "number_of_bedrooms": "number_of_bedrooms",
        "number_of_bathrooms": "number_of_bathrooms",
        "property_area": "property_area",
        "current_sales_date": "current_sales_date",
        "assessed_land_value": "assessed_land_value",
        "assessed_improvement_value": "assessed_improvement_value",
        "assessor_neighborhood": "assessor_neighborhood",
        "data_as_of": "data_as_of",
    }

    for col in keep_cols:
        if col not in df.columns:
            df[col] = None

    df = df[list(keep_cols.keys())]

    df["closed_roll_year"] = (
        pd.to_numeric(df["closed_roll_year"], errors="coerce").round().astype("Int64")
    )
    df["year_property_built"] = (
        pd.to_numeric(df["year_property_built"], errors="coerce").round().astype("Int64")
    )
    df["number_of_bedrooms"] = pd.to_numeric(df["number_of_bedrooms"], errors="coerce")
    df["number_of_bathrooms"] = pd.to_numeric(df["number_of_bathrooms"], errors="coerce")
    df["property_area"] = pd.to_numeric(df["property_area"], errors="coerce")
    df["assessed_land_value"] = pd.to_numeric(df["assessed_land_value"], errors="coerce")
    df["assessed_improvement_value"] = pd.to_numeric(df["assessed_improvement_value"], errors="coerce")




    df["current_sales_date"] = pd.to_datetime(df["current_sales_date"], errors="coerce")
    df["data_as_of"] = pd.to_datetime(df["data_as_of"], errors="coerce")

    df = df[df["property_id"].notna() & df["closed_roll_year"].notna()]

    df = df.drop_duplicates(subset=["property_id", "closed_roll_year"], keep="last")

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
    sql = f"COPY {table} ({columns}) FROM STDIN WITH CSV"
    cur.copy_expert(sql, buffer)
    conn.commit()


def upsert_assessor_rolls(df, conn):
    print(f"🏛️ Upserting {len(df):,} assessor tax roll rows...")

    copy_dataframe(df, "assessor_tax_rolls_staging", conn)

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO assessor_tax_rolls
        SELECT * FROM assessor_tax_rolls_staging
        ON CONFLICT (property_id, closed_roll_year) DO UPDATE SET
            block = EXCLUDED.block,
            lot = EXCLUDED.lot,
            use_definition = EXCLUDED.use_definition,
            property_class_code_definition = EXCLUDED.property_class_code_definition,
            year_property_built = EXCLUDED.year_property_built,
            number_of_bedrooms = EXCLUDED.number_of_bedrooms,
            number_of_bathrooms = EXCLUDED.number_of_bathrooms,
            property_area = EXCLUDED.property_area,
            current_sales_date = EXCLUDED.current_sales_date,
            assessed_land_value = EXCLUDED.assessed_land_value,
            assessed_improvement_value = EXCLUDED.assessed_improvement_value,
            assessor_neighborhood = EXCLUDED.assessor_neighborhood,
            data_as_of = EXCLUDED.data_as_of
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


    print("📥 Step 1: Getting target properties from our DB...")
    df_targets = get_target_properties(engine)
    df_targets = add_block_lot(df_targets)

    if df_targets.empty:
        raise ValueError("No matchable properties found — nothing to load.")

    print("🌐 Step 2: Fetching assessor data from DataSF...")
    df_raw = fetch_assessor_rows(df_targets["block"].tolist())
    print(f"   Raw rows fetched: {len(df_raw):,}")

    print("🔎 Step 3: Matching to our property_ids...")
    df_matched = match_to_properties(df_raw, df_targets)
    print(f"   Matched rows: {len(df_matched):,}")

    if df_matched.empty:
        raise ValueError("No rows matched — check block/lot parsing.")

    print("🧹 Step 4: Normalizing...")
    df_final = normalize_assessor_df(df_matched)
    print(f"   Final rows: {len(df_final):,}")
    print(f"   Unique properties covered: {df_final['property_id'].nunique():,}")

    print("🚀 Step 5: Loading to DB...")
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute("TRUNCATE assessor_tax_rolls_staging;")
        conn.commit()

        upsert_assessor_rolls(df_final, conn)

        print("✅ ASSESSOR TAX ROLLS LOAD COMPLETE")
    except Exception:
        conn.rollback()
        print("❌ LOAD FAILED — transaction rolled back")
        raise
    finally:
        conn.close()