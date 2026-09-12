"""
fix_vrma_first_frame.py — Replace first-frame rotations with frame 1 values
for bones whose frame 0->1 delta exceeds a threshold (rest-pose artifact).

Usage:
  python python_scripts/fix_vrma_first_frame.py vrma/104_31.vrma --in-place
"""

import struct, json, math, os, sys

GLB_MAGIC = b'glTF'
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

def parse_glb(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    magic = data[:4]
    if magic != GLB_MAGIC:
        raise ValueError(f"Not a GLB: {filepath}")
    version = struct.unpack('<I', data[4:8])[0]
    total_len = struct.unpack('<I', data[8:12])[0]
    pos = 12
    chunks = {'_raw': data}
    while pos < total_len:
        clen, ctype = struct.unpack('<II', data[pos:pos+8])
        pos += 8
        chunk = data[pos:pos+clen]
        pos += clen
        if ctype == CHUNK_JSON:
            chunks['json'] = json.loads(chunk.decode('utf-8'))
            chunks['json_offset'] = pos - clen - 8
            chunks['json_len'] = clen
        elif ctype == CHUNK_BIN:
            chunks['bin'] = chunk
            chunks['bin_offset'] = pos - clen - 8
            chunks['bin_len'] = clen
    return chunks

def write_glb(filepath, chunks):
    json_bytes = json.dumps(chunks['json'], separators=(',', ':')).encode('utf-8')
    json_pad = (4 - len(json_bytes) % 4) % 4
    json_bytes += b' ' * json_pad
    bin_data = chunks['bin']
    bin_pad = (4 - len(bin_data) % 4) % 4
    bin_data_padded = bin_data + b'\x00' * bin_pad
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_data_padded)
    with open(filepath, 'wb') as f:
        f.write(GLB_MAGIC)
        f.write(struct.pack('<II', 2, total))
        f.write(struct.pack('<II', len(json_bytes), CHUNK_JSON))
        f.write(json_bytes)
        f.write(struct.pack('<II', len(bin_data_padded), CHUNK_BIN))
        f.write(bin_data_padded)

def accessor_byte_offset(gltf, acc_idx):
    acc = gltf['accessors'][acc_idx]
    bv = gltf['bufferViews'][acc['bufferView']]
    return bv['byteOffset'] + acc.get('byteOffset', 0), acc['count']

def quat_angle_deg(a, b):
    dot = abs(a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3])
    return 2 * math.acos(min(1.0, dot)) * 180.0 / math.pi

def fix_first_frame(filepath, threshold=10.0, in_place=False):
    basename = os.path.basename(filepath)
    chunks = parse_glb(filepath)
    gltf = chunks['json']
    bin_data = bytearray(chunks['bin'])
    nodes = gltf.get('nodes', [])
    anims = gltf.get('animations', [])

    if not anims:
        print(f"{basename}: No animations found")
        return False

    total_fixed = 0
    for anim in anims:
        channels = anim.get('channels', [])
        samplers = anim.get('samplers', [])
        for ch in channels:
            target = ch.get('target', {})
            path = target.get('path', '')
            if path != 'rotation':
                continue
            ni = target.get('node')
            si = ch['sampler']
            name = nodes[ni].get('name', f'Node_{ni}') if ni is not None else 'unknown'
            sam = samplers[si]
            off, count = accessor_byte_offset(gltf, sam['output'])
            if count < 2:
                continue

            # Read frame 0 and frame 1 quaternions
            stride = 16  # 4 floats
            f0_bytes = bin_data[off:off+stride]
            f1_bytes = bin_data[off+stride:off+2*stride]
            q0 = struct.unpack('<ffff', f0_bytes)
            q1 = struct.unpack('<ffff', f1_bytes)
            deg = quat_angle_deg(q0, q1)

            if deg >= threshold:
                # Copy frame 1 values over frame 0
                bin_data[off:off+stride] = f1_bytes
                print(f"  {name:25s}: frame 0 <- frame 1 (delta was {deg:.1f}deg)")
                total_fixed += 1

    if total_fixed == 0:
        print(f"{basename}: No first-frame issues > {threshold}deg — clean")
        return False

    chunks['bin'] = bytes(bin_data)
    outpath = filepath if in_place else filepath.replace('.vrma', '_fixed.vrma')
    write_glb(outpath, chunks)
    print(f"{basename}: Fixed {total_fixed} bone(s) -> {os.path.basename(outpath)}")
    return True

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print("Usage: python fix_vrma_first_frame.py <vrma_path> [--in-place] [--threshold=10]")
        sys.exit(1)

    path = args[0]
    in_place = '--in-place' in args
    threshold = 10.0
    for a in args:
        if a.startswith('--threshold='):
            threshold = float(a.split('=')[1])

    if os.path.isdir(path):
        for f in sorted(os.listdir(path)):
            if f.endswith('.vrma'):
                fix_first_frame(os.path.join(path, f), threshold, in_place)
    else:
        fix_first_frame(path, threshold, in_place)
