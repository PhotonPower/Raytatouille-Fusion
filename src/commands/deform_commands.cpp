// Solid operations and deformations (docs/commands.md, "Solids" and "Deform"): Boolean split, Shell;
// Bend, Twist, Taper, Shear, Stretch, Maelstrom. The deformations map the control points of the
// selected objects (kernel::morphed): exact for Shear and Stretch, refined first for the others.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <exception>
#include <functional>
#include <numbers>
#include <nurbforge/topology/solid_ops.hpp>

#include "commands/command_util.hpp"
#include "kernel/geometry_ops.hpp"

namespace nfcad::commands {

namespace {

using namespace util;
using Map = std::function<nf::Vec3(const nf::Vec3&)>;

constexpr double kDeg = std::numbers::pi / 180.0;

/// Rotation of p about the axis through `o` with unit direction `a` by `angle` (Rodrigues).
nf::Vec3 rotated(const nf::Vec3& p, const nf::Vec3& o, const nf::Vec3& a, double angle) {
  const nf::Vec3 r = p - o;
  const double c = std::cos(angle), s = std::sin(angle);
  return o + r * c + nf::cross(a, r) * s + a * (nf::dot(a, r) * (1 - c));
}

// ------------------------------------------------------------------------------ Boolean split
/// Boolean split: the first selected solid split by the others into the part outside them and
/// the part inside them; the cutters stay.
class BooleanSplitCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("booleansplit"); }
  QString title() const override { return QObject::tr("Boolean split"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    std::vector<nf::Shell> shells;
    const document::Entity* first = nullptr;
    for (const document::Entity& e : selection) {
      if (const auto* s = std::get_if<nf::Shell>(e.geometry.get())) {
        if (first == nullptr) first = &e;
        shells.push_back(*s);
      }
    }
    if (shells.size() < 2) {
      message_ = QObject::tr("Boolean split: select the solid to split first, then the cutting solids");
      return false;
    }
    try {
      std::vector<nf::Shell> cutters(shells.begin() + 1, shells.end());
      const nf::Shell cutter = cutters.size() == 1 ? cutters.front() : kernel::boolean(cutters, kernel::BooleanOp::Union);
      for (const auto op : {kernel::BooleanOp::Difference, kernel::BooleanOp::Intersection}) {
        document::Entity part = document::make_entity(kernel::boolean({shells.front(), cutter}, op));
        part.layer = first->layer;
        part.color = first->color;
        entities_.push_back(std::move(part));
      }
      remove_.push_back(first->id);
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return false;
    }
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }
};

// ------------------------------------------------------------------------------ Shell
/// Shell: the picked faces of a closed solid (Ctrl+Shift-click) are removed and the rest is
/// given the typed wall thickness inwards – a cup open at those faces.
class ShellCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("shell"); }
  QString title() const override { return QObject::tr("Shell"); }
  QString prompt() const override { return QObject::tr("Shell: wall thickness"); }
  bool usesSelection() const override { return true; }
  bool usesFaces() const override { return true; }
  bool begin(const std::vector<document::Entity>&) override {
    if (picked_faces_.size() != 1 || !std::get<nf::Shell>(*picked_faces_.front().geometry).is_closed()) {
      message_ = QObject::tr("Shell: pick the faces to open of one closed solid (Ctrl+Shift-click)");
      return false;
    }
    return true;
  }
  Result number(double t) override {
    if (t <= 0) return Result::Rejected;
    try {
      const auto& shell = std::get<nf::Shell>(*picked_faces_.front().geometry);
      const auto& open = picked_faces_.front().indices;
      std::vector<nf::TrimmedSurface> faces;
      for (std::size_t i = 0; i < shell.faces().size(); ++i) {
        const bool opened = std::find(open.begin(), open.end(), static_cast<int>(i)) != open.end();
        faces.push_back(opened ? shell.faces()[i].with_label("nfcad.shell.open") : shell.faces()[i]);
      }
      const nf::Shell labelled = nf::Shell::sew(faces, 1e-6).oriented();
      replace_.emplace_back(picked_faces_.front().id, std::make_shared<const document::Geometry>(
                                                          nf::hollow(labelled, t, {"nfcad.shell.open"})));
      select_ = std::vector<document::SelectionItem>{};
      return Result::Done;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
};

// ------------------------------------------------------------------------------ deformations
/// Base of the deformations: the selected objects, their wireframe for the preview, and the
/// replacement of their geometry by the deformed one.
class DeformCommand : public Command {
 public:
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    selection_ = selection;
    if (selection_.empty()) {
      message_ = QObject::tr("%1: select objects first").arg(title());
      return false;
    }
    for (const document::Entity& e : selection_) {
      for (auto& pl : kernel::wire(*e.geometry, 3000 / selection_.size() + 8)) wire_.push_back(std::move(pl));
    }
    return true;
  }

 protected:
  /// The selection deformed by `map` (affine: exact, without refinement).
  Result apply(const Map& map, bool affine) {
    try {
      for (const document::Entity& e : selection_) {
        replace_.emplace_back(e.id, std::make_shared<const document::Geometry>(kernel::morphed(*e.geometry, map, !affine)));
      }
      return Result::Done;
    } catch (const std::exception& ex) {
      replace_.clear();
      message_ = failure(title(), ex);
      return Result::Rejected;
    }
  }
  /// The wireframe under `map` (preview).
  std::vector<Polyline3> wireUnder(const Map& map) const {
    std::vector<Polyline3> out;
    for (const auto& pl : wire_) {
      Polyline3 q;
      for (const nf::Vec3& p : pl) q.push_back(P(map(p)));
      out.push_back(std::move(q));
    }
    return out;
  }
  std::vector<document::Entity> selection_;
  std::vector<std::vector<nf::Vec3>> wire_;
};

/// An axis (two points) and a value: Twist (total angle, degrees), Taper (scale at the axis end),
/// Bend (a point on the side to bend to, then the angle in degrees).
class AxisDeformCommand : public DeformCommand {
 public:
  enum class Kind { Twist, Taper, Bend };
  explicit AxisDeformCommand(Kind kind) : kind_(kind) {}
  QString id() const override {
    switch (kind_) {
      case Kind::Twist: return QStringLiteral("twist");
      case Kind::Taper: return QStringLiteral("taper");
      case Kind::Bend: break;
    }
    return QStringLiteral("bend");
  }
  QString title() const override {
    switch (kind_) {
      case Kind::Twist: return QObject::tr("Twist");
      case Kind::Taper: return QObject::tr("Taper");
      case Kind::Bend: break;
    }
    return QObject::tr("Bend");
  }
  QString prompt() const override {
    if (!a_) return QObject::tr("%1: start of the axis").arg(title());
    if (!b_) return QObject::tr("%1: end of the axis").arg(title());
    switch (kind_) {
      case Kind::Twist: return QObject::tr("Twist: angle at the axis end in degrees");
      case Kind::Taper: return QObject::tr("Taper: scale at the axis end (1 at the start)");
      case Kind::Bend: break;
    }
    return side_ ? QObject::tr("Bend: angle in degrees") : QObject::tr("Bend: a point on the side to bend to");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!a_) {
      a_ = V(p);
      return Result::Continue;
    }
    if (!b_) {
      if (nf::distance(*a_, V(p)) < kEps) return Result::Rejected;
      b_ = V(p);
      return Result::Continue;
    }
    if (kind_ == Kind::Bend && !side_) {
      const nf::Vec3 ax = axis();
      const nf::Vec3 d = V(p) - *a_;
      const nf::Vec3 n = d - ax * nf::dot(d, ax);
      if (nf::norm(n) < kEps) return Result::Rejected;
      side_ = nf::normalized(n);
      return Result::Continue;
    }
    return Result::Rejected;
  }
  Result number(double v) override {
    if (!b_ || (kind_ == Kind::Bend && !side_)) return Result::Rejected;
    if (kind_ == Kind::Taper && v <= 0) return Result::Rejected;
    if (kind_ == Kind::Bend && (v == 0 || std::abs(v) >= 360)) return Result::Rejected;
    return apply(map(v), false);
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (a_ && !b_) return {{P(*a_), c}};
    if (b_) return {{P(*a_), P(*b_)}};
    return {};
  }
  std::optional<Point3> basePoint() const override {
    return b_ ? std::optional(P(*b_)) : a_ ? std::optional(P(*a_)) : std::nullopt;
  }

  /// The point map of this deformation with value v.
  Map map(double v) const {
    const nf::Vec3 o = *a_, ax = axis();
    const double length = nf::distance(*a_, *b_);
    switch (kind_) {
      case Kind::Twist:
        return [=](const nf::Vec3& p) {
          const double t = std::clamp(nf::dot(p - o, ax) / length, 0.0, 1.0);
          return rotated(p, o, ax, v * kDeg * t);
        };
      case Kind::Taper:
        return [=](const nf::Vec3& p) {
          const double s = nf::dot(p - o, ax);
          const double t = std::clamp(s / length, 0.0, 1.0);
          const nf::Vec3 on = o + ax * s;
          return on + (p - on) * (1.0 + (v - 1.0) * t);
        };
      case Kind::Bend: break;
    }
    // Bend: the axis from the start to the end becomes an arc of the given angle towards the side;
    // beyond the end the objects continue straight along the arc's end tangent
    const nf::Vec3 n = *side_, b = nf::cross(ax, n);
    const double theta = v * kDeg, radius = length / theta;
    return [=](const nf::Vec3& p) {
      const nf::Vec3 r = p - o;
      const double s = nf::dot(r, ax), h = nf::dot(r, n), w = nf::dot(r, b);
      if (s <= 0) return p;
      const double phi = std::min(s, length) / radius;
      nf::Vec3 q = o + ax * ((radius - h) * std::sin(phi)) + n * (radius - (radius - h) * std::cos(phi)) + b * w;
      if (s > length) q = q + (ax * std::cos(theta) + n * std::sin(theta)) * (s - length);
      return q;
    };
  }

 private:
  nf::Vec3 axis() const { return nf::normalized(*b_ - *a_); }
  Kind kind_;
  std::optional<nf::Vec3> a_, b_, side_;
};

/// Shear: base point, a point giving the shear direction (in the construction plane), then the
/// angle in degrees – points move along the direction in proportion to their distance across it.
/// Stretch: axis start, axis end, then the new end (or a factor): one-directional scaling.
class AffineDeformCommand : public DeformCommand {
 public:
  explicit AffineDeformCommand(bool shear) : shear_(shear) {}
  QString id() const override { return shear_ ? QStringLiteral("shear") : QStringLiteral("stretch"); }
  QString title() const override { return shear_ ? QObject::tr("Shear") : QObject::tr("Stretch"); }
  QString prompt() const override {
    if (!o_) return shear_ ? QObject::tr("Shear: base point") : QObject::tr("Stretch: start of the axis");
    if (!r_) return shear_ ? QObject::tr("Shear: reference point (the shear direction)") : QObject::tr("Stretch: end of the axis");
    return shear_ ? QObject::tr("Shear: angle in degrees") : QObject::tr("Stretch: new end (point or factor)");
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!o_) {
      o_ = V(p);
      plane_ = plane;
      return Result::Continue;
    }
    if (!r_) {
      const nf::Vec3 d = shear_ ? in_plane(p, P(*o_), plane_) : V(p) - *o_;
      if (nf::norm(d) < kEps) return Result::Rejected;
      r_ = V(p);
      return Result::Continue;
    }
    if (shear_) return Result::Rejected;
    return apply(map(nf::dot(V(p) - *o_, dir()) / nf::distance(*o_, *r_)), true);
  }
  Result number(double v) override {
    if (!r_) return Result::Rejected;
    if (shear_ && std::abs(v) >= 89) return Result::Rejected;
    if (!shear_ && v == 0) return Result::Rejected;
    return apply(map(v), true);
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (o_ && !r_) return {{P(*o_), c}};
    if (!r_) return {};
    if (shear_) return {{P(*o_), P(*r_)}};
    auto out = wireUnder(map(nf::dot(V(c) - *o_, dir()) / nf::distance(*o_, *r_)));
    out.push_back({P(*o_), c});
    return out;
  }
  std::optional<Point3> basePoint() const override { return o_ ? std::optional(P(*o_)) : std::nullopt; }

  Map map(double v) const {
    const nf::Vec3 o = *o_, d = dir();
    if (!shear_) return [=](const nf::Vec3& p) { return p + d * ((v - 1.0) * nf::dot(p - o, d)); };
    const nf::Vec3 e = nf::normalized(nf::cross(V(plane_.n), d));
    const double k = std::tan(v * kDeg);
    return [=](const nf::Vec3& p) { return p + d * (k * nf::dot(p - o, e)); };
  }

 private:
  nf::Vec3 dir() const {
    const nf::Vec3 d = shear_ ? in_plane(P(*r_), P(*o_), plane_) : *r_ - *o_;
    return nf::normalized(d);
  }
  bool shear_;
  std::optional<nf::Vec3> o_, r_;
  PlaneFrame plane_;
};

/// Maelstrom: a whirl about a centre in the construction plane – rotation by the typed angle at
/// the centre, decreasing to none at the radius.
class MaelstromCommand : public DeformCommand {
 public:
  QString id() const override { return QStringLiteral("maelstrom"); }
  QString title() const override { return QObject::tr("Maelstrom"); }
  QString prompt() const override {
    if (!o_) return QObject::tr("Maelstrom: centre");
    if (!radius_) return QObject::tr("Maelstrom: radius (point or number)");
    return QObject::tr("Maelstrom: angle at the centre in degrees");
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!o_) {
      o_ = V(p);
      plane_ = plane;
      return Result::Continue;
    }
    if (radius_) return Result::Rejected;
    const double r = nf::norm(in_plane(p, P(*o_), plane_));
    if (r < kEps) return Result::Rejected;
    radius_ = r;
    return Result::Continue;
  }
  Result number(double v) override {
    if (!o_) return Result::Rejected;
    if (!radius_) {
      if (v <= 0) return Result::Rejected;
      radius_ = v;
      return Result::Continue;
    }
    return v == 0 ? Result::Rejected : apply(map(v), false);
  }
  std::optional<Point3> basePoint() const override { return o_ ? std::optional(P(*o_)) : std::nullopt; }

  Map map(double v) const {
    const nf::Vec3 o = *o_, n = V(plane_.n);
    const double big = *radius_;
    return [=](const nf::Vec3& p) {
      const nf::Vec3 r = p - o;
      const double dist = nf::norm(r - n * nf::dot(r, n));
      if (dist >= big) return p;
      return rotated(p, o, n, v * kDeg * (1.0 - dist / big));
    };
  }

 private:
  std::optional<nf::Vec3> o_;
  std::optional<double> radius_;
  PlaneFrame plane_;
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"booleansplit", {"bs"}, [] { return std::make_unique<BooleanSplitCommand>(); }},
      {"shell", {}, [] { return std::make_unique<ShellCommand>(); }},
      {"bend", {}, [] { return std::make_unique<AxisDeformCommand>(AxisDeformCommand::Kind::Bend); }},
      {"twist", {}, [] { return std::make_unique<AxisDeformCommand>(AxisDeformCommand::Kind::Twist); }},
      {"taper", {}, [] { return std::make_unique<AxisDeformCommand>(AxisDeformCommand::Kind::Taper); }},
      {"shear", {}, [] { return std::make_unique<AffineDeformCommand>(true); }},
      {"stretch", {}, [] { return std::make_unique<AffineDeformCommand>(false); }},
      {"maelstrom", {}, [] { return std::make_unique<MaelstromCommand>(); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_deform_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList deform_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
