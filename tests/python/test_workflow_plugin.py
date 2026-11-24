"""Workflow engine (ADR 0010): a document computes without further files (RTT-Fusion W75).

A grating block that names its Jones table by path: Check workflow stores the table in the block
and clears the path, so the run still works after the file is gone; a path that cannot be read is
a warning at the check, and a run that computes nothing says why in its status line. Needs
rtt_fusion with `workflow.embed_files` (skips with 77 else)."""

import importlib
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "python"))
sys.path.insert(0, str(root / "python" / "plugins" / "workflow"))

import workflow_plugin  # noqa: E402

# the spectrum diagnostics of a run (RTT-Fusion R30a–R30d) at the links, in the status line (R30e);
# plain functions: no rtt_fusion needed
lines = [
    "lens.out -> cam.in: H -> S by the PFT (1/F = 3e-3)",
    "lens.out -> cam.in: exec.spectrum_cut: 1.20e-02 of the power left out of the spectrum (evanescent)",
    "gr@2: exec.spectrum_rays: the orders gr[0] and gr[1] overlap",
    "lens.out -> cam.in: exec.spectrum_cut: 1.20e-02 of the power left out of the spectrum (evanescent)",
    "src.out -> lens.in: toS: exec.spectrum_cut: 3e-3 dropped",
]
notes = workflow_plugin.run_notes(lines)
assert [(d["code"], d["location"]) for d in notes] == [
    ("exec.spectrum_cut", "lens.out -> cam.in"), ("exec.spectrum_rays", "gr@2"),
    ("exec.spectrum_cut", "src.out -> lens.in")], notes  # repeated lines once, a block's note on its link
assert all(d["severity"] == "warning" for d in notes)
assert notes[0]["message"].startswith("1.20e-02 of the power"), notes[0]
summary = workflow_plugin.notes_summary(notes)
assert summary.startswith("spectra: exec.spectrum_cut at lens.out -> cam.in: 1.20e-02") and "(+2 more)" in summary, summary
assert workflow_plugin.notes_summary([]) == ""


class SupportError(RuntimeError):  # as RTT-Fusion's ExecutionError: code and location
    code = "exec.spectrum_support"
    location = "cond.out -> cam.in"


err = workflow_plugin.error_note(SupportError("exec.spectrum_support: no sampling behind cond (cond.out -> cam.in)"))
assert err == {"code": "exec.spectrum_support", "severity": "error", "location": "cond.out -> cam.in",
               "message": "no sampling behind cond"}, err
assert workflow_plugin.error_note(RuntimeError("exec.field: x")) is None
plan = {"links": {"lens.out -> cam.in": {"representation": "S"}, "src.out -> lens.in": {"representation": "R"}},
        "conversions": []}
shown = workflow_plugin.with_notes(plan, notes, model_id=lambda i: i.split("@")[0])
assert shown["links"]["lens.out -> cam.in"]["notes"] == [
    "exec.spectrum_cut: 1.20e-02 of the power left out of the spectrum (evanescent)"], shown
assert shown["node_notes"] == {"gr": ["exec.spectrum_rays: the orders gr[0] and gr[1] overlap"]}, shown
assert "notes" not in plan["links"]["lens.out -> cam.in"]  # the plan itself is unchanged
# a model: the notes of a link go to its connection and direction
by_connection = workflow_plugin.with_notes(
    plan, notes[:1], per_connection=lambda texts: {"3": {"forward": texts["lens.out -> cam.in"]}})
assert by_connection["connections_notes"] == {"3": {"forward": [
    "exec.spectrum_cut: 1.20e-02 of the power left out of the spectrum (evanescent)"]}}, by_connection
assert workflow_plugin.with_notes(plan, []) is plan

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

    # a glass catalogue the document names only by its file name: the Raytracer panel's list is
    # stored in the workflow
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
        ctx.plugin_params = lambda plugin: {"catalogs": [str(agf)]} if plugin == "raytracer" else {}
        stored, problems = engine._embed(ctx, workflow, g)
        assert stored and not problems, problems
        assert g.nodes["source"].params["rtt_catalogs"] == []
        agf.unlink()
        lines: list[str] = []
        lib = engine._materials({"graph": io.to_dict(g)}, lines.append)
        if lib is not None:  # with raytatouille
            assert lib.catalogs() == ["K"] and not lines, lines
        assert engine._materials({"graph": io.to_dict(Graph())}, lines.append) is None or not lines

    # results kept with their fingerprint (CAD: saved in the .rttf): an unchanged display is not
    # computed again – also with a new engine, as after reopening the document – a changed one is
    table = write_mirror_table(Path(tmp) / "mirror3.json")
    ctx = Ctx(socket_graph(table))
    kept: dict[str, str] = {}

    def image(run, title, *args, key="", stamp="", **kwargs):
        ctx.images.append(title)
        if key and stamp:
            kept[key] = stamp

    ctx.image = image
    ctx.result_stamps = lambda: dict(kept)
    engine = workflow_plugin.WorkflowEngine()
    engine.check_workflow(ctx)
    assert engine.run_workflow(ctx).startswith("workflow: Camera"), ctx.lines
    assert list(kept) == ["workflow:show"] and len(ctx.images) == 1, (kept, ctx.images)
    message = workflow_plugin.WorkflowEngine().run_workflow(ctx)  # a fresh engine: no cache
    assert message == "workflow: Camera (unchanged)", message
    assert len(ctx.images) == 1
    states: list[dict] = []
    ctx.workflow_state = states.append
    workflow_plugin.WorkflowEngine().check_workflow(ctx)
    assert states and all(states[-1].values()), states  # up to date from the kept result
    ctx.params["pixels"] = 32  # changed: computed again with a new fingerprint
    message = workflow_plugin.WorkflowEngine().run_workflow(ctx)
    assert message == "workflow: Camera", message
    assert len(ctx.images) == 2

# a spectrum on a link planned R (fusion.convert to S in front of a camera): R→S at the link after
# the run, with the chain; the transports the editor offers in the document (R30e)
execute = importlib.import_module("rtt_fusion.graph.execute")
if "S" in workflow.available() and hasattr(execute.Executor, "_record_used"):
    g = Graph()
    g.add(Node("src", "optics.collimated_source", params={"radius": 1.0, "rings": 8}))
    g.add(Node("lens", "optics.aplanatic_lens",
               params={"focal_length": 2.0, "aperture_radius": 1.000001, "point": [0, 0, 1]}))
    g.add(Node("toS", "fusion.convert", params={"to": "S"}))
    g.add(Node("cam", "optics.detector", params={"point": [0, 0, 3], "normal": [0, 0, -1],
                                                 "half_size": [0.0025, 0.0025]}))
    g.add(Node("show", "display.image", name="Focus"))
    g.connect(("src", "out"), ("lens", "in"))
    g.connect(("lens", "out"), ("toS", "in"))
    g.connect(("toS", "out"), ("cam", "in"))
    g.connect(("cam", "image"), ("show", "in"))
    ctx = Ctx(io.to_dict(g))
    ctx.params["pixels"] = 9
    engine = workflow_plugin.WorkflowEngine()
    engine.check_workflow(ctx)
    assert ctx.wf["available"] == ["H", "R", "S"], ctx.wf["available"]
    assert ctx.wf["plan"]["links"]["toS.out -> cam.in"]["representation"] == "S"   # auto keeps spectra (R30f)
    message = engine.run_workflow(ctx)
    assert message.startswith("workflow: Focus"), (message, ctx.lines)
    shown = ctx.wf["plan"]["links"]["toS.out -> cam.in"]
    assert (shown["representation"], shown["used"], shown["used_chain"]) == ("S", "S", "S"), shown
    assert "cam takes them as they are" in shown["used_reason"], shown
    assert "used" not in ctx.wf["plan"]["links"]["src.out -> lens.in"]

# blocks nothing here can compute: not offered in the library, a warning on the ones in the workflow
registry, extra = workflow.registry()
evaluators = workflow_plugin._evaluators(extra)
library = workflow.catalogue(registry)
missing = {t["type"] for t in library} - set(evaluators) - workflow_plugin._STRUCTURAL
assert missing, "every built-in type has an evaluator – pick another planned type for this test"
planned = sorted(missing)[0]
g = Graph()
g.add(Node("p", planned))
checked = workflow_plugin._runnable_only({"types": library, "diagnostics": []}, g, evaluators)
assert planned in {t["type"] for t in checked["types"]}  # used: the editor still draws it
assert [d["code"] for d in checked["diagnostics"]] == ["check.no_evaluator"], checked["diagnostics"]
empty = workflow_plugin._runnable_only({"types": library, "diagnostics": []}, Graph(), evaluators)
assert not missing & {t["type"] for t in empty["types"]} and not empty["diagnostics"]

# Convert to model: a version 1 graph with two transmission gratings chained out → in (as scripts
# write it) becomes a model through the gratings' back ports (RTT-Fusion#120 and its reader)
topology = importlib.import_module("rtt_fusion.graph.topology")
if hasattr(topology, "_through_back_ports"):
    g = Graph()
    g.add(Node("src", "optics.collimated_source", params={"radius": 0.01, "rings": 2}))
    for name, z in (("G1", 1.0), ("G2", 2.0)):
        g.add(Node(name, "fg.grating", params={"side": "transmitted", "point": [0, 0, z],
                                                "normal": [0, 0, -1]}))
    g.add(Node("cam", "optics.detector", params={"point": [0, 0, 3.0], "normal": [0, 0, -1]}))
    g.connect(("src", "out"), ("G1", "in"))
    g.connect(("G1", "out"), ("G2", "in"))
    g.connect(("G2", "out"), ("cam", "in"))
    ctx = Ctx(io.to_dict(g))
    plugin = workflow_plugin.WorkflowEngine()
    text = plugin.convert_to_model(ctx)
    assert "graph" not in ctx.wf and len(ctx.wf["model"]["connections"]) == 3, (text, ctx.wf.keys())
    try:
        plugin.convert_to_model(ctx)
        raise AssertionError("a model converted again")
    except workflow_plugin.UserError:
        pass

print("workflow plugin: files stored in the document, failures in the status line, R→H at the link, "
      "glass catalogues stored, kept results not computed again, blocks without evaluator not offered, "
      "spectra at the links (R→S, notes)")
