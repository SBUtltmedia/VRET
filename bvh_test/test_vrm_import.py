import bpy

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

print('Importing VRM...')
bpy.ops.import_scene.vrm(filepath='models/Seed-san.vrm')
print('VRM imported')

for o in bpy.data.objects:
    if o.type == 'ARMATURE':
        print(f'Armature: {o.name}, bones: {len(o.data.bones)}')
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode='POSE')
        print(f'  Pose bones: {len(o.pose.bones)}')
        for pb in o.pose.bones:
            print(f'    {pb.name}')
        bpy.ops.object.mode_set(mode='OBJECT')
print('Done')
