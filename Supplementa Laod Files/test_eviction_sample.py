# test_eviction_sample.py
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

print(f"Rows returned: {len(df)}")
print(f"Columns: {df.columns.tolist()}")
print()
print(df[["eviction_id", "address", "file_date", "ellis_act_withdrawal", "owner_move_in", "condo_conversion"]].to_string())
print()
print("Sample client_location field (first row):")
print(df["client_location"].iloc[0])