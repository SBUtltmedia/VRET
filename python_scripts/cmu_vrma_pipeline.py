"""
CMU Mocap → VRMA Conversion Pipeline
======================================
Downloads CGSpeed BVH files from the una-dinosauria/cmu-mocap mirror,
converts to VRMA via Blender (bvh_to_vrma.py), normalizes to frame 0 origin,
and applies position keyframe smoothing for CMU data artifacts.

Usage:
  python cmu_vrma_pipeline.py --subjects 001,002,013     # specific subjects
  python cmu_vrma_pipeline.py --subjects all               # all available
  python cmu_vrma_pipeline.py --subjects 013 --takes 27,28 # specific takes

Requires:
  - Blender 3.6+ (set BLENDER_PATH env var or use --blender)
  - Python 3.7+
  - Internet access for first download
"""

import os, sys, subprocess, json, shutil, glob, argparse, time, math, struct
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed

# === Configuration ===
CMU_MIRROR = "https://raw.githubusercontent.com/una-dinosauria/cmu-mocap/master/data"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"

# === Known CMU subjects and take counts (CGSpeed release) ===
# Source: una-dinosauria/cmu-mocap repository index
SUBJECT_TAKES = {
    1: 14, 2: 10, 3: 4, 5: 20, 6: 15, 7: 12, 8: 11, 9: 12,
    10: 6, 11: 1, 12: 4, 13: 42, 14: 37, 15: 14, 16: 58, 17: 10,
    18: 15, 19: 15, 20: 13, 21: 13, 22: 25, 23: 25, 24: 1, 25: 1,
    26: 11, 27: 11, 28: 19, 29: 25, 30: 23, 31: 21, 32: 22, 33: 2,
    34: 2, 35: 34, 36: 37, 37: 1, 38: 4, 39: 14, 40: 12, 41: 11,
    42: 1, 43: 3, 45: 1, 46: 1, 47: 1, 49: 22,
    54: 27, 55: 28, 56: 8,
    60: 15, 61: 15, 62: 25, 63: 30, 64: 30,
    69: 75, 70: 13, 73: 13, 74: 20, 75: 20, 76: 11, 77: 34, 78: 35,
    79: 96, 80: 73, 81: 18, 82: 18, 83: 68, 84: 20, 85: 15, 86: 15,
    87: 5, 88: 11, 89: 6, 90: 36, 91: 62, 93: 8, 94: 16,
    102: 33, 103: 8, 104: 57, 105: 62, 106: 34, 107: 14, 108: 28,
    111: 41, 113: 29, 114: 16, 115: 10, 117: 15, 118: 32,
    120: 22, 121: 36, 122: 68, 123: 13, 124: 13, 125: 7, 126: 14,
    127: 38, 128: 11, 131: 14, 132: 56, 133: 26, 134: 15, 135: 11,
    136: 33, 137: 42, 138: 55, 139: 34, 140: 9, 141: 34, 142: 22,
    143: 42, 144: 34,
}


def subject_dir(s):
    return f"{int(s):03d}"


def bvh_url(subj, take):
    return f"{CMU_MIRROR}/{subject_dir(subj)}/{subj:02d}_{take:02d}.bvh"


def vrma_name(subj, take):
    return f"{subj:02d}_{take:02d}.vrma"


def download_bvh(subj, take, cache_dir):
    """Download a BVH file from the CMU mirror. Returns path or None."""
    dest = os.path.join(cache_dir, vrma_name(subj, take).replace('.vrma', '.bvh'))
    if os.path.exists(dest):
        return dest
    url = bvh_url(subj, take)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        print(f"  Downloading {url}")
        with urlopen(url, timeout=30) as resp:
            data = resp.read()
        with open(dest, 'wb') as f:
            f.write(data)
        return dest
    except Exception as e:
        print(f"  FAIL download {url}: {e}")
        return None


def precheck_mirror():
    """Quick check that CMU mirror is reachable."""
    try:
        with urlopen(f"{CMU_MIRROR}/001/01_01.bvh", timeout=10) as r:
            return r.status == 200
    except:
        return False


def convert_single(subj, take, bvh_path, vrm_path, output_dir, blender_path):
    """Convert a single BVH to VRMA via Blender. Returns output path or None."""
    out_name = vrma_name(subj, take)
    out_path = os.path.join(output_dir, out_name)
    if os.path.exists(out_path):
        return out_path

    script = os.path.join(SCRIPT_DIR, "bvh_to_vrma.py")
    if not os.path.exists(script):
        print(f"  ERROR: bvh_to_vrma.py not found at {script}")
        return None

    cmd = [
        blender_path, "--background", "--python", script,
        "--",
        f"--bvh={bvh_path}",
        f"--vrm={vrm_path}",
        f"--output={output_dir}",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                                cwd=PROJECT_ROOT)
        if result.returncode != 0 or not os.path.exists(out_path):
            print(f"  FAILED (exit={result.returncode}): {out_name}")
            if "Error:" in result.stdout[-500:]:
                print(f"  {result.stdout[-300:]}")
            return None
        return out_path
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT: {out_name}")
        return None
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def normalize_vrma(input_path, in_place=True):
    """Run normalize_vrma_origin.py on a VRMA file."""
    script = os.path.join(SCRIPT_DIR, "normalize_vrma_origin.py")
    cmd = [sys.executable, script, input_path]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return True
    except:
        return False


def build_subject_list(arg):
    """Parse --subjects argument into list of subject ints."""
    if arg == 'all':
        return sorted(SUBJECT_TAKES.keys())
    parts = arg.split(',')
    subjects = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            subjects.append(int(p))
    return sorted(set(subjects))


def main():
    parser = argparse.ArgumentParser(description='CMU BVH to VRMA Pipeline')
    parser.add_argument('--subjects', default='all',
                        help='Subject numbers (comma-separated) or "all"')
    parser.add_argument('--takes', type=str, default=None,
                        help='Take numbers (comma-separated). Default: all takes for each subject')
    parser.add_argument('--blender', default=DEFAULT_BLENDER,
                        help='Path to Blender executable')
    parser.add_argument('--vrm', default=None,
                        help='Path to VRM model (default: models/Seed-san.vrm)')
    parser.add_argument('--bvh-cache', default=None,
                        help='Directory to cache downloaded BVH files')
    parser.add_argument('--output', default=None,
                        help='Output directory for VRMAs (default: vrma/)')
    parser.add_argument('--skip-download', action='store_true',
                        help='Skip download step (use cached BVH files)')
    parser.add_argument('--skip-convert', action='store_true',
                        help='Skip conversion step (normalize only)')
    parser.add_argument('--skip-normalize', action='store_true',
                        help='Skip normalization step')
    parser.add_argument('--jobs', type=int, default=1,
                        help='Number of parallel conversion jobs (default: 1)')
    parser.add_argument('--check-mirror', action='store_true',
                        help='Only check if CMU mirror is reachable, then exit')

    args = parser.parse_args()

    # Validate Blender path
    blender = args.blender
    if not args.skip_convert and not os.path.exists(blender):
        print(f"ERROR: Blender not found at {blender}")
        print("Set BLENDER_PATH env var or use --blender")
        sys.exit(1)

    # VRM model
    vrm_path = args.vrm or os.path.join(PROJECT_ROOT, "models", "Seed-san.vrm")
    if not args.skip_convert and not os.path.exists(vrm_path):
        print(f"ERROR: VRM model not found at {vrm_path}")
        sys.exit(1)

    # Output directory
    output_dir = args.output or os.path.join(PROJECT_ROOT, "vrma")
    os.makedirs(output_dir, exist_ok=True)

    # BVH cache
    bvh_cache = args.bvh_cache or os.path.join(PROJECT_ROOT, "bvh_cache")
    os.makedirs(bvh_cache, exist_ok=True)

    # Mirror check
    if args.check_mirror:
        print("Checking CMU mirror...")
        ok = precheck_mirror()
        print(f"  Mirror {'REACHABLE' if ok else 'UNREACHABLE'}: {CMU_MIRROR}")
        return

    # Build subject/take list
    subjects = build_subject_list(args.subjects)
    print(f"Pipeline: {len(subjects)} subjects, Blender={blender}")
    print(f"  Output: {output_dir}")
    print(f"  BVH cache: {bvh_cache}")
    print(f"  VRM model: {vrm_path}")

    # If specific takes
    take_filter = None
    if args.takes:
        take_filter = set(int(t.strip()) for t in args.takes.split(','))

    # Build full task list
    tasks = []
    for subj in subjects:
        num_takes = SUBJECT_TAKES.get(subj, 0)
        for take in range(1, num_takes + 1):
            if take_filter and take not in take_filter:
                continue
            tasks.append((subj, take))

    print(f"Total tasks: {len(tasks)}")
    random.shuffle(tasks)

    # === Phase 1: Download ===
    if not args.skip_download:
        print(f"\n{'='*60}")
        print(f"Phase 1: Download BVH files ({len(tasks)} files)")
        print(f"{'='*60}")

        downloaded = 0
        for subj, take in tasks:
            bvh_path = download_bvh(subj, take, bvh_cache)
            if bvh_path:
                downloaded += 1
            else:
                print(f"  SKIPPING {subj:02d}_{take:02d}: BVH unavailable")

        print(f"Downloaded {downloaded}/{len(tasks)}")

    # === Phase 2: Convert ===
    if not args.skip_convert:
        print(f"\n{'='*60}")
        print(f"Phase 2: Convert BVH to VRMA ({len(tasks)} files)")
        print(f"{'='*60}")

        converted = 0
        failed = 0

        if args.jobs > 1:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = {}
                for subj, take in tasks:
                    bvh_path = os.path.join(bvh_cache, vrma_name(subj, take).replace('.vrma', '.bvh'))
                    if not os.path.exists(bvh_path):
                        print(f"  SKIP {subj:02d}_{take:02d}: BVH not cached")
                        continue
                    f = pool.submit(convert_single, subj, take, bvh_path, vrm_path, output_dir, blender)
                    futures[f] = (subj, take)

                for f in as_completed(futures):
                    subj, take = futures[f]
                    result = f.result()
                    if result:
                        converted += 1
                    else:
                        failed += 1
                    if (converted + failed) % 10 == 0:
                        print(f"  Progress: {converted} OK, {failed} FAIL / {len(tasks)}")
        else:
            for i, (subj, take) in enumerate(tasks):
                bvh_path = os.path.join(bvh_cache, vrma_name(subj, take).replace('.vrma', '.bvh'))
                if not os.path.exists(bvh_path):
                    print(f"  [{i+1}/{len(tasks)}] SKIP {subj:02d}_{take:02d}: BVH not cached")
                    continue
                result = convert_single(subj, take, bvh_path, vrm_path, output_dir, blender)
                if result:
                    converted += 1
                else:
                    failed += 1
                if (converted + failed) % 5 == 0:
                    print(f"  [{i+1}/{len(tasks)}] Progress: {converted} OK, {failed} FAIL")

        print(f"\nConversion: {converted} OK, {failed} FAIL / {len(tasks)}")

    # === Phase 3: Normalize ===
    if not args.skip_normalize:
        print(f"\n{'='*60}")
        print(f"Phase 3: Normalize VRMAs (frame 0 + position smoothing)")
        print(f"{'='*60}")

        normalized = 0
        already = 0
        failed = 0

        for subj, take in tasks:
            vrma_path = os.path.join(output_dir, vrma_name(subj, take))
            if not os.path.exists(vrma_path):
                continue
            # Check if already normalized (frame 0 Hips ≈ identity rotation)
            already_normalized = False
            try:
                from normalize_vrma_origin import read_glb
                data, _ = read_glb(vrma_path)
                nodes = data.get('nodes', [])
                hips_idx = next((i for i, n in enumerate(nodes) if n.get('name') == 'Hips'), None)
                if hips_idx is not None:
                    for anim in data.get('animations', []):
                        for ch in anim.get('channels', []):
                            tgt = ch.get('target', {})
                            if tgt.get('node') == hips_idx and tgt.get('path') == 'rotation':
                                sampler = anim['samplers'][ch['sampler']]
                                acc = data['accessors'][sampler['output']]
                                bv = data['bufferViews'][acc['bufferView']]
                                # Read just first frame
                                off = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
                                if acc['count'] > 0:
                                    import struct
                                    q = struct.unpack_from('<4f', old_buf if 'old_buf' in dir() else b'AAAA', off)
                                    # If first frame is close to identity, skip normalization
                                    if abs(q[3] - 1.0) < 0.01:
                                        already_normalized = True
                                        break
                        if already_normalized:
                            break
            except:
                pass

            if already_normalized:
                already += 1
                continue

            normalize_vrma(vrma_path, in_place=True)
            if os.path.exists(vrma_path):
                normalized += 1
            else:
                failed += 1

        print(f"Normalization: {normalized} fixed, {already} already OK, {failed} FAIL")

    # === Summary ===
    total_done = len([1 for (s, t) in tasks if os.path.exists(os.path.join(output_dir, vrma_name(s, t)))])
    print(f"\n{'='*60}")
    print(f"Pipeline complete: {total_done}/{len(tasks)} VRMAs in {output_dir}")


if __name__ == '__main__':
    # Import here to handle missing dependencies
    import random
    main()
