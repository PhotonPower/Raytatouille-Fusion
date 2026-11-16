"""What the ray tracing (al_trace) sees of a filament lamp: the coil as it is – a helix of
tungsten wire – and what inside the lamp stops its light (the H4's shield and cap), as NURBS
surfaces in design coordinates. The design and the filament images keep the cylinder of
al_optics.Filament.

The coil fills the cylinder of the lamp (length, diameter): the wire's centre runs on a helix
of radius (diameter − wire) / 2 from one end to the other. Its wire diameter and number of
turns are not in UN/ECE R37; without own values they are estimated from the lamp's power:
a tungsten wire at 3100 K (resistivity 95.6 µΩ cm, interpolated between 3000 K and 3200 K in
Desai et al., J. Phys. Chem. Ref. Data 13 (1984) 1069) at the test voltage 13.2 V, the power
rising as (U / 12 V)^1.6, wound with a pitch of 1.5 wire diameters. That gives 0.16 mm and 16
turns for an H7, 0.19 mm and 19 turns for an H4 – the range of real coils of such lamps.

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


@dataclass(frozen=True)
class Coil:
    """A helix of wire about the filament's axis through the origin: `turns` turns from one end of
    the cylinder (length, diameter) to the other, the wire's surface touching it."""

    length: float           # mm, outer length (the lamp's filament length)
    diameter: float         # mm, outer diameter
    wire: float             # mm, wire diameter
    turns: int
    axis: tuple             # unit vector along the coil

    @property
    def helix_radius(self) -> float:
        return 0.5 * (self.diameter - self.wire)

    @property
    def pitch(self) -> float:
        return (self.length - self.wire) / self.turns

    @property
    def wire_length(self) -> float:
        return self.turns * math.hypot(2.0 * math.pi * self.helix_radius, self.pitch)

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
        return along[:, None] * a + (r * np.cos(phi))[:, None] * e1 + (r * np.sin(phi))[:, None] * e2


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


def coil_of(lamp: Lamp, fil: Filament, wire: float = 0.0, turns: int = 0) -> Coil:
    """The coil of the lamp: wire diameter and turns as given, else estimated (see the module)."""
    if wire <= 0.0:
        if lamp.watts <= 0.0:
            raise ValueError(f"{lamp.name}: give the coil's wire diameter (its power is not known)")
        wire = estimated_wire(lamp.length, lamp.diameter, lamp.watts)
    if not wire < 0.5 * lamp.diameter:
        raise ValueError(f"the wire ({wire:g} mm) must be thinner than half the coil's diameter ({lamp.diameter:g} mm)")
    if turns <= 0:
        turns = max(1, round((lamp.length - wire) / (PITCH * wire)))
    coil = Coil(lamp.length, lamp.diameter, wire, int(turns), tuple(float(c) for c in fil.axis))
    if coil.pitch < wire * 1.02:
        raise ValueError(f"{turns} turns of {wire:g} mm wire do not fit into {lamp.length:g} mm: the turns would touch")
    return coil


# ------------------------------------------------------------------ NURBS
_CIRCLE = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0)]
_CIRCLE_W = [1.0, math.sqrt(0.5)] * 4 + [1.0]
_CIRCLE_KNOTS = [0, 0, 0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1, 1, 1]


def coil_faces(coil: Coil, origin=(0.0, 0.0, 0.0)) -> list[dict]:
    """The wire's surface as one face per turn: a tube about the helix – cubic along the wire
    (interpolating the helix and a frame across it), an exact circle around it. The normals
    point out of the wire."""
    a, _, _ = coil.frame()
    r = 0.5 * coil.wire
    n = PER_TURN + 3
    knots = al_spline.clamped_uniform_knots(n, 3, 0.0, 1.0)
    sites = al_spline.greville(knots, n, 3)
    solve = np.linalg.inv(al_spline.basis_matrix(knots, n, 3, sites))
    out = []
    for k in range(coil.turns):
        phi = 2.0 * math.pi * (k + sites)
        c = coil.centre(phi)
        radial = c - (c @ a)[:, None] * a                            # across the axis: out of the coil
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


def shield_faces(shield: Shield, origin=(0.0, 0.0, 0.0)) -> list[tuple[str, dict]]:
    """("shield", face) for the trough and its end wall, ("cap", face) for the cap on the bulb's
    tip – as Shield.passes sees them: the cylinder of the trough outside the window from `back`
    to `front`, the circle's segment below the chord at `back`, the cap as the disc of the bulb
    where its blackening begins (with a hole of 1 µm in the middle, where the disc's parameters
    would meet)."""
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
    if shield.cap_x is not None:
        yz, w, knots = _arc(1.0, 0.0, 360.0)
        out.append(("cap", _lofted([placed(shield.cap_x, 1e-3 * yz), placed(shield.cap_x, shield.bulb_radius * yz)],
                                   w, knots)))
    return out
