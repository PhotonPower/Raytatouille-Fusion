"""Photometry of the facetted reflector: the filament images on the measuring screen and the
luminous intensity of the low beam with the test points of UN/ECE R112.

Model: the coil is a cylinder whose lateral surface shines evenly in all directions (Lambertian,
luminance L = flux / (π · area)); every mirror point – on the facets and on the connecting faces –
reflects once (reflectance ρ); a step of the mirror may shade a point from the coil or stop its
reflected ray (HeightMap); no light that leaves the lamp directly, no bulb glass, no cover lens.
NumPy only."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from al_optics import Cutoff, Filament, Lamp, screen
from al_reflector import FACET, Reflector


def reflect(d: np.ndarray, n: np.ndarray) -> np.ndarray:
    return d - 2.0 * np.sum(d * n, axis=-1, keepdims=True) * n


def _hull(points: np.ndarray) -> np.ndarray:
    """Convex hull (counter-clockwise) of points (n, 2): Andrew's monotone chain."""
    pts = points[np.lexsort((points[:, 1], points[:, 0]))]

    def half(seq):
        out: list[np.ndarray] = []
        for p in seq:
            while len(out) >= 2:
                a, b = out[-2], out[-1]
                if (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) > 0:
                    break
                out.pop()
            out.append(p)
        return out[:-1]

    return np.array(half(pts) + half(pts[::-1]))


def filament_images(P: np.ndarray, n: np.ndarray, fil: Filament, after=None) -> list[np.ndarray]:
    """The outline of the filament image of every mirror point (position P, normal n): polygons
    (k, 2) of (H, V) in degrees. after(origins, directions) -> directions, factors: a lens."""
    Q = fil.outline_samples(32)
    out = []
    for p, normal in zip(P, n):
        d = p - Q
        d = reflect(d / np.linalg.norm(d, axis=1, keepdims=True), normal)
        d = d[d[:, 0] > 1e-6]
        if after is not None and len(d):
            d, factor, *_ = after(np.repeat(p[None, :], len(d), axis=0), d)
            d = d[(factor > 0.0) & (d[:, 0] > 1e-6)]
        if len(d) < 3:
            continue
        h, v = screen(d)
        out.append(_hull(np.degrees(np.arctan(np.stack([h, v], axis=1)))))
    return out


def draw_images(images: list[np.ndarray], cutoff: Cutoff, h_range=(-30.0, 30.0), v_range=(-12.0, 4.0),
                per_degree: int = 20) -> tuple[np.ndarray, int, int]:
    """A picture of the outlines (value 1 per outline, they add up) with the cut-off line (value
    -1 … drawn last): values[j * width + i], row 0 at the lowest V."""
    width = int(round((h_range[1] - h_range[0]) * per_degree))
    height = int(round((v_range[1] - v_range[0]) * per_degree))
    img = np.zeros((height, width))

    def plot(hv: np.ndarray, value: float, add: bool) -> None:
        i = np.floor((hv[:, 0] - h_range[0]) * per_degree).astype(int)
        j = np.floor((hv[:, 1] - v_range[0]) * per_degree).astype(int)
        ok = (i >= 0) & (i < width) & (j >= 0) & (j < height)
        flat = np.unique(j[ok] * width + i[ok])
        if add:
            img.reshape(-1)[flat] += value
        else:
            img.reshape(-1)[flat] = value

    for poly in images:
        closed = np.vstack([poly, poly[:1]])
        seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
        pts = [a + (b - a) * np.linspace(0.0, 1.0, max(2, int(s * per_degree * 2) + 1))[:, None]
               for a, b, s in zip(closed[:-1], closed[1:], seg)]
        plot(np.concatenate(pts), 1.0, True)
    H = np.linspace(h_range[0], h_range[1], width * 2)
    V = np.degrees(np.arctan(cutoff.line(np.tan(np.radians(H)))))
    plot(np.stack([H, V], axis=1), float(img.max()) * 1.25 + 1.0, False)
    return img.reshape(-1), width, height


# ------------------------------------------------------------------ luminous intensity
@dataclass
class Distribution:
    """Luminous intensity I (cd) over H x V in degrees: intensity[j, i] at (h[i], v[j])."""

    h: np.ndarray
    v: np.ndarray
    intensity: np.ndarray
    flux_beam: float               # lm in the beam (all directions forward)
    flux_mirror: float             # lm that reach the mirror
    flux_lamp: float
    flux_connections: float = 0.0  # lm of the beam that come from the connecting faces
    flux_walls: float = 0.0        # lm that meet the walls between the elements of a lens (what of it goes
                                   # on into the beam, as stray light, is part of flux_connections)
    flux_shadow: float = 0.0       # lm onto the mirror that a step of the mirror stops (before or after the
                                   # reflection; what leaves after a second reflection is part of flux_connections)

    def at(self, h_deg: float, v_deg: float, half_h: float = 0.25, half_v: float = 0.1) -> float:
        """Mean intensity in a small window about a point (a photometer's aperture)."""
        i = (self.h >= h_deg - half_h) & (self.h <= h_deg + half_h)
        j = (self.v >= v_deg - half_v) & (self.v <= v_deg + half_v)
        if not i.any() or not j.any():
            return float("nan")
        return float(self.intensity[np.ix_(j, i)].mean())

    def lux_25m(self) -> np.ndarray:
        return self.intensity / 625.0

    def measured(self, half_h: float = 0.25, half_v: float = 0.1) -> np.ndarray:
        """The intensity as a photometer sees it: at every point the mean over the window of at()."""
        ni = max(0, int(round(half_h / (self.h[1] - self.h[0]) - 0.5)))
        nj = max(0, int(round(half_v / (self.v[1] - self.v[0]) - 0.5)))
        padded = np.pad(self.intensity, ((nj, nj), (ni, ni)), mode="edge")
        out = np.zeros_like(self.intensity)
        for dj in range(2 * nj + 1):
            for di in range(2 * ni + 1):
                out += padded[dj:dj + len(self.v), di:di + len(self.h)]
        return out / ((2 * nj + 1) * (2 * ni + 1))


class HeightMap:
    """x of the whole mirror on a front-view lattice, to tell whether a ray from or to a mirror point
    runs into a step of the mirror on its way."""

    REACH = (0.2, 0.4, 0.8, 1.6, 3.2, 6.4)      # mm sideways from the point: where a ray is compared with the mirror
    CLEAR = 0.02                                # mm: a ray counts as stopped when the mirror stands this far above it

    def __init__(self, reflector: Reflector, pitch: float = 0.25):
        P = reflector.samples(pitch)[0]
        self.pitch = pitch
        i = np.rint(P[:, 1] / pitch - 0.5).astype(int)
        j = np.rint(P[:, 2] / pitch - 0.5).astype(int)
        self.i0, self.j0 = int(i.min()) - 1, int(j.min()) - 1
        self.x = np.zeros((int(i.max()) - self.i0 + 2, int(j.max()) - self.j0 + 2))
        self.known = np.zeros(self.x.shape, dtype=bool)
        self.x[i - self.i0, j - self.j0] = P[:, 0]
        self.known[i - self.i0, j - self.j0] = True

    def at(self, y, z) -> np.ndarray:
        """x of the mirror at points (bilinear); -inf where there is no mirror."""
        fy = np.asarray(y, dtype=float) / self.pitch - 0.5 - self.i0
        fz = np.asarray(z, dtype=float) / self.pitch - 0.5 - self.j0
        i = np.clip(np.floor(fy).astype(int), 0, self.x.shape[0] - 2)
        j = np.clip(np.floor(fz).astype(int), 0, self.x.shape[1] - 2)
        a, b = fy - i, fz - j
        inside = (a >= 0.0) & (a <= 1.0) & (b >= 0.0) & (b <= 1.0) & self.known[i, j] & self.known[i + 1, j] \
            & self.known[i, j + 1] & self.known[i + 1, j + 1]
        x = (1 - a) * (1 - b) * self.x[i, j] + a * (1 - b) * self.x[i + 1, j] + (1 - a) * b * self.x[i, j + 1] \
            + a * b * self.x[i + 1, j + 1]
        return np.where(inside, x, -np.inf)

    def stopped(self, p: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Whether rays from the mirror points p (m, 3) along the unit directions v (m, k, 3) run
        into the mirror within REACH sideways: (m, k)."""
        sideways = np.maximum(np.hypot(v[..., 1], v[..., 2]), 1e-9)
        out = np.zeros(v.shape[:2], dtype=bool)
        for reach in self.REACH:
            tau = np.minimum(reach / sideways, 40.0)
            out |= self.at(p[:, None, 1] + tau * v[..., 1], p[:, None, 2] + tau * v[..., 2]) \
                > p[:, None, 0] + tau * v[..., 0] + self.CLEAR
        return out


    def bounce(self, p: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Rays from the mirror points p (n, 3) along v (n, 3) that the mirror stops: where they
        meet it they are reflected a second time. Returns which of them then leave the mirror freely
        and forwards, and their new directions."""
        sideways = np.maximum(np.hypot(v[:, 1], v[:, 2]), 1e-9)

        def above(tau):      # how far the mirror stands above the ray there
            return self.at(p[:, 1] + tau * v[:, 1], p[:, 2] + tau * v[:, 2]) - (p[:, 0] + tau * v[:, 0])

        free, inside = np.zeros(len(p)), np.full(len(p), np.nan)
        for reach in self.REACH:                                # the first place where the ray is in the mirror
            tau = np.minimum(reach / sideways, 40.0)
            hit = np.isnan(inside) & (above(tau) > self.CLEAR)
            inside = np.where(hit, tau, inside)
            free = np.where(np.isnan(inside), tau, free)
        found = ~np.isnan(inside)
        inside = np.where(found, inside, free)
        for _ in range(12):                                     # the point where it enters, by halving
            middle = 0.5 * (free + inside)
            within = above(middle) > 0.0
            inside, free = np.where(within, middle, inside), np.where(within, free, middle)
        y, z = p[:, 1] + free * v[:, 1], p[:, 2] + free * v[:, 2]
        h = self.pitch
        with np.errstate(invalid="ignore"):                     # (beside the mirror: no slope, no reflection)
            gy = (self.at(y + h, z) - self.at(y - h, z)) / (2.0 * h)
            gz = (self.at(y, z + h) - self.at(y, z - h)) / (2.0 * h)
        found &= np.isfinite(gy) & np.isfinite(gz)
        gy, gz = np.where(found, gy, 0.0), np.where(found, gz, 0.0)
        normal = np.stack([np.ones_like(gy), -gy, -gz], axis=1)
        normal /= np.linalg.norm(normal, axis=1, keepdims=True)
        again = v - 2.0 * np.sum(v * normal, axis=1, keepdims=True) * normal
        where = np.column_stack([p[:, 0] + free * v[:, 0], y, z]) + 0.05 * normal
        found &= (np.sum(v * normal, axis=1) < 0.0) & (again[:, 0] > 1e-6)
        found &= ~self.stopped(where, again[:, None, :])[:, 0]
        return found, again


def light_distribution(reflector: Reflector, *, spacing: float = 1.0, reflectance: float = 0.85,
                       reflectance_connections: float | None = None, shadows: bool = False,
                       **options) -> Distribution:
    """The luminous intensity of the facetted reflector by rays from every sample of the coil's
    surface to every mirror point of a front-view lattice (`spacing`, mm); `shadows`: a ray that a
    step of the mirror stops on its way from the coil is left out, one that it stops after the
    reflection is reflected there a second time (with the reflectance of the connecting faces) and
    counts as stray light if it then leaves freely; options as intensity()."""
    if shadows and reflector.transitions is not None:
        if getattr(reflector, "_height_map", None) is None:
            reflector._height_map = HeightMap(reflector)
        options["stopped"] = reflector._height_map.stopped
        options["bounce"] = reflector._height_map.bounce
        options["rho_second"] = reflectance if reflectance_connections is None else reflectance_connections
    P, N, A, part = reflector.samples(spacing)
    connection = np.array([p.kind != FACET for p in reflector.parts()], dtype=bool)[part] if len(part) else part
    rho = np.where(connection, reflectance if reflectance_connections is None else reflectance_connections,
                   reflectance)
    return intensity(reflector.settings.lamp, reflector.filament, P, N, A, rho, connection, **options)


def intensity(lamp: Lamp, fil: Filament, P: np.ndarray, N: np.ndarray, A: np.ndarray, rho: np.ndarray,
              connection: np.ndarray | None = None, *, after=None, stopped=None, bounce=None,
              rho_second: float = 0.0, n_axial: int = 12, n_around: int = 24,
              h_range=(-40.0, 40.0), v_range=(-15.0, 10.0), dh: float = 0.25, dv: float = 0.1,
              progress=None) -> Distribution:
    """The luminous intensity of a mirror given by points P, unit normals N, areas A and reflectances
    rho: rays from every sample of the coil's surface to every mirror point. `connection`: points
    whose light is counted as stray light of connecting faces; after(origins, directions) ->
    directions, factors[, walls]: what follows the mirror (a lens), factor 0 for a lost ray, and
    optionally which rays met a wall there; stopped(points, directions (m, k, 3)) -> (m, k): rays
    from the mirror points that the mirror itself stops (HeightMap.stopped); bounce(points,
    directions (n, 3)) -> found, directions: the second reflection of reflected rays it stops
    (HeightMap.bounce), which keeps `rho_second` of their light."""
    if connection is None:
        connection = np.zeros(len(P), dtype=bool)
    flux_connections = flux_walls = flux_shadow = 0.0
    Q, nu, dA = fil.surface_samples(n_axial, n_around)
    luminance = lamp.flux / (math.pi * dA * len(Q))        # lm / (sr mm²)
    nh = int(round((h_range[1] - h_range[0]) / dh))
    nv = int(round((v_range[1] - v_range[0]) / dv))
    flux = np.zeros(nv * nh)
    flux_mirror = flux_beam = 0.0
    chunk = max(1, 120_000 // len(Q))
    for start in range(0, len(P), chunk):
        if progress is not None:
            progress(start / max(len(P), 1), "tracing …")
        p, n, a = P[start:start + chunk], N[start:start + chunk], A[start:start + chunk]
        d = p[:, None, :] - Q[None, :, :]
        r2 = np.einsum("mki,mki->mk", d, d)
        d /= np.sqrt(r2)[..., None]
        cos_q = np.einsum("mki,ki->mk", d, nu)
        cos_p = -np.einsum("mki,mi->mk", d, n)
        w = luminance * dA * a[:, None] * np.clip(cos_q, 0.0, None) * np.clip(cos_p, 0.0, None) / r2
        if lamp.shield is not None:          # the shield under the coil and the cap on the bulb's tip
            w = np.where(lamp.shield.passes(Q, d), w, 0.0)
        flux_mirror += float(w.sum())
        out = d - 2.0 * np.einsum("mki,mi->mk", d, n)[..., None] * n[:, None, :]
        twice = None
        if stopped is not None:      # in the shadow of a step as seen from the coil, or the reflected ray meets one
            shaded = (w > 0.0) & stopped(p, -d)
            caught = (w > 0.0) & ~shaded & stopped(p, out)
            flux_shadow += float(w[shaded | caught].sum())
            w = np.where(shaded, 0.0, w)
            if bounce is not None and caught.any():      # a second reflection where the ray meets the step
                rows, cols = np.nonzero(caught)
                found, again = bounce(p[rows], out[rows, cols])
                out[rows, cols] = again
                w[rows, cols] *= np.where(found, rho_second, 0.0)
                twice = caught
            else:
                w = np.where(caught, 0.0, w)
        ok = (out[..., 0] > 1e-6) & (w > 0.0)
        w = w * rho[start:start + chunk, None]
        if twice is not None:
            flux_connections += float(w[twice & ok].sum())
        if after is not None:
            rows = np.nonzero(ok)[0]
            passed, factor, *walls = after(p[rows], out[ok])
            if walls:        # what meets the walls of a lens, and what of it goes on as stray light
                flux_walls += float(w[ok][walls[0]].sum())
                flux_connections += float((w[ok] * factor)[walls[0] & (passed[:, 0] > 1e-6)].sum())
            out[ok] = passed
            w[ok] *= factor
            ok &= (w > 0.0) & (out[..., 0] > 1e-6)
        flux_connections += float((w * ok)[connection[start:start + chunk]].sum())
        w, out = w[ok], out[ok]
        flux_beam += float(w.sum())
        H = np.degrees(np.arctan(-out[:, 1] / out[:, 0]))
        V = np.degrees(np.arctan(out[:, 2] / out[:, 0]))
        i = np.floor((H - h_range[0]) / dh).astype(int)
        j = np.floor((V - v_range[0]) / dv).astype(int)
        inside = (i >= 0) & (i < nh) & (j >= 0) & (j < nv)
        flux += np.bincount(j[inside] * nh + i[inside], weights=w[inside], minlength=nv * nh)
    h = h_range[0] + (np.arange(nh) + 0.5) * dh
    v = v_range[0] + (np.arange(nv) + 0.5) * dv
    th, tv = np.tan(np.radians(h))[None, :], np.tan(np.radians(v))[:, None]
    # solid angle of a cell: dh dv / (1 + h² + v²)^(3/2) in the tangents, dh = dH / cos² H
    omega = (math.radians(dh) * (1 + th ** 2)) * (math.radians(dv) * (1 + tv ** 2)) / (1 + th ** 2 + tv ** 2) ** 1.5
    return Distribution(h, v, flux.reshape(nv, nh) / omega, flux_beam, flux_mirror, lamp.flux, flux_connections,
                        flux_walls, flux_shadow)


# ------------------------------------------------------------------ UN/ECE R112, class B passing beam
@dataclass(frozen=True)
class TestPoint:
    name: str
    h: float           # degrees, positive to the right (right-hand traffic)
    v: float
    minimum: float | None    # cd
    maximum: float | None


# Luminous intensities of UN/ECE R112, paragraph 6.2.4 (class B headlamp, passing beam, right-hand
# traffic; mirrored about V-V for left-hand traffic). The regulation decides, not this table.
R112_CLASS_B = (
    TestPoint("B50L", -3.43, 0.57, None, 350.0),
    TestPoint("BR", 2.5, 1.0, None, 1750.0),
    TestPoint("75R", 1.15, -0.57, 10100.0, None),
    TestPoint("75L", -3.43, -0.57, None, 10600.0),
    TestPoint("50L", -3.43, -0.86, None, 13200.0),
    TestPoint("50R", 1.72, -0.86, 10100.0, None),
    TestPoint("50V", 0.0, -0.86, 5100.0, None),
    TestPoint("25L", -9.0, -1.72, 1700.0, None),
    TestPoint("25R", 9.0, -1.72, 1700.0, None),
)
ZONE_III = ((-8.0, 1.0), (-8.0, 4.0), (8.0, 4.0), (8.0, 2.0), (6.0, 1.5), (1.5, 1.5), (0.0, 0.0), (-4.0, 0.0))
ZONE_III_MAX = 625.0
ZONE_IV = (-5.15, 5.15, -1.72, -0.86)     # H from, to, V from, to
ZONE_IV_MIN = 2500.0


def _inside(poly, h: np.ndarray, v: np.ndarray) -> np.ndarray:
    inside = np.zeros(h.shape, dtype=bool)
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        if ay != by:
            inside ^= ((ay > v) != (by > v)) & (h < (bx - ax) * (v - ay) / (by - ay) + ax)
    return inside


def test_points(dist: Distribution, cutoff: Cutoff) -> list[list]:
    """Rows name, H, V, intensity / cd, E at 25 m / lx, requirement, verdict – the test points and
    the zones III (maximum in it) and IV (minimum in it, of the mean over a photometer window)."""
    sign = 1.0 if cutoff.right_hand_traffic else -1.0
    rows = []
    for tp in R112_CLASS_B:
        value = dist.at(sign * tp.h, tp.v)
        if tp.minimum is not None:
            need, ok = f"≥ {tp.minimum:.0f} cd", value >= tp.minimum
        else:
            need, ok = f"≤ {tp.maximum:.0f} cd", value <= tp.maximum
        rows.append([tp.name, sign * tp.h, tp.v, round(value, 1), round(value / 625.0, 2), need,
                     "ok" if ok else "not met"])
    H, V = np.meshgrid(dist.h, dist.v)
    zone3 = _inside([(sign * h, v) for h, v in ZONE_III], H, V)
    if zone3.any():
        value = float(dist.measured()[zone3].max())
        rows.append(["zone III", "", "", round(value, 1), round(value / 625.0, 2), f"≤ {ZONE_III_MAX:.0f} cd",
                     "ok" if value <= ZONE_III_MAX else "not met"])
    hs = dist.h[(dist.h >= ZONE_IV[0]) & (dist.h <= ZONE_IV[1])][::2]
    vs = dist.v[(dist.v >= ZONE_IV[2]) & (dist.v <= ZONE_IV[3])][::2]
    if len(hs) and len(vs):
        value = min(dist.at(h, v) for h in hs for v in vs)
        rows.append(["zone IV", "", "", round(value, 1), round(value / 625.0, 2), f"≥ {ZONE_IV_MIN:.0f} cd",
                     "ok" if value >= ZONE_IV_MIN else "not met"])
    return rows


# ------------------------------------------------------------------ UN R148: light-signalling lamps
# Standard light distributions (Annex 3): H, V in degrees and the percentage of the minimum
# intensity required on the axis; and that minimum and the maximum in any direction for a single
# lamp (Tables 3, 4, 6, 7, 8), cd. The regulation decides, not these tables.
_STANDARD = tuple([(h, v, 20.0) for v in (10.0, -10.0) for h in (-5.0, 5.0)]
                  + [(h, v, pct) for v in (5.0, -5.0) for h, pct in ((-20.0, 10.0), (-10.0, 20.0), (0.0, 70.0),
                                                                    (10.0, 20.0), (20.0, 10.0))]
                  + [(-10.0, 0.0, 35.0), (-5.0, 0.0, 90.0), (0.0, 0.0, 100.0), (5.0, 0.0, 90.0), (10.0, 0.0, 35.0)])
_DAYTIME = tuple([(h, 10.0, 20.0) for h in (-5.0, 0.0, 5.0)]
                 + [(h, v, pct) for v in (5.0, -5.0) for h, pct in ((-20.0, 10.0), (-10.0, 20.0), (0.0, 70.0),
                                                                   (10.0, 20.0), (20.0, 10.0))]
                 + [(-20.0, 0.0, 25.0), (-10.0, 0.0, 70.0), (-5.0, 0.0, 90.0), (0.0, 0.0, 100.0), (5.0, 0.0, 90.0),
                    (10.0, 0.0, 70.0), (20.0, 0.0, 25.0)])
SIGNAL_LAMPS: dict[str, tuple[float, float, tuple]] = {
    "front position lamp (A)": (4.0, 140.0, _STANDARD),
    "rear position lamp (R1)": (4.0, 17.0, _STANDARD),
    "stop lamp (S1)": (60.0, 260.0, _STANDARD),
    "direction indicator, front (1)": (175.0, 1000.0, _STANDARD),
    "direction indicator, rear (2a)": (50.0, 500.0, _STANDARD),
    "daytime running lamp (RL)": (400.0, 1200.0, _DAYTIME),
}


def signal_points(dist: Distribution, function: str, half: float = 0.5) -> list[list]:
    """Rows point, H, V, intensity / cd, required, verdict for a light-signalling lamp of UN R148:
    the points of its standard light distribution (the mean over ± `half` degrees) and the highest
    intensity in any direction."""
    minimum, maximum, grid = SIGNAL_LAMPS[function]
    rows = []
    for h, v, percent in sorted(grid, key=lambda g: (-g[1], g[0])):
        value = dist.at(h, v, half, half)
        need = minimum * percent / 100.0
        name = f"{abs(h):g}°{'L' if h < 0 else 'R' if h > 0 else ''} {abs(v):g}°{'U' if v > 0 else 'D' if v < 0 else ''}"
        rows.append([name.strip(), h, v, round(value, 2), f"≥ {need:g} cd ({percent:g} %)", "ok" if value >= need else "not met"])
    top = float(dist.measured(half, half).max())
    rows.append(["maximum", "", "", round(top, 2), f"≤ {maximum:g} cd", "ok" if top <= maximum else "not met"])
    return rows


def glare(dist: Distribution, cutoff: Cutoff, clearance: float = 0.2) -> float:
    """The highest intensity (cd, over a photometer's window) more than `clearance` degrees above
    the cut-off line."""
    line = np.degrees(np.arctan(cutoff.line(np.tan(np.radians(dist.h)))))
    above = dist.v[:, None] > line[None, :] + clearance + 0.1
    return float(dist.measured()[above].max()) if above.any() else 0.0


def sharpness(dist: Distribution, cutoff: Cutoff, h_deg: float = 2.5) -> tuple[float, float]:
    """The cut-off as R112 measures it, on the vertical line `h_deg` on the side of the oncoming
    traffic: G = log I(V) - log I(V + 0.1°), its maximum within 2° of the nominal cut-off and the V
    where it lies (degrees). Only where I(V) is at least 2 % of the line's maximum: the weak stray
    light above the cut-off is noisy in this computation and is no cut-off."""
    h = -h_deg if cutoff.right_hand_traffic else h_deg
    cols = (dist.h >= h - 0.5) & (dist.h <= h + 0.5)
    profile = dist.intensity[:, cols].mean(axis=1)
    dv = dist.v[1] - dist.v[0]
    step = max(1, int(round(0.1 / dv)))
    top = float(profile.max())
    if top <= 0.0:
        return 0.0, float("nan")
    logs = np.log10(np.maximum(profile, 1e-3 * top))
    g = logs[:-step] - logs[step:]
    valid = (np.abs(dist.v[:-step] + 0.5 * step * dv - cutoff.v_deg) <= 2.0) & (profile[:-step] >= 0.02 * top)
    if not valid.any():
        return 0.0, float("nan")
    k = int(np.argmax(np.where(valid, g, -np.inf)))
    return float(g[k]), float(dist.v[k] + 0.5 * step * dv)
