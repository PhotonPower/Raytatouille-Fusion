"""Automotive Lighting plugin, the optimised lens: the probes of R112, the cells' patterns and how
they move and spread, the surrogate against the filament images, the objective in two views, the
optimisation of a small H4 lens and the plugin's action. NumPy only; exit code 77 (skipped)
without NumPy."""

import dataclasses
import json
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

import al_layout  # noqa: E402
import al_lens  # noqa: E402
import al_optics  # noqa: E402
import al_optimise as O  # noqa: E402
import al_photometry  # noqa: E402
import al_plugin  # noqa: E402

H4 = al_optics.LAMPS["H4 (low beam)"]
cut = al_optics.Cutoff()
h, v = O.grid()
H, V = np.meshgrid(h, v)

# ---- the probes: R112's points and zones, every bin that touches an upper limit's zone
pr = O.probes(cut)
names = [g.name for g in pr.groups]
assert names[:9] == [tp.name for tp in al_photometry.R112_CLASS_B]
assert names[9:] == ["zone III", "zone IV", "zone I", "above the cut-off", "under the cut-off", "over the cut-off"]
groups = {g.name: g for g in pr.groups}
assert all(len(g.at) for g in pr.groups) and len(pr.bins) == len(pr.omega)
inside = al_photometry._inside(list(al_photometry.ZONE_III), H, V).ravel()
zone3 = set(pr.bins[groups["zone III"].at])
assert set(np.flatnonzero(inside)) <= zone3 and len(zone3) > inside.sum()           # and its border
assert groups["zone I"].relative == "50R" and groups["over the cut-off"].relative == "under the cut-off"
left = O.probes(dataclasses.replace(cut, right_hand_traffic=False))
b50 = lambda p: (h[p.bins[p.groups[0].at] % len(h)]).mean()                          # noqa: E731
assert b50(pr) < 0 < b50(left)                                                       # B50L / B50R

# ---- smearing and blurring keep the flux
rng = np.random.default_rng(3)
a = np.zeros((40, 60))
a[15:25, 20:40] = rng.uniform(size=(10, 20))
assert abs(O._box(a, 4, 1).sum() - a.sum()) < 1e-9 and abs(O.blurred(a, (0.5, 0.2)).sum() - a.sum()) < 1e-9
assert O._box(a, 4, 1)[20, 20:40].std() < a[20, 20:40].std()

# ---- the objective: met with the margin it rewards the weakest margin, a shortfall costs; two views
ok = np.full(len(pr.bins), 3000.0)
ok[groups["zone III"].at] = ok[groups["above the cut-off"].at] = 100.0
ok[groups["over the cut-off"].at] = 100.0
ok[groups["B50L"].at] = ok[groups["BR"].at] = 100.0
for name in ("75R", "50R", "50V"):
    ok[groups[name].at] = 12000.0
ok[groups["under the cut-off"].at] = 5000.0
good = O.objective(ok[None, None, :], pr, 0.1)[0]
assert good < 0
bad = ok.copy()
bad[groups["75R"].at] = 9000.0
assert O.objective(bad[None, None, :], pr, 0.1)[0] > good + 0.01
glare = ok.copy()
glare[groups["zone III"].at[0]] = 2000.0
assert O.objective(glare[None, None, :], pr, 0.1)[0] > good + 0.1
both = O.objective(np.stack([ok, glare])[:, None, :], pr, 0.1)[0]     # the brighter view decides an upper limit
assert abs(both - O.objective(glare[None, None, :], pr, 0.1)[0]) < 1e-9
both = O.objective(np.stack([ok, bad])[:, None, :], pr, 0.1)[0]       # the darker one a lower limit
assert abs(both - O.objective(bad[None, None, :], pr, 0.1)[0]) < 1e-9
report = O.report(np.stack([ok, glare]), pr)
assert report["zone III"] == 2000.0 and report["75R"] == 12000.0

# ---- a small H4 lens: the cells' light, the surrogate against the filament images
frame = al_layout.rounded_rectangle(80.0, 50.0, 8.0)
settings = al_lens.LensSettings(H4, cut, (al_lens.Element(-1e3, 1e3, -1e3, 1e3),), focus_behind=3.0, cell_width=8.0,
                                cell_height=8.0)
plane = al_lens.build(settings, frame)
rays = O.lens_rays(plane, spacing=2.0)
assert len(rays.cells) == plane.cells and rays.cell.max() < len(rays.cells) and (rays.flux > 0).all()
sur = O.Surrogate(rays, pr, np.zeros((1, len(pr.bins))))
zero = O.Choice(*(np.full(len(rays.cells), z, dtype=np.int64) for z in (16, 15, 0, 0)))
assert O.DEFLECT_H[16] == 0.0 and O.DEFLECT_V[15] == 0.0
flat = sur.full(zero)[0]
inside = (rays.H >= O.H_RANGE[0]) & (rays.H < O.H_RANGE[1]) & (rays.V >= O.V_RANGE[0]) & (rays.V < O.V_RANGE[1])
assert abs(flat.sum() / rays.flux[inside].sum() - 1) < 1e-5
moved = O.Choice(np.full(len(rays.cells), 22), zero.dv.copy(), zero.sh.copy(), np.full(len(rays.cells), 2))
shifted = sur.full(moved)[0]                                                       # 6° to the right, ± 0.5° up and down
centre = lambda m: ((m.sum(axis=0) * h).sum() / m.sum(), (m.sum(axis=1) * v).sum() / m.sum())  # noqa: E731
assert abs(centre(shifted)[0] - centre(flat)[0] - 6.0) < 0.05 and abs(centre(shifted)[1] - centre(flat)[1]) < 0.02
assert np.allclose(sur.beam(zero)[0], flat.ravel()[pr.bins])
model = al_photometry.intensity(H4, plane.filament, *plane.samples(2.0), np.full(len(plane.samples(2.0)[0]), 0.85),
                                after=lambda o, d: plane.through(o, d, 0.92), n_axial=8, n_around=16)
seen, _ = O.resampled(model)
omega = al_photometry._solid_angle(h[None, :], v[:, None], O.DH, O.DV)
bright = seen > 0.2 * seen.max()
assert np.abs((flat / omega)[bright] / seen[bright] - 1).mean() < 0.05            # the surrogate is the model
# fit_blur finds a blur laid on
blurred = dataclasses.replace(model, intensity=O.blurred(model.intensity, (0.25 * 2, 0.2)))    # (model: 0.25° bins)
sh, sv, err = O.fit_blur(model, blurred)
assert abs(sh - 0.25) <= 0.125 and abs(sv - 0.2) <= 0.05 and err < 0.1, (sh, sv, err)

# ---- the optimisation: better than plane glass, every cell an element, the rounds reported
calls = []


def evaluate(system):
    calls.append(system)
    P, N, A = system.samples(2.0)
    dist = al_photometry.intensity(H4, system.filament, P, N, A, np.full(len(P), 0.85),
                                   after=lambda o, d: system.through(o, d, 0.92), n_axial=8, n_around=16)
    return dist


result = O.optimise(settings, frame, evaluate, rounds=1, spacing=2.0, direct=False)
assert len(result.elements) == plane.cells and len(calls) == 2 and len(result.rounds) == 2
assert any(c is result.system for c in calls) and result.dist is not None
plain, _ = O.resampled(evaluate(plane))
start = O.objective(plain.ravel()[pr.bins][None, None, :], pr, 0.1)[0]
assert result.objective < start - 0.5, (result.objective, start)
first = result.rounds[0]
assert set(first["model"]) == set(names) and first["sweeps"] >= 1
close = [abs(first["surrogate"][k] / first["model"][k] - 1) < 0.1 for k in ("75R", "50R", "50V")]
assert all(close), first
cells = {(e.y0, e.z0) for e in result.elements}
assert len(cells) == len(result.elements)
assert all(abs(e.deflect_h) + e.spread_h <= O.REACH for e in result.elements)

# ---- R112's zone I in the table of the test points
dist = al_photometry.Distribution(np.arange(-20, 20.01, 0.25), np.arange(-6, 3.01, 0.1), np.zeros((91, 161)), 0, 0, 1000)
dist.intensity[(dist.v > -1.0) & (dist.v < -0.7)] = 12000.0
dist.intensity[dist.v < -2.0] = 30000.0
rows = {r[0]: r for r in al_photometry.test_points(dist, cut)}
assert rows["zone I"][-1] == "not met" and "2 × I(50R)" in rows["zone I"][5]
dist.intensity[dist.v < -2.0] = 20000.0
assert {r[0]: r for r in al_photometry.test_points(dist, cut)}["zone I"][-1] == "ok"


# ---- the plugin's action, against a recorded context
class Host:
    def __init__(self):
        self.results, self.logs, self.set = [], [], {}

    def send(self, message):
        if message.get("type") == "log":
            self.logs.append(message["text"])

    def request(self, method, args):
        json.dumps(args)
        if method == "model.entities":
            return []
        if method == "params.set":
            self.set.update(args["values"])
            return None
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
assert "optimise_lens" in plugin.actions()
host = Host()
ctx = Context(host, 1, plugin.convert_params({"lamp": "H4 (low beam)", "frame_width": 80.0, "frame_height": 50.0,
                                              "frame_radius": 8.0, "cell_width": 8.0, "cell_height": 8.0,
                                              "focus_behind": 3.0, "sampling": 2.0, "optimise_rounds": 0,
                                              "optimise_blur": "none"}), [])
try:
    plugin.optimise_lens(ctx)
    raise AssertionError("the facetted reflector has no lens")
except al_plugin.UserError as e:
    assert "patterned lens" in str(e)
ctx.params["system"] = al_plugin.PATTERNED
summary = plugin.optimise_lens(ctx)
assert summary.startswith(f"lens optimised ({plane.cells} cells); filament images: R112"), summary
assert len(host.set["elements"]) == plane.cells and ctx.params["elements"] == host.set["elements"]
assert host.results == ["image", "table", "curve", "curve"], host.results
log = "\n".join(host.logs)
assert "round 1:" in log and "filament images: R112" in log and "cut-off at V" in log
again = plugin.lens_system(ctx)                    # the table builds the lens it was optimised for
assert again.cells == plane.cells and len(again.settings.elements) == plane.cells

print("al optimise ok")
