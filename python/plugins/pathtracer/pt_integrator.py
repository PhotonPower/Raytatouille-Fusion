"""Light transport: light tracing, path tracing and bidirectional path tracing as one estimator.

A light path x0 … x(n-1) runs from a source (x0) to the sensor (x(n-1)). It can be sampled in
n + 1 ways: s vertices from the source ("light subpath") and t = n - s from the sensor ("eye
subpath"), joined by a connection (a visibility test) – or, for s = 0 / t = 0, an eye subpath
that happens to hit a source / a light subpath that happens to hit a sensor face. The methods
differ only in the set of (s, t) they use:

  light   light tracing: t = 0 for irradiance on faces (particles deposit their flux where they
          land – or pass, on detector faces), t = 1 for a camera (every vertex of a light path is
          connected to the camera)
  path    path tracing from the sensor: s = 0 (the path hits a source) and s = 1 (connection to a
          point of a source, "next event estimation")
  bidir   bidirectional path tracing: all of them
  photon  photon mapping (pt_photon) for camera images; for irradiance on faces the same as light

When several ways can produce the same path, their results are combined with weights (multiple
importance sampling, balance heuristic) that add up to one – so every method estimates the
same quantity, and they agree within noise wherever a method can sample all paths. (Path
tracing cannot find light that reaches a point source through mirrors or glass.)

Sampled quantities: for a TexelSensor the flux per texel (W), for a Camera the mean radiance per
pixel (W/(mm² sr)). NumPy only."""

from __future__ import annotations

import numpy as np

METHODS = ("light", "path", "bidir", "photon")


def enabled(method: str, camera: bool, s: int, t: int) -> bool:
    """Whether the method uses the way with s light and t eye vertices."""
    if s + t < 2 or (camera and t == 0):
        return False
    if method == "light":
        return t == (1 if camera else 0)
    if method == "path":
        return s <= 1 and t >= (2 if camera else 1)
    return True


class Path:
    """Vertices of n subpaths, arrays [vertex, path]. Vertex 0 is the point on the source / the
    sensor. beta: weight of the subpath on arrival; pf: density (per area) with which the subpath
    made the vertex; pr: density with which the opposite direction would make it (known once the
    next vertex has scattered); wo: unit direction to the previous vertex."""

    def __init__(self, k: int, n: int):
        self.p = np.zeros((k, n, 3))
        self.ns = np.zeros((k, n, 3))
        self.ng = np.zeros((k, n, 3))
        self.wo = np.zeros((k, n, 3))
        self.m = np.zeros((k, n), dtype=np.int64)
        self.tex = np.full((k, n), -1, dtype=np.int64)
        self.src = np.full((k, n), -1, dtype=np.int64)
        self.beta = np.zeros((k, n))
        self.pf = np.zeros((k, n))
        self.pr = np.zeros((k, n))
        self.spec = np.zeros((k, n), dtype=bool)
        self.outside = np.ones((k, n))                       # index in front of the vertex's surface (1: air)
        self.valid = np.zeros((k, n), dtype=bool)
        self.point = np.zeros(n, dtype=bool)                 # vertex 0 is a point (no surface)
        self.channel = np.zeros(n, dtype=np.int64)           # number of the path's wavelength
        self.escape = np.full(n, -1, dtype=np.int64)         # vertex whose ray left the scene
        self.escape_dir = np.zeros((n, 3))
        self.escape_beta = np.zeros(n)                       # weight of the subpath as it left
        self.entity = np.full((k, n), -1, dtype=np.int64)   # entity of the vertex's surface (-1: vertex 0)
        self.rays = 0
        #: where rays crossed detector faces: {k: [crossings]} for the rays towards vertex k – each
        #: the vertex-k data (paths j, p, ns, wo, pf, tex, beta) of a subpath that ends there
        self.cross: dict[int, list[dict]] = {}

    def cos(self, k: int, j: np.ndarray, w: np.ndarray) -> np.ndarray:
        """|cos| between the normal of vertex k and w; 1 for points."""
        c = np.abs(np.einsum("ij,ij->i", self.ns[k, j], w))
        return np.where(self.point[j], 1.0, c) if k == 0 else c


def _dot(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.einsum("ij,ij->i", a, b)


def _walk(scene, sensor, path: Path, start: dict, beta0: np.ndarray, rng, radiance: bool,
          stop_rough: bool = False) -> None:
    """Follows the rays leaving vertex 0 through the scene: vertices 1 … of the subpaths.
    stop_rough: a subpath ends at its first vertex that is not specular."""
    k_max, n = path.valid.shape
    mesh, mats = scene.mesh, scene.materials
    alive = start["ok"].copy()
    d = start["d"].copy()
    beta = beta0.copy()
    pdf = start["pdf_dir"].copy()
    media = np.full((n, MEDIA), -1, dtype=np.int64)          # the glass bodies a path is inside, as entered
    held = np.zeros(n, dtype=np.int64)
    ghost = np.full(n, -1, dtype=np.int64)                   # a body just left through a touching one: its
    #                                                          own surface, a hair ahead, is none any more
    for k in range(1, k_max):
        idx = np.nonzero(alive)[0]
        if not idx.size:
            break
        dk = d[idx]
        o = scene.offset(path.p[k - 1, idx], path.ng[k - 1, idx], dk)
        t, tri, b1, b2 = scene.hit(o, dk)
        path.rays += len(idx)
        if not radiance and sensor is not None and not sensor.camera and sensor.crossed:
            path.cross[k] = _crossings(scene, sensor, path, k, idx, o, dk, t, pdf[idx], beta[idx])
        got = tri >= 0
        lost = idx[~got]
        alive[lost] = False
        path.escape[lost] = k - 1
        path.escape_dir[lost] = dk[~got]
        path.escape_beta[lost] = beta[lost]
        idx, dk, o, t, tri, b1, b2 = idx[got], dk[got], o[got], t[got], tri[got], b1[got], b2[got]
        if not idx.size:
            break
        ns, uv = mesh.shade_exact(tri, b1, b2, o, dk, t) if scene.exact else mesh.shade(tri, b1, b2)
        ng = mesh.ng[tri]
        cs = -_dot(ns, dk)
        good = cs * -_dot(ng, dk) > 0                        # same side for both normals
        alive[idx[~good]] = False
        idx, dk, o, t, tri, ns, ng, uv, cs = (a[good] for a in (idx, dk, o, t, tri, ns, ng, uv, cs))
        if not idx.size:
            break
        p = o + t[:, None] * dk
        dist2 = np.sum((p - path.p[k - 1, idx]) ** 2, axis=1)
        m = scene.tri_material[tri]
        b = beta[idx]
        glassy = scene.tri_glassy[tri]
        top = np.where(held[idx] > 0, media[idx, np.maximum(held[idx] - 1, 0)], -1)
        # the segment ran through the body entered last (a path that began inside one: the body it leaves)
        medium = np.where(top >= 0, scene.entity_material[np.maximum(top, 0)], m)
        absorb = np.where((top >= 0) | (glassy & (cs < 0)), mats.absorbs(medium, path.channel[idx]), 0.0)
        if (absorb > 0).any():
            b = b * np.exp(-absorb * np.sqrt(dist2))
        outside = np.ones(len(idx))
        straight = np.zeros(len(idx), dtype=bool)
        contact = np.full(len(idx), -1, dtype=np.int64)
        ending = np.full(len(idx), -1, dtype=np.int64)
        body = scene.tri_entity[tri]
        passed, ghost[idx] = ghost[idx], -1
        if glassy.any():                                     # which medium lies in front of this surface?
            g = np.nonzero(glassy)[0]
            rows, own = idx[g], body[g]
            stack, count = media[rows], held[rows]
            inside_own = (stack == own[:, None]).any(axis=1)
            on_top = top[g] == own
            enters = cs[g] > 0
            below = np.where(count >= 2, stack[np.arange(len(g)), np.maximum(count - 2, 0)], -1)
            # entering a body the path is in already (it touched the one before), or leaving one
            # that is not the innermost (two bodies overlap a little): no surface for the light
            straight[g] = np.where(enters, inside_own, (inside_own & ~on_top) | (passed[g] == own))
            beyond = np.where(enters, top[g], np.where(on_top, below, top[g]))
            ask = ~enters & ~straight[g] & (beyond < 0)       # out into air – or into a body that touches?
            if ask.any():
                beyond[ask] = scene.touching(p[g[ask]], dk[g[ask]], own[ask])
                contact[g[ask]] = beyond[ask]
            ask = enters & ~straight[g] & (top[g] >= 0)       # into a body from inside another: does that end here?
            if ask.any():
                ending[g[ask]] = scene.touching(p[g[ask]], dk[g[ask]], top[g][ask], ends=True)
            index = mats._ior(scene.entity_material[np.maximum(beyond, 0)], path.channel[rows])
            outside[g] = np.where(beyond >= 0, index, 1.0)
            gone = g[~enters & straight[g]]                  # left a body that was not the innermost
            _leave(media, held, idx[gone], body[gone])
        path.p[k, idx], path.ns[k, idx], path.ng[k, idx], path.wo[k, idx] = p, ns, ng, -dk
        path.outside[k, idx] = outside
        path.m[k, idx] = m
        if sensor is not None and not sensor.camera:
            path.tex[k, idx] = sensor.texel(tri, uv)
        path.src[k, idx] = scene.face_source[mesh.face[tri]]
        path.entity[k, idx] = body
        path.beta[k, idx] = b
        path.pf[k, idx] = pdf[idx] * np.abs(cs) / dist2
        spec = mats.specular(m) | straight
        path.spec[k, idx] = spec
        path.valid[k, idx] = True
        if k == k_max - 1:
            break
        wi, weight, pd = mats.sample(m, ns, -dk, rng, radiance, path.channel[idx], outside, straight)
        _, _, p_rev = mats.eval(m, ns, -dk, wi, path.channel[idx], outside=outside)
        path.pr[k - 1, idx] = p_rev * path.cos(k - 1, idx, dk) / dist2
        ok = (weight > 0) & (_dot(ns, wi) * _dot(ng, wi) > 0)
        through = glassy & ~straight & (_dot(ns, wi) * cs < 0)           # the path went through the surface
        if through.any():
            out_ = through & (cs < 0)
            _leave(media, held, idx[out_], body[out_])
            swap = through & (cs > 0) & (ending >= 0)        # the body it was in ended at this surface
            _leave(media, held, idx[swap], ending[swap])
            ghost[idx[swap]] = ending[swap]
            into = np.where(through & (cs > 0), body, np.where(out_, contact, -1))
            rows = idx[into >= 0]
            media[rows, np.minimum(held[rows], MEDIA - 1)] = into[into >= 0]
            held[rows] = np.minimum(held[rows] + 1, MEDIA)
        if stop_rough:
            ok &= spec
        if k >= 3:                                           # Russian roulette on dim paths
            q = np.where(spec, 1.0, np.clip(weight, 0.1, 1.0))
            ok &= rng.random(len(idx)) < q
            weight = weight / q
        beta[idx] = b * weight
        d[idx] = wi
        pdf[idx] = pd
        alive[idx] = ok


MEDIA = 4            # glass bodies a path can be inside of at once


def _leave(media: np.ndarray, held: np.ndarray, rows: np.ndarray, body: np.ndarray) -> None:
    """Takes `body` off the list of bodies the paths `rows` are inside (if it is on it)."""
    if not len(rows):
        return
    stack = media[rows]
    hit = stack == body[:, None]
    found = hit.any(axis=1)
    at = hit.argmax(axis=1)
    for c in range(MEDIA - 1):
        stack[:, c] = np.where(found & (c >= at), stack[:, c + 1], stack[:, c])
    stack[found, MEDIA - 1] = -1
    media[rows] = stack
    held[rows] -= found


def _crossings(scene, sensor, path: Path, k: int, idx, o, d, tmax, pdf, beta) -> list[dict]:
    """Where the rays towards vertex k cross detector faces of the sensor before they arrive (or
    leave the scene): one entry per crossing along the rays (first, second, …)."""
    mesh = scene.mesh
    out = []
    act = np.arange(len(idx))
    done = np.zeros(len(idx))                                # distance already searched
    for _ in range(64):
        t, tri, b1, b2 = scene.crossing(o[act] + d[act] * done[act][:, None], d[act], tmax[act] - done[act])
        path.rays += len(act)
        got = tri >= 0
        if not got.any():
            break
        act, t, tri, b1, b2 = act[got], t[got] + done[act[got]], tri[got], b1[got], b2[got]
        done[act] = t + scene.eps
        ns, uv = mesh.shade(tri, b1, b2)
        cs = _dot(ns, d[act])
        tex = sensor.texel(tri, uv)
        ok = (tex >= 0) & (cs * _dot(mesh.ng[tri], d[act]) > 0)
        a = act[ok]
        if not a.size:
            continue
        j = idx[a]
        p = o[a] + t[ok][:, None] * d[a]
        dist2 = np.sum((p - path.p[k - 1, j]) ** 2, axis=1)
        out.append({"j": j, "p": p, "ns": ns[ok], "wo": -d[a], "tex": tex[ok], "beta": beta[a],
                    "pf": pdf[a] * np.abs(cs[ok]) / dist2})
    return out


def _detector_deposits(scene, sensor, light: Path, eye: Path | None, method: str, depth: int,
                       accum: np.ndarray) -> None:
    """The light subpaths that crossed detector faces: each crossing is the end of a path made
    with t = 0, like a hit of a sensor face – only that the subpath goes on behind it."""
    rows = ("p", "ns", "wo", "pf", "tex", "valid", "beta")
    for k, crossings in light.cross.items():
        s = k + 1
        if s > depth + 1 or not enabled(method, False, s, 0):
            continue
        saved = {name: getattr(light, name)[k].copy() for name in rows}
        for c in crossings:
            j = c["j"]
            light.valid[k] = False
            light.valid[k, j] = True
            for name in ("p", "ns", "wo", "pf", "tex", "beta"):
                getattr(light, name)[k, j] = c[name]
            _strategy(scene, sensor, light, eye, s, 0, method, accum)
        for name in rows:
            getattr(light, name)[k] = saved[name]


def light_subpaths(scene, sensor, n: int, k: int, rng) -> Path:
    """n subpaths from the sources with up to k vertices."""
    path = Path(max(k, 1), n)
    e = scene.emit(n, rng)
    path.p[0], path.ns[0], path.ng[0], path.src[0] = e["p"], e["ns"], e["ng"], e["src"]
    path.point = e["point"]
    path.channel = e["channel"]
    path.beta[0] = 1.0 / e["pdf_pos"]
    path.pf[0] = e["pdf_pos"] * scene.spectral_weight(e["src"], e["channel"])     # point and wavelength
    path.valid[0] = True
    _walk(scene, sensor, path, e, np.full(n, scene.flux), rng, radiance=False)
    return path


def eye_subpaths(scene, sensor, n: int, k: int, rng, stop_rough: bool = False, channel=None) -> Path:
    """n subpaths from the sensor with up to k vertices (stop_rough: only as far as the first
    vertex that is not specular). channel: the wavelengths they carry – those of the light
    subpaths they are paired with."""
    path = Path(max(k, 1), n)
    if channel is not None:
        path.channel = channel
    e = sensor.sample(n, rng)
    path.p[0], path.ns[0], path.ng[0], path.tex[0] = e["p"], e["ns"], e["ng"], e["texel"]
    path.point = e["point"]
    path.beta[0] = 1.0 / e["pdf_pos"]
    path.pf[0] = e["pdf_pos"]
    path.valid[0] = e["exists"]
    _walk(scene, sensor, path, e, e["beta"], rng, radiance=True, stop_rough=stop_rough)
    return path


def _strategy(scene, sensor, light: Path, eye: Path | None, s: int, t: int, method: str, accum: np.ndarray) -> int:
    """Adds what the way (s, t) contributes for every pair of subpaths; returns the number of
    visibility rays."""
    n = s + t
    mats = scene.materials
    camera = sensor.camera
    valid = np.ones(light.valid.shape[1], dtype=bool)
    if s:
        valid &= light.valid[s - 1]
    if t:
        valid &= eye.valid[t - 1]
    if s == 0:
        valid &= eye.src[t - 1] >= 0
    if t == 0:
        valid &= light.tex[s - 1] >= 0
    j = np.nonzero(valid)[0]
    if not j.size:
        return 0
    rays = 0
    con: dict = {}
    if s == 0:                                               # the eye subpath hit a source
        le, _ = scene.emitted(eye.src[t - 1, j], eye.ns[t - 1, j], eye.wo[t - 1, j])
        c = eye.beta[t - 1, j] * le * scene.spectral_weight(eye.src[t - 1, j], light.channel[j])
        tex = eye.tex[0, j]
    elif t == 0:                                             # the light subpath hit a sensor face
        c = light.beta[s - 1, j].copy()
        tex = light.tex[s - 1, j]
    else:                                                    # connection y -> z
        y, z = light.p[s - 1, j], eye.p[t - 1, j]
        w = z - y
        dist2 = np.sum(w * w, axis=1)
        near = dist2 > 1e-24
        w = w / np.sqrt(np.where(near, dist2, 1.0))[:, None]
        if s == 1:
            fy, dens_y = scene.emitted(light.src[0, j], light.ns[0, j], w)
            dens_y_rev = None
        else:
            fy, dens_y, dens_y_rev = mats.eval(light.m[s - 1, j], light.ns[s - 1, j], light.wo[s - 1, j], w,
                                               light.channel[j], radiance=False, outside=light.outside[s - 1, j])
        if t == 1:
            fz, dens_z, pixel = sensor.response(eye.ns[0, j], -w, eye.p[0, j])
            tex = eye.tex[0, j] if pixel is None else pixel
            dens_z_rev = None
        else:
            fz, dens_z, dens_z_rev = mats.eval(eye.m[t - 1, j], eye.ns[t - 1, j], eye.wo[t - 1, j], -w,
                                               light.channel[j], outside=eye.outside[t - 1, j])
            tex = eye.tex[0, j]
        cy, cz = light.cos(s - 1, j, w), eye.cos(t - 1, j, w)
        c = light.beta[s - 1, j] * fy * cy * cz / np.where(near, dist2, 1.0) * fz * eye.beta[t - 1, j]
        # both normals of a surface vertex must see the connection on the same side
        side_y = _dot(light.ns[s - 1, j], w) * _dot(light.ng[s - 1, j], w) > 0
        side_z = _dot(eye.ns[t - 1, j], w) * _dot(eye.ng[t - 1, j], w) > 0
        if s == 1:
            side_y |= light.point[j]
        if t == 1:
            side_z |= eye.point[j]
        c = np.where(near & side_y & side_z & (tex >= 0), c, 0.0)
        if camera and n == 2 and sensor.pinhole:             # a point source has no image in a pinhole camera
            c = np.where(light.point[j], 0.0, c)
        k = np.nonzero(c > 0)[0]
        if k.size:
            o = scene.offset(y[k], light.ng[s - 1, j[k]], w[k])
            target = scene.offset(z[k], eye.ng[t - 1, j[k]], -w[k])
            c[k[scene.occluded(o, target)]] = 0.0
            rays = len(k)
        con = {"w": w, "dist2": dist2, "dens_y": dens_y, "dens_z": dens_z, "dens_y_rev": dens_y_rev,
               "dens_z_rev": dens_z_rev, "cy": cy, "cz": cz}
    keep = np.nonzero((c > 0) & (tex >= 0) & np.isfinite(c))[0]
    if not keep.size:
        return rays
    j, c, tex = j[keep], c[keep], tex[keep]
    con = {key: (v[keep] if v is not None else None) for key, v in con.items()}

    ways = [sp for sp in range(n + 1) if enabled(method, camera, sp, n - sp)]
    if ways != [s]:
        c = c * _weight(scene, sensor, light, eye, s, t, j, con, ways)
    accum += np.bincount(light.channel[j] * sensor.count + tex, weights=c, minlength=len(accum))
    return rays


def _weight(scene, sensor, light: Path, eye: Path | None, s: int, t: int, j: np.ndarray, con: dict,
            ways: list[int]) -> np.ndarray:
    """Balance-heuristic weight of the way (s, t) among `ways` (numbers of light vertices) for
    the full paths j: 1 / sum over the ways of (their density / this way's density)."""
    n = s + t
    count = len(j)
    pf: list = [None] * n                                    # density of x_i when made from the source side
    pr: list = [None] * n                                    # … from the sensor side
    for i in range(n):
        if i < s:
            pf[i] = light.pf[i, j]
        else:
            pr[i] = eye.pf[n - 1 - i, j]
    for i in range(0, s - 2):
        pr[i] = light.pr[i, j]
    for i in range(s + 2, n):
        pf[i] = eye.pr[n - 1 - i, j]

    def gap2(path: Path, k: int) -> np.ndarray:
        return np.sum((path.p[k, j] - path.p[k - 1, j]) ** 2, axis=1)

    if s >= 1 and t >= 1:
        pf[s] = con["dens_y"] * con["cz"] / con["dist2"]
        pr[s - 1] = con["dens_z"] * con["cy"] / con["dist2"]
        if s >= 2:
            pr[s - 2] = con["dens_y_rev"] * light.cos(s - 2, j, light.wo[s - 1, j]) / gap2(light, s - 1)
        if t >= 2:
            pf[s + 1] = con["dens_z_rev"] * eye.cos(t - 2, j, eye.wo[t - 1, j]) / gap2(eye, t - 1)
    elif s == 0:
        src = eye.src[t - 1, j]
        pf[0] = scene.emit_pdf_pos(src) * scene.spectral_weight(src, light.channel[j])
        _, dens = scene.emitted(src, eye.ns[t - 1, j], eye.wo[t - 1, j])
        pf[1] = dens * eye.cos(t - 2, j, eye.wo[t - 1, j]) / gap2(eye, t - 1)
    else:
        pr[n - 1] = sensor.pdf_pos_at(light.tex[s - 1, j])
        _, dens, _ = sensor.response(light.ns[s - 1, j], light.wo[s - 1, j])
        pr[n - 2] = dens * light.cos(s - 2, j, light.wo[s - 1, j]) / gap2(light, s - 1)

    # specular vertices: their directions are certain – the densities cancel, and no connection
    # can end on them
    spec = [np.zeros(count, dtype=bool)] * n
    for i in range(1, n - 1):
        spec[i] = light.spec[i, j] if i < s else eye.spec[n - 1 - i, j]
        if i + 1 < n:
            pf[i + 1] = np.where(spec[i], 1.0, pf[i + 1])
        pr[i - 1] = np.where(spec[i], 1.0, pr[i - 1])
    light_point = light.point[j] if s >= 1 else np.zeros(count, dtype=bool)

    def possible(sp: int):
        if sp == 0:
            return ~light_point
        if sp == n:
            return np.ones(count, dtype=bool)
        ok = ~spec[sp - 1] & ~spec[sp]
        if sensor.camera and n == 2 and sensor.pinhole:
            ok = ok & ~light_point
        return ok

    total = np.ones(count)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        r = np.ones(count)
        for sp in range(s + 1, n + 1):
            r = np.nan_to_num(r * pf[sp - 1] / pr[sp - 1], nan=0.0, posinf=1e300)
            if sp in ways:
                total += np.where(possible(sp), r, 0.0)
        r = np.ones(count)
        for sp in range(s - 1, -1, -1):
            r = np.nan_to_num(r * pr[sp] / pf[sp], nan=0.0, posinf=1e300)
            if sp in ways:
                total += np.where(possible(sp), r, 0.0)
    return 1.0 / total


def lengths(method: str, camera: bool, depth: int) -> tuple[int, int]:
    """Most vertices of the light and the eye subpaths for paths of up to `depth` segments."""
    if method == "light":
        return (depth if camera else depth + 1), (1 if camera else 0)
    if method == "path":
        return 1, depth + 1
    return (depth if camera else depth + 1), depth + 1


class Spread:
    """How far the estimate can be trusted: its standard error, from the spread of the batches
    it is the mean of."""

    def __init__(self, count: int, channels: int):
        self.count, self.channels = count, channels
        self.before = np.zeros(count)
        self.squares = np.zeros(count)
        self.batches = 0

    def add(self, accum: np.ndarray, n: int) -> None:
        """After a batch of n samples was added to the running sums `accum`."""
        total = accum.reshape(self.channels, self.count).sum(axis=0)
        self.squares += (total - self.before) ** 2 / n
        self.before = total
        self.batches += 1

    def error(self, done: int):
        """Standard error of the values (None with fewer than two batches)."""
        if self.batches < 2 or done < 1:
            return None
        mean = self.before / done
        return np.sqrt(np.clip((self.squares / done - mean ** 2) / (self.batches - 1), 0.0, None))


def batch_size(k_light: int, k_eye: int) -> int:
    """Subpaths per batch: large batches trace faster per ray, but every vertex of every subpath
    is kept (about 170 bytes) – this aims at some 100 MB."""
    return int(np.clip(100e6 / (170 * (k_light + k_eye + 1)), 10_000, 100_000))


def adapts(method: str, camera: bool) -> bool:
    """Whether the method draws samples from the sensor, so that they can be steered."""
    return method in ("path", "bidir") or (method == "photon" and camera)


def render(scene, sensor, method: str, samples: int, depth: int, *, seed: int = 0, batch: int | None = None,
           progress=None, cancelled=None, radius: float = 0.0, adaptive: bool = False, weights=None) -> dict:
    """Estimates the sensor's values with `samples` pairs of subpaths; paths have up to `depth`
    segments (source – … – sensor). Returns {"values": per texel the flux / W or per pixel the
    radiance / W/(mm² sr), "channels": the same per wavelength of scene.wavelengths (their sum is
    "values"), "error": the standard error of the values (from the spread of the batches; None
    with a single batch), "samples": done, "rays": traced}. progress(fraction) and cancelled()
    are called between batches; a cancelled run returns what it has.

    adaptive: after every batch the sensor moves its samples to the texels / pixels that are
    still uncertain (sensor.adapt; path tracing, bidirectional and photon mapping). weights: the
    shares of the texels / pixels to start with (default: by area / even). Every batch is drawn
    with shares fixed before it, so the mean of the batches stays right."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}")
    if depth < 1:
        raise ValueError("paths need at least one segment")
    sensor.reset()
    if weights is not None:
        sensor.set_weights(weights)
    if method == "photon":
        if sensor.camera:
            import pt_photon

            return pt_photon.render(scene, sensor, samples, depth, seed=seed, radius=radius, progress=progress,
                                    cancelled=cancelled, adaptive=adaptive)
        method = "light"            # on faces the texels already collect the photons
    rng = np.random.default_rng(seed)
    k_light, k_eye = lengths(method, sensor.camera, depth)
    if batch is None:                   # eight batches where the samples allow, for the error – but no
        batch = min(batch_size(k_light, k_eye), max(samples // 8, 20_000))       # small ones: they are slow
    accum = np.zeros(len(scene.wavelengths) * sensor.count)
    spread = Spread(sensor.count, len(scene.wavelengths))
    done = rays = 0
    while done < samples:
        n = min(batch, samples - done)
        light = light_subpaths(scene, sensor, n, k_light, rng)
        eye = eye_subpaths(scene, sensor, n, k_eye, rng, channel=light.channel) if k_eye else None
        rays += light.rays + (eye.rays if eye is not None else 0)
        for s in range(0, k_light + 1):
            for t in range(0, k_eye + 1):
                if 2 <= s + t <= depth + 1 and enabled(method, sensor.camera, s, t):
                    rays += _strategy(scene, sensor, light, eye, s, t, method, accum)
        if light.cross:
            _detector_deposits(scene, sensor, light, eye, method, depth, accum)
        done += n
        spread.add(accum, n)
        if adaptive and adapts(method, sensor.camera) and spread.batches >= 2 and done < samples:
            sensor.adapt(spread.error(done))
        if progress is not None:
            progress(done / samples)
        if cancelled is not None and cancelled():
            break
    channels = accum.reshape(len(scene.wavelengths), sensor.count) / max(done, 1)
    return {"values": channels.sum(axis=0), "channels": channels, "error": spread.error(done), "samples": done,
            "rays": rays}


def light_paths(scene, n: int, depth: int, seed: int = 0):
    """n light paths as polylines for drawing: (points (m, 3), starts (n + 1,)). A path that
    leaves the scene ends a tenth of the scene size further on."""
    path = light_subpaths(scene, None, n, depth + 1, np.random.default_rng(seed))
    points, starts = [], [0]
    for i in range(n):
        k = int(path.valid[:, i].sum())
        pts = [path.p[v, i] for v in range(k)]
        if path.escape[i] == k - 1:
            pts.append(pts[-1] + path.escape_dir[i] * 0.1 * scene.size)
        if len(pts) >= 2:
            points.extend(pts)
            starts.append(len(points))
    return np.asarray(points, dtype=float).reshape(-1, 3), np.asarray(starts, dtype=np.int64)


def escapes(scene, n: int, depth: int, seed: int = 0, index: int = 0, skip=()) -> dict:
    """The light that leaves the scene, from n light subpaths of up to `depth` segments (batch
    `index` of the seed): for every subpath that leaves, its direction d (m, 3), its flux (its
    weight over n: the fluxes of one call add up to the escaping flux), its wavelength's channel,
    its number of surface events before it left (bounces; 0: straight from the source) and the
    entities of its first surface not in `skip` and of its last surface (-1: none)."""
    if depth < 1:
        raise ValueError("paths need at least one segment")
    if n < 1:
        raise ValueError("at least one subpath is needed")
    skip = np.asarray(list(skip), dtype=np.int64)
    if (skip < 0).any():
        raise ValueError("skip: entities are numbers from 0 on")
    path = light_subpaths(scene, None, n, depth + 1, np.random.default_rng([seed, index]))
    j = np.nonzero(path.escape >= 0)[0]
    k = path.escape[j]
    vertices = path.entity[1:, j]                                   # (surface events, paths)
    rank = np.arange(1, vertices.shape[0] + 1)[:, None]
    counted = (vertices >= 0) & ~np.isin(vertices, skip) & (rank <= k[None, :])
    at = np.argmax(counted, axis=0)
    first = np.where(counted.any(axis=0), vertices[at, np.arange(len(j))], -1) if len(j) else np.zeros(0, int)
    return {"d": path.escape_dir[j], "flux": path.escape_beta[j] / n, "channel": path.channel[j], "bounces": k,
            "first": first, "last": np.where(k >= 1, path.entity[k, j], -1), "rays": path.rays}
