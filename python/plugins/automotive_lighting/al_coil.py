"""What the ray tracing (al_trace) sees of a filament lamp: the coil as it is – a helix of
tungsten wire, hotter in the middle than at its ends – the bulb's glass with its black top, the
H4's shield and its second (driving-beam) coil, as NURBS surfaces in design coordinates. The
design and the filament images keep the cylinder of al_optics.Filament.

The coil fills the cylinder of the lamp (length, diameter): the wire's centre runs on a helix
of radius (diameter − wire) / 2 from one end to the other. Its wire diameter and number of
turns are not in UN/ECE R37; without own values they are estimated from the lamp's power:
a tungsten wire at 3100 K (resistivity 95.6 µΩ cm, interpolated between 3000 K and 3200 K in
Desai et al., J. Phys. Chem. Ref. Data 13 (1984) 1069) at the test voltage 13.2 V, the power
rising as (U / 12 V)^1.6, wound with a pitch of 1.5 wire diameters. That gives 0.16 mm and 16
turns for an H7, 0.19 mm and 19 turns for an H4 – the range of real coils of such lamps.

The coil's ends are cooler: the leads draw heat off them. Along the wire the heat conducted
balances the Joule heat and the radiation, k A T'' = π d ε σ T⁴ − I² ρ(T) / A with ρ ∝ T^β and the
current that keeps the middle at 3100 K; its first integral gives the temperature's rise from the
ends (temperature `end` there, assumed: 2400 K) to the middle within about 1.5 mm of wire – half a
turn. The wire shines by its temperature (Planck's law weighted with V(λ), grey tungsten); the
coil's turns warming each other is left out.

The bulb (Bulb) is a tube of glass closed by a half sphere at its tip, about the lamp's reference
axis, with the black top as a coating on its outside – where R37 puts it at least: from the angle
γ3 seen from the coil's end nearest the reference plane (H7, H8, H11: 30°) or its centre (HB4:
45°), for the H4 from its shield's cap (α ≤ 40°). Diameters, wall and the tip's position are typical values of such lamps (R37 fixes
only the outline they must stay within).

NumPy only."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

import al_spline
from al_optics import Filament, Lamp, Shield

RESISTIVITY = 95.6e-6 * 10.0        # Ω mm (95.6 µΩ cm): tungsten at 3100 K
TEST_VOLTAGE = 13.2                 # V, UN/ECE R37 for 12 V lamps
PITCH = 1.5                         # pitch / wire diameter where it is not given
PER_TURN = 16                       # control points of the helix per turn (cubic: within 1e-4 of the radius)
T_COIL = 3100.0                     # K, the coil's middle
END_TEMPERATURE = 2400.0            # K, the coil's ends (assumed)
CONDUCTIVITY = 0.095                # W / (mm K): tungsten at 3000 K
EMISSIVITY = 0.34                   # total, hemispherical: tungsten at 3100 K
SIGMA = 5.670e-14                   # W / (mm² K⁴)
BETA = 1.15                         # d ln ρ / d ln T of tungsten at 3100 K (Desai et al.)
QUARTZ, HARD_GLASS = 1.458, 1.52    # refractive indices of the bulbs (quartz: halogen lamps; soft glass: signal lamps)


@dataclass(frozen=True)
class Coil:
    """A helix of wire about the filament's axis through the origin: `turns` turns from one end of
    the cylinder (length, diameter) to the other, the wire's surface touching it."""

    length: float           # mm, outer length (the lamp's filament length)
    diameter: float         # mm, outer diameter
    wire: float             # mm, wire diameter
    turns: int
    axis: tuple             # unit vector along the coil
    offset: tuple = (0.0, 0.0, 0.0)   # its centre (mm); the lamp's other coil is beside the design's origin

    @property
    def helix_radius(self) -> float:
        return 0.5 * (self.diameter - self.wire)

    @property
    def pitch(self) -> float:
        return (self.length - self.wire) / self.turns

    @property
    def turn_length(self) -> float:
        return math.hypot(2.0 * math.pi * self.helix_radius, self.pitch)

    @property
    def wire_length(self) -> float:
        return self.turns * self.turn_length

    def frame(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Unit vectors: along the coil, and two across it (e1 × e2 = axis)."""
        a = np.asarray(self.axis, dtype=float)
        e1 = np.cross(a, [0.0, 0.0, 1.0])
        e1 = e1 / np.linalg.norm(e1) if np.linalg.norm(e1) > 1e-9 else np.array([0.0, 1.0, 0.0])
        return a, e1, np.cross(a, e1)

    def centre(self, phi: np.ndarray) -> np.ndarray:
        """Points (n, 3) of the wire's centre line at the angles phi (0 … 2π turns)."""
        a, e1, e2 = self.frame()
        phi = np.asarray(phi, dtype=float)
        along = -0.5 * (self.length - self.wire) + self.pitch * phi / (2.0 * math.pi)
        r = self.helix_radius
        return (along[:, None] * a + (r * np.cos(phi))[:, None] * e1 + (r * np.sin(phi))[:, None] * e2
                + np.asarray(self.offset, dtype=float))


def estimated_wire(length: float, diameter: float, watts: float, pitch: float = PITCH) -> float:
    """Wire diameter (mm) of a coil of `length` and outer `diameter` that takes `watts` (at 12 V)
    at the test voltage: 4 (l − d)(D − d) / (p d³) = R / ρ with R = U² / P, solved by halving."""
    power = watts * (TEST_VOLTAGE / 12.0) ** 1.6
    want = TEST_VOLTAGE ** 2 / power / RESISTIVITY            # wire length / cross-section, 1/mm
    lo, hi = 1e-4, 0.5 * min(length, diameter)
    for _ in range(80):
        d = 0.5 * (lo + hi)
        if 4.0 * (length - d) * (diameter - d) / (pitch * d ** 3) > want:
            lo = d
        else:
            hi = d
    return 0.5 * (lo + hi)


def coil_of(lamp: Lamp, fil: Filament, wire: float = 0.0, turns: int = 0, offset=(0.0, 0.0, 0.0)) -> Coil:
    """The coil of the lamp: wire diameter and turns as given, else estimated (see the module)."""
    if wire <= 0.0:
        if lamp.watts <= 0.0:
            raise ValueError(f"{lamp.name}: give the coil's wire diameter (its power is not known)")
        wire = estimated_wire(lamp.length, lamp.diameter, lamp.watts)
    if not wire < 0.5 * lamp.diameter:
        raise ValueError(f"the wire ({wire:g} mm) must be thinner than half the coil's diameter ({lamp.diameter:g} mm)")
    if turns <= 0:
        turns = max(1, round((lamp.length - wire) / (PITCH * wire)))
    coil = Coil(lamp.length, lamp.diameter, wire, int(turns), tuple(float(c) for c in fil.axis),
                tuple(float(c) for c in offset))
    if coil.pitch < wire * 1.02:
        raise ValueError(f"{turns} turns of {wire:g} mm wire do not fit into {lamp.length:g} mm: the turns would touch")
    return coil


def driving_coil(lamp: Lamp) -> tuple[Lamp, tuple] | None:
    """The H4's other coil, of the driving beam, as a lamp of its own and where its centre lies
    from the passing-beam coil's (UN/ECE R37 sheets H4/2 to H4/4, 12 V): lR = 4.5 long, ending
    f = 1.7 before the passing-beam coil (whose start is e = 28.5 from the reference plane), its
    axis a = 0.8 below plane H and g = 0 beside the reference axis; 1650 lm (60 W). Its diameter is
    not given: that of the passing-beam coil. None: the lamp has one coil."""
    if lamp.shield is None or not lamp.name.startswith("H4"):
        return None
    length = 4.5
    driving = Lamp("H4 (driving beam)", length, lamp.diameter, 1650.0, watts=60.0, shield=lamp.shield,
                   note="the driving-beam coil of the H4")
    return driving, (-(0.5 * lamp.length + 1.7 + 0.5 * length), 0.0, lamp.shield.axis_z - 0.8)


# ------------------------------------------------------------------ the temperature along the wire
_V = np.array([0.000039, 0.00012, 0.000396, 0.00121, 0.004, 0.0116, 0.023, 0.038, 0.06, 0.09098, 0.13902,
               0.20802, 0.323, 0.503, 0.71, 0.862, 0.954, 0.99495, 0.995, 0.952, 0.87, 0.757, 0.631, 0.503,
               0.381, 0.265, 0.175, 0.107, 0.061, 0.032, 0.017, 0.00821, 0.004102, 0.002091, 0.001047, 0.00052,
               0.000249, 0.00012, 0.00006, 0.00003, 0.000015])            # CIE 1924 V(λ), 380 … 780 nm
_NM = np.arange(380.0, 781.0, 10.0)


def luminance(T) -> np.ndarray:
    """Relative luminance of grey tungsten at temperatures T (K): 1 at T_COIL."""
    lam = _NM * 1e-3                                                   # µm

    def planck(t):
        t = np.atleast_1d(np.asarray(t, dtype=float))[:, None]
        with np.errstate(over="ignore"):
            return (_V / (lam ** 5 * np.expm1(14388.0 / (lam * np.maximum(t, 1.0))))).sum(axis=1)

    return planck(T) / planck(T_COIL)[0]


def end_profile(wire: float, end: float, length: float, step: float = 0.005) -> tuple[np.ndarray, np.ndarray]:
    """(s, T): the temperature along `length` mm of wire from an end at `end` K towards T_COIL.
    The first integral of the heat balance: (k A / 2) T'² = π d ε σ T0⁵ F(T / T0) with
    F(τ) = (1 − τ^(β+1)) / (β + 1) − (1 − τ⁵) / 5, integrated by Runge–Kutta."""
    c = 8.0 * EMISSIVITY * SIGMA * T_COIL ** 5 / (CONDUCTIVITY * wire)

    def slope(T: float) -> float:
        tau = min(T / T_COIL, 1.0)
        return math.sqrt(max(c * ((1.0 - tau ** (BETA + 1.0)) / (BETA + 1.0) - (1.0 - tau ** 5) / 5.0), 0.0))

    n = max(2, int(math.ceil(length / step)) + 1)
    s = np.linspace(0.0, length, n)
    h = s[1] - s[0]
    T = np.empty(n)
    T[0] = min(end, T_COIL)
    for i in range(n - 1):
        k1 = slope(T[i])
        k2 = slope(T[i] + 0.5 * h * k1)
        k3 = slope(T[i] + 0.5 * h * k2)
        k4 = slope(T[i] + h * k3)
        T[i + 1] = min(T[i] + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0, T_COIL)
    return s, T


def emission(coil: Coil, pieces: int = 4, end: float = END_TEMPERATURE) -> np.ndarray:
    """Relative luminance of the pieces of coil_faces(coil, pieces), in their order (1: T_COIL):
    their mean over 16 points each, the temperature from the nearer end."""
    count = coil.turns * pieces
    if end >= T_COIL:
        return np.ones(count)
    total = coil.wire_length
    s_grid, T_grid = end_profile(coil.wire, end, 0.5 * total)
    s = (np.arange(count)[:, None] + (np.arange(16) + 0.5)[None, :] / 16) * (total / count)
    T = np.interp(np.minimum(s, total - s), s_grid, T_grid)
    return luminance(T.reshape(-1)).reshape(count, 16).mean(axis=1)


# ------------------------------------------------------------------ NURBS
_CIRCLE = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0)]
_CIRCLE_W = [1.0, math.sqrt(0.5)] * 4 + [1.0]
_CIRCLE_KNOTS = [0, 0, 0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1, 1, 1]


def coil_faces(coil: Coil, origin=(0.0, 0.0, 0.0), pieces: int = 1) -> list[dict]:
    """The wire's surface as `pieces` faces per turn, from one end to the other: a tube about the
    helix – cubic along the wire (interpolating the helix and a frame across it), an exact circle
    around it. The normals point out of the wire."""
    a, _, _ = coil.frame()
    r = 0.5 * coil.wire
    n = max(4, PER_TURN // pieces) + 3
    knots = al_spline.clamped_uniform_knots(n, 3, 0.0, 1.0)
    sites = al_spline.greville(knots, n, 3)
    solve = np.linalg.inv(al_spline.basis_matrix(knots, n, 3, sites))
    middle = np.asarray(coil.offset, dtype=float)
    out = []
    for k in range(coil.turns * pieces):
        phi = 2.0 * math.pi * (k + sites) / pieces
        c = coil.centre(phi)
        q = c - middle
        radial = q - (q @ a)[:, None] * a                            # across the axis: out of the coil
        radial /= np.linalg.norm(radial, axis=1, keepdims=True)
        tangent = coil.pitch / (2.0 * math.pi) * a + np.cross(a, radial) * coil.helix_radius
        e2 = np.cross(radial, tangent)                               # radial x tangent: the normals point out
        e2 /= np.linalg.norm(e2, axis=1, keepdims=True)
        ctrl_c, ctrl_1, ctrl_2 = (solve @ v for v in (c, radial, e2))
        pts = np.stack([ctrl_c[:, None, :] + r * (cx * ctrl_1[:, None, :] + cy * ctrl_2[:, None, :])
                        for cx, cy in _CIRCLE], axis=1)                       # (n, 9, 3)
        pts = pts + np.asarray(origin, dtype=float)
        out.append({"type": "surface", "degree_u": 3, "degree_v": 2,
                    "knots_u": [float(t) for t in knots], "knots_v": list(map(float, _CIRCLE_KNOTS)),
                    "num_u": n, "num_v": 9, "points": [float(v) for v in pts.reshape(-1)],
                    "weights": [w for _ in range(n) for w in _CIRCLE_W]})
    return out


def _arc(radius: float, start: float, end: float):
    """A circular arc in a plane (degrees, counter-clockwise from start to end) as a rational
    quadratic: 2D control points, weights and knots, in pieces of at most 90°."""
    pieces = max(1, math.ceil((end - start) / 90.0 - 1e-9))
    step = math.radians(end - start) / pieces
    pts, weights = [], []
    for k in range(pieces):
        a0 = math.radians(start) + k * step
        if k == 0:
            pts.append((radius * math.cos(a0), radius * math.sin(a0)))
            weights.append(1.0)
        mid, far = a0 + 0.5 * step, radius / math.cos(0.5 * step)
        a1 = a0 + step
        pts += [(far * math.cos(mid), far * math.sin(mid)), (radius * math.cos(a1), radius * math.sin(a1))]
        weights += [math.cos(0.5 * step), 1.0]
    knots = [0.0] * 3 + [float(t) for k in range(1, pieces) for t in (k / pieces,) * 2] + [1.0] * 3
    return np.asarray(pts), weights, knots


def _lofted(rings: list[np.ndarray], weights, knots) -> dict:
    """The ruled surface between curves with the same weights and knots (u along them, v across)."""
    pts = np.stack(rings, axis=1)                                    # (num_u, 2, 3)
    return {"type": "surface", "degree_u": 2, "degree_v": 1, "knots_u": knots, "knots_v": [0.0, 0.0, 1.0, 1.0],
            "num_u": len(weights), "num_v": 2, "points": [float(v) for v in pts.reshape(-1)],
            "weights": [w for w in weights for _ in range(2)]}


def shield_faces(shield: Shield, origin=(0.0, 0.0, 0.0), cap: bool = True) -> list[tuple[str, dict]]:
    """("shield", face) for the trough and its end wall, ("cap", face) for the cap on the bulb's
    tip – as Shield.passes sees them: the cylinder of the trough outside the window from `back`
    to `front`, the circle's segment below the chord at `back`, the cap as the disc of the bulb
    where its blackening begins (with a hole of 1 µm in the middle, where the disc's parameters
    would meet). cap False: the trough and its wall alone (the bulb's top is drawn with the bulb)."""
    o = np.asarray(origin, dtype=float)
    lo, hi = shield.window
    span = (hi - lo) % 360.0 or 360.0

    def placed(x: float, yz: np.ndarray) -> np.ndarray:
        return np.column_stack([np.full(len(yz), x), yz[:, 0], yz[:, 1] + shield.axis_z]) + o

    yz, w, knots = _arc(shield.radius, hi, lo + 360.0)              # the part of the circle outside the window
    out = [("shield", _lofted([placed(shield.back, yz), placed(shield.front, yz)], w, knots))]
    if span < 360.0:                                                 # the end wall: the segment, ruled to its chord
        e1, e2 = yz[0], yz[-1]
        chord = e2 - e1
        t = np.clip((yz - e1) @ chord / (chord @ chord), 0.0, 1.0)
        chord_points = e1 + t[:, None] * chord
        out.append(("shield", _lofted([placed(shield.back, chord_points), placed(shield.back, yz)], w, knots)))
    if cap and shield.cap_x is not None:
        yz, w, knots = _arc(1.0, 0.0, 360.0)
        out.append(("cap", _lofted([placed(shield.cap_x, 1e-3 * yz), placed(shield.cap_x, shield.bulb_radius * yz)],
                                   w, knots)))
    return out


# ------------------------------------------------------------------ the bulb
@dataclass(frozen=True)
class Bulb:
    """The bulb's glass about the lamp's reference axis (parallel to X, `axis_z` above the coil's
    centre): a tube of outer `radius` and `wall` from `back` (where it narrows to the pinch: the
    model leaves it open there) to a half sphere whose outer tip lies at `tip`; blackened outside
    from `cap_x` forwards (None: clear)."""

    radius: float
    wall: float
    tip: float
    back: float
    cap_x: float | None = None
    axis_z: float = 0.0
    index: float = QUARTZ

    @property
    def dome_x(self) -> float:
        return self.tip - self.radius

    def inside_glass(self, p: np.ndarray) -> np.ndarray:
        """Which points (n, 3) lie in the glass."""
        x, rho = p[:, 0], np.hypot(p[:, 1], p[:, 2] - self.axis_z)
        from_centre = np.hypot(x - self.dome_x, rho)
        inner = self.radius - self.wall
        tube = (x > self.back) & (x <= self.dome_x) & (rho > inner) & (rho < self.radius)
        dome = (x > self.dome_x) & (from_centre > inner) & (from_centre < self.radius)
        return tube | dome


# Typical bulbs (mm, from the coil's centre), within R37's outlines: outer diameter, wall, tip,
# back end, the black top – (γ3, where its vertex lies on the coil's axis as a share of the coil's
# length from its centre: R37 sheets H7/2, H8/2, H11/2 at the coil's end nearest the reference
# plane, HB4/2 at its centre), "shield" (the H4's cap) or None – and the glass.
_BULBS = {
    "H1": (8.5, 1.0, 14.0, -20.0, None, QUARTZ),
    "H4 (low beam)": (13.0, 1.0, 15.0, -25.0, "shield", QUARTZ),
    "H7": (9.0, 1.0, 14.8, -21.0, (30.0, -0.5), QUARTZ),
    "H8": (9.0, 1.0, 14.0, -21.0, (30.0, -0.5), QUARTZ),
    "H9": (9.0, 1.0, 14.0, -21.0, None, QUARTZ),
    "H11": (9.0, 1.0, 14.0, -21.0, (30.0, -0.5), QUARTZ),
    "HB3": (10.0, 1.0, 14.0, -21.0, None, QUARTZ),
    "HB4": (10.0, 1.0, 14.0, -21.0, (45.0, 0.0), QUARTZ),
    "H3": (10.0, 1.0, 12.0, -15.0, None, QUARTZ),
    "P21W": (26.5, 0.7, 13.2, -14.0, None, HARD_GLASS),
    "PY21W": (26.5, 0.7, 13.2, -14.0, None, HARD_GLASS),
    "R10W": (19.0, 0.6, 11.0, -8.0, None, HARD_GLASS),
    "R5W": (19.0, 0.6, 11.0, -8.0, None, HARD_GLASS),
}
_GENERIC = (10.0, 1.0, 14.0, -20.0, None, QUARTZ)


def bulb_of(lamp: Lamp, diameter: float = 0.0, wall: float = 0.0, coils=()) -> Bulb:
    """The lamp's bulb (typical, see _BULBS; diameter and wall as given if > 0); `coils` and the
    shield must fit into it."""
    d0, w0, tip, back, top, index = _BULBS.get(lamp.name, _GENERIC)
    diameter = diameter if diameter > 0.0 else d0
    wall = wall if wall > 0.0 else w0
    radius = 0.5 * diameter
    if not 0.0 < wall < 0.5 * radius:
        raise ValueError(f"the bulb's wall ({wall:g} mm) must be thinner than a quarter of its diameter")
    axis_z = lamp.shield.axis_z if lamp.shield is not None else 0.0
    dome_x = tip - radius
    if top == "shield":
        cap_x = lamp.shield.cap_x
    elif top is not None:
        angle, vertex = top
        cap_x = min(vertex * lamp.length + radius / math.tan(math.radians(angle)), dome_x)
    else:
        cap_x = None
    bulb = Bulb(radius, wall, tip, back, cap_x, axis_z, index)
    inner = radius - wall
    reach = [abs(float(np.hypot(c.offset[1], c.offset[2] - axis_z))) + 0.5 * c.diameter
             + (0.5 * c.length if abs(c.axis[0]) < 0.5 else 0.0) for c in coils]
    if lamp.shield is not None:
        reach.append(lamp.shield.radius)
    if reach and max(reach) >= inner:
        raise ValueError(f"the coil (or shield) does not fit into a bulb of {diameter:g} mm with a wall of {wall:g} mm")
    front = max([c.offset[0] + 0.5 * c.length * abs(c.axis[0]) + 0.5 * c.diameter for c in coils]
                + ([lamp.shield.front] if lamp.shield is not None else []), default=0.0)
    if front >= tip - wall:
        raise ValueError("the coil (or shield) reaches beyond the bulb's tip")
    return bulb


def _revolved(profile: np.ndarray, weights, knots, degree: int, axis_z: float) -> dict:
    """The surface of revolution of a profile (m, 2) of (x, distance from the axis) about the
    reference axis: u along the profile, v around (an exact circle)."""
    cx = np.array([c[0] for c in _CIRCLE], dtype=float)
    cy = np.array([c[1] for c in _CIRCLE], dtype=float)
    x = np.repeat(profile[:, 0][:, None], 9, axis=1)
    y = profile[:, 1][:, None] * cx[None, :]
    z = profile[:, 1][:, None] * cy[None, :] + axis_z
    pts = np.stack([x, y, z], axis=-1)
    return {"type": "surface", "degree_u": degree, "degree_v": 2, "knots_u": [float(t) for t in knots],
            "knots_v": list(map(float, _CIRCLE_KNOTS)), "num_u": len(profile), "num_v": 9,
            "points": [float(v) for v in pts.reshape(-1)],
            "weights": [float(w) * cw for w in weights for cw in _CIRCLE_W]}


def _line(x0: float, r0: float, x1: float, r1: float, axis_z: float) -> dict:
    return _revolved(np.array([[x0, r0], [x1, r1]]), [1.0, 1.0], [0.0, 0.0, 1.0, 1.0], 1, axis_z)


def _dome(centre_x: float, radius: float, axis_z: float, upto: float = 90.0) -> dict:
    """The zone of the sphere about (centre_x, axis) from its pole (a hole of 1 µm, where the
    parameters would meet) to `upto` degrees from the axis."""
    pole = math.degrees(1e-3 / radius)
    pts, w, knots = _arc(radius, pole, upto)
    return _revolved(np.column_stack([centre_x + pts[:, 0], pts[:, 1]]), w, knots, 2, axis_z)


COATING = 0.02            # mm: the black top lies this far outside the glass


def bulb_faces(bulb: Bulb) -> list[dict]:
    """The glass as one closed shell (normals in any direction – al_trace turns them out of the
    glass): outside and inside, tube and half sphere, and the ring at the back."""
    inner = bulb.radius - bulb.wall
    return [_line(bulb.back, bulb.radius, bulb.dome_x, bulb.radius, bulb.axis_z),
            _dome(bulb.dome_x, bulb.radius, bulb.axis_z),
            _line(bulb.back, inner, bulb.dome_x, inner, bulb.axis_z),
            _dome(bulb.dome_x, inner, bulb.axis_z),
            _line(bulb.back, inner, bulb.back, bulb.radius, bulb.axis_z)]


def top_faces(bulb: Bulb, glass: bool = True) -> list[dict]:
    """The black top: with the glass a coating just outside it from cap_x to the tip, else (no
    glass) the disc across the bulb at cap_x (with a hole of 1 µm in the middle)."""
    if bulb.cap_x is None:
        return []
    if not glass:
        return [_line(bulb.cap_x, 1e-3, bulb.cap_x, bulb.radius, bulb.axis_z)]
    r = bulb.radius + COATING
    out = []
    if bulb.cap_x < bulb.dome_x:
        out.append(_line(bulb.cap_x, r, bulb.dome_x, r, bulb.axis_z))
        upto = 90.0
    else:
        upto = math.degrees(math.acos(min((bulb.cap_x - bulb.dome_x) / bulb.radius, 1.0)))
    out.append(_dome(bulb.dome_x, r, bulb.axis_z, upto))
    return out
