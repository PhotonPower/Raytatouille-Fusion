"""The light distribution by ray tracing, with the kernel of the Path Tracer plugin (C++ if the
package `pathtracer` ≥ 0.2.0 is installed, else NumPy).

The scene: the coil as it is (al_coil: a helix of wire whose surface shines evenly – Lambertian,
the same luminance everywhere), the H4's shield and cap, the mirror (the facets and the
connecting faces, or the paraboloid) and the lens, all as NURBS surfaces in design coordinates.
Light paths start on the wire and are followed through every reflection – the mirror with its
reflectance, the lens with Fresnel's reflection and refraction (index of the panel, no
absorption) – until they leave; what leaves is binned by its direction into the cells of the
screen (luminous intensity = flux / solid angle of the cell). The wire, shield and cap absorb.

The coil's flux is set so that what gets out of the coil – past its own turns – is the lamp's
flux, as the design's cylinder sends it. Not modelled: the bulb's glass, the lamp's supports and
leads, the lens' rim (light that reaches it inside the glass leaves there, unrefracted)."""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import al_coil
from al_optics import Lamp
from al_photometry import Distribution

PATHTRACER = Path(__file__).resolve().parent.parent / "pathtracer"
TOLERANCE = 0.002          # mm: the triangles within this of the surfaces (the rays meet the surfaces themselves)
WAVELENGTH = 555.0         # nm: one line; fluxes are in lm throughout

COIL, SHIELD, CAP, FACETS, CONNECTIONS, MIRROR, LENS = "coil", "shield", "cap", "facets", "connections", "mirror", "lens"


def _numpy():
    """The NumPy kernel's modules (from the Path Tracer plugin next to this one)."""
    if str(PATHTRACER) not in sys.path:
        sys.path.append(str(PATHTRACER))
    try:
        import pt_bsdf
        import pt_integrator
        import pt_mesh
        import pt_scene
    except ImportError as e:
        raise RuntimeError(f"the ray tracing needs the Path Tracer plugin next to this one ({PATHTRACER})") from e
    return pt_bsdf, pt_integrator, pt_mesh, pt_scene


def _native():
    try:
        import pathtracer
    except ImportError:
        return None
    return pathtracer if hasattr(pathtracer, "escapes") else None


def kernel(choice: str = "automatic") -> str:
    """"C++" or "NumPy" for the choice automatic / C++ / NumPy."""
    native = _native()
    if choice == "C++" and native is None:
        raise RuntimeError("the C++ kernel (package pathtracer 0.2.0 or later) is not installed in the plugins' "
                           "Python: pip install git+https://github.com/PhotonPower/PathTracer")
    return "C++" if choice != "NumPy" and native is not None else "NumPy"


# ------------------------------------------------------------------ the scene
@dataclass
class Body:
    """One entity of the scene: its role (COIL …), the faces and its material row."""

    role: str
    faces: list[dict]
    material: dict


def lamp_bodies(lamp: Lamp, coil: al_coil.Coil) -> list[Body]:
    """The coil (first) and what of the lamp stops its light."""
    black = {"name": "black", "kind": "absorber"}
    bodies = [Body(COIL, [{"surface": f} for f in al_coil.coil_faces(coil)], {"name": "tungsten", "kind": "absorber"})]
    if lamp.shield is not None:
        parts = al_coil.shield_faces(lamp.shield)
        for role in (SHIELD, CAP):
            faces = [{"surface": g} for kind, g in parts if kind == role]
            if faces:
                bodies.append(Body(role, faces, dict(black, name=role)))
    return bodies


def _mirror(name: str, reflectance: float) -> dict:
    if reflectance <= 0.0:
        return {"name": name, "kind": "absorber"}
    return {"name": name, "kind": "mirror", "reflectance": float(reflectance)}


def reflector_bodies(reflector, reflectance: float, reflectance_connections: float) -> list[Body]:
    """The facets and the connecting faces of a facetted reflector."""
    import al_reflector

    facets, connections = [], []
    for part, face in al_reflector.faces(reflector):
        (facets if part.kind == al_reflector.FACET else connections).append(face)
    out = [Body(FACETS, facets, _mirror("facets", reflectance))]
    if connections:
        out.append(Body(CONNECTIONS, connections, _mirror("connections", reflectance_connections)))
    return out


def _turned(face: dict) -> dict:
    """The face with u and v swapped: the same surface, its normal the other way."""
    s = face["surface"]
    nu, nv = int(s["num_u"]), int(s["num_v"])
    surface = dict(s, degree_u=s["degree_v"], degree_v=s["degree_u"], knots_u=s["knots_v"], knots_v=s["knots_u"],
                   num_u=nv, num_v=nu,
                   points=[float(c) for c in np.asarray(s["points"], dtype=float).reshape(nu, nv, 3)
                           .transpose(1, 0, 2).reshape(-1)])
    if s.get("weights"):
        surface["weights"] = [float(w) for w in np.asarray(s["weights"], dtype=float).reshape(nu, nv).T.reshape(-1)]

    def swapped(curve: dict) -> dict:
        p = np.asarray(curve["points"], dtype=float).reshape(-1, 3)[:, [1, 0, 2]]
        return dict(curve, points=[float(c) for c in p.reshape(-1)])

    out = dict(face, surface=surface)
    if face.get("outer"):
        out["outer"] = [swapped(c) for c in face["outer"]]
    if face.get("holes"):
        out["holes"] = [[swapped(c) for c in loop] for loop in face["holes"]]
    return out


def lens_bodies(system, reflectance: float) -> list[Body]:
    """The paraboloid and the lens – one glass body of the outer side, the elements and the walls,
    every face turned so that its normal points out of the glass (tested a hair in front of a few
    of its points: inside the glass is between the inner side and the outer side)."""
    import al_lens

    _, _, pt_mesh, _ = _numpy()
    s = system.settings
    mirror, lens = [], []
    for kind, _name, face in al_lens.faces(system):
        (mirror if kind == "mirror" else lens).append(face)
    mesh = pt_mesh.build([{"id": 0, "geometry": {"type": "shell", "faces": lens}}], 0.005)
    rng = np.random.default_rng(1)
    faces = []
    for k, face in enumerate(lens):
        tri, b1, b2 = mesh.sample(np.array([k]), 5, rng)
        p = mesh.v0[tri] + b1[:, None] * mesh.e1[tri] + b2[:, None] * mesh.e2[tri]
        n, _ = mesh.shade(tri, b1, b2)
        q = p + 0.05 * n                                 # (ten times the triangles' distance from the surface)
        inner, _, _, on_cell, _ = system.inner(q[:, 1], q[:, 2])
        outer = s.lens_x + s.thickness + system.shape(q[:, 1], q[:, 2])[0]
        glass = on_cell & (q[:, 0] > s.lens_x + inner) & (q[:, 0] < outer)
        faces.append(_turned(face) if glass.sum() > len(glass) / 2 else face)
    return [Body(MIRROR, mirror, _mirror("mirror", reflectance)),
            Body(LENS, faces, {"name": "glass", "kind": "glass", "ior": float(s.index)})]


class Scene:
    """The bodies as a scene of the kernel, with the coil as the source of `flux` (lm)."""

    def __init__(self, bodies: list[Body], flux: float, kernel_name: str):
        self.bodies, self.kernel = bodies, kernel_name
        entities = [{"id": k + 1, "geometry": {"type": "shell", "faces": b.faces}} for k, b in enumerate(bodies)]
        rows, numbers = [], []
        for b in bodies:
            if b.material["name"] not in [r["name"] for r in rows]:
                rows.append(b.material)
            numbers.append([r["name"] for r in rows].index(b.material["name"]))
        coil = [k for k, b in enumerate(bodies) if b.role == COIL]
        if kernel_name == "C++":
            pt = _native()
            mesh = pt.build_mesh(entities, TOLERANCE)
            source = {"name": "coil", "flux": float(flux), "half_angle": 90.0, "side": "front", "entities": coil,
                      "points": [], "curves": [], "spectrum": [[WAVELENGTH, 1.0]], "distribution": None,
                      "axis": [0.0, 0.0, -1.0]}
            self.scene = pt.Scene(mesh, [dict(r, spectrum=[]) for r in rows], numbers, [source], [])
        else:
            pt_bsdf, _, pt_mesh, pt_scene = _numpy()
            mesh = pt_mesh.build(entities, TOLERANCE)
            source = pt_scene.SourceSpec("coil", float(flux), 90.0, "front", tuple(coil), spectrum=((WAVELENGTH, 1.0),))
            self.scene = pt_scene.Scene(mesh, pt_bsdf.Materials.from_rows(rows), np.asarray(numbers), [source])
        self.scene.exact = True
        self.scene.contact = max(self.scene.contact, 2 * TOLERANCE)
        self.triangles = int(mesh.triangles)

    def escapes(self, n: int, depth: int, seed: int, index: int) -> dict:
        if self.kernel == "C++":
            return _native().escapes(self.scene, n, depth, seed=seed, index=index)
        _, pt_integrator, _, _ = _numpy()
        return pt_integrator.escapes(self.scene, n, depth, seed=seed, index=index)


def coil_share(coil: al_coil.Coil, kernel_name: str, rays: int = 200_000, seed: int = 1) -> float:
    """The share of the wire's light that gets out of the coil past its own turns."""
    bodies = [Body(COIL, [{"surface": f} for f in al_coil.coil_faces(coil)], {"name": "tungsten", "kind": "absorber"})]
    out = Scene(bodies, 1.0, kernel_name).escapes(rays, 1, seed, 0)
    return float(out["flux"].sum())


# ------------------------------------------------------------------ the light distribution
@dataclass
class Traced:
    """What the ray tracing found, besides the distribution."""

    kernel: str
    coil: al_coil.Coil
    coil_share: float              # of the wire's light, what leaves the coil
    rays: int                      # light paths followed
    traced: int                    # rays traced (segments)
    triangles: int
    flux_back: float = 0.0         # lm that leave backwards (into the housing)
    flux_housing: float = 0.0      # lm that leave a lamp with a lens elsewhere than through the lens
    flux_lost: float = 0.0         # lm absorbed in the lamp (shield, cap, coil) and by the mirror
    noise: float = float("nan")    # standard error of the intensity near its maximum, relative
    by_role: dict = field(default_factory=dict)   # lm leaving forwards by the role of the first surface
    beam: np.ndarray | None = None                # cd of the beam alone (without the direct light), as intensity


def trace(bodies: list[Body], lamp: Lamp, coil: al_coil.Coil, *, rays: int, depth: int = 12, kernel_name: str,
          h_range=(-40.0, 40.0), v_range=(-15.0, 10.0), dh: float = 0.25, dv: float = 0.1, seed: int = 1,
          batch: int = 250_000, progress=None) -> tuple[Distribution, Traced]:
    """The luminous intensity of the scene `bodies` (lamp_bodies first) on the screen's cells,
    from `rays` light paths of up to `depth` segments. The light whose first surface is the mirror
    is the beam, of it what met a connecting face first or last its stray light; the rest that
    leaves forwards is the lamp's direct light (Distribution.add_direct). With a lens only what
    leaves through it reaches the screen – the rest stays in the housing. progress(fraction, text)."""
    share = coil_share(coil, kernel_name)
    if not share > 0:
        raise RuntimeError("no light gets out of the coil")
    scene = Scene(bodies, lamp.flux / share, kernel_name)
    roles = np.array([b.role for b in bodies] + ["none"])
    lensed = LENS in roles
    nh = int(round((h_range[1] - h_range[0]) / dh))
    nv = int(round((v_range[1] - v_range[0]) / dv))
    beam, direct = np.zeros(nv * nh), np.zeros(nv * nh)
    squares = np.zeros(nv * nh)
    batches = max(1, math.ceil(rays / batch))
    info = Traced(kernel_name, coil, share, 0, 0, scene.triangles)
    flux_beam = flux_direct = flux_connections = flux_out = 0.0
    by_role: dict[str, float] = {}
    for index in range(batches):
        n = min(batch, rays - index * batch)
        if progress is not None:
            progress(index / batches, f"ray tracing ({kernel_name}): {index * batch:,} of {rays:,} light paths")
        out = scene.escapes(n, depth, seed, index)
        info.rays += n
        info.traced += int(out["rays"])
        d, flux = np.asarray(out["d"]), np.asarray(out["flux"]) * n        # (flux of the batch: times its share)
        first, last = roles[np.asarray(out["first"])], roles[np.asarray(out["last"])]
        flux_out += float(flux.sum())
        housing = (last != LENS) if lensed else np.zeros(len(flux), dtype=bool)
        info.flux_housing += float(flux[housing].sum())
        forward = (d[:, 0] > 1e-9) & ~housing
        info.flux_back += float(flux[~forward & ~housing].sum())
        d, flux, first, last = d[forward], flux[forward], first[forward], last[forward]
        in_beam = np.isin(first, (FACETS, CONNECTIONS, MIRROR))
        flux_beam += float(flux[in_beam].sum())
        flux_direct += float(flux[~in_beam].sum())
        flux_connections += float(flux[in_beam & ((first == CONNECTIONS) | (last == CONNECTIONS))].sum())
        for role in np.unique(first):
            by_role[str(role)] = by_role.get(str(role), 0.0) + float(flux[first == role].sum())
        H = np.degrees(np.arctan(-d[:, 1] / d[:, 0]))
        V = np.degrees(np.arctan(d[:, 2] / d[:, 0]))
        i = np.floor((H - h_range[0]) / dh).astype(int)
        j = np.floor((V - v_range[0]) / dv).astype(int)
        inside = (i >= 0) & (i < nh) & (j >= 0) & (j < nv)
        cell = j[inside] * nh + i[inside]
        part_beam = np.bincount(cell, weights=(flux * in_beam)[inside], minlength=nv * nh)
        part_direct = np.bincount(cell, weights=(flux * ~in_beam)[inside], minlength=nv * nh)
        beam += part_beam
        direct += part_direct
        squares += (part_beam + part_direct) ** 2 / n
    total = float(info.rays)
    h = h_range[0] + (np.arange(nh) + 0.5) * dh
    v = v_range[0] + (np.arange(nv) + 0.5) * dv
    th, tv = np.tan(np.radians(h))[None, :], np.tan(np.radians(v))[:, None]
    omega = (math.radians(dh) * (1 + th ** 2)) * (math.radians(dv) * (1 + tv ** 2)) / (1 + th ** 2 + tv ** 2) ** 1.5
    info.beam = (beam / total).reshape(nv, nh) / omega
    dist = Distribution(h, v, info.beam.copy(), flux_beam / total, 0.0, lamp.flux, flux_connections / total)
    dist.add_direct((direct / total).reshape(nv, nh) / omega, flux_direct / total)
    info.flux_back /= total
    info.flux_housing /= total
    info.flux_lost = lamp.flux / share - flux_out / total
    info.by_role = {k: val / total for k, val in by_role.items()}
    if batches >= 2:      # standard error of a cell from the spread of the batches; its median where it is bright
        mean = (beam + direct) / total
        error = np.sqrt(np.maximum(squares - mean ** 2 * total, 0.0) / (total * (batches - 1)))
        bright = mean > 0.5 * mean.max()
        if bright.any():
            info.noise = float(np.median(error[bright] / mean[bright]))
    return dist, info
