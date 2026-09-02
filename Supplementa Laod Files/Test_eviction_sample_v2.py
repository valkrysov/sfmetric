# test_eviction_sample_v2.py
import requests
import pandas as pd

DATASF_ENDPOINT = "https://data.sfgov.org/resource/5cei-gny5.json"

response = requests.get(
    DATASF_ENDPOINT,
    params={"$limit": 20, "$order": "file_date DESC"},
    timeout=30,
)
response.raise_for_status()

rows = response.json()
df = pd.DataFrame(rows)

# Full first row, all fields
print("=== FULL FIRST ROW ===")
for col in df.columns:
    print(f"{col}: {df[col].iloc[0]}")

print()
print("=== BOOLEAN FLAG VALUES (unique across sample) ===")
for col in ["ellis_act_withdrawal", "owner_move_in", "condo_conversion", "non_payment"]:
    if col in df.columns:
        print(f"{col}: {df[col].unique()}")

print()
print("=== HOW MANY ROWS HAVE VALID LAT/LONG? ===")
def has_valid_location(loc):
    if not isinstance(loc, dict):
        return False
    lat = loc.get("latitude")
    lon = loc.get("longitude")
    return lat not in (None, "", "0", "0.0") and lon not in (None, "", "0", "0.0")

valid_count = df["client_location"].apply(has_valid_location).sum()
print(f"{valid_count} of {len(df)} rows have valid lat/long")