# Raytracer plugin

Raytatouille ([PhotonPower/Raytatouille](https://github.com/PhotonPower/Raytatouille)) inside
Raytatouille Fusion – milestone P6 of the [plugin plan](../../../docs/plugins.md).

## Setup

1. Install Raytatouille (with `rt.analysis.irradiance_map`, i.e. #379 – `main` from 2026-11-11 on)
   into the Python environment of the plugins (*Plugins → Settings…*), e.g.
   the repository's `.venv`:
   ```bash
   MACOSX_DEPLOYMENT_TARGET=26.0 .venv/bin/pip install ../Raytatouille   # macOS; elsewhere without the variable
   ```
2. The plugin is not signed yet: switch on the **developer mode** (*Plugins → Settings…*). In
   a development build it is found automatically (`python/plugins`).

## Use (dock *Plugin*, plugin *Raytracer*)

| Action | What happens |
|---|---|
| **Load system** | reads the `.rtt.json` (*System file*), compiles it with the glass catalogues and draws every surface as a NURBS face – lenses with their rims, the aperture stop as a ring, the image surface sized to the spot. The model tree follows the rtt node tree. Loading again replaces the drawing. |
| **Trace rays** | rays along the paths (*Paths*: names separated by commas, empty = every path of the system; *Field*, *Wavelengths*, *Rays (drawn)* per field and wavelength), one line set per path in *Results* (show / hide each; in a view the rays of a run are one object: click to select, *Move* / *Rotate* move the drawing – a display transform, nothing is traced again – and *Delete* removes them), coloured by wavelength, field or path; with *Quick irradiance* (off by default) a coarse irradiance with few rays on the last surface of each path as a field on its face – paths ending on the same surface add up (incoherently, no interference) (*Quick irradiance grid*, *Rays (quick irradiance)*), computed by Raytatouille (`rt.analysis.irradiance_map`, #379: incident weight per projected cell area). Rays that are not counted (outside the face, vignetted, not reached) are listed in the plugin log. Where a branch of the node workflow passes a block of another kind (a FourierGrating grating or stack, an hp-FEM grating – its Raytatouille path ends in front of it as "*branch* (aim)"), the workflow is computed with rays only (RTT-Fusion `graph.ray_paths`, the actuators applied) and the rays are drawn through every block to the detectors, one line set per branch; *Weakest order drawn* (default 0.01) leaves out bundles weaker than that share of the strongest through the same block. |
| **Camera image** | the irradiance on the last surface of each path computed with many rays (*Rays per field and wavelength*, default 200 000; *Pixels (long side)*, square pixels over the sensor = the surface's aperture), shown as an image in the **Image** window (mm axes, colour bar, *log* scale, zoom with the wheel, pan by dragging, double-click: all) and optionally on the surface in 3D. Paths, fields and wavelengths as for *Trace rays*; paths ending on the same surface add up. |
| **Optimise** | Raytatouille's optimiser on the system's variables and merit function; the changed surfaces are redrawn after every accepted iteration, the merit function grows in the *Plot* dock. Cancel (Esc) ends with the last accepted state. |
| **Save system** | writes the current system (*Save as*, default `<system>.optimised.rtt.json`). |

Glass catalogues: the files added under *Glass catalogues* (*Add…*, several at once), plus all
*.agf files next to the system file and in its sub-folder `catalogs`. Without catalogues only systems with
constant indices compile, such as `examples/singlet_optim.rtt.json`.

**Undo.** Every action is one undo step in CAD. The plugin numbers each state of the optical
system and stores the number in the attribute `rtt.revision` of the first surface; after an
undo of an optimisation the next action continues with the system before it.

**Drawing accuracy.** Rotationally symmetric surfaces (conic, aspheres, axicon, Q-type) with a
circular aperture are drawn as surfaces of revolution: the profile is interpolated along its
arc length, so steep, nearly hemispherical lenses are drawn as exactly as flat ones. Other
shapes, rectangular / elliptical apertures and image surfaces are bicubic B-splines over the
local x-y plane, trimmed with exact curves. The *Drawing tolerance* (default 0.1 µm) is
checked; planes are exact. Rays are always traced on the exact surfaces. The error per
surface is in the attribute `rtt.nurbs_error_mm`; surfaces above the tolerance are named in
the plugin log.

**Folded and tilted paths** (beam splitters, interferometers such as a Linnik): Raytatouille's
ray aiming needs a rotationally symmetric path. For other paths the plugin starts the rays
itself – on the same hexapolar grid over the stop, along the field angles (object at infinity)
or from the object points (finite object). That is exact when the aperture stop is the first
surface of the path (as with an illumination stop); otherwise the plugin says that it cannot
aim into the path.

**Overview of a block** (tab *Overview* of a workflow block's parameter dialog, `rtt_preview.py`):
the block's elements in the meridional section (y–z, mm) with the values in the dialog – every
lens as the closed outline of its glass segments from the exact sag profiles over the apertures
(`raytatouille.layout.outlines`), coloured by glass, the legend with the index at the reference
wavelength; cemented groups one area per glass; mirrors, ideal lenses (arrows, f), splitters
(dashed), detectors and stops (marks beside the opening) as their profiles; the optical axis; a fan
of seven parallel rays along the block's first run (sections, new lenses) when the glasses are
known; the centre thickness or the length dimensioned, a singlet's radii in the notes. The source
draws the whole system. Compiled with the source's glass catalogues; a missing glass draws the
geometry with a constant index and says so.

## Not yet

- Switching elements off for the computation (attribute `sim.inactive`, needs
  [#380](https://github.com/PhotonPower/Raytatouille/issues/380)); the plugin only logs them.
- Editing optical parameters in CAD (radii, thicknesses) and the conversion to
  `raytatouille.nurbs` in the library (D10).
