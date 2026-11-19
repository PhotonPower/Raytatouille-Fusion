"""Overview drawings of the blocks the engine computes itself (docs/plugin-api.md, "Block
previews"): RTT-Fusion's ideal optics (`optics.*`) and the particle (`fusion.particle`). Each is
drawn where its parameters put it, in the y–z plane (z to the right, mm): a lens as its symbol
with the focal points, a detector as its plane with its size and the arriving light, a source as
its beam, a mirror with its back hatched, a splitter dashed, an interface with its indices; the
particle as its circle (µm). Pure Python: the dialog needs neither RTT-Fusion nor NumPy for it.
"""

from __future__ import annotations

import math
from typing import Any

from nfcad.drawing import Drawing, answer, fmt, unsupported

TYPES = ("optics.thin_lens", "optics.aplanatic_lens", "optics.detector", "optics.collimated_source",
         "optics.plane_mirror", "optics.beam_splitter", "optics.splitter", "optics.interface", "fusion.particle")


def _vec(v: Any, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if isinstance(v, list) and len(v) == 3 and all(isinstance(x, int | float) and math.isfinite(x) for x in v):
        return float(v[0]), float(v[1]), float(v[2])
    return default


def _num(v: Any, default: float) -> float:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) else default


def _polarisation_note(p: dict) -> str:
    """The source's polarisation in words: linear along the field direction, or elliptical /
    circular with ellipticity χ (> 0: the field turns from it towards direction × it)."""
    axis = ", ".join(fmt(x) for x in _vec(p.get("polarisation"), (1.0, 0.0, 0.0)))
    chi = _num(p.get("ellipticity_deg"), 0.0)
    if chi == 0.0:
        return f"polarisation linear along ({axis})"
    turn = "towards" if chi > 0 else "away from"
    kind = "circular" if abs(chi) == 45.0 else f"elliptical, χ = {fmt(chi)}°"
    return f"polarisation {kind}, major axis ({axis}), turning {turn} direction × axis"


def _zy(p: tuple[float, float, float]) -> tuple[float, float]:
    return p[2], p[1]


def _unit_zy(v: tuple[float, float, float]) -> tuple[float, float]:
    """The direction of v in the y–z plane (z, y); +z if v has no part in it."""
    z, y = v[2], v[1]
    n = math.hypot(z, y)
    return (z / n, y / n) if n > 1e-12 else (1.0, 0.0)


def _plane(d: Drawing, at: tuple[float, float], normal: tuple[float, float], half: float, **kw) -> None:
    tz, ty = -normal[1], normal[0]
    d.polyline([(at[0] - tz * half, at[1] - ty * half), (at[0] + tz * half, at[1] + ty * half)], **kw)


def preview(request: dict) -> dict:
    node = request.get("node") or {}
    kind = str(node.get("type", ""))
    if kind not in TYPES:
        return unsupported(f"the workflow engine draws {', '.join(TYPES)}, not {kind}")
    p = node.get("params") or {}
    name = str(node.get("name") or node.get("id") or kind)
    if kind == "fusion.particle":
        return answer(_particle(p, name))
    d = Drawing(f"{name} – y–z plane", unit="mm", axes=("z", "y"))
    at = _zy(_vec(p.get("point", p.get("center")), (0.0, 0.0, 0.0)))
    if kind in ("optics.thin_lens", "optics.aplanatic_lens"):
        axis = _unit_zy(_vec(p.get("axis"), (0.0, 0.0, 1.0)))
        f = _num(p.get("focal_length"), 10.0)
        r = _num(p.get("aperture_radius"), 0.0)
        half = r if 0 < r < 1e6 else max(abs(f) / 4, 1.0)
        tz, ty = -axis[1], axis[0]
        a = (at[0] - tz * half, at[1] - ty * half)
        b = (at[0] + tz * half, at[1] + ty * half)
        d.polyline([a, b], role="surface", width=2.0)
        head = 0.15 * half
        for end, sign in ((a, -1.0), (b, 1.0)):
            out = sign if f >= 0 else -sign
            d.arrow((end[0] - out * tz * head, end[1] - out * ty * head), end, role="outline")
        for s, label in ((-1.0, "F"), (1.0, "F′")):
            q = (at[0] + s * axis[0] * f, at[1] + s * axis[1] * f)
            d.polyline([(q[0], q[1] - 0.05 * half), (q[0], q[1] + 0.05 * half)], role="outline")
            d.text(q, label, valign="bottom")
        d.polyline([(at[0] - axis[0] * 1.2 * abs(f), at[1] - axis[1] * 1.2 * abs(f)),
                    (at[0] + axis[0] * 1.2 * abs(f), at[1] + axis[1] * 1.2 * abs(f))], role="axis")
        text = f"f = {fmt(f)} mm" + (f", NA = {fmt(min(r / abs(f), 1.0), 3)}" if 0 < r < 1e6 and f else "")
        d.text((at[0], at[1] + half), text, valign="bottom")
        if kind == "optics.aplanatic_lens":
            d.note("ideal aplanatic lens (sine condition)")
        return answer(d)
    normal = _unit_zy(_vec(p.get("normal"), (0.0, 0.0, -1.0)))
    if kind == "optics.detector":
        size: list = p["half_size"] if isinstance(p.get("half_size"), list) and p["half_size"] else [1.0, 1.0]
        hx, hy = _num(size[0], 1.0), _num(size[1] if len(size) > 1 else size[0], 1.0)
        _plane(d, at, normal, hy, role="detector")
        length = 1.2 * hy
        d.arrow((at[0] + normal[0] * length, at[1] + normal[1] * length), at, "light")
        pixels = p.get("pixels") if isinstance(p.get("pixels"), list) else []
        d.note(f"{fmt(2 * hx)} × {fmt(2 * hy)} mm" + (f", {' × '.join(str(int(v)) for v in pixels)} pixels"
                                                     if pixels else ""))
        return answer(d)
    if kind == "optics.collimated_source":
        direction = _unit_zy(_vec(p.get("direction"), (0.0, 0.0, 1.0)))
        r = _num(p.get("radius"), 1.0)
        tz, ty = -direction[1], direction[0]
        length = 2.5 * r
        _plane(d, at, direction, r, role="outline")
        for k in range(5):
            s = -r + 2 * r * k / 4
            start = (at[0] + tz * s, at[1] + ty * s)
            d.arrow(start, (start[0] + direction[0] * length, start[1] + direction[1] * length))
        waves = p.get("wavelengths_um") if isinstance(p.get("wavelengths_um"), list) else []
        d.note(f"beam radius {fmt(r)} mm" + (f"; λ = {', '.join(fmt(w) for w in waves)} µm" if waves else ""))
        d.note(_polarisation_note(p))
        return answer(d)
    half = 1.0
    if kind == "optics.plane_mirror":
        _plane(d, at, normal, half, role="surface", width=3.0)
        back = (at[0] - normal[0] * 0.15, at[1] - normal[1] * 0.15)
        tz, ty = -normal[1], normal[0]
        d.polygon([(at[0] - tz, at[1] - ty), (at[0] + tz, at[1] + ty), (back[0] + tz, back[1] + ty),
                   (back[0] - tz, back[1] - ty)], hatched=True, fill="#00000000")
    elif kind in ("optics.beam_splitter", "optics.splitter"):
        _plane(d, at, normal, half, role="surface", width=2.0, dashed=True)
        d.note(f"r = {fmt(_num(p.get('r'), math.sqrt(0.5)))}, t = {fmt(_num(p.get('t'), math.sqrt(0.5)))}")
    else:  # interface
        _plane(d, at, normal, half, role="surface", width=2.0)
        for s, key in ((1.0, "n_front"), (-1.0, "n_back")):
            d.text((at[0] + s * normal[0] * 0.4, at[1] + s * normal[1] * 0.4), f"{key} = {fmt(_num(p.get(key), 1.0))}")
    d.arrow((at[0] + normal[0] * 1.2, at[1] + normal[1] * 1.2), (at[0] + normal[0] * 0.1, at[1] + normal[1] * 0.1),
            "normal", role="guide")
    d.note("plane of unlimited size (drawn 2 mm wide)")
    return answer(d)


def _particle(p: dict, name: str) -> Drawing:
    r = _num(p.get("radius_um"), 0.25)
    d = Drawing(f"{name} – particle", unit="µm", axes=("z", "y"))
    material = f"n = {fmt(_num(p.get('index'), 1.5))}"
    d.material(material, f"particle · {material}")
    d.polygon([(r * math.cos(2 * math.pi * k / 72), r * math.sin(2 * math.pi * k / 72)) for k in range(72)],
              material=material)
    d.dimension((-r, -1.3 * r), (r, -1.3 * r), f"⌀ {fmt(2 * r)} µm")
    d.arrow((-2.5 * r, 0.0), (-1.1 * r, 0.0), "focused beam")
    d.note(f"in a medium of n = {fmt(_num(p.get('n_medium'), 1.0))}")
    return d
