"""The Path Tracer examples (examples/pathtracer): the documents in the repository are what
make_examples.py writes, and the plugin computes a camera image from each (tiny, coarse mesh,
NumPy kernel). Exit code 77 (skipped) without NumPy."""

import json
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    print("skipped: numpy is not installed")
    sys.exit(77)

root = Path(__file__).resolve().parents[2]
examples = root / "examples" / "pathtracer"
sys.path.insert(0, str(root / "python"))
sys.path.insert(0, str(root / "python" / "plugins" / "pathtracer"))
sys.path.insert(0, str(examples))

import make_examples  # noqa: E402
import pathtracer_plugin  # noqa: E402
from nfcad import Context  # noqa: E402

# ---- colours: equal power on the lines is white; red, green and blue where they belong
assert max(range(3), key=lambda k: make_examples.colour_of(650.0)[k]) == 0
assert max(range(3), key=lambda k: make_examples.colour_of(540.0)[k]) == 1
assert max(range(3), key=lambda k: make_examples.colour_of(450.0)[k]) == 2
grey = make_examples.develop(np.full((5, 4, 6), 0.2), make_examples.lines(450.0, 650.0, 5), 99.0)
assert grey.shape == (4, 6, 3) and grey.dtype == np.uint8 and np.ptp(grey.astype(int), axis=2).max() <= 1
beside = np.zeros((5, 4, 6))
beside[:, :, :3] = 1.0                                      # left: all wavelengths, the white of the picture
beside[4, :, 3:] = 1.0                                      # right: 650 nm alone
red = make_examples.develop(beside, make_examples.lines(450.0, 650.0, 5), 99.0)
assert (red[:, :3] == 255).all() and red[0, 5, 0] > 100 and red[0, 5, 1] < 30 and red[0, 5, 2] < 30
flipped = np.zeros((1, 4, 6))
flipped[0, 0] = 1.0                                         # row 0 of the plugin's image is the bottom one
assert make_examples.develop(flipped, [550.0], 99.0)[3].min() == 255 and make_examples.develop(flipped, [550.0], 99.0)[0].max() == 0

plugin = pathtracer_plugin.PathTracerPlugin()
names = []
for make in make_examples.SCENES:
    scene = make()
    names.append(scene.name)
    document = scene.document()
    # ---- the document in the repository is the script's
    stored = json.loads((examples / f"{scene.name}.rttf").read_text(encoding="utf-8"))
    assert stored == json.loads(json.dumps(document)), f"{scene.name}.rttf is not what make_examples.py writes"
    assert (examples / f"{scene.name}.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert document["format"] == "nfcad" and len({e["id"] for e in document["entities"]}) == len(document["entities"])
    groups = {g["id"] for g in document["groups"]} | {0}
    assert all(e["group"] in groups for e in document["entities"])
    params = document["plugins"]["pathtracer"]["params"]
    assert set(params) <= set(plugin.params), set(params) - set(plugin.params)
    materials = {m["name"] for m in params["materials"]}
    sources = {s["name"] for s in params["sources"]}
    assert all(e["attributes"]["pt.material"] in materials for e in document["entities"])
    assert {e["attributes"]["pt.source"] for e in document["entities"] if "pt.source" in e["attributes"]} == sources
    # ---- and the plugin computes its camera image: one image and one per wavelength
    host = make_examples.Host(document)
    host.send = lambda message: None
    raw = {**params, "camera_width": 16, "camera_height": 12, "samples": 3000, "depth": 6, "tolerance": 2.0,
           "exact_normals": False, "kernel": "NumPy", "processes": 1}
    plugin.camera_image(Context(host, 1, plugin.convert_params(raw), []))
    assert len(host.images) == 1 + len(scene.nm), (scene.name, len(host.images))
    total = host.images[0][1]
    assert total.shape == (12, 16) and np.isfinite(total).all() and (total >= 0).all() and total.max() > 0
    assert np.allclose(sum(image for _, image in host.images[1:]), total, rtol=1e-4, atol=1e-6 * total.max())
assert len(set(names)) == 4

print("pathtracer examples ok")
