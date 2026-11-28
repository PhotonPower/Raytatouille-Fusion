"""Materials as blocks of the node workflow (Raytatouille Fusion ADR 0011, stage M2).

Blocks with data sockets only (no light), of the data type `bsdf` (rtt_fusion.material.Bsdf):

  pathtracer.bsdf_file      a .bsdf file (simulated or measured)
  pathtracer.bsdf_analytic  Lambert or the GGX conductor ("metal"), on a grid of its own
  pathtracer.bsdf_mix       (1 − weight) a + weight b, on the grids of a
  pathtracer.material       a material of the Path Tracer: a name for the BSDF at its input

The plugin provides them to the workflow (`provider`), and when it computes it collects the
material blocks of the document's workflow itself (`workflow_materials`): reading a file or making
an analytic table is cheap, so it needs no engine run. A material block's name is what the
attribute pt.material of CAD objects refers to, next to the names of the panel's table.

The block previews draw a sphere in the material, lit by a sun and a sky (`preview`)."""

from __future__ import annotations

import math

import numpy as np

import pt_colour
import pt_table

PREFIX = "pathtracer."
FILE, ANALYTIC, MIX, MATERIAL = (PREFIX + t for t in ("bsdf_file", "bsdf_analytic", "bsdf_mix", "material"))
BSDF_TYPES = (FILE, ANALYTIC, MIX)
TYPES_ALL = BSDF_TYPES + (MATERIAL,)


class BlockError(ValueError):
    """A block that cannot give its BSDF (the message names the block)."""


def _material_module():
    from rtt_fusion import material
    return material


def available() -> bool:
    """Whether the installed RTT-Fusion knows BSDFs as data of the workflow (from 0.5.x with R36b)."""
    try:
        from rtt_fusion.graph.model import DATA_TYPES
        _material_module()
    except ImportError:
        return False
    return "bsdf" in DATA_TYPES


# ------------------------------------------------------------------------------- the BSDFs
def parse_values(text: str) -> tuple[list[float], list[float]] | float:
    """A number, or pairs "nm:value, nm:value" (a spectrum): (wavelengths in nm, values)."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("a value is needed (a number, or nm:value pairs)")
    if ":" not in text:
        return float(text)
    pairs = sorted((float(a), float(b)) for a, b in (p.split(":") for p in text.replace(";", ",").split(",") if p.strip()))
    return [nm for nm, _ in pairs], [v for _, v in pairs]


def analytic(params: dict):
    """The BSDF of a pathtracer.bsdf_analytic block."""
    mt = _material_module()
    model = str(params.get("model", "lambert")).strip().lower()
    step = float(params.get("step", 2.0))
    if not 0.5 <= step <= 15:
        raise ValueError("step: 0.5 … 15 degrees")
    values = parse_values(params.get("value", "0.8"))
    if isinstance(values, float):
        nm, value = np.array([550.0]), values
    else:
        nm = np.asarray(values[0])
        value = mt.Spectrum(nm / 1000.0, np.asarray(values[1]))
    grid = (nm / 1000.0, np.deg2rad(np.arange(0.0, 90.0, 5.0)), np.deg2rad(np.linspace(0, 90, round(90 / step) + 1)),
            np.deg2rad(np.linspace(0, 180, round(180 / step) + 1)))
    if model == "lambert":
        return mt.lambert(value, *grid)
    if model in ("metal", "ggx", "ggx metal", "ggx_conductor"):
        return mt.ggx_conductor(value, float(params.get("roughness", 0.3)), *grid, sub=4)
    raise ValueError(f"model {model!r}: lambert or metal")


def bsdf_of(node: dict, inputs: dict):
    """The BSDF a bsdf block gives, from its parameters and its inputs (socket -> BSDF or None)."""
    mt = _material_module()
    kind, params = node.get("type"), node.get("params") or {}
    if kind == FILE:
        path = str(params.get("file", "")).strip()
        if not path:
            raise ValueError("no file chosen")
        return mt.load(path)
    if kind == ANALYTIC:
        return analytic(params)
    if kind == MIX:
        a, b = inputs.get("a"), inputs.get("b")
        if a is None or b is None:
            raise ValueError("both inputs a and b need a BSDF")
        return mt.mix(a, b, float(params.get("weight", 0.5)))
    raise ValueError(f"not a BSDF block: {kind}")


# ------------------------------------------------------------------- blocks for the workflow
def node_types() -> list:
    from rtt_fusion.graph.model import Category, NodeType, ParamSpec, data_in, data_out
    out = data_out("bsdf", "bsdf", "BSDF")
    return [
        NodeType(FILE, Category.DATA, (out,), (
            ParamSpec("file", "file", "", label="BSDF file", description="a .bsdf file (rtt_fusion.material)"),),
            description="A BSDF from a .bsdf file – simulated (SpeckleBem, hp-FEM) or measured"),
        NodeType(ANALYTIC, Category.DATA, (out,), (
            ParamSpec("model", "choice", "lambert", options=("lambert", "metal"), label="Model",
                      description="lambert: matt; metal: GGX microfacets (the material metal)"),
            ParamSpec("value", "text", "0.8", label="Reflectance",
                      description="a number, or nm:value pairs (450:0.2, 550:0.8, 650:0.9)"),
            ParamSpec("roughness", "number", 0.3, minimum=0.01, maximum=1.0, label="Roughness",
                      description="metal: GGX width roughness²"),
            ParamSpec("step", "number", 2.0, unit="°", minimum=0.5, maximum=15.0, label="Bin size",
                      description="of the table over the outgoing directions"),),
            description="A BSDF from a model: Lambert or the GGX conductor"),
        NodeType(MIX, Category.DATA, (data_in("a", "bsdf", "a"), data_in("b", "bsdf", "b"), out), (
            ParamSpec("weight", "number", 0.5, minimum=0.0, maximum=1.0, label="Share of b"),),
            through=(("bsdf", ("a", "b")),),
            description="(1 − share) a + share b, on the grids of a"),
        NodeType(MATERIAL, Category.DATA, (data_in("bsdf", "bsdf", "BSDF"),), (
            ParamSpec("name", "text", "", label="Material name",
                      description="what the attribute pt.material of objects refers to (empty: the block's name)"),),
            description="A material of the Path Tracer from the BSDF at its input"),
    ]


def _evaluate(ctx, node, socket, inputs):
    """Evaluator of the bsdf blocks for the engine: inputs are lists of values ([] unconnected)."""
    def first(v):
        if isinstance(v, list):
            return v[0] if v else None
        return v
    return bsdf_of({"type": node.type_id, "params": dict(node.params)},
                   {k: first(v) for k, v in inputs.items()})


_evaluate.representations = frozenset()  # no light


def _material_sink(ctx, node, socket, inputs):
    return None


_material_sink.representations = frozenset()


def provider():
    """The BlockProvider of these blocks (None without a suitable RTT-Fusion)."""
    if not available():
        return None
    from rtt_fusion.graph.remote import BlockProvider
    return BlockProvider(node_types(), {FILE: _evaluate, ANALYTIC: _evaluate, MIX: _evaluate, MATERIAL: _material_sink})


# --------------------------------------------------------------- the document's materials
def _containers(model: dict):
    """(nodes, links) of the model and of the active variant of every group in it."""
    yield model.get("nodes", []), model.get("links", [])
    for n in model.get("nodes", []):
        if "variants" in n:
            inner = (n.get("variants") or {}).get(n.get("variant"), {})
            yield from _containers(inner)


def material_name(node: dict) -> str:
    return str((node.get("params") or {}).get("name") or node.get("name") or node.get("id")).strip()


def _resolve(node: dict, nodes: dict, links: list, memo: dict, stack: tuple = ()):
    """The BSDF at the output of a bsdf block, its inputs followed through the links."""
    nid = str(node.get("id"))
    if nid in memo:
        return memo[nid]
    if nid in stack:
        raise BlockError(f"block {nid}: its inputs go round in a circle")
    inputs = {}
    for link in links:
        to = link.get("to") or []
        if len(to) == 2 and str(to[0]) == nid:
            src = nodes.get(str((link.get("from") or [None])[0]))
            if src is not None and src.get("type") in BSDF_TYPES and not src.get("muted"):
                inputs[str(to[1])] = _resolve(src, nodes, links, memo, stack + (nid,))
    try:
        memo[nid] = bsdf_of(node, inputs)
    except BlockError:
        raise
    except Exception as e:  # noqa: BLE001 – the user's data: say which block
        raise BlockError(f"block {node.get('name') or nid} ({node.get('type')}): {e}") from None
    return memo[nid]


def has_materials(workflow: dict | None) -> bool:
    """Whether the workflow has material blocks (not muted) – without computing them."""
    model = (workflow or {}).get("model") or {}
    return any(n.get("type") == MATERIAL and not n.get("muted") for ns, _ in _containers(model) for n in ns)


def workflow_materials(workflow: dict | None) -> dict:
    """The materials of the workflow's pathtracer.material blocks (not muted): name -> BSDF.
    BlockError when a block cannot give its BSDF or two have the same name."""
    out: dict = {}
    model = (workflow or {}).get("model") or {}
    for nodes_list, links in _containers(model):
        nodes = {str(n.get("id")): n for n in nodes_list}
        memo: dict = {}
        for n in nodes_list:
            if n.get("type") != MATERIAL or n.get("muted"):
                continue
            name = material_name(n)
            source = next((nodes.get(str((lk.get("from") or [None])[0])) for lk in links
                           if (lk.get("to") or [None])[0] == n.get("id") and (lk.get("to") or [None, None])[1] == "bsdf"),
                          None)
            if source is None or source.get("type") not in BSDF_TYPES:
                raise BlockError(f"material block {name!r}: no BSDF block is connected to its input")
            if name in out:
                raise BlockError(f"two material blocks are called {name!r}")
            out[name] = _resolve(source, nodes, links, memo)
    return out


def table_of(bsdf) -> dict:
    """The arrays of a BSDF for pt_table.Table (wavelengths in nm)."""
    return {"nm": bsdf.wavelength * 1000.0, "theta_in": bsdf.theta_in, "theta_edges": bsdf.theta_edges,
            "phi_edges": bsdf.phi_edges, "reflectance": bsdf.reflectance, "transmittance": bsdf.transmittance,
            "brdf": bsdf.brdf, "btdf": bsdf.btdf,
            "index_behind": None if bsdf.index_behind is None else bsdf.index_behind.at(bsdf.wavelength)}


# ------------------------------------------------------------------------------- previews
def sphere_colours(bsdf, cells: int = 40):
    """sRGB (0 … 1) of the visible cells of a sphere in the material, and their squares
    (x0, y0, x1, y1 in −1 … 1): lit by a white sun (from the upper left, behind the viewer) with
    irradiance 2.5 and a white sky of radiance 0.12 above the horizon and 0.02 below; seen from +z."""
    table = pt_table.Table.from_dict(table_of(bsdf))
    # white light over the visible range (the table linear between its wavelengths); one
    # wavelength only: grey
    nm = np.arange(400.0, 701.0, 10.0) if table.nm.size > 1 else table.nm
    table.at_channels(nm)
    edge = np.linspace(-1, 1, cells + 1)
    cx = 0.5 * (edge[:-1] + edge[1:])
    x, y = np.meshgrid(cx, cx[::-1])
    inside = x * x + y * y < 1
    x, y = x[inside], y[inside]
    n = np.stack([x, y, np.sqrt(1 - x * x - y * y)], axis=1)
    v = np.tile([0.0, 0.0, 1.0], (len(n), 1))
    sun = np.array([-0.45, 0.6, 0.66]) / np.linalg.norm([-0.45, 0.6, 0.66])
    s = np.tile(sun, (len(n), 1))
    cos_s = np.clip(n @ sun, 0.0, None)
    r = 2 * n[:, 2:3] * n - v                              # mirror direction of the view
    sky = np.where(r[:, 1] > 0, 0.12, 0.02)
    sky = sky + np.where(r @ sun > math.cos(math.radians(4)), 60.0, 0.0)   # the sun in the mirror
    channels = []
    for c in range(len(nm)):
        cc = np.full(len(n), c, dtype=np.int64)
        f = table.f(n, s, v, cc)
        rr, _, sr, _, _, _ = table.energies(n[:, 2], cc)
        channels.append(2.5 * f * cos_s + sr * 0.07 + rr * sky)
    channels = np.array(channels)
    if len(nm) == 1:
        grey = channels[0]
        rgb = np.stack([grey, grey, grey], axis=1)
    else:
        weights = pt_colour.table(nm)
        rgb = channels.T @ weights if weights is not None else np.repeat(channels.mean(axis=0)[:, None], 3, axis=1)
    rgb = np.clip(rgb / 0.9, 0.0, None)
    rgb = rgb / (1 + rgb)                                  # soft roll-off into white
    srgb = np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)
    half = 1.0 / cells
    squares = np.stack([x - half, y - half, x + half, y + half], axis=1)
    return np.clip(srgb, 0.0, 1.0), squares


def preview(request: dict) -> dict:
    """The answer to a block preview: a sphere in the BSDF of the block (for a material block:
    of the block at its input)."""
    from nfcad import drawing as dr
    node = request.get("node") or {}
    model = request.get("model") or {}
    try:
        nodes_list, links = next(((ns, ls) for ns, ls in _containers(model)
                                  if any(str(m.get("id")) == str(node.get("id")) for m in ns)),
                                 (model.get("nodes", []), model.get("links", [])))
        nodes = {str(m.get("id")): m for m in nodes_list}
        nodes[str(node.get("id"))] = node                  # the values in the dialog
        if node.get("type") == MATERIAL:
            src = next((nodes.get(str(lk["from"][0])) for lk in links if lk.get("to", [None])[0] == node.get("id")), None)
            if src is None:
                return dr.unsupported("connect a BSDF block to the material's input")
            node = src
        bsdf = _resolve(node, nodes, links, {})
        rgb, squares = sphere_colours(bsdf)
    except Exception as e:  # noqa: BLE001
        return dr.unsupported(str(e))
    d = dr.Drawing("Material", unit="", axes=None)
    for (x0, y0, x1, y1), (red, green, blue) in zip(squares.tolist(), rgb.tolist()):
        d.polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                  fill="#%02x%02x%02x" % (round(255 * red), round(255 * green), round(255 * blue)))
    d.note("lit by a sun from the upper left and a sky")
    return dr.answer(d)
