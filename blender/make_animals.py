"""Build realistic Cat, Bunny and Panda models by reshaping the Quaternius Fox / Shiba Inu.

Run headless:  blender -b -P blender/make_animals.py -- models/src models/src
(reads Fox.glb / Dog.glb, writes Cat.glb / Bunny.glb / Panda.glb; the original cartoon models
are kept in models/src/cartoon/)

The stock Cat (blocky), Bunny (two-legged cartoon) and Panda (cartoon in a karate outfit) did not
match the naturalistic Fox / Wolf / Dog. Each new animal starts from a quadruped that already has a
skeleton and Idle / Gallop / Gallop_Jump / Death animations:

  Cat   <- Fox:  short round face, smaller ears, thin tail, silver tabby stripes, white socks
  Bunny <- Fox:  round head, tiny muzzle, long upright ears, round body, big haunches, cotton tail
  Panda <- Dog:  big round head, small round ears, stocky body, thick legs, black-and-white coat

Shape edits happen in rest pose and are blended by each vertex's own skin weights, so joints stay
smooth and the existing animations drive the new shapes. Bones never move and limbs keep their
length, so the animations still line up. Markings are vertex colors painted after one level of
subdivision (soft edges); smooth_animals.py then shades them without subdividing again.
"""
import bpy, bmesh, sys, os, math
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
SRC, DST = argv[0], argv[1]
os.makedirs(DST, exist_ok=True)

LEGS = ['FrontShoulder', 'FrontUpperLeg', 'FrontLowerLeg', 'BackShoulder', 'BackLeg', 'BackUpperLeg', 'BackLowerLeg',
        'FF', 'FFB', 'IKFrontLeg', 'IKBackLeg']   # paws are partly skinned to the IK foot bones
SPINE = ['Back', 'Torso', 'Torso2', 'Torso3']
NECK = ['Neck1', 'Neck2', 'Neck3']
EARS = ['Ear1', 'Ear2', 'Ear3', 'Ear4']


def sided(names):
    return [f'{n}.{s}' for n in names for s in ('L', 'R')]


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ scene helpers
class Animal:
    """Imported model + skeleton. Positions are handled in Blender world space (+X side, -Y forward,
    +Z up, ground at z=0). The mesh's and armature's own spaces are rotated by the importer's
    Y-up -> Z-up conversion on their parent, so neither is upright."""

    def __init__(self, path):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=path)
        self.arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
        self.mesh = max((o for o in bpy.context.scene.objects if o.type == 'MESH' and o.parent == self.arm),
                        key=lambda o: len(o.data.vertices))
        for o in list(bpy.context.scene.objects):   # the importer's bone-display helper sphere
            if o.type == 'MESH' and o.parent is None:
                bpy.data.objects.remove(o)
        self.arm.data.pose_position = 'REST'
        bpy.context.view_layer.update()
        aw = self.arm.matrix_world
        self.seg = {b.name: (aw @ b.head_local, aw @ b.tail_local) for b in self.arm.data.bones}
        self.to_world = self.mesh.matrix_world.copy()
        self.to_mesh = self.to_world.inverted()
        self.names = {g.index: g.name for g in self.mesh.vertex_groups}
        self.weld()

    def head(self, n): return self.seg[n][0].copy()
    def tail(self, n): return self.seg[n][1].copy()
    def pos(self, co): return self.to_world @ co
    def tails(self): return sorted([n for n in self.seg if n.startswith('Tail')], key=lambda n: int(n[4:]))

    def weld(self):
        """The sources are flat-shaded: every face has its own corner vertices. Weld them first."""
        bm = bmesh.new(); bm.from_mesh(self.mesh.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5 * max(self.mesh.dimensions))
        bm.to_mesh(self.mesh.data); bm.free()

    def groups(self, v):
        return [(self.names[g.group], g.weight) for g in v.groups if g.weight > 0]

    def weight_of(self, v, bones):
        return sum(w for n, w in self.groups(v) if n in bones)

    def face_weight(self, p, bones):
        return sum(self.weight_of(self.mesh.data.vertices[i], bones) for i in p.vertices) / len(p.vertices)

    def eye_faces(self, side):
        names = [m.name for m in self.mesh.data.materials]
        return [p for p in self.mesh.data.polygons
                if names[p.material_index].startswith('Eyes') and (self.pos(p.center).x > 0) == (side > 0)]

    def eye_center(self, side):
        pts = [self.pos(p.center) for p in self.eye_faces(side)]
        return sum(pts, Vector()) / len(pts)

    def reshape(self, ops):
        """ops: {bone: fn(pos) -> pos}. Each vertex moves by the skin-weighted blend of its bones' ops."""
        for v in self.mesh.data.vertices:
            co = self.pos(v.co)
            tot, disp = 0.0, Vector()
            for n, w in self.groups(v):
                tot += w
                fn = ops.get(n)
                if fn: disp += (fn(co) - co) * w
            if tot > 0:
                v.co = self.to_mesh @ (co + disp / tot)
        self.mesh.data.update()

    def enlarge_eyes(self, k):
        for side in (1, -1):
            c = self.eye_center(side)
            for i in {i for p in self.eye_faces(side) for i in p.vertices}:
                v = self.mesh.data.vertices[i]
                v.co = self.to_mesh @ (c + (self.pos(v.co) - c) * k)
        self.mesh.data.update()

    def subdivide(self):
        """One Catmull-Clark level, applied now so markings can be painted at the finer resolution
        (vertex-group weights are interpolated onto the new vertices)."""
        bpy.context.view_layer.objects.active = self.mesh
        self.mesh.select_set(True)
        mod = self.mesh.modifiers.new('Subdiv', 'SUBSURF')
        mod.levels = mod.render_levels = 1
        mod.quality = 3
        bpy.ops.object.modifier_move_to_index(modifier='Subdiv', index=0)
        bpy.ops.object.modifier_apply(modifier='Subdiv')

    def recolor(self, name, rgb):
        for m in self.mesh.data.materials:
            if m and m.name == name:
                m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*rgb, 1)

    def paint(self, fn):
        """Vertex color = fn(vertex, world position) -> brightness 0..1 (multiplies the base color)."""
        col = self.mesh.data.color_attributes.new('Markings', 'FLOAT_COLOR', 'POINT')
        for v in self.mesh.data.vertices:
            k = fn(v, self.pos(v.co))
            col.data[v.index].color = (k, k, k, 1.0)
        self.mesh.data.color_attributes.active_color = col

    def set_material(self, face_test, name):
        idx = [m.name for m in self.mesh.data.materials].index(name)
        for p in self.mesh.data.polygons:
            if face_test(p, self.pos(p.center)): p.material_index = idx

    def export(self, name):
        self.mesh.name = self.mesh.data.name = name
        self.arm.data.pose_position = 'POSE'
        bpy.ops.object.select_all(action='SELECT')
        path = os.path.join(DST, f'{name}.glb')
        bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', export_animations=True, export_skins=True,
                                  export_yup=True, export_animation_mode='ACTIONS', export_vertex_color='ACTIVE')
        print('EXPORTED', path, os.path.getsize(path) // 1024, 'KB')


# ------------------------------------------------------------------ shape operators (world space)
def closest_on_segment(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return a + ab * t


def radial(a, b, k):
    """Fatter (k > 1) or thinner (k < 1) around a bone segment."""
    def f(v):
        p = closest_on_segment(v, a, b)
        return p + (v - p) * k
    return f


def along(pivot, axis, k_par, k_perp, turn_to=None):
    """Stretch along an axis from a pivot; optionally swing the result to point along turn_to."""
    axis = axis.normalized()
    rot = axis.rotation_difference(turn_to.normalized()).to_matrix() if turn_to is not None else None
    def f(v):
        d = v - pivot
        par = axis * d.dot(axis)
        out = par * k_par + (d - par) * k_perp
        return pivot + (rot @ out if rot is not None else out)
    return f


def head_shape(a, muzzle_y=0.4, muzzle_xz=1.0, skull=1.1):
    """Shorten the muzzle (everything in front of the eyes) and round out the skull behind it."""
    eye = (a.eye_center(1) + a.eye_center(-1)) / 2
    tip_y = min(a.pos(v.co).y for v in a.mesh.data.vertices if a.weight_of(v, {'Head'}) > 0.5)
    snout = max(1e-6, eye.y - tip_y)
    centre = Vector((0.0, eye.y + snout * 0.35, eye.z - snout * 0.15))
    def f(v):
        fwd = smoothstep(0.0, snout * 0.35, eye.y - v.y)          # 0 behind the eyes, 1 on the muzzle
        k_xz = skull + (muzzle_xz - skull) * fwd
        out = Vector((centre.x + (v.x - centre.x) * k_xz, v.y, centre.z + (v.z - centre.z) * k_xz))
        if v.y < eye.y:
            out.y = eye.y + (v.y - eye.y) * (1 + (muzzle_y - 1) * fwd)
        elif v.y > centre.y:
            out.y = centre.y + (v.y - centre.y) * skull
        return out
    return f


# ------------------------------------------------------------------ Cat (from Fox)
def make_cat():
    a = Animal(os.path.join(SRC, 'Fox.glb'))
    ops = {'Head': head_shape(a, muzzle_y=0.42, muzzle_xz=0.95, skull=1.12)}
    for s in 'LR':
        pivot = a.head(f'Ear1.{s}'); axis = a.tail(f'Ear4.{s}') - pivot
        for e in EARS: ops[f'{e}.{s}'] = along(pivot, axis, 0.62, 1.0)
    for n in a.tails(): ops[n] = radial(*a.seg[n], 0.42)                # thin tail, not a brush
    for n in SPINE: ops[n] = radial(*a.seg[n], 1.08)
    a.reshape(ops)
    a.enlarge_eyes(1.45)
    a.subdivide()

    a.recolor('Main', (0.20, 0.20, 0.21))
    a.recolor('Grey', (0.20, 0.20, 0.21))
    a.recolor('Main_Light', (0.80, 0.79, 0.76))
    tails = set(a.tails())
    a.set_material(lambda p, c: a.face_weight(p, tails) > 0.5, 'Main')          # no white fox tail tip
    sock_z = a.head('FrontLowerLeg.L').z * 0.4
    a.set_material(lambda p, c: c.z < sock_z, 'Main_Light')                    # white socks
    body_len = abs(a.head('Head').y - a.tail(a.tails()[-1]).y)
    legs = set(sided(LEGS))

    def tabby(v, c):
        if a.weight_of(v, legs) > 0.5:
            t = c.z / body_len * 10.0
        elif a.weight_of(v, tails) > 0.5:
            t = c.y / body_len * 12.0
        else:   # stripes run down the flanks from the spine, bending back slightly
            t = c.y / body_len * 9.0 + (a.head('Torso').z - c.z) / body_len * 2.5
        s = 0.5 + 0.5 * math.sin(t * math.tau)
        dark = smoothstep(0.62, 0.86, s)
        if a.weight_of(v, {'Head', 'Neck3'}) > 0.5: dark *= 0.55      # fainter on the face
        return 1.0 - 0.6 * dark
    a.paint(tabby)
    a.export('Cat')


# ------------------------------------------------------------------ Bunny (from Fox)
def make_bunny():
    a = Animal(os.path.join(SRC, 'Fox.glb'))
    ops = {'Head': head_shape(a, muzzle_y=0.34, muzzle_xz=1.05, skull=1.2)}
    for s, side in (('L', 1), ('R', -1)):
        pivot = a.head(f'Ear1.{s}'); axis = a.tail(f'Ear4.{s}') - pivot
        up_and_back = Vector((0.16 * side, 0.22, 1.0))                  # rabbit ears stand up
        for e in EARS: ops[f'{e}.{s}'] = along(pivot, axis, 2.4, 1.15, up_and_back)
    tb = a.tails(); pivot = a.head(tb[0]); axis = a.tail(tb[-1]) - pivot
    for n in tb: ops[n] = along(pivot, axis, 0.1, 0.85)                 # cotton tail
    for n in SPINE: ops[n] = radial(*a.seg[n], 1.58)                     # round body hides the leg tops
    for n in NECK: ops[n] = radial(*a.seg[n], 1.35)
    for n in sided(['BackLeg', 'BackUpperLeg', 'BackShoulder']): ops[n] = radial(*a.seg[n], 1.45)  # haunches
    for n in sided(['FrontUpperLeg', 'FrontLowerLeg', 'BackLowerLeg']): ops[n] = radial(*a.seg[n], 1.15)
    a.reshape(ops)
    # long hind feet: stretch the lowest part of the hind legs forward from the heel
    hind = set(sided(['BackLowerLeg', 'FFB']))
    foot_z = a.head('BackLowerLeg.L').z * 0.3
    heel_y = a.head('BackLowerLeg.L').y
    for v in a.mesh.data.vertices:
        c = a.pos(v.co)
        w = a.weight_of(v, hind)
        if w > 0 and c.z < foot_z:
            k = 1 + 0.9 * w * (1 - c.z / foot_z)
            c.y = heel_y + (c.y - heel_y) * k
            v.co = a.to_mesh @ c
    a.mesh.data.update()
    a.enlarge_eyes(1.6)
    a.subdivide()

    a.recolor('Main', (0.16, 0.11, 0.07))
    a.recolor('Grey', (0.16, 0.11, 0.07))
    a.recolor('Main_Light', (0.66, 0.60, 0.51))
    a.recolor('Black', (0.36, 0.16, 0.17))                               # pink-brown nose
    tails = set(tb)
    a.set_material(lambda p, c: a.face_weight(p, tails) > 0.4, 'Main_Light')   # white cotton tail
    ears = set(sided(EARS))
    a.paint(lambda v, c: 1.0 - 0.35 * smoothstep(0.5, 0.9, a.weight_of(v, ears)))   # darker ears
    a.export('Bunny')


# ------------------------------------------------------------------ Panda (from Shiba Inu)
def make_panda():
    a = Animal(os.path.join(SRC, 'Dog.glb'))
    ops = {'Head': head_shape(a, muzzle_y=0.5, muzzle_xz=1.2, skull=1.3)}
    for s in 'LR':
        pivot = a.head(f'Ear1.{s}'); axis = a.tail(f'Ear4.{s}') - pivot
        for e in EARS: ops[f'{e}.{s}'] = along(pivot, axis, 0.45, 1.2)    # small round ears
    tb = a.tails(); pivot = a.head(tb[0]); axis = a.tail(tb[-1]) - pivot
    for n in tb: ops[n] = along(pivot, axis, 0.3, 0.75)                   # stub tail
    for n in SPINE: ops[n] = radial(*a.seg[n], 1.42)                       # stocky bear body
    for n in NECK: ops[n] = radial(*a.seg[n], 1.35)
    for n in sided(LEGS): ops[n] = radial(*a.seg[n], 1.6)                  # thick legs
    a.reshape(ops)
    a.subdivide()

    white = (0.80, 0.78, 0.74)
    a.recolor('Main', white)
    a.recolor('Main_Light', white)
    legs, ears = set(sided(LEGS)), set(sided(EARS))
    eyes = [a.eye_center(1), a.eye_center(-1)]
    head_size = abs(a.head('Head').y - min(a.pos(v.co).y for v in a.mesh.data.vertices))
    shoulder_y = a.head('FrontShoulder.L').y
    body_len = abs(a.head('Head').y - a.tail(tb[-1]).y)
    trunk = set(SPINE) | set(NECK)

    def coat(v, c):
        black = max(a.weight_of(v, legs), a.weight_of(v, ears))
        if a.weight_of(v, trunk) > 0.3:                                   # band over the shoulders
            black = max(black, math.exp(-((c.y - shoulder_y) / (0.12 * body_len)) ** 2))
        if a.weight_of(v, {'Head'}) > 0.3:                                 # eye patches, drooping outward
            for e in eyes:
                d = c - e
                d = Vector((d.x * 0.9, d.y * 1.1, d.z * (0.55 if d.z < 0 else 1.2)))
                black = max(black, 1.0 - smoothstep(0.22 * head_size, 0.34 * head_size, d.length))
        black = smoothstep(0.38, 0.62, black)
        return 1.0 - 0.975 * black
    a.paint(coat)
    a.export('Panda')


for fn in (make_cat, make_bunny, make_panda):
    fn()
