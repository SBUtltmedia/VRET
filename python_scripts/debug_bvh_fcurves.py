"""
Quick diagnostic: import BVH, dump all fcurve data_paths and Hips location at frame 2.
"""
import bpy, sys, os

# Parse args
try:
    idx = sys.argv.index("--")
    args = sys.argv[idx + 1:]
except ValueError:
    args = []
bvh_path = args[0] if args else None
if not bvh_path:
    print("Usage: blender --background --python debug_bvh_fcurves.py -- <bvh_path>")
    sys.exit(1)

# Clear scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for a in list(bpy.data.actions):   bpy.data.actions.remove(a)
for m in list(bpy.data.meshes):    bpy.data.meshes.remove(m)
for ar in list(bpy.data.armatures): bpy.data.armatures.remove(ar)

# Import BVH
bpy.ops.import_anim.bvh(filepath=bvh_path, axis_up='Z', global_scale=0.01)

armature = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
if not armature:
    print("ERROR: No armature")
    sys.exit(1)

action = armature.animation_data.action
print(f"Armature: {armature.name}, Action: {action.name}")
print(f"Action type: {'layered' if hasattr(action, 'layers') and action.layers else 'legacy'}")
print(f"Bones: {len(armature.data.bones)}")

# Dump all fcurves
fcurves = []
if hasattr(action, 'fcurves'):
    fcurves = list(action.fcurves)

if not fcurves and hasattr(action, 'layers'):
    try:
        fcurves = list(action.layers[0].strips[0].channelbags[0].fcurves)
        print(f"Using layered action fallback: {len(fcurves)} fcurves")
    except Exception as e:
        print(f"Layered fallback failed: {e}")

print(f"\nTotal fcurves: {len(fcurves)}")

# Group by data_path
from collections import defaultdict
by_path = defaultdict(list)
for fc in fcurves:
    by_path[fc.data_path].append(fc.array_index)

for path, indices in sorted(by_path.items()):
    print(f"  {path}: indices={sorted(indices)} count={len(indices)}")

# Check Hips location specifically
loc_path = 'pose.bones["Hips"].location'
loc_fcurves = [fc for fc in fcurves if fc.data_path == loc_path]
print(f"\nHips location fcurves: {len(loc_fcurves)}")
if len(loc_fcurves) == 3:
    hip_pos = tuple(fc.evaluate(2) * 0.01 for fc in loc_fcurves)
    print(f"  Evaluated at frame 2 (scaled *0.01): ({hip_pos[0]:.4f}, {hip_pos[1]:.4f}, {hip_pos[2]:.4f})")
    hip_pos_f100 = tuple(fc.evaluate(100) * 0.01 for fc in loc_fcurves)
    print(f"  Evaluated at frame 100 (scaled *0.01): ({hip_pos_f100[0]:.4f}, {hip_pos_f100[1]:.4f}, {hip_pos_f100[2]:.4f})")
elif len(loc_fcurves) > 0:
    for fc in loc_fcurves:
        print(f"  Frame 2: index={fc.array_index}, value={fc.evaluate(2)}")
else:
    print("  NO Hips location fcurves found!")
    # Check if the Hips bone exists in the armature
    if "Hips" in armature.pose.bones:
        pb = armature.pose.bones["Hips"]
        print(f"  Hips bone exists. location=({pb.location.x:.4f}, {pb.location.y:.4f}, {pb.location.z:.4f}) at current frame")
    else:
        print("  Hips bone NOT found in armature")
        print(f"  Available bones: {[b.name for b in armature.data.bones][:10]}...")
