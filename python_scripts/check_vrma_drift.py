"""Check Hips position drift within a single VRMA clip."""
import struct, json, os, sys

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
                bin_data = cd
        json_data['bin'] = bin_data
        return json_data
    return None

vrma_dir = sys.argv[1] if len(sys.argv) > 1 else 'D:/VRE/vrma'

# Check a mix: gesture vs walking clips
targets = [
    '02_01.vrma',   # gesture (clean, standing)
    '13_27.vrma',   # gesture (direct traffic, standing)
    '18_08.vrma',   # gesture (conversation)
    '16_19.vrma',   # walking (walk-turn-90)
    '14_24.vrma',   # walking (direct traffic, walking)
    '105_13.vrma',  # walking (SadWalk)
    '111_37.vrma',  # gesture (Wave)
]

for name in targets:
    path = os.path.join(vrma_dir, name)
    if not os.path.exists(path):
        print(f'{name}: NOT FOUND')
        continue
    data = read_glb(path)
    nodes = data['nodes']
    hips_idx = next((i for i, n in enumerate(nodes) if n.get('name') == 'Hips'), None)

    for anim in data['animations']:
        for ch in anim.get('channels', []):
            tgt = ch.get('target', {})
            if tgt.get('node') != hips_idx: continue
            if tgt.get('path') != 'translation': continue

            sampler = anim['samplers'][ch['sampler']]
            acc = data['accessors'][sampler['output']]
            bv = data['bufferViews'][acc['bufferView']]
            off = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
            cnt = acc['count']
            stride = 12  # 3 floats

            buf = data['bin']
            # Read first and last position
            x0, y0, z0 = struct.unpack_from('<3f', buf, off)
            x1, y1, z1 = struct.unpack_from('<3f', buf, off + (cnt-1)*stride)

            dx = x1 - x0
            dz = z1 - z0
            drift_xy = (dx*dx + dz*dz) ** 0.5

            # Check max per-frame delta to identify fast movements vs slow drift
            max_dx = max_dz = 0
            px, pz = x0, z0
            for i in range(1, min(cnt, 500)):
                x = struct.unpack_from('<f', buf, off + i*stride)[0]
                z = struct.unpack_from('<f', buf, off + i*stride + 8)[0]
                max_dx = max(max_dx, abs(x - px))
                max_dz = max(max_dz, abs(z - pz))
                px, pz = x, z

            print(f'{name}: {cnt}f, start=({x0:.3f},{y0:.3f},{z0:.3f}), end=({x1:.3f},{y1:.3f},{z1:.3f}), total_drift={drift_xy:.3f}m, max_frame_dx={max_dx:.4f}, max_frame_dz={max_dz:.4f}')
