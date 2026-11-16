# Path Tracer plugin

Light transport on the CAD model in Raytatouille Fusion: some objects are **light sources**, the
others get **materials**; the plugin computes the **irradiance as a texture** on the faces and –
with a camera – an **image**. Several methods estimate the same quantities and can be compared:
light tracing, path tracing, bidirectional path tracing and photon mapping. Needs only `numpy` in the plugin
environment.

Lengths are mm (the document's unit), power is W. Radiometric: sources emit at single
wavelengths, the results are sums over them or one per wavelength; no colours.

## Steps

1. **Materials** (table in the panel). Select surfaces or bodies, write a material's name into
   *Material for the selection* and choose *Selection: set material*. Objects without one get the
   *Material of the other objects*.

   | Kind | Uses | Meaning |
   |---|---|---|
   | `absorber` | – | takes everything (a detector that does not reflect) |
   | `diffuse` | reflectance, transmittance | Lambertian reflection; with a transmittance also diffuse transmission (a diffuser sheet) |
   | `mirror` | reflectance | ideal mirror |
   | `glossy` | reflectance, roughness | a lobe around the mirror direction (normalised Phong, exponent 2/roughness² − 2) |
   | `glass` | index, absorption, Abbe number | smooth dielectric: Fresnel reflection and refraction, absorption inside (1/mm); the body must be closed. Glass bodies may touch (a cemented pair: one surface between the two glasses, no air – faces within twice the mesh tolerance count as touching) and lie inside one another (a lens in a liquid). With an Abbe number V the index depends on the wavelength: *Index* is n_d (587.56 nm) and n(λ) = A + B/λ² with n_F − n_C = (n_d − 1)/V; 0: constant |
   | `metal` | reflectance, roughness | a rough metal: microfacets (GGX, width roughness²) that reflect *reflectance* head-on and more at grazing angles – brushed or blasted surfaces, with a highlight that stretches at flat angles (which `glossy` does not show) |
   | `frosted` | index, roughness, absorption, Abbe number | rough glass: the same microfacets on a dielectric, so light is reflected and refracted into lobes instead of single directions – etched or sand-blasted glass, diffusers of glass. Body closed and in air, as for glass |
   | `detector` | – | no surface for the light – it passes as if the object were not there; only a place to measure the irradiance (a measuring plane in free space). Not visible to the camera, cannot be a source |

   *By wavelength* makes a material coloured: the reflectance (for glass: the absorption) at
   wavelengths in nm, e.g. `450:0.05, 550:0.1, 600:0.6, 650:0.8` for a red paint – straight
   lines between the values, the first / last value outside. It replaces the constant value and
   shows where the sources emit several wavelengths.

2. **Sources** (table in the panel: flux in W, half-angle, side). Select surfaces, bodies, curves
   or points, write a source's name into *Source for the selection* and choose *Selection: make
   it a source*.
   - Surfaces emit with constant radiance into a cone around their normal – half-angle 90° is a
     Lambertian emitter, a small angle a beam. All surfaces of one source share its flux by area.
     *Side*: the front is the side of the surface normal; for closed bodies the outside.
   - Points emit evenly into all directions; the points of one source share its flux.
   - Curves emit like a thin glowing wire (a filament, a line of LEDs): most across the wire,
     nothing along it (intensity Φ sin θ / π² at the angle θ to the wire). The curves of one
     source share its flux by length. Like points they are not visible to the camera.
   - One source is on objects of one kind (surfaces, curves or points).
   - *Flux in* W or lm: lumens are turned into watts through the eye's sensitivity V(λ) at the
     source's wavelengths (683 lm/W at 555 nm).
   - *Luminaire file*: the path of an IES (LM-63, type C) or EULUMDAT (.ldt) file. Surfaces and
     points then emit with its measured distribution instead of the cone: θ from the surface
     normal (the file's "straight down"; *Side* back: from the other side), for points from
     *Axis*; the C0 plane holds the world's X axis (Y if the axis is along X). A surface sends
     the distribution from each of its points. Only the shape of the file is used – the flux
     stays the table's.
   - A source also has its material (it reflects light like any other object).
   - *Wavelengths*: the lines a source emits, in nm, each with an optional share of its flux –
     `550`, `486.1, 587.6, 656.3` or `450:1, 550:2, 650:1`. Every path carries one wavelength;
     it matters where glass disperses. *Also per wavelength* adds a texture / an image for each
     wavelength to the sum.

   *Show materials and sources* lists the objects; *Show light paths* draws some paths from the
   sources (colour: number of the bounce) – a check of where and into which direction they emit.

3. **Irradiance.** *Irradiance on* (use the selection; empty: every surface), *Texels (longer
   side)*, then *Irradiance*: every face gets a texture with the irradiance in W/m² – the light
   arriving from both sides –, and the *Table* window lists area, flux, mean and maximum per face.
   To measure without disturbing the light, draw a surface where you want to know the
   irradiance and give it the material `detector`.
   Texels in which a trimmed face has hardly any area stay empty.

4. **Camera.** Position, *Looks at* (both with *Pick*), up direction, horizontal field of view and
   pixels; *Show camera* draws the viewing pyramid. *Camera image* shows the radiance in
   W/(m² sr) in the *Image* window (*White at percentile* sets the grey scale). With *Lens
   radius* 0 the camera is a pinhole and everything is sharp; with a radius it has a lens that
   is sharp at the *Focus distance* (0: the distance of *Looks at*) and blurs what is nearer or
   farther. A pinhole does not see point sources themselves, only the light they cast; a lens
   images them (light tracing or bidirectional).

**Light as the eye sees it.** *Results in* photometric: every wavelength is weighted with V(λ) –
the textures show the illuminance in lx, the camera the luminance in cd/m², the table lumens.
The log always names the sources' flux in W and in lm.

**How good is it?** The table of *Irradiance* shows the noise of each face's flux, and the log
the noise of a typical texel or pixel: the standard error in percent, estimated from the spread
of the batches the result is the mean of. Four times the samples halve it. (Photon mapping
also blurs; the noise does not show that.)

**Numbers for other programs.** With a file in *Also write to file*, *Irradiance* and *Camera
image* also write `<file>-irradiance.npz` / `<file>-camera.npz` (NumPy archives): the values, their
standard errors, the parts per wavelength and a JSON text `info` with the run and the faces –
`numpy.load(file)["E_<object id>_<face>"]` is the texture of a face in W/m².

*Cancel* stops a computation after the current batch and shows what it has so far.
`sim.inactive` objects take no part.

## Methods

A light path runs from a source over any number of surfaces to the sensor (a texel of a face, or
the camera). *Longest path* limits its segments (1: direct light only).

| Method | How | Good for | Weak at |
|---|---|---|---|
| **light tracing** | particles start at the sources and are followed; they leave their flux in the texels they land in, and every point they reach is connected to the camera | irradiance maps, light through lenses and off mirrors (caustics) | camera images of mirrors and glass (they stay black: a pinhole is never hit by chance) |
| **path tracing** | paths start at the sensor (points on the faces, or the camera's pixels); every point is connected to a point on a source, and paths that hit a source count too | camera images, large diffuse sources | small or narrow sources behind mirrors or glass; point sources seen through them are not found at all |
| **bidirectional** | both kinds of paths, every point of one connected to every point of the other; each way of making a path is weighted by how well it samples that path (multiple importance sampling) | scenes where neither of the others is good everywhere | costs most per sample |
| **photon mapping** | camera images only: light paths leave their flux ("photons") on the surfaces; camera paths are followed through mirrors and glass to the first other surface, and the light there is estimated from the photons within a radius that shrinks from pass to pass | light through glass or off mirrors that is also *seen* through glass or in a mirror – paths no connection can make (the caustic at the bottom of a glass) | blurs over the radius (a small error that vanishes with the passes); for the irradiance on faces it is the same as light tracing |


*Photon radius* is the first search radius (0: chosen so that about 30 photons lie around a
point); the log shows the last one.

The first three agree within their noise wherever a method can produce every path (tests:
`tests/python/test_pathtracer.py`, with closed-form cases – point source over a plane, a closed
diffuse box, a glass plate).

## Two kernels

The computations exist twice, with the same model and the same methods:

- **NumPy** – the modules `pt_*.py` of this plugin; nothing to install besides `numpy`.
- **C++** – the package `pathtracer` ([PhotonPower/PathTracer](https://github.com/PhotonPower/PathTracer),
  MIT): one path at a time on all processor cores, some ten times faster and more. The plugin
  uses it when it is installed in the plugin's Python –
  `pip install git+https://github.com/PhotonPower/PathTracer` (needs a C++20 compiler and CMake) –;
  *Kernel* in the panel chooses (automatic: C++ if installed). The log names the kernel of every
  computation.

Both are built from the same description of the model (`pt_setup.describe`) and are tested
against the same closed forms and against each other (`tests/python/test_pathtracer_native.py`).
Their random numbers differ, so two results agree within their noise, not digit for digit. With
the C++ kernel *Processes* are threads (0: all cores).

## How it works

- **Geometry.** Every face is tessellated in its surface parameters to the *Mesh tolerance*;
  trimming is a mask over (u, v) (512² cells per face; fewer with very many faces), tested at
  every hit. Where a ray hits a curved face, the point where it meets the surface itself is
  found from the triangle's hit (Newton's method), and the normal is the surface's there
  (*Exact normals on curved faces*): mirrors and lenses send the light on exactly, however
  coarse the triangles. The path's vertex stays on the triangle – within the mesh tolerance of
  the surface. Closed bodies are oriented by counting
  crossings, so that their front is the outside.
- **Tracing.** A bounding volume hierarchy (built with the surface area heuristic, large
  triangles set apart) and a traversal that advances all rays of a batch together (NumPy). Expect roughly 10⁵ … 10⁶ rays per second and processor core.
- **Sampling.** The points on sensor faces, the camera's rays and the choice of the source are
  spread evenly (stratified): every texel and every pixel gets the number of samples its size
  asks for instead of a number that scatters.
- **Adaptive sampling** (on by default; path tracing, bidirectional, photon mapping). After
  every batch the samples move to the texels / pixels whose values are still uncertain: a texel
  or pixel is picked in proportion to its standard error so far, 30 % of the samples stay evenly
  spread. Every batch is drawn with shares fixed before it, so the result stays right – only
  its noise is spread differently: less where it was large, a little more in the dark. With
  several processes the first four jobs find the shares for all others.
- **Several cores.** Larger computations are cut into jobs that worker processes render
  (*Processes*; 0: half of the cores, at most 4 – every process needs some hundred MB). The
  jobs do not depend on the number of processes, so the result does not either.
- **Modules** (no CAD in them, usable from scripts): `pt_nurbs` (NURBS evaluation), `pt_mesh`
  (tessellation, masks, areas), `pt_bvh` (intersection), `pt_bsdf` (materials), `pt_scene`
  (sources, sensors), `pt_integrator` (the estimator; `escapes`: the light that leaves the scene –
  direction, flux, bounces, first surface past `skip` – for far fields), `pt_photon` (photon mapping), `pt_photometry` (luminaire files,
  V(λ)), `pt_native` (the C++ kernel behind the same interface), `pt_parallel` and
  `pt_worker` (several processes), `pt_setup` (model and panel → scene).

## Not yet

Continuous spectra and colours, measured materials, sources and cameras inside glass, a compiled
intersection kernel, keeping results with the document (until then: *Also write to file*).
