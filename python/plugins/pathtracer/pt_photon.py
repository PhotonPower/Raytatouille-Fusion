"""Photon mapping for camera images (progressive, after Knaus and Zwicker 2011).

Light paths leave "photons" – their flux – on every surface that is not specular. Camera paths
are followed through mirrors and glass to the first surface that is not specular; the light it
sends on to the camera is estimated from the photons within a small radius around that point.
This is the one method here that finds light which reaches a surface through glass or off a
mirror *and* is seen through glass or in a mirror (a caustic at the bottom of a glass, the
spot of a lamp seen in a mirror) – no connection can make such a path. The price is a blur over
the radius: the estimate is biased. The radius shrinks from pass to pass so that the bias and the
noise both vanish with the number of passes.

Sources seen directly or through mirrors and glass are added from the camera paths themselves.
NumPy only."""

from __future__ import annotations

import numpy as np

import pt_integrator

ALPHA = 0.7          # radius reduction: r²(i+1) = r²(i) · (i + ALPHA) / (i + 1)
PHOTONS = 30         # photons expected within the first radius when it is chosen automatically
PAIRS = 2_000_000    # photon – point pairs looked at together


def pass_size(samples: int, depth: int) -> int:
    """Paths per pass: some 16 passes if the samples allow, within what a batch may hold."""
    limit = pt_integrator.batch_size(depth, depth + 1)
    return int(np.clip(samples // 16, min(5_000, limit), limit))


def first_radius2(scene, photons: np.ndarray, points: np.ndarray) -> float:
    """Squared radius in which about PHOTONS photons lie around the points the camera sees. A
    first guess spreads the photons evenly over the surfaces that can hold any; it is then
    corrected with the numbers found around some of the points."""
    rough = ~scene.face_virtual & ~scene.materials.specular(scene.face_material)
    area = float(scene.mesh.face_area[rough].sum())
    r2 = PHOTONS * max(area, 1e-300) / (np.pi * max(len(photons), 1))
    some = points[:: max(1, len(points) // 1000)]
    for _ in range(6):
        found = sum(len(q) for q, _ in PhotonGrid(photons, float(np.sqrt(r2))).pairs(some)) / len(some)
        if 0.6 * PHOTONS <= found <= 1.6 * PHOTONS:
            break
        r2 *= float(np.clip(PHOTONS / max(found, 0.25), 1 / 64, 64))      # the number grows with r²
    return r2


class PhotonGrid:
    """Photons in a grid of cells as wide as the search diameter: the photons within the radius
    of a point lie in the (up to) eight cells its search box touches."""

    def __init__(self, points: np.ndarray, radius: float):
        self.radius = radius
        self.cell = 2 * radius
        self.lo = (points.min(axis=0) if len(points) else np.zeros(3)) - 2 * self.cell
        self.order = np.argsort(self._key(self._cells(points)), kind="stable")
        self.keys = self._key(self._cells(points))[self.order]
        self.points = points

    def _cells(self, p: np.ndarray) -> np.ndarray:
        return np.clip(np.floor((p - self.lo) / self.cell), 0, 2 ** 20 - 1).astype(np.int64)

    @staticmethod
    def _key(c: np.ndarray) -> np.ndarray:
        return c[:, 0] + (c[:, 1] << 21) + (c[:, 2] << 42)

    def pairs(self, x: np.ndarray):
        """Yields (query, photon) index arrays of all pairs closer than the radius, in portions."""
        base = self._cells(x - self.radius)
        for off in np.ndindex(2, 2, 2):
            key = self._key(base + np.asarray(off))
            first = np.searchsorted(self.keys, key, side="left")
            count = np.searchsorted(self.keys, key, side="right") - first
            ends = np.cumsum(count)
            a = 0
            while a < len(x):                                # portions of at most PAIRS pairs
                start = ends[a - 1] if a else 0
                b = max(a + 1, int(np.searchsorted(ends, start + PAIRS, side="right")))
                cnt = count[a:b]
                total = int(cnt.sum())
                if total:
                    q = np.repeat(np.arange(a, b), cnt)
                    within = np.arange(total) - np.repeat(np.cumsum(cnt) - cnt, cnt)
                    ph = self.order[first[q] + within]
                    near = np.sum((self.points[ph] - x[q]) ** 2, axis=1) < self.radius ** 2
                    yield q[near], ph[near]
                a = b


def render(scene, camera, samples: int, depth: int, *, seed: int = 0, radius: float = 0.0,
           progress=None, cancelled=None) -> dict:
    """The camera's mean radiance per pixel (W/(mm² sr)) with `samples` camera paths and as many
    light paths, in passes; paths have up to `depth` segments. radius: the first search radius
    in mm (0: chosen from the number of photons and the area of the surfaces). Returns as
    pt_integrator.render, and "radius": the last radius used."""
    if not camera.camera:
        raise ValueError("photon mapping is for camera images")
    rng = np.random.default_rng(seed)
    mats = scene.materials
    n = pass_size(samples, depth)
    channels = len(scene.wavelengths)
    accum = np.zeros(channels * camera.count)
    done = rays = passes = 0
    r2 = radius * radius if radius > 0 else None
    last_r2 = 0.0
    while done < samples:
        count = min(n, samples - done)
        light = pt_integrator.light_subpaths(scene, camera, count, depth, rng)
        eye = pt_integrator.eye_subpaths(scene, camera, count, depth + 1, rng, stop_rough=True,
                                         channel=light.channel)
        rays += light.rays + eye.rays
        pixel = eye.tex[0]
        slot = eye.channel * camera.count + pixel            # wavelength and pixel
        # sources seen directly, in mirrors or through glass (every vertex before the last is specular)
        for k in range(1, eye.valid.shape[0]):
            j = np.nonzero(eye.valid[k] & (eye.src[k] >= 0) & (pixel >= 0))[0]
            if j.size:
                le, _ = scene.emitted(eye.src[k, j], eye.ns[k, j], eye.wo[k, j])
                le = le * scene.spectral_weight(eye.src[k, j], eye.channel[j])
                accum += np.bincount(slot[j], weights=eye.beta[k, j] * le, minlength=len(accum))
        # photons: the vertices of the light paths on surfaces that are not specular
        pk, pj = np.nonzero(light.valid[1:] & ~light.spec[1:])
        pk += 1
        # the points the camera sees: the last vertex of a camera path, if it is not specular
        last = eye.valid.sum(axis=0) - 1
        j = np.nonzero((last >= 1) & (pixel >= 0))[0]
        j = j[~eye.spec[last[j], j]]
        if j.size and pk.size:
            t = last[j]
            x, ns, wo, m = eye.p[t, j], eye.ns[t, j], eye.wo[t, j], eye.m[t, j]
            if r2 is None:
                r2 = first_radius2(scene, light.p[pk, pj], x)
            grid = PhotonGrid(light.p[pk, pj], float(np.sqrt(r2)))
            p_wo, p_ns, p_beta = light.wo[pk, pj], light.ns[pk, pj], light.beta[pk, pj]
            p_channel, channel = light.channel[pj], eye.channel[j]
            total = np.zeros(len(j))
            for q, ph in grid.pairs(x):                      # only photons of the camera path's wavelength
                ok = (pk[ph] + t[q] <= depth) & (np.abs(np.einsum("ij,ij->i", p_ns[ph], ns[q])) > 0.5) \
                    & (p_channel[ph] == channel[q])
                q, ph = q[ok], ph[ok]
                f, _, _ = mats.eval(m[q], ns[q], wo[q], p_wo[ph])
                total += np.bincount(q, weights=f * p_beta[ph], minlength=len(j))
            total /= scene.channel_prob[channel]             # the path stands for all wavelengths
            accum += np.bincount(slot[j], weights=eye.beta[t, j] * total / (np.pi * r2 * count),
                                 minlength=len(accum))
        done += count
        passes += 1
        if r2 is not None:
            last_r2 = r2
            r2 = r2 * (passes + ALPHA) / (passes + 1)
        if progress is not None:
            progress(done / samples)
        if cancelled is not None and cancelled():
            break
    per = accum.reshape(channels, camera.count) / max(done, 1)
    return {"values": per.sum(axis=0), "channels": per, "samples": done, "rays": rays, "passes": passes,
            "radius": float(np.sqrt(last_r2))}
