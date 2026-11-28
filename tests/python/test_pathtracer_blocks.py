"""Path Tracer plugin: materials as blocks of the node workflow (Raytatouille Fusion ADR 0011,
stage M2). The blocks' catalogue reaches the engine, a block evaluated through the engine's remote
evaluator equals the block evaluated in the plugin, the plugin collects the workflow's materials
(also in groups) and renders with them as with the same material in its table, and the block
preview draws a sphere. Needs numpy and an RTT-Fusion with the data type bsdf (skips with 77)."""

import math
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
    from rtt_fusion import material
    from rtt_fusion.graph.model import DATA_TYPES
except ImportError:
    sys.exit(77)
if "bsdf" not in DATA_TYPES:
    sys.exit(77)

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "python"))
sys.path.insert(0, str(root / "python" / "plugins" / "pathtracer"))

from nfcad import UserError, drawing  # noqa: E402
from rtt_fusion.graph import Graph, Node  # noqa: E402
from rtt_fusion.graph.execute import Context  # noqa: E402
from rtt_fusion.graph.model import NodeType  # noqa: E402
from rtt_fusion.graph.remote import RemoteEvaluator  # noqa: E402

import pt_blocks  # noqa: E402
import pt_integrator  # noqa: E402
import pt_scene  # noqa: E402
import pt_setup  # noqa: E402
from pathtracer_plugin import PathTracerPlugin  # noqa: E402

SEED = 3
folder = Path(tempfile.mkdtemp())
plugin = PathTracerPlugin()

# ---- the catalogue: four data-only blocks, readable by the engine
catalogue = plugin.blocks()
assert [e["type"] for e in catalogue] == list(pt_blocks.TYPES_ALL)
for entry in catalogue:
    t = NodeType.from_dict(entry)
    assert all(s.kind.value == "data" and s.accepts == frozenset({"bsdf"}) for s in t.sockets), entry["type"]
    assert entry["representations"] == []

# ---- a block through the engine's remote evaluator equals the block in the plugin
mix_params = {"weight": 0.25}
lam_a = pt_blocks.analytic({"model": "lambert", "value": "0.2"})
lam_b = pt_blocks.analytic({"model": "lambert", "value": "0.8", "step": 5.0})
g = Graph()
g.add(Node("mix", pt_blocks.MIX, params=mix_params))
with tempfile.TemporaryDirectory() as d:
    remote = RemoteEvaluator("pathtracer", lambda _p, r: plugin.evaluate_block(r), frozenset(), d)
    far = remote(Context(g, shared={}), g.nodes["mix"], "bsdf", {"a": [lam_a], "b": [lam_b]})
near = material.mix(lam_a, lam_b, 0.25)
assert isinstance(far, material.Bsdf) and np.array_equal(far.brdf, near.brdf)
assert np.allclose(far.scattered_reflectance(), 0.35, rtol=1e-12)

# ---- the document's materials: blocks linked into material blocks, also inside a group's variant
metal = material.ggx_conductor(0.9, 0.5, [0.55], np.deg2rad(np.arange(0, 90, 5.0)),
                               np.deg2rad(np.linspace(0, 90, 46)), np.deg2rad(np.linspace(0, 180, 37)))
material.save(metal, str(folder / "metal.bsdf"))


def wf(nodes, links):
    return {"model": {"format": "rtt-fusion-graph", "version": 2, "nodes": nodes, "links": links, "connections": []}}


def link(a, b, socket="bsdf"):
    return {"from": [a, "bsdf"], "to": [b, socket]}


nodes = [
    {"id": "w", "type": pt_blocks.ANALYTIC, "params": {"model": "lambert", "value": "0.6"}},
    {"id": "white", "type": pt_blocks.MATERIAL, "name": "white block", "params": {}},
    {"id": "f", "type": pt_blocks.FILE, "params": {"file": str(folder / "metal.bsdf")}},
    {"id": "m", "type": pt_blocks.MIX, "params": {"weight": 0.5}},
    {"id": "paint", "type": pt_blocks.MATERIAL, "params": {"name": "half metal"}},
    {"id": "grp", "type": "group", "variant": "a", "variants": {"a": {
        "nodes": [{"id": "x", "type": pt_blocks.ANALYTIC, "params": {"model": "metal", "value": "450:0.3, 650:0.9",
                                                                      "roughness": 0.4}},
                  {"id": "y", "type": pt_blocks.MATERIAL, "params": {"name": "copper"}}],
        "links": [link("x", "y")]}}},
    {"id": "off", "type": pt_blocks.MATERIAL, "muted": True, "params": {"name": "muted"}},
]
links = [link("w", "white"), link("f", "m", "a"), link("w", "m", "b"), link("m", "paint")]
found = pt_blocks.workflow_materials(wf(nodes, links))
assert sorted(found) == ["copper", "half metal", "white block"]
assert np.allclose(found["white block"].scattered_reflectance(), 0.6, rtol=1e-12)
half = 0.5 * metal.scattered_reflectance() + 0.5 * 0.6
assert np.allclose(found["half metal"].scattered_reflectance(), half, rtol=1e-12)
assert found["copper"].wavelength.tolist() == [0.45, 0.65]
assert pt_blocks.has_materials(wf(nodes, links)) and not pt_blocks.has_materials(wf(nodes[:1], []))
for bad_nodes, bad_links, message in (
        (nodes[:2], [], "no BSDF block is connected"),
        (nodes[:2] + [{"id": "w2", "type": pt_blocks.MATERIAL, "params": {"name": "white block"}}],
         [link("w", "white"), link("w", "w2")], "two material blocks"),
        ([{"id": "bad", "type": pt_blocks.ANALYTIC, "params": {"model": "wood"}}, nodes[1]],
         [link("bad", "white")], "model 'wood'"),
        ([{"id": "nf", "type": pt_blocks.FILE, "params": {"file": str(folder / "none.bsdf")}}, nodes[1]],
         [link("nf", "white")], "none.bsdf")):
    try:
        pt_blocks.workflow_materials(wf(bad_nodes, bad_links))
        raise AssertionError("not refused")
    except pt_blocks.BlockError as e:
        assert message in str(e), e


# ---- rendering: a block material gives what the same material in the table gives
def rect(p0, du, dv):
    p0, du, dv = (np.asarray(v, dtype=float) for v in (p0, du, dv))
    pts = [p0, p0 + dv, p0 + du, p0 + du + dv]
    return {"type": "surface", "degree_u": 1, "degree_v": 1, "knots_u": [0, 0, 1, 1], "knots_v": [0, 0, 1, 1],
            "num_u": 2, "num_v": 2, "points": [float(c) for p in pts for c in p]}


model = [
    {"id": 11, "name": "floor", "attributes": {"pt.material": "white block"},
     "geometry": rect((-100, -100, 0), (200, 0, 0), (0, 200, 0))},
    {"id": 12, "name": "lamp", "attributes": {"pt.source": "lamp", "pt.material": "black"},
     "geometry": rect((-10, -10, 80), (0, 20, 0), (20, 0, 0))},
    {"id": 13, "name": "ceiling", "attributes": {"pt.material": "black"},
     "geometry": rect((-100, -100, 100), (0, 200, 0), (200, 0, 0))},
]
params = {"materials": pt_setup.DEFAULT_MATERIALS, "default_material": "white", "sources": pt_setup.DEFAULT_SOURCES,
          "workflow_materials": {name: pt_blocks.table_of(b) for name, b in found.items()}}


def up_light(the_model, the_params):
    scene = pt_setup.build_scene(the_model, the_params)
    sensor = pt_scene.TexelSensor(scene, pt_setup.sensor_faces(scene, [13]), 2)
    return float(pt_integrator.render(scene, sensor, "light", 200_000, 4, seed=SEED)["values"].sum())


block = up_light(model, params)
table_model = [{**model[0], "attributes": {"pt.material": "plain"}}] + model[1:]
table_params = {**params, "materials": pt_setup.DEFAULT_MATERIALS + [
    {"name": "plain", "kind": "diffuse", "reflectance": 0.6}]}
plain = up_light(table_model, table_params)
assert abs(block / plain - 1) < 0.03, (block, plain)
try:                                                       # a block's name taken by the table as well
    pt_setup.describe(model, {**params, "materials": pt_setup.DEFAULT_MATERIALS + [
        {"name": "white block", "kind": "diffuse", "reflectance": 0.5}]})
    raise AssertionError("not refused")
except ValueError as e:
    assert "defined twice" in str(e), e


# ---- the plugin's actions read the workflow of the document
class FakeCad:
    def __init__(self, entities, params, workflow, selection=()):
        self.model, self.params, self.wf, self.selection = entities, params, workflow, list(selection)
        self.fields, self.logs = [], []

    def workflow(self):
        return self.wf

    def entities(self, ids=None, selection=False):
        return [e for e in self.model if not selection or e["id"] in self.selection]

    def set_attribute(self, entity, key, value):
        next(e for e in self.model if e["id"] == entity)["attributes"][key] = value

    def progress(self, value, text=""):
        pass

    def log(self, text):
        self.logs.append(text)

    def cancelled(self):
        return False

    def result_set(self, name):
        return 1

    def field(self, run, name, entity, data, width, height, **kw):
        self.fields.append((name, entity, np.asarray(data)))

    def table(self, run, name, columns, rows, **kw):
        pass


p = plugin.convert_params({"seed": SEED, "samples": 20_000, "processes": 1, "texels": 4, "irradiance_on": [11],
                           "assign_material": "copper", "kernel": "NumPy"})
cad = FakeCad([{**e, "attributes": dict(e["attributes"])} for e in model], p, wf(nodes, links), selection=[13])
assert plugin.set_material(cad) == "1 object(s): material copper"
plugin.irradiance(cad)
assert cad.fields and cad.fields[0][1] == 11 and cad.fields[0][2].sum() > 0
p["assign_material"] = "nowhere"
try:
    plugin.set_material(cad)
    raise AssertionError("not refused")
except UserError as e:
    assert "material block" in str(e), e
cad.wf = wf(nodes[:2], [])                                  # a material block without a BSDF: a clear message
try:
    plugin.irradiance(cad)
    raise AssertionError("not refused")
except UserError as e:
    assert str(e).startswith("Workflow:") and "no BSDF block" in str(e), e

# ---- previews: a sphere in the BSDF, brighter where the sun shines; a material block shows its input
answer = plugin.preview_block({"node": nodes[1], "type": pt_blocks.MATERIAL, "model": wf(nodes, links)["model"]})
assert answer["ok"] and not drawing.check(answer["drawing"]), answer
cells = [it for it in answer["drawing"]["items"] if it["type"] == "polygon"]
assert 1000 < len(cells) < 20_000


def brightness(item):
    return sum(int(item["fill"][k:k + 2], 16) for k in (1, 3, 5))


def centre(item):
    xs, ys = zip(*item["points"])
    return sum(xs) / len(xs), sum(ys) / len(ys)


lit = [brightness(c) for c in cells if centre(c)[0] < -0.3 and centre(c)[1] > 0.3]
dark = [brightness(c) for c in cells if centre(c)[0] > 0.3 and centre(c)[1] < -0.3]
assert np.mean(lit) > np.mean(dark) + 60, (np.mean(lit), np.mean(dark))
copper = plugin.preview_block({"node": {"id": "y", "type": pt_blocks.MATERIAL, "params": {"name": "copper"}},
                               "type": pt_blocks.MATERIAL, "model": wf(nodes, links)["model"]})
reds = [int(c["fill"][1:3], 16) - int(c["fill"][5:7], 16) for c in copper["drawing"]["items"] if c["type"] == "polygon"]
assert np.mean(reds) > 20, np.mean(reds)                  # reflects red more than blue
assert not plugin.preview_block({"node": {"id": "z", "type": pt_blocks.MATERIAL}, "type": pt_blocks.MATERIAL,
                                 "model": {"nodes": [], "links": []}})["ok"]
print("ok")
