"""Path Tracer plugin: tabulated materials (BSDF files, Raytatouille Fusion ADR 0011, stage M1).

A table of the Lambertian reflector gives what the material "diffuse" gives, a table of the GGX
conductor what "metal" gives; sample() draws what eval() says; a material with a mirror part and
a diffuse part gives the same light with every method (the delta events in the weights of the
bidirectional method). Needs numpy and rtt_fusion (skips with 77 without them)."""

import math
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
    from rtt_fusion import material
except ImportError:
    sys.exit(77)

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "python"))
sys.path.insert(0, str(root / "python" / "plugins" / "pathtracer"))

import pt_bsdf  # noqa: E402
import pt_integrator  # noqa: E402
import pt_mesh  # noqa: E402
import pt_scene  # noqa: E402
import pt_setup  # noqa: E402

SEED = 7
THETA_IN = np.deg2rad(np.arange(0.0, 90.0, 5.0))
THETA_EDGES = np.deg2rad(np.linspace(0.0, 90.0, 91))
PHI_EDGES = np.deg2rad(np.linspace(0.0, 180.0, 73))
LAMBDA = np.array([0.55])


def rect(p0, du, dv):
    """A flat face: corner and two edges; the normal is du x dv."""
    p0, du, dv = (np.asarray(v, dtype=float) for v in (p0, du, dv))
    pts = [p0, p0 + dv, p0 + du, p0 + du + dv]
    return {"type": "surface", "degree_u": 1, "degree_v": 1, "knots_u": [0, 0, 1, 1], "knots_v": [0, 0, 1, 1],
            "num_u": 2, "num_v": 2, "points": [float(c) for p in pts for c in p]}


def table_of(b: "material.Bsdf") -> dict:
    """The arrays pt_setup.load_bsdf makes of a file (wavelengths in nm)."""
    return {"nm": b.wavelength * 1000.0, "theta_in": b.theta_in, "theta_edges": b.theta_edges,
            "phi_edges": b.phi_edges, "reflectance": b.reflectance, "transmittance": b.transmittance,
            "brdf": b.brdf, "btdf": b.btdf,
            "index_behind": None if b.index_behind is None else b.index_behind.at(b.wavelength)}


lambert = material.lambert(0.6, LAMBDA, THETA_IN, THETA_EDGES, PHI_EDGES)
ggx = material.ggx_conductor(0.9, 0.5, LAMBDA, THETA_IN, THETA_EDGES, PHI_EDGES, sub=6)
# a clear coat over a matt base, roughly: a mirror part of 0.3 (same at every angle) and a
# Lambertian part of 0.4
coat = material.Bsdf(LAMBDA, THETA_IN, THETA_EDGES, PHI_EDGES, np.full((18, 1), 0.3), np.zeros((18, 1)),
                     np.full((18, 1), 0.3), brdf=np.full((18, 1, 90, 72), 0.4 / math.pi))
for b in (lambert, ggx, coat):
    b.check()

MATS = pt_bsdf.Materials.from_rows([
    {"name": "black", "kind": "absorber"},
    {"name": "white", "kind": "diffuse", "reflectance": 0.6},
    {"name": "metal", "kind": "metal", "reflectance": 0.9, "roughness": 0.5},
    {"name": "white table", "kind": "tabulated", "table": table_of(lambert)},
    {"name": "metal table", "kind": "tabulated", "table": table_of(ggx)},
    {"name": "coat", "kind": "tabulated", "table": table_of(coat)},
])
BLACK, WHITE, METAL, WHITE_T, METAL_T, COAT = range(6)
assert not MATS.specular(np.array([WHITE_T, METAL_T, COAT])).any()

# ---- sample() draws what eval() says: the density, the weight f |cos| / density, the same pair seen
# from the other end; the light leaving is what the table reflects
count = 40_000
up = np.tile([0.0, 0.0, 1.0], (count, 1))
for m, albedo in ((WHITE_T, None), (METAL_T, ggx), (COAT, None)):
    for towards in ((0.3, 0.0, 0.954), (0.8, 0.0, 0.6), (0.0, 0.0, 1.0), (0.5, 0.5, -0.707)):   # also from the back
        wo = np.tile(np.asarray(towards) / np.linalg.norm(towards), (count, 1))
        which = np.full(count, m)
        for radiance in (True, False):
            wi, weight, dens = MATS.sample(which, up, wo, np.random.default_rng(SEED), radiance)
            diffuse = dens > 0
            f, forward, backward = MATS.eval(which[diffuse], up[diffuse], wo[diffuse], wi[diffuse], None, radiance)
            assert np.allclose(forward, dens[diffuse], rtol=1e-9), (m, towards)
            assert np.allclose(f * np.abs(wi[diffuse, 2]) / dens[diffuse], weight[diffuse], rtol=1e-9), (m, towards)
            f2, forward2, _ = MATS.eval(which[diffuse], up[diffuse], wi[diffuse], wo[diffuse], None, not radiance)
            assert np.allclose(f2, f, rtol=1e-9) and np.allclose(forward2, backward, rtol=1e-9)
            if not radiance:
                expected = 0.6 if m == WHITE_T else 0.7 if m == COAT else None
                if albedo is not None:                       # the table's own albedo at this angle
                    j = np.searchsorted(THETA_IN, math.acos(abs(wo[0, 2])), side="right") - 1
                    expected = float(albedo.scattered_reflectance()[min(j, 17), 0])
                assert abs(weight.mean() - expected) < 0.03, (m, towards, weight.mean(), expected)
            if m == COAT:                                    # the mirror part: a third of what leaves
                mirror = (dens == 0) & (weight > 0)
                assert abs(mirror.mean() - 0.3 / 0.7) < 0.01
                assert np.allclose(wi[mirror], wo[mirror] * [-1, -1, 1])           # mirrored at the surface

# ---- in a scene: a lamp over a floor, the light the floor sends up to a ceiling. The table of a
# material gives what the material gives (light tracing), and every method agrees
lamp = rect((-10, -10, 80), (0, 20, 0), (20, 0, 0))                       # facing down
floor = rect((-100, -100, 0), (200, 0, 0), (0, 200, 0))                   # facing up
ceiling = rect((-100, -100, 100), (0, 200, 0), (200, 0, 0))               # facing down
mesh = pt_mesh.build([{"id": k + 1, "geometry": g} for k, g in enumerate([floor, lamp, ceiling])], 1e-3)


def up_light(floor_material: int, method: str, samples: int) -> float:
    scene = pt_scene.Scene(mesh, MATS, np.array([floor_material, BLACK, BLACK]),
                           [pt_scene.SourceSpec("a", 1.0, 90, "front", entities=(1,))], ())
    sensor = pt_scene.TexelSensor(scene, [2], 2)
    return float(pt_integrator.render(scene, sensor, method, samples, 4, seed=SEED)["values"].sum())


for plain, table in ((WHITE, WHITE_T), (METAL, METAL_T)):
    reference = up_light(plain, "light", 200_000)
    got = up_light(table, "light", 200_000)
    assert abs(got / reference - 1) < 0.03, (plain, got, reference)
    for method in ("path", "bidir"):
        other = up_light(table, method, 60_000)
        assert abs(other / reference - 1) < 0.05, (plain, method, other, reference)
# the clear coat: the mirror part sends the lamp's light straight up as well – the methods agree
reference = up_light(COAT, "light", 200_000)
for method in ("path", "bidir"):
    got = up_light(COAT, method, 60_000)
    assert abs(got / reference - 1) < 0.05, (method, got, reference)

# ---- the plugin's table of materials: kind "tabulated" with the path of a .bsdf file
with tempfile.TemporaryDirectory() as tmp:
    path = f"{tmp}/coat.bsdf"
    material.save(coat, path)
    rows = [{"name": "white", "kind": "diffuse", "reflectance": 0.6},
            {"name": "coat", "kind": "tabulated", "bsdf": path}]
    model = [{"id": 1, "geometry": floor, "attributes": {"pt.material": "coat"}},
             {"id": 2, "geometry": lamp, "attributes": {"pt.source": "lamp"}}]
    params = {"materials": rows, "default_material": "white", "sources": pt_setup.DEFAULT_SOURCES}
    d = pt_setup.describe(model, params)
    assert d["materials"][1]["table"]["nm"].tolist() == [550.0]
    scene = pt_setup.build_scene(model, params)
    assert scene.materials.kind[1] == pt_bsdf.TABULATED
    for bad, message in (("", "needs a BSDF file"), (f"{tmp}/missing.bsdf", "does not exist")):
        try:
            pt_setup.describe(model, {**params, "materials": [rows[0], {**rows[1], "bsdf": bad}]})
            raise AssertionError("not refused")
        except ValueError as e:
            assert message in str(e) and "'coat'" in str(e), e
print("ok")
