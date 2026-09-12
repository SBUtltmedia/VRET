"""
Quick test: convert 10 frames of BVH and check Hips position in output VRMA.
"""
import bpy, sys, json, struct, os

idx = sys.argv.index("--") if "--" in sys.argv else -1
args = sys.argv[idx+1:] if idx >= 0 else []
bvh_path = args[0] if args else None
if not bvh_path or not os.path.exists(bvh_path):
    print("Usage: blender --background --python test_bvh_position.py -- <bvh_path>")
    sys.exit(1)

import os
bvh_name = os.path.basename(bvh_path).replace('.bvh', '')

# Clear + import BVH
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for a in list(bpy.data.actions): bpy.data.actions.remove(a)
for m in list(bpy.data.meshes): bpy.data.meshes.remove(m)
for ar in list(bpy.data.armatures): bpy.data.armatures.remove(ar)

bpy.ops.import_anim.bvh(filepath=bvh_path, axis_up='Z', global_scale=0.01)
armature = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
action = armature.animation_data.action

# Get Hips location fcurves
fcurves = []
if hasattr(action, 'layers'):
    fcurves = list(action.layers[0].strips[0].channelbags[0].fcurves)

loc_fcurves = [fc for fc in fcurves if fc.data_path == 'pose.bones["Hips"].location']
assert len(loc_fcurves) == 3, f"Expected 3 loc fcurves, got {len(loc_fcurves)}"

f_range = action.frame_range
f_start = int(f_range[0])
f_end = int(f_range[1])

print(f"BVH: {bvh_name}, frames {f_start}-{f_end}")
print(f"Hips location fcurves: 3 channels")

# Print sampled positions (WITHOUT double scaling)
print(f"\nHips position (correct, meters):")
for pct in range(0, 101, 10):
    f = f_start + int((f_end - f_start) * pct / 100)
    x = loc_fcurves[0].evaluate(f)
    y = loc_fcurves[1].evaluate(f)
    z = loc_fcurves[2].evaluate(f)
    print(f"  {pct:3d}% (frame {f:4d}): ({x:.4f}, {y:.4f}, {z:.4f})")

# Compute drift
x1 = loc_fcurves[0].evaluate(f_start)
x2 = loc_fcurves[0].evaluate(f_end)
y1 = loc_fcurves[1].evaluate(f_start)
y2 = loc_fcurves[1].evaluate(f_end)
z1 = loc_fcurves[2].evaluate(f_start)
z2 = loc_fcurves[2].evaluate(f_end)
drift = ((x2-x1)**2 + (y2-y1)**2 + (z2-z1)**2)**0.5
print(f"\nTotal drift: {drift:.4f}m")
print(f"X: {x1:.4f} -> {x2:.4f}  (dx={x2-x1:.4f})")
print(f"Y: {y1:.4f} -> {y2:.4f}  (dy={y2-y1:.4f})")
print(f"Z: {z1:.4f} -> {z2:.4f}  (dz={z2-z1:.4f})")
