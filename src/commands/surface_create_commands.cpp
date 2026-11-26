// Creating surfaces (docs/commands.md, "Creating surfaces"): Surface from points, Edge surface,
// Planar surface, Patch, Rail revolve, Extrude along curve / to point / tapered, Extrude surface,
// Pipe, Surface from point grid, Ellipsoid, Paraboloid.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <exception>
#include <functional>
#include <limits>
#include <numbers>
#include <nurbforge/fitting/fit.hpp>
#include <nurbforge/geometry/primitives.hpp>
#include <nurbforge/geometry/transform.hpp>
#include <nurbforge/modeling/construct.hpp>
#include <nurbforge/modeling/gordon.hpp>
#include <nurbforge/modeling/surface_tools.hpp>
#include <nurbforge/modeling/sweep.hpp>
#include <nurbforge/topology/solid_ops.hpp>
#include <nurbforge/topology/solids.hpp>

#include "commands/command_util.hpp"
#include "kernel/geometry_ops.hpp"

namespace nfcad::commands {

namespace {

using namespace util;

nf::Vec3 start_of(const nf::NurbsCurve& c) { return c.evaluate(c.domain_start()); }
nf::Vec3 end_of(const nf::NurbsCurve& c) { return c.evaluate(c.domain_end()); }

double size_of(const std::vector<nf::NurbsCurve>& curves) {
  nf::Vec3 lo{1e300, 1e300, 1e300}, hi{-1e300, -1e300, -1e300};
  for (const auto& c : curves) {
    for (const nf::Vec3& p : c.control_points()) {
      lo = {std::min(lo.x, p.x), std::min(lo.y, p.y), std::min(lo.z, p.z)};
      hi = {std::max(hi.x, p.x), std::max(hi.y, p.y), std::max(hi.z, p.z)};
    }
  }
  return std::max(nf::distance(lo, hi), 1e-9);
}

/// The curves chained head to tail into one closed loop (some reversed), in loop order.
std::vector<nf::NurbsCurve> closed_loop(std::vector<nf::NurbsCurve> curves, double tol) {
  std::vector<nf::NurbsCurve> loop{curves.front()};
  curves.erase(curves.begin());
  while (!curves.empty()) {
    const nf::Vec3 tail = end_of(loop.back());
    auto it = std::find_if(curves.begin(), curves.end(), [&](const nf::NurbsCurve& c) {
      return nf::distance(start_of(c), tail) <= tol || nf::distance(end_of(c), tail) <= tol;
    });
    if (it == curves.end()) throw std::invalid_argument("the edges do not form a closed loop");
    loop.push_back(nf::distance(start_of(*it), tail) <= tol ? *it : it->reversed());
    curves.erase(it);
  }
  if (nf::distance(end_of(loop.back()), start_of(loop.front())) > tol) {
    throw std::invalid_argument("the edges do not form a closed loop");
  }
  return loop;
}

/// Adds the geometry `make` builds; false with the reason in `message` if it fails.
template <class G>
bool add(std::vector<document::Entity>& out, QString& message, const QString& what, const std::function<G()>& make) {
  try {
    out.push_back(document::make_entity(make()));
    return true;
  } catch (const std::exception& e) {
    message = failure(what, e);
    return false;
  }
}

/// The selected curves and points, in selection order.
class InputCommand : public Command {
 public:
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (const auto* c = std::get_if<nf::NurbsCurve>(e.geometry.get())) curves_.push_back(*c);
      if (const auto* p = std::get_if<nf::Vec3>(e.geometry.get())) points_.push_back(*p);
      for (nf::TrimmedSurface& f : kernel::faces_of(*e.geometry)) faces_.push_back(std::move(f));
    }
    if (!accepts()) {
      message_ = QObject::tr("%1: select %2").arg(title(), requirement());
      return false;
    }
    return prepare();
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }

 protected:
  [[nodiscard]] virtual bool accepts() const = 0;
  [[nodiscard]] virtual QString requirement() const = 0;
  virtual bool prepare() { return true; }
  template <class G>
  Result create(const std::function<G()>& make) {
    return add<G>(entities_, message_, title(), make) ? Result::Done : Result::Rejected;
  }
  std::vector<nf::NurbsCurve> curves_;
  std::vector<nf::Vec3> points_;
  std::vector<nf::TrimmedSurface> faces_;
};

// ------------------------------------------------------------------------------ Surface from points
/// Three or four corner points (Enter after three: a triangle, one side collapsed).
class SurfaceFromPointsCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("srfpt"); }
  QString title() const override { return QObject::tr("Surface from points"); }
  QString prompt() const override {
    return pts_.size() < 3 ? QObject::tr("Surface from points: corner %1").arg(pts_.size() + 1)
                           : QObject::tr("Surface from points: corner 4 (Enter: a triangle)");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    for (const Point3& q : pts_) {
      if (dist(q, p) < kEps) return Result::Rejected;
    }
    pts_.push_back(p);
    return pts_.size() == 4 ? create() : Result::Continue;
  }
  Result finish() override { return pts_.size() == 3 ? create() : Result::Cancelled; }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (pts_.empty()) return {};
    Polyline3 q = pts_;
    q.push_back(c);
    q.push_back(pts_.front());
    return {q};
  }
  std::optional<Point3> basePoint() const override {
    return pts_.empty() ? std::nullopt : std::optional(pts_.back());
  }

 private:
  Result create() {
    const nf::Vec3 a = V(pts_[0]), b = V(pts_[1]), c = V(pts_[2]);
    const nf::Vec3 d = pts_.size() == 4 ? V(pts_[3]) : c;
    return add<nf::NurbsSurface>(entities_, message_, title(), [&] { return nf::make_bilinear(a, b, d, c); })
               ? Result::Done
               : Result::Rejected;
  }
  Polyline3 pts_;
};

// ------------------------------------------------------------------------------ Edge surface
/// Two, three or four selected edge curves (in any order and direction): ruled, a three-sided
/// patch, or a Coons patch.
class EdgeSurfaceCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("edgesrf"); }
  QString title() const override { return QObject::tr("Edge surface"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    return create<nf::NurbsSurface>([&] { return edge_surface(curves_); });
  }

  static nf::NurbsSurface edge_surface(const std::vector<nf::NurbsCurve>& c) {
    const double tol = 1e-6 * size_of(c);
    if (c.size() == 2) {
      // run both the same way
      const bool flip = nf::distance(start_of(c[0]), end_of(c[1])) + nf::distance(end_of(c[0]), start_of(c[1])) <
                        nf::distance(start_of(c[0]), start_of(c[1])) + nf::distance(end_of(c[0]), end_of(c[1]));
      return nf::ruled(c[0], flip ? c[1].reversed() : c[1]);
    }
    const std::vector<nf::NurbsCurve> loop = closed_loop(c, tol);
    if (loop.size() == 3) return nf::triangle_patch(loop[0], loop[1], loop[2], tol);
    // loop: 00 -> 10 -> 11 -> 01 -> 00; Coons: c0 (v = 0), c1 (v = 1), d0 (u = 0), d1 (u = 1)
    return nf::coons(loop[0], loop[2].reversed(), loop[3].reversed(), loop[1], tol);
  }

 protected:
  bool accepts() const override { return curves_.size() >= 2 && curves_.size() <= 4; }
  QString requirement() const override { return QObject::tr("two, three or four edge curves"); }
};

// ------------------------------------------------------------------------------ Planar surface
/// Planar surfaces bounded by the selected closed planar curves; a curve inside another is a
/// hole (by nesting depth).
class PlanarSurfaceCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("planarsrf"); }
  QString title() const override { return QObject::tr("Planar surface"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    try {
      for (const nf::TrimmedSurface& f : kernel::planar_faces(curves_)) entities_.push_back(document::make_entity(f));
      return Result::Done;
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }

 protected:
  bool accepts() const override { return !curves_.empty(); }
  QString requirement() const override { return QObject::tr("closed planar curves"); }
};

// ------------------------------------------------------------------------------ Patch
/// A smooth surface fitted to the selected curves (sampled) and points; the typed smoothing
/// (Enter: 0.001) trades closeness for smoothness.
class PatchCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("patch"); }
  QString title() const override { return QObject::tr("Patch"); }
  QString prompt() const override { return QObject::tr("Patch: smoothing (Enter: 0.001; 0.1 … 1 for noisy data)"); }
  Result number(double s) override {
    if (s < 0) return Result::Rejected;
    std::vector<nf::Vec3> pts = points_;
    for (const nf::NurbsCurve& c : curves_) {
      for (const nf::Vec3& p : c.sample(60)) pts.push_back(p);
    }
    nf::SurfaceFitOptions o;
    o.smoothing = s;
    double err = 0;
    const Result r = create<nf::NurbsSurface>([&] {
      const nf::FittedSurface f = nf::fit_surface(pts, o);
      err = f.max_error;
      return f.surface;
    });
    if (r == Result::Done) message_ = QObject::tr("Patch: largest distance of the input %1").arg(err, 0, 'g', 3);
    return r;
  }
  Result finish() override { return number(1e-3); }

 protected:
  bool accepts() const override { return !curves_.empty() || points_.size() >= 3; }
  QString requirement() const override { return QObject::tr("curves and / or at least three points"); }
};

// ------------------------------------------------------------------------------ Rail revolve
/// The profile (first selected curve) revolved about an axis (two points) while its far end
/// follows the rail (second selected curve).
class RailRevolveCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("railrevolve"); }
  QString title() const override { return QObject::tr("Rail revolve"); }
  QString prompt() const override {
    return axis_start_ ? QObject::tr("Rail revolve: axis end") : QObject::tr("Rail revolve: axis start");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!axis_start_) {
      axis_start_ = p;
      return Result::Continue;
    }
    if (dist(*axis_start_, p) < kEps) return Result::Rejected;
    return create<nf::NurbsSurface>([&] {
      return nf::rail_revolve(curves_[0], curves_[1], V(*axis_start_), nf::normalized(V(p) - V(*axis_start_)));
    });
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (!axis_start_) return {};
    return {{*axis_start_, c}};
  }
  std::optional<Point3> basePoint() const override { return axis_start_; }

 protected:
  bool accepts() const override { return curves_.size() == 2; }
  QString requirement() const override { return QObject::tr("the profile, then the rail"); }

 private:
  std::optional<Point3> axis_start_;
};

// ------------------------------------------------------------------------------ Extrusions
/// Extrude along curve: the profile (first selected curve) moved along the path (second) without
/// turning – an exact translational sweep.
class ExtrudeAlongCurveCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("extrude_along"); }
  QString title() const override { return QObject::tr("Extrude along curve"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    return create<nf::NurbsSurface>([&] { return nf::sweep_translational(curves_[0], curves_[1]); });
  }

 protected:
  bool accepts() const override { return curves_.size() == 2; }
  QString requirement() const override { return QObject::tr("the profile, then the path"); }
};

/// Extrude to point: every selected curve to the clicked apex (a cone over the curve).
class ExtrudeToPointCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("extrude_to_point"); }
  QString title() const override { return QObject::tr("Extrude to point"); }
  QString prompt() const override { return QObject::tr("Extrude to point: apex"); }
  Result point(const Point3& p, const PlaneFrame&) override {
    try {
      for (const nf::NurbsCurve& c : curves_) entities_.push_back(document::make_entity(nf::extrude_to_point(c, V(p))));
      return Result::Done;
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    std::vector<Polyline3> out;
    for (const nf::NurbsCurve& k : curves_) {
      for (const nf::Vec3& q : k.sample(9)) out.push_back({P(q), c});
    }
    return out;
  }

 protected:
  bool accepts() const override { return !curves_.empty(); }
  QString requirement() const override { return QObject::tr("curves"); }
};

/// Extrude tapered: planar curves along the construction plane's normal with a draft angle
/// (degrees, Enter: 5; positive: the section grows), then the height (number or point).
class ExtrudeTaperedCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("extrude_tapered"); }
  QString title() const override { return QObject::tr("Extrude tapered"); }
  QString prompt() const override {
    return angle_ ? QObject::tr("Extrude tapered (%1°): height (number or point)").arg(*angle_)
                  : QObject::tr("Extrude tapered: draft angle in degrees (Enter: 5)");
  }
  Result number(double v) override {
    if (!angle_) {
      if (std::abs(v) >= 89) return Result::Rejected;
      angle_ = v;
      return Result::Continue;
    }
    return extrude(V(viewPlane().n) * v);
  }
  Result finish() override {
    if (angle_) return Result::Cancelled;
    angle_ = 5.0;
    return Result::Continue;
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!angle_) return Result::Rejected;
    const nf::Vec3 base = start_of(curves_.front());
    return extrude(V(plane.n) * nf::dot(V(p) - base, V(plane.n)));
  }

 protected:
  bool accepts() const override { return !curves_.empty(); }
  QString requirement() const override { return QObject::tr("planar curves"); }

 private:
  Result extrude(const nf::Vec3& dir) {
    if (nf::norm(dir) < kEps) return Result::Rejected;
    try {
      const double rad = *angle_ * std::numbers::pi / 180.0;
      for (const nf::NurbsCurve& c : curves_) {
        for (const nf::NurbsSurface& s : nf::extrude_tapered(c, dir, rad, 1e-7 * size_of({c}))) {
          entities_.push_back(document::make_entity(s));
        }
      }
      return Result::Done;
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::optional<double> angle_;
};

/// Extrude surface: the selected surfaces moved by the typed distance along the construction
/// plane's normal (or from a point to a point), closed by side walls into a solid.
class ExtrudeSurfaceCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("extrudesrf"); }
  QString title() const override { return QObject::tr("Extrude surface"); }
  QString prompt() const override {
    return from_ ? QObject::tr("Extrude surface: point to extrude to")
                 : QObject::tr("Extrude surface: distance along the plane's normal, or a point to extrude from");
  }
  Result number(double d) override { return d == 0 ? Result::Rejected : extrude(V(viewPlane().n) * d); }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!from_) {
      from_ = p;
      return Result::Continue;
    }
    return extrude(V(p) - V(*from_));
  }
  std::optional<Point3> basePoint() const override { return from_; }

  /// The faces, their copies moved by `dir`, and ruled walls along every boundary loop, sewn.
  static nf::Shell extruded(const std::vector<nf::TrimmedSurface>& faces, const nf::Vec3& dir) {
    std::vector<nf::TrimmedSurface> all = faces;
    const nf::Transform move = nf::Transform::translation(dir);
    for (const nf::TrimmedSurface& f : faces) {
      all.push_back(f.transformed(move).flipped());
      for (const auto& loop : f.boundary_curves()) {
        for (const nf::NurbsCurve& c : loop) all.emplace_back(nf::extrude(c, dir));
      }
    }
    return nf::Shell::sew(all, 1e-6).oriented();
  }

 protected:
  bool accepts() const override { return !faces_.empty(); }
  QString requirement() const override { return QObject::tr("surfaces"); }

 private:
  Result extrude(const nf::Vec3& dir) {
    if (nf::norm(dir) < kEps) return Result::Rejected;
    return create<nf::Shell>([&] { return extruded(faces_, dir); });
  }
  std::optional<Point3> from_;
};

// ------------------------------------------------------------------------------ Pipe
/// Pipe: solid pipes along the selected curves; start radius, then end radius (Enter: the same).
class PipeCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("pipe"); }
  QString title() const override { return QObject::tr("Pipe"); }
  QString prompt() const override {
    return r0_ ? QObject::tr("Pipe: end radius (Enter: %1)").arg(*r0_) : QObject::tr("Pipe: start radius");
  }
  Result number(double r) override {
    if (r <= 0) return Result::Rejected;
    if (!r0_) {
      r0_ = r;
      return Result::Continue;
    }
    return pipes(r);
  }
  Result finish() override { return r0_ ? pipes(*r0_) : Result::Cancelled; }

 protected:
  bool accepts() const override { return !curves_.empty(); }
  QString requirement() const override { return QObject::tr("curves"); }

 private:
  Result pipes(double r1) {
    try {
      for (const nf::NurbsCurve& c : curves_) {
        entities_.push_back(document::make_entity(nf::make_pipe(c, *r0_, r1, 1e-6 * size_of({c}))));
      }
      return Result::Done;
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::optional<double> r0_;
};

// ------------------------------------------------------------------------------ Point grid
/// Surface from point grid: the selected points, row by row in selection order, interpolated;
/// the typed number is the number of points per row.
class PointGridCommand : public InputCommand {
 public:
  QString id() const override { return QStringLiteral("srfptgrid"); }
  QString title() const override { return QObject::tr("Surface from point grid"); }
  QString prompt() const override {
    return QObject::tr("Point grid (%1 points): points per row").arg(points_.size());
  }
  Result number(double v) override {
    if (std::floor(v) != v || v < 2) return Result::Rejected;
    const auto per_row = static_cast<std::size_t>(v);
    if (points_.size() % per_row != 0 || points_.size() / per_row < 2) {
      message_ = QObject::tr("Point grid: %1 points are not rows of %2").arg(points_.size()).arg(per_row);
      return Result::Rejected;
    }
    const std::size_t rows = points_.size() / per_row;
    return create<nf::NurbsSurface>([&] {
      return nf::interpolate_surface(points_, rows, per_row, std::min<std::size_t>(3, rows - 1),
                                     std::min<std::size_t>(3, per_row - 1));
    });
  }

 protected:
  bool accepts() const override { return points_.size() >= 4; }
  QString requirement() const override { return QObject::tr("at least four points, row by row"); }
};

// ------------------------------------------------------------------------------ Ellipsoid, Paraboloid
/// Ellipsoid: centre, end of the first axis, then the second and third semi-axes (points: their
/// distances; numbers). Exact: the sphere scaled along the three axes.
class EllipsoidCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("ellipsoid"); }
  QString title() const override { return QObject::tr("Ellipsoid"); }
  QString prompt() const override {
    if (!centre_) return QObject::tr("Ellipsoid: centre");
    if (!a_) return QObject::tr("Ellipsoid: end of the first axis");
    if (!b_) return QObject::tr("Ellipsoid: second semi-axis (point or length)");
    return QObject::tr("Ellipsoid: third semi-axis along the plane's normal (point or length)");
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!centre_) {
      centre_ = p;
      plane_ = plane;
      return Result::Continue;
    }
    const nf::Vec3 d = V(p) - V(*centre_);
    if (!a_) {
      const nf::Vec3 a = in_plane(p, *centre_, plane_);
      if (nf::norm(a) < kEps) return Result::Rejected;
      a_ = a;
      return Result::Continue;
    }
    if (!b_) return length(nf::norm(d - nf::normalized(*a_) * nf::dot(d, nf::normalized(*a_))));
    return length(std::abs(nf::dot(d, V(plane_.n))));
  }
  Result number(double v) override { return centre_ && a_ ? length(v) : Result::Rejected; }
  std::optional<Point3> basePoint() const override { return centre_; }

  /// The ellipsoid with semi-axis vectors a, b, c (perpendicular) about `centre`.
  static nf::Shell ellipsoid(const nf::Vec3& centre, const nf::Vec3& a, const nf::Vec3& b, const nf::Vec3& c) {
    const nf::Transform t({a.x, b.x, c.x, centre.x, a.y, b.y, c.y, centre.y, a.z, b.z, c.z, centre.z});
    return std::get<nf::Shell>(kernel::transformed(nf::make_sphere({0, 0, 0}, 1.0), t));
  }

 private:
  Result length(double v) {
    if (v <= kEps) return Result::Rejected;
    if (!b_) {
      b_ = v;
      return Result::Continue;
    }
    const nf::Vec3 a = *a_;
    const nf::Vec3 b = nf::normalized(nf::cross(V(plane_.n), a)) * *b_;
    const nf::Vec3 c = V(plane_.n) * v;
    return add<nf::Shell>(entities_, message_, title(), [&] { return ellipsoid(V(*centre_), a, b, c); })
               ? Result::Done
               : Result::Rejected;
  }
  std::optional<Point3> centre_;
  std::optional<nf::Vec3> a_;
  std::optional<double> b_;
  PlaneFrame plane_;
};

/// Paraboloid: vertex, focus (axis and focal length), then the rim radius (point or number) – a
/// dish, exact (the parabola revolved about its axis).
class ParaboloidCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("paraboloid"); }
  QString title() const override { return QObject::tr("Paraboloid"); }
  QString prompt() const override {
    if (!vertex_) return QObject::tr("Paraboloid: vertex");
    if (!focus_) return QObject::tr("Paraboloid: focus");
    return QObject::tr("Paraboloid: rim radius (point or number)");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!vertex_) {
      vertex_ = p;
      return Result::Continue;
    }
    if (!focus_) {
      if (dist(*vertex_, p) < kEps) return Result::Rejected;
      focus_ = p;
      return Result::Continue;
    }
    const nf::Vec3 axis = nf::normalized(V(*focus_) - V(*vertex_));
    const nf::Vec3 d = V(p) - V(*vertex_);
    return rim(nf::norm(d - axis * nf::dot(d, axis)));
  }
  Result number(double r) override { return focus_ ? rim(r) : Result::Rejected; }
  std::optional<Point3> basePoint() const override { return vertex_; }

  /// z = r² / (4 f) about `vertex` along `axis`, out to radius r: the half parabola revolved.
  static nf::NurbsSurface paraboloid(const nf::Vec3& vertex, const nf::Vec3& axis, double f, double r) {
    const nf::Vec3 side = nf::any_perpendicular(axis);
    const double h = r * r / (4.0 * f);
    // the half parabola from the vertex to the rim: a quadratic Bézier (tangent at the vertex ⟂ axis)
    const nf::NurbsCurve half(2, {0, 0, 0, 1, 1, 1}, {vertex, vertex + side * (0.5 * r), vertex + side * r + axis * h});
    return nf::revolve(half, vertex, axis, 2.0 * std::numbers::pi);
  }

 private:
  Result rim(double r) {
    if (r <= kEps) return Result::Rejected;
    const nf::Vec3 axis = nf::normalized(V(*focus_) - V(*vertex_));
    const double f = dist(*vertex_, *focus_);
    return add<nf::NurbsSurface>(entities_, message_, title(), [&] { return paraboloid(V(*vertex_), axis, f, r); })
               ? Result::Done
               : Result::Rejected;
  }
  std::optional<Point3> vertex_, focus_;
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"srfpt", {"surfacefrompoints"}, [] { return std::make_unique<SurfaceFromPointsCommand>(); }},
      {"edgesrf", {"edgesurface"}, [] { return std::make_unique<EdgeSurfaceCommand>(); }},
      {"planarsrf", {"planarsurface"}, [] { return std::make_unique<PlanarSurfaceCommand>(); }},
      {"patch", {}, [] { return std::make_unique<PatchCommand>(); }},
      {"railrevolve", {}, [] { return std::make_unique<RailRevolveCommand>(); }},
      {"extrude_along", {"extrudecrvalongcrv", "extrudealong"}, [] { return std::make_unique<ExtrudeAlongCurveCommand>(); }},
      {"extrude_to_point", {"extrudecrvtopoint", "extrudetopoint"}, [] { return std::make_unique<ExtrudeToPointCommand>(); }},
      {"extrude_tapered", {"extrudecrvtapered", "extrudetapered"}, [] { return std::make_unique<ExtrudeTaperedCommand>(); }},
      {"extrudesrf", {"extrudesurface"}, [] { return std::make_unique<ExtrudeSurfaceCommand>(); }},
      {"pipe", {}, [] { return std::make_unique<PipeCommand>(); }},
      {"srfptgrid", {"frompointgrid", "pointgrid"}, [] { return std::make_unique<PointGridCommand>(); }},
      {"ellipsoid", {}, [] { return std::make_unique<EllipsoidCommand>(); }},
      {"paraboloid", {}, [] { return std::make_unique<ParaboloidCommand>(); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_surface_create_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList surface_create_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
