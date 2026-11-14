"""Path Tracer plugin: NURBS evaluation, tessellation with trimming, ray intersection, and the
three methods against closed-form cases and against each other; then the plugin's actions with
a stand-in for CAD. Needs numpy only (skips with 77 without it)."""

import json
import math
import os
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    sys.exit(77)

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "python"))
sys.path.insert(0, str(root / "python" / "plugins" / "pathtracer"))

import pt_bsdf  # noqa: E402
import pt_bvh  # noqa: E402
import pt_integrator  # noqa: E402
import pt_mesh  # noqa: E402
import pt_nurbs  # noqa: E402
import pt_scene  # noqa: E402
import pt_setup  # noqa: E402


def rect(p0, du, dv):
    """A flat face: corner and two edges; the normal is du x dv."""
    p0, du, dv = (np.asarray(v, dtype=float) for v in (p0, du, dv))
    pts = [p0, p0 + dv, p0 + du, p0 + du + dv]                       # index = i_u * num_v + i_v
    return {"type": "surface", "degree_u": 1, "degree_v": 1, "knots_u": [0, 0, 1, 1], "knots_v": [0, 0, 1, 1],
            "num_u": 2, "num_v": 2, "points": [float(c) for p in pts for c in p]}


def box(lo, hi):
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    ex, ey, ez = np.diag(hi - lo)
    faces = [rect(lo, ey, ex), rect(lo + ez, ex, ey), rect(lo, ex, ez), rect(lo + ey, ez, ex),
             rect(lo, ez, ey), rect(lo + ex, ey, ez)]                # normals outwards
    return {"type": "shell", "faces": [{"surface": f} for f in faces]}


def polyline(points):
    n = len(points)
    return {"degree": 1, "knots": [0.0] + [i / (n - 1) for i in range(n)] + [1.0],
            "points": [float(c) for p in points for c in (p[0], p[1], 0.0)]}


def sphere_patch(radius):
    """A quarter circle (rational, degree 2) revolved by a quarter turn: an eighth of a sphere."""
    w = math.sqrt(0.5)
    arc = [(1, 0), (1, 1), (0, 1)]
    pts, weights = [], []
    for (cx, cz), wu in zip(arc, (1, w, 1)):                         # u: from the equator to the pole
        for (ax, ay), wv in zip(arc, (1, w, 1)):                     # v: around the axis
            pts.append((radius * cx * ax, radius * cx * ay, radius * cz))
            weights.append(wu * wv)
    return {"type": "surface", "degree_u": 2, "degree_v": 2, "knots_u": [0, 0, 0, 1, 1, 1],
            "knots_v": [0, 0, 0, 1, 1, 1], "num_u": 3, "num_v": 3, "points": [float(c) for p in pts for c in p],
            "weights": weights}


MATERIALS = pt_bsdf.Materials.from_rows([
    {"name": "black", "kind": "absorber"},
    {"name": "white", "kind": "diffuse", "reflectance": 0.6},
    {"name": "mirror", "kind": "mirror", "reflectance": 0.9},
    {"name": "glass", "kind": "glass", "ior": 1.5},
    {"name": "glossy", "kind": "glossy", "reflectance": 0.7, "roughness": 0.3},
    {"name": "tinted", "kind": "glass", "ior": 1.5, "absorption": 0.05},
    {"name": "sheet", "kind": "diffuse", "reflectance": 0.3, "transmittance": 0.6},
    {"name": "detector", "kind": "detector"},
])
BLACK, WHITE, MIRROR, GLASS, GLOSSY, TINTED, SHEET, DETECTOR = range(8)


def scene_of(geometries, materials, sources, closed=()):
    mesh = pt_mesh.build([{"id": k + 1, "geometry": g} for k, g in enumerate(geometries)], 1e-3)
    return pt_scene.Scene(mesh, MATERIALS, np.asarray(materials), sources, closed)


SEED = int(os.environ.get("PT_TEST_SEED", "1"))                     # other seeds: how much room the bounds leave


def values(scene, sensor, method, samples, depth=6):
    return pt_integrator.render(scene, sensor, method, samples, depth, seed=SEED)["values"]


# ---- NURBS: partition of unity, a rational patch lies on its sphere, derivatives by differences
b, db = pt_nurbs.basis(3, [0, 0, 0, 0, 0.3, 0.6, 1, 1, 1, 1], np.linspace(0, 1, 11), derivative=True)
assert np.allclose(b.sum(axis=1), 1) and np.allclose(db.sum(axis=1), 0)
patch = sphere_patch(2.0)
us = np.linspace(0, 1, 9)
s, su, sv = pt_nurbs.surface_grid(patch, us, us)
assert np.allclose(np.linalg.norm(s, axis=-1), 2.0)
h = 1e-6
s1, _, _ = pt_nurbs.surface_grid(patch, us[1:-1] + h, us)
s0, _, _ = pt_nurbs.surface_grid(patch, us[1:-1] - h, us)
assert np.allclose((s1 - s0) / (2 * h), su[1:-1], atol=1e-6)
normal = np.cross(su, sv)[:-1]                                       # (not at the pole)
normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
assert np.allclose(np.abs(np.einsum("abk,abk->ab", normal, s[:-1])), 2.0)   # radial

# ---- mesh: the patch within the tolerance, its area
mesh = pt_mesh.build([{"id": 7, "geometry": patch}], 1e-3)
corners = np.concatenate([mesh.v0, mesh.v0 + mesh.e1, mesh.v0 + mesh.e2])
centres = mesh.v0 + (mesh.e1 + mesh.e2) / 3
assert np.allclose(np.linalg.norm(corners, axis=1), 2.0)
assert 0 < 2.0 - np.linalg.norm(centres, axis=1).min() < 2e-3        # chordal tolerance 1e-3
assert abs(mesh.face_area[0] - 4 * math.pi * 4 / 8) < 0.01 and mesh.entity_ids == [7]
n, uv = mesh.shade(np.arange(mesh.triangles), np.full(mesh.triangles, 1 / 3), np.full(mesh.triangles, 1 / 3))
radial = np.einsum("ij,ij->i", n, centres)                           # S_u x S_v points inwards here
assert np.allclose(np.linalg.norm(n, axis=1), 1) and (radial < -1.99).all(), (radial.min(), radial.max())
assert (uv >= 0).all() and (uv <= 1).all()

# ---- trimming: a disc with a square hole on a 100 mm square
angle = np.linspace(0, 2 * math.pi, 257)
disc = {"type": "trimmed_surface", "surface": rect((0, 0, 0), (100, 0, 0), (0, 100, 0)),
        "outer": [polyline(np.column_stack([0.5 + 0.4 * np.cos(angle), 0.5 + 0.4 * np.sin(angle)]))],
        "holes": [[polyline([(0.45, 0.45), (0.55, 0.45), (0.55, 0.55), (0.45, 0.55), (0.45, 0.45)])]]}
mesh = pt_mesh.build([{"id": 1, "geometry": disc}], 1e-3)
exact = math.pi * 40 ** 2 - 100
assert abs(mesh.face_area[0] / exact - 1) < 2e-3, mesh.face_area
texel = mesh.texel_areas(0, 20, 20)                                  # 5 mm texels: (row v, column u)
assert abs(texel.sum() - mesh.face_area[0]) < 1e-6 and texel[0, 0] == 0 and texel[10, 10] == 0
assert abs(texel[5, 10] - 25) < 1e-9 and 0 < texel[10, 1] < 25       # inside; cut by the circle
tri, b1, b2 = mesh.sample(np.array([0]), 5000, np.random.default_rng(0))
p = mesh.v0[tri] + b1[:, None] * mesh.e1[tri] + b2[:, None] * mesh.e2[tri]
r = np.hypot(p[:, 0] - 50, p[:, 1] - 50)
assert r.max() < 40.3 and not ((abs(p[:, 0] - 50) < 4.8) & (abs(p[:, 1] - 50) < 4.8)).any()
assert abs(r.mean() / 26.75 - 1) < 0.03                              # uniform on the disc: ~ 2/3 · 40

# ---- bodies of the geometry kernel (trimmed faces as CAD sends them), if nurbforge is installed
try:
    import nurbforge as nf
    from nfcad import geometry as cad_geometry
except ImportError:
    nf = None
if nf is not None:
    def shell(body):
        faces = []
        for f in body.faces:
            face = {"surface": cad_geometry.from_nurbforge(f.surface)}
            if not f.is_untrimmed:
                face["outer"] = [cad_geometry.from_nurbforge(c) for c in f.outer.curves]
                face["holes"] = [[cad_geometry.from_nurbforge(c) for c in hole.curves] for hole in f.holes]
            faces.append(face)
        return {"type": "shell", "faces": faces}

    plate = nf.boolean(nf.make_box(nf.Vec3(-20, -20, 0), nf.Vec3(40, 40, 10)),
                       nf.make_cylinder(nf.Vec3(0, 0, -5), nf.Vec3(0, 0, 1), 8.0, 20.0), nf.BooleanOp.Difference)
    for body in (nf.make_cylinder(nf.Vec3(0, 0, 0), nf.Vec3(0, 0, 1), 10.0, 30.0), plate):
        mesh = pt_mesh.build([{"id": 1, "geometry": shell(body)}], 0.01)
        assert abs(mesh.face_area.sum() / body.area() - 1) < 2e-3, (mesh.face_area.sum(), body.area())
        assert (mesh.mask_res > 0).sum() >= 2                            # trimmed faces among them

# ---- BVH against testing every triangle
rng = np.random.default_rng(3)
v0 = rng.uniform(-10, 10, (300, 3))
e1, e2 = rng.normal(0, 2, (300, 3)), rng.normal(0, 2, (300, 3))
e1[:6] *= 15                                                         # a few large ones among the small
e2[:6] *= 15
bvh = pt_bvh.BVH(v0, e1, e2)
assert bvh.count[bvh.left < 0].sum() == 300 and sorted(bvh.order) == list(range(300)) and bvh.leaf <= pt_bvh.LEAF
inner = bvh.left >= 0                                                # every box holds its children's boxes
for child in (bvh.left[inner], bvh.right[inner]):
    assert (bvh.bmin[child] >= bvh.bmin[inner] - 1e-12).all() and (bvh.bmax[child] <= bvh.bmax[inner] + 1e-12).all()
same = pt_bvh.BVH(np.tile(v0[:1], (40, 1)), np.tile(e1[:1], (40, 1)), np.tile(e2[:1], (40, 1)))      # 40 times one
assert same.count[same.left < 0].sum() == 40 and same.leaf <= pt_bvh.LEAF                            # triangle
o = rng.uniform(-15, 15, (500, 3))
d = rng.normal(size=(500, 3))
d /= np.linalg.norm(d, axis=1, keepdims=True)
t, tri, b1, b2 = bvh.intersect(o, d)
best = np.full(500, np.inf)
for k in range(300):                                                 # Möller–Trumbore, one triangle at a time
    pv = np.cross(d, e2[k])
    det = pv @ e1[k]
    sv_ = o - v0[k]
    u = np.einsum("ij,ij->i", sv_, pv) / det
    q = np.cross(sv_, e1[k])
    v = np.einsum("ij,ij->i", d, q) / det
    tk = (q @ e2[k]) / det
    ok = (u >= 0) & (v >= 0) & (u + v <= 1) & (tk > 0)
    best = np.where(ok & (tk < best), tk, best)
assert np.array_equal(np.isfinite(best), tri >= 0) and np.allclose(t[tri >= 0], best[tri >= 0])
hit = tri >= 0
assert np.allclose(o[hit] + t[hit, None] * d[hit], v0[tri[hit]] + b1[hit, None] * e1[tri[hit]] + b2[hit, None] * e2[tri[hit]])
assert np.array_equal(bvh.occluded(o, d * 1000.0), hit)
assert not bvh.occluded(o[hit], d[hit] * (t[hit, None] * 0.999)).any()

# ---- a point source 50 mm above a black plane: E = Phi / (4 pi) · h / (h² + r²)^(3/2)
plane = rect((-100, -100, 0), (200, 0, 0), (0, 200, 0))
scene = scene_of([plane], [BLACK], [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))])
sensor = pt_scene.TexelSensor(scene, [0], 10)
def solid_angle(a, b, height):
    """Of the rectangle |x| < a, |y| < b seen from the point at `height` above its centre."""
    return 4 * math.atan(a * b / (height * math.sqrt(a * a + b * b + height * height)))


for method in pt_integrator.METHODS:
    flux = values(scene, sensor, method, 60_000)                     # 20 mm texels
    assert abs(flux.sum() / (solid_angle(100, 100, 50) / (4 * math.pi)) - 1) < 0.02, (method, flux.sum())
    centre = flux.reshape(10, 10)[4:6, 4:6].sum() / (solid_angle(20, 20, 50) / (4 * math.pi))
    assert abs(centre - 1) < 0.08, (method, centre)
    assert np.allclose(sensor.texel_area, 400)

# ---- detectors: the light passes them. Two between the source and a white floor measure the solid
# angles they fill (also what the floor sends back up); the floor gets what it gets without them
floor = rect((-100, -100, 0), (200, 0, 0), (0, 200, 0))
upper, lower = rect((-25, -25, 25), (50, 0, 0), (0, 50, 0)), rect((-10, -10, 10), (20, 0, 0), (0, 20, 0))
source = [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))]
plain = scene_of([floor], [BLACK], source)
scene = scene_of([floor, upper, lower], [BLACK, DETECTOR, DETECTOR], source)
assert scene.detectors is not None and scene.hit(np.array([[0.0, 0, 50]]), np.array([[0.0, 0, -1]]))[0][0] == 50
sensor = pt_scene.TexelSensor(scene, [0, 1, 2], 2)
assert sensor.crossed and not pt_scene.TexelSensor(plain, [0], 2).crossed
expected = [solid_angle(100, 100, 50), solid_angle(25, 25, 25), solid_angle(10, 10, 40)]
for method in pt_integrator.METHODS:
    flux = values(scene, sensor, method, 40_000).reshape(3, 4).sum(axis=1) * 4 * math.pi
    assert (np.abs(flux / expected - 1) < [0.05, 0.05, 0.2]).all(), (method, flux / expected)    # (few samples
                                                                                                # on the small one)
scene = scene_of([floor, upper], [WHITE, DETECTOR], source)          # the floor reflects 0.6: more passes
sensor = pt_scene.TexelSensor(scene, [1], 2)
reference = values(scene, sensor, "light", 80_000).sum()
assert reference * 4 * math.pi > 1.1 * expected[1]
for method in ("path", "bidir"):
    got = values(scene, sensor, method, 40_000).sum()
    assert abs(got / reference - 1) < 0.04, (method, got, reference)
only = scene_of([upper], [DETECTOR], source)                         # nothing but a detector
flux = values(only, pt_scene.TexelSensor(only, [0], 2), "light", 20_000).sum() * 4 * math.pi
assert only.bvh is None and abs(flux / expected[1] - 1) < 0.05
camera = pt_scene.Camera((0, 0, 200), (0, 0, 0), (0, 1, 0), 20.0, 2, 2)      # and a camera does not see them
seen = [values(sc, camera, "path", 4_000, 2).mean() for sc in (scene_of([floor], [WHITE], source), scene)]
assert abs(seen[1] / seen[0] - 1) < 1e-9
try:
    scene_of([floor, upper], [BLACK, DETECTOR], [pt_scene.SourceSpec("a", 1.0, entities=(1,))])
    raise AssertionError("not refused")
except ValueError as e:
    assert "detector cannot be a source" in str(e), e

# ---- a closed diffuse box with a point source inside: what arrives is Phi / (1 − rho)
scene = scene_of([box((0, 0, 0), (100, 100, 100))], [WHITE], [pt_scene.SourceSpec("p", 1.0, points=((50, 50, 50),))], (0,))
assert scene.flipped == []
sensor = pt_scene.TexelSensor(scene, range(6), 2)
for method in pt_integrator.METHODS:                                 # paths of up to 12 segments: 1 + rho + … + rho^11
    total = values(scene, sensor, method, 20_000, 12).sum()
    assert abs(total / ((1 - 0.6 ** 12) / 0.4) - 1) < 0.03, (method, total)

# ---- closed bodies are oriented: two faces of a box turned the wrong way are turned back
turned = box((0, 0, 0), (10, 20, 30))
for k in (1, 4):
    surface = turned["faces"][k]["surface"]
    surface["points"] = [float(c) for c in np.asarray(surface["points"]).reshape(2, 2, 3).transpose(1, 0, 2).ravel()]
scene = scene_of([turned], [WHITE], [pt_scene.SourceSpec("p", 1.0, points=((5, 5, 5),))], (0,))
assert scene.flipped == [1, 4]
outward = scene.mesh.v0 + (scene.mesh.e1 + scene.mesh.e2) / 3 - [5, 10, 15]
assert (np.einsum("ij,ij->i", outward, scene.mesh.ng) > 0).all()

# ---- a glass plate (n = 1.5) in a narrow beam: T = (1 − R) / (1 + R) with R = 0.04, all orders
scene = scene_of([box((-50, -50, 0), (50, 50, 10)), rect((-1, -1, -20), (2, 0, 0), (0, 2, 0)),
                  rect((-40, -40, 30), (80, 0, 0), (0, 80, 0))], [GLASS, BLACK, BLACK],
                 [pt_scene.SourceSpec("beam", 1.0, 0.5, "front", entities=(1,))], (0,))
sensor = pt_scene.TexelSensor(scene, [7], 4)
for method in ("light", "bidir"):
    total = values(scene, sensor, method, 30_000, 30).sum()
    assert abs(total - 0.96 / 1.04) < 0.01, (method, total)

# ---- the same plate absorbing 0.05 / mm: T = (1 − R)² a / (1 − R² a²) with a = exp(−0.05 · 10)
scene = scene_of([box((-50, -50, 0), (50, 50, 10)), rect((-1, -1, -20), (2, 0, 0), (0, 2, 0)),
                  rect((-40, -40, 30), (80, 0, 0), (0, 80, 0))], [TINTED, BLACK, BLACK],
                 [pt_scene.SourceSpec("beam", 1.0, 0.5, "front", entities=(1,))], (0,))
inner = math.exp(-0.5)
total = values(scene, pt_scene.TexelSensor(scene, [7], 4), "light", 30_000, 30).sum()
assert abs(total - 0.96 ** 2 * inner / (1 - 0.04 ** 2 * inner ** 2)) < 0.01, total

# ---- a diffusing sheet (reflects 0.3, lets 0.6 through) between a lamp and the floor of a closed box
scene = scene_of([box((0, 0, 0), (100, 100, 100)), rect((0.5, 0.5, 50), (99, 0, 0), (0, 99, 0)),
                  rect((40, 40, 80), (0, 20, 0), (20, 0, 0))], [WHITE, SHEET, BLACK],
                 [pt_scene.SourceSpec("a", 1.0, 90, "front", entities=(2,))], (0,))
sensor = pt_scene.TexelSensor(scene, [0, 6], 2)                      # the floor and the sheet
reference = values(scene, sensor, "light", 40_000, 6)
assert 0.2 < reference[:4].sum() < reference[4:].sum()
for method in ("path", "bidir"):
    got = values(scene, sensor, method, 20_000, 6)
    assert abs(got[:4].sum() / reference[:4].sum() - 1) < 0.06, (method, got[:4].sum(), reference[:4].sum())
    assert abs(got[4:].sum() / reference[4:].sum() - 1) < 0.06, (method, got[4:].sum(), reference[4:].sum())

# ---- an area source in a box with a glossy plate and a mirror wall: the methods agree
scene = scene_of([rect((-100, -100, 0), (200, 0, 0), (0, 200, 0)), rect((-100, -100, 0), (0, 200, 0), (0, 0, 100)),
                  rect((100, -100, 0), (0, 0, 100), (0, 200, 0)), rect((-20, -20, 90), (40, 0, 0), (0, 40, 0))],
                 [WHITE, MIRROR, GLOSSY, BLACK], [pt_scene.SourceSpec("a", 1.0, 60, "back", entities=(3,))])
sensor = pt_scene.TexelSensor(scene, [0, 2], 3)
reference = values(scene, sensor, "light", 150_000)
assert 0.8 < reference.sum() < 1.2
for method in ("path", "bidir"):
    got = values(scene, sensor, method, 60_000)
    assert abs(got.sum() / reference.sum() - 1) < 0.03, (method, got.sum(), reference.sum())
    assert np.sqrt(np.mean((got / reference - 1) ** 2)) < 0.15, method

# ---- camera: a Lambertian emitter of 1 W on 20 x 20 mm has the radiance 1 / (pi · 400) W/(mm² sr)
scene = scene_of([rect((-10, -10, 0), (20, 0, 0), (0, 20, 0))], [BLACK], [pt_scene.SourceSpec("a", 1.0, 90, "front", entities=(0,))])
camera = pt_scene.Camera((0, 0, 100), (0, 0, 0), (0, 1, 0), 5.0, 4, 4)
for method in pt_integrator.METHODS:                                 # (light tracing: few connections land in 5°)
    image = values(scene, camera, method, 20_000, 3)
    assert abs(image.mean() * math.pi * 400 - 1) < (0.15 if method == "light" else 0.03), (method, image.mean())
camera = pt_scene.Camera((0, 0, -100), (0, 0, 0), (0, 1, 0), 5.0, 4, 4)       # from behind: dark
assert values(scene, camera, "path", 2_000, 3).max() == 0

# ---- camera: a diffuse wall under a point source, L = rho · E / pi; pixel (i, j): i right, j up
wall = rect((-100, -100, 0), (200, 0, 0), (0, 200, 0))
scene = scene_of([wall], [WHITE], [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))])
camera = pt_scene.Camera((0, 0, 200), (0, 0, 0), (0, 1, 0), 2.0, 4, 4)
exact = 0.6 / math.pi / (4 * math.pi * 50 ** 2)
for method in ("path", "bidir"):
    image = values(scene, camera, method, 40_000, 2)
    assert abs(image.mean() / exact - 1) < 0.02, (method, image.mean() / exact)
camera = pt_scene.Camera((0, 0, 200), (0, 0, 0), (0, 1, 0), 40.0, 4, 4)       # wide, for light tracing
reference = values(scene, camera, "path", 40_000, 2)
for method in ("light", "bidir"):
    image = values(scene, camera, method, 80_000, 2)
    assert abs(image.sum() / reference.sum() - 1) < 0.06, (method, image.sum() / reference.sum())
scene = scene_of([wall], [WHITE], [pt_scene.SourceSpec("p", 1.0, points=((60, 0, 20),))])     # light at +x
camera = pt_scene.Camera((0, 0, 300), (0, 0, 0), (0, 1, 0), 30.0, 2, 2)      # up = +y: right = +x
image = values(scene, camera, "path", 20_000, 2).reshape(2, 2)
assert image[:, 1].sum() > 3 * image[:, 0].sum() and abs(image[0].sum() / image[1].sum() - 1) < 0.1

# ---- a curve as a source: a thin glowing wire along z, intensity Phi sin(theta) / pi². Detectors
# across the wire and on its axis against the integral over the wire; everything arrives in a box
wire = pt_scene.SourceSpec("wire", 1.0, curves=(np.array([[0.0, 0, -5], [0, 0, 0], [0, 0, 5]]),))
side, top = rect((50, -10, -10), (0, 20, 0), (0, 0, 20)), rect((-10, -10, 50), (20, 0, 0), (0, 20, 0))
scene = scene_of([box((-100, -100, -100), (100, 100, 100)), side, top], [BLACK, DETECTOR, DETECTOR], [wire], (0,))
sensor = pt_scene.TexelSensor(scene, range(8), 1)
grid = (np.arange(20) + 0.5) - 10                                    # 1 mm steps over a detector
along = (np.arange(40) + 0.5) / 4 - 5                                # along the wire
expected = []
for point, normal in (((50.0, grid[:, None, None], grid[None, :, None]), (1, 0, 0)),
                      ((grid[:, None, None], grid[None, :, None], 50.0), (0, 0, 1))):
    dx, dy, dz = point[0] - 0.0, point[1] - 0.0, point[2] - along[None, None, :]
    dist = np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
    sin_theta = np.sqrt(dx ** 2 + dy ** 2) / dist                    # to the wire
    cos_in = np.abs(dx * normal[0] + dz * normal[2]) / dist          # on the detector
    expected.append(float((sin_theta * cos_in / dist ** 2 / math.pi ** 2).mean() * 400))
assert expected[0] > 4 * expected[1]                                  # little along the wire
assert abs(values(scene, sensor, "light", 20_000, 2)[:6].sum() - 1) < 0.02
sensor = pt_scene.TexelSensor(scene, [6, 7], 1)
for method, samples in (("light", 100_000), ("path", 20_000), ("bidir", 20_000)):
    flux = values(scene, sensor, method, samples, 2)
    assert abs(flux[0] / expected[0] - 1) < 0.1 and abs(flux[1] / expected[1] - 1) < 0.3, (method, flux, expected)
try:
    scene_of([side], [BLACK], [pt_scene.SourceSpec("mixed", 1.0, points=((0, 0, 0),), curves=wire.curves)])
    raise AssertionError("not refused")
except ValueError as e:
    assert "different kinds" in str(e), e

# ---- photon mapping (camera): the lit wall; on faces it is light tracing
scene = scene_of([wall], [WHITE], [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))])
camera = pt_scene.Camera((0, 0, 200), (0, 0, 0), (0, 1, 0), 2.0, 4, 4)
out = pt_integrator.render(scene, camera, "photon", 80_000, 2, seed=SEED)
assert abs(out["values"].mean() / exact - 1) < 0.12 and out["passes"] == 16 and 1 < out["radius"] < 20, out
assert pt_integrator.render(scene, camera, "photon", 5_000, 2, seed=SEED, radius=5.0)["radius"] == 5.0    # one pass
sensor = pt_scene.TexelSensor(scene, [0], 4)
assert np.array_equal(values(scene, sensor, "photon", 5_000), values(scene, sensor, "light", 5_000))

# ---- photon mapping: a glass plate between the source and the floor, the camera looks through it.
# No connection can make these paths (specular on both sides of the floor): the other methods see
# nothing. The floor's radiance is rho · E / pi with E = T · I / h'², the source seen 10 (1 − 1/n)
# nearer through the plate, and the plate takes its share again on the way to the camera
scene = scene_of([wall, box((-200, -200, 20), (200, 200, 30))], [WHITE, GLASS],
                 [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))], (1,))
camera = pt_scene.Camera((0, 0, 45), (0, 0, 0), (0, 1, 0), 6.0, 4, 4)
through = 0.96 / 1.04
expected = 0.6 / math.pi * through / (4 * math.pi * (50 - 10 / 3) ** 2) * through
image = values(scene, camera, "photon", 60_000, 8)
assert abs(image.mean() / expected - 1) < 0.15, image.mean() / expected
for method in ("light", "path", "bidir"):
    assert values(scene, camera, method, 4_000, 8).max() == 0, method

# ---- photon mapping: the lit wall seen in a mirror, as path tracing sees it
scene = scene_of([wall, rect((-100, 100, 0), (200, 0, 0), (0, 0, 150))], [WHITE, MIRROR],
                 [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))])
camera = pt_scene.Camera((0, -50, 80), (0, 100, 60), (0, 0, 1), 20.0, 4, 4)
reference = values(scene, camera, "path", 40_000, 6).mean()
assert abs(values(scene, camera, "photon", 80_000, 6).mean() / reference - 1) < 0.1

# ---- wavelengths: a beam of two lines falls at 60° through a plate of glass that disperses
# (n_d = 1.5, Abbe number 10); a detector below shows each line where Snell's law puts it
angle = math.radians(60)
way = np.array([math.sin(angle), 0.0, -math.cos(angle)])            # the beam
start = np.array([-60.0, 0.0, 30.0])
across = np.array([-way[2], 0.0, way[0]])                            # in the beam's cross-section: y x across = way
beam = rect(start - np.array([0.0, 1.0, 0.0]) - across, (0, 2, 0), 2 * across)
strong = pt_bsdf.Materials.from_rows([{"name": "flint", "kind": "glass", "ior": 1.5, "abbe": 10.0},
                                      {"name": "black", "kind": "absorber"}, {"name": "detector", "kind": "detector"}])
mesh = pt_mesh.build([{"id": k + 1, "geometry": g} for k, g in enumerate(
    [box((-300, -300, 0), (300, 300, 20)), beam, rect((-40, -10, -10), (80, 0, 0), (0, 20, 0))])], 1e-3)
scene = pt_scene.Scene(mesh, strong, np.array([0, 1, 2]),
                       [pt_scene.SourceSpec("beam", 1.0, 0.5, "front", entities=(1,), spectrum=((450, 1), (650, 3)))], (0,))
assert list(scene.wavelengths) == [450, 650] and np.allclose(scene.channel_prob, [0.25, 0.75])
index = strong.ior_table[0]
assert index[0] > 1.5 > index[1] and abs((index[0] - index[1]) - 0.5 / 10 * (1 / 0.45 ** 2 - 1 / 0.65 ** 2)
                                         / (1 / 0.48613 ** 2 - 1 / 0.65627 ** 2)) < 1e-12
assert np.allclose(strong.wavelengths([587.56]), [[1.5], [1.5], [1.5]])
strong.wavelengths(scene.wavelengths)
sensor = pt_scene.TexelSensor(scene, [7], 160)                       # 0.5 mm along x
assert sensor.size[0] == (160, 40)
out = pt_integrator.render(scene, sensor, "light", 40_000, 3, seed=SEED)   # 3 segments: no second pass inside
x = -40 + (np.arange(160) + 0.5) * 0.5
straight = start[0] + (start[2] + 10) * math.tan(angle)
for k in range(2):
    per_x = out["channels"][k].reshape(40, 160).sum(axis=0)
    expected = straight - 20 * (math.tan(angle) - math.sin(angle) / math.sqrt(index[k] ** 2 - math.sin(angle) ** 2))
    assert abs((per_x * x).sum() / per_x.sum() - expected) < 0.08, (k, (per_x * x).sum() / per_x.sum(), expected)
assert abs(out["channels"][1].sum() / out["channels"][0].sum() - 3) < 0.25 and np.allclose(out["channels"].sum(axis=0), out["values"])

# ---- wavelengths: two lamps of different colour over a white floor – every method gives each
# wavelength its lamp's light (paths that end on a source count by that source's spectrum)
lamps = [rect((-60, -10, 80), (0, 20, 0), (20, 0, 0)), rect((40, -10, 80), (0, 20, 0), (20, 0, 0))]
scene = scene_of([wall] + lamps, [WHITE, BLACK, BLACK],
                 [pt_scene.SourceSpec("blue", 1.0, 90, "front", entities=(1,), spectrum=((450, 1),)),
                  pt_scene.SourceSpec("red", 3.0, 90, "front", entities=(2,), spectrum=((650, 2), (450, 1)))])
sensor = pt_scene.TexelSensor(scene, [0], 2)                         # 2 x 2 texels: left and right half
light = pt_integrator.render(scene, sensor, "light", 80_000, 4, seed=SEED)["channels"]
assert light[1].reshape(2, 2)[:, 1].sum() > 1.5 * light[1].reshape(2, 2)[:, 0].sum()        # red: at +x
assert abs(light[0].sum() / light[1].sum() - 1) < 0.05                                      # 1 + 1 W blue, 2 W red
for method in ("path", "bidir"):
    got = pt_integrator.render(scene, sensor, method, 40_000, 4, seed=SEED)["channels"]
    assert np.allclose(got.reshape(2, 2, 2).sum(axis=1) / light.reshape(2, 2, 2).sum(axis=1), 1, atol=0.06), method
camera = pt_scene.Camera((0, 0, 20), (0, 0, 80), (0, 1, 0), 120.0, 2, 1)     # looks up: right is -x, so
seen = pt_integrator.render(scene, camera, "path", 20_000, 2, seed=SEED)["channels"]       # pixel 0 holds the red
bidir = pt_integrator.render(scene, camera, "bidir", 20_000, 2, seed=SEED)["channels"]     # lamp, pixel 1 the blue
radiance = 1 / (math.pi * 400)                                       # of 1 W: blue lamp, and each line of the red
share = 400 / 60 ** 2 / (4 * math.tan(math.radians(60)) ** 2 / 4)    # of a pixel, roughly (lamp area / film)
for image in (seen, bidir):
    assert image[1, 1] == 0 and image[1, 0] > 0                      # 650 nm: only the red lamp
    assert abs(image[1, 0] / image[0, 0] - 2) < 0.3 and abs(image[0, 1] / image[0, 0] - 1) < 0.3
    assert 0.3 < image[0, 1] / (radiance * share) < 1.5
assert pt_setup.parse_spectrum("450:1, 550: 2;650") == ((450.0, 1.0), (550.0, 2.0), (650.0, 1.0))
assert pt_setup.parse_spectrum("") == ((550.0, 1.0),)

# ---- samples are spread evenly: every texel of a sensor gets the points its area asks for (also on
# a trimmed face, where they stay inside), every pixel its rays – no scatter of the numbers
scene = scene_of([disc], [BLACK], [pt_scene.SourceSpec("p", 1.0, points=((50, 50, 40),))])
sensor = pt_scene.TexelSensor(scene, [0], 20)
tri, b1, b2, chosen = sensor.points(20_000, np.random.default_rng(SEED))
assert (tri >= 0).mean() > 0.999                                     # (none found: in slivers of texels)
chosen, tri, b1, b2 = chosen[tri >= 0], tri[tri >= 0], b1[tri >= 0], b2[tri >= 0]
_, uv = scene.mesh.shade(tri, b1, b2)
assert (sensor.texel(tri, uv) == chosen).mean() > 0.999              # (a point exactly on a border may differ)
counts = np.bincount(chosen, minlength=sensor.count)
asked = 20_000 * sensor.texel_area / sensor.area
assert np.abs(counts - asked).max() < 3 and np.abs(counts - asked).mean() < 0.4, np.abs(counts - asked).max()
assert np.sqrt(asked.mean()) > 6                                     # (numbers that scatter would differ by ~7)
p = scene.mesh.v0[tri] + b1[:, None] * scene.mesh.e1[tri] + b2[:, None] * scene.mesh.e2[tri]
r = np.hypot(p[:, 0] - 50, p[:, 1] - 50)
assert r.max() < 40.3 and not ((abs(p[:, 0] - 50) < 4.8) & (abs(p[:, 1] - 50) < 4.8)).any()
assert abs(r.mean() / 27.13 - 1) < 0.01, r.mean()                    # mean radius of the disc without the hole
turned_patch = pt_mesh.build([{"id": 1, "geometry": sphere_patch(2.0)}], 1e-3)       # a curved face, also turned
for flip in (False, True):
    if flip:
        turned_patch.flip_faces([0])
    u, v = np.random.default_rng(1).random(500) * 0.9, np.random.default_rng(2).random(500)   # (not at the pole)
    t, c1, c2, density = turned_patch.locate(0, u, v)
    _, back = turned_patch.shade(t, c1, c2)
    assert (t >= 0).all() and np.allclose(back, np.column_stack([u, v]), atol=1e-9)
    assert 0 < density.min() and density.max() <= turned_patch.grids[0].max_density * (1 + 1e-12)
    assert abs(turned_patch.cell_density(0).max() - turned_patch.grids[0].max_density) < 1e-9
pixels = pt_scene.Camera((0, 0, 200), (0, 0, 0), (0, 1, 0), 20.0, 10, 10).sample(1_000, np.random.default_rng(SEED))["texel"]
assert np.array_equal(np.bincount(pixels, minlength=100), np.full(100, 10))
strata = pt_mesh.stratified(8, np.random.default_rng(SEED))
assert sorted((strata * 8).astype(int)) == list(range(8))
scene = scene_of([wall], [BLACK], [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))])
sensor = pt_scene.TexelSensor(scene, [0], 4)                         # 2 500 points per texel: their number alone
smooth = pt_integrator.render(scene, sensor, "path", 40_000, 2, seed=SEED, batch=5_000)     # would scatter by 2 %
assert pt_setup.typical_noise(smooth["values"], smooth["error"]) < 0.008

# ---- materials that depend on the wavelength: a closed box whose paint reflects 0.2 at 450 nm and 0.6
# at 650 nm, a source with both lines – each wavelength arrives as its own series 1 + rho + rho² + …
paints = pt_bsdf.Materials.from_rows([
    {"name": "paint", "kind": "diffuse", "spectrum": ((650, 0.6), (450, 0.2))},
    {"name": "tinted", "kind": "glass", "ior": 1.5, "spectrum": ((450, 0.05), (650, 0.0))},
    {"name": "black", "kind": "absorber"}])
assert np.allclose(paints.wavelengths([400, 450, 550, 650, 700])[0], 1.5)
assert np.allclose(paints.rho_table[0], [0.2, 0.2, 0.4, 0.6, 0.6]) and np.allclose(paints.absorb_table[1], [0.05, 0.05, 0.025, 0, 0])
lines = pt_scene.SourceSpec("p", 1.0, points=((50, 50, 50),), spectrum=((450, 1), (650, 1)))
colour_mesh = pt_mesh.build([{"id": 1, "geometry": box((0, 0, 0), (100, 100, 100))}], 1e-3)
coloured = pt_scene.Scene(colour_mesh, paints, np.array([0]), [lines], (0,))
colour_sensor = pt_scene.TexelSensor(coloured, range(6), 2)
series = [0.5 * (1 - rho ** 12) / (1 - rho) for rho in (0.2, 0.6)]
for method in pt_integrator.METHODS[:3]:
    got = pt_integrator.render(coloured, colour_sensor, method, 20_000, 12, seed=SEED)["channels"].sum(axis=1)
    assert np.allclose(got / series, 1, atol=0.04), (method, got / series)
colour_mesh = pt_mesh.build([{"id": k + 1, "geometry": g} for k, g in enumerate(
    [box((0, 0, 0), (100, 100, 100)), rect((-100, -100, -1), (300, 0, 0), (0, 300, 0))])], 1e-3)
coloured = pt_scene.Scene(colour_mesh, paints, np.array([0, 0]), [pt_scene.SourceSpec("p", 1.0, points=((50, 50, 150),),
                                                                            spectrum=((450, 1), (650, 1)))], (0,))
colour_camera = pt_scene.Camera((50, 50, 400), (50, 50, 100), (0, 1, 0), 5.0, 2, 2)       # the top of the box, lit directly
for method in ("path", "photon"):
    seen = pt_integrator.render(coloured, colour_camera, method, 40_000, 2, seed=SEED)["channels"].mean(axis=1)
    assert abs(seen[0] / seen[1] - 0.2 / 0.6) < 0.04, (method, seen)
# tinted glass that absorbs 0.05 / mm at 450 nm and nothing at 650 nm: the plate in the beam again
colour_mesh = pt_mesh.build([{"id": k + 1, "geometry": g} for k, g in enumerate(
    [box((-50, -50, 0), (50, 50, 10)), rect((-1, -1, -20), (2, 0, 0), (0, 2, 0)), rect((-40, -40, 30), (80, 0, 0), (0, 80, 0))])], 1e-3)
coloured = pt_scene.Scene(colour_mesh, paints, np.array([1, 2, 2]),
                       [pt_scene.SourceSpec("beam", 1.0, 0.5, "front", entities=(1,), spectrum=((450, 1), (650, 1)))], (0,))
got = pt_integrator.render(coloured, pt_scene.TexelSensor(coloured, [7], 2), "light", 40_000, 30, seed=SEED)["channels"].sum(axis=1)
assert np.allclose(got * 2, [0.96 ** 2 * inner / (1 - 0.04 ** 2 * inner ** 2), 0.96 / 1.04], atol=0.015), got * 2
for bad, why in (({"name": "x", "kind": "diffuse", "transmittance": 0.5, "spectrum": ((500, 0.6),)}, "0 … 1"),
                 ({"name": "x", "kind": "glass", "spectrum": ((500, -1.0),)}, "not negative")):
    try:
        pt_bsdf.Materials.from_rows([bad])
        raise AssertionError("not refused")
    except ValueError as e:
        assert why in str(e), e
assert pt_setup.parse_values("450:0.2; 650 : 0.9,") == ((450.0, 0.2), (650.0, 0.9)) and pt_setup.parse_values("") == ()
try:
    pt_setup.parse_values("450, 650")
    raise AssertionError("not refused")
except ValueError as e:
    assert "values at wavelengths" in str(e), e

# ---- samples steered by weights: any shares of the texels / pixels give the same values – here
# shares that differ by up to a factor of 100, on the plane under the point source
shares = np.random.default_rng(5).uniform(0.01, 1.0, 16)
for method in ("path", "bidir"):
    even = pt_integrator.render(scene, sensor, method, 40_000, 2, seed=SEED)["values"]
    skew = pt_integrator.render(scene, sensor, method, 40_000, 2, seed=SEED, weights=shares)["values"]
    assert abs(skew.sum() / even.sum() - 1) < 0.01 and np.allclose(skew / even, 1, atol=0.06), (method, skew / even)
    assert np.allclose(sensor.prob, shares / shares.sum())
lit = scene_of([wall, rect((-100, 100, 0), (200, 0, 0), (0, 0, 150))], [WHITE, WHITE],
               [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))])                  # with a second wall: light
both = pt_scene.TexelSensor(lit, [0, 1], 3)                                            # comes around, t = 0 counts
reference = pt_integrator.render(lit, both, "light", 150_000, 4, seed=SEED)["values"]
shares = np.random.default_rng(6).uniform(0.02, 1.0, both.count)
for method in ("path", "bidir"):
    skew = pt_integrator.render(lit, both, method, 60_000, 4, seed=SEED, weights=shares)["values"]
    assert abs(skew.sum() / reference.sum() - 1) < 0.02 and np.allclose(skew / reference, 1, atol=0.12), (method, skew / reference)
camera = pt_scene.Camera((0, 0, 200), (0, 0, 0), (0, 1, 0), 40.0, 4, 4)
shares = np.random.default_rng(7).uniform(0.01, 1.0, 16)
even = pt_integrator.render(lit, camera, "path", 40_000, 3, seed=SEED)["values"]
for method in ("path", "bidir", "photon"):
    skew = pt_integrator.render(lit, camera, method, 40_000, 3, seed=SEED, weights=shares)["values"]
    assert np.allclose(skew / even, 1, atol=0.1), (method, skew / even)
assert np.allclose(camera.prob, shares / shares.sum())

# ---- adaptive sampling: a camera that sees the lit floor in a small part of its image and nothing
# around it moves its rays to the floor – the same image, less noise
half = pt_scene.Camera((0, 0, 300), (0, 0, 0), (0, 1, 0), 110.0, 16, 8)
plain = pt_integrator.render(lit, half, "path", 120_000, 3, seed=SEED, batch=10_000)
steered = pt_integrator.render(lit, half, "path", 120_000, 3, seed=SEED, batch=10_000, adaptive=True)
seen = plain["values"] > 0.1 * plain["values"].max()
assert 15 <= seen.sum() <= 40 and half.prob[seen].sum() > 3 * seen.mean()          # the lit pixels get more


def same(a: dict, b: dict, where) -> bool:
    """Two results agree within their errors (six standard errors and 2 %)."""
    return bool(np.all(np.abs(a["values"] - b["values"])[where]
                       < (6 * np.hypot(a["error"], b["error"]) + 0.02 * b["values"])[where]))


assert same(steered, plain, seen)
less = (steered["error"][seen] ** 2).sum() / (plain["error"][seen] ** 2).sum()      # of the variance is left
assert less < 0.8, less
plain = pt_integrator.render(lit, both, "bidir", 80_000, 4, seed=SEED, batch=10_000, adaptive=True)["values"]
assert abs(plain.sum() / reference.sum() - 1) < 0.02 and np.allclose(plain / reference, 1, atol=0.1)
light_only = pt_integrator.render(lit, both, "light", 40_000, 4, seed=SEED, batch=10_000, adaptive=True)
assert np.allclose(both.prob, both.texel_area / both.area)            # light tracing draws nothing from the sensor

# ---- the standard error from the spread of the batches: of the right size, falls with sqrt(N)
scene = scene_of([wall], [BLACK], [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))])
sensor = pt_scene.TexelSensor(scene, [0], 4)
runs = [pt_integrator.render(scene, sensor, "light", 40_000, 2, seed=SEED + k, batch=5_000) for k in range(6)]
assert pt_integrator.render(scene, sensor, "light", 4_000, 2, seed=SEED)["error"] is None       # one batch
scatter = np.std([r["values"] for r in runs], axis=0, ddof=1)        # what six runs really differ by
stated = np.mean([r["error"] for r in runs], axis=0)
assert np.all(stated > 0) and abs(np.median(stated / scatter) - 1) < 0.5, stated / scatter
more = pt_integrator.render(scene, sensor, "light", 160_000, 2, seed=SEED, batch=10_000)["error"]
assert abs(np.median(stated / more) - 2) < 0.6
assert 0.01 < pt_setup.typical_noise(runs[0]["values"], runs[0]["error"]) < 0.05
assert math.isnan(pt_setup.typical_noise(runs[0]["values"], None))
camera = pt_scene.Camera((0, 0, 200), (0, 0, 0), (0, 1, 0), 20.0, 2, 2)
assert pt_integrator.render(scene_of([wall], [WHITE], [pt_scene.SourceSpec("p", 1.0, points=((0, 0, 50),))]),
                            camera, "photon", 80_000, 2, seed=SEED)["error"].shape == (4,)

# ---- several processes: the same jobs whatever the number of processes, so the same result; a
# small computation stays in this process; Cancel ends the workers
import pt_parallel  # noqa: E402

assert pt_parallel.process_count(3) == 3 and 1 <= pt_parallel.process_count(0) <= 4
assert pt_parallel.job_size(1_000) == 20_000 and pt_parallel.job_size(10 ** 9) == 200_000
exact = solid_angle(100, 100, 50) / (4 * math.pi)
two = pt_parallel.render(scene, sensor, "light", 60_000, 2, seed=SEED, processes=2)
three = pt_parallel.render(scene, sensor, "light", 60_000, 2, seed=SEED, processes=3)
assert two["processes"] == 2 and three["processes"] == 3 and two["samples"] == 60_000
assert np.allclose(two["values"], three["values"]) and np.allclose(two["error"], three["error"])
assert abs(two["values"].sum() / exact - 1) < 0.02
assert 0.6 < np.median(two["error"] / more) < 4                      # about sqrt(160 / 60), from three jobs only
small = pt_parallel.render(scene, sensor, "light", 30_000, 2, seed=SEED, processes=4)
assert small["processes"] == 1 and np.array_equal(small["values"], values(scene, sensor, "light", 30_000, 2))
calls = []
steered = pt_parallel.render(lit, half, "path", 160_000, 3, seed=SEED, processes=2, adaptive=True)   # 8 jobs, 4 pilot
again = pt_parallel.render(lit, half, "path", 160_000, 3, seed=SEED, processes=3, adaptive=True)
assert np.allclose(steered["values"], again["values"]) and steered["samples"] == 160_000
whole = pt_integrator.render(lit, half, "path", 80_000, 3, seed=SEED)
assert same(steered, whole, whole["values"] > 0.1 * whole["values"].max()) and np.allclose(half.prob, 1 / 128)
stopped = pt_parallel.render(scene, sensor, "bidir", 4_000_000, 6, seed=SEED, processes=2,
                             cancelled=lambda: calls.append(1) or len(calls) > 2)
assert stopped["samples"] < 4_000_000
parts = [{"values": np.array([1.0, 3.0]), "channels": np.array([[1.0, 3.0]]), "error": None, "samples": 10, "rays": 5},
         {"values": np.array([3.0, 3.0]), "channels": np.array([[3.0, 3.0]]), "error": None, "samples": 30, "rays": 7}]
whole = pt_parallel.combine(parts)
assert np.allclose(whole["values"], [2.5, 3.0]) and whole["samples"] == 40 and whole["rays"] == 12
assert whole["error"][0] > 0 and whole["error"][1] == 0

# ---- the model and the panel -> scene; the plugin's actions with a stand-in for CAD
params = {"materials": pt_setup.DEFAULT_MATERIALS, "default_material": "white", "sources": pt_setup.DEFAULT_SOURCES,
          "tolerance": 0.01}
model = [
    {"id": 11, "name": "floor", "attributes": {}, "geometry": rect((-100, -100, 0), (200, 0, 0), (0, 200, 0))},
    {"id": 12, "name": "lamp", "attributes": {"pt.source": "lamp", "pt.material": "black"},
     "geometry": rect((-10, -10, 80), (0, 20, 0), (20, 0, 0))},      # normal -z: shines down
    {"id": 13, "name": "ball", "attributes": {"pt.material": "glass"}, "geometry": box((-10, -10, 20), (10, 10, 40))},
    {"id": 14, "name": "off", "attributes": {"sim.inactive": True}, "geometry": rect((-100, -100, 60), (200, 0, 0), (0, 200, 0))},
    {"id": 15, "name": "axis", "attributes": {}, "geometry": {"type": "curve", "degree": 1, "knots": [0, 0, 1, 1],
                                                              "points": [0, 0, 0, 0, 0, 1]}},
]
arc = {"type": "curve", "degree": 2, "knots": [0, 0, 0, 1, 1, 1], "points": [10, 0, 60, 10, 10, 60, 0, 10, 60],
       "weights": [1, math.sqrt(0.5), 1]}                           # a quarter circle of radius 10
line = pt_setup.polyline(arc)
assert len(line) == 33 and np.allclose(np.hypot(line[:, 0], line[:, 1]), 10) and np.allclose(line[:, 2], 60)
filament = {"id": 16, "name": "filament", "attributes": {"pt.source": "glow"}, "geometry": arc}
both = {**params, "sources": pt_setup.DEFAULT_SOURCES + [{"name": "glow", "flux": 3.0, "spectrum": "600"}]}
lit = pt_setup.build_scene(model + [filament], both)
assert list(lit.src_is_wire) == [False, True] and np.allclose(lit.src_prob, [0.25, 0.75])
assert abs(lit.src_wires[1][2][-1] - math.pi * 5) < 5e-3 and list(lit.wavelengths) == [550, 600]
assert pt_setup.assignments(model + [filament], both)[-1] == ["filament", "curve", "", "glow"]
cache = pt_setup.MeshCache()
scene = pt_setup.build_scene(model, params, cache)
assert scene.mesh.entity_ids == [11, 12, 13] and len(scene.mesh.face_area) == 8
assert pt_setup.build_scene(model, params, cache).mesh is scene.mesh                      # not tessellated again
red = scene.materials.names.index("red paint")                       # a default material with a spectrum
assert np.allclose(scene.materials.rho_table[red], np.interp(scene.wavelengths, [450, 550, 600, 650], [0.05, 0.1, 0.6, 0.8]))
assert [scene.materials.names[m] for m in scene.tri_material[scene.mesh.face_first[:3]]] == ["white", "black", "glass"]
assert pt_setup.sensor_faces(scene, [13]) == list(range(2, 8)) and len(pt_setup.sensor_faces(scene, [])) == 8
assert pt_setup.assignments(model, params) == [["floor", "surface", "(white)", ""], ["lamp", "surface", "black", "lamp"],
                                               ["ball", "shell", "glass", ""]]
for change, why in (({"default_material": "gold"}, "default material"), ({"sources": []}, "not in the table of sources"),
                    ({"materials": [{"name": "white", "kind": "wood"}]}, "unknown kind")):
    try:
        pt_setup.build_scene(model, {**params, **change})
        raise AssertionError("not refused")
    except ValueError as e:
        assert why in str(e), e
try:
    pt_setup.build_scene([model[0]], params)
    raise AssertionError("not refused")
except ValueError as e:
    assert "no object is a source" in str(e), e
sensor = pt_scene.TexelSensor(scene, pt_setup.sensor_faces(scene, [11]), 8)
out = pt_setup.irradiance(sensor, values(scene, sensor, "light", 20_000))
assert [(f["entity"], f["face"], f["w"], f["h"]) for f in out] == [(11, 0, 8, 8)]
assert 0.3 < out[0]["flux"] < 1.0 and abs(out[0]["area"] - 40_000) < 1e-6 and np.isfinite(out[0]["values"]).all()
assert math.isnan(out[0]["noise"])
result = pt_integrator.render(scene, sensor, "light", 40_000, 6, seed=SEED, batch=10_000)
assert 0 < pt_setup.irradiance(sensor, result["values"], result["error"])[0]["noise"] < 0.03
import tempfile  # noqa: E402

folder = Path(tempfile.mkdtemp())
written = pt_setup.export_irradiance(str(folder / "run.npz"), sensor, result, {11: "floor"}, {"method": "light tracing"})
assert written.endswith("run-irradiance.npz") and pt_setup.tagged("a/b", "camera") == "a/b-camera.npz"
with np.load(written) as data:
    assert data["E_11_0"].shape == (8, 8) and np.allclose(data["flux_11_0"].sum(), result["values"].sum())
    assert np.allclose(data["E_11_0"], data["flux_11_0"] / 625 * 1e6) and data["error_11_0"].min() > 0
    info = json.loads(str(data["info"]))
    assert info["faces"][0]["name"] == "floor" and info["method"] == "light tracing" and list(data["wavelengths"]) == [550]

from nfcad import UserError  # noqa: E402
from pathtracer_plugin import PathTracerPlugin  # noqa: E402


class FakeCad:
    """What the actions use of nfcad.Context."""

    def __init__(self, entities, params, selection=()):
        self.model, self.params, self.selection = entities, params, list(selection)
        self.fields, self.images, self.tables, self.line_sets, self.sets, self.logs = [], [], [], [], [], []

    def entities(self, ids=None, selection=False):
        return [e for e in self.model if not selection or e["id"] in self.selection]

    def set_attribute(self, entity, key, value):
        attributes = next(e for e in self.model if e["id"] == entity)["attributes"]
        attributes.pop(key, None) if value is None else attributes.__setitem__(key, value)

    def progress(self, value, text=""):
        assert 0 <= value <= 1

    def log(self, text):
        self.logs.append(text)

    def cancelled(self):
        return False

    def result_set(self, name):
        self.sets.append(name)
        return len(self.sets)

    def field(self, run, name, entity, data, width, height, **kw):
        assert len(data) == width * height
        self.fields.append((name, entity, kw))

    def image(self, run, name, data, width, height, **kw):
        assert len(data) == width * height
        self.images.append((name, np.asarray(data), kw))

    def table(self, run, name, columns, rows, **kw):
        assert all(len(r) == len(columns) for r in rows)
        self.tables.append((name, rows))

    def lines(self, run, name, points, starts, line_values, **kw):
        assert len(points) == len(line_values) == starts[-1]
        self.line_sets.append((name, len(starts) - 1))


plugin = PathTracerPlugin()
schema = plugin.params_schema()
json.dumps(schema)                                                   # plain JSON for the hello
assert set(plugin.actions()) == {"set_material", "set_source", "clear", "show", "irradiance", "camera_image",
                                 "show_camera", "show_paths"}
assert [c["name"] for c in next(s for s in schema if s["name"] == "materials")["columns"]][:2] == ["name", "kind"]
p = plugin.convert_params({"seed": SEED, "samples": 20_000, "processes": 2, "texels": 8, "camera_width": 16, "camera_height": 12,
                           "camera_position": [0, -200, 120], "camera_target": [0, 0, 20], "preview_paths": 20})
assert p["method"] == "light tracing" and p["materials"][0]["name"] == "white" and p["irradiance_on"] == []
plain = [{**e, "attributes": {}} for e in model[:3]]
cad = FakeCad(plain, p, selection=[12])
assert plugin.set_source(cad) == "1 object(s): source lamp" and plain[1]["attributes"] == {"pt.source": "lamp"}
cad.selection = [13]
p["assign_material"] = "glass"
plugin.set_material(cad)
assert plain[2]["attributes"] == {"pt.material": "glass"}
p["assign_material"] = "gold"
for call, selection in ((plugin.set_material, [13]), (plugin.set_source, [])):
    cad.selection = selection
    try:
        call(cad)
        raise AssertionError("not refused")
    except UserError:
        pass
plugin.show(cad)
assert cad.tables[-1][1][1] == ["lamp", "surface", "(white)", "lamp"]
for method in pt_setup.METHODS:
    p["method"] = method
    assert plugin.irradiance(cad).startswith("Irradiance on 8 face(s)")
    assert plugin.camera_image(cad).startswith("Camera image 16 × 12")
assert len(cad.fields) == 32 and cad.fields[0][0] == "E floor" and cad.fields[2][0] == "E ball · face 1"
assert any("photon mapping: " in line for line in cad.logs)
assert cad.fields[0][2]["unit"] == "W/m²" and cad.fields[0][2]["value_range"][1] > 0 and cad.fields[3][2]["face"] == 1
means = [img.mean() for _, img, _ in cad.images]
assert min(means) > 0 and max(means) / min(means) < 1.5, means       # the three methods see the same scene
p.update(method="light tracing", per_wavelength=True,
         sources=[{"name": "lamp", "flux": 1.0, "half_angle": 90.0, "side": "front", "spectrum": "450, 650:3"}])
before = len(cad.fields), len(cad.images)
plugin.irradiance(cad)
plugin.camera_image(cad)
assert (len(cad.fields) - before[0], len(cad.images) - before[1]) == (24, 3)        # the sum and two wavelengths
assert cad.fields[-1][0] == "E ball · face 6 · 650 nm" and cad.images[-1][0] == "Radiance 650 nm – light tracing"
assert any("at 450, 650 nm" in line for line in cad.logs)
assert abs(cad.images[-1][1].sum() / cad.images[-2][1].sum() - 3) < 0.6               # the shares of the flux
p["sources"][0]["spectrum"] = "blue"
try:
    plugin.irradiance(cad)
    raise AssertionError("not refused")
except UserError as e:
    assert "write wavelengths in nm" in str(e), e
p.update(per_wavelength=False, sources=pt_setup.DEFAULT_SOURCES, export=str(folder / "plugin"), samples=40_000)
plugin.irradiance(cad)                                               # 40 000 samples: two batches, so with an error
plugin.camera_image(cad)
assert len(cad.tables[-1][1][0]) == 6 and float(cad.tables[-1][1][0][5]) > 0             # the noise in %
assert any("noise of a typical texel" in line for line in cad.logs) and any("written: " in line for line in cad.logs)
with np.load(folder / "plugin-camera.npz") as data:
    assert data["radiance"].shape == (12, 16) and data["radiance_per_wavelength"].shape == (1, 12, 16)
    assert np.allclose(data["radiance"].ravel(), cad.images[-1][1]) and data["error"].shape == (12, 16)
assert (folder / "plugin-irradiance.npz").exists()
p["export"] = str(folder / "missing" / "x.npz")
try:
    plugin.camera_image(cad)
    raise AssertionError("not refused")
except UserError as e:
    assert "Cannot write" in str(e), e
p.update(export="", samples=20_000)
assert plugin.show_paths(cad) == "20 light paths" and plugin.show_camera(cad) == "Camera drawn"
assert cad.line_sets == [("Light paths", 20), ("Viewing pyramid", 5)]
cad.selection = [12, 13]
plugin.clear(cad)
assert plain[1]["attributes"] == {} and plain[2]["attributes"] == {}
try:
    plugin.irradiance(cad)                                           # no source any more
    raise AssertionError("not refused")
except UserError as e:
    assert "no object is a source" in str(e)
print("ok")
