"""The Raytracer's block overview (python/plugins/raytracer/rtt_preview.py) draws blocks whose poses
name parameters of the system ({"param": "Z_L"}): the preview's system carries the source's
parameter rows and schema version. A system the installed raytatouille cannot read gives a clear
message. Exit code 77 (ctest: skipped) without numpy or raytatouille."""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "python" / "plugins" / "raytracer")]
try:
    import numpy  # noqa: F401
    import raytatouille  # noqa: F401
except ImportError as e:
    print(f"skipped: {e}")
    sys.exit(77)

import rtt_preview  # noqa: E402 - after the skip check

LENS = {"type": "lens", "name": "L", "pose": {"position": [0.0, 0.0, {"param": "Z_L"}]},
        "material": "CONST:1.5",
        "surfaces": [{"id": "L.1", "shape": {"base": {"type": "conic", "radius": 20.0}},
                      "aperture": {"type": "circular", "radius": 5.0}},
                     {"id": "L.2", "pose": {"position": [0.0, 0.0, 3.0]},
                      "shape": {"base": {"type": "conic", "radius": -20.0}},
                      "aperture": {"type": "circular", "radius": 5.0}}]}
SYSTEM = {"schema_version": "0.9.0", "name": "t", "units": {"length": "mm", "wavelength": "um"},
          "wavelengths": [{"um": 0.5876, "reference": True}],
          "parameters": [{"name": "Z_BASE", "value": 40.0}, {"name": "Z_L", "expression": "Z_BASE + 10"}]}


def model(system):
    source = {"id": "source", "type": "rtt.source",
              "params": {"rtt_system": system, "rtt_tree": {"/root": {"type": "assembly", "name": "root",
                                                                       "children": []}}}}
    lens = {"id": "L", "type": "rtt.section", "params": {"rtt": {"/root/children/0": LENS}}}
    return {"nodes": [source, lens]}, lens


failures = []

m, lens = model(SYSTEM)
r = rtt_preview.preview({"node": lens, "model": m})
if not r.get("ok"):
    failures.append(f"lens with a parameter pose: {r}")
else:
    zs = [p[0] for item in r["drawing"].get("items", []) if item.get("type") == "polygon"
          for p in item.get("points", [])]
    if not zs or not 49.0 < min(zs) < 51.0:
        failures.append(f"lens not at Z_L = 50: z from {min(zs, default=None)}")
r = rtt_preview.preview({"node": m["nodes"][0], "model": m})
if not r.get("ok"):
    failures.append(f"source overview: {r}")

newer = copy.deepcopy(SYSTEM)
newer["schema_version"] = "99.0.0"
m, lens = model(newer)
r = rtt_preview.preview({"node": lens, "model": m})
if r.get("ok") or "pip install -U raytatouille" not in str(r.get("error")):
    failures.append(f"newer schema: {r}")

for f in failures:
    print("FAIL", f)
print("ok" if not failures else f"{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
