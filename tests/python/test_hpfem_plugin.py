"""hp-FEM plugin: job <-> panel round trip and the result tables (without hpfem) and, if hpfem is
installed, Check and Solve of a small grating job (skips with 77 else for that part only)."""

import copy
import json
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "python"))
sys.path.insert(0, str(root / "python" / "plugins" / "hpfem"))

import hpfem_job  # noqa: E402
import hpfem_map  # noqa: E402
import hpfem_results  # noqa: E402
from hpfem_plugin import HpFemPlugin  # noqa: E402


def as_panel(values: dict) -> dict:
    """The values as CAD stores and passes them: defaults, JSON round trip, converted per type."""
    out = {}
    for name, param in HpFemPlugin.params.items():
        out[name] = param.convert(json.loads(json.dumps(values.get(name, param.default))))
    return out


# grammars
assert hpfem_job.material_spec("SiO2") == "SiO2"
assert hpfem_job.material_spec("1.5") == {"n": 1.5}
assert hpfem_job.material_spec("3.88+0.02i") == {"n": [3.88, 0.02]}
assert hpfem_job.material_spec("eps=2.25-0.1i") == {"eps": [2.25, -0.1]}
assert hpfem_job.material_spec('{"eps": 2, "name": "x"}') == {"eps": 2, "name": "x"}
for spec in ("Au", {"n": 1.5}, {"n": [3.88, 0.02]}, {"eps": [2.25, 0.0]}, {"eps": [-10, 1.5]}, {"eps": 4},
             {"n": [1, 2], "name": "x"}):
    assert hpfem_job.material_spec(hpfem_job.material_text(spec)) == spec, spec
assert hpfem_job.material_text({"eps": [2.25, 0.0]}) == "eps=2.25+0i"
assert hpfem_job.values_spec("400:410:3") == ({"start": 400, "stop": 410, "count": 3}, True)
assert hpfem_job.values_spec("400, 405.5") == ([400, 405.5], True)
assert hpfem_job.values_spec("400") == (400, False)
assert hpfem_job.count("0:80:9") == 9 and hpfem_job.count("1, 2") == 2 and hpfem_job.count("5") == 1
try:
    hpfem_job.unit_name(2.5e-8)
    raise AssertionError("not refused")
except ValueError as e:
    assert "nm, µm" in str(e)

# round trips: the example, and a job with every form the panel keeps or shows otherwise
OTHER = {
    "version": 2, "problem": "grating", "name": "mixed", "unit": 1e-6,
    "model": {"period": 0.5, "y_bottom": -1, "y_top": 1.2, "background_tag": 1, "x0": 0,
              "slabs": [{"tag": 2, "y0": -1, "y1": 0}],
              "shapes": [{"kind": "trapezoid", "tag": 3, "params": {"x": 0.25, "y": 0, "bottom": 0.2, "top": 0.1,
                                                                     "height": 0.1}},
                         {"kind": "ellipse", "tag": 4, "params": {"x": 0.25, "y": 0.3, "rx": 0.05, "ry": 0.04}},
                         {"kind": "polygon", "tag": 3, "params": {"points": [[0, 0.5], [0.1, 0.5], [0.05, 0.6]]}},
                         {"kind": "rectangle", "tag": 4, "params": {"x": 0, "y": 0}, "note": "kept as JSON"}]},
    "mesh": {"gmsh": {"interface_factor": 0.4, "sizes": {"1": 0.05}}},
    "materials": {"1": "air", "2": {"n": [1.45, 0]}, "3": "Si", "4": {"eps": [-10, 1.5]}},
    "stack": {"incidence": "air", "substrate": {"n": 1.45},
              "layers": [{"material": "TiO2", "thickness": 0.02}], "top": 0.02},
    "incidence": {"polarisation": "s", "phi_deg": 0},
    "sweep": {"theta_deg": {"start": 0, "stop": 60, "count": 7}},
    "solver": {"order": 4, "bottom": "pec", "orders_max": 3, "check": False, "snap_tolerance": 1e-8},
    "maps": [{"quantity": "E", "x": [0, 0.5, 11], "y": [-0.5, 1, 31]}],
}
OTHER["incidence"]["wavelength"] = 0.6
for job in (hpfem_job.EXAMPLE, OTHER):
    p = as_panel(hpfem_job.to_params(job))
    back = hpfem_job.to_job(p)
    assert back == job, json.dumps({"job": job, "back": back}, indent=1)
p = hpfem_job.to_params(OTHER)
assert p["advanced"] == {"version": 2, "model": {"x0": 0}, "mesh": {"gmsh": {"sizes": {"1": 0.05}}},
                         "solver": {"snap_tolerance": 1e-8}, "maps": OTHER["maps"]}, p["advanced"]
assert [s["kind"] for s in p["shapes"]] == ["trapezoid", "ellipse", "polygon", "json"]
assert p["theta_deg"] == "0:60:7" and p["wavelength"] == "0.6" and p["unit"] == "µm"
assert hpfem_job.points_count(p) == 7
assert p["materials"][1]["material"] == "1.45+0i" and p["substrate"] == "1.45"
# a wavelength sweep, no PML given (hp-FEM's recommendation), old polarisation names
wl = copy.deepcopy(hpfem_job.EXAMPLE)
wl["incidence"] = {"polarisation": "TE", "theta_deg": 0, "phi_deg": 0}
wl["sweep"] = {"wavelength": [400, 450, 500]}
wl["solver"] = {"order": 2, "bottom": "pml", "orders_max": 1, "check": True}
p = hpfem_job.to_params(wl)
assert p["polarisation"] == "s" and p["wavelength"] == "400, 450, 500" and (p["pml_top"], p["pml_bottom"]) == (0, 0)
back = hpfem_job.to_job(as_panel(p))
assert back["sweep"] == wl["sweep"] and "wavelength" not in back["incidence"] and "pml" not in back["solver"]
for bad, why in (({"wavelength": "400, 410", "theta_deg": "0:10:2"}, "not both"),
                 ({"mesh_kind": "file", "mesh_file": ""}, "msh"),
                 ({"materials": [{"tag": 1, "material": "eps=x"}]}, "eps="),
                 ({"shapes": [{"kind": "polygon", "tag": 3, "points": [{"x": 0, "y": 0}]}]}, "three points")):
    try:
        hpfem_job.to_job(as_panel({**hpfem_job.to_params(hpfem_job.EXAMPLE), **bad}))
        raise AssertionError(f"not refused: {bad}")
    except ValueError as e:
        assert why in str(e), (why, e)
for job, why in (({**hpfem_job.EXAMPLE, "task": "bands"}, "scattering"), ({**hpfem_job.EXAMPLE, "unit": 3e-9}, "unit")):
    try:
        hpfem_job.to_params(job)
        raise AssertionError("not refused")
    except ValueError as e:
        assert why in str(e), e

# results (synthetic points as the runner gives them)
def point(i, wl, r0, t0, t1):
    return {"i": i, "wavelength": wl * 1e-9, "theta_deg": 0.0, "R": r0, "T": t0 + t1, "A": 1 - r0 - t0 - t1,
            "balance": 1e-5, "dofs": 100, "seconds": 0.5,
            "R_orders": [{"m": 0, "efficiency": r0, "propagating": True},
                         {"m": 1, "efficiency": 0.0, "propagating": False}],
            "T_orders": [{"m": 0, "efficiency": t0, "propagating": True},
                         {"m": 1, "efficiency": t1, "propagating": t1 > 0}]}


pts = [point(0, 400, 0.1, 0.6, 0.2), point(1, 450, 0.2, 0.7, 0.0), point(2, 500, 0.3, 0.7, 0.0)]
assert hpfem_results.order_rows(pts[1]) == [["R", 0, 0.2, "yes"], ["T", 0, 0.7, "yes"]]
assert len(hpfem_results.order_rows(pts[1], evanescent=True)) == 4
assert hpfem_results.order_bars(pts[0]) == (["R 0", "T 0", "T 1"], [0.1, 0.6, 0.2])
label, found = hpfem_results.curves(pts, 1e-9, "nm")
names = {name: (x, y) for name, x, y in found}
assert label == "λ / nm" and sorted(names) == ["A", "R 0", "T 0", "T 1", "ΣR", "ΣT"], names
assert names["T 1"] == ([400.0], [0.2]) and names["ΣR"][1] == [0.1, 0.2, 0.3]
assert abs(names["ΣR"][0][1] - 450.0) < 1e-9
row = hpfem_results.point_rows(pts, 1e-9)[2]
assert row[0] == 2 and abs(row[1] - 500.0) < 1e-9 and row[2:4] == [0.0, 0.3], row
assert hpfem_results.diagnostic_lines([{"severity": "warning", "text": "thin", "hint": "thicker"}]) == [
    "warning: thin – thicker"]

# field maps without hpfem: grid, the job of one point, pictures, the cell's tags
assert hpfem_map.sweep_values("400:420:3") == [400.0, 410.0, 420.0] and hpfem_map.sweep_values("5") == [5.0]
ex = hpfem_job.EXAMPLE
xs_, ys_ = hpfem_map.grid(ex, {"map_periods": 2, "map_nx": 5, "map_ny": 7})
assert xs_ == [-200.0, 600.0, 5] and ys_ == [-800 + 419, 950 - 419, 7], (xs_, ys_)
assert hpfem_map.grid(ex, {"map_x_from": -50, "map_x_to": 50, "map_y_from": 1, "map_y_to": 2})[0] == [-50, 50, 201]
pp = {"wavelength": "400:420:3", "theta_deg": "50", "map_quantity": "S", "map_scattered": True}
one, wl1, th1 = hpfem_map.point_job({**ex, "sweep": {"wavelength": {"start": 400, "stop": 420, "count": 3}},
                                     "maps": [{"quantity": "H"}]}, pp, 2, xs_, ys_)
assert (wl1, th1) == (420.0, 50.0) and "sweep" not in one and one["incidence"]["wavelength"] == 420
assert one["maps"] == [{"quantity": "S", "x": xs_, "y": ys_, "scattered": True}]
try:
    hpfem_map.point_job(ex, pp, 3, xs_, ys_)
    raise AssertionError("not refused")
except ValueError as e:
    assert "3 points" in str(e)
try:
    import numpy as np
except ImportError:  # CI without numpy: the pure part only
    print("numpy not installed: round trip only")
    sys.exit(77)

vals = np.zeros((2, 3, 3), dtype=complex)
vals[:, :, 0] = [[1 + 1j, -2, 3], [4, 5j, np.nan]]
pic = hpfem_map.picture(np.array([0.0, 1.0, 2.0]), np.array([10.0, 20.0]), vals, "Re Fx")
assert (pic.width, pic.height, pic.missing) == (3, 2, 1) and pic.values[:5] == [1, -2, 3, 4, 0]
assert pic.extent == (-0.5, 2.5, 5.0, 25.0) and pic.value_range == (-4.0, 4.0) and pic.colormap == "coolwarm"
pic = hpfem_map.picture(np.array([0.0, 1.0, 2.0]), np.array([10.0, 20.0]), vals, "|F|²")
assert abs(pic.values[0] - 2.0) < 1e-12 and pic.value_range is None and hpfem_map.label("|F|²", "E") == "|E|²"
grid_tags, unknown = hpfem_map.tags(ex, [0.0, 150.0, 400.0, 0.0, 0.0], [50.0, 50.0, 50.0, -100.0, 500.0])
assert [grid_tags[k, k] for k in range(5)] == [3, 1, 3, 2, 1] and unknown == [], grid_tags
tri = {"model": {"period": 1, "y_bottom": 0, "y_top": 1, "background_tag": 1, "slabs": [],
                 "shapes": [{"kind": "polygon", "tag": 2, "params": {"points": [[0, 0], [0.4, 0], [0, 0.4]]}},
                            {"kind": "ellipse", "tag": 3, "params": {"x": 0.25, "y": 0.75, "rx": 0.1, "ry": 0.1}},
                            {"kind": "star", "tag": 4, "params": {}}]}}
grid_tags, unknown = hpfem_map.tags(tri, [0.1, 0.3, 0.25], [0.1, 0.3, 0.75])
assert [grid_tags[k, k] for k in range(3)] == [2, 1, 3] and unknown == ["3 (star)"], (grid_tags, unknown)

# the plugin's actions with hpfem (a coarse cell: a few seconds)
try:
    import hpfem  # noqa: F401
except ImportError:
    print("hpfem not installed: round trip only")
    sys.exit(77)


class Ctx:
    def __init__(self, params):
        self.params, self.out = params, {}

    def progress(self, value, text=""):
        assert 0.0 <= value <= 1.0, value
        self.out.setdefault("progress", []).append(value)

    def log(self, m):
        self.out.setdefault("log", []).append(m)

    def result_set(self, name):
        self.out["run"] = name
        return 1

    def table(self, run, name, columns, rows, **k):
        self.out.setdefault("tables", {})[name] = (columns, rows)

    def bars(self, run, name, labels, values, **k):
        self.out["bars"] = (labels, values)

    def curve(self, run, name, x=(), y=(), **k):
        self.out.setdefault("curves", {})[name] = (x, y)

    def image(self, run, name, values, width, height, **k):
        assert len(values) == width * height
        self.out.setdefault("images", {})[name] = (values, width, height, k)

    def set_params(self, values):
        self.params.update(as_panel({**self.params, **values}))

    def cancelled(self):
        return False


coarse = copy.deepcopy(hpfem_job.EXAMPLE)
coarse["mesh"] = {"structured": {"nx": 8, "rows": [[-800, 0, 10], [0, 148, 2], [148, 950, 10]]}}
coarse["solver"]["order"] = 2
coarse["incidence"] = {"polarisation": "p", "theta_deg": 50, "phi_deg": 30}
coarse["sweep"] = {"wavelength": {"start": 400, "stop": 420, "count": 2}}
plugin = HpFemPlugin()
with tempfile.TemporaryDirectory() as d:
    src, dst = Path(d) / "job.json", Path(d) / "saved.json"
    src.write_text(json.dumps(coarse))
    ctx = Ctx(as_panel({"job_file": str(src), "save_as": str(dst), "results_file": str(Path(d) / "out" / "r.json")}))
    message = plugin.load_job(ctx)
    assert "2 points" in message, message
    plugin.save_job(ctx)
    assert json.loads(dst.read_text()) == coarse
    message = plugin.check_job(ctx)
    assert "ready to solve" in message and "points" not in ctx.out.get("tables", {}), message
    assert any(line.startswith("estimate:") for line in ctx.out["log"]), ctx.out["log"]
    message = plugin.solve(ctx)
    assert message.startswith("2 points"), message
    curves = ctx.out["curves"]
    assert {"ΣR", "ΣT", "A"} <= set(curves) and all(abs(a - b) < 1e-9 for a, b in zip(curves["ΣR"][0], [400.0, 420.0])), curves.keys()
    rows = ctx.out["tables"]["Points"][1]
    assert len(rows) == 2 and all(abs(r[3] + r[4] + r[5] - 1) < 0.02 for r in rows), rows
    assert (Path(d) / "out" / "results.json").exists()
    assert max(ctx.out["progress"]) <= 1.0
    # a single point: the order table and bars
    ctx.params["wavelength"] = "400"
    message = plugin.solve(ctx)
    assert message.startswith("ΣR"), message
    columns, rows = ctx.out["tables"]["Orders"]
    assert columns == hpfem_results.ORDER_COLUMNS and {r[0] for r in rows} == {"R", "T"}
    r_sum = sum(r[2] for r in rows if r[0] == "R")
    assert abs(r_sum - float(message.split()[1].rstrip(","))) < 1e-3, (rows, message)
    assert ctx.out["bars"][0][0].startswith(("R", "T"))
    # field maps: |E|² over two periods, periodic (inside the cells: on the cell edge the normal component
    # jumps between the elements of the two sides); the power flow S_y in the substrate points down
    ctx.params.update({"wavelength": "400:420:2", "map_point": 2, "map_nx": 17, "map_ny": 23, "map_npz": str(Path(d) / "m.npz")})
    message = plugin.field_map(ctx)
    values, width, height, k = ctx.out["images"]["|E|²"]
    assert (width, height) == (17, 23) and all(np.isfinite(values)), message
    grid = np.array(values).reshape(height, width)
    assert np.allclose(grid[:, 1], grid[:, 9], rtol=1e-9) and k["extent"][0] == -225.0, k["extent"]
    assert "λ = 420" in ctx.out["run"] and (Path(d) / "m.npz").exists()
    ctx.params.update({"map_quantity": "S", "map_show": "Re Fy", "map_y_from": -700, "map_y_to": -300, "map_npz": ""})
    plugin.field_map(ctx)
    values, width, height, k = ctx.out["images"]["Re Sy"]
    assert np.mean(values) < 0 and k["value_range"][0] == -k["value_range"][1], (np.mean(values), k)
    ctx.params["map_point"] = 3
    try:
        plugin.field_map(ctx)
        raise AssertionError("not refused")
    except Exception as e:  # noqa: BLE001
        assert "2 points" in str(e), e
    ctx.params.update({"map_y_from": 0, "map_y_to": 0})
    message = plugin.show_cell(ctx)
    assert message.startswith("3 tags") and any(line.startswith("tag 3: eps=2.25") for line in ctx.out["log"]), message
print("hp-FEM plugin ok")
