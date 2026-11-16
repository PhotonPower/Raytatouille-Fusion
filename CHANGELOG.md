# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com),
versioning: [SemVer](https://semver.org): from 1.0 on, the `.nfcad` format and the plugin API
(`nfcad`, API 1) change compatibly within a major version.

## [Unreleased]

### Added
- **Automotive Lighting plugin**: *Optimise lens* – every cell of a patterned lens gets its own
  deflection and spread so that the low beam meets the R112 test points and zones with a margin
  (H4: the shield makes the cut-off). The cells' light of the plane lens is shifted and smeared
  per element choice (a surrogate of the filament images, within a few per cent), the cells are
  optimised one by one in sweeps, the lens is built and checked in rounds; with the lamp's blur
  measured by ray tracing the limits hold for the lamp as it is too. Zone I of R112 (the
  foreground, at most 2 × I(50R)) is now in the table of the test points.
- **Colour images** in the *Image* window: `ctx.image(…, rgb=)` shows an image in the colours the
  plugin gives it (red, green, blue per pixel), without colour map, colour bar and log scale; the
  value under the cursor stays the number of `values`.
- **Path Tracer plugin**: *Camera image* adds an image in colour when the scene has several
  wavelengths (*Colour image* in the Camera group, on by default) – every wavelength in the colour
  of the CIE 1931 observer, equal power on all wavelengths as white, exposed by *White at
  percentile*. The prism example now shows its rainbow in the application; the example documents
  ask for the colour image instead of one grey image per wavelength, and `make_examples.py`
  writes that image as the picture.
- **Path Tracer plugin**: example documents in `examples/pathtracer` – a Cornell box, caustics of
  glass and polished metal, a prism that fans white light into its colours (31 wavelengths) and
  materials with depth of field –, each ready for *Camera image*, with `make_examples.py` that
  writes them and puts the images of the wavelengths together to colour pictures.
- **FourierGrating plugin**: the dialog of a grating or stack block (double-click) shows the
  numbers of its configuration – period, Fourier orders, layer thicknesses, lamella edges,
  refractive indices – once *Store panel configuration in block* stored it.
- **Hide / Unhide** buttons in the View toolbar (also *Edit* menu, H and Shift + H): Hide hides
  the selected objects and deselects them, so a later Delete or Move cannot act on them unseen;
  Unhide shows what Hide and Isolate hid and leaves layers and model-tree check boxes as they are.
- **Automotive Lighting plugin**: *Generate lamp* – the lamp of the ray tracing in the model, to
  look at what is traced: the coil's wire (the traced quarter turns, with their luminance as an
  attribute), the bulb's glass and black top, the H4's shield and other coil as NURBS faces in the
  group *Lamp &lt;lamp&gt;*, each part in a group of its own that can be hidden.
- **FourierGrating plugin**: a grating or stack block holds its configuration in the document –
  *Store panel configuration in block* (right-click on the block) takes over a configuration
  loaded from GUI-FourierGrating, *Load block configuration into panel* brings it back to edit,
  solve or optimise it.
- **Automotive Lighting plugin**, *Light distribution (ray tracing)*: the lamp as it is – the
  coil's cooler ends (the temperature along the wire from its heat balance, each quarter turn
  shining by its temperature), the bulb as a glass body with its black top where R37 puts it, the
  H4's shield as a mirror and its driving-beam coil (R37 sheet H4/3) in its place; *H4: lit coil →
  driving beam* gives the same reflector's high beam with the driving-beam points of UN/ECE R112.
- **Path Tracer plugin**: `escapes(..., skip=...)` in both kernels (package `pathtracer` 0.3.0) –
  the first surface past given entities, e.g. what the light of a lamp meets after its bulb.
- **Automotive Lighting plugin**: *Light distribution (ray tracing)* – the coil modelled as a
  helix of tungsten wire (one NURBS face per turn; wire diameter and turns estimated from the
  lamp's power or given), the H4's shield and cap, the mirror's facets and connecting faces or
  the paraboloid, and the lens as a glass body with Fresnel's reflection and refraction, traced
  by the Path Tracer plugin's kernel (C++ if installed) from the wire through every reflection
  until the light leaves; the same image, test points and cuts as *Light distribution*, with the
  flux split into beam, direct, backwards, housing and absorbed, and the noise. The filament
  images and the design keep the cylinder.
- **Path Tracer plugin**: `escapes` in both kernels (`pt_integrator`, `pt_native`; package
  `pathtracer` 0.2.0) – the light that leaves the scene: per light path its direction, flux,
  number of surface events and its first and last surface; the base of far-field results such
  as luminous intensities.
- **Automotive Lighting plugin**: the facetted reflector of a clear-lens headlamp. For a
  filament lamp (H1, H4, H7, H8, H9, H11, HB3, HB4 or own data), the cut-off line and the frame
  of the mirror, the reflector is cut into zones and strips whose filament images all touch the
  cut-off – each strip a family of characteristic strips of that condition (an ordinary
  differential equation). *Generate reflector* adds the facets as trimmed NURBS faces; *Filament
  images* and *Light distribution* show the images on the screen, the luminous intensity, the test
  points of UN/ECE R112 and the sharpness of the cut-off; *Show strips* draws the strips.
  **Connecting faces** (step 2): walls with a draft angle, rounded at foot and head, join the
  facets to one mirror surface that can be injection-moulded; their stray light is part of the
  light distribution. **Facet length**: strips cut into rows of facets, so the spread of a zone
  holds all over the mirror.
  **Patterned lens** (Streuscheibe): a second system – a paraboloid mirror and a lens whose inner
  side is a grid of elements (prisms, cylinder lenses, pillows) that turn and spread the light –
  with the ray trace through the lens. **Signal lamps**: the standard light distribution of
  UN R148 (position, stop, direction indicator, daytime running lamps) as test points, and the
  lamps P21W, PY21W, R10W, R5W. The lens may lean back, run back to one side and be domed;
  the walls between its elements are faces of their own and mirror the light that meets them
  (stray light), or with a draft angle lean, are rounded and refract it.
  The facetted reflector also takes lamps with the filament across the axis (H3: fog lamps);
  its light distribution leaves out the rays that a step of the mirror shades and follows those
  it stops after the reflection through a second one. The H4 brings its shield as UN/ECE R37
  draws it (sheets H4/1 to H4/5): a trough under the coil, closed at the back and open in front,
  its edges where the sheet puts them relative to the coil, and the black cap on the bulb's tip.
  *Direct light of the lamp*: what leaves the coil forwards past the mirror (and through the
  patterned lens) is part of the light distribution.
  ([python/plugins/automotive_lighting](python/plugins/automotive_lighting/README.md))
- **Layer stacks** in the node workflow: the FourierGrating plugin provides `fg.stack` (coatings,
  filters, mirror layers between two media, exact per ray), with an RTT-Fusion that has it.
- **FourierGrating plugin** (ADR 0010, W4, step 1): a grating's structure, materials, layers and
  incidence in the plugin panel; load and save FourierGrating configurations; *Solve* shows the
  efficiency of every order as a table and as bars; *Scan* shows the efficiency per order over λ,
  an angle, the polarisation or a sweep as curves and can write all values as CSV; *Near field*
  shows the field in the grating (|E|², |H|², power flow, components, material) as images; the
  plugin provides the grating block `fg.grating` of the node workflow, computed in its process;
  *Optimise* finds layer depths, breakpoints or periods for an objective Σ weight · efficiency with
  FourierGrating's exact gradients (live curve, the optimum applied to the panel); *Set Littrow
  angle*; the order table as CSV and the near field as `.npz`; *Layer from CAD bodies* turns
  drawn bodies into a grating layer (FourierGrating's STEP slicer) and *Check CAD layers* shows its
  bands and findings. Plugins can write entities as STEP (`ctx.export_step`). *Estimate* gives
  the size and rough memory of a computation; *Scan* and *Optimise* warn when it nears the RAM.
- Plugins: structured parameters (lists, tables, JSON), result tables and bar charts,
  `ctx.set_params` (ADR 0010, W4a).
- **Path Tracer plugin**: light transport on the CAD model – surfaces, bodies and points as light
  sources (flux, emission cone, side), materials on the others (absorber, diffuse with
  transmission, mirror, glossy, glass with absorption); *Irradiance* as a texture on the faces
  (W/m²) with a table per face, *Camera image* (radiance of a pinhole camera) in the Image window;
  light tracing, path tracing and bidirectional path tracing as one estimator with multiple
  importance sampling; *Show light paths* and *Show camera* as previews. NumPy only.
  Material `detector`: a face the light passes unchanged, only to measure the irradiance there.
  Method *photon mapping* for camera images: also finds light through glass or off mirrors that
  is seen through glass or in a mirror.
  Wavelengths: sources emit lines with shares of their flux, glass disperses by its Abbe number,
  results as the sum or per wavelength.
  Curves as sources: thin glowing wires (filaments, lines of LEDs).
  The noise of the results (standard error from the spread of the batches) in the table and
  the log; *Also write to file* saves the numbers as NumPy archives.
  Larger computations use several processor cores (*Processes*).
  Samples are spread evenly over texels, pixels and sources (less noise for the same samples).
  *Adaptive sampling*: samples move to the texels / pixels that are still uncertain.
  Coloured materials: reflectance (glass: absorption) by wavelength.
  Exact normals where rays hit curved faces (the NURBS surface itself, not the triangle).
  Luminaire files (IES, EULUMDAT) as the distribution of surface and point sources; flux in
  lumens; results in lx and cd/m² (weighted with V(λ)).
  Materials `metal` (rough metal) and `frosted` (rough glass): GGX microfacets.
  Camera with a lens: sharp at a focus distance, blurred elsewhere.
  Glass bodies that touch (cemented surfaces) or lie inside one another (immersion).
  *Kernel*: the computations also exist in C++ (package `pathtracer`, all processor cores);
  the plugin uses it when it is installed.
- **Camera image** (Raytracer): the irradiance on the last surface of each path from many rays
  (default 200 000 per field and wavelength, millions possible), square pixels over the
  sensor, shown in the new **Image** window and optionally on the surface in 3D. The quick
  irradiance of *Trace rays* is now optional (off).
- Documents are saved as **`.rttf`** (Raytatouille Fusion file); `.nfcad` files from before
  1.0 still open (same content), *Save As* offers them as `.rttf`. Windows associates both.
- Raytracer: the number of rays is set directly (*Rays (drawn)*, *Rays (quick irradiance)*,
  per field and wavelength) instead of pupil rings.
- *Plugins → Uninstall plugin* lists every plugin; those from a plugin folder are shown greyed
  out with the folder they come from.
- **Image** window and result type: 2D images with physical axes, colour bar, linear / log
  scale, read-out under the cursor, zoom and pan; plugin API `ctx.image`.

### Changed
- Raytracer plugin: the irradiance comes from Raytatouille (`rt.analysis.irradiance_map`, #379)
  on the last surface of the path – incident weight per projected cell area, uncounted rays
  in the plugin log – instead of the plugin's own binning; it needs a Raytatouille with #379.

### Added
- Plugin parameter type `Param.files` (a list of files with *Add…* / *Remove*); the Raytracer's
  *Glass catalogues* use it – catalogues are chosen with the file dialog instead of typing
  `;`-separated paths (documents with the old text are still read).

### Fixed
- **Node editor**: a block of another kind that replaces a Raytatouille block (*Replace with*)
  keeps its element and traversals, keyed by the new ports, so the Raytracer still draws it.
- **Workflow: a document computes on its own.** A grating (`fg.grating`) or layer stack
  (`fg.stack`) that named its FourierGrating configuration or Jones table by path failed on any
  other machine – every display behind it gave up and the status line only said *nothing
  computed*. *Check workflow* (and *Run workflow*) now store such files in the blocks and clear the
  paths (RTT-Fusion W75), so the `.rttf` carries them; a file that cannot be read is a warning at
  the check. A run that computes nothing names the first reason in the status line.
- Crash when hiding results (e.g. the rays of one arm) or a layer with its check box: the panel
  rebuilt its list while Qt was still handling the click. The lists also keep their scroll
  position now.
- Raytracer: loading some systems failed with "Singular matrix" (a rounding error put the
  last interpolation point outside the parameter range); steep, nearly hemispherical lenses
  were drawn up to 0.1 mm off – rotationally symmetric surfaces are now surfaces of revolution
  (all surfaces of the tested objectives and the Linnik within 0.1 µm).
- Raytracer: *Trace rays* traces every path of the system (or the ones listed under *Paths*),
  one line set per path, *Colour by → path*; paths ending on the same surface add up in its
  irradiance.
- Raytracer: *Trace rays* works for folded / tilted paths (beam splitter, Linnik) whose stop is
  the first surface: the plugin builds the start rays itself, identical to Raytatouille's
  `make_rays` where both work.
- Plugin panel in a narrow dock: rows wrap (editor below its label), the file chooser button is
  no longer cut off, an empty file field says what to do.
- Plugin errors the user can fix (`nfcad.UserError`, e.g. no system file chosen, missing glass
  catalogue) are shown as a message instead of a Python traceback in the log.

## [1.0.0] - 2026-11-11

First release: a CAD front end for Nurbforge with four views, object snaps, drawing, solids,
STEP / STL, results on the model – and plugins for computation kernels, starting with the
Raytatouille ray tracer. Packages: Windows 11 installer, AlmaLinux / RHEL 10 RPM, macOS disk
image (universal, unsigned).

### Added
- **Release 1.0 (M8):** macOS build as a universal binary (arm64 + x86_64); local crash
  reports (written on a crash, pointed to at the next start, never sent); versioned settings
  migration; user guide with screenshots and shortcuts (`docs/user-guide.md`); example
  models (`examples/`); a tag `v*` builds the packages and drafts a GitHub release.
- A plugin run that fills an empty document zooms all views to its result.

### Fixed
- Closing the window with an undo history could call into the half-destroyed window (crash in
  debug builds, undefined behaviour in release builds).
- Model tree: names get the column width instead of the type column.

### Added
- **Plugin distribution (P7):** `.nfplugin` packages (zip of the plugin folder with its
  signature; `nfcad-plugin pack`), *Plugins → Install plugin…* / *Uninstall plugin* into the
  folder for installed plugins (also by opening the file); requirements in `plugin.json`
  (`requires`) with *Check environment* and *Create environment…* in the plugin settings;
  manual update check *Help → Check for updates…* (GitHub releases, `update_url` of plugins).
- **Raytracer plugin (P6)**, `python/plugins/raytracer`: loads Raytatouille systems
  (`.rtt.json`) as NURBS faces (bridge rtt → NURBS: interpolated sag within a tolerance,
  exact trims, lens rims, stop ring) in a model tree following the rtt node tree; traces rays
  (line set) and the irradiance on the image surface (face field); optimises with live
  surface updates and a merit curve; saves the system. Undo in CAD follows the system revision.
- Plugin API: `ctx.remove`, `ctx.groups`, `ctx.add_group`, `ctx.remove_group`, `group=` in
  `ctx.add` – all part of the run's single undo step.
- **Plugin signatures (P5):** only plugins signed with the built-in publisher key load
  (Ed25519 via Monocypher; file `SIGNATURE`); they run from a private, checked copy. Developer
  mode loads unsigned plugins, marked, with a red banner. Tool `nfcad-plugin` (keygen, sign,
  verify); test `signed_plugins` checks signed plugins in the repository. ADR 0009.
- **Plugin parameter panel (P4):** plugins describe their parameters with `nfcad.Param`
  (number with unit and limits, integer, boolean, choice, text, file, number list, point,
  model object); CAD builds a form in the new *Plugin* dock with the plugin's action buttons.
  Points are picked in the views with object snaps, objects taken from the selection. The
  values are saved per plugin in the `.nfcad` document and arrive in `ctx.params` as Python
  types.

### Changed
- Renamed to **Raytatouille Fusion** (was *Nurbforge CAD*): window and menu texts, executable
  and bundle (`RaytatouilleFusion`), installer, RPM `raytatouille-fusion` (replaces
  `nurbforge-cad`), desktop entry and bundle id. Settings of the old name are taken over on the
  first start; the Windows installer keeps its AppId (updates the old installation). Unchanged:
  namespace and Python package `nfcad`, format `.nfcad`, `NFCAD_*` variables.
- GitHub repository renamed from `PhotonPower/CAD` to `PhotonPower/Raytatouille-Fusion`
  (GitHub redirects the old URLs).

### Added
- P3 – plugin host (docs/plugin-api.md): plugins in their own Python process
  (`python -m nfcad.host`), TCP channel on 127.0.0.1 with a token, JSON lines, arrays as mapped
  temporary files; Python package `nfcad` (actions, context with progress / log / cancel, model
  access, results API, geometry helpers incl. `nurbforge` conversion); Plugins menu and a
  tool-column group per plugin, settings (Python interpreter, plugin folders), progress bar with
  Cancel, plugin log dock; one undo step per run (`Document::recordApplied`); demo plugin;
  tests with a real Python process (model, results, cancel, errors, crash, foreign connection)
- P2 – result display (docs/plugins.md): `ResultStore` with runs of line sets (rays, coloured
  by a value), face fields / images (textures on faces via the mesh (u, v)) and curves; colour
  maps (viridis, inferno, plasma, coolwarm, grey) with a colour bar per view; Results dock;
  Plot dock with live curves; rays → CAD curves; *Help → Demo results on the selected object*;
  offscreen render test
- P1 – model tree and attributes (docs/plugins.md): groups (nested, undoable group / ungroup),
  visibility of objects and groups (inherited), isolate, show all; Model dock with selection
  in both directions; entity attributes (key / value, undoable, edited in the property panel,
  `sim.inactive`); `.nfcad` version 2 (groups, attributes; version 1 still read); STEP files
  import as one group; (u, v) texture coordinates in the display meshes
- M7 – Windows 11 and AlmaLinux / RHEL 10: CI jobs required; `Packages` workflow with Inno
  Setup installer (`.nfcad` association), RPM (desktop entry, icon, AppStream metadata) and
  unsigned macOS DMG; install component `app` with Qt deployment (windeployqt / macdeployqt);
  `NFCAD_RHI_BACKEND` override; THIRD_PARTY_NOTICES.md
- M6c – editing and analysis: Join (curve chains in any order, faces into shells), Explode,
  Cap planar holes (`kernel::cap_planar_holes`), Split, Trim, Intersect, Area, Volume,
  Curvature; tests incl. exact volumes of a joined box and a capped extrusion
- M6b – surfaces from curves: Spline, Offset curve, Fillet curves (two curves or all corners),
  Plane, Extrude, Revolve, Loft, Sweep 1 / 2 rails, Coons, Gordon (network sorted
  automatically), Offset surface, Fillet surfaces; tests against exact areas
- M6a – solids, transforms, export: commands Box, Sphere, Cylinder, Cone, Torus, Union,
  Difference, Intersection, Move, Copy, Rotate, Scale, Mirror, Linear / Grid / Polar array,
  Angle; selection-based commands (selection order kept for Difference); `Document::apply`
  (add / remove / replace as one undo step); File → Export STEP / STL; tests with exact volumes
- M5 – drawing commands: command framework (`Command`, `CommandController`), Point, Line,
  Polyline, Rectangle, Polygon, Circle, Circle (3 points), Arc, Helix, Distance; typed command
  names and aliases, coordinates (`x,y,z`, `x,y` in the construction plane, `@` relative,
  `d<a` polar), numbers and lengths; orange rubber-band preview; ortho (F8); Enter /
  right-click finish or repeat, Esc cancels; one undo step per result; typing in a view goes to
  the command line; docs/commands.md; tests for parser, commands and controller
- M4 – object snaps: `SnapEngine` with Point, End, Mid, Centre, Quadrant (cut points of the
  coordinate planes), Near, Intersection (real and apparent), Face corner, Face edge and Grid;
  exact refinement with Nurbforge (circle detection, arc length, closest point, curve/curve
  intersection); magnetic cursor with glyphs and labels, Tab cycles candidates, Alt suppresses,
  F3 and status bar toggles; tools Point and Distance; tests for every snap type against exact
  values, 0.34 ms per query with 10 000 curves

### Changed
- Snap priority: Face corner ranks right after End (corners are the ends of B-rep edges)
- M3 – picking and selection: CPU picking with BVHs over the display meshes (ADR 0007);
  click / Shift / Cmd-Ctrl selection, Cmd/Ctrl+Shift for faces, edges and vertices, window
  (left → right) and crossing (right → left) selection with rubber band; hover highlight (cyan)
  and selection highlight (yellow, face overlays); property panel (type, degrees, knots,
  length, area, volume); layer panel (visibility, colour, rename, new layer, move selection);
  Edit menu Delete / Select All / Select None; tests for picking, selection, layer assignment,
  properties and viewport selection
- M2 – document model and display: `Document` with entities (point, curve, surface, trimmed
  surface, shell), layers, undo/redo; STEP import (Nurbforge reader, in the background); native
  format `.nfcad` (JSON, docs/file-format.md); adaptive display tessellation in worker threads
  (CDT for trimmed faces, ADR 0006); shared `Scene` and per-view `SceneRenderer` with the display
  modes wireframe (edges + iso-curves), surfaces (flat) and shaded (Blinn–Phong, two headlights);
  MSAA; zoom extents fits the model (tight box fit in parallel views); File menu (New, Open,
  Import STEP, Save, Save As), Edit menu (Undo, Redo); command line options `file`,
  `--display-mode`, `--benchmark`; `tools/make_demo_model`; tests for tessellation, document,
  file format and STEP import
- M1 – viewports and camera: `Camera` (orthographic / perspective with the same scale,
  project / pick ray, pan, zoom to cursor, turntable orbit, zoom extents), standard views
  Front / Left / Top / Perspective, adaptive grid in the construction plane with world-coloured
  axes, axis triad, view menu on the view title, cursor coordinates in the status bar,
  trackpad pan / pinch zoom on macOS, line pipeline (`render/line_renderer`, shaders via
  `qt_add_shaders`), tests for camera, grid and viewport input
- Project structure, documentation (plan, UI concept, object snaps, rendering, architecture,
  ADRs 0001–0005, build guides for macOS, Windows 11 and AlmaLinux / RHEL 10)
- CMake build with Qt 6 and Nurbforge (installed package, local checkout or download)
- Main window skeleton: tool column with collapsible groups, 2×2 viewports (`QRhiWidget`),
  display-mode buttons, snap bar
- CI: macOS (required), Windows 11 and AlmaLinux 10 (prepared)

### Fixed
- Qt 6.8: `Qt6::GuiPrivate` comes with `Gui`; the separate package is only searched from Qt 6.9 on
