"""Photometry: luminaire files (IES LM-63, EULUMDAT) as directional distributions of sources,
and the eye's sensitivity V(lambda) for lumen, lux and candela. NumPy only.

A distribution is the luminous intensity over the directions around an axis: theta from the
axis (0 … 180°, in a luminaire file 0 is straight down), phi around it (the C-planes). Only its
shape is used here – the flux of a source comes from the table of sources."""

from __future__ import annotations

import numpy as np

LM_PER_W = 683.0     # at 555 nm

# CIE 1924 photopic luminous efficiency, 380 … 780 nm in steps of 10 nm
_V = [0.000039, 0.00012, 0.000396, 0.00121, 0.0040, 0.0116, 0.023, 0.038, 0.060, 0.09098, 0.13902, 0.20802,
      0.323, 0.503, 0.710, 0.862, 0.954, 0.99495, 0.995, 0.952, 0.870, 0.757, 0.631, 0.503, 0.381, 0.265,
      0.175, 0.107, 0.061, 0.032, 0.017, 0.00821, 0.004102, 0.002091, 0.001047, 0.00052, 0.000249, 0.00012,
      0.00006, 0.00003, 0.000015]


def v_lambda(nm) -> np.ndarray:
    """The eye's sensitivity (photopic, 0 … 1) at wavelengths in nm; 0 outside 380 … 780 nm."""
    at = np.insert(380.0 + 10.0 * np.arange(len(_V)), 18, 555.0)        # … and the maximum, 1 at 555 nm
    return np.interp(np.asarray(nm, dtype=float), at, np.insert(_V, 18, 1.0), left=0.0, right=0.0)


def lumens_per_watt(wavelengths, shares) -> float:
    """Of light with the given shares of its radiant flux at the wavelengths."""
    shares = np.asarray(shares, dtype=float)
    return float(LM_PER_W * (v_lambda(wavelengths) * shares).sum() / shares.sum())


# ---------------------------------------------------------------------------- distributions
class Distribution:
    """Intensity over the directions as a table of cells (0.5° in theta; 2° in phi unless it is
    the same all around): constant in a cell, scaled so that its integral over the sphere is 1.
    Directions are drawn in proportion to it."""

    def __init__(self, theta, phi, intensity):
        """theta (degrees, rising), phi (degrees, rising, covering the full turn – or a single
        value for a distribution that is the same all around) and intensity[phi, theta]; zero
        outside the range of theta."""
        theta = np.asarray(theta, dtype=float)
        phi = np.asarray(phi, dtype=float)
        intensity = np.asarray(intensity, dtype=float).reshape(len(phi), len(theta))
        if len(theta) < 2 or np.any(np.diff(theta) <= 0) or np.any(intensity < 0):
            raise ValueError("distribution: angles must rise and intensities must not be negative")
        self.cells_t = 360
        self.cells_p = 1 if len(phi) == 1 else 180
        edges = np.linspace(0.0, 180.0, self.cells_t + 1)
        centre_t = 0.5 * (edges[:-1] + edges[1:])
        centre_p = (np.arange(self.cells_p) + 0.5) * 360.0 / self.cells_p
        along = np.stack([np.interp(centre_t, theta, row, left=0.0, right=0.0) for row in intensity])   # [phi, cell]
        if len(phi) == 1:
            table = along.T                                                                # [cell t, 1]
        else:
            table = np.stack([np.interp(centre_p, phi, along[:, k], period=360.0) for k in range(self.cells_t)])
        self.cos_edges = np.cos(np.radians(edges))
        solid = (self.cos_edges[:-1] - self.cos_edges[1:])[:, None] * (2 * np.pi / self.cells_p)
        total = float((table * solid).sum())
        if not total > 0:
            raise ValueError("distribution: no light in any direction")
        self.density = table / total                         # per steradian, [cell theta, cell phi]
        self.cdf = np.cumsum((self.density * solid).ravel())
        self.symmetric = len(phi) == 1

    def _cell(self, cos: np.ndarray, phi: np.ndarray):
        theta = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
        it = np.minimum((theta * self.cells_t / 180.0).astype(np.int64), self.cells_t - 1)
        ip = np.minimum((np.mod(phi, 2 * np.pi) * self.cells_p / (2 * np.pi)).astype(np.int64), self.cells_p - 1)
        return it, ip

    def eval(self, cos: np.ndarray, phi: np.ndarray) -> np.ndarray:
        """Density (per steradian) of the direction with cos(theta) and phi (radians)."""
        it, ip = self._cell(cos, phi)
        return self.density[it, ip]

    def sample(self, n: int, rng: np.random.Generator):
        """n directions drawn by the distribution: cos(theta), phi, density."""
        cell = np.minimum(np.searchsorted(self.cdf, rng.random(n) * self.cdf[-1], side="right"), len(self.cdf) - 1)
        it, ip = cell // self.cells_p, cell % self.cells_p
        cos = self.cos_edges[it] - rng.random(n) * (self.cos_edges[it] - self.cos_edges[it + 1])
        phi = (ip + rng.random(n)) * (2 * np.pi / self.cells_p)
        return cos, phi, self.density[it, ip]


def _all_around(phi: np.ndarray, cd: np.ndarray):
    """Planes 0 … 90 or 0 … 180 mirrored to the full turn (planes 0 … 360 as they are)."""
    last = phi[-1]
    if abs(last - 90.0) < 1e-6:                              # a quarter: mirror at the 90° plane …
        phi, cd = np.concatenate([phi, 180.0 - phi[-2::-1]]), np.concatenate([cd, cd[-2::-1]])
        last = 180.0
    if abs(last - 180.0) < 1e-6:                             # … and a half at the 0 – 180° plane
        phi, cd = np.concatenate([phi, 360.0 - phi[-2:0:-1]]), np.concatenate([cd, cd[-2:0:-1]])
    elif abs(last - 360.0) < 1e-6:
        phi, cd = phi[:-1], cd[:-1]
    else:
        raise ValueError(f"luminaire file: planes up to {last:g}° – expected 0, 90, 180 or 360")
    return phi, cd


def parse_ies(text: str) -> Distribution:
    """A distribution from the text of an IES LM-63 file (photometry of type C)."""
    lines = text.replace("\r", "").split("\n")
    tilt = next((k for k, line in enumerate(lines) if line.strip().upper().startswith("TILT")), None)
    if tilt is None:
        raise ValueError("IES file: no TILT line")
    kind = lines[tilt].split("=", 1)[1].strip().upper() if "=" in lines[tilt] else ""
    try:
        numbers = [float(v) for v in " ".join(lines[tilt + 1:]).replace(",", " ").split()]
    except ValueError:
        raise ValueError("IES file: text among the numbers") from None
    if kind == "INCLUDE":                                    # lamp geometry, number of pairs, angles, factors
        pairs = int(numbers[1])
        numbers = numbers[2 + 2 * pairs:]
    elif kind != "NONE":
        raise ValueError(f"IES file: TILT={kind} is not supported")
    if len(numbers) < 13:
        raise ValueError("IES file: too short")
    n_t, n_p, photometry = int(numbers[3]), int(numbers[4]), int(numbers[5])
    if photometry != 1:
        raise ValueError("IES file: only photometry of type C is supported")
    data = numbers[13:]
    if len(data) < n_t + n_p + n_t * n_p:
        raise ValueError("IES file: fewer values than its angles need")
    theta = np.asarray(data[:n_t])
    phi = np.asarray(data[n_t:n_t + n_p])
    cd = np.asarray(data[n_t + n_p:n_t + n_p + n_t * n_p]).reshape(n_p, n_t)
    if n_p > 1:
        phi, cd = _all_around(phi, cd)
    return Distribution(theta, phi, cd)


def parse_ldt(text: str) -> Distribution:
    """A distribution from the text of an EULUMDAT (.ldt) file."""
    lines = [line.strip() for line in text.replace("\r", "").split("\n")]
    try:
        symmetry, planes, n_g = int(float(lines[2])), int(float(lines[3])), int(float(lines[5]))
        sets = int(float(lines[25]))
        at = 26 + 6 * sets + 10
        c = np.asarray([float(v.replace(",", ".")) for v in lines[at:at + planes]])
        gamma = np.asarray([float(v.replace(",", ".")) for v in lines[at + planes:at + planes + n_g]])
        given = {0: planes, 1: 1, 2: planes // 2 + 1, 3: planes // 2 + 1, 4: planes // 4 + 1}[symmetry]
        start = at + planes + n_g
        cd = np.asarray([float(v.replace(",", ".")) for v in lines[start:start + given * n_g]]).reshape(given, n_g)
    except (ValueError, IndexError, KeyError):
        raise ValueError("EULUMDAT file: not in the expected form") from None
    if symmetry == 1:
        return Distribution(gamma, [0.0], cd)
    if symmetry == 0:
        return Distribution(gamma, c, cd)
    if symmetry == 3:                                        # planes C90 … C270 given: mirror at C90 – C270
        first = int(np.argmin(np.abs(c - 90.0)))
        have = c[first:first + given]
        full = np.stack([cd[int(np.argmin(np.abs(have - (a if 90.0 <= a <= 270.0 else (180.0 - a) % 360.0))))]
                         for a in c])
        return Distribution(gamma, c, full)
    phi, cd = _all_around(c[:given], cd)                     # C0 … C180 or C0 … C90
    return Distribution(gamma, phi, cd)


def load(path: str) -> Distribution:
    """A distribution from an .ies or .ldt file (by its content if the ending says nothing)."""
    try:
        with open(path, encoding="latin-1") as f:
            text = f.read()
    except OSError as e:
        raise ValueError(f"luminaire file {path!r}: {e.strerror or e}") from None
    if path.lower().endswith(".ldt") or (not path.lower().endswith(".ies") and "TILT" not in text.upper()):
        return parse_ldt(text)
    return parse_ies(text)
