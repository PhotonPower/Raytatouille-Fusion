"""The Path Tracer examples (examples/pathtracer): the documents in the repository are what
make_examples.py writes, and the plugin computes a camera image from each (tiny, coarse mesh,
NumPy kernel) – the sum in grey and the picture in colour. Exit code 77 (skipped) without NumPy."""

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
import pt_colour  # noqa: E402
from nfcad import Context  # noqa: E402

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
    assert params["camera_colour"] and not params["per_wavelength"] and params["camera_white"] == scene.white
    # ---- and the plugin computes its camera image: the sum, one per wavelength, the one in colour
    host = make_examples.Host(document)
    host.send = lambda message: None
    raw = {**params, "camera_width": 16, "camera_height": 12, "samples": 3000, "depth": 6, "tolerance": 2.0,
           "exact_normals": False, "kernel": "NumPy", "processes": 1, "per_wavelength": True}
    plugin.camera_image(Context(host, 1, plugin.convert_params(raw), []))
    assert len(host.images) == 2 + len(scene.nm), (scene.name, len(host.images))
    assert all("rgb" not in image for image in host.images[:-1])
    total = host.images[0]["values"]
    assert total.shape == (12, 16) and np.isfinite(total).all() and (total >= 0).all() and total.max() > 0
    lines = [image["values"] for image in host.images[1:-1]]
    assert np.allclose(sum(lines), total, rtol=1e-4, atol=1e-6 * total.max())
    colour = host.images[-1]
    assert colour["name"].startswith("Colour") and np.array_equal(colour["values"], total)
    rgb = colour["rgb"]
    assert rgb.shape == (12, 16, 3) and rgb.min() >= 0.0 and rgb.max() <= 1.0 and rgb.max() > 0.5
    assert not rgb[total == 0].any()                            # dark stays dark
    # the script's picture is this image, the top row first
    assert np.allclose(rgb, pt_colour.develop(np.stack(lines), scene.nm, scene.white), atol=2e-3)
assert len(set(names)) == 4

print("pathtracer examples ok")
