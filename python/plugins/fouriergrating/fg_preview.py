"""Overview drawings of the FourierGrating blocks (docs/plugin-api.md, "Block previews").

The tab "Overview" of an `fg.grating` or `fg.stack` block shows the cross-section of its
configuration in the x–y plane (x along the grating vector, y the stacking direction, µm) over
two periods: the substrate below, the layers from the bottom up, the superstrate on top, each
part in the colour of its material (legend with the index as given). Layer types: homogeneous,
lamellar1d, profile1d (sinus, triangle, points), profile2d (its section at z0), polygon2d and
contour2d (their section at the height z of the first inclusion), rings (radial, from the
axis); other types (cad, rings_profile, json) as a hatched band with their name. Each layer's
thickness is dimensioned at the right, the period on top; the incidence (λ, θ, ψ, polarisation)
is an arrow onto the top surface, for a grating with its reflected or transmitted zeroth order.
A grating that only holds a Jones table is drawn as the sample plane with its orders.

Pure Python (no NumPy): the drawing is quick and needs nothing beyond nfcad.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from nfcad.drawing import Drawing, answer, fmt, unsupported

PERIODS = 2  # periods drawn
SAMPLES = 64  # points per period of a profile


def _num(v: Any, default: float = 0.0) -> float:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) else default


def material_label(name: str, m: Any) -> str:
    """'si · n = 4.087 + 0.035i', 'sio2 · Sellmeier', …"""
    if not isinstance(m, dict):
        return name
    n = m.get("n")
    if isinstance(n, int | float):
        return f"{name} · n = {fmt(n)}"
    if isinstance(n, list) and len(n) == 2 and all(isinstance(v, int | float) for v in n):
        sign = "+" if n[1] >= 0 else "−"
        return f"{name} · n = {fmt(n[0])} {sign} {fmt(abs(n[1]))}i"
    if isinstance(n, dict) and n:
        return f"{name} · n: {next(iter(n))}"
    eps = m.get("eps")
    if isinstance(eps, int | float):
        return f"{name} · ε = {fmt(eps)}"
    if isinstance(eps, list) and len(eps) == 2:
        return f"{name} · ε = {fmt(eps[0])} + {fmt(eps[1])}i"
    if isinstance(eps, dict) and eps:
        return f"{name} · ε: {next(iter(eps))}"
    if "eps_tensor" in m:
        return f"{name} · ε tensor"
    if "eps_principal" in m:
        return f"{name} · ε principal (anisotropic)"
    return name


def _profile(layer: dict, d: float) -> Callable[[float], float] | None:
    """g(x) in [0, depth] of a profile layer (x in µm), None if not drawable."""
    kind = layer.get("type")
    a = _num(layer.get("depth_um"))
    shape = layer.get("shape")
    k = 2 * math.pi / d if d > 0 else 0.0
    x0 = _num(layer.get("x0_um"))
    if kind in ("profile1d", "profile2d") and shape in ("sinus", "sinus_x", "egg_crate"):
        # egg_crate at its own z0: a/4 (1 + cos Kx (x − x0)) · 2
        return lambda x: a / 2 * (1 + math.cos(k * (x - x0)))
    if kind == "profile1d" and shape == "triangle":
        apex = _num(layer.get("apex_x_um"), d / 2)

        def tri(x: float) -> float:
            u = x % d if d > 0 else x
            if u <= apex:
                return a * u / apex if apex > 0 else a
            return a * (d - u) / (d - apex) if d > apex else a
        return tri
    if kind == "profile1d" and shape == "points":
        xs = [_num(v) for v in layer.get("x_um") or []]
        ys = [_num(v) for v in layer.get("y_um") or []]
        if len(xs) < 2 or len(xs) != len(ys) or d <= 0:
            return None
        xs_p, ys_p = xs + [xs[0] + d], ys + [ys[0]]

        def pts(x: float) -> float:
            u = (x - xs[0]) % d + xs[0]
            for i in range(len(xs_p) - 1):
                if xs_p[i] <= u <= xs_p[i + 1]:
                    t = (u - xs_p[i]) / (xs_p[i + 1] - xs_p[i]) if xs_p[i + 1] > xs_p[i] else 0.0
                    return ys_p[i] + t * (ys_p[i + 1] - ys_p[i])
            return ys[0]
        return pts
    return None


def _thickness(layer: dict) -> float:
    if layer.get("type") in ("profile1d", "profile2d"):
        return _num(layer.get("depth_um"), _num(layer.get("thickness_um")))
    return _num(layer.get("thickness_um"))


def _chords(poly: list[tuple[float, float]], zc: float) -> list[tuple[float, float]]:
    """x-intervals where the line z = zc runs inside the polygon (x, z)."""
    xs = []
    n = len(poly)
    for i in range(n):
        (x1, z1), (x2, z2) = poly[i], poly[(i + 1) % n]
        if (z1 <= zc < z2) or (z2 <= zc < z1):
            xs.append(x1 + (zc - z1) * (x2 - x1) / (z2 - z1))
    xs.sort()
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def _shape_polygon(region: dict) -> tuple[list[tuple[float, float]] | None, bool]:
    """The outline (x, z) of an inclusion or region; (outline, approximate)."""
    if "vertices_um" in region or "polygon_um" in region:
        pts = region.get("vertices_um") or region.get("polygon_um") or []
        return [(_num(p[0]), _num(p[1])) for p in pts if isinstance(p, list) and len(p) >= 2], False
    if isinstance(region.get("rectangle_um"), dict):
        r = region["rectangle_um"]
        (cx, cz), (sx, sz) = r.get("center", [0, 0]), r.get("size", [0, 0])
        cx, cz, sx, sz = _num(cx), _num(cz), _num(sx), _num(sz)
        return [(cx - sx / 2, cz - sz / 2), (cx + sx / 2, cz - sz / 2), (cx + sx / 2, cz + sz / 2),
                (cx - sx / 2, cz + sz / 2)], False
    for key in ("circle", "ellipse"):
        c = region.get(key)
        if isinstance(c, dict):
            cx, cz = (_num(v) for v in (c.get("center_um") or [0, 0])[:2])
            if key == "circle":
                rx = rz = _num(c.get("radius_um"))
                angle = 0.0
            else:
                rx, rz = (_num(v) for v in (c.get("radii_um") or [0, 0])[:2])
                angle = math.radians(_num(c.get("angle_deg")))
            pts = []
            for k in range(96):
                t = 2 * math.pi * k / 96
                u, v = rx * math.cos(t), rz * math.sin(t)
                pts.append((cx + u * math.cos(angle) - v * math.sin(angle), cz + u * math.sin(angle) + v * math.cos(angle)))
            return pts, False
    if isinstance(region.get("nurbs"), dict):  # the control polygon
        pts = region["nurbs"].get("points_um") or []
        return [(_num(p[0]), _num(p[1])) for p in pts if isinstance(p, list) and len(p) >= 2], True
    return None, False


class _Stack:
    """Draws a FourierGrating configuration into a drawing."""

    def __init__(self, d: Drawing, cfg: dict):
        self.d = d
        self.cfg = cfg
        self.materials: dict = cfg.get("materials") or {}
        self.period = _num((cfg.get("period_um") or {}).get("x"))
        layers = [L for L in cfg.get("layers") or [] if isinstance(L, dict)]
        self.layers = layers
        self.total = sum(_thickness(L) for L in layers)
        rings = [r for L in layers if L.get("type") in ("rings", "rings_profile") for r in L.get("radii_um") or []]
        if rings:
            outer = 1.3 * max(_num(r) for r in rings)
            self.x0, self.x1 = -outer, outer
        elif self.period > 0:
            self.x0, self.x1 = 0.0, PERIODS * self.period
        else:  # a laterally homogeneous stack
            width = max(1.5 * self.total, 1.0)
            self.x0, self.x1 = 0.0, width
        self.width = self.x1 - self.x0
        self.half = max(0.3 * self.total, 0.18 * self.width, 0.05)  # height of the half-spaces drawn

    def mat(self, name: Any) -> str:
        name = str(name or "?")
        self.d.material(name, material_label(name, self.materials.get(name)))
        return name

    def rect(self, x0: float, x1: float, y0: float, y1: float, material: Any, **kw) -> None:
        x0, x1 = max(x0, self.x0), min(x1, self.x1)
        if x1 - x0 <= 1e-12 or y1 - y0 <= 0:
            return
        self.d.polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], material=self.mat(material), **kw)

    def copies(self) -> range:
        if self.period <= 0:
            return range(0, 1)
        return range(-1, int(math.ceil(self.width / self.period)) + 1)

    def draw(self) -> None:
        cfg = self.cfg
        sub, sup = cfg.get("substrate"), cfg.get("superstrate")
        self.rect(self.x0, self.x1, -self.half, 0.0, sub or "substrate")
        self.d.text((self.x1 - 0.02 * self.width, -0.3 * self.half), f"substrate {sub or ''}".strip(), align="right",
                    role="note")
        y = 0.0
        for i, layer in enumerate(self.layers):
            h = _thickness(layer)
            self.layer(layer, y, h, i)
            if h > 0:
                x = self.x1 + 0.05 * self.width
                if h >= 0.03 * max(self.total, 1e-9):
                    self.d.dimension((x, y), (x, y + h), f"{fmt(h)}")
                    self.d.extension((self.x1, y + h), (x + 0.02 * self.width, y + h))
            y += h
        self.rect(self.x0, self.x1, y, y + self.half, sup or "superstrate")
        self.d.text((self.x0 + 0.02 * self.width, y + 0.5 * self.half), f"superstrate {sup or ''}".strip(),
                    align="left", role="note")
        self.d.extension((self.x1, 0.0), (self.x1 + 0.07 * self.width, 0.0))
        if self.period > 0 and not any(L.get("type") in ("rings", "rings_profile") for L in self.layers):
            yp = -0.8 * self.half  # in the substrate: the incidence is on top
            self.d.dimension((0.0, yp), (self.period, yp), f"Λ = {fmt(self.period)} µm")
        thin = [f"{i + 1}: {fmt(_thickness(L))} µm" for i, L in enumerate(self.layers)
                if 0 < _thickness(L) < 0.03 * max(self.total, 1e-9)]
        if thin:
            self.d.note("thin layers (not dimensioned): " + ", ".join(thin))
        if cfg.get("superstrate_structure"):
            self.d.note("superstrate_structure is not drawn")

    def layer(self, layer: dict, y: float, h: float, index: int) -> None:
        kind = layer.get("type")
        if kind == "homogeneous":
            self.rect(self.x0, self.x1, y, y + h, layer.get("material"))
        elif kind == "lamellar1d":
            b = [_num(v) for v in layer.get("breakpoints_um") or []]
            mats = layer.get("materials") or []
            if len(b) < 2 or len(mats) < len(b) - 1:
                return self.unknown(layer, y, h, "lamellar1d without breakpoints")
            d = self.period if self.period > 0 else b[-1] - b[0]
            for p in self.copies():
                for k in range(len(b) - 1):
                    self.rect(p * d + b[k], p * d + b[k + 1], y, y + h, mats[k])
        elif kind in ("profile1d", "profile2d"):
            g = _profile(layer, self.period)
            if g is None or self.period <= 0:
                return self.unknown(layer, y, h, f"{kind} {layer.get('shape', '')}")
            self.rect(self.x0, self.x1, y, y + h, layer.get("above"))
            n = SAMPLES * max(1, round(self.width / self.period))
            xs = [self.x0 + self.width * k / n for k in range(n + 1)]
            pts = [(self.x0, y)] + [(x, y + min(max(g(x), 0.0), h)) for x in xs] + [(self.x1, y)]
            self.d.polygon(pts, material=self.mat(layer.get("below")))
            if kind == "profile2d":
                self.d.note(f"layer {index + 1}: profile2d at z = {fmt(_num(layer.get('z0_um')))} µm")
        elif kind in ("polygon2d", "contour2d"):
            regions = layer.get("inclusions") if kind == "polygon2d" else layer.get("regions")
            regions = [r for r in regions or [] if isinstance(r, dict)]
            self.rect(self.x0, self.x1, y, y + h, layer.get("background"))
            shapes = [(_shape_polygon(r), r) for r in regions]
            first = next((s for (s, _), _r in shapes if s), None)
            if not first:
                return
            zc = (min(p[1] for p in first) + max(p[1] for p in first)) / 2
            approx = False
            for (poly, rough), r in shapes:
                if not poly:
                    continue
                approx |= rough or bool(r.get("holes"))
                for left, right in _chords(poly, zc):
                    for p in self.copies():
                        off = p * self.period if self.period > 0 else 0.0
                        self.rect(left + off, right + off, y, y + h, r.get("material"))
            self.d.note(f"layer {index + 1}: {kind} cut at z = {fmt(zc)} µm" + (" (approximate)" if approx else ""))
        elif kind == "rings":
            radii = [_num(r) for r in layer.get("radii_um") or []]
            mats = layer.get("materials") or []
            edges = [0.0] + radii + [self.x1]
            for k in range(min(len(mats), len(edges) - 1)):
                for sign in (1.0, -1.0):
                    lo, hi = sorted((sign * edges[k], sign * edges[k + 1]))
                    self.rect(lo, hi, y, y + h, mats[k])
        else:
            self.unknown(layer, y, h, str(kind))
        return None

    def unknown(self, layer: dict, y: float, h: float, what: str) -> None:
        mat = layer.get("material") or layer.get("background") or layer.get("above") or "?"
        if h <= 0:
            return
        self.rect(self.x0, self.x1, y, y + h, mat, hatched=True)
        self.d.text(((self.x0 + self.x1) / 2, y + h / 2), what or "layer")

    def incidence(self, side: str = "") -> None:
        inc = self.cfg.get("incidence") or {}
        lam = inc.get("lambda_um")
        phi = inc.get("phi_deg", 0.0)
        theta = _num(phi[0] if isinstance(phi, list) and phi else phi)
        length = 0.8 * self.half
        top = self.total
        xc = (self.x0 + self.x1) / 2
        sx, sy = math.sin(math.radians(theta)), math.cos(math.radians(theta))
        start = (xc - length * sx, top + length * sy)
        bits = []
        if isinstance(lam, int | float):
            bits.append(f"λ = {fmt(lam)} µm")
        elif isinstance(lam, (list, dict)):
            bits.append("λ scan")
        bits.append(f"θ = {fmt(theta)}°")
        psi = _num(inc.get("psi_deg")) if not isinstance(inc.get("psi_deg"), list) else 0.0
        if psi:
            bits.append(f"ψ = {fmt(psi)}°")
        delta = inc.get("delta_deg")
        if delta in (0, 0.0):
            bits.append("TE")
        elif delta in (90, 90.0):
            bits.append("TM")
        self.d.arrow(start, (xc, top), ", ".join(bits), align="right" if theta >= 0 else "left")
        if side == "reflected":
            end = (xc + 0.75 * length * sx, top + 0.75 * length * sy)
            self.d.arrow((xc, top), end, dashed=True)
            self.d.text(end, "R₀", align="left", valign="bottom", role="note")
        elif side == "transmitted":
            end = (xc + 0.6 * self.half * sx, -0.6 * self.half * sy)
            self.d.arrow((xc, 0.0), end, dashed=True)
            self.d.text(end, "T₀", align="left", valign="top", role="note")
        if inc.get("type") and inc.get("type") != "plane_wave":
            self.d.note(f"incidence: {inc.get('type')}")


def draw_config(cfg: dict, title: str, side: str = "") -> Drawing:
    stack = _Stack(Drawing(title, unit="µm", axes=("x", "y")), cfg)
    stack.draw()
    stack.incidence(side)
    ratio = (stack.total + 2 * stack.half) / max(stack.width, 1e-12)
    if ratio < 0.12 or ratio > 10:
        stack.d.aspect = "fit"
        stack.d.note("x and y are drawn to different scales")
    if cfg.get("dimension") == "2D":
        stack.d.note(f"2D grating: section x–y; period z {fmt(_num((cfg.get('period_um') or {}).get('z')))} µm")
    return stack.d


def _table_only(node: dict, title: str) -> Drawing:
    """A grating with a Jones table but no configuration: the sample plane and its orders."""
    params = node.get("params") or {}
    d = Drawing(title, unit="", axes=None)
    d.polygon([(-1.0, -0.25), (1.0, -0.25), (1.0, 0.0), (-1.0, 0.0)], material="sample", hatched=True)
    d.arrow((-0.5, 0.9), (0.0, 0.0), "incident")
    orders = [o for o in params.get("orders") or [] if isinstance(o, int | float)] or [-1, 0, 1]
    side = params.get("side", "reflected")
    for o in orders:
        angle = math.radians(25.0 * o)
        sign = 1.0 if side == "reflected" else -1.0
        d.arrow((0.0, 0.0), (0.9 * math.sin(angle), sign * 0.9 * math.cos(angle)), f"{int(o)}", dashed=True)
    d.note("the block holds a Jones table only: no structure to draw (angles schematic)")
    return d


def preview(request: dict, config_of: Callable[[dict], dict | None]) -> dict:
    node = request.get("node") or {}
    kind = str(node.get("type", ""))
    if kind not in ("fg.grating", "fg.stack"):
        return unsupported(f"the FourierGrating plugin draws fg.grating and fg.stack, not {kind}")
    name = str(node.get("name") or node.get("id") or kind)
    params = node.get("params") or {}
    cfg = config_of(node)
    if cfg is None:
        if kind == "fg.grating" and (params.get("table") or params.get("table_data")):
            return answer(_table_only(node, f"{name} – Jones table"))
        return {"ok": False, "error": f"{name} holds no FourierGrating configuration (Store panel configuration "
                                       "in block, or name a configuration file)"}
    side = str(params.get("side", "")) if kind == "fg.grating" else ""
    d = draw_config(cfg, f"{name} – cross-section x–y", side)
    point, normal = params.get("point"), params.get("normal")
    if isinstance(point, list) and isinstance(normal, list):
        d.note(f"in the system at {', '.join(fmt(_num(v)) for v in point)} mm, normal "
               f"{', '.join(fmt(_num(v)) for v in normal)}")
    return answer(d)
