import json, struct, sys

def dump_nodes(path):
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

    print("NODE LIST:")
    for i, node in enumerate(gltf.get('nodes', [])):
        print(f"{i}: {node.get('name')}")

if __name__ == "__main__":
    dump_nodes(sys.argv[1])
