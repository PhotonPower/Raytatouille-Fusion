"""Overview drawings of the Raytatouille blocks (docs/plugin-api.md, "Block previews").

The tab "Overview" of an `rtt.*` block's parameter dialog shows its part of the system in the
meridional section (global y–z plane, z to the right): every lens as the closed outline of its
glass segments from the exact sag profiles over the apertures (``raytatouille.layout.outlines``),
coloured by glass with the index at the reference wavelength in the legend; mirrors, thin
elements (ideal lenses with f), stops (marked beside the opening) and detectors as their
profiles; the optical axis; a few real rays along the block's first run (the events of a branch
through it) when the glasses are known; the centre thickness or the length as a dimension.
The source block draws the whole system without rays.

The block's data are the ones of the dialog (``request["node"]``, with unsaved values): the
elements of its model-tree node (``params["rtt"]``: location → element without children) put
back into a tree and compiled with the glass catalogues the source block holds. Without them
the geometry is drawn all the same (indices unknown, no rays).
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

import numpy as np

from nfcad.drawing import Drawing, answer, fmt, unsupported

try:
    import raytatouille as rt
except ImportError:  # the plugin reports it
    rt = None  # type: ignore[assignment]

STOP_RING = 1.5  # outer radius of a drawn stop mark, relative to its opening
RAYS = 7  # rays of the fan
LABELS = 5  # elements named in the drawing; more are listed in the notes


# ------------------------------------------------------------------ the block's system
def tree(items: dict[str, Any], top: str | None = None) -> dict | None:
    """The model-tree nodes ``{location: node without children}`` as one tree: the node at `top`
    (default: the shortest location) with its descendants put back as children, in the order of
    their indices. None without nodes."""
    if not items:
        return None
    nodes = {k: copy.deepcopy(v) for k, v in items.items() if isinstance(v, dict)}
    top = top if top is not None else min(nodes, key=lambda k: (k.count("/"), k))
    if top not in nodes:
        return None
    children: dict[str, list[tuple[int, dict]]] = {}
    for loc in nodes:
        parent, sep, index = loc.rpartition("/children/")
        if sep and parent in nodes and index.isdigit() and loc != top:
            children.setdefault(parent, []).append((int(index), nodes[loc]))
    for parent, kids in children.items():
        nodes[parent]["children"] = [k for _, k in sorted(kids, key=lambda t: t[0])]
    return nodes[top]


def _model_nodes(model: dict) -> list[dict]:
    """Every block of a model, also in the active variants of its groups."""
    out = []
    for n in model.get("nodes") or []:
        out.append(n)
        variants = n.get("variants")
        if isinstance(variants, dict):
            active = variants.get(n.get("variant")) or next(iter(variants.values()), None)
            if isinstance(active, dict):
                out += _model_nodes(active)
    return out


def _source(model: dict) -> dict | None:
    return next((n for n in _model_nodes(model) if n.get("type") == "rtt.source"), None)


def _wavelength(source: dict | None) -> float:
    """The reference wavelength of the system in µm (0.5876 without one)."""
    waves = ((source or {}).get("params", {}).get("rtt_system") or {}).get("wavelengths") or []
    for w in waves:
        if isinstance(w, dict) and w.get("reference") and isinstance(w.get("um"), int | float):
            return float(w["um"])
    first = waves[0] if waves else None
    return float(first["um"]) if isinstance(first, dict) and isinstance(first.get("um"), int | float) else 0.5876


def _system(top: dict, wavelength: float, events: list | None) -> dict:
    """A system of the block's tree alone (pose kept: coordinates of its parent assembly)."""
    path: dict[str, Any] = {"name": "preview", "events": events if events else "auto"}
    return {"schema_version": "0.9.0", "name": "preview", "units": {"length": "mm", "wavelength": "um"},
            "wavelengths": [{"um": wavelength, "reference": True}], "aperture": {"type": "epd", "value": 1.0},
            "fields": {"points": [{}]},
            "root": {"type": "assembly", "name": "preview", "children": [top]}, "paths": [path]}


def _without_glass(node: Any) -> Any:
    """The tree with every material replaced by a constant index (geometry only)."""
    if isinstance(node, dict):
        out = {k: _without_glass(v) for k, v in node.items()}
        if "material" in node:
            m = node["material"]
            out["material"] = ["CONST:1.5"] * len(m) if isinstance(m, list) else "CONST:1.5"
        return out
    if isinstance(node, list):
        return [_without_glass(v) for v in node]
    return node


def _element_nodes(node: dict) -> list[dict]:
    """The elements of a tree in tree order (as raytatouille.layout.elements)."""
    if node.get("type") == "assembly":
        return [e for c in node.get("children") or [] if isinstance(c, dict) for e in _element_nodes(c)]
    return [node]


def _compile(system: dict, source: dict | None) -> tuple[Any, str]:
    """(compiled, problem): with the source's glass catalogues, else with constant indices."""
    library = rt.MaterialLibrary()
    problem = ""
    if source is not None:
        try:
            from rtt_fusion.graph.embedded import load_catalogs
        except ImportError:  # an RTT-Fusion without embedded catalogues: the files only
            for path in source.get("params", {}).get("rtt_catalogs") or []:
                try:
                    library.add_catalog(str(path))
                except Exception:  # noqa: BLE001 - reported below as an unknown glass
                    pass
        else:
            load_catalogs(library, source.get("params", {}))
    try:
        return rt.compile(rt.System.from_json(json.dumps(system)), library), ""
    except rt.errors.CompileError as e:
        problem = "; ".join(str(d.message) for d in list(getattr(e, "diagnostics", []))[:2]) or str(e)
    flat = dict(system, root=_without_glass(system["root"]))
    return rt.compile(rt.System.from_json(json.dumps(flat)), rt.MaterialLibrary()), problem


# ------------------------------------------------------------------ drawing
def _zy(points: np.ndarray) -> list[list[float]]:
    return [[float(p[2]), float(p[1])] for p in np.asarray(points, dtype=float)]


def _local(layout, x: float, y: float, z: float = 0.0) -> np.ndarray:
    return np.asarray(layout.rotation, dtype=float) @ np.array([x, y, z]) + np.asarray(layout.translation, dtype=float)


def _half_height(layout) -> float | None:
    """Half the opening of a surface in its local y (None without aperture)."""
    if layout.aperture is None:
        return None
    kind, p = layout.aperture
    return float(p.get("radius", p.get("semi_axis_y", p.get("half_width_y", 0.0))))


def _glass(reference: str) -> str:
    """The name of a glass for the legend: without its catalogue ("SCHOTT:N-BK7" → "N-BK7"); a
    constant index keeps its reference."""
    return reference if reference.upper().startswith("CONST:") else reference.split(":", 1)[-1]


def _glass_label(reference: str, medium, known: bool) -> str:
    if reference.upper().startswith("CONST:"):
        return f"n = {reference.split(':', 1)[1]} (constant)"
    return _glass(reference) + (f" · n = {medium.index[0].real:.4f}" if known and medium is not None else "")


def _draw_element(d: Drawing, compiled, index: int, element, node: dict, layouts, media, known: bool,
                  label: bool) -> None:
    kind = str(node.get("type", ""))
    surfaces = list(range(element.first_surface, element.first_surface + element.surface_count))
    outlines = rt.layout.outlines(compiled, index, "yz", 121) if element.segmented else []
    names = node.get("material")
    names = names if isinstance(names, list) else [names] * max(1, len(element.media))
    if outlines:
        for k, outline in enumerate(outlines):
            ref = str(names[k]) if k < len(names) and names[k] else "glass"
            medium = media[element.media[k]] if k < len(element.media) else None
            d.material(_glass(ref), _glass_label(ref, medium, known))
            d.polygon(_zy(outline), material=_glass(ref))
    for s in surfaces:
        L = layouts[s]
        try:
            profiles = rt.layout.profile(compiled, s, "yz", 81)
        except ValueError:  # not cut by the y–z plane (tilted out of it)
            d.note(f"{L.id}: not in the y–z section")
            continue
        if outlines:
            continue
        interaction = next((q.get("interaction") for q in node.get("surfaces") or []
                            if isinstance(q, dict) and q.get("id") == L.id), None) or {}
        role, width, dashed = "surface", 2.0, False
        if kind == "detector" or L.kind == "detector":
            role, width = "detector", 3.0
        elif kind == "mirror" or L.kind == "mirror":
            width = 3.0
        elif interaction.get("type") not in (None, "ideal_lens", "ideal_mirror"):
            dashed = True  # a splitter, a coating …
        if L.kind == "stop" or kind == "stop":
            _stop(d, L)
            continue
        for prof in profiles:
            d.polyline(_zy(prof), role=role, width=width, dashed=dashed)
            if interaction.get("type") == "ideal_lens":
                _lens_arrows(d, prof, float(interaction.get("focal_length", 0.0)))
        if kind != "lens" and len(element.media) == 1 and len(surfaces) == 2 and s == surfaces[-1]:
            _plate(d, compiled, surfaces, names[0] if names else "glass", media[element.media[0]], known)
    if label:
        box = _element_box(compiled, surfaces)
        if box is not None:
            z0, y0, z1, y1 = box
            name = str(node.get("name", ""))
            d.text(((z0 + z1) / 2, y1), name if len(name) <= 24 else name[:23] + "…", valign="bottom")


def _plate(d: Drawing, compiled, surfaces, name, medium, known) -> None:
    """A window of one material: its two profiles joined."""
    try:
        a = rt.layout.profile(compiled, surfaces[0], "yz", 81)
        b = rt.layout.profile(compiled, surfaces[1], "yz", 81)
    except ValueError:
        return
    if len(a) == 1 and len(b) == 1:
        d.material(_glass(str(name)), _glass_label(str(name), medium, known))
        d.polygon(_zy(a[0]) + _zy(b[0])[::-1], material=_glass(str(name)))


def _lens_arrows(d: Drawing, profile: np.ndarray, f: float) -> None:
    """The symbol of an ideal lens: arrow heads at both ends (outwards: converging, inwards:
    diverging) and its focal length."""
    pts = _zy(profile)
    if len(pts) < 2:
        return
    (z0, y0), (z1, y1) = pts[0], pts[-1]
    length = math.hypot(z1 - z0, y1 - y0)
    if length == 0:
        return
    uz, uy = (z1 - z0) / length, (y1 - y0) / length
    head = 0.06 * length
    for (z, y), sign in (((z0, y0), -1.0), ((z1, y1), 1.0)):
        out = sign if f >= 0 else -sign  # the heads point outwards for a converging lens
        bz, by = z - out * uz * head, y - out * uy * head
        d.polyline([(bz - uy * head * 0.7, by + uz * head * 0.7), (z, y), (bz + uy * head * 0.7, by - uz * head * 0.7)],
                   role="surface", width=2.0)
    d.text(((z0 + z1) / 2, min(y0, y1) - 0.04 * length), f"f = {fmt(f)} mm", valign="top", role="note")


def _stop(d: Drawing, L) -> None:
    r = _half_height(L)
    if r is None:
        return
    for sign in (1.0, -1.0):
        a = _local(L, 0.0, sign * r)
        b = _local(L, 0.0, sign * STOP_RING * r)
        d.polyline([[a[2], a[1]], [b[2], b[1]]], role="stop")
    top = _local(L, 0.0, STOP_RING * r)
    d.text((float(top[2]), float(top[1])), f"stop ⌀ {fmt(2 * r)}", valign="bottom", role="note")


def _element_box(compiled, surfaces) -> tuple[float, float, float, float] | None:
    zs: list[float] = []
    ys: list[float] = []
    for s in surfaces:
        try:
            for prof in rt.layout.profile(compiled, s, "yz", 21):
                zs += list(np.asarray(prof)[:, 2])
                ys += list(np.asarray(prof)[:, 1])
        except ValueError:
            continue
    return (min(zs), min(ys), max(zs), max(ys)) if zs else None


def _run_events(params: dict, ids: set[str]) -> list | None:
    """The events of the block's first run whose surfaces are all in the drawn system."""
    for events in (params.get("runs") or {}).values():
        if isinstance(events, list) and events and all(isinstance(e, dict) and e.get("surface") in ids
                                                       for e in events):
            # as given: a surface without a kind refracts ("transmit" passes a thin element)
            return [{k: e[k] for k in ("surface", "kind", "order") if k in e} for e in events]
    return None


def _rays(d: Drawing, compiled, layouts, events: list | None) -> str:
    """A fan of parallel rays in the y–z plane along the path; '' or why there are none."""
    ids = [L.id for L in layouts]
    first = ids.index(events[0]["surface"]) if events else 0
    backwards = bool(events and len(events) > 1 and ids.index(events[1]["surface"]) < first)
    L = layouts[first]
    openings = [h for h in (_half_height(x) for x in layouts) if h]
    if not openings:
        return "no apertures: no rays"
    axis = np.asarray(L.rotation, dtype=float)[:, 2] * (-1.0 if backwards else 1.0)
    if abs(axis[0]) > 1e-9:
        return ""
    through = len(events or ids)
    # over the first surface's opening; if most rays are stopped on the way, within the smallest one
    for h in dict.fromkeys(0.85 * x for x in (_half_height(L) or min(openings), min(openings))):
        span = max(float(np.ptp([x.translation[2] for x in layouts])),
                   float(np.ptp([x.translation[1] for x in layouts])), 2 * h)
        rays = rt.trace.RayBatch(RAYS)
        for k, y in enumerate(np.linspace(-h, h, RAYS)):
            p = _local(L, 0.0, float(y)) - axis * 0.15 * span
            rays.pos_x[k], rays.pos_y[k], rays.pos_z[k] = p
            rays.dir_x[k], rays.dir_y[k], rays.dir_z[k] = axis
        _, paths = rt.trace.trace(compiled, rays, path=0, record_path=True)
        count = np.asarray(paths.count)
        if np.sum(count - 1 == through) >= 3:
            break
    pos = np.asarray(paths.position)
    direction = np.asarray(paths.direction)
    # behind the block the rays run on to where they cross the axis (a focus not too far away),
    # else a little
    ends = [(pos[k, int(count[k]) - 1], direction[k, int(count[k]) - 1]) for k in range(pos.shape[0])
            if int(count[k]) - 1 == through and np.all(np.isfinite(direction[k, int(count[k]) - 1]))]
    crossing = [float(-q[1] / u[1]) for q, u in ends if abs(u[1]) > 1e-12 and -q[1] / u[1] > 0]
    reach = 0.3 * span
    if len(crossing) >= 2 and float(np.median(crossing)) < 6 * max(span, 2 * max(openings)):
        reach = 1.1 * float(np.median(crossing))
    drawn = 0
    for k in range(pos.shape[0]):
        n = int(count[k])
        if n < 2:
            continue
        pts = [list(map(float, (q[2], q[1]))) for q in pos[k, :n]]
        last, u = pos[k, n - 1], direction[k, n - 1]
        if n - 1 == through and np.all(np.isfinite(u)):  # through: on behind the block
            end = last + u * reach
            pts.append([float(end[2]), float(end[1])])
        d.polyline(pts, role="ray")
        drawn += 1
    return "" if drawn else "no ray passes the block"


def draw_system(d: Drawing, top: dict, source: dict | None, params: dict, *, rays: bool, labels: bool) -> None:
    """Draws the tree `top` (an element or an assembly) in the y–z section."""
    wavelength = _wavelength(source)
    probe, _ = _compile(_system(top, wavelength, None), source)
    ids = {L.id for L in rt.layout.surfaces(probe)}
    events = _run_events(params, ids)
    system = _system(top, wavelength, events)
    compiled, problem = _compile(system, source)
    known = not problem
    layouts = rt.layout.surfaces(compiled)
    elements = rt.layout.elements(compiled)
    nodes = _element_nodes(top)
    media = compiled.media
    for i, element in enumerate(elements):
        node = nodes[i] if i < len(nodes) else {}
        _draw_element(d, compiled, i, element, node, layouts, media, known, labels and len(elements) <= LABELS)
    b = d.bounds()
    if b is None:
        d.note("nothing to draw in the y–z section")
        return
    if labels and len(elements) > LABELS:
        names = [str(n.get("name", "")) for n in nodes if n.get("name")]
        d.note("elements in tree order: " + ", ".join(names))
    z0, y0, z1, y1 = b
    pad = 0.06 * max(z1 - z0, y1 - y0, 1e-3)
    if abs(y0) < 10 * (y1 - y0 + pad) and y0 - pad <= 0 <= y1 + pad:
        d.polyline([[z0 - pad, 0.0], [z1 + pad, 0.0]], role="axis")
    _dimensions(d, compiled, elements, nodes, layouts, y0 - pad)
    if not known:
        d.note(f"glasses unknown ({problem}) – geometry only, no rays; add the glass catalogue in the "
               "Raytracer panel")
    elif rays and any(node.get("type") in ("lens", "mirror", "thin_element", "plate", "assembly") for node in nodes):
        try:
            why = _rays(d, compiled, layouts, events)
        except Exception as e:  # noqa: BLE001 - the drawing without rays
            why = f"rays: {e}"
        if why:
            d.note(why)
        else:
            d.note(f"rays: a parallel fan along {'the block' + chr(39) + 's first run' if events else 'the surfaces'}, "
                   f"λ = {fmt(wavelength)} µm")


def _dimensions(d: Drawing, compiled, elements, nodes, layouts, below: float) -> None:
    """The centre thickness of a single lens (and its radii, diameter in the notes), else the
    length from the first to the last vertex on the axis."""
    if not layouts:
        return
    if len(elements) == 1 and nodes and nodes[0].get("type") == "lens":
        e = elements[0]
        ls = layouts[e.first_surface:e.first_surface + e.surface_count]
        parts = []
        for L in ls:
            r = "∞" if L.curvature == 0 else fmt(1.0 / L.curvature)
            parts.append(f"{L.id}: R = {r} mm" + (f", k = {fmt(L.conic_constant)}" if L.conic_constant else ""))
        opening = max((h for h in (_half_height(L) for L in ls) if h), default=None)
        thick = [fmt(float(np.linalg.norm(np.asarray(b.translation) - np.asarray(a.translation))))
                 for a, b in zip(ls, ls[1:])]
        d.note("; ".join(parts) + f"; thickness {' + '.join(thick)} mm" + (f"; ⌀ {fmt(2 * opening)} mm" if opening else ""))
    first, last = layouts[0].translation, layouts[-1].translation
    if abs(first[1]) < 1e-9 and abs(last[1]) < 1e-9 and abs(last[2] - first[2]) > 1e-9:
        d.extension((first[2], 0.0), (first[2], below))
        d.extension((last[2], 0.0), (last[2], below))
        d.dimension((first[2], below), (last[2], below), f"{fmt(abs(last[2] - first[2]))} mm")


# ------------------------------------------------------------------ the blocks
def preview(request: dict) -> dict:
    node = request.get("node") or {}
    kind = str(node.get("type", ""))
    params = node.get("params") or {}
    model = request.get("model") or {}
    if not kind.startswith("rtt."):
        return unsupported(f"the Raytracer draws rtt.* blocks, not {kind}")
    if rt is None:
        return {"ok": False, "error": "the Raytracer's overview needs the Python package raytatouille"}
    source = _source(model)
    name = str(node.get("name") or node.get("id") or kind)
    if kind == "rtt.source":
        return _source_preview(node, model, name)
    items = params.get("rtt")
    if isinstance(params.get("rtt_new"), dict) and params["rtt_new"]:  # a new part (rtt.part.*)
        top = copy.deepcopy(params["rtt_new"])
    else:
        top = tree(items) if isinstance(items, dict) else None
    if top is None:
        return unsupported(f"{name} holds no Raytatouille elements")
    d = Drawing(f"{name} – y–z section", unit="mm", axes=("z", "y"))
    draw_system(d, top, source, params, rays=kind in ("rtt.section", "rtt.part.lens"), labels=True)
    if kind.startswith("rtt.part."):
        d.note("a new part: drawn where its pose puts it in the system's root")
    return answer(d)


def _source_preview(node: dict, model: dict, name: str) -> dict:
    """The whole system: the tree skeleton of the source and every block's elements."""
    params = node.get("params") or {}
    items: dict[str, Any] = dict(params.get("rtt_tree") or {})
    for n in _model_nodes(model):
        rtt = (n.get("params") or {}).get("rtt")
        if isinstance(rtt, dict) and n.get("id") != node.get("id"):
            items.update(rtt)
    system = params.get("rtt_system") or {}
    d = Drawing(f"{system.get('name') or name} – y–z section", unit="mm", axes=("z", "y"))
    top = tree(items, "/root") if "/root" in items else tree(items)
    if top is None:
        return unsupported(f"{name} holds no system")
    parts = [copy.deepcopy(n["params"]["rtt_new"]) for n in _model_nodes(model)
             if isinstance((n.get("params") or {}).get("rtt_new"), dict)]
    if parts:  # new parts (rtt.part.*) are elements of the system's root
        top = dict(top, children=[*(top.get("children") or []), *parts])
    draw_system(d, top, node, {}, rays=False, labels=True)
    waves = ", ".join(fmt(w["um"]) for w in system.get("wavelengths") or [] if isinstance(w, dict) and "um" in w)
    fields = len((system.get("fields") or {}).get("points") or [])
    if waves:
        d.note(f"wavelengths {waves} µm; {fields} field point(s)")
    return answer(d)
