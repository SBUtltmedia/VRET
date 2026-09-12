import bpy
import os

"""
recompose_expressions.py

A Blender script to fix distorted ARKit shapes and create VRM presets 
(Happy, Sad, Angry, etc.) by mixing existing blendshapes.
"""

def get_main_mesh():
    # Priority for meshes with many shape keys (usually the face)
    mesh_objs = [obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.data.shape_keys]
    if not mesh_objs:
        return None
    return max(mesh_objs, key=lambda obj: len(obj.data.shape_keys.key_blocks))

def clear_influences(obj):
    for sk in obj.data.shape_keys.key_blocks:
        sk.value = 0.0

def create_shape_from_mix(obj, new_name, mix_recipe):
    """
    mix_recipe: dict of {shape_name: weight}
    """
    clear_influences(obj)
    
    found_any = False
    for name, weight in mix_recipe.items():
        if name in obj.data.shape_keys.key_blocks:
            obj.data.shape_keys.key_blocks[name].value = weight
            found_any = True
        else:
            print(f"  [Warning] Shape '{name}' not found for mix '{new_name}'")
            
    if not found_any:
        return None

    # Remove existing if it exists
    if new_name in obj.data.shape_keys.key_blocks:
        idx = obj.data.shape_keys.key_blocks.find(new_name)
        obj.active_shape_key_index = idx
        bpy.ops.object.shape_key_remove(all=False)

    # Create the mix
    obj.shape_key_add(name=new_name, from_mix=True)
    print(f"  [Success] Created '{new_name}'")
    
    # Reset
    clear_influences(obj)
    return obj.data.shape_keys.key_blocks[new_name]

def process_vrm():
    obj = get_main_mesh()
    if not obj:
        print("No mesh with shape keys found.")
        return

    print(f"Processing mesh: {obj.name}")

    # --- 1. Fix mouthFunnel (it's often too open) ---
    # We mix the original funnel with mouthPucker and mouthClose to "tighten" the O
    create_shape_from_mix(obj, "mouthFunnel_FIXED", {
        "mouthFunnel": 0.6,
        "mouthPucker": 0.6,
        "mouthRollLower": 0.3,
        "mouthRollUpper": 0.3,
        "mouthClose": 0.1
    })

    # --- 2. Create VRM Presets from ARKit ---
    # HAPPY
    create_shape_from_mix(obj, "happy", {
        "mouthSmileLeft": 1.0,
        "mouthSmileRight": 1.0,
        "eyeSquintLeft": 0.5,
        "eyeSquintRight": 0.5,
        "cheekPuff": 0.2
    })

    # SAD
    create_shape_from_mix(obj, "sad", {
        "mouthFrownLeft": 0.8,
        "mouthFrownRight": 0.8,
        "browDownLeft": 0.6,
        "browDownRight": 0.6,
        "eyeSquintLeft": 0.2,
        "eyeSquintRight": 0.2
    })

    # ANGRY
    create_shape_from_mix(obj, "angry", {
        "browDownLeft": 1.0,
        "browDownRight": 1.0,
        "eyeSquintLeft": 1.0,
        "eyeSquintRight": 1.0,
        "noseSneerLeft": 0.8,
        "noseSneerRight": 0.8,
        "mouthPressLeft": 0.4,
        "mouthPressRight": 0.4
    })

    # SURPRISED
    create_shape_from_mix(obj, "surprised", {
        "eyeWideLeft": 1.0,
        "eyeWideRight": 1.0,
        "jawOpen": 0.4,
        "browOuterUpLeft": 0.8,
        "browOuterUpRight": 0.8
    })

    # RELAXED
    create_shape_from_mix(obj, "relaxed", {
        "eyeSquintLeft": 0.3,
        "eyeSquintRight": 0.3,
        "mouthSmileLeft": 0.1,
        "mouthSmileRight": 0.1
    })

    print("Recomposition complete.")

if __name__ == "__main__":
    process_vrm()
