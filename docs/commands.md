# Commands and keyboard input (M5)

Commands are started from the tool column, or by typing their name (or alias) + Enter – typing
while a view has the focus goes straight to the command line. The aliases are no shortcuts: the
tooltip of each tool says what to type ("Type: l + Enter"). **H** in a view hides the selection;
with nothing selected it is typed like any other letter (Helix: `h`). The prompt in the command
line says what the command expects; the rubber band (orange) previews the result. Every result is
one undo step.

| Command | Alias | Input |
|---|---|---|
| Point | `pt` | locations, until Enter / right-click |
| Line | `l` | start, end (or a length) |
| Tangent line | `tan` | one selected curve: start point, then click near the touching point; two curves: click near the common tangent (construction plane) |
| Perpendicular line | `perp` | one selected curve; points: a line from each to its foot on the curve (Enter: done) |
| Polyline | `pl` | points; Enter: open polyline, clicking the start point (it snaps as End): closed |
| Rectangle | `rec` | corner, opposite corner (edges along the construction-plane axes) |
| Polygon | `pol` | (number of sides,) centre, corner point or circumradius |
| Circle | `c` | centre, radius point or radius |
| Circle (3 points) | `c3` | three points on the circle |
| Arc | `a` | start, end, point on the arc |
| Helix | `h` | (number of turns,) axis start, axis end, radius point or radius |
| Ellipse | `el` | centre, end of the first axis (or its length), second semi-axis (point or length); exact |
| Spiral | `spi` | (number of turns,) centre, start radius, end radius (points or numbers); planar, Archimedean |
| Curve (control points) | `crv` | control points (Enter: done; clicking the first one closes); cubic B-spline |
| Sketch | `sk` | click the start, move the cursor along the curve, click / Enter: a cubic fit of the path (0.5 % of its length) |
| Curve through points | `crvpts` | the selected point objects in selection order (immediately); interpolating cubic |
| Conic | `conic` | start, end, apex (where the end tangents meet), rho in (0, 1) or a point; exact |
| Parabola | `para` | vertex, focus (or focal length), end point (or half width); exact |
| Hyperbola | `hyp` | centre, vertex, a point of the branch; exact |
| Distance | `dist` | two points; the result appears in the status bar |
| Angle | `ang` | vertex, a point on each leg |
| **Solids** (M6a) | | |
| Box | `b` | base corner, opposite corner, height (point or number, sign = direction) |
| Sphere | `sph` | centre, radius |
| Cylinder / Cone | `cyl` / `cone` | base centre, radius, height (axis: construction-plane normal) |
| Torus | `tor` | centre, major radius, tube radius |
| Union / Intersection | `bu` / `bi` | the selected solids (immediately) |
| Difference | `bd` | the **first selected** solid minus the other selected solids |
| **Deform** (selected objects; Shear and Stretch exact) | | |
| Bend | `bend` | axis start, axis end, a point on the side, angle (degrees) |
| Twist / Taper | `twist` / `taper` | axis start, axis end, angle at the end / scale at the end |
| Shear | `shear` | base point, direction point, angle |
| Stretch | `stretch` | axis start, axis end, new end (or factor) |
| Maelstrom | `maelstrom` | centre, radius, angle at the centre |
| Boolean split | `booleansplit`, `bs` | the solid to split, then the cutters: the parts outside and inside |
| Shell | `shell` | picked faces of a closed solid (open), wall thickness |
| **Transforms** (on the selection) | | |
| Move | `m` | from, to; also moves selected result drawings |
| Copy | `co` | from, to (repeat; Enter: done) |
| Rotate | `ro` | centre, angle in degrees – or two reference points (axis: plane normal); also turns selected result drawings |
| Scale | `sc` | base, factor – or two reference points (ratio of distances) |
| Mirror | `mi` | two points of the mirror line (plane through the line and the plane normal); creates copies |
| Linear array | `array` | (count,) base, step |
| Grid array | `array_grid` | (count a, count b,) base, step a, step b |
| Polar array | `arraypolar` | (count,) centre, total angle (Enter: 360°) |

| **Curves from objects** | | |
| Project / Pull curves | `project` / `pull` | selected curves and surfaces (faces of solids may be picked as parts); immediately: along the view direction / the surface normal; the trim is not applied |
| Section | `section` | selected surfaces / solids; two points of the section line (plane perpendicular to the view): closed loops of solids, trimmed pieces of faces |
| Contour | `contour` | selected surfaces / solids; base point, direction of the planes' normal, spacing (≤ 1000 planes) |
| Duplicate edge / border | `dupedge` / `dupborder` | picked edges (Ctrl+Shift-click) as curves / the boundary loops of surfaces, the free edges of open shells, joined into loops |
| Extract isocurve | `iso` | selected surfaces; points: the isocurves through them (1: u, 2: v, 3: both; Enter: done) |
| Extract wireframe | `extractwireframe` | selected surfaces; their isocurves at all knot lines, borders included |
| Offset curve on surface | `offsetcrvonsrf` | one curve and its surface; distance (sign: side), geodesic |
| Curve Boolean | `crvboolean` | closed curves in the construction plane; 1 union, 2 intersection, 3 difference (first minus the others) |

| **Editing surfaces** | | |
| Untrim | `untrim` | selected trimmed surfaces; click near a hole (Enter: every trim) |
| Extract surface | `extractsrf` | picked faces of a solid (Ctrl+Shift-click) become surfaces |
| Shrink trimmed surface | `shrink` | selected trimmed surfaces: the surface shrunk to the trim's parameter rectangle |
| Extend surface | `extendsrf` | untrimmed surfaces; click near an edge, length |
| Rebuild surface / in one direction | `rebuildsrf` / `rebuilduv` | control points in u, v (Enter: as u) / direction 1 or 2, count |
| Change surface degree | `changedegreesrf` | degree in u, v (Enter: the same) |
| Slab | `slab` | planar curves; thickness, click the side, height |
| Thicken / Make hollow | `thicken` / `makehollow` | surfaces / closed solids; thickness (smooth faces) |

| **Editing curves** | | |
| Extend curve | `extendcrv` | selected curves; click near an end, length (number or point); natural continuation |
| Divide / Divide by length | `divide` / `divlen` | selected curves; number of segments / segment length; point objects |
| Rebuild curve | `rebuild` | selected curves; number of control points, degree (Enter: 3); reports the deviation |
| Change degree | `changedegree` | selected curves; degree (raising exact, lowering within 0.1 % of the size, else rebuilt) |
| Flip direction | `flip`, `dir` | selected curves and surfaces (immediately) |
| Close curve | `closecrv` | selected open curves (immediately): end moved onto the start if near, else a closing segment |
| Curve seam | `crvseam` | one closed curve; click the new start |
| Insert / Remove knot | `insertknot` / `removeknot` | one curve; clicks (Enter: done) |
| Smooth / Fair | `smooth` / `fair` | selected curves; factor (Enter: 0.5) / tolerance |
| Match curve | `match` | the curve to change, then the one to match; 0 / 1 / 2 (Enter): position / tangent / curvature at the nearest ends |
| Simplify curve | `simplify` | selected curves (immediately): straight and circular pieces become exact lines and arcs, merged |
| Arc blend | `arcblend` | two selected curves (immediately): a biarc between the closest ends, tangent to both |
| Points on / off | `pon` / `poff` | selected curves: show / hide their control points (grips) and polygon (saved); `poff` without a selection: all |
| Select points | `selpoints` | every grip of the selected curves, or of all curves with points on |
| Weight | `weight` | selected grips; weight > 0 (1: plain) |
| Insert control point | `insertcp` | one curve (or its grips); clicks near the control polygon add a control point there (Enter: done) |

Grips (shown control points) are picked by a click (Shift: add, Ctrl: remove) or a window, before
curves and above faces; dragging a grip moves the selected grips (in the plane through it, perpendicular
to the view); Move, Rotate and Scale move the selected grips and the curve follows.

| **Curves and surfaces** (M6b) | | |
| Spline (Interpolated curve) | `sp`, `interpcrv` | points (Enter: done); interpolating cubic |
| Offset curve | `offset` | (distance,) click the side; on the selection, in the construction plane |
| Fillet curves | `fillet`, `filletcorners` | radius; two selected curves (arc + both trimmed) or one curve (all corners) |
| Chamfer curves | `cha`, `chamfercorners` | distance; two selected curves (cut + both trimmed) or one curve (all corners) |
| Blend curves | `blend` | two selected curves; Enter: the closest ends, or click near an end of each; typed 1 / 2: G1 / G2 (default) |
| Tween curves | `tween` | two selected curves; number of curves (Enter: 1); the second turned round if it runs the other way |
| Plane | `plane` | two corners in the construction plane |
| Extrude | `ext` | selected curves; a typed distance along the normal of the view's construction plane (Top / Perspective: +Z, Front: −Y, Left: −X; negative: the other way), or two points |
| Revolve | `rev` | selected curves; axis start, axis end, angle (Enter: 360°) |
| Loft | `loft` | ≥ 2 selected sections, in selection order |
| Sweep 1 / 2 rails | `sweep1` / `sweep2` | selected: profile, then rail(s) |
| Coons | `coons` | four selected boundary curves (orientation is corrected) |
| Gordon | `network` | a selected curve network (≥ 2 × 2, any order: sorted automatically) |
| Offset surface | `offsetsrf` | selected (untrimmed) surfaces; signed distance along the normal |
| Fillet surfaces | `filletsrf` | two selected surfaces; radius (the ball side is found automatically) |
| Surface from points | `srfpt` | 3 or 4 corners (Enter after 3: a triangle) |
| Edge surface | `edgesrf` | 2 / 3 / 4 selected edge curves, any order and direction: ruled / three-sided / Coons |
| Planar surface | `planarsrf` | selected closed planar curves; nested curves are holes |
| Patch | `patch` | selected curves and points; smoothing (Enter: 0.001); fitted surface |
| Surface from point grid | `srfptgrid`, `frompointgrid` | selected points row by row; points per row; interpolating |
| Rail revolve | `railrevolve` | profile, rail; axis start, axis end |
| Extrude along / to point / tapered | `extrudealong` / `extrudetopoint` / `extrudetapered` | profile + path / curves + apex / planar curves, draft angle (Enter: 5°), height |
| Extrude surface | `extrudesrf` | selected surfaces; distance along the plane normal or two points; a solid |
| Pipe | `pipe` | selected curves; start radius, end radius (Enter: the same); solids |
| Drape | `drape` | selected surfaces / solids; (grid, default 20,) two corners; from above along the plane normal |
| Heightfield | `heightfield` | an image file (dialog), two corners, height of white |
| Developable loft | `devloft` | two selected curves; rulings between points with coplanar tangents |
| Blend surface / Match surface | `blendsrf` / `matchsrf` | two surfaces; (0 / 1 / 2: continuity, default 2,) click near the edge of each; a new surface / the first changed |
| Merge surfaces | `mergesrf` | two untrimmed surfaces sharing an edge: one surface |
| Connect surfaces | `connectsrf` | two untrimmed surfaces: extended at their facing edges and trimmed at their intersection |
| Tween surfaces | `tweensrf` | two surfaces; number (Enter: 1) |
| Fillet / Chamfer edges | `filletedge`, `blendedge` / `chamferedge`, `bevel` | picked edges of one solid (Ctrl+Shift-click); radius / distance |
| Variable fillet | `variableblend` | picked edges; points on them, each followed by its radius; Enter: apply |
| Merge faces | `merge` | selected solids: faces that continue each other merged |
| Ellipsoid / Paraboloid | `ellipsoid` / `paraboloid` | centre, first axis end, 2nd and 3rd semi-axis / vertex, focus, rim radius; exact |

| **Editing and analysis** (M6c) | | |
| Join | `j` | selected curves (chained in any order / direction) or surfaces / faces (sewn into one shell) |
| Explode | `x` | shells into faces, curves at their kinks |
| Cap | `cap` | closes planar open loops of the selected surfaces with trimmed planes (extrusion → solid) |
| Split | `split` | one curve: click the split point; a surface and a cutting surface: immediately |
| Trim | `tr` | first selected curve / surface, then the cutting objects; click the part to remove |
| Intersect | `intersect` | intersection points / curves of the selected curves and surfaces |
| Area | `area` | total area and length of the selection |
| Volume | `volume` | volume and centroid of the selected closed solids |
| Curvature | `curv` | one selected curve (curvature, radius) or surface (k1, k2, Gaussian, mean); click a point |

Selection-based commands use the whole selected objects in selection order; each result –
including a Boolean that removes its inputs – is one undo step.

## Export (M6a)

File → Export STEP / Export STL writes the selected objects (or all visible ones if nothing is
selected). STEP: solids and surfaces, exact (AP214, mm). STL: binary, from the display
tessellation.

## Keyboard input

| Typed | Meaning |
|---|---|
| `x,y,z` | absolute world coordinates |
| `x,y` | coordinates in the construction plane of the view (Front: x, z; Left: −y, z; Top / Perspective: x, y) |
| `@dx,dy,dz` / `@dx,dy` | relative to the last point (world / construction plane) |
| `d<a` / `@d<a` | polar in the construction plane (angle in degrees from its u axis), absolute / relative |
| number | what the prompt asks for (radius, sides, turns); otherwise a length from the last point towards the cursor |
| name | starts a command |
| Enter on an empty line, right-click in a view | finishes the command, or repeats the last one (a right *drag* only orbits / pans) |
| Esc | cancels |

The construction plane for typed input is that of the view the cursor was last over while the
command runs; before that, the active view's (the view clicked last).

## Errors

Input a command cannot use leaves it running and the status bar says why, e.g. "Fillet: radius 5
too large for these curves", "Offset curve: the curve has corners – …", "Split: the point is at
an end of the curve", "Trim: the cutting objects do not cross the curve", "Revolve: the angle
must be between -360 and 360 degrees and not 0". Only input without a specific reason shows
"Input not accepted – <prompt>".

Decimal point `.`; coordinates are separated by `,`.

## Modifiers while picking points

- Object snaps as in [snapping.md](snapping.md): F3 on/off, Tab cycles, Alt suppresses.
- **Ortho (F8)**: without a snap, the point is moved onto the construction-plane axis through the
  last point that is closest to the cursor direction. Snapped points are not changed.

## Architecture

`commands/` (no widgets): `Command` state machines and the `parse_input` parser – unit tested
without a window. `app/CommandController` connects them to the viewports (clicked and snapped
points, rubber band), the command line, ortho and the undo stack. Commands build geometry
with the Nurbforge constructors (`make_line`, `make_circle`, `make_arc_3pt`, `make_polygon`,
`make_helix`, …).

Not yet: user-defined construction planes (each view has the plane of its standard view),
options inside commands (e.g. arc by centre), surface and solid commands (M6).
