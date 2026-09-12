"""
Parse VRMA GLB binary to extract Hips translation data.
"""
import struct, json, sys

vrma_path = sys.argv[1] if len(sys.argv) > 1 else "vrma/16_19.vrma"

with open(vrma_path, 'rb') as f:
    data = f.read()

# GLB header: magic (4) + version (4) + length (4) = 12 bytes
magic, version, glb_len = struct.unpack_from('<III', data, 0)
assert magic == 0x46546C67, f"Not a GLB file: magic=0x{magic:08X}"

# Parse chunks
pos = 12
json_str = None
bin_data = None
while pos < len(data):
    chunk_len, chunk_type = struct.unpack_from('<II', data, pos)
    pos += 8
    chunk_data = data[pos:pos+chunk_len]
    pos += chunk_len
    if chunk_type == 0x4E4F534A:  # JSON
        json_str = chunk_data.decode('utf-8')
    elif chunk_type == 0x004E4942:  # BIN
        bin_data = chunk_data

if not json_str:
    print("No JSON chunk found")
    sys.exit(1)

gltf = json.loads(json_str)
accessors = gltf.get('accessors', [])
nodes = gltf.get('nodes', [])
anims = gltf.get('animations', [])
buffer_views = gltf.get('bufferViews', [])

# Find Hips node
hips_node = None
for i, n in enumerate(nodes):
    if 'Hips' in n.get('name', ''):
        hips_node = i
        break
print(f"Hips node index: {hips_node}")

if hips_node is None:
    # Try gltf node names
    for i, n in enumerate(nodes):
        print(f"  Node {i}: {n.get('name', '(unnamed)')}")
    sys.exit(1)

# Find animation channel for Hips translation
for ai, a in enumerate(anims):
    for ci, c in enumerate(a.get('channels', [])):
        target = c.get('target', {})
        if target.get('node') == hips_node and target.get('path') == 'translation':
            sampler = a['samplers'][c['sampler']]
            output_acc = accessors[sampler['output']]
            input_acc = accessors[sampler['input']]
            
            # Read output data
            out_bv = buffer_views[output_acc['bufferView']]
            out_off = output_acc.get('byteOffset', 0) + out_bv.get('byteOffset', 0)
            count = output_acc['count']
            stride = 12  # 3 floats (FLOAT VEC3)
            
            print(f"\nHips translation: {count} keyframes")
            positions = []
            for k in range(count):
                off = out_off + k * stride
                vals = struct.unpack_from('<fff', bin_data, off)
                positions.append(vals)
            
            # Print summary
            for label, idx in [('first', 0), ('10%', count//10), ('25%', count//4), 
                               ('50%', count//2), ('75%', 3*count//4), ('last', count-1)]:
                print(f"  {label}: ({positions[idx][0]:.4f}, {positions[idx][1]:.4f}, {positions[idx][2]:.4f})")
            
            # Compute drift
            first = positions[0]
            last = positions[-1]
            x_drift = last[0] - first[0]
            z_drift = last[2] - first[2]
            total_drift = ((last[0]-first[0])**2 + (last[1]-first[1])**2 + (last[2]-first[2])**2)**0.5
            print(f"\n  VRMA Hips drift: X={x_drift:.4f}m, Z={z_drift:.4f}m, total={total_drift:.4f}m")
            print(f"  BVH Hips drift (from earlier): total=0.4003m")
            print(f"  Match: {'YES' if abs(total_drift - 0.4003) < 0.01 else 'DIFFERS'}")
