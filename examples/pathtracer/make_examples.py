"""Example scenes for the Path Tracer plugin: writes them as documents (.rttf) next to this file
and, with --render, a colour preview (.png) of each – the plugin's *Camera image* per wavelength,
put together to colours here.

    python make_examples.py                 the documents
    python make_examples.py --render        and the previews (the plugin's Python: NumPy; fast
                                            only with the C++ kernel, package pathtracer)
    python make_examples.py --render --scale 0.5 prism      one scene, half the size, a quick look

Open a document in Raytatouille Fusion and choose *Camera image* in the Path Tracer panel:
materials, sources, camera and method are part of the document. Lengths in mm, +Z is up.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
W = math.sqrt(0.5)
CIRCLE = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0)]
CIRCLE_W = [1.0, W] * 4 + [1.0]
CIRCLE_KNOTS = [0, 0, 0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1, 1, 1]


# ------------------------------------------------------------------ geometry (docs/file-format.md)
def add(a, b, s=1.0):
    return tuple(x + s * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a):
    n = math.sqrt(sum(x * x for x in a))
    return tuple(x / n for x in a)


def rect(p0, du, dv) -> dict:
    """A flat face: a corner and two edges; its normal (the front) is du x dv."""
    pts = [p0, add(p0, dv), add(p0, du), add(add(p0, du), dv)]            # index = i_u * num_v + i_v
    return {"type": "surface", "degree_u": 1, "degree_v": 1, "knots_u": [0, 0, 1, 1], "knots_v": [0, 0, 1, 1],
            "num_u": 2, "num_v": 2, "points": [round(float(c), 9) for p in pts for c in p]}


def panel(centre, normal, width, height) -> dict:
    """A rectangle about `centre` whose front looks along `normal` (its width is horizontal)."""
    n = unit(normal)
    u = unit(cross((0, 0, 1), n)) if abs(n[2]) < 0.999 else (1.0, 0.0, 0.0)
    v = cross(n, u)
    return rect(add(add(centre, u, -0.5 * width), v, -0.5 * height), tuple(width * c for c in u),
                tuple(height * c for c in v))


def shell(faces: list[dict]) -> dict:
    return {"type": "shell", "faces": [f if "surface" in f else {"surface": f} for f in faces]}


def block(centre, size, height, angle=0.0, z0=0.0) -> dict:
    """A box standing on z0: centre (x, y), size (along its own x and y), turned by `angle` degrees."""
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    ex, ey, ez = (size[0] * c, size[0] * s, 0.0), (-size[1] * s, size[1] * c, 0.0), (0.0, 0.0, height)
    lo = add(add((centre[0], centre[1], z0), ex, -0.5), ey, -0.5)
    return shell([rect(lo, ey, ex), rect(add(lo, ez), ex, ey), rect(lo, ex, ez), rect(add(lo, ey), ez, ex),
                  rect(lo, ez, ey), rect(add(lo, ex), ey, ez)])           # normals outwards


def revolved(profile, weights, knots, centre) -> dict:
    """The surface of revolution of a profile of (distance from the axis, height) – a rational
    curve of degree 2 – about the vertical through `centre`: u along the profile, v around."""
    pts, wts = [], []
    for (r, z), w in zip(profile, weights):
        for (cx, cy), cw in zip(CIRCLE, CIRCLE_W):
            pts.append((centre[0] + r * cx, centre[1] + r * cy, centre[2] + z))
            wts.append(w * cw)
    return {"type": "surface", "degree_u": 2, "degree_v": 2, "knots_u": [float(k) for k in knots],
            "knots_v": [float(k) for k in CIRCLE_KNOTS], "num_u": len(profile), "num_v": 9,
            "points": [round(float(c), 9) for p in pts for c in p], "weights": [round(w, 12) for w in wts]}


def sphere(centre, radius) -> dict:
    """A ball as a body of one face: half a circle from pole to pole, revolved."""
    r = radius
    return shell([revolved([(0, -r), (r, -r), (r, 0), (r, r), (0, r)], [1, W, 1, W, 1],
                           [0, 0, 0, 0.5, 0.5, 1, 1, 1], centre)])


def torus(centre, major, minor) -> dict:
    """A ring lying flat as a body of one face: a circle of radius `minor`, revolved at `major`."""
    return shell([revolved([(major + minor * x, minor * y) for x, y in CIRCLE], CIRCLE_W, CIRCLE_KNOTS, centre)])


def tube(centre, radius, height) -> dict:
    """An open cylinder standing on `centre` (a thin band of metal)."""
    r, h = radius, 0.5 * height
    return revolved([(r, 0.0), (r, h), (r, height)], [1, 1, 1], [0, 0, 0, 1, 1, 1], centre)


def prism(corners, z0, z1) -> dict:
    """A body with the outline `corners` (x, y; counter-clockwise) from z0 to z1: flat sides, and
    two flat faces trimmed with the outline as bottom and top."""
    n = len(corners)
    sides = []
    for k in range(n):
        (x0, y0), (x1, y1) = corners[k], corners[(k + 1) % n]
        sides.append(rect((x0, y0, z0), (x1 - x0, y1 - y0, 0.0), (0.0, 0.0, z1 - z0)))     # normals outwards
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    lo, size = (min(xs), min(ys)), (max(xs) - min(xs), max(ys) - min(ys))
    loop = [((x - lo[0]) / size[0], (y - lo[1]) / size[1]) for x, y in corners]
    loop.append(loop[0])
    outline = {"degree": 1, "knots": [0.0] + [i / n for i in range(n + 1)] + [1.0],
               "points": [round(float(c), 9) for p in loop for c in (p[0], p[1], 0.0)]}
    caps = [{"surface": rect((lo[0], lo[1], z), (size[0], 0.0, 0.0), (0.0, size[1], 0.0)), "outer": [outline]}
            for z in (z0, z1)]
    return shell(sides + caps)


# ------------------------------------------------------------------ documents
def material(name: str, kind: str, **values) -> dict:
    row = {"name": name, "kind": kind, "reflectance": 0.8, "transmittance": 0.0, "roughness": 0.2, "ior": 1.5,
           "absorption": 0.0, "abbe": 0.0, "spectrum": ""}
    assert set(values) <= set(row), values
    return {**row, **values}


def source(name: str, flux: float, lines: str, half_angle: float = 90.0, side: str = "front") -> dict:
    return {"name": name, "flux": flux, "unit": "W", "half_angle": half_angle, "side": side, "spectrum": lines,
            "distribution": "", "axis": "0, 0, -1"}


def lines(first: float, last: float, count: int) -> list[float]:
    return [first + (last - first) * k / (count - 1) for k in range(count)]


def spectrum(nm: list[float]) -> str:
    return ", ".join(f"{v:g}" for v in nm)


class Scene:
    """A document in the making: objects with their material / source, and the panel's values."""

    def __init__(self, name: str, title: str, text: str):
        self.name, self.title, self.text = name, title, text
        self.entities, self.groups, self.params = [], [], {}
        self.materials, self.sources = [], []
        self.white = 99.0                  # preview: the luminance of this percentile becomes white
        self.nm: list[float] = []

    def group(self, name: str) -> int:
        self.groups.append({"id": len(self.groups) + 1, "name": name, "parent": 0, "visible": True})
        return len(self.groups)

    def add(self, name: str, geometry: dict, material_: str, colour: str = "#bec6d2", group: int = 0,
            source_: str = "") -> None:
        attributes = {"pt.material": material_}
        if source_:
            attributes["pt.source"] = source_
        self.entities.append({"id": str(len(self.entities) + 1), "name": name, "layer": 0, "visible": True,
                              "color": colour, "group": group, "attributes": attributes, "geometry": geometry})

    def camera(self, position, target, fov: float, width: int, height: int, lens: float = 0.0,
               focus: float = 0.0) -> None:
        self.params.update({"camera_position": list(map(float, position)), "camera_target": list(map(float, target)),
                            "camera_up": "+Z", "camera_fov": fov, "camera_width": width, "camera_height": height,
                            "camera_lens": lens, "camera_focus": focus})

    def compute(self, method: str, per_pixel: int, depth: int) -> None:
        pixels = self.params["camera_width"] * self.params["camera_height"]
        self.params.update({"method": method, "samples": pixels * per_pixel, "depth": depth, "kernel": "automatic",
                            "per_wavelength": True, "adaptive": True, "seed": 1})

    def document(self) -> dict:
        used = {e["attributes"]["pt.material"] for e in self.entities}
        assert used <= {m["name"] for m in self.materials}, used
        params = {"materials": self.materials, "default_material": self.materials[0]["name"],
                  "assign_material": self.materials[0]["name"], "sources": self.sources,
                  "assign_source": self.sources[0]["name"], **self.params}
        return {"format": "nfcad", "version": 2, "units": "mm",
                "layers": [{"id": 0, "name": "Default", "color": "#bec6d2", "visible": True}],
                "groups": self.groups, "entities": self.entities, "plugins": {"pathtracer": {"params": params}}}


# ------------------------------------------------------------------ the scenes
def cornell_box() -> Scene:
    s = Scene("cornell-box", "Cornell box",
              "A room of 550 mm with a red and a green wall, a lamp in the ceiling, a block and a ball of glass: "
              "the walls colour the light they pass on, the ball throws a caustic. Bidirectional.")
    s.nm = lines(450.0, 650.0, 5)
    s.materials = [material("white", "diffuse", reflectance=0.75),
                   material("red", "diffuse", spectrum="450:0.04, 550:0.06, 600:0.45, 650:0.7"),
                   material("green", "diffuse", spectrum="450:0.06, 500:0.3, 550:0.55, 600:0.15, 650:0.06"),
                   material("glass", "glass", ior=1.5),
                   material("lamp", "diffuse", reflectance=0.8)]
    s.sources = [source("lamp", 40.0, spectrum(s.nm))]
    room = s.group("Room")
    a = 550.0
    s.add("Floor", rect((0, 0, 0), (a, 0, 0), (0, a, 0)), "white", "#d9d9d9", room)
    s.add("Ceiling", rect((0, 0, a), (0, a, 0), (a, 0, 0)), "white", "#d9d9d9", room)
    s.add("Back wall", rect((0, a, 0), (a, 0, 0), (0, 0, a)), "white", "#d9d9d9", room)
    s.add("Left wall", rect((0, 0, 0), (0, a, 0), (0, 0, a)), "red", "#c0392b", room)
    s.add("Right wall", rect((a, 0, 0), (0, 0, a), (0, a, 0)), "green", "#27ae60", room)
    s.add("Lamp", rect((210, 220, a - 0.5), (0, 110, 0), (130, 0, 0)), "lamp", "#fff3b0", room, "lamp")
    s.add("Block", block((185, 360), (165, 165), 330, 17.0, 0.0), "white", "#d9d9d9")
    s.add("Glass ball", sphere((380, 215, 96), 95), "glass", "#9fd3e6")
    s.camera((275, -760, 275), (275, 0, 275), 39.5, 400, 400)
    s.compute("bidirectional", 128, 12)
    return s


def caustics() -> Scene:
    s = Scene("caustics", "Caustics",
              "A spot on a table: a ball of strongly dispersing glass, a ring of blue glass and a band of polished "
              "gold. The ball gathers the light into a bright spot with coloured rims, the ring into blue figures, "
              "the band into the heart-shaped curve of a coffee cup. Bidirectional.")
    s.nm = lines(430.0, 670.0, 7)
    s.materials = [material("table", "diffuse", reflectance=0.8),
                   material("dispersing glass", "glass", ior=1.5, abbe=28.0),
                   material("blue glass", "glass", ior=1.6, abbe=36.0,
                            spectrum="430:0.002, 470:0.001, 510:0.006, 550:0.018, 590:0.03, 630:0.04, 670:0.045"),
                   material("gold", "mirror", spectrum="430:0.36, 470:0.4, 510:0.6, 550:0.82, 590:0.9, 630:0.95, 670:0.96"),
                   material("black", "absorber")]
    s.sources = [source("spot", 10.0, spectrum(s.nm), half_angle=24.0),
                 source("room", 4.0, spectrum(s.nm))]
    s.add("Table", rect((-600, -600, 0), (1200, 0, 0), (0, 1200, 0)), "table", "#d9d9d9")
    eye = (-390.0, 410.0, 400.0)                               # the spot looks at the middle from 35° above the table
    s.add("Spot", panel(eye, add((0, 0, 0), eye, -1.0), 16, 16), "black", "#fff3b0", 0, "spot")
    s.add("Glass ball", sphere((20, 80, 70.5), 70), "dispersing glass", "#9fd3e6")
    s.add("Glass ring", torus((170, -75, 22.5), 62, 22), "blue glass", "#5d8fd6")
    s.add("Gold band", tube((-145, -85, 0.2), 85, 60), "gold", "#d4af37")
    s.add("Room light", rect((-150, -150, 900), (0, 300, 0), (300, 0, 0)), "black", "#fff3b0", 0, "room")
    s.camera((130, -760, 520), (10, -50, 0), 40.0, 480, 320)
    s.compute("bidirectional", 160, 12)
    s.white = 99.8
    return s


def prism_scene() -> Scene:
    s = Scene("prism", "Prism",
              "A thin sheet of white light grazes a table and meets a prism of heavy flint glass at the angle of "
              "least deviation: the colours leave it as a fan, 31 wavelengths from 400 to 700 nm; part of the light "
              "is reflected at the faces. Bidirectional.")
    s.nm = lines(400.0, 700.0, 31)
    s.materials = [material("table", "diffuse", reflectance=0.8),
                   material("SF11", "glass", ior=1.785, abbe=25.7),
                   material("black", "absorber")]
    index = 1.785
    side, height, tilt = 90.0, 44.0, 3.0
    half = math.degrees(math.asin(index * 0.5))                # angle of incidence at least deviation (60° prism)
    heading = half - 30.0                                      # of the beam, from +X; the left face looks along 150°
    apex = side * math.sqrt(0.75)
    corners = [(-0.5 * side, -apex / 3.0), (0.5 * side, -apex / 3.0), (0.0, 2.0 * apex / 3.0)]
    c, sn = math.cos(math.radians(heading)), math.sin(math.radians(heading))
    t = math.radians(tilt)
    beam = (c * math.cos(t), sn * math.cos(t), -math.sin(t))
    hit = (-0.25 * side, apex / 6.0)                           # the middle of the left face
    back = 330.0
    slit = (hit[0] - back * c, hit[1] - back * sn, 22.0)
    s.sources = [source("slit", 1.0, spectrum(s.nm), half_angle=0.25),
                 source("room", 10.0, spectrum(s.nm))]
    s.add("Table", rect((-700, -700, 0), (1700, 0, 0), (0, 1300, 0)), "table", "#d9d9d9")
    s.add("Prism", prism(corners, 0.2, height), "SF11", "#9fd3e6")
    s.add("Slit", panel(slit, beam, 1.2, 40.0), "black", "#fff3b0", 0, "slit")
    s.add("Room light", rect((-50, -250, 900), (0, 300, 0), (300, 0, 0)), "black", "#fff3b0", 0, "room")
    s.camera((190, -640, 780), (165, -125, 0), 46.0, 540, 360)
    s.compute("bidirectional", 120, 12)
    s.white = 99.7
    return s


def depth_of_field() -> Scene:
    s = Scene("depth-of-field", "Materials and depth of field",
              "Five balls on a chequered floor under a soft light – red paint, brushed gold, glass, a mirror and "
              "frosted blue glass – seen by a camera with a lens of 14 mm radius that is sharp on the glass ball. "
              "Path tracing.")
    s.nm = lines(450.0, 650.0, 5)
    s.materials = [material("light tile", "diffuse", reflectance=0.75),
                   material("dark tile", "diffuse", reflectance=0.2),
                   material("wall", "diffuse", reflectance=0.6),
                   material("red paint", "glossy", roughness=0.25,
                            spectrum="450:0.05, 550:0.07, 600:0.5, 650:0.75"),
                   material("gold", "metal", roughness=0.3, spectrum="450:0.35, 500:0.5, 550:0.8, 600:0.92, 650:0.96"),
                   material("glass", "glass", ior=1.5),
                   material("mirror", "mirror", reflectance=0.95),
                   material("blue frosted", "frosted", ior=1.5, roughness=0.35,
                            spectrum="450:0.0005, 500:0.002, 550:0.008, 600:0.016, 650:0.02"),
                   material("softbox", "absorber")]
    s.sources = [source("softbox", 60.0, spectrum(s.nm))]
    floor = s.group("Floor")
    tile, n = 80.0, 12
    for i in range(n):
        for j in range(n):
            dark = (i + j) % 2 == 0
            s.add(f"Tile {i + 1}.{j + 1}", rect(((i - n / 2) * tile, (j - 4) * tile, 0), (tile, 0, 0), (0, tile, 0)),
                  "dark tile" if dark else "light tile", "#555555" if dark else "#d9d9d9", floor)
    s.add("Wall", rect((-480, 640, 0), (960, 0, 0), (0, 0, 500)), "wall", "#d9d9d9")
    s.add("Softbox", panel((-250, 150, 560), (0.35, -0.1, -1.0), 520, 420), "softbox", "#fff3b0", 0, "softbox")
    balls = s.group("Balls")
    names = [("Red ball", "red paint", "#c0392b"), ("Gold ball", "gold", "#d4af37"), ("Glass ball", "glass", "#9fd3e6"),
             ("Mirror ball", "mirror", "#c9ccd1"), ("Frosted ball", "blue frosted", "#5d8fd6")]
    r = 45.0
    for k, (name, mat, colour) in enumerate(names):
        s.add(name, sphere((-125 + 80 * k, -130 + 120 * k, r + 0.5), r), mat, colour, balls)
    s.camera((-40, -700, 190), (10, 110, 45), 34.0, 480, 320, lens=14.0, focus=0.0)
    s.compute("path tracing", 160, 12)
    return s


SCENES = [cornell_box, caustics, prism_scene, depth_of_field]


# ------------------------------------------------------------------ previews
def colour_of(nm: float) -> tuple[float, float, float]:
    """Linear sRGB of light of one wavelength with unit power: the CIE 1931 observer in the fit of
    Wyman, Sloan and Shirley (JCGT 2 (2013) 1), then XYZ to sRGB (may be negative: outside sRGB)."""
    def lobe(mu: float, s1: float, s2: float) -> float:
        return math.exp(-0.5 * ((nm - mu) / (s1 if nm < mu else s2)) ** 2)

    x = 1.056 * lobe(599.8, 37.9, 31.0) + 0.362 * lobe(442.0, 16.0, 26.7) - 0.065 * lobe(501.1, 20.4, 26.2)
    y = 0.821 * lobe(568.8, 46.9, 40.5) + 0.286 * lobe(530.9, 16.3, 31.1)
    z = 1.217 * lobe(437.0, 11.8, 36.0) + 0.681 * lobe(459.0, 26.0, 13.8)
    return (3.2406 * x - 1.5372 * y - 0.4986 * z, -0.9689 * x + 1.8758 * y + 0.0415 * z,
            0.0557 * x - 0.2040 * y + 1.0570 * z)


def write_png(path: Path, rgb) -> None:
    """rgb: (height, width, 3) of uint8, row 0 on top."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[j].tobytes() for j in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def develop(channels, nm: list[float], white: float):
    """The images of the wavelengths (count, height, width; row 0 at the bottom) as sRGB bytes:
    each wavelength in its colour, equal power on all of them is white, the luminance of the
    percentile `white` the brightest value; above it the colours run softly into white."""
    import numpy as np

    table = np.array([colour_of(v) for v in nm])
    table /= table.sum(axis=0)                                  # equal power on every line: (1, 1, 1)
    rgb = np.maximum(np.tensordot(channels, table, axes=(0, 0)), 0.0)        # (height, width, 3)
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722])
    lit = lum[lum > 0]
    rgb /= float(np.percentile(lit, white)) if lit.size else 1.0
    peak = rgb.max(axis=2, keepdims=True)
    over = np.maximum(peak - 1.0, 0.0)
    rgb = np.where(peak > 1.0, rgb / np.maximum(peak, 1e-30) + (1.0 - rgb / np.maximum(peak, 1e-30))
                   * (1.0 - np.exp(-0.5 * over)), rgb)          # brighter than white: towards white
    rgb = np.clip(rgb, 0.0, 1.0)
    rgb = np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - 0.055)
    return (rgb[::-1] * 255.0 + 0.5).astype(np.uint8)


class Host:
    """Plays the application for the plugin's action: hands out the document's objects and keeps
    the images."""

    def __init__(self, document: dict):
        self.entities = [{"id": int(e["id"]), "name": e["name"], "group": e["group"], "attributes": e["attributes"],
                          "geometry": e["geometry"]} for e in document["entities"]]
        self.images, self.last = [], 0.0

    def send(self, message: dict) -> None:
        if message.get("type") == "log":
            print("   ", message["text"])
        elif message.get("type") == "progress" and time.time() - self.last > 20.0:
            self.last = time.time()
            print(f"    … {100.0 * message['value']:.0f} %", flush=True)

    def request(self, method: str, args: dict):
        import numpy as np

        if method == "model.entities":
            return self.entities
        if method == "results.create_set":
            return 1
        if method == "results.image":
            file = Path(args["values"]["file"])
            self.images.append((args["name"], np.fromfile(file, dtype="<f4").reshape(args["height"], args["width"])))
            file.unlink()
            return len(self.images)
        raise RuntimeError(f"unexpected request {method}")


def render(scene: Scene, scale: float, quality: float):
    """The plugin's Camera image of the scene's document: the images per wavelength and the time."""
    import numpy as np

    for folder in (ROOT / "python", ROOT / "python" / "plugins" / "pathtracer"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    import pathtracer_plugin
    import pt_native
    from nfcad import Context

    document = json.loads(json.dumps(scene.document()))
    raw = document["plugins"]["pathtracer"]["params"]
    raw["camera_width"] = max(8, round(raw["camera_width"] * scale))
    raw["camera_height"] = max(8, round(raw["camera_height"] * scale))
    raw["samples"] = max(1000, round(raw["samples"] * scale * scale * quality))
    if not pt_native.available():
        print("    the C++ kernel (package pathtracer) is not installed: the NumPy kernel takes very long for "
              "this – use --scale and --quality")
    plugin = pathtracer_plugin.PathTracerPlugin()
    host = Host(document)
    start = time.time()
    plugin.camera_image(Context(host, 1, plugin.convert_params(raw), []))
    per_line = [(float(m.group(1)), image) for name, image in host.images[1:]
                if (m := re.search(r" ([0-9.]+) nm ", name))]
    if not per_line:                                            # one wavelength: its image alone
        per_line = [(scene.nm[0], host.images[0][1])]
    return [v for v, _ in per_line], np.stack([image for _, image in per_line]), time.time() - start


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("names", nargs="*", help="scenes (default: all): " + ", ".join(f().name for f in SCENES))
    parser.add_argument("--render", action="store_true", help="also compute the colour previews (.png)")
    parser.add_argument("--scale", type=float, default=1.0, help="size of the previews against the documents'")
    parser.add_argument("--quality", type=float, default=1.0, help="samples per pixel against the documents'")
    parser.add_argument("--out", type=Path, default=HERE, help="folder for the files")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for make in SCENES:
        scene = make()
        if args.names and scene.name not in args.names:
            continue
        document = scene.document()
        path = args.out / f"{scene.name}.rttf"
        path.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"{path.name}: {len(document['entities'])} objects, {len(scene.nm)} wavelengths")
        if args.render:
            nm, channels, seconds = render(scene, args.scale, args.quality)
            write_png(args.out / f"{scene.name}.png", develop(channels, nm, scene.white))
            print(f"    {scene.name}.png: {channels.shape[2]} x {channels.shape[1]} in {seconds:.0f} s")


if __name__ == "__main__":
    main()
