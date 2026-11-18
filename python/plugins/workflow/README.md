# Workflow (engine of the node workflow)

The engine of Raytatouille Fusion's node workflow ([ADR 0010](../../../docs/adr/0010-multi-plugin-workflow.md),
stage W1): **Check workflow** checks the model, plans the representation per link and marks the
blocks; **Run workflow** computes what the display blocks show (camera images, sweep curves, beam
probes; links set to H as fields), keeps earlier results and turns every display's view into a
result with the key `workflow:<block>` and a fingerprint (`stamp`: the executor's content hash of
the display, the same in every session). CAD saves these results in the `.rttf` file. After
opening, a display whose kept fingerprint still matches counts as up to date, and a run skips it.

Blocks of other plugins (ADR 0010, W2): the engine asks CAD for the other plugins' block catalogues,
adds those types to its library and has such a block evaluated in its plugin's process (inputs and
outputs as RTT-Fusion port data); the workflow records the provider of every such type it uses.
A detector with another plugin's block on its path (a FourierGrating sample) calls that block
itself, so the engine computes it in its own process, which reaches both plugins.

The panel holds the image settings: rays per field and wavelength, pixels, image window (0: each
detector's own size), a Gaussian illumination and the field accuracy ε of links set to H (the
error Fieldtracing may make, relative to the peak amplitude; it takes the cheapest method within
it, e.g. Debye near a focus at 0.05 instead of Rayleigh–Sommerfeld at 0.02) and *Wave optics
near a focus*: a detector on a link left on auto computes fields from the last surface on when
the rays cross or focus near it, and rays otherwise; after the run such a link shows what was
used, e.g. **R→H** (planned R, computed as fields). The engine knows no kernel – the blocks' data
come with the workflow (a Raytatouille system from the data of the `rtt.*` blocks, its glass
catalogues stored in the source, `rtt_catalog_data`, from the files the Raytracer plugin writes
into `rtt_catalogs` or lists under *Glass catalogues* in its panel – the one place for them). Until stage W3 the
blocks of all kernels are evaluated in this plugin's process, so its Python environment needs
`rtt_fusion` and, for Raytatouille blocks, `raytatouille` (the same environment as the Raytracer).

Files that blocks name – a grating's FourierGrating configuration or Jones table, a layer
stack's configuration – are stored in the blocks by *Check workflow* (and *Run workflow*), and the
paths are cleared, so the `.rttf` computes on any machine; a named file that cannot be read is a
warning (`graph.file_unreadable`). STEP files of CAD layers in a FourierGrating configuration stay
outside (`graph.file_external`).

**Overviews** (tab *Overview* of a block's parameter dialog, `workflow_preview.py`, pure Python):
the engine draws the blocks it computes itself – the ideal optics `optics.*` (a lens as its symbol
with focal points and f, a detector's plane with its size and the arriving light, the collimated
source's beam, a mirror hatched behind, a splitter dashed, an interface with both indices) and the
particle `fusion.particle` (its circle in µm); `plugin.json` lists them under `"previews"`.

A workflow made before the blocks held their data cannot run here: run *Workflow from system* once
in the Raytracer plugin.
