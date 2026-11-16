"""The elements of a patterned lens chosen cell by cell, so that the beam meets the test points of
UN/ECE R112 (class B passing beam) with a margin – for a lamp whose cut-off its own shield makes
(H4): the mirror and the shield form the cut-off, the lens spreads the light below it.

The surrogate. Light reaches a cell of the plane lens from the mirror: rays from samples of the
coil's surface to the mirror's points, reflected, through the cell – their directions binned on a
grid of the screen (0.5° x 0.1°), one pattern per cell. An element turns the light of its middle
by (deflect H, deflect V) and that of its borders by ± the spread more, linearly across the cell
(al_lens): its pattern is the plane cell's, shifted by the deflection and smeared over ± the
spread (a box: the points of the cell are spread evenly). The beam is the sum of the cells'
patterns and the lamp's direct light (through the plane lens).

The objective, at the test points' windows and the zones' bins (luminous intensities):

    Σ (shortfall below (1 + m) min / min)² + Σ (excess above (1 − m) max / max)²      (m: margin)
    − ε softmin(value / minimum, maximum / value; each up to 2) + λ Σ cells (|deflection| + |spread|)

– squared shortfalls and excesses, then the weakest requirement raised (the smallest margin made
as large as can be), gentle elements where nothing depends on them. Zone I (the foreground) may
have at most twice the intensity at 50R. It is minimised one cell at a time: its deflection over
all choices with its spread kept, then its spread with the deflection kept; sweeps over all cells
until no cell changes. The surrogate differs from the lens built (the elements are fitted
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
from al_optics import Cutoff

DH, DV = 0.5, 0.1                                  # degrees: the surrogate's grid
H_RANGE, V_RANGE = (-45.0, 45.0), (-12.0, 6.0)
DEFLECT_H = np.arange(-16.0, 16.01, 1.0)
DEFLECT_V = np.round(np.arange(-3.0, 0.61, 0.2), 6)
SPREAD_H = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0])
SPREAD_V = np.array([0.0, 0.2, 0.5, 1.0])
REACH = 22.0                                       # degrees: |deflect H| + spread H at most (the patches' slope)
EPSILON, LAMBDA = 0.02, 2e-6
NEAR = 3                                           # after the first sweep: deflections this many steps away
SWEEPS, LATER = 8, 3                               # sweeps at most: the first round, the later ones
DEPTH = 0.85                                       # share of the lens' thickness (less 0.3 mm) the elements may take
DAMPING = 0.5                                      # share of the full model's difference carried back per round
STEP = 0.1                                         # the cut-off's fall where R112 measures it
ABOVE = 0.3                                        # degrees above the cut-off from which it must be dark


@dataclass
class Rays:
    """The light of the plane lens' cells: per ray its cell (index into `cells`), H, V (degrees) and
    flux (lm)."""

    cells: list                                    # (i, j) of the lens' grid
    cell: np.ndarray
    H: np.ndarray
    V: np.ndarray
    flux: np.ndarray


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
    index = -np.ones((system.ny, system.nz), dtype=np.int64)
    cells = [tuple(int(k) for k in c) for c in np.argwhere(system.used)]
    for k, (i, j) in enumerate(cells):
        index[i, j] = k
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
        iy, iz, inside = system.cell(y, z)
        cut = np.flatnonzero(inside & ~system.whole[np.clip(iy, 0, system.ny - 1), np.clip(iz, 0, system.nz - 1)])
        if len(cut):
            inside[cut] = al_layout.contains(system._outline, np.column_stack([y[cut], z[cut]]))
        keep = np.flatnonzero(inside)
        parts.append((index[iy[keep], iz[keep]], np.degrees(np.arctan(-dd[keep, 1] / dd[keep, 0])),
                      np.degrees(np.arctan(dd[keep, 2] / dd[keep, 0])), ww[keep]))
    cell, H, V, flux = (np.concatenate([q[k] for q in parts]) for k in range(4))
    return Rays(cells, cell, H.astype(np.float32), V.astype(np.float32), flux.astype(np.float32))


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


@dataclass
class Probes:
    """Where the beam is judged: bins of the surrogate's grid (flat indices) and their groups."""

    bins: np.ndarray
    omega: np.ndarray                               # solid angle of each bin (sr)
    groups: list = field(default_factory=list)


def grid() -> tuple[np.ndarray, np.ndarray]:
    nh = int(round((H_RANGE[1] - H_RANGE[0]) / DH))
    nv = int(round((V_RANGE[1] - V_RANGE[0]) / DV))
    return H_RANGE[0] + (np.arange(nh) + 0.5) * DH, V_RANGE[0] + (np.arange(nv) + 0.5) * DV


def probes(cutoff: Cutoff) -> Probes:
    """R112's test points (their photometer windows: ± 0.25° x ± 0.1°) and every bin of its zones
    III, IV and I – of III and I every bin that touches them: an optimiser finds any gap between the
    probes –, for the traffic side of `cutoff`; and, to keep the cut-off where it is aimed, every
    bin from ABOVE degrees above the cut-off line (|H| ≤ 10°, up to 1.5° up) at most as zone III."""
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
    flat = np.asarray(bins)
    omega = al_photometry._solid_angle(h[flat % len(h)], v[flat // len(h)], DH, DV)
    return Probes(flat, omega, groups)


CAP, TAU = 2.0, 0.05      # the margins counted up to 2x what is needed; softness of their minimum


def objective(I: np.ndarray, pr: Probes, margin: float) -> np.ndarray:
    """The objective for intensities I (views, k, bins) of k candidates at the probes' bins, seen
    in one or more views (the filament images and the same blurred as the lamp blurs them): the
    squared shortfalls (in the darkest view) and excesses (in the brightest) beyond the margin, less
    EPSILON x the (soft) smallest of the ratios value / minimum and maximum / value (each up to
    CAP) – the weakest requirement raised."""
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
            total += (short ** 2).sum(axis=1) / math.sqrt(x.shape[1])
            ratios.append(np.minimum(x.min(axis=1) / g.low, CAP))
        high = g.factor * value(low_view, by_name[g.relative])[:, :1] if g.relative else g.high
        if high is not None:
            x = value(high_view, g)
            over = np.maximum(x - (1.0 - margin) * high, 0.0) / np.maximum(high, 1.0)
            total += (over ** 2).sum(axis=1) / math.sqrt(x.shape[1])
            ratios.append(np.minimum(np.ravel(high * np.ones((len(x), 1))) / np.maximum(x.max(axis=1), 1e-9), CAP))
    R = np.stack(ratios, axis=1)
    weakest = R.min(axis=1)
    soft = weakest - TAU * np.log(np.exp(-(R - weakest[:, None]) / TAU).sum(axis=1))
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
    """Indices into DEFLECT_H, DEFLECT_V, SPREAD_H, SPREAD_V per cell."""

    dh: np.ndarray
    dv: np.ndarray
    sh: np.ndarray
    sv: np.ndarray

    def element(self, k: int) -> tuple[float, float, float, float]:
        return (float(DEFLECT_H[self.dh[k]]), float(DEFLECT_V[self.dv[k]]), float(SPREAD_H[self.sh[k]]),
                float(SPREAD_V[self.sv[k]]))


class Surrogate:
    """The cells' patterns (flux per bin of the plane cell, each cut to where it has light, with room
    for the widest spread) in its views – as they are and, with a `blur` (sigma H, V in degrees:
    what the lamp as it is adds to the filament images), blurred – and the beam at the probes."""

    def __init__(self, rays: Rays, pr: Probes, background: np.ndarray, blur: tuple[float, float] = (0.0, 0.0)):
        h, v = grid()
        self.nh, self.nv = len(h), len(v)
        self.probes = pr
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
        self.half_h = np.rint(SPREAD_H / DH).astype(int)
        self.half_v = np.rint(SPREAD_V / DV).astype(int)
        mh = int(self.half_h.max()) + int(math.ceil(3.0 * blur[0] / DH))
        mv = int(self.half_v.max()) + int(math.ceil(3.0 * blur[1] / DV))
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
        self.depth_h = np.zeros((len(DEFLECT_H), len(SPREAD_H)))      # (depths(): how deep an element reaches)
        self.depth_v = np.zeros((len(DEFLECT_V), len(SPREAD_V)))
        self.deepest = np.inf

    def smeared(self, k: int, sh: int, sv: int) -> np.ndarray:
        return _box(_box(self.crops[k], self.half_v[sv], 1), self.half_h[sh], 2)

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
            total += self.at_probes(k, self.smeared(k, choice.sh[k], choice.sv[k]), choice.dh[k], choice.dv[k])[:, 0]
        return total

    def full(self, choice: Choice) -> np.ndarray:
        """The beam's flux on the whole grid (views, nv, nh)."""
        out = np.zeros((len(self.blurs), self.nv + 400, self.nh + 400))
        for k in np.flatnonzero(self.flux > 0.0):
            m = self.smeared(k, choice.sh[k], choice.sv[k])
            j = 200 + self.offsets[k][0] + self.shift_v[choice.dv[k]]
            i = 200 + self.offsets[k][1] + self.shift_h[choice.dh[k]]
            out[:, j:j + m.shape[1], i:i + m.shape[2]] += m
        return out[:, 200:200 + self.nv, 200:200 + self.nh]


def depths(settings: al_lens.LensSettings) -> tuple[np.ndarray, np.ndarray]:
    """How deep (mm, below the cell's middle) an element of the cell on the lamp axis reaches:
    (DEFLECT_H x SPREAD_H) turning across, (DEFLECT_V x SPREAD_V) up and down – the two add about
    so (al_lens integrates the slopes along y, then along z). inf: the element cannot bend the
    light that far."""
    w, hgt = settings.cell_width, settings.cell_height
    frame = al_layout.rounded_rectangle(1.02 * w, 1.02 * hgt, 0.0)
    out = []
    for first, second, make in ((DEFLECT_H, SPREAD_H, lambda a, b: (a, 0.0, b, 0.0)),
                                (DEFLECT_V, SPREAD_V, lambda a, b: (0.0, a, 0.0, b))):
        table = np.full((len(first), len(second)), np.inf)
        for i, a in enumerate(first):
            for j, b in enumerate(second):
                try:
                    one = al_lens.build(replace(settings, elements=(al_lens.Element(-1e9, 1e9, -1e9, 1e9, *make(a, b)),),
                                                thickness=1e3, wall_draft=0.0, rake=0.0, sweep=0.0, radius=0.0), frame)
                except DesignError:
                    continue
                table[i, j] = -one.sag[0]
        out.append(table)
    return out[0], out[1]


def _cost(dh, dv, sh, sv) -> np.ndarray:
    return LAMBDA * (np.abs(DEFLECT_H[dh]) + 5.0 * np.abs(DEFLECT_V[dv]) + SPREAD_H[sh] + 5.0 * SPREAD_V[sv])


def descend(sur: Surrogate, choice: Choice, margin: float, sweeps: int = 8, progress=None) -> tuple[Choice, int]:
    """Coordinate descent over the cells (brightest first): each cell's deflection with its spread
    kept, then its spread with its deflection kept. Returns the choice and the sweeps made."""
    pr = sur.probes

    def judged(flux):                            # (views, k, probes) -> objective (k)
        return objective(flux / pr.omega + sur.background[:, None, :], pr, margin)

    total = sur.beam(choice)
    order = np.argsort(-sur.flux)
    order = order[sur.flux[order] > 0.0]
    DHg, DVg = np.meshgrid(np.arange(len(DEFLECT_H)), np.arange(len(DEFLECT_V)), indexing="ij")
    DHg, DVg = DHg.ravel(), DVg.ravel()
    SHg, SVg = np.meshgrid(np.arange(len(SPREAD_H)), np.arange(len(SPREAD_V)), indexing="ij")
    SHg, SVg = SHg.ravel(), SVg.ravel()
    done = 0
    before = float(judged(total[:, None, :])[0])
    for sweep in range(sweeps):
        changed = 0
        for n, k in enumerate(order):
            if progress is not None and n % 50 == 0:
                progress((sweep + n / len(order)) / sweeps, f"optimising the lens: sweep {sweep + 1}, cell {n} of "
                                                            f"{len(order)}")
            old = (choice.dh[k], choice.dv[k], choice.sh[k], choice.sv[k])
            m = sur.smeared(k, choice.sh[k], choice.sv[k])
            rest = total - sur.at_probes(k, m, choice.dh[k], choice.dv[k])[:, 0]
            # the deflection, the spread kept: all in the first sweep, then those near the present one
            fits = (np.abs(DEFLECT_H[DHg]) + SPREAD_H[choice.sh[k]] <= REACH) & (
                sur.depth_h[DHg, choice.sh[k]] + sur.depth_v[DVg, choice.sv[k]] <= sur.deepest)
            if sweep > 0:
                fits &= (np.abs(DHg - choice.dh[k]) <= NEAR) & (np.abs(DVg - choice.dv[k]) <= NEAR)
            cand = sur.at_probes(k, m, DHg[fits], DVg[fits])
            score = judged(rest[:, None, :] + cand) + _cost(DHg[fits], DVg[fits], choice.sh[k], choice.sv[k])
            best = int(np.argmin(score))
            choice.dh[k], choice.dv[k] = DHg[fits][best], DVg[fits][best]
            # the spread, the deflection kept
            fits = np.flatnonzero((np.abs(DEFLECT_H[choice.dh[k]]) + SPREAD_H[SHg] <= REACH) & (
                sur.depth_h[choice.dh[k], SHg] + sur.depth_v[choice.dv[k], SVg] <= sur.deepest))
            cand = np.stack([sur.at_probes(k, sur.smeared(k, SHg[q], SVg[q]), choice.dh[k], choice.dv[k])[:, 0]
                             for q in fits], axis=1)
            score = judged(rest[:, None, :] + cand) + _cost(choice.dh[k], choice.dv[k], SHg[fits], SVg[fits])
            best = int(np.argmin(score))
            choice.sh[k], choice.sv[k] = SHg[fits[best]], SVg[fits[best]]
            total = rest + cand[:, best]
            changed += old != (choice.dh[k], choice.dv[k], choice.sh[k], choice.sv[k])
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


def elements_of(system: al_lens.LensSystem, cells: list, choice: Choice) -> tuple:
    s = system.settings
    out = []
    for k, (i, j) in enumerate(cells):
        y0, z0 = system.y0 + i * s.cell_width, system.z0 + j * s.cell_height
        out.append(al_lens.Element(round(y0, 6), round(y0 + s.cell_width, 6), round(z0, 6),
                                   round(z0 + s.cell_height, 6), *choice.element(k)))
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


def optimise(settings: al_lens.LensSettings, frame: np.ndarray, evaluate, *, margin: float = 0.1,
             rounds: int = 2, blur: tuple[float, float] = (0.0, 0.0), spacing: float = 1.0,
             reflectance: float = 0.85, transmittance: float = 0.92, direct: bool = True, progress=None,
             log=None) -> Result:
    """The elements of every cell. evaluate(system) -> Distribution: the filament images (with the
    lamp's direct light) of a lens built; rounds: how often half its difference from the surrogate
    is carried back; blur (fit_blur, sigma H, V in degrees): a second view in which the beam must
    hold too – lower limits in the darker view, upper ones in the brighter."""
    def step(lo: float, hi: float):
        if progress is None:
            return None
        return lambda fraction, text: progress(lo + (hi - lo) * fraction, text)

    plane = al_lens.build(replace(settings, elements=(al_lens.Element(-1e9, 1e9, -1e9, 1e9),), wall_draft=0.0), frame)
    rays = lens_rays(plane, spacing=spacing, reflectance=reflectance, transmittance=transmittance,
                     progress=step(0.0, 0.1))
    pr = probes(settings.cutoff)
    h, v = grid()
    omega = al_photometry._solid_angle(h[None, :], v[:, None], DH, DV)
    direct_light = np.zeros((len(v), len(h)))
    if direct:
        direct_light, _ = al_photometry.direct_light(settings.lamp, plane.filament, h, v,
                                                     after=lambda o, d: plane.through(o, d, transmittance))
    sur = Surrogate(rays, pr, np.zeros(0), blur)
    sur.depth_h, sur.depth_v = depths(settings)
    sur.deepest = DEPTH * (settings.thickness - 0.3)              # (al_lens.build: at least 0.3 mm of glass left)
    if sur.depth_h[np.argmin(np.abs(DEFLECT_H)), 0] + sur.depth_v[np.argmin(np.abs(DEFLECT_V)), 0] > sur.deepest:
        raise DesignError("the lens is too thin for even plane elements")
    background = np.stack([blurred(direct_light, b) for b in sur.blurs])
    sur.background = background.reshape(len(sur.blurs), -1)[:, pr.bins]
    zero = (int(np.argmin(np.abs(DEFLECT_H))), int(np.argmin(np.abs(DEFLECT_V))), 0, 0)
    count = len(rays.cells)
    choice = Choice(*(np.full(count, z, dtype=np.int64) for z in zero))
    result = Result((), choice, rays.cells)
    share = 0.8 / (rounds + 1)
    for r in range(rounds + 1):
        choice, sweeps = descend(sur, choice, margin, sweeps=SWEEPS if r == 0 else LATER,
                                 progress=step(0.1 + r * share, 0.1 + r * share + 0.7 * share))
        predicted = sur.full(choice) / omega + background
        elements = elements_of(plane, rays.cells, choice)
        system = al_lens.build(replace(settings, elements=elements), frame,
                               progress=step(0.1 + r * share + 0.7 * share, 0.1 + r * share + 0.8 * share))
        dist = evaluate(system)
        model, seen = resampled(dist)
        actual = np.stack([blurred(model, b) for b in sur.blurs])       # the model in the surrogate's views
        at = lambda a: a.reshape(len(sur.blurs), -1)[:, pr.bins]       # noqa: E731
        score = float(objective(at(actual)[:, None, :], pr, margin)[0])
        result.rounds.append({"sweeps": sweeps, "surrogate": report(at(predicted), pr),
                              "model": report(at(actual), pr), "objective": score})
        if log is not None:
            log(r, sweeps, result.rounds[-1])
        if r == 0 or score < result.objective:       # the best round is kept
            result.elements, result.dist, result.system, result.objective = elements, dist, system, score
            result.choice = Choice(choice.dh.copy(), choice.dv.copy(), choice.sh.copy(), choice.sv.copy())
        if r < rounds:                               # half of what the surrogate misses, kept
            background = background + DAMPING * np.where(seen[None], actual - predicted, 0.0)
            sur.background = at(background)
    return result
