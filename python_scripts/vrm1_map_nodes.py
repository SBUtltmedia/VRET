import json, struct, sys

def map_vrm_nodes(path):
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

    # 1. Map node indices to names
    node_names = [n.get('name', f'node_{i}') for i, n in enumerate(gltf.get('nodes', []))]
    
    # 2. Find meshes and their morph targets
    print("MESH MAPPING:")
    for i, node in enumerate(gltf.get('nodes', [])):
        mesh_idx = node.get('mesh')
        if mesh_idx is not None:
            mesh = gltf['meshes'][mesh_idx]
            print(f"Node {i}: {node.get('name')} (Mesh {mesh_idx}: {mesh.get('name')})")
            # Look for extras/targetNames or primitives[0].targets
            prim = mesh['primitives'][0]
            target_names = mesh.get('extras', {}).get('targetNames', [])
            print(f"  Targets: {len(target_names)}")
            if target_names:
                # Print sample
                print(f"  Sample: {target_names[:5]}...")

    # 3. Check Eye parenting
    vrm1 = gltf.get('extensions', {}).get('VRMC_vrm', {})
    bones = vrm1.get('humanoid', {}).get('humanBones', {})
    print("\nBONE PARENTING:")
    for bone_name in ['leftEye', 'rightEye', 'jaw']:
        bone_data = bones.get(bone_name)
        if bone_data:
            node_idx = bone_data['node']
            print(f"{bone_name}: Node {node_idx} ({node_names[node_idx]})")
            # Find children
            children = gltf['nodes'][node_idx].get('children', [])
            child_names = [node_names[c] for k, c in enumerate(children)]
            print(f"  Children: {child_names}")

if __name__ == "__main__":
    map_vrm_nodes(sys.argv[1])
