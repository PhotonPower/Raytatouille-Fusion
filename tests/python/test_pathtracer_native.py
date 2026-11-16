"""Path Tracer plugin with the C++ kernel (package pathtracer): the same model gives the same
values with both kernels, and the plugin's actions run with it. Skips with 77 if numpy or the
package is not installed."""

import math
import os
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
except ImportError:
    sys.exit(77)

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "python"))
sys.path.insert(0, str(root / "python" / "plugins" / "pathtracer"))

import pt_native  # noqa: E402

if not pt_native.available():
    sys.exit(77)

import pt_integrator  # noqa: E402
import pt_scene  # noqa: E402
import pt_setup  # noqa: E402

SEED = int(os.environ.get("PT_TEST_SEED", "1"))


def rect(p0, du, dv):
    p0, du, dv = (np.asarray(v, dtype=float) for v in (p0, du, dv))
    pts = [p0, p0 + dv, p0 + du, p0 + du + dv]
    return {"type": "surface", "degree_u": 1, "degree_v": 1, "knots_u": [0, 0, 1, 1], "knots_v": [0, 0, 1, 1],
            "num_u": 2, "num_v": 2, "points": [float(c) for p in pts for c in p]}


def box(lo, hi):
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    ex, ey, ez = np.diag(hi - lo)
    faces = [rect(lo, ey, ex), rect(lo + ez, ex, ey), rect(lo, ex, ez), rect(lo + ey, ez, ex),
             rect(lo, ez, ey), rect(lo + ex, ey, ez)]
    return {"type": "shell", "faces": [{"surface": f} for f in faces]}


folder = Path(tempfile.mkdtemp())
gammas = np.arange(0, 91, 5.0)
(folder / "lamp.ies").write_text("\n".join(
    ["IESNA:LM-63-2002", "TILT=NONE", f"1 1000 1 {len(gammas)} 1 1 2 0 0 0", "1 1 100",
     " ".join(f"{v:g}" for v in gammas), "0", " ".join(f"{1000 * math.cos(math.radians(v)):.6g}" for v in gammas)]))
arc = {"type": "curve", "degree": 2, "knots": [0, 0, 0, 1, 1, 1], "points": [10, 0, 60, 10, 10, 60, 0, 10, 60],
       "weights": [1, math.sqrt(0.5), 1]}
model = [
    {"id": 11, "name": "floor", "attributes": {}, "geometry": rect((-100, -100, 0), (200, 0, 0), (0, 200, 0))},
    {"id": 12, "name": "lamp", "attributes": {"pt.source": "lamp", "pt.material": "black"},
     "geometry": rect((-10, -10, 80), (0, 20, 0), (20, 0, 0))},
    {"id": 13, "name": "block", "attributes": {"pt.material": "glass"}, "geometry": box((-10, -10, 20), (10, 10, 40))},
    {"id": 14, "name": "off", "attributes": {"sim.inactive": True}, "geometry": rect((-100, -100, 60), (200, 0, 0), (0, 200, 0))},
    {"id": 16, "name": "filament", "attributes": {"pt.source": "glow"}, "geometry": arc},
    {"id": 17, "name": "bulb", "attributes": {"pt.source": "spot"}, "geometry": {"type": "point", "point": [60, 60, 50]}},
    {"id": 18, "name": "gauge", "attributes": {"pt.material": "detector"}, "geometry": rect((-90, -90, 5), (60, 0, 0), (0, 60, 0))},
]
params = {"materials": pt_setup.DEFAULT_MATERIALS, "default_material": "white", "tolerance": 0.01,
          "sources": [{"name": "lamp", "flux": 1.0, "half_angle": 90.0, "side": "front", "spectrum": "450:1, 650:2"},
                      {"name": "glow", "flux": 0.5, "spectrum": "550"},
                      {"name": "spot", "flux": 400.0, "unit": "lm", "spectrum": "550", "distribution": str(folder / "lamp.ies"),
                       "axis": "0, 0, -1"}]}

# ---- the same description, two kernels
numpy_scene = pt_setup.build_scene(model, params)
cache = pt_native.MeshCache()
native_scene = pt_native.build_scene(model, params, cache)
assert pt_native.build_scene(model, params, cache).mesh.triangles == native_scene.mesh.triangles and cache.mesh is not None
assert native_scene.mesh.entity_ids == numpy_scene.mesh.entity_ids == [11, 12, 13, 18]
assert native_scene.mesh.triangles == numpy_scene.mesh.triangles
assert np.allclose(native_scene.mesh.face_area, numpy_scene.mesh.face_area)
assert list(native_scene.wavelengths) == list(numpy_scene.wavelengths) == [450, 550, 650]
assert abs(native_scene.flux / numpy_scene.flux - 1) < 1e-12 and np.allclose(native_scene.channel_prob, numpy_scene.channel_prob)
assert list(native_scene.src_is_wire) == list(numpy_scene.src_is_wire) == [False, True, False]
assert list(native_scene.src_is_measured) == [False, False, True] and native_scene.has_detectors
faces = pt_setup.sensor_faces(numpy_scene, [11, 18])
assert faces == pt_setup.sensor_faces(native_scene, [11, 18]) == [0, 8]
numpy_sensor = pt_scene.TexelSensor(numpy_scene, faces, 3)
native_sensor = pt_native.texel_sensor(native_scene, faces, 3)
assert np.allclose(native_sensor.texel_area, numpy_sensor.texel_area) and list(native_sensor.first) == list(numpy_sensor.first)
reference = pt_integrator.render(numpy_scene, numpy_sensor, "light", 150_000, 6, seed=SEED)
for method in ("light", "path", "bidir"):
    got = pt_native.render(native_scene, native_sensor, method, 600_000, 6, seed=SEED)
    assert got["processes"] >= 1 and got["channels"].shape == reference["channels"].shape
    floor, gauge = slice(0, 9), slice(9, 18)
    assert abs(got["values"][floor].sum() / reference["values"][floor].sum() - 1) < 0.03, method
    if method != "path":                 # (path tracing does not find the bulb's light through the glass block)
        assert np.allclose(got["values"][floor] / reference["values"][floor], 1, atol=0.06), method
        assert abs(got["values"][gauge].sum() / reference["values"][gauge].sum() - 1) < 0.08, method
        assert np.allclose(got["channels"].sum(axis=1) / reference["channels"].sum(axis=1), 1, atol=0.05), method
rows = pt_setup.irradiance(native_sensor, got["values"], got["error"])
assert [(r["entity"], r["face"], r["w"], r["h"]) for r in rows] == [(11, 0, 3, 3), (18, 0, 3, 3)] and 0 < rows[0]["noise"] < 0.05
numpy_camera = pt_scene.Camera((0, -250, 150), (0, 0, 20), (0, 0, 1), 40.0, 4, 3)
native_camera = pt_native.camera((0, -250, 150), (0, 0, 20), (0, 0, 1), 40.0, 4, 3)
for method, samples in (("path", 60_000), ("bidir", 40_000)):       # (bidirectional also finds the bulb's light
    reference = pt_integrator.render(numpy_scene, numpy_camera, method, samples, 5, seed=SEED)["values"]   # through
    image = pt_native.render(native_scene, native_camera, method, 400_000, 5, seed=SEED)["values"]        # the glass)
    seen = reference > 0                                             # (the upper row looks past the model)
    assert np.array_equal(image > 0, seen) and abs(image.sum() / reference.sum() - 1) < 0.05, (method, image, reference)
    assert np.allclose(image[seen] / reference[seen], 1, atol=0.2), (method, image[seen] / reference[seen])
points, starts = pt_native.light_paths(native_scene, 30, 4, SEED)
assert len(starts) == 31 and starts[-1] == len(points)
mine = pt_integrator.escapes(numpy_scene, 100_000, 6, seed=SEED)        # the light that leaves the model
theirs = [pt_native.escapes(native_scene, 200_000, 6, seed=SEED, index=k) for k in range(2)]
for bounces, room in ((0, 0.01), (1, 0.03), (None, 0.01)):           # (None: all of it)
    a = mine["flux"][mine["bounces"] == bounces].sum() if bounces is not None else mine["flux"].sum()
    b = sum((t["flux"][t["bounces"] == bounces] if bounces is not None else t["flux"]).sum() for t in theirs) / 2
    assert abs(b / a - 1) < room, (bounces, a, b)
up = lambda g: g["flux"][g["d"][:, 2] > 0.5].sum() / g["flux"].sum()            # noqa: E731
assert abs(up(theirs[0]) / up(mine) - 1) < 0.03 and set(np.unique(theirs[0]["first"])) == set(np.unique(mine["first"]))
if pt_native.skips():                                                 # the first surface past the most common one
    common = int(np.bincount(mine["first"][mine["first"] >= 0]).argmax())
    mine = pt_integrator.escapes(numpy_scene, 100_000, 6, seed=SEED, skip=[common])
    theirs = pt_native.escapes(native_scene, 400_000, 6, seed=SEED, skip=[common])
    assert common not in mine["first"] and common not in theirs["first"]
    for e in np.unique(mine["first"]):
        a, b = mine["flux"][mine["first"] == e].sum(), theirs["flux"][theirs["first"] == e].sum()
        assert abs(b - a) < 0.02 * mine["flux"].sum(), (e, a, b)

# ---- the plugin's actions with the C++ kernel
from nfcad import UserError  # noqa: E402
from pathtracer_plugin import PathTracerPlugin  # noqa: E402


class FakeCad:
    def __init__(self, entities, params):
        self.model, self.params, self.selection = entities, params, []
        self.fields, self.images, self.tables, self.line_sets, self.logs = [], [], [], [], []

    def entities(self, ids=None, selection=False):
        return [e for e in self.model if not selection or e["id"] in self.selection]

    def progress(self, value, text=""):
        assert 0 <= value <= 1

    def log(self, text):
        self.logs.append(text)

    def cancelled(self):
        return False

    def result_set(self, name):
        return 1

    def field(self, run, name, entity, data, width, height, **kw):
        assert len(data) == width * height
        self.fields.append((name, entity, kw))

    def image(self, run, name, data, width, height, **kw):
        assert len(data) == width * height
        self.images.append((name, np.asarray(data), kw))

    def table(self, run, name, columns, rows, **kw):
        self.tables.append((name, rows))

    def lines(self, run, name, points, starts, line_values, **kw):
        assert len(points) == len(line_values) == starts[-1]
        self.line_sets.append((name, len(starts) - 1))


plugin = PathTracerPlugin()
p = plugin.convert_params({**params, "seed": SEED, "samples": 200_000, "texels": 4, "camera_width": 16, "camera_height": 12,
                           "camera_position": [0, -250, 150], "camera_target": [0, 0, 20], "preview_paths": 20,
                           "export": str(folder / "run"), "per_wavelength": True})
assert p["kernel"] == "automatic"
cad = FakeCad(model, p)
means = {}
for kernel in ("C++", "NumPy"):
    p["kernel"] = kernel
    p["samples"] = 200_000 if kernel == "C++" else 30_000
    for method in ("light tracing", "path tracing", "bidirectional", "photon mapping"):
        if kernel == "NumPy" and method != "path tracing":
            continue
        p["method"] = method
        assert plugin.irradiance(cad).startswith("Irradiance on 9 face(s)")
        assert plugin.camera_image(cad).startswith("Camera image 16 × 12")
        means[kernel, method] = cad.images[-4][1].mean()             # the sum (before the three wavelengths)
    assert plugin.show_paths(cad) == "20 light paths"
assert sum("kernel: C++" in line for line in cad.logs) == 9 and sum("kernel: NumPy" in line for line in cad.logs) == 3
assert any("thread(s)" in line for line in cad.logs) and any("process(es)" in line for line in cad.logs)
assert max(means.values()) / min(means.values()) < 1.25, means
assert abs(means["C++", "path tracing"] / means["NumPy", "path tracing"] - 1) < 0.1
with np.load(folder / "run-camera.npz") as data:
    assert data["radiance"].shape == (12, 16) and data["radiance_per_wavelength"].shape == (3, 12, 16)
with np.load(folder / "run-irradiance.npz") as data:
    assert data["E_11_0"].shape == (4, 4) and "flux_18_0_650nm" in data
p.update(kernel="C++", sources=[{**p["sources"][0], "side": "sideways"}] + p["sources"][1:])
try:
    plugin.irradiance(cad)
    raise AssertionError("not refused")
except UserError as e:
    assert "side must be" in str(e), e
print("ok")
