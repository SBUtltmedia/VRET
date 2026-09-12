import json, struct, os, sys
from pathlib import Path

"""
vrm1_batch_recompose.py

Automated batch processor for VRM 1.0 models.
1. Fixes mouthFunnel distortion by mixing with mouthPucker.
2. Wires up missing high-level presets (happy, sad, angry, surprised, relaxed) 
   using combinations of ARKit shapes.
"""

# Config: Define which shapes make up an emotion
EMOTION_RECIPES = {
    "happy": [
        ("mouthSmileLeft", 1.0), ("mouthSmileRight", 1.0),
        ("eyeSquintLeft", 0.5), ("eyeSquintRight", 0.5)
    ],
    "sad": [
        ("mouthFrownLeft", 0.8), ("mouthFrownRight", 0.8),
        ("browDownLeft", 0.6), ("browDownRight", 0.6)
    ],
    "angry": [
        ("browDownLeft", 1.0), ("browDownRight", 1.0),
        ("eyeSquintLeft", 0.8), ("eyeSquintRight", 0.8),
        ("noseSneerLeft", 0.7), ("noseSneerRight", 0.7)
    ],
    "surprised": [
        ("eyeWideLeft", 1.0), ("eyeWideRight", 1.0),
        ("jawOpen", 0.4), ("browOuterUpLeft", 0.8), ("browOuterUpRight", 0.8)
    ],
    "relaxed": [
        ("eyeSquintLeft", 0.4), ("eyeSquintRight", 0.4),
        ("mouthSmileLeft", 0.2), ("mouthSmileRight", 0.2)
    ]
}

# Config: Fixes for distorted or under-defined shapes
SHAPE_FIXES = {
    "mouthFunnel": [
        ("mouthPucker", 0.6),
        ("jawOpen", 0.1)
        # Stripped extra funnel/roll weights to prevent over-opening and clipping
    ],
    "mouthPucker": [
        ("mouthPucker", 1.0),
        ("mouthClose", 0.1)
    ],
    "mouthStretchLeft": [
        ("mouthStretchLeft", 1.0),
        ("mouthLeft", 0.2) # Add lateral pull
    ],
    "mouthStretchRight": [
        ("mouthStretchRight", 1.0),
        ("mouthRight", 0.2) # Add lateral pull
    ],
    "noseSneerLeft": [
        ("noseSneerLeft", 1.0),
        ("browDownLeft", 0.3) # Add upper face involvement
    ],
    "noseSneerRight": [
        ("noseSneerRight", 1.0),
        ("browDownRight", 0.3) # Add upper face involvement
    ]
}

def read_glb(path):
    data = path.read_bytes()
    if len(data) < 12: return None, None
    magic, version, length = struct.unpack_from('<III', data, 0)
    if magic != 0x46546C67: return None, None
    
    offset = 12
    json_bytes = bin_bytes = b''
    while offset < len(data):
        chunk_len, chunk_type = struct.unpack_from('<II', data, offset)
        offset += 8
        chunk_data = data[offset: offset + chunk_len]
        offset += chunk_len
        if chunk_type == 0x4E4F534A: json_bytes = chunk_data
        elif chunk_type == 0x004E4942: bin_bytes = chunk_data
    return json.loads(json_bytes), bin_bytes

def write_glb(path, gltf, bin_bytes):
    json_bytes = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    pad = (4 - len(json_bytes) % 4) % 4
    json_bytes += b' ' * pad
    
    chunks = bytearray()
    chunks += struct.pack('<II', len(json_bytes), 0x4E4F534A)
    chunks += json_bytes
    if bin_bytes:
        bin_pad = (4 - len(bin_bytes) % 4) % 4
        padded_bin = bin_bytes + b'\x00' * bin_pad
        chunks += struct.pack('<II', len(padded_bin), 0x004E4942)
        chunks += padded_bin
    
    header = struct.pack('<III', 0x46546C67, 2, 12 + len(chunks))
    path.write_text('') # Clear
    path.write_bytes(header + bytes(chunks))

def process_file(path):
    gltf, bin_bytes = read_glb(path)
    if not gltf: return False
    
    vrm1 = gltf.get('extensions', {}).get('VRMC_vrm')
    if not vrm1: return False
    
    exprs = vrm1.get('expressions', {})
    custom = exprs.get('custom', {})
    presets = exprs.get('preset', {})
    
    # 1. Map ALL morph targets from ALL meshes
    # This allows us to sync Face and Teeth
    name_to_binds = {} # name -> list of {node, index}
    
    for node_idx, node in enumerate(gltf.get('nodes', [])):
        mesh_idx = node.get('mesh')
        if mesh_idx is not None:
            mesh = gltf['meshes'][mesh_idx]
            target_names = mesh.get('extras', {}).get('targetNames', [])
            if not target_names: continue
            
            for morph_idx, full_name in enumerate(target_names):
                # Normalize names
                # Face uses: 'h_expressions.jawOpen' or 'jawOpen'
                # Teeth uses: 't_MouthOpen_h' or 'MouthOpen_tg_h'
                
                # 1. Strip common prefixes/suffixes
                clean_name = full_name.split('.')[-1]
                clean_name = clean_name.replace('t_', '').replace('_h', '').replace('_tg', '')
                
                # 2. Map specific VALID Teeth/Skin aliases
                # We want to map Teeth names to their ARKit counterparts
                TEETH_ALIAS = {
                    'MouthOpen': 'jawOpen',
                    'Shout': 'mouthFunnel',
                    'MPB': 'mouthClose',
                    'Ljaw': 'jawLeft',
                    'Rjaw': 'jawRight',
                    'JawFront': 'jawForward',
                    'Kiss': 'mouthPucker',
                    'AE_AA': 'aa', 'TD_I': 'ih', 'UH_OO': 'ou', 'AO_a': 'oh', 'Ax_E': 'ee'
                }
                clean_name = TEETH_ALIAS.get(clean_name, clean_name)
                
                if clean_name not in name_to_binds:
                    name_to_binds[clean_name] = []
                name_to_binds[clean_name].append({'node': node_idx, 'index': morph_idx})

    if not name_to_binds:
        return False

    changed = False

    # 2. Apply Shape Fixes (mouthFunnel, mouthPucker, etc)
    for target_name, recipe in SHAPE_FIXES.items():
        if target_name in custom or target_name in presets:
            new_binds = []
            for source_name, weight in recipe:
                source_binds = name_to_binds.get(source_name, [])
                for b in source_binds:
                    bind = b.copy()
                    bind['weight'] = weight
                    new_binds.append(bind)
            
            target_dict = custom.get(target_name) or presets.get(target_name)
            if new_binds and target_dict:
                # EXPLICIT OVERWRITE: ensure we aren't appending to broken original binds
                target_dict['morphTargetBinds'] = new_binds
                changed = True
                print(f"    - Overwrote {target_name} with {len(new_binds)} clean sync-binds")

    # 3. Wire up Presets (Happy/Sad/etc)
    for preset_name, recipe in EMOTION_RECIPES.items():
        if preset_name in presets:
            new_binds = []
            for source_name, weight in recipe:
                source_binds = name_to_binds.get(source_name, [])
                for b in source_binds:
                    bind = b.copy()
                    bind['weight'] = weight
                    new_binds.append(bind)
            if new_binds:
                presets[preset_name]['morphTargetBinds'] = new_binds
                changed = True
                print(f"    - Wired preset {preset_name} with {len(new_binds)} sync-binds")

    # 4. Update Meta Info
    meta = vrm1.get('meta', {})
    vrm_name = path.stem.replace('_CLEANED', '')
    
    meta_updates = {
        "authors": ["Google VALID", "TLTMedia"],
        "name": vrm_name,
        "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
        "avatarPermission": "everyone",
        "allowAntisocialOrHateUsage": False,
        "allowExcessivelySexualUsage": False,
        "allowExcessivelyViolentUsage": False,
        "allowPoliticalOrReligiousUsage": False,
        "commercialUsage": "allow",
        "modification": "allow",
        "creditNotation": "required"
    }
    
    for k, v in meta_updates.items():
        if meta.get(k) != v:
            meta[k] = v
            changed = True
            
    if changed:
        vrm1['meta'] = meta
        write_glb(path, gltf, bin_bytes)
        return True
    return False

def main():
    root_dir = Path("models")
    # Target ONLY the specific file for debugging
    vrm_files = [root_dir / "AIAN" / "AIAN_F_1_Busi.vrm"]
    
    print(f"DEBUG: Processing ONLY {vrm_files[0]}")
    
    patched_count = 0
    for vrm in vrm_files:
        if not vrm.exists():
            print(f"    [Error] File not found: {vrm}")
            continue
        print(f"  Processing {vrm}...")
        try:
            if process_file(vrm):
                patched_count += 1
        except Exception as e:
            print(f"    [Error] {e}")
            
    print(f"\nDone! Patched {patched_count} models.")

if __name__ == "__main__":
    main()
