"""The scene of a computation: mesh, materials, sources – and the sensors (irradiance on faces,
camera). Lengths in mm, power in W: radiance in W/(mm² sr), irradiance in W/mm². NumPy only.

Sources
  surfaces   emit with constant radiance into a cone around the normal (half-angle 90°: a
             Lambertian emitter), from the front, the back or both sides; all surfaces of one
             source share its flux by area
  points     emit evenly into all directions; the points of one source share its flux
  curves     emit like a thin glowing wire (a Lambertian cylinder): the intensity is
             Phi sin(theta) / pi² at the angle theta to the wire; the curves of one source share
             its flux by length
  measured   a surface or a point can emit with a measured distribution (pt_photometry.Distribution,
             from a luminaire file) instead: theta from the surface normal (points: from `axis`),
             phi from the world's X axis projected across it (Y if the axis is along X). A surface
             then sends the same distribution from each of its points
  spectrum   a source emits at single wavelengths (lines), each with a share of its flux. Every
             path carries one wavelength ("channel": its number in Scene.wavelengths); it matters
             where glass disperses, and the sensors keep the channels apart

Sensors
  TexelSensor   irradiance on faces: the flux arriving (from both sides) in every texel; also on
                faces with a detector material, which the light passes
  Camera        a pinhole camera: radiance per pixel"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import pt_bsdf
import pt_bvh
import pt_mesh


def _across(axis: np.ndarray):
    """Two unit vectors across each axis: the first is the world's X axis projected across it (Y
    where the axis is along X) – the direction phi = 0 of a measured distribution."""
    ref = np.where((np.abs(axis[:, 0]) < 0.999)[:, None], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    a = ref - np.einsum("ij,ij->i", ref, axis)[:, None] * axis
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    return a, np.cross(axis, a)


class _Part:
    """The BVH of some of the mesh's triangles; hits name the triangles of the mesh."""

    def __init__(self, mesh: pt_mesh.Mesh, tris: np.ndarray):
        self.tris = tris
        self.bvh = pt_bvh.BVH(mesh.v0[tris], mesh.e1[tris], mesh.e2[tris])

    def intersect(self, o, d, tmax=None, *, any_hit: bool = False, accept=None):
        inner = None if accept is None else (lambda ray, t, b1, b2: accept(ray, self.tris[t], b1, b2))
        t, tri, b1, b2 = self.bvh.intersect(o, d, tmax, any_hit=any_hit, accept=inner)
        return t, np.where(tri >= 0, self.tris[np.maximum(tri, 0)], -1), b1, b2


@dataclass
class SourceSpec:
    name: str
    flux: float                          # W
    half_angle: float = 90.0             # degrees, surfaces only
    side: str = "front"                  # front, back, both
    entities: tuple = ()                 # indices into the entity list of the mesh (surfaces)
    points: tuple = ()                   # (x, y, z) of point sources
    curves: tuple = ()                   # polylines (arrays (m, 3)) of wire sources
    spectrum: tuple = ((550.0, 1.0),)    # lines (wavelength / nm, share of the flux – any scale)
    distribution: object = None          # pt_photometry.Distribution: measured (surfaces, points)
    axis: tuple = (0.0, 0.0, -1.0)       # points with a distribution: the direction theta = 0


class Scene:
    def __init__(self, mesh: pt_mesh.Mesh, materials: pt_bsdf.Materials, entity_material: np.ndarray,
                 sources: list[SourceSpec], closed: tuple = ()):
        """entity_material: material number per entity of the mesh; closed: entities (indices) whose
        faces should be turned so that their front is the outside (closed bodies)."""
        self.mesh = mesh
        self.materials = materials
        self.exact = True               # normals of the surfaces themselves where rays hit curved faces
        self.bvh = pt_bvh.BVH(mesh.v0, mesh.e1, mesh.e2)
        lo, hi = self.bvh.bmin[0], self.bvh.bmax[0]
        self.size = float(np.linalg.norm(hi - lo))
        self.eps = 1e-7 * max(self.size, 1e-12)
        self.flipped = self._orient(closed) if len(closed) else []
        self.face_material = np.asarray(entity_material, dtype=np.int64)[mesh.face_entity]
        self.tri_material = self.face_material[mesh.face]
        # detectors are no surfaces for the light: they get a BVH of their own, used only to find
        # where rays cross them
        virtual = materials.kind[self.tri_material] == pt_bsdf.DETECTOR
        self.face_virtual = materials.kind[self.face_material] == pt_bsdf.DETECTOR
        self.detectors = None
        if virtual.any():
            self.detectors = _Part(mesh, np.nonzero(virtual)[0])
            self.bvh = _Part(mesh, np.nonzero(~virtual)[0]) if not virtual.all() else None
        self._sources(sources)

    # ------------------------------------------------------------------ rays
    def _accept(self, ray, tri, b1, b2):
        return self.mesh.accept(tri, b1, b2)

    def hit(self, o: np.ndarray, d: np.ndarray):
        """Nearest hit: t, triangle (-1: none), b1, b2. Detectors are not hit."""
        if self.bvh is None:
            n = len(o)
            return np.full(n, np.inf), np.full(n, -1, dtype=np.int64), np.zeros(n), np.zeros(n)
        return self.bvh.intersect(o, d, accept=self._accept if self.mesh.masks.size else None)

    def occluded(self, o: np.ndarray, target: np.ndarray) -> np.ndarray:
        if self.bvh is None:
            return np.zeros(len(o), dtype=bool)
        return self.bvh.intersect(o, target - o, 1.0, any_hit=True,
                                  accept=self._accept if self.mesh.masks.size else None)[1] >= 0

    def crossing(self, o: np.ndarray, d: np.ndarray, tmax: np.ndarray):
        """Nearest crossing of a detector before tmax: t, triangle (-1: none), b1, b2."""
        return self.detectors.intersect(o, d, tmax, accept=self._accept if self.mesh.masks.size else None)

    def offset(self, p: np.ndarray, ng: np.ndarray, towards: np.ndarray) -> np.ndarray:
        """p moved a hair off its surface to the side of the direction `towards`."""
        s = np.sign(np.einsum("ij,ij->i", ng, towards))
        return p + ng * (s * self.eps)[:, None]

    # ------------------------------------------------------------------ orientation
    def _orient(self, entities) -> list[int]:
        """Turns faces of closed bodies whose normal points inwards: a ray from a face along its
        normal leaves a closed body through an even number of its faces, the opposite ray through
        an odd number. Faces without a clear answer (open shells) stay. Returns the turned faces."""
        mesh = self.mesh
        rng = np.random.default_rng(1)
        faces = np.nonzero(np.isin(mesh.face_entity, np.asarray(list(entities))) & (mesh.face_area > 0))[0]
        if not faces.size:
            return []
        per = 5
        f = np.repeat(faces, per)
        tri = np.empty(len(f), dtype=np.int64)
        b1, b2 = np.empty(len(f)), np.empty(len(f))
        for k, face in enumerate(faces):                        # points on every face
            tri[k * per:(k + 1) * per], b1[k * per:(k + 1) * per], b2[k * per:(k + 1) * per] = \
                mesh.sample(np.array([face]), per, rng)
        p = mesh.v0[tri] + b1[:, None] * mesh.e1[tri] + b2[:, None] * mesh.e2[tri]
        n = mesh.ng[tri]
        ent = mesh.face_entity[f]
        counts = []
        for sign in (1.0, -1.0):
            d = n * sign
            o = p + d * self.eps
            count = np.zeros(len(f), dtype=np.int64)
            act = np.arange(len(f))
            for _ in range(256):
                own = ent[act]

                def accept(ray, t, c1, c2, own=own):
                    return (mesh.face_entity[mesh.face[t]] == own[ray]) & mesh.accept(t, c1, c2)

                t, hit, _, _ = self.bvh.intersect(o[act], d[act], accept=accept)
                got = hit >= 0
                act = act[got]
                if not act.size:
                    break
                count[act] += 1
                o[act] = o[act] + d[act] * (t[got] + self.eps)[:, None]
            counts.append(count)
        out_even = (counts[0] % 2 == 0) & (counts[1] % 2 == 1)      # normal points outwards
        in_odd = (counts[0] % 2 == 1) & (counts[1] % 2 == 0)        # normal points inwards
        slot = np.repeat(np.arange(len(faces)), per)
        keep = np.bincount(slot, weights=out_even, minlength=len(faces))
        turn = np.bincount(slot, weights=in_odd, minlength=len(faces))
        flip = faces[turn > np.maximum(keep, per - turn - keep)]
        if flip.size:
            mesh.flip_faces(flip)
            self.bvh.refresh(mesh.v0, mesh.e1, mesh.e2)
        return [int(v) for v in flip]

    # ------------------------------------------------------------------ sources
    def _sources(self, specs: list[SourceSpec]) -> None:
        mesh = self.mesh
        flux, sin_max, sides, area, point, is_point, spectra = [], [], [], [], [], [], []
        faces: list[np.ndarray] = []
        wires: dict[int, tuple] = {}                         # source -> segment starts, ends, cumulative length
        measured: dict[int, object] = {}                     # source -> Distribution
        axes: dict[int, np.ndarray] = {}                     # point source with a distribution -> its axis
        self.face_source = np.full(len(mesh.face_area), -1, dtype=np.int64)
        self.source_names = []
        for spec in specs:
            if spec.flux < 0:
                raise ValueError(f"source {spec.name!r}: negative flux")
            if sum(1 for group in (spec.entities, spec.points, spec.curves) if len(group)) > 1:
                raise ValueError(f"source {spec.name!r} is on objects of different kinds (surfaces, points, "
                                 f"curves): use one source for each kind")
            if spec.flux == 0 or not (len(spec.entities) or len(spec.points) or len(spec.curves)):
                continue
            lines: dict[float, float] = {}
            for nm, share in spec.spectrum:
                if not (nm > 0 and share >= 0):
                    raise ValueError(f"source {spec.name!r}: wavelengths must be positive, shares not negative")
                lines[float(nm)] = lines.get(float(nm), 0.0) + float(share)
            if sum(lines.values()) <= 0:
                raise ValueError(f"source {spec.name!r}: its spectrum is empty")
            if spec.entities:
                if not 0 < spec.half_angle <= 90:
                    raise ValueError(f"source {spec.name!r}: half-angle must lie in 0 … 90°")
                if spec.side not in ("front", "back", "both"):
                    raise ValueError(f"source {spec.name!r}: side must be front, back or both")
                fs = np.nonzero(np.isin(mesh.face_entity, np.asarray(spec.entities)) & (mesh.face_area > 0))[0]
                if not fs.size:
                    raise ValueError(f"source {spec.name!r}: its surfaces have no area")
                if self.face_virtual[fs].any():
                    raise ValueError(f"source {spec.name!r}: a detector cannot be a source (light passes it "
                                     f"as if it were not there)")
                if (self.face_source[fs] >= 0).any():
                    raise ValueError(f"source {spec.name!r}: a surface already belongs to another source")
                if spec.distribution is not None:
                    measured[len(flux)] = spec.distribution
                self.face_source[fs] = len(flux)
                faces.append(fs)
                flux.append(spec.flux)
                sin_max.append(np.sin(np.radians(spec.half_angle)))
                sides.append({"front": 1, "back": -1, "both": 0}[spec.side])
                area.append(float(mesh.face_area[fs].sum()))
                point.append((np.nan,) * 3)
                is_point.append(False)
                spectra.append(lines)
                self.source_names.append(spec.name)
            elif len(spec.curves):
                starts = np.concatenate([np.asarray(c, dtype=float)[:-1] for c in spec.curves])
                ends = np.concatenate([np.asarray(c, dtype=float)[1:] for c in spec.curves])
                length = np.linalg.norm(ends - starts, axis=1)
                keep = length > 0
                if not keep.any():
                    raise ValueError(f"source {spec.name!r}: its curves have no length")
                wires[len(flux)] = (starts[keep], ends[keep], np.cumsum(length[keep]))
                faces.append(np.zeros(0, dtype=np.int64))
                flux.append(spec.flux)
                sin_max.append(1.0)
                sides.append(0)
                area.append(1.0)
                point.append((np.nan,) * 3)
                is_point.append(True)
                spectra.append(lines)
                self.source_names.append(spec.name)
            else:
                for p in spec.points:
                    if spec.distribution is not None:
                        axis = np.asarray(spec.axis, dtype=float)
                        if not np.linalg.norm(axis) > 0:
                            raise ValueError(f"source {spec.name!r}: its axis has no direction")
                        measured[len(flux)] = spec.distribution
                        axes[len(flux)] = axis / np.linalg.norm(axis)
                    faces.append(np.zeros(0, dtype=np.int64))
                    flux.append(spec.flux / len(spec.points))
                    sin_max.append(1.0)
                    sides.append(0)
                    area.append(1.0)
                    point.append(tuple(float(c) for c in p))
                    is_point.append(True)
                    spectra.append(lines)
                    self.source_names.append(spec.name)
        if not flux:
            raise ValueError("no source: give at least one object a source with a flux above 0")
        self.src_flux = np.asarray(flux)
        self.src_sin = np.asarray(sin_max)
        self.src_cos = np.sqrt(np.clip(1 - self.src_sin ** 2, 0.0, None))
        self.src_sides = np.asarray(sides, dtype=np.int64)
        self.src_area = np.asarray(area)
        self.src_point = np.asarray(point, dtype=float).reshape(-1, 3)
        self.src_is_point = np.asarray(is_point, dtype=bool)
        self.src_faces = faces
        self.src_wires = wires
        self.src_measured = measured
        self.src_axes = axes
        self.src_is_measured = np.asarray([k in measured for k in range(len(flux))], dtype=bool)
        self.src_is_wire = np.asarray([k in wires for k in range(len(flux))], dtype=bool)
        self.flux = float(self.src_flux.sum())
        self.src_prob = self.src_flux / self.flux
        nsides = np.where(self.src_sides == 0, 2.0, 1.0)
        # radiance of surfaces W/(mm² sr), intensity of points W/sr (wires: across the wire)
        self.src_radiance = np.where(self.src_is_point, self.src_flux / (4 * np.pi),
                                     self.src_flux / (nsides * self.src_area * np.pi * self.src_sin ** 2))
        self.src_dir_norm = np.where(self.src_is_point, 1 / (4 * np.pi), 1 / (nsides * np.pi * self.src_sin ** 2))
        self.src_radiance[self.src_is_wire] = self.src_flux[self.src_is_wire] / np.pi ** 2
        self.src_dir_norm[self.src_is_wire] = 1 / np.pi ** 2
        # wavelengths: the lines of all sources; per source the share of its flux in each
        self.wavelengths = np.asarray(sorted({nm for lines in spectra for nm, share in lines.items() if share > 0}))
        self.src_spectrum = np.asarray([[lines.get(nm, 0.0) for nm in self.wavelengths] for lines in spectra])
        self.src_spectrum /= self.src_spectrum.sum(axis=1, keepdims=True)
        self.channel_prob = self.src_prob @ self.src_spectrum           # share of each wavelength in all paths
        self.materials.wavelengths(self.wavelengths)

    def spectral_weight(self, src: np.ndarray, channel: np.ndarray) -> np.ndarray:
        """Share of the wavelength `channel` in the flux of source `src`, over its share in all
        paths: what a path that carries this wavelength and ends on this source has to count."""
        return self.src_spectrum[src, channel] / self.channel_prob[channel]

    def _emits(self, src: np.ndarray, cos: np.ndarray) -> np.ndarray:
        """Whether a surface source emits into a direction with the cosine `cos` to its normal."""
        sides = self.src_sides[src]
        return (np.abs(cos) >= self.src_cos[src]) & (np.abs(cos) > 0) & ((sides == 0) | (np.sign(cos) == sides))

    def emitted(self, src: np.ndarray, n: np.ndarray, w: np.ndarray):
        """Radiance (points and wires: intensity) of source `src` into the direction w and the
        density (per solid angle) with which emission picks w; n: normal at the point (wires: the
        direction of the wire; ignored for points)."""
        cos = np.einsum("ij,ij->i", n, w)
        pt = self.src_is_point[src]
        ok = pt | self._emits(src, cos)
        across = np.where(self.src_is_wire[src], np.sqrt(np.clip(1 - cos * cos, 0.0, None)), 1.0)   # sin(theta)
        le = np.where(ok, self.src_radiance[src] * across, 0.0)
        pdf = np.where(ok, self.src_dir_norm[src] * np.where(pt, across, np.abs(cos)), 0.0)
        if self.src_is_measured[src].any():
            for k in np.unique(src[self.src_is_measured[src]]):
                sel = np.nonzero(src == k)[0]
                axis = self._axis(k, n[sel])
                c = np.einsum("ij,ij->i", axis, w[sel])
                a, b = _across(axis)
                density = self.src_measured[k].eval(c, np.arctan2(np.einsum("ij,ij->i", b, w[sel]),
                                                                  np.einsum("ij,ij->i", a, w[sel])))
                pdf[sel] = density
                if pt[sel[0]]:                               # intensity; a surface: radiance = it / (area |cos|)
                    le[sel] = self.src_flux[k] * density
                else:
                    le[sel] = self.src_flux[k] * density / (self.src_area[k] * np.maximum(np.abs(c), 1e-9))
        return le, pdf

    def _axis(self, k: int, n: np.ndarray) -> np.ndarray:
        """The direction theta = 0 of the measured source k at points with the normals n."""
        if k in self.src_axes:
            return np.broadcast_to(self.src_axes[k], n.shape)
        return n * (-1.0 if self.src_sides[k] < 0 else 1.0)

    def emit_pdf_pos(self, src: np.ndarray) -> np.ndarray:
        """Density of picking a point of the source (per mm²; points: the probability)."""
        return self.src_prob[src] / np.where(self.src_is_point[src], 1.0, self.src_area[src])

    def emit(self, n: int, rng: np.random.Generator) -> dict:
        """n emitted rays: position p, normals ns / ng (zero for points), source, direction d, the
        densities pdf_pos and pdf_dir, and whether the ray is usable (ok)."""
        mesh = self.mesh
        src = np.minimum(np.searchsorted(np.cumsum(self.src_prob), pt_mesh.stratified(n, rng), side="right"),
                         len(self.src_prob) - 1)
        p = np.zeros((n, 3))
        ns = np.zeros((n, 3))
        ng = np.zeros((n, 3))
        d = np.zeros((n, 3))
        cos = np.ones(n)
        u1, u2, u3 = rng.random(n), rng.random(n), rng.random(n)
        channel = (rng.random(n)[:, None] < np.cumsum(self.src_spectrum, axis=1)[src]).argmax(axis=1)
        measured_pdf = np.zeros(n)
        for k in np.unique(src):
            sel = np.nonzero(src == k)[0]
            if self.src_is_measured[k]:                      # a direction by the measured distribution
                if self.src_is_point[k]:
                    p[sel] = self.src_point[k]
                    axis = np.broadcast_to(self.src_axes[k], (len(sel), 3))
                else:
                    tri, b1, b2 = mesh.sample(self.src_faces[k], len(sel), rng)
                    p[sel] = mesh.v0[tri] + b1[:, None] * mesh.e1[tri] + b2[:, None] * mesh.e2[tri]
                    normal, _ = mesh.shade(tri, b1, b2)
                    ns[sel], ng[sel] = normal, mesh.ng[tri]
                    axis = self._axis(k, normal)
                c, phi, density = self.src_measured[k].sample(len(sel), rng)
                a, b = _across(axis)
                sin = np.sqrt(np.clip(1 - c * c, 0.0, None))
                d[sel] = (sin * np.cos(phi))[:, None] * a + (sin * np.sin(phi))[:, None] * b + c[:, None] * axis
                if self.src_is_point[k]:
                    ns[sel] = axis                           # (kept for emitted(); a point has no surface)
                measured_pdf[sel] = density
                continue
            if self.src_is_wire[k]:                          # a point on the wire, a direction as from the
                starts, ends, cum = self.src_wires[k]        # surface of a thin Lambertian cylinder around it
                seg = np.minimum(np.searchsorted(cum, u3[sel] * cum[-1], side="right"), len(cum) - 1)
                p[sel] = starts[seg] + rng.random(len(sel))[:, None] * (ends[seg] - starts[seg])
                along = ends[seg] - starts[seg]
                along /= np.linalg.norm(along, axis=1, keepdims=True)
                outward = pt_bsdf._around(along, np.zeros(len(sel)), 2 * np.pi * rng.random(len(sel)))
                d[sel], _ = pt_bsdf._cosine(outward, u1[sel], u2[sel])
                ns[sel] = along
                cos[sel] = np.sqrt(np.clip(1 - np.einsum("ij,ij->i", along, d[sel]) ** 2, 0.0, None))
                continue
            if self.src_is_point[k]:
                p[sel] = self.src_point[k]
                z = 1 - 2 * u1[sel]
                r = np.sqrt(np.clip(1 - z * z, 0.0, None))
                d[sel] = np.column_stack([r * np.cos(2 * np.pi * u2[sel]), r * np.sin(2 * np.pi * u2[sel]), z])
                continue
            tri, b1, b2 = mesh.sample(self.src_faces[k], len(sel), rng)
            p[sel] = mesh.v0[tri] + b1[:, None] * mesh.e1[tri] + b2[:, None] * mesh.e2[tri]
            normal, _ = mesh.shade(tri, b1, b2)
            ns[sel], ng[sel] = normal, mesh.ng[tri]
            side = float(self.src_sides[k]) if self.src_sides[k] else np.where(u3[sel] < 0.5, 1.0, -1.0)
            w, c = pt_bsdf.cone(normal * np.reshape(side, (-1, 1)), np.full(len(sel), self.src_sin[k]), u1[sel], u2[sel])
            d[sel], cos[sel] = w, c
        pt = self.src_is_point[src]
        pdf_dir = self.src_dir_norm[src] * np.where(pt & ~self.src_is_wire[src], 1.0, cos)
        ok = pt | ((cos > 0) & (np.einsum("ij,ij->i", ng, d) * np.einsum("ij,ij->i", ns, d) > 0))
        by_table = self.src_is_measured[src]
        pdf_dir = np.where(by_table, measured_pdf, pdf_dir)
        ok = np.where(by_table, pt | (np.einsum("ij,ij->i", ng, d) * np.einsum("ij,ij->i", ns, d) > 0), ok)
        return {"p": p, "ns": ns, "ng": ng, "src": src, "d": d, "pdf_pos": self.emit_pdf_pos(src),
                "pdf_dir": pdf_dir, "ok": ok, "point": pt, "channel": channel}


# ---------------------------------------------------------------------------- sensors
class TexelSensor:
    """Irradiance on faces: every face gets a texture over its normalised (u, v); a texel collects
    the flux that arrives in it, from both sides."""
    camera = False

    def __init__(self, scene: Scene, faces, long_side: int):
        mesh = scene.mesh
        self.scene = scene
        self.faces = np.asarray([f for f in faces if mesh.face_area[f] > 0], dtype=np.int64)
        if not self.faces.size:
            raise ValueError("no face to compute the irradiance on")
        self.slot = np.full(len(mesh.face_area), -1, dtype=np.int64)
        self.slot[self.faces] = np.arange(len(self.faces))
        self.size = [mesh.texels(int(f), long_side) for f in self.faces]          # (w, h) per face
        self.w = np.asarray([s[0] for s in self.size], dtype=np.int64)
        self.h = np.asarray([s[1] for s in self.size], dtype=np.int64)
        self.first = np.concatenate([[0], np.cumsum(self.w * self.h)])
        self.count = int(self.first[-1])
        self.texel_area = np.concatenate([mesh.texel_areas(int(f), w, h).ravel()
                                          for f, (w, h) in zip(self.faces, self.size)])
        self.area = float(mesh.face_area[self.faces].sum())
        self.crossed = bool(scene.face_virtual[self.faces].any())   # light passes some of the faces
        self.texel_density = np.concatenate([self._densities(int(f), w, h) for f, (w, h) in zip(self.faces, self.size)])
        self.reset()

    def _densities(self, face: int, w: int, h: int) -> np.ndarray:
        """Largest area density (mm² per unit of (u, v)) in every texel of a face, row by row."""
        g = self.scene.mesh.grids[face]
        cells = self.scene.mesh.cell_density(face)

        def ranges(lines, count):                            # grid cells a texel touches: first, last
            edges = np.arange(count + 1) / count
            first = np.clip(np.searchsorted(lines, edges[:-1], side="right") - 1, 0, len(lines) - 2)
            last = np.clip(np.searchsorted(lines, edges[1:], side="left") - 1, 0, len(lines) - 2)
            return first, np.maximum(first, last)

        u0, u1 = ranges(g.ug, w)
        v0, v1 = ranges(g.vg, h)
        along_u = np.stack([cells[a:b + 1].max(axis=0) for a, b in zip(u0, u1)])           # (w, grid v)
        return np.stack([along_u[:, a:b + 1].max(axis=1) for a, b in zip(v0, v1)]).ravel()   # (h, w)

    # ------------------------------------------------------------------ where the samples go
    def reset(self) -> None:
        """Points uniform by area: every texel is picked by its area."""
        self.set_weights(self.texel_area)

    def set_weights(self, weights: np.ndarray) -> None:
        """Texels are picked in proportion to `weights` (points stay uniform within a texel)."""
        weights = np.where(self.texel_area > 0, np.asarray(weights, dtype=float), 0.0)
        self.prob = weights / weights.sum()
        self.cum_prob = np.cumsum(self.prob)

    def adapt(self, error: np.ndarray, floor: float = 0.3) -> None:
        """More points where the irradiance is still uncertain. error: the standard error of the
        flux per texel so far, got with the present choice. The sum of the variances of the
        texels' irradiances is smallest when a texel is picked in proportion to (its error x
        the root of its present share); `floor` of the points stay spread by area."""
        usable = self.texel_area > 0.1 * np.median(self.texel_area[self.texel_area > 0])
        with np.errstate(divide="ignore", invalid="ignore"):
            want = np.where(usable, error / self.texel_area * np.sqrt(self.prob), 0.0)
        if np.isfinite(want).all() and want.sum() > 0:
            self.set_weights(floor * self.texel_area / self.texel_area.sum() + (1 - floor) * want / want.sum())

    def pdf_pos_at(self, tex: np.ndarray) -> np.ndarray:
        """Density (per mm²) with which the sensor picks a point of the texel."""
        return self.prob[tex] / self.texel_area[tex]

    def texel(self, tri: np.ndarray, uv: np.ndarray) -> np.ndarray:
        """Texel of points on triangles (-1: not on a sensor face)."""
        s = self.slot[self.scene.mesh.face[tri]]
        on = s >= 0
        out = np.full(len(tri), -1, dtype=np.int64)
        so = s[on]
        w, h = self.w[so], self.h[so]
        i = np.clip((uv[on, 0] * w).astype(np.int64), 0, w - 1)
        j = np.clip((uv[on, 1] * h).astype(np.int64), 0, h - 1)
        out[on] = self.first[so] + j * w + i
        return out

    def sample(self, n: int, rng: np.random.Generator) -> dict:
        """n rays from points on the sensor faces (see points), into both half-spaces by the
        cosine. exists: False where no point was found (nothing may be made of such a sample)."""
        mesh = self.scene.mesh
        tri, b1, b2, tex = self.points(n, rng)
        exists = tri >= 0
        tri = np.maximum(tri, 0)
        pdf_pos = np.where(exists, self.pdf_pos_at(tex), 1.0)
        p = mesh.v0[tri] + b1[:, None] * mesh.e1[tri] + b2[:, None] * mesh.e2[tri]
        ns, uv = mesh.shade(tri, b1, b2)
        ng = mesh.ng[tri]
        side = np.where(rng.random(n) < 0.5, 1.0, -1.0)
        d, cos = pt_bsdf._cosine(ns * side[:, None], rng.random(n), rng.random(n))
        ok = exists & (cos > 0) & (np.einsum("ij,ij->i", ng, d) * np.einsum("ij,ij->i", ns, d) > 0)
        return {"p": p, "ns": ns, "ng": ng, "d": d, "texel": np.where(exists, tex, -1), "ok": ok, "exists": exists,
                "pdf_pos": pdf_pos, "pdf_dir": cos / (2 * np.pi), "beta": 2 * np.pi / pdf_pos,
                "point": np.zeros(n, dtype=bool)}

    def points(self, n: int, rng: np.random.Generator):
        """n points on the sensor faces – triangle (-1: none found), b1, b2, texel. The texel is
        picked by its share (reset, set_weights, adapt), the point uniform by area inside it. The
        points are spread evenly: every texel gets the number its share asks for (to within one)
        instead of a number that scatters, which would be noise of its own in the texel's value."""
        mesh = self.scene.mesh
        tex = np.minimum(np.searchsorted(self.cum_prob, pt_mesh.stratified(n, rng) * self.cum_prob[-1], side="right"),
                         self.count - 1)
        slot = np.searchsorted(self.first, tex, side="right") - 1
        w, h = self.w[slot], self.h[slot]
        i, j = (tex - self.first[slot]) % w, (tex - self.first[slot]) // w
        tri = np.full(n, -1, dtype=np.int64)
        b1, b2 = np.zeros(n), np.zeros(n)
        todo = np.arange(n)
        for _ in range(256):        # evenly in the texel's (u, v), kept where the face is, by the area there
            u = (i[todo] + rng.random(len(todo))) / w[todo]
            v = (j[todo] + rng.random(len(todo))) / h[todo]
            keep = rng.random(len(todo))
            ok = np.zeros(len(todo), dtype=bool)
            for s in np.unique(slot[todo]):
                sel = np.nonzero(slot[todo] == s)[0]
                face = int(self.faces[s])
                t, c1, c2, density = mesh.locate(face, u[sel], v[sel])
                good = (t >= 0) & (keep[sel] * self.texel_density[tex[todo[sel]]] < density) \
                    & mesh.inside(np.full(len(sel), face), u[sel], v[sel])
                a = todo[sel[good]]
                tri[a], b1[a], b2[a] = t[good], c1[good], c2[good]
                ok[sel[good]] = True
            todo = todo[~ok]
            if not todo.size:
                break
        return tri, b1, b2, tex                              # (left without: texels with hardly any area)

    def response(self, ns: np.ndarray, w: np.ndarray):
        """Importance into the direction w from a sensor point, the density of picking w, and
        the texel it belongs to (None: the point's own)."""
        return np.ones(len(w)), np.abs(np.einsum("ij,ij->i", ns, w)) / (2 * np.pi), None

class Camera:
    """A pinhole camera at `position` looking at `target`; `fov`: full horizontal angle in
    degrees; width x height pixels. Pixel (i, j): i to the right, j upwards."""
    camera = True

    def __init__(self, position, target, up, fov: float, width: int, height: int):
        self.position = np.asarray(position, dtype=float)
        forward = np.asarray(target, dtype=float) - self.position
        if np.linalg.norm(forward) < 1e-12:
            raise ValueError("camera: position and target are the same point")
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, np.asarray(up, dtype=float))
        if np.linalg.norm(right) < 1e-9:
            raise ValueError("camera: the view direction is parallel to the up direction")
        right /= np.linalg.norm(right)
        if not 0 < fov < 180:
            raise ValueError("camera: field of view must lie in 0 … 180°")
        self.forward, self.right, self.up = forward, right, np.cross(right, forward)
        self.w, self.h = int(width), int(height)
        self.tan_x = float(np.tan(np.radians(fov) / 2))
        self.tan_y = self.tan_x * self.h / self.w
        self.count = self.w * self.h
        self.film = 4 * self.tan_x * self.tan_y              # film area at distance 1
        self.area = 1.0
        self.reset()

    # ------------------------------------------------------------------ where the samples go
    def reset(self) -> None:
        """Every pixel gets the same share of the rays."""
        self.set_weights(np.ones(self.count))

    def set_weights(self, weights: np.ndarray) -> None:
        """Pixels are picked in proportion to `weights` (rays stay uniform within a pixel)."""
        weights = np.asarray(weights, dtype=float)
        self.prob = weights / weights.sum()
        self.cum_prob = np.cumsum(self.prob)

    def adapt(self, error: np.ndarray, floor: float = 0.3) -> None:
        """More rays for the pixels that are still uncertain: picked in proportion to (their
        standard error so far x the root of their present share), `floor` of the rays stay
        spread evenly – that makes the sum of the pixels' variances smallest."""
        want = error * np.sqrt(self.prob)
        if np.isfinite(want).all() and want.sum() > 0:
            self.set_weights(floor / self.count + (1 - floor) * want / want.sum())

    def pdf_pos_at(self, tex: np.ndarray) -> np.ndarray:
        return np.ones(len(tex))

    def sample(self, n: int, rng: np.random.Generator) -> dict:
        # spread over the pixels: each gets its share of the rays (to within one), jittered inside
        pixel = np.minimum(np.searchsorted(self.cum_prob, pt_mesh.stratified(n, rng) * self.cum_prob[-1],
                                           side="right"), self.count - 1)
        x = (2 * (pixel % self.w + rng.random(n)) / self.w - 1) * self.tan_x
        y = (2 * (pixel // self.w + rng.random(n)) / self.h - 1) * self.tan_y
        d = self.forward + x[:, None] * self.right + y[:, None] * self.up
        length = np.linalg.norm(d, axis=1)
        d /= length[:, None]
        cos = 1.0 / length
        share = self.prob[pixel] * self.count                # of the rays, against an even spread
        return {"p": np.broadcast_to(self.position, (n, 3)).copy(), "ns": np.zeros((n, 3)), "ng": np.zeros((n, 3)),
                "d": d, "texel": pixel, "ok": np.ones(n, dtype=bool), "exists": np.ones(n, dtype=bool),
                "pdf_pos": np.ones(n), "pdf_dir": share / (self.film * cos ** 3), "beta": self.count / share,
                "point": np.ones(n, dtype=bool)}

    def _pixel(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        i = np.floor((x / self.tan_x + 1) * 0.5 * self.w).astype(np.int64)
        j = np.floor((y / self.tan_y + 1) * 0.5 * self.h).astype(np.int64)
        return np.where((i >= 0) & (i < self.w) & (j >= 0) & (j < self.h), j * self.w + i, -1)

    def response(self, ns: np.ndarray, w: np.ndarray):
        """Importance of the camera into the direction w (the mean radiance of a pixel is the
        integral of radiance x importance over the directions), the density with which the
        camera picks w, and the pixel of w (-1: outside the image)."""
        cos = w @ self.forward
        front = cos > 1e-9
        c = np.where(front, cos, 1.0)
        pixel = np.where(front, self._pixel((w @ self.right) / c, (w @ self.up) / c), -1)
        inside = pixel >= 0
        even = np.where(inside, 1.0 / (self.film * c ** 3), 0.0)
        return even * self.count, even * self.prob[np.maximum(pixel, 0)] * self.count, pixel

    def frustum(self, length: float) -> np.ndarray:
        """Polylines of the viewing pyramid up to `length`: (points (10, 3)) – apex to the four
        corners and the rectangle; for drawing."""
        corners = [self.position + length * (self.forward + sx * self.tan_x * self.right + sy * self.tan_y * self.up)
                   for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        return np.asarray(corners)
