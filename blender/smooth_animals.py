"""Smooth the rigged animal models for a more organic, lifelike silhouette.

Run headless:  blender -b -P blender/smooth_animals.py -- <models_in_dir> <models_out_dir>

For each GLB: import, add a Subdivision Surface modifier *before* the Armature
modifier (so the skin weights are interpolated onto the new vertices and all the
animations still work), shade smooth, make materials matte like fur, re-export
with every animation clip.
"""
import bpy, sys, os

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
SRC, DST = argv[0], argv[1]
os.makedirs(DST, exist_ok=True)

# Bunny is already dense (8k tris) — smooth shading only
SUBDIV = {'Fox': 1, 'Cat': 1, 'Wolf': 1, 'Dog': 1, 'Panda': 1, 'Bunny': 0}

for name, level in SUBDIV.items():
    src = os.path.join(SRC, f'{name}.glb')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    tris_before = sum(len(o.data.polygons) for o in meshes)
    for ob in meshes:
        bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        if level > 0:
            sub = ob.modifiers.new('Subdiv', 'SUBSURF')
            sub.levels = level
            sub.render_levels = level
            sub.quality = 3
            bpy.ops.object.modifier_move_to_index(modifier='Subdiv', index=0)
        bpy.ops.object.shade_smooth()
    # natural coat colors (linear RGB) where the stock palette looks toy-like
    RECOLOR = {'Bunny': {'Bunny_Main': (0.26, 0.18, 0.11)}}
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        rc = RECOLOR.get(name, {}).get(mat.name)
        if rc:
            for n in mat.node_tree.nodes:
                if n.type == 'BSDF_PRINCIPLED':
                    n.inputs['Base Color'].default_value = (*rc, 1)
        for n in mat.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                n.inputs['Roughness'].default_value = 0.88
                n.inputs['Metallic'].default_value = 0.0
                # eyes stay glossy so they catch light
                if 'eye' in mat.name.lower():
                    n.inputs['Roughness'].default_value = 0.15
    out = os.path.join(DST, f'{name}.glb')
    bpy.ops.export_scene.gltf(
        filepath=out, export_format='GLB', export_apply=True,
        export_animations=True, export_skins=True, export_yup=True,
        export_animation_mode='ACTIONS'
    )
    print(f'SMOOTHED {name}: {tris_before} faces before, subdiv {level} -> {out} ({os.path.getsize(out)//1024} KB)')
