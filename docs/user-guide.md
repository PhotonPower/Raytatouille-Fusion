# User guide

Raytatouille Fusion is a CAD front end for the NURBS kernel
[Nurbforge](https://github.com/PhotonPower/Nurbforge) and the computation kernels built on it,
such as the ray tracer [Raytatouille](https://github.com/PhotonPower/Raytatouille). You model
or import geometry, run a kernel through a plugin and see its results on the model: rays as
lines, fields and images on faces, curves in a plot.

![Main window, shaded](images/main-window-shaded.png)

## Installing

| System | Package | Notes |
|---|---|---|
| macOS 14 or newer (Apple Silicon and Intel) | `RaytatouilleFusion-<version>-macos-universal.dmg` | The app is **not signed**: the first time, open it with right-click → *Open* (or allow it in *System Settings → Privacy & Security*). |
| Windows 11 | `RaytatouilleFusion-<version>-win64-setup.exe` | Installs per machine; updates replace older versions. |
| AlmaLinux / RHEL 10 | `raytatouille-fusion-<version>.x86_64.rpm` | `sudo dnf install ./raytatouille-fusion-*.rpm` (Qt from the distribution). |

Plugins run in **your** Python environment (3.10 or newer, with numpy and the kernel packages),
see [Plugins](#plugins). The plugins of the project (Raytracer, Workflow, FourierGrating, Path
Tracer, Automotive Lighting) are installed with the application.

**First start** – install Python once (Windows: [python.org](https://www.python.org/downloads/),
tick *Add python.exe to PATH*; macOS: python.org or Homebrew; RHEL: `dnf install python3.12`),
then *Plugins → Settings… → Create environment…*: it makes a venv and installs numpy and the
kernel packages from PyPI (raytatouille, rtt-fusion, photonpower-fieldtracing, fouriergrating,
pathtracer, with prebuilt wheels for Windows, Linux and macOS). Confirm with OK; *Check
environment* should then show only ✓.

## The main window

- **Tool column** (left): commands in collapsible groups – Draw, Curves, Surfaces, Solids,
  Transform, Edit, Analyze, and one group per plugin. Hover for the name and what to type to
  start the tool from the keyboard (e.g. "Type: l + Enter").
- **Four views** (centre): Front (XZ), Left (YZ), Top (XY) and Perspective. The header of each
  view switches its display mode; **Space** maximises the view under the cursor and back.
- **Display modes** (toolbar): *Wireframe*, *Surfaces* (flat, with edges) and *Shaded*.
- **Hide / Unhide** (toolbar, also *Edit* menu): *Hide* (H) hides the selected objects and
  deselects them; *Unhide* (Shift + H) shows every object hidden with Hide or Isolate again –
  layers and the model tree's check boxes keep their state (*Show all* switches those on too).
- **Docks** (right): *Properties* of the selection (also free attributes), *Layers* (see
  [Layers](#layers)), *Model* tree (groups with visibility check boxes, double-click a group to
  rename it; right-click: group, hide, isolate, unhide, show all),
  *Results* of computations, *Plugin* (parameters and actions); *Plot* appears at the bottom
  with the first curve. Every dock can be moved, tabbed or hidden (*View* menu).
- **Command line** (bottom): type a command or coordinates; the prompt says what is expected.
- **Status bar**: coordinates, messages, *Ortho* and the snap toggles.

![Wireframe](images/main-window-wireframe.png)

### Navigating

| Action | Mouse / keys |
|---|---|
| Orbit (perspective view) | right drag, or Alt + left drag |
| Pan | middle drag, Shift + right drag; trackpad: two-finger scroll |
| Zoom at the cursor | mouse wheel; trackpad: pinch or Cmd/Ctrl + scroll |
| Zoom extents | toolbar *Zoom extents*, **Z, E** or double-click with the middle button (active view); Shift + toolbar: all views |
| Maximise / restore a view | **Space** |

### Selecting

Click an object to select it (click into empty space clears), **Shift**-click adds,
**Cmd/Ctrl**-click removes, **Cmd/Ctrl + Shift**-click toggles a single face, edge or vertex.
Dragging a rectangle from left to right selects objects completely inside it, from right to
left also those touching it. The object under the cursor is highlighted in cyan, the selection
in yellow. **Esc** clears the selection (or first cancels the running command or plugin job).

## Drawing and modelling

Start a command from the tool column or by typing its name or alias + Enter (typing in a view
goes to the command line; **H** there hides the selection, with nothing selected it is just a
letter, e.g. for Helix `h`). Input:

- **Points** with the mouse (with object snaps) or typed: `x,y,z`, `x,y` (in the construction
  plane), `@dx,dy,dz` relative to the last point, `d<a` as distance and angle.
- **Numbers** where a length, radius or count is expected. A typed Extrude distance goes along
  the normal of the view's construction plane (Front: −Y, Left: −X, Top: +Z).
- **Enter** or right-click (without dragging) finishes (e.g. a polyline); Enter with an empty
  command line or a right-click in a view with no running command repeats the last command.
  **F8** toggles *Ortho* (horizontal / vertical in the construction plane).
- If an input cannot be used, the status bar says why (e.g. "Fillet: radius 5 too large for
  these curves") and the command keeps waiting.

All commands with their input: [commands.md](commands.md). Every command is one undo step.

### Layers

The *Layers* dock lists the layers: the check box shows or hides a layer, *Lock* locks it, a
double-click on the name renames it, a double-click on the swatch changes its colour; the
right-click menu has all of it.

- **Current layer** (bold): new objects go there – drawn, imported with *Import STEP…*, made by
  plugins. Highlight a layer and click *Make current*. A new document starts on *Default*; the
  current layer is saved with the document.
- **Locked**: the objects stay visible (and snap points on them still work), but they cannot be
  selected – neither by clicking nor with a window, *Select All* or the model tree – and so not
  moved, edited or deleted. Locking a layer deselects its objects.
- **Delete layer…**: if the layer holds objects, you choose whether they move to *Default* or are
  deleted with it. *Default* cannot be deleted.
- *Move selection here* puts the selected objects on the highlighted layer.

New, renamed, recoloured and deleted layers – like renamed groups and moving objects to a layer –
are undo steps. Showing, hiding and locking (layers, groups, objects with *Hide*, *Isolate*,
*Unhide* and the check boxes), and the current layer, are not, but they are saved with the
document: the title bar marks it modified and closing asks to save.

### Object snaps

The cursor snaps to points, ends, midpoints, centres, quadrants (where the axes of the
construction plane pierce circles), intersections, face corners and edges, and "near" any
curve. Every corner of a polyline, rectangle or polygon counts as an end and every segment has a
midpoint; the start of a polyline being drawn snaps too, which closes it. A glyph shows the type:

![Snap glyphs](images/snap-glyphs.png)

**Tab** cycles through all candidates under the cursor, **Alt** suppresses snapping while
held, **F3** switches all snaps off and on; each type has its own toggle in the status bar.
Details: [snapping.md](snapping.md).

## Files

| Format | Read | Write | Notes |
|---|---|---|---|
| `.rttf` (also `.nfcad` from before 1.0) | ✓ | ✓ | the document: exact geometry, layers, groups, attributes, plugin parameters ([format](file-format.md)) |
| STEP | ✓ | ✓ (AP214) | opening replaces the document, *File → Import STEP…* adds to it; *File → Export STEP…* writes solids and surfaces exactly |
| STL | | ✓ | *File → Export STL…*: binary, from the display tessellation |
| `.nfplugin` | ✓ | | a plugin package: opening it installs the plugin ([Plugins](#plugins)) |

*File → Open…* takes all of them (the filter *All supported*, or one type). *File → Open Recent*
lists the last ten documents and STEP files opened or saved; *Clear list* empties it. A
double-click on a `.rttf`, `.nfcad`, STEP or `.nfplugin` file opens it in the application:
macOS (Finder; the application declares the types, *Open With* shows it for STEP), Linux (the
desktop file and the MIME types `application/x-raytatouille-fusion` and
`application/x-raytatouille-fusion-plugin` installed with the package), or on any system as the
argument on the command line. If the open document has unsaved changes you are asked first.

Example models are in [`examples/`](../examples/README.md).

## Plugins

Plugins connect computation kernels: they add a group to the tool column and a page to the
**Plugin** dock with their parameters and actions. Results appear in the *Results* dock (rays,
fields on faces) and the *Plot* dock; everything a plugin run changes in the model is **one
undo step**.

![Raytracer plugin](images/raytracer.png)

**Setting up** (*Plugins → Settings…*):

1. **Python interpreter** – an environment with the kernel's packages. *Check environment*
   shows what the installed plugins need and what is missing (with the `pip` command);
   *Create environment…* makes a new venv.
2. **Installing plugins** – *Plugins → Install plugin…* with a `.nfplugin` file, or open the
   file with the application. *Plugins → Uninstall plugin* removes it.
   *Plugins → Show in the side panels* keeps a plugin out of the tool column and the Plugin
   panel (check box per plugin, remembered); its actions stay in the *Plugins* menu.
3. **Signatures** – only plugins signed by the publisher whose key is built into the
   application are loaded, and the plugins installed with the application (they are part of
   it, in its write-protected folder). A plugin folder of your own with the same plugin id
   replaces the installed one. *Developer mode* also loads unsigned plugins (for plugin
   developers); a red banner in the status bar shows that it is on.

![Plugin settings](images/plugin-settings.png)

Images (e.g. a camera image of the Raytracer) appear in the **Image** window: physical axes,
colour bar, *log* for a logarithmic scale, the value under the cursor below the image; the
mouse wheel zooms at the cursor, dragging pans, a double-click shows the whole image.

The **Raytracer** plugin (Raytatouille) loads `.rtt.json` optical systems, traces rays, shows
the irradiance on the image surface and optimises with live updates – see its
[guide](../python/plugins/raytracer/README.md).

The **Path Tracer** plugin computes light transport on the CAD model itself: objects become
light sources, the others get materials (diffuse, mirror, glossy, glass, absorber); it shows the
irradiance as a texture on the faces and a camera image, by light tracing, path tracing or
bidirectional path tracing – see its [guide](../python/plugins/pathtracer/README.md). With the package
[pathtracer](https://github.com/PhotonPower/PathTracer) installed in the plugin's Python it computes
in C++ on all processor cores.

Editing the **node workflow** (moving a block, connecting, deleting, parameters, groups …) is
one undo step per edit – dragging a block counts once, when you let go; a plugin run that
changes the workflow is undone as a whole.

Writing your own plugins: [plugin-api.md](plugin-api.md).

## Updates, crashes, settings

- *Help → Check for updates…* compares with the latest release and with the plugins' update
  information – only when you choose it.
- If the application crashes, it writes a **crash report on this computer** (nothing is sent)
  and points to it at the next start; attach it when you report the problem on
  [GitHub](https://github.com/PhotonPower/Raytatouille-Fusion/issues).
- Settings (window layout, tool column, snaps, plugin settings) are kept across updates;
  those of the former *Nurbforge CAD* are taken over once.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl/Cmd + N, O, S, Shift + S | new, open, save, save as (recent documents: *File → Open Recent*) |
| Ctrl/Cmd + I | import STEP |
| Ctrl/Cmd + Z, Shift + Ctrl/Cmd + Z | undo, redo |
| Ctrl/Cmd + A | select all |
| Delete / Backspace | delete the selection |
| Ctrl/Cmd + G, Shift + Ctrl/Cmd + G | group, ungroup |
| H, Shift + H | hide the selection (with nothing selected, H in a view is typed into the command line), unhide (show what Hide and Isolate hid) |
| Esc | cancel the command / plugin job, else clear the selection |
| Enter, right-click | finish the command; on an empty command line / with no running command: repeat the last one |
| Space | maximise / restore the view under the cursor |
| Z, E | zoom extents (active view) |
| F3 | object snaps on / off |
| F8 | ortho on / off |
| Tab / Shift + Tab | next / previous snap candidate |
| Alt (held) | no snapping |
| letters + Enter | a command by its name or alias, e.g. `l` line, `c` circle, `m` move (the tooltips of the tool column name them) |
