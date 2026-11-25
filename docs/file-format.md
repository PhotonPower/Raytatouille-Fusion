# Document format `.rttf`

Documents are saved with the extension **`.rttf`** (Raytatouille Fusion file). Files with the
extension `.nfcad` from before 1.0 have the same content and are still opened; *Save As*
offers them as `.rttf`. Inside, the format is still called `"nfcad"`.

Version 2 (P1; version 1 files are still read). UTF-8 JSON, written atomically (`QSaveFile`).
Units: millimetres.
Geometry is stored exactly: degrees, knot vectors, control points and weights – no tessellation.

```json
{
  "format": "nfcad",
  "version": 1,
  "units": "mm",
  "layers":   [ { "id": 0, "name": "Default", "color": "#bec6d2", "visible": true },
                { "id": 1, "name": "Mounts", "color": "#78a0dc", "visible": true, "locked": true } ],  // "locked": optional
  "current_layer": 1,                            // optional (missing: 0, Default)
  "groups":   [ { "id": 1, "name": "objective", "parent": 0, "visible": true } ],   // v2
  "entities": [ { "id": "1", "name": "part_0_0", "layer": 0, "visible": true,
                  "color": "#ff0000",            // optional, default: layer colour
                  "group": 1,                    // v2, optional (0 / missing: top level)
                  "attributes": { "rtt.role": "mirror", "sim.inactive": true },   // v2, optional
                  "geometry": { "type": "shell", "faces": [ ... ] } } ],
  "plugins":  { "demo": { "params": { "rays": 300, "origin": [0, 0, 0] } } },  // v2, optional
  "workflow": { "model": { "format": "rtt-fusion-graph", "version": 2, ... }, "types": [], "diagnostics": [], "plan": {} },  // v2, optional
  "results":  [ { "key": "workflow:Kamerabild", "name": "Kamera", "kind": "image", "stamp": "3f1c…",
                  "image": { "width": 512, "height": 512, "values": "<base64>", "extent": [-1, 1, -1, 1], ... } } ]  // v2, optional
}
```

| `type` | Fields |
|---|---|
| `point` | `point`: [x, y, z] |
| `curve` | `degree`, `knots`, `points` (flat x, y, z list), `weights` (omitted if all 1) |
| `surface` | `degree_u`, `degree_v`, `knots_u`, `knots_v`, `num_u`, `num_v`, `points` (row-major, i along u), `weights` |
| `trimmed_surface` | `surface`, `outer` and `holes` (lists of 2D curves in parameter space, z = 0; omitted if untrimmed), `label` |
| `shell` | `faces`: list of trimmed surfaces; topology (edges, vertices) is rebuilt by sewing on load |

Layer `0` is *Default*; it is always there (added when a file lacks it). `locked` (optional,
written only when true) keeps the layer's objects visible but out of selection. `current_layer`
(optional, written only when it is not 0) is the layer new objects go to; an unknown id falls back
to 0. Both came after 1.0 within version 2: older readers ignore them (and leave them out when they
save), and files without them load as before – no layer locked, Default current. Visibility (`visible` of layers, groups and
entities), the lock and the current layer are saved with the document: changing them marks it
modified, although they are not undo steps.

Groups form the model tree (`parent` 0 = top level). Attributes are free key / value data
(strings, numbers, booleans); plugins use namespaced keys (`rtt.*`), `sim.inactive = true`
excludes an object from computations ([plugins.md](plugins.md), D11).

`plugins` holds the values of each plugin's parameter panel by plugin id (P4,
[plugin-api.md](plugin-api.md)); readers that do not know a plugin keep its entry unchanged.

`workflow` holds the node workflow as a model of RTT-Fusion (`rtt-fusion-graph` version 2:
blocks with ports, connections, branches, groups), with the block library, the diagnostics and
the plan of the last check. Older documents may hold a socket graph instead (`"graph"`, version
1): when such a document is opened, the Workflow plugin converts it into a model (*Convert to
model*, RTT-Fusion 0.5.1 or newer); the document is then modified and is saved with the model.
Without the plugin the graph is kept unchanged and the node editor only says so. Raytatouille
Fusion writes no version 1.

`results` keeps the newest result of every keyed display window, e.g. `workflow:<block>`, the
display blocks of the node workflow. It holds images, curves, tables and bars, each with the
fingerprint (`stamp`) of what the producer computed it from. Number arrays are stored as base64
of their little-endian bytes: float32 for image values, float64 for curves and bars, bytes for
colours. When the document is opened they come back as the result set "Saved results". The
workflow engine compares the fingerprints with what it would compute now: an unchanged display
counts as up to date, and a run does not compute it again. Readers that do not know the section
skip it.

Entity ids are strings (64-bit). Readers reject newer versions and invalid geometry with a
message; the document is unchanged in that case.

Planned: binary blocks for large control nets (version 2), stored B-rep topology instead of
re-sewing, units other than mm.
