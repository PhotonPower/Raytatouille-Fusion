"""Workflow engine (ADR 0010): a document computes without further files (RTT-Fusion W75).

A grating block that names its Jones table by path: Check workflow stores the table in the block
and clears the path, so the run still works after the file is gone; a path that cannot be read is
a warning at the check, and a run that computes nothing says why in its status line. Needs
rtt_fusion with `workflow.embed_files` (skips with 77 else)."""

import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "python"))
sys.path.insert(0, str(root / "python" / "plugins" / "workflow"))

try:
    import numpy as np
    from rtt_fusion.graph import Graph, Node, io, workflow
    from rtt_fusion.results import FIELD_REFERENCE, to_json
except ImportError as e:
    print(f"skipped: {e}")
    sys.exit(77)
if not hasattr(workflow, "embed_files"):
    print("skipped: rtt_fusion without workflow.embed_files (W75)")
    sys.exit(77)

import workflow_plugin  # noqa: E402


def write_mirror_table(path: Path) -> str:
    """A Jones table of a plain mirror (order 0, amplitude −1) around normal incidence."""
    lam = np.linspace(0.59, 0.61, 4)
    s = np.linspace(-0.03, 0.03, 7)
    jones = np.zeros((1, len(lam), len(s), len(s), 2, 2), dtype=complex)
    jones[...] = -np.eye(2)
    data = {
        "parameters": {"orders": [0], "side": "reflected", "period_um": 0.7, "n_in": 1.0, "n_out": 1.0},
        "inputs": {"wavelengths_um": lam, "sigma_x": s, "sigma_y": s, "jones": jones},
    }
    path.write_text(to_json(FIELD_REFERENCE, data), encoding="utf-8")
    return str(path)


def socket_graph(table: str) -> dict:
    g = Graph()
    g.add(Node("src", "optics.collimated_source", params={
        "radius": 0.01, "rings": 3, "center": [0, 0, -0.1], "wavelengths_um": [0.6],
        "field_angles_deg": [[0.0, 0.0]]}))
    g.add(Node("gr", "fg.grating", params={"table": table}))
    g.add(Node("cam", "optics.detector", params={
        "point": [0, 0, -0.05], "normal": [0, 0, 1], "half_size": [0.02, 0.02], "pixels": [16, 16]}))
    g.add(Node("show", "display.image", name="Camera"))
    g.connect(("src", "out"), ("gr", "in"))
    g.connect(("gr", "out"), ("cam", "in"))
    g.connect(("cam", "image"), ("show", "in"))
    return io.to_dict(g)


class Ctx:
    def __init__(self, graph: dict):
        self.params = {"rays": 37, "pixels": 16, "window": 0.0, "gaussian_waist": 0.0}
        self.wf = {"graph": graph}
        self.lines: list[str] = []
        self.images: list[str] = []

    def workflow(self):
        return self.wf

    def set_workflow(self, wf):
        self.wf = wf

    def log(self, line):
        self.lines.append(line)

    def evaluate_block(self, *_):  # no other plugins: the engine computes every block
        raise AssertionError("no block of another plugin expected")

    def workflow_state(self, _):
        pass

    def workflow_running(self, _):
        pass

    def result_set(self, name):
        return name

    def progress(self, *_):
        pass

    def check_cancel(self):
        pass

    def image(self, run, title, *args, **kwargs):
        self.images.append(title)

    def curve(self, *args, **kwargs):
        pass


def grating_params(ctx: Ctx) -> dict:
    return next(n for n in ctx.wf["graph"]["nodes"] if n["id"] == "gr")["params"]


with tempfile.TemporaryDirectory() as tmp:
    # the table goes into the document at the check; the run works after the file is gone
    table = write_mirror_table(Path(tmp) / "mirror.json")
    ctx = Ctx(socket_graph(table))
    engine = workflow_plugin.WorkflowEngine()
    engine.check_workflow(ctx)
    params = grating_params(ctx)
    assert params["table"] == "" and params["table_data"]["format"] == "raytatouille-result", params
    assert tmp not in str(ctx.wf["graph"])
    assert any("stored in the workflow" in line for line in ctx.lines), ctx.lines
    Path(table).unlink()
    message = engine.run_workflow(ctx)
    assert message.startswith("workflow: Camera"), message
    assert ctx.images, ctx.lines

    # a path that cannot be read: a warning at the check, the reason in the run's status line
    missing = str(Path(tmp) / "elsewhere" / "grating.fg.json")
    ctx = Ctx(socket_graph(missing))
    engine = workflow_plugin.WorkflowEngine()
    engine.check_workflow(ctx)
    codes = [d["code"] for d in ctx.wf["diagnostics"]]
    assert "graph.file_unreadable" in codes, codes
    assert grating_params(ctx)["table"] == missing
    message = engine.run_workflow(ctx)
    assert message.startswith("workflow: nothing computed – Camera: exec.param: cannot read"), message
    assert "Check workflow" in message, message

    # what a camera used at run time on an auto link (fields near a focus) is shown at the link
    if hasattr(workflow, "with_used"):
        table = write_mirror_table(Path(tmp) / "mirror2.json")
        plain = workflow_plugin._evaluators

        def deciding(extra):
            evaluators = plain(extra)
            if "optics.detector" not in evaluators:  # the evaluators the remote blocks fall back to
                return evaluators
            camera = evaluators["optics.detector"]

            def detector(ctx_, node, socket, inputs):
                ctx_.used["gr.out -> cam.in"] = {"representation": "H", "reason": "a focus"}
                return camera(ctx_, node, socket, inputs)

            return {**evaluators, "optics.detector": detector}

        workflow_plugin._evaluators = deciding
        try:
            ctx = Ctx(socket_graph(table))
            engine = workflow_plugin.WorkflowEngine()
            engine.check_workflow(ctx)
            assert "used" not in ctx.wf["plan"]["links"]["gr.out -> cam.in"]
            engine.run_workflow(ctx)
            shown = ctx.wf["plan"]["links"]["gr.out -> cam.in"]
            assert shown["representation"] == "R" and shown["used"] == "H", shown
            assert shown["used_reason"] == "a focus", shown
            engine.check_workflow(ctx)  # the result is still up to date: the check keeps it
            assert ctx.wf["plan"]["links"]["gr.out -> cam.in"]["used"] == "H"
            ctx.params["pixels"] = 32  # out of date: only the plan
            engine.check_workflow(ctx)
            assert "used" not in ctx.wf["plan"]["links"]["gr.out -> cam.in"]
        finally:
            workflow_plugin._evaluators = plain

    # a glass catalogue the document names only by its file name: added once in the panel, stored
    from rtt_fusion.graph import embedded

    if hasattr(embedded, "load_catalogs"):
        agf = Path(tmp) / "K.agf"
        agf.write_text("CC Test\nNM TESTGLAS 2 0 1.5 60 0 0 0\nCD 1.0 0.005 0 0 0 0 0 0 0 0\nLD 0.3 2.5\n",
                       encoding="utf-8")
        g = Graph()
        g.add(Node("source", "rtt.source", params={"rtt_system": {}, "rtt_catalogs": ["k.agf"]}))
        ctx = Ctx(io.to_dict(g))
        engine = workflow_plugin.WorkflowEngine()
        stored, problems = engine._embed(ctx, workflow, g)
        assert not stored and problems[0]["code"] == "graph.file_unreadable", problems
        ctx.params["catalogs"] = [str(agf)]
        ctx.set_params = lambda values: ctx.params.update(values)
        stored, problems = engine._embed(ctx, workflow, g)
        assert stored and not problems and ctx.params["catalogs"] == [], (problems, ctx.params)
        assert g.nodes["source"].params["rtt_catalogs"] == []
        agf.unlink()
        lines: list[str] = []
        lib = engine._materials({"graph": io.to_dict(g)}, lines.append)
        if lib is not None:  # with raytatouille
            assert lib.catalogs() == ["K"] and not lines, lines
        assert engine._materials({"graph": io.to_dict(Graph())}, lines.append) is None or not lines

print("workflow plugin: files stored in the document, failures in the status line, R→H at the link, "
      "glass catalogues stored")
