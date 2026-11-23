"""hp-FEM grating job <-> panel values (pure Python, no hpfem needed).

The job is the document of hp-FEM's job runner (`python -m hpfem.run`, schema version 1, task
"scattering"): unit cell (period, slabs, shapes), materials by cell tag, background stack,
incidence, sweep, mesh and solver. The panel shows these; every other key of the file (maps,
model.x0, solver tolerances, other tasks' blocks, …) is kept verbatim under *Advanced* and
merged back when the job is written, so loading and saving gives the same file.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

UNITS = {"nm": 1e-9, "µm": 1e-6, "mm": 1e-3, "m": 1.0}
SHAPE_KINDS = ("rectangle", "trapezoid", "ellipse", "polygon")
SHAPE_FIELDS = {
    "rectangle": ("x", "y", "width", "height"),
    "trapezoid": ("x", "y", "bottom", "top", "height"),
    "ellipse": ("x", "y", "rx", "ry"),
}
MESH_KINDS = ("structured", "gmsh", "file")
BOTTOMS = ("pml", "pec", "modal")

#: the example of hp-FEM's job runner (run.py): a dielectric bar on SiO2, p polarised at 50°
EXAMPLE: dict[str, Any] = {
    "version": 1, "problem": "grating", "name": "bar on SiO2", "unit": 1e-9,
    "model": {"period": 400, "y_bottom": -800, "y_top": 950, "background_tag": 1,
              "slabs": [{"tag": 2, "y0": -800, "y1": 0}],
              "shapes": [{"kind": "rectangle", "tag": 3,
                          "params": {"x": -100, "y": 0, "width": 200, "height": 148}}]},
    "mesh": {"structured": {"nx": 16, "rows": [[-800, 0, 32], [0, 148, 6], [148, 950, 32]]}},
    "materials": {"1": "air", "2": "SiO2", "3": {"eps": [2.25, 0.0]}},
    "stack": {"incidence": "air", "substrate": "SiO2", "layers": [], "top": 0},
    "incidence": {"polarisation": "p", "theta_deg": 50, "phi_deg": 30, "wavelength": 400},
    "solver": {"order": 3, "pml": {"top": 419, "bottom": 419}, "bottom": "pml", "orders_max": 2,
               "check": True},
}


# ---------------------------------------------------------------------------- small grammars
def _num(v: float) -> float | int:
    """Numbers as the file writes them: whole numbers as int (400, not 400.0)."""
    f = float(v)
    return int(f) if f.is_integer() and abs(f) < 1e15 else f


def _fmt(v: float) -> str:
    return repr(_num(v))


def material_text(spec: Any) -> str:
    """A material of the job as one line of text: a library name (`SiO2`), n + i k (`1.5`,
    `3.88+0.02i`), the permittivity (`eps=2.25+0.1i`) or, for any other form, its JSON."""
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict) and len(spec) == 1:
        (key, value), = spec.items()
        if key in ("n", "eps"):
            if isinstance(value, (list, tuple)) and len(value) == 2:
                re_, im = float(value[0]), float(value[1])
                body = f"{_fmt(re_)}{'+' if im >= 0 else '-'}{_fmt(abs(im))}i"
            elif isinstance(value, (int, float)):
                body = _fmt(value)
            else:
                return json.dumps(spec)
            return body if key == "n" else f"eps={body}"
    return json.dumps(spec)


_COMPLEX = re.compile(r"^\s*([-+]?[0-9.]+(?:[eE][-+]?\d+)?)\s*(?:([-+])\s*([0-9.]+(?:[eE][-+]?\d+)?)\s*i)?\s*$")


def material_spec(text: str) -> Any:
    """Inverse of `material_text`."""
    t = str(text).strip()
    if not t:
        raise ValueError("a material is empty")
    if t.startswith("{"):
        return json.loads(t)
    key = "n"
    if t.lower().startswith("eps="):
        key, t = "eps", t[4:]
    m = _COMPLEX.match(t)
    if m is None:
        if key == "eps":
            raise ValueError(f"'eps={t}': write eps=2.25 or eps=2.25+0.1i")
        return t  # a library name
    re_ = _num(m.group(1))
    if m.group(2) is None:
        return {key: re_}
    im = _num(m.group(3)) * (-1 if m.group(2) == "-" else 1)
    return {key: [re_, im]}


def values_text(spec: Any) -> str:
    """A sweep or a single value as text: `400`, `400, 410` or `400:410:3` (start:stop:count)."""
    if isinstance(spec, dict):
        return f"{_fmt(spec['start'])}:{_fmt(spec.get('stop', spec['start']))}:{int(spec['count'])}"
    if isinstance(spec, (list, tuple)):
        return ", ".join(_fmt(v) for v in spec)
    return _fmt(spec)


def values_spec(text: str) -> tuple[Any, bool]:
    """Inverse of `values_text`: (value, is_sweep). A list or a range is a sweep even with one value."""
    t = str(text).strip()
    if not t:
        raise ValueError("no value")
    if ":" in t:
        parts = [p.strip() for p in t.split(":")]
        if len(parts) != 3:
            raise ValueError(f"'{t}': a range is start:stop:count")
        return {"start": _num(parts[0]), "stop": _num(parts[1]), "count": int(parts[2])}, True
    if "," in t:
        return [_num(p) for p in t.split(",") if p.strip()], True
    return _num(t), False


def count(text: str) -> int:
    """Number of values of a value text (1 for a single value)."""
    value, sweep = values_spec(text)
    if not sweep:
        return 1
    return int(value["count"]) if isinstance(value, dict) else len(value)


def unit_name(factor: float) -> str:
    for name, f in UNITS.items():
        if abs(float(factor) - f) <= 1e-12 * f:
            return name
    raise ValueError(f"unit {factor!r}: the panel works in nm, µm, mm or m – change 'unit' in the file")


# ---------------------------------------------------------------------------- job -> panel
def _pop(d: dict, key: str, default: Any = None) -> Any:
    return d.pop(key, default) if isinstance(d, dict) else default


def _shape_item(sh: dict) -> dict:
    item = {"kind": "json", "tag": int(sh.get("tag", 0)), "x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0,
            "bottom": 0.0, "top": 0.0, "rx": 0.0, "ry": 0.0, "points": [], "json": None}
    kind, params = sh.get("kind"), sh.get("params", {})
    simple = set(sh) <= {"kind", "tag", "params"} and isinstance(params, dict)
    if simple and kind in SHAPE_FIELDS and set(params) == set(SHAPE_FIELDS[kind]):
        item["kind"] = kind
        for k in SHAPE_FIELDS[kind]:
            item[k] = float(params[k])
    elif simple and kind == "polygon" and set(params) == {"points"}:
        item["kind"] = "polygon"
        item["points"] = [{"x": float(p[0]), "y": float(p[1])} for p in params["points"]]
    else:
        item["json"] = sh
    return item


def to_params(job: dict) -> dict:
    """Panel values of a job; what the panel does not show goes to `advanced`."""
    rest = copy.deepcopy(job)
    for key, expected in (("problem", "grating"), ("task", "scattering")):
        if rest.get(key, expected) != expected:
            raise ValueError(f"{key} {rest[key]!r}: the panel edits grating scattering jobs")
    _pop(rest, "problem")
    if rest.get("version") == 1:
        rest.pop("version")
    p: dict[str, Any] = {"name": str(_pop(rest, "name", ""))}
    p["unit"] = unit_name(_pop(rest, "unit", 1.0))

    model = rest.get("model", {})
    p["period"] = float(_pop(model, "period", 0.0))
    p["y_bottom"] = float(_pop(model, "y_bottom", 0.0))
    p["y_top"] = float(_pop(model, "y_top", 0.0))
    p["background_tag"] = int(_pop(model, "background_tag", 0))
    p["slabs"] = [{"tag": int(s["tag"]), "y0": float(s["y0"]), "y1": float(s["y1"])}
                  for s in _pop(model, "slabs", [])]
    p["shapes"] = [_shape_item(sh) for sh in _pop(model, "shapes", [])]

    p["materials"] = [{"tag": int(t), "material": material_text(m)}
                      for t, m in dict(_pop(rest, "materials", {})).items()]

    stack = rest.get("stack", {})
    p["incidence_medium"] = material_text(_pop(stack, "incidence", "air"))
    p["substrate"] = material_text(_pop(stack, "substrate", "air"))
    p["stack_layers"] = [{"material": material_text(layer["material"]), "thickness": float(layer["thickness"])}
                         for layer in _pop(stack, "layers", [])]
    p["stack_top"] = float(_pop(stack, "top", 0.0))

    inc = rest.get("incidence", {})
    pol = str(_pop(inc, "polarisation", "p")).strip().lower()
    p["polarisation"] = {"te": "s", "ez": "s", "e_z": "s", "tm": "p", "hz": "p", "h_z": "p"}.get(pol, pol)
    p["phi_deg"] = float(_pop(inc, "phi_deg", 0.0))
    sweep = rest.get("sweep", {})
    if isinstance(sweep, dict) and "wavelength" in sweep and "theta_deg" not in sweep:
        p["wavelength"] = values_text(sweep.pop("wavelength"))  # a bare number becomes the incidence's
        p["theta_deg"] = values_text(_pop(inc, "theta_deg", 0.0))
    elif isinstance(sweep, dict) and "theta_deg" in sweep and "wavelength" not in sweep:
        p["theta_deg"] = values_text(sweep.pop("theta_deg"))
        p["wavelength"] = values_text(_pop(inc, "wavelength", 0.0))
    else:
        p["wavelength"] = values_text(_pop(inc, "wavelength", 0.0))
        p["theta_deg"] = values_text(_pop(inc, "theta_deg", 0.0))

    mesh = rest.get("mesh", {})
    p.update({"mesh_kind": "structured", "mesh_nx": 16, "mesh_rows": [], "gmsh_interface_factor": 0.5,
              "mesh_file": "", "mesh_scale": 1.0})
    if isinstance(mesh.get("structured"), dict):
        s = mesh["structured"]
        p["mesh_nx"] = int(_pop(s, "nx", 16))
        p["mesh_rows"] = [{"y0": float(r[0]), "y1": float(r[1]), "n": int(r[2])} for r in _pop(s, "rows", [])]
    elif isinstance(mesh.get("gmsh"), dict):
        p["mesh_kind"] = "gmsh"
        p["gmsh_interface_factor"] = float(_pop(mesh["gmsh"], "interface_factor", 0.5))
    elif "file" in mesh:
        p["mesh_kind"] = "file"
        p["mesh_file"] = str(mesh.pop("file"))
        p["mesh_scale"] = float(_pop(mesh, "scale", 1.0))

    solver = rest.get("solver", {})
    p["order"] = int(_pop(solver, "order", 4))
    pml = solver.get("pml") if isinstance(solver.get("pml"), dict) else {}
    p["pml_top"] = float(_pop(pml, "top", 0.0))
    p["pml_bottom"] = float(_pop(pml, "bottom", 0.0))
    p["bottom"] = str(_pop(solver, "bottom", "pml"))
    p["orders_max"] = int(_pop(solver, "orders_max", 3))
    p["check"] = bool(_pop(solver, "check", True))

    p["advanced"] = _prune(rest)
    return p


def _prune(d: Any) -> Any:
    """Drops the empty dicts the panel emptied (a dict the file had empty stays only at the top)."""
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        v = _prune(v)
        if isinstance(v, dict) and not v:
            continue
        out[k] = v
    return out


# ---------------------------------------------------------------------------- panel -> job
def _shape(item: dict) -> dict:
    kind = item.get("kind", "rectangle")
    if kind == "json":
        if not isinstance(item.get("json"), dict):
            raise ValueError("a shape of type json needs its JSON")
        return item["json"]
    if kind == "polygon":
        points = [[_num(q["x"]), _num(q["y"])] for q in item.get("points", [])]
        if len(points) < 3:
            raise ValueError("a polygon needs at least three points")
        params: dict[str, Any] = {"points": points}
    elif kind in SHAPE_FIELDS:
        params = {k: _num(item.get(k, 0.0)) for k in SHAPE_FIELDS[kind]}
    else:
        raise ValueError(f"shape type {kind!r}")
    return {"kind": kind, "tag": int(item["tag"]), "params": params}


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def to_job(p: dict) -> dict:
    """The job of the panel values (hp-FEM job runner, schema version 1)."""
    job: dict[str, Any] = {"version": 1, "problem": "grating"}
    if p.get("name"):
        job["name"] = p["name"]
    job["unit"] = UNITS[p.get("unit", "nm")]
    job["model"] = {
        "period": _num(p["period"]), "y_bottom": _num(p["y_bottom"]), "y_top": _num(p["y_top"]),
        "background_tag": int(p.get("background_tag", 0)),
        "slabs": [{"tag": int(s["tag"]), "y0": _num(s["y0"]), "y1": _num(s["y1"])} for s in p.get("slabs", [])],
        "shapes": [_shape(item) for item in p.get("shapes", [])],
    }
    kind = p.get("mesh_kind", "structured")
    if kind == "structured":
        job["mesh"] = {"structured": {"nx": int(p.get("mesh_nx", 16)),
                                      "rows": [[_num(r["y0"]), _num(r["y1"]), int(r["n"])]
                                               for r in p.get("mesh_rows", [])]}}
    elif kind == "gmsh":
        job["mesh"] = {"gmsh": {"interface_factor": _num(p.get("gmsh_interface_factor", 0.5))}}
    else:
        if not p.get("mesh_file"):
            raise ValueError("mesh from a file: choose the .msh file")
        job["mesh"] = {"file": p["mesh_file"], "scale": _num(p.get("mesh_scale", 1.0))}
    job["materials"] = {str(int(m["tag"])): material_spec(m["material"]) for m in p.get("materials", [])}
    job["stack"] = {"incidence": material_spec(p.get("incidence_medium", "air")),
                    "substrate": material_spec(p.get("substrate", "air")),
                    "layers": [{"material": material_spec(layer["material"]), "thickness": _num(layer["thickness"])}
                               for layer in p.get("stack_layers", [])],
                    "top": _num(p.get("stack_top", 0.0))}
    wl, wl_sweep = values_spec(p.get("wavelength", ""))
    th, th_sweep = values_spec(p.get("theta_deg", "0"))
    if wl_sweep and th_sweep:
        raise ValueError("sweep either the wavelength or θ, not both")
    incidence: dict[str, Any] = {"polarisation": p.get("polarisation", "p")}
    if not th_sweep:
        incidence["theta_deg"] = th
    incidence["phi_deg"] = _num(p.get("phi_deg", 0.0))
    if not wl_sweep:
        incidence["wavelength"] = wl
    job["incidence"] = incidence
    if wl_sweep:
        job["sweep"] = {"wavelength": wl}
    elif th_sweep:
        job["sweep"] = {"theta_deg": th}
    solver: dict[str, Any] = {"order": int(p.get("order", 4))}
    pml = {k: _num(p[f"pml_{k}"]) for k in ("top", "bottom") if float(p.get(f"pml_{k}", 0.0)) > 0}
    if pml:
        solver["pml"] = pml
    solver.update({"bottom": p.get("bottom", "pml"), "orders_max": int(p.get("orders_max", 3)),
                   "check": bool(p.get("check", True))})
    job["solver"] = solver
    advanced = p.get("advanced") or {}
    if not isinstance(advanced, dict):
        raise ValueError("Advanced must be a JSON object")
    return _merge(job, advanced)


def points_count(p: dict) -> int:
    """Number of solves of the panel's job (points of the sweep)."""
    return max(count(p.get("wavelength", "0")), count(p.get("theta_deg", "0")))
