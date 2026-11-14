"""From the CAD model and the panel to a scene, and from the estimates to results – without CAD:
entities are the dicts of `ctx.entities()`, params the values of the panel."""

from __future__ import annotations

import hashlib
import json

import numpy as np

import pt_bsdf
import pt_mesh
import pt_nurbs
import pt_scene

MATERIAL = "pt.material"        # attribute of an object: name of a material of the panel
SOURCE = "pt.source"            # attribute of an object: name of a source of the panel
INACTIVE = "sim.inactive"       # attribute: the object takes no part (docs/plugins.md, D11)

METHODS = {"light tracing": "light", "path tracing": "path", "bidirectional": "bidir", "photon mapping": "photon"}
UP = {"+Z": (0, 0, 1), "-Z": (0, 0, -1), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+X": (1, 0, 0), "-X": (-1, 0, 0)}

DEFAULT_MATERIALS = [
    {"name": "white", "kind": "diffuse", "reflectance": 0.8, "transmittance": 0.0, "roughness": 0.2, "ior": 1.5,
     "absorption": 0.0, "abbe": 0.0, "spectrum": ""},
    {"name": "black", "kind": "absorber", "reflectance": 0.0, "transmittance": 0.0, "roughness": 0.2, "ior": 1.5,
     "absorption": 0.0, "abbe": 0.0, "spectrum": ""},
    {"name": "mirror", "kind": "mirror", "reflectance": 0.95, "transmittance": 0.0, "roughness": 0.2, "ior": 1.5,
     "absorption": 0.0, "abbe": 0.0, "spectrum": ""},
    {"name": "metal", "kind": "glossy", "reflectance": 0.85, "transmittance": 0.0, "roughness": 0.2, "ior": 1.5,
     "absorption": 0.0, "abbe": 0.0, "spectrum": ""},
    {"name": "glass", "kind": "glass", "reflectance": 0.0, "transmittance": 0.0, "roughness": 0.2, "ior": 1.5,
     "absorption": 0.0, "abbe": 0.0, "spectrum": ""},
    {"name": "diffuser", "kind": "diffuse", "reflectance": 0.3, "transmittance": 0.6, "roughness": 0.2, "ior": 1.5,
     "absorption": 0.0, "abbe": 0.0, "spectrum": ""},
    {"name": "BK7", "kind": "glass", "reflectance": 0.0, "transmittance": 0.0, "roughness": 0.2, "ior": 1.5168,
     "absorption": 0.0, "abbe": 64.17, "spectrum": ""},
    {"name": "red paint", "kind": "diffuse", "reflectance": 0.5, "transmittance": 0.0, "roughness": 0.2, "ior": 1.5,
     "absorption": 0.0, "abbe": 0.0, "spectrum": "450:0.05, 550:0.1, 600:0.6, 650:0.8"},
    {"name": "detector", "kind": "detector", "reflectance": 0.0, "transmittance": 0.0, "roughness": 0.2, "ior": 1.5,
     "absorption": 0.0, "abbe": 0.0, "spectrum": ""},
]
DEFAULT_SOURCES = [{"name": "lamp", "flux": 1.0, "half_angle": 90.0, "side": "front", "spectrum": "550"}]


def parse_values(text) -> tuple:
    """Values at wavelengths from text: "450:0.2, 550:0.8, 650:0.9" -> ((450, 0.2), …); empty: ().
    ValueError for anything else."""
    pairs = []
    for part in str(text or "").replace(";", ",").split(","):
        if not part.strip():
            continue
        nm, colon, value = part.partition(":")
        try:
            if not colon:
                raise ValueError
            pairs.append((float(nm), float(value)))
        except ValueError:
            raise ValueError(f"spectrum {text!r}: write values at wavelengths in nm, e.g. "
                             f"\"450:0.2, 550:0.8, 650:0.9\"") from None
    return tuple(pairs)


def parse_spectrum(text) -> tuple:
    """The lines of a source from text: wavelengths in nm, separated by commas, each with an
    optional share of the flux after a colon – "550", "486.1, 587.6, 656.3", "450:1, 550:2".
    Empty: 550 nm. ValueError for anything else."""
    lines = []
    for part in str(text or "").replace(";", ",").split(","):
        if not part.strip():
            continue
        nm, _, share = part.partition(":")
        try:
            lines.append((float(nm), float(share) if share.strip() else 1.0))
        except ValueError:
            raise ValueError(f"spectrum {text!r}: write wavelengths in nm, e.g. \"450:1, 550:2, 650:1\"") from None
    return tuple(lines) or ((550.0, 1.0),)


def label(entity: dict) -> str:
    return str(entity.get("name") or f"object {entity.get('id')}")


def _kind(entity: dict) -> str:
    return str((entity.get("geometry") or {}).get("type", ""))


def _attr(entity: dict, key: str) -> str:
    value = (entity.get("attributes") or {}).get(key)
    return "" if value is None else str(value).strip()


def active(entities: list[dict]) -> list[dict]:
    return [e for e in entities if not (e.get("attributes") or {}).get(INACTIVE)]


def surfaces(entities: list[dict]) -> list[dict]:
    """The objects that are traced: active surfaces, trimmed surfaces and shells."""
    return [e for e in active(entities) if _kind(e) in pt_mesh.SURFACE_KINDS]


def assignments(entities: list[dict], params: dict) -> list[list]:
    """Rows object, kind, material, source for the active objects that take part."""
    rows = []
    for e in active(entities):
        kind = _kind(e)
        if kind in pt_mesh.SURFACE_KINDS:
            rows.append([label(e), kind, _attr(e, MATERIAL) or f"({params['default_material']})", _attr(e, SOURCE)])
        elif kind in ("point", "curve") and _attr(e, SOURCE):
            rows.append([label(e), kind, "", _attr(e, SOURCE)])
    return rows


def polyline(curve: dict) -> np.ndarray:
    """Points along a curve dict, close enough for a wire source (32 per knot span; the corners
    of a polyline exactly)."""
    degree = int(curve["degree"])
    spans = pt_nurbs.distinct_knots(degree, curve["knots"])
    if degree > 1:
        spans = np.unique(np.concatenate([np.linspace(a, b, 33) for a, b in zip(spans[:-1], spans[1:])]))
    return pt_nurbs.curve_points(curve, spans)


class MeshCache:
    """Keeps the mesh of the last model: tessellation is repeated only when the geometry or the
    tolerance changed."""

    def __init__(self):
        self.key = None
        self.mesh = None

    def get(self, entities: list[dict], tol: float) -> pt_mesh.Mesh:
        digest = hashlib.sha1()
        digest.update(repr(float(tol)).encode())
        for e in entities:
            digest.update(json.dumps([e.get("id"), e.get("geometry")], sort_keys=True).encode())
        key = digest.hexdigest()
        if key != self.key:
            self.mesh = pt_mesh.build(entities, tol)
            self.key = key
        return self.mesh


def build_scene(entities: list[dict], params: dict, cache: MeshCache | None = None) -> pt_scene.Scene:
    """The scene of the model: materials and sources of the panel, assigned by the attributes
    pt.material and pt.source. ValueError with a message for the user when something is missing."""
    materials = pt_bsdf.Materials.from_rows([{**row, "spectrum": parse_values(row.get("spectrum", ""))}
                                             for row in params["materials"]])
    default = str(params.get("default_material", "")).strip()
    if default not in materials.names:
        raise ValueError(f"the default material {default!r} is not in the table of materials")
    surf = surfaces(entities)
    if not surf:
        raise ValueError("the model has no surfaces or bodies to trace")
    entity_material = []
    for e in surf:
        name = _attr(e, MATERIAL) or default
        if name not in materials.names:
            raise ValueError(f"{label(e)}: its material {name!r} is not in the table of materials")
        entity_material.append(materials.names.index(name))
    names = [str(row.get("name", "")).strip() for row in params["sources"]]
    if len(set(names)) != len(names) or "" in names:
        raise ValueError("sources need different, non-empty names")
    for e in active(entities):
        if _attr(e, SOURCE) and _attr(e, SOURCE) not in names:
            raise ValueError(f"{label(e)}: its source {_attr(e, SOURCE)!r} is not in the table of sources")
    specs = []
    for row, name in zip(params["sources"], names):
        on = tuple(k for k, e in enumerate(surf) if _attr(e, SOURCE) == name)
        points = tuple(tuple(e["geometry"]["point"]) for e in active(entities)
                       if _kind(e) == "point" and _attr(e, SOURCE) == name)
        curves = tuple(polyline(e["geometry"]) for e in active(entities)
                       if _kind(e) == "curve" and _attr(e, SOURCE) == name)
        specs.append(pt_scene.SourceSpec(name, float(row.get("flux", 0.0)), float(row.get("half_angle", 90.0)),
                                         str(row.get("side", "front")), on, points, curves,
                                         parse_spectrum(row.get("spectrum", ""))))
    if not any(s.entities or s.points or s.curves for s in specs):
        raise ValueError("no object is a source: select a surface, a body, a curve or a point and choose "
                         "\"Selection: make it a source\"")
    tol = float(params.get("tolerance", 0.01))
    mesh = cache.get(surf, tol) if cache is not None else pt_mesh.build(surf, tol)
    closed = tuple(k for k, e in enumerate(surf) if _kind(e) == "shell")
    return pt_scene.Scene(mesh, materials, np.asarray(entity_material), specs, closed)


def sensor_faces(scene: pt_scene.Scene, ids) -> list[int]:
    """Faces of the mesh that belong to the objects `ids` (empty: all faces)."""
    mesh = scene.mesh
    if not ids:
        return list(range(len(mesh.face_area)))
    wanted = {int(i) for i in ids}
    faces = [f for f in range(len(mesh.face_area)) if mesh.entity_ids[mesh.face_entity[f]] in wanted]
    if not faces:
        raise ValueError("the objects chosen for the irradiance are not surfaces of the model (or inactive)")
    return faces


def irradiance(sensor: pt_scene.TexelSensor, flux: np.ndarray, error: np.ndarray | None = None) -> list[dict]:
    """Per sensor face: entity (id), face (number within the entity), w, h, values (irradiance in
    W/m², row by row, NaN where the face has no or hardly any area in a texel), flux / W,
    area / mm² and – with the standard error of the flux per texel – noise: the relative
    standard error of the face's flux (NaN if unknown)."""
    mesh = sensor.scene.mesh
    out = []
    for k, f in enumerate(sensor.faces):
        a, b = sensor.first[k], sensor.first[k + 1]
        area = sensor.texel_area[a:b]
        full = np.median(area[area > 0]) if (area > 0).any() else 0.0
        with np.errstate(divide="ignore", invalid="ignore"):
            values = np.where(area > 0.1 * full, flux[a:b] / area * 1e6, np.nan)
        out.append({"entity": mesh.entity_ids[mesh.face_entity[f]], "face": int(mesh.face_index[f]),
                    "w": int(sensor.w[k]), "h": int(sensor.h[k]), "values": values,
                    "flux": float(flux[a:b].sum()), "area": float(mesh.face_area[f]),
                    "noise": float(np.sqrt((error[a:b] ** 2).sum()) / flux[a:b].sum())
                    if error is not None and flux[a:b].sum() > 0 else float("nan")})
    return out


def typical_noise(values: np.ndarray, error: np.ndarray | None) -> float:
    """The relative standard error of a typical texel or pixel: the median over those that got
    light (NaN if unknown)."""
    if error is None or not (values > 0).any():
        return float("nan")
    return float(np.median(error[values > 0] / values[values > 0]))


def tagged(path: str, tag: str) -> str:
    """file.npz -> file-<tag>.npz (the extension added if missing)."""
    stem = path[:-4] if path.lower().endswith(".npz") else path
    return f"{stem}-{tag}.npz"


def export_irradiance(path: str, sensor: pt_scene.TexelSensor, out: dict, names: dict, info: dict) -> str:
    """Writes the irradiance as a NumPy archive: per face `E_<entity>_<face>` (W/m², [row v,
    column u]), `flux_…` (W per texel) and `error_…` (standard error of the flux); with several
    wavelengths `flux_…_<nm>nm`; `wavelengths` and `info` (JSON: the run and the faces)."""
    arrays: dict[str, np.ndarray] = {"wavelengths": np.asarray(sensor.scene.wavelengths)}
    faces = []
    several = len(sensor.scene.wavelengths) > 1
    for k, f in enumerate(irradiance(sensor, out["values"], out.get("error"))):
        a, b, shape = sensor.first[k], sensor.first[k + 1], (f["h"], f["w"])
        key = f"{f['entity']}_{f['face']}"
        arrays[f"E_{key}"] = f["values"].reshape(shape)
        arrays[f"flux_{key}"] = out["values"][a:b].reshape(shape)
        if out.get("error") is not None:
            arrays[f"error_{key}"] = out["error"][a:b].reshape(shape)
        if several:
            for nm, channel in zip(sensor.scene.wavelengths, out["channels"]):
                arrays[f"flux_{key}_{nm:g}nm"] = channel[a:b].reshape(shape)
        faces.append({"key": key, "name": names.get(f["entity"], str(f["entity"])), "entity": f["entity"],
                      "face": f["face"], "area_mm2": f["area"], "flux_W": f["flux"]})
    arrays["info"] = np.asarray(json.dumps({**info, "faces": faces}))
    path = tagged(path, "irradiance")
    np.savez_compressed(path, **arrays)
    return path


def export_image(path: str, camera: pt_scene.Camera, out: dict, info: dict) -> str:
    """Writes a camera image as a NumPy archive: `radiance` (W/(m² sr), [row from the bottom,
    column]), `error` (its standard error), `radiance_per_wavelength` [wavelength, row, column],
    `wavelengths` and `info` (JSON)."""
    shape = (camera.h, camera.w)
    arrays = {"radiance": out["values"].reshape(shape) * 1e6,
              "radiance_per_wavelength": out["channels"].reshape((-1,) + shape) * 1e6,
              "wavelengths": np.asarray(info.get("wavelengths", [])), "info": np.asarray(json.dumps(info))}
    if out.get("error") is not None:
        arrays["error"] = out["error"].reshape(shape) * 1e6
    path = tagged(path, "camera")
    np.savez_compressed(path, **arrays)
    return path
