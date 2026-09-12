"""Scan all valid VRMAs, categorize by drift type (gesture vs walking)."""
import struct, json, os, sys, glob

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
files = sorted(glob.glob(os.path.join(vrma_dir, '*.vrma')))

walking = []
gesture = []
for f in files:
    name = os.path.basename(f).replace('.vrma', '')
    data = read_glb(f)
    nodes = data['nodes']
    hips_idx = next((i for i, n in enumerate(nodes) if n.get('name') == 'Hips'), None)
    buf = data['bin']

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
            stride = 12

            x0 = struct.unpack_from('<f', buf, off)[0]
            z0 = struct.unpack_from('<f', buf, off + 8)[0]
            x1 = struct.unpack_from('<f', buf, off + (cnt-1)*stride)[0]
            z1 = struct.unpack_from('<f', buf, off + (cnt-1)*stride + 8)[0]
            dx = x1 - x0; dz = z1 - z0
            drift_xy = (dx*dx + dz*dz) ** 0.5

            max_dx = max_dz = 0
            px, pz = x0, z0
            limit = min(cnt, 2000)
            for i in range(1, limit):
                x = struct.unpack_from('<f', buf, off + i*stride)[0]
                z = struct.unpack_from('<f', buf, off + i*stride + 8)[0]
                max_dx = max(max_dx, abs(x - px))
                max_dz = max(max_dz, abs(z - pz))
                px, pz = x, z

            if drift_xy > 0.1 or max_dx > 0.005 or max_dz > 0.005:
                walking.append((name, cnt, drift_xy, max_dx, max_dz))
            else:
                gesture.append((name, cnt, drift_xy, max_dx, max_dz))

print(f'Walking: {len(walking)}')
print(f'Gesture: {len(gesture)}')

# Write categorized lists
out_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(out_dir, '..', 'pool_walking.txt'), 'w') as f:
    for name, _, _, _, _ in walking:
        f.write(f'{name}.vrma\n')
with open(os.path.join(out_dir, '..', 'pool_gesture.txt'), 'w') as f:
    for name, _, _, _, _ in gesture:
        f.write(f'{name}.vrma\n')

# Stats
if walking:
    avg_drift = sum(w[2] for w in walking) / len(walking)
    max_drift = max(w[2] for w in walking)
    print(f'  Walking avg_drift: {avg_drift:.3f}m, max_drift: {max_drift:.3f}m')
if gesture:
    avg_drift = sum(g[2] for g in gesture) / len(gesture)
    max_drift = max(g[2] for g in gesture)
    print(f'  Gesture avg_drift: {avg_drift:.3f}m, max_drift: {max_drift:.3f}m')
    # Show worst gesture drifts
    gesture.sort(key=lambda x: -x[2])
    print(f'  Top 5 gesture drifters:')
    for name, cnt, d, dx, dz in gesture[:5]:
        print(f'    {name}: {d:.3f}m drift over {cnt}f, max_frame_dx={dx:.4f}, dz={dz:.4f}')
