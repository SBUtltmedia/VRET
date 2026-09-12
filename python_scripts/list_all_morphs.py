import json, struct, sys

def list_all_morphs(path):
    with open(path, 'rb') as f:
        data = f.read()
    
    magic, version, length = struct.unpack_from('<III', data, 0)
    if magic != 0x46546C67: return
    
    offset = 12
    gltf = {}
    while offset < len(data):
        chunk_len, chunk_type = struct.unpack_from('<II', data, offset)
        offset += 8
        if chunk_type == 0x4E4F534A: # JSON
            json_bytes = data[offset:offset+chunk_len]
            gltf = json.loads(json_bytes)
            break
        offset += chunk_len

    for i, node in enumerate(gltf.get('nodes', [])):
        mesh_idx = node.get('mesh')
        if mesh_idx is not None:
            mesh = gltf['meshes'][mesh_idx]
            target_names = mesh.get('extras', {}).get('targetNames', [])
            print(f"\nNODE {i} ({node.get('name')}):")
            for tidx, tname in enumerate(target_names):
                print(f"  [{tidx}] {tname}")

if __name__ == "__main__":
    list_all_morphs(sys.argv[1])
