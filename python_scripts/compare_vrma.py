"""Compare raw vs normalized VRMA Hips data."""
import struct, json, sys

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

def read_acc_data(gltf, buf, acc_idx):
    acc = gltf['accessors'][acc_idx]
    bv = gltf['bufferViews'][acc['bufferView']]
    cs = {5120:1, 5121:1, 5122:2, 5123:2, 5125:4, 5126:4}[acc['componentType']]
    cc = {'SCALAR':1, 'VEC2':2, 'VEC3':3, 'VEC4':4}[acc['type']]
    stride = bv.get('byteStride', cs*cc)
    off = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
    cnt = acc['count']
    fmt = '<' + 'f' * cc
    out = []
    for i in range(cnt):
        vals = struct.unpack_from(fmt, buf, off + i*stride)
        out.append(vals if cc > 1 else vals[0])
    return out

raw_path = 'vrma_test/105_13.vrma'
norm_path = 'vrma/105_13.vrma'

for label, path in [('RAW (unnormalized)', raw_path), ('NORMALIZED', norm_path)]:
    g, b = read_glb(path)
    nodes = g.get('nodes', [])
    hips_idx = next((i for i, n in enumerate(nodes) if n.get('name') == 'Hips'), None)
    print(f'\n=== {label} ===')
    print(f'Nodes: {len(nodes)}, Size: {len(b)} bytes')

    for anim in g.get('animations', []):
        for ch in anim.get('channels', []):
            tgt = ch.get('target', {})
            if tgt.get('node') != hips_idx:
                continue
            samp = anim['samplers'][ch['sampler']]
            out_acc = samp['output']
            data = read_acc_data(g, b, out_acc)
            if tgt.get('path') == 'translation':
                print(f'Hips translation: {len(data)} frames')
                print(f'  Frame 0: ({data[0][0]:.4f}, {data[0][1]:.4f}, {data[0][2]:.4f})')
                print(f'  Frame 5: ({data[5][0]:.4f}, {data[5][1]:.4f}, {data[5][2]:.4f})')
                print(f'  Last:    ({data[-1][0]:.4f}, {data[-1][1]:.4f}, {data[-1][2]:.4f})')
                body_dx = data[-1][0] - data[0][0]
                body_dz = data[-1][2] - data[0][2]
                print(f'  Body delta: dx={body_dx:.4f}, dz={body_dz:.4f}')
            elif tgt.get('path') == 'rotation':
                print(f'Hips rotation: {len(data)} frames')
                print(f'  Frame 0: ({data[0][0]:.4f}, {data[0][1]:.4f}, {data[0][2]:.4f}, {data[0][3]:.4f})')
                print(f'  Frame 5: ({data[5][0]:.4f}, {data[5][1]:.4f}, {data[5][2]:.4f}, {data[5][3]:.4f})')

# Also compare leg bone rotations
print('\n\n=== FIRST NON-HIPS BONE (leftUpperLeg) ===')
for label, path in [('RAW', raw_path), ('NORM', norm_path)]:
    g, b = read_glb(path)
    for anim in g.get('animations', []):
        for ch in anim.get('channels', []):
            tgt = ch.get('target', {})
            tgt_path = tgt.get('path', '')
            if tgt_path != 'rotation':
                continue
            nidx = tgt['node']
            node_name = g['nodes'][nidx].get('name', f'node_{nidx}')
            if node_name not in ('LeftUpLeg', 'LeftLeg', 'RightUpLeg', 'RightLeg'):
                continue
            samp = anim['samplers'][ch['sampler']]
            data = read_acc_data(g, b, samp['output'])
            print(f'  {label} {node_name}: {len(data)} frames')
            print(f'    Frame 0: ({data[0][0]:.4f}, {data[0][1]:.4f}, {data[0][2]:.4f}, {data[0][3]:.4f})')
            if len(data) > 5:
                print(f'    Frame 5: ({data[5][0]:.4f}, {data[5][1]:.4f}, {data[5][2]:.4f}, {data[5][3]:.4f})')
