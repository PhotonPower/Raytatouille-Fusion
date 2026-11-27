#include "ui/tool_catalog.hpp"

#include <QObject>

namespace nfcad::ui {

namespace {

/// alias: the shortest name of the command to type in the command line (or in a view) + Enter.
ToolDef t(const char* id, const char* label, const char* short_label, const char* alias,
          QKeySequence key = {}) {
  return {QString::fromLatin1(id), QString::fromUtf8(label), QString::fromUtf8(short_label),
          std::move(key), QString::fromLatin1(alias)};
}

std::vector<ToolGroupDef> build() {
  return {
      {"draw", "Draw", true,
       {t("point", "Point", "Pt", "pt"), t("line", "Line", "Ln", "l"),
        t("tangent", "Tangent line", "Tan", "tan"), t("perpendicular", "Perpendicular line", "Prp", "perp"),
        t("polyline", "Polyline", "PL", "pl"), t("rectangle", "Rectangle", "Rec", "rec"),
        t("polygon", "Polygon", "Pol", "pol")}},
      {"curves", "Curves", true,
       {t("circle", "Circle (centre, radius)", "Ci", "c"),
        t("circle3p", "Circle (3 points)", "C3", "c3"), t("arc", "Arc", "Arc", "a"),
        t("ellipse", "Ellipse", "El", "el"), t("helix", "Helix", "Hx", "h"),
        t("spiral", "Spiral", "Spi", "spi"), t("curve", "Curve (control points)", "Crv", "crv"),
        t("spline", "Interpolated curve", "Sp", "sp"), t("sketch", "Sketch (freehand)", "Sk", "sk"),
        t("curve_through_points", "Curve through points", "CtP", "crvpts"),
        t("conic", "Conic", "Cnc", "conic"), t("parabola", "Parabola", "Par", "para"),
        t("hyperbola", "Hyperbola", "Hyp", "hyp"),
        t("offset_curve", "Offset curve", "Off", "offset"),
        t("fillet_curve", "Fillet curves", "Fil", "fillet"),
        t("chamfer", "Chamfer curves", "Cha", "cha"), t("blend", "Blend curves", "Bln", "blend"),
        t("tween", "Tween curves", "Twn", "tween")}},
      {"derive", "Curves from objects", false,
       {t("project", "Project curves", "Prj", "project"), t("pull", "Pull curves", "Pul", "pull"),
        t("section", "Section", "Sec", "section"), t("contour", "Contour", "Ctr", "contour"),
        t("dupedge", "Duplicate edge", "DpE", "dupedge"), t("dupborder", "Duplicate border", "DpB", "dupborder"),
        t("extract_isocurve", "Extract isocurve", "Iso", "iso"),
        t("extract_wireframe", "Extract wireframe", "Wir", "extractwireframe"),
        t("offset_on_surface", "Offset curve on surface", "OCS", "offsetcrvonsrf"),
        t("curve_boolean", "Curve Boolean", "CBo", "crvboolean")}},
      {"surfaces", "Surfaces", false,
       {t("plane", "Plane", "Pln", "plane"), t("srfpt", "Surface from points", "SPt", "srfpt"),
        t("edgesrf", "Edge surface", "Edg", "edgesrf"), t("planarsrf", "Planar surface", "PlS", "planarsrf"),
        t("patch", "Patch", "Pat", "patch"), t("srfptgrid", "Surface from point grid", "Grd", "srfptgrid"), t("extrude", "Extrude", "Ext", "ext"),
        t("revolve", "Revolve", "Rev", "rev"), t("railrevolve", "Rail revolve", "RRv", "railrevolve"),
        t("extrude_along", "Extrude along curve", "ExA", "extrudealong"),
        t("extrude_to_point", "Extrude to point", "ExP", "extrudetopoint"),
        t("extrude_tapered", "Extrude tapered", "ExT", "extrudetapered"),
        t("extrudesrf", "Extrude surface", "ExS", "extrudesrf"), t("pipe", "Pipe", "Pip", "pipe"),
        t("drape", "Drape", "Drp", "drape"), t("heightfield", "Heightfield", "Hgt", "heightfield"),
        t("devloft", "Developable loft", "DLo", "devloft"), t("loft", "Loft", "Lft", "loft"),
        t("sweep1", "Sweep 1 rail", "Sw1", "sweep1"), t("sweep2", "Sweep 2 rails", "Sw2", "sweep2"),
        t("coons", "Coons patch", "Cns", "coons"), t("gordon", "Gordon surface", "Gor", "gordon"),
        t("offset_surface", "Offset surface", "OfS", "offsetsrf"),
        t("fillet_surface", "Fillet surfaces", "FiS", "filletsrf"),
        t("blendsrf", "Blend surface", "BlS", "blendsrf"),
        t("matchsrf", "Match surface", "MaS", "matchsrf"), t("mergesrf", "Merge surfaces", "MgS", "mergesrf"),
        t("connectsrf", "Connect surfaces", "CoS", "connectsrf"), t("tweensrf", "Tween surfaces", "TwS", "tweensrf"),
        t("cap", "Cap planar holes", "Cap", "cap")}},
      {"solids", "Solids", false,
       {t("box", "Box", "Box", "b"), t("sphere", "Sphere", "Sph", "sph"),
        t("cylinder", "Cylinder", "Cyl", "cyl"), t("cone", "Cone", "Con", "cone"),
        t("torus", "Torus", "Tor", "tor"), t("ellipsoid", "Ellipsoid", "Ell", "ellipsoid"),
        t("paraboloid", "Paraboloid", "Prb", "paraboloid"), t("union", "Boolean union", "∪", "bu"),
        t("difference", "Boolean difference", "−", "bd"),
        t("intersection", "Boolean intersection", "∩", "bi"), t("filletedge", "Fillet edges", "FiE", "filletedge"),
        t("chamferedge", "Chamfer edges", "ChE", "chamferedge"),
        t("variableblend", "Variable fillet", "VFi", "variableblend"), t("merge", "Merge faces", "MgF", "merge"),
        t("booleansplit", "Boolean split", "BSp", "booleansplit"), t("shell", "Shell", "Shl", "shell")}},
      {"deform", "Deform", false,
       {t("bend", "Bend", "Bnd", "bend"), t("twist", "Twist", "Twi", "twist"), t("taper", "Taper", "Tap", "taper"),
        t("shear", "Shear", "Shr", "shear"), t("stretch", "Stretch", "Str", "stretch"),
        t("maelstrom", "Maelstrom", "Mae", "maelstrom"), t("flow", "Flow along curve", "Flw", "flow"),
        t("flowalongsrf", "Flow along surface", "FlS", "flowalongsrf"), t("cageedit", "Cage edit", "Cag", "cageedit"),
        t("splop", "Splop", "Spl", "splop"), t("unrollsrf", "Unroll surface", "Unr", "unrollsrf"),
        t("smash", "Smash", "Sma", "smash"), t("squish", "Squish", "Sqi", "squish")}},
      {"transform", "Transform", false,
       {t("move", "Move", "Mv", "m"), t("copy", "Copy", "Cp", "co"),
        t("rotate", "Rotate", "Rot", "ro"), t("scale", "Scale", "Scl", "sc"),
        t("mirror", "Mirror", "Mir", "mi"), t("array_linear", "Linear array", "ArL", "array"),
        t("array_grid", "Grid array", "ArG", "array_grid"),
        t("array_polar", "Polar array", "ArP", "arraypolar")}},
      {"edit", "Edit", false,
       {t("trim", "Trim", "Trm", "tr"), t("split", "Split", "Spl", "split"),
        t("join", "Join", "Jn", "j"), t("explode", "Explode", "Exp", "x"),
        // not a command: the Edit menu's Delete (Del / Backspace)
        t("delete", "Delete", "Del", "", QKeySequence::Delete)}},
      {"surface_edit", "Edit surfaces", false,
       {t("untrim", "Untrim", "Utr", "untrim"), t("extractsrf", "Extract surface", "ExF", "extractsrf"),
        t("shrinktrimmedsrf", "Shrink trimmed surface", "Shr", "shrink"),
        t("extendsrf", "Extend surface", "ExE", "extendsrf"), t("rebuildsrf", "Rebuild surface", "RbS", "rebuildsrf"),
        t("rebuilduv", "Rebuild surface in one direction", "RUV", "rebuilduv"),
        t("changedegreesrf", "Change surface degree", "DgS", "changedegreesrf"), t("slab", "Slab", "Slb", "slab"),
        t("thicken", "Thicken", "Thk", "thicken"), t("makehollow", "Make hollow", "Hol", "makehollow")}},
      {"curve_edit", "Edit curves", false,
       {t("extend", "Extend curve", "Ext", "extendcrv"), t("divide", "Divide", "Div", "divide"),
        t("divide_length", "Divide by length", "DvL", "divlen"), t("rebuild", "Rebuild curve", "Rbd", "rebuild"),
        t("change_degree", "Change degree", "Deg", "changedegree"), t("flip", "Flip direction", "Flp", "flip"),
        t("close", "Close curve", "Cls", "closecrv"), t("seam", "Curve seam", "Sea", "crvseam"),
        t("insert_knot", "Insert knot", "IKn", "insertknot"), t("remove_knot", "Remove knot", "RKn", "removeknot"),
        t("smooth", "Smooth curve", "Smo", "smooth"), t("fair", "Fair curve", "Fai", "fair"),
        t("match", "Match curve", "Mat", "match"), t("simplify", "Simplify curve", "Smp", "simplify"),
        t("arc_blend", "Arc blend", "ABl", "arcblend"), t("points_on", "Points on", "POn", "pon"),
        t("points_off", "Points off", "POf", "poff"), t("select_points", "Select points", "SPt", "selpoints"),
        t("weight", "Weight", "Wgt", "weight"), t("insert_control_point", "Insert control point", "ICP", "insertcp")}},
      {"analyze", "Analyze", false,
       {t("distance", "Distance", "Dst", "di"), t("angle", "Angle", "Ang", "ang"),
        t("curvature", "Curvature", "Crv", "curv"), t("area", "Area", "Are", "area"),
        t("mass_properties", "Volume / mass properties", "Vol", "volume"),
        t("intersection_check", "Intersection check", "Chk", "intersect")}},
  };
}

}  // namespace

const std::vector<ToolGroupDef>& tool_catalog() {
  static const std::vector<ToolGroupDef> catalog = build();
  return catalog;
}

QString tool_tip(const ToolDef& tool) {
  QString tip = tool.label;
  if (!tool.shortcut.isEmpty()) {
    tip += QStringLiteral("  (%1)").arg(tool.shortcut.toString(QKeySequence::NativeText));
  }
  if (!tool.alias.isEmpty()) {
    // not a shortcut: the name to type in the command line (typing in a view goes there too)
    tip += QStringLiteral("\n") + QObject::tr("Type: %1 + Enter").arg(tool.alias);
  }
  return tip;
}

}  // namespace nfcad::ui
