"""
survey_vrma_deltas.py — Survey max per-frame angular deltas for all bones in
all VRMA files referenced by plays/traffic_scene.json.

Reports:
- Per-bone max delta for each VRMA
- Overall per-file max delta and worst bone
- Comparison with 10deg threshold (matches the diagnostic's SMOOTH_THRESHOLD)

Usage:
  python python_scripts/survey_vrma_deltas.py
"""

import struct, json, math, os, sys
from math import acos, pi

GLB_MAGIC = b'glTF'
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

def parse_glb(filepath):
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        if magic != GLB_MAGIC:
            raise ValueError(f"Not a GLB file: {filepath}")
        f.read(8)  # version, total_length
        chunks = {}
        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            chunk_length, chunk_type = struct.unpack('<II', header)
            chunk_data = f.read(chunk_length)
            if chunk_type == CHUNK_JSON:
                chunks['json'] = json.loads(chunk_data.decode('utf-8'))
            elif chunk_type == CHUNK_BIN:
                chunks['bin'] = chunk_data
        return chunks

def accessor_data(gltf, accessor_idx, bin_data):
    acc = gltf['accessors'][accessor_idx]
    bv = gltf['bufferViews'][acc['bufferView']]
    comp_size = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}[acc['componentType']]
    num_comps = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[acc['type']]
    stride = bv.get('byteStride', comp_size * num_comps)
    offset = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
    count = acc['count']
    fmt = {5126: 'f', 5123: 'H', 5122: 'h', 5121: 'B', 5120: 'b', 5125: 'I'}[acc['componentType']]
    out = []
    for i in range(count):
        byte_start = offset + i * stride
        chunk = bin_data[byte_start:byte_start + comp_size * num_comps]
        vals = struct.unpack('<' + fmt * num_comps, chunk)
        out.append(vals if num_comps > 1 else vals[0])
    return out

def quat_angle_deg(a, b):
    dot = abs(a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3])
    return 2 * acos(min(1.0, dot)) * 180.0 / pi

def survey_vrma(filepath, threshold=10.0):
    """Analyze a VRMA file. Returns per-bone and overall max deltas."""
    basename = os.path.basename(filepath)
    chunks = parse_glb(filepath)
    gltf = json.loads(chunks['json']) if isinstance(chunks['json'], str) else chunks['json']
    bin_data = chunks['bin']
    nodes = gltf.get('nodes', [])
    anims = gltf.get('animations', [])
    if not anims:
        return None

    bone_deltas = {}  # {bone_name: [(frame_idx, deg), ...]}
    bone_max = {}     # {bone_name: max_deg}
    total_frames = 0

    for anim in anims:
        channels = anim.get('channels', [])
        samplers = anim.get('samplers', [])
        for ch in channels:
            target = ch.get('target', {})
            node_idx = target.get('node')
            path = target.get('path', '')
            if path != 'rotation':
                continue
            sampler = samplers[ch['sampler']]
            input_data = accessor_data(gltf, sampler['input'], bin_data)
            output_data = accessor_data(gltf, sampler['output'], bin_data)
            node_name = nodes[node_idx].get('name', f'Node_{node_idx}') if node_idx is not None else 'unknown'
            total_frames = max(total_frames, len(output_data))

            if len(output_data) < 2:
                continue

            max_deg = 0
            max_frame = 0
            bad_frames = []
            for i in range(1, len(output_data)):
                deg = quat_angle_deg(output_data[i-1], output_data[i])
                if deg > max_deg:
                    max_deg = deg
                    max_frame = i
                if deg >= threshold:
                    bad_frames.append((i, deg))

            bone_deltas[node_name] = bad_frames
            bone_max[node_name] = max_deg

    # Sort bones by max delta descending
    sorted_bones = sorted(bone_max.items(), key=lambda x: -x[1])

    overall_max = max([d for _, d in sorted_bones], default=0)
    worst_bone = sorted_bones[0][0] if sorted_bones else None
    bones_over_10 = sum(1 for _, d in sorted_bones if d >= 10)
    bones_over_15 = sum(1 for _, d in sorted_bones if d >= 15)

    return {
        'file': basename,
        'total_frames': total_frames,
        'num_animated_bones': len(bone_max),
        'overall_max_deg': round(overall_max, 1),
        'worst_bone': worst_bone,
        'sorted_bones': [(name, round(d, 1)) for name, d in sorted_bones],
        'bones_over_10': bones_over_10,
        'bones_over_15': bones_over_15,
        'bone_bad_frames': {name: frames for name, frames in bone_deltas.items() if frames},
    }

def load_traffic_scene_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def resolve_path(base_dir, clip_ref):
    if not clip_ref:
        return None
    if isinstance(clip_ref, dict):
        clip_ref = clip_ref.get('url', '')
    if clip_ref.startswith('http') or clip_ref.startswith('/'):
        return None
    # Relative to scene.html which is in plays/
    return os.path.normpath(os.path.join(base_dir, '..', clip_ref))

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.normpath(os.path.join(script_dir, '..'))
    scene_json_path = os.path.join(project_root, 'plays', 'traffic_scene.json')

    if not os.path.exists(scene_json_path):
        print(f"ERROR: {scene_json_path} not found")
        sys.exit(1)

    scene = load_traffic_scene_json(scene_json_path)
    vrma_files = set()

    # Collect idle clips
    for actor_def in scene.get('actors', []):
        clip = actor_def.get('idleClip')
        if clip:
            resolved = resolve_path(os.path.join(project_root, 'plays'), clip)
            if resolved:
                vrma_files.add(resolved)

    # Collect timeline clip references
    for ev in scene.get('timeline', []):
        clip_def = ev.get('clip') or (ev.get('layers') or {}).get('BODY')
        if clip_def:
            resolved = resolve_path(os.path.join(project_root, 'plays'), clip_def)
            if resolved:
                vrma_files.add(resolved)

    if not vrma_files:
        print("No VRMA files found in traffic_scene.json")
        sys.exit(1)

    vrma_files = sorted(vrma_files)

    THRESHOLD = 10.0

    print(f"Surveying {len(vrma_files)} VRMA files from traffic_scene.json")
    print(f"Threshold: {THRESHOLD}deg")
    print()

    results = []
    for vf in vrma_files:
        if not os.path.exists(vf):
            print(f"  SKIP (not found): {os.path.basename(vf)}")
            continue
        r = survey_vrma(vf, THRESHOLD)
        if r:
            results.append(r)

    # ── Print per-file bone table ────────────────────────────────────────
    print(f"\n{'='*100}")
    print("PER-FILE BONE MAX DELTAS")
    print(f"{'='*100}")
    for r in results:
        print(f"\n{r['file']}  ({r['total_frames']} frames, {r['num_animated_bones']} bones)")
        print(f"  Overall max: {r['overall_max_deg']}deg  ({r['worst_bone']})")
        print(f"  Bones with max delta >= 10: {r['bones_over_10']}  >= 15: {r['bones_over_15']}")
        print(f"  Worst bones:")
        for name, d in r['sorted_bones'][:10]:
            marker = ' ***' if d >= 10 else ''
            print(f"    {name:30s}: {d:6.1f}deg{marker}")
        if len(r['sorted_bones']) > 10:
            print(f"    ... ({len(r['sorted_bones']) - 10} more bones)")

    # ── Summary table ────────────────────────────────────────────────────
    print(f"\n{'='*100}")
    print("SUMMARY")
    print(f"{'='*100}")
    print(f"{'File':30s} {'Frames':>7s} {'Bones':>6s} {'MaxDeg':>7s} {'WorstBone':20s} {'>10Deg':>6s} {'>15Deg':>6s}")
    print(f"{'-'*30} {'-'*7} {'-'*6} {'-'*7} {'-'*20} {'-'*6} {'-'*6}")
    for r in results:
        print(f"{r['file']:30s} {r['total_frames']:>7d} {r['num_animated_bones']:>6d} "
              f"{r['overall_max_deg']:>6.1f} {r['worst_bone']:20s} "
              f"{r['bones_over_10']:>5d} {r['bones_over_15']:>5d}")

    # ── Cross-file worst bones analysis ──────────────────────────────────
    print(f"\n{'='*100}")
    print("CROSS-FILE WORST BONE COMPARISON")
    print(f"{'='*100}")
    # Collect per-bone max across all files
    all_bone_max = {}  # {bone_name: {file: max_deg, ...}, overall: max}
    for r in results:
        for name, d in r['sorted_bones']:
            if name not in all_bone_max:
                all_bone_max[name] = {}
            all_bone_max[name][r['file']] = d

    # Show bones that appear in the top deltas in multiple files
    bone_file_count = {name: len(data) for name, data in all_bone_max.items()}
    frequent_offenders = [(name, max(data.values()), count)
                         for name, data in all_bone_max.items()
                         if (count := len(data)) >= 2 and max(data.values()) >= 10]
    frequent_offenders.sort(key=lambda x: -x[1])

    if frequent_offenders:
        print(f"\n  Bones with max delta >= 10deg in 2+ files:")
        for name, worst_deg, count in frequent_offenders[:15]:
            print(f"    {name:25s}: max {worst_deg:5.1f}deg  (in {count} files)")
    else:
        print("  No cross-file bone patterns found")

    # ── Pass/fail per the diagnostic threshold ───────────────────────────
    print(f"\n{'='*100}")
    print("PASS/FAIL (threshold: overall max <= 10 = diagnostic SMOOTH_THRESHOLD)")
    print(f"{'='*100}")
    pass_count = sum(1 for r in results if r['overall_max_deg'] <= 10)
    fail_count = sum(1 for r in results if r['overall_max_deg'] > 10)
    print(f"  Pass: {pass_count}/{len(results)}")
    print(f"  Fail: {fail_count}/{len(results)}")
    print()
    for r in results:
        status = 'PASS' if r['overall_max_deg'] <= 10 else 'FAIL'
        print(f"  {r['file']:30s}: {status}  (max {r['overall_max_deg']}deg — {r['worst_bone']})")

    # Print bone-level pass/fail
    print(f"\n  --- Bone-level pass/fail (threshold: <= 10deg) ---")
    for r in results:
        over = [f"{n}({d}deg)" for n, d in r['sorted_bones'] if d > 10]
        if over:
            print(f"  {r['file']:30s}: {len(over)} bones over threshold: {', '.join(over[:8])}{'...' if len(over) > 8 else ''}")

if __name__ == '__main__':
    main()
