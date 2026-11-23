"""hp-FEM plugin (step 1): grating jobs of hp-FEM's job runner in Raytatouille Fusion.

The panel holds a grating scattering job (`python -m hpfem.run`, schema version 1): unit cell
(period, slabs, shapes), materials by cell tag, background stack, incidence and sweep, mesh and
solver; every other key of the file stays under *Advanced*. *Check* builds the mesh and
estimates the memory, *Solve* runs the job with progress and Cancel (between the phases of a
solve) and shows the efficiencies per order, for a sweep ΣR, ΣT, A and the orders as curves.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from nfcad import Param, Plugin, UserError, action

import hpfem_job
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

    # ------------------------------------------------------------------ running
    def _base(self, ctx) -> Path:
        job_file = ctx.params.get("job_file")
        return Path(job_file).parent if job_file else Path.cwd()

    def _out_dir(self, ctx) -> Path:
        if ctx.params.get("results_file"):
            return Path(ctx.params["results_file"]).parent
        return Path(tempfile.mkdtemp(prefix="hpfem-"))

    def _run(self, ctx, job: dict, out_dir: Path | None, check_only: bool) -> dict:
        hp = _hp()
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
