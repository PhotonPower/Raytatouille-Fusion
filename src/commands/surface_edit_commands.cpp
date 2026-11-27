// Editing surfaces (docs/commands.md, "Editing surfaces"): Untrim, Extract surface, Shrink trimmed
// surface, Extend surface, Rebuild surface (and in one direction), Change surface degree, Slab,
// Thicken, Make hollow.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <exception>
#include <functional>
#include <limits>
#include <nurbforge/analysis/closest_point.hpp>
#include <nurbforge/geometry/primitives.hpp>
#include <nurbforge/geometry/transform.hpp>
#include <nurbforge/modeling/construct.hpp>
#include <nurbforge/modeling/extend.hpp>
#include <nurbforge/modeling/offset.hpp>
#include <nurbforge/modeling/surface_tools.hpp>
#include <nurbforge/topology/solid_ops.hpp>
#include <nurbforge/topology/trimmed_surface.hpp>

#include "commands/command_util.hpp"
#include "kernel/geometry_ops.hpp"

namespace nfcad::commands {

namespace {

using namespace util;

using Geometry = document::Geometry;

std::shared_ptr<const Geometry> shared(Geometry g) { return std::make_shared<const Geometry>(std::move(g)); }

/// The selected surfaces – plain or trimmed – with their entity ids (a plain one counts as an
/// untrimmed face).
class FacesCommand : public Command {
 public:
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (const auto* s = std::get_if<nf::NurbsSurface>(e.geometry.get())) {
        faces_.emplace_back(*s);
        ids_.push_back(e.id);
      } else if (const auto* f = std::get_if<nf::TrimmedSurface>(e.geometry.get())) {
        faces_.push_back(*f);
        ids_.push_back(e.id);
      }
    }
    if (faces_.empty()) {
      message_ = QObject::tr("%1: select surfaces").arg(title());
      return false;
    }
    return prepare();
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }

 protected:
  virtual bool prepare() { return true; }
  /// Replaces every face by `edit` of it; on failure nothing changes.
  Result each(const std::function<Geometry(const nf::TrimmedSurface&)>& edit) {
    try {
      for (std::size_t i = 0; i < faces_.size(); ++i) replace_.emplace_back(ids_[i], shared(edit(faces_[i])));
      return Result::Done;
    } catch (const std::exception& e) {
      replace_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::vector<nf::TrimmedSurface> faces_;
  std::vector<document::EntityId> ids_;
};

// ------------------------------------------------------------------------------ Untrim
/// Untrim: a click near a hole of a selected trimmed surface removes that hole; Enter removes
/// every trim (the whole underlying surface comes back).
class UntrimCommand : public FacesCommand {
 public:
  QString id() const override { return QStringLiteral("untrim"); }
  QString title() const override { return QObject::tr("Untrim"); }
  QString prompt() const override { return QObject::tr("Untrim: click near a hole to remove it (Enter: remove every trim)"); }
  Result point(const Point3& p, const PlaneFrame&) override {
    // the hole whose boundary passes nearest the click
    std::size_t best_face = 0, best_hole = 0;
    double d = std::numeric_limits<double>::infinity();
    for (std::size_t i = 0; i < faces_.size(); ++i) {
      const auto loops = faces_[i].boundary_curves();
      for (std::size_t h = 1; h < loops.size(); ++h) {  // loop 0: the outer boundary
        for (const nf::NurbsCurve& c : loops[h]) {
          const double dc = nf::closest_point(c, V(p)).distance;
          if (dc < d) {
            d = dc;
            best_face = i;
            best_hole = h - 1;
          }
        }
      }
    }
    if (!std::isfinite(d)) {
      message_ = QObject::tr("Untrim: the surfaces have no holes – Enter removes the outer trim");
      return Result::Rejected;
    }
    const nf::TrimmedSurface& f = faces_[best_face];
    std::vector<nf::TrimLoop> holes = f.holes();
    holes.erase(holes.begin() + static_cast<std::ptrdiff_t>(best_hole));
    faces_[best_face] = nf::TrimmedSurface(f.surface(), f.outer(), holes);
    replace_.emplace_back(ids_[best_face], shared(faces_[best_face]));
    return Result::Done;
  }
  Result finish() override {
    return each([](const nf::TrimmedSurface& f) -> Geometry { return f.surface(); });
  }
};

// ------------------------------------------------------------------------------ Extract surface
/// Extract surface: the picked faces of a solid (Ctrl+Shift-click) become surfaces of their own;
/// the solid keeps the rest (it is open then).
class ExtractSurfaceCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("extractsrf"); }
  QString title() const override { return QObject::tr("Extract surface"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool usesFaces() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>&) override {
    if (picked_faces_.empty()) {
      message_ = QObject::tr("Extract surface: pick faces of a solid (Ctrl+Shift-click)");
      return false;
    }
    try {
      for (const GripSet& g : picked_faces_) {
        const auto& shell = std::get<nf::Shell>(*g.geometry);
        std::vector<nf::TrimmedSurface> keep;
        for (std::size_t i = 0; i < shell.faces().size(); ++i) {
          const bool picked = std::find(g.indices.begin(), g.indices.end(), static_cast<int>(i)) != g.indices.end();
          if (picked) {
            entities_.push_back(document::make_entity(shell.faces()[i]));
          } else {
            keep.push_back(shell.faces()[i]);
          }
        }
        if (keep.empty()) {
          remove_.push_back(g.id);
        } else {
          replace_.emplace_back(g.id, shared(nf::Shell::sew(keep, 1e-6)));
        }
      }
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return false;
    }
    select_ = std::vector<document::SelectionItem>{};  // the face indices are gone
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }
};

// ------------------------------------------------------------------------------ Shrink
/// The trimmed surface on the smallest piece of its surface that holds its trim (the parameter
/// rectangle around the outer loop); the trim curves keep their parameters.
nf::TrimmedSurface shrunk(const nf::TrimmedSurface& f) {
  if (f.is_untrimmed()) return f;
  double u0 = 1e300, u1 = -1e300, v0 = 1e300, v1 = -1e300;
  for (const auto& p : f.outer().polyline(32)) {
    u0 = std::min(u0, p[0]);
    u1 = std::max(u1, p[0]);
    v0 = std::min(v0, p[1]);
    v1 = std::max(v1, p[1]);
  }
  nf::NurbsSurface s = f.surface();
  const auto du = s.domain_u(), dv = s.domain_v();
  const double eu = 1e-9 * (du[1] - du[0]), ev = 1e-9 * (dv[1] - dv[0]);
  if (u0 > du[0] + eu) s = s.split_u(u0).second;
  if (u1 < du[1] - eu) s = s.split_u(u1).first;
  if (v0 > dv[0] + ev) s = s.split_v(v0).second;
  if (v1 < dv[1] - ev) s = s.split_v(v1).first;
  return nf::TrimmedSurface(s, f.outer(), f.holes());
}

class ShrinkCommand : public FacesCommand {
 public:
  QString id() const override { return QStringLiteral("shrinktrimmedsrf"); }
  QString title() const override { return QObject::tr("Shrink trimmed surface"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override { return each([](const nf::TrimmedSurface& f) -> Geometry { return shrunk(f); }); }
};

// ------------------------------------------------------------------------------ Extend surface
/// Extend surface: click near an edge of a selected untrimmed surface, then the length (number or
/// a point's distance from the edge); the natural continuation.
class ExtendSurfaceCommand : public FacesCommand {
 public:
  QString id() const override { return QStringLiteral("extendsrf"); }
  QString title() const override { return QObject::tr("Extend surface"); }
  QString prompt() const override {
    return side_ ? QObject::tr("Extend surface: length (number or a point)")
                 : QObject::tr("Extend surface: click near the edge to extend");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!side_) {
      double d = std::numeric_limits<double>::infinity();
      for (std::size_t i = 0; i < faces_.size(); ++i) {
        for (nf::SurfaceSide side : {nf::SurfaceSide::UMin, nf::SurfaceSide::UMax, nf::SurfaceSide::VMin, nf::SurfaceSide::VMax}) {
          const double ds = nf::closest_point(edge(faces_[i].surface(), side), V(p)).distance;
          if (ds < d) {
            d = ds;
            index_ = i;
            side_ = side;
          }
        }
      }
      return Result::Continue;
    }
    return create(nf::closest_point(edge(faces_[index_].surface(), *side_), V(p)).distance);
  }
  Result number(double v) override { return side_ ? create(v) : Result::Rejected; }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (side_) return {};
    // the edge the click would take
    std::optional<nf::NurbsCurve> best;
    double d = std::numeric_limits<double>::infinity();
    for (const auto& f : faces_) {
      for (nf::SurfaceSide side : {nf::SurfaceSide::UMin, nf::SurfaceSide::UMax, nf::SurfaceSide::VMin, nf::SurfaceSide::VMax}) {
        const nf::NurbsCurve e = edge(f.surface(), side);
        const double de = nf::closest_point(e, V(c)).distance;
        if (de < d) {
          d = de;
          best = e;
        }
      }
    }
    return best ? std::vector<Polyline3>{sample(*best, 64)} : std::vector<Polyline3>{};
  }

  static nf::NurbsCurve edge(const nf::NurbsSurface& s, nf::SurfaceSide side) {
    switch (side) {
      case nf::SurfaceSide::UMin: return s.iso_curve_u(s.domain_u()[0]);
      case nf::SurfaceSide::UMax: return s.iso_curve_u(s.domain_u()[1]);
      case nf::SurfaceSide::VMin: return s.iso_curve_v(s.domain_v()[0]);
      case nf::SurfaceSide::VMax: break;
    }
    return s.iso_curve_v(s.domain_v()[1]);
  }

 protected:
  bool prepare() override {
    for (const auto& f : faces_) {
      if (!f.is_untrimmed()) {
        message_ = QObject::tr("Extend surface: the surfaces must be untrimmed (Untrim or Shrink first)");
        return false;
      }
    }
    return true;
  }

 private:
  Result create(double length) {
    if (length <= 0) return Result::Rejected;
    try {
      replace_.emplace_back(ids_[index_], shared(nf::extend(faces_[index_].surface(), *side_, length)));
      return Result::Done;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::size_t index_ = 0;
  std::optional<nf::SurfaceSide> side_;
};

// ------------------------------------------------------------------------------ Rebuild, Change degree
/// Rebuild surface: the typed control-point counts in u, then v (Enter: as many as u), degree 3;
/// Rebuild UV: only in one direction (typed: 1 for u, 2 for v; then the count), the other kept.
/// Trims stay (the parameters are kept).
class RebuildSurfaceCommand : public FacesCommand {
 public:
  explicit RebuildSurfaceCommand(bool one_direction) : one_(one_direction) {}
  QString id() const override { return one_ ? QStringLiteral("rebuilduv") : QStringLiteral("rebuildsrf"); }
  QString title() const override { return one_ ? QObject::tr("Rebuild surface in one direction") : QObject::tr("Rebuild surface"); }
  QString prompt() const override {
    const auto& s = faces_.front().surface();
    if (one_) {
      return dir_ ? QObject::tr("Rebuild %1: number of control points").arg(*dir_ == 1 ? "u" : "v")
                  : QObject::tr("Rebuild UV: direction (1: u, now %1 points; 2: v, now %2)").arg(s.num_u()).arg(s.num_v());
    }
    return nu_ ? QObject::tr("Rebuild surface: control points in v (Enter: %1)").arg(*nu_)
               : QObject::tr("Rebuild surface: control points in u (now %1 × %2)").arg(s.num_u()).arg(s.num_v());
  }
  Result number(double v) override {
    if (std::floor(v) != v) return Result::Rejected;
    if (one_ && !dir_) {
      if (v != 1 && v != 2) return Result::Rejected;
      dir_ = static_cast<int>(v);
      return Result::Continue;
    }
    if (v < 4 || v > 1000) {
      message_ = QObject::tr("%1: between 4 and 1000 control points").arg(title());
      return Result::Rejected;
    }
    const auto n = static_cast<std::size_t>(v);
    if (one_) return create([&](const nf::NurbsSurface& s) {
      return *dir_ == 1 ? std::pair{n, s.num_v()} : std::pair{s.num_u(), n};
    });
    if (!nu_) {
      nu_ = n;
      return Result::Continue;
    }
    return create([&](const nf::NurbsSurface&) { return std::pair{*nu_, n}; });
  }
  Result finish() override {
    if (!one_ && nu_) return create([&](const nf::NurbsSurface&) { return std::pair{*nu_, *nu_}; });
    return Result::Cancelled;
  }

 private:
  Result create(const std::function<std::pair<std::size_t, std::size_t>(const nf::NurbsSurface&)>& counts) {
    double worst = 0;
    const Result r = each([&](const nf::TrimmedSurface& f) -> Geometry {
      const auto [nu, nv] = counts(f.surface());
      const nf::RebuiltSurface rb = nf::rebuild_surface(f.surface(), nu, nv);
      worst = std::max(worst, rb.max_error);
      if (f.is_untrimmed()) return rb.surface;
      return nf::TrimmedSurface(rb.surface, f.outer(), f.holes());
    });
    if (r == Result::Done) message_ = QObject::tr("%1: largest deviation %2").arg(title()).arg(worst, 0, 'g', 3);
    return r;
  }
  bool one_;
  std::optional<int> dir_;
  std::optional<std::size_t> nu_;
};

/// Change surface degree: the degree in u, then in v (Enter: the same); raising is exact,
/// lowering approximates within 0.1 % of the surface's size.
class ChangeSurfaceDegreeCommand : public FacesCommand {
 public:
  QString id() const override { return QStringLiteral("changedegreesrf"); }
  QString title() const override { return QObject::tr("Change surface degree"); }
  QString prompt() const override {
    const auto& s = faces_.front().surface();
    return pu_ ? QObject::tr("Change surface degree: degree in v (Enter: %1)").arg(*pu_)
               : QObject::tr("Change surface degree: degree in u (now %1 × %2)").arg(s.degree_u()).arg(s.degree_v());
  }
  Result number(double v) override {
    if (std::floor(v) != v || v < 1 || v > 11) return Result::Rejected;
    if (!pu_) {
      pu_ = static_cast<std::size_t>(v);
      return Result::Continue;
    }
    return create(static_cast<std::size_t>(v));
  }
  Result finish() override { return pu_ ? create(*pu_) : Result::Cancelled; }

 private:
  Result create(std::size_t pv) {
    return each([&](const nf::TrimmedSurface& f) -> Geometry {
      nf::NurbsSurface s = f.surface();
      double size = 0;
      for (const nf::Vec3& p : s.control_points()) size = std::max(size, nf::norm(p - s.control_points().front()));
      const double tol = 1e-3 * std::max(size, 1e-9);
      while (s.degree_u() < *pu_) s = s.elevate_degree_u(*pu_ - s.degree_u());
      while (s.degree_u() > *pu_) s = s.reduce_degree_u(tol);
      while (s.degree_v() < pv) s = s.elevate_degree_v(pv - s.degree_v());
      while (s.degree_v() > pv) s = s.reduce_degree_v(tol);
      if (f.is_untrimmed()) return s;
      return nf::TrimmedSurface(s, f.outer(), f.holes());
    });
  }
  std::optional<std::size_t> pu_;
};

// ------------------------------------------------------------------------------ Slab, Thicken, Hollow
/// Slab: a wall along each selected planar curve – the curve offset by the typed thickness to
/// the side of the click (in the construction plane), closed and extruded by the typed height
/// along the plane's normal.
class SlabCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("slab"); }
  QString title() const override { return QObject::tr("Slab"); }
  QString prompt() const override {
    if (!thickness_) return QObject::tr("Slab: wall thickness");
    if (!side_) return QObject::tr("Slab (thickness %1): click the side of the wall").arg(*thickness_);
    return QObject::tr("Slab: height (negative: downwards)");
  }
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (const auto* c = std::get_if<nf::NurbsCurve>(e.geometry.get())) curves_.push_back(*c);
    }
    if (curves_.empty()) {
      message_ = QObject::tr("Slab: select planar curves");
      return false;
    }
    return true;
  }
  Result number(double v) override {
    if (!thickness_) {
      if (v <= 0) return Result::Rejected;
      thickness_ = v;
      return Result::Continue;
    }
    if (!side_ || v == 0) return Result::Rejected;
    try {
      for (const nf::NurbsCurve& c : curves_) entities_.push_back(document::make_entity(slab(c, *side_ * *thickness_, plane_, v)));
      return Result::Done;
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!thickness_ || side_) return Result::Rejected;
    plane_ = plane;
    const nf::NurbsCurve& c = curves_.front();
    const nf::CurvePoint foot = nf::closest_point(c, V(p));
    side_ = nf::dot(nf::cross(V(plane.n), c.tangent(foot.u)), V(p) - foot.point) >= 0 ? 1.0 : -1.0;
    return Result::Continue;
  }

  /// The wall: the region between the curve and its offset (a closed curve: a ring; an open one:
  /// closed by the two end lines), extruded by `height` along the plane normal.
  static nf::Shell slab(const nf::NurbsCurve& c, double offset, const PlaneFrame& plane, double height) {
    const nf::Vec3 n = V(plane.n);
    const nf::NurbsCurve o = nf::offset_curve(c, offset, n, 1e-7);
    const nf::Vec3 c0 = c.evaluate(c.domain_start()), c1 = c.evaluate(c.domain_end());
    std::vector<nf::NurbsCurve> loops;
    if (nf::distance(c0, c1) <= 1e-9 * std::max(1.0, nf::norm(c0))) {
      loops = {c, o};  // a ring: the offset is the inner or the outer boundary
    } else {
      const nf::Vec3 o0 = o.evaluate(o.domain_start()), o1 = o.evaluate(o.domain_end());
      loops = {kernel::join_chain({c, nf::make_line(c1, o1), o.reversed(), nf::make_line(o0, c0)})};
    }
    std::vector<nf::TrimmedSurface> base = kernel::planar_faces(loops);
    std::vector<nf::TrimmedSurface> all = base;
    const nf::Transform move = nf::Transform::translation(n * height);
    for (const nf::TrimmedSurface& f : base) {
      all.push_back(f.transformed(move).flipped());
      for (const auto& loop : f.boundary_curves()) {
        for (const nf::NurbsCurve& e : loop) all.emplace_back(nf::extrude(e, n * height));
      }
    }
    return nf::Shell::sew(all, 1e-6).oriented();
  }

 private:
  std::vector<nf::NurbsCurve> curves_;
  std::optional<double> thickness_;
  std::optional<double> side_;
  PlaneFrame plane_;
};

/// Thicken: the selected surfaces (or open solids) given a wall of the typed thickness along
/// their normal (negative: the other way) – a solid. Make hollow: a closed solid gets an inner
/// void of the typed wall thickness. Both need faces that join smoothly.
class ThickenCommand : public Command {
 public:
  explicit ThickenCommand(bool hollow) : hollow_(hollow) {}
  QString id() const override { return hollow_ ? QStringLiteral("makehollow") : QStringLiteral("thicken"); }
  QString title() const override { return hollow_ ? QObject::tr("Make hollow") : QObject::tr("Thicken"); }
  QString prompt() const override {
    return hollow_ ? QObject::tr("Make hollow: wall thickness")
                   : QObject::tr("Thicken: thickness along the normal (negative: the other side)");
  }
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      const auto faces = kernel::faces_of(*e.geometry);
      if (faces.empty()) continue;
      const auto* shell = std::get_if<nf::Shell>(e.geometry.get());
      if (hollow_ && (shell == nullptr || !shell->is_closed())) continue;
      shells_.push_back(shell != nullptr ? *shell : nf::Shell::sew(faces, 1e-6));
      ids_.push_back(e.id);
    }
    if (shells_.empty()) {
      message_ = hollow_ ? QObject::tr("Make hollow: select closed solids") : QObject::tr("Thicken: select surfaces");
      return false;
    }
    return true;
  }
  Result number(double t) override {
    if (t == 0 || (hollow_ && t < 0)) return Result::Rejected;
    try {
      for (std::size_t i = 0; i < shells_.size(); ++i) {
        replace_.emplace_back(ids_[i], shared(hollow_ ? nf::hollow(shells_[i], t) : nf::thicken(shells_[i], t)));
      }
      return Result::Done;
    } catch (const std::exception& e) {
      replace_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }

 private:
  bool hollow_;
  std::vector<nf::Shell> shells_;
  std::vector<document::EntityId> ids_;
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"untrim", {}, [] { return std::make_unique<UntrimCommand>(); }},
      {"extractsrf", {"extractsurface"}, [] { return std::make_unique<ExtractSurfaceCommand>(); }},
      {"shrinktrimmedsrf", {"shrink", "shrinksrf"}, [] { return std::make_unique<ShrinkCommand>(); }},
      {"extendsrf", {"extendsurface"}, [] { return std::make_unique<ExtendSurfaceCommand>(); }},
      {"rebuildsrf", {"rebuildsurface"}, [] { return std::make_unique<RebuildSurfaceCommand>(false); }},
      {"rebuilduv", {}, [] { return std::make_unique<RebuildSurfaceCommand>(true); }},
      {"changedegreesrf", {"changesurfacedegree"}, [] { return std::make_unique<ChangeSurfaceDegreeCommand>(); }},
      {"slab", {}, [] { return std::make_unique<SlabCommand>(); }},
      {"thicken", {}, [] { return std::make_unique<ThickenCommand>(false); }},
      {"makehollow", {"hollow"}, [] { return std::make_unique<ThickenCommand>(true); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_surface_edit_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList surface_edit_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
