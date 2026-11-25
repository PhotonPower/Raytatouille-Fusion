"""Workflow engine of Raytatouille Fusion (ADR 0010, stage W1).

Checks, plans and runs the node workflow of the document (RTT-Fusion): the model's branches are
unrolled, only what the display blocks need is computed, results of earlier runs are kept
(R23), the blocks get their state (up to date / out of date) and every display block's view
becomes a result with the key "workflow:<block>". It knows no kernel: the blocks' data come with
the workflow (ADR "Bidirektionale Ports, Posen, Äste und Gruppen", Nachtrag 1) – a Raytatouille
system, for example, from the data of the `rtt.*` blocks and its glass catalogues from the
source's `rtt_catalogs`, written by the Raytracer plugin. Until stage W3 the blocks of all kernels
are evaluated in this process (RTT-Fusion's evaluators).
"""

from __future__ import annotations

import hashlib
import importlib
import math
import re
import tempfile
from pathlib import Path

from nfcad import Param, Plugin, UserError, action


def rings_for(rays: int) -> int:
    """Hexapolar rings r whose 1 + 3 r (r + 1) rays come closest to `rays` (at least 1 ring)."""
    r = (-3 + math.sqrt(max(9 + 12 * (rays - 1), 0))) / 6
    lo, hi = max(1, math.floor(r)), max(1, math.ceil(r))

    def count(k: int) -> int:
        return 1 + 3 * k * (k + 1)

    return lo if abs(count(lo) - rays) <= abs(count(hi) - rays) else hi


def _fusion():
    try:
        workflow = importlib.import_module("rtt_fusion.graph.workflow")
        fg = importlib.import_module("rtt_fusion.graph")
        execute = importlib.import_module("rtt_fusion.graph.execute")
        io = importlib.import_module("rtt_fusion.graph.io")
    except ImportError as e:
        raise UserError("The node workflow needs the Python package rtt_fusion (RTT-Fusion with the "
                        "module graph.workflow) in the plugin environment: pip install -e <RTT-Fusion>") from e
    return workflow, fg, execute, io


#: the Raytracer plugin's folder: its process resolves a catalogue named without a folder there
_RAYTRACER = Path(__file__).resolve().parents[1] / "raytracer"


def _raytracer_catalogues(ctx) -> list[str]:
    """The glass catalogues of the Raytracer panel, as the Raytracer finds them: the listed files
    (one without a folder next to the system file or in the Raytracer's folder) and *.agf next to
    the system file and in its folder "catalogs". One place for the catalogues: the workflow
    stores what the Raytracer uses. [] without `ctx.plugin_params` (an older CAD)."""
    if not hasattr(ctx, "plugin_params"):
        return []
    try:
        params = ctx.plugin_params("raytracer")
    except Exception:  # noqa: BLE001 - no Raytracer: only what the workflow holds
        return []
    system = Path(str(params.get("system") or "")).expanduser()
    folder = system.parent if system.is_absolute() else None
    out: list[str] = []
    for name in params.get("catalogs") or []:
        path = Path(str(name)).expanduser()
        if not path.is_absolute():
            candidates = [d / path for d in (folder, _RAYTRACER) if d is not None]
            path = next((c for c in candidates if c.is_file()), candidates[-1])
        out.append(str(path.resolve()))
    if folder is not None and folder.is_dir():
        out += [str(p.resolve()) for p in sorted(folder.glob("*.agf")) + sorted((folder / "catalogs").glob("*.agf"))]
    return list(dict.fromkeys(out))


def _link_target(key: str) -> str:
    """The block a link key "a.out -> b.in" leads to."""
    return key.split(" -> ", 1)[-1].rsplit(".", 1)[0]


#: diagnostics of the spectrum conversions in the run's log (RTT-Fusion R30a–R30d): "<where>: <code>: <text>"
_RUN_CODES = re.compile(r"^(?P<where>.*?):\s+(?P<code>exec\.spectrum_[a-z_]+):\s*(?P<message>.*)$", re.S)

#: what each representation is, for the status line and the log
REPRESENTATIONS = {"R": "rays", "H": "fields", "S": "plane-wave spectra", "G": "gridded fields",
                   "T": "tables", "P": "radiometric rays"}


def run_notes(lines) -> list[dict]:
    """The warnings of the spectrum conversions (`exec.spectrum_cut`, `exec.spectrum_rays`, …) in
    an executor's log, as diagnostics {"code", "severity", "location", "message"}: the location
    is a link key ("a.out -> b.in") or a block, as the line names it. A line that repeats one
    already listed counts once."""
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for line in lines:
        m = _RUN_CODES.match(str(line))
        if m is None:
            continue
        where = m["where"].split(": ")[0].strip()  # a block's note on a link: the link
        key = (m["code"], where, m["message"].strip())
        if key in seen:
            continue
        seen.add(key)
        out.append({"code": key[0], "severity": "warning", "location": where, "message": key[2]})
    return out


def error_note(error) -> dict | None:
    """A run's `exec.spectrum_*` error (an ExecutionError with code and location) as a diagnostic."""
    code = str(getattr(error, "code", ""))
    if not code.startswith("exec.spectrum_"):
        return None
    where = str(getattr(error, "location", ""))
    text = str(error)
    text = text.removeprefix(f"{code}: ")
    if where:
        text = text.removesuffix(f" ({where})")
    return {"code": code, "severity": "error", "location": where, "message": text}


def notes_summary(notes: list[dict]) -> str:
    """One line for the status bar: how many notes, the first one shortened."""
    if not notes:
        return ""
    first = notes[0]
    text = first["message"]
    if len(text) > 90:
        text = text[:87].rstrip() + "…"
    more = f" (+{len(notes) - 1} more)" if len(notes) > 1 else ""
    return f"spectra: {first['code']} at {first['location']}: {text}{more} – marked at the link, details in the log"


def with_notes(plan: dict, notes: list[dict], model_id=None, per_connection=None) -> dict:
    """The plan with the run's notes at the links (`links[key]["notes"]`), at the blocks
    (`node_notes[block]`, a block of the model with `model_id`) and – with `per_connection`
    (link key -> text) -> {connection: {direction: text}} – at the connections of a model
    (`connections_notes`). Lines "code: message"; the plan itself is not changed."""
    if not notes or not plan:
        return plan
    out = {**plan, "links": {k: dict(v) for k, v in plan.get("links", {}).items()}}
    on_links: dict[str, list[str]] = {}
    on_nodes: dict[str, list[str]] = {}
    for d in notes:
        line = f"{d['code']}: {d['message']}"
        where = d["location"]
        if " -> " in where:
            on_links.setdefault(where, []).append(line)
        elif where:
            block = model_id(where) if model_id is not None else where
            on_nodes.setdefault(block, []).append(line)
    for key, lines in on_links.items():
        if key in out["links"]:
            out["links"][key]["notes"] = lines
    if on_nodes:
        out["node_notes"] = on_nodes
    if per_connection is not None and on_links:
        try:
            out["connections_notes"] = {
                c: {side: text.split("\n") for side, text in sides.items()}
                for c, sides in per_connection({k: "\n".join(v) for k, v in on_links.items()}).items()}
        except Exception:  # noqa: BLE001 - only a hint at the connections
            pass
    return out


def _evaluators(extra: dict) -> dict:
    """RTT-Fusion's evaluators: the Raytatouille backend when raytatouille is installed, and the
    ones of the optional modules."""
    try:
        backend_rtt = importlib.import_module("rtt_fusion.graph.backend_rtt")
        base = dict(backend_rtt.EVALUATORS)
    except ImportError:
        base = {}
    return {**base, **extra}


def _discard(cache, key: str) -> None:
    """Removes one result from the executor's cache (RTT-Fusion's ResultCache, which has no
    method for it yet)."""
    if cache is None:
        return
    discard = getattr(cache, "discard", None)
    if discard is not None:
        discard(key)
        return
    items = getattr(cache, "_items", None)
    if items is not None and key in items:
        _, size = items.pop(key)
        cache.size_bytes -= size


#: types the engine runs without an evaluator of their own (a junction adds what arrives; a group
#: is unrolled into its blocks)
_STRUCTURAL = frozenset({"fusion.sum", "group"})


def _runnable_only(wf: dict, blocks, evaluators: dict) -> dict:
    """The block library without the types nothing in this installation can compute (a planned
    type, or the block of a plugin that is not loaded), and a warning on each such block in the
    workflow – so it shows at Check instead of stopping a run. Types the workflow uses stay in the
    library (the editor draws the blocks from it)."""
    runnable = set(evaluators) | _STRUCTURAL
    nodes = list(getattr(blocks, "nodes", {}).values()) if blocks is not None else []
    used = {n.type_id for n in nodes}
    out = dict(wf)
    if out.get("types"):
        out["types"] = [t for t in out["types"] if t.get("type") in runnable or t.get("type") in used]
    warnings = [
        {"code": "check.no_evaluator", "severity": "warning", "location": n.id,
         "message": f"{n.type_id} cannot be computed in this installation (no evaluator: a planned block "
                    "type, or its plugin is not loaded) – a run that needs this block stops"}
        for n in nodes if n.type_id not in runnable and not getattr(n, "muted", False)
    ]
    if warnings:
        out["diagnostics"] = [*(out.get("diagnostics") or []), *warnings]
    return out


class WorkflowEngine(Plugin):
    params = {
        "rays": Param.integer(20_000, min=7, max=500_000, label="Rays per field and wavelength",
                              description="Ray sources of the workflow (coherent image; every ray path is "
                                          "recorded, so memory grows with rays × events)"),
        "pixels": Param.integer(512, min=16, max=4096, label="Pixels (long side)"),
        "window": Param.number(0.0, min=0.0, label="Image window (half width, mm)",
                               description="0: each detector's own size. For a focus computed as a field "
                                           "(link into the camera set to H) a small window, e.g. 0.05 mm"),
        "gaussian_waist": Param.number(0.0, min=0.0, max=10.0, label="Gaussian illumination (w / pupil radius)",
                                       description="0: uniform (a hard-edged beam, whose Fresnel diffraction a "
                                                   "field link shows); e.g. 0.5 for a laser beam"),
        "auto_fields": Param.boolean(True, label="Wave optics near a focus (automatic)",
                                     description="A detector on a link left on auto checks whether the rays cross "
                                                 "or focus near it (Fieldtracing's caustic rule with ε below) and "
                                                 "then computes fields from the last surface on, as if the link "
                                                 "were set to H; elsewhere it keeps rays. A link set to R or H "
                                                 "keeps its setting. Needs fieldtracing"),
        "field_tolerance": Param.number(0.02, min=0.001, max=0.2, label="Field accuracy ε (H links)",
                                        description="Allowed error of a field propagation (link set to H), relative "
                                                    "to the peak amplitude: Fieldtracing takes the cheapest method "
                                                    "within it. 0.02 is its default; near a focus 0.05 often lets "
                                                    "Debye (seconds) through instead of Rayleigh–Sommerfeld "
                                                    "(minutes to hours); the log names the method and its error"),
    }

    def __init__(self):
        self._portdata = tempfile.TemporaryDirectory(prefix="nfcad-portdata-")  # remote blocks (D4)
        self._cache = None
        #: what blocks used at run time on links on "auto" (link key -> representation, reason):
        #: shown at the link (R→H) while the block's result is up to date
        self._used = {}
        #: the warnings of the spectrum conversions in the runs (exec.spectrum_*), kept like `_used`
        self._run_notes: list[dict] = []
        self._ran = set()
        self._notes: list[str] = []
        self._model_ids: set[str] | None = None
        self._failures: list[str] = []

    def preview_block(self, request: dict) -> dict:
        """The overview drawing of an ideal-optics block or a particle (workflow_preview)."""
        import workflow_preview

        return workflow_preview.preview(request)

    def _blocks(self, ctx, registry) -> tuple[dict, dict]:
        """The other plugins' block types in `registry` (ADR 0010, D2/D3): their evaluators (a
        request each) and the providers by type {"plugin", "version"}."""
        try:
            remote = importlib.import_module("rtt_fusion.graph.remote")
        except ImportError:
            return {}, {}
        try:  # no routing (an older CAD, a test host): no other plugins' blocks
            catalogues = ctx.block_catalogues() if hasattr(ctx, "block_catalogues") else []
        except RuntimeError as e:
            ctx.log(f"blocks of other plugins: {e}")
            catalogues = []
        try:  # a detector with another plugin's block on its path (a grating) computes here
            evaluators = remote.register_remote(registry, catalogues, ctx.evaluate_block, self._portdata.name,
                                                local=_evaluators({}))
        except TypeError:  # an RTT-Fusion before #82
            evaluators = remote.register_remote(registry, catalogues, ctx.evaluate_block, self._portdata.name)
        providers = {str(e["type"]["type"]): {"plugin": str(e["provider"]), "version": str(e.get("version", ""))}
                     for e in catalogues}
        return evaluators, providers

    @staticmethod
    def _embed(ctx, workflow, model) -> tuple[bool, list]:
        """The files blocks name (a grating's FourierGrating configuration or Jones table, a
        stack's configuration) stored in the blocks, so the document computes on any machine
        (RTT-Fusion W75): (anything stored, what could not be read as diagnostics). Nothing with
        an older RTT-Fusion."""
        embed = getattr(workflow, "embed_files", None)
        if embed is None:
            return False, []
        added = _raytracer_catalogues(ctx)
        if added:  # the Raytracer panel's glass catalogues go to the sources, which store them
            for node in model.nodes.values():
                if node.type_id == "rtt.source":
                    node.params["rtt_catalogs"] = list(dict.fromkeys([*(node.params.get("rtt_catalogs") or []),
                                                                      *added]))
        done = embed(model)
        for line in done.stored:
            ctx.log(line)
        return bool(done.stored), [dict(d.__dict__) for d in done.diagnostics]

    @staticmethod
    def _document(workflow, model, registry, wf, providers):
        try:  # with the provider records (ADR 0010, D7)
            return workflow.model_document(model, registry, None, workflow.kept_fields(wf), providers,
                                           wf.get("providers") or {})
        except TypeError:  # RTT-Fusion before W2c
            return workflow.model_document(model, registry, None, workflow.kept_fields(wf))

    @staticmethod
    def _require_model(wf: dict) -> None:
        """Check and Run work on a model (version 2); an old socket graph (version 1) is converted
        when CAD opens the document – here only if that was not possible."""
        if wf.get("model"):
            return
        if wf.get("graph"):
            raise UserError("The node workflow is an old socket graph (version 1). Convert to model makes "
                            "it a model (CAD does that when it opens the document; it needs RTT-Fusion 0.5.1 "
                            "or newer in the plugin environment).")
        raise UserError("No node workflow yet – a plugin makes one (Raytracer: Workflow from system, "
                        "New Raytatouille system).")

    # ------------------------------------------------------------------ convert
    @action("Convert to model", description="An old socket graph (version 1, e.g. written by a script) as a "
                                            "model: ports, connections and branches. CAD runs it when it "
                                            "opens such a document; saving then writes version 2")
    def convert_to_model(self, ctx):
        workflow, fg, _, io = _fusion()
        wf = ctx.workflow()
        if wf.get("model"):
            raise UserError("The node workflow is a model already.")
        if not wf.get("graph"):
            raise UserError("No node workflow yet – a plugin makes one (Raytracer: Workflow from system, "
                            "New Raytatouille system).")
        registry, _ = workflow.registry()
        _, providers = self._blocks(ctx, registry)
        try:
            model = fg.model_from_graph(io.from_dict(wf["graph"]), registry)
        except ValueError as e:
            raise UserError(f"This graph cannot become a model:\n{e}") from e
        rest = {k: v for k, v in wf.items() if k != "graph"}
        ctx.set_workflow({**rest, **self._document(workflow, model, registry, rest, providers)})
        self._model_ids = set(model.nodes)
        return (f"old workflow (version 1) converted to a model: {len(model.nodes)} blocks, "
                f"{len(model.connections)} connections, {len(model.branches)} branches "
                f"({', '.join(b.name for b in model.branches)}) – saving writes version 2")

    # ------------------------------------------------------------------ check
    @action("Check workflow", description="Check the node workflow and mark problems; the plan per link")
    def check_workflow(self, ctx):
        workflow, fg, execute, io = _fusion()
        wf = ctx.workflow()
        self._require_model(wf)
        registry, extra = workflow.registry()
        remote, providers = self._blocks(ctx, registry)
        extra = {**extra, **remote}
        graph = None
        model = io.model_from_dict(wf["model"], registry)
        _, files = self._embed(ctx, workflow, model)
        wf = {**wf, **self._document(workflow, model, registry, wf, providers)}
        if not any(d["severity"] == "error" for d in wf["diagnostics"]):
            graph = fg.unroll(model, registry)
        self._model_ids = set(model.nodes)
        wf["diagnostics"] = list(wf["diagnostics"]) + files
        wf = _runnable_only(wf, model, _evaluators(extra))
        ex = None
        if graph is not None and not any(d["severity"] == "error" for d in wf["diagnostics"]):
            try:  # which blocks the kept results still cover
                ex = self._executor(ctx, graph, registry, _evaluators(extra), execute, wf)
                fresh = self._fresh(ex)
                wf["plan"] = self._plan_with_used(workflow, wf["plan"], graph, model, registry, fresh)
            except Exception as e:  # noqa: BLE001 - only a hint
                ctx.log(f"workflow state: {e}")
        wf["available"] = sorted(workflow.available())  # the editor offers these transports
        ctx.set_workflow(wf)
        if ex is not None:
            self._send_status(ctx, ex)
        diagnostics = wf["diagnostics"]
        n_err = sum(1 for d in diagnostics if d["severity"] == "error")
        for d in diagnostics:
            ctx.log(f"{d['severity']}: {d['code']} – {d['message']} ({d['location']})")
        planned = sorted(set(v["representation"] for v in wf["plan"].get("links", {}).values()))
        return (f"workflow: {n_err} error(s), {len(diagnostics) - n_err} warning(s); "
                f"planned {''.join(planned) or '–'}, {len(wf['plan']['conversions'])} conversion(s)")

    # ------------------------------------------------------------------ run
    @action("Run workflow", description="Compute what the display blocks of the node workflow show: camera "
                                         "images, sweep curves, beam probes; links set to H as fields")
    def run_workflow(self, ctx):
        return self._run(ctx)

    @action("Recompute", description="Compute this block and everything behind it again, also where the "
                                     "shown result counts as up to date (e.g. one the document kept from "
                                     "an older version of a plugin)", block_types=("*",))
    def recompute_block(self, ctx):
        block = str(ctx.target.get("block", ""))
        if not block:
            raise UserError("Recompute: no block named.")
        return self._run(ctx, "/".join([*(str(g) for g in ctx.target.get("scope", [])), block]))

    def _run(self, ctx, force: str | None = None):
        """Run the displays; `force`: a block of the model (path "group/…/block") whose results and
        those of everything behind it are computed again, kept or cached ones dropped."""
        workflow, fg, execute, io = _fusion()
        wf = ctx.workflow()
        self._require_model(wf)
        registry, extra = workflow.registry()
        remote, providers = self._blocks(ctx, registry)
        extra = {**extra, **remote}
        # RTT-Fusion R24: exactly the branches of the model, unrolled
        model = io.model_from_dict(wf["model"], registry)
        stored, files = self._embed(ctx, workflow, model)
        if stored:  # the files are in the document from now on (saved with it), and this run uses them
            wf = {**wf, **self._document(workflow, model, registry, wf, providers)}
            ctx.set_workflow(wf)
        self._log_files(ctx, files)
        try:
            graph = fg.unroll(model, registry)
        except fg.ModelError as e:
            for d in e.diagnostics:
                ctx.log(f"{d.severity}: {d.code} – {d.message} ({d.location})")
            raise UserError(f"The workflow has errors – Check workflow marks them: {e}") from e
        self._model_ids = set(model.nodes)
        self._require_data(graph)
        displays = [n for n in graph.nodes.values() if n.type_id.startswith("display.")]
        if not displays:
            raise UserError("Nothing to show: attach a display block (right-click on the canvas → Add block → "
                            "analysis → display.image / display.plot / display.beam) to a camera, a phase "
                            "shifter or a component output, then run again. Only what the displays need is "
                            "computed.")
        window = float(ctx.params.get("window", 0.0) or 0.0)
        if window > 0:
            for n in graph.nodes.values():
                if n.type_id in ("rtt.detector", "rtt.part.detector"):  # also a detector of the library
                    n.params["half_size"] = [window, window]
        source = next((n for n in graph.nodes.values() if n.type_id == "rtt.source"), None)
        name = str(((source.params.get("rtt_system") or {}).get("name") if source is not None else "") or "")
        run = ctx.result_set(f"Workflow {name or 'run'}")
        self._notes = []
        self._failures = []
        made, fresh = self._run_displays(ctx, run, graph, registry, _evaluators(extra), execute, wf, displays,
                                         force)
        ctx.workflow_running("")
        self._show_used(ctx, workflow, graph, model, registry, providers, fresh)
        if made:
            message = "workflow: " + ", ".join(made)
        else:  # the reason in the status line, not only in the log
            message = "workflow: nothing computed"
            if self._failures:
                message += " – " + self._failures[0]
                if len(self._failures) > 1:
                    message += f" (and {len(self._failures) - 1} more in the log)"
        if self._notes:  # shown in the status line, not only in the log
            message += " – warning: " + "; ".join(self._notes)
        return message

    @staticmethod
    def _log_files(ctx, files: list) -> None:
        for d in files:
            ctx.log(f"{d['severity']}: {d['code']} – {d['message']} ({d['location']})")

    @staticmethod
    def _require_data(graph) -> None:
        """Raytatouille blocks compute from the system their data make (S2); a workflow from before
        the data were kept cannot run without the system file, which the engine does not know."""
        rtt = [n for n in graph.nodes.values()
               if n.type_id.startswith("rtt.") and n.type_id != "rtt.source" and not n.type_id.startswith("rtt.part.")]
        has_system = any(n.type_id == "rtt.source" and "rtt_system" in n.params for n in graph.nodes.values())
        if rtt and (not has_system or any("rtt" not in n.params for n in rtt)):
            raise UserError("This workflow holds no Raytatouille system data (made before they were kept): run "
                            "Workflow from system once in the Raytracer plugin, then Run workflow again.")

    @staticmethod
    def _materials(wf: dict, log=None):
        """Raytatouille's material library with the glass catalogues of the source: those stored
        in the workflow (`rtt_catalog_data`) and the files the Raytracer wrote (`rtt_catalogs`).
        A catalogue that cannot be loaded is left out and reported to `log` – the glasses from it
        are then missing, which the system's check names. None without raytatouille."""
        try:
            rt = importlib.import_module("raytatouille")
        except ImportError:
            return None
        try:
            load = importlib.import_module("rtt_fusion.graph.embedded").load_catalogs
        except (ImportError, AttributeError):  # an RTT-Fusion before the stored catalogues
            load = None
        lib = rt.MaterialLibrary()
        for node in (wf.get("model") or {}).get("nodes", []):
            if node.get("type") != "rtt.source":
                continue
            params = node.get("params", {})
            if load is not None:
                problems = load(lib, params)
            else:
                problems = []
                for path in params.get("rtt_catalogs", []):
                    try:
                        lib.add_catalog(str(path))
                    except Exception as e:  # noqa: BLE001 - a missing catalogue should not stop the run
                        problems.append(f"glass catalogue {path}: {e}")
            for line in problems:
                if log is not None:
                    log(f"warning: {line}")
        return lib

    @staticmethod
    def _catalogues(wf: dict) -> list:
        """What the results depend on of the glass catalogues: the files and the stored ones (a
        hash of their content)."""
        for node in (wf.get("model") or {}).get("nodes", []):
            if node.get("type") == "rtt.source":
                params = node.get("params", {})
                held = [f"{c.get('name')}:{hashlib.sha1(str(c.get('base64', '')).encode()).hexdigest()[:12]}"
                        for c in params.get("rtt_catalog_data") or []]
                return list(params.get("rtt_catalogs", [])) + held
        return []

    def _hook(self, ctx, ex, a: float, b: float, workflow) -> None:
        """Progress of an executor (R21) into a part a … b of the job, the running block into the
        node editor; every report checks for Cancel."""
        last = {"node": None}

        def progress(part: float, text: str) -> None:
            ctx.check_cancel()
            ctx.progress(a + (b - a) * part, text)

        def on_node(node_id: str) -> None:
            self._ran.add(node_id)
            node_id = workflow.model_id(node_id)
            if node_id != last["node"]:
                last["node"] = node_id
                ctx.workflow_running(node_id)

        if hasattr(ex.context, "progress"):
            ex.context.progress = progress
            ex.context.on_node = on_node

    def _run_displays(self, ctx, run, graph, registry, evaluators, execute, wf, displays, force=None) -> list:
        """Display blocks (R21) and everything in front of them, in one executor (shared blocks are
        computed once); their views as results with the key "workflow:<block>", shown in the
        block's window (double-click). `force`: see `_run`."""
        workflow, _, _, _ = _fusion()
        made = []
        failed: list[dict] = []
        ex = self._executor(ctx, graph, registry, evaluators, execute, wf)
        self._ran = set()
        kept = self._kept(ctx)
        if force:
            again = self._forget(ex, force, [n.id for n in displays])
            if not again:
                raise UserError(f"No display shows a result of {force} – nothing to compute again.")
            kept = {k: v for k, v in kept.items() if k.removeprefix("workflow:") not in again}
            displays = [n for n in displays if n.id in again]
        for k, node in enumerate(displays):
            ctx.check_cancel()
            a, b = k / len(displays), (k + 1) / len(displays)
            self._hook(ctx, ex, a, b, workflow)
            ctx.progress(a, f"display: {node.name or node.id}")
            stamp = self._stamp(ex, node.id)
            if stamp and kept.get(f"workflow:{node.id}") == stamp:  # the shown result is up to date
                made.append(f"{node.name or node.id} (unchanged)")
                continue
            try:
                view = ex.evaluate(node.id, "view")
            except execute.ExecutionError as e:
                ctx.log(f"{node.name or node.id}: {e}")
                self._failures.append(f"{node.name or node.id}: {e}")
                if (failure := error_note(e)) is not None:
                    failed.append(failure)
                continue
            key = f"workflow:{node.id}"
            if view.kind == "image" and view.image is not None:
                ny, nx = view.image.values.shape
                note = str(getattr(view.image, "note", "") or "")  # RTT-Fusion W65: too few pixels
                # here the window is the engine's "Image window" (or more "Pixels")
                note = note.replace("set the detector's half size to", "set Image window (Workflow panel) to")
                note = note.replace("use more pixels", "raise Pixels (Workflow panel)")
                if note:
                    ctx.log(f"warning: {node.name or node.id}: {note}")
                    self._notes.append(f"{node.name or node.id}: {note}")
                elif float(view.image.values.max()) <= 0.0:
                    hint = ("switch on Wave optics near a focus (Workflow panel) or set the link into the camera "
                            "to H (right-click on the link → Transport → H), and choose a small image window"
                            if "H" in workflow.available() else
                            "install fieldtracing in the plugin environment, then set the link into the "
                            "camera to H")
                    ctx.log(f"{node.name or node.id}: dark – the light focuses into less than a pixel; {hint}")
                ctx.image(run, view.title, view.image.values.reshape(-1), nx, ny, extent=view.image.extent,
                          x_label=view.x_label, y_label=view.y_label, unit=view.unit,
                          description=f"{view.title}: {nx}×{ny} px", key=key, **self._stamped(ctx, stamp))
            else:
                for c in view.curves:
                    ctx.curve(run, f"{view.title}: {c.name}", c.x, c.y, x_label=view.x_label,
                              y_label=view.y_label, key=key, **self._stamped(ctx, stamp))
            made.append(f"{node.name or node.id}")
        for line in ex.context.log:
            ctx.log(line)
        cache = getattr(ex, "cache", None)
        for line in getattr(cache, "warnings", [])[-3:]:
            ctx.log(line)
        if cache is not None and hasattr(cache, "warnings"):
            cache.warnings.clear()
        used = getattr(ex.context, "used", None)
        if used is not None:  # the blocks computed now replace what they decided before
            self._used = {k: v for k, v in self._used.items() if _link_target(k) not in self._ran}
            self._used.update(used)
        notes = run_notes(ex.context.log) + failed
        self._run_notes = [d for d in self._run_notes if self._note_block(d) not in self._ran] + notes
        warnings = [d for d in notes if d["severity"] == "warning"]  # errors: already in the failures
        if warnings:  # shown in the status line and at the link
            self._notes.append(notes_summary(warnings))
        self._send_status(ctx, ex)
        try:
            fresh = self._fresh(ex)
        except Exception:  # noqa: BLE001 - only a hint
            fresh = set()
        return made, fresh

    @staticmethod
    def _forget(ex, block: str, displays: list) -> set:
        """Drops the cached results of `block` (a block of the model, "group/…/block") and of
        everything that depends on it on the way to `displays`; the displays that do (whose kept
        results are then not up to date either)."""
        ex.check()  # the plan is part of the keys
        start = {nid for nid in ex.graph.nodes
                 if nid.split("@")[0] == block or nid.split("@")[0].startswith(block + "/")}
        needed = {d: ex.needed([(d, "view")]) for d in displays}
        again = {d for d, deps in needed.items() if start & set(deps)}
        cache = getattr(ex, "cache", None)
        for d in again:
            for node_id, sockets in needed[d].items():
                for socket in sockets:
                    if start & set(ex.needed([(node_id, socket)])):
                        _discard(cache, ex._key(node_id, socket))
        return again

    @staticmethod
    def _fresh(ex) -> set:
        """The blocks (of the run's graph) whose results the cache holds."""
        shown = [(n.id, "view") for n in ex.graph.nodes.values() if n.type_id.startswith("display.")]
        return {k for k, v in ex.status(wanted=shown).items() if v}

    @staticmethod
    def _note_block(note: dict) -> str:
        """The block (of the run's graph) a note belongs to: the end of its link, or the block."""
        where = note.get("location", "")
        return _link_target(where) if " -> " in where else where

    def _plan_with_used(self, workflow, plan, graph, model, registry, fresh):
        """The plan with what the blocks used on links in the run whose results are up to date (a
        detector that computed fields near a focus: R→H at the link, RTT-Fusion #85; a spectrum
        on a link planned R: R→S, R30e – rare since auto plans S behind spectra, R30f) and the
        warnings of the spectrum conversions."""
        with_used = getattr(workflow, "with_used", None)
        used = {k: v for k, v in self._used.items() if _link_target(k) in fresh}
        shown = plan
        if with_used is not None and used and plan:
            shown = with_used(plan, used, graph, model, registry)
        notes = [d for d in self._run_notes if self._note_block(d) in fresh]
        per_connection = None
        connection_plan = getattr(workflow, "connection_plan", None)
        if connection_plan is not None:
            def per_connection(texts: dict) -> dict:
                return connection_plan(graph, model, registry,
                                       {"links": {k: {"representation": v} for k, v in texts.items()}})
        model_id = getattr(workflow, "model_id", None)
        return with_notes(shown, notes, model_id, per_connection)

    def _show_used(self, ctx, workflow, graph, model, registry, providers, fresh) -> None:
        """After a run: the plan of the current workflow with what the blocks used (R→H)."""
        try:
            wf = ctx.workflow()
            # the plan of the model as it is now (a transport set since)
            plan = self._document(workflow, model, registry, wf, providers)["plan"]
            shown = self._plan_with_used(workflow, plan, graph, model, registry, fresh)
            if shown is not plan or plan is not wf.get("plan"):
                ctx.set_workflow({**wf, "plan": shown, "available": sorted(workflow.available())})
        except Exception as e:  # noqa: BLE001 - only a hint at the links
            ctx.log(f"workflow plan: {e}")

    def _executor(self, ctx, graph, registry, evaluators, execute, wf):
        """An executor with the results of earlier runs (R23): only what changed is computed again.
        The environment covers what the results depend on outside the graph."""
        workflow, _, _, _ = _fusion()
        shared = {"rings": rings_for(int(ctx.params["rays"])),
                  "pixels": [int(ctx.params["pixels"])] * 2,
                  "gaussian_waist": float(ctx.params.get("gaussian_waist", 0.0) or 0.0),
                  "field_tolerance": float(ctx.params.get("field_tolerance", 0.02) or 0.02),
                  "auto_fields": bool(ctx.params.get("auto_fields", True))}
        materials = self._materials(wf, ctx.log)
        if materials is not None:
            shared["materials"] = materials
        available = workflow.available()
        if self._cache is None:
            self._cache = execute.ResultCache(limit_bytes=1 << 30)
        environment = {
            "rings": shared["rings"], "pixels": shared["pixels"], "window": ctx.params.get("window"),
            "gaussian": shared["gaussian_waist"], "field_tolerance": shared["field_tolerance"],
            "auto_fields": shared["auto_fields"], "catalogs": self._catalogues(wf), "available": sorted(available),
        }
        return execute.Executor(graph, registry, evaluators, shared, available=available, cache=self._cache,
                                environment=environment)

    @staticmethod
    def _kept(ctx) -> dict:
        """Fingerprints of the shown display results ({"workflow:<block>": stamp}), also of those
        the document kept from an earlier session; {} with an older CAD."""
        try:
            return dict(ctx.result_stamps()) if hasattr(ctx, "result_stamps") else {}
        except Exception:  # noqa: BLE001 - without fingerprints everything is computed
            return {}

    @staticmethod
    def _stamp(ex, node_id: str) -> str:
        """Fingerprint of a display's result: the content hash of everything it depends on (the
        executor's cache key: parameters, inputs, settings), the same in every session."""
        try:
            ex.check()  # the plan is part of the key: the same before and after the first evaluation
            return str(ex._key(node_id, "view"))
        except Exception:  # noqa: BLE001 - no fingerprint: the result is not kept as up to date
            return ""

    @staticmethod
    def _stamped(ctx, stamp: str) -> dict:
        """`stamp=` for ctx.image / ctx.curve where CAD knows it (kept with the document)."""
        if not stamp or not hasattr(ctx, "result_stamps"):
            return {}
        return {"stamp": stamp}

    def _send_status(self, ctx, ex) -> None:
        """Up to date / out of date per block (R23) for the node editor, per block of the model; a
        display whose shown result (also one the document kept) has the present fingerprint counts
        as up to date with everything it needs."""
        workflow, _, _, _ = _fusion()
        try:
            shown = [(n.id, "view") for n in ex.graph.nodes.values() if n.type_id.startswith("display.")]
            raw = {k: bool(v) for k, v in ex.status(wanted=shown).items()}
            kept = self._kept(ctx)
            fresh = [(d, s) for d, s in shown if (st := self._stamp(ex, d)) and kept.get(f"workflow:{d}") == st]
            stale = [w for w in shown if w not in fresh]
            if fresh:  # blocks only unchanged displays need (not those another display still waits for)
                waiting = set(ex.needed(stale)) if stale else set()
                for block in ex.needed(fresh):
                    if block not in waiting:
                        raw[block] = True
            ctx.workflow_state(workflow.block_states(raw, self._model_ids))
        except Exception as e:  # noqa: BLE001 - the state is a display hint only
            ctx.log(f"workflow state: {e}")
