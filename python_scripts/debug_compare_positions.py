"""
Compare BVH Hips position data with VRMA output for a walking clip.
Usage: blender --background --python debug_compare_positions.py -- <bvh_path> <vrma_path>
"""
import bpy, sys, json, struct

try:
    idx = sys.argv.index("--")
    args = sys.argv[idx + 1:]
except ValueError:
    args = []
bvh_path = args[0] if args else None
vrma_path = args[1] if args else None
if not bvh_path:
    print("Usage: blender --background --python debug_compare_positions.py -- <bvh_path> <vrma_path>")
    sys.exit(1)

# ---------- 1. BVH fcurve analysis ----------
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for a in list(bpy.data.actions): bpy.data.actions.remove(a)
for m in list(bpy.data.meshes): bpy.data.meshes.remove(m)
for ar in list(bpy.data.armatures): bpy.data.armatures.remove(ar)

bpy.ops.import_anim.bvh(filepath=bvh_path, axis_up='Z', global_scale=0.01)
armature = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
action = armature.animation_data.action

fcurves = []
if hasattr(action, 'layers'):
    try:
        fcurves = list(action.layers[0].strips[0].channelbags[0].fcurves)
    except Exception as e:
        print(f"Layered error: {e}")

loc_fcurves = [fc for fc in fcurves if fc.data_path == 'pose.bones["Hips"].location']
print(f"\n=== BVH: {bvh_path} ===")
print(f"Action: {action.name}, Hips location fcurves: {len(loc_fcurves)}")
if len(loc_fcurves) == 3:
    frame_start = int(loc_fcurves[0].range()[0])
    frame_end = int(loc_fcurves[0].range()[1])
    print(f"Frame range: {frame_start}-{frame_end}")
    
    # Sample every 10% of the animation
    bvh_samples = []
    for f in range(frame_start, frame_end + 1, max(1, (frame_end - frame_start) // 20)):
        pos = (loc_fcurves[0].evaluate(f), loc_fcurves[1].evaluate(f), loc_fcurves[2].evaluate(f))
        bvh_samples.append((f, pos))
        print(f"  Frame {f}: ({pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f})")
    
    # Compute total drift
    first = bvh_samples[0][1]
    last = bvh_samples[-1][1]
    drift = ((last[0]-first[0])**2 + (last[1]-first[1])**2 + (last[2]-first[2])**2)**0.5
    print(f"  BVH Total Hips drift: {drift:.4f}m")
    print(f"  BVH X range: {first[0]:.4f} → {last[0]:.4f} (Δ={last[0]-first[0]:.4f})")
    print(f"  BVH Z range: {first[2]:.4f} → {last[2]:.4f} (Δ={last[2]-first[2]:.4f})")

# ---------- 2. VRMA binary parse ----------
if vrma_path:
    print(f"\n=== VRMA: {vrma_path} ===")
    with open(vrma_path, 'rb') as f:
        data = f.read()
    
    # Find "KHR_animation_pointer" or "node" in the binary
    # GlTF: look for the accessor data
    txt = data.decode('utf-8', errors='replace')
    
    # Find Hips translation accessor
    # Look for "translation" near "hips" or "Hips"
    import re
    # Parse frame count from VRMA by finding animation/samplers
    # Count the occurrence of "Hips" in the JSON
    json_start = txt.find('{')
    json_end = txt.rfind('}')
    if json_start >= 0 and json_end >= 0:
        json_str = txt[json_start:json_end+1]
        try:
            gltf = json.loads(json_str)
            meshes = gltf.get('meshes', [])
            accessors = gltf.get('accessors', [])
            
            # Find Hips node index
            nodes = gltf.get('nodes', [])
            hips_node = None
            for i, n in enumerate(nodes):
                if 'Hips' in str(n.get('name', '')):
                    hips_node = i
                    break
            
            # Find animation targeting Hips translation
            anims = gltf.get('animations', [])
            hips_trans = None
            for ai, a in enumerate(anims):
                for ci, c in enumerate(a.get('channels', [])):
                    target = c.get('target', {})
                    if target.get('node') == hips_node and target.get('path') == 'translation':
                        # Get sampler -> accessor
                        sampler = a['samplers'][c['sampler']]
                        output_acc = accessors[sampler['output']]
                        input_acc = accessors[sampler['input']]
                        
                        # Read data from buffer
                        buf = gltf.get('buffers', [{}])[0]
                        buf_data = data
                        buf_start = buf.get('byteOffset', 0)
                        
                        out_off = output_acc.get('byteOffset', 0) + buf_start
                        in_off = input_acc.get('byteOffset', 0) + buf_start
                        count = output_acc['count']
                        comp_type = output_acc.get('componentType', 5126)  # FLOAT
                        stride = 12  # 3 floats
                        
                        print(f"  Hips translation accessor: count={count}, type={output_acc.get('type')}")
                        positions = []
                        for k in range(count):
                            off = out_off + k * stride
                            vals = struct.unpack_from('<fff', buf_data, off)
                            positions.append(vals)
                        
                        # Sample first, middle, last
                        for label, idx in [('frame 0', 0), ('mid', count//2), ('last', count-1)]:
                            print(f"    {label}: ({positions[idx][0]:.4f}, {positions[idx][1]:.4f}, {positions[idx][2]:.4f})")
                        
                        fps = positions[0]
                        lps = positions[-1]
                        x_drift = lps[0] - fps[0]
                        z_drift = lps[2] - fps[2]
                        total_drift = ((lps[0]-fps[0])**2 + (lps[1]-fps[1])**2 + (lps[2]-fps[2])**2)**0.5
                        print(f"  VRMA Hips drift: X={x_drift:.4f}, Z={z_drift:.4f}, total={total_drift:.4f}m")
        except json.JSONDecodeError as e:
            print(f"  JSON parse error: {e}")
            # Fallback: count binary size
            print(f"  VRMA size: {len(data)} bytes")
