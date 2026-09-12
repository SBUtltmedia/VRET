import bpy

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

bpy.ops.import_scene.vrm(filepath='models/Seed-san.vrm')

for o in bpy.data.objects:
    if o.type == 'ARMATURE':
        arm = o
        break

ext = arm.data.vrm_addon_extension
hb = ext.vrm1.humanoid.human_bones

# Show all attributes of hb
keys_found = []
for attr_name in dir(hb):
    if attr_name.startswith('_'):
        continue
    entry = getattr(hb, attr_name, None)
    if entry is None:
        continue
    try:
        node = entry.node
        if node and node.bone_name:
            keys_found.append((attr_name, node.bone_name))
    except:
        pass

print(f"Found {len(keys_found)} humanoid bone mappings:")
for attr_name, bone_name in sorted(keys_found):
    print(f"  {attr_name:30s} -> {bone_name}")

print("\n--- All dir attributes of hb ---")
for a in dir(hb):
    if not a.startswith('_'):
        e = getattr(hb, a, None)
        print(f"  {a}: {type(e).__name__}")
