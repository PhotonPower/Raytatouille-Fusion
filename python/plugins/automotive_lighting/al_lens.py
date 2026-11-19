"""A headlamp or signal lamp with a patterned lens: a paraboloid mirror and, in front of it, a lens
whose inner side is a grid of spreading elements (prisms, cylinder lenses, pillows).

Every cell of the grid turns the light that reaches it: its middle by (deflect H, deflect V), its
borders by ± the spread more – running linearly across the cell, its left part to the left, its
upper part upwards; with a spread angle φ the two spreads are turned by φ on the screen: a
cylinder lens whose axis is turned so, that spreads the light along the line rising by φ (as the
facets of a clear-lens reflector lay their filament images along the cut-off). A cell with
neither is plane glass. For a point of the cell, the ray that comes
from the filament centre by way of the mirror (direction d) is to leave the lens in the direction t,
d turned by these angles. The outer side of the lens is a plane; the direction g inside the glass follows from t by
refraction there, and the inner surface must have the normal

    N ∝ d − n g          (Snell's law in vector form, n: refractive index),

which gives its slopes ∂x/∂y and ∂x/∂z; they are integrated over the cell (through its centre) and
the cell's surface is the Bézier patch of degree 5 closest to that. The cells are independent:
between neighbours a step remains, closed by a wall along X. A ray that meets a wall – in the air
before the elements or in the glass behind them – is mirrored there once (with the glass' reflectance
at that angle, or totally) and goes on as stray light. With a draft angle the walls lean and are
rounded at foot and head (_join): then they are part of the inner surface and refract like it.

Sectors (radial sections about the lamp axis, as the zones of a clear-lens reflector) cut the
cells along radial lines: each part of a cell in a sector is an element of its own – its patch
designed over the whole cell, used in its part, the step to its neighbour a wall along the radial
line. Where the light of a cell ends at different branches of the cut-off on either side of such
a line (the wedge in front of the H4 shield's slanting edge), each part can follow its own.

The lens may lean back (rake), run back to one side (sweep) and be domed (a sphere's radius): its
outer side is that shape, its inner side the same shape `thickness` behind it (measured along X)
with the elements on it. The refraction at the outer side then uses the normal of the shape there.

Strips (structure STRIPS): instead of the grid of cells, cylinder lenses that run through their
sector – `pitch` wide, upright where the sector's light ends at the horizontal branch, leaning by
the rise (15°) where it ends at the rising one (their cylinders then spread along the rise), as the
flutes of a classic headlamp lens. Along a strip (w = y sin φ + z cos φ, φ its lean) its segments
(`segment` long, one centred on the lamp axis; 0: the strip in one piece) are its elements: the
element table's row that holds the segment's middle in (t, w), t = y cos φ − z sin φ across the
strips. A segment's prism may be its own, the cylinder (spread and lean) is the strip's – the
optimiser keeps it so: the cylinder lenses run through, the prisms make steps between segments.
A segment's slopes are integrated along the strip's middle and then across it, its surface the
B-spline (degree 5 across, cubic along) closest to that; a segment that is like the one before it
(no prism along the strip) goes on from it without a step.

Coordinates as everywhere in the plugin: origin = filament centre, +X the driving direction, +Y
left, +Z up. NumPy only."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

import al_layout
import al_spline
from al_design import DesignError
from al_optics import HORIZONTAL, RISING, Cutoff, Filament, Lamp, direction
from al_spline import Graph

DEGREE = 5
NODES = 15             # per direction: where a cell's slopes are computed
CELLS, STRIPS = "cells", "strips"      # the lens' structure
STRIP_SPAN = 8.0       # mm: the spans of a strip's B-spline along it
STRIP_STEP = 1.0       # mm: where its slopes are computed along it (at most this far apart)


@dataclass(frozen=True)
class Element:
    """What the cells whose centre lies in y0 … y1, z0 … z1 do (degrees): by how much the light is
    turned in the cell's middle, and the half spread horizontally and vertically – both turned by
    `spread_angle` (counter-clockwise on the screen, as the driver sees it): a cylinder lens
    (spread_v 0) spreads the light along the line that rises by that angle."""

    y0: float
    y1: float
    z0: float
    z1: float
    deflect_h: float = 0.0
    deflect_v: float = 0.0
    spread_h: float = 0.0
    spread_v: float = 0.0
    spread_angle: float = 0.0
    sector: int = -1               # the lens' sector (index by azimuth) whose parts it is for; -1: every one

    def offsets(self, a, b, width: float, height: float):
        """The turn (H, V degrees) besides the deflection at points of the cell – a to the right, b
        up from its middle (mm) – of a cell width x height: the spreads run linearly along their
        directions and reach ± their value at the cell's farthest corner."""
        phi = math.radians(self.spread_angle)
        c, s = math.cos(phi), math.sin(phi)
        a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        u, w = a * c + b * s, -a * s + b * c
        along = self.spread_h * u / (0.5 * width * abs(c) + 0.5 * height * abs(s))
        across = self.spread_v * w / (0.5 * width * abs(s) + 0.5 * height * abs(c))
        return along * c - across * s, along * s + across * c


@dataclass(frozen=True)
class Sector:
    """A radial section of the lens from azimuth atan2(z, y) `az_from` (degrees, counter-clockwise
    seen in the driving direction: 0 = left, 90 = up) to the next sector's, and the cut-off branch
    its light ends at."""

    az_from: float
    branch: str = HORIZONTAL


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
    wall_draft: float = 0.0        # degrees between the walls of the elements and X (0: walls along X)
    wall_fillet: float = 0.0       # mm, radius at the foot and the head of these walls (with a draft only)
    sectors: tuple[Sector, ...] = ()   # radial sections (at least two to cut the cells; else one)
    structure: str = CELLS         # CELLS: a grid of cells; STRIPS: cylinder lenses through each sector
    pitch: float = 5.0             # mm: the strips' width
    segment: float = 10.0          # mm: the strips' segments, each an element of its own (0: a strip in one)


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


def fresnel(cos_in, n_from: float, n_to: float) -> np.ndarray:
    """Reflectance of a smooth surface for unpolarised light arriving with the cosine `cos_in` to
    the normal, from the index n_from into n_to (1 where the reflection is total)."""
    cos_in = np.asarray(cos_in, dtype=float)
    sin2 = (n_from / n_to) ** 2 * (1.0 - cos_in * cos_in)
    cos_out = np.sqrt(np.maximum(1.0 - sin2, 0.0))
    rs = ((n_from * cos_in - n_to * cos_out) / np.maximum(n_from * cos_in + n_to * cos_out, 1e-300)) ** 2
    rp = ((n_from * cos_out - n_to * cos_in) / np.maximum(n_from * cos_out + n_to * cos_in, 1e-300)) ** 2
    return np.where(sin2 >= 1.0, 1.0, 0.5 * (rs + rp))


@dataclass
class LensSystem:
    settings: LensSettings
    frame: np.ndarray              # outline of mirror and lens in the front view (y, z)
    filament: Filament
    y0: float = 0.0                # the grid of cells: first edges and numbers
    z0: float = 0.0
    ny: int = 0
    nz: int = 0
    coeff: np.ndarray = field(default_factory=lambda: np.zeros((0, 0, 1, DEGREE + 1, DEGREE + 1)))   # sag, Bernstein,
    used: np.ndarray = field(default_factory=lambda: np.zeros((0, 0, 1), dtype=bool))  # per cell and sector
    whole: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))   # cells the outline does not cut
    fit_error: float = 0.0         # largest slope error of the patches against the wanted slopes
    sag: tuple[float, float] = (0.0, 0.0)     # the elements' depth and height about the lens' shape
    column_bands: dict = field(default_factory=dict)   # (i, j): the wall between the cells i - 1 and i of the row j
    row_bands: dict = field(default_factory=dict)      # j: the walls between the rows j - 1 and j
    warnings: list[str] = field(default_factory=list)
    # STRIPS: segment j (along, from (j + strip_j0 - 0.5) segment) of strip i (across, m = i + strip_m0:
    # from (m - 0.5) pitch to (m + 0.5) pitch) of sector k is the cell (i, j, k) of used; its surface's
    # coefficients (Bernstein across, B-spline along)
    strip_m0: int = 0
    strip_j0: int = 0
    strip_coeff: dict = field(default_factory=dict)    # (i, j, k): (DEGREE + 1, n)
    strip_knots: dict = field(default_factory=dict)    # (j, k): the knots along the segments j of sector k (w, mm)
    tilts: np.ndarray = field(default_factory=lambda: np.zeros(1))   # degrees: the strips' lean per sector

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

    def element(self, y: float, z: float, sector: int = 0) -> Element | None:
        return next((e for e in self.settings.elements if e.y0 <= y < e.y1 and e.z0 <= z < e.z1
                     and e.sector in (-1, sector)), None)

    # ---- the sectors
    @property
    def bounds(self) -> np.ndarray:
        """The sectors' first azimuths (degrees, 0 … 360, rising); empty: one sector."""
        if not hasattr(self, "_bounds"):
            a = sorted(float(x.az_from) % 360.0 for x in self.settings.sectors)
            self._bounds = np.array(a if len(a) >= 2 else [])
        return self._bounds

    @property
    def count(self) -> int:
        """How many sectors."""
        return max(len(self.bounds), 1)

    def branch(self, k: int) -> str:
        """The cut-off branch of sector k."""
        if not len(self.bounds):
            return HORIZONTAL
        rows = sorted(self.settings.sectors, key=lambda x: float(x.az_from) % 360.0)
        return rows[k].branch

    def sector(self, y, z) -> np.ndarray:
        """The sector of points (index by azimuth: k from bounds[k] to bounds[k + 1])."""
        y, z = np.asarray(y, dtype=float), np.asarray(z, dtype=float)
        if not len(self.bounds):
            return np.zeros(np.shape(y), dtype=int)
        az = np.degrees(np.arctan2(z, y)) % 360.0
        k = np.searchsorted(self.bounds, az, side="right") - 1
        return np.where(k < 0, len(self.bounds) - 1, k)

    def sector_pieces(self, polys: list[np.ndarray], k: int) -> list[np.ndarray]:
        """The parts of polygons (y, z) in sector k: between the radial lines at its azimuths."""
        if not len(self.bounds):
            return polys
        a0, a1 = self.bounds[k], self.bounds[(k + 1) % len(self.bounds)]
        span = (a1 - a0) % 360.0 or 360.0
        n = math.ceil(span / 180.0 - 1e-9)
        out = []
        for m in range(n):              # in pieces of at most 180°: two half planes each
            lo, hi = math.radians(a0 + span * m / n), math.radians(a0 + span * (m + 1) / n)
            part = al_layout.clip_all(polys, al_layout.Line(np.array([-math.sin(lo), math.cos(lo)]), 0.0))
            out += al_layout.clip_all(part, al_layout.Line(np.array([math.sin(hi), -math.cos(hi)]), 0.0))
        return [q for q in out if abs(al_layout.area(q)) > 1e-9]

    def sector_region(self, polys: list[np.ndarray], k: int) -> list[np.ndarray]:
        """The parts of polygons (y, z) in sector k, in one piece where they are (a wedge's clip)."""
        if not len(self.bounds):
            return polys
        curve = al_layout.sector_curve(self.bounds[k], self.bounds[(k + 1) % len(self.bounds)])
        out = polys if curve is None else al_layout.clip_all(polys, curve)
        return [q for q in out if abs(al_layout.area(q)) > 1e-9]

    # ---- the strips
    @property
    def strips(self) -> bool:
        return self.settings.structure == STRIPS

    def tilt(self, k: int) -> float:
        """Degrees: how far the strips of sector k lean – those whose light ends at the rising branch
        by the rise (their cylinders spread along it), the others not at all."""
        return math.degrees(math.atan(self.settings.cutoff.slope)) if self.branch(k) == RISING else 0.0

    def turned(self, y, z, k):
        """(t, w, cos φ, sin φ) of points in their sectors' (k) strip coordinates: t across the strips
        (to the left where they stand upright), w along them (upwards); φ the strips' lean."""
        phi = np.radians(self.tilts[np.asarray(k)])
        c, s = np.cos(phi), np.sin(phi)
        return y * c - z * s, y * s + z * c, c, s

    def strip_band(self, i: int, k: int, polys: list[np.ndarray], j: int | None = None) -> list[np.ndarray]:
        """The parts of polygons (y, z) on strip i of sector k (its band across, whatever the sector) –
        on its segment j if given."""
        p, L = self.settings.pitch, self.settings.segment
        m = i + self.strip_m0
        phi = math.radians(float(self.tilts[k]))
        c, s = math.cos(phi), math.sin(phi)
        out = al_layout.clip_all(polys, al_layout.Line(np.array([c, -s]), (m - 0.5) * p))
        out = al_layout.clip_all(out, al_layout.Line(np.array([-c, s]), -(m + 0.5) * p))
        if j is not None and L > 0.0:
            n = j + self.strip_j0
            out = al_layout.clip_all(out, al_layout.Line(np.array([s, c]), (n - 0.5) * L))
            out = al_layout.clip_all(out, al_layout.Line(np.array([-s, -c]), -(n + 0.5) * L))
        return [q for q in out if abs(al_layout.area(q)) > 1e-12]

    def strip_index(self, t: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(i, j): the strip and its segment at points (t, w) (outside the lens' ranges too)."""
        L = self.settings.segment
        i = np.floor(t / self.settings.pitch + 0.5).astype(int) - self.strip_m0
        j = np.floor(w / L + 0.5).astype(int) - self.strip_j0 if L > 0.0 else np.zeros_like(i)
        return i, j

    def strip_at(self, i: int, j: int, k: int, t: np.ndarray, w: np.ndarray, slopes: bool = True):
        """x - lens_x of segment j of strip i of sector k at points (t, w) – and its slopes along t, w."""
        p = self.settings.pitch
        C = self.strip_coeff[(i, j, k)]
        knots = self.strip_knots[(j, k)]
        n = C.shape[1]
        a = (t - (i + self.strip_m0 - 0.5) * p) / p
        M = _bernstein(a) @ C
        Bw = al_spline.basis_matrix(knots, n, 3, w)
        sag = np.sum(M * Bw, axis=1)
        if not slopes:
            return sag
        dt = np.sum((DEGREE * _bernstein(a, DEGREE - 1) @ (C[1:] - C[:-1]) / p) * Bw, axis=1)
        dw = np.sum(M * al_spline.basis_matrix(knots, n, 3, w, deriv=1), axis=1)
        return sag, dt, dw

    def _strip_patch(self, y: np.ndarray, z: np.ndarray):
        k = self.sector(y, z)
        t, w, c, s = self.turned(y, z, k)
        iy, iz = self.strip_index(t, w)
        inside = (iy >= 0) & (iy < self.ny) & (iz >= 0) & (iz < self.nz)
        iy, iz = np.clip(iy, 0, self.ny - 1), np.clip(iz, 0, self.nz - 1)
        inside &= self.used[iy, iz, k]
        sag, dt, dw = np.zeros(len(y)), np.zeros(len(y)), np.zeros(len(y))
        rows = np.flatnonzero(inside)
        key = (iy[rows] * self.nz + iz[rows]) * self.count + k[rows]
        order = np.argsort(key, kind="stable")
        rows, key = rows[order], key[order]
        cuts = np.flatnonzero(np.diff(key)) + 1
        for part in np.split(np.arange(len(rows)), cuts):
            if not len(part):
                continue
            r = rows[part]
            q = int(key[part[0]])
            sag[r], dt[r], dw[r] = self.strip_at(q // (self.nz * self.count), (q // self.count) % self.nz,
                                                 q % self.count, t[r], w[r])
        return sag, dt * c + dw * s, -dt * s + dw * c, inside, np.zeros(len(y), dtype=bool)

    def inner(self, y: np.ndarray, z: np.ndarray):
        """x - lens_x of the inner side and its slopes at points; `inside` marks the points that lie
        on a cell. With drafted walls: the elements' patches, and near the cells' borders the bands
        that join them (those between the rows first)."""
        sag, dy, dz, inside, whole = self.patch(y, z)
        if not self.column_bands and not self.row_bands:
            return sag, dy, dz, inside, whole
        s = self.settings
        sag, dy, dz = sag.copy(), dy.copy(), dz.copy()
        self.on_band = np.zeros(len(sag), dtype=bool)
        j = np.rint((z - self.z0) / s.cell_height).astype(int)              # the nearest border between rows
        offset = z - (self.z0 + j * s.cell_height)
        for key in np.unique(j):
            band = self.row_bands.get(int(key))
            if band is None:
                continue
            rows = np.flatnonzero((j == key) & (np.abs(offset) <= band.half_width)
                                  & (y >= band.graph.knots_p[0]) & (y <= band.graph.knots_p[-1]))
            if len(rows):
                sag[rows], dy[rows], dz[rows] = band.graph.evaluate(y[rows], offset[rows])
                self.on_band[rows] = True
        i = np.rint((y - self.y0) / s.cell_width).astype(int)               # the nearest border between columns
        offset = y - (self.y0 + i * s.cell_width)
        row = np.floor((z - self.z0) / s.cell_height).astype(int)
        keys = i * 100003 + row
        for key in np.unique(keys[~self.on_band]):
            band = self.column_bands.get((int(key // 100003), int(key % 100003)))
            if band is None:
                continue
            rows = np.flatnonzero((keys == key) & ~self.on_band & (np.abs(offset) <= band.half_width))
            if len(rows):
                f, fu, fxi = band.graph.evaluate(-z[rows], offset[rows])      # the band's u runs along -z
                sag[rows], dy[rows], dz[rows] = f, fxi, -fu
                self.on_band[rows] = True
        return sag, dy, dz, inside, whole

    def patch(self, y: np.ndarray, z: np.ndarray):
        """x - lens_x of the cells' own surfaces (the lens' shape with the elements on it) and their
        slopes at points; `inside` marks the points that lie on a cell."""
        if self.strips:
            return self._strip_patch(np.asarray(y, dtype=float), np.asarray(z, dtype=float))
        s = self.settings
        iy = np.floor((y - self.y0) / s.cell_width).astype(int)
        iz = np.floor((z - self.z0) / s.cell_height).astype(int)
        inside = (iy >= 0) & (iy < self.ny) & (iz >= 0) & (iz < self.nz)
        iy, iz = np.clip(iy, 0, self.ny - 1), np.clip(iz, 0, self.nz - 1)
        k = self.sector(y, z)
        inside &= self.used[iy, iz, k]
        ta = (y - self.y0) / s.cell_width - iy
        tb = (z - self.z0) / s.cell_height - iz
        C = self.coeff[iy, iz, k]                                          # (n, 6, 6)
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
        """Indices of the cell at points and whether it (its part there) is one of the lens."""
        iy, iz, _, inside = self.part(y, z)
        return iy, iz, inside

    def part(self, y, z):
        """Indices of the cell and the sector at points and whether that part is one of the lens
        (strips: the strip's index i, its segment's j, the sector)."""
        s = self.settings
        k = self.sector(y, z)
        if self.strips:
            t, w, _, _ = self.turned(y, z, k)
            iy, iz = self.strip_index(t, w)
            inside = (iy >= 0) & (iy < self.ny) & (iz >= 0) & (iz < self.nz)
            return iy, iz, k, inside & self.used[np.clip(iy, 0, self.ny - 1), np.clip(iz, 0, self.nz - 1), k]
        iy = np.floor((y - self.y0) / s.cell_width).astype(int)
        iz = np.floor((z - self.z0) / s.cell_height).astype(int)
        inside = (iy >= 0) & (iy < self.ny) & (iz >= 0) & (iz < self.nz)
        return iy, iz, k, inside & self.used[np.clip(iy, 0, self.ny - 1), np.clip(iz, 0, self.nz - 1), k]

    def _wall(self, start: np.ndarray, v: np.ndarray, end_yz: tuple, in_air: bool):
        """Whether straight paths from `start` (n, 3) along v to the points end_yz meet a wall between
        two elements: where a path passes from one cell to its neighbour it must still be in the air
        before both surfaces (in_air) or already in the glass behind both. Returns the mask, the
        points on the walls (n, 3) and the walls' unit normals (n, 3; 0 where a path crosses a
        corner, a whole cell or a sector's line)."""
        s = self.settings
        ia, ja, ka, used_a = self.part(start[:, 1], start[:, 2])
        ib, jb, kb, used_b = self.part(*end_yz)
        other = (ka != kb) if self.strips else np.zeros(len(ia), dtype=bool)      # (strips: another sector's)
        moved = ((ia != ib) | (ja != jb) | other) & used_a & used_b
        hit = moved & (((np.abs(ia - ib) + np.abs(ja - jb)) > 1) | other)        # across a corner, a whole cell
        where = np.zeros((len(hit), 3))
        normal = np.zeros((len(hit), 3))
        if self.strips:          # across the border between two strips of a sector, or two segments
            phi = np.radians(self.tilts[ka])
            zero = np.zeros(len(hit))
            groups = ((ia, ib, (self.strip_m0 - 0.5) * s.pitch, s.pitch,
                       np.stack([zero, np.cos(phi), -np.sin(phi)], axis=1)),                # along t
                      (ja, jb, (self.strip_j0 - 0.5) * s.segment, s.segment,
                       np.stack([zero, np.sin(phi), np.cos(phi)], axis=1)))                 # along w
        else:
            groups = ((ia, ib, self.y0, s.cell_width, np.array([0.0, 1.0, 0.0])),
                      (ja, jb, self.z0, s.cell_height, np.array([0.0, 0.0, 1.0])))
        for a, b, first, size, axis in groups:
            rows = np.flatnonzero(moved & ~hit & (a != b))
            if not len(rows):
                continue
            axes_rows = np.broadcast_to(axis, (len(hit), 3))[rows] if axis.ndim == 1 else axis[rows]
            border = first + np.maximum(a[rows], b[rows]) * size
            along = np.sum(v[rows] * axes_rows, axis=1)
            tau = (border - np.sum(start[rows] * axes_rows, axis=1)) / np.where(along != 0.0, along, 1.0)
            point = start[rows] + tau[:, None] * v[rows]
            side = (np.where(b[rows] > a[rows], 1.0, -1.0) * 1e-7 * size)[:, None] * axes_rows   # just beyond the border
            before, behind = point - side, point + side
            x = point[:, 0] - s.lens_x
            h0, h1 = self.inner(before[:, 1], before[:, 2])[0], self.inner(behind[:, 1], behind[:, 2])[0]
            met = (x > np.minimum(h0, h1) - 1e-9) if in_air else (x < np.maximum(h0, h1) + 1e-9)
            hit[rows] = met
            where[rows[met]] = point[met]
            normal[rows[met]] = axes_rows[met]
        return hit, where, normal

    def _leave(self, x_in, y, z, glass):
        """From points in the glass along `glass` to the outer side and out: directions, passed."""
        s = self.settings
        gx = np.where(glass[:, 0] > 1e-6, glass[:, 0], 1.0)
        tg = s.thickness / gx
        for _ in range(3):
            ox, oy, oz = self.shape(y + tg * glass[:, 1], z + tg * glass[:, 2])
            tg = (s.lens_x + s.thickness + ox - x_in) / gx
        outer = np.stack([np.ones_like(oy), -oy, -oz], axis=1)
        outer /= np.linalg.norm(outer, axis=1, keepdims=True)
        out, ok = refract(glass, outer, s.index)
        return out, ok & (glass[:, 0] > 1e-6) & (tg > 0.0)

    def _pass(self, origins: np.ndarray, d: np.ndarray):
        """One way through the lens without regard to walls: the directions behind it, which rays
        pass, and for the walls: (mask, points, axes) met in the air and in the glass, and the
        directions in the glass."""
        s = self.settings
        forward = d[:, 0] > 1e-6
        dx = np.where(forward, d[:, 0], 1.0)
        t = np.maximum((s.lens_x - origins[:, 0]) / dx, 0.0)                 # (a ray mirrored at a wall starts
        for _ in range(3):                                                  # among the elements) onto the shape …
            y, z = origins[:, 1] + t * d[:, 1], origins[:, 2] + t * d[:, 2]
            t = np.maximum((s.lens_x + self.shape(y, z)[0] - origins[:, 0]) / dx, 0.0)
        banded = bool(self.column_bands or self.row_bands)
        for _ in range(4 if banded else 2):                                 # … and onto the elements
            y, z = origins[:, 1] + t * d[:, 1], origins[:, 2] + t * d[:, 2]
            sag, dy, dz, inside, whole = self.inner(y, z)
            if banded:       # Newton: a drafted wall is steep, the plain step would overshoot there
                miss = origins[:, 0] + t * dx - s.lens_x - sag
                rate = dx - dy * d[:, 1] - dz * d[:, 2]
                t_before, t = t, np.maximum(t - miss / np.where(np.abs(rate) > 0.05, rate, dx), 0.0)
            else:
                t_before, t = t, np.maximum((s.lens_x + sag - origins[:, 0]) / dx, 0.0)
        if banded:
            y, z = origins[:, 1] + t * d[:, 1], origins[:, 2] + t * d[:, 2]
            sag, dy, dz, inside, whole = self.inner(y, z)
        normal = np.stack([np.ones_like(dy), -dy, -dz], axis=1)
        normal /= np.linalg.norm(normal, axis=1, keepdims=True)
        glass, ok1 = refract(d, normal, 1.0 / s.index)
        x_in = s.lens_x + sag
        out, ok2 = self._leave(x_in, y, z, glass)
        ok = forward & inside & ok1 & ok2
        cut = np.flatnonzero(ok & ~whole)                                   # only cells at the rim need the outline
        if len(cut):
            ok[cut] = al_layout.contains(self._outline, np.column_stack([y[cut], z[cut]]))
        if banded:           # the walls are part of the surface: what lies on a band is the walls' light
            none = (np.zeros(len(ok), dtype=bool), np.zeros((len(ok), 3)), np.zeros((len(ok), 3)))
            return out, ok, (self.on_band.copy(), none[1], none[2]), none, glass
        # walls: the path in the air from where the elements begin, and in the glass to where they end.
        # A ray that finds no surface point in one cell – the point it is sent to lies in the next
        # one, whose surface lies elsewhere – runs into the wall between the two on its way there.
        form = s.lens_x + self.shape(y, z)[0]
        hit = np.column_stack([x_in, y, z])
        front = np.maximum(np.minimum((form + self.sag[0] - 0.01 - origins[:, 0]) / dx, np.minimum(t, t_before)), 0.0)
        far = np.maximum(t, t_before)
        air = self._wall(origins + front[:, None] * d, d,
                         (origins[:, 1] + far * d[:, 1], origins[:, 2] + far * d[:, 2]), True)
        ia, ja, ka, _ = self.part(y, z)
        ib, jb, kb, _ = self.part(origins[:, 1] + t * d[:, 1], origins[:, 2] + t * d[:, 2])
        air = (air[0] | (ia != ib) | (ja != jb) | (ka != kb), air[1], air[2])
        gx = np.where(glass[:, 0] > 1e-6, glass[:, 0], 1.0)
        on = np.maximum(form + self.sag[1] + 0.01 - x_in, 0.0) / gx
        in_glass = self._wall(hit, glass, (y + on * glass[:, 1], z + on * glass[:, 2]), False)
        return out, ok, air, in_glass, glass

    def through(self, origins: np.ndarray, d: np.ndarray, transmittance: float = 1.0):
        """Rays (origins (n, 3), unit directions (n, 3)) through the lens: the directions behind it,
        a factor per ray and which rays met a wall between two elements. The factor is
        `transmittance`; 0 for a ray that misses the lens or is totally reflected at its outer side.
        A ray that meets a wall is mirrored there once – from the air with the reflectance of the
        glass at that angle, in the glass totally or with its reflectance – and goes on as stray
        light; what enters or leaves through the wall is lost."""
        s = self.settings
        out, ok, air, in_glass, glass = self._pass(origins, d)
        wall = (air[0] | in_glass[0]) & ok
        if self.column_bands or self.row_bands:      # drafted walls refract like the rest of the surface
            return out, np.where(ok, transmittance, 0.0), wall
        factor = np.where(ok & ~wall, transmittance, 0.0)
        rows = np.flatnonzero(wall & air[0] & np.any(air[2] != 0.0, axis=1))   # mirrored in the air, then through
        if len(rows):
            n = air[2][rows]
            cos = np.sum(d[rows] * n, axis=1)
            mirrored = d[rows] - 2.0 * cos[:, None] * n
            share = fresnel(np.abs(cos), 1.0, s.index)
            again, passed, air2, glass2, _ = self._pass(air[1][rows] + 1e-6 * mirrored, mirrored)
            passed &= ~air2[0] & ~glass2[0]
            out[rows[passed]] = again[passed]
            factor[rows[passed]] = transmittance * share[passed]
        rows = np.flatnonzero(wall & ~air[0] & np.any(in_glass[2] != 0.0, axis=1))   # mirrored in the glass, then out
        if len(rows):
            n = in_glass[2][rows]
            cos = np.sum(glass[rows] * n, axis=1)
            mirrored = glass[rows] - 2.0 * cos[:, None] * n
            share = fresnel(np.abs(cos), s.index, 1.0)
            point = in_glass[1][rows]
            again, passed = self._leave(point[:, 0], point[:, 1], point[:, 2], mirrored)
            out[rows[passed]] = again[passed]
            factor[rows[passed]] = transmittance * share[passed]
        return out, factor, wall

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
    if s.structure == STRIPS:
        if s.pitch <= 0.0:
            raise DesignError("the strips need a width")
        if s.wall_draft > 0.0:
            raise DesignError("walls with a draft angle and strips together are not supported yet: set the draft "
                              "angle to 0 or choose cells")
        _build_strips(system, progress)
        if s.thickness + system.sag[0] < 0.3:
            raise DesignError(f"the strips are {-system.sag[0]:.1f} mm deep, more than the lens is thick "
                              f"({s.thickness:g} mm) – a thicker lens, narrower strips or less deflection")
        return system
    # cells: one is centred on the lamp axis
    i0, i1 = math.floor(lo[0] / s.cell_width + 0.5), math.floor(hi[0] / s.cell_width + 0.5)
    j0, j1 = math.floor(lo[1] / s.cell_height + 0.5), math.floor(hi[1] / s.cell_height + 0.5)
    system.y0, system.z0 = (i0 - 0.5) * s.cell_width, (j0 - 0.5) * s.cell_height
    system.ny, system.nz = i1 - i0 + 1, j1 - j0 + 1
    S = system.count
    if S > 1 and s.wall_draft > 0.0:
        raise DesignError("walls with a draft angle and lens sectors together are not supported yet: set the draft "
                          "angle to 0 or leave the sector table empty")
    system.coeff = np.zeros((system.ny, system.nz, S, DEGREE + 1, DEGREE + 1))
    system.used = np.zeros((system.ny, system.nz, S), dtype=bool)
    system.whole = np.zeros((system.ny, system.nz), dtype=bool)
    t = np.linspace(0.0, 1.0, NODES)
    fit = np.linalg.pinv(_bernstein(t))                                    # values at the nodes -> coefficients
    B = _bernstein(t)
    low = _bernstein(t, DEGREE - 1)
    KRON = np.kron(B, B)                                                   # node (a, b) <- coefficient (p, q)
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
            Y, Z = np.meshgrid(ya + t * s.cell_width, za + t * s.cell_height, indexing="ij")
            arrive = system.chief(Y, Z)
            base, base_y, base_z = system.shape(Y, Z)
            outer = np.stack([np.ones_like(base_y), -base_y, -base_z], axis=-1)
            outer /= np.linalg.norm(outer, axis=-1, keepdims=True)
            parts = [(0, corners[4], (s.cell_width, s.cell_height), np.ones((NODES, NODES), dtype=bool))]
            if S > 1:                                                       # the cell's parts in the sectors
                parts = []
                at = system.sector(Y, Z)
                for k in range(S):
                    pieces = system.sector_pieces([corners[:4]], k)
                    if sum(al_layout.area(q) for q in pieces) < 1e-6 * s.cell_width * s.cell_height:
                        continue
                    pts = np.vstack(pieces)
                    lo_, hi_ = pts.min(axis=0), pts.max(axis=0)
                    mask = at == k
                    if not mask.any():                                      # a sliver between the nodes
                        mask = np.zeros_like(mask)
                        mask[np.unravel_index(np.argmin(np.hypot(Y - 0.5 * (lo_[0] + hi_[0]), Z - 0.5 * (lo_[1] + hi_[1]))),
                                              mask.shape)] = True
                    parts.append((k, 0.5 * (lo_ + hi_), tuple(np.maximum(hi_ - lo_, 1e-3)), mask))
            for k, centre, (width, height), mask in parts:
                e = system.element(ya + 0.5 * s.cell_width, za + 0.5 * s.cell_height, k)
                if e is None:
                    without += 1
                    e = Element(0, 0, 0, 0)
                # y runs to the left: the part's left side turns its light to the left
                turn_h, turn_v = e.offsets(np.clip(centre[0] - Y, -0.5 * width, 0.5 * width),
                                           np.clip(Z - centre[1], -0.5 * height, 0.5 * height), width, height)
                H = np.degrees(np.arctan(-arrive[..., 1] / arrive[..., 0])) + e.deflect_h + turn_h
                V = np.degrees(np.arctan(arrive[..., 2] / arrive[..., 0])) + e.deflect_v + turn_v
                want = direction(np.tan(np.radians(H)), np.tan(np.radians(V)))
                # the direction in the glass: the wanted ray followed backwards through the outer side
                back, _ = refract(-want.reshape(-1, 3), -outer.reshape(-1, 3), 1.0 / s.index)
                glass = -back.reshape(want.shape)
                normal = arrive - s.index * glass
                if np.any(normal[..., 0][mask] >= -1e-6):
                    raise DesignError(f"the lens element at y = {centre[0]:.0f}, z = {centre[1]:.0f} mm cannot bend "
                                      "the light that far – reduce its deflection or spread")
                nx = np.where(normal[..., 0] < -1e-6, normal[..., 0], -1e-6)
                sy, sz = -normal[..., 1] / nx, -normal[..., 2] / nx
                # the element on the lens' shape: its slopes along y through the part's centre, then along z
                ey, ez = sy - base_y, sz - base_z
                da, db = s.cell_width / (NODES - 1), s.cell_height / (NODES - 1)
                ma = int(np.clip(np.rint((centre[0] - ya) / da), 0, NODES - 1))
                mb = int(np.clip(np.rint((centre[1] - za) / db), 0, NODES - 1))
                line = np.concatenate([[0.0], np.cumsum(0.5 * (ey[1:, mb] + ey[:-1, mb]) * da)])
                up = np.concatenate([np.zeros((NODES, 1)), np.cumsum(0.5 * (ez[:, 1:] + ez[:, :-1]) * db, axis=1)],
                                    axis=1)
                sag = line[:, None] + up - up[:, mb:mb + 1]
                sag -= sag[ma, mb]
                sag_lo, sag_hi = min(sag_lo, float(sag[mask].min())), max(sag_hi, float(sag[mask].max()))
                if mask.all():
                    C = fit @ (base + sag) @ fit.T
                else:            # a part: fitted where it is, the rest of the cell only held loosely
                    w = np.where(mask, 1.0, 1e-2).ravel()
                    C = np.linalg.lstsq(w[:, None] * KRON, w * (base + sag).ravel(), rcond=None)[0].reshape(B.shape[1], -1)
                system.coeff[i, j, k], system.used[i, j, k] = C, True
                fy = DEGREE * (low @ (C[1:] - C[:-1]) @ B.T) / s.cell_width
                fz = DEGREE * (B @ (C[:, 1:] - C[:, :-1]) @ low.T) / s.cell_height
                system.fit_error = max(system.fit_error, float(np.abs(fy - sy)[mask].max()),
                                       float(np.abs(fz - sz)[mask].max()))
    if not system.used.any():
        raise DesignError("the lens has no cell within the frame")
    if without:
        system.warnings.append(f"{without} cells (or their parts) lie in no row of the element table: they are plane")
    system.sag = (sag_lo, sag_hi)
    if s.wall_draft > 0.0:
        _join(system, progress)
    if s.thickness + system.sag[0] < 0.3:
        raise DesignError(f"the lens elements are {-system.sag[0]:.1f} mm deep, more than the lens is thick "
                          f"({s.thickness:g} mm) – a thicker lens, smaller cells or less deflection")
    return system


def _build_strips(system: LensSystem, progress=None) -> None:
    """The strips of every sector (STRIPS): across the sector's part of the frame, `pitch` wide, one
    centred on the lamp axis; along them their segments, each designed over its length (the
    sector's whole length for a strip in one piece), used where it is."""
    s = system.settings
    p, L, S = s.pitch, s.segment, system.count
    system.tilts = np.array([system.tilt(k) for k in range(S)])
    pieces = {k: system.sector_region([system.frame], k) for k in range(S)}
    reach = {}
    for k, polys in pieces.items():
        if not polys:
            continue
        pts = np.vstack(polys)
        t, w, _, _ = system.turned(pts[:, 0], pts[:, 1], np.full(len(pts), k))
        reach[k] = (math.floor(t.min() / p + 0.5), math.floor(t.max() / p + 0.5), float(w.min()) - 0.5,
                    float(w.max()) + 0.5)
    if not reach:
        raise DesignError("the lens has no strip within the frame")
    system.strip_m0 = min(r[0] for r in reach.values())
    system.ny = max(r[1] for r in reach.values()) - system.strip_m0 + 1
    if L > 0.0:
        system.strip_j0 = min(math.floor(r[2] / L + 0.5) for r in reach.values())
        system.nz = max(math.floor(r[3] / L + 0.5) for r in reach.values()) - system.strip_j0 + 1
    else:
        system.strip_j0, system.nz = 0, 1
    system.used = np.zeros((system.ny, system.nz, S), dtype=bool)
    system.whole = np.zeros((system.ny, system.nz), dtype=bool)
    a = np.linspace(0.0, 1.0, NODES)
    Ba, low = _bernstein(a), _bernstein(a, DEGREE - 1)
    fit_a = np.linalg.pinv(Ba)
    mid = NODES // 2                                                       # (a = 0.5: the strip's middle)
    without, sag_lo, sag_hi = 0, 0.0, 0.0
    done, total = 0, sum(r[1] - r[0] + 1 for r in reach.values())
    for k, (m_lo, m_hi, w0, w1) in reach.items():
        phi = math.radians(float(system.tilts[k]))
        c, sn = math.cos(phi), math.sin(phi)
        spans = {}                                                         # j: (from, to) along, within the sector
        for j in range(system.nz):
            n_ = j + system.strip_j0
            lo, hi = (max(w0, (n_ - 0.5) * L), min(w1, (n_ + 0.5) * L)) if L > 0.0 else (w0, w1)
            if hi - lo > 1e-6:
                spans[j] = (lo, hi)
        lattice = {}
        for j, (lo, hi) in spans.items():                                  # knots and nodes per segment
            n = max(1, math.ceil((hi - lo) / STRIP_SPAN)) + 3
            knots = al_spline.clamped_uniform_knots(n, 3, lo, hi)
            wn = np.linspace(lo, hi, max(2 * n, math.ceil((hi - lo) / STRIP_STEP) + 1))
            Bw = al_spline.basis_matrix(knots, n, 3, wn)
            lattice[j] = (knots, wn, Bw, al_spline.basis_matrix(knots, n, 3, wn, deriv=1), np.linalg.pinv(Bw))
            system.strip_knots[(j, k)] = knots
        for m in range(m_lo, m_hi + 1):
            done += 1
            if progress is not None:
                progress(done / total, "lens strips …")
            i = m - system.strip_m0
            band = system.strip_band(i, k, pieces[k])
            if sum(abs(al_layout.area(q)) for q in band) < 1e-6 * p * p:
                continue
            before = None                                                  # (element, sag at its upper end) of the last
            for j, (lo, hi) in spans.items():
                knots, wn, Bw, Dw, fit_w = lattice[j]
                part = system.strip_band(i, k, band, j) if L > 0.0 else band
                if sum(abs(al_layout.area(q)) for q in part) < 1e-6 * p * p:
                    before = None
                    continue
                T, W = np.meshgrid((m - 0.5 + a) * p, wn, indexing="ij")     # (NODES, len(wn))
                Y, Z = T * c + W * sn, -T * sn + W * c
                pts = np.column_stack([Y.ravel(), Z.ravel()])
                mask = np.zeros(len(pts), dtype=bool)
                for q in part:
                    mask |= al_layout.contains(q, pts)
                mask = mask.reshape(T.shape)
                if not mask.any():                                          # a sliver between the nodes
                    centre = al_layout.centroid(max(part, key=lambda q: abs(al_layout.area(q))))
                    mask[np.unravel_index(np.argmin(np.hypot(Y - centre[0], Z - centre[1])), mask.shape)] = True
                e = system.element(m * p, (j + system.strip_j0) * L if L > 0.0 else 0.0, k)
                if e is None:
                    without += 1
                    e = Element(0, 0, 0, 0)
                arrive = system.chief(Y, Z)
                base, base_y, base_z = system.shape(Y, Z)
                outer = np.stack([np.ones_like(base_y), -base_y, -base_z], axis=-1)
                outer /= np.linalg.norm(outer, axis=-1, keepdims=True)
                along = e.spread_h * (m * p - T) / (0.5 * p)                # across the strip, to the right
                H = np.degrees(np.arctan(-arrive[..., 1] / arrive[..., 0])) + e.deflect_h + along * c
                V = np.degrees(np.arctan(arrive[..., 2] / arrive[..., 0])) + e.deflect_v + along * sn
                want = direction(np.tan(np.radians(H)), np.tan(np.radians(V)))
                back, _ = refract(-want.reshape(-1, 3), -outer.reshape(-1, 3), 1.0 / s.index)
                normal = arrive + s.index * back.reshape(want.shape)
                if np.any(normal[..., 0][mask] >= -1e-6):
                    raise DesignError(f"the lens strip {m} (sector {k}) cannot bend the light that far – reduce its "
                                      "deflection or spread")
                nx = np.where(normal[..., 0] < -1e-6, normal[..., 0], -1e-6)
                sy, sz = -normal[..., 1] / nx, -normal[..., 2] / nx
                ey, ez = sy - base_y, sz - base_z
                et, ew = ey * c - ez * sn, ey * sn + ez * c                # along t and along w
                # along the strip's middle, then across it
                line = np.concatenate([[0.0], np.cumsum(0.5 * (ew[mid, 1:] + ew[mid, :-1]) * np.diff(wn))])
                across = np.concatenate([np.zeros((1, len(wn))),
                                         np.cumsum(0.5 * (et[1:] + et[:-1]) * (p / (NODES - 1)), axis=0)])
                sag = line[None, :] + across - across[mid:mid + 1]
                # like the segment before (no prism along the strip): on from it; else about its own middle
                optics = (e.deflect_h, e.deflect_v, e.spread_h, e.spread_v, e.spread_angle)
                if before is not None and before[0] == optics and abs(e.deflect_v * c - e.deflect_h * sn) < 0.05:
                    sag += before[1] - sag[mid, 0]
                else:            # (the same place for all strips: alike ones meet without a step)
                    centre = (j + system.strip_j0) * L if L > 0.0 else 0.0
                    sag -= sag[mid, int(np.argmin(np.abs(wn - centre)))]
                before = (optics, float(sag[mid, -1]))
                sag_lo, sag_hi = min(sag_lo, float(sag[mask].min())), max(sag_hi, float(sag[mask].max()))
                C = fit_a @ (base + sag) @ fit_w.T
                system.strip_coeff[(i, j, k)], system.used[i, j, k] = C, True
                ft = (DEGREE * low @ (C[1:] - C[:-1]) / p) @ Bw.T
                fw = Ba @ C @ Dw.T
                system.fit_error = max(system.fit_error, float(np.abs(ft * c + fw * sn - sy)[mask].max()),
                                       float(np.abs(-ft * sn + fw * c - sz)[mask].max()))
    if not system.used.any():
        raise DesignError("the lens has no strip within the frame")
    if without:
        system.warnings.append(f"{without} strip segments lie in no row of the element table: they are plane")
    system.sag = (sag_lo, sag_hi)


def _join(system: LensSystem, progress=None) -> None:
    """Walls with a draft angle, rounded at foot and head, between the elements: the profile across
    every border as between the facets of the reflector (al_transitions.blend), as bands that run
    out into the cells. First between the cells of a row, then between the rows, whose two sides
    are the rows as built so far."""
    import al_transitions as T

    s = system.settings
    room = min(s.cell_width, s.cell_height)
    site = 0.05          # mm across a wall: these walls are low and narrow, their fillets small

    def used(y, z):
        return system.cell(np.ravel(y), np.ravel(z))[2].reshape(np.shape(y))

    def height(y, z):
        return system.inner(np.ravel(y), np.ravel(z))[0].reshape(np.shape(y))

    def profiles(border, breaks, extra=0.0):
        try:
            return T.profiles(border, breaks, s.wall_draft, s.wall_fillet, height, height, 1e9, room, used, extra)
        except DesignError as e:
            raise DesignError("the lens elements are too small for walls with this draft angle and fillet radius "
                              f"({e})") from e

    for j in range(system.nz):                                             # between the cells of a row
        if progress is not None:
            progress(0.5 * j / system.nz, "walls of the lens elements …")
        za = system.z0 + j * s.cell_height
        for i in range(1, system.ny):
            if not (system.used[i - 1, j].any() and system.used[i, j].any()):
                continue
            border = T.LineBorder(np.array([system.y0 + i * s.cell_width, 0.0]), np.array([0.0, -1.0]))   # ξ along +y
            # (the stations stay inside the row: on its upper border a point belongs to the next row)
            pr = profiles(border, T.stations((-(za + s.cell_height) + 1e-6, -za - 1e-6)))
            if pr is not None:
                system.column_bands[(i, j)] = T.band_of(pr, T._width(pr.reach), (j,), i, site=site)
    for j in range(1, system.nz):                                          # between the rows
        if progress is not None:
            progress(0.5 + 0.5 * j / system.nz, "walls of the lens elements …")
        both = np.flatnonzero(system.used[:, j - 1].any(axis=1) & system.used[:, j].any(axis=1))
        if not len(both):
            continue
        border = T.LineBorder(np.array([0.0, system.z0 + j * s.cell_height]), np.array([1.0, 0.0]))      # ξ along +z
        u_range = (system.y0 + both[0] * s.cell_width, system.y0 + (both[-1] + 1) * s.cell_width)
        crossings = [system.y0 + i * s.cell_width for i in range(1, system.ny)
                     if (i, j - 1) in system.column_bands or (i, j) in system.column_bands]
        pr = profiles(border, T.stations(u_range, crossings), extra=0.8 if crossings else 0.0)
        if pr is not None:
            system.row_bands[j] = T.band_of(pr, T._width(pr.reach), (j - 1, j), site=site)


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
    if system.strips:
        return out + _strip_faces(system, origin)
    # the cells (their parts in the sectors): Bézier patches of degree 5
    S = system.count
    for i in range(system.ny):
        for j in range(system.nz):
            ya, za = system.y0 + i * s.cell_width, system.z0 + j * s.cell_height
            yb, zb = ya + s.cell_width, za + s.cell_height
            cell = np.array([[ya, za], [yb, za], [yb, zb], [ya, zb]])
            for k in np.flatnonzero(system.used[i, j]):
                pieces = [system.frame]
                left, right = system.column_bands.get((i, j)), system.column_bands.get((i + 1, j))   # the bands take
                below, above = system.row_bands.get(j), system.row_bands.get(j + 1)                    # their share
                for normal, offset in (((1.0, 0.0), ya + (left.half_width if left else 0.0)),
                                       ((-1.0, 0.0), -yb + (right.half_width if right else 0.0)),
                                       ((0.0, 1.0), za + (below.half_width if below else 0.0)),
                                       ((0.0, -1.0), -zb + (above.half_width if above else 0.0))):
                    pieces = al_layout.clip_all(pieces, al_layout.Line(np.array(normal), offset))
                if S > 1:
                    pieces = system.sector_pieces(pieces, int(k))
                if not pieces:
                    continue
                C = system.coeff[i, j, k]
                ctrl = [(s.lens_x + C[a_, b_] + ox, ya + (yb - ya) * a_ / DEGREE + oy, za + (zb - za) * b_ / DEGREE + oz)
                        for a_ in range(DEGREE + 1) for b_ in range(DEGREE + 1)]
                patch = {"degree_u": DEGREE, "degree_v": DEGREE, "knots_u": [ya] * (DEGREE + 1) + [yb] * (DEGREE + 1),
                         "knots_v": [za] * (DEGREE + 1) + [zb] * (DEGREE + 1), "num_u": DEGREE + 1,
                         "num_v": DEGREE + 1, "points": [round(float(c), 8) for p in ctrl for c in p]}
                name = f"lens element {i}.{j}" + (f"/{k}" if S > 1 else "")
                for piece in pieces:
                    whole = abs(al_layout.area(piece) - al_layout.area(cell)) < 1e-6 and not (left or right or below or above)
                    face = {"type": "trimmed_surface", "surface": patch, "label": name}
                    if not whole:
                        face["outer"] = [_loop(piece)]
                    out.append(("element", name.capitalize(), face))
    if system.column_bands or system.row_bands:        # walls with a draft: the bands that join the cells
        here = (ox + s.lens_x, oy, oz)
        for key, band in sorted(system.row_bands.items()) + sorted(system.column_bands.items()):
            row = isinstance(key, int)
            zb = system.z0 + (key if row else key[1]) * s.cell_height
            if row:
                limits = ((1.0, 0.0), band.graph.knots_p[0]), ((-1.0, 0.0), -band.graph.knots_p[-1]), \
                    ((0.0, 1.0), zb - band.half_width), ((0.0, -1.0), -zb - band.half_width)
            else:
                yb = system.y0 + key[0] * s.cell_width
                below, above = system.row_bands.get(key[1]), system.row_bands.get(key[1] + 1)
                limits = ((1.0, 0.0), yb - band.half_width), ((-1.0, 0.0), -yb - band.half_width), \
                    ((0.0, 1.0), zb + (below.half_width if below else 0.0)), \
                    ((0.0, -1.0), -zb - s.cell_height + (above.half_width if above else 0.0))
            pieces = [system.frame]
            for normal, offset in limits:
                pieces = al_layout.clip_all(pieces, al_layout.Line(np.array(normal), offset))
            surface = band.surface(here)
            name = f"Lens walls between the rows {key - 1}|{key}" if row else f"Lens wall {key[0] - 1}|{key[0]}.{key[1]}"
            for piece in pieces:
                loop = np.stack(band.border.uxi(piece[:, 0], piece[:, 1]), axis=1)
                out.append(("wall", name, {"type": "trimmed_surface", "surface": surface, "label": name.lower(),
                                           "outer": [_loop(loop if al_layout.area(loop) > 0 else loop[::-1])]}))
        return out
    # the walls between neighbouring cells: ruled along X between the two patches' rims – on a border
    # the radial lines cross, piece by piece between them
    outline = al_layout.simplified(system.frame, 0.05)
    fraction = np.arange(DEGREE + 1) / DEGREE
    for i in range(system.ny):
        for j in range(system.nz):
            if not system.used[i, j].any():
                continue
            ya, za = system.y0 + i * s.cell_width, system.z0 + j * s.cell_height
            yb, zb = ya + s.cell_width, za + s.cell_height
            for (ni, nj), fixed, lo_v, hi_v, across in (((i + 1, j), yb, za, zb, False), ((i, j + 1), zb, ya, yb, True)):
                if ni >= system.ny or nj >= system.nz or not system.used[ni, nj].any():
                    continue
                for va, vb in _between(system, fixed, lo_v, hi_v, across):
                    vm = 0.5 * (va + vb)
                    k = int(system.sector(*((vm, fixed) if across else (fixed, vm))))
                    if not (system.used[i, j, k] and system.used[ni, nj, k]):
                        continue
                    mine = system.coeff[i, j, k, :, DEGREE] if across else system.coeff[i, j, k, DEGREE, :]
                    theirs = system.coeff[ni, nj, k, :, 0] if across else system.coeff[ni, nj, k, 0, :]
                    if np.abs(mine - theirs).max() < 1e-6:
                        continue                                            # no step here
                    v = va + (vb - va) * np.linspace(0.0, 1.0, 33)
                    line = np.column_stack([v, np.full(33, fixed)] if across else [np.full(33, fixed), v])
                    on = v[al_layout.contains(outline, line)]
                    if len(on) < 2:
                        continue
                    ctrl = [(s.lens_x + edge[b_] + ox, (lo_v + (hi_v - lo_v) * fraction[b_] if across else fixed) + oy,
                             (fixed if across else lo_v + (hi_v - lo_v) * fraction[b_]) + oz)
                            for edge in (mine, theirs) for b_ in range(DEGREE + 1)]
                    wall = {"degree_u": 1, "degree_v": DEGREE, "knots_u": [0.0, 0.0, 1.0, 1.0],
                            "knots_v": [lo_v] * (DEGREE + 1) + [hi_v] * (DEGREE + 1), "num_u": 2,
                            "num_v": DEGREE + 1, "points": [round(float(c), 8) for p in ctrl for c in p]}
                    name = f"lens wall {i}.{j}|{ni}.{nj}" + (f"/{k}" if S > 1 else "")
                    face = {"type": "trimmed_surface", "surface": wall, "label": name}
                    if on[0] > lo_v + 1e-9 or on[-1] < hi_v - 1e-9:        # the outline or a radial line ends it
                        face["outer"] = [_loop(np.array([[0.0, on[0]], [1.0, on[0]], [1.0, on[-1]], [0.0, on[-1]]]))]
                    out.append(("wall", name.capitalize(), face))
    out += _radial_walls(system, outline, origin)
    return out


def _crossings(polys: list[np.ndarray], c: float) -> list[tuple[float, float]]:
    """The pieces of the line p = c (polygons of points (p, q)) inside the polygons: (q from, q to)."""
    out = []
    for poly in polys:
        a, b = poly, np.roll(poly, -1, axis=0)
        da, db = a[:, 0] - c, b[:, 0] - c
        cross = (da > 0.0) != (db > 0.0)
        q = np.sort(a[cross, 1] + (b[cross, 1] - a[cross, 1]) * da[cross] / (da[cross] - db[cross]))
        out += [(float(q[n]), float(q[n + 1])) for n in range(0, len(q) - 1, 2) if q[n + 1] - q[n] > 1e-9]
    return out


def _strip_faces(system: LensSystem, origin) -> list[tuple[str, str, dict]]:
    """The strips' segments (STRIPS) as B-spline surfaces with the parameters (t, w) of their sector,
    trimmed to their part of it; the walls between neighbouring strips and between the segments of
    a strip, ruled along X between their rims; and those along the sectors' lines."""
    s = system.settings
    ox, oy, oz = origin
    p, S = s.pitch, system.count
    out, walls = [], []
    deg = list(range(DEGREE + 1))

    def wall_face(label, ctrl, knots_v, degree_v, lo, hi):
        surface = {"degree_u": 1, "degree_v": degree_v, "knots_u": [0.0, 0.0, 1.0, 1.0],
                   "knots_v": [float(x) for x in knots_v], "num_u": 2, "num_v": len(ctrl) // 2,
                   "points": [round(float(x), 8) for q in ctrl for x in q]}
        return ("wall", label.capitalize(), {"type": "trimmed_surface", "surface": surface, "label": label,
                                             "outer": [_loop(np.array([[0.0, lo], [1.0, lo], [1.0, hi], [0.0, hi]]))]})

    for k in range(S):
        phi = math.radians(float(system.tilts[k]))
        c, sn = math.cos(phi), math.sin(phi)
        region = system.sector_region([system.frame], k)
        tw = [np.column_stack([q[:, 0] * c - q[:, 1] * sn, q[:, 0] * sn + q[:, 1] * c]) for q in region]  # (t, w)
        wt = [q[:, ::-1] for q in tw]                                                                      # (w, t)
        yz = lambda t, w: (t * c + w * sn + oy, -t * sn + w * c + oz)        # noqa: E731
        for i, j in np.argwhere(system.used[:, :, k]):
            i, j = int(i), int(j)
            m, knots = i + system.strip_m0, system.strip_knots[(j, k)]
            n = len(knots) - 4
            gw = al_spline.greville(knots, n, 3)
            ta, tb, wa, wb = (m - 0.5) * p, (m + 0.5) * p, float(knots[0]), float(knots[-1])
            C = system.strip_coeff[(i, j, k)]
            T, W = np.meshgrid(ta + p * np.arange(DEGREE + 1) / DEGREE, gw, indexing="ij")
            Y, Z = yz(T, W)
            pts = np.stack([s.lens_x + C + ox, Y, Z], axis=-1)
            surface = {"degree_u": DEGREE, "degree_v": 3, "knots_u": [ta] * (DEGREE + 1) + [tb] * (DEGREE + 1),
                       "knots_v": [float(x) for x in knots], "num_u": DEGREE + 1, "num_v": n,
                       "points": [round(float(x), 8) for x in pts.reshape(-1)]}
            name = f"lens strip {m}" + (f".{j + system.strip_j0}" if s.segment > 0.0 else "") + (f"/{k}" if S > 1 else "")
            for piece in system.strip_band(i, k, region, j):
                loop = np.column_stack([piece[:, 0] * c - piece[:, 1] * sn, piece[:, 0] * sn + piece[:, 1] * c])
                out.append(("element", name.capitalize(), {"type": "trimmed_surface", "surface": surface,
                                                           "label": name, "outer": [_loop(loop)]}))
            # the wall to the next strip (to the left where they stand upright)
            if i + 1 < system.ny and system.used[i + 1, j, k]:
                mine, theirs = C[DEGREE], system.strip_coeff[(i + 1, j, k)][0]
                if np.abs(mine - theirs).max() >= 1e-6:
                    ctrl = [(s.lens_x + edge[b] + ox, *yz(tb, gw[b])) for edge in (mine, theirs) for b in range(n)]
                    for lo, hi in _crossings(tw, tb):
                        lo, hi = max(lo, wa), min(hi, wb)
                        if hi - lo > 1e-9:
                            walls.append(wall_face(f"lens wall {m}|{m + 1}" + name[len(f"lens strip {m}"):], ctrl,
                                                   knots, 3, lo, hi))
            # the step to the next segment (upwards where they stand upright)
            if j + 1 < system.nz and system.used[i, j + 1, k]:
                above = system.strip_knots[(j + 1, k)]
                mine = C @ al_spline.basis_matrix(knots, n, 3, np.array([wb]))[0]
                theirs = system.strip_coeff[(i, j + 1, k)] @ al_spline.basis_matrix(above, len(above) - 4, 3,
                                                                                  np.array([wb]))[0]
                if np.abs(mine - theirs).max() >= 1e-6:
                    ctrl = [(s.lens_x + edge[a] + ox, *yz(ta + p * a / DEGREE, wb)) for edge in (mine, theirs) for a in deg]
                    for lo, hi in _crossings(wt, wb):
                        lo, hi = max(lo, ta), min(hi, tb)
                        if hi - lo > 1e-9:
                            walls.append(wall_face(f"lens step {name[len('lens strip '):]}|{j + 1 + system.strip_j0}",
                                                   ctrl, [ta] * (DEGREE + 1) + [tb] * (DEGREE + 1), DEGREE, lo, hi))
    return out + walls + _strip_radial_walls(system, origin)


def _strip_radial_walls(system: LensSystem, origin) -> list[tuple[str, str, dict]]:
    """The walls along the sectors' radial lines between the strips on either side (STRIPS): piece
    by piece between the borders of the strips and segments that the line crosses, each side's rim
    a cubic B-spline fitted to the segment there (within some 1e-5 mm)."""
    s = system.settings
    ox, oy, oz = origin
    p, L, S = s.pitch, s.segment, system.count
    out = []
    if S < 2:
        return out
    count = 8                                                              # control points per rim
    for q, az in enumerate(np.radians(system.bounds)):
        d = np.array([math.cos(az), math.sin(az)])
        # the line from the axis outwards (r d, r >= 0) within the frame: in coordinates (across, along)
        turn = np.array([[-d[1], d[0]], [d[0], d[1]]])
        reach = [(a, b) for a, b in _crossings([system.frame @ turn.T], 0.0) if b > 0.0]
        before, after = (q - 1) % S, q
        for r_lo, r_hi in reach:
            r_lo = max(r_lo, 0.0)
            cuts = {r_lo, r_hi}
            for k in (before, after):
                lean = math.radians(float(system.tilts[k]))
                for rate, size in ((math.cos(az + lean), p), (math.sin(az + lean), L)):   # t, w = r × rate
                    if abs(rate) < 1e-12 or size <= 0.0:
                        continue
                    lo, hi = sorted((r_lo * rate, r_hi * rate))
                    for m in range(math.floor(lo / size - 0.5), math.ceil(hi / size - 0.5) + 1):
                        r = (m + 0.5) * size / rate
                        if r_lo + 1e-9 < r < r_hi - 1e-9:
                            cuts.add(r)
            cuts = sorted(cuts)
            for ra, rb in zip(cuts[:-1], cuts[1:]):
                if rb - ra < 1e-6:
                    continue
                r = np.linspace(ra, rb, 49)
                y, z = r * d[0], r * d[1]
                rims = []
                for k in (before, after):
                    t, w, _, _ = system.turned(y, z, np.full(len(r), k))
                    i, j = (int(x[24]) for x in system.strip_index(t, w))
                    if not (0 <= i < system.ny and 0 <= j < system.nz and system.used[i, j, k]):
                        break
                    rims.append(system.strip_at(i, j, k, t, w, slopes=False))
                if len(rims) < 2 or np.abs(rims[0] - rims[1]).max() < 1e-6:
                    continue
                knots = al_spline.clamped_uniform_knots(count, 3, ra, rb)
                B = al_spline.basis_matrix(knots, count, 3, r)
                g = al_spline.greville(knots, count, 3)
                ctrl = [(s.lens_x + x + ox, g[b] * d[0] + oy, g[b] * d[1] + oz)
                        for rim in rims for b, x in enumerate(np.linalg.lstsq(B, rim, rcond=None)[0])]
                wall = {"degree_u": 1, "degree_v": 3, "knots_u": [0.0, 0.0, 1.0, 1.0],
                        "knots_v": [float(x) for x in knots], "num_u": 2, "num_v": count,
                        "points": [round(float(x), 8) for c_ in ctrl for x in c_]}
                label = f"lens wall {before}|{after} at {ra:.1f}–{rb:.1f} mm"
                out.append(("wall", label.capitalize(), {"type": "trimmed_surface", "surface": wall, "label": label}))
    return out


def _between(system: LensSystem, fixed: float, lo_v: float, hi_v: float, across: bool) -> list[tuple[float, float]]:
    """The pieces of a cell border (z = fixed for `across`, else y = fixed; v from lo_v to hi_v)
    between the radial lines of the sectors that cross it."""
    cuts = [lo_v, hi_v]
    for a in np.radians(system.bounds):
        c, n = math.cos(a), math.sin(a)
        reach, along = (n, c) if across else (c, n)
        if abs(reach) > 1e-12 and fixed / reach > 0.0:
            v = fixed / reach * along
            if lo_v + 1e-9 < v < hi_v - 1e-9:
                cuts.append(v)
    cuts = sorted(cuts)
    return [(a, b) for a, b in zip(cuts[:-1], cuts[1:]) if b - a > 1e-9]


def _radial_walls(system: LensSystem, outline: np.ndarray, origin) -> list[tuple[str, str, dict]]:
    """The walls along the radial lines between the parts of a cut cell: ruled along X between the
    two patches along the line – a patch of degree 5 along a straight line is a curve of degree 10,
    exact as such."""
    s = system.settings
    ox, oy, oz = origin
    out = []
    S = system.count
    if S < 2:
        return out
    m = 2 * DEGREE
    tau = np.linspace(0.0, 1.0, m + 1)
    solve = np.linalg.inv(_bernstein(tau, m))
    for i in range(system.ny):
        for j in range(system.nz):
            if system.used[i, j].sum() < 2:
                continue
            ya, za = system.y0 + i * s.cell_width, system.z0 + j * s.cell_height
            yb, zb = ya + s.cell_width, za + s.cell_height
            for q, a in enumerate(np.radians(system.bounds)):
                d = np.array([math.cos(a), math.sin(a)])
                lo, hi = 0.0, np.inf                                        # the ray t d (t >= 0) within the cell
                for axis, (c0, c1) in enumerate(((ya, yb), (za, zb))):
                    if abs(d[axis]) < 1e-12:
                        if not c0 <= 0.0 <= c1:
                            hi = -1.0
                        continue
                    t0, t1 = sorted((c0 / d[axis], c1 / d[axis]))
                    lo, hi = max(lo, t0), min(hi, t1)
                if not hi - lo > 1e-6:
                    continue
                before, after = (q - 1) % S, q                              # clockwise of the line, counter-clockwise
                if not (system.used[i, j, before] and system.used[i, j, after]):
                    continue
                p0, p1 = lo * d, hi * d
                pts = p0 + tau[:, None] * (p1 - p0)
                ta, tb = (pts[:, 0] - ya) / s.cell_width, (pts[:, 1] - za) / s.cell_height
                Ba, Bb = _bernstein(ta), _bernstein(tb)
                edges = [solve @ np.einsum("np,pq,nq->n", Ba, system.coeff[i, j, k], Bb) for k in (before, after)]
                if np.abs(edges[0] - edges[1]).max() < 1e-6:
                    continue
                v = np.linspace(0.0, 1.0, 33)
                on = v[al_layout.contains(outline, p0 + v[:, None] * (p1 - p0))]
                if len(on) < 2:
                    continue
                ctrl = [(s.lens_x + edge[b] + ox, pts[b, 0] + oy, pts[b, 1] + oz) for edge in edges for b in range(m + 1)]
                wall = {"degree_u": 1, "degree_v": m, "knots_u": [0.0, 0.0, 1.0, 1.0],
                        "knots_v": [0.0] * (m + 1) + [1.0] * (m + 1), "num_u": 2, "num_v": m + 1,
                        "points": [round(float(c), 8) for p in ctrl for c in p]}
                name = f"lens wall {i}.{j}/{before}|{after}"
                face = {"type": "trimmed_surface", "surface": wall, "label": name}
                if on[0] > 1e-9 or on[-1] < 1.0 - 1e-9:
                    face["outer"] = [_loop(np.array([[0.0, on[0]], [1.0, on[0]], [1.0, on[-1]], [0.0, on[-1]]]))]
                out.append(("wall", name.capitalize(), face))
    return out
