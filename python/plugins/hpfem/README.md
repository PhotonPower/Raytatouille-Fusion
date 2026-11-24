# hp-FEM plugin

Grating computations with [hp-FEM](https://github.com/PhotonPower/hp-FEM) (adaptive hp finite
elements for nano-optics) in Raytatouille Fusion. Needs the Python package `hpfem` (≥ 0.5) in the
plugin environment: `pip install hpfem` (wheels for Linux x86_64, Windows x86_64 and macOS arm64
from macOS 15; elsewhere a source build).

**Step 1: grating jobs in the panel.**

The panel holds a job of hp-FEM's job runner (`python -m hpfem.run`, schema version 1, task
*scattering*); the default is the runner's example, a dielectric bar on SiO2.

- **Structure:** length unit (nm, µm, mm, m – every length and the wavelength), period (x), cell
  bottom and top (y is the stack normal, light comes from +y; the PML lies inside the cell),
  background tag, slabs over the full period and shapes (rectangle, trapezoid, ellipse, polygon,
  any other form as JSON); the last shape lies on top.
- **Materials by tag**, the **stack** (incidence medium, substrate, background layers, top
  interface): a library name (`air`, `SiO2`, `Si`, `Au`, … – *Library materials* lists them),
  n + i k (`1.5`, `3.88+0.02i`), the permittivity (`eps=2.25+0.1i`) or JSON.
- **Incidence:** polarisation s (E_z at φ = 0) or p, wavelength and θ as a number, a list
  (`400, 410`) or a range `start:stop:count` – a list or range is a sweep (of the wavelength or of
  θ, not both), φ (≠ 0: conical incidence).
- **Mesh:** *structured* (columns × row bands, without Gmsh; put the interfaces and shape edges
  on the lines), *gmsh* (element sizes from the wavelength; needs the `gmsh` package) or a
  periodic `.msh` *file*.
- **Solver:** polynomial order p, PML thicknesses (0 for both: hp-FEM's recommendation), bottom
  (pml, pec, modal), orders up to |m|, diagnostics.
- **Advanced:** every other key of the job file (field maps, `model.x0`, solver tolerances, …)
  is kept and merged back.

Actions:

- **Load job / Save job:** hp-FEM's JSON job; loading and saving again gives the same file, and
  a saved job runs with `python -m hpfem.run job.json --out DIR`.
- **Check:** builds the mesh and estimates the memory of one factorisation without solving
  (warning above 70 % of the RAM); tags without material and the like are named in the log.
- **Solve:** runs the job with progress per phase; *Cancel* stops between the phases of a solve.
  One point: the efficiency of every propagating order (*Table*, bars in *Plot*), ΣR, ΣT, A and
  the power balance. A sweep: ΣR, ΣT, A and every order that reaches *Orders from efficiency*
  as curves over λ or θ, and a table of the points. hp-FEM's diagnostics (PML, elements per
  wavelength, …) with their hints go to the log; `results.json` (and the maps of *Advanced*) to
  the folder of *Results in folder of* or a temporary one.

**Step 2: field maps.**

- **Field map:** computes one point of the sweep (*Point of the sweep*) and shows the total – or
  with *Scattered field only* the scattered – field on a grid in the *Image* window: E (incident
  wave of amplitude 1 V/m), H in A/m or the Poynting vector S in W/m²; *Show* |F|², |F_x|, |F_y|,
  |F_z| or the real or imaginary part of a component (colour scale symmetric about 0; Re S_y < 0
  is power flowing down). The grid: x over *Periods* periods from the cell's left edge (or *x
  from* … *to*; the field is periodic), y over the cell without the PML layers given in
  *Solver* (or *y from* … *to*; points outside the cell stay empty). *Also write .npz*: the
  runner's map (x, y in metres, values (ny, nx, 3)).
- **Show cell:** the cell's tags on the same grid without solving – shapes (the last on top,
  repeated periodically), slabs, background – with the material of every tag in the log.

**Step 3: the grating block in the node workflow.**

With RTT-Fusion (≥ 0.5, stage R35) in the plugin environment the plugin offers the block
`hpfem.grating` to the *Workflow* plugin: a periodic sample in the place of a mirror (the same
sockets, so *Replace block* keeps the links) that sends every requested diffraction order on as a
channel of its own, computed in this plugin's process.

- The block's grating is an hp-FEM job without incidence, sweep and maps – the rays at the block
  set the incidence. **Store job in block** (on the block in the node editor) gives it the
  panel's job; period, polynomial order and the indices of materials given as n or n, k appear
  in its dialog. **Load block job into panel** brings the job back to edit, check or solve
  (the panel keeps its own incidence and sweep). A mesh file stays outside the document.
- Frames: the job's x is the block's *grating vector*, its z the lines, its y the block's
  normal; the job's x = 0 lies at the block's *point*, which is the top of the structure. The
  block's *side* (reflected, transmitted) and *orders* choose what goes on.
- Around the rays of one wavelength the block builds a Jones table: for collimated light (one
  direction) exactly there – one hp-FEM computation (2 solves) per direction –, for a cone of
  directions nodes every *σ step* up to *Most table nodes*. Tables are kept while the plugin runs.
  Fields and spectra reach the block as rays.

**Next step:** the unit cell from CAD bodies.
