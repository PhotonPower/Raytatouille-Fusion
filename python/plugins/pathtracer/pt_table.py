"""Tabulated BSDFs (material kind "tabulated", ADR 0011 of Raytatouille Fusion, stage M1).

The data of a `.bsdf` file (rtt_fusion.material.Bsdf): on a grid of incidence angles θi and
wavelengths, a coherent part – mirror reflection R and refraction T into the index behind – and a
diffuse part, the BRDF / BTDF as mean values in bins of (θo, Δφ). Δφ is measured from the plane of
incidence on the forward side (0: the side of the mirror and of the straight-through direction).
The table is isotropic, unpolarised and two-sided: light arriving from the back sees the same
table with the normal turned (and the inverse index ratio).

Between the incidence angles the values are linear in θ; between the wavelengths of the file
linear in λ (resampled to the kernel's channels by `at_channels`); within a bin constant. A
material is a stack of lobes: mirror, refraction, diffuse reflection, diffuse transmission, chosen
in proportion to their power at the angle of wo. Sampling uses the table at the angle of wo for
both directions of transport (reciprocity); the weight f |cos| / pdf then corrects for tables that
are not reciprocal, as `f` always takes the direction the light really travels."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Table:
    """One tabulated material. Wavelengths in nm, angles in rad.

    nm (L), theta_in (J), theta_edges (K + 1), phi_edges (P + 1); reflectance, transmittance
    (J, L); brdf, btdf (J, L, K, P) or None; index_behind (L) or None."""
    nm: np.ndarray
    theta_in: np.ndarray
    theta_edges: np.ndarray
    phi_edges: np.ndarray
    reflectance: np.ndarray
    transmittance: np.ndarray
    brdf: np.ndarray | None = None
    btdf: np.ndarray | None = None
    index_behind: np.ndarray | None = None
    # per channel (at_channels): R, T (J, C); f (2, J, C, K·P) – 0 reflection, 1 transmission;
    # their powers S (2, J, C); the cumulative distributions over the bins (2, J·C, K·P), offset
    # by the row number (for one searchsorted over all rows); the index behind (C)
    _r: np.ndarray | None = None
    _t: np.ndarray | None = None
    _f: np.ndarray | None = None
    _s: np.ndarray | None = None
    _cdf: np.ndarray | None = None
    _nb: np.ndarray | None = None

    @staticmethod
    def from_dict(d: dict) -> "Table":
        """From the arrays of pt_setup.describe (lists or arrays), with checks."""
        def arr(key, optional=False):
            v = d.get(key)
            if v is None:
                if optional:
                    return None
                raise ValueError(f"tabulated material: {key} is missing")
            return np.asarray(v, dtype=float)
        t = Table(arr("nm"), arr("theta_in"), arr("theta_edges"), arr("phi_edges"), arr("reflectance"),
                  arr("transmittance"), arr("brdf", True), arr("btdf", True), arr("index_behind", True))
        j, l, k, p = t.theta_in.size, t.nm.size, t.theta_edges.size - 1, t.phi_edges.size - 1
        if t.reflectance.shape != (j, l) or t.transmittance.shape != (j, l):
            raise ValueError("tabulated material: reflectance and transmittance need (J, L) values")
        for f in (t.brdf, t.btdf):
            if f is not None and f.shape != (j, l, k, p):
                raise ValueError("tabulated material: brdf and btdf need (J, L, K, P) values")
        if (np.any(t.transmittance > 0) or t.btdf is not None) and t.index_behind is None:
            raise ValueError("tabulated material: transmission needs the index behind")
        return t

    def diffuse(self) -> bool:
        """Whether there is a diffuse part (else the material is specular)."""
        return any(f is not None and np.any(f > 0) for f in (self.brdf, self.btdf))

    def weights(self) -> np.ndarray:
        """∫ cos θ dω of the bins, both halves of ±Δφ, flattened (K·P)."""
        s2 = np.sin(self.theta_edges) ** 2
        return np.outer(np.diff(s2), np.diff(self.phi_edges)).reshape(-1)

    def at_channels(self, nm: np.ndarray) -> None:
        """Resamples the table to the kernel's wavelength channels (linear, constant outside)."""
        nm = np.atleast_1d(np.asarray(nm, dtype=float))
        j, kp = self.theta_in.size, (self.theta_edges.size - 1) * (self.phi_edges.size - 1)

        def along(a):  # interpolate the axis of wavelengths (axis 1)
            if self.nm.size == 1:
                return np.repeat(a[:, :1], nm.size, axis=1)
            i = np.clip(np.searchsorted(self.nm, nm, side="right") - 1, 0, self.nm.size - 2)
            w = np.clip((nm - self.nm[i]) / (self.nm[i + 1] - self.nm[i]), 0.0, 1.0)
            shape = (1, nm.size) + (1,) * (a.ndim - 2)
            return a[:, i] * (1 - w).reshape(shape) + a[:, i + 1] * w.reshape(shape)

        self._r, self._t = along(self.reflectance), along(self.transmittance)
        zero = np.zeros((j, nm.size, kp))
        self._f = np.stack([zero if f is None else along(f).reshape(j, nm.size, kp) for f in (self.brdf, self.btdf)])
        cell = self._f * self.weights()                                  # power per bin
        self._s = cell.sum(axis=3)
        cum = np.cumsum(cell, axis=3)
        with np.errstate(divide="ignore", invalid="ignore"):
            cum = np.where(cum[..., -1:] > 0, cum / cum[..., -1:], (np.arange(kp) + 1) / kp)
        rows = np.arange(j * nm.size, dtype=float)[None, :, None]
        self._cdf = cum.reshape(2, j * nm.size, kp) + rows
        if self.index_behind is not None:
            self._nb = along(self.index_behind[None, :])[0]
        else:
            self._nb = np.ones(nm.size)

    # ------------------------------------------------------------------ geometry
    def _row(self, theta: np.ndarray):
        """Row j and weight t of the incidence angles: θ between θi[j] and θi[j + 1] (constant outside)."""
        g = self.theta_in
        if g.size == 1:
            return np.zeros(theta.size, dtype=np.int64), np.zeros(theta.size)
        j = np.clip(np.searchsorted(g, theta, side="right") - 1, 0, g.size - 2)
        t = np.clip((theta - g[j]) / (g[j + 1] - g[j]), 0.0, 1.0)
        return j, t

    def _bin(self, theta_o: np.ndarray, dphi: np.ndarray) -> np.ndarray:
        k = np.clip(np.searchsorted(self.theta_edges, theta_o, side="right") - 1, 0, self.theta_edges.size - 2)
        p = np.clip(np.searchsorted(self.phi_edges, dphi, side="right") - 1, 0, self.phi_edges.size - 2)
        return k * (self.phi_edges.size - 1) + p

    def energies(self, cos_in: np.ndarray, c: np.ndarray):
        """R, T, diffuse reflection and transmission at the incidence |cos| and channels c."""
        j, t = self._row(np.arccos(np.clip(np.abs(cos_in), 0.0, 1.0)))

        def lerp(a):
            return a[j, c] * (1 - t) + a[j + 1 if self.theta_in.size > 1 else j, c] * t
        return lerp(self._r), lerp(self._t), lerp(self._s[0]), lerp(self._s[1]), j, t

    def f(self, n: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
        """f for light arriving from a (pointing away from the surface) and leaving towards b."""
        ca, cb = _dot(n, a), _dot(n, b)
        through = (ca * cb < 0).astype(np.int64)
        j, t = self._row(np.arccos(np.clip(np.abs(ca), 0.0, 1.0)))
        cell = self._bin(np.arccos(np.clip(np.abs(cb), 0.0, 1.0)), _dphi(n, a, b, ca, cb))
        j1 = j + 1 if self.theta_in.size > 1 else j
        return self._f[through, j, c, cell] * (1 - t) + self._f[through, j1, c, cell] * t

    def density(self, n: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
        """Density (per solid angle) of sampling b from a: f(a → b) |cos b| / power at a."""
        r, tr, sr, st, _, _ = self.energies(_dot(n, a), c)
        total = r + tr + sr + st
        dens = self.f(n, a, b, c) * np.abs(_dot(n, b))
        return np.divide(dens, total, out=np.zeros(len(a)), where=total > 0)

    def sample(self, n: np.ndarray, wo: np.ndarray, c: np.ndarray, rng, radiance: bool):
        """(wi, weight, pdf, delta) for each point; pdf 0 and delta True for mirror and refraction."""
        count = len(wo)
        co = _dot(n, wo)
        side = np.where(co >= 0, 1.0, -1.0)
        ns = n * side[:, None]
        aco = np.abs(co)
        r, tr, sr, st, j, t = self.energies(co, c)
        total = r + tr + sr + st
        u = rng.random((count, 6))
        x = u[:, 0] * total
        mirror = x < r
        refract = ~mirror & (x < r + tr)
        scatter_r = ~mirror & ~refract & (x < r + tr + sr)
        scatter_t = ~mirror & ~refract & ~scatter_r & (total > 0)
        wi = np.zeros((count, 3))
        weight = np.zeros(count)
        pdf = np.zeros(count)
        delta = mirror | refract
        # mirror
        wi[mirror] = (2 * aco[mirror])[:, None] * ns[mirror] - wo[mirror]
        weight[mirror] = total[mirror]
        # refraction: front side -> index behind; back side -> out again
        if refract.any():
            i = np.nonzero(refract)[0]
            nb = self._nb[c[i]]
            eta = np.where(side[i] > 0, 1.0 / nb, nb)                     # n(side of wo) / n(other side)
            sin2 = eta ** 2 * (1 - aco[i] ** 2)
            cos_t = np.sqrt(np.clip(1 - sin2, 0.0, None))
            total_reflection = sin2 >= 1
            refr = -eta[:, None] * wo[i] + (eta * aco[i] - cos_t)[:, None] * ns[i]
            refl = (2 * aco[i])[:, None] * ns[i] - wo[i]
            wi[i] = np.where(total_reflection[:, None], refl, refr)
            weight[i] = total[i] * np.where(total_reflection | (not radiance), 1.0, eta ** 2)
        # diffuse: a row (θi[j] or θi[j + 1], by power), a bin, a direction in the bin
        diff = np.nonzero(scatter_r | scatter_t)[0]
        if diff.size:
            lobe = scatter_t[diff].astype(np.int64)
            jj, tt, cc = j[diff], t[diff], c[diff]
            j1 = jj + 1 if self.theta_in.size > 1 else jj
            s0, s1 = self._s[lobe, jj, cc] * (1 - tt), self._s[lobe, j1, cc] * tt
            row = np.where(u[diff, 1] * (s0 + s1) < s0, jj, j1)
            channels = self._r.shape[1]
            index = row * channels + cc
            kp = self._cdf.shape[2]
            cell = np.empty(diff.size, dtype=np.int64)
            for lb in (0, 1):
                sel = np.nonzero(lobe == lb)[0]
                if sel.size:
                    flat = self._cdf[lb].reshape(-1)
                    found = np.searchsorted(flat, u[diff[sel], 2] + index[sel], side="right")
                    cell[sel] = np.clip(found - index[sel] * kp, 0, kp - 1)
            p_count = self.phi_edges.size - 1
            k, p = cell // p_count, cell % p_count
            s2 = np.sin(self.theta_edges) ** 2
            sin2_o = s2[k] + (s2[k + 1] - s2[k]) * u[diff, 3]
            dphi = self.phi_edges[p] + (self.phi_edges[p + 1] - self.phi_edges[p]) * u[diff, 4]
            dphi = np.where(u[diff, 5] < 0.5, dphi, -dphi)
            sin_o, cos_o = np.sqrt(sin2_o), np.sqrt(np.clip(1 - sin2_o, 0.0, None))
            ex, ey = _tangents(ns[diff], wo[diff])
            up = np.where(lobe == 1, -1.0, 1.0) * cos_o
            w = (-sin_o * np.cos(dphi))[:, None] * ex + (sin_o * np.sin(dphi))[:, None] * ey + up[:, None] * ns[diff]
            wi[diff] = w
            nd, wod = n[diff], wo[diff]
            pdf[diff] = self.density(nd, wod, w, cc)
            f = self.f(nd, w, wod, cc) if radiance else self.f(nd, wod, w, cc)
            weight[diff] = np.divide(f * np.abs(_dot(nd, w)), pdf[diff], out=np.zeros(diff.size),
                                     where=pdf[diff] > 0)
        return wi, weight, pdf, delta


def _dot(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.einsum("ij,ij->i", a, b)


def _tangents(ns: np.ndarray, wo: np.ndarray):
    """ex: towards wo in the tangent plane (any tangent at normal incidence), ey = ns × ex."""
    t = wo - _dot(ns, wo)[:, None] * ns
    length = np.linalg.norm(t, axis=1)
    helper = np.where((np.abs(ns[:, 0]) < 0.9)[:, None], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    fallback = np.cross(ns, helper)
    fallback /= np.linalg.norm(fallback, axis=1, keepdims=True)
    ex = np.where((length > 1e-12)[:, None], t / np.maximum(length, 1e-300)[:, None], fallback)
    return ex, np.cross(ns, ex)


def _dphi(n: np.ndarray, a: np.ndarray, b: np.ndarray, ca: np.ndarray, cb: np.ndarray) -> np.ndarray:
    """Azimuth of b from the forward side of the plane of incidence of a (0 … π)."""
    at = a - ca[:, None] * n
    bt = b - cb[:, None] * n
    la, lb = np.linalg.norm(at, axis=1), np.linalg.norm(bt, axis=1)
    ok = (la > 1e-12) & (lb > 1e-12)
    cos = -_dot(at, bt) / np.where(ok, la * lb, 1.0)
    return np.where(ok, np.arccos(np.clip(cos, -1.0, 1.0)), 0.0)
