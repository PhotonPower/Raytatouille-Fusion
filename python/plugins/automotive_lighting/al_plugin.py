"""Automotive Lighting plugin: headlamps and signal lamps for filament lamps – the facetted
reflector of a clear-lens headlamp (low beam), or a paraboloid with a patterned lens (al_lens).

For a filament lamp (H7, H4, …) and the frame of the reflector, the mirror is cut into zones and
strips; every strip is a surface whose filament images touch the cut-off line (al_design); walls
with draft and fillets connect the strips to one mirror surface that can be moulded
(al_transitions). The faces as trimmed NURBS, the filament images and the light distribution with
the test points of UN/ECE R112. Coordinates: +X the driving direction, +Y left, +Z up, the filament
centre at *Filament centre*.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from nfcad import Param, Plugin, UserError, action

import al_layout
import al_lens
import al_photometry
import al_reflector
from al_design import DesignError
from al_layout import Zone
from al_optics import CUSTOM, HORIZONTAL, LAMPS, RISING, Cutoff, Lamp
from al_spline import curve_points

RIGHT, LEFT = "right-hand", "left-hand"
CLEAR, PATTERNED = "clear lens: facetted reflector", "patterned lens: paraboloid and lens"

_ELEMENT = {
    "y_from": Param.number(-500.0, decimals=1, unit="mm", label="y from"),
    "y_to": Param.number(500.0, decimals=1, unit="mm", label="y to"),
    "z_from": Param.number(-500.0, decimals=1, unit="mm", label="z from"),
    "z_to": Param.number(500.0, decimals=1, unit="mm", label="z to"),
    "deflect_h": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="deflect H"),
    "deflect_v": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="deflect V"),
    "spread_h": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="spread ± H"),
    "spread_v": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="spread ± V"),
}

_ZONE = {
    "from": Param.number(0.0, min=-360.0, max=360.0, decimals=1, unit="°", label="from azimuth"),
    "branch": Param.choice([HORIZONTAL, RISING], HORIZONTAL, label="cut-off branch"),
    "aim_right": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="aim, right border"),
    "aim_left": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="aim, left border"),
    "below": Param.number(0.0, min=0.0, max=10.0, decimals=2, unit="°", label="below cut-off"),
}


def default_zones(right_hand_traffic: bool = True) -> list[dict]:
    """Four sectors: the flank whose filament images lie along the rising branch carries it, the
    other flank makes the horizontal cut-off and the hot spot, top and bottom spread the light."""
    rows = [(-20.0, 20.0, HORIZONTAL, 6.0, -1.0), (20.0, 145.0, HORIZONTAL, 25.0, -25.0),
            (145.0, 185.0, RISING, 7.0, 1.0), (185.0, 340.0, HORIZONTAL, 25.0, -25.0)]
    if not right_hand_traffic:   # mirrored: a sector a0 … a1 becomes 180° - a1 … 180° - a0, the aims swap
        rows = sorted((180.0 - a1, 180.0 - a0, branch, -left, -right) for a0, a1, branch, right, left in rows)
    return [{"from": a0, "branch": branch, "aim_right": right, "aim_left": left, "below": 0.0}
            for a0, _, branch, right, left in rows]


def zones_of(rows: list[dict]) -> tuple[Zone, ...]:
    """The zone table as sectors: each row from its azimuth to the next row's (the last one to the
    first), sorted by azimuth."""
    if not rows:
        raise UserError("The zone table is empty: add a zone (or press Default zones).")
    rows = sorted(rows, key=lambda r: float(r["from"]) % 360.0)
    starts = [float(r["from"]) % 360.0 for r in rows]
    if len(set(starts)) != len(starts):
        raise UserError("Two zones start at the same azimuth.")
    out = []
    for i, r in enumerate(rows):
        end = starts[(i + 1) % len(rows)] if len(rows) > 1 else starts[0] + 360.0
        if end <= starts[i]:
            end += 360.0
        out.append(Zone(starts[i], end, str(r["branch"]), float(r["aim_right"]), float(r["aim_left"]),
                        float(r["below"])))
    return tuple(out)


class AutomotiveLighting(Plugin):
    params = {
        "system": Param.choice([CLEAR, PATTERNED], CLEAR, label="System", group="System",
                               description="clear lens: the facets of the mirror shape the beam and its cut-off. "
                                           "Patterned lens: a paraboloid mirror, the elements of the lens in front "
                                           "of it deflect and spread the light (groups Frame, Lamp and Lens)"),
        "lamp": Param.choice([*LAMPS, CUSTOM], "H7", label="Lamp", group="Lamp",
                             description="lamps with a filament along the axis: its length / diameter and luminous "
                                         "flux after UN/ECE R37 (nominal values); Custom takes the fields below"),
        "custom_length": Param.number(4.1, min=0.1, max=30.0, decimals=2, unit="mm", label="Custom: filament length",
                                      group="Lamp"),
        "custom_diameter": Param.number(1.3, min=0.05, max=10.0, decimals=2, unit="mm",
                                        label="Custom: filament diameter", group="Lamp"),
        "custom_flux": Param.number(1500.0, min=1.0, max=100000.0, decimals=0, unit="lm", label="Custom: luminous flux",
                                    group="Lamp"),
        "position": Param.point((0.0, 0.0, 0.0), label="Filament centre", group="Lamp",
                                description="the light leaves along +X, +Z is up"),
        "traffic": Param.choice([RIGHT, LEFT], RIGHT, label="Traffic", group="Cut-off",
                                description="right-hand traffic: the cut-off rises to the right"),
        "cutoff_v": Param.number(-0.57, min=-10.0, max=5.0, decimals=2, unit="°", label="Horizontal part at V",
                                 group="Cut-off", description="-0.57° = 1 % below the horizon"),
        "cutoff_rise": Param.number(15.0, min=0.0, max=60.0, decimals=1, unit="°", label="Rise", group="Cut-off"),
        "cutoff_kink": Param.number(0.0, min=-10.0, max=10.0, decimals=2, unit="°", label="Kink at H", group="Cut-off"),
        "frame_curves": Param.entity(kinds=["curve"], multiple=True, label="Frame (curves)", group="Frame",
                                     description="closed outline of the mirror, seen along X; empty: the "
                                                 "rounded rectangle below"),
        "frame_width": Param.number(170.0, min=10.0, max=1000.0, decimals=1, unit="mm", label="Width", group="Frame"),
        "frame_height": Param.number(100.0, min=10.0, max=1000.0, decimals=1, unit="mm", label="Height", group="Frame"),
        "frame_radius": Param.number(20.0, min=0.0, max=500.0, decimals=1, unit="mm", label="Corner radius",
                                     group="Frame"),
        "frame_y": Param.number(0.0, decimals=1, unit="mm", label="Centre to the left of the lamp axis", group="Frame"),
        "frame_z": Param.number(0.0, decimals=1, unit="mm", label="Centre above the lamp axis", group="Frame"),
        "hole_radius": Param.number(12.0, min=0.0, max=200.0, decimals=1, unit="mm", label="Lamp hole radius",
                                    group="Frame"),
        "focal": Param.number(25.0, min=5.0, max=200.0, decimals=2, unit="mm", label="Focal length", group="Reflector",
                              description="of the base paraboloid the facets start on (focus at the filament centre)"),
        "strip_width": Param.number(10.0, min=1.0, max=200.0, decimals=1, unit="mm", label="Strip width",
                                    group="Reflector"),
        "facet_length": Param.number(0.0, min=0.0, max=500.0, decimals=1, unit="mm", label="Facet length",
                                     group="Reflector",
                                     description="cuts every strip into facets of this length (0: whole strips). "
                                                 "Each facet starts anew with its aims, so the spread holds all "
                                                 "over the mirror – at the price of more connecting faces"),
        "zones": Param.table(_ZONE, default_zones(), label="Zones", group="Reflector",
                             description="sectors about the lamp axis (azimuth 0° = left, 90° = up, 180° = right, seen "
                                         "in the driving direction), each up to the next one's start. Aim: where the "
                                         "filament image is placed along the cut-off (H, positive to the right), "
                                         "running from the right to the left border of every strip"),
        "knot_spacing": Param.number(1.5, min=0.3, max=10.0, decimals=2, unit="mm", label="Surface knots every",
                                     group="Reflector", description="of the facets' B-splines; smaller: closer to "
                                                                    "the computed strips, more control points"),
        "lens_x": Param.number(75.0, min=1.0, max=1000.0, decimals=1, unit="mm", label="Lens in front of the filament",
                               group="Lens", description="the base plane of its inner side"),
        "lens_thickness": Param.number(3.0, min=0.5, max=50.0, decimals=2, unit="mm", label="Thickness", group="Lens"),
        "lens_index": Param.number(1.49, min=1.01, max=3.0, decimals=3, label="Refractive index", group="Lens",
                                   description="PMMA 1.49, polycarbonate 1.59, glass about 1.52"),
        "lens_transmittance": Param.number(0.92, min=0.0, max=1.0, decimals=2, label="Transmittance", group="Lens"),
        "cell_width": Param.number(10.0, min=0.5, max=500.0, decimals=2, unit="mm", label="Element width", group="Lens"),
        "cell_height": Param.number(10.0, min=0.5, max=500.0, decimals=2, unit="mm", label="Element height",
                                    group="Lens"),
        "focus_behind": Param.number(0.0, min=-50.0, max=50.0, decimals=2, unit="mm",
                                     label="Mirror focus behind the filament centre", group="Lens",
                                     description="0: the filament sits in the focus of the paraboloid (its focal "
                                                 "length: Reflector → Focal length)"),
        "elements": Param.table(_ELEMENT, [{"y_from": -500.0, "y_to": 500.0, "z_from": -500.0, "z_to": 500.0,
                                            "deflect_h": 0.0, "deflect_v": -1.0, "spread_h": 15.0, "spread_v": 4.0}],
                                label="Elements", group="Lens",
                                description="what the cells of the lens do, by the place of their centre (the first "
                                            "row that holds it; y to the left, z up, about the lamp axis): by how "
                                            "much the light is turned in the cell's middle and the half spread "
                                            "about that; all 0: plane glass; a negative spread turns the element "
                                            "round (crossing rays)"),
        "connect": Param.boolean(True, label="Connecting faces", group="Connecting faces",
                                 description="walls with draft and fillets between the facets: one mirror surface "
                                             "that can be moulded; off: the bare facets with steps between them"),
        "draft": Param.number(5.0, min=0.5, max=45.0, decimals=1, unit="°", label="Draft angle",
                              group="Connecting faces",
                              description="between the walls and the demoulding direction X"),
        "fillet": Param.number(0.3, min=0.0, max=5.0, decimals=2, unit="mm", label="Fillet radius",
                               group="Connecting faces", description="at the foot and the head of every wall"),
        "reflectance": Param.number(0.85, min=0.0, max=1.0, decimals=2, label="Reflectance", group="Analysis"),
        "reflectance_connections": Param.number(0.85, min=0.0, max=1.0, decimals=2,
                                                label="Reflectance of the connecting faces", group="Analysis",
                                                description="0: their light does not count (masked or matt walls)"),
        "sampling": Param.number(1.0, min=0.2, max=10.0, decimals=2, unit="mm", label="Mirror points every",
                                 group="Analysis", description="lattice of the light distribution"),
        "image_points": Param.integer(150, min=1, max=5000, label="Filament images (number)", group="Analysis"),
    }

    # ------------------------------------------------------------------ the reflector
    @staticmethod
    def lamp_of(params: dict) -> Lamp:
        if params["lamp"] != CUSTOM:
            return LAMPS[params["lamp"]]
        return Lamp(CUSTOM, float(params["custom_length"]), float(params["custom_diameter"]),
                    float(params["custom_flux"]))

    @staticmethod
    def cutoff_of(params: dict) -> Cutoff:
        return Cutoff(float(params["cutoff_v"]), float(params["cutoff_rise"]), float(params["cutoff_kink"]),
                      params["traffic"] == RIGHT)

    def frame_of(self, ctx) -> np.ndarray:
        """The frame in the front view about the lamp axis: the chosen curves, else the rectangle."""
        p = ctx.params
        ids = [int(i) for i in (p.get("frame_curves") or [])]
        if not ids:
            return al_layout.rounded_rectangle(float(p["frame_width"]), float(p["frame_height"]),
                                               float(p["frame_radius"]), (float(p["frame_y"]), float(p["frame_z"])))
        origin = np.asarray(p["position"], dtype=float)
        curves = []
        for e in ctx.entities(ids):
            g = e.get("geometry") or {}
            if g.get("type") != "curve":
                raise UserError(f"Frame: {e.get('name') or e['id']} is not a curve.")
            curves.append((curve_points(g) - origin)[:, 1:])
        if len(curves) != len(ids):
            raise UserError("Frame: a chosen curve no longer exists – choose the frame again.")
        return al_layout.chain(curves)

    def lens_system(self, ctx) -> al_lens.LensSystem:
        """The paraboloid and lens of the panel; kept until a setting changes."""
        p = ctx.params
        try:
            frame = self.frame_of(ctx)
            elements = tuple(al_lens.Element(float(r["y_from"]), float(r["y_to"]), float(r["z_from"]), float(r["z_to"]),
                                             float(r["deflect_h"]), float(r["deflect_v"]), float(r["spread_h"]),
                                             float(r["spread_v"])) for r in p["elements"])
            settings = al_lens.LensSettings(self.lamp_of(p), self.cutoff_of(p), elements, focal=float(p["focal"]),
                                            focus_behind=float(p["focus_behind"]), hole_radius=float(p["hole_radius"]),
                                            lens_x=float(p["lens_x"]), thickness=float(p["lens_thickness"]),
                                            index=float(p["lens_index"]), cell_width=float(p["cell_width"]),
                                            cell_height=float(p["cell_height"]))
            key = hashlib.sha256(repr(settings).encode() + frame.tobytes()).hexdigest()
            if getattr(self, "_lens", (None, None))[0] != key:
                def progress(fraction: float, text: str) -> None:
                    ctx.check_cancel()
                    ctx.progress(0.9 * fraction, text)

                self._lens = (key, al_lens.build(settings, frame, progress))
        except DesignError as e:
            raise UserError(str(e)) from e
        return self._lens[1]

    def _replace_parts(self, ctx, name: str) -> int:
        """Removes what the plugin generated before; the model-tree group for the new parts."""
        for e in ctx.entities():
            if (e.get("attributes") or {}).get("al.part"):
                ctx.remove(e["id"])
        return next((g["id"] for g in ctx.groups() if g["name"] == name), None) or ctx.add_group(name)

    def _generate_lens(self, ctx):
        system = self.lens_system(ctx)
        s = system.settings
        origin = tuple(float(v) for v in ctx.params["position"])
        group = self._replace_parts(ctx, f"Headlamp {s.lamp.name}")
        ctx.add(al_reflector.filament_surface(system.filament, origin), f"Filament {s.lamp.name}",
                {"al.part": "filament"}, group)
        faces = al_lens.faces(system, origin)
        for k, (kind, name, geometry) in enumerate(faces):
            ctx.check_cancel()
            ctx.add(geometry, name, {"al.part": kind}, group)
            ctx.progress(0.9 + 0.1 * (k + 1) / len(faces), "adding the faces …")
        for w in system.warnings:
            ctx.log(f"warning: {w}")
        ctx.log(f"paraboloid f = {s.focal:g} mm; lens at x = {s.lens_x + origin[0]:g} mm, {s.thickness:g} mm thick, "
                f"n = {s.index:g}: {system.cells} elements of {s.cell_width:g} x {s.cell_height:g} mm, their surfaces "
                f"from {system.sag[0]:.2f} to {system.sag[1]:.2f} mm about the base plane (slopes within "
                f"{system.fit_error:.1e} of the wanted ones)")
        return f"paraboloid and lens with {system.cells} elements"

    def reflector(self, ctx) -> al_reflector.Reflector:
        """The reflector of the panel; kept until a setting changes."""
        p = ctx.params
        try:
            frame = self.frame_of(ctx)
            settings = al_reflector.Settings(self.lamp_of(p), self.cutoff_of(p), zones_of(p["zones"]),
                                             focal=float(p["focal"]), strip_width=float(p["strip_width"]),
                                             facet_length=float(p["facet_length"]),
                                             hole_radius=float(p["hole_radius"]), knot_spacing=float(p["knot_spacing"]),
                                             connect=bool(p["connect"]), draft=float(p["draft"]),
                                             fillet=float(p["fillet"]))
            key = hashlib.sha256(repr(settings).encode() + frame.tobytes()).hexdigest()
            if getattr(self, "_built", (None, None))[0] != key:
                def progress(fraction: float, text: str) -> None:
                    ctx.check_cancel()
                    ctx.progress(0.9 * fraction, text)

                self._built = (key, al_reflector.build(settings, frame, progress))
        except DesignError as e:
            raise UserError(str(e)) from e
        return self._built[1]

    @action("Generate reflector", description="The mirror as trimmed NURBS faces – the facets and the connecting "
                                              "faces between them – and the filament")
    def generate(self, ctx):
        if ctx.params["system"] == PATTERNED:
            return self._generate_lens(ctx)
        r = self.reflector(ctx)
        origin = tuple(float(v) for v in ctx.params["position"])
        group = self._replace_parts(ctx, f"Reflector {r.settings.lamp.name}")   # a new reflector replaces the last
        ctx.add(al_reflector.filament_surface(r.filament, origin), f"Filament {r.settings.lamp.name}",
                {"al.part": "filament"}, group)
        faces = al_reflector.faces(r, origin)
        for k, (part, geometry) in enumerate(faces):
            ctx.check_cancel()
            attributes = {"al.part": "facet" if part.kind == al_reflector.FACET else "connection"}
            if part.cell >= 0:
                cell = r.cells[part.cell]
                attributes.update({"al.zone": cell.zone + 1, "al.strip": cell.strip, "al.row": cell.row,
                                   "al.branch": r.settings.zones[cell.zone].branch})
            ctx.add(geometry, part.label, attributes, group)
            ctx.progress(0.9 + 0.1 * (k + 1) / len(faces), "adding the faces …")
        for w in r.warnings:
            ctx.log(f"warning: {w}")
        held = [c.name for c, f in zip(r.cells, r.facets) if f.aim_limited]
        if held:
            ctx.log(f"aim held back in {len(held)} facets ({', '.join(held[:12])}{' …' if len(held) > 12 else ''}): "
                    "the mirror there cannot throw its light as far sideways as the zone asks")
        x0, x1 = r.depth()
        ctx.log(f"{len(r.cells)} facets in {len(r.settings.zones)} zones, mirror area {r.area / 100.0:.1f} cm² "
                f"(front view), x from {x0 + origin[0]:.1f} to {x1 + origin[0]:.1f} mm; the filament images lie "
                f"within {r.cutoff_error:.3f}° of the cut-off")
        connected = ""
        if r.transitions is not None:
            t = r.transitions
            parts = r.parts()
            lost = sum(p.area for p in parts if p.kind != al_reflector.FACET)
            _, N, _, index = r.samples(0.25, kinds=(al_reflector.ROW_BAND, al_reflector.STRIP_BAND, al_reflector.ZONE_BAND))
            steepest = float(np.max(np.hypot(N[:, 1], N[:, 2]) / N[:, 0])) if len(N) else 0.0
            ctx.log(f"{len(t.bands)} connecting faces: steps up to {t.max_step:.2f} mm, fillet radius {t.radius:g} mm, "
                    f"smallest draft angle {math.degrees(math.atan2(1.0, steepest)):.1f}° (set: {t.draft:g}°; less "
                    f"only where two walls meet), {100.0 * lost / r.area:.1f} % of the mirror area")
            connected = f", {len(t.bands)} connecting faces"
        return f"{len(r.cells)} facets{connected}, images within {r.cutoff_error:.3f}° of the cut-off"

    # ------------------------------------------------------------------ analysis
    @action("Filament images", description="The filament images of points all over the mirror on the measuring "
                                           "screen, with the cut-off line")
    def filament_images(self, ctx):
        count = int(ctx.params["image_points"])
        if ctx.params["system"] == PATTERNED:
            r = self.lens_system(ctx)
            P, N, _ = r.samples(max(0.5, math.sqrt(al_layout.area(r.frame) / count)))
            images = al_photometry.filament_images(P, N, r.filament, after=r.through)
        else:
            r = self.reflector(ctx)
            P, N, _, _ = r.samples(max(0.5, math.sqrt(r.area / count)), kinds=(al_reflector.FACET,))
            images = al_photometry.filament_images(P, N, r.filament)
        h_range, v_range = (-45.0, 45.0), (-15.0, 5.0)
        values, width, height = al_photometry.draw_images(images, r.settings.cutoff, h_range, v_range)
        run = ctx.result_set(f"Filament images {r.settings.lamp.name}")
        ctx.image(run, "Filament images", values, width, height, extent=(*h_range, *v_range), x_label="H / °",
                  y_label="V / °", colormap="viridis", unit="images",
                  description="outline of the filament image of each mirror point; the bright line is the cut-off")
        return f"{len(images)} filament images"

    @action("Light distribution", description="Luminous intensity of the low beam, the test points of UN/ECE R112 "
                                              "and the sharpness of the cut-off")
    def light_distribution(self, ctx):
        patterned = ctx.params["system"] == PATTERNED
        r = self.lens_system(ctx) if patterned else self.reflector(ctx)
        cutoff = r.settings.cutoff

        def progress(fraction: float, text: str) -> None:
            ctx.check_cancel()
            ctx.progress(0.9 + 0.1 * fraction, text)

        if patterned:
            P, N, A = r.samples(float(ctx.params["sampling"]))
            transmittance = float(ctx.params["lens_transmittance"])
            dist = al_photometry.intensity(r.settings.lamp, r.filament, P, N, A,
                                           np.full(len(P), float(ctx.params["reflectance"])),
                                           after=lambda origins, d: r.through(origins, d, transmittance),
                                           n_axial=8, n_around=16, progress=progress)
        else:
            dist = al_photometry.light_distribution(
                r, spacing=float(ctx.params["sampling"]), reflectance=float(ctx.params["reflectance"]),
                reflectance_connections=float(ctx.params["reflectance_connections"]), progress=progress)
        run = ctx.result_set(f"Low beam {r.settings.lamp.name}")
        ctx.image(run, "Luminous intensity", dist.intensity.reshape(-1), len(dist.h), len(dist.v),
                  extent=_extent(dist), x_label="H / °", y_label="V / °", unit="cd",
                  description=("mirror, then the lens (no light from the steps between its elements)" if patterned
                               else "single reflection at the facets and the connecting faces")
                  + "; 625 cd = 1 lx at 25 m")
        ctx.table(run, "R112 test points (class B, passing beam)",
                  ["point", "H / °", "V / °", "I / cd", "E at 25 m / lx", "required", ""],
                  al_photometry.test_points(dist, cutoff))
        side = -2.5 if cutoff.right_hand_traffic else 2.5
        columns = (dist.h >= side - 0.5) & (dist.h <= side + 0.5)
        ctx.curve(run, f"Vertical cut at H = {side:g}°", dist.v, dist.intensity[:, columns].mean(axis=1),
                  x_label="V / °", y_label="I / cd")
        rows = (dist.v >= -0.96) & (dist.v <= -0.76)
        ctx.curve(run, "Horizontal cut at V = -0.86°", dist.h, dist.intensity[rows].mean(axis=0),
                  x_label="H / °", y_label="I / cd")
        g, v_cut = al_photometry.sharpness(dist, cutoff)
        glare = al_photometry.glare(dist, cutoff)
        ctx.log(f"flux: lamp {dist.flux_lamp:.0f} lm, onto the mirror {dist.flux_mirror:.0f} lm, in the beam "
                f"{dist.flux_beam:.0f} lm, of it {dist.flux_connections:.0f} lm from the connecting faces; maximum "
                f"{dist.intensity.max():.0f} cd; cut-off at V = {v_cut:.2f}° with G = {g:.2f} (R112 asks for 0.13 … "
                f"0.40; the model's coil shines evenly and nothing scatters, a real lamp is softer); more than 0.2° "
                f"above the cut-off at most {glare:.0f} cd")
        return (f"{dist.flux_beam:.0f} lm in the beam ({100.0 * dist.flux_beam / dist.flux_lamp:.0f} %), maximum "
                f"{dist.intensity.max():.0f} cd, cut-off G = {g:.2f}")

    @action("Show strips", description="The start curve and some characteristic strips of every facet as lines")
    def show_strips(self, ctx):
        if ctx.params["system"] == PATTERNED:
            raise UserError("Strips belong to the facetted reflector (System: clear lens).")
        r = self.reflector(ctx)
        origin = np.asarray(ctx.params["position"], dtype=float)
        run = ctx.result_set(f"Strips {r.settings.lamp.name}")
        for name, curves in (("Start curves", [_within(f.start_curve[None], c) for f, c in zip(r.facets, r.cells)]),
                             ("Characteristic strips", [_within(f.strips, c) for f, c in zip(r.facets, r.cells)])):
            lines = [line for per_facet in curves for line in per_facet]
            if not lines:
                continue
            points = np.concatenate(lines) + origin
            starts = np.concatenate([[0], np.cumsum([len(line) for line in lines])])
            ctx.lines(run, name, points, starts, on_top=False)
        return f"strips of {len(r.facets)} facets"

    @action("Default zones", description="Sets the zone table for the chosen traffic side")
    def set_default_zones(self, ctx):
        ctx.set_params({"zones": default_zones(ctx.params["traffic"] == RIGHT)})
        return f"zones for {ctx.params['traffic']} traffic"


def _extent(dist) -> tuple[float, float, float, float]:
    dh, dv = dist.h[1] - dist.h[0], dist.v[1] - dist.v[0]
    return (float(dist.h[0] - 0.5 * dh), float(dist.h[-1] + 0.5 * dh),
            float(dist.v[0] - 0.5 * dv), float(dist.v[-1] + 0.5 * dv))


def _within(curves: np.ndarray, cell) -> list[np.ndarray]:
    """The parts of polylines (k, n, 3) inside the cell (front view), each as its own polyline."""
    out = []
    for curve in np.asarray(curves, dtype=float):
        inside = np.zeros(len(curve), dtype=bool)
        for piece in cell.pieces:
            inside |= al_layout.contains(piece, curve[:, 1:])
        edges = np.flatnonzero(np.diff(np.concatenate([[False], inside, [False]]).astype(int)))
        for a, b in zip(edges[::2], edges[1::2]):
            if b - a >= 2:
                out.append(curve[a:b])
    return out
