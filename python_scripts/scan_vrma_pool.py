"""Scan all VRMAs for validity: extensions, Hips channels, bone mapping."""
import struct, json, os, sys, glob

def read_glb(path):
    with open(path, 'rb') as f:
        magic = struct.unpack('<I', f.read(4))[0]
        if magic != 0x46546C67: return None, 'bad magic'
        struct.unpack('<I', f.read(4))[0]
        length = struct.unpack('<I', f.read(4))[0]
        while f.tell() < length:
            cl = struct.unpack('<I', f.read(4))[0]
            ct = struct.unpack('<I', f.read(4))[0]
            cd = f.read(cl)
            if ct == 0x4E4F534A:
                return json.loads(cd.decode('utf-8')), None
            elif ct == 0x004E4942:
                pass
        return None, 'no JSON'
    return None, 'read error'

def scan_vrma(path):
    data, err = read_glb(path)
    if err: return None, err
    
    issues = []
    
    exts_used = data.get('extensionsUsed', [])
    if 'VRMC_vrm_animation' not in exts_used:
        issues.append('no VRMC_vrm_animation extension')
    
    ext = data.get('extensions', {}).get('VRMC_vrm_animation', {})
    sv = ext.get('specVersion')
    if sv != '1.0':
        issues.append(f'bad specVersion: {sv}')
    
    nodes = data.get('nodes', [])
    hips_idx = next((i for i, n in enumerate(nodes) if n.get('name') == 'Hips'), None)
    if hips_idx is None:
        issues.append('no Hips node')
    
    human_bones = ext.get('humanoid', {}).get('humanBones', {})
    if len(human_bones) < 5:
        issues.append(f'too few humanBones: {len(human_bones)}')
    
    # Check animation channels for Hips
    has_rot = False
    has_pos = False
    for anim in data.get('animations', []):
        for ch in anim.get('channels', []):
            tgt = ch.get('target', {})
            if tgt.get('node') == hips_idx:
                if tgt.get('path') == 'rotation': has_rot = True
                if tgt.get('path') == 'translation': has_pos = True
    
    if not has_rot: issues.append('no Hips rotation')
    if not has_pos: issues.append('no Hips translation')
    
    if issues:
        return None, '; '.join(issues)
    
    return {
        'nodes': len(nodes),
        'bones': len(human_bones),
        'anims': len(data.get('animations', [])),
        'spec': sv,
    }, None


vrma_dir = sys.argv[1] if len(sys.argv) > 1 else 'D:/VRE/vrma'
files = sorted(glob.glob(os.path.join(vrma_dir, '*.vrma')))
print(f'Scanning {len(files)} VRMAs...')

valid = []
invalid = []
for f in files:
    name = os.path.basename(f)
    info, err = scan_vrma(f)
    if info:
        valid.append((name, info))
    else:
        invalid.append((name, err))

print(f'\nValid: {len(valid)}')
print(f'Invalid: {len(invalid)}')

if invalid:
    print(f'\nFirst 20 invalid:')
    for name, err in invalid[:20]:
        print(f'  {name}: {err}')

print(f'\nSample of valid:')
for name, info in valid[:10]:
    print(f'  {name}: {info["nodes"]} nodes, {info["bones"]} bones, {info["anims"]} anims')

# Write valid list
out_path = os.path.join(vrma_dir, '..', 'test_pool_valid.txt')
with open(out_path, 'w') as f:
    for name, _ in valid:
        f.write(name + '\n')
print(f'\nValid list written to {out_path}')
