import re

# backup.sql is UTF-16 (confirmed by the findstr Unicode warning)
with open("backup.sql", "r", encoding="utf-16") as f:
    content = f.read()

# Grab the CREATE TABLE block for assessor_tax_rolls (not the _staging one)
create_match = re.search(
    r"CREATE TABLE public\.assessor_tax_rolls \(.*?\);\n",
    content,
    re.DOTALL
)

# Grab the COPY ... FROM stdin; ... \.  block (the actual data)
copy_match = re.search(
    r"COPY public\.assessor_tax_rolls \(.*?\n\\\.\n",
    content,
    re.DOTALL
)

if not create_match:
    raise ValueError("Could not find CREATE TABLE for assessor_tax_rolls")
if not copy_match:
    raise ValueError("Could not find COPY data block for assessor_tax_rolls")

with open("assessor_tax_rolls_only.sql", "w", encoding="utf-8") as out:
    out.write("DROP TABLE IF EXISTS assessor_tax_rolls;\n\n")
    out.write(create_match.group(0))
    out.write("\n")
    out.write(copy_match.group(0))

print("✅ Extracted to assessor_tax_rolls_only.sql")
print(f"   CREATE TABLE block: {len(create_match.group(0))} chars")
print(f"   COPY data block: {len(copy_match.group(0))} chars")