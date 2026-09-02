# scan_apn_letter_suffixes.py
import pandas as pd
import glob
import re

files = glob.glob("*.csv")  # run from your HistoricalSales folder

all_apns = []

for f in files:
    try:
        df = pd.read_csv(f, low_memory=False)
    except Exception as e:
        print(f"Skipped {f}: {e}")
        continue

    if "Parcel Number" not in df.columns:
        continue

    apns = df["Parcel Number"].dropna().astype(str).str.strip()
    for apn in apns:
        all_apns.append(apn)

print(f"Total APN values scanned: {len(all_apns):,}")

# Find ones with a trailing letter on the lot portion (e.g. "1625-005C")
suffixed = [a for a in all_apns if re.search(r"[A-Za-z]$", a)]
print(f"APNs with a trailing letter suffix: {len(suffixed):,}")

# Check how many of those collide with an existing unsuffixed APN
unsuffixed_set = set(a for a in all_apns if not re.search(r"[A-Za-z]$", a))

collisions = []
for a in suffixed:
    stripped = re.sub(r"[A-Za-z]+$", "", a)
    if stripped in unsuffixed_set:
        collisions.append((a, stripped))

print(f"Suffixed APNs that collide with an existing unsuffixed APN: {len(collisions):,}")
print()
print("Sample collisions:")
for a, s in collisions[:20]:
    print(f"  {a}  ->  clashes with  {s}")