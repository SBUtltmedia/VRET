"""Batch run normalize_vrma.py on all test VRMAs."""
import subprocess
import os

FILES = [
    "02_01", "02_03", "02_04",
    "05_01",
    "07_01", "07_12",
    "08_05", "08_07",
    "09_01",
    "104_02", "104_31", "104_44",
    "111_22", "111_28",
]

for name in FILES:
    path = os.path.join("vrma", f"{name}.vrma")
    print(f"[{name}] ...", end=" ", flush=True)
    r = subprocess.run(
        ["python", "python_scripts/normalize_vrma.py", "--in-place", "--threshold=10", path],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode == 0:
        lines = [l for l in r.stdout.split("\n") if l.strip() and "Normalizing" not in l]
        summary = "; ".join(lines[-3:]) if lines else "OK"
        print(f"{summary}")
    else:
        print(f"FAIL: {r.stderr[:200]}")
