"""
Normalize VRMA so frame 0 starts at world origin facing forward.
- Hips position: subtract frame 0 position from ALL position keyframes
- Hips rotation: apply inverse of frame 0 quaternion to ALL rotation keyframes
- Child bones are NOT modified (they're parent-relative in glTF)
- Position smoothing: detects & interpolates single-frame Y-axis discontinuities > 0.05m

Usage: python normalize_vrma_origin.py <input.vrma> [output.vrma]
       python normalize_vrma_origin.py <input.vrma>  (in-place overwrite)
       python normalize_vrma_origin.py input_dir/*.vrma  (batch in-place)
"""
import struct, json, sys, os, math, copy, glob

def read_glb(path):
    with open(path, 'rb') as f:
        magic = struct.unpack('<I', f.read(4))[0]
        assert magic == 0x46546C67
        struct.unpack('<I', f.read(4))[0]
        length = struct.unpack('<I', f.read(4))[0]
        json_data = bin_data = None
        while f.tell() < length:
            cl = struct.unpack('<I', f.read(4))[0]
            ct = struct.unpack('<I', f.read(4))[0]
            cd = f.read(cl)
            if ct == 0x4E4F534A:
                json_data = json.loads(cd.decode('utf-8'))
            elif ct == 0x004E4942:
                bin_data = bytearray(cd)
        return json_data, bin_data

def write_glb(json_data, bin_data, path):
    json_str = json.dumps(json_data, separators=(',', ':'))
    json_bytes = json_str.encode('utf-8')
    while len(json_bytes) % 4:
        json_bytes += b' '
    while len(bin_data) % 4:
        bin_data += b'\x00'
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    with open(path, 'wb') as f:
        f.write(struct.pack('<3I', 0x46546C67, 2, total))
        f.write(struct.pack('<I', len(json_bytes)))
        f.write(struct.pack('<I', 0x4E4F534A))
        f.write(json_bytes)
        f.write(struct.pack('<I', len(bin_data)))
        f.write(struct.pack('<I', 0x004E4942))
        f.write(bin_data)

def apply_position_smoothing(raw_data, comp_cnt, cnt, threshold=0.05):
    """
    Detect and interpolate single-frame position discontinuities (> threshold in any axis).
    Returns smoothed bytearray if any frames fixed, None if all clean.
    threshold: max allowed per-frame delta in meters (default 0.05).
    """
    import struct
    stride = comp_cnt * 4
    # Read all positions
    frames = []
    for i in range(cnt):
        vals = struct.unpack_from('<%df' % comp_cnt, raw_data, i * stride)
        frames.append(list(vals))

    fixed = 0
    for i in range(1, cnt - 1):
        # Check delta from previous frame in any axis
        d = [abs(frames[i][a] - frames[i-1][a]) for a in range(comp_cnt)]
        if any(dd > threshold for dd in d):
            # Check if this is a single-frame spike (current→next is also large, but prev→next is smooth)
            d_next = [abs(frames[i+1][a] - frames[i][a]) for a in range(comp_cnt)]
            d_skip = [abs(frames[i+1][a] - frames[i-1][a]) for a in range(comp_cnt)]
            if any(dd > threshold for dd in d_next) and all(dd < threshold * 2 for dd in d_skip):
                # Interpolate frame i between i-1 and i+1
                for a in range(comp_cnt):
                    frames[i][a] = (frames[i-1][a] + frames[i+1][a]) / 2.0
                fixed += 1

    if fixed == 0:
        return None

    out = bytearray()
    for i in range(cnt):
        out.extend(struct.pack('<%df' % comp_cnt, *frames[i]))
    return out

def normalize_vrma(data, buf):
    nodes = data.get('nodes', [])
    anims = data.get('animations', [])
    accessors = data['accessors']
    buffer_views = data['bufferViews']

    # Find Hips node index
    hips_idx = next((i for i, n in enumerate(nodes) if n.get('name') == 'Hips'), None)
    if hips_idx is None:
        print('  WARNING: No Hips node found, cannot normalize')
        return data, buf

    print('  Hips node index: %d' % hips_idx)

    # Find animation channels for Hips rotation and translation
    rot_ch = None  # {sampler_idx, output_acc_idx, num_components}
    pos_ch = None

    for anim in anims:
        for ch in anim.get('channels', []):
            tgt = ch.get('target', {})
            if tgt.get('node') != hips_idx:
                continue
            sampler = anim['samplers'][ch['sampler']]
            out_acc = sampler['output']

            if tgt.get('path') == 'rotation':
                acc = accessors[out_acc]
                comp = 1 if acc['type'] == 'SCALAR' else {'VEC2':2,'VEC3':3,'VEC4':4}.get(acc['type'], 4)
                rot_ch = {'sampler': ch['sampler'], 'acc': out_acc, 'comp': comp}
            elif tgt.get('path') == 'translation':
                acc = accessors[out_acc]
                comp = 1 if acc['type'] == 'SCALAR' else {'VEC2':2,'VEC3':3,'VEC4':4}.get(acc['type'], 3)
                pos_ch = {'sampler': ch['sampler'], 'acc': out_acc, 'comp': comp}

    if rot_ch is None:
        print('  WARNING: No Hips rotation channel found')
        return data, buf

    old_buf = bytearray(buf)
    new_buf = bytearray()
    new_offset = 0

    # Track which buffer views we've processed
    processed_bvs = {}

    comp_size = 4  # all FLOAT = 4 bytes

    # Phase 1: Read frame 0 values to compute correction
    def read_acc_data(acc_idx):
        acc = accessors[acc_idx]
        bv = buffer_views[acc['bufferView']]
        off = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
        comp_cnt = 1 if acc['type'] == 'SCALAR' else {'VEC2':2,'VEC3':3,'VEC4':4}.get(acc['type'], 4)
        cnt = acc['count']
        stride = comp_cnt * comp_size
        values = []
        for i in range(cnt):
            vals = struct.unpack_from('<%df' % comp_cnt, old_buf, off + i * stride)
            values.append(vals)
        return values

    # Get frame 0 Hips rotation
    rot_vals = read_acc_data(rot_ch['acc'])
    q0 = rot_vals[0]  # (qx, qy, qz, qw)
    print('  Frame 0 Hips rotation: (%.4f, %.4f, %.4f, %.4f)' % q0)

    # Compute inverse quaternion
    q0_norm = math.sqrt(q0[0]**2 + q0[1]**2 + q0[2]**2 + q0[3]**2)
    if q0_norm < 0.0001:
        q0_inv = (0.0, 0.0, 0.0, 1.0)
    else:
        # Inverse = conjugate for unit quaternion
        q0_inv = (-q0[0]/q0_norm, -q0[1]/q0_norm, -q0[2]/q0_norm, q0[3]/q0_norm)

    print('  Correction quaternion: (%.4f, %.4f, %.4f, %.4f)' % q0_inv)

    # Get frame 0 Hips position
    h0 = None
    if pos_ch:
        pos_vals = read_acc_data(pos_ch['acc'])
        h0 = pos_vals[0]
        print('  Frame 0 Hips position: (%.4f, %.4f, %.4f)' % h0)
    else:
        print('  No Hips translation channel — skipping position correction')

    # Phase 2: Rewrite buffer with corrected data
    # For each buffer view, check if its referenced by any accessor we need to modify
    # Collect all accessor indices we need to modify
    modify_accs = {}  # acc_idx -> type ('rot' or 'pos')
    for anim in anims:
        for ch in anim.get('channels', []):
            tgt = ch.get('target', {})
            sampler = anim['samplers'][ch['sampler']]
            out_acc = sampler['output']
            acc = accessors[out_acc]

            if tgt.get('node') == hips_idx:
                if tgt.get('path') == 'rotation':
                    modify_accs[out_acc] = 'rot'
                elif tgt.get('path') == 'translation':
                    modify_accs[out_acc] = 'pos'

    # Now rebuild all buffer views sequentially
    for bv_idx, bv in enumerate(buffer_views):
        bv_off = bv.get('byteOffset', 0)
        bv_len = bv['byteLength']
        old_data = old_buf[bv_off:bv_off + bv_len]
        ref_accs = [i for i, acc in enumerate(accessors) if acc.get('bufferView') == bv_idx]

        needs_mod = False
        mod_type = None
        for acc_idx in ref_accs:
            if acc_idx in modify_accs:
                needs_mod = True
                mod_type = modify_accs[acc_idx]
                break

        if needs_mod and ref_accs:
            acc = accessors[ref_accs[0]]
            cnt = acc['count']
            comp_cnt = 1 if acc['type'] == 'SCALAR' else {'VEC2':2,'VEC3':3,'VEC4':4}.get(acc['type'], 4)
            stride = comp_cnt * comp_size

            new_data = bytearray()
            for frame in range(cnt):
                vals = struct.unpack_from('<%df' % comp_cnt, old_data, frame * stride)

                if mod_type == 'rot':
                    # Apply q0_inv * q_frame (quaternion multiply)
                    qx, qy, qz, qw = vals
                    # q0_inv * q
                    ix, iy, iz, iw = q0_inv
                    rx = iw * qx + ix * qw + iy * qz - iz * qy
                    ry = iw * qy - ix * qz + iy * qw + iz * qx
                    rz = iw * qz + ix * qy - iy * qx + iz * qw
                    rw = iw * qw - ix * qx - iy * qy - iz * qz
                    new_vals = (rx, ry, rz, rw)
                elif mod_type == 'pos' and h0:
                    # Subtract frame 0 position
                    new_vals = tuple(vals[i] - h0[i] for i in range(comp_cnt))
                else:
                    new_vals = vals

                new_data.extend(struct.pack('<%df' % comp_cnt, *new_vals))

            # --- Position smoothing pass ---
            if mod_type == 'pos' and comp_cnt >= 3 and cnt >= 3:
                smoothed = apply_position_smoothing(new_data, comp_cnt, cnt, threshold=0.05)
                if smoothed is not None:
                    new_data = smoothed
            # ---

            # Update accessor min/max
            if mod_type == 'pos':
                # Recompute min/max for position
                mins = [float('inf')] * comp_cnt
                maxs = [float('-inf')] * comp_cnt
                for frame in range(cnt):
                    vals = struct.unpack_from('<%df' % comp_cnt, new_data, frame * stride)
                    for i in range(comp_cnt):
                        mins[i] = min(mins[i], vals[i])
                        maxs[i] = max(maxs[i], vals[i])
                acc['min'] = mins
                acc['max'] = maxs
            elif mod_type == 'rot':
                acc.pop('min', None)
                acc.pop('max', None)

            bv['byteLength'] = len(new_data)
            bv['byteOffset'] = new_offset
            new_buf.extend(new_data)
            new_offset += len(new_data)
        else:
            bv['byteOffset'] = new_offset
            new_buf.extend(old_data)
            new_offset += len(old_data)

    data['buffers'][0]['byteLength'] = len(new_buf)
    return data, bytes(new_buf)

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print('Usage: python normalize_vrma_origin.py <input.vrma> [output.vrma]')
        print('       python normalize_vrma_origin.py path/*.vrma  (batch in-place)')
        sys.exit(1)

    # Check if glob pattern
    files = []
    for a in args:
        if '*' in a or '?' in a:
            files.extend(glob.glob(a))
        else:
            files.append(a)

    for inp in files:
        if not os.path.exists(inp):
            print('  SKIP (not found): %s' % inp)
            continue
        out = args[1] if len(args) > 1 and '*' not in args[0] and not args[0].startswith('*') else inp
        if out != inp and len(files) > 1:
            out = inp  # batch mode: in-place

        print('Normalizing %s -> %s' % (inp, out))
        try:
            data, buf = read_glb(inp)
            data2, buf2 = normalize_vrma(data, buf)
            write_glb(data2, buf2, out)
            print('  Done: %d bytes' % os.path.getsize(out))
        except Exception as e:
            print('  ERROR: %s' % e)
