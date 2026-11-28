# ADR 0011 – Simulated materials: from refractive index and topography to the rendered product

Status: **accepted** 2026-11-28 (by the maintainer: SpeckleBem before hp-FEM, `layer.stack` in the
pathtracer plugin; elliDFT as tables; questions 2 and 3 are decided when their stages start)

**Context.** Customers want to see what a material looks like in the finished product. Several of
our kernels can each answer part of that question, but nothing yet links them:

| Kernel | What it can compute | Repository |
|---|---|---|
| **elliDFT** | n(λ), k(λ) of polymers (Kohn–Sham DFT of oligomers, ellipsometry) | PhotonPower/elliDFT |
| **SpeckleBem** | rigorous, polarised scattering from rough surfaces (surface integral equations, RWG, MLFMM): far fields, DRC, speckle statistics of a finite rough patch under a Gaussian beam | PhotonPower/SpeckleBem |
| **hp-FEM** | rigorous fields with anisotropic materials: e.g. birefringent particles embedded in a coating | PhotonPower/hp-FEM (plugin `hpfem`) |
| **Raytatouille** | the luminaire: optical design, ray sets, detectors | plugin `raytracer` |
| **PathTracer** | light transport on the CAD model (light / path / bidirectional tracing, photon mapping), spectral, two kernels (NumPy, C++) | PhotonPower/PathTracer, plugin `pathtracer` |

The chain we want is: **n,k + topography (+ particles) → rigorous scattering → BSDF → path tracer,
lit by a Raytatouille luminaire → image / irradiance of the CAD product.**

Today the path tracer only knows a flat material table (`Param.table`: one kind per row – diffuse,
mirror, glossy, glass, metal, frosted, … – with a few numbers and an optional spectrum). It has no
tabulated BSDF, no layers, and it takes light sources only as emitting CAD objects or IES/LDT
files. There is no common format for refractive indices, topographies or BSDFs between the plugins.

The node workflow (ADR 0010) already provides most of what such a chain needs: blocks from several
plugins in one graph, an engine with a result cache keyed by content, progress and Cancel, large
data passed as handles (`rtt_fusion.portdata`), and groups.

## Decision

**D1 – The chain lives in the node workflow; no second node editor.** Materials are built from
blocks in the workflow of ADR 0010. Blocks with data sockets only (no light ports) are allowed.

- A material is a group whose output is a `pt.material` block. The group can be collapsed, copied
  and given variants like any other group.
- The material name of a `pt.material` block is what the attribute `pt.material` of CAD objects
  refers to. Assignment stays as it is today. The table materials of today remain valid and keep
  working as analytic materials (D5).
- A Blender-like material editor whose graph is evaluated at every hit is rejected (see
  *Alternatives*).

**D2 – New port data types.** They are dataclasses in a new module `rtt_fusion.material`, written
with `rtt_fusion.portdata`. Units are RTT-Fusion's (its docs/konventionen.md): lengths in mm, vacuum
wavelengths in µm, angles in radians; the path tracer converts to its nm. Every type is versioned.

| Type | Content |
|---|---|
| `Spectrum` | values on a wavelength grid (µm); linear interpolation, constant outside the grid |
| `RefractiveIndex` | n(λ), k(λ) on a grid. Anisotropic case: principal values n₁,₂,₃(λ), k₁,₂,₃(λ) and the orientation of the principal axes |
| `Topography` | either a height map (heights, pixel pitch, size) or statistics: rms height, correlation length, autocorrelation type (Gaussian, exponential) or a tabulated PSD |
| `ParticleScatter` | per wavelength: scattering and absorption cross sections, and the phase function (unpolarised: M₁₁ over the scattering angle), averaged over the orientation distribution of the particles; the host medium's index |
| `Bsdf` | the scattering of a surface or a layer stack (D3) |

Every value records its *provenance*: the producing block type and plugin version, a hash of the
parameters, and, for statistical results, the number of realisations and an uncertainty estimate.

**D3 – The BSDF format.** One format for simulated, measured and analytic data:

- **Polarisation.** Unpolarised and radiometric. Simulations average s and p (Mueller element
  M₁₁); the polarised data stay in the producing plugin.
- **Grids.** A wavelength grid λₖ and an incidence grid θᵢ,ⱼ. Isotropic materials depend on
  (θᵢ, θₒ, Δφ); anisotropic ones on (θᵢ, φᵢ, θₒ, φₒ), in the local frame of the surface (D5).
- **Coherent (specular) part.** Reflectance R and transmittance T of the zeroth order per (θᵢ, λ),
  plus the index behind the surface, which fixes the refracted direction.
- **Diffuse part.** Tabulated BRDF / BTDF f in 1/sr over the outgoing hemisphere(s), per (θᵢ, λ).
  The scattered power is ∫ f cos θₒ dω.
- **Diffraction orders** (optional, for periodic structures): grating vector(s) in the local frame
  and the efficiencies of the orders (m, n) per (θᵢ, λ). Their directions follow from the grating
  equation.
- **Absorption** A per (θᵢ, λ).
- **Energy balance.** R + T + scattered + Σ orders + A = 1 for every (θᵢ, λ). Data that miss it by
  more than a tolerance (default 1 %) are rejected or rescaled only on request, and the import
  reports the deviation. Reciprocity is checked and reported, not enforced.
- **File.** A `Bsdf` is port data. As a standalone file (`.bsdf`, a zip of the port data folder) it
  is used for exchange and the material library.

**D4 – Blocks.** Every type id carries its plugin's prefix (ADR 0010).

| Block | Plugin | Inputs → output |
|---|---|---|
| `nk.file`, `nk.catalogue` | pathtracer | table file (also n,k computed by elliDFT); glass catalogue (AGF/Sellmeier) → `RefractiveIndex` |
| `topo.file`, `topo.random` | SpeckleBem | measured height map (AFM, WLI); Gaussian / exponential random surface → `Topography` |
| `speckle.scatter` | SpeckleBem (new plugin, ADR 0010 W5) | `RefractiveIndex` (material and background), `Topography`, λ and θᵢ grids, number of realisations → `Bsdf` |
| `hpfem.particle` | hp-FEM | particle shape (parametric or a CAD body), anisotropic `RefractiveIndex`, host index, orientation distribution → `ParticleScatter` |
| `layer.stack` | pathtracer | top interface `Bsdf` (rough: from `speckle.scatter`; smooth: Fresnel), coating (thickness, host index, particle volume fraction, `ParticleScatter`), substrate `Bsdf` → `Bsdf` of the whole stack |
| `bsdf.file` | pathtracer | measured BSDF (own format first; goniometer formats as later importers) → `Bsdf` |
| `bsdf.analytic` | pathtracer | Lambert, GGX (metal, dielectric), ABg / Harvey → `Bsdf` (tabulated) |
| `bsdf.mix` | pathtracer | `Bsdf` × n, weights → `Bsdf` |
| `pt.material` | pathtracer | `Bsdf` (later also maps over (u, v), D9), name → material |

Type ids carry their plugin's id (ADR 0010, D2); the short names here stand for them – in the
pathtracer plugin `pathtracer.bsdf_file`, `pathtracer.bsdf_analytic`, `pathtracer.bsdf_mix`,
`pathtracer.material` (stage M2), later `pathtracer.layer_stack`, `pathtracer.nk_file`,
`pathtracer.render`.

Details of the producing blocks:

- **`speckle.scatter`** uses the DRC of SpeckleBem, averaged over realisations, and separates the
  coherent part |⟨E⟩|² (specular, R / T) from the incoherent part ⟨|E|²⟩ − |⟨E⟩|² (diffuse f). The
  patch size and the beam waist limit the angular resolution, so they are recorded in the
  provenance.
- **`layer.stack`** computes the stack by the adding–doubling method for plane-parallel layers
  (radiative transfer with the particles' phase function). The path tracer therefore never traces
  volume scattering inside thin coatings.

**D5 – Path tracer kernels: a material is a stack of lobes.** Both kernels, NumPy and C++, get the
same extension, with tests that compare the two:

- **Lobes.** Delta lobes for the coherent part (reflection, refraction) with tabulated R / T; one
  tabulated diffuse lobe; delta lobes for diffraction orders. The material kinds of today become
  analytic lobes, so old documents give the same results.
- **Sampling.** The lobe is chosen in proportion to its share of the power at (θᵢ, λ). Within the
  diffuse lobe, a 2D cumulative distribution over the outgoing hemisphere per (θᵢ, λ), linear
  between neighbouring θᵢ. The kernels' wavelength channels are interpolated from the BSDF's λ grid.
- **Local frame.** Normal and tangent; the tangent is ∂S/∂u of the NURBS face (normalised), so
  anisotropic BSDFs and gratings have an orientation without extra data.
- **Checks.** A white-furnace test (energy), reciprocity, and the two kernels agreeing within the
  Monte Carlo noise.

**D6 – Rendering as a block; the luminaire from Raytatouille.**

- **`pt.render` block.** Its inputs are the materials (the `pt.material` blocks) and the light; the
  scene is the CAD document. Its outputs are an image and irradiance textures, shown as results.
  The actions of the plugin stay for quick runs without the workflow.
- **Light from Raytatouille.** First a **ray set source**: the rays leaving the luminaire's exit
  surface (position, direction, λ, power) start light subpaths (light tracing, bidirectional).
  Then a **near-field luminance source**: luminance binned from the ray set over the exit surface,
  which path tracing needs for direct light sampling. IES / LDT far fields stay.

**D7 – Caching, cost and library.**

- **Cache.** Rigorous runs are expensive: |θᵢ| × |λ| × 2 polarisations × realisations runs per
  `speckle.scatter`. The engine's content-keyed cache (ADR 0010 D5) recomputes a `Bsdf` only when n,k,
  topography, grids or solver settings change.
- **Cost estimate.** The blocks report their cost estimate in the catalogue, and the check warns
  before an expensive run.
- **Reciprocity.** It halves the incidence grid when the material allows it (isotropic, no
  orders).
- **Stored results.** Computed `Bsdf`s are saved with the document, so opening it does not
  recompute them. A material library (`.bsdf` files plus material groups) shares them between
  documents.

**D8 – Physical limits, stated in the documentation.**

- **Incoherent between surfaces.** Ray optics is incoherent between different surfaces.
  Interference inside a layer stack is computed coherently in its block, but only there.
- **Polarisation.** Polarisation is dropped between bounces. Mueller lobes are a possible later
  extension of D5.
- **Speckle.** Speckle contrast is not rendered: the BSDF is the ensemble mean.
- **Sparkle.** Sparkle of effect pigments needs spatial variation (D9).

**D9 – Later: spatial variation.** Maps over the normalised (u, v) of a face – a weight between two
BSDFs, an orientation field for anisotropic BSDFs, random sparkle – are baked per face onto a grid
in Python, as the path tracer's irradiance textures already are, so the kernels only read a texel.

## Alternatives rejected

- **A separate, Blender-like material node editor evaluated per hit.** It would need a graph
  interpreter in both kernels (slow in the vectorised NumPy kernel, hard to keep in step), it would
  duplicate the workflow editor, and it would have no cache for the expensive simulations.
- **Fitting the simulations to analytic models (ABg, GGX) only.** That loses what the rigorous
  computation found. `bsdf.analytic` remains for analytic materials and as a comparison; the table
  is the reference.
- **Volume scattering of coatings in the path tracer.** For thin layers full of particles it is
  slow and noisy; adding–doubling is exact for plane-parallel layers and runs once per material.

## Stages (proposal)

| Stage | Content | Acceptance |
|---|---|---|
| **M1 BSDF in the kernels** | `rtt_fusion.material` (`Spectrum`, `Bsdf`), lobe stacks and the tabulated lobe in both kernels, `bsdf.file`, `bsdf.analytic` | GGX as a table reproduces today's metal material within the noise; white furnace; NumPy and C++ agree; old documents unchanged |
| **M2 Materials in the workflow** | data-only blocks, `pt.material`, `bsdf.mix`, assignment by name, a preview sphere for material blocks (block previews) | a document with block materials renders as with the equivalent table materials |
| **M3 Rough surfaces** | SpeckleBem plugin with `topo.*` and `speckle.scatter`; `nk.file`, `nk.catalogue` | smooth surface: Fresnel only, no scatter; small roughness: agrees with Rayleigh–Rice in its range; energy balance of the simulation within 1 % |
| **M4 Coatings with particles** | `hpfem.particle`, `layer.stack` (adding–doubling) | isotropic sphere: equals Mie; layer without particles: equals the Fresnel stack; energy balance |
| **M5 The product under the luminaire** | `pt.render` block, ray set source from Raytatouille, later the near-field source | a plane under the luminaire: irradiance equals Raytatouille's own detector within the noise |
| **M6 Spatial variation** | (u, v) maps (D9) | per feature |

Repositories touched: RTT-Fusion (`rtt_fusion.material`, port data), PathTracer (both kernels:
lobes, tabulated BSDF, ray set source), CAD (plugins `pathtracer`, `hpfem`, new plugin SpeckleBem;
data-only blocks in the workflow editor if they need changes), SpeckleBem
(Python API as needed by its plugin).

## Consequences

The appearance of a product follows from its physics: from n,k and topography to the rendered
image, reproducible in one document and recomputed only where an input changed. Each kernel stays
in its own plugin, as ADR 0010 intends. Measured BSDFs from customers use the same path as
simulated ones.

Costs:
- a BSDF format and the `rtt_fusion.material` types to maintain;
- the lobe-stack extension in two kernels, which must be kept in step;
- a new plugin (SpeckleBem);
- expensive simulations, which make the cache and the cost estimates essential.

## Open questions for the maintainer

1. **Order of M3 and M4.** Rough surfaces (SpeckleBem) or particle coatings (hp-FEM) first?
2. **Topography input.** Which measured formats matter (AFM, WLI: e.g. `.sur`, `.datx`, `.gwy`)?
3. **Goniometer formats** to import for `bsdf.file` besides our own.
4. **Where `layer.stack` lives.** In the pathtracer plugin, or in a small materials plugin together
   with `nk.*` and `bsdf.*`?
5. **elliDFT as a plugin.** A plugin of its own, or are its n,k tables imported as files at first?

## Stage M3 split (2026-11-28, with the maintainer)

A rigorous SpeckleBem run of one rough patch takes 26–50 min on a 24-thread desktop, a whole BSDF
100–200 h: not on the workstation. M3 is therefore split:

- **M3a – approximation (local, seconds).** `pathtracer.nk`, `pathtracer.topography` (statistics or
  a height map; the `topo.*` blocks of D4, now in the pathtracer plugin) and
  `pathtracer.rough_surface` (Rayleigh–Rice, RTT-Fusion `material.rayleigh_rice`). It is also the
  reference the rigorous results are checked against in its range (σ ≪ λ).
- **M3b – SpeckleBem on a server.** The SpeckleBem plugin writes the cases of a BSDF as a job
  (SpeckleBem's sweep driver), the maintainer runs it on a server and copies the result folders
  back; a block reads them into a `Bsdf`.

## Answers of the maintainer (2026-11-28)

1. Rough surfaces first: M3 (SpeckleBem) before M4 (hp-FEM particles).
2. Topography formats: decided when M3 starts.
3. Goniometer formats: our own `.bsdf` first (M1); importers are decided later.
4. `layer.stack` lives in the pathtracer plugin (with `nk.*` and `bsdf.*`).
5. elliDFT stays outside: its computations take very long, so its n,k results come in as tables
   (`nk.file`). There is no `elli.nk` block and no elliDFT plugin.
