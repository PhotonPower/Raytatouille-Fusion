"""The unit cell from CAD bodies (step 4): closed bodies cut by a plane across the grating lines
become polygons of the hp-FEM cell.

Frames: the lines run along CAD +Y; the section plane is CAD y = const; the job's x is CAD +X and
the job's y (the stack normal, light from +y) is CAD +Z – as the FourierGrating plugin's CAD
layers (CAD +Z the stacking direction). One CAD length unit is `cad_unit` (the bodies are drawn
at that scale), converted to the job's unit.

Nurbforge cuts every body exactly (`nurbforge.section`: closed loops of the section); the loops
are sampled into polygons (straight edges by their end points, curved ones by `points` points).
Nesting decides what a loop is: a loop inside an even number of the body's other loops bounds
material (a polygon with the body's tag), inside an odd number a hole (a polygon with the tag
found there without the body). Every polygon runs counter-clockwise, outer ones first, so that
the later ones lie on top as in hp-FEM's cell.

The parts without Nurbforge (nesting, orientation, tags, the panel rows) are pure Python.
"""

from __future__ import annotations

from typing import Any

#: CAD length units the bodies may be drawn in, in metres
CAD_UNITS = {"nm": 1e-9, "µm": 1e-6, "mm": 1e-3}

Point = tuple[float, float]


# ---------------------------------------------------------------------------- pure geometry
def signed_area(poly: list[Point]) -> float:
    """Shoelace area, > 0 counter-clockwise."""
    n = len(poly)
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))


def contains(poly: list[Point], p: Point) -> bool:
    """Even-odd rule."""
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def ccw(poly: list[Point]) -> list[Point]:
    return poly if signed_area(poly) > 0 else poly[::-1]


def inner_point(poly: list[Point]) -> Point:
    """A point inside a simple polygon: on a horizontal line through the middle of its y range,
    the midpoint of the widest inside span."""
    ys = sorted({q[1] for q in poly})
    best: tuple[float, Point] | None = None
    for k in range(len(ys) - 1):
        y = 0.5 * (ys[k] + ys[k + 1])
        xs = []
        n = len(poly)
        for i in range(n):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
            if (y0 > y) != (y1 > y):
                xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        xs.sort()
        for a, b in zip(xs[0::2], xs[1::2]):
            if best is None or b - a > best[0]:
                best = (b - a, (0.5 * (a + b), y))
    if best is None:
        raise ValueError("a section loop without area")
    return best[1]


def nesting(loops: list[list[Point]]) -> list[int]:
    """For every loop of one body: how many of the body's other loops contain it."""
    depth = []
    for i, loop in enumerate(loops):
        probe = loop[0]  # loops of a closed body do not touch: any point of one tells
        depth.append(sum(1 for j, other in enumerate(loops) if j != i and contains(other, probe)))
    return depth


def drop_duplicates(poly: list[Point], tol: float) -> list[Point]:
    """Consecutive points closer than `tol` (the joints of a loop's curves) and the closing one."""
    out: list[Point] = []
    for q in poly:
        if not out or abs(q[0] - out[-1][0]) > tol or abs(q[1] - out[-1][1]) > tol:
            out.append(q)
    while len(out) > 1 and abs(out[0][0] - out[-1][0]) <= tol and abs(out[0][1] - out[-1][1]) <= tol:
        out.pop()
    return out


def _key(text: str) -> Any:
    """A material text by its value: `1.5`, `1.5+0i` and `{"n": [1.5, 0]}` are one material."""
    from hpfem_job import material_spec

    try:
        spec = material_spec(text)
    except ValueError:
        return str(text).strip()
    if isinstance(spec, dict) and len(spec) == 1:
        (k, v), = spec.items()
        if k in ("n", "eps"):
            if isinstance(v, int | float):
                return (k, float(v), 0.0)
            if isinstance(v, list) and len(v) == 2:
                return (k, float(v[0]), float(v[1]))
    return spec if isinstance(spec, str) else repr(spec)


def tag_for(materials: list[dict], material: str) -> tuple[int, list[dict]]:
    """The tag of a material in the panel's table (rows {tag, material}, compared by value); a new
    row with the next free tag if it has none. Returns the tag and the (possibly longer) table."""
    key = _key(material)
    for row in materials:
        if _key(str(row.get("material", ""))) == key:
            return int(row["tag"]), materials
    tag = max([int(r["tag"]) for r in materials] + [0]) + 1
    return tag, [*materials, {"tag": tag, "material": material}]


def polygon_row(tag: int, poly: list[Point], digits: int = 9) -> dict:
    """A shape row of the panel (type polygon)."""
    return {"kind": "polygon", "tag": int(tag), "x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0, "bottom": 0.0,
            "top": 0.0, "rx": 0.0, "ry": 0.0, "json": None,
            "points": [{"x": round(x, digits), "y": round(y, digits)} for x, y in poly]}


def material_of(entity: dict[str, Any], panel_materials: list[str], library: list[str] | None) -> str:
    """The material of a body as a material text: its attribute "material" (any form the panel
    takes: a library name, n + i k, eps=…), else its name if that is a material of the panel or of
    hp-FEM's library; ValueError otherwise."""
    from hpfem_job import material_spec

    label = entity.get("name") or entity.get("id")
    attr = (entity.get("attributes") or {}).get("material")
    if attr not in (None, ""):
        text = str(attr).strip()
        spec = material_spec(text)  # ValueError for a malformed eps=…
        if isinstance(spec, str) and library is not None and spec not in library and text not in panel_materials:
            raise ValueError(f"{label}: material {text!r} is neither in hp-FEM's library nor in the panel's materials")
        return text
    name = str(entity.get("name", "")).strip()
    if name and (name in panel_materials or (library is not None and name in library)):
        return name
    raise ValueError(f"body {label!r} has no material: give it the attribute \"material\" (a library name, n + i k "
                     "or eps=…) or name it after one")


def bounds(polys: list[list[Point]]) -> tuple[float, float, float, float]:
    xs = [q[0] for p in polys for q in p]
    ys = [q[1] for p in polys for q in p]
    return min(xs), max(xs), min(ys), max(ys)


# ---------------------------------------------------------------------------- Nurbforge
def _nf():
    try:
        import nurbforge
    except ImportError as e:
        raise ValueError("the unit cell from CAD bodies needs Nurbforge's Python package (nurbforge ≥ 0.7) in the "
                         "plugin environment") from e
    if not hasattr(nurbforge, "section"):
        raise ValueError("this nurbforge has no planar section of shells (nurbforge ≥ 0.7)")
    return nurbforge


def shell_of(geometry: dict, tolerance: float = 1e-6):
    """A Nurbforge shell from an entity's geometry (.nfcad: a shell of trimmed surfaces)."""
    from nfcad.geometry import to_nurbforge

    nf = _nf()
    if geometry.get("type") != "shell":
        raise ValueError("not a closed body (shell)")
    faces = []
    for face in geometry.get("faces") or []:
        surface = to_nurbforge(face["surface"])
        if not face.get("outer"):
            faces.append(nf.TrimmedSurface(surface))
            continue
        outer = nf.TrimLoop([to_nurbforge(c) for c in face["outer"]])
        holes = [nf.TrimLoop([to_nurbforge(c) for c in hole]) for hole in face.get("holes") or []]
        faces.append(nf.TrimmedSurface(surface, outer, holes))
    shell = nf.Shell.sew(faces, tolerance)
    if not shell.is_closed:
        raise ValueError("the body is not closed (free edges after sewing)")
    return shell


def section_loops(shell, y: float, scale: float, points: int) -> list[list[Point]]:
    """The loops of a body's section with the plane CAD y = `y`, as polygons in the job's (x, y) =
    (CAD x, CAD z) · `scale`; curved edges sampled with `points` points."""
    nf = _nf()
    section = nf.section(shell, nf.Plane(nf.Vec3(0.0, float(y), 0.0), nf.Vec3(0.0, 1.0, 0.0)), nf.SectionOptions())
    loops = []
    for loop in section.loops:
        poly: list[Point] = []
        for piece in loop.curves:
            curve = piece.curve3d
            n = 2 if curve.degree == 1 and len(curve.control_points) == 2 else max(points, 4)
            for q in curve.sample(n):
                poly.append((float(q[0]) * scale, float(q[2]) * scale))
        size = max(max(abs(q[0]), abs(q[1])) for q in poly) if poly else 1.0
        poly = drop_duplicates(poly, 1e-9 * max(size, 1e-30))
        if len(poly) >= 3:
            loops.append(poly)
    return loops


def body_polygons(loops: list[list[Point]]) -> list[tuple[int, list[Point]]]:
    """(depth, counter-clockwise polygon) of a body's loops, outer ones first."""
    depth = nesting(loops)
    return sorted(((d, ccw(loop)) for d, loop in zip(depth, loops)), key=lambda t: t[0])
