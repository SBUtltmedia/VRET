"""
Trim a VRMA (GLB) file to a specific frame range.
Usage: python trim_vrma.py <input.vrma> <output.vrma> <num_frames>
"""
import struct, json, sys, os

COMP_SIZES = {5126: 4, 5123: 2, 5121: 1}
TYPE_SIZES = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}

def read_glb(path):
    with open(path, 'rb') as f:
        magic = struct.unpack('<I', f.read(4))[0]
        assert magic == 0x46546C67
        version = struct.unpack('<I', f.read(4))[0]
        length = struct.unpack('<I', f.read(4))[0]
        json_data = None
        bin_data = None
        while f.tell() < length:
            chunk_len = struct.unpack('<I', f.read(4))[0]
            chunk_type = struct.unpack('<I', f.read(4))[0]
            chunk_data = f.read(chunk_len)
            if chunk_type == 0x4E4F534A:
                json_data = json.loads(chunk_data.decode('utf-8'))
            elif chunk_type == 0x004E4942:
                bin_data = bytearray(chunk_data)
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

def trim_vrma(json_data, bin_data, new_count):
    accessors = json_data['accessors']
    buffer_views = json_data['bufferViews']

    anim_accs = set()
    for anim in json_data.get('animations', []):
        for sampler in anim.get('samplers', []):
            anim_accs.add(sampler['input'])
            anim_accs.add(sampler['output'])

    old_buf = bytearray(bin_data)
    new_buf = bytearray()
    new_offset = 0

    for bv_idx, bv in enumerate(buffer_views):
        bv_off = bv.get('byteOffset', 0)
        bv_len = bv['byteLength']
        old_data = old_buf[bv_off:bv_off + bv_len]
        ref_accs = [i for i, acc in enumerate(accessors) if acc.get('bufferView') == bv_idx]

        trim = any(i in anim_accs for i in ref_accs)

        if trim and ref_accs:
            acc = accessors[ref_accs[0]]
            comp_size = COMP_SIZES.get(acc['componentType'], 4)
            type_size = TYPE_SIZES.get(acc['type'], 1)
            elem_size = comp_size * type_size
            old_c = acc['count']
            nc = min(old_c, new_count)
            nd = old_data[:nc * elem_size]

            is_time = acc['type'] == 'SCALAR' and acc['componentType'] == 5126
            if is_time:
                floats = list(struct.iter_unpack('<f', nd))
                first = floats[0][0]
                if first > 0.001:
                    floats = [(f[0] - first,) for f in floats]
                    nd = struct.pack(f'{len(floats)}f', *[f[0] for f in floats])
                acc['min'] = [0.0]
                acc['max'] = [float(nc - 1) * (1.0 / 30.0)]

            acc['count'] = nc
            if 'min' not in acc or is_time:
                pass
            else:
                acc.pop('min', None)
                acc.pop('max', None)

            bv['byteLength'] = len(nd)
            bv['byteOffset'] = new_offset
            new_buf.extend(nd)
            new_offset += len(nd)
        else:
            bv['byteOffset'] = new_offset
            new_buf.extend(old_data)
            new_offset += len(old_data)

    json_data['buffers'][0]['byteLength'] = len(new_buf)
    return json_data, bytes(new_buf)

if __name__ == '__main__':
    inp = sys.argv[1]
    out = sys.argv[2]
    nf = int(sys.argv[3])
    print(f'Trimming {inp} -> {out} ({nf} frames)')
    j, b = read_glb(inp)
    # Get original frame count
    for acc in j['accessors']:
        orig = acc['count']
        break
    print(f'  Original: {orig} frames')
    j2, b2 = trim_vrma(j, b, nf)
    write_glb(j2, b2, out)
    print(f'  Done: {os.path.getsize(out)} bytes')
