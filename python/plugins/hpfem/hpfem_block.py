"""The hp-FEM grating block of the node workflow (`hpfem.grating`, RTT-Fusion R35): the job a block
holds, its fields in the block's dialog, and the block an action was chosen on. Pure Python."""

from __future__ import annotations

import json
from pathlib import Path

from nfcad import UserError

#: the blocks of this plugin that hold an hp-FEM job (`job_data`, else the file `job`)
BLOCK_TYPES = ("hpfem.grating",)

#: keys of a job the block does not use (the rays set the incidence; RTT-Fusion `hpfem_grating.UNUSED`)
UNUSED = ("incidence", "sweep", "maps")


def target_block(wf: dict, target: dict) -> dict:
    """The block an action was chosen on (`ctx.target`: its id and the groups it lies in), as the
    node dict inside `wf` – changing it changes `wf`."""
    container = wf.get("model")
    if not container:
        if wf.get("graph"):  # version 1: CAD converts it when it opens the document
            raise UserError("The node workflow is an old socket graph (version 1) – Convert to model "
                            "(Workflow plugin) makes it a model.")
        raise UserError("The document has no node workflow.")
    nodes = container.get("nodes", [])
    for gid in target.get("scope", []):  # the block may lie inside groups (their active variant)
        group = next((n for n in nodes if str(n.get("id")) == str(gid) and "variants" in n), None)
        if group is None:
            raise UserError(f"The group {gid} is gone – check the workflow and try again.")
        nodes = group["variants"][group["variant"]].get("nodes", [])
    block = str(target.get("block", ""))
    node = next((n for n in nodes if str(n.get("id")) == block), None)
    if node is None or node.get("type") not in BLOCK_TYPES:
        raise UserError(f"The block {block or '?'} is gone – check the workflow and try again.")
    return node


def _pointer(*parts) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def job_fields(job: dict, unit_name: str) -> list[dict]:
    """The numbers of a block's job as fields of its dialog in the node editor (JSON pointers into
    its params): period, the solver's order, the indices of materials given as n or n, k."""
    out: list[dict] = []

    def add(parts, kind, label, group, unit=""):
        out.append({"name": _pointer("job_data", *parts), "type": kind, "label": label, "group": group,
                    "unit": unit})

    model = job.get("model") or {}
    if isinstance(model.get("period"), int | float):
        add(("model", "period"), "number", "Period", "Grating", unit_name)
    if isinstance((job.get("solver") or {}).get("order"), int):
        add(("solver", "order"), "integer", "Polynomial order", "Solver")
    for tag, material in (job.get("materials") or {}).items():
        n = material.get("n") if isinstance(material, dict) else None
        if isinstance(n, int | float):
            add(("materials", tag, "n"), "number", f"Tag {tag}: n", "Materials")
        elif isinstance(n, list):
            add(("materials", tag, "n"), "numbers", f"Tag {tag}: n, k", "Materials")
    return out


def block_job(node: dict) -> dict | None:
    """The job a block holds, else the one its file names; None if it has neither."""
    params = node.get("params") or {}
    if params.get("job_data"):
        return json.loads(json.dumps(params["job_data"]))
    path = str(params.get("job") or "")
    if not path:
        return None
    try:
        job = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise UserError(f"{node.get('name') or node.get('id')} names {path}, which cannot be read ({e}) – "
                        "Load job from where it is now, then Store job in block.") from e
    if not isinstance(job, dict):
        raise UserError(f"{path} is no hp-FEM job (not a JSON object).")
    return job


def for_block(job: dict, base: Path) -> tuple[dict, list[str]]:
    """The job as a block holds it: without incidence, sweep and maps (the rays set them), a mesh
    file made absolute against `base` (the job file's folder, as `hpfem.run` resolves it). Returns
    the job and notes for the user."""
    job = json.loads(json.dumps(job))
    notes: list[str] = []
    dropped = [k for k in UNUSED if k in job]
    for key in dropped:
        del job[key]
    if dropped:
        notes.append(f"{', '.join(dropped)} left out – the rays at the block set the incidence")
    mesh = job.get("mesh")
    if isinstance(mesh, dict) and isinstance(mesh.get("file"), str):
        path = Path(mesh["file"])
        if not path.is_absolute():
            mesh["file"] = str((base / path).resolve())
        notes.append(f"the mesh file {Path(mesh['file']).name} stays outside the document")
    return job, notes


def set_job(node: dict, job: dict, unit_name: str) -> None:
    """The block holds `job` (and no longer names a file) and shows its numbers in its dialog
    (the fields of other data, e.g. the element it replaced, stay)."""
    params = node.setdefault("params", {})
    params["job_data"] = job
    params["job"] = ""
    kept = [f for f in node.get("fields") or [] if not str(f.get("name", "")).startswith("/job_data/")]
    node["fields"] = kept + job_fields(job, unit_name)
