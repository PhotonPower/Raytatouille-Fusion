"""The Raytracer draws the system of a node workflow from its model (version 2) – the same surfaces
as the system it was made from. An old socket graph (version 1, `workflow.graph`) is not read
any more: CAD converts it into a model when it opens the document (Workflow plugin, Convert to
model). Exit code 77 (ctest: skipped) without numpy, raytatouille or rtt_fusion."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "python" / "plugins" / "raytracer")]
try:
    import numpy  # noqa: F401
    import raytatouille as rt
    from rtt_fusion.graph import graph_from_raytatouille, io, model_from_raytatouille
except ImportError as e:
    print(f"skipped: {e}")
    sys.exit(77)

import raytracer_plugin  # noqa: E402 - after the skip check

SYSTEM = ROOT / "python" / "plugins" / "raytracer" / "examples" / "singlet_optim.rtt.json"


class Ctx:
    def __init__(self, workflow):
        self._wf = workflow
        self.params = {"system": "", "catalogs": []}

    def workflow(self):
        return self._wf

    def log(self, *args):
        pass


def plugin():
    cls = next(v for k, v in vars(raytracer_plugin).items()
               if isinstance(v, type) and k.endswith("Plugin") and hasattr(v, "_workflow_system"))
    return cls()


def surfaces(system) -> list:
    return [L.id for L in rt.layout.surfaces(rt.compile(system, rt.MaterialLibrary()))]


failures = []
d = json.loads(SYSTEM.read_text(encoding="utf-8"))
system = rt.System.from_json(json.dumps(d))
expected = surfaces(system)

model = io.model_to_dict(model_from_raytatouille(system))
made = plugin()._workflow_system(Ctx({"model": model}))
if made is None:
    failures.append("no system from a workflow model")
elif surfaces(made[0]) != expected:
    failures.append(f"surfaces {surfaces(made[0])} != {expected}")

# an actuator (RTT-Fusion fusion.actuator) sets a system parameter: the drawing shows the stage
# where it stands, and a new value draws again
try:
    import rtt_fusion.graph.actuator  # noqa: F401
except ImportError:
    print("actuators skipped: rtt_fusion without fusion.actuator")
else:
    with_parameter = {**d, "parameters": [{"name": "T", "value": 1.0, "variable": True, "min": 0, "max": 10}]}
    model = io.model_to_dict(model_from_raytatouille(rt.System.from_json(json.dumps(with_parameter))))
    model["nodes"].append({"id": "stage", "type": "fusion.actuator", "params": {"value": 2.5, "parameter": "T"}})
    engine = plugin()

    def value_of_t(made) -> float:
        return next(p["value"] for p in json.loads(made[0].to_json())["parameters"] if p["name"] == "T")

    first = engine._workflow_system(Ctx({"model": model}))
    if first is None or value_of_t(first) != 2.5:
        failures.append(f"actuator not in the drawn system: {first and value_of_t(first)}")
    model["nodes"][-1]["params"]["value"] = 4.0
    again = engine._workflow_system(Ctx({"model": model}))
    if again is None or again is first or value_of_t(again) != 4.0:
        failures.append("a new value of the actuator is not drawn")

# a block of another kind on a plane (a grating added in the workflow, no Raytatouille surface): its
# plane is drawn where it lies, its offset (an actuator's move) applied
import rtt_nurbs  # noqa: E402
from rtt_fusion import graph as fusion_graph  # noqa: E402

model = io.model_to_dict(model_from_raytatouille(system))
model["nodes"].append({"id": "plate", "type": "fg.grating",
                       "params": {"point": [0, 0, 5], "normal": [0, 0, 1], "pose_by_stage": [0, 0, 1, 0, 0, 0]}})
engine = plugin()
registry, _ = engine._registry(fusion_graph)
planes = engine._block_planes(fusion_graph, io.model_from_dict(model, registry), registry)
if [(n, [round(x, 9) for x in p], q) for n, p, q in planes] != [("plate", [0.0, 0.0, 6.0], [0.0, 0.0, 1.0])]:
    failures.append(f"planes of blocks without a surface: {planes}")
disc = rtt_nurbs.plane_disc([0, 0, 6], [0, 0, 1], 2.0, "plate")
corners = [disc["surface"]["points"][i:i + 3] for i in range(0, 12, 3)]
if {c[2] for c in corners} != {6.0} or disc["outer"][0]["points"][0] != 2.0:
    failures.append(f"a block's plane as a disc: {corners}")

graph = io.to_dict(graph_from_raytatouille(d))  # version 1: converted on opening, not read here
if plugin()._workflow_system(Ctx({"graph": graph})) is not None:
    failures.append("a system from an old socket graph (version 1)")
if plugin()._workflow_system(Ctx({})) is not None:
    failures.append("a system from an empty workflow")

# rays through the gratings of a workflow (RTT-Fusion graph.ray_paths): pieces of polylines per ray,
# NaN where a ray is lost or has no point in front, become one line set per branch
from types import SimpleNamespace  # noqa: E402

nan = float("nan")
pieces = [
    SimpleNamespace(path=("Belichtung", "L"), field=0, wavelength_um=0.633,
                    points=[[[0, 0, 0], [0, 0, 5]], [[1, 0, 0], [nan, nan, nan]]]),  # the second ray lost
    SimpleNamespace(path=("Belichtung", "L", "G[1]", "M"), field=0, wavelength_um=0.633,
                    points=[[[0, 0, 5], [0, 0, 9], [0, 1, 20]]]),
    SimpleNamespace(path=("Sensor", "L"), field=1, wavelength_um=0.633, points=[[[nan, nan, nan], [0, 0, 1], [0, 0, 2]]]),
    SimpleNamespace(path=("Belichtung", "L"), field=0, wavelength_um=0.5, points=[[[0, 0, 0], [0, 0, 5]]]),
]
sets = raytracer_plugin.workflow_lines(pieces, "path", wavelength_um=0.633)
points, starts, values = sets["Belichtung"]
if list(starts) != [0, 2, 5] or points.shape != (5, 3) or set(values) != {1.0}:
    failures.append(f"workflow lines of a branch: starts {list(starts)}, {points.shape}, {set(values)}")
points, starts, values = sets["Sensor"]
if list(starts) != [0, 2] or float(values[0]) != 2.0:  # the leading NaN dropped; the second branch
    failures.append(f"workflow lines: a ray without a point in front: {list(starts)}, {values}")
by_field = raytracer_plugin.workflow_lines(pieces, "field", field=1)
if list(by_field) != ["Sensor"] or float(by_field["Sensor"][2][0]) != 2.0:
    failures.append(f"workflow lines of one field: {list(by_field)}")
if len(raytracer_plugin.workflow_lines(pieces, "wavelength", branches=["Sensor"])) != 1:
    failures.append("workflow lines of one branch")

for f in failures:
    print("FAIL", f)
print("ok" if not failures else f"{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
