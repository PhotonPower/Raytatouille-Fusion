// Solid operations and deformations (docs/commands.md, "Solids" and "Deform"): Boolean split, Shell;
// Bend, Twist, Taper, Shear, Stretch, Maelstrom, Flow along curve, Flow along surface, Cage edit,
// Splop; Unroll,
// Smash and Squish (flattening surfaces). The deformations map the selected objects with
// kernel::morphed: exact for Shear and Stretch, refined first for the others.
#include <QObject>
#include <algorithm>
#include <array>
#include <cmath>
#include <exception>
#include <functional>
#include <numbers>
#include <nurbforge/analysis/closest_point.hpp>
#include <nurbforge/analysis/properties.hpp>
#include <nurbforge/fitting/fit.hpp>
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

// ------------------------------------------------------------------------------ Flow
/// The objects after the first two selected items: Flow along curve takes a base curve and a
/// target curve first, Flow along surface a base and a target surface.
class FlowCommand : public DeformCommand {
 public:
  explicit FlowCommand(bool surface) : surface_(surface) {}
  QString id() const override { return surface_ ? QStringLiteral("flowalongsrf") : QStringLiteral("flow"); }
  QString title() const override { return surface_ ? QObject::tr("Flow along surface") : QObject::tr("Flow along curve"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    if (selection.size() < 3) {
      message_ = surface_ ? QObject::tr("Flow along surface: select the base surface, the target surface, then the objects")
                          : QObject::tr("Flow along curve: select the base curve, the target curve, then the objects");
      return false;
    }
    if (surface_) {
      const auto a = surface_of(selection[0]), b = surface_of(selection[1]);
      if (!a || !b) {
        message_ = QObject::tr("Flow along surface: the first two selected objects must be surfaces");
        return false;
      }
      base_s_ = *a;
      target_s_ = *b;
    } else {
      const auto* a = std::get_if<nf::NurbsCurve>(selection[0].geometry.get());
      const auto* b = std::get_if<nf::NurbsCurve>(selection[1].geometry.get());
      if (a == nullptr || b == nullptr) {
        message_ = QObject::tr("Flow along curve: the first two selected objects must be curves");
        return false;
      }
      base_c_ = *a;
      target_c_ = *b;
    }
    return DeformCommand::begin({selection.begin() + 2, selection.end()});
  }
  Result finish() override { return apply(surface_ ? surface_map() : curve_map(V(viewPlane().n)), false); }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }

  /// Along curves: a point's arc-length position on the base curve and its offsets in the base
  /// curve's frame (tangent, side = up × tangent, up = the plane normal) carried to the same
  /// relative position on the target curve; offsets beyond the ends run along the end tangents.
  static Map flow_curve(const nf::NurbsCurve& base, const nf::NurbsCurve& target, const nf::Vec3& up) {
    const double lb = nf::arc_length(base), lt = nf::arc_length(target);
    return [=](const nf::Vec3& p) {
      const nf::CurvePoint f = nf::closest_point(base, p);
      const nf::Vec3 tb = nf::normalized(base.tangent(f.u)), sb = nf::normalized(nf::cross(up, tb));
      const nf::Vec3 d = p - f.point;
      const double s = nf::arc_length(base, base.domain_start(), f.u) / lb;
      const double ut = nf::parameter_at_length(target, std::clamp(s, 0.0, 1.0) * lt);
      const nf::Vec3 tt = nf::normalized(target.tangent(ut)), st = nf::normalized(nf::cross(up, tt));
      return target.evaluate(ut) + tt * (nf::dot(d, tb) * lt / lb) + st * nf::dot(d, sb) + up * nf::dot(d, up);
    };
  }

  /// Along surfaces: a point's (u, v) on the base surface (relative to its domain) and its
  /// height along the base normal carried to the target surface.
  static Map flow_surface(const nf::NurbsSurface& base, const nf::NurbsSurface& target) {
    return [=](const nf::Vec3& p) {
      const nf::SurfacePoint f = nf::closest_point(base, p);
      const auto bu = base.domain_u(), bv = base.domain_v(), tu = target.domain_u(), tv = target.domain_v();
      const double h = nf::dot(p - f.point, base.normal(f.u, f.v));
      const double u = tu[0] + (f.u - bu[0]) / (bu[1] - bu[0]) * (tu[1] - tu[0]);
      const double v = tv[0] + (f.v - bv[0]) / (bv[1] - bv[0]) * (tv[1] - tv[0]);
      return target.evaluate(u, v) + target.normal(u, v) * h;
    };
  }

 private:
  static std::optional<nf::NurbsSurface> surface_of(const document::Entity& e) {
    if (const auto* s = std::get_if<nf::NurbsSurface>(e.geometry.get())) return *s;
    if (const auto* f = std::get_if<nf::TrimmedSurface>(e.geometry.get())) return f->surface();
    return std::nullopt;
  }
  Map curve_map(const nf::Vec3& up) const { return flow_curve(*base_c_, *target_c_, up); }
  Map surface_map() const { return flow_surface(*base_s_, *target_s_); }
  bool surface_;
  std::optional<nf::NurbsCurve> base_c_, target_c_;
  std::optional<nf::NurbsSurface> base_s_, target_s_;
};

// ------------------------------------------------------------------------------ Cage edit
/// Cage edit: a lattice of n × n × n points (a Bézier volume) around the selection, aligned with
/// the construction plane. Click a lattice point (they are snap points), then its new place –
/// as often as wanted; Enter deforms the objects with the moved lattice.
class CageEditCommand : public DeformCommand {
 public:
  QString id() const override { return QStringLiteral("cageedit"); }
  QString title() const override { return QObject::tr("Cage edit"); }
  QString prompt() const override {
    if (lattice_.empty()) return QObject::tr("Cage edit: points per direction, 2 … 6 (Enter: 4)");
    if (!picked_) return QObject::tr("Cage edit: a cage point to move (Enter: apply)");
    return QObject::tr("Cage edit: its new place");
  }
  bool begin(const std::vector<document::Entity>& selection) override {
    if (!DeformCommand::begin(selection)) return false;
    plane_ = viewPlane();
    const nf::Vec3 e[3] = {V(plane_.u), V(plane_.v), V(plane_.n)};
    for (int k = 0; k < 3; ++k) {
      lo_[k] = 1e300;
      hi_[k] = -1e300;
    }
    double size = 0;
    for (const auto& pl : wire_) {
      for (const nf::Vec3& q : pl) {
        for (int k = 0; k < 3; ++k) {
          lo_[k] = std::min(lo_[k], nf::dot(q, e[k]));
          hi_[k] = std::max(hi_[k], nf::dot(q, e[k]));
        }
      }
    }
    for (int k = 0; k < 3; ++k) size = std::max(size, hi_[k] - lo_[k]);
    if (size <= 0) size = 1;
    for (int k = 0; k < 3; ++k) {  // a flat direction gets some depth
      if (hi_[k] - lo_[k] < 1e-6 * size) {
        lo_[k] -= 0.05 * size;
        hi_[k] += 0.05 * size;
      }
    }
    return true;
  }
  Result number(double v) override {
    if (!lattice_.empty() || v < 2 || v > 6 || v != std::floor(v)) return Result::Rejected;
    build(static_cast<int>(v));
    return Result::Continue;
  }
  Result finish() override {
    if (lattice_.empty()) {
      build(4);
      return Result::Continue;
    }
    if (!moved_) return Result::Cancelled;
    return apply(map(), false);
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (lattice_.empty()) return Result::Rejected;
    if (!picked_) {
      std::size_t best = 0;
      double d = 1e300;
      for (std::size_t i = 0; i < lattice_.size(); ++i) {
        const double di = nf::distance(lattice_[i], V(p));
        if (di < d) {
          d = di;
          best = i;
        }
      }
      if (d > 1e-6 * extent()) return Result::Rejected;  // not on a cage point (use the snap)
      picked_ = best;
      return Result::Continue;
    }
    lattice_[*picked_] = V(p);
    picked_.reset();
    moved_ = true;
    return Result::Continue;
  }
  std::vector<Point3> snapPoints() const override {
    std::vector<Point3> out;
    for (const nf::Vec3& q : lattice_) out.push_back(P(q));
    return out;
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (lattice_.empty()) return {};
    CageEditCommand* self = const_cast<CageEditCommand*>(this);
    std::optional<nf::Vec3> keep;
    if (picked_) {
      keep = lattice_[*picked_];
      self->lattice_[*picked_] = V(c);
    }
    std::vector<Polyline3> out = moved_ || picked_ ? wireUnder(map()) : std::vector<Polyline3>{};
    for (int a = 0; a < n_; ++a) {  // the lattice lines
      for (int b = 0; b < n_; ++b) {
        Polyline3 l0, l1, l2;
        for (int k = 0; k < n_; ++k) {
          l0.push_back(P(at(k, a, b)));
          l1.push_back(P(at(a, k, b)));
          l2.push_back(P(at(a, b, k)));
        }
        out.push_back(l0);
        out.push_back(l1);
        out.push_back(l2);
      }
    }
    if (keep) self->lattice_[*picked_] = *keep;
    return out;
  }
  std::optional<Point3> basePoint() const override { return picked_ ? std::optional(P(lattice_[*picked_])) : std::nullopt; }

  /// The Bézier volume of the lattice.
  Map map() const {
    const auto pts = lattice_;
    const int n = n_;
    const nf::Vec3 e0 = V(plane_.u), e1 = V(plane_.v), e2 = V(plane_.n);
    const std::array<double, 3> lo = lo_, hi = hi_;
    return [=](const nf::Vec3& p) {
      const double t[3] = {(nf::dot(p, e0) - lo[0]) / (hi[0] - lo[0]), (nf::dot(p, e1) - lo[1]) / (hi[1] - lo[1]),
                           (nf::dot(p, e2) - lo[2]) / (hi[2] - lo[2])};
      std::vector<double> b[3];
      for (int k = 0; k < 3; ++k) {
        b[k].assign(std::size_t(n), 0.0);
        for (int i = 0; i < n; ++i) {
          double binom = 1;
          for (int m = 1; m <= i; ++m) binom = binom * double(n - 1 - i + m) / double(m);
          b[k][std::size_t(i)] = binom * std::pow(t[k], i) * std::pow(1 - t[k], n - 1 - i);
        }
      }
      nf::Vec3 q{0, 0, 0};
      for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
          for (int k = 0; k < n; ++k) {
            q = q + pts[std::size_t((i * n + j) * n + k)] * (b[0][std::size_t(i)] * b[1][std::size_t(j)] * b[2][std::size_t(k)]);
          }
        }
      }
      return q;
    };
  }

 private:
  void build(int n) {
    n_ = n;
    lattice_.clear();
    const nf::Vec3 e0 = V(plane_.u), e1 = V(plane_.v), e2 = V(plane_.n);
    for (int i = 0; i < n; ++i) {
      for (int j = 0; j < n; ++j) {
        for (int k = 0; k < n; ++k) {
          const double a = lo_[0] + (hi_[0] - lo_[0]) * i / (n - 1), b = lo_[1] + (hi_[1] - lo_[1]) * j / (n - 1),
                       c = lo_[2] + (hi_[2] - lo_[2]) * k / (n - 1);
          lattice_.push_back(e0 * a + e1 * b + e2 * c);
        }
      }
    }
  }
  const nf::Vec3& at(int i, int j, int k) const { return lattice_[std::size_t((i * n_ + j) * n_ + k)]; }
  double extent() const { return std::max({hi_[0] - lo_[0], hi_[1] - lo_[1], hi_[2] - lo_[2]}); }
  PlaneFrame plane_;
  std::array<double, 3> lo_{}, hi_{};
  int n_ = 0;
  std::vector<nf::Vec3> lattice_;
  std::optional<std::size_t> picked_;
  bool moved_ = false;
};

// ------------------------------------------------------------------------------ Splop
/// Splop: the objects around a base point in the construction plane placed onto a point of a
/// surface (the first selected object) – the plane's directions follow the surface's u direction
/// and its normal, distances along the surface approximately kept.
class SplopCommand : public DeformCommand {
 public:
  QString id() const override { return QStringLiteral("splop"); }
  QString title() const override { return QObject::tr("Splop"); }
  QString prompt() const override {
    return base_ ? QObject::tr("Splop: point on the surface") : QObject::tr("Splop: base point of the objects");
  }
  bool begin(const std::vector<document::Entity>& selection) override {
    std::optional<nf::NurbsSurface> s;
    if (!selection.empty()) {
      if (const auto* a = std::get_if<nf::NurbsSurface>(selection.front().geometry.get())) s = *a;
      if (const auto* f = std::get_if<nf::TrimmedSurface>(selection.front().geometry.get())) s = f->surface();
    }
    if (!s || selection.size() < 2) {
      message_ = QObject::tr("Splop: select the target surface first, then the objects");
      return false;
    }
    target_ = *s;
    return DeformCommand::begin({selection.begin() + 1, selection.end()});
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!base_) {
      base_ = V(p);
      plane_ = plane;
      return Result::Continue;
    }
    try {
      const nf::SurfacePoint f = nf::closest_point(*target_, V(p));
      return apply(map(f.u, f.v), false);
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::optional<Point3> basePoint() const override { return base_ ? std::optional(P(*base_)) : std::nullopt; }

  /// Offsets (x, y) in the plane walked on the surface from (u0, v0) in small steps along the
  /// local frame (u direction, normal × u direction); the height goes along the normal.
  Map map(double u0, double v0) const {
    const nf::NurbsSurface s = *target_;
    const nf::Vec3 o = *base_, eu = V(plane_.u), ev = V(plane_.v), en = V(plane_.n);
    return [=](const nf::Vec3& p) {
      const nf::Vec3 r = p - o;
      const double x = nf::dot(r, eu), y = nf::dot(r, ev), h = nf::dot(r, en);
      const auto du = s.domain_u(), dv = s.domain_v();
      double u = u0, v = v0;
      constexpr int steps = 32;
      for (int k = 0; k < steps; ++k) {
        const auto d = s.first_derivatives(u, v);
        const nf::Vec3 n = s.normal(u, v), e1 = nf::normalized(d[1]), e2 = nf::cross(n, e1);
        const nf::Vec3 w = (e1 * x + e2 * y) * (1.0 / steps);
        // [Su Sv] (a, b) = w, least squares
        const double g11 = nf::dot(d[1], d[1]), g12 = nf::dot(d[1], d[2]), g22 = nf::dot(d[2], d[2]);
        const double r1 = nf::dot(d[1], w), r2 = nf::dot(d[2], w), det = g11 * g22 - g12 * g12;
        if (std::abs(det) < 1e-300) break;
        u = std::clamp(u + (g22 * r1 - g12 * r2) / det, du[0], du[1]);
        v = std::clamp(v + (g11 * r2 - g12 * r1) / det, dv[0], dv[1]);
      }
      return s.evaluate(u, v) + s.normal(u, v) * h;
    };
  }

 private:
  std::optional<nf::NurbsSurface> target_;
  std::optional<nf::Vec3> base_;
  PlaneFrame plane_;
};

// ------------------------------------------------------------------------------ Unroll, Smash, Squish
/// A tensor-product cubic through a grid of points at the given parameters (rows along u):
/// every row interpolated at `us`, then the rows' control points along v at `vs` – so the
/// flattened surface keeps the original parameters (and trims).
nf::NurbsSurface grid_surface(const std::vector<std::vector<nf::Vec3>>& grid, const std::vector<double>& us,
                              const std::vector<double>& vs) {
  std::vector<nf::NurbsCurve> rows;  // one per v: along u
  for (std::size_t j = 0; j < vs.size(); ++j) {
    std::vector<nf::Vec3> row;
    for (std::size_t i = 0; i < us.size(); ++i) row.push_back(grid[i][j]);
    rows.push_back(nf::interpolate_curve(row, 3, us));
  }
  const std::size_t nu = rows.front().num_control_points();
  std::vector<nf::NurbsCurve> cols;
  for (std::size_t i = 0; i < nu; ++i) {
    std::vector<nf::Vec3> col;
    for (const nf::NurbsCurve& r : rows) col.push_back(r.control_points()[i]);
    cols.push_back(nf::interpolate_curve(col, 3, vs));
  }
  const std::size_t nv = cols.front().num_control_points();
  std::vector<nf::Vec3> pts(nu * nv);
  for (std::size_t i = 0; i < nu; ++i) {
    for (std::size_t j = 0; j < nv; ++j) pts[i * nv + j] = cols[i].control_points()[j];
  }
  return {3, 3, rows.front().knots(), cols.front().knots(), nu, nv, pts};
}

/// The surface's grid flattened into the plane (x, y) by unfolding triangle by triangle: the
/// first row keeps its segment lengths along x, every further point the distances to its two
/// known neighbours. Exact (up to the grid) for developable surfaces. `relax`: spring iterations
/// that spread the stretch of a non-developable surface (Squish).
struct Flattened {
  std::vector<std::vector<nf::Vec3>> grid;
  double max_strain = 0;  ///< largest relative change of a grid edge's length
};

Flattened flatten(const nf::NurbsSurface& s, std::size_t n, int relax) {
  const auto du = s.domain_u(), dv = s.domain_v();
  std::vector<std::vector<nf::Vec3>> p(n + 1, std::vector<nf::Vec3>(n + 1));
  for (std::size_t i = 0; i <= n; ++i) {
    for (std::size_t j = 0; j <= n; ++j) {
      p[i][j] = s.evaluate(du[0] + (du[1] - du[0]) * double(i) / double(n), dv[0] + (dv[1] - dv[0]) * double(j) / double(n));
    }
  }
  // length of a grid edge along the surface (iso line in 16 chords: error ~ 1/16² of a chord's)
  auto edge = [&](std::size_t i0, std::size_t j0, std::size_t i1, std::size_t j1) {
    constexpr int k = 16;
    double len = 0;
    nf::Vec3 prev = p[i0][j0];
    for (int m = 1; m <= k; ++m) {
      const double t = double(m) / k;
      const double ui = (double(i0) + (double(i1) - double(i0)) * t) / double(n), vj = (double(j0) + (double(j1) - double(j0)) * t) / double(n);
      const nf::Vec3 cur = s.evaluate(du[0] + (du[1] - du[0]) * ui, dv[0] + (dv[1] - dv[0]) * vj);
      len += nf::distance(prev, cur);
      prev = cur;
    }
    return len;
  };
  std::vector<std::vector<nf::Vec3>> q(n + 1, std::vector<nf::Vec3>(n + 1));
  // the third corner of a triangle from two placed points and the distances to them, on the left
  // of a → b (the side the surface's v grows to)
  auto apex = [](const nf::Vec3& a, const nf::Vec3& b, double da, double db, double side) {
    const double ab = nf::distance(a, b);
    const double x = (da * da - db * db + ab * ab) / (2 * ab);
    const double y = std::sqrt(std::max(da * da - x * x, 0.0));
    const nf::Vec3 e = (b - a) / ab, f{-e.y, e.x, 0};
    return a + e * x + f * (side * y);
  };
  q[0][0] = {0, 0, 0};
  for (std::size_t i = 1; i <= n; ++i) q[i][0] = q[i - 1][0] + nf::Vec3{edge(i - 1, 0, i, 0), 0, 0};
  for (std::size_t j = 1; j <= n; ++j) {
    for (std::size_t i = 0; i <= n; ++i) {
      // from the point below and its neighbour in the row below (or the point to the left)
      if (i == 0) {
        q[0][j] = apex(q[0][j - 1], q[1][j - 1], edge(0, j - 1, 0, j), nf::distance(p[0][j], p[1][j - 1]), 1);
      } else {
        q[i][j] = apex(q[i - 1][j], q[i][j - 1], edge(i - 1, j, i, j), edge(i, j - 1, i, j), 1);
      }
    }
  }
  // springs along the grid edges and diagonals (Squish)
  for (int it = 0; it < relax; ++it) {
    std::vector<std::vector<nf::Vec3>> moved = q;
    for (std::size_t i = 0; i <= n; ++i) {
      for (std::size_t j = 0; j <= n; ++j) {
        nf::Vec3 shift{0, 0, 0};
        int k = 0;
        for (const auto& [di, dj] : {std::pair{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {-1, -1}}) {
          const long a = long(i) + di, b = long(j) + dj;
          if (a < 0 || b < 0 || a > long(n) || b > long(n)) continue;
          const nf::Vec3 d = q[std::size_t(a)][std::size_t(b)] - q[i][j];
          const double rest = nf::distance(p[std::size_t(a)][std::size_t(b)], p[i][j]), now = nf::norm(d);
          if (now > 0) shift = shift + d * (0.5 * (now - rest) / now);
          ++k;
        }
        if (k > 0) moved[i][j] = q[i][j] + shift * (1.0 / k);
      }
    }
    q = moved;
  }
  Flattened out;
  out.grid = q;
  for (std::size_t i = 0; i <= n; ++i) {
    for (std::size_t j = 0; j <= n; ++j) {
      for (const auto& [di, dj] : {std::pair{1, 0}, {0, 1}}) {
        if (i + di > n || j + dj > n) continue;
        const double rest = edge(i, j, i + di, j + dj);
        if (rest > 0) out.max_strain = std::max(out.max_strain, std::abs(nf::distance(q[i + di][j + dj], q[i][j]) - rest) / rest);
      }
    }
  }
  return out;
}

/// Unroll surface / Smash / Squish: the selected surfaces flattened into the construction plane
/// (beside each other's origin at the surface's first corner); trims are kept. Unroll is for
/// developable surfaces (it reports the stretch); Squish relaxes the stretch of others.
class FlattenCommand : public Command {
 public:
  enum class Kind { Unroll, Smash, Squish };
  explicit FlattenCommand(Kind kind) : kind_(kind) {}
  QString id() const override {
    switch (kind_) {
      case Kind::Unroll: return QStringLiteral("unrollsrf");
      case Kind::Smash: return QStringLiteral("smash");
      case Kind::Squish: break;
    }
    return QStringLiteral("squish");
  }
  QString title() const override {
    switch (kind_) {
      case Kind::Unroll: return QObject::tr("Unroll surface");
      case Kind::Smash: return QObject::tr("Smash");
      case Kind::Squish: break;
    }
    return QObject::tr("Squish");
  }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    double strain = 0;
    try {
      for (const document::Entity& e : selection) {
        const nf::TrimmedSurface* face = std::get_if<nf::TrimmedSurface>(e.geometry.get());
        const nf::NurbsSurface* plain = std::get_if<nf::NurbsSurface>(e.geometry.get());
        if (face == nullptr && plain == nullptr) continue;
        const nf::NurbsSurface& s = face != nullptr ? face->surface() : *plain;
        const std::size_t n = 24;
        const Flattened f = flatten(s, n, kind_ == Kind::Squish ? 300 : 0);
        strain = std::max(strain, f.max_strain);
        // into the construction plane at the surface's first corner (projected)
        const PlaneFrame& pl = viewPlane();
        const nf::Vec3 corner = s.evaluate(s.domain_u()[0], s.domain_v()[0]);
        const nf::Vec3 origin = corner - V(pl.n) * nf::dot(corner - V(pl.origin), V(pl.n));
        std::vector<std::vector<nf::Vec3>> grid = f.grid;
        for (auto& col : grid) {
          for (nf::Vec3& q : col) q = origin + V(pl.u) * q.x + V(pl.v) * q.y;
        }
        std::vector<double> us, vs;
        for (std::size_t i = 0; i <= n; ++i) {
          us.push_back(s.domain_u()[0] + (s.domain_u()[1] - s.domain_u()[0]) * double(i) / double(n));
          vs.push_back(s.domain_v()[0] + (s.domain_v()[1] - s.domain_v()[0]) * double(i) / double(n));
        }
        const nf::NurbsSurface flat = grid_surface(grid, us, vs);
        if (face != nullptr && !face->is_untrimmed()) {
          entities_.push_back(document::make_entity(nf::TrimmedSurface(flat, face->outer(), face->holes())));
        } else {
          entities_.push_back(document::make_entity(flat));
        }
      }
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return false;
    }
    if (entities_.empty()) {
      message_ = QObject::tr("%1: select surfaces").arg(title());
      return false;
    }
    message_ = QObject::tr("%1: largest stretch %2 %").arg(title()).arg(100.0 * strain, 0, 'g', 3);
    if (kind_ == Kind::Unroll && strain > 0.01) {
      message_ += QObject::tr(" – the surface is not developable; Squish spreads the stretch");
    }
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }

 private:
  Kind kind_;
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
      {"flow", {"flowalongcrv"}, [] { return std::make_unique<FlowCommand>(false); }},
      {"flowalongsrf", {}, [] { return std::make_unique<FlowCommand>(true); }},
      {"cageedit", {"cage"}, [] { return std::make_unique<CageEditCommand>(); }},
      {"splop", {}, [] { return std::make_unique<SplopCommand>(); }},
      {"unrollsrf", {"unroll"}, [] { return std::make_unique<FlattenCommand>(FlattenCommand::Kind::Unroll); }},
      {"smash", {}, [] { return std::make_unique<FlattenCommand>(FlattenCommand::Kind::Smash); }},
      {"squish", {}, [] { return std::make_unique<FlattenCommand>(FlattenCommand::Kind::Squish); }},
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
