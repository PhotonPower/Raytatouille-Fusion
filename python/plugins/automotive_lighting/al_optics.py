"""Lamps and the cut-off of the low beam.

Coordinates of the design (mm): the origin is the centre of the filament, +X the driving direction
(the light leaves along +X), +Y to the left, +Z up. A direction d is seen on the measuring screen at
h = -d_y / d_x (to the right) and v = d_z / d_x (up) – the tangents of the angles H and V; a straight
line on the screen is a plane through the lamp, so every branch of the cut-off is a plane m · d = 0
with the dark side m · d > 0. NumPy only."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


# ------------------------------------------------------------------ lamps
@dataclass(frozen=True)
class Shield:
    """What inside a two-filament lamp (H4) stops the light of the low-beam coil, in design
    coordinates. The lamp's reference axis runs parallel to X, `axis_z` above the coil centre.

    The shield is a trough under the coil: the part of the cylinder of `radius` about the reference
    axis that lies outside `window` – azimuths atan2(z, y) about that axis, in degrees; light leaves
    between the two edges. It runs from `back` (closed there by an end wall, the segment of the
    circle below the chord between the edges) to `front` (open). The bulb is a cylinder of
    `bulb_radius` about the reference axis, blackened from `cap_x` on (the cap on its tip); `cap_x`
    None: no cap."""

    window: tuple[float, float]
    radius: float
    back: float
    front: float
    axis_z: float = 0.0
    cap_x: float | None = None
    bulb_radius: float = 6.5

    def passes(self, Q: np.ndarray, d: np.ndarray) -> np.ndarray:
        """Which rays from points Q (k, 3) on the coil in unit directions d (..., k, 3) get out of
        the lamp: neither the trough, its end wall nor the cap stop them."""
        dx, dy, dz = d[..., 0], d[..., 1], d[..., 2]
        x0, y0, z0 = Q[:, 0], Q[:, 1], Q[:, 2] - self.axis_z
        lo, hi = self.window
        span = (hi - lo) % 360.0 or 360.0
        # where the ray leaves the cylinder of the trough (it starts inside it)
        qa = dy * dy + dz * dz
        qb = y0 * dy + z0 * dz
        qc = y0 * y0 + z0 * z0 - self.radius ** 2
        inside = qc < 0.0
        with np.errstate(divide="ignore", invalid="ignore"):   # (along the axis: t = ∞, it never meets the trough)
            t = np.where(qa > 1e-12, (-qb + np.sqrt(np.maximum(qb * qb - qa * qc, 0.0))) / qa, np.inf)
            x_out = x0 + t * dx
            az = np.where(inside, np.degrees(np.arctan2(z0 + t * dz, y0 + t * dy)),
                          np.degrees(np.arctan2(dz, dy)))     # (a coil wider than the trough: the direction)
        on_trough = ~inside | ((x_out >= self.back) & (x_out <= self.front))
        stopped = on_trough & (((az - lo) % 360.0) > span)
        # the end wall at the back: the segment below the chord between the two edges
        with np.errstate(divide="ignore", invalid="ignore"):
            s = np.where(dx < 0.0, (self.back - x0) / dx, np.inf)
        e1 = self.radius * np.array([math.cos(math.radians(lo)), math.sin(math.radians(lo))])
        e2 = self.radius * np.array([math.cos(math.radians(hi)), math.sin(math.radians(hi))])
        mid = math.radians(hi + 0.5 * (360.0 - span))
        m = self.radius * np.array([math.cos(mid), math.sin(mid)])
        chord = e2 - e1
        side = chord[0] * (m[1] - e1[1]) - chord[1] * (m[0] - e1[0])
        with np.errstate(invalid="ignore"):
            yb, zb = y0 + s * dy, z0 + s * dz
            wall = (inside & (x_out < self.back) & np.isfinite(s)
                    & ((chord[0] * (zb - e1[1]) - chord[1] * (yb - e1[0])) * side > 0.0))
        stopped |= wall
        if self.cap_x is not None:
            # the cap: a ray still within the bulb where the blackening begins meets it
            with np.errstate(divide="ignore", invalid="ignore"):
                s = np.where(dx > 0.0, np.maximum(self.cap_x - Q[:, 0], 0.0) / dx, np.inf)
                yc, zc = y0 + s * dy, z0 + s * dz
                stopped |= np.isfinite(s) & (yc * yc + zc * zc < self.bulb_radius ** 2)
        return ~stopped


def h4_shield(length: float, diameter: float, *, radius: float = 4.3, alpha: float = 40.0,
              bulb_diameter: float = 13.0) -> Shield:
    """The shield and the tip cap of an H4 (UN/ECE R37, sheets H4/1 to H4/5, 12 V) about a coil of
    `length` and `diameter`, from the regulation where it fixes them:
      e = 28.5   from the reference plane to the start of the low-beam coil (its centre: e + l/2)
      c = 0.6    top of the coil above plane H; the shield's edges: b1 = 0 on plane H, b2 = 0 on the
                 line 15° below it through the reference axis – the window (−15°, 180°)
      p = 28.95, α ≤ 40°: the cap's edge is seen from the point p on the reference axis at most α
                 from the axis (footnote 5/: it covers the tip and overlaps the shield)
    and taken from the drawing of sheet H4/3 where it does not (it "is not mandatory with respect
    to the design of the shield"; p, q at 33 mm "depend on the shape of the shield"): a half
    cylinder about 8.6 mm wide and 4.2 mm deep – radius 4.3 –, its ends 1.2 mm behind and 3.4 mm in
    front of the coil; the bulb's outer diameter (13 mm, OSRAM data sheets).

    In its headlamp the H4's mirror has its focus at the driving-beam coil, 6.7 mm behind the
    passing-beam coil's centre: then the light the shining shield sends back – from its rear part
    backwards and up – stays below the cut-off; with the focus closer to the passing-beam coil it
    rises above it."""
    e, c, p = 28.5, 0.6, 28.95
    centre = e + 0.5 * length
    bulb_radius = 0.5 * bulb_diameter
    return Shield(window=(-15.0, 180.0), radius=radius,
                  back=-0.5 * length - 1.2, front=0.5 * length + 3.4,
                  axis_z=0.5 * diameter - c,
                  cap_x=(p - centre) + bulb_radius / math.tan(math.radians(alpha)),
                  bulb_radius=bulb_radius)


@dataclass(frozen=True)
class Lamp:
    """A filament lamp as the design sees it: the coil as a cylinder (length, diameter), its
    luminous flux, and what of it reaches the reflector."""

    name: str
    length: float                 # mm, filament (coil) length
    diameter: float               # mm, coil diameter
    flux: float                   # lm at the test voltage
    axial: bool = True            # coil along the lamp axis (X); else across it (along Y)
    shield: Shield | None = None  # what inside the lamp stops light of the coil (H4)
    note: str = ""
    watts: float = 0.0            # W at 12 V (the coil's wire for the ray tracing is estimated from it)


# UN/ECE R37 (Rev. 7), 12 V lamps: luminous flux = the objective value at the test voltage (13.2 V,
# signal lamps 13.5 V; ± 10 … 20 %), filament length = the nominal one of the lamp's sheet (R5W,
# R10W: none given, typical). R37 gives no coil diameters – at most an objective maximum (H7 1.3,
# H8 1.2, H9 1.4, H11 1.4 mm) –: typical values. "Custom" takes the panel's.
LAMPS: dict[str, Lamp] = {
    "H1": Lamp("H1", 5.0, 1.4, 1550.0, note="55 W, axial coil", watts=55.0),
    "H4 (low beam)": Lamp("H4 (low beam)", 5.5, 1.5, 1000.0, shield=h4_shield(5.5, 1.5), watts=55.0,
                          note="55 W coil above its shield (R37 sheet H4/3): light over the edges into the upper "
                               "195°, a trough 4.3 mm in radius closed at the back; the black tip cap ≤ 40°; the "
                               "mirror's focus at the driving-beam coil (6.7 mm behind)"),
    "H7": Lamp("H7", 4.1, 1.3, 1500.0, note="55 W, axial coil", watts=55.0),
    "H8": Lamp("H8", 3.7, 1.2, 800.0, note="35 W, axial coil", watts=35.0),
    "H9": Lamp("H9", 4.8, 1.4, 2100.0, note="65 W, axial coil", watts=65.0),
    "H11": Lamp("H11", 4.5, 1.3, 1350.0, note="55 W, axial coil", watts=55.0),
    "HB3": Lamp("HB3", 5.1, 1.4, 1860.0, note="60 W, axial coil", watts=60.0),
    "HB4": Lamp("HB4", 5.1, 1.4, 1095.0, note="51 W, axial coil", watts=51.0),
    "H3": Lamp("H3", 5.0, 1.4, 1450.0, axial=False, note="55 W, transverse coil (fog lamps)", watts=55.0),
    # signal lamps: the coil lies across the axis
    "P21W": Lamp("P21W", 6.0, 1.0, 460.0, axial=False, note="21 W, transverse coil", watts=21.0),
    "PY21W": Lamp("PY21W", 6.0, 1.0, 280.0, axial=False, note="21 W amber, transverse coil", watts=21.0),
    "R10W": Lamp("R10W", 4.0, 0.8, 125.0, axial=False, note="10 W, transverse coil", watts=10.0),
    "R5W": Lamp("R5W", 4.0, 0.7, 50.0, axial=False, note="5 W, transverse coil", watts=5.0),
}
CUSTOM = "Custom"


@dataclass(frozen=True)
class Filament:
    """The coil as a solid cylinder about the origin."""

    axis: np.ndarray       # unit vector
    half_length: float
    radius: float

    @staticmethod
    def of(lamp: Lamp) -> "Filament":
        axis = np.array([1.0, 0.0, 0.0]) if lamp.axial else np.array([0.0, 1.0, 0.0])
        return Filament(axis, 0.5 * lamp.length, 0.5 * lamp.diameter)

    def support(self, u: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(σ, a) for unit vectors u (n, 3): σ = max over the cylinder of u · Q, a = u · axis."""
        a = u @ self.axis
        return self.half_length * np.abs(a) + self.radius * np.sqrt(np.maximum(1.0 - a * a, 0.0)), a

    def contact(self, u: np.ndarray, sign: np.ndarray | None = None) -> np.ndarray:
        """The point of the cylinder lowest along u (n, 3): where a plane with normal u touches it
        from below. `sign` forces the end (±1) instead of the sign of u · axis."""
        a = u @ self.axis
        s = np.where(a >= 0.0, 1.0, -1.0) if sign is None else sign
        perp = u - a[:, None] * self.axis
        norm = np.linalg.norm(perp, axis=1, keepdims=True)
        perp = perp / np.maximum(norm, 1e-300)
        return -self.half_length * s[:, None] * self.axis - self.radius * perp

    def surface_samples(self, n_axial: int, n_around: int) -> tuple[np.ndarray, np.ndarray, float]:
        """Points on the lateral surface with their outward normals and the area of one sample."""
        t = (np.arange(n_axial) + 0.5) / n_axial * 2.0 - 1.0
        phi = (np.arange(n_around) + 0.5) / n_around * 2.0 * math.pi
        e1 = np.cross(self.axis, [0.0, 0.0, 1.0])
        if np.linalg.norm(e1) < 1e-9:
            e1 = np.cross(self.axis, [0.0, 1.0, 0.0])
        e1 = e1 / np.linalg.norm(e1)
        e2 = np.cross(self.axis, e1)
        normals = np.cos(phi)[:, None] * e1 + np.sin(phi)[:, None] * e2            # (n_around, 3)
        points = (t[:, None, None] * self.half_length * self.axis
                  + self.radius * normals[None, :, :]).reshape(-1, 3)
        area = 2.0 * math.pi * self.radius * 2.0 * self.half_length / (n_axial * n_around)
        return points, np.tile(normals, (n_axial, 1)), area

    def outline_samples(self, n_around: int = 24) -> np.ndarray:
        """Points on the two end circles: their convex hull is the cylinder."""
        pts, _, _ = self.surface_samples(1, n_around)
        ring = pts - (pts @ self.axis)[:, None] * self.axis
        return np.concatenate([ring - self.half_length * self.axis, ring + self.half_length * self.axis])


# ------------------------------------------------------------------ screen and cut-off
def screen(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(h, v) of directions (n, 3) with d_x > 0."""
    return -d[..., 1] / d[..., 0], d[..., 2] / d[..., 0]


def direction(h, v) -> np.ndarray:
    """Unit directions (n, 3) of screen points."""
    h, v = np.broadcast_arrays(np.asarray(h, dtype=float), np.asarray(v, dtype=float))
    d = np.stack([np.ones_like(h), -h, v], axis=-1)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


HORIZONTAL, RISING = "horizontal", "rising"


@dataclass(frozen=True)
class Cutoff:
    """The cut-off line of an asymmetric low beam: horizontal at V (below the horizon) on the side
    of the oncoming traffic, rising by `rise` from the kink at H = kink on the driver's own side."""

    v_deg: float = -0.57          # 1 % below the horizon
    rise_deg: float = 15.0
    kink_deg: float = 0.0
    right_hand_traffic: bool = True

    @property
    def slope(self) -> float:
        """dv/dh of the rising branch (negative for left-hand traffic: it rises to the left)."""
        k = math.tan(math.radians(self.rise_deg))
        return k if self.right_hand_traffic else -k

    def plane(self, branch: str, below_deg: float = 0.0) -> np.ndarray:
        """Unit normal m of the branch's plane, lowered by `below`; m · d > 0 is the dark side."""
        v0 = math.tan(math.radians(self.v_deg - below_deg))
        hk = math.tan(math.radians(self.kink_deg))
        k = self.slope if branch == RISING else 0.0
        m = np.array([-(v0 - k * hk), k, 1.0])   # m · (1, -h, v) = v - v0 - k (h - hk)
        return m / np.linalg.norm(m)

    def line(self, h: np.ndarray) -> np.ndarray:
        """v of the cut-off at screen positions h: the higher of the two branches."""
        v0 = math.tan(math.radians(self.v_deg))
        hk = math.tan(math.radians(self.kink_deg))
        return np.maximum(v0, v0 + self.slope * (np.asarray(h, dtype=float) - hk))

    def above(self, d: np.ndarray) -> np.ndarray:
        """Sine of the angle by which directions (n, 3) lie above the cut-off (dark side > 0)."""
        return np.minimum(d @ self.plane(HORIZONTAL), d @ self.plane(RISING))
