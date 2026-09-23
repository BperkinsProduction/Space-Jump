"""Render the five theme skyboxes as 360° equirectangular panoramas.

Run headless:  blender -b -P blender/render_skies.py -- <outdir> [preview]

Each sky = Nishita physical atmosphere (or a stylized world for the fantasy themes)
+ a volumetric cloud sea below the camera + scattered volumetric cumulus.
Also writes skies.json with each sky's sun direction (u, v in the panorama) so the
game can align its directional light with the sun painted into the sky.
"""
import bpy, sys, math, json, os

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = argv[0] if argv else '/tmp/skies'
PREVIEW = len(argv) > 1 and argv[1] == 'preview'
ONLY = argv[2] if len(argv) > 2 else None
os.makedirs(OUT, exist_ok=True)

W, H = (1024, 512) if PREVIEW else (2048, 1024)
SAMPLES = 24 if PREVIEW else 128

THEMES = [
    # name, sun elevation (deg), sun azimuth (deg), world style, cloud tint, sun strength, exposure
    dict(name='sky',        elev=38,  azim=150, style='nishita', air=1.0, dust=0.4, ozone=1.3, sun=9.0,  expo=-1.5, cloudCol=(1, 1, 1)),
    dict(name='sunset',     elev=3.0, azim=190, style='nishita', air=1.8, dust=5.0, ozone=1.0, sun=9.0,  expo=-0.9, cloudCol=(1, 0.9, 0.82)),
    dict(name='night',      elev=-8,  azim=200, style='night',   air=1.0, dust=1.0, ozone=1.0, sun=0.7,  expo=-0.2, cloudCol=(0.7, 0.78, 1.0)),
    dict(name='underwater', elev=60,  azim=170, style='water',   air=1.0, dust=1.0, ozone=1.0, sun=6.0,  expo=-0.9, cloudCol=(0.42, 0.74, 0.78)),
    dict(name='candy',      elev=12,  azim=175, style='candy',   air=1.0, dust=2.0, ozone=1.0, sun=8.0,  expo=-1.0, cloudCol=(1, 0.86, 0.95)),
]


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
        print('GPU setup failed, using CPU:', e)
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    sc.cycles.volume_step_rate = 6.0 if PREVIEW else 3.0
    sc.cycles.volume_max_steps = 256
    sc.cycles.max_bounces = 6
    sc.cycles.volume_bounces = 1
    sc.render.resolution_x = W
    sc.render.resolution_y = H
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'JPEG'
    sc.render.image_settings.quality = 88
    sc.view_settings.view_transform = 'AgX'
    try:
        sc.view_settings.look = 'AgX - Punchy'
    except Exception:
        pass
    return sc


def make_camera(sc):
    cam_data = bpy.data.cameras.new('PanoCam')
    cam_data.type = 'PANO'
    try:
        cam_data.panorama_type = 'EQUIRECTANGULAR'
    except Exception:
        cam_data.cycles.panorama_type = 'EQUIRECTANGULAR'
    cam_data.clip_start = 0.5
    cam_data.clip_end = 250000
    cam = bpy.data.objects.new('PanoCam', cam_data)
    sc.collection.objects.link(cam)
    cam.location = (0, 0, 0)
    cam.rotation_euler = (math.pi / 2, 0, 0)  # looking along +Y at the horizon
    sc.camera = cam
    return cam


def cloud_volume_material(name, tint, density, scale, threshold, height_lo, height_hi, detail=8):
    """Procedural cumulus-ish density: fbm noise, thresholded, faded by altitude."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    vol = nt.nodes.new('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value = (*tint, 1)
    vol.inputs['Anisotropy'].default_value = 0.55
    coord = nt.nodes.new('ShaderNodeTexCoord')
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = scale
    noise.inputs['Detail'].default_value = detail
    noise.inputs['Roughness'].default_value = 0.62
    nt.links.new(coord.outputs['Object'], noise.inputs['Vector'])
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = threshold
    ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    ramp.color_ramp.elements[1].position = min(1.0, threshold + 0.12)
    ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt.links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    # altitude fade using object-space Z (-1..1 across the domain)
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
    mr = nt.nodes.new('ShaderNodeMapRange')
    mr.inputs['From Min'].default_value = height_lo
    mr.inputs['From Max'].default_value = height_hi
    mr.inputs['To Min'].default_value = 1.0
    mr.inputs['To Max'].default_value = 0.0
    nt.links.new(sep.outputs['Z'], mr.inputs['Value'])
    mul = nt.nodes.new('ShaderNodeMath')
    mul.operation = 'MULTIPLY'
    nt.links.new(ramp.outputs['Color'], mul.inputs[0])
    nt.links.new(mr.outputs['Result'], mul.inputs[1])
    mul2 = nt.nodes.new('ShaderNodeMath')
    mul2.operation = 'MULTIPLY'
    mul2.inputs[1].default_value = density
    nt.links.new(mul.outputs['Value'], mul2.inputs[0])
    nt.links.new(mul2.outputs['Value'], vol.inputs['Density'])
    nt.links.new(vol.outputs['Volume'], out.inputs['Volume'])
    return mat


def add_cloud_domain(sc, name, loc, size, mat):
    bpy.ops.mesh.primitive_cube_add(size=2, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    ob.data.materials.append(mat)
    return ob


def build_world(sc, t):
    world = bpy.data.worlds.new('World')
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld')
    elev = math.radians(t['elev'])
    azim = math.radians(t['azim'])

    def nishita(disc, elev_override=None):
        s = nt.nodes.new('ShaderNodeTexSky')
        s.sky_type = 'NISHITA'
        s.sun_elevation = elev if elev_override is None else elev_override
        s.sun_rotation = azim
        s.altitude = 1200
        s.air_density = t['air']
        s.dust_density = t['dust']
        s.ozone_density = t['ozone']
        s.sun_disc = disc
        s.sun_size = math.radians(1.2)
        s.sun_intensity = 0.6
        return s

    # Camera sees the sun disc; lighting comes from a lamp (clean, noise-free)
    lp = nt.nodes.new('ShaderNodeLightPath')
    bg_cam = nt.nodes.new('ShaderNodeBackground')
    bg_light = nt.nodes.new('ShaderNodeBackground')
    mix = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac'])
    nt.links.new(bg_light.outputs['Background'], mix.inputs[1])
    nt.links.new(bg_cam.outputs['Background'], mix.inputs[2])
    nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])

    style = t['style']
    if style in ('nishita', 'candy'):
        s_cam = nishita(True)
        HAZE['sun_node'] = s_cam
        s_light = nishita(False)
        if style == 'candy':
            # hue-shift the physical sky toward pink / lavender
            for s, bg in ((s_cam, bg_cam), (s_light, bg_light)):
                hs = nt.nodes.new('ShaderNodeHueSaturation')
                hs.inputs['Hue'].default_value = 0.83
                hs.inputs['Saturation'].default_value = 1.15
                nt.links.new(s.outputs['Color'], hs.inputs['Color'])
                nt.links.new(hs.outputs['Color'], bg.inputs['Color'])
        else:
            nt.links.new(s_cam.outputs['Color'], bg_cam.inputs['Color'])
            nt.links.new(s_light.outputs['Color'], bg_light.inputs['Color'])
        bg_cam.inputs['Strength'].default_value = 1.0
        bg_light.inputs['Strength'].default_value = 1.0
    elif style == 'night':
        # twilight Nishita + procedural stars + aurora curtains
        s_cam = nishita(False)
        coord = nt.nodes.new('ShaderNodeTexCoord')
        # stars: sparse voronoi points
        vor = nt.nodes.new('ShaderNodeTexVoronoi')
        vor.inputs['Scale'].default_value = 420
        nt.links.new(coord.outputs['Generated'], vor.inputs['Vector'])
        sr = nt.nodes.new('ShaderNodeMapRange')
        sr.inputs['From Min'].default_value = 0.035
        sr.inputs['From Max'].default_value = 0.0
        sr.inputs['To Min'].default_value = 0.0
        sr.inputs['To Max'].default_value = 6.0
        nt.links.new(vor.outputs['Distance'], sr.inputs['Value'])
        # only above the horizon
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(coord.outputs['Generated'], sep.inputs['Vector'])
        horiz = nt.nodes.new('ShaderNodeMapRange')
        horiz.inputs['From Min'].default_value = 0.02
        horiz.inputs['From Max'].default_value = 0.12
        nt.links.new(sep.outputs['Z'], horiz.inputs['Value'])
        stars = nt.nodes.new('ShaderNodeMath'); stars.operation = 'MULTIPLY'
        nt.links.new(sr.outputs['Result'], stars.inputs[0])
        nt.links.new(horiz.outputs['Result'], stars.inputs[1])
        # aurora: vertical curtains that vary with compass direction, in a mid-sky belt
        dirn = nt.nodes.new('ShaderNodeVectorMath'); dirn.operation = 'NORMALIZE'
        nt.links.new(coord.outputs['Generated'], dirn.inputs[0])
        dsep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(dirn.outputs['Vector'], dsep.inputs['Vector'])
        az = nt.nodes.new('ShaderNodeMath'); az.operation = 'ARCTAN2'
        nt.links.new(dsep.outputs['Y'], az.inputs[0])
        nt.links.new(dsep.outputs['X'], az.inputs[1])
        def scaled(src, k):
            m = nt.nodes.new('ShaderNodeMath'); m.operation = 'MULTIPLY'; m.inputs[1].default_value = k
            nt.links.new(src, m.inputs[0]); return m.outputs['Value']
        cv = nt.nodes.new('ShaderNodeCombineXYZ')
        nt.links.new(scaled(az.outputs['Value'], 1.3), cv.inputs['X'])
        nt.links.new(scaled(dsep.outputs['Z'], 0.5), cv.inputs['Y'])
        curt = nt.nodes.new('ShaderNodeTexNoise')
        curt.inputs['Scale'].default_value = 2.2
        curt.inputs['Detail'].default_value = 3
        nt.links.new(cv.outputs['Vector'], curt.inputs['Vector'])
        cramp = nt.nodes.new('ShaderNodeMapRange')
        cramp.inputs['From Min'].default_value = 0.5
        cramp.inputs['From Max'].default_value = 0.68
        nt.links.new(curt.outputs['Fac'], cramp.inputs['Value'])
        rv = nt.nodes.new('ShaderNodeCombineXYZ')
        nt.links.new(scaled(az.outputs['Value'], 16.0), rv.inputs['X'])
        rays = nt.nodes.new('ShaderNodeTexNoise')
        rays.inputs['Scale'].default_value = 3.0
        rays.inputs['Detail'].default_value = 1
        nt.links.new(rv.outputs['Vector'], rays.inputs['Vector'])
        rayk = nt.nodes.new('ShaderNodeMapRange')
        rayk.inputs['To Min'].default_value = 0.35
        rayk.inputs['To Max'].default_value = 1.4
        nt.links.new(rays.outputs['Fac'], rayk.inputs['Value'])
        belt = nt.nodes.new('ShaderNodeFloatCurve')
        c = belt.mapping.curves[0]
        c.points[0].location = (0.0, 0.0)
        c.points[1].location = (1.0, 0.0)
        c.points.new(0.06, 0.0); c.points.new(0.2, 1.0); c.points.new(0.42, 0.45); c.points.new(0.7, 0.0)
        belt.mapping.update()
        nt.links.new(dsep.outputs['Z'], belt.inputs['Value'])
        a1n = nt.nodes.new('ShaderNodeMath'); a1n.operation = 'MULTIPLY'
        nt.links.new(cramp.outputs['Result'], a1n.inputs[0])
        nt.links.new(rayk.outputs['Result'], a1n.inputs[1])
        aur = nt.nodes.new('ShaderNodeMath'); aur.operation = 'MULTIPLY'
        nt.links.new(a1n.outputs['Value'], aur.inputs[0])
        nt.links.new(belt.outputs['Value'], aur.inputs[1])
        aurCol = nt.nodes.new('ShaderNodeMix'); aurCol.data_type = 'RGBA'
        aurCol.inputs['A'].default_value = (0.08, 0.9, 0.45, 1)
        aurCol.inputs['B'].default_value = (0.5, 0.25, 0.95, 1)
        nt.links.new(scaled(dsep.outputs['Z'], 1.8), aurCol.inputs['Factor'])
        aurStr = nt.nodes.new('ShaderNodeVectorMath'); aurStr.operation = 'SCALE'
        nt.links.new(aurCol.outputs['Result'], aurStr.inputs[0])
        nt.links.new(scaled(aur.outputs['Value'], 0.35), aurStr.inputs['Scale'])
        # night base color: dim deep blue gradient
        base = nt.nodes.new('ShaderNodeRGB'); base.outputs[0].default_value = (0.006, 0.01, 0.03, 1)
        add1 = nt.nodes.new('ShaderNodeVectorMath'); add1.operation = 'ADD'
        nt.links.new(s_cam.outputs['Color'], add1.inputs[0])
        nt.links.new(base.outputs[0], add1.inputs[1])
        add2 = nt.nodes.new('ShaderNodeVectorMath'); add2.operation = 'ADD'
        nt.links.new(add1.outputs['Vector'], add2.inputs[0])
        nt.links.new(aurStr.outputs['Vector'], add2.inputs[1])
        starv = nt.nodes.new('ShaderNodeCombineXYZ')
        for k in ('X', 'Y', 'Z'):
            nt.links.new(stars.outputs['Value'], starv.inputs[k])
        add3 = nt.nodes.new('ShaderNodeVectorMath'); add3.operation = 'ADD'
        nt.links.new(add2.outputs['Vector'], add3.inputs[0])
        nt.links.new(starv.outputs['Vector'], add3.inputs[1])
        nt.links.new(add3.outputs['Vector'], bg_cam.inputs['Color'])
        # clouds get lit by a soft blue night ambient + aurora glow
        bg_light.inputs['Color'].default_value = (0.03, 0.06, 0.12, 1)
        bg_light.inputs['Strength'].default_value = 1.0
    elif style == 'water':
        # stylized sunlit ocean: bright surface above, deep teal below
        coord = nt.nodes.new('ShaderNodeTexCoord')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(coord.outputs['Generated'], sep.inputs['Vector'])
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        cr = ramp.color_ramp
        cr.elements[0].position = 0.25; cr.elements[0].color = (0.004, 0.06, 0.09, 1)
        cr.elements[1].position = 0.95; cr.elements[1].color = (0.35, 0.85, 0.95, 1)
        e = cr.elements.new(0.55); e.color = (0.03, 0.3, 0.42, 1)
        mr = nt.nodes.new('ShaderNodeMapRange')
        mr.inputs['From Min'].default_value = -1
        mr.inputs['From Max'].default_value = 1
        nt.links.new(sep.outputs['Z'], mr.inputs['Value'])
        nt.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
        # caustic shimmer near the top
        vor = nt.nodes.new('ShaderNodeTexVoronoi')
        vor.feature = 'SMOOTH_F1' if hasattr(vor, 'feature') else vor.feature
        vor.inputs['Scale'].default_value = 6
        nt.links.new(coord.outputs['Generated'], vor.inputs['Vector'])
        caus = nt.nodes.new('ShaderNodeMapRange')
        caus.inputs['From Min'].default_value = 0.0
        caus.inputs['From Max'].default_value = 0.25
        caus.inputs['To Min'].default_value = 0.18
        caus.inputs['To Max'].default_value = 0.0
        nt.links.new(vor.outputs['Distance'], caus.inputs['Value'])
        top = nt.nodes.new('ShaderNodeMapRange')
        top.inputs['From Min'].default_value = 0.3
        top.inputs['From Max'].default_value = 0.9
        nt.links.new(sep.outputs['Z'], top.inputs['Value'])
        cm = nt.nodes.new('ShaderNodeMath'); cm.operation = 'MULTIPLY'
        nt.links.new(caus.outputs['Result'], cm.inputs[0])
        nt.links.new(top.outputs['Result'], cm.inputs[1])
        cv = nt.nodes.new('ShaderNodeCombineXYZ')
        for k in ('X', 'Y', 'Z'):
            nt.links.new(cm.outputs['Value'], cv.inputs[k])
        add = nt.nodes.new('ShaderNodeVectorMath'); add.operation = 'ADD'
        nt.links.new(ramp.outputs['Color'], add.inputs[0])
        nt.links.new(cv.outputs['Vector'], add.inputs[1])
        nt.links.new(add.outputs['Vector'], bg_cam.inputs['Color'])
        nt.links.new(ramp.outputs['Color'], bg_light.inputs['Color'])
        bg_cam.inputs['Strength'].default_value = 1.0
        bg_light.inputs['Strength'].default_value = 1.0

    # Sun / moon lamp aligned with the sky's sun direction
    sun_data = bpy.data.lights.new('Sun', 'SUN')
    sun_data.energy = t['sun']
    sun_data.angle = math.radians(1.5)
    if style == 'night':
        sun_data.color = (0.55, 0.65, 1.0)
    elif style == 'water':
        sun_data.color = (0.75, 0.95, 1.0)
    elif t['elev'] < 10:
        sun_data.color = (1.0, 0.62, 0.38)
    else:
        sun_data.color = (1.0, 0.95, 0.88)
    sun = bpy.data.objects.new('Sun', sun_data)
    sc.collection.objects.link(sun)
    e = max(elev, math.radians(8)) if style == 'night' else elev
    # Blender sun lamps point down -Z; aim it so light travels from the sky's sun direction
    to_sun = (-math.sin(azim) * math.cos(e), math.cos(azim) * math.cos(e), math.sin(e))
    import mathutils
    v = mathutils.Vector(to_sun)
    sun.rotation_euler = v.to_track_quat('Z', 'Y').to_euler()
    sc.view_settings.exposure = t['expo']


HAZE = {'path': None, 'rot': 0.0, 'debug': False}


def haze_source(nt, t):
    """Color the far clouds fade into: the real sky color just above the horizon,
    looked up from a linear EXR render of the bare sky (pass 1)."""
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    neg = nt.nodes.new('ShaderNodeVectorMath'); neg.operation = 'SCALE'
    neg.inputs['Scale'].default_value = -1.0
    nt.links.new(geo.outputs['Incoming'], neg.inputs[0])
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(neg.outputs['Vector'], sep.inputs['Vector'])
    comb = nt.nodes.new('ShaderNodeCombineXYZ')
    nt.links.new(sep.outputs['X'], comb.inputs['X'])
    nt.links.new(sep.outputs['Y'], comb.inputs['Y'])
    flat = nt.nodes.new('ShaderNodeVectorMath'); flat.operation = 'NORMALIZE'
    nt.links.new(comb.outputs['Vector'], flat.inputs[0])
    lift = nt.nodes.new('ShaderNodeVectorMath'); lift.operation = 'ADD'
    lift.inputs[1].default_value = (0, 0, 0.035)
    nt.links.new(flat.outputs['Vector'], lift.inputs[0])
    comb = lift
    rot = nt.nodes.new('ShaderNodeVectorRotate')
    rot.rotation_type = 'Z_AXIS'
    rot.inputs['Angle'].default_value = HAZE['rot']
    nt.links.new(comb.outputs['Vector'], rot.inputs['Vector'])
    env = nt.nodes.new('ShaderNodeTexEnvironment')
    env.image = bpy.data.images.load(HAZE['path'], check_existing=True)
    nt.links.new(rot.outputs['Vector'], env.inputs['Vector'])
    return env.outputs['Color']


def cloud_surface_material(t, fog_dist):
    mat = bpy.data.materials.new('CloudSurface')
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (*t['cloudCol'], 1)
    bsdf.inputs['Roughness'].default_value = 1.0
    try:
        bsdf.inputs['Subsurface Weight'].default_value = 0.12
        bsdf.inputs['Subsurface Radius'].default_value = (40, 40, 55)
        bsdf.inputs['Sheen Weight'].default_value = 0.15
    except KeyError:
        pass
    emis = nt.nodes.new('ShaderNodeEmission')
    nt.links.new(haze_source(nt, t), emis.inputs['Color'])
    emis.inputs['Strength'].default_value = 1.0
    # fog factor = 1 - exp(-distance / fog_dist)
    lp = nt.nodes.new('ShaderNodeLightPath')
    m1 = nt.nodes.new('ShaderNodeMath'); m1.operation = 'DIVIDE'; m1.inputs[1].default_value = -fog_dist
    nt.links.new(lp.outputs['Ray Length'], m1.inputs[0])
    m2 = nt.nodes.new('ShaderNodeMath'); m2.operation = 'EXPONENT'
    nt.links.new(m1.outputs['Value'], m2.inputs[0])
    m3 = nt.nodes.new('ShaderNodeMath'); m3.operation = 'SUBTRACT'; m3.inputs[0].default_value = 1.0
    nt.links.new(m2.outputs['Value'], m3.inputs[1])
    # only camera rays get hazed
    m4 = nt.nodes.new('ShaderNodeMath'); m4.operation = 'MULTIPLY'
    nt.links.new(m3.outputs['Value'], m4.inputs[0])
    nt.links.new(lp.outputs['Is Camera Ray'], m4.inputs[1])
    mix = nt.nodes.new('ShaderNodeMixShader')
    if HAZE['debug']:
        mix.inputs['Fac'].default_value = 1.0
    else:
        nt.links.new(m4.outputs['Value'], mix.inputs['Fac'])
    nt.links.new(bsdf.outputs['BSDF'], mix.inputs[1])
    nt.links.new(emis.outputs['Emission'], mix.inputs[2])
    nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    return mat


def build_clouds(sc, t):
    mat = cloud_surface_material(t, fog_dist=26000)
    # --- cloud sea: a huge displaced grid seen from ~450 m above its tops ---
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=700, y_subdivisions=700, size=60000, location=(0, 0, -650))
    sea = bpy.context.active_object
    for name, size, strength in (('big', 1300, 520), ('mid', 320, 140), ('small', 85, 34)):
        tex = bpy.data.textures.new(f'sea_{name}', 'CLOUDS')
        tex.noise_scale = size
        tex.noise_depth = 2
        d = sea.modifiers.new(f'disp_{name}', 'DISPLACE')
        d.texture = tex
        d.texture_coords = 'GLOBAL'
        d.strength = strength
        d.mid_level = 0.45
    bpy.ops.object.shade_smooth()
    sea.data.materials.append(mat)
    # --- distant cumulus towers rising out of the sea around the horizon ---
    import random
    rng = random.Random(3)
    for i in range(26):
        w = rng.uniform(650, 1500)
        ang = rng.uniform(0, math.tau)
        dist = rng.uniform(max(5000, w * 5), 16000)
        cx, cy = math.cos(ang) * dist, math.sin(ang) * dist
        base = -430
        tall = rng.uniform(0.9, 2.2)
        mb = bpy.data.metaballs.new(f'cu{i}')
        mb.resolution = max(18, w / 55)
        mb.render_resolution = mb.resolution
        n = rng.randint(9, 14)
        for k in range(n):
            e = mb.elements.new()
            hgt = (k / (n - 1)) ** 1.2
            spread = w * 0.55 * (1 - 0.55 * hgt)
            e.co = (cx + rng.uniform(-spread, spread), cy + rng.uniform(-spread, spread), base + hgt * w * tall)
            e.radius = w * rng.uniform(0.75, 1.0) * (1 - 0.4 * hgt)
        ob = bpy.data.objects.new(f'cu{i}', mb)
        sc.collection.objects.link(ob)
        bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.convert(target='MESH')
        cm = bpy.context.active_object
        for nm, sz, st in (('a', w * 0.32, w * 0.22), ('b', w * 0.09, w * 0.06)):
            tx = bpy.data.textures.new(f'cu{i}{nm}', 'CLOUDS')
            tx.noise_scale = sz
            tx.noise_depth = 2
            dm = cm.modifiers.new(nm, 'DISPLACE')
            dm.texture = tx
            dm.texture_coords = 'GLOBAL'
            dm.strength = st
        bpy.ops.object.shade_smooth()
        cm.data.materials.clear()
        cm.data.materials.append(mat)


def sun_pixel_uv(path):
    """Find the brightest region of the rendered panorama (the sun) → (u, v)."""
    img = bpy.data.images.load(path)
    w, h = img.size
    px = list(img.pixels)
    best, bi = -1, 0
    for i in range(0, w * h):
        r, g, b = px[i * 4], px[i * 4 + 1], px[i * 4 + 2]
        lum = r * 0.3 + g * 0.6 + b * 0.1
        if lum > best:
            best, bi = lum, i
    x, y = bi % w, bi // w  # Blender pixel rows go bottom→top
    return (x + 0.5) / w, (y + 0.5) / h


meta = {}
HAZE['rot'] = float(os.environ.get('HAZE_ROT', str(-math.pi / 2)))
HAZE['debug'] = os.environ.get('HAZE_DEBUG') == '1'
for t in THEMES:
    if ONLY and t['name'] != ONLY:
        continue
    sc = reset()
    make_camera(sc)
    build_world(sc, t)
    # pass 1: bare sky, scene-linear EXR (haze lookup source)
    haze = os.path.join(OUT, f"_haze_{t['name']}.exr")
    sc.render.resolution_x, sc.render.resolution_y = 1024, 512
    sc.cycles.samples = 16
    sc.render.image_settings.file_format = 'OPEN_EXR'
    sc.render.image_settings.color_depth = '16'
    sc.render.filepath = haze
    if HAZE.get('sun_node'):
        HAZE['sun_node'].sun_disc = False
    bpy.ops.render.render(write_still=True)
    if HAZE.get('sun_node'):
        HAZE['sun_node'].sun_disc = True
        HAZE['sun_node'] = None
    HAZE['path'] = haze
    # pass 2: full sky with clouds
    sc.render.resolution_x, sc.render.resolution_y = W, H
    sc.cycles.samples = SAMPLES
    sc.render.image_settings.file_format = 'JPEG'
    sc.render.image_settings.quality = 88
    build_clouds(sc, t)
    path = os.path.join(OUT, f"sky_{t['name']}.jpg")
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print('RENDERED', path)
    meta[t['name']] = {'elev': t['elev'], 'azim': t['azim']}
    if t['style'] in ('nishita', 'candy'):
        u, v = sun_pixel_uv(path)
        meta[t['name']].update({'sunU': u, 'sunV': v})

mp = os.path.join(OUT, 'skies.json')
old = json.load(open(mp)) if os.path.exists(mp) else {}
old.update(meta)
json.dump(old, open(mp, 'w'), indent=2)
print('META', json.dumps(old))
