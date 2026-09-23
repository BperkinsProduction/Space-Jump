"""Generate cloud and floating-island models with baked lighting.

Run headless:  blender -b -P blender/make_world_assets.py -- <outdir>

clouds.glb   — 8 cumulus cloud meshes (Cloud_0..7). COLOR_0 = baked sky lighting
               (bright sunlit tops, soft blue-grey undersides).
islands.glb  — 3 floating sky-island meshes (Island_0..2). Unit footprint
               (x, z in [-0.5, 0.5]), flat top at y = 0, rocky underside hanging
               down to about y = -1.3. COLOR_0: R = baked ambient occlusion,
               G = grass-lip mask used by the game's triplanar shader.
"""
import bpy, bmesh, sys, os, math, random
from mathutils import Vector, noise

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = argv[0] if argv else '/tmp/world_assets'
os.makedirs(OUT, exist_ok=True)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'METAL'
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        sc.cycles.device = 'GPU'
    except Exception as e:
        print('GPU setup failed:', e)
    sc.cycles.samples = 64
    return sc


def select_only(ob):
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def bake_to_color(ob, bake_type, attr_name):
    """Bake a lighting pass into a per-vertex color attribute."""
    me = ob.data
    if attr_name not in me.color_attributes:
        me.color_attributes.new(attr_name, 'FLOAT_COLOR', 'POINT')
    me.color_attributes.active_color = me.color_attributes[attr_name]
    sc = bpy.context.scene
    sc.render.bake.target = 'VERTEX_COLORS'
    select_only(ob)
    if bake_type == 'COMBINED':
        sc.render.bake.use_pass_direct = True
        sc.render.bake.use_pass_indirect = True
    bpy.ops.object.bake(type=bake_type)


def sky_world(sc, strength=0.9):
    w = bpy.data.worlds.new('W')
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (0.42, 0.6, 0.95, 1)
    bg.inputs['Strength'].default_value = strength


# ------------------------------------------------------------------ clouds
def make_clouds():
    sc = reset()
    sky_world(sc, 0.75)
    sun_d = bpy.data.lights.new('Sun', 'SUN')
    sun_d.energy = 4.0
    sun_d.angle = math.radians(12)
    sun = bpy.data.objects.new('Sun', sun_d)
    sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(30), math.radians(-12), 0)

    mat = bpy.data.materials.new('Cloud')
    mat.use_nodes = True
    p = mat.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (0.95, 0.96, 1.0, 1)
    p.inputs['Roughness'].default_value = 1.0
    try:
        p.inputs['Subsurface Weight'].default_value = 0.35
        p.inputs['Subsurface Radius'].default_value = (0.6, 0.6, 0.8)
    except KeyError:
        pass

    tex = bpy.data.textures.new('CloudDisp', 'CLOUDS')
    tex.noise_scale = 0.45
    tex.noise_depth = 2

    rng = random.Random(7)
    clouds = []
    for i in range(8):
        mb = bpy.data.metaballs.new(f'mb{i}')
        mb.resolution = 0.09
        mb.render_resolution = 0.09
        mb.threshold = 0.6
        # cumulus: a broad flat-ish base row, then stacked mounds on top
        length = rng.uniform(2.6, 4.2)
        nbase = rng.randint(4, 6)
        for k in range(nbase):
            e = mb.elements.new()
            t = k / (nbase - 1) - 0.5
            e.co = (t * length, rng.uniform(-0.35, 0.35), rng.uniform(-0.05, 0.1))
            e.radius = rng.uniform(0.75, 1.0)
        for k in range(rng.randint(3, 5)):
            e = mb.elements.new()
            e.co = (rng.uniform(-0.35, 0.35) * length, rng.uniform(-0.3, 0.3), rng.uniform(0.35, 0.8))
            e.radius = rng.uniform(0.6, 0.95)
        for k in range(rng.randint(1, 3)):
            e = mb.elements.new()
            e.co = (rng.uniform(-0.2, 0.2) * length, rng.uniform(-0.2, 0.2), rng.uniform(0.9, 1.25))
            e.radius = rng.uniform(0.45, 0.7)
        ob = bpy.data.objects.new(f'mbo{i}', mb)
        sc.collection.objects.link(ob)
        select_only(ob)
        bpy.ops.object.convert(target='MESH')
        ob = bpy.context.active_object
        ob.name = f'Cloud_{i}'
        # flatten the underside like real cumulus bases
        for v in ob.data.vertices:
            if v.co.z < -0.25:
                v.co.z = -0.25 + (v.co.z + 0.25) * 0.25
        # cauliflower detail
        d = ob.modifiers.new('disp', 'DISPLACE')
        d.texture = tex
        d.strength = 0.22
        d.mid_level = 0.5
        dec = ob.modifiers.new('dec', 'DECIMATE')
        dec.ratio = 0.35
        bpy.ops.object.modifier_apply(modifier='disp')
        bpy.ops.object.modifier_apply(modifier='dec')
        bpy.ops.object.shade_smooth()
        ob.data.materials.append(mat)
        ob.location = (i * 9.0, 0, 0)
        clouds.append(ob)

    for ob in clouds:
        bake_to_color(ob, 'COMBINED', 'Col')
        # The bake is linear radiance (sunlit tops exceed 1) — soft exponential tone-map
        ca = ob.data.color_attributes['Col']
        for c in ca.data:
            r, g, b, a = c.color
            c.color = (1 - math.exp(-r * 1.25), 1 - math.exp(-g * 1.25), 1 - math.exp(-b * 1.25), 1.0)
        ob.location = (0, 0, 0)
        # connect the color attribute to the material so the exporter keeps it
    nt = mat.node_tree
    ca_node = nt.nodes.new('ShaderNodeVertexColor')
    ca_node.layer_name = 'Col'
    nt.links.new(ca_node.outputs['Color'], p.inputs['Base Color'])

    select_only(clouds[0])
    for ob in clouds:
        ob.select_set(True)
    export(os.path.join(OUT, 'clouds.glb'), selected=True)


# ------------------------------------------------------------------ islands
def island_mesh(seed):
    rng = random.Random(seed)
    bm = bmesh.new()
    N = 14  # grid resolution of the flat top
    # top grid, unit footprint, z = 0
    verts = {}
    for iy in range(N + 1):
        for ix in range(N + 1):
            verts[(ix, iy)] = bm.verts.new((ix / N - 0.5, iy / N - 0.5, 0.0))
    for iy in range(N):
        for ix in range(N):
            bm.faces.new((verts[(ix, iy)], verts[(ix + 1, iy)], verts[(ix + 1, iy + 1)], verts[(ix, iy + 1)]))
    bm.normal_update()

    # boundary loop, ordered
    boundary = []
    for ix in range(N):
        boundary.append(verts[(ix, 0)])
    for iy in range(N):
        boundary.append(verts[(N, iy)])
    for ix in range(N, 0, -1):
        boundary.append(verts[(ix, N)])
    for iy in range(N, 0, -1):
        boundary.append(verts[(0, iy)])

    # rings hanging down: (z, footprint scale). First ring keeps the exact footprint
    # so the grass lip lines up with the gameplay collision box.
    rings_spec = [(-0.07, 1.0), (-0.16, 0.985), (-0.32, 0.93), (-0.52, 0.82),
                  (-0.74, 0.66), (-0.95, 0.46), (-1.12, 0.27), (-1.24, 0.12)]
    prev = boundary
    ring_levels = []
    for (z, s) in rings_spec:
        ring = []
        for v in boundary:
            x, y = v.co.x, v.co.y
            ring.append(bm.verts.new((x * s, y * s, z)))
        ring_levels.append((z, ring))
        n = len(ring)
        for k in range(n):
            a, b = prev[k], prev[(k + 1) % n]
            c, d = ring[(k + 1) % n], ring[k]
            bm.faces.new((a, d, c, b))
        prev = ring
    tip = bm.verts.new((rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), -1.34))
    n = len(prev)
    for k in range(n):
        bm.faces.new((prev[(k + 1) % n], prev[k], tip))

    # rocky irregularity on the underside only (top & lip stay exact)
    off = Vector((rng.uniform(0, 100), rng.uniform(0, 100), rng.uniform(0, 100)))
    for (z, ring) in ring_levels[1:]:
        for v in ring:
            p = v.co * 2.6 + off
            nval = noise.noise(p)
            nv2 = noise.noise(p * 2.3 + Vector((5, 5, 5)))
            radial = Vector((v.co.x, v.co.y, 0))
            if radial.length > 1e-6:
                radial.normalize()
            depth_k = min(1.0, -z / 0.4)
            v.co += radial * (nval * 0.09 + nv2 * 0.04) * depth_k
            v.co.z += nv2 * 0.05 * depth_k
    tip.co.z += rng.uniform(-0.12, 0.08)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    me = bpy.data.meshes.new(f'Island_{seed}')
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(f'Island_{seed}', me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def make_islands():
    sc = reset()
    sky_world(sc, 1.0)
    mat = bpy.data.materials.new('Island')
    mat.use_nodes = True
    p = mat.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (0.8, 0.8, 0.8, 1)
    p.inputs['Roughness'].default_value = 0.95

    obs = []
    for i in range(3):
        ob = island_mesh(11 + i * 7)
        ob.data.materials.append(mat)
        select_only(ob)
        bpy.ops.object.shade_smooth()
        try:
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(50))
        except Exception:
            pass
        ob.location = (i * 3.0, 0, 0)
        obs.append(ob)

    for ob in obs:
        bake_to_color(ob, 'AO', 'AOcol')
        ob.location = (0, 0, 0)
        # pack: R = AO, G = grass-lip mask (top rim wraps a little grass over the edge)
        ao = ob.data.color_attributes['AOcol']
        col = ob.data.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
        for i, v in enumerate(ob.data.vertices):
            a = ao.data[i].color[0]
            lip = 1.0 if v.co.z > -0.1 else max(0.0, 1.0 - (-0.1 - v.co.z) / 0.1)
            col.data[i].color = (a, lip, 0.0, 1.0)
        ob.data.color_attributes.remove(ob.data.color_attributes['AOcol'])
        ob.data.color_attributes.active_color = ob.data.color_attributes['Col']

    nt = mat.node_tree
    vc = nt.nodes.new('ShaderNodeVertexColor')
    vc.layer_name = 'Col'
    nt.links.new(vc.outputs['Color'], p.inputs['Base Color'])

    select_only(obs[0])
    for ob in obs:
        ob.select_set(True)
    export(os.path.join(OUT, 'islands.glb'), selected=True)


def export(path, selected):
    kw = dict(filepath=path, export_format='GLB', use_selection=selected,
              export_apply=True, export_yup=True, export_normals=True,
              export_materials='EXPORT')
    try:
        bpy.ops.export_scene.gltf(**kw, export_vertex_color='ACTIVE')
    except TypeError:
        bpy.ops.export_scene.gltf(**kw)
    print('EXPORTED', path, os.path.getsize(path))


make_clouds()
make_islands()
