import struct, json, math

def parse_glb(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    gltf, bin_data = None, None
    pos = 12
    while pos < len(data):
        clen, ctype = struct.unpack('<II', data[pos:pos+8])
        pos += 8
        if ctype == 0x4E4F534A:
            gltf = json.loads(data[pos:pos+clen].decode('utf-8'))
        elif ctype == 0x004E4942:
            bin_data = data[pos:pos+clen]
        pos += clen
    return gltf, bin_data

def get_accessor(gltf, acc_idx, bin_data):
    acc = gltf['accessors'][acc_idx]
    bv = gltf['bufferViews'][acc['bufferView']]
    off = bv['byteOffset'] + acc.get('byteOffset', 0)
    stride = bv.get('byteStride', 16)
    out = []
    for i in range(acc['count']):
        s = off + i * stride
        out.append(struct.unpack('<ffff', bin_data[s:s+16]))
    return out

def qdot(a, b):
    return abs(a[0]*b[0]+a[1]*b[1]+a[2]*b[2]+a[3]*b[3])

for fname, label in [('vrma/02_04.vrma', 'OLD (Mixamo)'), ('bvh_test/02_04.vrma', 'NEW (BVH)')]:
    gltf, bin_data = parse_glb(fname)
    anim = gltf['animations'][0]
    samplers = anim['samplers']
    nodes = gltf['nodes']
    ext = gltf.get('extensions', {}).get('VRMC_vrm_animation', {})
    hb = ext.get('humanoid', {}).get('humanBones', {})
    
    hb_nodes = {}
    for hk, hv in hb.items():
        ni = hv.get('node')
        if ni is not None:
            hb_nodes[ni] = (hk, nodes[ni].get('name', f'N{ni}'))
    
    print(f'=== {label} ===')
    rot_chs = [c for c in anim['channels'] if c['target']['path'] == 'rotation']
    pos_chs = [c for c in anim['channels'] if c['target']['path'] == 'translation']
    print(f'  Rot channels: {len(rot_chs)}, Pos channels: {len(pos_chs)}')
    
    max_deltas = {}
    for ch in rot_chs:
        ni = ch['target']['node']
        si = ch['sampler']
        out = get_accessor(gltf, samplers[si]['output'], bin_data)
        n = nodes[ni].get('name', f'N{ni}')
        hk = hb_nodes.get(ni, ('',''))[0]
        display = f'{hk}({n})' if hk else n
        
        md = 0
        for i in range(1, len(out)):
            de = 2 * math.acos(min(1, qdot(out[i-1], out[i]))) * 180 / math.pi
            if de > md: md = de
        max_deltas[display] = md
    
    sd = sorted(max_deltas.items(), key=lambda x: -x[1])
    for n, d in sd[:10]:
        print(f'  {n:50s} {d:.1f}deg')
    print(f'  ... ({len(sd)} total)')
    print(f'  MAX: {sd[0][1]:.1f}deg ({sd[0][0]})')
    
    print(f'  Frame 0->1 deltas >10deg:')
    for ch in rot_chs:
        ni = ch['target']['node']
        si = ch['sampler']
        out = get_accessor(gltf, samplers[si]['output'], bin_data)
        if len(out) < 2: continue
        de = 2 * math.acos(min(1, qdot(out[0], out[1]))) * 180 / math.pi
        if de > 10:
            n = nodes[ni].get('name', f'N{ni}')
            print(f'    {n:30s} {de:.1f}deg')
    print()
