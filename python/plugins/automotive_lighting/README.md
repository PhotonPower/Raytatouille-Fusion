# Automotive Lighting plugin

Headlamps and signal lamps for filament lamps (H1, H4, H7, H8, H9, H11, HB3, HB4 with the filament
along the axis; H3, P21W, PY21W, R10W, R5W with the filament across it; or your own data), in two
systems (*System* in the panel):

- **Clear lens: facetted reflector.** The mirror is facetted so that the low beam gets its
  **cut-off line** from the mirror alone, and the facets are joined to one surface that can be
  moulded. Most of this page.
- **Patterned lens: paraboloid and lens** (Streuscheibe). A paraboloid mirror and, in front of it,
  a lens whose inner side is a grid of elements – prisms, cylinder lenses, pillows – that turn and
  spread the light. See *Patterned lens* below.

Needs only NumPy in the plugin environment; the ray tracing also the Path Tracer plugin next to
this one (and, to be fast, its C++ kernel).

Coordinates: **+X** is the driving direction (the light leaves along +X), **+Y** left, **+Z** up; the
centre of the filament lies at *Filament centre*. On the measuring screen H is positive to the right
and V upwards.

## Panel

- *Lamp*: the filament as a cylinder (length, diameter) and its luminous flux; nominal flux of
  UN/ECE R37, typical coil dimensions – check them against the lamp's sheet, or enter them under
  *Custom*. H4: the low-beam coil above its shield and the black cap on the bulb's tip, after
  UN/ECE R37 sheets H4/1 to H4/5: the shield's edges on plane H and 15° below it (light leaves
  over them into the upper 195°), the top of the coil 0.6 mm above plane H; the shield a trough
  about the reference axis from 1.2 mm behind the coil (closed by an end wall) to 3.4 mm in front
  of it (open); the cap seen at 40° from the axis point p = 28.95 mm (the limit of the sheet) on a
  bulb 13 mm across. The regulation fixes the edges, the coil's position and the cap's angle;
  the trough's radius (4.3 mm: about 8.6 mm wide, 4.2 mm deep) and its length are taken from the
  drawing of sheet H4/3, which is not binding for the shield, the bulb's diameter is assumed. In
  its headlamp the H4's mirror has its focus at the driving-beam coil, 6.7 mm behind the
  low-beam coil's centre (*Mirror focus behind the filament centre* 6.7).
- *Cut-off*: right- or left-hand traffic, the height of the horizontal part (−0.57° = 1 %), the
  rise (15°) and the position of the kink.
- *Frame*: the outline of the mirror seen along X – closed curves drawn in CAD (*Frame (curves)*,
  joined end to end) or a rounded rectangle – and the radius of the lamp hole.
- *Reflector*: the focal length of the base paraboloid, the strip width, the **facet length**
  (0: whole strips; else every strip is cut into rows of this length) and the **zones**.
- *Connecting faces*: on / off, the draft angle of the walls between the facets and the fillet
  radius at their foot and head.
- *Lens* (patterned lens only): position, shape, thickness, refractive index, transmittance,
  the **structure** (cylinder strips – their width and segments – or cells, their size), draft angle and fillet radius of the walls between the elements, the position of
  the mirror's focus, the **sectors** and the **elements**; for *Optimise lens* its margin, rounds, the weight of
  the beam's evenness, what the cells start with, whether the elements follow the edges of their
  light, the band under the cut-off and the rising branch a real beam has, and whether the lamp's
  blur is measured by ray tracing.
- *Analysis*: the shadows of the steps on / off, the **direct light of the lamp** on / off, the
  **test points** – the low beam's (UN R112) or a signal lamp's (UN R148) –,
  reflectance of the mirror and of the connecting faces (0: masked or matt walls),
  the lattice of mirror points, the number of filament images.
- *Ray tracing*: the number of light paths (default 5 million), the longest path (20 segments),
  the H4's **lit coil** (passing or driving beam), the coil's **wire diameter** and **turns** (0:
  estimated, see below), the **temperature at its ends** (2400 K; 3100 K: even), the **bulb glass**
  on / off with its outer diameter and wall (0: typical of the lamp), the **H4 shield's
  reflectance** (0.5) and the kernel (automatic, C++, NumPy). *Lamp → Custom: power* is the power
  its coil is estimated from.

**Zones.** A zone is a sector about the lamp axis (azimuth 0° = left, 90° = up, 180° = right, seen
in the driving direction; each row reaches to the next row's start). Its facets use one branch of
the cut-off – *horizontal* or *rising* – and place their filament images along it: the image of
the filament centre at *aim* (H), running from the strip's right border to its left one (the
spread of each strip). *below cut-off* keeps the images of a zone that far under the line.
*Default zones* fills the table for the chosen traffic side: the flank whose images lie along the
rising branch carries it, the other flank forms the horizontal cut-off and the hot spot, top and
bottom spread the light.

## Actions

- **Generate reflector**: the mirror as trimmed NURBS faces – every facet (bicubic B-spline,
  trimmed with its cell) and every connecting face – and the filament as a cylinder, in the
  model-tree group *Reflector &lt;lamp&gt;*; a new run replaces the last reflector. The faces carry
  the attribute `al.part` (`facet`, `connection`, `filament`). The log gives the area, the depth,
  how close the filament images lie to the cut-off, the highest step, the smallest draft angle
  and the share of the mirror the connecting faces take.
- **Filament images**: the outlines of the filament images of points all over the facets on the
  screen, with the cut-off line (*Image* window).
- **Light distribution**: the luminous intensity (cd; 625 cd = 1 lx at 25 m) as an image, the test
  points and zones of UN/ECE R112 (class B, passing beam) as a table, a vertical cut through the
  cut-off at 2.5° and a horizontal cut at V = −0.86° as curves; flux (also what the connecting
  faces send into the beam – stray light), the sharpness G of the cut-off and the highest
  intensity above it in the log. With *Direct light of the lamp* the light that leaves the coil
  forwards past the mirror is part of the image and the table (with the patterned lens through the
  lens; it may miss it): an H4's cap stops it within about 40° of the axis, a lamp without a cap
  sends it all over the screen – with an H7 up to about 100 cd, Φ sin θ / π² at θ from the axis.
  Its flux is logged apart from the beam's.
- **Light distribution (ray tracing)**: the same image, table and cuts by ray tracing (see
  below), in the result set *Low beam &lt;lamp&gt; – ray tracing* beside the other one for comparison.
  The log names the kernel, the light paths and the time, the coil (wire, turns, pitch, how much
  of the wire's light gets out of the coil), the flux in the beam, of the connecting faces, direct,
  backwards, into the housing (with a lens) and absorbed, and the noise where the light is
  brightest.
- **Generate lamp**: the lamp as the ray tracing has it (see below), as NURBS faces in the
  model-tree group *Lamp &lt;lamp&gt;* at the *Filament centre* – the coil's wire in the quarter
  turns that are traced (*Coil 3.2*: third turn, second quarter; the attribute `al.luminance` is
  its luminance against the coil's middle), the bulb's glass, the black top, the H4's shield and
  its other coil, each in a group of its own, with the settings of the panel's group *Ray tracing*
  (wire, turns, bulb, lit coil). The faces carry the attributes `al.lamp` (`coil`, `other coil`,
  `bulb`, `cap`, `shield`) and `al.material`; a new run replaces the last lamp, *Generate
  reflector* leaves it. Glass is drawn like any other face: hide the group *Bulb glass* – and the
  filament's cylinder of *Generate reflector*, which the wire touches from inside – in the model
  tree to see the coil. The ray tracing does not read these faces: it builds the lamp anew from
  the panel.
- **Optimise lens** (patterned lens): chooses every cell's element so that the low beam meets the
  R112 test points and zones with *Optimise: margin* (see *Optimising the lens* below) and writes
  the element table, one row per cell (per part of a cell the sectors cut) – and, if it was empty,
  the sector table; the result sets *… – optimised lens, filament images* and
  (with the lamp's blur measured) *…, ray tracing* show how the lens built does.
- **Show strips**: the start curve and some characteristic strips of every facet as lines.
- **Default zones**: the zone table for the chosen traffic side.

## The method

A mirror point P with unit normal n images the filament point Q into the direction
d = R_n (P − Q)/|P − Q| (R_n: the reflection). The **filament image** of P – all these directions –
lies below a branch of the cut-off, the plane m · d = 0 through the lamp, and touches it exactly
when the cut-off plane through P, *mirrored at the facet*, touches the filament:

    F(P, n) = m' · (C − P) − σ(m') = 0,        m' = R_n m

(C: the filament centre, σ: the support function of the filament cylinder). For a surface this is
a first-order partial differential equation. Its **characteristic strips** – curves on the mirror
together with the normals along them – solve the ordinary differential equations

    dP/ds = −2 [(g · n) m_t + (m · n) g_t],        dn/ds = m_t,

with g = Q* − P towards the filament point that touches and m_t, g_t the tangential parts of m and
g. Along such a curve the mirror may tilt about the curve's tangent without lifting the image off
the cut-off; the image only slides along the line. The curve lies in a plane normal to the
direction of the cut-off at the image – a vertical section for the horizontal branch aimed
straight ahead, a tilted one for the rising branch, and a curved strip on the mirror in general.

A **facet** is the family of characteristic strips through a start curve across the strip. On the
start curve the normal is fully prescribed – the image touches the cut-off and its centre lies at
the aim – which gives an ordinary differential equation for that section; its middle lies on the
base paraboloid. So on the whole facet every filament image touches the cut-off, to the accuracy of
the B-spline (reported, typically below 0.05°); the aim holds on the start curve and drifts with
the distance from it. The start curve lies at the facet's deepest section, so that strips whose
aims diverge (right border aimed right) fan out towards the rim; aims that converge too strongly
make the strips cross, which is reported. A steep part of the mirror cannot throw its light
across its own wall: where the zone's aim asks for that, the aim is held back (the log names the
facets).

**Rows.** The aim of a facet holds on its start curve and drifts away from it; a long strip aimed
with a wide spread narrows its spread towards the rim. With a *facet length* every strip is cut
into rows (straight across the strip, the row 0 about the lamp axis' level). Each row is a facet of
its own, with the zone's aims on its own start curve; from the lamp axis' level outwards every row
starts where the row before it ends, so only a low step and a crease remain between rows.

The **strip borders** follow the characteristics of a facet aimed at the middle of the zone's
aims: sections of the base paraboloid with parallel planes, which are straight lines in the front
view for a zone aimed straight ahead and circles otherwise.

Where the long edge of the filament image is parallel to the cut-off, the end of the coil that
touches changes; the surface is smooth there but its curvature jumps (the strips are integrated
with the change located inside the step).

**A coil across the axis** (H3; for a fog lamp *Cut-off → Rise* 0 and one zone or an upper and a
lower one; the asymmetric cut-off with its rising zone works as well). The image of such a coil lies along a horizontal cut-off – both its ends touch – where the
mirror's normal has no part along the coil. One such line runs across the strips near the lamp
axis' level: the strips cross it and change the touching end, as above. The other runs along
the strips, where a facet looks straight ahead sideways; the strips of its two sides run into
each other there. So a strip border lies at the lamp axis (not a strip's middle), and every facet
keeps to one side of that line: where its aim would bring it across, the aim is moved on (the log
names these facets – those next to the lamp axis, whose beams then cross).

## Connecting faces

Neighbouring facets meet with a step that changes along their border (each facet starts on the
base paraboloid, then follows its own differential equation). So that the mirror is one surface
that can be injection-moulded – demoulding along X – the facets are joined by **walls with a draft
angle**, **rounded** at their foot and head. Across a border (ξ, in the front view) the mirror is
the raw profile G – one facet for ξ < 0, the other for ξ > 0 – turned into

    F1 = median(L, w, U)      the wall w through the middle of the step, with the slope
                              cot(draft), kept between the envelopes L ≤ G ≤ U of that slope;
    F2 = open(close(F1))      a ball of the fillet radius rolled over both sides.

Where the step vanishes the wall does too, and only the crease between the facets is rounded.
The profiles of all stations along a border make a **band**, a bicubic B-spline that runs out
into the facets on both sides; the facets are trimmed back to it. There are three levels, the
sides of each being what the levels before have built: the bands between the rows of a strip,
then those between the strips of a zone, then those along the rays between two zones – so the
junctions are covered too. Along a border the stations lie closer (0.1 mm instead of 0.5 mm)
where a wall of a lower level meets it. All bands between zones have one width.

What to expect: the walls keep the draft angle (a little less only where two walls meet at a
junction – the smallest angle is logged); bands and facets join within about 0.01 mm; the bands
take 10 – 15 % of the mirror with the default settings and send their light elsewhere – the
light distribution shows it as stray light above the cut-off. Lower steps mean narrower walls:
narrower strips, a smaller spread per strip, or neighbouring zones with similar aims.

## Patterned lens

*System → patterned lens*. The mirror is the paraboloid of *Reflector → Focal length* within the
frame, outside the lamp hole; *Lens → Mirror focus behind the filament centre* moves its focus
(H4: the low-beam coil sits before the focus – in the H4's headlamp the focus is at the
driving-beam coil, 6.7 mm behind –, so the upper half of the mirror, which alone gets light past
the shield, sends it below the horizon). The lens is a plate that meets the lamp axis
at *Lens in front of the filament*; its outer side is smooth, its inner side carries the elements
– **cylinder strips** (*Structure*, the default, below) or a grid of **cells** (*Element width /
height*, one cell centred on the lamp axis). It may lean back (*Rake*: its top
towards the mirror), run back to one side (*Sweep*) and be domed outwards (*Dome radius*, a
sphere): the outer side has that shape, the inner side the same shape *Thickness* behind it
(measured along X) with the elements on it.

**Elements.** Each row of the table holds a region (y to the left, z up, about the lamp axis) and
what the cells with their centre in it do; the first row that holds a cell counts.

- *deflect H / V*: by how much the cell turns the light in its middle – a prism.
- *spread ± H / V*: by how much more at its borders, running linearly across the cell (its left
  part to the left, its upper part upwards; negative: the other way round, the rays cross) – a
  cylinder lens with one spread, a pillow with both.
- *spread turned by*: both spreads turned on the screen by this angle (counter-clockwise as the
  driver sees it): a cylinder lens (spread V 0) turned by 15° spreads the light along a line that
  rises by 15° – as the facets of a clear-lens reflector lay their filament images along the
  cut-off. The spread is reached at the cell's farthest corner along its direction.
- All 0: plane glass.
- *sector*: the sector whose part of the cell the row is for (their number by azimuth, from 0);
  −1: every part.

**Sectors.** The table cuts the lens into radial sections about the lamp axis – as the zones of a
clear-lens reflector, each from its azimuth (0 left, 90 up, seen in the driving direction) to the
next one's, with the cut-off branch its light ends at. With two or more, the cells the radial
lines cross are cut along them: each part is an element of its own (its patch designed over the
whole cell, its deflection about the part's middle and its spread over the part's extent, used in
its part), the step between two parts a wall along the radial line (ruled between the two patches
along it – a patch of degree 5 along a line is a curve of degree 10, exact). The H4's light that
leaves the shield by its slanting edge reaches a wedge from the middle of the lens whose borders
are radial lines – a classic H4 lens has its slanted flutes there – and cells of a square grid
mix it with the rest at both borders: some 40 % of that light lies in cells half in, half out.
Empty: one sector; *Optimise lens* (along the edges) fills it. Not with a draft angle yet.

**Cylinder strips** (*Structure → cylinder strips through the sectors*): cylinder lenses that run
through their sector, *Strip width* wide (5 mm; one centred on the lamp axis) – upright where the
sector's light ends at the horizontal branch, leaning by the rise (15°) in the wedge whose light
ends at the rising one, their cylinders spreading along it: the flutes of a classic H4 lens. Along
a strip, its **segments** (*Strip segments*, 10 mm; 0: the strip in one piece) are its elements:
the table's row that holds a segment's middle counts – y and z are then the strip's coordinates
t = y cos φ − z sin φ across and w = y sin φ + z cos φ along (φ its lean; for upright strips y and
z). A segment's prism may be its own; its cylinder is the strip's – *Optimise lens* keeps it so:
the cylinder lens runs through the strip, the prisms make steps between its segments (a segment
like the one before it, with no prism up or down along the strip, goes on from it without a
step). The slopes of a segment are integrated along the strip's middle and then across it; its
surface is the B-spline closest to that (degree 5 across, cubic along, a span per 8 mm), exact in
CAD as such and trimmed to the segment's part of the sector. The walls between strips and between
segments are ruled between their rims; those along the sectors' radial lines are fitted (cubic,
within some 1e-5 mm), piece by piece between the strips and segments the line crosses. Not with a
draft angle yet. With cells, each has a prism and a cylinder lens of its own and a step to all of
its neighbours: in CAD a mosaic of square patches, the cylinders not running on.

For a point of a cell, the ray that comes from the filament centre by way of the mirror
(direction d) is to leave the lens turned by these angles (direction t). The direction g inside
the glass follows from t by refraction at the outer side (with the normal of the lens' shape
there), and the inner surface gets the normal N ∝ d − n g (Snell's law in vector form). A plate
of any shape without elements turns nothing. Its slopes are integrated over the cell and the
cell's surface is the Bézier patch of degree 5 closest to that (the log gives the largest slope
error).

Neighbouring elements meet with a step – at every border of a row of prisms, less between
pillows. It is closed by a **wall** along X, ruled between the rims of the two patches. A ray that
meets a wall is mirrored there once and goes on as stray light: from the air before the elements
with the reflectance of the glass at that – grazing – angle (what enters the wall is lost), in
the glass behind them by total reflection (or with its reflectance). *Light distribution* logs how
much of the light from the mirror meets the walls and how much of that goes on.

With *Lens → Draft angle of the walls* the walls lean by that angle against X and are rounded at
foot and head with the *Fillet radius of the walls* – as moulding or pressing needs them. They
are built like the connecting faces of the facetted reflector: the profile across every border
(the wall through the middle of the step, a ball rolled over both sides), as bands that run out
into the elements – first between the elements of a row, then between the rows. The walls are
then part of the inner surface: a ray that meets one is refracted there like anywhere else (the
log still names the share of the light on them), and the elements are trimmed back to the bands.

*Generate reflector* adds the mirror (exact, with the lamp hole), the outer side of the lens, every
element and every wall as trimmed NURBS faces (`al.part` = `mirror`, `lens`, `element`, `wall`) in
the group *Headlamp &lt;lamp&gt;*. *Filament images* and *Light distribution* trace from the coil to the mirror
and through the lens (refraction at both sides, *Transmittance*; a ray that misses the lens or is
totally reflected at its outer side is lost; one that meets a wall is mirrored there).

**Signal lamps.** With *Analysis → Test points* set to a signal lamp, *Light distribution* shows
the points of its standard light distribution of UN R148 (± 20° horizontally, ± 10° vertically:
the percentage of the minimum intensity required on the axis) and the highest intensity in any
direction, for a single lamp: front position lamp (4 … 140 cd), rear position lamp (4 … 17 cd),
stop lamp S1 (60 … 260 cd), direction indicator front 1 (175 … 1000 cd) and rear 2a
(50 … 500 cd), daytime running lamp (400 … 1200 cd, its own grid). The cuts then go through the
axis. The colour of the lens is part of *Transmittance* (a red or amber lens passes a fraction of
the lamp's flux); the lamps P21W, PY21W, R10W and R5W have their filament across the axis.

Not modelled: a second wall on the way of a ray mirrored at a wall along X (then it is lost), the
reflections at the two sides of the lens. Drafted walls are computed on the lens' elements as
they stand along X; they join the elements within about 0.01 mm. The dome is a sphere about a point on the lamp axis; the elements
stand on the lens' shape along X (for a steep rake they are sheared, not perpendicular to it).

## Optimising the lens

A low beam through a patterned lens takes its cut-off from the lamp – the H4's shield, with the
paraboloid's focus behind the coil (*Mirror focus behind the filament centre*; the H4's headlamp
has it at the driving-beam coil, 6.7 mm) –; the lens
has to place the light below it, finely: *Optimise lens* gives every cell (best a few mm, *Element
width / height*) its own prism and cylinder lens – the cylinder's strength and its direction, so
that a cell can lay its light along the cut-off: horizontally under its horizontal part, along 15°
under its rise, steeper into the foreground, as the facets of a clear-lens reflector do.

- **The cells' light.** Rays from the coil's surface by way of the mirror points reach the cells of
  a plane lens; each cell's light, binned on a grid of 0.5° x 0.1°, is its **pattern**. An element
  moves it by its deflection and smears it along the cylinder's direction over ± its spread
  (al_lens turns a cell's middle by the deflection and the rest by up to ± the spread more): evenly
  along a horizontal or vertical line, along a slanting one as a trapezoid (how a rectangle's
  points lie along it). The beam of any choice is the sum of the shifted and smeared patterns and
  the lamp's direct light – no filament images to be taken again. Choices: deflection −16 … 16°
  (1° steps) across, −3 … 0.6° (0.2°) up and down; a cylinder of 0 … 12° spread turned by −60 …
  90° (0, ± 5, 10, 15, 20, 30, 45, 60, 90°; in the wedge along the rise also 12.5 and 17.5°);
  |deflection| + the spread's part across ≤ 22°, its
  part up and down ≤ 4°, and only elements that fit into the lens' thickness (prism and cylinder
  depths taken from al_lens).
- **The objective**: R112's test points (their photometer windows) and zones III, IV and I (every
  bin; of III and I every bin that touches them – an optimiser finds any gap between the probes)
  within *Optimise: margin*, as squared shortfalls and excesses; then the smallest margin is made
  as large as it can be. Two requirements beyond R112 keep the cut-off where it is aimed: from 0.3°
  above the line (|H| ≤ 10°) at most zone III's 625 cd, and at 2.5° to the side of the oncoming
  traffic – where R112 measures the cut-off – a fall by a factor 10 from just below the line to
  just above it. Small elements are preferred where nothing depends on a cell.
- **A real beam** – what R112 does not ask but a headlamp's beam has, at a fifth of R112's weight,
  so that R112 comes first: brightest at its cut-off, not in a patch below it (*Optimise: under the
  cut-off*, 6000 cd: at least that on average 0.15–0.65° under both branches, ± 10° about the
  kink), and the kink seen with the rise lit and sharp (*Optimise: under the rise*, 3000 cd: at
  least that 0.15–0.35° under the rising branch, 1–5° from the kink, above it at most a tenth);
  0 leaves either out.
- **A target beam** (*Optimise: target beam*, a weight, 0.3; 0: none) – not only test points: the
  whole field (|H| ≤ 30°, −6 … 2°; every 1° across, 0.1° up and down near the cut-off, 0.3°
  further down) is fitted to the shape of a classic lens' beam, made from the plane lens' own
  light: each row under the horizontal branch (its light summed across) spread anew – a core
  (55 %, σ 2.5°, its middle 0.5° to the driver's side of the kink) and a wide part (σ 9°), both
  wider the deeper the row –; on the driver's side every column lifted to the rising line (up to
  1°), so that the rows follow the cut-off and the wedge under the rise is lit as the same depth
  under the line; nothing above the line. Its term: the squared difference in the blurred view,
  weighted three times within |H| < 12°, V > −4°, scaled so that the weight is that of a beam
  missing the target entirely. The rounds log how far the beam is off it (the surrogate's / the
  filament images', rms relative to the target's). With the weight 1 the target pulls against
  R112 (zone III, 25R just missed); 0.3 keeps R112 first.
- **Evenness** (*Optimise: evenness*, a weight; 0: R112 alone): below the cut-off (from 0.4°
  under the line down to −5°, |H| ≤ 20°) the beam is to be free of patches, stripes and hot
  spots. On a lattice of 1° across and 0.3° up and down, the second differences between
  neighbours – zero for a plane or a steady slope – are taken in the blurred view (the lamp as it
  is); their rms relative to 50R's minimum (10 100 cd), squared and weighted, is added to the
  objective. The rounds log it as *bumps* (the surrogate's / the filament images').
- **The search**: one cell after the other (the brightest first), its deflection over all choices
  with its cylinder kept, then its cylinder (strength and direction together) with the deflection
  kept, in sweeps over all cells; after the first sweep only choices near the present ones.
- **Along the edges** (*Optimise: along the edges*, on): as the flutes of a classic lens, every
  element spreads and deflects along the edge of its own light – the branch of its sector. With
  the sector table empty the lens is cut first: on the plane lens, in 1° steps of azimuth, where
  more than half of the light lies above the horizontal branch on the driver's side it ends at the
  rising one – the wedge in front of the mirror's sector that the shield's slanting edge lets light
  reach (H4: from 316° to 4°, 1110 elements instead of 1063 cells); the rest ends at the
  horizontal branch. Then its two radial lines are searched: the one moved by ± 6 and ± 12°, the
  best kept, then the other – for each the parts near the lines (15°) optimised again from where
  the lens with the lines first found has them (two sweeps), the surrogate's objective compared;
  the log lists them (H4: from 316–328° to 4–10°, depending on the objective). The wedge's elements
  get cylinders turned by the rise (15°, or up to 5° off it: 10 … 20°) and deflections along it
  (within 0.15°), so the rise stays on its line; the others cylinders across and any deflection.
  Free, the search pulls the wedge's light down to the oncoming traffic's side, where R112 counts
  it, and leaves the rise dark. (Without a wedge: per cell, by the majority of its light.)
- **Cylinder strips** (*Structure*, the default): the cells of the search are the strips'
  segments. A segment's prism is its own (in the wedge along the rise), the cylinder the strip's:
  when the first segment of a strip comes, the cylinder is chosen for all of its segments at once,
  their prisms kept (one strip in one piece: its deflection along its lean only, no prism up or
  down). *Optimise: strips spread at least* (0°) is the weakest cylinder a strip may have – with
  1° or 2° every strip is a curved cylinder lens; 0 lets the search leave strips flat, their
  segments' prisms alone spreading the light.
- **The start** (*Optimise: start with*): every cell begins as a cylinder lens spreading 6° across
  (the default), as plane glass, or both are tried – two searches, twice the time – and the better
  kept. The search ends near where it begins: from plane glass nearly every cell becomes a prism,
  from cylinder lenses many keep theirs.
- **Rounds** (*Optimise: rounds*): the lens is built and its filament images taken; half the
  difference from the patterns' sum is carried back, the cells are optimised again, the best
  round is kept. The patterns' sum and the filament images agree within a few per cent.
- **The lamp's blur** (*Optimise: the lamp's blur → measured by ray tracing*): the lamp as it is
  (helix, cooler ends, bulb) makes the beam softer than the filament images – on the plane lens of
  an H4 by σ = 0.5° across and 0.2° up and down (a Gaussian fitted to the ray tracing). The beam is
  then judged in two views, as the filament images have it and blurred: every lower limit in the
  darker one, every upper limit in the brighter one. Then the lens kept is ray traced (at least 20
  million light paths: below that the noise of a zone III bin is some 100 cd); what the ray
  tracing has beyond the blurred view – a faint veil, some 300 cd over zone III, that the filament
  images do not have – is carried back and the cells optimised again, twice, each lens ray traced;
  the best by its ray tracing is kept.

What to expect with cylinder strips (H4 as below, strips 5 mm wide, segments 10 mm – 415 –, the
target 0.3; ray tracing; some 11 minutes on a quiet machine, 50 on a busy one):

| ray tracing | strips spread at least 0° (default) | 1° | 2° | strips in one piece | 4 mm cells |
|---|---|---|---|---|---|
| R112 | met | 75R, zone III missed | 75R, zone III missed | 75R, 50R, 50V, 25L, III, IV missed | met |
| 75R / 50R / 50V | 11 100 / 17 700 / 10 100 cd | 9 300 / 15 600 / 8 600 cd | 7 700 / 13 100 / 7 600 cd | 4 100 / 5 600 / 3 200 cd | 11 600 / 14 300 / 11 800 cd |
| zone III / at most | 625 / 18 400 cd | 779 / 18 400 cd | 789 / 16 000 cd | 1 121 / 7 600 cd | 547 / 15 900 cd |
| cut-off | −0.70°, G = 0.30 | −0.60°, G = 0.25 | −0.70°, G = 0.27 | −0.60°, G = 0.26 | −0.50°, G = 0.32 |
| bumps (of 50R's minimum) | 3.9 % | 4.0 % | 3.1 % | 3.3 % | 2.7 % |
| strips with a cylinder | 12 of 54 | 54 | 54 | 23 of 54 | – |

A strip's cylinder spreads all along it, also where the light has to stay together under the cut-off
and at 75R: R112 holds only if most strips may stay flat (the prisms of their segments spread the
light, steps between them). Strips in one piece have no prisms up or down: the paraboloid's light,
6.7 mm out of focus, cannot be gathered to a hot spot (the prototype of continuous flutes alike:
9 650 cd at most).

What to expect with cells (H4, frame 170 x 100 mm, 4 mm cells – 1063 –, the focus at the driving-beam coil
6.7 mm behind, the shield shining at 0.5, the blur measured, 2 rounds, evenness 1, from cylinder
lenses, 0.75 GB; about 9 minutes before the sectors were searched and the target fitted, with
them some 20 … 25 minutes on a machine shared with other work): all of R112 met by the filament
images and by the ray tracing.

| ray tracing | default (sectors searched, target 0.3) | target 0 | before (0.22: lines found, 15°) | free, R112 alone |
|---|---|---|---|---|
| under the cut-off, −10 … −2° / −2 … 0° | 4 300 / 10 900 cd | 4 800 / 11 300 cd | 6 700 / 14 000 cd | 2 500 / 7 400 cd |
| under the cut-off, 0 … 2° / 2 … 6° (rise) | 11 400 / 4 800 cd | 11 700 / 4 700 cd | 12 400 / 3 300 cd | 11 800 / 3 700 cd |
| 5000 cd line at H = 4° / 2000 cd at 8° | 0.05° / 0.55° | 0.05° / −0.65° | −0.25° / −1.65° | |
| 75R / 50R / 50V | 11 900 / 14 500 / 11 300 cd | 11 800 / 18 500 / 11 100 cd | 12 400 / 16 900 / 13 300 cd | 11 000 / 19 500 / 11 900 cd |
| 25L / zone III | 2 200 / 537 cd | 2 300 / 574 cd | 2 200 / 582 cd | 2 600 / 594 cd |
| at most | 15 700 cd | 20 000 cd | 19 000 cd | 20 200 cd |
| cut-off | −0.50°, G = 0.34 | −0.60°, G = 0.28 | −0.70°, G = 0.28 | −0.70°, G = 0.46 |
| bumps (of 50R's minimum) | 3.0 % | 3.9 % | 3.8 % | 3.7 % |

Free, the light gathers in a patch 2 … 3° under the cut-off and the horizontal branch is a faint
seam; with the band it lies at the cut-off and falls off downwards, as in a real beam – the
horizontal branch carried from below, the kink seen. Cut into sectors the rise is brighter and
follows its line further than with square cells alone. Searching the sectors' lines and letting
the wedge's cylinders turn by 10 … 20° makes it brighter still (2 … 6°: 4 700 instead of
3 300 cd; at H = 4° 10 600 instead of 6 400 cd at most); the target beam spreads the light wider
across (as a classic lens' flutes), evens it, keeps the rise lit along its line out to 8° and
sharpens the cut-off – at the price of the hot spot (15 700 instead of 20 000 cd) and of the
horizontal branch's band far to the side. A prototype of the target alone (continuous flutes, no
prisms: its strips spread but do not move the light) reaches only 9 650 cd at most – 75R and 50R
below R112's 10 100 cd: the prisms of the cells are what puts the hot spot under the kink. With
the target's wedge at half the brightness of the row under the horizontal branch, as in that
prototype, the target pulls the rise down (at H = 4° 6 900 cd at most): it is lit as the same
depth under the line. How bright the beam can be at all is set by the mirror: every
cell placed on its own as well as it can, the band would hold some 7 600 cd on average with the
focus 6.7 mm behind the coil, 11 900 cd with it 3 mm behind; a longer focal length (35 mm) gives
no more – the frame's mirror takes in less light. From plane glass (free) the beam is less even
(4.2 %) with a higher hot spot (23 400 cd); without the evenness the bumps are twice as high
(9.2 %) and the hot spot 32 400 cd. Without the blur the filament images are met but the ray tracing finds
light in zone III at the cut-off's kink. With the focus close to the coil (3 mm) the shining
shield sends light above the cut-off that no lens can take back (zone III about 5 500 cd): its
rear part reflects the coil's light backwards and up, as from a coil behind the focus; at 6.7 mm
that light stays below the cut-off (a lens deflecting 1° down, ray tracing: zone III 791 cd with
the shield black, 799 cd shining; with the focus 3 mm behind 223 and 5 459 cd).

## Ray tracing

*Light distribution (ray tracing)* checks the design with the lamp as it is, without the
assumptions of the filament images, which stay as they are for the design and for *Filament
images* and *Light distribution*. *Generate lamp* puts this lamp into the model to look at:

- **The coil** is a helix of tungsten wire that fills the lamp's cylinder (length, diameter): the
  wire's centre runs on a helix of radius (diameter − wire) / 2, a NURBS face per quarter turn (a
  tube about the helix, within 0.2 µm of it). Its surface is Lambertian; light that meets another
  turn is absorbed. The flux is set so that what gets out of the coil is the lamp's flux, as from
  the cylinder – about 56 % of the wire's light does for an H7. Wire diameter and turns are not in
  UN/ECE R37: without own values they are estimated from the power – a wire at 3100 K
  (tungsten's resistivity 95.6 µΩ cm, Desai et al., J. Phys. Chem. Ref. Data 13 (1984) 1069) at
  13.2 V, the power rising with the voltage to the 1.6th, wound with a pitch of 1.5 wire
  diameters: H7 0.161 mm and 16 turns, H4 0.187 mm and 19 turns.
- **Its cooler ends**: the leads draw heat off the coil's ends. Along the wire, conducted heat
  balances Joule heat and radiation, k A T'' = π d ε σ T⁴ − I² ρ(T) / A (tungsten at 3100 K:
  k = 95 W/m K, ε = 0.34, ρ ∝ T^1.15; the current keeps the middle at 3100 K); its first integral
  gives the rise from the ends' temperature (*Coil: temperature at its ends*, assumed 2400 K) to
  the middle – 2900 K after 2 mm of wire, 3040 K after 4 mm (near the middle it closes in on
  3100 K by e every λ = √(k d / 4 ε σ T³ (4 − β)) ≈ 1.5 mm). Every quarter turn shines with the
  luminance of its temperature (Planck's law weighted with V(λ), grey tungsten): the first and last
  turns of an H7 at about half the middle's. The turns warming each other is left out.
- **The bulb**: a tube of glass about the reference axis closed by a half sphere, one glass body
  with Fresnel's reflection and refraction (quartz n = 1.458, signal lamps' glass 1.52), open at
  the back where it narrows to the pinch. Its black top, an absorbing coating just outside the
  glass, reaches as far back as R37 demands at least: to the angle γ3 from the coil's end nearest
  the reference plane (H7, H8, H11 30°; sheets H7/2, H8/2, H11/2) or from its centre (HB4 45°,
  sheet HB4/2), the H4's to its cap (α ≤ 40°). Diameter, wall and the tip's place are typical,
  within R37's outlines: H7 9 mm, H1 8.5 mm, H4 13 mm, wall 1 mm, the tip about 15 mm in front of
  the coil; P21W 26.5 mm with its tip 13.2 mm, R5W/R10W 19 mm with 11 mm in front of the coil. Without the glass the black
  top is a disc across the bulb.
- **The H4's inside**: the shield (the trough and its end wall, where the photometry has it) as a
  mirror of *H4 shield: reflectance* (0: black) – being nearly coaxial with the coil, the trough
  sends much of what it reflects back onto the wire –, and the other coil, dark, in its place
  (UN/ECE R37 sheet H4/3: the driving-beam coil 4.5 mm long, 1.7 mm behind the passing-beam
  coil, its axis 0.8 mm below plane H). *H4: lit coil → driving beam* lights that one instead
  (1650 lm): the same reflector's high beam, with the driving-beam points of UN/ECE R112 (IM
  40 500 … 215 000 cd, HV ≥ 80 % of IM, H-2.5L/R ≥ 20 300 cd, H-5L/R ≥ 5100 cd).
- **The mirror**: every facet and connecting face (or the paraboloid) as generated, with the
  panel's reflectances; **the lens** as one glass body (outer side, elements and walls, turned
  so that their normals point out of the glass) with Fresnel's reflection and refraction at the
  panel's index – *Transmittance* is not used, no absorption.
- **Light paths** start on the wire and are followed through every reflection and refraction, up
  to *Longest path* segments (the meeting points on the exact surfaces); the light that leaves
  is sorted by its direction into the cells of the screen. Light whose first surface past the
  lamp (coils, bulb, shield, black top) is the mirror is the beam, the rest that leaves forwards
  the direct light; with a lens only what leaves through it counts, the rest stays in the housing.
- **The kernel** is the Path Tracer plugin's (it must be installed next to this plugin): C++ if
  the package `pathtracer` 0.3.0 or later is installed in the plugins' Python, else NumPy. The C++
  kernel traces 5 million paths through bulb and facetted reflector in about 10 s; NumPy needs
  minutes for a few hundred thousand.
- **Noise**: every cell of 0.25° × 0.1° gets the light of a few hundred paths; the log gives the
  standard error where the light is brightest (5 million paths: some 5 %). The test points are
  means over the photometer's window, which halves it.

Compared with the filament images (H7, the test reflector, 12 million paths): the same flux in the
beam (508 against 500 lm) and directly (736 against 740 lm), the same glare above the cut-off
(288 against 293 cd), a maximum some 15 % lower – the wire shines less brightly than the cylinder
across the coil and more along its axis: seen from its ends one sees the turns, the cylinder
sends nothing there. That light meets the mirror near its vertex, where the images are large,
and brightens the beam's wide parts (with a paraboloid, at B50L: 3000 instead of 160 cd).

What the lamp adds (the panel's defaults, H7, 5 million paths, against the even coil without
glass): the cooler ends change little (G 1.03 against 0.96, the light along the coil's axis
13 % weaker); the bulb's glass most – its reflections send light above the cut-off (zone III 520
against 200 cd, B50L 180 against 15 cd, G 0.36): ghost images of the coil, which R37 asks the
lamp makers to keep above the coil (sheet H7/2, note 8). The H4 likewise (G 0.25 against 0.97, B50L
93 against 20 cd).

## Limits of this version

- Photometry (*Filament images*, *Light distribution*): the coil as an evenly shining cylinder, one reflection at the facets and the
  connecting faces, no bulb glass (its refraction), no cover lens, no housing; of the lamp's inner
  parts only the H4's shield and cap (not its driving-beam coil and supports, nor light the
  shield's inside reflects). The direct light is taken on a grid of 1° and, whether the mirror is
  in its way, from the coil centre (its rim casts no half shadow); through the lens it goes from
  the coil centre too. The cut-off
  is sharper than a real lamp's. With *Analysis → Shadows of the steps* a ray that a step of the
  mirror stops on its way from the coil to a mirror point is left out; one that it stops after the
  reflection is reflected there a second time (with the reflectance of the connecting faces) and
  counts as stray light if it then leaves the mirror freely – a third reflection is not followed.
  The log gives the stopped share; the mirror is compared as a height map of 0.25 mm, up to 6.4 mm
  sideways of the point.
- Ray tracing: typical bulbs, open at the back (no pinch); no supports or leads of the coil; the
  coil's end temperature assumed, its turns not warming each other; the wires absorb what meets
  them (tungsten reflects about half); the shield is an ideal mirror (no scatter); the lens has
  no rim – light that reaches its edge inside the glass leaves there unrefracted.
- The lamp hole must be large enough for the bands between the zones, which meet at the lamp
  axis; the strips must be wider than their connecting faces (both are reported).
- The frame should be convex or nearly so; the lamp axis is +X; the faces are separate trimmed
  surfaces (not sewn to a shell).
