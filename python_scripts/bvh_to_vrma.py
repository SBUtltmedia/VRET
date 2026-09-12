"""
bvh_to_vrma.py  —  Blender Python script
Converts CGSpeed CMU BVH (MotionBuilder-friendly 2010) to VRMA format.

Reads the target VRM's actual bone names from the VRM extension metadata,
so it works with any VRM model regardless of bone naming convention.

Usage:
  blender --background --python bvh_to_vrma.py -- <bvh_path> <vrm_path> <output_dir>
  blender --background --python bvh_to_vrma.py -- --bvh=<path> --vrm=<path> --output=<dir>
"""

import bpy
import os
import sys
from pathlib import Path
from mathutils import Matrix, Quaternion

# ── BVH bone name → VRM 1.0 humanoid standard key ─────────────────────────
# Left column: CGSpeed MotionBuilder-friendly BVH bone names
# Right column: VRM 1.0 humanoid bone key (lowerCamelCase as defined in spec)

BVH_BONE_MAP = {
    'Hips': 'hips',
    'LowerBack': 'spine',
    'Spine': 'chest',
    'Spine1': 'upper_chest',

    'Neck': 'neck',
    'Neck1': None,      # VRM has only one Neck
    'Head': 'head',

    'LeftShoulder': 'left_shoulder',
    'LeftArm': 'left_upper_arm',
    'LeftForeArm': 'left_lower_arm',
    'LeftHand': 'left_hand',

    'RightShoulder': 'right_shoulder',
    'RightArm': 'right_upper_arm',
    'RightForeArm': 'right_lower_arm',
    'RightHand': 'right_hand',

    'LeftUpLeg': 'left_upper_leg',
    'LeftLeg': 'left_lower_leg',
    'LeftFoot': 'left_foot',
    'LeftToeBase': 'left_toes',

    'RightUpLeg': 'right_upper_leg',
    'RightLeg': 'right_lower_leg',
    'RightFoot': 'right_foot',
    'RightToeBase': 'right_toes',

    # Hip joints (no motion data — skip)
    'LHipJoint': None,
    'RHipJoint': None,

    # Fingers: CMU explicitly says these are procedural filler, NOT real mocap data.
    # See https://mocap.cs.cmu.edu/ — "The 'finger' and 'thumb' joints are added
    # to the skeleton for editing convenience — we do not actually capture these
    # joints' motions and any such data should be ignored."
    # DO NOT map finger BVH bones — they corrupt the hand if mapped there, and
    # are artificial filler anyway. All VRM finger bones will be zeroed to
    # identity rotation in a separate pass after the bake loop.
    'LeftFingerBase': None,
    'LeftHandIndex1': None,
    'LThumb': None,
    'RightFingerBase': None,
    'RightHandIndex1': None,
    'RThumb': None,
}


def read_vrm_humanoid_map(armature):
    """
    Read the VRM extension's humanoid bone mapping from the armature.
    Returns dict: VRM standard key (e.g. 'leftUpperLeg') → actual bone name (e.g. 'thigh.L')
    """
    result = {}
    try:
        ext = armature.data.vrm_addon_extension
        human_bones = ext.vrm1.humanoid.human_bones
        # Iterate over all attributes of human_bones
        for attr_name in dir(human_bones):
            if attr_name.startswith('_'):
                continue
            entry = getattr(human_bones, attr_name, None)
            if entry is None:
                continue
            try:
                node = entry.node
                if node and node.bone_name:
                    result[attr_name] = node.bone_name
            except Exception:
                pass
    except Exception as e:
        print(f"   ⚠ Could not read VRM extension: {e}")
    return result


# ── Utilities ─────────────────────────────────────────────────────────────────

def clear_scene():
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for a in list(bpy.data.actions):   bpy.data.actions.remove(a)
    for m in list(bpy.data.meshes):    bpy.data.meshes.remove(m)
    for ar in list(bpy.data.armatures): bpy.data.armatures.remove(ar)


def get_armature():
    return next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)


def get_action_fcurves(action):
    if hasattr(action, 'fcurves') and len(list(action.fcurves)) > 0:
        return action.fcurves
    try:
        return action.layers[0].strips[0].channelbags[0].fcurves
    except (IndexError, AttributeError):
        return []


def build_euler_fcurve_cache(bvh_armature):
    """
    Build a dict: bone_name -> [x_fcurve, y_fcurve, z_fcurve]
    from the BVH armature's rotation_euler fcurves.

    The CGSpeed BVH stores rotation as Euler angles (XYZ channels).
    We must evaluate them manually because Blender background mode
    does not auto-evaluate rotation_euler -> rotation_quaternion
    for all pose bones when frame_set is called.
    """
    action = bvh_armature.animation_data.action
    if not action:
        return {}

    fcurves = get_action_fcurves(action)
    cache = {}

    for fc in fcurves:
        dp = fc.data_path
        if '.rotation_euler' not in dp:
            continue
        # Extract bone name from data_path like pose.bones["LeftArm"].rotation_euler
        import re
        m = re.search(r'pose\.bones\["(.+?)"\]', dp)
        if not m:
            continue
        bname = m.group(1)
        if bname not in cache:
            cache[bname] = [None, None, None]
        cache[bname][fc.array_index] = fc

    return cache


def get_bvh_rotation(bvh_armature, bone_name, frame, euler_cache):
    """
    Evaluate a BVH bone's Euler rotation at a given frame and convert to quaternion.
    Uses pre-built fcurve cache for efficiency.
    """
    from mathutils import Euler
    import math as _math

    curves = euler_cache.get(bone_name)
    if not curves:
        return Euler((0, 0, 0)).to_quaternion()

    def eval_curve(curve, f):
        if curve is None:
            return 0.0
        return curve.evaluate(f)

    euler = Euler((
        eval_curve(curves[0], frame),
        eval_curve(curves[1], frame),
        eval_curve(curves[2], frame),
    ))
    return euler.to_quaternion()


# ── Core Conversion ───────────────────────────────────────────────────────────

def convert_bvh_to_vrma(bvh_path, vrm_path, output_dir, start_frame=1):
    """
    Convert a single BVH file to VRMA.
    start_frame=1 skips the CGSpeed artificial T-pose at frame 0.
    """
    bvh_name = Path(bvh_path).stem
    out_path = os.path.join(output_dir, f"{bvh_name}.vrma")

    # ── 1. Import BVH ──────────────────────────────────────────────────────
    clear_scene()
    print(f"\n[1] Importing BVH: {os.path.basename(bvh_path)}")
    bpy.ops.import_anim.bvh(filepath=bvh_path, axis_up='Z', global_scale=0.01)

    bvh_armature = get_armature()
    if not bvh_armature:
        print("ERROR: No armature imported from BVH")
        return None

    bvh_action = bvh_armature.animation_data.action
    if not bvh_action:
        print("ERROR: BVH has no animation")
        return None

    f_range = bvh_action.frame_range
    f_start = int(f_range[0])  # usually 1 (frame 0 is T-pose, skipped)
    f_end = int(f_range[1])
    total_frames = f_end - f_start + 1
    print(f"   Armature: {bvh_armature.name}  Bones: {len(bvh_armature.data.bones)}")
    print(f"   Action: '{bvh_action.name}'  Frames: {total_frames} ({f_start}–{f_end})")

    # ── 2. Import VRM ──────────────────────────────────────────────────────
    print(f"\n[2] Importing VRM: {os.path.basename(vrm_path)}")
    bpy.ops.import_scene.vrm(filepath=vrm_path)

    all_armatures = [o for o in bpy.data.objects if o.type == 'ARMATURE']
    vrm_armature = None
    for a in all_armatures:
        if a.name != bvh_armature.name:
            vrm_armature = a
            break
    if not vrm_armature:
        print("ERROR: No armature in VRM")
        return None

    vrm_armature.name = "VRM_Character"
    bvh_armature.name = "BVH_Source"
    print(f"   Armature: {vrm_armature.name}  Bones: {len(vrm_armature.data.bones)}")

    # ── 3. Read VRM humanoid bone mapping ────────────────────────────────
    print("\n[3] Reading VRM humanoid bone mapping...")
    vrm_humanoid = read_vrm_humanoid_map(vrm_armature)
    print(f"   Found {len(vrm_humanoid)} humanoid bone entries")

    # Build final bone mapping: BVH name → actual VRM bone name
    bone_map = {}
    for bvh_bone, vrm_key in BVH_BONE_MAP.items():
        if vrm_key is None:
            continue
        actual_bone = vrm_humanoid.get(vrm_key)
        if actual_bone:
            bone_map[bvh_bone] = actual_bone
        else:
            print(f"   ⚠ VRM has no bone for '{vrm_key}' (BVH '{bvh_bone}')")

    print(f"   Mapped {len(bone_map)} BVH bones to VRM bones")

    # Identify finger bones to zero out (CMU artificial data — ignore per https://mocap.cs.cmu.edu/)
    FINGER_PATTERNS = ['index', 'middle', 'ring', 'little', 'thumb']
    finger_bones = []
    for hkey, actual_name in vrm_humanoid.items():
        for pat in FINGER_PATTERNS:
            if pat in hkey.lower():
                finger_bones.append(actual_name)
                break
    if finger_bones:
        print(f"   Identified {len(finger_bones)} finger bones to zero")

    # ── 4. Align armatures ──────────────────────────────────────────────
    vrm_armature.location = bvh_armature.location
    vrm_armature.rotation_euler = bvh_armature.rotation_euler

    # ── 5. Create VRM action ──────────────────────────────────────────────
    bpy.context.view_layer.objects.active = vrm_armature
    bpy.ops.object.mode_set(mode='POSE')

    if vrm_armature.animation_data:
        vrm_armature.animation_data.action = None
    else:
        vrm_armature.animation_data_create()

    vrm_action = bpy.data.actions.new(f"BVH_{bvh_name}")
    vrm_armature.animation_data.action = vrm_action

    # ── 6. Compute rest-pose corrections ──────────────────────────────────
    print(f"\n[4] Computing rest-pose corrections...")

    hips_vrm_key = BVH_BONE_MAP.get('Hips', 'hips')
    hips_actual = vrm_humanoid.get(hips_vrm_key, 'Hips')

    rest_corrections = {}
    for bvh_bone, vrm_bone in bone_map.items():
        vrm_pb = vrm_armature.pose.bones.get(vrm_bone)
        if not vrm_pb:
            continue
        parent = vrm_pb.parent
        parent_matrix = parent.matrix if parent else Matrix()
        local_rest = parent_matrix.inverted() @ vrm_pb.matrix
        rest_corrections[vrm_bone] = local_rest.to_quaternion().inverted()

    print(f"   {len(rest_corrections)} corrections computed")

    # ── 7. Build Euler fcurve cache for BVH ──────────────────────────────
    print(f"   Building BVH Euler fcurve cache...")
    euler_cache = build_euler_fcurve_cache(bvh_armature)
    print(f"   Cached {len(euler_cache)} bones with Euler rotation curves")

    # ── 8. Frame-by-frame bake ────────────────────────────────────────────
    print(f"   Baking frames {start_frame}–{f_end}...")

    for frame in range(start_frame, f_end + 1):
        bpy.context.scene.frame_set(frame)

        for bvh_bone, vrm_bone in bone_map.items():
            vrm_pb = vrm_armature.pose.bones.get(vrm_bone)
            if not vrm_pb:
                continue

            correction = rest_corrections.get(vrm_bone)
            if correction:
                bvh_q = get_bvh_rotation(bvh_armature, bvh_bone, frame, euler_cache)
                vrm_pb.rotation_quaternion = correction @ bvh_q
                vrm_pb.keyframe_insert('rotation_quaternion', frame=frame)

                if vrm_bone == hips_actual:
                    # Evaluate Hips location from BVH fcurves too
                    try:
                        loc_path = f'pose.bones["{bvh_bone}"].location'
                        loc_fcurves = [c for c in get_action_fcurves(bvh_armature.animation_data.action)
                                       if c.data_path == loc_path]
                        if len(loc_fcurves) == 3:
                            vrm_pb.location.xyz = (
                                loc_fcurves[0].evaluate(frame),
                                loc_fcurves[1].evaluate(frame),
                                loc_fcurves[2].evaluate(frame),
                            )
                        else:
                            vrm_pb.location.xyz = (0, 0, 0)
                    except Exception:
                        vrm_pb.location.xyz = (0, 0, 0)
                    vrm_pb.keyframe_insert('location', frame=frame)

        # Zero all finger bones to identity (CMU artificial data, not real mocap)
        for fb in finger_bones:
            pb = vrm_armature.pose.bones.get(fb)
            if pb:
                pb.rotation_quaternion = Quaternion((1, 0, 0, 0))
                pb.keyframe_insert('rotation_quaternion', frame=frame)

    # Set LINEAR interpolation
    vrm_action = vrm_armature.animation_data.action
    if vrm_action:
        for fc in get_action_fcurves(vrm_action):
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'

    # ── 9. Export VRMA ────────────────────────────────────────────────────
    print(f"\n[6] Exporting VRMA: {os.path.basename(out_path)}")
    os.makedirs(output_dir, exist_ok=True)

    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    vrm_armature.select_set(True)
    for child in vrm_armature.children:
        if child.type == 'MESH':
            child.select_set(True)
    bpy.context.view_layer.objects.active = vrm_armature

    orig_fs = bpy.context.scene.frame_start
    orig_fe = bpy.context.scene.frame_end
    bpy.context.scene.frame_start = start_frame
    bpy.context.scene.frame_end = f_end

    result = None
    try:
        from bl_ext.blender_org.vrm.exporter.vrm_animation_exporter import VrmAnimationExporter
        VrmAnimationExporter.execute(bpy.context, Path(out_path), vrm_armature)
        result = out_path
        print(f"   ✓ Exported: {out_path}")
    except Exception as e:
        print(f"   ✗ Export failed: {e}")
        try:
            bpy.ops.vrm.export_vrma(filepath=out_path)
            result = out_path
            print(f"   ✓ Exported (operator): {out_path}")
        except Exception as e2:
            print(f"   ✗ Operator export also failed: {e2}")

    bpy.context.scene.frame_start = orig_fs
    bpy.context.scene.frame_end = orig_fe

    return result


# ── CLI Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    bvh_path = None
    vrm_path = None
    output_dir = None
    start_frame = 2  # skip BVH frame 0 T-pose (Blender frame 1)

    try:
        idx = sys.argv.index("--")
        args = sys.argv[idx + 1:]
    except ValueError:
        args = []

    for a in args:
        if a.startswith('--bvh='):
            bvh_path = os.path.abspath(a.split('=', 1)[1])
        elif a.startswith('--vrm='):
            vrm_path = os.path.abspath(a.split('=', 1)[1])
        elif a.startswith('--output='):
            output_dir = os.path.abspath(a.split('=', 1)[1])
        elif a.startswith('--start-frame='):
            start_frame = int(a.split('=', 1)[1])

    if not bvh_path and args and not args[0].startswith('--'):
        bvh_path = os.path.abspath(args[0])
    if not vrm_path and len(args) >= 2 and not args[1].startswith('--'):
        vrm_path = os.path.abspath(args[1])
    if not output_dir and len(args) >= 3 and not args[2].startswith('--'):
        output_dir = os.path.abspath(args[2])

    if not bvh_path or not vrm_path or not output_dir:
        print("Usage:")
        print("  blender --background --python bvh_to_vrma.py -- <bvh> <vrm> <output_dir>")
        print("  blender --background --python bvh_to_vrma.py -- --bvh=<path> --vrm=<path> --output=<dir>")
        sys.exit(1)

    if not os.path.exists(bvh_path):
        print(f"ERROR: BVH not found: {bvh_path}")
        sys.exit(1)
    if not os.path.exists(vrm_path):
        print(f"ERROR: VRM not found: {vrm_path}")
        sys.exit(1)

    result = convert_bvh_to_vrma(bvh_path, vrm_path, output_dir, start_frame)
    if result:
        print(f"\nSUCCESS: {result}")
    else:
        print("\nFAILED")
        sys.exit(1)
