"""hp-FEM job results -> tables, bars and curves of the CAD result windows (pure Python).

`point` is one entry of the runner's `points` (event `point`): wavelength in metres, theta_deg,
R, T, A, balance, R_orders / T_orders (m, efficiency, propagating, amplitude), dofs, seconds.
"""

from __future__ import annotations

from typing import Any

ORDER_COLUMNS = ["side", "m", "efficiency", "propagating"]
POINT_COLUMNS = ["point", "λ", "θ / deg", "R", "T", "A", "balance", "DoFs", "seconds"]


def wavelength(point: dict, unit: float) -> float:
    """The point's wavelength in the job's length unit."""
    return float(point["wavelength"]) / unit


def order_rows(point: dict, evanescent: bool = False) -> list[list[Any]]:
    """One row per order: side, m, efficiency, propagating (evanescent orders only if asked)."""
    rows = []
    for side in ("R", "T"):
        for o in point.get(f"{side}_orders", []):
            if o.get("propagating", True) or evanescent:
                rows.append([side, int(o["m"]), float(o["efficiency"]), "yes" if o.get("propagating", True) else "no"])
    return rows


def order_bars(point: dict) -> tuple[list[str], list[float]]:
    labels, values = [], []
    for side, m, eff, _ in order_rows(point):
        labels.append(f"{side} {m}")
        values.append(eff)
    return labels, values


def point_rows(points: list[dict], unit: float) -> list[list[Any]]:
    return [[int(p.get("i", k)), wavelength(p, unit), float(p.get("theta_deg", 0.0)), float(p["R"]), float(p["T"]),
             float(p.get("A", 0.0)), float(p.get("balance", 0.0)), int(p.get("dofs", 0)),
             float(p.get("seconds", 0.0))] for k, p in enumerate(points)]


def x_axis(points: list[dict], unit: float, unit_name: str) -> tuple[list[float], str]:
    """The quantity that varies: the wavelength (in the job's unit) or θ."""
    wl = [wavelength(p, unit) for p in points]
    th = [float(p.get("theta_deg", 0.0)) for p in points]
    if len(set(th)) > 1 and len(set(wl)) == 1:
        return th, "θ / deg"
    return wl, f"λ / {unit_name}"


def curves(points: list[dict], unit: float, unit_name: str, min_efficiency: float = 0.01,
           ) -> tuple[str, list[tuple[str, list[float], list[float]]]]:
    """(x label, [(name, x, y)]): ΣR, ΣT, A and every order that reaches `min_efficiency` at some
    point; an order evanescent at a point has no point there."""
    x, label = x_axis(points, unit, unit_name)
    out = [(name, list(x), [float(p.get(key, 0.0)) for p in points])
           for name, key in (("ΣR", "R"), ("ΣT", "T"), ("A", "A"))]
    keys: list[tuple[str, int]] = []
    for p in points:
        for side in ("R", "T"):
            for o in p.get(f"{side}_orders", []):
                key = (side, int(o["m"]))
                if key not in keys:
                    keys.append(key)
    for side, m in sorted(keys, key=lambda k: (k[0], k[1])):
        xs, ys = [], []
        for xv, p in zip(x, points):
            for o in p.get(f"{side}_orders", []):
                if int(o["m"]) == m and o.get("propagating", True):
                    xs.append(xv)
                    ys.append(float(o["efficiency"]))
        if ys and max(ys) >= min_efficiency:
            out.append((f"{side} {m}", xs, ys))
    return label, out


def summary(point: dict) -> str:
    return (f"ΣR {float(point['R']):.4f}, ΣT {float(point['T']):.4f}, A {float(point.get('A', 0.0)):.4f}, "
            f"balance {float(point.get('balance', 0.0)):.2e}")


def diagnostic_lines(items: list[dict]) -> list[str]:
    """Log lines of the runner's diagnostics (warnings with their hint)."""
    lines = []
    for d in items:
        text = f"{d.get('severity', 'note')}: {d.get('text', '')}"
        if d.get("hint"):
            text += f" – {d['hint']}"
        lines.append(text)
    return lines


def mesh_line(report: dict) -> str:
    text = f"mesh: {report.get('num_cells', '?')} cells, {report.get('num_vertices', '?')} vertices"
    if report.get("tags_without_material"):
        text += f"; tags without material: {report['tags_without_material']}"
    if report.get("materials_without_cells"):
        text += f"; materials without cells: {report['materials_without_cells']}"
    if report.get("num_invalid"):
        text += f"; {report['num_invalid']} invalid cells"
    return text
