// Curve constructions (docs/commands.md, "Curves"): Curve (control points), Ellipse, Spiral,
// Parabola, Hyperbola, Conic, Sketch (freehand) and Curve through points; curves from curves:
// Blend, Chamfer, Tween; lines: Tangent, Perpendicular. Conic sections are exact rational quadratic NURBS; Sketch is a
// least-squares fit of the cursor's path.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <exception>
#include <functional>
#include <limits>
#include <nurbforge/analysis/closest_point.hpp>
#include <nurbforge/fitting/fit.hpp>
#include <nurbforge/geometry/primitives.hpp>
#include <nurbforge/modeling/blend.hpp>
#include <nurbforge/modeling/fillet.hpp>

#include "commands/command_util.hpp"

namespace nfcad::commands {

namespace {

using namespace util;

/// Rational quadratic Bézier arc P0 -> P2 with the middle control point P1 (where the end
/// tangents meet) of weight w: an ellipse arc (w < 1), a parabola (w = 1) or a hyperbola (w > 1).
nf::NurbsCurve conic_arc(const nf::Vec3& p0, const nf::Vec3& p1, const nf::Vec3& p2, double w) {
  return {2, {0, 0, 0, 1, 1, 1}, {p0, p1, p2}, {1.0, w, 1.0}};
}

/// Adds the curve `make` builds; false (and the reason in `message`) if it fails.
bool add(std::vector<document::Entity>& out, QString& message, const QString& what,
         const std::function<nf::NurbsCurve()>& make) {
  try {
    out.push_back(document::make_entity(make()));
    return true;
  } catch (const std::exception& e) {
    message = failure(what, e);
    return false;
  }
}

std::vector<Polyline3> try_sample(const std::function<nf::NurbsCurve()>& make, std::size_t n = 96) {
  try {
    return {sample(make(), n)};
  } catch (const std::exception&) {
    return {};
  }
}

// ------------------------------------------------------------------------------ Curve
/// A B-spline from its control points (degree 3, lower with fewer points); clicking the first
/// point again closes it.
class ControlPointCurveCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("curve"); }
  QString title() const override { return QObject::tr("Curve (control points)"); }
  QString prompt() const override {
    if (pts_.empty()) return QObject::tr("Curve: first control point");
    return QObject::tr("Curve: next control point (Enter: done, snap to the first point: close)");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!pts_.empty() && dist(pts_.back(), p) < kEps) return Result::Rejected;
    if (pts_.size() >= 3 && dist(pts_.front(), p) < kEps) {
      pts_.push_back(pts_.front());
      return create();
    }
    pts_.push_back(p);
    return Result::Continue;
  }
  Result finish() override { return pts_.size() >= 2 ? create() : Result::Cancelled; }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (pts_.empty()) return {};
    Polyline3 q = pts_;
    if (dist(q.back(), c) > kEps) q.push_back(c);
    std::vector<Polyline3> out = try_sample([&] { return make(q); }, 24 * q.size());
    out.push_back(q);  // the control polygon
    return out;
  }
  std::optional<Point3> basePoint() const override {
    return pts_.empty() ? std::nullopt : std::optional(pts_.back());
  }
  std::vector<Point3> snapPoints() const override { return pts_; }

  static nf::NurbsCurve make(const Polyline3& pts) {
    std::vector<nf::Vec3> v;
    for (const Point3& p : pts) v.push_back(V(p));
    return nf::NurbsCurve::from_points(std::min<std::size_t>(3, v.size() - 1), v);
  }

 private:
  Result create() {
    return add(entities_, message_, title(), [&] { return make(pts_); }) ? Result::Done
                                                                         : Result::Cancelled;
  }
  Polyline3 pts_;
};

// ------------------------------------------------------------------------------ Ellipse
/// Centre, end of the first axis, then the second semi-axis (a point or a number), in the
/// construction plane: an exact rational NURBS (the circle's control net scaled per axis).
class EllipseCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("ellipse"); }
  QString title() const override { return QObject::tr("Ellipse"); }
  QString prompt() const override {
    if (!centre_) return QObject::tr("Ellipse: centre");
    if (!axis_) return QObject::tr("Ellipse: end of the first axis");
    return QObject::tr("Ellipse: second axis (point or length)");
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!centre_) {
      centre_ = p;
      plane_ = plane;
      return Result::Continue;
    }
    if (!axis_) {
      const nf::Vec3 a = in_plane(p, *centre_, plane_);
      if (nf::norm(a) < kEps) return Result::Rejected;
      axis_ = a;
      return Result::Continue;
    }
    return create(second(p));
  }
  Result number(double v) override {
    if (!centre_) return Result::Rejected;
    if (!axis_) {  // the first semi-axis along the plane's u
      if (v <= 0) return Result::Rejected;
      axis_ = V(plane_.u) * v;
      return Result::Continue;
    }
    return create(v);
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame& plane) const override {
    if (!centre_) return {};
    if (!axis_) {
      const double r = nf::norm(in_plane(c, *centre_, plane_));
      return {{*centre_, c}, circle(V(*centre_), V(plane.n), r)};
    }
    std::vector<Polyline3> out = try_sample([&] { return make(second(c)); });
    out.push_back({P(V(*centre_) - *axis_), P(V(*centre_) + *axis_)});
    return out;
  }
  std::optional<Point3> basePoint() const override { return centre_; }

  /// The ellipse about `centre` with semi-axis vectors a and b (perpendicular).
  static nf::NurbsCurve ellipse(const nf::Vec3& centre, const nf::Vec3& a, const nf::Vec3& b) {
    const double w = std::sqrt(0.5);
    const double unit[9][2] = {{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}, {1, 0}};
    std::vector<nf::Vec3> pts;
    for (const auto& u : unit) pts.push_back(centre + a * u[0] + b * u[1]);
    return {2, {0, 0, 0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1, 1, 1}, pts, {1, w, 1, w, 1, w, 1, w, 1}};
  }

 private:
  double second(const Point3& p) const {
    const nf::Vec3 d = in_plane(p, *centre_, plane_);
    const nf::Vec3 along = nf::normalized(*axis_);
    return nf::norm(d - along * nf::dot(d, along));
  }
  nf::NurbsCurve make(double b) const {
    const nf::Vec3 bdir = nf::normalized(nf::cross(V(plane_.n), *axis_));
    return ellipse(V(*centre_), *axis_, bdir * b);
  }
  Result create(double b) {
    if (b < kEps) return Result::Rejected;
    return add(entities_, message_, title(), [&] { return make(b); }) ? Result::Done : Result::Rejected;
  }
  std::optional<Point3> centre_;
  std::optional<nf::Vec3> axis_;
  PlaneFrame plane_;
};

// ------------------------------------------------------------------------------ Spiral
/// A planar Archimedean spiral in the construction plane: (turns,) centre, start radius, end
/// radius (points or numbers); counter-clockwise about the plane normal.
class SpiralCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("spiral"); }
  QString title() const override { return QObject::tr("Spiral"); }
  QString prompt() const override {
    if (!centre_) return QObject::tr("Spiral (%1 turns): centre (type a number to change the turns)").arg(turns_);
    if (!start_) return QObject::tr("Spiral (%1 turns): start radius (point or number)").arg(turns_);
    return QObject::tr("Spiral (%1 turns): end radius (point or number)").arg(turns_);
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!centre_) {
      centre_ = p;
      plane_ = plane;
      return Result::Continue;
    }
    const nf::Vec3 r = in_plane(p, *centre_, plane_);
    if (!start_) {
      if (nf::norm(r) < kEps) return Result::Rejected;
      start_ = V(*centre_) + r;
      return Result::Continue;
    }
    return create(nf::norm(r));
  }
  Result number(double v) override {
    if (!centre_) {
      if (v <= 0) return Result::Rejected;
      turns_ = v;
      return Result::Continue;
    }
    if (!start_) {
      if (v <= 0) return Result::Rejected;
      start_ = V(*centre_) + V(plane_.u) * v;
      return Result::Continue;
    }
    return v < 0 ? Result::Rejected : create(v);
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame& plane) const override {
    if (!centre_) return {};
    const double r = nf::norm(in_plane(c, *centre_, plane_));
    if (!start_) return {{*centre_, c}, circle(V(*centre_), V(plane.n), r)};
    return try_sample([&] { return make(r, 1e-3 * std::max(r, nf::norm(*start_ - V(*centre_)))); },
                      static_cast<std::size_t>(std::clamp(turns_ * 64.0, 64.0, 3000.0)));
  }
  std::optional<Point3> basePoint() const override { return centre_; }

 private:
  nf::NurbsCurve make(double end_radius, double tol) const {
    return nf::make_helix(V(*centre_), V(plane_.n), *start_, 0.0, turns_, end_radius, false, tol);
  }
  Result create(double end_radius) {
    const double size = std::max(end_radius, nf::norm(*start_ - V(*centre_)));
    return add(entities_, message_, title(), [&] { return make(end_radius, 1e-7 * std::max(size, 1.0)); })
               ? Result::Done
               : Result::Rejected;
  }
  std::optional<Point3> centre_;
  std::optional<nf::Vec3> start_;
  PlaneFrame plane_;
  double turns_ = 5.0;
};

// ------------------------------------------------------------------------------ Parabola
/// Vertex, focus (axis and focal length), then the end point: the parabola segment symmetric
/// about the axis out to the end point's distance from it, in the construction plane.
class ParabolaCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("parabola"); }
  QString title() const override { return QObject::tr("Parabola"); }
  QString prompt() const override {
    if (!vertex_) return QObject::tr("Parabola: vertex");
    if (!focus_) return QObject::tr("Parabola: focus (or focal length)");
    return QObject::tr("Parabola: end point (or half width)");
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!vertex_) {
      vertex_ = p;
      plane_ = plane;
      return Result::Continue;
    }
    if (!focus_) {
      const nf::Vec3 d = in_plane(p, *vertex_, plane_);
      if (nf::norm(d) < kEps) return Result::Rejected;
      focus_ = d;
      return Result::Continue;
    }
    return create(half_width(p));
  }
  Result number(double v) override {
    if (!vertex_ || v <= 0) return Result::Rejected;
    if (!focus_) {
      focus_ = V(plane_.v) * v;  // opening along the plane's v
      return Result::Continue;
    }
    return create(v);
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (!vertex_) return {};
    if (!focus_) return {{*vertex_, c}};
    auto out = try_sample([&] { return make(half_width(c)); });
    out.push_back({*vertex_, P(V(*vertex_) + *focus_)});
    return out;
  }
  std::optional<Point3> basePoint() const override { return vertex_; }

  /// y = x² / (4 f) about `vertex` (axis: unit `axis`, x along unit `side`), |x| <= half.
  static nf::NurbsCurve parabola(const nf::Vec3& vertex, const nf::Vec3& axis, const nf::Vec3& side,
                                 double f, double half) {
    const double y = half * half / (4.0 * f);
    return conic_arc(vertex - side * half + axis * y, vertex - axis * y, vertex + side * half + axis * y, 1.0);
  }

 private:
  /// The signed half width: the curve ends on the side of the point.
  double half_width(const Point3& p) const {
    return nf::dot(in_plane(p, *vertex_, plane_), side());
  }
  nf::Vec3 side() const { return nf::normalized(nf::cross(nf::normalized(*focus_), V(plane_.n))); }
  nf::NurbsCurve make(double half) const {
    const nf::Vec3 s = half < 0 ? side() * -1.0 : side();
    return parabola(V(*vertex_), nf::normalized(*focus_), s, nf::norm(*focus_), std::abs(half));
  }
  Result create(double half) {
    if (std::abs(half) < kEps) return Result::Rejected;
    return add(entities_, message_, title(), [&] { return make(half); }) ? Result::Done : Result::Rejected;
  }
  std::optional<Point3> vertex_;
  std::optional<nf::Vec3> focus_;
  PlaneFrame plane_;
};

// ------------------------------------------------------------------------------ Hyperbola
/// Centre, vertex (axis and semi-axis a), then a point of the branch: x²/a² − y²/b² = 1 through
/// it (b from the point), the branch segment symmetric about the axis out to the point.
class HyperbolaCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("hyperbola"); }
  QString title() const override { return QObject::tr("Hyperbola"); }
  QString prompt() const override {
    if (!centre_) return QObject::tr("Hyperbola: centre");
    if (!vertex_) return QObject::tr("Hyperbola: vertex");
    return QObject::tr("Hyperbola: a point of the branch (farther from the centre than the vertex)");
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!centre_) {
      centre_ = p;
      plane_ = plane;
      return Result::Continue;
    }
    if (!vertex_) {
      const nf::Vec3 d = in_plane(p, *centre_, plane_);
      if (nf::norm(d) < kEps) return Result::Rejected;
      vertex_ = d;
      return Result::Continue;
    }
    if (!add(entities_, message_, title(), [&] { return make(p); })) {
      message_ = QObject::tr("Hyperbola: the point must lie beyond the vertex, off the axis");
      return Result::Rejected;
    }
    return Result::Done;
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (!centre_) return {};
    if (!vertex_) return {{*centre_, c}};
    auto out = try_sample([&] { return make(c); });
    out.push_back({*centre_, P(V(*centre_) + *vertex_)});
    return out;
  }
  std::optional<Point3> basePoint() const override { return centre_; }

  /// The branch x > 0 of x²/a² − y²/b² = 1 (x along unit `axis`, y along unit `side`) from
  /// y = −h to h, x = a·sqrt(1 + h²/b²).
  static nf::NurbsCurve hyperbola(const nf::Vec3& centre, const nf::Vec3& axis, const nf::Vec3& side,
                                  double a, double b, double h) {
    const double x = a * std::sqrt(1.0 + h * h / (b * b));
    // the end tangents meet on the axis at a²/x; the weight x/a puts the middle on the vertex
    return conic_arc(centre + axis * x - side * h, centre + axis * (a * a / x), centre + axis * x + side * h,
                     x / a);
  }

 private:
  nf::NurbsCurve make(const Point3& p) const {
    const double a = nf::norm(*vertex_);
    const nf::Vec3 ax = *vertex_ / a;
    const nf::Vec3 side = nf::normalized(nf::cross(V(plane_.n), ax));
    const nf::Vec3 d = in_plane(p, *centre_, plane_);
    const double x = std::abs(nf::dot(d, ax));
    const double h = std::abs(nf::dot(d, side));
    if (x <= a * (1 + 1e-9) || h < kEps) throw std::invalid_argument("the point is not beyond the vertex");
    const double b = h / std::sqrt(x * x / (a * a) - 1.0);
    return hyperbola(V(*centre_), ax, side, a, b, h);
  }
  std::optional<Point3> centre_;
  std::optional<nf::Vec3> vertex_;
  PlaneFrame plane_;
};

// ------------------------------------------------------------------------------ Conic
/// Start, end, apex (where the end tangents meet), then rho (a number in (0, 1), or a point:
/// its position from the chord's midpoint towards the apex): ellipse arc for rho < 0.5,
/// parabola for 0.5, hyperbola above.
class ConicCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("conic"); }
  QString title() const override { return QObject::tr("Conic"); }
  QString prompt() const override {
    switch (pts_.size()) {
      case 0: return QObject::tr("Conic: start point");
      case 1: return QObject::tr("Conic: end point");
      case 2: return QObject::tr("Conic: apex (where the end tangents meet)");
      default: return QObject::tr("Conic: rho (0 … 1; 0.5: parabola) or a point it passes through");
    }
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (pts_.size() < 3) {
      for (const Point3& q : pts_) {
        if (dist(q, p) < kEps) return Result::Rejected;
      }
      pts_.push_back(p);
      return Result::Continue;
    }
    return create(rho_of(p));
  }
  Result number(double v) override { return pts_.size() == 3 ? create(v) : Result::Rejected; }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (pts_.empty()) return {};
    if (pts_.size() < 3) {
      Polyline3 q = pts_;
      q.push_back(c);
      return {q};
    }
    auto out = try_sample([&] { return make(rho_of(c)); });
    out.push_back({pts_[0], pts_[2], pts_[1]});
    return out;
  }
  std::optional<Point3> basePoint() const override {
    return pts_.empty() ? std::nullopt : std::optional(pts_.back());
  }

  /// The conic from p0 to p2 tangent to p0p1 and p1p2, through the shoulder point
  /// M + rho (p1 − M) (M: midpoint of p0p2): weight rho / (1 − rho).
  static nf::NurbsCurve conic(const nf::Vec3& p0, const nf::Vec3& p1, const nf::Vec3& p2, double rho) {
    if (!(rho > 0.0 && rho < 1.0)) throw std::invalid_argument("rho must lie between 0 and 1");
    if (nf::norm(nf::cross(p1 - p0, p2 - p0)) < kEps * std::max(1.0, nf::norm(p2 - p0))) {
      throw std::invalid_argument("the apex lies on the chord");
    }
    return conic_arc(p0, p1, p2, rho / (1.0 - rho));
  }

 private:
  double rho_of(const Point3& p) const {
    const nf::Vec3 m = (V(pts_[0]) + V(pts_[1])) * 0.5;
    const nf::Vec3 d = V(pts_[2]) - m;
    return nf::dot(V(p) - m, d) / nf::dot(d, d);
  }
  nf::NurbsCurve make(double rho) const { return conic(V(pts_[0]), V(pts_[2]), V(pts_[1]), rho); }
  Result create(double rho) {
    return add(entities_, message_, title(), [&] { return make(rho); }) ? Result::Done : Result::Rejected;
  }
  Polyline3 pts_;  // start, end, apex
};

// ------------------------------------------------------------------------------ Sketch
/// Freehand: click to start, move the cursor along the curve, click (or Enter) to end. The path
/// is fitted by a cubic B-spline within 0.5 % of its length.
class SketchCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("sketch"); }
  QString title() const override { return QObject::tr("Sketch"); }
  QString prompt() const override {
    return path_.empty() ? QObject::tr("Sketch: start point")
                         : QObject::tr("Sketch: move along the curve, click or Enter to end");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (path_.empty()) {
      path_.push_back(p);
      return Result::Continue;
    }
    record(p);
    return create();
  }
  Result finish() override { return path_.size() >= 2 ? create() : Result::Cancelled; }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (path_.empty()) return {};
    record(c);  // the cursor's path is the input
    return {path_};
  }
  std::optional<Point3> basePoint() const override {
    return path_.empty() ? std::nullopt : std::optional(path_.back());
  }

  /// The fitted curve of a path (at least two distinct points).
  static nf::NurbsCurve fit(const Polyline3& path) {
    std::vector<nf::Vec3> v;
    double length = 0;
    for (const Point3& p : path) {
      if (!v.empty()) {
        const double step = nf::distance(v.back(), V(p));
        if (step < kEps) continue;
        length += step;
      }
      v.push_back(V(p));
    }
    if (v.size() < 2) throw std::invalid_argument("the path has no length");
    if (v.size() < 4) return nf::NurbsCurve::from_points(v.size() - 1, v);
    return nf::approximate_curve_tol(v, 3, 0.005 * length);
  }

 private:
  void record(const Point3& p) const {
    if (path_.empty() || dist(path_.back(), p) > kEps) path_.push_back(p);
  }
  Result create() {
    return add(entities_, message_, title(), [&] { return fit(path_); }) ? Result::Done : Result::Rejected;
  }
  mutable Polyline3 path_;  // grows with the cursor (preview)
};

// ------------------------------------------------------------------------------ Curve through points
/// An interpolating cubic through the selected points, in selection order.
class CurveThroughPointsCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("curve_through_points"); }
  QString title() const override { return QObject::tr("Curve through points"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    std::vector<nf::Vec3> pts;
    for (const document::Entity& e : selection) {
      if (const auto* p = std::get_if<nf::Vec3>(e.geometry.get())) {
        if (pts.empty() || nf::distance(pts.back(), *p) > kEps) pts.push_back(*p);
      }
    }
    if (pts.size() < 2) {
      message_ = QObject::tr("Curve through points: select two or more points (in order)");
      return false;
    }
    return add(entities_, message_, title(),
               [&] { return nf::interpolate_curve(pts, std::min<std::size_t>(3, pts.size() - 1)); });
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return entities_.empty() ? Result::Cancelled : Result::Done; }
};

// ------------------------------------------------------------------------------ curves from curves
/// The curves of the selection (with their entities), in selection order.
class SelectedCurvesCommand : public Command {
 public:
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (const auto* c = std::get_if<nf::NurbsCurve>(e.geometry.get())) {
        curves_.push_back(*c);
        ids_.push_back(e.id);
      }
    }
    if (curves_.size() < min_ || curves_.size() > max_) {
      message_ = QObject::tr("%1: select %2").arg(title(), requirement_);
      return false;
    }
    return true;
  }

 protected:
  SelectedCurvesCommand(std::size_t min, std::size_t max, QString requirement)
      : min_(min), max_(max), requirement_(std::move(requirement)) {}
  void replaceCurve(std::size_t i, const nf::NurbsCurve& c) {
    replace_.emplace_back(ids_[i], std::make_shared<const document::Geometry>(c));
  }
  std::vector<nf::NurbsCurve> curves_;
  std::vector<document::EntityId> ids_;

 private:
  std::size_t min_, max_;
  QString requirement_;
};

nf::Vec3 end_point(const nf::NurbsCurve& c, nf::CurveEnd e) {
  return c.evaluate(e == nf::CurveEnd::Start ? c.domain_start() : c.domain_end());
}

/// Blend: a smooth curve between an end of each of two selected curves – the ends nearest to
/// the two clicks, or (Enter) the two ends closest to each other; G2 unless 1 is typed.
class BlendCommand : public SelectedCurvesCommand {
 public:
  BlendCommand() : SelectedCurvesCommand(2, 2, QObject::tr("two curves")) {}
  QString id() const override { return QStringLiteral("blend"); }
  QString title() const override { return QObject::tr("Blend curves"); }
  QString prompt() const override {
    const QString g = QStringLiteral("G%1").arg(continuity_);
    if (!first_) {
      return QObject::tr("Blend (%1): click near the end of the first curve, or Enter: the closest ends "
                         "(type 1 or 2: continuity)").arg(g);
    }
    return QObject::tr("Blend (%1): click near the end of the second curve").arg(g);
  }
  bool begin(const std::vector<document::Entity>& selection) override {
    if (!SelectedCurvesCommand::begin(selection)) return false;
    double best = std::numeric_limits<double>::infinity();
    for (auto ea : {nf::CurveEnd::Start, nf::CurveEnd::End}) {
      for (auto eb : {nf::CurveEnd::Start, nf::CurveEnd::End}) {
        const double d = nf::distance(end_point(curves_[0], ea), end_point(curves_[1], eb));
        if (d < best) {
          best = d;
          closest_ = {ea, eb};
        }
      }
    }
    return true;
  }
  Result number(double v) override {
    if (v != 1 && v != 2) {
      message_ = QObject::tr("Blend: the continuity is 1 (tangent) or 2 (curvature)");
      return Result::Rejected;
    }
    continuity_ = static_cast<int>(v);
    return Result::Continue;
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!first_) {
      first_ = nearest_end(curves_[0], p);
      return Result::Continue;
    }
    return create(*first_, nearest_end(curves_[1], p));
  }
  Result finish() override {
    return first_ ? Result::Cancelled : create(closest_.first, closest_.second);
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    const auto ends = first_ ? std::pair{*first_, nearest_end(curves_[1], c)} : closest_;
    return try_sample([&] { return make(ends.first, ends.second); });
  }

 private:
  static nf::CurveEnd nearest_end(const nf::NurbsCurve& c, const Point3& p) {
    return nf::distance(end_point(c, nf::CurveEnd::Start), V(p)) <=
                   nf::distance(end_point(c, nf::CurveEnd::End), V(p))
               ? nf::CurveEnd::Start
               : nf::CurveEnd::End;
  }
  nf::NurbsCurve make(nf::CurveEnd a, nf::CurveEnd b) const {
    return nf::blend_curves(curves_[0], a, curves_[1], b, continuity_);
  }
  Result create(nf::CurveEnd a, nf::CurveEnd b) {
    return add(entities_, message_, title(), [&] { return make(a, b); }) ? Result::Done : Result::Rejected;
  }
  int continuity_ = 2;
  std::optional<nf::CurveEnd> first_;
  std::pair<nf::CurveEnd, nf::CurveEnd> closest_{nf::CurveEnd::End, nf::CurveEnd::Start};
};

/// Chamfer: a straight cut at the typed distance from the corner – between two selected
/// curves (both trimmed to it) or at every corner of one curve.
class ChamferCommand : public SelectedCurvesCommand {
 public:
  ChamferCommand() : SelectedCurvesCommand(1, 2, QObject::tr("one curve (all its corners) or two curves")) {}
  QString id() const override { return QStringLiteral("chamfer"); }
  QString title() const override { return QObject::tr("Chamfer curves"); }
  QString prompt() const override {
    return QObject::tr("Chamfer: distance from the corner (two curves: between them; one curve: all its corners)");
  }
  Result number(double d) override {
    if (d <= 0) {
      message_ = QObject::tr("Chamfer: the distance must be positive");
      return Result::Rejected;
    }
    try {
      if (curves_.size() == 1) {
        replaceCurve(0, nf::chamfer_corners(curves_[0], d));
        return Result::Done;
      }
      const nf::CurveChamfer c = nf::chamfer_curves(curves_[0], curves_[1], d, d);
      entities_.push_back(document::make_entity(c.line));
      if (c.trimmed_a) replaceCurve(0, *c.trimmed_a);
      if (c.trimmed_b) replaceCurve(1, *c.trimmed_b);
      return Result::Done;
    } catch (const std::exception& e) {
      entities_.clear();
      replace_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
};

/// Tween: curves between two selected curves (the typed number, Enter: one), evenly from the
/// first to the second; a second curve running the other way is turned round first.
class TweenCommand : public SelectedCurvesCommand {
 public:
  TweenCommand() : SelectedCurvesCommand(2, 2, QObject::tr("two curves")) {}
  QString id() const override { return QStringLiteral("tween"); }
  QString title() const override { return QObject::tr("Tween curves"); }
  QString prompt() const override { return QObject::tr("Tween: number of curves (Enter: 1)"); }
  Result number(double v) override {
    if (v < 1 || v > 1000 || std::floor(v) != v) {
      message_ = QObject::tr("Tween: the number of curves is a whole number from 1");
      return Result::Rejected;
    }
    return create(static_cast<std::size_t>(v));
  }
  Result finish() override { return create(1); }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  std::vector<Polyline3> preview(const Point3&, const PlaneFrame&) const override {
    try {
      return {sample(tweens(1).front())};
    } catch (const std::exception&) {
      return {};
    }
  }

  /// `count` tweens of a and b, b turned round if its start lies nearer to a's end.
  static std::vector<nf::NurbsCurve> tween(const nf::NurbsCurve& a, nf::NurbsCurve b, std::size_t count) {
    const nf::Vec3 a0 = end_point(a, nf::CurveEnd::Start), a1 = end_point(a, nf::CurveEnd::End);
    const nf::Vec3 b0 = end_point(b, nf::CurveEnd::Start), b1 = end_point(b, nf::CurveEnd::End);
    if (nf::distance(a0, b1) + nf::distance(a1, b0) < nf::distance(a0, b0) + nf::distance(a1, b1)) {
      b = b.reversed();
    }
    return nf::tween_curves(a, b, count);
  }

 private:
  std::vector<nf::NurbsCurve> tweens(std::size_t n) const { return tween(curves_[0], curves_[1], n); }
  Result create(std::size_t n) {
    try {
      for (const nf::NurbsCurve& c : tweens(n)) entities_.push_back(document::make_entity(c));
      return Result::Done;
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
};

// ------------------------------------------------------------------------------ Tangent, Perpendicular
/// Tangent lines: with one selected curve from a point to the curve, with two the common
/// tangents; of several solutions the one whose touching point lies nearest the click. In the
/// construction plane of the view.
class TangentCommand : public SelectedCurvesCommand {
 public:
  TangentCommand() : SelectedCurvesCommand(1, 2, QObject::tr("one curve (tangent from a point) or two curves")) {}
  QString id() const override { return QStringLiteral("tangent"); }
  QString title() const override { return QObject::tr("Tangent line"); }
  QString prompt() const override {
    if (curves_.size() == 2) return QObject::tr("Tangent: click near the tangent you want");
    return from_ ? QObject::tr("Tangent: click near the touching point you want")
                 : QObject::tr("Tangent: start point");
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (curves_.size() == 1 && !from_) {
      from_ = p;
      plane_ = plane;
      return Result::Continue;
    }
    if (!from_) plane_ = plane;
    try {
      const auto line = choose(p, plane_);
      if (!line) {
        message_ = QObject::tr("Tangent: there is no tangent line here");
        return Result::Rejected;
      }
      entities_.push_back(document::make_entity(line->line));
      return Result::Done;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame& plane) const override {
    if (curves_.size() == 1 && !from_) return {};
    try {
      const auto line = choose(c, from_ ? plane_ : plane);
      if (line) return {{P(line->point_a), P(line->point_b)}};
    } catch (const std::exception&) {
    }
    return {};
  }
  std::optional<Point3> basePoint() const override { return from_; }

 private:
  std::optional<nf::TangentLine> choose(const Point3& near, const PlaneFrame& plane) const {
    const std::vector<nf::TangentLine> all =
        curves_.size() == 1 ? nf::tangent_lines(V(*from_), curves_[0], V(plane.n))
                            : nf::tangent_lines(curves_[0], curves_[1], V(plane.n));
    std::optional<nf::TangentLine> best;
    double d_best = std::numeric_limits<double>::infinity();
    for (const nf::TangentLine& t : all) {
      // one curve: the touching point; two: the nearer of the two touching points
      double d = nf::distance(t.point_b, V(near));
      if (curves_.size() == 2) d = std::min(d, nf::distance(t.point_a, V(near)));
      if (d < d_best) {
        d_best = d;
        best = t;
      }
    }
    return best;
  }
  std::optional<Point3> from_;
  PlaneFrame plane_;
};

/// Perpendicular: from a point to its foot on the selected curve (the nearest point: the line
/// meets the curve at a right angle); repeats until Enter.
class PerpendicularCommand : public SelectedCurvesCommand {
 public:
  PerpendicularCommand() : SelectedCurvesCommand(1, 1, QObject::tr("one curve")) {}
  QString id() const override { return QStringLiteral("perpendicular"); }
  QString title() const override { return QObject::tr("Perpendicular line"); }
  QString prompt() const override {
    return QObject::tr("Perpendicular: from point (Enter: done)");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    const nf::CurvePoint foot = nf::closest_point(curves_[0], V(p));
    if (foot.distance < kEps) {
      message_ = QObject::tr("Perpendicular: the point lies on the curve");
      return Result::Rejected;
    }
    entities_.push_back(document::make_entity(nf::make_line(V(p), foot.point)));
    ++count_;
    return Result::Continue;
  }
  Result finish() override { return count_ > 0 ? Result::Done : Result::Cancelled; }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    return {{c, P(nf::closest_point(curves_[0], V(c)).point)}};
  }

 private:
  int count_ = 0;
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"curve", {"crv"}, [] { return std::make_unique<ControlPointCurveCommand>(); }},
      {"ellipse", {"el"}, [] { return std::make_unique<EllipseCommand>(); }},
      {"spiral", {"spi"}, [] { return std::make_unique<SpiralCommand>(); }},
      {"parabola", {"para"}, [] { return std::make_unique<ParabolaCommand>(); }},
      {"hyperbola", {"hyp"}, [] { return std::make_unique<HyperbolaCommand>(); }},
      {"conic", {}, [] { return std::make_unique<ConicCommand>(); }},
      {"sketch", {"sk"}, [] { return std::make_unique<SketchCommand>(); }},
      {"curve_through_points", {"crvpts", "curvethroughpoints"},
       [] { return std::make_unique<CurveThroughPointsCommand>(); }},
      {"blend", {"blendcrv"}, [] { return std::make_unique<BlendCommand>(); }},
      {"chamfer", {"cha", "chamfercorners"}, [] { return std::make_unique<ChamferCommand>(); }},
      {"tween", {"tweencurves"}, [] { return std::make_unique<TweenCommand>(); }},
      {"tangent", {"tan"}, [] { return std::make_unique<TangentCommand>(); }},
      {"perpendicular", {"perp"}, [] { return std::make_unique<PerpendicularCommand>(); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_curve_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList curve_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
