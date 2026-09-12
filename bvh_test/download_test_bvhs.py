"""
Batch download BVH test files from GitHub mirror.
Downloads only the files needed for our test set.
"""
import urllib.request
import os
import json

BASE_URL = "https://raw.githubusercontent.com/una-dinosauria/cmu-mocap/master/data"

FILES = [
    "002/02_01.bvh",
    "002/02_03.bvh",
    "005/05_01.bvh",
    "007/07_01.bvh",
    "007/07_12.bvh",
    "008/08_05.bvh",
    "008/08_07.bvh",
    "009/09_01.bvh",
    "104/104_02.bvh",
    "104/104_31.bvh",
    "104/104_44.bvh",
    "111/111_22.bvh",
    "111/111_28.bvh",
]

OUTPUT_DIR = "bvh_test"

os.makedirs(OUTPUT_DIR, exist_ok=True)

for fname in FILES:
    url = f"{BASE_URL}/{fname}"
    local = os.path.join(OUTPUT_DIR, os.path.basename(fname))
    if os.path.exists(local):
        size = os.path.getsize(local)
        print(f"  EXISTS {local} ({size} bytes)")
        continue
    print(f"  Downloading {url}...", end=" ")
    try:
        urllib.request.urlretrieve(url, local)
        size = os.path.getsize(local)
        print(f"OK ({size} bytes)")
    except Exception as e:
        print(f"FAILED: {e}")

print(f"\nDone. Files in {os.path.abspath(OUTPUT_DIR)}:")
for f in sorted(os.listdir(OUTPUT_DIR)):
    if f.endswith('.bvh'):
        print(f"  {f:20s} {os.path.getsize(os.path.join(OUTPUT_DIR, f)):>8} bytes")
