import bpy
import os, sys

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# Import BVH
bpy.ops.import_anim.bvh(filepath='bvh_test/02_04.bvh', axis_up='Z', global_scale=0.01)
bvh_arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]

# Import VRM
bpy.ops.import_scene.vrm(filepath='models/Seed-san.vrm')

# Find VRM armature
for o in bpy.data.objects:
    if o.type == 'ARMATURE' and o.name != bvh_arm.name:
        vrm_arm = o
        break

print(f"\nBVH arm: {bvh_arm.name}, bones: {len(bvh_arm.data.bones)}")
print(f"VRM arm: {vrm_arm.name}, bones: {len(vrm_arm.data.bones)}")

# Debug: check BVH bone rotations at a few frames
bpy.context.view_layer.objects.active = bvh_arm
bpy.ops.object.mode_set(mode='POSE')

print("\nBVH bone rotations by frame:")
for frame in [1, 2, 5, 10]:
    bpy.context.scene.frame_set(frame)
    vals = []
    for bname in ['Hips', 'LeftUpLeg', 'LeftArm', 'Neck', 'Head', 'Spine']:
        pb = bvh_arm.pose.bones.get(bname)
        if pb:
            q = pb.rotation_quaternion
            vals.append(f"{bname}: ({q.x:.4f}, {q.y:.4f}, {q.z:.4f}, {q.w:.4f})")
    print(f"  Frame {frame:3d}: {' | '.join(vals)}")

# Debug: check VRM rest pose at frame 1
print("\nVRM bone rest rotations (frame 1):")
bpy.context.view_layer.objects.active = vrm_arm
bpy.ops.object.mode_set(mode='POSE')

# Read VRM humanoid map
ext = vrm_arm.data.vrm_addon_extension
hb = ext.vrm1.humanoid.human_bones
vrm_humanoid = {}
for attr_name in dir(hb):
    if attr_name.startswith('_'): continue
    entry = getattr(hb, attr_name, None)
    if entry is None: continue
    try:
        node = entry.node
        if node and node.bone_name:
            vrm_humanoid[attr_name] = node.bone_name
    except:
        pass

bpy.context.scene.frame_set(1)
for key in ['hips', 'left_upper_leg', 'left_upper_arm', 'neck', 'head', 'spine']:
    bn = vrm_humanoid.get(key, f"??{key}")
    pb = vrm_arm.pose.bones.get(bn)
    if pb:
        q = pb.rotation_quaternion
        print(f"  {key:20s} -> {bn:20s}: ({q.x:.4f}, {q.y:.4f}, {q.z:.4f}, {q.w:.4f})")

# Now test applying a BVH frame to a VRM bone
print("\nTest applying frame 1 BVH->VRM:")
bpy.context.scene.frame_set(1)
for key, bvh_name in [('left_upper_leg', 'LeftUpLeg'), ('left_upper_arm', 'LeftArm'), ('spine', 'Spine')]:
    vrm_bn = vrm_humanoid.get(key)
    bvh_pb = bvh_arm.pose.bones.get(bvh_name)
    vrm_pb = vrm_arm.pose.bones.get(vrm_bn)
    if not bvh_pb or not vrm_pb: continue
    
    # Compute correction
    parent = vrm_pb.parent
    pm = parent.matrix if parent else __import__('mathutils').Matrix()
    local_rest = pm.inverted() @ vrm_pb.matrix
    correction = local_rest.to_quaternion().inverted()
    
    result = correction @ bvh_pb.rotation_quaternion
    print(f"  {bvh_name:15s} -> {vrm_bn:20s}: bvh_q=({bvh_pb.rotation_quaternion.x:.4f}, {bvh_pb.rotation_quaternion.y:.4f}, {bvh_pb.rotation_quaternion.z:.4f}, {bvh_pb.rotation_quaternion.w:.4f})")
    print(f"    correction=({correction.x:.4f}, {correction.y:.4f}, {correction.z:.4f}, {correction.w:.4f})")
    print(f"    result=({result.x:.4f}, {result.y:.4f}, {result.z:.4f}, {result.w:.4f})")
