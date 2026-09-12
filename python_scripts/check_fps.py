import bpy, sys
idx = sys.argv.index("--")
bvh_path = sys.argv[idx+1]
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for a in list(bpy.data.actions): bpy.data.actions.remove(a)
bpy.ops.import_anim.bvh(filepath=bvh_path, axis_up='Z', global_scale=0.01)
print(f"Scene render FPS: {bpy.context.scene.render.fps} (base: {bpy.context.scene.render.fps_base})")
print(f"Scene frames: {bpy.context.scene.frame_start}-{bpy.context.scene.frame_end}")
action = next((o for o in bpy.data.objects if o.type == 'ARMATURE')).animation_data.action
print(f"BVH action frames: {action.frame_range}")
