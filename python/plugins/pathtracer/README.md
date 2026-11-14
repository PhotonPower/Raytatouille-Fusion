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
   | `glass` | index, absorption, Abbe number | smooth dielectric: Fresnel reflection and refraction, absorption inside (1/mm); the body must be closed and stand in air. With an Abbe number V the index depends on the wavelength: *Index* is n_d (587.56 nm) and n(λ) = A + B/λ² with n_F − n_C = (n_d − 1)/V; 0: constant |
   | `detector` | – | no surface for the light – it passes as if the object were not there; only a place to measure the irradiance (a measuring plane in free space). Not visible to the camera, cannot be a source |

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
   W/(m² sr) in the *Image* window (a pinhole camera; *White at percentile* sets the grey scale).
   Point sources themselves are not visible, the light they cast is.

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

## How it works

- **Geometry.** Every face is tessellated in its surface parameters to the *Mesh tolerance*;
  trimming is a mask over (u, v) (512² cells per face; fewer with very many faces), tested at
  every hit. Normals are interpolated over the triangles. Closed bodies are oriented by counting
  crossings, so that their front is the outside.
- **Tracing.** A bounding volume hierarchy (built with the surface area heuristic, large
  triangles set apart) and a traversal that advances all rays of a batch together (NumPy). Expect roughly 10⁵ … 10⁶ rays per second and processor core.
- **Sampling.** The points on sensor faces, the camera's rays and the choice of the source are
  spread evenly (stratified): every texel and every pixel gets the number of samples its size
  asks for instead of a number that scatters.
- **Several cores.** Larger computations are cut into jobs that worker processes render
  (*Processes*; 0: half of the cores, at most 4 – every process needs some hundred MB). The
  jobs do not depend on the number of processes, so the result does not either.
- **Modules** (no CAD in them, usable from scripts): `pt_nurbs` (NURBS evaluation), `pt_mesh`
  (tessellation, masks, areas), `pt_bvh` (intersection), `pt_bsdf` (materials), `pt_scene`
  (sources, sensors), `pt_integrator` (the estimator), `pt_photon` (photon mapping), `pt_parallel` and
  `pt_worker` (several processes), `pt_setup` (model and panel → scene).

## Not yet

Continuous spectra and colours, reflectances that depend on the wavelength, measured materials
and rough glass, glass touching glass,
sources with a measured distribution, a lens
camera with depth of field, the exact NURBS surface at a hit (instead of the triangle), a
compiled intersection kernel, keeping results with the document (until then: *Also write to file*).
