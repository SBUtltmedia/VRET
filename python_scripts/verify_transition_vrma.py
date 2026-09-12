"""
verify_transition_vrma.py

Verify that a generated transition VRMA file has:
- All per-frame bone rotation deltas ≤ threshold (default 15°)
- Frame 0 matches the last frame of source VRMA A (boundary continuity)
- Frame N matches the first frame of target VRMA B (boundary continuity)

Usage:
  python verify_transition_vrma.py vrma/transitions/02_01_to_05_01.vrma --source-a vrma/02_01.vrma --source-b vrma/05_01.vrma
"""

import struct
import json
import math
import os
import sys

GLB_MAGIC = b'glTF'
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
COMPONENT_BYTE_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
COMPONENT_COUNT = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def parse_glb(filepath):
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        if magic != GLB_MAGIC:
            raise ValueError(f"Not a GLB file: {filepath}")
        version, total_length = struct.unpack('<II', f.read(8))
        chunks = {}
        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            chunk_length, chunk_type = struct.unpack('<II', header)
            chunk_data = f.read(chunk_length)
            if len(chunk_data) < chunk_length:
                break
            if chunk_type == CHUNK_JSON:
                chunks['json'] = json.loads(chunk_data.decode('utf-8'))
            elif chunk_type == CHUNK_BIN:
                chunks['bin'] = chunk_data
        return chunks


def read_accessor(gltf, bin_data, accessor_idx):
    acc = gltf['accessors'][accessor_idx]
    bv = gltf['bufferViews'][acc['bufferView']]
    comp_size = COMPONENT_BYTE_SIZE[acc['componentType']]
    comp_cnt = COMPONENT_COUNT[acc['type']]
    stride = bv.get('byteStride', comp_size * comp_cnt)
    offset = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
    count = acc['count']
    fmt = '<' + 'f' * comp_cnt
    out = []
    for i in range(count):
        byte_start = offset + i * stride
        chunk = bin_data[byte_start:byte_start + comp_size * comp_cnt]
        vals = struct.unpack(fmt, chunk)
        out.append(vals if comp_cnt > 1 else vals[0])
    return out


def quat_dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3]


def quat_angle_deg(a, b):
    dot = min(1.0, max(-1.0, quat_dot(a, b)))
    return 2 * math.acos(abs(dot)) * 180.0 / math.pi


def extract_bone_data(gltf, bin_data, frame_idx=None, use_last=False):
    nodes = gltf.get('nodes', [])
    bone_rots = {}
    hips_pos = None
    for anim in gltf.get('animations', []):
        channels = anim.get('channels', [])
        samplers = anim.get('samplers', [])
        for ch in channels:
            ni = ch['target']['node']
            path = ch['target']['path']
            sidx = ch['sampler']
            if sidx >= len(samplers):
                continue
            samp = samplers[sidx]
            output_idx = samp.get('output', -1)
            try:
                values = read_accessor(gltf, bin_data, output_idx)
            except (IndexError, KeyError):
                continue
            if not values:
                continue
            if frame_idx is not None:
                idx = frame_idx
            elif use_last:
                idx = len(values) - 1
            else:
                idx = 0
            idx = min(idx, len(values) - 1)
            val = values[idx]
            name = nodes[ni].get('name', f'Node_{ni}')
            if path == 'rotation':
                bone_rots[name] = val
            elif path == 'translation' and name == 'Hips':
                hips_pos = val
    return bone_rots, hips_pos


def verify_transition(transition_path, source_a_path=None, source_b_path=None, threshold_deg=15.0):
    basename = os.path.basename(transition_path)
    print(f"\nVerifying: {basename}")

    chunks_t = parse_glb(transition_path)
    gltf_t = chunks_t['json']
    bin_t = chunks_t['bin']
    nodes_t = gltf_t.get('nodes', [])

    # Collect per-bone rotation sequences from the transition
    bone_sequences = {}  # {name: [q0, q1, ..., qN]}
    hips_sequence = None

    for anim in gltf_t.get('animations', []):
        channels = anim.get('channels', [])
        samplers = anim.get('samplers', [])
        for ch in channels:
            ni = ch['target']['node']
            path = ch['target']['path']
            sidx = ch['sampler']
            if sidx >= len(samplers):
                continue
            samp = samplers[sidx]
            output_idx = samp.get('output', -1)
            try:
                values = read_accessor(gltf_t, bin_t, output_idx)
            except (IndexError, KeyError):
                continue
            name = nodes_t[ni].get('name', f'Node_{ni}')
            if path == 'rotation':
                bone_sequences[name] = values
            elif path == 'translation' and name == 'Hips':
                hips_sequence = values

    if not bone_sequences:
        print(f"  FAIL: No bone rotation data found in transition")
        return False

    num_frames = len(next(iter(bone_sequences.values())))
    print(f"  Transition frames: {num_frames}")
    print(f"  Bones with rotation data: {len(bone_sequences)}")

    # Check per-frame deltas within the transition
    max_delta = 0
    worst_bone = ''
    worst_frame = -1
    bones_over_threshold = []

    for name, values in bone_sequences.items():
        for i in range(1, len(values)):
            angle = quat_angle_deg(values[i-1], values[i])
            if angle > max_delta:
                max_delta = angle
                worst_bone = name
                worst_frame = i
            if angle > threshold_deg:
                bones_over_threshold.append((name, i, angle))

    print(f"  Max internal delta: {max_delta:.2f}° ({worst_bone} frame {worst_frame})")

    # Check boundary continuity: frame 0 matches A's last frame
    boundary_ok = True
    if source_a_path:
        print(f"\n  Checking boundary with source A: {os.path.basename(source_a_path)}")
        chunks_a = parse_glb(source_a_path)
        gltf_a = chunks_a['json']
        bin_a = chunks_a['bin']
        rots_a_end, pos_a_end = extract_bone_data(gltf_a, bin_a, use_last=True)
        boundary_errors = []
        for name, values in bone_sequences.items():
            if name not in rots_a_end:
                continue
            q_t = values[0]
            q_a = rots_a_end[name]
            angle = quat_angle_deg(q_t, q_a)
            if angle > threshold_deg:
                boundary_errors.append((name, angle))
        if boundary_errors:
            print(f"  FAIL: {len(boundary_errors)} bones exceed {threshold_deg}° at frame 0 boundary")
            for name, angle in boundary_errors[:5]:
                print(f"    {name}: {angle:.2f}°")
            boundary_ok = False
        else:
            print(f"  OK: frame 0 matches A's last frame (all bones ≤ {threshold_deg}°)")

    if source_b_path:
        print(f"  Checking boundary with source B: {os.path.basename(source_b_path)}")
        chunks_b = parse_glb(source_b_path)
        gltf_b = chunks_b['json']
        bin_b = chunks_b['bin']
        rots_b_start, pos_b_start = extract_bone_data(gltf_b, bin_b, use_last=False)
        boundary_errors = []
        for name, values in bone_sequences.items():
            if name not in rots_b_start:
                continue
            q_t = values[-1]
            q_b = rots_b_start[name]
            angle = quat_angle_deg(q_t, q_b)
            if angle > threshold_deg:
                boundary_errors.append((name, angle))
        if boundary_errors:
            print(f"  FAIL: {len(boundary_errors)} bones exceed {threshold_deg}° at last frame boundary")
            for name, angle in boundary_errors[:5]:
                print(f"    {name}: {angle:.2f}°")
            boundary_ok = False
        else:
            print(f"  OK: frame {num_frames - 1} matches B's first frame (all bones ≤ {threshold_deg}°)")

    # Check Hips translation boundary
    if source_a_path and source_b_path and hips_sequence is not None:
        _, pos_a_end = extract_bone_data(gltf_a, bin_a, use_last=True)
        _, pos_b_start = extract_bone_data(gltf_b, bin_b, use_last=False)
        if pos_a_end and pos_b_start:
            # Check first frame
            p_t0 = hips_sequence[0]
            dx = abs(p_t0[0] - pos_a_end[0])
            dy = abs(p_t0[1] - pos_a_end[1])
            dz = abs(p_t0[2] - pos_a_end[2])
            max_pos_delta = max(dx, dy, dz)
            if max_pos_delta > 0.01:
                print(f"  WARN: Hips position at frame 0 differs from A's last frame: ({p_t0[0]:.6f} vs {pos_a_end[0]:.6f})")

            # Check last frame
            p_tn = hips_sequence[-1]
            dx = abs(p_tn[0] - pos_b_start[0])
            dy = abs(p_tn[1] - pos_b_start[1])
            dz = abs(p_tn[2] - pos_b_start[2])
            max_pos_delta = max(dx, dy, dz)
            if max_pos_delta > 0.01:
                print(f"  WARN: Hips position at last frame differs from B's first frame: ({p_tn[0]:.6f} vs {pos_b_start[0]:.6f})")

    # Overall result
    if bones_over_threshold:
        print(f"\n  FAIL: {len(bones_over_threshold)} bones exceed {threshold_deg}°/frame threshold")
        # Show worst 5
        bones_over_threshold.sort(key=lambda x: -x[2])
        for name, frame, angle in bones_over_threshold[:5]:
            print(f"    {name}: {angle:.2f}° at frame {frame}→{frame+1}")
        return False

    if not boundary_ok:
        print(f"\n  FAIL: Boundary continuity check failed")
        return False

    print(f"\n  PASS: All bones ≤ {threshold_deg}°/frame, boundaries clean")
    return True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Verify transition VRMA meets continuity thresholds')
    parser.add_argument('transition', help='Transition VRMA file to verify')
    parser.add_argument('--source-a', help='Source VRMA A (for boundary check)')
    parser.add_argument('--source-b', help='Source VRMA B (for boundary check)')
    parser.add_argument('--threshold', type=float, default=15.0,
                        help=f'Per-frame rotation threshold in degrees (default: 15.0)')
    args = parser.parse_args()

    success = verify_transition(
        args.transition,
        source_a_path=args.source_a,
        source_b_path=args.source_b,
        threshold_deg=args.threshold,
    )
    sys.exit(0 if success else 1)
