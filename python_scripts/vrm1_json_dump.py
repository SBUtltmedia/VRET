import json, struct, sys

def dump_vrm1(path):
    with open(path, 'rb') as f:
        data = f.read()
    
    magic, version, length = struct.unpack_from('<III', data, 0)
    if magic != 0x46546C67: return "Not GLB"
    
    offset = 12
    while offset < len(data):
        chunk_len, chunk_type = struct.unpack_from('<II', data, offset)
        offset += 8
        if chunk_type == 0x4E4F534A: # JSON
            json_bytes = data[offset:offset+chunk_len]
            gltf = json.loads(json_bytes)
            
            # Look for VRM 1.0 extension
            vrm1 = gltf.get('extensions', {}).get('VRMC_vrm')
            if vrm1:
                print(json.dumps(vrm1, indent=2))
            else:
                print("No VRMC_vrm extension found.")
            return
        offset += chunk_len

if __name__ == "__main__":
    dump_vrm1(sys.argv[1])
