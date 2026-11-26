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
       {t("plane", "Plane", "Pln", "plane"), t("extrude", "Extrude", "Ext", "ext"),
        t("revolve", "Revolve", "Rev", "rev"), t("loft", "Loft", "Lft", "loft"),
        t("sweep1", "Sweep 1 rail", "Sw1", "sweep1"), t("sweep2", "Sweep 2 rails", "Sw2", "sweep2"),
        t("coons", "Coons patch", "Cns", "coons"), t("gordon", "Gordon surface", "Gor", "gordon"),
        t("offset_surface", "Offset surface", "OfS", "offsetsrf"),
        t("fillet_surface", "Fillet surfaces", "FiS", "filletsrf"),
        t("cap", "Cap planar holes", "Cap", "cap")}},
      {"solids", "Solids", false,
       {t("box", "Box", "Box", "b"), t("sphere", "Sphere", "Sph", "sph"),
        t("cylinder", "Cylinder", "Cyl", "cyl"), t("cone", "Cone", "Con", "cone"),
        t("torus", "Torus", "Tor", "tor"), t("union", "Boolean union", "∪", "bu"),
        t("difference", "Boolean difference", "−", "bd"),
        t("intersection", "Boolean intersection", "∩", "bi")}},
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
