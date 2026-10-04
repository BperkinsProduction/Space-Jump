"""Smooth the rigged animal models for a more organic, lifelike silhouette.

Run headless:  blender -b -P blender/smooth_animals.py -- <models_in_dir> <models_out_dir>

For each GLB: import, add a Subdivision Surface modifier *before* the Armature
modifier (so the skin weights are interpolated onto the new vertices and all the
animations still work), shade smooth, make materials matte like fur, re-export
with every animation clip.
"""
import bpy, bmesh, sys, os

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
SRC, DST = argv[0], argv[1]
os.makedirs(DST, exist_ok=True)

# Cat, Bunny and Panda arrive from make_animals.py already subdivided (their markings were
# painted at that resolution), so they are only shaded here.
SUBDIV = {'Fox': 1, 'Cat': 0, 'Wolf': 1, 'Dog': 1, 'Panda': 0, 'Bunny': 0}

for name, level in SUBDIV.items():
    src = os.path.join(SRC, f'{name}.glb')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    tris_before = sum(len(o.data.polygons) for o in meshes)
    # The source models are flat-shaded, so every face arrives with its own copies of its corner
    # vertices. Weld them first — otherwise subdivision rounds each face off on its own and the
    # body turns into separate floating patches with gaps between them.
    for ob in meshes:
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        co = [v.co for v in bm.verts]
        diag = (max(c.x for c in co) - min(c.x for c in co)) ** 2 + (max(c.y for c in co) - min(c.y for c in co)) ** 2 \
             + (max(c.z for c in co) - min(c.z for c in co)) ** 2
        before = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5 * diag ** 0.5)
        print(f'WELD {name}/{ob.name}: {before} -> {len(bm.verts)} verts')
        bm.to_mesh(ob.data)
        bm.free()
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
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        for n in mat.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                n.inputs['Roughness'].default_value = 0.88
                n.inputs['Metallic'].default_value = 0.0
                # eyes stay glossy so they catch light
                if 'eye' in mat.name.lower():
                    n.inputs['Roughness'].default_value = 0.15
    # keep only the clips the game plays (idle / run / air / death) — one action each
    # (Cat, Bunny and Panda are built from the Fox / Shiba rigs by make_animals.py, so they share clips)
    KEEP = ('Idle', 'Gallop', 'Gallop_Jump', 'Death')
    chosen = {}
    for act in sorted(bpy.data.actions, key=lambda a: len(a.name)):
        base = act.name.split('|')[-1].strip()
        if base in KEEP and base not in chosen:
            chosen[base] = act
    for act in list(bpy.data.actions):
        if act not in chosen.values():
            bpy.data.actions.remove(act)
    for act in chosen.values():
        act.use_fake_user = True
    print(f'CLIPS {name}:', sorted(chosen))
    out = os.path.join(DST, f'{name}.glb')
    bpy.ops.export_scene.gltf(
        filepath=out, export_format='GLB', export_apply=True,
        export_animations=True, export_skins=True, export_yup=True,
        export_animation_mode='ACTIONS', export_optimize_animation_size=True,
        export_vertex_color='ACTIVE'   # the Cat's tabby stripes; the others have no color attribute
    )
    print(f'SMOOTHED {name}: {tris_before} faces before, subdiv {level} -> {out} ({os.path.getsize(out)//1024} KB)')
