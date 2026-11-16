"""Automotive Lighting plugin, ray tracing: the coil as a helix of wire, the H4's shield and cap
as surfaces, the lens' faces turned out of the glass, the light that leaves – with the NumPy
kernel of the Path Tracer plugin (and the C++ one, if installed) – and the plugin's action.
Exit code 77 (skipped) without NumPy."""

import json
import math
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    print("skipped: numpy is not installed")
    sys.exit(77)

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "python"))
sys.path.insert(0, str(root / "python" / "plugins" / "automotive_lighting"))

import al_coil  # noqa: E402
import al_layout  # noqa: E402
import al_lens  # noqa: E402
import al_optics  # noqa: E402
import al_photometry  # noqa: E402
import al_plugin  # noqa: E402
import al_trace  # noqa: E402

pt_bsdf, pt_integrator, pt_mesh, pt_scene = al_trace._numpy()
import pt_nurbs  # noqa: E402

H7, H4 = al_optics.LAMPS["H7"], al_optics.LAMPS["H4 (low beam)"]
cut = al_optics.Cutoff()

# ---- the coil: wire and turns from the power, the tube about the helix, its normals outwards
coil = al_coil.coil_of(H7, al_optics.Filament.of(H7))
assert abs(coil.wire - 0.161) < 0.002 and coil.turns == 16 and coil.axis == (1.0, 0.0, 0.0)
assert abs(coil.helix_radius + 0.5 * coil.wire - 0.5 * H7.diameter) < 1e-12
assert al_coil.coil_of(H4, al_optics.Filament.of(H4)).turns == 19
p21 = al_coil.coil_of(al_optics.LAMPS["P21W"], al_optics.Filament.of(al_optics.LAMPS["P21W"]))
assert p21.wire < coil.wire and p21.axis == (0.0, 1.0, 0.0)
given = al_coil.coil_of(H7, al_optics.Filament.of(H7), wire=0.2, turns=10)
assert given.wire == 0.2 and given.turns == 10 and abs(given.pitch - 0.39) < 1e-12
for wire, turns, words in ((0.7, 0, "thinner"), (0.2, 30, "touch")):
    try:
        al_coil.coil_of(H7, al_optics.Filament.of(H7), wire=wire, turns=turns)
        raise AssertionError("not refused")
    except ValueError as e:
        assert words in str(e), e
try:
    al_coil.coil_of(al_optics.Lamp("own", 4.0, 1.2, 1000.0), al_optics.Filament.of(H7))
    raise AssertionError("no power, no wire")
except ValueError as e:
    assert "wire diameter" in str(e)
faces = al_coil.coil_faces(coil)
assert len(faces) == coil.turns
phi = np.linspace(2 * math.pi * 1.9, 2 * math.pi * 3.1, 6000)
centre = coil.centre(phi)
s, su, sv = pt_nurbs.surface_grid(faces[2], np.linspace(0, 1, 23), np.linspace(0, 1, 13))
pts, normal = s.reshape(-1, 3), np.cross(su, sv).reshape(-1, 3)
gap = np.linalg.norm(pts[:, None, :] - centre[None], axis=2)
assert np.abs(gap.min(axis=1) - 0.5 * coil.wire).max() < 2e-4             # on the wire's surface
out = (pts - centre[gap.argmin(axis=1)]) / gap.min(axis=1)[:, None]
assert (np.einsum("ij,ij->i", normal / np.linalg.norm(normal, axis=1, keepdims=True), out) > 0.999).all()
end, _, _ = pt_nurbs.surface_grid(faces[2], [1.0], np.linspace(0, 1, 13))
start, _, _ = pt_nurbs.surface_grid(faces[3], [0.0], np.linspace(0, 1, 13))
assert np.abs(end - start).max() < 1e-12                                   # the turns join
assert abs(al_coil.estimated_wire(4.1, 1.3, 55.0) - coil.wire) < 1e-12

# ---- the H4's shield and cap as surfaces: they stop what Shield.passes says they stop
shield = H4.shield
areas = []
for kind, g in al_coil.shield_faces(shield):
    areas.append((kind, float(pt_mesh.build([{"id": 0, "geometry": g}], 0.002).face_area.sum())))
span = math.radians(165.0)
assert [k for k, _ in areas] == ["shield", "shield", "cap"]
assert abs(areas[0][1] / (span * shield.radius * (shield.front - shield.back)) - 1) < 1e-3
assert abs(areas[1][1] / (0.5 * shield.radius ** 2 * (span - math.sin(span))) - 1) < 2e-3
assert abs(areas[2][1] / (math.pi * shield.bulb_radius ** 2) - 1) < 1e-3
lamp_only = al_trace.lamp_bodies(H4, al_coil.coil_of(H4, al_optics.Filament.of(H4)))
assert [b.role for b in lamp_only] == [al_trace.COIL, al_trace.SHIELD, al_trace.CAP]
walls = pt_scene.Scene(pt_mesh.build([{"id": k, "geometry": {"type": "shell", "faces": b.faces}}
                                      for k, b in enumerate(lamp_only[1:])], al_trace.TOLERANCE),
                       pt_bsdf.Materials.from_rows([{"name": "black", "kind": "absorber"}]), np.zeros(2, dtype=int),
                       [pt_scene.SourceSpec("p", 1.0, points=((0.0, 0.0, 0.0),))])
rng = np.random.default_rng(2)
Q = rng.uniform(-1, 1, (4000, 3)) * [2.5, 0.6, 0.6]             # points about the coil, any direction
d = rng.normal(size=(4000, 3))
d /= np.linalg.norm(d, axis=1, keepdims=True)
t, tri, _, _ = walls.hit(Q, d)
agree = (tri < 0) == shield.passes(Q, d[None])[0]
assert agree.mean() > 0.995, agree.mean()                        # (the cap's 1 µm hole, rays along a face)

# ---- a face turned: the same surface, the normal the other way, the trimming along
lens_frame = al_layout.rounded_rectangle(80.0, 50.0, 8.0)
system = al_lens.build(al_lens.LensSettings(H7, cut, (al_lens.Element(-1e3, 1e3, -1e3, 1e3, 0.0, -1.0, 15.0, 3.0),)),
                       lens_frame)
element = next(f for kind, _, f in al_lens.faces(system) if kind == "element" and f.get("outer"))
turned = al_trace._turned(element)
a, au, av = pt_nurbs.surface_grid(element["surface"], [element["surface"]["knots_u"][0] + 0.3], [element["surface"]["knots_v"][0] + 0.7])
b, bu, bv = pt_nurbs.surface_grid(turned["surface"], [turned["surface"]["knots_u"][0] + 0.7], [turned["surface"]["knots_v"][0] + 0.3])
assert np.allclose(a, b) and np.allclose(np.cross(au, av), -np.cross(bu, bv))
both = pt_mesh.build([{"id": 0, "geometry": element}, {"id": 1, "geometry": turned}], 0.005)
assert abs(both.face_area[0] / both.face_area[1] - 1) < 1e-3

# ---- the lens: every face's normal points out of the glass
lens = al_trace.lens_bodies(system, 0.85)
assert [b.role for b in lens] == [al_trace.MIRROR, al_trace.LENS] and lens[1].material["ior"] == system.settings.index
mesh = pt_mesh.build([{"id": 0, "geometry": {"type": "shell", "faces": lens[1].faces}}], 0.005)
tri, b1, b2 = mesh.sample(np.arange(len(lens[1].faces)), 3000, rng)
p = mesh.v0[tri] + b1[:, None] * mesh.e1[tri] + b2[:, None] * mesh.e2[tri]
n, _ = mesh.shade(tri, b1, b2)
s = system.settings
inner = s.lens_x + system.inner(p[:, 1], p[:, 2])[0]
outer = s.lens_x + s.thickness + system.shape(p[:, 1], p[:, 2])[0]
on_inner, on_outer = np.abs(p[:, 0] - inner) < 0.01, np.abs(p[:, 0] - outer) < 0.01
assert on_inner.sum() > 1000 and on_outer.sum() > 1000
assert (n[on_inner, 0] < 0).all() and (n[on_outer, 0] > 0).all()

# ---- the bare coil: what leaves it is the lamp's flux, half of it forwards
share = al_trace.coil_share(coil, "NumPy", rays=40_000)
assert 0.5 < share < 0.65, share
looser = al_trace.coil_share(al_coil.coil_of(H7, al_optics.Filament.of(H7), wire=coil.wire, turns=8), "NumPy",
                             rays=40_000)
assert looser > share + 0.1                                     # open turns hide less of each other
bare, info = al_trace.trace(al_trace.lamp_bodies(H7, coil), H7, coil, rays=60_000, depth=4, kernel_name="NumPy",
                            batch=20_000)
assert abs((bare.flux_direct + info.flux_back) / H7.flux - 1) < 0.02, (bare.flux_direct, info.flux_back)
assert abs(bare.flux_direct / H7.flux - 0.5) < 0.02 and bare.flux_beam == 0.0
assert abs(info.flux_lost - H7.flux * (1 / info.coil_share - 1)) < 0.02 * H7.flux
assert info.rays == 60_000 and info.noise > 0 and info.by_role == {"none": bare.flux_direct}
# near the axis the wire shines brighter than the design's cylinder (Phi sin(theta) / pi²): one sees
# the turns from their ends too
side = (np.abs(bare.h) > 20) & (np.abs(bare.h) < 40)
cylinder = H7.flux * np.sin(np.radians(np.abs(bare.h[side]))) / math.pi ** 2
ratio = bare.intensity[np.abs(bare.v) < 5][:, side].mean() / cylinder.mean()
assert 1.1 < ratio < 1.5, ratio

# ---- the paraboloid alone: the beam where the design's model has it
mirror_only = al_trace.lamp_bodies(H7, coil) + lens[:1]
beam, info = al_trace.trace(mirror_only, H7, coil, rays=150_000, depth=4, kernel_name="NumPy", batch=50_000)
P, N, A = system.samples(1.0)
model = al_photometry.intensity(H7, system.filament, P, N, A, np.full(len(P), 0.85), n_axial=8, n_around=16)
assert abs(beam.flux_beam / model.flux_beam - 1) < 0.12, (beam.flux_beam, model.flux_beam)


w = info.beam / info.beam.sum()
assert abs((w.sum(axis=0) * beam.h).sum()) < 0.2 and abs((w.sum(axis=1) * beam.v).sum()) < 0.2
spread = [math.sqrt((w.sum(axis=0) * beam.h ** 2).sum()), math.sqrt((w.sum(axis=1) * beam.v ** 2).sum())]
w = model.intensity / model.intensity.sum()
wanted = [math.sqrt((w.sum(axis=0) * model.h ** 2).sum()), math.sqrt((w.sum(axis=1) * model.v ** 2).sum())]
assert np.allclose(spread, wanted, rtol=0.15), (spread, wanted)
assert info.flux_housing == 0.0 and beam.flux_direct > beam.flux_beam      # (no lens: the direct light goes on)

native = al_trace._native()
if native is not None:            # the C++ kernel: the same fluxes
    again, info = al_trace.trace(mirror_only, H7, coil, rays=600_000, depth=4, kernel_name="C++")
    assert abs(again.flux_beam / beam.flux_beam - 1) < 0.03 and abs(again.flux_direct / beam.flux_direct - 1) < 0.03
    assert info.kernel == "C++" and al_trace.kernel("automatic") == "C++"
else:
    assert al_trace.kernel("automatic") == "NumPy"
    try:
        al_trace.kernel("C++")
        raise AssertionError("no C++ kernel, yet chosen")
    except RuntimeError as e:
        assert "pathtracer" in str(e)


# ---- the plugin's action, against a recorded context
class Host:
    def __init__(self):
        self.results, self.logs = [], []

    def send(self, message):
        if message.get("type") == "log":
            self.logs.append(message["text"])

    def request(self, method, args):
        json.dumps(args)
        if method == "model.entities":
            return []
        if method == "results.create_set":
            return 1
        if method.startswith("results."):
            for value in args.values():
                if isinstance(value, dict) and "file" in value:
                    Path(value["file"]).unlink()
            self.results.append(method.split(".")[1])
            return len(self.results)
        raise AssertionError(f"unexpected request {method}")


from nfcad import Context  # noqa: E402

plugin = al_plugin.AutomotiveLighting()
assert "light_distribution_traced" in plugin.actions()
host = Host()
ctx = Context(host, 1, plugin.convert_params({"system": al_plugin.PATTERNED, "frame_width": 80.0, "frame_height": 50.0,
                                              "frame_radius": 8.0, "cell_width": 12.5, "cell_height": 16.0,
                                              "trace_rays": 30_000, "trace_depth": 6, "trace_kernel": "NumPy"}), [])
summary = plugin.light_distribution_traced(ctx)
assert summary.startswith("ray tracing:") and host.results == ["image", "table", "curve", "curve"], host.results
log = "\n".join(host.logs)
assert "NumPy kernel: 30,000 light paths" in log and "turns of 0.161 mm wire" in log and "(wire and turns estimated)" in log
assert "into the housing beside the lens" in log and "Transmittance* is not used" in log
ctx.params.update({"coil_wire": 0.9})
try:
    plugin.light_distribution_traced(ctx)
    raise AssertionError("a wire thicker than the coil")
except al_plugin.UserError as e:
    assert "thinner" in str(e)

print("al trace ok")
