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

graph = io.to_dict(graph_from_raytatouille(d))  # version 1: converted on opening, not read here
if plugin()._workflow_system(Ctx({"graph": graph})) is not None:
    failures.append("a system from an old socket graph (version 1)")
if plugin()._workflow_system(Ctx({})) is not None:
    failures.append("a system from an empty workflow")

for f in failures:
    print("FAIL", f)
print("ok" if not failures else f"{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
