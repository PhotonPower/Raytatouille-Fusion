"""Overview drawings of workflow blocks (docs/plugin-api.md, "Block previews"): the producers of
the Raytracer (a singlet, a cemented doublet behind a stop, a detector, a section whose glass is
unknown), of the FourierGrating plugin (a lamellar grating, a coating stack, profiles) and of the
workflow engine (optics.* blocks) give valid "nfcad-drawing" JSON. The FourierGrating and engine
parts need nothing but nfcad; the Raytracer part needs raytatouille (skipped without it; the
whole test exits 77 if nothing could run).

``--write`` stores the drawings of the singlet, the doublet and the grating as fixtures of the
C++ test (tests/data/drawings) – they are what the dialog draws.
"""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "python"))
for plugin in ("raytracer", "fouriergrating", "workflow"):
    sys.path.insert(0, str(root / "python" / "plugins" / plugin))

from nfcad import drawing  # noqa: E402

FIXTURES = root / "tests" / "data" / "drawings"
written: dict[str, dict] = {}
ran = 0


def valid(answer: dict, what: str) -> dict:
    assert answer.get("ok"), (what, answer)
    d = answer["drawing"]
    assert drawing.check(d) == [], (what, drawing.check(d))
    json.dumps(d, allow_nan=False)  # reaches CAD
    return d


def kinds(d: dict, kind: str, **match) -> list:
    return [i for i in d["items"] if i["type"] == kind and all(i.get(k) == v for k, v in match.items())]


# ------------------------------------------------------------------ the builder
b = drawing.Drawing("t", unit="µm", axes=("x", "y"))
b.polygon([(0, 0), (1, 0), (1, 1)], material="si")
b.text((0.5, 0.5), "x")
assert b.to_json()["materials"] == [{"name": "si"}] and b.bounds() == (0, 0, 1, 1)
for bad in (lambda: b.polygon([(0, 0), (1, 1)]), lambda: b.polyline([(0, float("nan")), (1, 1)]),
            lambda: b.polyline([(0, 0), (1, 1)], role="nonsense")):
    try:
        bad()
    except ValueError:
        pass
    else:
        raise AssertionError("accepted a bad item")
assert drawing.check({"items": [{"type": "polygon", "points": [[0, 0], [1, 1]]}]}) == ["item 0: too few points"]

# ------------------------------------------------------------------ FourierGrating
import fg_preview  # noqa: E402

GRATING = {
    "dimension": "1D", "period_um": {"x": 1.0, "z": 0.0}, "truncation": {"Nx": 25},
    "incidence": {"lambda_um": 0.54607, "phi_deg": 10, "psi_deg": 0, "delta_deg": 0},
    "materials": {"air": {"n": 1.0}, "si": {"n": [4.087, 0.035]}, "sio2": {"n": 1.46}},
    "superstrate": "air", "substrate": "si",
    "layers": [{"type": "homogeneous", "thickness_um": 0.05, "material": "sio2"},
               {"type": "lamellar1d", "thickness_um": 0.1, "breakpoints_um": [0.0, 0.5, 1.0],
                "materials": ["si", "air"]}],
}


def config_of(node):
    return (node.get("params") or {}).get("config") or None


node = {"id": "Probe", "name": "Si line grating", "type": "fg.grating",
        "params": {"config": GRATING, "side": "reflected", "point": [0, 0, 57.9], "normal": [0, 0, -1]}}
d = valid(fg_preview.preview({"node": node}, config_of), "grating")
assert d["unit"] == "µm" and d["aspect"] == "equal"
assert {m["name"] for m in d["materials"]} == {"air", "si", "sio2"}
assert any("4.087 + 0.035i" in m.get("label", "") for m in d["materials"])
# two periods: the lamellae of the second period are there, the layer thicknesses dimensioned
assert len(kinds(d, "polygon", material="si")) >= 3
assert {i["text"] for i in kinds(d, "dimension")} >= {"0.05", "0.1", "Λ = 1 µm"}
assert len(kinds(d, "arrow")) == 2  # incidence and the reflected zeroth order
written["fg_grating"] = d
# the values of the dialog count: a thicker layer is drawn thicker
thick = json.loads(json.dumps(node))
thick["params"]["config"]["layers"][1]["thickness_um"] = 0.3
assert "0.3" in {i["text"] for i in kinds(valid(fg_preview.preview({"node": thick}, config_of), "thick"), "dimension")}
# a coating stack: no period, a layer too thin to dimension is listed
stack = {"id": "AR", "type": "fg.stack", "params": {"config": {
    "materials": {"air": {"n": 1}, "mgf2": {"n": 1.38}, "glass": {"n": {"sellmeier": {"B": [1.0]}}}},
    "superstrate": "air", "substrate": "glass", "incidence": {"lambda_um": 0.55, "phi_deg": 0},
    "layers": [{"type": "homogeneous", "thickness_um": 0.1, "material": "mgf2"},
               {"type": "homogeneous", "thickness_um": 0.001, "material": "mgf2"}]}}}
d = valid(fg_preview.preview({"node": stack}, config_of), "stack")
assert any("thin layers" in n for n in d["notes"]) and any("sellmeier" in m.get("label", "") for m in d["materials"])
# profiles, sections of 2D layers, an unknown layer type (hatched)
profiles = json.loads(json.dumps(GRATING))
profiles["layers"] = [{"type": "profile1d", "shape": "sinus", "depth_um": 0.2, "below": "si", "above": "air"},
                      {"type": "profile1d", "shape": "triangle", "apex_x_um": 0.8, "depth_um": 0.1, "below": "si",
                       "above": "air"},
                      {"type": "contour2d", "thickness_um": 0.1, "background": "air",
                       "regions": [{"material": "si", "circle": {"center_um": [0.5, 0.0], "radius_um": 0.2}}]},
                      {"type": "cad", "thickness_um": 0.1}]
d = valid(fg_preview.preview({"node": {"type": "fg.grating", "params": {"config": profiles}}}, config_of), "profiles")
assert len(kinds(d, "polygon", hatched=True)) == 1 and any("contour2d cut" in n for n in d["notes"])
# a Jones table only; another type is not ours; no configuration is an error
assert valid(fg_preview.preview({"node": {"type": "fg.grating", "params": {"table_data": {"a": 1}}}}, config_of), "t")
assert fg_preview.preview({"node": {"type": "rtt.section"}}, config_of)["unsupported"]
assert not fg_preview.preview({"node": {"type": "fg.stack", "params": {}}}, config_of)["ok"]
ran += 1

# ------------------------------------------------------------------ workflow engine (optics.*)
import workflow_preview  # noqa: E402

for t, params in (("optics.thin_lens", {"point": [0, 0, 5], "axis": [0, 0, 1], "focal_length": 20,
                                        "aperture_radius": 4}),
                  ("optics.detector", {"point": [0, 0, 30], "normal": [0, 0, -1], "half_size": [2, 1]}),
                  ("optics.collimated_source", {"center": [0, 0, 0], "direction": [0, 0, 1], "radius": 3}),
                  ("optics.plane_mirror", {"point": [0, 0, 10], "normal": [0, 1, -1]}),
                  ("fusion.particle", {"radius_um": 0.25, "index": 1.5})):
    d = valid(workflow_preview.preview({"node": {"id": "b", "type": t, "params": params}}), t)
    assert d["items"], t
assert workflow_preview.preview({"node": {"type": "display.image"}})["unsupported"]
ran += 1

# ------------------------------------------------------------------ Raytracer
try:
    import raytatouille  # noqa: F401
    import rtt_preview
except ImportError:
    rtt_preview = None

if rtt_preview is not None:
    singlet = {"type": "lens", "name": "L1", "pose": {"position": [0.0, 0.0, 5.0]}, "material": "CONST:1.5168",
               "surfaces": [{"id": "L1.S1", "shape": {"base": {"type": "conic", "radius": {"value": 103.36}}},
                             "aperture": {"type": "circular", "radius": 12.7}},
                            {"id": "L1.S2", "pose": {"position": [0.0, 0.0, 4.0]},
                             "shape": {"base": {"type": "conic", "radius": -103.36}},
                             "aperture": {"type": "circular", "radius": 12.7}}]}
    lens = {"id": "L1", "name": "Singlet f = 100", "type": "rtt.section",
            "params": {"location": "/root/children/1", "rtt": {"/root/children/1": singlet},
                       "runs": {"a>b|": [{"surface": "L1.S1"}, {"surface": "L1.S2"}]}}}
    d = valid(rtt_preview.preview({"node": lens, "model": {"nodes": [lens]}}), "singlet")
    assert d["unit"] == "mm" and d["axes"] == ["z", "y"]
    assert len(kinds(d, "polygon", material="CONST:1.5168")) == 1  # the closed outline of the glass
    outline = kinds(d, "polygon")[0]["points"]
    assert max(p[1] for p in outline) > 12.6 and min(p[0] for p in outline) < 5.0 + 0.8  # aperture, sag
    rays = kinds(d, "polyline", role="ray")
    assert len(rays) == rtt_preview.RAYS
    top = max(rays, key=lambda r: r["points"][0][1])["points"]
    assert top[-1][1] < top[0][1] - 1.0 and top[-1][0] > 50  # refracted, on towards the focus near z = 105
    assert kinds(d, "polyline", role="axis") and kinds(d, "dimension")[0]["text"] == "4 mm"
    assert any("L1.S1: R = 103.4 mm" in n for n in d["notes"])
    written["lens"] = d
    # the dialog's values: a thicker lens is drawn thicker
    thicker = json.loads(json.dumps(lens))
    thicker["params"]["rtt"]["/root/children/1"]["surfaces"][1]["pose"]["position"][2] = 6.0
    assert kinds(valid(rtt_preview.preview({"node": thicker, "model": {}}), "thicker"), "dimension")[0]["text"] == "6 mm"

    # a cemented doublet behind a stop, in an assembly (the section of an objective)
    doublet = {"type": "lens", "name": "Achromat", "pose": {"position": [0.0, 0.0, 2.0]},
               "material": ["CONST:1.5168", "CONST:1.6727"],
               "surfaces": [{"id": "D.S1", "shape": {"base": {"type": "conic", "radius": 61.47}},
                             "aperture": {"type": "circular", "radius": 12.5}},
                            {"id": "D.S2", "pose": {"position": [0.0, 0.0, 6.0]},
                             "shape": {"base": {"type": "conic", "radius": -44.64}},
                             "aperture": {"type": "circular", "radius": 12.5}},
                            {"id": "D.S3", "pose": {"position": [0.0, 0.0, 8.5]},
                             "shape": {"base": {"type": "conic", "radius": -129.94}},
                             "aperture": {"type": "circular", "radius": 12.5}}]}
    stop = {"type": "stop", "name": "Stop", "surfaces": [{"id": "STO", "aperture": {"type": "circular", "radius": 10.0}}]}
    section = {"id": "O", "name": "Achromat with stop", "type": "rtt.section",
               "params": {"rtt": {"/root/children/2": {"type": "assembly", "name": "Objective",
                                                       "pose": {"position": [0.0, 0.0, 20.0]}},
                                  "/root/children/2/children/0": stop,
                                  "/root/children/2/children/1": doublet}}}
    d = valid(rtt_preview.preview({"node": section, "model": {"nodes": [section]}}), "doublet")
    assert [len(kinds(d, "polygon", material=m)) for m in ("CONST:1.5168", "CONST:1.6727")] == [1, 1]
    assert len(kinds(d, "polyline", role="stop")) == 2 and any("stop" in t["text"] for t in kinds(d, "text"))
    assert len(kinds(d, "polyline", role="ray")) >= 5  # all through the stop
    assert {t["text"] for t in kinds(d, "text")} >= {"Stop", "Achromat"}
    assert kinds(d, "dimension")[0]["text"] == "10.5 mm"  # stop to the last vertex
    written["doublet"] = d

    # a detector: its plane; a glass from a catalogue that is not there: geometry, no rays
    detector = {"id": "CAM", "type": "rtt.detector", "params": {"rtt": {"/root/children/3": {
        "type": "detector", "name": "Camera", "pose": {"position": [0, 0, 100]},
        "surfaces": [{"id": "IMG", "aperture": {"type": "rectangular", "half_width_x": 6.4, "half_width_y": 4.8}}]}}}}
    d = valid(rtt_preview.preview({"node": detector, "model": {}}), "detector")
    assert len(kinds(d, "polyline", role="detector")) == 1
    unknown = json.loads(json.dumps(lens))
    unknown["params"]["rtt"]["/root/children/1"]["material"] = "NOWHERE:N-BK7"
    d = valid(rtt_preview.preview({"node": unknown, "model": {}}), "unknown glass")
    assert not kinds(d, "polyline", role="ray") and any("glasses unknown" in n for n in d["notes"])
    assert d["materials"][0]["name"] == "N-BK7"
    # the source: the whole system (tree skeleton and every block's elements)
    source = {"id": "source", "type": "rtt.source", "params": {
        "rtt_tree": {"/root": {"type": "assembly", "name": "System", "children": []}},
        "rtt_system": {"name": "Demo", "wavelengths": [{"um": 0.55, "reference": True}], "fields": {"points": [{}]}}}}
    d = valid(rtt_preview.preview({"node": source, "model": {"nodes": [source, lens, section, detector]}}), "source")
    assert len(kinds(d, "polygon")) == 3 and kinds(d, "polyline", role="detector")
    assert not kinds(d, "polyline", role="ray") and any("0.55" in n for n in d["notes"])
    # a new part (rtt.part.lens) holds its element in rtt_new
    part = {"id": "P", "type": "rtt.part.lens", "params": {"rtt_new": singlet}}
    d = valid(rtt_preview.preview({"node": part, "model": {}}), "part")
    assert len(kinds(d, "polygon")) == 1 and len(kinds(d, "polyline", role="ray")) == rtt_preview.RAYS
    # not ours / nothing to draw
    assert rtt_preview.preview({"node": {"type": "fg.grating"}})["unsupported"]
    assert rtt_preview.preview({"node": {"type": "rtt.section", "params": {}}})["unsupported"]
    ran += 1
else:
    print("raytatouille is not installed: the Raytracer's drawings are not tested")

if "--write" in sys.argv:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, d in written.items():
        (FIXTURES / f"{name}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {', '.join(sorted(written))} to {FIXTURES}")

print(f"block previews: {ran} producer group(s) checked")
sys.exit(0 if ran else 77)
