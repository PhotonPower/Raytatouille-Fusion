// Curves seen from the view (docs/commands.md, "Curves from objects"): Silhouette (the curves
// where surfaces turn away from the viewer), Make2D (visible and hidden lines projected into a
// 2D drawing) and Outline (the contour of solids seen along the view). All use the camera of
// the active view: parallel views along their direction, perspective views from their eye.
#include <QColor>
#include <QObject>
#include <algorithm>
#include <cmath>
#include <exception>
#include <functional>
#include <nurbforge/analysis/drawing.hpp>
#include <nurbforge/analysis/silhouette.hpp>

#include "commands/command_util.hpp"
#include "kernel/geometry_ops.hpp"

namespace nfcad::commands {

namespace {

using namespace util;

nf::View view_of(const PlaneFrame& f) {
  return f.eye ? nf::View::perspective(V(*f.eye)) : nf::View::parallel(V(f.view));
}

/// Screen right of the view (s axis of the drawings: the drawing reads as the view shows it).
nf::Vec3 right_of(const PlaneFrame& f) { return nf::cross(V(f.view), V(f.up)); }

/// Largest coordinate magnitude of the control points (scale of the tolerances).
double size_of(const std::vector<nf::Shell>& shells) {
  double size = 1.0;
  for (const nf::Shell& s : shells) {
    for (const nf::TrimmedSurface& f : s.faces()) {
      for (const nf::Vec3& p : f.surface().control_points()) size = std::max(size, nf::norm(p));
    }
  }
  return size;
}

/// Solids and polysurfaces as they are; every surface as a shell of its own.
std::vector<nf::Shell> shells_of(const std::vector<document::Entity>& selection) {
  std::vector<nf::Shell> out;
  for (const document::Entity& e : selection) {
    if (const auto* s = std::get_if<nf::Shell>(e.geometry.get())) {
      out.push_back(*s);
    } else if (std::holds_alternative<nf::NurbsSurface>(*e.geometry) ||
               std::holds_alternative<nf::TrimmedSurface>(*e.geometry)) {
      out.push_back(nf::Shell::sew(kernel::faces_of(*e.geometry)));
    }
  }
  return out;
}

/// Base of the three commands: works on the selected surfaces and solids at once.
class ViewDrawingCommand : public Command {
 public:
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    try {
      shells_ = shells_of(selection);
      if (shells_.empty()) {
        message_ = QObject::tr("%1: select surfaces, polysurfaces or solids").arg(title());
        return false;
      }
      tolerance_ = 1e-6 * size_of(shells_);
      make();
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return false;
    }
    if (entities_.empty()) {
      message_ = QObject::tr("%1: no curves in this view").arg(title());
      return false;
    }
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }

 protected:
  virtual void make() = 0;
  nf::DrawingOptions options(const nf::Vec3& origin) const {
    nf::DrawingOptions o;
    o.tolerance = tolerance_;
    o.s_axis = right_of(viewPlane());
    o.origin = origin;
    return o;
  }
  std::vector<nf::Shell> shells_;
  double tolerance_ = 1e-6;
};

// ------------------------------------------------------------------------------ Silhouette
class SilhouetteCommand : public ViewDrawingCommand {
 public:
  QString id() const override { return QStringLiteral("silhouette"); }
  QString title() const override { return QObject::tr("Silhouette"); }

 protected:
  void make() override {
    nf::SilhouetteOptions o;
    o.tolerance = tolerance_;
    const nf::View view = view_of(viewPlane());
    for (const nf::Shell& s : shells_) {
      for (const nf::SilhouetteCurve& c : nf::silhouette(s, view, o)) {
        entities_.push_back(document::make_entity(c.curve, QObject::tr("Silhouette")));
      }
    }
    message_ = QObject::tr("Silhouette: %n curve(s)", nullptr, static_cast<int>(entities_.size()));
  }
};

// ------------------------------------------------------------------------------ Make2D
/// The drawing lies in the world XY plane, seen as in the view (s to the right, t up): a
/// parallel view projected from the world origin, a perspective view onto the plane through the
/// view's target. Hidden lines are grey.
class Make2DCommand : public ViewDrawingCommand {
 public:
  QString id() const override { return QStringLiteral("make2d"); }
  QString title() const override { return QObject::tr("Make2D"); }

 protected:
  void make() override {
    const PlaneFrame& f = viewPlane();
    const nf::Drawing d = nf::make2d(shells_, view_of(f), options(f.eye ? V(f.target) : nf::Vec3{0, 0, 0}));
    for (const nf::DrawingCurve& c : d.visible) {
      entities_.push_back(document::make_entity(c.curve, QObject::tr("Make2D visible")));
    }
    for (const nf::DrawingCurve& c : d.hidden) {
      document::Entity e = document::make_entity(c.curve, QObject::tr("Make2D hidden"));
      e.color = QColor(150, 150, 150);
      entities_.push_back(std::move(e));
    }
    message_ = QObject::tr("Make2D: %1 visible, %2 hidden lines in the XY plane")
                   .arg(d.visible.size())
                   .arg(d.hidden.size());
  }
};

// ------------------------------------------------------------------------------ Outline
/// Closed contour curves in the plane normal to the view: through the construction plane's
/// origin (parallel views, i.e. in the construction plane of a standard view) or through the
/// view's target (perspective).
class OutlineCommand : public ViewDrawingCommand {
 public:
  QString id() const override { return QStringLiteral("outline"); }
  QString title() const override { return QObject::tr("Outline"); }

 protected:
  void make() override {
    const PlaneFrame& f = viewPlane();
    const nf::Outline out = nf::outline(shells_, view_of(f), options(f.eye ? V(f.target) : V(f.origin)));
    const auto map = [&](const nf::Vec3& p) { return out.origin + p.x * out.s_axis + p.y * out.t_axis; };
    const auto add = [&](const nf::NurbsCurve& c) {
      entities_.push_back(document::make_entity(kernel::morphed(c, map, false), QObject::tr("Outline")));
    };
    for (const std::vector<nf::NurbsCurve>& loop : out.loops) {
      try {
        add(kernel::join_chain(loop, 10 * tolerance_));
      } catch (const std::exception&) {
        for (const nf::NurbsCurve& c : loop) add(c);  // keep the pieces
      }
    }
    message_ = QObject::tr("Outline: %n closed curve(s)", nullptr, static_cast<int>(out.loops.size()));
  }
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"silhouette", {}, [] { return std::make_unique<SilhouetteCommand>(); }},
      {"make2d", {}, [] { return std::make_unique<Make2DCommand>(); }},
      {"outline", {}, [] { return std::make_unique<OutlineCommand>(); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_view_drawing_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList view_drawing_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
