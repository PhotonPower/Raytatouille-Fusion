# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com),
versioning: [SemVer](https://semver.org): from 1.0 on, the `.nfcad` format and the plugin API
(`nfcad`, API 1) change compatibly within a major version.

## [Unreleased]

### Added
- **Plane-wave spectra (S) on workflow links** (RTT-Fusion R30e). The transport menu of a link or
  connection names each representation (*auto – the planner chooses*, *R – rays*, *H – fields*,
  *S – plane-wave spectra*, *G*, *T*, *P*), ticks the current one and disables those the
  installation cannot compute, with the reason in the tooltip (the document's new `available`,
  e.g. `["H", "R", "S"]` with fieldtracing; *Check workflow* writes it). After a run a link shows
  what it actually carried: on an *auto* link planned R a spectrum (e.g. from `fusion.convert` to a
  camera) reads **R→S**, as fields near a focus read R→H; the tooltip names the conversions on the
  way (*last run: S (R→H→S) – lens gave rays; spectra on the link; Camera takes them as they are*),
  also on a fixed link. The warnings of the spectrum conversions (`exec.spectrum_cut`,
  `exec.spectrum_rays`) mark the link (⚠, the lines in the tooltip) or the block, and the status
  line names the first one; `exec.spectrum_support` (a spectrum without sampling cannot become a
  field or rays) marks its link as well. The conversions on the way need RTT-Fusion with
  `Context.used` per link (R30e); with an older one the links show the plan as before. The
  Raytracer's check of a socket graph plans with RTT-Fusion's `workflow.checked` (S available, what
  the blocks take natively). Manual: chapter *Node-Workflow* (representations, when S is used, the
  transport menu, the new messages) and the block appendix (sockets RHS, `fusion.convert` to S).
- **Overview of every workflow block.** The parameter dialog of a block in the node editor opens on
  a new first tab *Overview*: a drawing of the block's sub-model with the values in the dialog
  (also those not applied yet), redrawn a moment after a value changes and with *Update*. The
  Raytracer draws `rtt.*` blocks in the meridional section – lenses as the closed outlines of their
  glass segments from the exact sag profiles, coloured by glass with the index in the legend,
  cemented groups, stops, mirrors, ideal lenses, detectors, the axis and a fan of real rays along
  the block's run; the source the whole system. The FourierGrating plugin draws a grating's or
  stack's cross-section over two periods with layer thicknesses, profiles (lamellar, sinus,
  triangle, points, 2D layers cut), materials and the incidence; the workflow engine the ideal
  optics (`optics.*`) and the particle. Every other block shows its schematic (ports, sockets,
  parameters). Context menu: copy or save the image. Plugin API: `Plugin.preview_block(request)`
  returns a dependency-free 2-D vector drawing (`nfcad.drawing`, format `nfcad-drawing` 1:
  polygons with materials, polylines, texts, dimensions, arrows; CAD draws it scaled, dark-palette
  aware, with a legend); `plugin.json` may list further types under `"previews"`
  (docs/plugin-api.md, "Block previews"). A future kernel (e.g. FEM) draws its mesh's section the
  same way.
- **Saving results.** *Results* dock: *Save run…* (a folder named after the run, one file per
  result) and *Save…* for one result, also as a button under the tree; *Image* window: *Save…* →
  *Image as PNG…* (one pixel per value, colour map and log scale as shown), *View with axes as
  PNG…*, *Values as CSV…*. Images and fields as PNG and CSV (a grid, `numpy.loadtxt` reads it),
  curves, tables, bars and rays as CSV (docs/plugins.md, "Saving results").
- **Result drawings are objects in the views.** The rays of a run (Raytracer *Trace rays*) and the
  Path Tracer's camera are one clickable element each: hovered and selected like an object
  (Shift / Cmd–Ctrl add and remove), *Move* and *Rotate* move them (alone or with objects, one
  undo step; a display transform – the rays are not traced again, CSV export and *Convert to CAD
  curves* use the shown place), *Delete* removes them (undoable). Copy, Scale, Mirror and the
  arrays stay for objects.
- **Path Tracer: move and rotate the camera in the views.** Moving or rotating the drawn viewing
  pyramid writes *Position*, *Looks at*, *Up* and the new *Roll* (`camera_roll`: turn about the
  view direction, degrees) into the panel, in the same undo step; *Up* is the axis needing the
  least turn, *Roll* the rest, so every rotation is kept exactly.
- **Plugin API: `ctx.lines(..., key=..., binding=...)`** – a keyed drawing replaces the earlier
  line items with that key; a binding names point parameters and a camera orientation that
  moving the drawing writes back (docs/plugin-api.md, "Drawings bound to parameters").
- **User manual (German, LaTeX and PDF)**: `docs/manual/handbuch.pdf`, about 390 pages – installation,
  main window, navigation, modelling with every command, layers and groups, files, plugins, the
  node workflow, the Raytracer, Path Tracer, FourierGrating and Automotive Lighting plugins; appendices
  with all keyboard shortcuts, every command of the command line, the programs' command-line options
  and environment variables, a parameter reference per plugin, every workflow block, plugin
  management, the file format, troubleshooting and a glossary. Source in `docs/manual/` (`make`).
- **Layers: current layer, lock, delete.** The current layer (bold in the *Layers* dock, *Make
  current*) receives new objects – drawn, imported with *Import STEP…*, made by plugins – and is
  saved with the document. A locked layer's objects stay visible and can be snapped to, but cannot
  be selected and so not changed. *Delete layer…* asks whether the objects move to *Default* or are
  deleted; *Default* stays. File format: optional `"locked"` per layer and `"current_layer"`
  (docs/file-format.md), compatible both ways.
- **File → Open Recent** with the last ten documents and *Clear list*.
- **Opening files from the Finder (macOS) and the file manager (Linux).** The application's
  `Info.plist` declares `.rttf` / `.nfcad` (documents), `.step` / `.stp` and `.nfplugin`, and a
  double-clicked file arrives as `QFileOpenEvent`; Linux installs the MIME types
  `application/x-raytatouille-fusion` and `application/x-raytatouille-fusion-plugin`
  (shared-mime-info) and the desktop file names them. As with the command-line argument, a
  `.nfplugin` is installed, a document or STEP file opened after asking to save the changes.
- **File → Open… shows plugin packages (`.nfplugin`)**, which it installs; choosing one no longer
  asks to save the document first.
- **The plugins ship with the application** (Windows installer, macOS DMG, RPM): Raytracer,
  Workflow, FourierGrating, Path Tracer and Automotive Lighting are installed with it and load
  without a signature, as part of the installation (ADR 0009, addendum). A plugin folder of one's
  own with the same plugin id replaces the installed plugin.
- **Create environment… installs everything the plugins need**: numpy and the kernel packages
  from PyPI (raytatouille, rtt-fusion, photonpower-fieldtracing, fouriergrating, pathtracer – wheels
  for Windows, Linux and macOS), not only numpy. `plugin.json` `requires` can name the pip
  distribution when it differs from the import name: `"fieldtracing>=0.2 (photonpower-fieldtracing)"`.
  On Windows, the Python on the PATH skips the Microsoft Store stubs and also finds the launcher `py`.
- **Results are saved in the `.rttf` file.** The newest result of every display window of the
  node workflow (camera images, pupil images, curves of sweeps, tables, bars) is written with
  the document and shown again after opening. Each result carries a fingerprint of what it was
  computed from. If the workflow and its settings are unchanged, the display counts as up to
  date (green tick), and *Run workflow* does not compute it again ("(unchanged)" in the status
  line). Change something and it is computed anew. The intermediate results (ray bundles, fields)
  are not saved. A run with new results marks the document as modified. Plugin API: `stamp=` for
  `ctx.image`/`curve`/`table`/`bars` and `ctx.result_stamps()`. File format: optional section
  `results` (docs/file-format.md).
- **Glass catalogues in one place: the Raytracer panel.** The workflow takes the catalogues listed
  there (and *.agf next to the system file) and stores them in the document at the next Check or
  Run. The `.rttf` file then computes without the .agf files, also in the Raytracer panel, which
  uses the stored catalogues when a file is missing. A catalogue that cannot be read no longer
  stops *Run workflow* with a traceback. The log and the status line name the catalogue, the
  glasses that are missing, and the fix (RTT-Fusion #87, #89). Plugin API:
  `ctx.plugin_params(plugin_id)` reads another plugin's panel values.
- **Automotive Lighting plugin**: *Optimise lens* fits a **target beam** and **searches the
  sectors**. *Optimise: target beam* (a weight, 0.3; 0: none): besides R112's points the whole
  field is fitted to the shape of a classic lens' beam made from the plane lens' own light – each
  row under the cut-off spread across anew (a core to the driver's side, a wide part, both wider
  further down), the rows lifted to follow the rise up to 1°, nothing above the line; the rounds
  log how far the beam is off it. The wedge found is no longer taken as it is: its two radial
  lines are moved (± 6, ± 12°) one after the other and the lowest objective kept (the parts near
  the lines optimised again for each; the log lists them), and the wedge's cylinders may turn by
  10 … 20° instead of exactly 15°. For the H4 a wider, more even beam whose rise is lit along its
  line out to 8° (under the rise 4 800 instead of 3 300 cd, the 2000 cd line at H = 8° at 0.55°
  instead of −1.65°), a sharper cut-off, R112 met in the ray tracing; the hot spot lower (15 700
  instead of 19 000 cd). A bin of the screen is probed once, whichever requirement judges it.
- **Automotive Lighting plugin**: lens **sectors** – radial sections about the lamp axis, as the
  zones of a clear-lens reflector (a new table: azimuth and cut-off branch). They cut the cells along
  radial lines, each part an element of its own (a new *sector* column of the element table), the
  step between two parts a wall along the line (exact, degree 10). *Optimise lens* cuts out the
  wedge whose light ends at the rising branch – where a classic H4 lens has its slanted flutes –
  and the elements there follow the rise: for the H4 a brighter rise that follows its line further,
  R112 met in the ray tracing.
- **Node editor: a link on auto shows what the last run used**, e.g. **R→H** at the link into the
  pupil camera when it switched to fields near a focus; the tooltip says why (RTT-Fusion #85). The
  label stays while the camera's result is up to date and goes back to the planned representation
  once the result is out of date.
- **Automotive Lighting plugin**: *Optimise lens* makes a real beam's cut-off. *Optimise: along
  the edges* – every element spreads and deflects along the edge of its own light, as the flutes of
  a classic lens (cylinders turned by 15° in the wedge in front of the shield's slanting edge);
  *Optimise: under the cut-off* and *under the rise* – the beam brightest just under both branches
  and the rise lit and sharp, weighted below R112's limits; and the lens is ray traced (20 million
  paths at least) and optimised twice more for what the ray tracing has beyond the blurred view.
  For the H4 the band under the horizontal branch is 2.5 times as bright (6 500 instead of 2 500 cd
  at −10 … −2°) with R112 met in the ray tracing.
- **Workflow panel: *Wave optics near a focus (automatic)*, on by default.** A camera on a link
  left on auto checks whether the rays cross or focus near it and then computes fields from the
  last surface on, as if the link were set to H; elsewhere it keeps rays. A link set to R or H
  keeps its setting. The log says why it switched. With the default ε (0.02) the pupil camera of
  the reflected-light microscope switches by itself and takes about 3 minutes; Debye stands in
  for a Rayleigh–Sommerfeld step that would only cover a few micrometres of the window, with its
  estimated error in the log (RTT-Fusion #84).
- **Automotive Lighting plugin**: *Optimise: start with* – *Optimise lens* starts every cell
  with a cylinder lens spreading 6° across (new default), with plane glass, or from both and keeps
  the better. The search stays near its start: from cylinder lenses about 45 % of the H4's cells keep
  one and the beam is more even (ray tracing: bumps 3.7 instead of 4.2 %, hot spot 20 200 instead of
  23 400 cd, G 0.46 instead of 0.35), with less to spare at 75R (11 000 instead of 12 200 cd).
- **Automotive Lighting plugin**: *Optimise: evenness* – *Optimise lens* also makes the beam even
  below the cut-off: the bumps (second differences over 1° across and 0.3° up and down, in the
  lamp's blur) cost in the objective. For the H4 they halve (9.2 → 4.2 % of 50R's minimum in the
  ray tracing) with R112 still met.

### Changed
- **More undo steps**: new, renamed, recoloured and deleted layers, renamed groups, and every edit
  in the node editor (moving a block counts once, at the release; before, only plugin runs that
  changed the workflow could be undone).
- **Automotive Lighting plugin**: the elements of a patterned lens may be turned (*spread turned
  by*, a new column of the element table): a cylinder lens turned by 15° spreads the light along a
  line that rises by 15°, as the facets of a clear-lens reflector lay their filament images along
  the cut-off. *Optimise lens* chooses per cell a prism and a cylinder lens – its strength and its
  direction – instead of spreads across and up and down.

### Fixed
- **Path Tracer: *Show camera* drew the new camera over the old one.** The drawing now replaces
  the previous one (keyed line result `pathtracer:camera`).
- **Extrude: a typed distance went along +Z in every view.** It now follows the normal of the
  construction plane of the view one works in (Front: −Y, Left: −X), as the prompt says.
- **Right-click with no running command repeats the last command** in the views (like Enter on an
  empty command line), as documented; a right drag still orbits / pans.
- **Tool tooltips named shortcuts that did not exist** (L, C, M). They now say what to type, e.g.
  "Type: l + Enter"; only Delete has a real shortcut.
- **H in a view always meant Hide**, so the Helix alias could not be typed there. With nothing
  selected, H is now typed into the command line; with a selection it still hides.
- **Snaps on polylines, rectangles and polygons**: every corner is an End and every segment has a
  Mid (before: only the ends and the middle of the whole curve). The points of a polyline being
  drawn snap too, so it can be closed by snapping its start point.
- **Error messages say why**: Fillet curves, Offset curve, Revolve, Extrude, Split and Trim show the
  reason ("Fillet: radius 5 too large for these curves", "Split: the point is at an end of the
  curve") instead of only "Input not accepted – <prompt>"; the kernel's function names are not
  shown.
- **Workflow: blocks that cannot be computed are no longer offered.** *Add block* listed planned
  types without an evaluator (`analysis.camera_image`, `biooptomd.layer`, and before RTT-Fusion
  0.2.1 `fusion.convert`); a run with one stopped with `exec.no_evaluator`. The library now holds
  only types this installation can compute (plus those the workflow already uses), and *Check
  workflow* warns on each block without an evaluator (`check.no_evaluator`).
- **Closing did not ask to save after layer and visibility changes.** Creating, renaming,
  recolouring layers, renaming groups and showing or hiding layers, groups and objects (Hide,
  Isolate, Unhide, the check boxes) now mark the document modified.
- **Windows (and Linux under a light system theme): the menu bar and other texts were dark on
  dark.** The dark style sheet coloured only some widgets; the rest took the light system palette.
  The application now uses a dark palette everywhere: Fusion with the colours of `dark.qss` on
  Windows and Linux, the native dark appearance on macOS.
- **Automotive Lighting plugin**: lamp data checked against UN/ECE R37 Rev. 7 – HB3 5.1 mm and
  1860 lm, HB4 1095 lm, P21W/PY21W 6.0 mm; the black top of H7, H8, H11 from γ3 at the coil's end
  nearest the reference plane, of the HB4 from its centre (it reached not far enough back); bulbs
  within R37's outlines (H1 8.5 mm, the tips of P21W, PY21W, R5W, R10W); the H4's shield 4.3 mm in
  radius as on sheet H4/3. The README says where the H4's mirror has its focus (at the
  driving-beam coil, 6.7 mm behind): then its shining shield sends no light above the cut-off.

### Added
- **Workflow panel: *Field accuracy ε (H links)*.** The allowed error of a field propagation,
  relative to the peak amplitude (default 0.02, Fieldtracing's). Fieldtracing takes the cheapest
  method within it; near a focus 0.05 often allows Debye (seconds) instead of Rayleigh–Sommerfeld
  (hours). With RTT-Fusion #83 a pupil camera behind a grating (link H) takes about 3 minutes
  instead of not finishing; the log names the method and its error.
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
- **Workflow: a camera behind a grating computes.** The camera of a path through a FourierGrating
  sample was evaluated in the Raytracer plugin's process, which has no grating – the run stopped
  with *raytracer: … no evaluator for fg.grating*. Such a detector is now computed by the
  workflow engine itself, which reaches both plugins (needs RTT-Fusion #82).
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
