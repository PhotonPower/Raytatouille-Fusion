"""The elements of a patterned lens chosen cell by cell, so that the beam meets the test points of
UN/ECE R112 (class B passing beam) with a margin – for a lamp whose cut-off its own shield makes
(H4): the mirror and the shield form the cut-off, the lens spreads the light below it. Every cell
is a prism (deflect H, V) with a cylinder lens on it whose strength (the spread) and direction
(the angle its spread rises by on the screen) are chosen – as the facets of a clear-lens
reflector lay their filament images along the cut-off: horizontally beneath its horizontal part,
along 15° beneath its rise, steeper into the foreground.

The surrogate. Light reaches a cell of the plane lens from the mirror: rays from samples of the
coil's surface to the mirror's points, reflected, through the cell – their directions binned on a
grid of the screen (0.5° x 0.1°), one pattern per cell. An element turns the light of its middle
by (deflect H, deflect V) and that of the rest by up to ± the spread more along the spread's
direction, linearly across the cell (al_lens): its pattern is the plane cell's, shifted by the
deflection and smeared along that line as the cell's points spread – evenly for a horizontal or
vertical line, as a trapezoid for a slanting one (a rectangle's points along a slanting line: two
boxes in a row). The beam is the sum of the cells' patterns and the lamp's direct light (through
the plane lens).

The objective, at the test points' windows and the zones' bins (luminous intensities):

    Σ (shortfall below (1 + m) min / min)² + Σ (excess above (1 − m) max / max)²      (m: margin)
    − ε softmin(value / minimum, maximum / value; each up to 2) + λ Σ cells (|deflection| + |spread|)

– squared shortfalls and excesses, then the weakest requirement raised (the smallest margin made
as large as can be), gentle elements where nothing depends on them. Zone I (the foreground) may
have at most twice the intensity at 50R. It is minimised one cell at a time: its deflection over
all choices with its cylinder kept, then its cylinder (strength and direction) with the deflection
kept; sweeps over all cells until no cell changes. The surrogate differs from the lens built (the elements are fitted
patches, steps between them stray light, the coil is no point): `rounds` times the lens is built,
its light distribution taken with the full model (evaluate) and half the difference carried into
the surrogate before it is optimised again; the best round is kept. The lamp as it is (helix,
bulb) is softer than the filament images: with a Gaussian blur fitted on the plane lens
(fit_blur) the beam is judged in two views, as the filament images have it and blurred – every
lower limit in the darker of the two, every upper limit in the brighter. NumPy only."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

import al_layout
import al_lens
import al_photometry
from al_design import DesignError
from al_optics import HORIZONTAL, RISING, Cutoff

DH, DV = 0.5, 0.1                                  # degrees: the surrogate's grid
H_RANGE, V_RANGE = (-45.0, 45.0), (-12.0, 6.0)
DEFLECT_H = np.arange(-16.0, 16.01, 1.0)
DEFLECT_V = np.round(np.arange(-3.0, 0.61, 0.2), 6)
SPREAD = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0])        # the cylinder's ± spread
ANGLE = np.array([-60.0, -45.0, -30.0, -20.0, -15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0])
REACH = 22.0                                       # degrees: |deflect H| + the spread's H part at most (the patches' slope)
REACH_V = 4.0                                      # degrees: the spread's V part at most
EPSILON, LAMBDA = 0.02, 2e-6
NEAR = 3                                           # after the first sweep: deflections this many steps away
SWEEPS, LATER = 8, 3                               # sweeps at most: the first round, the later ones
DEPTH = 0.85                                       # share of the lens' thickness (less 0.3 mm) the elements may take
DAMPING = 0.5                                      # share of the full model's difference carried back per round
STEP = 0.1                                         # the cut-off's fall where R112 measures it
RISE_H = (1.0, 5.0)                                # degrees from the kink: where the rising branch is lit and sharp
BAND_H = 10.0                                      # degrees about the kink: the band under the cut-off
BAND_V = (0.15, 0.65)                              # degrees under the line: the band (and the rising branch's: the upper part)
REAL = 0.2                                         # the weight of a real beam's requirements (band, rise) against R112's
CHECKS = 2                                         # rounds with what the ray tracing adds (check)
CHECK_BLUR = (0.5, 0.3)                             # degrees: what the ray tracing adds, smoothed so (its noise)
FIELD_H, FIELD_V = 20.0, -5.0                      # degrees: the beam judged for its evenness: |H| ≤ 20°, V ≥ −5° …
FIELD_GAP = 0.4                                    # … up to this far below the cut-off line
BUMP_H, BUMP_V = 2, 3                              # bins (1°, 0.3°): the field's lattice, the scale of the bumps counted
ABOVE = 0.3                                        # degrees above the cut-off from which it must be dark
RISING_SHARE = 0.5                                 # a cell whose light lies this much above the horizontal branch: its edge rises
ALONG = 0.15                                       # degrees: a rising cell's deflection at most this far off its edge's line


@dataclass
class Rays:
    """The light of the plane lens' cells (their parts in the sectors): per ray its cell (index into
    `cells`), H, V (degrees), flux (lm) and where it meets the lens (y, z mm)."""

    cells: list                                    # (i, j, sector) of the lens' grid
    cell: np.ndarray
    H: np.ndarray
    V: np.ndarray
    flux: np.ndarray
    y: np.ndarray | None = None
    z: np.ndarray | None = None

    def regrouped(self, system: al_lens.LensSystem) -> "Rays":
        """The same light by the cells (parts) of `system` – the same lens cut otherwise."""
        iy, iz, k, inside = system.part(self.y.astype(float), self.z.astype(float))
        cells = [tuple(int(c) for c in x) for x in np.argwhere(system.used)]
        index = -np.ones(system.used.shape, dtype=np.int64)
        for n, c in enumerate(cells):
            index[c] = n
        keep = np.flatnonzero(inside)
        cell = index[iy[keep], iz[keep], k[keep]]
        keep, cell = keep[cell >= 0], cell[cell >= 0]
        return Rays(cells, cell, self.H[keep], self.V[keep], self.flux[keep], self.y[keep], self.z[keep])


def lens_rays(system: al_lens.LensSystem, *, spacing: float = 1.0, reflectance: float = 0.85,
              transmittance: float = 0.92, n_axial: int = 8, n_around: int = 16, progress=None) -> Rays:
    """Rays from every sample of the coil's surface by way of every mirror point (as
    al_photometry.intensity) to the inner side of the lens: the cell each meets and the direction it
    leaves the plane lens in (a plate: unchanged)."""
    s = system.settings
    lamp, fil = s.lamp, system.filament
    P, N, A = system.samples(spacing)
    Q, nu, dA = fil.surface_samples(n_axial, n_around)
    luminance = lamp.flux / (math.pi * dA * len(Q))
    index = -np.ones(system.used.shape, dtype=np.int64)
    cells = [tuple(int(k) for k in c) for c in np.argwhere(system.used)]     # (i, j, sector)
    for k, c in enumerate(cells):
        index[c] = k
    parts = []
    chunk = max(1, 120_000 // len(Q))
    for start in range(0, len(P), chunk):
        if progress is not None:
            progress(start / len(P), "the light of the lens' cells …")
        p, n, a = P[start:start + chunk], N[start:start + chunk], A[start:start + chunk]
        d = p[:, None, :] - Q[None, :, :]
        r2 = np.einsum("mki,mki->mk", d, d)
        d /= np.sqrt(r2)[..., None]
        w = luminance * dA * a[:, None] * np.clip(np.einsum("mki,ki->mk", d, nu), 0.0, None) \
            * np.clip(-np.einsum("mki,mi->mk", d, n), 0.0, None) / r2
        if lamp.shield is not None:
            w = np.where(lamp.shield.passes(Q, d), w, 0.0)
        out = d - 2.0 * np.einsum("mki,mi->mk", d, n)[..., None] * n[:, None, :]
        ok = (out[..., 0] > 1e-6) & (w > 0.0)
        rows = np.nonzero(ok)[0]
        o, dd, ww = p[rows], out[ok], w[ok] * reflectance * transmittance
        t = np.maximum((s.lens_x - o[:, 0]) / dd[:, 0], 0.0)
        for _ in range(3):                                                  # onto the lens' shape
            y, z = o[:, 1] + t * dd[:, 1], o[:, 2] + t * dd[:, 2]
            t = np.maximum((s.lens_x + system.shape(y, z)[0] - o[:, 0]) / dd[:, 0], 0.0)
        y, z = o[:, 1] + t * dd[:, 1], o[:, 2] + t * dd[:, 2]
        iy, iz, sector, inside = system.part(y, z)
        cut = np.flatnonzero(inside & ~system.whole[np.clip(iy, 0, system.ny - 1), np.clip(iz, 0, system.nz - 1)])
        if len(cut):
            inside[cut] = al_layout.contains(system._outline, np.column_stack([y[cut], z[cut]]))
        keep = np.flatnonzero(inside)
        parts.append((index[iy[keep], iz[keep], sector[keep]], np.degrees(np.arctan(-dd[keep, 1] / dd[keep, 0])),
                      np.degrees(np.arctan(dd[keep, 2] / dd[keep, 0])), ww[keep], y[keep], z[keep]))
    cell, H, V, flux, y, z = (np.concatenate([q[k] for q in parts]) for k in range(6))
    return Rays(cells, cell, H.astype(np.float32), V.astype(np.float32), flux.astype(np.float32),
                y.astype(np.float32), z.astype(np.float32))


# ------------------------------------------------------------------ the objective
@dataclass(frozen=True)
class Group:
    """Probes judged together: a test point (the mean of its bins) or a zone (every bin), at least
    `low` and at most `high` cd – or at most `factor` x the value of the group `relative`."""

    name: str
    at: np.ndarray                                  # positions in Probes.bins
    low: float | None = None
    high: float | None = None
    each: bool = False
    relative: str = ""
    factor: float = 1.0
    weight: float = 1.0                             # of its shortfalls and excesses; below 1: not R112's, yields to it


@dataclass
class Probes:
    """Where the beam is judged: bins of the surrogate's grid (flat indices) and their groups."""

    bins: np.ndarray
    omega: np.ndarray                               # solid angle of each bin (sr)
    groups: list = field(default_factory=list)
    field: np.ndarray | None = None                 # positions in bins of the field judged for evenness (rows, columns)
    inside: np.ndarray | None = None                # which of them lie below the cut-off
    reference: float = 1.0                          # cd: the evenness' measure (R112's minimum at 50R)


def grid() -> tuple[np.ndarray, np.ndarray]:
    nh = int(round((H_RANGE[1] - H_RANGE[0]) / DH))
    nv = int(round((V_RANGE[1] - V_RANGE[0]) / DV))
    return H_RANGE[0] + (np.arange(nh) + 0.5) * DH, V_RANGE[0] + (np.arange(nv) + 0.5) * DV


def probes(cutoff: Cutoff, band: float = 0.0, rise: float = 0.0) -> Probes:
    """R112's test points (their photometer windows: ± 0.25° x ± 0.1°) and every bin of its zones
    III, IV and I – of III and I every bin that touches them: an optimiser finds any gap between the
    probes –, for the traffic side of `cutoff`; and, to keep the cut-off where it is aimed, every
    bin from ABOVE degrees above the cut-off line (|H| ≤ 10°, up to 1.5° up) at most as zone III.
    Beyond R112, as a real beam has it: `band` cd at least on average in a band under both
    branches (BAND_V under the line, BAND_H about the kink) – the beam brightest at its cut-off,
    not in a patch below it –, and `rise` cd just under the rising branch (RISE_H from the kink)
    with a fall by STEP above it – the kink seen, the rise sharp (0: neither)."""
    h, v = grid()
    sign = 1.0 if cutoff.right_hand_traffic else -1.0
    bins: list[int] = []
    groups = []

    def add(flat) -> np.ndarray:
        start = len(bins)
        bins.extend(int(b) for b in flat)
        return np.arange(start, len(bins))

    for tp in al_photometry.R112_CLASS_B:
        hi = np.flatnonzero(np.abs(h - sign * tp.h) <= 0.25 + 1e-9)
        vj = np.flatnonzero(np.abs(v - tp.v) <= 0.1 + 1e-9)
        hi = hi if len(hi) else [int(np.argmin(np.abs(h - sign * tp.h)))]
        vj = vj if len(vj) else [int(np.argmin(np.abs(v - tp.v)))]
        groups.append(Group(tp.name, add([j * len(h) + i for j in vj for i in hi]), tp.minimum, tp.maximum))
    H, V = np.meshgrid(h, v)

    def touching(inside) -> np.ndarray:
        """Bins any corner of which is in the zone (an upper limit holds up to its border)."""
        hit = np.zeros(H.shape, dtype=bool)
        for a in (-0.5 * DH, 0.5 * DH):
            for b in (-0.5 * DV, 0.5 * DV):
                hit |= inside(H + a, V + b)
        return np.flatnonzero(hit.ravel())

    zone3 = [(sign * a, b) for a, b in al_photometry.ZONE_III]
    groups.append(Group("zone III", add(touching(lambda x, y: al_photometry._inside(zone3, x, y))),
                        high=al_photometry.ZONE_III_MAX, each=True))
    h0, h1, v0, v1 = al_photometry.ZONE_IV
    zone4 = (H >= h0) & (H <= h1) & (V >= v0) & (V <= v1)
    groups.append(Group("zone IV", add(np.flatnonzero(zone4.ravel())), low=al_photometry.ZONE_IV_MIN, each=True))
    h0, h1, v0, v1 = al_photometry.ZONE_I
    groups.append(Group("zone I", add(touching(lambda x, y: (x >= h0) & (x <= h1) & (y >= v0) & (y <= v1))),
                        each=True, relative="50R", factor=al_photometry.ZONE_I_FACTOR))
    # not R112's, but what keeps the cut-off where it is aimed: little light from ABOVE above the line
    groups.append(Group("above the cut-off", add(touching(lambda x, y: (np.abs(x) <= 10.0) & (y <= 1.5) & (
        y >= np.degrees(np.arctan(cutoff.line(np.tan(np.radians(x))))) + ABOVE))),
        high=al_photometry.ZONE_III_MAX, each=True))
    # and where R112 measures the cut-off (2.5° to the side of the oncoming traffic): it must fall
    # there by a factor 10 – from 0.15 … 0.35° below the line to 0.15 … 1° above it – so that its
    # steepest step is the line
    side = -2.5 * sign
    level = math.degrees(math.atan(float(cutoff.line(np.tan(np.radians(side))))))
    near = np.abs(H - side) <= 0.25 + 1e-9
    groups.append(Group("under the cut-off", add(np.flatnonzero((near & (V >= level - 0.35) & (V <= level - 0.15)).ravel()))))
    groups.append(Group("over the cut-off", add(np.flatnonzero((near & (V >= level + 0.15) & (V <= level + 1.0)).ravel())),
                        each=True, relative="under the cut-off", factor=STEP))
    # a real beam's: brightest under its cut-off, the rising branch lit and sharp
    line = np.degrees(np.arctan(cutoff.line(np.tan(np.radians(H)))))
    if band > 0.0:
        under = (np.abs(H - cutoff.kink_deg) <= BAND_H) & (V <= line - BAND_V[0]) & (V >= line - BAND_V[1])
        groups.append(Group("under the line", add(np.flatnonzero(under.ravel())), low=band, weight=REAL))
    if rise > 0.0:
        along = (sign * (H - cutoff.kink_deg) >= RISE_H[0]) & (sign * (H - cutoff.kink_deg) <= RISE_H[1])
        groups.append(Group("under the rise", add(np.flatnonzero((along & (V >= line - 0.35) & (V <= line - BAND_V[0])).ravel())),
                            low=rise, weight=REAL))
        groups.append(Group("over the rise", add(np.flatnonzero((along & (V >= line + 0.15) & (V <= line + 1.0)).ravel())),
                            each=True, relative="under the rise", factor=STEP, weight=REAL))
    # the field whose evenness counts: below the cut-off (FIELD_GAP), |H| ≤ FIELD_H, V ≥ FIELD_V, on
    # a lattice of every BUMP_H-th bin across and BUMP_V-th up and down (the views judged blurred as
    # the lamp blurs: nothing hides between its points)
    cols = np.flatnonzero(np.abs(h) <= FIELD_H + 1e-9)[::BUMP_H]
    line = np.degrees(np.arctan(cutoff.line(np.tan(np.radians(h[cols])))))
    rows = np.flatnonzero((v >= FIELD_V - 1e-9) & (v <= line.max() - FIELD_GAP))[::BUMP_V]
    where = add((rows[:, None] * len(h) + cols[None, :]).ravel()).reshape(len(rows), len(cols))
    inside = v[rows][:, None] <= line[None, :] - FIELD_GAP
    reference = next(tp.minimum for tp in al_photometry.R112_CLASS_B if tp.name == "50R")
    flat = np.asarray(bins)
    omega = al_photometry._solid_angle(h[flat % len(h)], v[flat // len(h)], DH, DV)
    return Probes(flat, omega, groups, where, inside, float(reference))


def bumps(F: np.ndarray, inside: np.ndarray) -> np.ndarray:
    """The mean square of the bumps of intensities F (..., rows, columns) on the field's lattice:
    second differences between neighbours across and up and down, where all three points are
    inside. A plane or a steady slope has none; a patch, a stripe, a hot spot has."""
    a, b = 1, 1
    across = F[..., :, 2 * a:] - 2.0 * F[..., :, a:-a] + F[..., :, :-2 * a]
    ok_a = inside[:, 2 * a:] & inside[:, a:-a] & inside[:, :-2 * a]
    up = F[..., 2 * b:, :] - 2.0 * F[..., b:-b, :] + F[..., :-2 * b, :]
    ok_u = inside[2 * b:] & inside[b:-b] & inside[:-2 * b]
    return ((across ** 2 * ok_a).sum(axis=(-2, -1)) + (up ** 2 * ok_u).sum(axis=(-2, -1))) / (ok_a.sum() + ok_u.sum())


def evenness(I: np.ndarray, pr: Probes) -> np.ndarray:
    """The rms of the bumps relative to pr.reference, for intensities I (..., bins) at the probes."""
    return np.sqrt(bumps(I[..., pr.field], pr.inside)) / pr.reference


CAP, TAU = 2.0, 0.05      # the margins counted up to 2x what is needed; softness of their minimum


def objective(I: np.ndarray, pr: Probes, margin: float, uniformity: float = 0.0) -> np.ndarray:
    """The objective for intensities I (views, k, bins) of k candidates at the probes' bins, seen
    in one or more views (the filament images and the same blurred as the lamp blurs them): the
    squared shortfalls (in the darkest view) and excesses (in the brightest) beyond the margin, less
    EPSILON x the (soft) smallest of the ratios value / minimum and maximum / value (each up to
    CAP) – the weakest requirement raised –, plus `uniformity` x the squared rms of the bumps
    (relative to 50R's minimum) in the last view – the lamp's as it is if it has one."""
    low_view, high_view = I.min(axis=0), I.max(axis=0)
    total = np.zeros(I.shape[1])

    def value(view, g):
        return view[:, g.at] if g.each else view[:, g.at].mean(axis=1, keepdims=True)

    by_name = {g.name: g for g in pr.groups}
    ratios = []
    for g in pr.groups:
        if g.low is not None:
            x = value(low_view, g)
            short = np.maximum((1.0 + margin) * g.low - x, 0.0) / g.low
            total += g.weight * (short ** 2).sum(axis=1) / math.sqrt(x.shape[1])
            if g.weight >= 1.0:
                ratios.append(np.minimum(x.min(axis=1) / g.low, CAP))
        high = g.factor * value(low_view, by_name[g.relative])[:, :1] if g.relative else g.high
        if high is not None:
            x = value(high_view, g)
            over = np.maximum(x - (1.0 - margin) * high, 0.0) / np.maximum(high, 1.0)
            total += g.weight * (over ** 2).sum(axis=1) / math.sqrt(x.shape[1])
            if g.weight >= 1.0:
                ratios.append(np.minimum(np.ravel(high * np.ones((len(x), 1))) / np.maximum(x.max(axis=1), 1e-9), CAP))
    R = np.stack(ratios, axis=1)
    weakest = R.min(axis=1)
    soft = weakest - TAU * np.log(np.exp(-(R - weakest[:, None]) / TAU).sum(axis=1))
    if uniformity > 0.0 and pr.field is not None:
        total += uniformity * bumps(I[-1][:, pr.field], pr.inside) / pr.reference ** 2
    return total - EPSILON * soft


def report(I: np.ndarray, pr: Probes) -> dict:
    """Per test point and zone its value at intensities I (views, bins): a lower limit's in the
    darkest view, an upper limit's in the brightest – the mean of a point, a zone's lowest / highest
    bin."""
    low_view, high_view = I.min(axis=0), I.max(axis=0)
    out = {}
    for g in pr.groups:
        x = (low_view if g.low is not None or not (g.high or g.relative) else high_view)[g.at]
        out[g.name] = float(x.mean() if not g.each else x.min() if g.low is not None else x.max())
    return out


# ------------------------------------------------------------------ the cells' patterns
def _box(a: np.ndarray, half: int, axis: int) -> np.ndarray:
    """a smeared evenly over 2 half + 1 bins along `axis` (the flux kept)."""
    if half <= 0:
        return a
    c = np.cumsum(np.pad(a, [(half + 1, half) if k == axis else (0, 0) for k in range(a.ndim)]), axis=axis)
    upper = np.take(c, np.arange(2 * half + 1, c.shape[axis]), axis=axis)
    lower = np.take(c, np.arange(0, c.shape[axis] - 2 * half - 1), axis=axis)
    return (upper - lower) / (2 * half + 1)


def _gauss(a: np.ndarray, sigma: float, axis: int) -> np.ndarray:
    """a blurred along `axis` by a Gaussian of `sigma` bins (cut at 3 sigma; the flux kept)."""
    if sigma <= 0.0:
        return a
    r = int(math.ceil(3.0 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    return np.apply_along_axis(lambda x: np.convolve(x, k, mode="same"), axis, a)


def blurred(intensity: np.ndarray, blur: tuple[float, float]) -> np.ndarray:
    """An intensity on the surrogate's grid blurred by (sigma H, sigma V) degrees."""
    return _gauss(_gauss(intensity, blur[1] / DV, 0), blur[0] / DH, 1)


def fit_blur(model: al_photometry.Distribution, traced: al_photometry.Distribution) -> tuple[float, float, float]:
    """The Gaussian blur (sigma H, sigma V degrees) that turns `model` (filament images) into
    `traced` (the lamp as it is) best where either is bright, and the relative error left."""
    M, _ = resampled(model)
    T, _ = resampled(traced)
    bright = (M > 0.02 * M.max()) | (T > 0.02 * T.max())
    best = (float("inf"), 0.0, 0.0)
    for sh in (0.0, 0.125, 0.25, 0.375, 0.5, 0.75):
        for sv in (0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4):
            B = blurred(M, (sh, sv))
            err = float(np.sqrt(((B - T)[bright] ** 2).mean()) / T[bright].mean())
            best = min(best, (err, sh, sv))
    return best[1], best[2], best[0]


@dataclass
class Choice:
    """Indices into DEFLECT_H, DEFLECT_V, SPREAD, ANGLE per cell."""

    dh: np.ndarray
    dv: np.ndarray
    sp: np.ndarray
    an: np.ndarray

    def element(self, k: int) -> tuple[float, float, float, float, float]:
        """(deflect H, deflect V, spread H, spread V, spread angle) of cell k – al_lens.Element's."""
        return (float(DEFLECT_H[self.dh[k]]), float(DEFLECT_V[self.dv[k]]), float(SPREAD[self.sp[k]]), 0.0,
                float(ANGLE[self.an[k]]))

    def copy(self) -> "Choice":
        return Choice(self.dh.copy(), self.dv.copy(), self.sp.copy(), self.an.copy())


def spread_parts(cell: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """The H and V parts (degrees) of the cylinders' spreads (SPREAD x ANGLE) for cells of (width,
    height) mm: the spread is reached at the cell's farthest corner along its direction."""
    phi = np.radians(ANGLE)
    return np.abs(SPREAD[:, None] * np.cos(phi)[None, :]), np.abs(SPREAD[:, None] * np.sin(phi)[None, :])


def _line(cell: tuple[float, float], spread: float, angle: float):
    """How a cylinder smears on the surrogate's grid: the axis it runs along most (1: V, 2: H), the
    shift per bin along it on the other axis (bins), and the two boxes' half lengths along it (bins)
    – the cell's points spread along the line as two boxes in a row: its width's and its height's."""
    w, h = 0.5 * cell[0], 0.5 * cell[1]
    phi = math.radians(angle)
    c, s = math.cos(phi), math.sin(phi)
    q = w * abs(c) + h * abs(s)
    first, second = spread * w * abs(c) / q, spread * h * abs(s) / q       # degrees along the line
    if abs(c) / DH >= abs(s) / DV:                                        # mostly across: along H
        per = c / DH
        return 2, (s / DV) / per, (first * abs(c) / DH, second * abs(c) / DH)
    per = s / DV
    return 1, (c / DH) / per, (first * abs(s) / DV, second * abs(s) / DV)


def _smear(a: np.ndarray, axis: int, slope: float, halves) -> np.ndarray:
    """a (views, rows, columns) smeared by boxes of `halves` (bins) along a line that runs along
    `axis` and moves `slope` bins on the other axis per bin: the other axis sheared so that the line
    runs along `axis` (whole bins), the boxes, sheared back. What leaves the array is lost (the
    patterns have room for the widest spread)."""
    halves = [int(round(x)) for x in halves]
    if not any(halves):
        return a
    other = 3 - axis
    n_along, n_other = a.shape[axis], a.shape[other]
    shift = -np.rint((np.arange(n_along) - 0.5 * (n_along - 1)) * slope).astype(int)    # (the line rises by slope)
    if not shift.any():
        out = a
        for half in halves:
            out = _box(out, half, axis)
        return out
    pad = int(np.abs(shift).max())
    idx_other = np.arange(n_other)[:, None] + pad + shift[None, :]            # (other, along) in the sheared array
    idx_along = np.broadcast_to(np.arange(n_along)[None, :], idx_other.shape)
    sheared = np.zeros((a.shape[0], n_other + 2 * pad, n_along) if axis == 2 else (a.shape[0], n_along, n_other + 2 * pad),
                       dtype=a.dtype)
    if axis == 2:                                                         # a[:, other, along]
        sheared[:, idx_other, idx_along] = a
    else:                                                                 # a[:, along, other]
        sheared[:, idx_along.T, idx_other.T] = a
    for half in halves:
        sheared = _box(sheared, half, axis)
    return sheared[:, idx_other, idx_along] if axis == 2 else sheared[:, idx_along.T, idx_other.T]


def edges(rays: Rays, cutoff: Cutoff) -> np.ndarray:
    """Per cell: whether the edge of its light is the cut-off's rising branch (True) or its
    horizontal one – whether more than RISING_SHARE of its flux on the plane lens lies above the
    horizontal branch on the driver's side (the light that leaves the shield by its 15° edge: in
    front of the mirror's sector below it, a wedge from the middle of the lens)."""
    sign = 1.0 if cutoff.right_hand_traffic else -1.0
    total = np.bincount(rays.cell, rays.flux, minlength=len(rays.cells))
    up = (rays.V > cutoff.v_deg + 0.1) & (sign * (rays.H - cutoff.kink_deg) > 0.0)
    above = np.bincount(rays.cell[up], rays.flux[up], minlength=len(rays.cells))
    return above > RISING_SHARE * np.maximum(total, 1e-300)


def default_sectors(rays: Rays, cutoff: Cutoff) -> tuple:
    """The lens' sectors from the plane lens' light: the wedge (azimuths about the lamp axis, in
    1° steps) where more than RISING_SHARE of the light lies above the horizontal branch on the
    driver's side – it ends at the rising branch – and the rest; () if there is none."""
    sign = 1.0 if cutoff.right_hand_traffic else -1.0
    az = np.floor(np.degrees(np.arctan2(rays.z, rays.y)) % 360.0).astype(int) % 360
    up = (rays.V > cutoff.v_deg + 0.1) & (sign * (rays.H - cutoff.kink_deg) > 0.0)
    total = np.bincount(az, rays.flux, minlength=360)
    above = np.bincount(az[up], rays.flux[up], minlength=360)
    smooth = lambda a: (np.roll(a, 1) + a + np.roll(a, -1)) / 3.0         # noqa: E731
    rising = smooth(above) > RISING_SHARE * np.maximum(smooth(total), 1e-300)
    if not rising.any() or rising.all():
        return ()
    start = int(np.flatnonzero(rising & ~np.roll(rising, 1))[0])        # the runs, the one with the most light kept
    runs, a = [], start
    for _ in range(360):
        if rising[a % 360] and not rising[(a - 1) % 360]:
            b = a
            while rising[b % 360]:
                b += 1
            runs.append((float(above[np.arange(a, b) % 360].sum()), a % 360, b % 360))
        a += 1
    _, a0, a1 = max(runs)
    return (al_lens.Sector(float(a0), RISING), al_lens.Sector(float(a1), HORIZONTAL))


class Surrogate:
    """The cells' patterns (flux per bin of the plane cell, each cut to where it has light, with room
    for the widest spread) in its views – as they are and, with a `blur` (sigma H, V in degrees:
    what the lamp as it is adds to the filament images), blurred – and the beam at the probes.
    `cell`: the cells' width and height (mm), which shape a slanting cylinder's smear."""

    def __init__(self, rays: Rays, pr: Probes, background: np.ndarray, blur: tuple[float, float] = (0.0, 0.0),
                 cell: tuple[float, float] = (4.0, 4.0)):
        h, v = grid()
        self.nh, self.nv = len(h), len(v)
        self.probes = pr
        self.cell = cell
        self.blurs = [(0.0, 0.0)] + ([tuple(blur)] if any(blur) else [])
        i = np.floor((rays.H - H_RANGE[0]) / DH).astype(int)
        j = np.floor((rays.V - V_RANGE[0]) / DV).astype(int)
        inside = (i >= 0) & (i < self.nh) & (j >= 0) & (j < self.nv)
        count = len(rays.cells)
        flat = (rays.cell[inside].astype(np.int64) * self.nv + j[inside]) * self.nh + i[inside]
        pattern = np.bincount(flat, weights=rays.flux[inside], minlength=count * self.nv * self.nh) \
            .reshape(count, self.nv, self.nh)
        self.flux = pattern.reshape(count, -1).sum(axis=1)
        self.shift_h = np.rint(DEFLECT_H / DH).astype(int)
        self.shift_v = np.rint(DEFLECT_V / DV).astype(int)
        self.part_h, self.part_v = spread_parts(cell)
        self.lines = {(a, b): _line(cell, float(SPREAD[a]), float(ANGLE[b]))
                      for a in range(len(SPREAD)) for b in range(len(ANGLE))}
        mh = int(math.ceil(REACH / DH)) + 2 + int(math.ceil(3.0 * blur[0] / DH))
        mv = int(math.ceil(REACH_V / DV)) + 2 + int(math.ceil(3.0 * blur[1] / DV))
        self.crops, self.offsets = [], []                 # crops[k]: (views, rows, columns)
        for k in range(count):
            if self.flux[k] <= 0.0:
                self.crops.append(np.zeros((len(self.blurs), 1, 1), dtype=np.float32))
                self.offsets.append((0, 0))
                continue
            rows = np.flatnonzero(pattern[k].any(axis=1))
            cols = np.flatnonzero(pattern[k].any(axis=0))
            crop = np.zeros((rows[-1] - rows[0] + 1 + 2 * mv, cols[-1] - cols[0] + 1 + 2 * mh), dtype=np.float32)
            crop[mv:mv + rows[-1] - rows[0] + 1, mh:mh + cols[-1] - cols[0] + 1] = \
                pattern[k, rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
            self.crops.append(np.stack([blurred(crop, b) for b in self.blurs]).astype(np.float32))
            self.offsets.append((int(rows[0]) - mv, int(cols[0]) - mh))
        del pattern
        self.pv, self.ph = pr.bins // self.nh, pr.bins % self.nh
        self.background = background            # cd per view at the probes (direct light; the full model's difference)
        self.depth_h = np.zeros(len(DEFLECT_H))                      # (depths(): how deep an element reaches)
        self.depth_v = np.zeros(len(DEFLECT_V))
        self.depth_c = np.zeros((len(SPREAD), len(ANGLE)))
        self.deepest = np.inf
        self.edge_angle = np.full(count, -1)                         # per cell: the one direction its cylinder may
        self.edge_slope = np.full(count, np.nan)                     # have, the line its deflection keeps to (-1, nan: any)

    def smeared(self, k: int, sp: int, an: int) -> np.ndarray:
        axis, slope, halves = self.lines[(int(sp), int(an))]
        return _smear(self.crops[k], axis, slope, halves)

    def fits(self, dh, dv, sp, an) -> np.ndarray:
        """Which elements (index arrays, broadcast) the lens can have: within the patches' slope and
        the spread's reach, not deeper than the lens allows."""
        return ((np.abs(DEFLECT_H[dh]) + self.part_h[sp, an] <= REACH) & (self.part_v[sp, an] <= REACH_V)
                & (self.depth_h[dh] + self.depth_v[dv] + self.depth_c[sp, an] <= self.deepest))

    def at_probes(self, k: int, smeared: np.ndarray, dh, dv) -> np.ndarray:
        """Flux (views, k, probes) of cell k's smeared pattern shifted by the deflections (index arrays)."""
        dh, dv = np.atleast_1d(dh), np.atleast_1d(dv)
        oj, oi = self.offsets[k]
        j = self.pv[None, :] - self.shift_v[dv][:, None] - oj
        i = self.ph[None, :] - self.shift_h[dh][:, None] - oi
        _, nj, ni = smeared.shape
        ok = (j >= 0) & (j < nj) & (i >= 0) & (i < ni)
        return np.where(ok[None], smeared[:, np.clip(j, 0, nj - 1), np.clip(i, 0, ni - 1)], 0.0)

    def beam(self, choice: Choice) -> np.ndarray:
        """Flux (views, probes) of all cells with their choice."""
        total = np.zeros((len(self.blurs), len(self.probes.bins)))
        for k in np.flatnonzero(self.flux > 0.0):
            total += self.at_probes(k, self.smeared(k, choice.sp[k], choice.an[k]), choice.dh[k], choice.dv[k])[:, 0]
        return total

    def full(self, choice: Choice) -> np.ndarray:
        """The beam's flux on the whole grid (views, nv, nh)."""
        out = np.zeros((len(self.blurs), self.nv + 400, self.nh + 400))
        for k in np.flatnonzero(self.flux > 0.0):
            m = self.smeared(k, choice.sp[k], choice.an[k])
            j = 200 + self.offsets[k][0] + self.shift_v[choice.dv[k]]
            i = 200 + self.offsets[k][1] + self.shift_h[choice.dh[k]]
            out[:, j:j + m.shape[1], i:i + m.shape[2]] += m
        return out[:, 200:200 + self.nv, 200:200 + self.nh]


def depths(settings: al_lens.LensSettings) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """How deep (mm, below the cell's middle) an element of the cell on the lamp axis reaches: the
    prism turning across (DEFLECT_H), up and down (DEFLECT_V), the cylinder (SPREAD x ANGLE) – an
    element's depth is at most their sum. inf: the element cannot bend the light that far."""
    w, hgt = settings.cell_width, settings.cell_height
    frame = al_layout.rounded_rectangle(1.02 * w, 1.02 * hgt, 0.0)

    def depth(*element) -> float:
        try:
            one = al_lens.build(replace(settings, elements=(al_lens.Element(-1e9, 1e9, -1e9, 1e9, *element),),
                                        thickness=1e3, wall_draft=0.0, rake=0.0, sweep=0.0, radius=0.0), frame)
        except DesignError:
            return np.inf
        return -one.sag[0]

    across = np.array([depth(a) for a in DEFLECT_H])
    up = np.array([depth(0.0, a) for a in DEFLECT_V])
    cylinder = np.array([[depth(0.0, 0.0, s, 0.0, a) for a in ANGLE] for s in SPREAD])
    return across, up, cylinder


def _cost(dh, dv, sp, an, sur: Surrogate) -> np.ndarray:
    return LAMBDA * (np.abs(DEFLECT_H[dh]) + 5.0 * np.abs(DEFLECT_V[dv]) + sur.part_h[sp, an] + 5.0 * sur.part_v[sp, an])


def descend(sur: Surrogate, choice: Choice, margin: float, sweeps: int = 8, progress=None,
            uniformity: float = 0.0) -> tuple[Choice, int]:
    """Coordinate descent over the cells (brightest first): each cell's deflection with its
    cylinder kept, then its cylinder (strength, direction) with its deflection kept. Returns the
    choice and the sweeps made."""
    pr = sur.probes

    def judged(flux):                            # (views, k, probes) -> objective (k)
        return objective(flux / pr.omega + sur.background[:, None, :], pr, margin, uniformity)

    total = sur.beam(choice)
    order = np.argsort(-sur.flux)
    order = order[sur.flux[order] > 0.0]
    DHg, DVg = np.meshgrid(np.arange(len(DEFLECT_H)), np.arange(len(DEFLECT_V)), indexing="ij")
    DHg, DVg = DHg.ravel(), DVg.ravel()
    SPg, ANg = np.meshgrid(np.arange(len(SPREAD)), np.arange(len(ANGLE)), indexing="ij")
    SPg, ANg = SPg.ravel(), ANg.ravel()
    plain = SPREAD[SPg] == 0.0
    SPg, ANg = np.concatenate([SPg[~plain], [0]]), np.concatenate([ANg[~plain], [int(np.argmin(np.abs(ANGLE)))]])
    done = 0
    before = float(judged(total[:, None, :])[0])
    for sweep in range(sweeps):
        changed = 0
        for n, k in enumerate(order):
            if progress is not None and n % 50 == 0:
                progress((sweep + n / len(order)) / sweeps, f"optimising the lens: sweep {sweep + 1}, cell {n} of "
                                                            f"{len(order)}")
            old = (choice.dh[k], choice.dv[k], choice.sp[k], choice.an[k])
            m = sur.smeared(k, choice.sp[k], choice.an[k])
            rest = total - sur.at_probes(k, m, choice.dh[k], choice.dv[k])[:, 0]
            # the deflection, the cylinder kept: all in the first sweep, then those near the present one
            fits = sur.fits(DHg, DVg, choice.sp[k], choice.an[k])
            if not np.isnan(sur.edge_slope[k]):        # along its edge
                fits &= np.abs(DEFLECT_V[DVg] - sur.edge_slope[k] * DEFLECT_H[DHg]) <= ALONG
            if sweep > 0:
                fits &= (np.abs(DHg - choice.dh[k]) <= NEAR) & (np.abs(DVg - choice.dv[k]) <= NEAR)
            fits |= (DHg == choice.dh[k]) & (DVg == choice.dv[k])
            cand = sur.at_probes(k, m, DHg[fits], DVg[fits])
            score = judged(rest[:, None, :] + cand) + _cost(DHg[fits], DVg[fits], choice.sp[k], choice.an[k], sur)
            best = int(np.argmin(score))
            choice.dh[k], choice.dv[k] = DHg[fits][best], DVg[fits][best]
            # the cylinder, the deflection kept: all in the first sweep, then those near the present one
            fits = sur.fits(choice.dh[k], choice.dv[k], SPg, ANg)
            if sur.edge_angle[k] >= 0:                  # spreading along its edge
                fits &= (ANg == sur.edge_angle[k]) | (SPREAD[SPg] == 0.0)
            if sweep > 0:
                turn = np.abs(ANg - choice.an[k])
                fits &= (np.abs(SPg - choice.sp[k]) <= 2) & (np.minimum(turn, len(ANGLE) - turn) <= 2)
            fits |= (SPg == choice.sp[k]) & (ANg == choice.an[k])
            fits = np.flatnonzero(fits)
            cand = np.stack([sur.at_probes(k, sur.smeared(k, SPg[q], ANg[q]), choice.dh[k], choice.dv[k])[:, 0]
                             for q in fits], axis=1)
            score = judged(rest[:, None, :] + cand) + _cost(choice.dh[k], choice.dv[k], SPg[fits], ANg[fits], sur)
            best = int(np.argmin(score))
            choice.sp[k], choice.an[k] = SPg[fits[best]], ANg[fits[best]]
            total = rest + cand[:, best]
            changed += old != (choice.dh[k], choice.dv[k], choice.sp[k], choice.an[k])
        done = sweep + 1
        now = float(judged(total[:, None, :])[0])
        if changed == 0 or before - now < 1e-5 * max(abs(now), 1e-3):
            break
        before = now
    return choice, done


# ------------------------------------------------------------------ the whole
@dataclass
class Result:
    elements: tuple                     # al_lens.Element per cell
    choice: Choice
    cells: list
    rounds: list = field(default_factory=list)       # per round: the surrogate's and the full model's values
    objective: float = 0.0
    dist: al_photometry.Distribution | None = None   # the full model's, of the lens built last
    system: al_lens.LensSystem | None = None
    start: int = 0                      # which of optimise's starts it came from
    checked: bool = False               # whether the ray tracing's round is the one kept
    sectors: tuple = ()                 # the lens' sectors (al_lens.Sector) the elements are for
    traced: al_photometry.Distribution | None = None   # check()'s of the lens kept
    background: np.ndarray | None = None   # (views, grid) the surrogate's in its best round


def elements_of(system: al_lens.LensSystem, cells: list, choice: Choice) -> tuple:
    s = system.settings
    out = []
    for k, (i, j, sector) in enumerate(cells):
        y0, z0 = system.y0 + i * s.cell_width, system.z0 + j * s.cell_height
        out.append(al_lens.Element(round(y0, 6), round(y0 + s.cell_width, 6), round(z0, 6),
                                   round(z0 + s.cell_height, 6), *choice.element(k),
                                   sector=sector if system.count > 1 else -1))
    return tuple(out)


def resampled(dist: al_photometry.Distribution) -> tuple[np.ndarray, np.ndarray]:
    """A distribution (finer grid) on the surrogate's grid: the mean of its cells in each bin, and
    where it has any."""
    h, v = grid()
    i = np.floor((dist.h - H_RANGE[0]) / DH).astype(int)
    j = np.floor((dist.v - V_RANGE[0]) / DV + 1e-9).astype(int)
    oi, oj = (i >= 0) & (i < len(h)), (j >= 0) & (j < len(v))
    J, I = np.meshgrid(j[oj], i[oi], indexing="ij")
    flat = (J * len(h) + I).ravel()
    total = np.bincount(flat, weights=dist.intensity[np.ix_(oj, oi)].ravel(), minlength=len(h) * len(v))
    count = np.bincount(flat, minlength=len(h) * len(v))
    return (total / np.maximum(count, 1)).reshape(len(v), len(h)), (count > 0).reshape(len(v), len(h))


CYLINDERS = (0.0, 0.0, 6.0, 0.0)     # a start: cylinder lenses spreading 6° across in every cell


def nearest(start: tuple, sur: "Surrogate") -> tuple[int, int, int, int]:
    """The choice nearest to (deflect H, deflect V, spread, angle); its spread made weaker until the
    element fits the lens."""
    dh, dv, sp, an = (int(np.argmin(np.abs(table - value))) for table, value in
                      zip((DEFLECT_H, DEFLECT_V, SPREAD, ANGLE), start))
    while sp > 0 and not sur.fits(dh, dv, sp, an):
        sp -= 1
    if not sur.fits(dh, dv, sp, an):
        raise DesignError(f"the lens is too thin for the start {start}")
    return dh, dv, sp, an


def optimise(settings: al_lens.LensSettings, frame: np.ndarray, evaluate, *, margin: float = 0.1,
             rounds: int = 2, blur: tuple[float, float] = (0.0, 0.0), spacing: float = 1.0,
             reflectance: float = 0.85, transmittance: float = 0.92, direct: bool = True, progress=None,
             log=None, uniformity: float = 0.0, starts: tuple = (None,), along_edges: bool = False,
             band: float = 0.0, rise: float = 0.0, check=None) -> Result:
    """The elements of every cell. evaluate(system) -> Distribution: the filament images (with the
    lamp's direct light) of a lens built; rounds: how often half its difference from the surrogate
    is carried back; blur (fit_blur, sigma H, V in degrees): a second view in which the beam must
    hold too – lower limits in the darker view, upper ones in the brighter; uniformity: the weight
    of the beam's evenness (objective); starts: what every cell begins with, one search each, the
    best kept – None: plane glass, or (deflect H, deflect V, spread, angle) in degrees (the nearest
    choices; a spread too deep for the lens is made weaker). The descent ends near where it begins:
    from plane glass it seldom takes up a cylinder lens, from CYLINDERS it keeps many. along_edges:
    every element spreads and deflects along the edge of its own light – the horizontal branch or
    the rising one –, as the flutes of a classic lens: the kink stays sharp and the rising branch
    lit; False: any direction. The edge is the branch of the element's sector; without sectors the
    lens is cut into them first (default_sectors: the wedge whose light ends at the rising branch,
    radial lines about the lamp axis, as the zones of a clear-lens reflector) – or, if there is no
    such wedge, it is found per cell (edges()). band, rise: what a real beam has beyond R112 (probes).
    check(system) -> Distribution: the lamp as it is (ray tracing) – once the rounds are done, what
    it adds to the blurred view of the lens kept is carried back and the cells optimised again, CHECKS
    times, each lens ray traced; the best by its ray tracing is kept (Result.traced)."""
    def step(lo: float, hi: float):
        if progress is None:
            return None
        return lambda fraction, text: progress(lo + (hi - lo) * fraction, text)

    plane = al_lens.build(replace(settings, elements=(al_lens.Element(-1e9, 1e9, -1e9, 1e9),), wall_draft=0.0), frame)
    rays = lens_rays(plane, spacing=spacing, reflectance=reflectance, transmittance=transmittance,
                     progress=step(0.0, 0.1))
    if along_edges and not settings.sectors:      # the wedge's radial lines, from the plane lens' light
        found = default_sectors(rays, settings.cutoff)
        if found:
            settings = replace(settings, sectors=found)
            plane = al_lens.build(replace(settings, elements=(al_lens.Element(-1e9, 1e9, -1e9, 1e9),),
                                          wall_draft=0.0), frame)
            rays = rays.regrouped(plane)
    pr = probes(settings.cutoff, band, rise)
    h, v = grid()
    omega = al_photometry._solid_angle(h[None, :], v[:, None], DH, DV)
    direct_light = np.zeros((len(v), len(h)))
    if direct:
        direct_light, _ = al_photometry.direct_light(settings.lamp, plane.filament, h, v,
                                                     after=lambda o, d: plane.through(o, d, transmittance))
    sur = Surrogate(rays, pr, np.zeros(0), blur, (settings.cell_width, settings.cell_height))
    sur.depth_h, sur.depth_v, sur.depth_c = depths(settings)
    sur.deepest = DEPTH * (settings.thickness - 0.3)              # (al_lens.build: at least 0.3 mm of glass left)
    zero = (int(np.argmin(np.abs(DEFLECT_H))), int(np.argmin(np.abs(DEFLECT_V))), 0, int(np.argmin(np.abs(ANGLE))))
    if not sur.fits(*zero):
        raise DesignError("the lens is too thin for even plane elements")
    first = np.stack([blurred(direct_light, b) for b in sur.blurs])
    if along_edges:
        cut = settings.cutoff
        rising = np.array([plane.branch(k) == RISING for _, _, k in rays.cells]) if plane.count > 1 \
            else edges(rays, cut)
        level = int(np.argmin(np.abs(ANGLE)))
        sur.edge_angle = np.where(rising, int(np.argmin(np.abs(ANGLE - math.degrees(math.atan(cut.slope))))), level)
        sur.edge_slope = np.where(rising, cut.slope, np.nan)
    count = len(rays.cells)
    at = lambda a: a.reshape(len(sur.blurs), -1)[:, pr.bins]           # noqa: E731
    best = None
    share = 0.8 / (len(starts) * (rounds + 1) + (CHECKS if check is not None else 0))

    def judge(choice, background, sweeps, lo, extra=0.0):
        """Descend from `choice`, build the lens, take its filament images: the round's record."""
        sur.background = at(background)
        choice, sweeps = descend(sur, choice, margin, sweeps=sweeps, progress=step(lo, lo + 0.7 * share),
                                 uniformity=uniformity)
        predicted = sur.full(choice) / omega + background
        elements = elements_of(plane, rays.cells, choice)
        system = al_lens.build(replace(settings, elements=elements), frame,
                               progress=step(lo + 0.7 * share, lo + 0.8 * share))
        dist = evaluate(system)
        model, seen = resampled(dist)
        actual = np.stack([blurred(model, b) for b in sur.blurs])       # the model in the surrogate's views
        actual[-1] += extra                                             # (and what the ray tracing adds)
        score = float(objective(at(actual)[:, None, :], pr, margin, uniformity)[0])
        record = {"sweeps": sweeps, "surrogate": report(at(predicted), pr), "model": report(at(actual), pr),
                  "objective": score, "bumps": (float(evenness(at(predicted)[-1], pr)),
                                                float(evenness(at(actual)[-1], pr)))}
        return choice, elements, system, dist, score, record, np.where(seen[None], actual - predicted, 0.0)

    for n, start in enumerate(starts):
        z = zero if start is None else nearest(start, sur)
        choice = Choice(*(np.full(count, c, dtype=np.int64) for c in z))
        if along_edges:                             # a start's cylinders turned along each cell's edge
            choice.an[:] = np.where(SPREAD[choice.sp] > 0.0, sur.edge_angle, choice.an)
            off = ~np.isnan(sur.edge_slope) & (np.abs(DEFLECT_V[choice.dv] - cut.slope * DEFLECT_H[choice.dh]) > ALONG)
            choice.dh[off], choice.dv[off] = zero[0], zero[1]
            bad = ~sur.fits(choice.dh, choice.dv, choice.sp, choice.an)
            choice.sp[bad], choice.an[bad] = 0, zero[3]
        result = Result((), choice, rays.cells, start=n, sectors=settings.sectors)
        background = first
        for r in range(rounds + 1):
            choice, elements, system, dist, score, record, missed = judge(
                choice, background, SWEEPS if r == 0 else LATER, 0.1 + (n * (rounds + 1) + r) * share)
            result.rounds.append({"start": n, **record})
            if log is not None:
                log(r, record["sweeps"], result.rounds[-1])
            if r == 0 or score < result.objective:       # the best round is kept
                result.elements, result.dist, result.system, result.objective = elements, dist, system, score
                result.choice, result.background = choice.copy(), background
            if r < rounds:                               # half of what the surrogate misses, kept
                background = background + DAMPING * missed
        if best is None or result.objective < best.objective:
            if best is not None:
                result.rounds = best.rounds + result.rounds
            best = result
        else:
            best.rounds += result.rounds
    if check is not None:          # what the lamp as it is adds to the blurred view, carried back

        def traced_score(dist, traced):
            """The objective with the ray tracing as the blurred view, and that view's report."""
            views = np.stack([blurred(resampled(dist)[0], b) for b in sur.blurs])
            views[-1] = resampled(traced)[0]
            return float(objective(at(views)[:, None, :], pr, margin, uniformity)[0]), report(at(views), pr)

        best.traced = check(best.system)
        best.objective, told = traced_score(best.dist, best.traced)
        best.rounds.append({"start": best.start, "traced": True, "objective": best.objective, "model": told})
        if log is not None:
            log(-1, 0, best.rounds[-1])
        choice, dist, traced = best.choice, best.dist, best.traced
        for c in range(CHECKS):                    # from the lens last traced, what it misses carried back
            model, seen = resampled(dist)
            ray, hit = resampled(traced)
            extra = np.where(seen & hit, blurred(ray - blurred(model, sur.blurs[-1]), CHECK_BLUR), 0.0)
            background = best.background.copy()
            background[-1] += extra
            choice, elements, system, dist, _, record, _ = judge(
                choice.copy(), background, LATER, 0.1 + (len(starts) * (rounds + 1) + c) * share, extra)
            traced = check(system)
            score, told = traced_score(dist, traced)
            best.rounds.append({"start": best.start, "checked": True, **record, "objective": score, "traced": told})
            if log is not None:
                log(-1, record["sweeps"], best.rounds[-1])
            if score < best.objective:
                best.elements, best.dist, best.system, best.objective = elements, dist, system, score
                best.choice, best.checked, best.traced = choice.copy(), True, traced
    return best
