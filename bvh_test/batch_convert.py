"""
Batch convert test BVH files to VRMA via Blender.
Usage: python bvh_test/batch_convert.py
"""
import subprocess
import os
import sys
import time

BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
SCRIPT = os.path.abspath("python_scripts/bvh_to_vrma.py")
VRM = os.path.abspath("models/Seed-san.vrm")
BVH_DIR = os.path.abspath("bvh_test")
OUTPUT_DIR = os.path.abspath("bvh_test/vrma_output")

os.makedirs(OUTPUT_DIR, exist_ok=True)

BVH_FILES = [
    "02_01.bvh", "02_03.bvh", "02_04.bvh",
    "05_01.bvh",
    "07_01.bvh", "07_12.bvh",
    "08_05.bvh", "08_07.bvh",
    "09_01.bvh",
    "104_02.bvh", "104_31.bvh", "104_44.bvh",
    "111_22.bvh", "111_28.bvh",
]

results = {}
total_start = time.time()

for bvh_name in BVH_FILES:
    bvh_path = os.path.join(BVH_DIR, bvh_name)
    output_name = bvh_name.replace('.bvh', '.vrma')
    output_path = os.path.join(OUTPUT_DIR, output_name)
    
    if os.path.exists(output_path):
        print(f"[SKIP] {bvh_name} -> already exists ({os.path.getsize(output_path)} bytes)")
        results[bvh_name] = "EXISTS"
        continue
    
    print(f"\n{'='*60}")
    print(f"[CONVERT] {bvh_name}...")
    start = time.time()
    
    cmd = [
        BLENDER, "--background", "--python", SCRIPT,
        "--", "--bvh=" + bvh_path, "--vrm=" + VRM,
        "--output=" + OUTPUT_DIR
    ]
    
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=os.path.dirname(SCRIPT))
        elapsed = time.time() - start
        if r.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"  OK ({elapsed:.1f}s, {size} bytes)")
            results[bvh_name] = "OK"
        else:
            print(f"  FAILED (exit={r.returncode}, {elapsed:.1f}s)")
            print(f"  Last lines: {r.stdout[-500:]}")
            print(f"  Stderr: {r.stderr[-500:]}")
            results[bvh_name] = "FAIL"
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT")
        results[bvh_name] = "TIMEOUT"
    except Exception as e:
        print(f"  ERROR: {e}")
        results[bvh_name] = "ERROR"

total_elapsed = time.time() - total_start
print(f"\n{'='*60}")
print(f"RESULTS ({total_elapsed:.1f}s total):")
ok = sum(1 for v in results.values() if v in ("OK", "EXISTS"))
fail = sum(1 for v in results.values() if v not in ("OK", "EXISTS"))
for name, status in results.items():
    print(f"  {name:20s} {status}")
print(f"\n{ok}/{len(results)} OK, {fail} failed")
print(f"VRMAs in: {OUTPUT_DIR}")
