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
print("hp-FEM plugin ok")
