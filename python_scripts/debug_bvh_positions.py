"""
Diagnose BVH position import: dump Hips location at sampled frames.
"""
import bpy, sys

try:
    idx = sys.argv.index("--")
    args = sys.argv[idx + 1:]
except ValueError:
    args = []
bvh_path = args[0] if args else None
if not bvh_path:
    print("Usage: blender --background --python debug_bvh_positions.py -- <bvh_path>")
    sys.exit(1)

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for a in list(bpy.data.actions): bpy.data.actions.remove(a)
for m in list(bpy.data.meshes): bpy.data.meshes.remove(m)
for ar in list(bpy.data.armatures): bpy.data.armatures.remove(ar)

bpy.ops.import_anim.bvh(filepath=bvh_path, axis_up='Z', global_scale=0.01)

armature = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
action = armature.animation_data.action

# Get Hips location fcurves from layered action
fcurves = []
if hasattr(action, 'layers'):
    try:
        fcurves = list(action.layers[0].strips[0].channelbags[0].fcurves)
    except Exception as e:
        print(f"Layered error: {e}")

loc_fcurves = [fc for fc in fcurves if fc.data_path == 'pose.bones["Hips"].location']

if len(loc_fcurves) == 3:
    print(f"Hips location fcurves: {len(loc_fcurves)}")
    print(f"  Range: frames {loc_fcurves[0].range()[0]:.0f} to {loc_fcurves[0].range()[1]:.0f}")
    
    # Dump keyframe values for each fcurve
    for fc in loc_fcurves:
        key = fc.keyframe_points[0] if fc.keyframe_points else None
        if key:
            print(f"  Fcurve index={fc.array_index}: {len(fc.keyframe_points)} keypoints")
            # Show first 3 and last 3 keypoints
            fps = list(fc.keyframe_points)
            for kp in fps[:3]:
                print(f"    frame={kp.co[0]:.0f} val={kp.co[1]:.6f}")
            if len(fps) > 6:
                print(f"    ...")
            for kp in fps[-3:]:
                print(f"    frame={kp.co[0]:.0f} val={kp.co[1]:.6f}")
    
    # Check evaluated values at multiple frames with scaling 0.01
    print(f"\n  Evaluated positions (scaled *0.01):")
    for f in [2, 100, 500, 1000, 2000, 2960]:
        pos = tuple(fc.evaluate(f) * 0.01 for fc in loc_fcurves)
        print(f"    Frame {f}: ({pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f})")
else:
    print(f"Expected 3 fcurves, got {len(loc_fcurves)}")

# Also check: does the BVH file have position data?
# Read the BVH directly and compare
import struct
with open(bvh_path, 'r') as f:
    content = f.read()

idx = content.find('MOTION')
data_lines = content[idx:].strip().split('\n')
data = [l.strip() for l in data_lines if l.strip() and not l.startswith('MOTION') and not l.startswith('Frames') and not l.startswith('Frame Time')]

# Frame 2 is index 1 (skip frame 0 which is T-pose)
# Frame 100 is index 99
for frame_name, bvh_idx in [('frame 2', 1), ('frame 100', 99)]:
    if bvh_idx < len(data):
        vals = data[bvh_idx].split()
        print(f"\n  BVH {frame_name} raw: X={vals[0]} Y={vals[1]} Z={vals[2]}")
        print(f"  BVH {frame_name} scaled*0.01: X={float(vals[0])*0.01:.4f} Y={float(vals[1])*0.01:.4f} Z={float(vals[2])*0.01:.4f}")
