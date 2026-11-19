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
from dataclasses import replace
import math
import time

import numpy as np

from nfcad import Param, Plugin, UserError, action

import al_coil
import al_layout
import al_lens
import al_optimise
import al_photometry
import al_reflector
import al_trace
from al_design import DesignError
from al_layout import Zone
from al_optics import CUSTOM, HORIZONTAL, LAMPS, RISING, Cutoff, Filament, Lamp
from al_spline import curve_points

RIGHT, LEFT = "right-hand", "left-hand"
CLEAR, PATTERNED = "clear lens: facetted reflector", "patterned lens: paraboloid and lens"
LOW_BEAM = "low beam (UN R112, class B)"
CHECK_RAYS = 20_000_000          # Optimise lens: rays at least in its ray tracing (zone III within its noise)
# Optimise lens: what every cell begins with (al_optimise.optimise's starts)
CYLINDER_START = "cylinder lenses (6° across)"
OPTIMISE_STARTS = {CYLINDER_START: (al_optimise.CYLINDERS,), "plane glass": (None,),
                   "both, the better kept": (al_optimise.CYLINDERS, None)}
STARTED = {al_optimise.CYLINDERS: "cylinder lenses", None: "plane glass"}
# the patterned lens' structure (al_lens.LensSettings.structure)
STRIPS, CELLS = "cylinder strips through the sectors", "cells (a grid)"
STRUCTURES = {STRIPS: al_lens.STRIPS, CELLS: al_lens.CELLS}
# the lamp's parts in the model tree (Generate lamp): group and face names by their role in the ray tracing
_LAMP_PARTS = {al_trace.COIL: "Coil (lit)", al_trace.OFF: "Other coil (dark)", al_trace.SHIELD: "Shield",
               al_trace.BULB: "Bulb glass", al_trace.CAP: "Black top"}

_ELEMENT = {
    "y_from": Param.number(-500.0, decimals=1, unit="mm", label="y from"),
    "y_to": Param.number(500.0, decimals=1, unit="mm", label="y to"),
    "z_from": Param.number(-500.0, decimals=1, unit="mm", label="z from"),
    "z_to": Param.number(500.0, decimals=1, unit="mm", label="z to"),
    "deflect_h": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="deflect H"),
    "deflect_v": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="deflect V"),
    "spread_h": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="spread ± H"),
    "spread_v": Param.number(0.0, min=-60.0, max=60.0, decimals=2, unit="°", label="spread ± V"),
    "spread_angle": Param.number(0.0, min=-180.0, max=180.0, decimals=1, unit="°", label="spread turned by"),
    "sector": Param.integer(-1, min=-1, max=99, label="sector"),
}

_SECTOR = {
    "from": Param.number(0.0, min=-360.0, max=360.0, decimals=1, unit="°", label="from azimuth"),
    "branch": Param.choice([HORIZONTAL, RISING], HORIZONTAL, label="cut-off branch"),
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
                             description="filament length / diameter and luminous flux after UN/ECE R37 (nominal "
                                         "values); Custom takes the fields below. H3, P21W, PY21W, R10W, R5W "
                                         "have the filament across the axis"),
        "custom_length": Param.number(4.1, min=0.1, max=30.0, decimals=2, unit="mm", label="Custom: filament length",
                                      group="Lamp"),
        "custom_diameter": Param.number(1.3, min=0.05, max=10.0, decimals=2, unit="mm",
                                        label="Custom: filament diameter", group="Lamp"),
        "custom_flux": Param.number(1500.0, min=1.0, max=100000.0, decimals=0, unit="lm", label="Custom: luminous flux",
                                    group="Lamp"),
        "custom_watts": Param.number(55.0, min=0.1, max=1000.0, decimals=1, unit="W", label="Custom: power",
                                     group="Lamp", description="at 12 V; for the coil of the ray tracing"),
        "custom_across": Param.boolean(False, label="Custom: filament across the axis", group="Lamp",
                                       description="horizontal, at right angles to the lamp axis (H3, signal "
                                                   "lamps)"),
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
        "lens_rake": Param.number(0.0, min=-60.0, max=60.0, decimals=1, unit="°", label="Rake", group="Lens",
                                  description="the lens leans back: its top towards the mirror"),
        "lens_sweep": Param.number(0.0, min=-60.0, max=60.0, decimals=1, unit="°", label="Sweep", group="Lens",
                                   description="the lens runs back towards the left (negative: towards the right)"),
        "lens_radius": Param.number(0.0, min=0.0, max=100000.0, decimals=1, unit="mm", label="Dome radius",
                                    group="Lens", description="domed outwards as a sphere of this radius; 0: flat"),
        "wall_draft": Param.number(0.0, min=0.0, max=45.0, decimals=1, unit="°", label="Draft angle of the walls",
                                   group="Lens",
                                   description="between the walls of neighbouring elements and X; 0: walls along X. "
                                               "With a draft the walls are faces that join the elements smoothly"),
        "wall_fillet": Param.number(0.0, min=0.0, max=5.0, decimals=2, unit="mm", label="Fillet radius of the walls",
                                    group="Lens", description="at the foot and the head of every wall (with a draft)"),
        "lens_index": Param.number(1.49, min=1.01, max=3.0, decimals=3, label="Refractive index", group="Lens",
                                   description="PMMA 1.49, polycarbonate 1.59, glass about 1.52"),
        "lens_transmittance": Param.number(0.92, min=0.0, max=1.0, decimals=2, label="Transmittance", group="Lens"),
        "lens_structure": Param.choice(list(STRUCTURES), STRIPS, label="Structure", group="Lens",
                                       description="cylinder strips: cylinder lenses that run through their sector "
                                                   "in one piece, upright – leaning by the rise where the light ends "
                                                   "at the rising branch –, as the flutes of a classic lens; each strip "
                                                   "one element. Cells: a grid of elements, each a prism with a "
                                                   "cylinder lens of its own (steps between all of them)"),
        "lens_pitch": Param.number(5.0, min=0.5, max=100.0, decimals=2, unit="mm", label="Strip width", group="Lens",
                                   description="of the cylinder strips"),
        "lens_segment": Param.number(10.0, min=0.0, max=500.0, decimals=1, unit="mm", label="Strip segments",
                                     group="Lens",
                                     description="their length along the strips: each segment an element with a "
                                                 "prism of its own, the cylinder lens the strip's (Optimise lens "
                                                 "keeps it so) – it runs through, the prisms make steps; 0: every "
                                                 "strip in one piece (no prisms up or down)"),
        "optimise_least_spread": Param.number(0.0, min=0.0, max=12.0, decimals=1, unit="°",
                                              label="Optimise: strips spread at least", group="Lens",
                                              description="cylinder strips with segments: the weakest cylinder lens a "
                                                          "strip may have (± this across), so that every strip is one; "
                                                          "0: flat strips too, their segments' prisms alone spreading "
                                                          "the light (H4: R112 met only so – with 1° or 2° every strip "
                                                          "is curved, but 75R and zone III are missed)"),
        "cell_width": Param.number(10.0, min=0.5, max=500.0, decimals=2, unit="mm", label="Element width", group="Lens",
                                   description="of the cells (Structure: cells)"),
        "cell_height": Param.number(10.0, min=0.5, max=500.0, decimals=2, unit="mm", label="Element height",
                                    group="Lens", description="of the cells (Structure: cells)"),
        "focus_behind": Param.number(0.0, min=-50.0, max=50.0, decimals=2, unit="mm",
                                     label="Mirror focus behind the filament centre", group="Lens",
                                     description="0: the filament sits in the focus of the paraboloid (its focal "
                                                 "length: Reflector → Focal length)"),
        "lens_sectors": Param.table(_SECTOR, [], label="Sectors", group="Lens",
                                    description="radial sections of the lens about the lamp axis, as the zones of a "
                                                "clear-lens reflector: each from its azimuth (0 left, 90 up, seen in "
                                                "the driving direction) to the next one's, with the cut-off branch its "
                                                "light ends at; they cut the cells along radial lines, each part an "
                                                "element of its own (the element table's sector: their number by "
                                                "azimuth, from 0). Empty: one; Optimise lens (along the edges) then "
                                                "finds the wedge whose light ends at the rising branch"),
        "elements": Param.table(_ELEMENT, [{"y_from": -500.0, "y_to": 500.0, "z_from": -500.0, "z_to": 500.0,
                                            "deflect_h": 0.0, "deflect_v": -1.0, "spread_h": 15.0, "spread_v": 4.0,
                                            "spread_angle": 0.0}],
                                label="Elements", group="Lens",
                                description="what the cells of the lens do, by the place of their centre (the first "
                                            "row that holds it; y to the left, z up, about the lamp axis; a strip: "
                                            "its middle across, t = y cos φ − z sin φ with φ its lean, at z 0): by how "
                                            "much the light is turned in the cell's middle and the half spread "
                                            "about that, both turned by the angle (counter-clockwise on the "
                                            "screen: a cylinder lens, spread V 0, that spreads along the line "
                                            "rising by it); all 0: plane glass; a negative spread turns the "
                                            "element round (crossing rays)"),
        "optimise_margin": Param.number(10.0, min=0.0, max=50.0, decimals=1, unit="%", label="Optimise: margin",
                                        group="Lens", description="*Optimise lens*: how far within R112's limits "
                                                                  "the test points and zones are to lie"),
        "optimise_blur": Param.choice(["measured by ray tracing", "none"], "measured by ray tracing",
                                      label="Optimise: the lamp's blur", group="Lens",
                                      description="the lamp as it is (coil, bulb: the panel's Ray tracing settings) "
                                                  "makes the beam softer than the filament images: measured on the "
                                                  "plane lens and given to every cell's light, so that the margins "
                                                  "hold for it; the result is then checked by ray tracing"),
        "optimise_rounds": Param.integer(2, min=0, max=10, label="Optimise: rounds", group="Lens",
                                         description="how often the lens is built, checked and optimised again"),
        "optimise_uniformity": Param.number(1.0, min=0.0, max=100.0, decimals=2, label="Optimise: evenness",
                                            group="Lens",
                                            description="the weight of the beam's evenness below the cut-off: patches, "
                                                        "stripes and hot spots (bumps over 1° across, 0.3° up and down, "
                                                        "relative to 50R's minimum) cost; 0: R112 alone"),
        "optimise_edges": Param.boolean(True, label="Optimise: along the edges", group="Lens",
                                        description="every element spreads and deflects along the edge of its own "
                                                    "light, as the flutes of a classic lens: cylinders across where "
                                                    "the light ends at the horizontal branch, turned by the rise "
                                                    "(15°) in the wedge in front of the shield's slanting edge"),
        "optimise_band": Param.number(6000.0, min=0.0, max=50000.0, decimals=0, unit="cd",
                                      label="Optimise: under the cut-off", group="Lens",
                                      description="at least this on average 0.15–0.65° under the cut-off, ± 10° about "
                                                  "the kink: the beam brightest at its cut-off, as a real one, not in "
                                                  "a patch below it (0: as R112 alone asks)"),
        "optimise_rise": Param.number(3000.0, min=0.0, max=50000.0, decimals=0, unit="cd",
                                      label="Optimise: under the rise", group="Lens",
                                      description="at least this on average 0.15–0.35° under the rising branch, "
                                                  "1–5° from the kink, and above it at most a tenth: the kink seen, "
                                                  "the rise lit and sharp (0: not asked)"),
        "optimise_target": Param.number(0.3, min=0.0, max=100.0, decimals=2, label="Optimise: target beam",
                                        group="Lens",
                                        description="the weight of a target beam, the shape of a classic lens' one: "
                                                    "the mirror's light under the cut-off spread across (a core "
                                                    "to the driver's side, a wide part, both wider further down), "
                                                    "the wedge under the rise filled up to 1° – the whole field "
                                                    "fitted, not only the test points (0: none)"),
        "optimise_start": Param.choice(list(OPTIMISE_STARTS), CYLINDER_START, label="Optimise: start with",
                                       group="Lens",
                                       description="what every cell begins with: the search stays near it – from "
                                                   "plane glass it mostly makes prisms, from cylinder lenses it "
                                                   "keeps many of them (a more even beam); both: two searches, the "
                                                   "better kept (twice the time)"),
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
        "test_points": Param.choice([LOW_BEAM, *al_photometry.SIGNAL_LAMPS], LOW_BEAM, label="Test points",
                                    group="Analysis",
                                    description="the table of Light distribution: the low beam's points, or the "
                                                "standard light distribution of a signal lamp (UN R148) with its "
                                                "minimum on the axis and its maximum"),
        "shadows": Param.boolean(True, label="Shadows of the steps", group="Analysis",
                                 description="facetted reflector with connecting faces: a ray that a step of the "
                                             "mirror stops on its way from the coil is left out; one it stops after "
                                             "the reflection is reflected there a second time (takes longer)"),
        "direct": Param.boolean(True, label="Direct light of the lamp", group="Analysis",
                                description="light that leaves the coil forwards past the mirror – over an H4's "
                                            "shield and around its cap; with the patterned lens through the lens"),
        "sampling": Param.number(1.0, min=0.2, max=10.0, decimals=2, unit="mm", label="Mirror points every",
                                 group="Analysis", description="lattice of the light distribution"),
        "image_points": Param.integer(150, min=1, max=5000, label="Filament images (number)", group="Analysis"),
        "trace_rays": Param.integer(5_000_000, min=10_000, max=2_000_000_000, label="Light paths", group="Ray tracing",
                                    description="from the coil's wire; the noise of a cell of the screen falls with "
                                                "their root (5 million: some 5 % where the beam is brightest)"),
        "trace_depth": Param.integer(20, min=1, max=100, unit="segments", label="Longest path", group="Ray tracing",
                                     description="reflections and refractions a light path may have before it ends "
                                                 "(through the bulb alone: two)"),
        "trace_filament": Param.choice(["passing beam", "driving beam"], "passing beam", label="H4: lit coil",
                                       group="Ray tracing",
                                       description="driving beam: the H4's other coil (behind the shield, R37) lit – "
                                                   "the same reflector's high beam, with the driving-beam points of "
                                                   "R112"),
        "coil_end_temperature": Param.number(2400.0, min=1000.0, max=3100.0, decimals=0, unit="K",
                                             label="Coil: temperature at its ends", group="Ray tracing",
                                             description="the leads cool the coil's ends (assumed 2400 K), its middle "
                                                         "is at 3100 K; 3100: the coil shines evenly"),
        "bulb": Param.boolean(True, label="Bulb glass", group="Ray tracing",
                              description="the bulb as glass (Fresnel) with its black top; off: no glass, the black "
                                          "top as a disc across the bulb"),
        "bulb_diameter": Param.number(0.0, min=0.0, max=60.0, decimals=2, unit="mm", label="Bulb: outer diameter",
                                      group="Ray tracing", description="0: typical of the lamp (H7 9 mm, H4 13 mm)"),
        "bulb_wall": Param.number(0.0, min=0.0, max=5.0, decimals=2, unit="mm", label="Bulb: wall",
                                  group="Ray tracing", description="0: typical (quartz 1 mm, signal lamps 0.6–0.7 mm)"),
        "shield_reflectance": Param.number(0.5, min=0.0, max=1.0, decimals=2, label="H4 shield: reflectance",
                                           group="Ray tracing",
                                           description="the shield's shining metal as a mirror (assumed 0.5); 0: black"),
        "coil_wire": Param.number(0.0, min=0.0, max=2.0, decimals=3, unit="mm", label="Coil: wire diameter",
                                  group="Ray tracing", description="0: estimated from the lamp's power (tungsten "
                                                                   "at 3100 K, 13.2 V)"),
        "coil_turns": Param.integer(0, min=0, max=1000, label="Coil: turns", group="Ray tracing",
                                    description="0: a pitch of 1.5 wire diameters"),
        "trace_kernel": Param.choice(["automatic", "C++", "NumPy"], "automatic", label="Kernel", group="Ray tracing",
                                     description="the Path Tracer plugin's: C++ (package pathtracer 0.3.0 or later) "
                                                 "if installed – NumPy takes minutes for a reflector"),
    }

    # ------------------------------------------------------------------ the reflector
    @staticmethod
    def lamp_of(params: dict) -> Lamp:
        if params["lamp"] != CUSTOM:
            return LAMPS[params["lamp"]]
        return Lamp(CUSTOM, float(params["custom_length"]), float(params["custom_diameter"]),
                    float(params["custom_flux"]), axial=not params["custom_across"], watts=float(params["custom_watts"]))

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
                                             float(r["spread_v"]), float(r.get("spread_angle") or 0.0),
                                             -1 if r.get("sector") is None else int(r["sector"]))
                             for r in p["elements"])
            sectors = tuple(al_lens.Sector(float(r["from"]), str(r["branch"])) for r in p.get("lens_sectors") or [])
            settings = al_lens.LensSettings(self.lamp_of(p), self.cutoff_of(p), elements, focal=float(p["focal"]),
                                            focus_behind=float(p["focus_behind"]), hole_radius=float(p["hole_radius"]),
                                            lens_x=float(p["lens_x"]), thickness=float(p["lens_thickness"]),
                                            index=float(p["lens_index"]), cell_width=float(p["cell_width"]),
                                            cell_height=float(p["cell_height"]), rake=float(p["lens_rake"]),
                                            sweep=float(p["lens_sweep"]), radius=float(p["lens_radius"]),
                                            wall_draft=float(p["wall_draft"]), wall_fillet=float(p["wall_fillet"]),
                                            sectors=sectors, structure=STRUCTURES[p["lens_structure"]],
                                            pitch=float(p["lens_pitch"]), segment=float(p["lens_segment"]))
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
        form = ", ".join(text for value, text in ((s.rake, f"rake {s.rake:g}°"), (s.sweep, f"sweep {s.sweep:g}°"),
                                                  (s.radius, f"dome radius {s.radius:g} mm")) if value) or "flat, upright"
        what = (f"cylinder strips {s.pitch:g} mm wide" + (f" in {system.cells} segments of up to {s.segment:g} mm"
                                                          if s.segment > 0.0 else f", {system.cells} of them")
                if system.strips
                else f"{system.cells} elements of {s.cell_width:g} x {s.cell_height:g} mm")
        ctx.log(f"paraboloid f = {s.focal:g} mm; lens at x = {s.lens_x + origin[0]:g} mm on the axis ({form}), "
                f"{s.thickness:g} mm thick, n = {s.index:g}: {what}, their surfaces from {system.sag[0]:.2f} to "
                f"{system.sag[1]:.2f} mm about the lens' shape (slopes within {system.fit_error:.1e} of the wanted ones)")
        return f"paraboloid and lens with {system.cells} " + ("strips" if system.strips else "elements")

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

        function = ctx.params["test_points"]
        # a signal lamp is measured up to ± 20° / ± 10° about its axis, coarser than a cut-off needs
        field = {} if function == LOW_BEAM else {"h_range": (-40.0, 40.0), "v_range": (-20.0, 20.0), "dv": 0.25}
        if patterned:
            dist = self._lens_distribution(r, ctx.params, progress, field)
        else:
            dist = al_photometry.light_distribution(
                r, spacing=float(ctx.params["sampling"]), reflectance=float(ctx.params["reflectance"]),
                reflectance_connections=float(ctx.params["reflectance_connections"]),
                shadows=bool(ctx.params["shadows"]), direct=bool(ctx.params["direct"]), progress=progress, **field)
            if ctx.params["shadows"] and r.transitions is not None:
                ctx.log(f"shadows of the steps: {dist.flux_shadow:.0f} lm of the light onto the mirror are stopped "
                        f"by a step ({100.0 * dist.flux_shadow / max(dist.flux_mirror, 1e-9):.1f} %); what is stopped "
                        "after the reflection is reflected there once more and counts as stray light")
        if ctx.params["direct"]:
            ctx.log(f"direct light of the lamp: {dist.flux_direct:.0f} lm leave it forwards past the mirror"
                    + " (not counted in the flux of the beam)"
                    + (" and through the lens" if patterned else "")
                    + f", up to {dist.direct_max:.0f} cd on the screen"
                    + (" (the H4's cap stops what goes forwards within about 40° of the axis)"
                       if r.settings.lamp.shield is not None and r.settings.lamp.shield.cap_x is not None else ""))
        self._present(ctx, dist, r, f"Low beam {r.settings.lamp.name}",
                      ("mirror, then the lens (no light from the steps between its elements)" if patterned
                       else "single reflection at the facets and the connecting faces")
                      + ("; with the lamp's direct light" if ctx.params["direct"] else ""))
        if patterned:
            ctx.log(f"walls between the lens elements: {dist.flux_walls:.0f} lm meet them "
                    f"({100.0 * dist.flux_walls / max(dist.flux_mirror, 1e-9):.1f} % of the light from the mirror), "
                    f"{dist.flux_connections:.0f} lm of it go on as stray light")
        if function != LOW_BEAM:
            failed = [row[0] for row in al_photometry.signal_points(dist, function) if row[-1] != "ok"]
            ctx.log(f"flux: lamp {dist.flux_lamp:.0f} lm, onto the mirror {dist.flux_mirror:.0f} lm, in the beam "
                    f"{dist.flux_beam:.0f} lm; maximum {dist.intensity.max():.0f} cd; {function}: "
                    + ("all points met" if not failed else "not met: " + ", ".join(failed)))
            return (f"{dist.flux_beam:.0f} lm in the beam ({100.0 * dist.flux_beam / dist.flux_lamp:.0f} %), maximum "
                    f"{dist.intensity.max():.0f} cd, {function}: " + ("met" if not failed else f"{len(failed)} not met"))
        g, v_cut = al_photometry.sharpness(dist, cutoff)
        glare = al_photometry.glare(dist, cutoff)
        ctx.log(f"flux: lamp {dist.flux_lamp:.0f} lm, onto the mirror {dist.flux_mirror:.0f} lm, in the beam "
                f"{dist.flux_beam:.0f} lm, of it {dist.flux_connections:.0f} lm from the connecting faces; maximum "
                f"{dist.intensity.max():.0f} cd; cut-off at V = {v_cut:.2f}° with G = {g:.2f} (R112 asks for 0.13 … "
                f"0.40; the model's coil shines evenly and nothing scatters, a real lamp is softer); more than 0.2° "
                f"above the cut-off at most {glare:.0f} cd")
        return (f"{dist.flux_beam:.0f} lm in the beam ({100.0 * dist.flux_beam / dist.flux_lamp:.0f} %), maximum "
                f"{dist.intensity.max():.0f} cd, cut-off G = {g:.2f}")

    @staticmethod
    def _traced_lamp(p: dict, lamp: Lamp, filament: Filament):
        """The lamp of the ray tracing as the panel has it: (the lit coil, the other coil or None,
        the lit coil's lamp, the bulb). ValueError: the coil or the bulb cannot be built."""
        second = al_coil.driving_coil(lamp)
        driving = p["trace_filament"] == "driving beam"
        if driving and second is None:
            raise UserError("Only the H4 has a driving-beam coil (H4: lit coil).")
        wire, turns = float(p["coil_wire"]), int(p["coil_turns"])
        if second is None:
            coil, other, lit = al_coil.coil_of(lamp, filament, wire, turns), None, lamp
        elif driving:
            lit, offset = second
            coil = al_coil.coil_of(lit, filament, wire, turns, offset)
            other = al_coil.coil_of(lamp, filament)
        else:
            coil, lit = al_coil.coil_of(lamp, filament, wire, turns), lamp
            other = al_coil.coil_of(second[0], filament, offset=second[1])
        bulb = al_coil.bulb_of(lamp, float(p["bulb_diameter"]), float(p["bulb_wall"]),
                               [c for c in (coil, other) if c is not None])
        return coil, other, lit, bulb

    @staticmethod
    def _lamp_bodies(p: dict, lamp: Lamp, coil, other, bulb) -> list:
        """The lamp's bodies of the ray tracing (al_trace.lamp_bodies) with the panel's settings."""
        return al_trace.lamp_bodies(lamp, coil, other=other, bulb=bulb, glass=bool(p["bulb"]),
                                    end=float(p["coil_end_temperature"]),
                                    shield_reflectance=float(p["shield_reflectance"]))

    def _lamp_groups(self, ctx, name: str, roles: list[str]) -> dict[str, int]:
        """Removes the lamp generated before; the model-tree groups for the new one – `name` and
        in it one per part of `roles`. Groups the old lamp leaves empty are removed."""
        entities = ctx.entities()
        old = [e for e in entities if (e.get("attributes") or {}).get("al.lamp")]
        gone = {e["id"] for e in old}
        for e in old:
            ctx.remove(e["id"])
        groups = ctx.groups()

        def group(label: str, parent: int) -> int:
            return next((g["id"] for g in groups if g["name"] == label and int(g.get("parent") or 0) == parent),
                        None) or ctx.add_group(label, parent)

        top = group(name, 0)
        out = {role: group(_LAMP_PARTS[role], top) for role in roles}
        keep = {top, *out.values()} | {int(e.get("group") or 0) for e in entities if e["id"] not in gone}
        parent_of = {g["id"]: int(g.get("parent") or 0) for g in groups}
        left = {int(e.get("group") or 0) for e in old} - keep - {0}        # the old lamp's part groups
        above = {parent_of.get(g, 0) for g in left} - keep - {0}             # and the groups they were in
        for g in [*sorted(left), *sorted(above)]:
            if g in parent_of and not any(parent == g for parent in parent_of.values()):
                ctx.remove_group(g)
                del parent_of[g]
        return out

    @action("Generate lamp", description="The lamp as the ray tracing has it, as NURBS faces: the coil's wire, the "
                                         "bulb's glass and black top, the H4's shield and other coil (group Ray "
                                         "tracing) – to look at what is traced; hide the bulb glass and the filament's "
                                         "cylinder in the model tree to see the coil")
    def generate_lamp(self, ctx):
        p = ctx.params
        lamp = self.lamp_of(p)
        try:
            coil, other, lit, bulb = self._traced_lamp(p, lamp, Filament.of(lamp))
            bodies = self._lamp_bodies(p, lamp, coil, other, bulb)
        except (RuntimeError, ValueError) as e:
            raise UserError(str(e)) from e
        origin = np.asarray(p["position"], dtype=float)
        roles = [role for role in _LAMP_PARTS if any(b.role == role for b in bodies)]
        groups = self._lamp_groups(ctx, f"Lamp {lamp.name}", roles)
        count = {role: sum(len(b.faces) for b in bodies if b.role == role) for role in roles}
        done = dict.fromkeys(roles, 0)
        total = sum(count.values())
        for body in bodies:
            for face in body.faces:
                ctx.check_cancel()
                k = done[body.role] = done[body.role] + 1
                label = _LAMP_PARTS[body.role].split(" (")[0]
                if body.role == al_trace.COIL:                       # the trace's pieces of the wire, by turn
                    name = f"{label} {(k - 1) // al_trace.PIECES + 1}.{(k - 1) % al_trace.PIECES + 1}"
                else:
                    name = f"{label} {k}" if count[body.role] > 1 else label
                attributes = {"al.lamp": body.role, "al.material": str(body.material.get("kind", ""))}
                if body.emission > 0.0:
                    attributes["al.luminance"] = round(float(body.emission), 4)
                ctx.add(_placed(face, origin), name, attributes, groups[body.role])
                ctx.progress(sum(done.values()) / total, "adding the lamp's faces …")
        ctx.log(f"lamp {lamp.name} as the ray tracing has it, in the group Lamp {lamp.name}: "
                + ", ".join(f"{_LAMP_PARTS[role].lower()} {count[role]} faces" for role in roles)
                + f"; lit: {lit.name}, {coil.turns} turns of {coil.wire:.3f} mm wire (al.luminance: the luminance of "
                  "each piece of the wire against the coil's middle)")
        hide = (["the group Bulb glass (glass is drawn like any other face)"] if al_trace.BULB in roles else []) + [
            "the filament's cylinder of Generate reflector (the wire touches it from inside)"]
        ctx.log(f"to see the coil{' and the shield' if lamp.shield is not None else ''}, hide in the model tree: "
                + " and ".join(hide))
        return f"lamp {lamp.name}: {total} faces in {len(roles)} groups"

    @action("Light distribution (ray tracing)",
            description="The same by ray tracing: the coil as a helix of wire, the bulb, the H4's shield and cap, the "
                        "mirror and the lens as surfaces; light paths from the wire through every reflection and "
                        "refraction, traced by the Path Tracer plugin's kernel")
    def light_distribution_traced(self, ctx):
        p = ctx.params
        patterned = p["system"] == PATTERNED
        r = self.lens_system(ctx) if patterned else self.reflector(ctx)
        lamp, cutoff, function = r.settings.lamp, r.settings.cutoff, p["test_points"]
        driving = p["trace_filament"] == "driving beam"
        field = {} if function == LOW_BEAM else {"h_range": (-40.0, 40.0), "v_range": (-20.0, 20.0), "dv": 0.25}
        try:
            kernel = al_trace.kernel(p["trace_kernel"])
            coil, other, lit, bulb = self._traced_lamp(p, lamp, r.filament)
            ctx.progress(0.9, "the scene: coil, lamp, mirror" + (" and lens" if patterned else "") + " …")
            bodies = self._lamp_bodies(p, lamp, coil, other, bulb) + (
                al_trace.lens_bodies(r, float(p["reflectance"])) if patterned else
                al_trace.reflector_bodies(r, float(p["reflectance"]), float(p["reflectance_connections"])))

            def progress(fraction: float, text: str) -> None:
                ctx.check_cancel()
                ctx.progress(0.9 + 0.1 * fraction, text)

            start = time.time()
            dist, info = al_trace.trace(bodies, lit, coil, rays=int(p["trace_rays"]), depth=int(p["trace_depth"]),
                                        kernel_name=kernel, progress=progress, **field)
        except (RuntimeError, ValueError) as e:
            raise UserError(str(e)) from e
        ctx.log(f"ray tracing with the {kernel} kernel: {info.rays:,} light paths, {info.traced:,} rays, "
                f"{info.triangles:,} triangles, {time.time() - start:.1f} s")
        estimated = [what for what, given in (("wire", p["coil_wire"]), ("turns", p["coil_turns"])) if not given]
        ctx.log(f"coil{' (driving beam)' if driving else ''}: {coil.turns} turns of {coil.wire:.3f} mm wire, pitch "
                f"{coil.pitch:.3f} mm, {coil.wire_length:.0f} mm of wire"
                + (f" ({' and '.join(estimated)} estimated)" if estimated else "")
                + f"; {100.0 * info.coil_share:.0f} % of the wire's light gets out of the coil, the rest meets its "
                  "other turns")
        end = float(p["coil_end_temperature"])
        if end < al_coil.T_COIL:
            glow = al_coil.emission(coil, al_trace.PIECES, end)
            ctx.log(f"coil's ends at {end:.0f} K (middle {al_coil.T_COIL:.0f} K): its first and last turns shine at "
                    f"{100.0 * glow[:al_trace.PIECES].mean():.0f} % of the middle's luminance, the coil as a whole at "
                    f"{100.0 * glow.mean():.0f} %")
        ctx.log(f"bulb: {'glass' if p['bulb'] else 'no glass'} (n = {bulb.index:g}), {2.0 * bulb.radius:g} mm across, "
                f"wall {bulb.wall:g} mm, tip {bulb.tip:g} mm in front of the coil"
                + (f", black from {bulb.cap_x:.1f} mm on" if bulb.cap_x is not None else ", no black top")
                + (f"; the shield reflects {100.0 * float(p['shield_reflectance']):.0f} % (mirror)"
                   if lamp.shield is not None else "")
                + ("; the other coil dark in its place" if other is not None else ""))
        own = lit.flux / info.coil_share - lit.flux                 # what the coil's turns take of their own light
        ctx.log(f"flux: lamp {lit.flux:.0f} lm; in the beam {dist.flux_beam:.0f} lm (by the mirror), of it "
                f"{dist.flux_connections:.0f} lm by the connecting faces; direct {dist.flux_direct:.0f} lm forwards, "
                f"not by the mirror{' (through the lens)' if patterned else ''}, up to {dist.direct_max:.0f} cd; "
                f"backwards {info.flux_back:.0f} lm; "
                + (f"into the housing beside the lens {info.flux_housing:.0f} lm; " if patterned else "")
                + f"absorbed {max(info.flux_lost - own, 0.0):.0f} lm (lamp, mirror)")
        if patterned:
            ctx.log(f"the lens refracts and reflects by Fresnel (n = {r.settings.index:g}): *Transmittance* is not "
                    "used here")
        if math.isfinite(info.noise):
            ctx.log(f"noise: {100.0 * info.noise:.1f} % per cell where the light is brightest (standard error; four "
                    f"times the light paths halve it)")
        description = (f"ray tracing ({kernel}): the coil as a helix of wire, every reflection and refraction, with the "
                       "lamp's direct light")
        if driving:
            self._present(ctx, dist, r, "Driving beam H4 – ray tracing", description, driving=True)
            failed = [row[0] for row in al_photometry.driving_points(dist) if row[-1] != "ok"]
            return (f"ray tracing, driving beam: {dist.flux_beam:.0f} lm in the beam, maximum "
                    f"{dist.intensity.max():.0f} cd, R112: " + ("met" if not failed else f"{', '.join(failed)} not met"))
        self._present(ctx, dist, r, f"Low beam {lamp.name} – ray tracing", description)
        if function != LOW_BEAM:
            failed = [row[0] for row in al_photometry.signal_points(dist, function) if row[-1] != "ok"]
            return (f"ray tracing: {dist.flux_beam:.0f} lm in the beam, maximum {dist.intensity.max():.0f} cd, "
                    f"{function}: " + ("met" if not failed else f"{len(failed)} not met"))
        g, v_cut = al_photometry.sharpness(dist, cutoff)
        glare = al_photometry.glare(dist, cutoff)
        ctx.log(f"maximum {dist.intensity.max():.0f} cd; cut-off at V = {v_cut:.2f}° with G = {g:.2f}; more than 0.2° "
                f"above the cut-off at most {glare:.0f} cd")
        return (f"ray tracing: {dist.flux_beam:.0f} lm in the beam, maximum {dist.intensity.max():.0f} cd, "
                f"cut-off G = {g:.2f}")

    @staticmethod
    def _lens_distribution(r, params, progress=None, field=None):
        """The light distribution of the paraboloid and lens `r` (filament images), with the lamp's
        direct light through the lens if the panel says so."""
        field = field or {}
        P, N, A = r.samples(float(params["sampling"]))
        transmittance = float(params["lens_transmittance"])
        dist = al_photometry.intensity(r.settings.lamp, r.filament, P, N, A, np.full(len(P), float(params["reflectance"])),
                                       after=lambda origins, d: r.through(origins, d, transmittance),
                                       n_axial=8, n_around=16, progress=progress, **field)
        if params["direct"]:             # as far as the elements may turn light into the screen
            spread = [abs(e.spread_h) + abs(e.spread_v) if e.spread_angle else None for e in r.settings.elements]
            reach = [max([abs(e.deflect_h) + (abs(e.spread_h) if w is None else w)
                          for e, w in zip(r.settings.elements, spread)] + [0.0]),
                     max([abs(e.deflect_v) + (abs(e.spread_v) if w is None else w)
                          for e, w in zip(r.settings.elements, spread)] + [0.0])]
            dist.add_direct(*al_photometry.direct_light(
                r.settings.lamp, r.filament, dist.h, dist.v, progress=progress,
                after=lambda origins, d: r.through(origins, d, transmittance),
                margin=(reach[0] + 5.0, reach[1] + 5.0)))
        return dist

    @staticmethod
    def _present(ctx, dist, r, title: str, description: str, driving: bool = False):
        """The intensity as an image, the table of the test points and two cuts, in a new result set."""
        function = "driving" if driving else ctx.params["test_points"]
        cutoff = r.settings.cutoff
        run = ctx.result_set(title)
        ctx.image(run, "Luminous intensity", dist.intensity.reshape(-1), len(dist.h), len(dist.v),
                  extent=_extent(dist), x_label="H / °", y_label="V / °", unit="cd",
                  description=description + "; 625 cd = 1 lx at 25 m")
        if function == LOW_BEAM:
            ctx.table(run, "R112 test points (class B, passing beam)",
                      ["point", "H / °", "V / °", "I / cd", "E at 25 m / lx", "required", ""],
                      al_photometry.test_points(dist, cutoff))
        elif driving:
            ctx.table(run, "R112 test points (class B, driving beam)",
                      ["point", "H / °", "V / °", "I / cd", "E at 25 m / lx", "required", ""],
                      al_photometry.driving_points(dist))
        else:
            ctx.table(run, f"R148 standard light distribution, {function}",
                      ["point", "H / °", "V / °", "I / cd", "required", ""],
                      al_photometry.signal_points(dist, function))
        # the cuts: through the cut-off and the 50 m line of a low beam, through the axis of a signal lamp
        side = 0.0 if function != LOW_BEAM else -2.5 if cutoff.right_hand_traffic else 2.5
        level = -0.86 if function == LOW_BEAM else 0.0
        columns = (dist.h >= side - 0.5) & (dist.h <= side + 0.5)
        ctx.curve(run, f"Vertical cut at H = {side:g}°", dist.v, dist.intensity[:, columns].mean(axis=1),
                  x_label="V / °", y_label="I / cd")
        rows = (dist.v >= level - 0.25) & (dist.v <= level + 0.25)
        ctx.curve(run, f"Horizontal cut at V = {level:g}°", dist.h, dist.intensity[rows].mean(axis=0),
                  x_label="H / °", y_label="I / cd")
        return run

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

    @action("Optimise lens",
            description="Chooses every cell's element (a prism and a cylinder lens: deflection, spread and its "
                        "direction) – every strip's (deflection and spread along its lean) – so that the low beam "
                        "meets the R112 test points and zones with the margin – for a lamp whose shield makes the "
                        "cut-off (H4); sets the element table, one row per cell or strip")
    def optimise_lens(self, ctx):
        p = ctx.params
        if p["system"] != PATTERNED:
            raise UserError("Optimise lens belongs to the patterned lens (System: patterned lens).")
        if p["test_points"] != LOW_BEAM:
            raise UserError("Optimise lens aims at the low beam's test points (Analysis: test points).")
        r = self.lens_system(ctx)
        frame = self.frame_of(ctx)
        traced = p["optimise_blur"] == "measured by ray tracing"
        if traced:
            try:
                al_trace.kernel(p["trace_kernel"])
            except RuntimeError as e:
                raise UserError(str(e)) from e
        if r.settings.lamp.shield is None:
            ctx.log(f"{r.settings.lamp.name} has no shield: the paraboloid makes no cut-off – the lens alone cannot "
                    "meet the low beam's limits above it")

        def trace(system, rays: int | None = None):
            coil, other, lit, bulb = self._traced_lamp(p, system.settings.lamp, system.filament)
            bodies = self._lamp_bodies(p, system.settings.lamp, coil, other, bulb) + \
                al_trace.lens_bodies(system, float(p["reflectance"]))
            dist, _ = al_trace.trace(bodies, lit, coil, rays=rays or int(p["trace_rays"]), depth=int(p["trace_depth"]),
                                     kernel_name=al_trace.kernel(p["trace_kernel"]))
            return dist

        def check(system):      # the lens' ray tracing: enough rays that its noise does not count (zone III)
            return trace(system, max(int(p["trace_rays"]), CHECK_RAYS))

        def progress(fraction: float, text: str) -> None:
            ctx.check_cancel()
            ctx.progress(fraction, text)

        starts = OPTIMISE_STARTS[p["optimise_start"]]

        def log(r_: int, sweeps: int, values: dict) -> None:
            begun = f"start {values['start'] + 1} ({STARTED[starts[values['start']]]}), " if len(starts) > 1 else ""
            if values.get("traced") is True:
                ctx.log(f"{begun}the lens so far, ray traced: " + ", ".join(
                    f"{k} {v:.0f}" for k, v in values["model"].items()) + " cd")
                return
            if values.get("checked"):
                ctx.log(f"{begun}after the ray tracing: {sweeps} sweeps; " + ", ".join(
                    f"{k} {values['surrogate'][k]:.0f}/{values['model'][k]:.0f}/{values['traced'][k]:.0f}"
                    for k in values["model"]) + " cd (the surrogate's / the filament images' with what the ray "
                    "tracing added / the ray tracing's)")
                return
            ctx.log(f"{begun}round {r_ + 1}: {sweeps} sweeps; " + ", ".join(
                f"{k} {values['surrogate'][k]:.0f}/{values['model'][k]:.0f}" for k in values["model"])
                + " cd (the surrogate's / the filament images'); bumps "
                + "/".join(f"{100.0 * b:.1f}" for b in values["bumps"]) + " % of 50R's minimum"
                + ("; off the target beam by " + "/".join(f"{100.0 * f:.0f}" for f in values["fit"]) + " %"
                   if "fit" in values else ""))

        start = time.time()
        blur = (0.0, 0.0)
        try:
            if traced:          # how much softer the lamp as it is makes the plane lens' beam than the filament images
                ctx.progress(0.0, "the plane lens: filament images and ray tracing …")
                plane = al_lens.build(replace(r.settings, elements=(al_lens.Element(-1e9, 1e9, -1e9, 1e9),),
                                              wall_draft=0.0), frame)
                sh, sv, err = al_optimise.fit_blur(self._lens_distribution(plane, p), trace(plane))
                blur = (sh, sv)
                ctx.log(f"the lamp as it is blurs the plane lens' beam by σ = {sh:g}° (H) × {sv:g}° (V) against the "
                        f"filament images ({100.0 * err:.0f} % relative difference left where it is bright)")
            result = al_optimise.optimise(r.settings, frame, lambda system: self._lens_distribution(system, p),
                                          margin=float(p["optimise_margin"]) / 100.0,
                                          rounds=int(p["optimise_rounds"]), blur=blur,
                                          spacing=float(p["sampling"]), reflectance=float(p["reflectance"]),
                                          transmittance=float(p["lens_transmittance"]), direct=bool(p["direct"]),
                                          progress=progress, log=log, uniformity=float(p["optimise_uniformity"]),
                                          starts=starts, along_edges=bool(p["optimise_edges"]),
                                          band=float(p["optimise_band"]), rise=float(p["optimise_rise"]),
                                          check=check if traced else None, fit=float(p["optimise_target"]),
                                          least=float(p["optimise_least_spread"]))
            if result.scouted:
                kept = min(result.scouted, key=lambda x: x[2])
                ctx.log("the sectors searched: " + ", ".join(
                    f"rising {a:g}°–{b:g}° {s:.4g}" for a, b, s in result.scouted)
                    + f" (the surrogate's objective) – kept: rising from {kept[0]:g}° to {kept[1]:g}°")
            if traced:
                ctx.log("kept: " + ("the lens optimised once more for what the ray tracing adds" if result.checked
                                    else "the lens before (the one optimised once more is worse in the ray tracing)"))
            if len(starts) > 1:
                ctx.log(f"kept: the search from {STARTED[starts[result.start]]}")
            checked = result.traced
        except (DesignError, RuntimeError, ValueError) as e:
            raise UserError(str(e)) from e
        rows = [{"y_from": e.y0, "y_to": e.y1, "z_from": e.z0, "z_to": e.z1, "deflect_h": e.deflect_h,
                 "deflect_v": e.deflect_v, "spread_h": e.spread_h, "spread_v": e.spread_v, "spread_angle": e.spread_angle,
                 "sector": e.sector}
                for e in result.elements]
        changes = {"elements": rows}
        if result.sectors and not p.get("lens_sectors"):
            changes["lens_sectors"] = [{"from": x.az_from, "branch": x.branch} for x in result.sectors]
            spans = ", ".join(f"{x.branch} from {x.az_from:g}°" for x in result.sectors)
            ctx.log(f"the lens cut into sectors ({spans}): the wedge whose light ends at the rising branch, cut out "
                    "along radial lines – the sector table now has them")
        ctx.set_params(changes)
        cutoff = r.settings.cutoff
        verdicts = []
        for name, dist in (("filament images", result.dist), ("ray tracing", checked)):
            if dist is None:
                continue
            self._present(ctx, dist, r, f"Low beam {r.settings.lamp.name} – optimised lens, {name}",
                          f"the optimised lens ({len(rows)} elements), {name}")
            failed = [row[0] for row in al_photometry.test_points(dist, cutoff) if row[-1] != "ok"]
            g, v_cut = al_photometry.sharpness(dist, cutoff)
            ctx.log(f"{name}: R112 " + ("met" if not failed else "not met: " + ", ".join(failed))
                    + f"; cut-off at V = {v_cut:.2f}° with G = {g:.2f}")
            verdicts.append(f"{name}: R112 " + ("met" if not failed else "not met: " + ", ".join(failed)))
        ctx.log(f"optimised {len(rows)} elements in {time.time() - start:.0f} s; the element table now has a row per "
                + ("strip segment" if r.strips else "cell (per part of a cell cut by the sectors)"))
        return f"lens optimised ({len(rows)} elements); " + "; ".join(verdicts)

    @action("Default zones", description="Sets the zone table for the chosen traffic side")
    def set_default_zones(self, ctx):
        ctx.set_params({"zones": default_zones(ctx.params["traffic"] == RIGHT)})
        return f"zones for {ctx.params['traffic']} traffic"


def _placed(face: dict, origin: np.ndarray) -> dict:
    """A face of the ray tracing ({"surface", "outer", "holes"}, design coordinates) as geometry of
    the document, moved to `origin`."""
    s = face["surface"]
    points = np.asarray(s["points"], dtype=float).reshape(-1, 3) + origin
    surface = dict(s, type="surface", points=[float(c) for c in points.reshape(-1)])
    if not face.get("outer") and not face.get("holes"):
        return surface
    return dict(face, type="trimmed_surface", surface=surface)


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
