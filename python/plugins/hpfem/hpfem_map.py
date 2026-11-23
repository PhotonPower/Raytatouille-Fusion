"""Field maps of an hp-FEM grating job as pictures for the CAD's Image window (numpy, no hpfem).

The job runner samples the total (or scattered) field E, H or the Poynting vector S on a grid
of the cell (`maps` of the job) and writes `values` (ny, nx, 3) complex with the axes `x`, `y` in
metres. The field is Bloch-periodic along x, so the grid may span several periods; points above
or below the cell have no field (NaN, shown empty).
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any

import hpfem_job  # numpy only inside picture() and tags(): the plugin loads without it

QUANTITIES = ("E", "H", "S")
#: what can be shown, with F for the chosen quantity: label -> (component or None, part, colormap, symmetric)
SHOW = {
    "|F|²": (None, "abs2", "inferno", False),
    **{f"|F{c}|": (i, "abs", "inferno", False) for i, c in enumerate("xyz")},
    **{f"Re F{c}": (i, "real", "coolwarm", True) for i, c in enumerate("xyz")},
    **{f"Im F{c}": (i, "imag", "coolwarm", True) for i, c in enumerate("xyz")},
}


@dataclass
class Picture:
    """values[j * width + i], row 0 at y0; extent = pixel edges in the job's length unit."""
    values: list
    width: int
    height: int
    extent: tuple[float, float, float, float]
    colormap: str
    value_range: tuple[float, float] | None
    missing: int = 0


def label(show: str, quantity: str) -> str:
    return show.replace("F", quantity)


def sweep_values(text: str) -> list[float]:
    """Every value of a panel value text (number, list, range start:stop:count)."""
    value, sweep = hpfem_job.values_spec(text)
    if not sweep:
        return [float(value)]
    if isinstance(value, dict):
        n = int(value["count"])
        a, b = float(value["start"]), float(value.get("stop", value["start"]))
        return [a + (b - a) * k / (n - 1) for k in range(n)] if n > 1 else [a]
    return [float(v) for v in value]


def _pml(job: dict) -> tuple[float, float]:
    pml = job.get("solver", {}).get("pml")
    if not isinstance(pml, dict):
        return 0.0, 0.0
    return float(pml.get("bottom", 0.0)), float(pml.get("top", 0.0))


def grid(job: dict, p: dict) -> tuple[list, list]:
    """The map's x and y specs [from, to, points] in the job's unit. Equal from and to: x over
    *Periods* periods from the cell's left edge, y over the cell without the given PML layers."""
    model = job["model"]
    period = float(model["period"])
    x0, x1 = float(p.get("map_x_from", 0.0)), float(p.get("map_x_to", 0.0))
    if x0 == x1:
        x0 = float(model.get("x0", -period / 2))
        x1 = x0 + max(int(p.get("map_periods", 1)), 1) * period
    y0, y1 = float(p.get("map_y_from", 0.0)), float(p.get("map_y_to", 0.0))
    if y0 == y1:
        bottom, top = _pml(job)
        y0, y1 = float(model["y_bottom"]) + bottom, float(model["y_top"]) - top
    return [x0, x1, int(p.get("map_nx", 201))], [y0, y1, int(p.get("map_ny", 301))]


def point_job(job: dict, p: dict, index: int, xspec: list, yspec: list) -> tuple[dict, float, float]:
    """The job of one point of the sweep (index from 0) with the panel's map as its only map:
    (job, wavelength, θ) in the job's unit and degrees."""
    wavelengths = sweep_values(p["wavelength"])
    thetas = sweep_values(p["theta_deg"])
    n = max(len(wavelengths), len(thetas))
    if not 0 <= index < n:
        raise ValueError(f"point {index + 1}: the sweep has {n} point{'s' if n > 1 else ''}")
    wl = wavelengths[index] if len(wavelengths) > 1 else wavelengths[0]
    th = thetas[index] if len(thetas) > 1 else thetas[0]
    out = copy.deepcopy(job)
    out.pop("sweep", None)
    out["incidence"] = {**out.get("incidence", {}), "wavelength": hpfem_job._num(wl), "theta_deg": hpfem_job._num(th)}
    spec = {"quantity": p.get("map_quantity", "E"), "x": xspec, "y": yspec}
    if p.get("map_scattered"):
        spec["scattered"] = True
    out["maps"] = [spec]
    return out, wl, th


def _edges(axis: Any) -> tuple[float, float]:
    if len(axis) < 2:
        return float(axis[0]) - 0.5, float(axis[0]) + 0.5
    return float(axis[0] - (axis[1] - axis[0]) / 2), float(axis[-1] + (axis[-1] - axis[-2]) / 2)


def picture(x: Any, y: Any, values: Any, show: str) -> Picture:
    """`values` (ny, nx, 3) on the axes x, y (already in the job's unit) as a picture."""
    import numpy as np

    component, part, colormap, symmetric = SHOW[show]
    v = np.asarray(values)
    if part == "abs2":
        data = np.sum(np.abs(v) ** 2, axis=2)
    else:
        c = v[:, :, component]
        data = {"abs": np.abs, "real": np.real, "imag": np.imag}[part](c)
    data = np.asarray(data, dtype=float)
    missing = int(np.count_nonzero(~np.isfinite(data)))
    value_range = None
    if symmetric:
        finite = data[np.isfinite(data)]
        m = float(np.max(np.abs(finite))) if finite.size else 0.0
        value_range = (-m, m) if m > 0 else None
    ex, ey = _edges(np.asarray(x, dtype=float)), _edges(np.asarray(y, dtype=float))
    return Picture(data.ravel().tolist(), data.shape[1], data.shape[0], (ex[0], ex[1], ey[0], ey[1]),
                   colormap, value_range, missing)


# ---------------------------------------------------------------------------- the cell's tags
def _inside_polygon(points: list, x: float, y: float) -> bool:
    inside = False
    n = len(points)
    for i in range(n):
        (x1, y1), (x2, y2) = points[i], points[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _shape_contains(shape: dict, x: float, y: float) -> bool | None:
    """As hpfem.meshing.Shape.contains; None for a shape this module does not know."""
    kind, q = shape.get("kind"), shape.get("params", {})
    try:
        if kind == "rectangle":
            return q["x"] <= x <= q["x"] + q["width"] and q["y"] <= y <= q["y"] + q["height"]
        if kind == "trapezoid":
            pts = [(q["x"] - q["bottom"] / 2, q["y"]), (q["x"] + q["bottom"] / 2, q["y"]),
                   (q["x"] + q["top"] / 2, q["y"] + q["height"]), (q["x"] - q["top"] / 2, q["y"] + q["height"])]
            return _inside_polygon(pts, x, y)
        if kind == "ellipse":
            return ((x - q["x"]) / q["rx"]) ** 2 + ((y - q["y"]) / q["ry"]) ** 2 <= 1.0
        if kind == "polygon":
            return _inside_polygon([tuple(map(float, pt)) for pt in q["points"]], x, y)
    except (KeyError, TypeError, ZeroDivisionError):
        return None
    return None


def tags(job: dict, xs: list[float], ys: list[float]) -> tuple[Any, list[str]]:
    """The cell tag at every grid point (ny, nx) as hpfem.meshing.UnitCell.tag_at: the last shape
    containing it (periodically repeated), else its slab, else the background; and the shapes it
    cannot draw. Lengths in the job's unit."""
    model = job["model"]
    period = float(model["period"])
    shapes = list(model.get("shapes", []))
    unknown = [f"{i + 1} ({s.get('kind')})" for i, s in enumerate(shapes)
               if _shape_contains(s, 0.0, 0.0) is None]
    import numpy as np

    left = float(model.get("x0", -period / 2))
    out = np.zeros((len(ys), len(xs)), dtype=float)
    for j, y in enumerate(ys):
        for i, x_grid in enumerate(xs):
            x = wrapped(float(x_grid), left, period)
            tag = None
            for s in reversed(shapes):
                if any(_shape_contains(s, x - k * period, y) for k in (-1, 0, 1)):
                    tag = int(s["tag"])
                    break
            if tag is None:
                for slab in model.get("slabs", []):
                    if float(slab["y0"]) <= y <= float(slab["y1"]):
                        tag = int(slab["tag"])
                        break
            out[j, i] = model.get("background_tag", 0) if tag is None else tag
    return out, unknown


def wrapped(x: float, left: float, period: float) -> float:
    """x moved into the cell [left, left + period)."""
    return left + math.fmod(math.fmod(x - left, period) + period, period)
