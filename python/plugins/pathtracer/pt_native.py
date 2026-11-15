"""The C++ kernel (Python package `pathtracer`, repository PathTracer) behind what the plugin uses
of the NumPy kernel: the same scene from the same description (pt_setup.describe), the same
results as dicts of NumPy arrays. Present only if the package is installed in the plugin's
Python; the plugin then uses it for the computations and keeps NumPy for everything else."""

from __future__ import annotations

import hashlib
import json

try:
    import pathtracer as _pt
except ImportError:                      # not installed: the NumPy kernel does the work
    _pt = None

import pt_setup


def available() -> bool:
    return _pt is not None


def version() -> str:
    return getattr(_pt, "__version__", "") if _pt is not None else ""


class MeshCache:
    """Keeps the mesh of the last model (as pt_setup.MeshCache, for the C++ mesh)."""

    def __init__(self):
        self.key = None
        self.mesh = None

    def get(self, entities: list[dict], tol: float):
        digest = hashlib.sha1()
        digest.update(repr(float(tol)).encode())
        for e in entities:
            digest.update(json.dumps([e.get("id"), e.get("geometry")], sort_keys=True).encode())
        key = digest.hexdigest()
        if key != self.key:
            self.mesh = _pt.build_mesh([{"id": e.get("id", k), "geometry": e.get("geometry")}
                                        for k, e in enumerate(entities)], tol)
            self.key = key
        return self.mesh


def build_scene(entities: list[dict], params: dict, cache: MeshCache | None = None, files=None):
    """The scene of the model for the C++ kernel (see pt_setup.describe)."""
    d = pt_setup.describe(entities, params, files)
    sources = []
    for s in d["sources"]:
        theta_phi_cd = s["table"]
        sources.append({"name": s["name"], "flux": s["flux"], "half_angle": s["half_angle"], "side": s["side"],
                        "entities": list(s["entities"]), "points": [list(p) for p in s["points"]],
                        "curves": [[list(map(float, p)) for p in c] for c in s["curves"]],
                        "spectrum": [list(pair) for pair in s["spectrum"]],
                        "distribution": _pt.Distribution(list(theta_phi_cd[0]), list(theta_phi_cd[1]), theta_phi_cd[2])
                        if theta_phi_cd is not None else None,
                        "axis": list(s["axis"])})
    materials = [{**row, "spectrum": [list(pair) for pair in row["spectrum"]]} for row in d["materials"]]
    mesh = (cache or MeshCache()).get(d["surfaces"], d["tol"])
    scene = _pt.Scene(mesh, materials, list(d["entity_material"]), sources, list(d["closed"]))
    scene.exact = d["exact"]
    scene.contact = max(scene.contact, 2 * d["tol"])
    return scene


def texel_sensor(scene, faces, long_side: int):
    return _pt.TexelSensor(scene, [int(f) for f in faces], int(long_side))


def camera(position, target, up, fov, width, height, lens_radius=0.0, focus=0.0):
    return _pt.Camera(list(position), list(target), list(up), fov, width, height, lens_radius, focus)


def render(scene, sensor, method: str, samples: int, depth: int, *, seed: int = 0, processes: int = 0,
           radius: float = 0.0, adaptive: bool = False, progress=None, cancelled=None) -> dict:
    """As pt_parallel.render; `processes` are threads here (0: all cores)."""
    out = _pt.render(scene, sensor, method, samples, depth, seed=seed, threads=processes, radius=radius,
                     adaptive=adaptive, progress=progress, cancelled=cancelled)
    out["processes"] = out["threads"]
    return out


def light_paths(scene, n: int, depth: int, seed: int = 0):
    return _pt.light_paths(scene, n, depth, seed)
