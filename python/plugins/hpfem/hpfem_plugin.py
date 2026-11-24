"""hp-FEM plugin (step 1): grating jobs of hp-FEM's job runner in Raytatouille Fusion.

The panel holds a grating scattering job (`python -m hpfem.run`, schema version 1): unit cell
(period, slabs, shapes), materials by cell tag, background stack, incidence and sweep, mesh and
solver; every other key of the file stays under *Advanced*. *Check* builds the mesh and
estimates the memory, *Solve* runs the job with progress and Cancel (between the phases of a
solve) and shows the efficiencies per order, for a sweep ΣR, ΣT, A and the orders as curves.
Step 2: *Field map* computes one point of the sweep and shows E, H or the Poynting vector S on
a grid of the cell in the Image window; *Show cell* draws the cell's tags without solving.
Step 3: the plugin offers the block `hpfem.grating` to the node workflow (RTT-Fusion R35: a
rigorous grating in the place of a mirror, its diffraction orders as channels, computed in this
plugin's process); *Store job in block* gives a block the panel's job, *Load block job into
panel* brings it back to edit.
Step 4: *Shapes from CAD bodies* cuts closed CAD bodies across the grating lines (Nurbforge's
exact planar section) and makes their sections polygons of the cell, with tags for their materials.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from nfcad import Param, Plugin, UserError, action

import hpfem_block
import hpfem_cad
import hpfem_job
import hpfem_map
import hpfem_results

_SHAPE = {
    "kind": Param.choice([*hpfem_job.SHAPE_KINDS, "json"], "rectangle", label="Type",
                         description="rectangle: lower-left corner x, y, width, height; trapezoid: centre x, base y, "
                                     "bottom, top, height; ellipse: centre x, y, rx, ry; polygon: the points "
                                     "counter-clockwise; json: any other form"),
    "tag": Param.integer(3, min=0, max=10000, label="Tag", description="cell tag – its material in Materials"),
    "x": Param.number(0.0, decimals=6, label="x"),
    "y": Param.number(0.0, decimals=6, label="y"),
    "width": Param.number(0.0, decimals=6, label="width (rectangle)"),
    "height": Param.number(0.0, decimals=6, label="height (rectangle, trapezoid)"),
    "bottom": Param.number(0.0, decimals=6, label="bottom width (trapezoid)"),
    "top": Param.number(0.0, decimals=6, label="top width (trapezoid)"),
    "rx": Param.number(0.0, decimals=6, label="rx (ellipse)"),
    "ry": Param.number(0.0, decimals=6, label="ry (ellipse)"),
    "points": Param.table({"x": Param.number(0.0, decimals=6, label="x"),
                           "y": Param.number(0.0, decimals=6, label="y")}, label="Points (polygon)"),
    "json": Param.json(None, label="Shape as JSON (type json)"),
}
_MATERIAL_HELP = ("a library name (air, SiO2, Si, Au, … – see Library materials), n + i k (1.5, 3.88+0.02i), "
                  "the permittivity (eps=2.25+0.1i) or JSON")

_DEFAULTS = hpfem_job.to_params(hpfem_job.EXAMPLE)
_LENGTH = "in the job's length unit (Structure → Unit)"


def _hp():
    try:
        import hpfem
        import hpfem.run
    except ImportError as e:
        raise UserError("The hp-FEM plugin needs the Python package hpfem (≥ 0.5) in the plugin environment "
                        "(pip install hpfem).") from e
    return hpfem


def _ram_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


class HpFemPlugin(Plugin):
    d = _DEFAULTS
    params = {
        "job_file": Param.file("", filter="hp-FEM job (*.json)", label="Job", group="File",
                               description="Load job reads it into the panel; a mesh file is found relative to it"),
        "save_as": Param.file("", filter="hp-FEM job (*.json)", save=True, label="Save as", group="File"),
        "results_file": Param.file("", filter="results.json (*.json)", save=True, label="Results in folder of",
                                   group="File", description="Solve writes results.json (and the maps of Advanced) "
                                                             "into this file's folder; empty: a temporary folder"),
        "name": Param.text(d["name"], label="Name", group="Structure"),
        "unit": Param.choice(list(hpfem_job.UNITS), d["unit"], label="Unit", group="Structure",
                             description="length unit of every length and the wavelength of the job"),
        "period": Param.number(d["period"], min=0.0, decimals=6, label="Period", group="Structure",
                               description=f"along x, {_LENGTH}"),
        "y_bottom": Param.number(d["y_bottom"], decimals=6, label="Cell bottom y", group="Structure",
                                 description="y is the stack normal, light from +y; the PML lies inside the cell"),
        "y_top": Param.number(d["y_top"], decimals=6, label="Cell top y", group="Structure"),
        "background_tag": Param.integer(d["background_tag"], min=0, max=10000, label="Background tag",
                                        group="Structure", description="tag of the cells no slab and no shape covers"),
        "slabs": Param.table({"tag": Param.integer(2, min=0, max=10000, label="tag"),
                              "y0": Param.number(0.0, decimals=6, label="y0"),
                              "y1": Param.number(0.0, decimals=6, label="y1")},
                             d["slabs"], label="Slabs (full period)", group="Structure"),
        "shapes": Param.list(_SHAPE, d["shapes"], item_label="kind", label="Shapes (the last on top)"),
        "materials": Param.table({"tag": Param.integer(1, min=0, max=10000, label="tag"),
                                  "material": Param.text("air", label="material")},
                                 d["materials"], label="Materials by tag", group="Materials",
                                 description=_MATERIAL_HELP),
        "incidence_medium": Param.text(d["incidence_medium"], label="Incidence medium (above)", group="Stack",
                                       description=_MATERIAL_HELP),
        "substrate": Param.text(d["substrate"], label="Substrate (below)", group="Stack"),
        "stack_layers": Param.table({"material": Param.text("SiO2", label="material"),
                                     "thickness": Param.number(0.0, min=0.0, decimals=6, label="thickness")},
                                    d["stack_layers"], label="Background layers (top down)", group="Stack"),
        "stack_top": Param.number(d["stack_top"], decimals=6, label="Top interface y", group="Stack"),
        "polarisation": Param.choice(["s", "p"], d["polarisation"], label="Polarisation", group="Incidence",
                                     description="s: E_z at φ = 0 (TE), p: H_z at φ = 0 (TM)"),
        "wavelength": Param.text(d["wavelength"], label="Wavelength", group="Incidence",
                                 description="in the job's unit: a number, a list (400, 410) or a range start:stop:count"),
        "theta_deg": Param.text(d["theta_deg"], label="θ / deg", group="Incidence",
                                description="polar angle against the normal: a number, a list or a range "
                                            "(sweep the wavelength or θ, not both)"),
        "phi_deg": Param.number(d["phi_deg"], decimals=4, label="φ / deg", group="Incidence",
                                description="azimuth; 0: plane of incidence x–y, otherwise conical"),
        "mesh_kind": Param.choice(list(hpfem_job.MESH_KINDS), d["mesh_kind"], label="Mesh", group="Mesh",
                                  description="structured: columns × rows without Gmsh (put interfaces and shape "
                                              "edges on row and column lines); gmsh: by wavelength (needs the gmsh "
                                              "package); file: a periodic .msh"),
        "mesh_nx": Param.integer(d["mesh_nx"], min=1, max=10000, label="Columns (structured)", group="Mesh"),
        "mesh_rows": Param.table({"y0": Param.number(0.0, decimals=6, label="y0"),
                                  "y1": Param.number(0.0, decimals=6, label="y1"),
                                  "n": Param.integer(1, min=1, max=10000, label="rows")},
                                 d["mesh_rows"], label="Row bands (structured, bottom up)", group="Mesh"),
        "gmsh_interface_factor": Param.number(d["gmsh_interface_factor"], min=0.01, max=10.0, decimals=3,
                                              label="Interface factor (gmsh)", group="Mesh"),
        "mesh_file": Param.file(d["mesh_file"], filter="Gmsh mesh (*.msh)", label="Mesh file (file)", group="Mesh"),
        "mesh_scale": Param.number(d["mesh_scale"], decimals=12, label="Scale to metres (file)", group="Mesh"),
        "order": Param.integer(d["order"], min=1, max=12, label="Polynomial order p", group="Solver"),
        "pml_top": Param.number(d["pml_top"], min=0.0, decimals=6, label="PML top", group="Solver",
                                description="thickness inside the cell; 0 for both: hp-FEM's recommendation"),
        "pml_bottom": Param.number(d["pml_bottom"], min=0.0, decimals=6, label="PML bottom", group="Solver"),
        "bottom": Param.choice(list(hpfem_job.BOTTOMS), d["bottom"], label="Bottom", group="Solver",
                               description="pml: open substrate; pec: a metal wall; modal: modal bottom"),
        "orders_max": Param.integer(d["orders_max"], min=0, max=200, label="Orders up to |m|", group="Solver"),
        "check": Param.boolean(d["check"], label="Diagnostics before solving", group="Solver"),
        "min_efficiency": Param.number(0.01, min=0.0, max=1.0, decimals=4, label="Orders from efficiency",
                                       group="Results", description="a sweep shows an order if it reaches this"),
        "evanescent": Param.boolean(False, label="List evanescent orders", group="Results"),
        "map_quantity": Param.choice(list(hpfem_map.QUANTITIES), "E", label="Field", group="Field map",
                                     description="E (incident wave of amplitude 1 V/m), H in A/m or the Poynting "
                                                 "vector S in W/m² (SI, as hp-FEM samples them)"),
        "map_show": Param.choice(list(hpfem_map.SHOW), "|F|²", label="Show", group="Field map",
                                 description="F is the chosen field; real and imaginary parts with a colour scale "
                                             "symmetric about 0"),
        "map_point": Param.integer(1, min=1, max=100000, label="Point of the sweep", group="Field map"),
        "map_scattered": Param.boolean(False, label="Scattered field only", group="Field map"),
        "map_periods": Param.integer(2, min=1, max=50, label="Periods", group="Field map",
                                     description="x over this many periods from the cell's left edge (when x from = x to)"),
        "map_x_from": Param.number(0.0, decimals=6, label="x from", group="Field map",
                                   description="equal from and to: Periods periods"),
        "map_x_to": Param.number(0.0, decimals=6, label="x to", group="Field map"),
        "map_nx": Param.integer(201, min=2, max=4000, label="Points x", group="Field map"),
        "map_y_from": Param.number(0.0, decimals=6, label="y from", group="Field map",
                                   description="equal from and to: the cell without the PML layers given in Solver"),
        "map_y_to": Param.number(0.0, decimals=6, label="y to", group="Field map"),
        "map_ny": Param.integer(301, min=2, max=4000, label="Points y", group="Field map"),
        "map_npz": Param.file("", filter="NumPy archive (*.npz)", save=True, label="Also write .npz",
                              group="Field map", description="the runner's map: x, y in metres, values (ny, nx, 3)"),
        "cad_bodies": Param.entity(kinds=["shell"], multiple=True, label="Bodies", group="CAD cell",
                                   description="closed bodies of one unit cell, drawn with the lines along CAD +Y and "
                                               "the stack normal along CAD +Z (light from above); the material from "
                                               "the body's attribute 'material' or its name"),
        "cad_unit": Param.choice(list(hpfem_cad.CAD_UNITS), "µm", label="Bodies drawn in", group="CAD cell",
                                 description="what one CAD length unit is; converted to the job's unit"),
        "cad_section_y": Param.number(0.0, decimals=6, label="Section at CAD y", group="CAD cell",
                                      description="the plane across the lines where the bodies are cut (CAD units)"),
        "cad_points": Param.integer(48, min=4, max=2000, label="Points per curved edge", group="CAD cell",
                                    description="curved edges of a section become polygons with this many points; "
                                                "straight edges keep their end points"),
        "cad_mode": Param.choice(["replace shapes", "add shapes"], "replace shapes", label="Shapes",
                                 group="CAD cell", description="replace the panel's shapes or add the bodies on top"),
        "advanced": Param.json(d["advanced"], label="Further keys (JSON)", group="Advanced",
                               description="every other key of the job file (maps, model.x0, solver tolerances, …), "
                                           "merged into the job"),
    }
    del d

    # ------------------------------------------------------------------ job
    def job(self, ctx) -> dict:
        """The job of the panel (hp-FEM job runner, schema version 1)."""
        try:
            return hpfem_job.to_job(ctx.params)
        except (ValueError, KeyError, TypeError) as e:
            raise UserError(f"The panel does not give a valid job: {e}") from e

    @action("Load job", description="Read an hp-FEM grating job (.json) into the panel")
    def load_job(self, ctx):
        path = ctx.params["job_file"]
        if not path:
            raise UserError("Choose the job first: File → Job.")
        try:
            job = json.loads(Path(path).read_text(encoding="utf-8"))
            values = hpfem_job.to_params(job)
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise UserError(f"{Path(path).name} cannot be read: {e}") from e
        ctx.set_params(values)
        extra = f", further keys: {', '.join(values['advanced'])}" if values["advanced"] else ""
        return (f"{Path(path).name}: {len(values['materials'])} materials, {len(values['slabs'])} slabs, "
                f"{len(values['shapes'])} shapes, {hpfem_job.points_count(values)} points{extra}")

    @action("Save job", description="Write the panel's job as .json (Save as, else Job); runs with python -m hpfem.run")
    def save_job(self, ctx):
        path = ctx.params["save_as"] or ctx.params["job_file"]
        if not path:
            raise UserError("Choose where to save: File → Save as.")
        Path(path).write_text(json.dumps(self.job(ctx), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return f"saved {Path(path).name}"

    @action("Library materials", description="The materials of hp-FEM's library (names for the material fields)")
    def library(self, ctx):
        hp = _hp()
        names = sorted(hp.materials.library)
        ctx.log("hp-FEM materials: " + ", ".join(names))
        return f"{len(names)} library materials (in the log)"

    # ------------------------------------------------------------------ blocks (RTT-Fusion R35)
    def _block_provider(self):
        """RTT-Fusion's provider of the block `hpfem.grating`, evaluated in this process with
        RTT-Fusion's evaluator; None without an RTT-Fusion that has it (from 0.5)."""
        if getattr(self, "_provider", None) is None:
            try:
                remote = importlib.import_module("rtt_fusion.graph.remote")
                module = importlib.import_module("rtt_fusion.graph.hpfem_grating")
            except ImportError:
                return None
            self._provider = remote.BlockProvider([module.TYPE], dict(module.EVALUATORS))
        return self._provider

    def blocks(self) -> list:
        provider = self._block_provider()
        return provider.catalogue() if provider is not None else []

    def evaluate_block(self, request: dict) -> dict:
        provider = self._block_provider()
        if provider is None:
            return {"ok": False, "error": "the hp-FEM plugin needs RTT-Fusion with the block hpfem.grating (0.5)"}
        return provider.handle(request)

    @action("Store job in block",
            description="The panel's job becomes this block's grating (saved with the document; period, order "
                        "and indices in its dialog); the rays at the block set the incidence",
            block_types=hpfem_block.BLOCK_TYPES)
    def job_to_block(self, ctx):
        job, notes = hpfem_block.for_block(self.job(ctx), self._base(ctx))
        wf = ctx.workflow()
        node = hpfem_block.target_block(wf, ctx.target)
        hpfem_block.set_job(node, job, ctx.params["unit"])
        ctx.set_workflow(wf)
        for note in notes:
            ctx.log(note)
        name = node.get("name") or node.get("id")
        return (f"{name}: job stored in the block ({len(job.get('materials', {}))} materials, "
                f"{len((job.get('model') or {}).get('shapes', []))} shapes)")

    @action("Load block job into panel",
            description="Show this block's job in the panel to edit, check or solve it; Store job in block writes "
                        "it back",
            block_types=hpfem_block.BLOCK_TYPES)
    def block_to_job(self, ctx):
        node = hpfem_block.target_block(ctx.workflow(), ctx.target)
        name = node.get("name") or node.get("id")
        job = hpfem_block.block_job(node)
        if job is None:
            raise UserError(f"{name} holds no hp-FEM job yet – fill the panel, then Store job in block.")
        try:
            values = hpfem_job.to_params(job)
        except (ValueError, KeyError, TypeError) as e:
            raise UserError(f"{name}: its job cannot be shown in the panel: {e}") from e
        values["job_file"] = ""  # Save job must not overwrite a file the block came from
        for key in ("polarisation", "wavelength", "theta_deg", "phi_deg"):  # the block holds none
            values.pop(key, None)
        ctx.set_params(values)
        return (f"{name}: job in the panel ({len(values['materials'])} materials, {len(values['shapes'])} shapes; "
                "incidence and sweep are the panel's own)")

    # ------------------------------------------------------------------ running
    def _base(self, ctx) -> Path:
        job_file = ctx.params.get("job_file")
        return Path(job_file).parent if job_file else Path.cwd()

    def _out_dir(self, ctx) -> Path:
        if ctx.params.get("results_file"):
            return Path(ctx.params["results_file"]).parent
        return Path(tempfile.mkdtemp(prefix="hpfem-"))

    def _run(self, ctx, job: dict, out_dir: Path | None, check_only: bool, n_points: int | None = None) -> dict:
        hp = _hp()
        if n_points is None:
            n_points = hpfem_job.points_count(ctx.params) if not check_only else 1

        def emit(event: dict) -> None:
            kind = event.get("event")
            if kind == "mesh":
                ctx.log(hpfem_results.mesh_line(event))
            elif kind == "estimate":
                ctx.log(f"estimate: {event.get('text', '')}")
                ram, need = _ram_bytes(), event.get("total_bytes")
                if ram and need and need > 0.7 * ram:
                    ctx.log(f"warning: one factorisation needs about {need / 2**30:.1f} GiB of "
                            f"{ram / 2**30:.1f} GiB RAM")
            elif kind == "progress":
                i, step, steps = int(event["i"]), int(event["step"]), max(int(event["num_steps"]), 1)
                ctx.progress(min((i + step / steps) / n_points, 1.0),
                             f"point {i + 1}/{n_points}: {event.get('phase', '')}")
            elif kind == "diagnostics":
                for line in hpfem_results.diagnostic_lines(event.get("items", [])):
                    ctx.log(f"point {int(event.get('i', 0)) + 1}: {line}")
            elif kind == "point":
                ctx.log(f"point {int(event['i']) + 1}/{n_points}: λ = {float(event['wavelength']) / job['unit']:.6g} "
                        f"{ctx.params['unit']}, θ = {float(event.get('theta_deg', 0)):.4g}°: "
                        f"{hpfem_results.summary(event)} ({float(event.get('seconds', 0)):.1f} s)")
            elif kind == "map":
                ctx.log(f"map written: {event.get('file')}")

        cancel = (lambda: True) if check_only else ctx.cancelled
        ctx.progress(0.0, "mesh …")
        try:
            return hp.run.run_job(job, out_dir=out_dir, emit=emit, cancel=cancel, base=self._base(ctx))
        except UserError:
            raise
        except Exception as e:  # noqa: BLE001 - hp-FEM's message (JobError, GratingError, …) is for the user
            raise UserError(f"hp-FEM: {e}") from e

    @action("Check", description="Build the mesh and estimate the memory of one solve, without solving")
    def check_job(self, ctx):
        job = self.job(ctx)
        res = self._run(ctx, job, None, check_only=True)
        mesh = res.get("mesh", {})
        problems = [k for k in ("tags_without_material", "materials_without_cells", "invalid_cells") if mesh.get(k)]
        return (f"{mesh.get('num_cells', '?')} cells, {hpfem_job.points_count(ctx.params)} points"
                + (f" – check {', '.join(problems)} in the log" if problems else " – ready to solve"))

    # ------------------------------------------------------------------ field map (step 2)
    def _grid(self, ctx, job):
        try:
            return hpfem_map.grid(job, ctx.params)
        except (ValueError, KeyError) as e:
            raise UserError(f"Field map: {e}") from e

    @action("Field map", description="One point of the sweep: E, H or S on a grid of the cell in the Image window")
    def field_map(self, ctx):
        job = self.job(ctx)
        xspec, yspec = self._grid(ctx, job)
        try:
            one, wl, th = hpfem_map.point_job(job, ctx.params, int(ctx.params["map_point"]) - 1, xspec, yspec)
        except ValueError as e:
            raise UserError(str(e)) from e
        out_dir = self._out_dir(ctx)
        res = self._run(ctx, one, out_dir, check_only=False, n_points=1)
        maps = [m for m in res.get("maps", []) if m.get("file")]
        if not maps:
            return "cancelled before the map"
        import numpy as np

        with np.load(maps[0]["file"]) as data:
            unit = float(job["unit"])
            x, y, values = data["x"] / unit, data["y"] / unit, data["values"]
        quantity, show = ctx.params["map_quantity"], ctx.params["map_show"]
        pic = hpfem_map.picture(x, y, values, show)
        name = hpfem_map.label(show, quantity) + (" (scattered)" if ctx.params["map_scattered"] else "")
        unit_name = ctx.params["unit"]
        run = ctx.result_set(f"{job.get('name') or 'hp-FEM'}: {name}, λ = {wl:.6g} {unit_name}, θ = {th:.4g}°")
        ctx.image(run, name, pic.values, pic.width, pic.height, extent=pic.extent, x_label=f"x / {unit_name}",
                  y_label=f"y / {unit_name}", colormap=pic.colormap, value_range=pic.value_range,
                  description="incident plane wave of amplitude 1 (hp-FEM); light from +y")
        if pic.missing:
            ctx.log(f"{pic.missing} grid points lie outside the cell (no field, shown empty)")
        if ctx.params.get("map_npz"):
            shutil.copyfile(maps[0]["file"], ctx.params["map_npz"])
            ctx.log(f"map written to {Path(ctx.params['map_npz']).name}")
        points = res.get("points", [])
        return f"{name}: {pic.width} × {pic.height} points" + (
            f"; {hpfem_results.summary(points[0])}" if points else "")

    @action("Shapes from CAD bodies",
            description="Cut the chosen bodies across the lines (CAD y = Section at) and make their sections "
                        "polygons of the cell, with a tag per material; Show cell draws the result")
    def shapes_from_cad(self, ctx):
        ids = [int(i) for i in ctx.params["cad_bodies"]]
        if not ids:
            raise UserError("Choose the bodies first: CAD cell → Bodies (select them, then take the selection).")
        try:
            library = sorted(_hp().materials.library)
        except UserError:
            library = None  # without hpfem a body's name must be one of the panel's materials
        scale = hpfem_cad.CAD_UNITS[ctx.params["cad_unit"]] / hpfem_job.UNITS[ctx.params["unit"]]
        y_cut, points = float(ctx.params["cad_section_y"]), int(ctx.params["cad_points"])
        materials = [dict(r) for r in ctx.params["materials"]]
        shapes = [] if ctx.params["cad_mode"] == "replace shapes" else [dict(r) for r in ctx.params["shapes"]]
        made, holes, polys, missed = 0, 0, [], []
        for entity in ctx.entities(ids):
            label = entity.get("name") or entity.get("id")
            try:
                material = hpfem_cad.material_of(entity, [str(r["material"]) for r in materials], library)
                loops = hpfem_cad.section_loops(hpfem_cad.shell_of(entity.get("geometry") or {}), y_cut, scale, points)
            except ValueError as e:
                raise UserError(f"{label}: {e}") from e
            if not loops:
                missed.append(str(label))
                continue
            tag, materials = hpfem_cad.tag_for(materials, material)
            before = list(shapes)  # what lies under the body: its holes show that
            for depth, poly in hpfem_cad.body_polygons(loops):
                fill = tag
                if depth % 2:
                    job = hpfem_job.to_job({**ctx.params, "shapes": before, "materials": materials})
                    px, py = hpfem_cad.inner_point(poly)
                    fill = int(hpfem_map.tags(job, [px], [py])[0][0, 0])
                    holes += 1
                shapes.append(hpfem_cad.polygon_row(fill, poly))
                polys.append(poly)
            made += 1
        if not made:
            raise UserError(f"No body reaches the plane CAD y = {y_cut:g} – set CAD cell → Section at.")
        ctx.set_params({"shapes": shapes, "materials": materials})
        unit = ctx.params["unit"]
        x0, x1, y0, y1 = hpfem_cad.bounds(polys)
        ctx.log(f"bodies span x {x0:.6g} … {x1:.6g} {unit}, y {y0:.6g} … {y1:.6g} {unit}")
        period = float(ctx.params["period"])
        left = float((ctx.params.get("advanced") or {}).get("model", {}).get("x0", -period / 2))
        if x0 < left - 1e-9 * period or x1 > left + period + 1e-9 * period:
            ctx.log(f"warning: the bodies leave the cell x {left:.6g} … {left + period:.6g} {unit} – set the period "
                    "(Structure) or move the bodies")
        if y0 < float(ctx.params["y_bottom"]) or y1 > float(ctx.params["y_top"]):
            ctx.log(f"warning: the bodies leave the cell y {ctx.params['y_bottom']:.6g} … {ctx.params['y_top']:.6g} "
                    f"{unit} – set Cell bottom / top (Structure)")
        if ctx.params["mesh_kind"] == "structured":
            ctx.log("note: the structured mesh gives every element the tag at its centre – for slanted or curved "
                    "bodies choose Mesh → gmsh")
        if missed:
            ctx.log(f"not cut by the plane CAD y = {y_cut:g}: {', '.join(missed)}")
        return (f"{made} bodies → {len(polys)} polygons" + (f" ({holes} holes)" if holes else "")
                + f", {len(materials)} materials; Show cell draws the cell")

    @action("Show cell", description="The cell's tags on the map's grid, without solving (shapes, slabs, background)")
    def show_cell(self, ctx):
        job = self.job(ctx)
        xspec, yspec = self._grid(ctx, job)
        xs = [xspec[0] + (xspec[1] - xspec[0]) * i / (xspec[2] - 1) for i in range(xspec[2])]
        ys = [yspec[0] + (yspec[1] - yspec[0]) * j / (yspec[2] - 1) for j in range(yspec[2])]
        grid, unknown = hpfem_map.tags(job, xs, ys)
        pic = hpfem_map.picture(xs, ys, grid[:, :, None] + 0j, "Re Fx")
        unit_name = ctx.params["unit"]
        run = ctx.result_set(f"{job.get('name') or 'hp-FEM'}: cell")
        ctx.image(run, "Tags", pic.values, pic.width, pic.height, extent=pic.extent, x_label=f"x / {unit_name}",
                  y_label=f"y / {unit_name}", colormap="viridis", description="cell tag per point")
        materials = job.get("materials", {})
        for tag in sorted({int(t) for t in grid.ravel()}):
            ctx.log(f"tag {tag}: {hpfem_job.material_text(materials.get(str(tag), '– no material –'))}")
        if unknown:
            ctx.log(f"warning: shapes not drawn (unknown form): {', '.join(unknown)}")
        return f"{len(set(grid.ravel().tolist()))} tags on {len(xs)} × {len(ys)} points"

    @action("Solve", description="Run the job: efficiencies per order; for a sweep ΣR, ΣT, A and the orders as curves")
    def solve(self, ctx):
        job = self.job(ctx)
        out_dir = self._out_dir(ctx)
        res = self._run(ctx, job, out_dir, check_only=False)
        points = res.get("points", [])
        if not points:
            return "cancelled before the first point"
        unit, unit_name = float(job["unit"]), ctx.params["unit"]
        title = job.get("name") or "hp-FEM"
        if len(points) == 1:
            p = points[0]
            run = ctx.result_set(f"{title}: λ = {hpfem_results.wavelength(p, unit):.6g} {unit_name}, "
                                 f"θ = {float(p.get('theta_deg', 0)):.4g}°")
            ctx.table(run, "Orders", hpfem_results.ORDER_COLUMNS,
                      hpfem_results.order_rows(p, bool(ctx.params["evanescent"])))
            labels, values = hpfem_results.order_bars(p)
            ctx.bars(run, "Efficiency per order", labels, values, y_label="efficiency")
        else:
            x_label, found = hpfem_results.curves(points, unit, unit_name, float(ctx.params["min_efficiency"]))
            run = ctx.result_set(f"{title}: sweep over {x_label.split(' /')[0]}")
            for name, x, y in found:
                ctx.curve(run, name, x, y, x_label=x_label, y_label="efficiency")
            ctx.table(run, "Points", hpfem_results.POINT_COLUMNS, hpfem_results.point_rows(points, unit))
        ctx.log(f"results: {out_dir / 'results.json'}")
        cancelled = " – cancelled" if res.get("cancelled") else ""
        if len(points) == 1:
            return hpfem_results.summary(points[0]) + cancelled
        return f"{len(points)} points in {float(res.get('seconds', 0)):.1f} s{cancelled}"
