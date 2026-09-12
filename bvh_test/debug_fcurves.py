import bpy

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

bpy.ops.import_anim.bvh(filepath='bvh_test/02_04.bvh', axis_up='Z', global_scale=0.01)
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]

action = arm.animation_data.action
print(f"Action: {action.name}, frame_range: {action.frame_range}")

# Blender 5.0 uses layered actions
try:
    fcurves = action.fcurves
except:
    fcurves = action.layers[0].strips[0].channelbags[0].fcurves

print(f"Fcurves: {len(fcurves)}")

# Show unique data paths
seen = set()
for fc in fcurves:
    dp = fc.data_path
    if dp not in seen:
        seen.add(dp)
        kps = fc.keyframe_points
        if len(kps) > 0:
            print(f"  {dp}: {len(kps)} kf, range {kps[0].co[1]:.3f}..{kps[-1].co[1]:.3f}")

# Evaluate at frames
print(f"\nEvaluating pose bones at frames...")
for frame in [1, 10, 50, 100]:
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    
    bpy.ops.object.mode_set(mode='POSE')
    vals = []
    for bname in ['Hips', 'LeftUpLeg', 'LeftArm', 'RightArm', 'Spine']:
        pb = arm.pose.bones.get(bname)
        if pb:
            q = pb.rotation_quaternion
            vals.append(f"{bname}: ({q.x:.4f}, {q.y:.4f}, {q.z:.4f}, {q.w:.4f})")
    print(f"  Frame {frame:3d}: {' | '.join(vals)}")

print("\nDone")
