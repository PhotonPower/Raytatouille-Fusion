"""Materials: how a surface scatters light, for many points at once.

All directions point away from the surface point; `n` is the surface normal (unit) on the front
side. One channel (radiometric, no colour). Kinds:

  absorber     takes everything
  diffuse      Lambertian: reflects `reflectance`, lets `transmittance` through (diffusely)
  mirror       ideal mirror with `reflectance`
  glossy       a lobe around the mirror direction (normalised Phong), width from `roughness`
  glass        smooth dielectric with refractive index `ior` inside (behind the front side),
               Fresnel reflection and refraction; `absorption` (1/mm) inside (Beer–Lambert).
               With an Abbe number `abbe` the index depends on the wavelength: `ior` is n_d
               (587.56 nm), n = A + B / lambda² through n_d and the dispersion n_F − n_C

A `spectrum` – pairs (wavelength / nm, value) – replaces the reflectance (diffuse, mirror, glossy)
or the absorption (glass) by values that depend on the wavelength: straight lines between the
pairs, the first / last value outside them.
  metal        a rough metal: microfacets (GGX) with the width roughness², reflecting `reflectance`
               head-on and more at grazing angles (Schlick)
  frosted      rough glass: the same microfacets on a dielectric – reflects and refracts into
               lobes; `ior`, `abbe`, `absorption` as for glass
  detector     no surface at all for the light: rays pass as if it were not there. Only a place
               to measure the irradiance (the scene keeps such faces out of the tracing)
  tabulated    a BSDF from a table (a `.bsdf` file: simulated or measured, see pt_table): mirror
               reflection and refraction plus a diffuse part, on a grid of incidence angles and
               wavelengths

mirror and glass scatter into single directions ("specular"); they cannot be connected to
other points, only followed."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import pt_table

ABSORBER, DIFFUSE, MIRROR, GLOSSY, GLASS, DETECTOR, METAL, FROSTED, TABULATED = range(9)
KINDS = ["absorber", "diffuse", "mirror", "glossy", "glass", "detector", "metal", "frosted", "tabulated"]


@dataclass
class Materials:
    """Material table: one entry per material, arrays indexed by material number."""
    kind: np.ndarray
    reflectance: np.ndarray
    transmittance: np.ndarray
    exponent: np.ndarray                 # glossy: Phong exponent
    ior: np.ndarray
    absorption: np.ndarray               # 1/mm
    names: list[str]
    abbe: np.ndarray | None = None       # Abbe number V_d of glass (0: the index is constant)
    spectra: list | None = None          # per material: pairs (nm, value) or None
    alpha: np.ndarray | None = None      # metal, frosted: width of the microfacets' slopes (roughness²)
    ior_table: np.ndarray | None = None  # index [material, wavelength], set by wavelengths()
    rho_table: np.ndarray | None = None  # reflectance [material, wavelength]
    absorb_table: np.ndarray | None = None
    tables: dict | None = None           # tabulated: material number -> pt_table.Table

    @staticmethod
    def from_rows(rows: list[dict]) -> "Materials":
        """rows: dicts with name, kind and (optional) reflectance, transmittance, roughness, ior,
        absorption. ValueError for values that make no sense."""
        if not rows:
            raise ValueError("no materials")
        names = []
        cols: dict[str, list[float]] = {k: [] for k in ("kind", "rho", "tau", "exp", "ior", "abs", "abbe", "alpha")}
        spectra = []
        tables = {}
        for row in rows:
            name = str(row.get("name", "")).strip()
            kind = str(row.get("kind", "diffuse")).strip().lower()
            if not name:
                raise ValueError("a material has no name")
            if name in names:
                raise ValueError(f"material {name!r} is defined twice")
            if kind not in KINDS:
                raise ValueError(f"material {name!r}: unknown kind {kind!r} (one of {', '.join(KINDS)})")
            rho = float(row.get("reflectance", 0.0))
            tau = float(row.get("transmittance", 0.0)) if kind == "diffuse" else 0.0
            rough = float(row.get("roughness", 0.2))
            ior = float(row.get("ior", 1.5))
            absorb = float(row.get("absorption", 0.0))
            if rho < 0 or tau < 0 or rho + tau > 1 + 1e-12:
                raise ValueError(f"material {name!r}: reflectance + transmittance must lie in 0 … 1")
            if kind in ("glossy", "metal", "frosted") and not 0 < rough <= 1:
                raise ValueError(f"material {name!r}: roughness must lie in 0 … 1 (not 0)")
            if kind in ("glass", "frosted") and ior < 1:
                raise ValueError(f"material {name!r}: refractive index below 1")
            if absorb < 0:
                raise ValueError(f"material {name!r}: negative absorption")
            abbe = float(row.get("abbe", 0.0)) if kind in ("glass", "frosted") else 0.0
            if abbe < 0:
                raise ValueError(f"material {name!r}: negative Abbe number")
            cols["abbe"].append(abbe)
            pairs = sorted((float(nm), float(v)) for nm, v in (row.get("spectrum") or ()))
            if pairs and kind in ("absorber", "detector"):
                pairs = []
            for nm, v in pairs:
                if nm <= 0 or v < 0 or (kind not in ("glass", "frosted") and v + tau > 1 + 1e-12):
                    raise ValueError(f"material {name!r}: its spectrum needs wavelengths above 0 and values "
                                     + ("that are not negative" if kind in ("glass", "frosted") else
                                        "in 0 … 1 (with the transmittance)"))
            spectra.append(pairs or None)
            if kind == "tabulated":
                if not isinstance(row.get("table"), dict):
                    raise ValueError(f"material {name!r}: a tabulated material needs its BSDF file")
                try:
                    tables[len(names)] = pt_table.Table.from_dict(row["table"])
                except ValueError as e:
                    raise ValueError(f"material {name!r}: {e}") from None
                tables[len(names)].at_channels(np.array([550.0]))
            names.append(name)
            cols["kind"].append(KINDS.index(kind))
            cols["rho"].append(rho)
            cols["tau"].append(tau)
            cols["exp"].append(2.0 / max(rough, 1e-3) ** 2 - 2.0)
            cols["alpha"].append(max(rough * rough, 1e-4))
            cols["ior"].append(ior)
            cols["abs"].append(absorb)
        return Materials(np.asarray(cols["kind"], dtype=np.int64), np.asarray(cols["rho"]), np.asarray(cols["tau"]),
                         np.asarray(cols["exp"]), np.asarray(cols["ior"]), np.asarray(cols["abs"]), names,
                         np.asarray(cols["abbe"]), spectra, np.asarray(cols["alpha"]), tables=tables or None)

    def wavelengths(self, nm) -> np.ndarray:
        """Sets and returns the refractive index of every material at the wavelengths (nm):
        [material, wavelength]. Sampling with a `channel` then uses it."""
        lam = np.asarray(nm, dtype=float)[None, :] / 1000.0             # µm
        f, dd, c = 0.48613, 0.58756, 0.65627                            # F, d and C line
        abbe = np.zeros(len(self.ior)) if self.abbe is None else self.abbe
        nd = self.ior[:, None]
        with np.errstate(divide="ignore", invalid="ignore"):
            b = np.where(abbe > 0, (self.ior - 1) / (abbe * (1 / f ** 2 - 1 / c ** 2)), 0.0)[:, None]
        self.ior_table = nd + b * (1 / lam ** 2 - 1 / dd ** 2)
        count = len(np.atleast_1d(nm))
        self.rho_table = np.repeat(self.reflectance[:, None], count, axis=1)
        self.absorb_table = np.repeat(self.absorption[:, None], count, axis=1)
        for k, pairs in enumerate(self.spectra or []):
            if pairs:
                at = np.interp(np.atleast_1d(np.asarray(nm, dtype=float)), [p[0] for p in pairs], [p[1] for p in pairs])
                (self.absorb_table if self.kind[k] in (GLASS, FROSTED) else self.rho_table)[k] = at
        for k, table in (self.tables or {}).items():
            table.at_channels(np.atleast_1d(np.asarray(nm, dtype=float)))
        return self.ior_table

    def _rho(self, m: np.ndarray, channel) -> np.ndarray:
        if channel is None or self.rho_table is None:
            return self.reflectance[m]
        return self.rho_table[m, channel]

    def absorbs(self, m: np.ndarray, channel=None) -> np.ndarray:
        """Absorption (1/mm) of the materials m at the paths' wavelengths."""
        if channel is None or self.absorb_table is None:
            return self.absorption[m]
        return self.absorb_table[m, channel]

    def specular(self, m: np.ndarray) -> np.ndarray:
        """Materials that scatter only into single directions (no connections end on them). A
        tabulated material without a diffuse part is one; with both parts it is not, but its
        mirror and refraction events are (the integrators see them as pdf 0 with a weight)."""
        k = self.kind[m]
        out = (k == MIRROR) | (k == GLASS)
        for i, table in (self.tables or {}).items():
            if not table.diffuse():
                out = out | (np.asarray(m) == i)
        return out

    def _tabulated(self, m: np.ndarray):
        """(table, rows) for each tabulated material among m."""
        for i, table in (self.tables or {}).items():
            rows = np.nonzero(m == i)[0]
            if rows.size:
                yield table, rows

    # ------------------------------------------------------------------ evaluation
    def _ior(self, m: np.ndarray, channel) -> np.ndarray:
        if channel is None or self.ior_table is None:
            return self.ior[m]
        return self.ior_table[m, channel]

    def eval(self, m: np.ndarray, n: np.ndarray, wo: np.ndarray, wi: np.ndarray, channel=None,
             radiance: bool = True, outside=None):
        """f(wo, wi) in 1/sr and the densities (per solid angle) of sampling wi from wo and wo
        from wi. Zero for specular materials. channel: number of each path's wavelength.
        radiance: wo points towards the sensor and the light arrives from wi (a vertex of an eye
        subpath); False: the light arrives from wo (a vertex of a light subpath) – it matters
        for refraction through frosted glass, where radiance changes with the square of the index.
        outside: the index in front of each surface (default 1, air; another glass that touches)."""
        k = self.kind[m]
        co = np.einsum("ij,ij->i", n, wo)
        ci = np.einsum("ij,ij->i", n, wi)
        same = co * ci > 0
        f = np.zeros(len(m))
        p_fwd = np.zeros(len(m))
        p_rev = np.zeros(len(m))
        d = np.nonzero(k == DIFFUSE)[0]
        if d.size:
            rho, tau = self._rho(m[d], None if channel is None else channel[d]), self.transmittance[m[d]]
            part = np.where(same[d], rho, tau)
            total = rho + tau
            pick = np.divide(part, total, out=np.zeros(len(d)), where=total > 0)
            f[d] = part / np.pi
            p_fwd[d] = pick * np.abs(ci[d]) / np.pi
            p_rev[d] = pick * np.abs(co[d]) / np.pi
        g = np.nonzero((k == GLOSSY) & same)[0]
        if g.size:
            e = self.exponent[m[g]]
            # cosine between wi and the mirror direction of wo (symmetric in wo and wi)
            c = np.clip(2 * co[g] * ci[g] - np.einsum("ij,ij->i", wo[g], wi[g]), 0.0, 1.0)
            lobe = c ** e
            f[g] = self._rho(m[g], None if channel is None else channel[g]) * (e + 2) / (2 * np.pi) * lobe
            p_fwd[g] = (e + 1) / (2 * np.pi) * lobe
            p_rev[g] = p_fwd[g]
        g = np.nonzero((k == METAL) & same)[0]
        if g.size:
            alpha = self.alpha[m[g]]
            h = wo[g] + wi[g]
            h /= np.maximum(np.linalg.norm(h, axis=1, keepdims=True), 1e-300)
            dist = _ggx(alpha, np.einsum("ij,ij->i", n[g], h))
            g_o, g_i = _g1(alpha, co[g]), _g1(alpha, ci[g])
            f0 = self._rho(m[g], None if channel is None else channel[g])
            fresnel = f0 + (1 - f0) * (1 - np.clip(np.einsum("ij,ij->i", wo[g], h), 0.0, 1.0)) ** 5
            f[g] = fresnel * dist * g_o * g_i / (4 * np.abs(co[g] * ci[g]))
            p_fwd[g] = g_o * dist / (4 * np.abs(co[g]))
            p_rev[g] = g_i * dist / (4 * np.abs(ci[g]))
        t = np.nonzero((k == FROSTED) & (co != 0) & (ci != 0))[0]
        if t.size:
            alpha = self.alpha[m[t]]
            ior = self._ior(m[t], None if channel is None else channel[t])
            front = 1.0 if outside is None else outside[t]
            eta_o = np.where(co[t] > 0, front, ior)           # index on the side of wo, of wi, beyond wo's side
            eta_i = np.where(ci[t] > 0, front, ior)
            beyond = np.where(co[t] > 0, ior, front)
            h = np.where(same[t][:, None], wo[t] + wi[t], eta_o[:, None] * wo[t] + eta_i[:, None] * wi[t])
            length = np.linalg.norm(h, axis=1)
            h = h / np.maximum(length, 1e-300)[:, None]
            h *= (np.sign(np.einsum("ij,ij->i", h, n[t])) * np.sign(co[t]))[:, None]      # onto wo's side
            woh, wih = np.einsum("ij,ij->i", wo[t], h), np.einsum("ij,ij->i", wi[t], h)
            ok = (length > 1e-12) & (woh > 0) & np.where(same[t], wih > 0, wih < 0)
            fresnel = _fresnel(np.clip(woh, 0.0, 1.0), eta_o / beyond)
            dist = _ggx(alpha, np.einsum("ij,ij->i", n[t], h))
            g_o, g_i = _g1(alpha, co[t]), _g1(alpha, ci[t])
            aco, aci = np.abs(co[t]), np.abs(ci[t])
            with np.errstate(divide="ignore", invalid="ignore"):
                through = (1 - fresnel) * dist * np.abs(woh * wih) / (eta_o * woh + eta_i * wih) ** 2
            through = np.where(np.isfinite(through), through, 0.0)
            f[t] = np.where(ok, np.where(same[t], fresnel * dist * g_o * g_i / (4 * aco * aci),
                                         through * g_o * g_i / (aco * aci) * (eta_o if radiance else eta_i) ** 2), 0.0)
            p_fwd[t] = np.where(ok, np.where(same[t], fresnel * g_o * dist / (4 * aco),
                                             through * g_o * eta_i ** 2 / aco), 0.0)
            p_rev[t] = np.where(ok, np.where(same[t], fresnel * g_i * dist / (4 * aci),
                                             through * g_i * eta_o ** 2 / aci), 0.0)
        for table, r in self._tabulated(m):                  # the diffuse part (mirror, refraction: deltas)
            c = np.zeros(len(r), dtype=np.int64) if channel is None else channel[r]
            a, b = (wi[r], wo[r]) if radiance else (wo[r], wi[r])          # the light goes a -> b
            f[r] = table.f(n[r], a, b, c)
            p_fwd[r] = table.density(n[r], wo[r], wi[r], c)
            p_rev[r] = table.density(n[r], wi[r], wo[r], c)
        return f, p_fwd, p_rev

    # ------------------------------------------------------------------ sampling
    def sample(self, m: np.ndarray, n: np.ndarray, wo: np.ndarray, rng: np.random.Generator, radiance: bool,
               channel: np.ndarray | None = None, outside=None, straight=None):
        """A scattered direction wi for each point: (wi, weight, pdf) with weight = f |cos| / pdf
        (0: absorbed) and pdf per solid angle (0 for specular materials). `radiance`: the path
        comes from the sensor (refraction then scales by the squared ratio of the indices).
        `channel`: number of each path's wavelength (see wavelengths()). outside: the index in
        front of each surface (default 1). straight: where the path goes on unchanged (a surface
        between two parts of the same medium)."""
        count = len(m)
        k = self.kind[m]
        co = np.einsum("ij,ij->i", n, wo)
        side = np.where(co >= 0, 1.0, -1.0)
        wi = np.zeros((count, 3))
        weight = np.zeros(count)
        pdf = np.zeros(count)
        u1, u2, u3 = rng.random(count), rng.random(count), rng.random(count)

        d = np.nonzero(k == DIFFUSE)[0]
        if d.size:
            rho, tau = self._rho(m[d], None if channel is None else channel[d]), self.transmittance[m[d]]
            total = rho + tau
            reflect = u3[d] * total < rho
            axis = n[d] * (side[d] * np.where(reflect, 1.0, -1.0))[:, None]
            w, cos = _cosine(axis, u1[d], u2[d])
            wi[d] = w
            weight[d] = total
            pdf[d] = np.divide(np.where(reflect, rho, tau), total, out=np.zeros(len(d)), where=total > 0) * cos / np.pi
        s = np.nonzero(k == MIRROR)[0]
        if s.size:
            wi[s] = 2 * co[s][:, None] * n[s] - wo[s]
            weight[s] = self._rho(m[s], None if channel is None else channel[s])
        g = np.nonzero(k == GLOSSY)[0]
        if g.size:
            e = self.exponent[m[g]]
            mirror = 2 * co[g][:, None] * n[g] - wo[g]
            cos_a = u1[g] ** (1.0 / (e + 1))
            w = _around(mirror, cos_a, 2 * np.pi * u2[g])
            ci = np.einsum("ij,ij->i", n[g], w)
            ok = ci * co[g] > 0
            wi[g] = w
            weight[g] = np.where(ok, self._rho(m[g], None if channel is None else channel[g]) * (e + 2) / (e + 1)
                                 * np.abs(ci), 0.0)
            pdf[g] = (e + 1) / (2 * np.pi) * cos_a ** e
        g = np.nonzero((k == METAL) | (k == FROSTED))[0]
        if g.size:                                           # a microfacet seen from wo, then its mirror / lens
            alpha = self.alpha[m[g]]
            nn = n[g] * side[g][:, None]
            h = _visible_normal(alpha, nn, wo[g], u1[g], u2[g])
            woh = np.clip(np.einsum("ij,ij->i", wo[g], h), 0.0, 1.0)
            aco = np.maximum(np.abs(co[g]), 1e-300)
            dist = _ggx(alpha, np.einsum("ij,ij->i", nn, h))
            g_o = _g1(alpha, co[g])
            metal = k[g] == METAL
            ior = self._ior(m[g], None if channel is None else channel[g])
            front = 1.0 if outside is None else outside[g]
            eta = np.where(co[g] >= 0, front / ior, ior / front)   # n(side of wo) / n(other side)
            f0 = self._rho(m[g], None if channel is None else channel[g])
            fresnel = np.where(metal, f0 + (1 - f0) * (1 - woh) ** 5, _fresnel(woh, eta))
            reflect = metal | (u3[g] < fresnel)
            cos_t = np.sqrt(np.clip(1 - eta ** 2 * (1 - woh ** 2), 0.0, None))
            w = np.where(reflect[:, None], 2 * woh[:, None] * h - wo[g],
                         -eta[:, None] * wo[g] + (eta * woh - cos_t)[:, None] * h)
            ci = np.einsum("ij,ij->i", nn, w)
            g_i = _g1(alpha, ci)
            ok = np.where(reflect, ci > 0, ci < 0) & (woh > 0)
            wi[g] = w
            weight[g] = np.where(ok, g_i * np.where(metal, fresnel, np.where(reflect | (not radiance), 1.0, eta ** 2)),
                                 0.0)
            eta_o = np.where(co[g] >= 0, front, ior)
            eta_i = np.where(co[g] >= 0, ior, front)
            with np.errstate(divide="ignore", invalid="ignore"):
                through = (1 - fresnel) * g_o * woh * dist / aco * eta_i ** 2 * cos_t / (eta_o * woh - eta_i * cos_t) ** 2
            pdf[g] = np.where(reflect, np.where(metal, 1.0, fresnel) * g_o * dist / (4 * aco),
                              np.where(np.isfinite(through), through, 0.0))
        t = np.nonzero(k == GLASS)[0]
        if t.size:
            ior = self._ior(m[t], None if channel is None else channel[t])
            front = 1.0 if outside is None else outside[t]
            eta = np.where(co[t] >= 0, front / ior, ior / front)   # n(side of wo) / n(other side)
            cos_o = np.abs(co[t])
            sin2 = eta ** 2 * (1 - cos_o ** 2)
            cos_t = np.sqrt(np.clip(1 - sin2, 0.0, None))
            fresnel = _fresnel(cos_o, eta)
            reflect = u3[t] < fresnel
            nn = n[t] * side[t][:, None]
            refl = 2 * cos_o[:, None] * nn - wo[t]
            refr = -eta[:, None] * wo[t] + (eta * cos_o - cos_t)[:, None] * nn
            wi[t] = np.where(reflect[:, None], refl, refr)
            weight[t] = np.where(reflect | (not radiance), 1.0, eta ** 2)
        for table, r in self._tabulated(m):
            c = np.zeros(len(r), dtype=np.int64) if channel is None else channel[r]
            wi[r], weight[r], pdf[r], _ = table.sample(n[r], wo[r], c, rng, radiance)
        if straight is not None and straight.any():
            wi[straight], weight[straight], pdf[straight] = -wo[straight], 1.0, 0.0
        return wi, weight, pdf


def _fresnel(cos: np.ndarray, eta: np.ndarray) -> np.ndarray:
    """Reflectance of a smooth dielectric interface for unpolarised light arriving with the cosine
    `cos` to the normal; eta = index on the arriving side / index beyond. 1 for total reflection."""
    sin2 = eta ** 2 * (1 - cos ** 2)
    cos_t = np.sqrt(np.clip(1 - sin2, 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = (eta * cos - cos_t) / (eta * cos + cos_t)
        rp = (cos - eta * cos_t) / (cos + eta * cos_t)
    return np.where(sin2 >= 1, 1.0, 0.5 * (rs ** 2 + rp ** 2))


def _ggx(alpha: np.ndarray, cos_h: np.ndarray) -> np.ndarray:
    """GGX distribution of the microfacet normals: density (per steradian) of normals with the
    cosine cos_h to the surface normal."""
    return alpha ** 2 / (np.pi * (cos_h ** 2 * (alpha ** 2 - 1) + 1) ** 2)


def _g1(alpha: np.ndarray, cos: np.ndarray) -> np.ndarray:
    """Share of the microfacets not hidden from a direction with the cosine `cos` (Smith)."""
    c = np.abs(cos)
    return 2 * c / (c + np.sqrt(alpha ** 2 + (1 - alpha ** 2) * c * c))


def _visible_normal(alpha: np.ndarray, n: np.ndarray, wo: np.ndarray, u1: np.ndarray, u2: np.ndarray) -> np.ndarray:
    """A microfacet normal as wo sees them (Heitz 2018, sampling the visible normals of GGX);
    n: the surface normal on the side of wo. Its density is G1(wo) max(wo.h, 0) D(h) / |n.wo|."""
    a, b = _frame(n)
    x, y, z = np.einsum("ij,ij->i", wo, a), np.einsum("ij,ij->i", wo, b), np.einsum("ij,ij->i", wo, n)
    v = np.stack([alpha * x, alpha * y, z], axis=1)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    lensq = v[:, 0] ** 2 + v[:, 1] ** 2
    inv = 1.0 / np.sqrt(np.where(lensq > 0, lensq, 1.0))
    t1 = np.where((lensq > 0)[:, None], np.stack([-v[:, 1] * inv, v[:, 0] * inv, np.zeros(len(z))], axis=1), [1.0, 0.0, 0.0])
    t2 = np.cross(v, t1)
    r, phi = np.sqrt(u1), 2 * np.pi * u2
    p1, p2 = r * np.cos(phi), r * np.sin(phi)
    s = 0.5 * (1 + v[:, 2])
    p2 = (1 - s) * np.sqrt(np.clip(1 - p1 * p1, 0.0, None)) + s * p2
    nh = p1[:, None] * t1 + p2[:, None] * t2 + np.sqrt(np.clip(1 - p1 * p1 - p2 * p2, 0.0, None))[:, None] * v
    h = np.stack([alpha * nh[:, 0], alpha * nh[:, 1], np.maximum(nh[:, 2], 0.0)], axis=1)
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    return h[:, 0:1] * a + h[:, 1:2] * b + h[:, 2:3] * n


def _frame(axis: np.ndarray):
    """Two unit vectors perpendicular to each axis (unit) and to each other."""
    helper = np.where((np.abs(axis[:, 0]) < 0.9)[:, None], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    a = np.cross(axis, helper)
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    return a, np.cross(axis, a)


def _around(axis: np.ndarray, cos: np.ndarray, phi: np.ndarray) -> np.ndarray:
    a, b = _frame(axis)
    sin = np.sqrt(np.clip(1 - cos ** 2, 0.0, None))
    return (sin * np.cos(phi))[:, None] * a + (sin * np.sin(phi))[:, None] * b + cos[:, None] * axis


def _cosine(axis: np.ndarray, u1: np.ndarray, u2: np.ndarray):
    """Directions with density cos / pi around each axis, and their cosines."""
    cos = np.sqrt(1 - u1)
    return _around(axis, cos, 2 * np.pi * u2), cos


def cone(axis: np.ndarray, sin_max: np.ndarray, u1: np.ndarray, u2: np.ndarray):
    """Directions with density cos / (pi sin_max²) within the cone of half-angle asin(sin_max)
    around each axis, and their cosines."""
    cos = np.sqrt(1 - sin_max ** 2 * u1)
    return _around(axis, cos, 2 * np.pi * u2), cos
