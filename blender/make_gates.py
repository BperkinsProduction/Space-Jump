"""Ornate pearly gates of heaven — real 3D geometry for the game.

Run headless:  blender -b -P blender/make_gates.py -- <outdir> [preview.png]

gates.glb objects (glTF / three.js space: Y up, gates face +Z):
  Gate_L  – left door, origin at its hinge (x = -1.8), door spans x in [0, 1.8] locally
  Gate_R  – right door, origin at its hinge (x = +1.8), spans x in [-1.8, 0] locally
  Frame   – pearl pillars, gold capitals, the arch, cross and pearls (static)
Ground (bottom of the doors) is at y = 0. Materials: 'Gold', 'Pearl', 'PearlGlow'.
"""
import bpy, bmesh, sys, os, math
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = argv[0] if argv else '/tmp/gates'
PREVIEW = argv[1] if len(argv) > 1 else None
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

W, H = 1.8, 3.0          # door width / height
PILLAR_X = 2.05


def mat(name, color, metal, rough, emit=None, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Metallic'].default_value = metal
    p.inputs['Roughness'].default_value = rough
    try:
        p.inputs['Coat Weight'].default_value = coat
    except KeyError:
        pass
    if emit:
        p.inputs['Emission Color'].default_value = (*emit, 1)
        p.inputs['Emission Strength'].default_value = 3.0
    return m


GOLD = mat('Gold', (1.0, 0.74, 0.3), 1.0, 0.22)
PEARL = mat('Pearl', (0.93, 0.91, 0.87), 0.0, 0.28, coat=0.8)
GLOW = mat('PearlGlow', (1.0, 0.96, 0.85), 0.0, 0.2, emit=(1.0, 0.92, 0.7))


class Builder:
    """Accumulates primitives into one bmesh with per-face material indices."""
    def __init__(self, mats):
        self.bm = bmesh.new()
        self.mats = mats

    def _tag_verts(self, verts, mat_index, smooth=True):
        faces = {f for v in verts for f in v.link_faces}
        for f in faces:
            f.material_index = mat_index
            f.smooth = smooth

    def cyl(self, a, b, r, mi, seg=12):
        a, b = Vector(a), Vector(b)
        d = b - a
        L = d.length
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
        res = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=L, matrix=m)
        self._tag_verts(res['verts'], mi)

    def cone(self, base, tip, r, mi, seg=10):
        base, tip = Vector(base), Vector(tip)
        d = tip - base
        m = Matrix.Translation((base + tip) / 2) @ d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
        res = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=seg, radius1=r, radius2=0.0, depth=d.length, matrix=m)
        self._tag_verts(res['verts'], mi)

    def sphere(self, c, r, mi, seg=12):
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=seg, v_segments=max(6, seg // 2), radius=r,
                                        matrix=Matrix.Translation(Vector(c)))
        self._tag_verts(res['verts'], mi)

    def box(self, c, size, mi):
        m = Matrix.Translation(Vector(c)) @ Matrix.Diagonal((*size, 1))
        res = bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)
        self._tag_verts(res['verts'], mi, smooth=False)

    def torus(self, c, R, r, mi, axis='Y', arc=(0, math.tau), seg=40, rseg=8):
        """Torus (or arc of one) lying in the plane perpendicular to `axis`."""
        c = Vector(c)
        a0, a1 = arc
        full = abs((a1 - a0) - math.tau) < 1e-6
        n = seg if full else seg + 1
        rings = []
        for i in range(n):
            t = a0 + (a1 - a0) * i / seg
            if axis == 'Y':   # ring in XZ plane (facing the viewer)
                ctr = Vector((math.cos(t) * R, 0, math.sin(t) * R))
                u = Vector((math.cos(t), 0, math.sin(t))); v = Vector((0, 1, 0))
            else:             # ring in XY plane
                ctr = Vector((math.cos(t) * R, math.sin(t) * R, 0))
                u = Vector((math.cos(t), math.sin(t), 0)); v = Vector((0, 0, 1))
            ring = [self.bm.verts.new(c + ctr + (u * math.cos(k * math.tau / rseg) + v * math.sin(k * math.tau / rseg)) * r)
                    for k in range(rseg)]
            rings.append(ring)
        segs = n if full else n - 1
        for i in range(segs):
            r0, r1 = rings[i], rings[(i + 1) % n]
            for k in range(rseg):
                f = self.bm.faces.new((r0[k], r0[(k + 1) % rseg], r1[(k + 1) % rseg], r1[k]))
                f.material_index = mi
                f.smooth = True

    def to_object(self, name):
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        ob = bpy.data.objects.new(name, me)
        sc.collection.objects.link(ob)
        return ob


G, P, L = 0, 1, 2   # material indices: gold, pearl, glow


def build_door():
    """Door in Blender XZ plane, hinge at x = 0, spanning x in [0, W]."""
    b = Builder([GOLD, PEARL, GLOW])
    r_frame, r_bar = 0.045, 0.022
    # frame: stiles + rails
    b.cyl((0.04, 0, 0.04), (0.04, 0, H), r_frame, G)
    b.cyl((W - 0.04, 0, 0.04), (W - 0.04, 0, H - 0.25), r_frame, G)
    for z in (0.08, 1.05, 1.55, H - 0.9):
        b.cyl((0.04, 0, z), (W - 0.04, 0, z), r_frame * 0.85, G)
    # vertical bars with spear-tip finials rising in a gentle arc toward the hinge side
    nbars = 8
    for i in range(1, nbars + 1):
        x = W * i / (nbars + 1)
        top = H - 0.25 + 0.35 * math.sin(math.pi * (1 - x / W) * 0.5)
        b.cyl((x, 0, 0.08), (x, 0, top), r_bar, G)
        b.cone((x, 0, top), (x, 0, top + 0.16), 0.045, G)
        b.sphere((x, 0, top - 0.02), 0.035, G, seg=8)
    # scrollwork: rings between the bars in two decorative bands
    for i in range(nbars + 1):
        x = W * (i + 0.5) / (nbars + 1)
        b.torus((x, 0, 1.30), 0.085, 0.012, G, seg=24, rseg=6)
        b.torus((x, 0, 0.55), 0.07, 0.011, G, seg=24, rseg=6)
        # S-curl pairs in the upper band
        b.torus((x, 0, H - 0.75), 0.06, 0.01, G, arc=(0, math.pi), seg=14, rseg=6)
        b.torus((x, 0, H - 0.63), 0.06, 0.01, G, arc=(math.pi, math.tau), seg=14, rseg=6)
    # pearls — the "pearly" gates: studs along the rails
    for z in (1.05, 1.55):
        for i in range(nbars + 2):
            b.sphere((W * i / (nbars + 1), -0.02, z), 0.045, P, seg=12)
    # medallion with a cross near the meeting edge
    mx, mz = W - 0.45, 2.05
    b.torus((mx, 0, mz), 0.3, 0.03, G, seg=48, rseg=8)
    b.torus((mx, 0, mz), 0.22, 0.012, G, seg=40, rseg=6)
    b.cyl((mx, 0, mz - 0.2), (mx, 0, mz + 0.2), 0.022, G)
    b.cyl((mx - 0.13, 0, mz + 0.06), (mx + 0.13, 0, mz + 0.06), 0.022, G)
    b.sphere((mx, -0.03, mz + 0.06), 0.05, L, seg=12)
    return b


def build_frame():
    b = Builder([GOLD, PEARL, GLOW])
    for sx in (-1, 1):
        x = sx * PILLAR_X
        b.box((x, 0, 0.12), (0.62, 0.62, 0.24), P)         # plinth
        b.torus((x, 0, 0.3), 0.21, 0.05, G, axis='Z', seg=28)
        b.cyl((x, 0, 0.26), (x, 0, 3.7), 0.18, P, seg=28)   # shaft
        for z in (0.9, 2.2, 3.35):
            b.torus((x, 0, z), 0.19, 0.03, G, axis='Z', seg=28)
        b.torus((x, 0, 3.72), 0.2, 0.05, G, axis='Z', seg=28)  # capital
        b.box((x, 0, 3.86), (0.56, 0.56, 0.14), G)
        b.sphere((x, 0, 4.15), 0.17, L, seg=20)              # glowing orb finial
        for k in range(8):                                   # pearl ring round the capital
            a = k * math.tau / 8
            b.sphere((x + math.cos(a) * 0.3, math.sin(a) * 0.3, 3.95), 0.05, P, seg=10)
    # arch spanning the pillars
    R = PILLAR_X
    b.torus((0, 0, 3.9), R, 0.07, G, arc=(0, math.pi), seg=64, rseg=10)
    b.torus((0, 0, 3.9), R - 0.2, 0.035, G, arc=(0, math.pi), seg=64, rseg=8)
    # sunburst spokes between the two arch lines
    for k in range(1, 16):
        a = math.pi * k / 16
        p0 = Vector((math.cos(a) * (R - 0.2), 0, 3.9 + math.sin(a) * (R - 0.2)))
        p1 = Vector((math.cos(a) * R, 0, 3.9 + math.sin(a) * R))
        b.cyl(p0, p1, 0.014, G, seg=6)
    for k in range(0, 17):
        a = math.pi * k / 16
        b.sphere((math.cos(a) * (R + 0.1), -0.02, 3.9 + math.sin(a) * (R + 0.1)), 0.05, P, seg=10)
    # cross at the apex
    top = 3.9 + R
    b.cyl((0, 0, top), (0, 0, top + 0.75), 0.05, G)
    b.cyl((-0.25, 0, top + 0.5), (0.25, 0, top + 0.5), 0.05, G)
    b.sphere((0, -0.02, top + 0.5), 0.07, L, seg=12)
    return b


door = build_door()
gl = door.to_object('Gate_L')
gl.location = (-W, 0, 0)
# right door = mirrored copy (x in [-W, 0]) with its own hinge at +W
door2 = build_door()
for v in door2.bm.verts:
    v.co.x = -v.co.x
for f in door2.bm.faces:
    f.normal_flip()
gr = door2.to_object('Gate_R')
gr.location = (W, 0, 0)
frame = build_frame().to_object('Frame')

if PREVIEW:
    sc.render.engine = 'CYCLES'
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'METAL'; prefs.get_devices()
        for d in prefs.devices: d.use = True
        sc.cycles.device = 'GPU'
    except Exception:
        pass
    sc.cycles.samples = 48
    sc.render.resolution_x, sc.render.resolution_y = 900, 900
    world = bpy.data.worlds.new('W'); sc.world = world; world.use_nodes = True
    sky = world.node_tree.nodes.new('ShaderNodeTexSky'); sky.sky_type = 'NISHITA'; sky.sun_elevation = math.radians(30)
    world.node_tree.links.new(sky.outputs['Color'], world.node_tree.nodes['Background'].inputs['Color'])
    cam_d = bpy.data.cameras.new('C'); cam = bpy.data.objects.new('C', cam_d); sc.collection.objects.link(cam)
    cam.location = (0, -11, 3.2); cam.rotation_euler = (math.radians(88), 0, 0); sc.camera = cam
    gl.rotation_euler = (0, 0, math.radians(-35)); gr.rotation_euler = (0, 0, math.radians(35))
    sc.view_settings.view_transform = 'AgX'
    sc.render.filepath = PREVIEW
    bpy.ops.render.render(write_still=True)
    gl.rotation_euler = (0, 0, 0); gr.rotation_euler = (0, 0, 0)

bpy.ops.object.select_all(action='DESELECT')
for ob in (gl, gr, frame):
    ob.select_set(True)
out = os.path.join(OUT, 'gates.glb')
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', use_selection=True, export_apply=True, export_yup=True)
for ob in (gl, gr, frame):
    print(ob.name, len(ob.data.polygons), 'faces')
print('EXPORTED', out, os.path.getsize(out))
