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
# a real beam's: a band under both branches, the rising branch lit and sharp
real = O.probes(cut, band=6000.0, rise=3000.0)
assert [g.name for g in real.groups][15:18] == ["under the line", "under the rise", "over the rise"]
rg = {g.name: g for g in real.groups}
bh, bv = h[real.bins % len(h)], v[real.bins // len(h)]
bl = np.degrees(np.arctan(cut.line(np.tan(np.radians(bh)))))
u = rg["under the line"].at
assert rg["under the line"].low == 6000.0 and np.all(np.abs(bh[u]) <= O.BAND_H)
assert np.all((bl[u] - bv[u] >= O.BAND_V[0] - 1e-9) & (bl[u] - bv[u] <= O.BAND_V[1] + 1e-9))
assert bh[u].min() < -5 and bh[u].max() > 5                                          # both branches
r_, o_ = rg["under the rise"].at, rg["over the rise"].at
assert rg["under the rise"].low == 3000.0 and np.all((bh[r_] >= 1.0) & (bh[r_] <= 5.0)) and np.all(bv[r_] < bl[r_])
assert rg["over the rise"].relative == "under the rise" and np.all(bv[o_] > bl[o_])
mirrored = O.probes(dataclasses.replace(cut, right_hand_traffic=False), rise=3000.0)
mg = {g.name: g for g in mirrored.groups}
assert np.all(h[mirrored.bins[mg["under the rise"].at] % len(h)] < 0) and "under the line" not in mg

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
lit = np.full(len(real.bins), 3000.0)                # the same beam with a band and a rise
lit[rg["under the line"].at] = lit[rg["under the rise"].at] = 7000.0      # (a bin is probed once: the
lit[rg["zone III"].at] = lit[rg["above the cut-off"].at] = lit[rg["over the cut-off"].at] = 100.0   # band
lit[rg["B50L"].at] = lit[rg["BR"].at] = lit[rg["over the rise"].at] = 100.0                         # first)
for name in ("75R", "50R", "50V"):
    lit[rg[name].at] = 12000.0
lit[rg["under the cut-off"].at] = 5000.0
points = np.concatenate([g.at for g in real.groups if g.weight >= 1.0])
dark = lit.copy()
dark[np.setdiff1d(np.concatenate([rg["under the line"].at, rg["under the rise"].at]), points)] = 3000.0
assert O.objective(lit[None, None, :], real, 0.1)[0] < 0
assert O.objective(dark[None, None, :], real, 0.1)[0] > O.objective(lit[None, None, :], real, 0.1)[0] + 0.02
legal = lit.copy()                                   # but R112 comes first: a shortfall at 75R costs more
legal[rg["75R"].at] = 6000.0
assert O.objective(legal[None, None, :], real, 0.1)[0] > O.objective(dark[None, None, :], real, 0.1)[0]
report = O.report(np.stack([ok, glare]), pr)
assert report["zone III"] == 2000.0 and report["75R"] == 12000.0
# the evenness: the field below the cut-off on its lattice; a slope has no bumps, a patch has
fh, fv = h[pr.bins[pr.field] % len(h)], v[pr.bins[pr.field] // len(h)]
assert np.allclose(np.diff(fh[0]), O.BUMP_H * O.DH) and np.allclose(np.diff(fv[:, 0]), O.BUMP_V * O.DV)
line = np.degrees(np.arctan(cut.line(np.tan(np.radians(fh)))))
assert (fv[pr.inside] <= line[pr.inside] - O.FIELD_GAP + 1e-9).all() and pr.inside.mean() > 0.5
assert pr.reference == 10100.0
slope = ok.copy()
slope[pr.field] = 5000.0 + 100.0 * fh + 300.0 * fv
assert O.evenness(slope, pr) < 1e-12
patch = slope.copy()
patch[pr.field[5, 10]] += 3000.0
assert O.evenness(patch, pr) > 0.01
assert O.objective(patch[None, None, :], pr, 0.1, 1.0)[0] > O.objective(slope[None, None, :], pr, 0.1, 1.0)[0] + 1e-4

# ---- the target beam: the plane lens' light under the cut-off spread across, the wedge under the
# rise filled, nothing above the line, as much light as the plane lens has
HH, VV = np.meshgrid(h, v)
beam = np.where((VV < -0.6) & (VV > -4.0) & (np.abs(HH) < 8.0), 10000.0, 0.0) \
    + np.where((VV > -0.57) & (VV < 0.5) & (HH > 0.0) & (HH < 6.0), 3000.0, 0.0)
T = O.target(cut, beam)
om = al_photometry._solid_angle(HH, VV, O.DH, O.DV)
assert abs((T * om).sum() / (beam * om).sum() - 1) < 1e-9
top = np.minimum(np.degrees(np.arctan(cut.line(np.tan(np.radians(HH))))), O.TARGET_TOP)
assert T[VV > top + 0.4].max() == 0.0 and T[(HH < 0) & (VV > cut.v_deg)].max() == 0.0
at = lambda x, y: T[int(np.argmin(np.abs(v - y))), int(np.argmin(np.abs(h - x)))]  # noqa: E731
rise_line = lambda x: min(-0.57 + np.tan(np.radians(15.0)) * x, O.TARGET_TOP)       # noqa: E731
assert at(3.25, rise_line(3.25) - 0.3) > 0.5 * at(0.25, -0.87) and at(-3.0, 0.0) == 0.0   # the wedge lit as under the line
assert at(6.25, 1.5) == 0.0 and at(6.25, 0.7) > 0.0                                 # up to TARGET_TOP
row = T[int(np.argmin(np.abs(v + 1.0)))]
assert (row * h).sum() / row.sum() > 0.0                                           # its core to the driver's side
deep = T[int(np.argmin(np.abs(v + 3.0)))]
left = h < 0.0                                                                     # (the side not lifted to the rise)
assert deep[left].max() / deep[left].sum() < row[left].max() / row[left].sum()     # wider further down
lefthand = dataclasses.replace(cut, right_hand_traffic=False)
assert np.allclose(O.target(lefthand, beam[:, ::-1]), T[:, ::-1])                  # mirrored for left-hand traffic
fitted = O.probes(cut, band=6000.0, rise=3000.0, fit=True)
assert len(set(fitted.bins.tolist())) == len(fitted.bins)                          # a bin probed once
fh_, fv_ = h[fitted.bins[fitted.fit] % len(h)], v[fitted.bins[fitted.fit] // len(h)]
assert np.abs(fh_).max() <= O.FIT_H and fv_.min() >= O.FIT_V - O.DV and fv_.max() <= O.FIT_TOP
assert np.allclose(np.diff(np.unique(fh_)), 2 * O.DH)
O.set_target(fitted, T, 2.0)
on = T.ravel()[fitted.bins]
assert O.fit_error(on, fitted) < 1e-12 and abs(O.fit_error(0.0 * on, fitted) - 1) < 1e-12
untargeted = dataclasses.replace(fitted, fit_weight=None)
for x, extra in ((on, 0.0), (0.0 * on, 2.0)):                                    # its weight: that of the beam missing it all
    assert abs(O.objective(x[None, None, :], fitted, 0.1)[0] - O.objective(x[None, None, :], untargeted, 0.1)[0] - extra) < 1e-9
assert O.objective(patch[None, None, :], pr, 0.1)[0] == O.objective(slope[None, None, :], pr, 0.1)[0]

# ---- a small H4 lens: the cells' light, the surrogate against the filament images
frame = al_layout.rounded_rectangle(80.0, 50.0, 8.0)
settings = al_lens.LensSettings(H4, cut, (al_lens.Element(-1e3, 1e3, -1e3, 1e3),), focus_behind=3.0, cell_width=8.0,
                                cell_height=8.0)
plane = al_lens.build(settings, frame)
rays = O.lens_rays(plane, spacing=2.0)
assert len(rays.cells) == plane.cells and rays.cell.max() < len(rays.cells) and (rays.flux > 0).all()
sur = O.Surrogate(rays, pr, np.zeros((1, len(pr.bins))), cell=(8.0, 8.0))
ANG = lambda a: int(np.flatnonzero(O.ANGLE == a)[0])                  # noqa: E731
zero = O.Choice(*(np.full(len(rays.cells), z, dtype=np.int64) for z in (16, 15, 0, ANG(0.0))))
assert O.DEFLECT_H[16] == 0.0 and O.DEFLECT_V[15] == 0.0
flat = sur.full(zero)[0]
inside = (rays.H >= O.H_RANGE[0]) & (rays.H < O.H_RANGE[1]) & (rays.V >= O.V_RANGE[0]) & (rays.V < O.V_RANGE[1])
assert abs(flat.sum() / rays.flux[inside].sum() - 1) < 1e-5
assert O.SPREAD[1] == 1.0
moved = O.Choice(np.full(len(rays.cells), 22), zero.dv.copy(), np.full(len(rays.cells), 1), np.full(len(rays.cells), ANG(90.0)))
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
# a cylinder turned by 15° (strength 6°): the surrogate's slanting smear against the lens built
assert O.SPREAD[5] == 6.0
slant = O.Choice(zero.dh.copy(), zero.dv.copy(), np.full(len(rays.cells), 5), np.full(len(rays.cells), ANG(15.0)))
built = al_lens.build(dataclasses.replace(settings, elements=(al_lens.Element(-1e3, 1e3, -1e3, 1e3, 0.0, 0.0, 6.0, 0.0, 15.0),)),
                      frame)
model15 = al_photometry.intensity(H4, built.filament, *built.samples(2.0), np.full(len(built.samples(2.0)[0]), 0.85),
                                  after=lambda o, d: built.through(o, d, 0.92), n_axial=8, n_around=16)
seen15, _ = O.resampled(model15)
pred15 = sur.full(slant)[0] / omega
on = seen15 > 0.2 * seen15.max()
assert abs(pred15[on].sum() / seen15[on].sum() - 1) < 0.1 and np.abs(pred15[on] / seen15[on] - 1).mean() < 0.25
H2, V2 = np.meshgrid(h, v)
tilt = lambda m: np.degrees(np.arctan(np.polyfit(H2[m > 0.2 * m.max()], V2[m > 0.2 * m.max()], 1)[0] / 1.0))  # noqa: E731
assert abs(tilt(pred15) - tilt(seen15)) < 3.0 and tilt(seen15) > 5.0, (tilt(pred15), tilt(seen15))
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
close = [abs(first["surrogate"][k] / first["model"][k] - 1) < 0.15 for k in ("75R", "50R", "50V")]
assert all(close), first
cells = {(e.y0, e.z0) for e in result.elements}
assert len(cells) == len(result.elements)
assert all(abs(e.deflect_h) + e.spread_h <= O.REACH for e in result.elements)

# ---- two starts, one search each: the better kept, both searches' rounds told
calls.clear()
both = O.optimise(settings, frame, evaluate, rounds=0, spacing=2.0, direct=False, starts=(O.CYLINDERS, None))
assert [r["start"] for r in both.rounds] == [0, 1] and len(calls) == 2
assert both.objective == min(r["objective"] for r in both.rounds)
assert both.rounds[both.start]["objective"] == both.objective
assert any(e.spread_h > 0 for e in both.elements) or both.start == 1

# ---- which cells' light ends at the rising branch: above the horizontal one on the driver's side
fake = O.Rays([(0, 0), (1, 0), (2, 0)], np.array([0, 0, 1, 1, 2, 2]), np.array([-3.0, 2.0, 3.0, 4.0, -3.0, -4.0]),
              np.array([-1.5, -2.0, 0.3, 0.6, 0.3, 0.6]), np.ones(6))
assert list(O.edges(fake, cut)) == [False, True, False]
assert list(O.edges(fake, dataclasses.replace(cut, right_hand_traffic=False))) == [False, False, True]

# ---- along the edges, a real beam's band and rise, and a round for what the ray tracing adds
calls.clear()
traced = []


def check(system):
    traced.append(system)
    d = evaluate(system)
    d.intensity = d.intensity + 300.0 * ((d.v[:, None] > 1.0) & (np.abs(d.h[None, :]) < 6.0))   # stray light above
    return d


edged = O.optimise(settings, frame, evaluate, rounds=0, spacing=2.0, direct=False, starts=(O.CYLINDERS,),
                   along_edges=True, band=4000.0, rise=1500.0, check=check, fit=1.0)
n = O.CHECKS
assert len(traced) == 1 + n and len(calls) == 2 + 2 * n and edged.rounds[-n - 1].get("traced") is True
assert all(r.get("checked") for r in edged.rounds[-n:]) and edged.traced is not None
assert edged.objective == min(r["objective"] for r in edged.rounds[-n - 1:])
assert "under the line" in edged.rounds[0]["model"] and np.isfinite(edged.objective)
assert all(0.0 < f < 1.0 for f in edged.rounds[0]["fit"])                          # the target beam, missed by
assert [x.branch for x in edged.sectors] == ["rising", "horizontal"]           # the wedge, cut out radially
a0, a1 = edged.sectors[0].az_from, edged.sectors[1].az_from
assert 270.0 < a0 < 360.0 and (a1 > a0 or a1 < 30.0), (a0, a1)                    # below the left side (driver's view)
# the sectors searched: the lines first found, each moved in turn; the lowest kept
assert len(edged.scouted) == 2 * len(O.SCOUT) + 1 and len({x[:2] for x in edged.scouted}) == len(edged.scouted)
assert min(edged.scouted, key=lambda x: x[2])[:2] == (a0, a1)
first_found = edged.scouted[0][:2]
assert all(x[0] == first_found[0] or x[1] == first_found[1] or x[0] == a0 for x in edged.scouted)
cutlens = al_lens.build(dataclasses.replace(settings, sectors=edged.sectors), frame)
assert len(edged.elements) == cutlens.cells > plane.cells and all(e.sector in (0, 1) for e in edged.elements)
slope = cut.slope
rising = [cutlens.branch(e.sector) == "rising" for e in edged.elements]
for e, up in zip(edged.elements, rising):
    if up:
        assert abs(e.deflect_v - slope * e.deflect_h) <= O.ALONG + 1e-9, e
        assert e.spread_h == 0.0 or abs(e.spread_angle - 15.0) <= O.TILT, e
    else:
        assert e.spread_h == 0.0 or e.spread_angle == 0.0, e
assert any(rising)

# ---- cylinder strips: a segment's prism its own, the cylinder the strip's – through it
calls.clear()
stripped = dataclasses.replace(settings, structure=al_lens.STRIPS, pitch=5.0, segment=10.0)
flutes = O.optimise(stripped, frame, evaluate, rounds=0, spacing=2.0, direct=False, starts=(O.CYLINDERS,),
                    along_edges=True, scout=False, least=2.0)
fluted = al_lens.build(dataclasses.replace(stripped, sectors=flutes.sectors), frame)
assert fluted.strips and len(flutes.elements) == fluted.cells > fluted.ny and len(calls) == 1
assert flutes.objective < start - 0.5, (flutes.objective, start)
by_strip = {}
for e in flutes.elements:
    by_strip.setdefault((e.y0, e.sector), set()).add((e.spread_h, e.spread_angle))
    lean = fluted.tilts[e.sector]
    assert e.spread_angle == round(lean, 6) and e.spread_v == 0.0 and e.z1 - e.z0 == 10.0, e
    if lean:
        assert abs(e.deflect_v - slope * e.deflect_h) <= O.ALONG + 1e-9, e
assert all(len(x) == 1 for x in by_strip.values())                                 # one cylinder per strip,
assert all(e.spread_h >= 2.0 for e in flutes.elements)                             # a real one (least)
assert len({x for v_ in by_strip.values() for x in v_}) > 1 and any(e.deflect_v for e in flutes.elements)
again_ = al_lens.build(dataclasses.replace(stripped, sectors=flutes.sectors, elements=flutes.elements), frame)
assert again_.cells == fluted.cells and not again_.warnings

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
                                              "lens_structure": al_plugin.CELLS,
                                              "focus_behind": 3.0, "sampling": 2.0, "optimise_rounds": 0,
                                              "optimise_blur": "none",
                                              "optimise_start": "both, the better kept"}), [])
try:
    plugin.optimise_lens(ctx)
    raise AssertionError("the facetted reflector has no lens")
except al_plugin.UserError as e:
    assert "patterned lens" in str(e)
ctx.params["system"] = al_plugin.PATTERNED
summary = plugin.optimise_lens(ctx)
n_parts = len(host.set["elements"])
assert summary.startswith(f"lens optimised ({n_parts} elements); filament images: R112"), summary
assert n_parts > plane.cells and ctx.params["elements"] == host.set["elements"]
assert [r["branch"] for r in host.set["lens_sectors"]] == ["rising", "horizontal"]
assert {r["sector"] for r in host.set["elements"]} == {0, 1}
assert host.results == ["image", "table", "curve", "curve"], host.results
log = "\n".join(host.logs)
assert "start 1 (cylinder lenses), round 1:" in log and "start 2 (plane glass), round 1:" in log
assert "kept: the search from" in log and "filament images: R112" in log and "cut-off at V" in log
assert "the lens cut into sectors" in log and "the sectors searched: rising" in log
assert "off the target beam by" in log
again = plugin.lens_system(ctx)                    # the tables build the lens it was optimised for
assert again.cells == n_parts and len(again.settings.elements) == n_parts and again.count == 2

print("al optimise ok")
