"""
test_transition.py

Pure Python test: reads clip A, transition VRMA, and clip B; concatenates
per-bone keyframe arrays; measures angular deltas at the two concatenation
boundaries (A->transition and transition->B) and within each clip. Reports
max deltas and PASS/FAIL at the configured thresholds.

Usage:
  python test_transition.py vrma/02_01.vrma vrma/test_transition.vrma vrma/111_37.vrma
  python test_transition.py A.vrma T.vrma B.vrma --rot-threshold 15 --pos-threshold 0.05
"""

import struct, json, sys, math, os

COMPONENT_BYTE_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
COMPONENT_COUNT = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}
EXT_NAME = 'VRMC_vrm_animation'

def parse_glb(filepath):
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        if magic != b'glTF':
            raise ValueError(f"Not a GLB file: {filepath}")
        version, total_length = struct.unpack('<II', f.read(8))
        json_data = None
        bin_data = bytearray()
        while f.tell() < total_length:
            hdr = f.read(8)
            if len(hdr) < 8: break
            cl, ct = struct.unpack('<II', hdr)
            cd = f.read(cl)
            if len(cd) < cl: break
            if ct == 0x4E4F534A:
                json_data = json.loads(cd.decode('utf-8'))
            elif ct == 0x004E4942:
                bin_data = bytearray(cd)
        if json_data is None:
            raise ValueError("No JSON chunk found")
        return json_data, bin_data

def read_accessor(gltf, bin_data, acc_idx):
    acc = gltf['accessors'][acc_idx]
    bv = gltf['bufferViews'][acc['bufferView']]
    cs = COMPONENT_BYTE_SIZE[acc['componentType']]
    cc = COMPONENT_COUNT[acc['type']]
    stride = bv.get('byteStride', cs * cc)
    off = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
    cnt = acc['count']
    fmt = '<' + 'f' * cc
    out = []
    for i in range(cnt):
        chunk = bin_data[off + i*stride:off + i*stride + cs*cc]
        vals = struct.unpack(fmt, chunk)
        out.append(vals if cc > 1 else vals[0])
    return out

def get_human_bones(gltf):
    ext = gltf.get('extensions', {}).get(EXT_NAME, {})
    return ext.get('humanoid', {}).get('humanBones', {})

def extract_all_keyframes(gltf, bin_data, hb):
    """Extract ALL rotation keyframes and Hips translation keyframes per standard bone name.
    
    Returns:
        rot_kfs: {std_name: [(qw,qx,qy,qz), ...]}
        pos_kfs: [ (x,y,z), ... ] or None
    """
    rot_kfs = {}
    pos_kfs = None
    nodes = gltf.get('nodes', [])
    
    for anim in gltf.get('animations', []):
        for ch in anim.get('channels', []):
            ni = ch['target']['node']
            path = ch['target']['path']
            sidx = ch['sampler']
            if sidx >= len(anim['samplers']):
                continue
            samp = anim['samplers'][sidx]
            out_idx = samp.get('output', -1)
            if out_idx < 0 or out_idx >= len(gltf['accessors']):
                continue
            values = read_accessor(gltf, bin_data, out_idx)
            if not values:
                continue
            
            # Find which standard bone name this channel belongs to
            std_name = None
            for name, info in hb.items():
                if info['node'] == ni:
                    std_name = name
                    break
            if std_name is None:
                continue
            
            if path == 'rotation':
                rot_kfs[std_name] = list(values)
            elif path == 'translation' and std_name == 'hips':
                pos_kfs = list(values)
    
    return rot_kfs, pos_kfs

def quat_dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3]

def quat_angle_deg(a, b):
    dot = min(1.0, max(-1.0, quat_dot(a, b)))
    return 2 * math.acos(abs(dot)) * 180.0 / math.pi

def vec_dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def test_transition(input_a, input_t, input_b, rot_thresh=15.0, pos_thresh=0.05):
    """Test the concatenation smoothness of clip A -> transition -> clip B."""
    
    print(f"Reading A: {input_a}")
    gltf_a, bin_a = parse_glb(input_a)
    print(f"Reading T: {input_t}")
    gltf_t, bin_t = parse_glb(input_t)
    print(f"Reading B: {input_b}")
    gltf_b, bin_b = parse_glb(input_b)
    
    hb_a = get_human_bones(gltf_a)
    hb_t = get_human_bones(gltf_t)
    hb_b = get_human_bones(gltf_b)
    
    print(f"  humanBones: A={len(hb_a)}, T={len(hb_t)}, B={len(hb_b)}")
    
    rot_a, pos_a = extract_all_keyframes(gltf_a, bin_a, hb_a)
    rot_t, pos_t = extract_all_keyframes(gltf_t, bin_t, hb_t)
    rot_b, pos_b = extract_all_keyframes(gltf_b, bin_b, hb_b)
    
    print(f"  rotation channels: A={len(rot_a)}, T={len(rot_t)}, B={len(rot_b)}")
    print(f"  Hips translation: A={'yes' if pos_a else 'no'}, T={'yes' if pos_t else 'no'}, B={'yes' if pos_b else 'no'}")
    
    # Union of all standard bone names across all three clips
    all_bones = set(rot_a.keys()) | set(rot_t.keys()) | set(rot_b.keys())
    print(f"  union bones: {len(all_bones)}")
    
    # For each bone, concatenate keyframes and check deltas
    boundary_results = {}  # std_name -> [(boundary_name, angle_deg), ...]
    internal_results = {}  # std_name -> (max_internal_A, max_internal_T, max_internal_B)
    overall_max_rot = 0
    overall_max_pos = 0
    worst_rot_bone = ''
    worst_pos_boundary = ''
    
    for name in sorted(all_bones):
        kfs_a = rot_a.get(name, [])
        kfs_t = rot_t.get(name, [])
        kfs_b = rot_b.get(name, [])
        
        # Concatenate
        concat = list(kfs_a)
        at_boundary_a = len(concat)
        concat.extend(kfs_t)
        at_boundary_b = len(concat)
        concat.extend(kfs_b)
        
        if len(concat) < 2:
            continue
        
        # Check concatenation boundaries
        bones_deltas = []
        if kfs_a and kfs_t:
            deg = quat_angle_deg(kfs_a[-1], kfs_t[0])
            bones_deltas.append(('A->T', deg))
            if deg > overall_max_rot:
                overall_max_rot = deg
                worst_rot_bone = f"{name}@A->T"
        if kfs_t and kfs_b:
            deg = quat_angle_deg(kfs_t[-1], kfs_b[0])
            bones_deltas.append(('T->B', deg))
            if deg > overall_max_rot:
                overall_max_rot = deg
                worst_rot_bone = f"{name}@T->B"
        if kfs_a and not kfs_t and kfs_b:
            # A -> B directly (no transition)
            deg = quat_angle_deg(kfs_a[-1], kfs_b[0])
            bones_deltas.append(('A->B', deg))
            if deg > overall_max_rot:
                overall_max_rot = deg
                worst_rot_bone = f"{name}@A->B"
        
        if bones_deltas:
            boundary_results[name] = bones_deltas
        
        # Check internal per-frame deltas
        max_intra_a = max((quat_angle_deg(concat[i], concat[i+1]) for i in range(len(kfs_a)-1)), default=0)
        max_intra_t = max((quat_angle_deg(concat[at_boundary_a+i], concat[at_boundary_a+i+1]) for i in range(len(kfs_t)-1)), default=0)
        max_intra_b = max((quat_angle_deg(concat[at_boundary_b+i], concat[at_boundary_b+i+1]) for i in range(len(kfs_b)-1)), default=0)
        max_intra = max(max_intra_a, max_intra_t, max_intra_b)
        internal_results[name] = (max_intra_a, max_intra_t, max_intra_b)
    
    # Hips position check
    pos_results = {}
    if pos_a and pos_t and pos_b:
        concat_pos = list(pos_a) + list(pos_t) + list(pos_b)
        if pos_a and pos_t:
            d_a_t = vec_dist(pos_a[-1], pos_t[0])
            pos_results['A->T'] = d_a_t
            if d_a_t > overall_max_pos:
                overall_max_pos = d_a_t
                worst_pos_boundary = 'A->T'
        if pos_t and pos_b:
            d_t_b = vec_dist(pos_t[-1], pos_b[0])
            pos_results['T->B'] = d_t_b
            if d_t_b > overall_max_pos:
                overall_max_pos = d_t_b
                worst_pos_boundary = 'T->B'
    elif pos_a and pos_b:
        d = vec_dist(pos_a[-1], pos_b[0])
        pos_results['A->B'] = d
        if d > overall_max_pos:
            overall_max_pos = d
            worst_pos_boundary = 'A->B'
    
    # Report
    rot_pass = overall_max_rot < rot_thresh
    pos_pass = overall_max_pos < pos_thresh
    
    print(f"\n{'='*60}")
    print(f"  ROTATION: max boundary snap = {overall_max_rot:.2f} deg ({worst_rot_bone})")
    print(f"    Threshold: {rot_thresh} deg => {'PASS' if rot_pass else 'FAIL'}")
    print(f"  POSITION: max boundary snap = {overall_max_pos:.4f} m ({worst_pos_boundary})")
    print(f"    Threshold: {pos_thresh} m => {'PASS' if pos_pass else 'FAIL'}")
    print(f"{'='*60}")
    
    # Print per-bone detail for bones with high deltas
    print(f"\n  Per-bone boundary deltas (sorted by max):")
    rows = []
    for name, deltas in boundary_results.items():
        max_d = max(d[1] for d in deltas)
        rows.append((max_d, name, deltas))
    rows.sort(reverse=True)
    for max_d, name, deltas in rows:
        detail = ', '.join(f'{d[0]}={d[1]:.2f} deg' for d in deltas)
        flag = ' <<<' if max_d >= rot_thresh else ''
        print(f"    {name:30s}: max={max_d:6.2f} deg ({detail}){flag}")
    
    if pos_results:
        print(f"\n  Hips position boundary deltas:")
        for boundary, d in pos_results.items():
            flag = ' <<<' if d >= pos_thresh else ''
            print(f"    {boundary:10s}: {d:.4f} m{flag}")
    
    # Also report worst internal deltas
    print(f"\n  Worst internal per-frame deltas:")
    worst_intra = []
    for name, (a, t, b) in internal_results.items():
        w = max(a, t, b)
        worst_intra.append((w, name, a, t, b))
    worst_intra.sort(reverse=True)
    for w, name, a, t, b in worst_intra[:10]:
        mark = ' <<<' if w >= rot_thresh else ''
        print(f"    {name:30s}: A={a:5.1f}  T={t:5.1f}  B={b:5.1f}  max={w:5.1f}{mark}")
    
    print()
    return rot_pass and pos_pass


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Test transition smoothness')
    parser.add_argument('input_a', help='First clip VRMA')
    parser.add_argument('input_t', help='Transition VRMA')
    parser.add_argument('input_b', help='Second clip VRMA')
    parser.add_argument('--rot-threshold', type=float, default=15.0)
    parser.add_argument('--pos-threshold', type=float, default=0.05)
    args = parser.parse_args()
    
    passed = test_transition(args.input_a, args.input_t, args.input_b, args.rot_threshold, args.pos_threshold)
    sys.exit(0 if passed else 1)
