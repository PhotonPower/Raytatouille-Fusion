"""The Raytracer draws the system of a node workflow also when the document holds it as a socket
graph (version 1, `workflow.graph`, e.g. written by a script) instead of a model (version 2):
before, such a document showed no CAD model at all. Exit code 77 (ctest: skipped) without
numpy, raytatouille or rtt_fusion."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "python" / "plugins" / "raytracer")]
try:
    import numpy  # noqa: F401
    import raytatouille as rt
    from rtt_fusion.graph import graph_from_raytatouille, io
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


failures = []
d = json.loads(SYSTEM.read_text(encoding="utf-8"))
graph = io.to_dict(graph_from_raytatouille(d))
made = plugin()._workflow_system(Ctx({"graph": graph}))
if made is None:
    failures.append("no system from a version-1 workflow graph")
else:
    expected = [L.id for L in rt.layout.surfaces(rt.compile(rt.System.from_json(json.dumps(d)),
                                                             rt.MaterialLibrary()))]
    got = [L.id for L in rt.layout.surfaces(rt.compile(made[0], rt.MaterialLibrary()))]
    if got != expected:
        failures.append(f"surfaces {got} != {expected}")
if plugin()._workflow_system(Ctx({})) is not None:
    failures.append("a system from an empty workflow")

for f in failures:
    print("FAIL", f)
print("ok" if not failures else f"{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
