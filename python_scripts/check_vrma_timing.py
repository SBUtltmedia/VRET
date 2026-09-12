"""
Parse VRMA: Hips translation keyframes and their time values.
"""
import struct, json, sys

vrma_path = sys.argv[1] if len(sys.argv) > 1 else "vrma/105_13.vrma"

with open(vrma_path, 'rb') as f:
    data = f.read()

magic, version, glb_len = struct.unpack_from('<III', data, 0)
pos = 12
json_str = None
bin_data = None
while pos < len(data):
    chunk_len, chunk_type = struct.unpack_from('<II', data, pos)
    pos += 8
    chunk_data = data[pos:pos+chunk_len]
    pos += chunk_len
    if chunk_type == 0x4E4F534A:
        json_str = chunk_data.decode('utf-8')
    elif chunk_type == 0x004E4942:
        bin_data = chunk_data

gltf = json.loads(json_str)
accessors = gltf.get('accessors', [])
nodes = gltf.get('nodes', [])
anims = gltf.get('animations', [])
buffer_views = gltf.get('bufferViews', [])

hips_node = next((i for i, n in enumerate(nodes) if 'Hips' in n.get('name', '')), None)
if hips_node is None:
    print("No Hips node found")
    exit(1)

for a in anims:
    for c in a.get('channels', []):
        target = c.get('target', {})
        if target.get('node') == hips_node and target.get('path') == 'translation':
            sampler = a['samplers'][c['sampler']]
            # Input accessor (time values)
            in_acc = accessors[sampler['input']]
            in_bv = buffer_views[in_acc['bufferView']]
            in_off = in_acc.get('byteOffset', 0) + in_bv.get('byteOffset', 0)
            in_count = in_acc['count']
            
            times = []
            for k in range(in_count):
                t = struct.unpack_from('<f', bin_data, in_off + k * 4)[0]
                times.append(t)
            
            print(f"Input timing: {in_count} samples")
            print(f"  First: {times[0]:.4f}s")
            print(f"  Last:  {times[-1]:.4f}s")
            print(f"  Duration: {times[-1]-times[0]:.4f}s")
            print(f"  Sample rate: {in_count / (times[-1]-times[0]):.1f}fps")
            print(f"  Interval (1st→2nd): {(times[1]-times[0]):.4f}s → {(1/(times[1]-times[0])):.1f}fps")
            
            # Show every 10th sample
            step = max(1, in_count // 10)
            for i in range(0, in_count, step):
                print(f"  time={times[i]:.4f}s  frame={i}")
