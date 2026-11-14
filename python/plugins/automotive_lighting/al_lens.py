"""A headlamp or signal lamp with a patterned lens: a paraboloid mirror and, in front of it, a lens
whose inner side is a grid of spreading elements (prisms, cylinder lenses, pillows).

Every cell of the grid turns the light that reaches it: its middle by (deflect H, deflect V), its
borders by ± the spread more – running linearly across the cell, its left part to the left, its
upper part upwards. A cell with neither is plane glass. For a point of the cell, the ray that comes
from the filament centre by way of the mirror (direction d) is to leave the lens in the direction t,
d turned by these angles. The outer side of the lens is a plane; the direction g inside the glass follows from t by
refraction there, and the inner surface must have the normal

    N ∝ d − n g          (Snell's law in vector form, n: refractive index),

which gives its slopes ∂x/∂y and ∂x/∂z; they are integrated over the cell (through its centre) and
the cell's surface is the Bézier patch of degree 5 closest to that. The cells are independent:
between neighbours a step remains, closed by a wall along X. A ray that meets a wall – in the air
before the elements or in the glass behind them – is lost for the beam.

The lens may lean back (rake), run back to one side (sweep) and be domed (a sphere's radius): its
outer side is that shape, its inner side the same shape `thickness` behind it (measured along X)
with the elements on it. The refraction at the outer side then uses the normal of the shape there.

Coordinates as everywhere in the plugin: origin = filament centre, +X the driving direction, +Y
left, +Z up. NumPy only."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

import al_layout
from al_design import DesignError
from al_optics import Cutoff, Filament, Lamp, direction
from al_spline import Graph

DEGREE = 5
NODES = 15             # per direction: where a cell's slopes are computed


@dataclass(frozen=True)
class Element:
    """What the cells whose centre lies in y0 … y1, z0 … z1 do (degrees): by how much the light is
    turned in the cell's middle, and the half spread horizontally and vertically."""

    y0: float
    y1: float
    z0: float
    z1: float
    deflect_h: float = 0.0
    deflect_v: float = 0.0
    spread_h: float = 0.0
    spread_v: float = 0.0


@dataclass(frozen=True)
class LensSettings:
    lamp: Lamp
    cutoff: Cutoff
    elements: tuple[Element, ...]
    focal: float = 25.0            # mm, of the paraboloid
    focus_behind: float = 0.0      # mm: its focus lies this far behind the filament centre
    hole_radius: float = 12.0      # mm, lamp hole
    lens_x: float = 75.0           # mm, the inner side's base plane in front of the filament centre
    thickness: float = 3.0         # mm
    index: float = 1.49            # refractive index (PMMA; glass about 1.52)
    cell_width: float = 10.0       # mm
    cell_height: float = 10.0      # mm
    rake: float = 0.0              # degrees: the lens leans back, its top towards the mirror
    sweep: float = 0.0             # degrees: it runs back towards the left (negative: the right)
    radius: float = 0.0            # mm: domed outwards, a sphere of this radius (0: flat)


def _bernstein(t: np.ndarray, degree: int = DEGREE) -> np.ndarray:
    """B[k, i] = the Bernstein polynomial i of `degree` at t_k (built up degree by degree)."""
    t = np.asarray(t, dtype=float)
    u = 1.0 - t
    rows = [np.ones_like(t)]
    for n in range(1, degree + 1):
        rows = [u * rows[0]] + [u * rows[i] + t * rows[i - 1] for i in range(1, n)] + [t * rows[n - 1]]
    return np.stack(rows, axis=1)


def refract(d: np.ndarray, normal: np.ndarray, ratio: float) -> tuple[np.ndarray, np.ndarray]:
    """Unit directions d (n, 3) refracted at surfaces with unit normals `normal` (n, 3 or 3) that
    point along the light (normal · d > 0); ratio = index before / index after. Returns the new
    directions and whether the ray passes (no total reflection)."""
    c = np.sum(d * normal, axis=-1)
    k = 1.0 - ratio * ratio * (1.0 - c * c)
    ok = (k > 0.0) & (c > 0.0)
    out = ratio * d + (np.sqrt(np.maximum(k, 0.0)) - ratio * c)[..., None] * normal
    return out, ok


@dataclass
class LensSystem:
    settings: LensSettings
    frame: np.ndarray              # outline of mirror and lens in the front view (y, z)
    filament: Filament
    y0: float = 0.0                # the grid of cells: first edges and numbers
    z0: float = 0.0
    ny: int = 0
    nz: int = 0
    coeff: np.ndarray = field(default_factory=lambda: np.zeros((0, 0, DEGREE + 1, DEGREE + 1)))   # sag, Bernstein
    used: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))
    whole: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))   # cells the outline does not cut
    fit_error: float = 0.0         # largest slope error of the patches against the wanted slopes
    sag: tuple[float, float] = (0.0, 0.0)     # the elements' depth and height about the lens' shape
    warnings: list[str] = field(default_factory=list)

    # ---- the mirror
    def mirror(self, y, z) -> tuple[np.ndarray, np.ndarray]:
        """x of the paraboloid and its unit normals (towards the light)."""
        s = self.settings
        y, z = np.asarray(y, dtype=float), np.asarray(z, dtype=float)
        x = (y * y + z * z) / (4.0 * s.focal) - s.focal - s.focus_behind
        n = np.stack([np.ones_like(x), -y / (2.0 * s.focal), -z / (2.0 * s.focal)], axis=-1)
        return x, n / np.linalg.norm(n, axis=-1, keepdims=True)

    def chief(self, y, z) -> np.ndarray:
        """The direction in which the mirror point above (y, z) sends the light of the filament centre."""
        x, n = self.mirror(y, z)
        d = np.stack([x, np.asarray(y, dtype=float), np.asarray(z, dtype=float)], axis=-1)
        d = d / np.linalg.norm(d, axis=-1, keepdims=True)
        return d - 2.0 * np.sum(d * n, axis=-1, keepdims=True) * n

    def samples(self, spacing: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Mirror points on a front-view lattice within the frame, outside the lamp hole: positions,
        unit normals, areas."""
        lo, hi = self.frame.min(axis=0), self.frame.max(axis=0)
        ys = (np.arange(math.floor(lo[0] / spacing), math.ceil(hi[0] / spacing)) + 0.5) * spacing
        zs = (np.arange(math.floor(lo[1] / spacing), math.ceil(hi[1] / spacing)) + 0.5) * spacing
        Y, Z = np.meshgrid(ys, zs, indexing="ij")
        pts = np.stack([Y.ravel(), Z.ravel()], axis=1)
        pts = pts[al_layout.contains(self.frame, pts) & (np.hypot(pts[:, 0], pts[:, 1]) >= self.settings.hole_radius)]
        x, n = self.mirror(pts[:, 0], pts[:, 1])
        return np.column_stack([x, pts]), n, spacing * spacing / n[:, 0]

    # ---- the lens
    def shape(self, y, z):
        """The form of the lens: x relative to where the lamp axis meets it, and its slopes ∂x/∂y,
        ∂x/∂z – of the inner side's base and of the outer side alike."""
        s = self.settings
        y, z = np.asarray(y, dtype=float), np.asarray(z, dtype=float)
        ky, kz = -math.tan(math.radians(s.sweep)), -math.tan(math.radians(s.rake))
        x, dy, dz = ky * y + kz * z, ky + 0.0 * y, kz + 0.0 * z
        if s.radius > 0.0:
            root = np.sqrt(np.maximum(s.radius ** 2 - y * y - z * z, 1e-12))
            x, dy, dz = x + root - s.radius, dy - y / root, dz - z / root
        return x, dy, dz

    def element(self, y: float, z: float) -> Element | None:
        return next((e for e in self.settings.elements if e.y0 <= y < e.y1 and e.z0 <= z < e.z1), None)

    def inner(self, y: np.ndarray, z: np.ndarray):
        """x - lens_x of the inner side (the lens' shape with the elements on it) and its slopes at
        points; `inside` marks the points that lie on a cell."""
        s = self.settings
        iy = np.floor((y - self.y0) / s.cell_width).astype(int)
        iz = np.floor((z - self.z0) / s.cell_height).astype(int)
        inside = (iy >= 0) & (iy < self.ny) & (iz >= 0) & (iz < self.nz)
        iy, iz = np.clip(iy, 0, self.ny - 1), np.clip(iz, 0, self.nz - 1)
        inside &= self.used[iy, iz]
        ta = (y - self.y0) / s.cell_width - iy
        tb = (z - self.z0) / s.cell_height - iz
        C = self.coeff[iy, iz]                                             # (n, 6, 6)
        Ba, Bb = _bernstein(ta), _bernstein(tb)
        low_a, low_b = _bernstein(ta, DEGREE - 1), _bernstein(tb, DEGREE - 1)
        Db = np.zeros_like(Bb)                                             # d/dt of the Bernstein polynomials
        Db[:, 1:] += DEGREE * low_b
        Db[:, :-1] -= DEGREE * low_b
        along_b = np.matmul(C, Bb[:, :, None])[:, :, 0]                    # (n, 6): the patch along a, at b
        sag = np.sum(along_b * Ba, axis=1)
        dy = DEGREE * np.sum((along_b[:, 1:] - along_b[:, :-1]) * low_a, axis=1) / s.cell_width
        dz = np.sum(np.matmul(C, Db[:, :, None])[:, :, 0] * Ba, axis=1) / s.cell_height
        return sag, dy, dz, inside, self.whole[iy, iz]

    def cell(self, y, z):
        """Indices of the cell at points and whether it is one of the lens."""
        s = self.settings
        iy = np.floor((y - self.y0) / s.cell_width).astype(int)
        iz = np.floor((z - self.z0) / s.cell_height).astype(int)
        inside = (iy >= 0) & (iy < self.ny) & (iz >= 0) & (iz < self.nz)
        return iy, iz, inside & self.used[np.clip(iy, 0, self.ny - 1), np.clip(iz, 0, self.nz - 1)]

    def _wall(self, start: np.ndarray, v: np.ndarray, end_yz: tuple, in_air: bool) -> np.ndarray:
        """Whether straight paths from `start` (n, 3) along v to the points end_yz meet a wall between
        two elements: where a path passes from one cell to its neighbour it must still be in the air
        before both surfaces (in_air) or already in the glass behind both."""
        s = self.settings
        ia, ja, used_a = self.cell(start[:, 1], start[:, 2])
        ib, jb, used_b = self.cell(*end_yz)
        moved = ((ia != ib) | (ja != jb)) & used_a & used_b
        hit = moved & ((np.abs(ia - ib) + np.abs(ja - jb)) > 1)             # across a corner or a whole cell
        for axis, (a, b, first, size) in enumerate(((ia, ib, self.y0, s.cell_width), (ja, jb, self.z0, s.cell_height))):
            rows = np.flatnonzero(moved & ~hit & (a != b))
            if not len(rows):
                continue
            border = first + np.maximum(a[rows], b[rows]) * size
            along = v[rows, 1 + axis]
            tau = (border - start[rows, 1 + axis]) / np.where(along != 0.0, along, 1.0)
            point = start[rows] + tau[:, None] * v[rows]
            side = np.where(b[rows] > a[rows], 1.0, -1.0) * 1e-7 * size      # just beyond the border
            before, behind = point[:, 1:].copy(), point[:, 1:].copy()
            before[:, axis] -= side
            behind[:, axis] += side
            x = point[:, 0] - s.lens_x
            h0, h1 = self.inner(before[:, 0], before[:, 1])[0], self.inner(behind[:, 0], behind[:, 1])[0]
            hit[rows] = (x > np.minimum(h0, h1) - 1e-9) if in_air else (x < np.maximum(h0, h1) + 1e-9)
        return hit

    def through(self, origins: np.ndarray, d: np.ndarray, transmittance: float = 1.0):
        """Rays (origins (n, 3), unit directions (n, 3)) through the lens: the directions behind it,
        a factor per ray – `transmittance`, or 0 for a ray that misses the lens, meets a wall between
        two elements or is totally reflected – and which rays met a wall."""
        s = self.settings
        forward = d[:, 0] > 1e-6
        dx = np.where(forward, d[:, 0], 1.0)
        t = (s.lens_x - origins[:, 0]) / dx
        for _ in range(3):                                                  # onto the lens' shape …
            y, z = origins[:, 1] + t * d[:, 1], origins[:, 2] + t * d[:, 2]
            t = (s.lens_x + self.shape(y, z)[0] - origins[:, 0]) / dx
        for _ in range(2):                                                  # … and onto its elements
            y, z = origins[:, 1] + t * d[:, 1], origins[:, 2] + t * d[:, 2]
            sag, dy, dz, inside, whole = self.inner(y, z)
            t = (s.lens_x + sag - origins[:, 0]) / dx
        normal = np.stack([np.ones_like(dy), -dy, -dz], axis=1)
        normal /= np.linalg.norm(normal, axis=1, keepdims=True)
        glass, ok1 = refract(d, normal, 1.0 / s.index)
        # through the glass to the outer side
        gx = np.where(glass[:, 0] > 1e-6, glass[:, 0], 1.0)
        x_in = s.lens_x + sag
        tg = s.thickness / gx
        for _ in range(3):
            yo, zo = y + tg * glass[:, 1], z + tg * glass[:, 2]
            ox, oy, oz = self.shape(yo, zo)
            tg = (s.lens_x + s.thickness + ox - x_in) / gx
        outer = np.stack([np.ones_like(oy), -oy, -oz], axis=1)
        outer /= np.linalg.norm(outer, axis=1, keepdims=True)
        out, ok2 = refract(glass, outer, s.index)
        ok2 &= (glass[:, 0] > 1e-6) & (tg > 0.0)
        ok = forward & inside & ok1 & ok2
        cut = np.flatnonzero(ok & ~whole)                                   # only cells at the rim need the outline
        if len(cut):
            ok[cut] = al_layout.contains(self._outline, np.column_stack([y[cut], z[cut]]))
        # walls: the path in the air from where the elements begin, and in the glass to where they end
        form = s.lens_x + self.shape(y, z)[0]
        hit = np.column_stack([x_in, y, z])
        back = np.maximum(x_in - (form + self.sag[0] - 0.01), 0.0) / dx
        wall = self._wall(hit - back[:, None] * d, d, (y, z), True)
        # a ray that finds no surface point in one cell – the point it is sent to lies in the next
        # one, whose surface lies elsewhere – runs into the wall between the two
        ia, ja, _ = self.cell(y, z)
        ib, jb, _ = self.cell(origins[:, 1] + t * d[:, 1], origins[:, 2] + t * d[:, 2])
        wall |= (ia != ib) | (ja != jb)
        on = np.maximum(form + self.sag[1] + 0.01 - x_in, 0.0) / gx
        wall |= self._wall(hit, glass, (y + on * glass[:, 1], z + on * glass[:, 2]), False)
        wall &= ok
        return out, np.where(ok & ~wall, transmittance, 0.0), wall

    @property
    def _outline(self) -> np.ndarray:
        if not hasattr(self, "_simple"):
            self._simple = al_layout.simplified(self.frame, 0.05)
        return self._simple

    @property
    def cells(self) -> int:
        return int(self.used.sum())


def build(settings: LensSettings, frame: np.ndarray, progress=None) -> LensSystem:
    """The system within `frame` (front view about the lamp axis): the paraboloid and the lens with
    its cells designed."""
    s = settings
    if s.index <= 1.0 or s.thickness <= 0.0 or s.cell_width <= 0.0 or s.cell_height <= 0.0:
        raise DesignError("the lens needs a refractive index above 1, a thickness and a cell size")
    if al_layout.area(frame) < 0:
        frame = frame[::-1]
    system = LensSystem(s, frame, Filament.of(s.lamp))
    lo, hi = frame.min(axis=0), frame.max(axis=0)
    if s.radius > 0.0 and s.radius < 1.05 * float(np.hypot(frame[:, 0], frame[:, 1]).max()):
        raise DesignError(f"the lens' radius ({s.radius:g} mm) is smaller than the lens is wide")
    gap = s.lens_x + system.shape(frame[:, 0], frame[:, 1])[0] - system.mirror(frame[:, 0], frame[:, 1])[0]
    if gap.min() < 1.0:
        raise DesignError(f"the lens (at x = {s.lens_x:g} mm on the axis) lies inside the mirror: at the rim it is "
                          f"{-gap.min():.1f} mm behind it – move it further forward or lean it less")
    # cells: one is centred on the lamp axis
    i0, i1 = math.floor(lo[0] / s.cell_width + 0.5), math.floor(hi[0] / s.cell_width + 0.5)
    j0, j1 = math.floor(lo[1] / s.cell_height + 0.5), math.floor(hi[1] / s.cell_height + 0.5)
    system.y0, system.z0 = (i0 - 0.5) * s.cell_width, (j0 - 0.5) * s.cell_height
    system.ny, system.nz = i1 - i0 + 1, j1 - j0 + 1
    system.coeff = np.zeros((system.ny, system.nz, DEGREE + 1, DEGREE + 1))
    system.used = np.zeros((system.ny, system.nz), dtype=bool)
    system.whole = np.zeros((system.ny, system.nz), dtype=bool)
    t = np.linspace(0.0, 1.0, NODES)
    fit = np.linalg.pinv(_bernstein(t))                                    # values at the nodes -> coefficients
    B = _bernstein(t)
    low = _bernstein(t, DEGREE - 1)
    mid = NODES // 2
    outline = al_layout.simplified(frame, 0.05)
    without = 0
    sag_lo, sag_hi = 0.0, 0.0
    for i in range(system.ny):
        if progress is not None:
            progress(i / system.ny, "lens elements …")
        for j in range(system.nz):
            ya, za = system.y0 + i * s.cell_width, system.z0 + j * s.cell_height
            corners = np.array([[ya, za], [ya + s.cell_width, za], [ya + s.cell_width, za + s.cell_height],
                                [ya, za + s.cell_height], [ya + 0.5 * s.cell_width, za + 0.5 * s.cell_height]])
            within = al_layout.contains(outline, corners)
            if not within.any():
                continue                                                    # (a cell the outline only grazes is left out)
            edge = np.concatenate([corners[k] + np.linspace(0, 1, 9)[:, None] * (corners[(k + 1) % 4] - corners[k])
                                   for k in range(4)])
            system.whole[i, j] = bool(al_layout.contains(outline, edge).all())
            e = system.element(ya + 0.5 * s.cell_width, za + 0.5 * s.cell_height)
            if e is None:
                without += 1
                e = Element(0, 0, 0, 0)
            Y, Z = np.meshgrid(ya + t * s.cell_width, za + t * s.cell_height, indexing="ij")
            arrive = system.chief(Y, Z)
            H = np.degrees(np.arctan(-arrive[..., 1] / arrive[..., 0])) + e.deflect_h \
                - e.spread_h * (2.0 * t - 1.0)[:, None]                         # the left part to the left
            V = np.degrees(np.arctan(arrive[..., 2] / arrive[..., 0])) + e.deflect_v \
                + e.spread_v * (2.0 * t - 1.0)[None, :]                         # the upper part upwards
            want = direction(np.tan(np.radians(H)), np.tan(np.radians(V)))
            base, base_y, base_z = system.shape(Y, Z)
            outer = np.stack([np.ones_like(base_y), -base_y, -base_z], axis=-1)
            outer /= np.linalg.norm(outer, axis=-1, keepdims=True)
            # the direction in the glass: the wanted ray followed backwards through the outer side
            back, _ = refract(-want.reshape(-1, 3), -outer.reshape(-1, 3), 1.0 / s.index)
            glass = -back.reshape(want.shape)
            normal = arrive - s.index * glass
            if np.any(normal[..., 0] >= -1e-6):
                raise DesignError(f"the lens element at y = {ya + 0.5 * s.cell_width:.0f}, z = "
                                  f"{za + 0.5 * s.cell_height:.0f} mm cannot bend the light that far – reduce "
                                  "its deflection or spread")
            sy, sz = -normal[..., 1] / normal[..., 0], -normal[..., 2] / normal[..., 0]
            # the element on the lens' shape: its slopes along y through the cell's centre, then along z
            ey, ez = sy - base_y, sz - base_z
            da, db = s.cell_width / (NODES - 1), s.cell_height / (NODES - 1)
            line = np.concatenate([[0.0], np.cumsum(0.5 * (ey[1:, mid] + ey[:-1, mid]) * da)])
            up = np.concatenate([np.zeros((NODES, 1)), np.cumsum(0.5 * (ez[:, 1:] + ez[:, :-1]) * db, axis=1)], axis=1)
            sag = line[:, None] + up - up[:, mid:mid + 1]
            sag -= sag[mid, mid]
            sag_lo, sag_hi = min(sag_lo, float(sag.min())), max(sag_hi, float(sag.max()))
            C = fit @ (base + sag) @ fit.T
            system.coeff[i, j], system.used[i, j] = C, True
            fy = DEGREE * (low @ (C[1:] - C[:-1]) @ B.T) / s.cell_width
            fz = DEGREE * (B @ (C[:, 1:] - C[:, :-1]) @ low.T) / s.cell_height
            system.fit_error = max(system.fit_error, float(np.abs(fy - sy).max()), float(np.abs(fz - sz).max()))
    if not system.used.any():
        raise DesignError("the lens has no cell within the frame")
    if without:
        system.warnings.append(f"{without} cells lie in no row of the element table: they are plane")
    system.sag = (sag_lo, sag_hi)
    if s.thickness + system.sag[0] < 0.3:
        raise DesignError(f"the lens elements are {-system.sag[0]:.1f} mm deep, more than the lens is thick "
                          f"({s.thickness:g} mm) – a thicker lens, smaller cells or less deflection")
    return system


# ------------------------------------------------------------------ geometry for CAD
def _loop(points: np.ndarray) -> dict:
    pts = np.vstack([points, points[:1]])
    n = len(pts)
    return {"degree": 1, "knots": [0.0] + [k / (n - 1) for k in range(n)] + [1.0],
            "points": [round(float(c), 8) for p in pts for c in (p[0], p[1], 0.0)]}


def faces(system: LensSystem, origin=(0.0, 0.0, 0.0)) -> list[tuple[str, str, dict]]:
    """(kind, name, trimmed surface): the mirror, the lens' outer side and every cell of its inner
    side. All surfaces have the parameters (u, v) = (y, z) of the design."""
    s = system.settings
    ox, oy, oz = origin
    lo, hi = system.frame.min(axis=0) - 1.0, system.frame.max(axis=0) + 1.0
    out = []
    # the mirror: a paraboloid is a polynomial of degree 2 – the bicubic graph is exact
    g = Graph((lo[0], hi[0]), (lo[1], hi[1]), 6, 6)
    Y, Z = np.meshgrid(g.sites_p, g.sites_q, indexing="ij")
    g.interpolate(system.mirror(Y, Z)[0])
    pts = np.stack([g.coeff + ox, Y + oy, Z + oz], axis=-1)
    surface = {"degree_u": 3, "degree_v": 3, "knots_u": [float(k) for k in g.knots_p],
               "knots_v": [float(k) for k in g.knots_q], "num_u": 6, "num_v": 6,
               "points": [round(float(c), 8) for c in pts.reshape(-1)]}
    mirror = {"type": "trimmed_surface", "surface": surface, "outer": [_loop(system.frame)], "label": "mirror"}
    if s.hole_radius > 0.0:
        n = max(24, math.ceil(2.0 * math.pi / math.sqrt(8.0 * al_layout.ARC_TOLERANCE / s.hole_radius)))
        a = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
        mirror["holes"] = [[_loop(s.hole_radius * np.column_stack([np.cos(a), np.sin(a)]))]]
    out.append(("mirror", "Mirror (paraboloid)", mirror))
    # the outer side of the lens: its shape (a plane is exact; a dome within about 1e-4 mm)
    count = 4 if s.radius <= 0.0 else 16
    g = Graph((lo[0], hi[0]), (lo[1], hi[1]), count, count)
    Y, Z = np.meshgrid(g.sites_p, g.sites_q, indexing="ij")
    g.interpolate(s.lens_x + s.thickness + system.shape(Y, Z)[0])
    pts = np.stack([g.coeff + ox, Y + oy, Z + oz], axis=-1)
    plane = {"degree_u": 3, "degree_v": 3, "knots_u": [float(k) for k in g.knots_p],
             "knots_v": [float(k) for k in g.knots_q], "num_u": count, "num_v": count,
             "points": [round(float(c), 8) for c in pts.reshape(-1)]}
    out.append(("lens", "Lens outer side", {"type": "trimmed_surface", "surface": plane,
                                            "outer": [_loop(system.frame)], "label": "lens outer side"}))
    # the cells: Bézier patches of degree 5
    for i in range(system.ny):
        for j in range(system.nz):
            if not system.used[i, j]:
                continue
            ya, za = system.y0 + i * s.cell_width, system.z0 + j * s.cell_height
            yb, zb = ya + s.cell_width, za + s.cell_height
            cell = np.array([[ya, za], [yb, za], [yb, zb], [ya, zb]])
            pieces = [system.frame]
            for normal, offset in (((1.0, 0.0), ya), ((-1.0, 0.0), -yb), ((0.0, 1.0), za), ((0.0, -1.0), -zb)):
                pieces = al_layout.clip_all(pieces, al_layout.Line(np.array(normal), offset))
            if not pieces:
                continue
            ctrl = [(s.lens_x + system.coeff[i, j, a, b] + ox, ya + (yb - ya) * a / DEGREE + oy,
                     za + (zb - za) * b / DEGREE + oz) for a in range(DEGREE + 1) for b in range(DEGREE + 1)]
            patch = {"degree_u": DEGREE, "degree_v": DEGREE, "knots_u": [ya] * (DEGREE + 1) + [yb] * (DEGREE + 1),
                     "knots_v": [za] * (DEGREE + 1) + [zb] * (DEGREE + 1), "num_u": DEGREE + 1, "num_v": DEGREE + 1,
                     "points": [round(float(c), 8) for p in ctrl for c in p]}
            for piece in pieces:
                whole = abs(al_layout.area(piece) - al_layout.area(cell)) < 1e-6
                face = {"type": "trimmed_surface", "surface": patch, "label": f"lens element {i}.{j}"}
                if not whole:
                    face["outer"] = [_loop(piece)]
                out.append(("element", f"Lens element {i}.{j}", face))
    # the walls between neighbouring cells: ruled along X between the two patches' rims
    outline = al_layout.simplified(system.frame, 0.05)
    fraction = np.arange(DEGREE + 1) / DEGREE
    for i in range(system.ny):
        for j in range(system.nz):
            if not system.used[i, j]:
                continue
            ya, za = system.y0 + i * s.cell_width, system.z0 + j * s.cell_height
            yb, zb = ya + s.cell_width, za + s.cell_height
            for (ni, nj), mine, theirs, fixed, lo_v, hi_v, across in (
                    ((i + 1, j), system.coeff[i, j, DEGREE, :], None, yb, za, zb, False),
                    ((i, j + 1), system.coeff[i, j, :, DEGREE], None, zb, ya, yb, True)):
                if ni >= system.ny or nj >= system.nz or not system.used[ni, nj]:
                    continue
                theirs = system.coeff[ni, nj, :, 0] if across else system.coeff[ni, nj, 0, :]
                if np.abs(mine - theirs).max() < 1e-6:
                    continue                                                # no step here
                v = lo_v + (hi_v - lo_v) * np.linspace(0.0, 1.0, 33)
                line = np.column_stack([v, np.full(33, fixed)] if across else [np.full(33, fixed), v])
                on = v[al_layout.contains(outline, line)]
                if len(on) < 2:
                    continue
                ctrl = [(s.lens_x + edge[b] + ox, (lo_v + (hi_v - lo_v) * fraction[b] if across else fixed) + oy,
                         (fixed if across else lo_v + (hi_v - lo_v) * fraction[b]) + oz)
                        for edge in (mine, theirs) for b in range(DEGREE + 1)]
                wall = {"degree_u": 1, "degree_v": DEGREE, "knots_u": [0.0, 0.0, 1.0, 1.0],
                        "knots_v": [lo_v] * (DEGREE + 1) + [hi_v] * (DEGREE + 1), "num_u": 2, "num_v": DEGREE + 1,
                        "points": [round(float(c), 8) for p in ctrl for c in p]}
                face = {"type": "trimmed_surface", "surface": wall, "label": f"lens wall {i}.{j}|{ni}.{nj}"}
                if on[0] > lo_v or on[-1] < hi_v:                           # the outline ends the wall
                    face["outer"] = [_loop(np.array([[0.0, on[0]], [1.0, on[0]], [1.0, on[-1]], [0.0, on[-1]]]))]
                out.append(("wall", f"Lens wall {i}.{j}|{ni}.{nj}", face))
    return out
