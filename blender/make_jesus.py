"""Render a realistic figure of Jesus for the heaven scene.

Run headless:
  blender -b -P blender/make_jesus.py -- <human_base_meshes_bundle.blend> <out.png> [stage] [res]

Body: Blender Studio "Human Base Meshes" (CC0), realistic male, with its multires
sculpt detail applied. Arms are brought gently forward into a welcoming pose.
Robe + mantle: cloth-simulated over the body. Hair + beard: particle hair with
hair dynamics (gravity + collision). Rendered in Cycles with a transparent
background so the game can show it as a sprite in front of heaven's glow.

stage: 'body' | 'robe' | 'full' (default full) — for iterating on previews.
"""
import bpy, bmesh, sys, os, math
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
BUNDLE, OUT = argv[0], argv[1]
STAGE = argv[2] if len(argv) > 2 else 'full'
RES = int(argv[3]) if len(argv) > 3 else 1400

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene


def select_only(ob):
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def principled(name, color, rough, **kw):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = rough
    for k, v in kw.items():
        try:
            p.inputs[k].default_value = v
        except KeyError:
            print('no input', k)
    return m, p


# ---------------------------------------------------------------- body
with bpy.data.libraries.load(BUNDLE, link=False) as (src, dst):
    dst.objects = [n for n in src.objects if n in ('GEO-body_male_realistic',
                                                   'GEO-body_male_realistic.eye.L',
                                                   'GEO-body_male_realistic.eye.R')]
objs = {o.name: o for o in dst.objects if o}
body = objs['GEO-body_male_realistic']
eyes = [objs[n] for n in ('GEO-body_male_realistic.eye.L', 'GEO-body_male_realistic.eye.R') if n in objs]
for o in [body] + eyes:
    sc.collection.objects.link(o)

# bake the multires sculpt detail into the mesh
select_only(body)
for m in list(body.modifiers):
    if m.type == 'MULTIRES':
        m.levels = min(1, m.total_levels)
        m.render_levels = m.levels
        bpy.ops.object.modifier_apply(modifier=m.name)
    else:
        bpy.ops.object.modifier_apply(modifier=m.name)
bpy.ops.object.shade_smooth()
# the bundle lays its assets out on a grid — center this one at the origin, feet on z=0
bb = [body.matrix_world @ Vector(c) for c in body.bound_box]
cx = sum(v.x for v in bb) / 8; cy = sum(v.y for v in bb) / 8; z0 = min(v.z for v in bb)
body.location -= Vector((cx, cy, z0))
bpy.context.view_layer.update()
print('ORIGIN SHIFT', round(cx, 3), round(cy, 3), round(z0, 3), 'rot', tuple(round(a, 2) for a in body.rotation_euler))
bb = [body.matrix_world @ Vector(c) for c in body.bound_box]
zmin = min(v.z for v in bb); zmax = max(v.z for v in bb)
HEIGHT = zmax - zmin
print('BODY verts', len(body.data.vertices), 'height', round(HEIGHT, 3), 'zmin', round(zmin, 3))

# welcoming pose: rotate each arm forward (toward -Y, the camera) around the shoulder
def pose_arm(side):
    sx = 1 if side == 'L' else -1
    me = body.data
    shoulder = Vector((sx * 0.17, 0.0, zmin + HEIGHT * 0.815))
    ang = math.radians(18)
    rot = Matrix.Rotation(-ang * sx * 0, 4, 'Z') @ Matrix.Rotation(ang, 4, 'X')
    for v in me.vertices:
        co = body.matrix_world @ v.co
        d = (co.x - shoulder.x) * sx
        if d <= 0:
            continue
        w = min(1.0, d / 0.12)           # smooth blend across the shoulder
        rel = co - shoulder
        rotated = (Matrix.Rotation(-ang * w, 3, 'X') @ rel) + shoulder
        v.co = body.matrix_world.inverted() @ rotated
pose_arm('L'); pose_arm('R')

skin, skin_p = principled('Skin', (0.48, 0.27, 0.16), 0.45,
                          **{'Subsurface Weight': 0.25, 'Subsurface Radius': (1.0, 0.35, 0.2), 'Subsurface Scale': 0.02})
body.data.materials.clear(); body.data.materials.append(skin)
eye_m, _ = principled('Eye', (0.05, 0.03, 0.02), 0.08)
for e in eyes:
    e.data.materials.clear(); e.data.materials.append(eye_m)


# ---------------------------------------------------------------- scene / lights / camera
def setup_render():
    sc.render.engine = 'CYCLES'
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'METAL'; prefs.get_devices()
        for d in prefs.devices: d.use = True
        sc.cycles.device = 'GPU'
    except Exception as e:
        print('gpu', e)
    sc.cycles.samples = 64 if RES < 1000 else 192
    sc.cycles.use_denoising = True
    sc.render.film_transparent = True
    sc.render.resolution_x = int(RES * 0.72)
    sc.render.resolution_y = RES
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.exposure = -0.7
    world = bpy.data.worlds.new('W'); sc.world = world; world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (1.0, 0.93, 0.8, 1)
    bg.inputs['Strength'].default_value = 0.55

    def area(name, loc, target, size, energy, color):
        d = bpy.data.lights.new(name, 'AREA'); d.size = size; d.energy = energy; d.color = color
        o = bpy.data.objects.new(name, d); sc.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
        return o
    mid = zmin + HEIGHT * 0.6
    area('Key', (-1.4, -3.0, mid + 1.6), (0, 0, mid), 2.5, 480, (1.0, 0.95, 0.88))
    area('Fill', (2.2, -2.6, mid + 0.4), (0, 0, mid), 3.0, 220, (0.9, 0.93, 1.0))
    area('RimL', (-1.3, 1.9, mid + 1.2), (0, 0, mid), 1.5, 600, (1.0, 0.9, 0.7))
    area('RimR', (1.3, 1.9, mid + 1.2), (0, 0, mid), 1.5, 600, (1.0, 0.9, 0.7))
    area('Crown', (0, 0.4, zmax + 1.4), (0, 0, zmax), 1.2, 300, (1.0, 0.92, 0.75))

    cd = bpy.data.cameras.new('Cam'); cd.lens = 70
    cam = bpy.data.objects.new('Cam', cd); sc.collection.objects.link(cam)
    cam.location = (0, -5.6, zmin + HEIGHT * 0.45)
    look = Vector((0, 0, zmin + HEIGHT * 0.53))
    cam.rotation_euler = (look - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = cam


setup_render()
sc.render.filepath = OUT
if STAGE == 'body':
    bpy.ops.render.render(write_still=True)
    print('RENDERED', OUT)
    sys.exit(0)


# ---------------------------------------------------------------- landmarks
def world_verts():
    mw = body.matrix_world
    return [mw @ v.co for v in body.data.vertices]
WV = world_verts()

def slice_centroid(cond):
    pts = [p for p in WV if cond(p)]
    return sum(pts, Vector()) / max(1, len(pts)), len(pts)

arm = {}
for side, sx in (('L', 1), ('R', -1)):
    elbow, _ = slice_centroid(lambda p: 0.285 < p.x * sx < 0.305 and p.z > 0.8)
    wrist, _ = slice_centroid(lambda p: 0.355 < p.x * sx < 0.37 and p.z > 0.6)
    arm[side] = (elbow, wrist)
    print('ARM', side, tuple(round(c, 3) for c in elbow), tuple(round(c, 3) for c in wrist))

# ---------------------------------------------------------------- cloth helpers
def add_collision(ob, dist=0.006):
    ob.modifiers.new('Collision', 'COLLISION')
    ob.collision.thickness_outer = dist
    ob.collision.cloth_friction = 5.0

def cloth(ob, pin_group, mass=0.25, stiff=15.0, bend=0.6, q=8):
    m = ob.modifiers.new('Cloth', 'CLOTH')
    cs = m.settings
    cs.mass = mass
    cs.quality = q
    cs.tension_stiffness = stiff; cs.compression_stiffness = stiff
    cs.shear_stiffness = stiff * 0.5
    cs.bending_stiffness = bend
    cs.air_damping = 1.5
    cs.vertex_group_mass = pin_group
    m.collision_settings.distance_min = 0.006
    m.collision_settings.use_self_collision = False
    return m

def grid_mesh(name, rows, cols, fn, pin_rows=1):
    """Build a quad grid; fn(r, c) -> world position. Top `pin_rows` rows pinned."""
    bm = bmesh.new()
    vs = [[bm.verts.new(fn(r, c)) for c in range(cols)] for r in range(rows)]
    closed = (fn(0, 0) - fn(0, cols - 1)).length < 1e-4
    cc = cols - 1 if closed else cols - 1
    for r in range(rows - 1):
        for c in range(cc):
            bm.faces.new((vs[r][c], vs[r][c + 1], vs[r + 1][c + 1], vs[r + 1][c]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
    vg = ob.vertex_groups.new(name='pin')
    vg.add([r * cols + c for r in range(pin_rows) for c in range(cols)], 1.0, 'REPLACE')
    return ob

def tube(name, top, bot, r_top, r_bot, rows, segs, pin_rows=2, wobble=0.0):
    """Open tube from `top` to `bot` (world points), elliptical radius tuples."""
    axis = (bot - top)
    L = axis.length; axis.normalize()
    ref = Vector((0, 1, 0)) if abs(axis.y) < 0.9 else Vector((1, 0, 0))
    u = axis.cross(ref).normalized(); v = axis.cross(u).normalized()
    import random
    rnd = random.Random(len(name))
    phase = [rnd.uniform(0, 6.28) for _ in range(4)]
    def fn(r, c):
        t = r / (rows - 1)
        a = c / segs * math.tau
        rx = r_top[0] + (r_bot[0] - r_top[0]) * t
        ry = r_top[1] + (r_bot[1] - r_top[1]) * t
        w = 1 + wobble * t * (math.sin(a * 3 + phase[0]) * 0.5 + math.sin(a * 7 + phase[1]) * 0.5)
        return top + axis * (L * t) + (u * math.cos(a) * rx + v * math.sin(a) * ry) * w
    bm = bmesh.new()
    vs = [[bm.verts.new(fn(r, c)) for c in range(segs)] for r in range(rows)]
    for r in range(rows - 1):
        for c in range(segs):
            bm.faces.new((vs[r][c], vs[r][(c + 1) % segs], vs[r + 1][(c + 1) % segs], vs[r + 1][c]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
    vg = ob.vertex_groups.new(name='pin')
    vg.add([r * segs + c for r in range(pin_rows) for c in range(segs)], 1.0, 'REPLACE')
    return ob

# ---------------------------------------------------------------- garments
# 1) fitted tunic shell: body torso + arms (no hands/neck/head), pushed outward
bm = bmesh.new(); bm.from_mesh(body.data); bm.transform(body.matrix_world)
kill = [v for v in bm.verts if not (0.9 <= v.co.z <= 1.46 and abs(v.co.x) <= 0.36)]
bmesh.ops.delete(bm, geom=kill, context='VERTS')
bm.normal_update()
for v in bm.verts:
    v.co += v.normal * 0.026
for _ in range(30):
    bmesh.ops.smooth_vert(bm, verts=bm.verts[:], factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
me = bpy.data.meshes.new('Tunic'); bm.to_mesh(me); bm.free()
tunic = bpy.data.objects.new('Tunic', me); sc.collection.objects.link(tunic)
select_only(tunic); bpy.ops.object.shade_smooth()

add_collision(body)
floor_d = bpy.data.meshes.new('Floor')
fbm = bmesh.new(); bmesh.ops.create_grid(fbm, x_segments=1, y_segments=1, size=2.0); fbm.to_mesh(floor_d); fbm.free()
floor = bpy.data.objects.new('Floor', floor_d); sc.collection.objects.link(floor)
floor.location.z = -0.005
add_collision(floor, 0.004)

# 2) skirt: waist -> floor, cut long and wide so the slack settles into folds
skirt = tube('Skirt', Vector((0, 0.01, 1.04)), Vector((0, 0.01, -0.08)), (0.21, 0.16), (0.56, 0.5),
             rows=50, segs=110, pin_rows=2, wobble=0.28)
cloth(skirt, 'pin', mass=0.3, stiff=12, bend=0.4)

# 3) bell sleeves from the elbows past the wrists
sleeves = []
for side in ('L', 'R'):
    e, w = arm[side]
    d = (w - e).normalized()
    sl = tube('Sleeve' + side, e - d * 0.03, w + d * 0.11, (0.068, 0.068), (0.15, 0.15),
              rows=18, segs=40, pin_rows=2, wobble=0.1)
    cloth(sl, 'pin', mass=0.15, stiff=10, bend=0.3)
    sleeves.append(sl)

# 4) mantle: pinned in a U around the back of the neck, hanging to calf length
def mantle_fn(r, c, rows=48, cols=44):
    t = c / (cols - 1) * 2 - 1              # -1 (left front) .. 1 (right front)
    ang = t * math.radians(142)
    top = Vector((math.sin(ang) * 0.215, math.cos(ang) * 0.135 + 0.01, 1.435 - abs(t) * 0.03))
    drop = r / (rows - 1) * 1.05
    spread = 1 + (r / (rows - 1)) * 0.75
    return Vector((top.x * spread, top.y * spread + 0.03 * (r / (rows - 1)), top.z - drop))
mantle = grid_mesh('Mantle', 48, 44, mantle_fn, pin_rows=2)
cloth(mantle, 'pin', mass=0.35, stiff=18, bend=1.2)

garments = [skirt, mantle] + sleeves
sc.frame_start = 1; sc.frame_end = 60
for f in range(1, 61):
    sc.frame_set(f)
print('CLOTH SIM DONE')
for g in garments:
    select_only(g)
    bpy.ops.object.modifier_apply(modifier='Cloth')
    if g.name == 'Mantle':
        g.data.update()
        for v in g.data.vertices:
            v.co += v.normal * 0.018      # sit clearly on top of the tunic
    sol = g.modifiers.new('Thick', 'SOLIDIFY'); sol.thickness = 0.006
    sub = g.modifiers.new('Smooth', 'SUBSURF'); sub.levels = 1; sub.render_levels = 1
    bpy.ops.object.shade_smooth()

robe_m, _ = principled('Robe', (0.74, 0.7, 0.62), 0.8, **{'Sheen Weight': 0.6, 'Sheen Roughness': 0.4,
                                                              'Subsurface Weight': 0.08})
red_m, _ = principled('Mantle', (0.3, 0.018, 0.02), 0.72, **{'Sheen Weight': 0.8, 'Sheen Roughness': 0.35})
for g in (tunic, skirt) + tuple(sleeves):
    g.data.materials.clear(); g.data.materials.append(robe_m)
mantle.data.materials.clear(); mantle.data.materials.append(red_m)
floor.hide_render = True

if STAGE == 'robe':
    bpy.ops.render.render(write_still=True)
    print('RENDERED', OUT)
    sys.exit(0)


# ---------------------------------------------------------------- belt, halo
def ring(name, c, rx, ry, r, segs=64, rseg=10):
    bm = bmesh.new()
    rings = []
    for i in range(segs):
        a = i / segs * math.tau
        ctr = Vector((math.cos(a) * rx, math.sin(a) * ry, 0)) + c
        rad = Vector((math.cos(a), math.sin(a), 0))
        rings.append([bm.verts.new(ctr + (rad * math.cos(k / rseg * math.tau) + Vector((0, 0, 1)) * math.sin(k / rseg * math.tau)) * r) for k in range(rseg)])
    for i in range(segs):
        a0, a1 = rings[i], rings[(i + 1) % segs]
        for k in range(rseg):
            bm.faces.new((a0[k], a0[(k + 1) % rseg], a1[(k + 1) % rseg], a1[k]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
    select_only(ob); bpy.ops.object.shade_smooth()
    return ob

gold_m, _ = principled('Gold', (1.0, 0.72, 0.3), 0.3, **{'Metallic': 1.0})
belt = ring('Belt', Vector((0, 0.012, 1.02)), 0.225, 0.172, 0.013)
belt.data.materials.append(gold_m)
# hanging cord ends
for dx in (-0.03, 0.03):
    cord = tube('Cord', Vector((dx, -0.17, 1.02)), Vector((dx * 1.6, -0.19, 0.72)), (0.008, 0.008), (0.007, 0.007), rows=6, segs=10, pin_rows=0)
    cord.data.materials.append(gold_m)

head_pts = [p for p in WV if p.z > 1.52]
HC = sum(head_pts, Vector()) / len(head_pts)
halo_m = bpy.data.materials.new('Halo'); halo_m.use_nodes = True
nt = halo_m.node_tree; nt.nodes.clear()
em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (1.0, 0.78, 0.35, 1); em.inputs['Strength'].default_value = 6.0
o = nt.nodes.new('ShaderNodeOutputMaterial'); nt.links.new(em.outputs['Emission'], o.inputs['Surface'])
halo = ring('Halo', Vector((0, 0, 0)), 0.2, 0.2, 0.009, segs=96, rseg=8)
halo.rotation_euler = (math.radians(90), 0, 0)
halo.location = (0, HC.y + 0.13, HC.z + 0.05)
halo.data.materials.append(halo_m)

# ---------------------------------------------------------------- hair & beard (procedural strands)
import random
rnd = random.Random(12)
head_pts = [p for p in WV if p.z > 1.55]
hx = [p.x for p in head_pts]; hy = [p.y for p in head_pts]; hz = [p.z for p in head_pts]
C = Vector(((max(hx) + min(hx)) / 2, (max(hy) + min(hy)) / 2, 0))
R = Vector(((max(hx) - min(hx)) / 2, (max(hy) - min(hy)) / 2, 0))
C.z = max(hz) - 0.115
R.z = 0.125
print('HEAD center', tuple(round(c, 3) for c in C), 'radii', tuple(round(c, 3) for c in R))

def on_ellipsoid(p, off):
    d = p - C
    k = math.sqrt((d.x / R.x) ** 2 + (d.y / R.y) ** 2 + (d.z / R.z) ** 2)
    return C + d / k * (1 + off)

def ell_normal(p):
    d = p - C
    return Vector((d.x / R.x ** 2, d.y / R.y ** 2, d.z / R.z ** 2)).normalized()

def scalp_root():
    # sample the upper/back ellipsoid, hairline above the forehead
    while True:
        th = rnd.uniform(0, math.tau); ph = math.acos(rnd.uniform(-0.6, 0.97))
        d = Vector((math.sin(ph) * math.cos(th), math.sin(ph) * math.sin(th), math.cos(ph)))
        p = C + Vector((d.x * R.x, d.y * R.y, d.z * R.z))
        if d.y < -0.35 and d.z < 0.55:        # forehead / face — no hair
            continue
        if d.y < 0.1 and d.z < 0.05:          # temples in front of the ears
            continue
        return p

def strand_path(root, length, off, n=18):
    pts = [root.copy()]
    p = on_ellipsoid(root, off)
    side = 1 if root.x >= 0 else -1
    ds = length / (n - 1)
    free = False
    dirv = Vector((0, 0, -1))
    for i in range(1, n):
        if not free:
            nrm = ell_normal(p)
            down = Vector((0, 0, -1)) - nrm * nrm.dot(Vector((0, 0, -1)))
            # part in the middle: sweep toward each side, and toward the back near the face
            sweep = Vector((side * 0.9, 0.35 if p.y < C.y else 0.1, 0))
            sweep -= nrm * nrm.dot(sweep)
            w = max(0.0, (p.z - (C.z - 0.03)) / R.z)   # stronger sweep near the crown
            dirv = (down * (1.0 - 0.6 * w) + sweep * (0.25 + 0.9 * w))
            if dirv.length < 1e-5:
                dirv = Vector((side, 0, -1))
            dirv.normalize()
            q = on_ellipsoid(p + dirv * ds, off)
            if q.z < C.z - 0.55 * R.z or (q - p).length > ds * 2.5:
                free = True
            p = q
        else:
            spread = Vector((side * 0.4, 0, 0)) if abs(p.x) < 0.17 else Vector()
            dirv = (dirv * 0.35 + Vector((0, 0, -1)) + spread).normalized()
            p = p + dirv * ds
            # long hair lies down the front of the chest or down the back — never through the body
            if p.z < 1.47 and abs(p.x) < 0.25:
                half_depth = 0.135 + max(0.0, 0.25 - abs(p.x)) * 0.12
                front = p.y < -0.02
                if abs(p.y) < half_depth:
                    jitter = rnd.uniform(0.0, 0.03)
                    p = Vector((p.x, -(half_depth + jitter) if front else (half_depth + jitter), p.z))
        pts.append(p.copy())
    return pts

def perp(v):
    a = Vector((1, 0, 0)) if abs(v.x) < 0.9 else Vector((0, 1, 0))
    return v.cross(a).normalized()

strands = []    # list of (points, root_radius)
GUIDES, CHILD = 1100, 12
for g in range(GUIDES):
    root = scalp_root()
    L = rnd.uniform(0.36, 0.46) if root.y < C.y + 0.03 else rnd.uniform(0.4, 0.52)
    off = rnd.uniform(0.01, 0.05)
    guide = strand_path(root, L, off)
    phase = rnd.uniform(0, 6.28)
    for c in range(CHILD):
        jit = Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), rnd.gauss(0, 1))) * 0.017
        pts = []
        for i, q in enumerate(guide):
            t = i / (len(guide) - 1)
            clump = 1.0 - 0.75 * t                        # children gather toward the tips
            wave = perp(Vector((0, 0, 1))) * math.sin(t * 9 + phase + c) * 0.004 * t
            pts.append(q + jit * clump * (0.2 + t) + wave)
        pts[0] = guide[0] + jit * 0.3
        strands.append((pts, 0.00045))

# beard + moustache: short strands from the jaw, curving downward
beard_ids = []
for i, p_ in enumerate(WV):
    rel = p_ - C
    jaw = 1.462 < p_.z < 1.535 and rel.y < -0.02                      # chin, jawline, lower cheeks
    lip = 1.536 < p_.z < 1.55 and abs(rel.x) < 0.032 and rel.y < -0.07  # moustache band
    mouth = 1.522 < p_.z < 1.537 and abs(rel.x) < 0.02 and rel.y < -0.085
    if (jaw or lip) and not mouth:
        beard_ids.append(i)
print('BEARD verts', len(beard_ids))
for i in beard_ids[::2]:
    root = WV[i]
    nrm = (body.matrix_world.to_3x3() @ body.data.vertices[i].normal).normalized()
    rel = root - C
    L = rnd.uniform(0.045, 0.075) if root.z > 1.49 else rnd.uniform(0.07, 0.1)
    if root.z > 1.536:
        L = 0.024                                        # moustache
    pts = []
    p = root.copy(); d = nrm
    n = 7
    for k in range(n):
        pts.append(p.copy())
        d = (d * 0.55 + Vector((0, -0.05, -1.0)) * 0.45).normalized()
        p = p + d * (L / (n - 1))
    strands.append((pts, 0.00035))
print('STRANDS', len(strands))

hc = bpy.data.hair_curves.new('JesusHair')
hc.add_curves([len(s_[0]) for s_ in strands])
flat, rads = [], []
for pts, r0 in strands:
    n = len(pts)
    for i, q in enumerate(pts):
        flat.extend((q.x, q.y, q.z))
        rads.append(r0 * (1.0 - 0.75 * i / (n - 1)))
hc.position_data.foreach_set('vector', flat)
try:
    rad_attr = hc.attributes.get('radius') or hc.attributes.new('radius', 'FLOAT', 'POINT')
    rad_attr.data.foreach_set('value', rads)
except Exception as e:
    print('radius attr failed', e)

hair_m = bpy.data.materials.new('Hair'); hair_m.use_nodes = True
nt = hair_m.node_tree; nt.nodes.clear()
hb = nt.nodes.new('ShaderNodeBsdfHairPrincipled')
try:
    hb.parametrization = 'MELANIN'
except Exception:
    pass
for k, v in (('Melanin', 0.97), ('Melanin Redness', 0.22), ('Roughness', 0.3), ('Radial Roughness', 0.45), ('Coat', 0.1)):
    try: hb.inputs[k].default_value = v
    except KeyError: print('hair no', k)
o = nt.nodes.new('ShaderNodeOutputMaterial'); nt.links.new(hb.outputs['BSDF'], o.inputs['Surface'])
hc.materials.append(hair_m)
hair_ob = bpy.data.objects.new('JesusHair', hc)
sc.collection.objects.link(hair_ob)

bpy.ops.render.render(write_still=True)
print('RENDERED', OUT)
