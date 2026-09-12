"""
generate_transition_vrma.py

Generate a transition VRMA between two CMU clips using standard VRM bone names
(from VRMC_vrm_animation.humanoid.humanBones). Handles the union of bones from both
clips — bones missing from one side slerp to/from identity rotation.

Usage:
  python generate_transition_vrma.py A.vrma B.vrma --output out.vrma
  python generate_transition_vrma.py A.vrma B.vrma -o out.vrma --threshold 15 --fps 60
"""

import struct, json, math, os, sys

GLB_MAGIC = b'glTF'
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN  = 0x004E4942

COMPONENT_BYTE_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
COMPONENT_COUNT = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}
EXT_NAME = 'VRMC_vrm_animation'

def parse_glb(filepath):
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        if magic != GLB_MAGIC:
            raise ValueError(f"Not a GLB file: {filepath}")
        version, total_length = struct.unpack('<II', f.read(8))
        chunks = {}
        while f.tell() < total_length:
            hdr = f.read(8)
            if len(hdr) < 8: break
            cl, ct = struct.unpack('<II', hdr)
            cd = f.read(cl)
            if len(cd) < cl: break
            if ct == CHUNK_JSON:
                chunks['json'] = json.loads(cd.decode('utf-8'))
            elif ct == CHUNK_BIN:
                chunks['bin'] = bytearray(cd)
        if 'json' not in chunks:
            raise ValueError("No JSON chunk found")
        if 'bin' not in chunks:
            chunks['bin'] = bytearray()
        return chunks['json'], chunks['bin']

def write_glb(filepath, json_data, bin_data):
    json_bytes = json.dumps(json_data, separators=(',', ':')).encode('utf-8')
    json_pad = (4 - len(json_bytes) % 4) % 4
    json_bytes += b' ' * json_pad
    bin_pad = (4 - len(bin_data) % 4) % 4
    bin_data = bytes(bin_data) + b'\x00' * bin_pad
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    with open(filepath, 'wb') as f:
        f.write(GLB_MAGIC)
        f.write(struct.pack('<II', 2, total))
        f.write(struct.pack('<II', len(json_bytes), CHUNK_JSON))
        f.write(json_bytes)
        f.write(struct.pack('<II', len(bin_data), CHUNK_BIN))
        f.write(bin_data)

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

def quat_dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3]

def quat_angle_deg(a, b):
    dot = min(1.0, max(-1.0, quat_dot(a, b)))
    return 2 * math.acos(abs(dot)) * 180.0 / math.pi

def quat_slerp(a, b, t):
    cos_omega = quat_dot(a, b)
    b_neg = False
    if cos_omega < 0:
        cos_omega = -cos_omega
        b_neg = True
    cos_omega = min(1.0, max(-1.0, cos_omega))
    if cos_omega > 0.9999:
        s0, s1 = 1.0 - t, t
    else:
        omega = math.acos(cos_omega)
        sin_omega = math.sin(omega)
        s0 = math.sin((1.0 - t) * omega) / sin_omega
        s1 = math.sin(t * omega) / sin_omega
    if b_neg: s1 = -s1
    return (a[0]*s0 + b[0]*s1, a[1]*s0 + b[1]*s1, a[2]*s0 + b[2]*s1, a[3]*s0 + b[3]*s1)

def vec3_lerp(a, b, t):
    return (a[0] + (b[0]-a[0])*t, a[1] + (b[1]-a[1])*t, a[2] + (b[2]-a[2])*t)

def normalize_quat(q):
    length = math.sqrt(q[0]**2 + q[1]**2 + q[2]**2 + q[3]**2)
    if length < 1e-10: return (0.0, 0.0, 0.0, 1.0)
    return (q[0]/length, q[1]/length, q[2]/length, q[3]/length)

def IDENTITY_Q():
    return (0.0, 0.0, 0.0, 1.0)

def get_human_bones(gltf):
    """Return dict: standard_bone_name -> node_index from VRMC_vrm_animation extension."""
    ext = gltf.get('extensions', {}).get(EXT_NAME, {})
    return ext.get('humanoid', {}).get('humanBones', {})

def extract_frame(gltf, bin_data, hb, frame_idx=None, use_last=None):
    """Extract per-bone rotation (by standard name) and Hips position at a frame.
    
    Returns: {std_name: (qx,qy,qz,qw), ...}, hips_pos (x,y,z) or None.
    """
    result = {}
    hips_pos = None
    nodes = gltf.get('nodes', [])
    
    # Build reverse map: node_index -> list of (std_name, path) for channels
    node_channels = {}  # node_idx -> [(std_name, anim_channel), ...]
    for anim in gltf.get('animations', []):
        for ch in anim.get('channels', []):
            ni = ch['target']['node']
            path = ch['target']['path']
            sidx = ch['sampler']
            node_channels.setdefault(ni, []).append((path, sidx, anim))
    
    # For each standard bone name, find the node and its animation
    for std_name, bone_info in hb.items():
        ni = bone_info['node']
        if ni not in node_channels:
            continue
        for path, sidx, anim in node_channels[ni]:
            if path not in ('rotation', 'translation'):
                continue
            if std_name == 'hips' and path == 'translation':
                pass  # handled separately
            elif path != 'rotation':
                continue
            samp = anim['samplers'][sidx]
            values = read_accessor(gltf, bin_data, samp['output'])
            if not values:
                continue
            if use_last:
                idx = len(values) - 1
            elif frame_idx is not None:
                idx = min(frame_idx, len(values) - 1)
            else:
                idx = 0
            val = values[idx]
            
            if path == 'rotation':
                result[std_name] = val
            elif path == 'translation' and std_name == 'hips':
                hips_pos = val
    
    # Also handle Hips translation explicitly
    for anim in gltf.get('animations', []):
        for ch in anim.get('channels', []):
            ni = ch['target']['node']
            path = ch['target']['path']
            if hb.get('hips', {}).get('node') == ni and path == 'translation':
                samp = anim['samplers'][ch['sampler']]
                values = read_accessor(gltf, bin_data, samp['output'])
                if values:
                    if use_last:
                        idx = len(values) - 1
                    elif frame_idx is not None:
                        idx = min(frame_idx, len(values) - 1)
                    else:
                        idx = 0
                    hips_pos = values[idx]
                break
    
    return result, hips_pos

def generate_transition(input_a, input_b, output_path, threshold_deg=15.0, fps=60):
    basename_a = os.path.splitext(os.path.basename(input_a))[0]
    basename_b = os.path.splitext(os.path.basename(input_b))[0]

    print(f"Reading A: {input_a}")
    gltf_a, bin_a = parse_glb(input_a)
    print(f"Reading B: {input_b}")
    gltf_b, bin_b = parse_glb(input_b)

    hb_a = get_human_bones(gltf_a)
    hb_b = get_human_bones(gltf_b)
    print(f"  A humanBones: {len(hb_a)}, B humanBones: {len(hb_b)}")

    # Union of all standard bone names
    all_std = sorted(set(hb_a.keys()) | set(hb_b.keys()))
    print(f"  Union: {len(all_std)} standard bones")

    # Extract last frame from A, first frame from B
    rots_a, hips_a = extract_frame(gltf_a, bin_a, hb_a, use_last=True)
    rots_b, hips_b = extract_frame(gltf_b, bin_b, hb_b, use_last=False)
    print(f"  A last frame: {len(rots_a)} bones with rotation, Hips pos={hips_a}")
    print(f"  B first frame: {len(rots_b)} bones with rotation, Hips pos={hips_b}")

    # Determine per-bone transition parameters
    trans_info = {}  # std_name -> (q_from, q_to, angle, in_a, in_b)
    max_angle = 0
    worst_bone = ''
    for name in all_std:
        in_a = name in rots_a
        in_b = name in rots_b
        if in_a and in_b:
            qA = rots_a[name]
            qB = rots_b[name]
            if quat_dot(qA, qB) < 0:
                qB = tuple(-v for v in qB)
            angle = quat_angle_deg(qA, qB)
        elif in_a:
            qA = rots_a[name]
            qB = IDENTITY_Q()
            angle = quat_angle_deg(qA, qB)
        elif in_b:
            qA = IDENTITY_Q()
            qB = rots_b[name]
            angle = quat_angle_deg(qA, qB)
        else:
            # Both missing — no transition needed
            trans_info[name] = (IDENTITY_Q(), IDENTITY_Q(), 0, False, False)
            continue
        trans_info[name] = (qA, qB, angle, in_a, in_b)
        if angle > max_angle:
            max_angle = angle
            worst_bone = name

    # Nothing to do
    active = {n for n, info in trans_info.items() if info[3] or info[4]}
    if not active:
        print("ERROR: No bones to transition (both clips have zero rotation channels)")
        return False

    N = max(1, max(math.ceil(info[2] / threshold_deg) for n, info in trans_info.items() if n in active))
    hz = fps
    print(f"  Max angle: {max_angle:.1f} deg ({worst_bone})")
    print(f"  Transition frames: {N} ({N/hz:.3f}s at {hz}fps)")

    # Build node hierarchy for output
    # Use A's nodes as base, add any bones from B that are missing
    nodes_a = gltf_a.get('nodes', [])
    # Build name -> node mapping for A and B
    name_to_node_a = {}
    for i, n in enumerate(nodes_a):
        name_to_node_a[n.get('name', f'Node_{i}')] = (i, n)
    
    # We need the canonical VRM skeleton structure.
    # Find the most complete skeleton from either clip.
    # 52-node VRM skeleton is preferred; 38-node CGSpeed is fallback.
    use_b_nodes = len(nodes_a) < 30  # CGSpeed has ~38 nodes
    src_nodes = gltf_b.get('nodes', []) if use_b_nodes else nodes_a
    src_hb = hb_b if use_b_nodes else hb_a

    # Verify the chosen source has the 'Hips' root
    has_hips = 'hips' in src_hb and 0 <= src_hb['hips']['node'] < len(src_nodes)
    if not has_hips:
        # Fallback: whichever has more nodes
        src_nodes = nodes_a if len(nodes_a) >= len(gltf_b.get('nodes',[])) else gltf_b.get('nodes', [])
        src_hb = hb_a if src_nodes == nodes_a else hb_b

    # Build output nodes from source, then add missing bones
    # Map old node indices to new
    old_to_new = {}
    new_nodes = []
    name_to_new_idx = {}

    def add_node(old_idx, old_node):
        if old_idx in old_to_new:
            return old_to_new[old_idx]
        new_idx = len(new_nodes)
        old_to_new[old_idx] = new_idx
        name = old_node.get('name', f'Node_{old_idx}')
        # Create node without children first
        node_copy = dict(old_node)
        node_copy.pop('children', None)
        new_nodes.append(node_copy)
        name_to_new_idx[name] = new_idx
        return new_idx

    # First pass: add all nodes from source, preserving order
    for i, n in enumerate(src_nodes):
        add_node(i, n)

    # Now rebuild children lists
    for old_i, n in enumerate(src_nodes):
        new_i = old_to_new.get(old_i)
        if new_i is None:
            continue
        children = n.get('children', [])
        remapped = [old_to_new[c] for c in children if c in old_to_new]
        if remapped:
            new_nodes[new_i]['children'] = remapped

    # Find root (node with no parent)
    all_children = set()
    for n in new_nodes:
        for c in n.get('children', []):
            all_children.add(c)
    root_idx = [i for i in range(len(new_nodes)) if i not in all_children]
    root_idx = root_idx[0] if root_idx else 0

    # Build standard name -> new node index mapping from source humanBones
    std_to_new = {}
    for std_name, bone_info in src_hb.items():
        old_ni = bone_info['node']
        if old_ni in old_to_new:
            std_to_new[std_name] = old_to_new[old_ni]

    # Add missing bones (in union but not in source skeleton)
    # These need a parent. We'll find parent based on VRM standard hierarchy.
    VRM_PARENTS = {
        'leftUpperLeg': 'hips', 'rightUpperLeg': 'hips',
        'leftLowerLeg': 'leftUpperLeg', 'rightLowerLeg': 'rightUpperLeg',
        'leftFoot': 'leftLowerLeg', 'rightFoot': 'rightLowerLeg',
        'leftToes': 'leftFoot', 'rightToes': 'rightFoot',
        'spine': 'hips',
        'chest': 'spine', 'upperChest': 'chest',
        'neck': 'chest', 'head': 'neck',
        'leftShoulder': 'chest', 'rightShoulder': 'chest',
        'leftUpperArm': 'leftShoulder', 'rightUpperArm': 'rightShoulder',
        'leftLowerArm': 'leftUpperArm', 'rightLowerArm': 'rightUpperArm',
        'leftHand': 'leftLowerArm', 'rightHand': 'rightLowerArm',
        'leftThumbMetacarpal': 'leftHand', 'rightThumbMetacarpal': 'rightHand',
        'leftThumbProximal': 'leftThumbMetacarpal', 'rightThumbProximal': 'rightThumbMetacarpal',
        'leftThumbDistal': 'leftThumbProximal', 'rightThumbDistal': 'rightThumbProximal',
        'leftIndexProximal': 'leftHand', 'rightIndexProximal': 'rightHand',
        'leftIndexIntermediate': 'leftIndexProximal', 'rightIndexIntermediate': 'rightIndexProximal',
        'leftIndexDistal': 'leftIndexIntermediate', 'rightIndexDistal': 'rightIndexIntermediate',
        'leftMiddleProximal': 'leftHand', 'rightMiddleProximal': 'rightHand',
        'leftMiddleIntermediate': 'leftMiddleProximal', 'rightMiddleIntermediate': 'rightMiddleProximal',
        'leftMiddleDistal': 'leftMiddleIntermediate', 'rightMiddleDistal': 'rightMiddleIntermediate',
        'leftRingProximal': 'leftHand', 'rightRingProximal': 'rightHand',
        'leftRingIntermediate': 'leftRingProximal', 'rightRingIntermediate': 'rightRingProximal',
        'leftRingDistal': 'leftRingIntermediate', 'rightRingDistal': 'rightRingIntermediate',
        'leftLittleProximal': 'leftHand', 'rightLittleProximal': 'rightHand',
        'leftLittleIntermediate': 'leftLittleProximal', 'rightLittleIntermediate': 'rightLittleProximal',
        'leftLittleDistal': 'leftLittleIntermediate', 'rightLittleDistal': 'rightLittleIntermediate',
    }
    VRM_NODE_NAMES = {
        'hips': 'Hips', 'spine': 'Spine', 'chest': 'Chest', 'upperChest': 'UpperChest',
        'neck': 'Neck', 'head': 'Head',
        'leftUpperLeg': 'LeftUpperLeg', 'leftLowerLeg': 'LeftLowerLeg',
        'leftFoot': 'LeftFoot', 'leftToes': 'LeftToes',
        'rightUpperLeg': 'RightUpperLeg', 'rightLowerLeg': 'RightLowerLeg',
        'rightFoot': 'RightFoot', 'rightToes': 'RightToes',
        'leftShoulder': 'LeftShoulder', 'rightShoulder': 'RightShoulder',
        'leftUpperArm': 'LeftUpperArm', 'leftLowerArm': 'LeftLowerArm',
        'leftHand': 'LeftHand',
        'rightUpperArm': 'RightUpperArm', 'rightLowerArm': 'RightLowerArm',
        'rightHand': 'RightHand',
        'leftThumbMetacarpal': 'LeftThumbMetacarpal', 'leftThumbProximal': 'LeftThumbProximal',
        'leftThumbDistal': 'LeftThumbDistal',
        'rightThumbMetacarpal': 'RightThumbMetacarpal', 'rightThumbProximal': 'RightThumbProximal',
        'rightThumbDistal': 'RightThumbDistal',
        'leftIndexProximal': 'LeftIndexProximal', 'leftIndexIntermediate': 'LeftIndexIntermediate',
        'leftIndexDistal': 'LeftIndexDistal',
        'rightIndexProximal': 'RightIndexProximal', 'rightIndexIntermediate': 'RightIndexIntermediate',
        'rightIndexDistal': 'RightIndexDistal',
        'leftMiddleProximal': 'LeftMiddleProximal', 'leftMiddleIntermediate': 'LeftMiddleIntermediate',
        'leftMiddleDistal': 'LeftMiddleDistal',
        'rightMiddleProximal': 'RightMiddleProximal', 'rightMiddleIntermediate': 'RightMiddleIntermediate',
        'rightMiddleDistal': 'RightMiddleDistal',
        'leftRingProximal': 'LeftRingProximal', 'leftRingIntermediate': 'LeftRingIntermediate',
        'leftRingDistal': 'LeftRingDistal',
        'rightRingProximal': 'RightRingProximal', 'rightRingIntermediate': 'RightRingIntermediate',
        'rightRingDistal': 'RightRingDistal',
        'leftLittleProximal': 'LeftLittleProximal', 'leftLittleIntermediate': 'LeftLittleIntermediate',
        'leftLittleDistal': 'LeftLittleDistal',
        'rightLittleProximal': 'RightLittleProximal', 'rightLittleIntermediate': 'RightLittleIntermediate',
        'rightLittleDistal': 'RightLittleDistal',
    }

    # Add missing bones to the skeleton
    for std_name in all_std:
        if std_name in std_to_new:
            continue
        # Need to add this bone
        parent_std = VRM_PARENTS.get(std_name, 'hips')
        node_name = VRM_NODE_NAMES.get(std_name, std_name)
        # Create the node
        new_idx = len(new_nodes)
        new_nodes.append({'name': node_name})
        std_to_new[std_name] = new_idx
        name_to_new_idx[node_name] = new_idx
        # Add as child of parent
        if parent_std in std_to_new:
            parent_new = std_to_new[parent_std]
            parent_node = new_nodes[parent_new]
            if 'children' not in parent_node:
                parent_node['children'] = []
            if new_idx not in parent_node['children']:
                parent_node['children'].append(new_idx)
        else:
            # Orphan — make it a child of root
            parent_node = new_nodes[root_idx]
            if 'children' not in parent_node:
                parent_node['children'] = []
            if new_idx not in parent_node['children']:
                parent_node['children'].append(new_idx)

    # Generate keyframe data
    num_frames = N + 1
    time_values = [i / hz for i in range(num_frames)]

    # Generate rotation keyframes for each active bone
    bone_output = {}
    for name in active:
        qA, qB, angle, in_a, in_b = trans_info[name]
        keys = []
        for i in range(num_frames):
            t = i / max(N, 1)
            q = quat_slerp(qA, qB, t)
            q = normalize_quat(q)
            keys.append(q)
        bone_output[name] = keys

    # Hips translation
    hips_pos_keys = None
    if hips_a is not None and hips_b is not None:
        print(f"  Hips: ({hips_a[0]:.4f},{hips_a[1]:.4f},{hips_a[2]:.4f}) -> ({hips_b[0]:.4f},{hips_b[1]:.4f},{hips_b[2]:.4f})")
        hips_pos_keys = [vec3_lerp(hips_a, hips_b, i / max(N, 1)) for i in range(num_frames)]
    elif hips_a is not None:
        hips_pos_keys = [hips_a] * num_frames
    elif hips_b is not None:
        hips_pos_keys = [hips_b] * num_frames

    # Build GLB binary buffer
    chunks_float = []
    accessors_info = []
    buffer_views_info = []
    byte_offset = 0

    # 1. Time input accessor
    time_binary = struct.pack('<' + 'f' * len(time_values), *time_values)
    chunks_float.append(time_binary)
    time_bv = len(buffer_views_info)
    buffer_views_info.append({'buffer': 0, 'byteOffset': byte_offset, 'byteLength': len(time_binary)})
    time_acc = len(accessors_info)
    accessors_info.append({
        'bufferView': time_bv, 'byteOffset': 0,
        'componentType': 5126, 'count': num_frames, 'type': 'SCALAR',
        'min': [time_values[0]], 'max': [time_values[-1]],
    })
    byte_offset += len(time_binary)

    channels = []
    samplers = []

    # 2. Rotation output accessors
    for name in active:
        new_ni = std_to_new.get(name)
        if new_ni is None:
            continue
        keys = bone_output[name]
        flat = []
        for q in keys:
            flat.extend(q)
        binary = struct.pack('<' + 'f' * len(flat), *flat)
        chunks_float.append(binary)
        bv_idx = len(buffer_views_info)
        buffer_views_info.append({'buffer': 0, 'byteOffset': byte_offset, 'byteLength': len(binary)})
        acc_idx = len(accessors_info)
        accessors_info.append({
            'bufferView': bv_idx, 'byteOffset': 0,
            'componentType': 5126, 'count': num_frames, 'type': 'VEC4',
        })
        byte_offset += len(binary)

        samp_idx = len(samplers)
        samplers.append({'input': time_acc, 'output': acc_idx, 'interpolation': 'LINEAR'})
        channels.append({'sampler': samp_idx, 'target': {'node': new_ni, 'path': 'rotation'}})

    # 3. Hips translation channel
    if hips_pos_keys is not None and 'hips' in std_to_new:
        flat = []
        for p in hips_pos_keys:
            flat.extend(p)
        binary = struct.pack('<' + 'f' * len(flat), *flat)
        chunks_float.append(binary)
        bv_idx = len(buffer_views_info)
        buffer_views_info.append({'buffer': 0, 'byteOffset': byte_offset, 'byteLength': len(binary)})
        acc_idx = len(accessors_info)
        accessors_info.append({
            'bufferView': bv_idx, 'byteOffset': 0,
            'componentType': 5126, 'count': num_frames, 'type': 'VEC3',
        })
        byte_offset += len(binary)

        samp_idx = len(samplers)
        samplers.append({'input': time_acc, 'output': acc_idx, 'interpolation': 'LINEAR'})
        channels.append({'sampler': samp_idx, 'target': {'node': std_to_new['hips'], 'path': 'translation'}})

    bin_data = b''.join(chunks_float)

    # Build humanBones for output (only bones that are in the skeleton)
    output_human_bones = {}
    for std_name in all_std:
        if std_name in std_to_new:
            output_human_bones[std_name] = {'node': std_to_new[std_name]}

    output_gltf = {
        'asset': {'version': '2.0', 'generator': 'generate_transition_vrma.py'},
        'scene': 0,
        'scenes': [{'nodes': [root_idx]}],
        'nodes': new_nodes,
        'animations': [{
            'name': f'{basename_a}_to_{basename_b}',
            'channels': channels,
            'samplers': samplers,
        }],
        'accessors': accessors_info,
        'bufferViews': buffer_views_info,
        'buffers': [{'byteLength': len(bin_data)}],
        'extensions': {
            EXT_NAME: {
                'specVersion': '1.0',
                'humanoid': {'humanBones': output_human_bones},
            }
        }
    }

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    write_glb(output_path, output_gltf, bin_data)
    print(f"  Written: {output_path} ({len(bin_data)} bytes, {len(channels)} channels, {len(new_nodes)} nodes, {len(output_human_bones)} humanBones)")

    # Print per-bone detail
    print(f"\n  Per-bone transition (threshold {threshold_deg} deg):")
    for name in sorted(active):
        _, _, angle, in_a, in_b = trans_info[name]
        n = max(1, math.ceil(angle / threshold_deg))
        src = f"{'A' if in_a else ''}{'+' if in_a and in_b else ''}{'B' if in_b else ''}"
        marker = ' <<<' if angle > threshold_deg else ''
        print(f"    {name:30s}: {angle:6.1f} deg -> {n:3d} frames [{src}]{marker}")
    missed = set(all_std) - active
    if missed:
        print(f"  (no transition needed for: {', '.join(sorted(missed)[:10])}...)")

    return True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate transition VRMA between two CMU clips')
    parser.add_argument('input_a', help='Source VRMA (first clip)')
    parser.add_argument('input_b', help='Target VRMA (second clip)')
    parser.add_argument('--output', '-o', required=True, help='Output transition VRMA path')
    parser.add_argument('--threshold', type=float, default=15.0)
    parser.add_argument('--fps', type=int, default=60)
    args = parser.parse_args()

    success = generate_transition(args.input_a, args.input_b, args.output, args.threshold, args.fps)
    sys.exit(0 if success else 1)
