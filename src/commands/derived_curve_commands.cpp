// Curves derived from other geometry (docs/commands.md, "Curves from geometry"): Project, Pull,
// Section, Contour, Duplicate edge, Duplicate border, Extract isocurve, Extract wireframe,
// Offset curve on surface, Curve Boolean.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <exception>
#include <functional>
#include <limits>
#include <nurbforge/analysis/closest_point.hpp>
#include <nurbforge/analysis/section.hpp>
#include <nurbforge/analysis/shell_section.hpp>
#include <nurbforge/geometry/transform.hpp>
#include <nurbforge/modeling/project.hpp>
#include <nurbforge/topology/region.hpp>

#include "commands/command_util.hpp"
#include "kernel/geometry_ops.hpp"

namespace nfcad::commands {

namespace {

using namespace util;

const nf::NurbsCurve* curve_of(const document::Entity& e) {
  return std::get_if<nf::NurbsCurve>(e.geometry.get());
}

/// Adds the curves; returns how many.
std::size_t add_curves(std::vector<document::Entity>& out, const std::vector<nf::NurbsCurve>& curves) {
  for (const nf::NurbsCurve& c : curves) out.push_back(document::make_entity(c));
  return curves.size();
}

/// Size of the selection's geometry (for tolerances): the diagonal of its wire's bounding box.
double extent(const std::vector<document::Entity>& entities) {
  nf::Vec3 lo{1e300, 1e300, 1e300}, hi{-1e300, -1e300, -1e300};
  for (const document::Entity& e : entities) {
    for (const auto& line : kernel::wire(*e.geometry, 2000)) {
      for (const nf::Vec3& p : line) {
        lo = {std::min(lo.x, p.x), std::min(lo.y, p.y), std::min(lo.z, p.z)};
        hi = {std::max(hi.x, p.x), std::max(hi.y, p.y), std::max(hi.z, p.z)};
      }
    }
  }
  return lo.x <= hi.x ? nf::distance(lo, hi) : 0.0;
}

/// Base of the commands on the selection: the selected curves and faces (surfaces, trimmed
/// surfaces, the faces of shells; a face of a solid picked on its own counts too).
class GeometryInputCommand : public Command {
 public:
  bool usesSelection() const override { return true; }
  bool usesSubElements() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    selection_ = selection;
    for (const document::Entity& e : selection) {
      if (const nf::NurbsCurve* c = curve_of(e)) {
        curves_.push_back(*c);
        continue;
      }
      const auto* shell = std::get_if<nf::Shell>(e.geometry.get());
      const bool solid = shell != nullptr && shell->is_closed();
      if (solid) shells_.push_back(*shell);
      for (nf::TrimmedSurface& f : kernel::faces_of(*e.geometry)) {
        if (!solid) open_faces_.push_back(f);
        faces_.push_back(std::move(f));
      }
    }
    if (!accepts()) {
      message_ = QObject::tr("%1: select %2").arg(title(), requirement());
      return false;
    }
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }

 protected:
  [[nodiscard]] virtual bool accepts() const = 0;
  [[nodiscard]] virtual QString requirement() const = 0;
  /// Done with the curves made, or Rejected with `why` if there are none.
  Result finished(std::size_t made, const QString& why) {
    if (made > 0) return Result::Done;
    message_ = why;
    return Result::Rejected;
  }
  std::vector<document::Entity> selection_;
  std::vector<nf::NurbsCurve> curves_;
  std::vector<nf::TrimmedSurface> faces_;       ///< all faces (also those of solids)
  std::vector<nf::TrimmedSurface> open_faces_;  ///< faces not bounding a selected solid
  std::vector<nf::Shell> shells_;               ///< the selected closed shells (solids)
};

// ------------------------------------------------------------------------------ Project / Pull
/// Project: the selected curves onto the selected surfaces along the view direction (the
/// construction plane's normal); Pull: along the surface normal (closest points). The curve
/// follows the whole surface of a trimmed face – the trim is not applied.
class ProjectCommand : public GeometryInputCommand {
 public:
  explicit ProjectCommand(bool pull) : pull_(pull) {}
  QString id() const override { return pull_ ? QStringLiteral("pull") : QStringLiteral("project"); }
  QString title() const override { return pull_ ? QObject::tr("Pull curves") : QObject::tr("Project curves"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    const nf::Vec3 dir = pull_ ? nf::Vec3{0, 0, 0} : V(viewPlane().n);
    const double tol = 1e-6 * std::max(1.0, extent(selection_));
    std::size_t made = 0;
    QString last;
    for (const nf::NurbsCurve& c : curves_) {
      for (const nf::TrimmedSurface& f : faces_) {
        try {
          entities_.push_back(document::make_entity(nf::project_curve(c, f.surface(), dir, tol).curve));
          ++made;
        } catch (const std::exception& e) {
          last = reason(e);
        }
      }
    }
    return finished(made, QObject::tr("%1: no curve projects onto the surfaces (%2)").arg(title(), last));
  }

 protected:
  bool accepts() const override { return !curves_.empty() && !faces_.empty(); }
  QString requirement() const override { return QObject::tr("curves and the surfaces to project onto"); }

 private:
  bool pull_;
};

// ------------------------------------------------------------------------------ Section / Contour
/// Section curves of the selected faces and closed solids with a plane: a solid gives its
/// closed section loops (Nurbforge section; if that fails, e.g. the plane contains a face, its
/// faces are cut one by one), other faces their planar sections clipped to their trim.
std::vector<nf::NurbsCurve> plane_sections(const std::vector<nf::TrimmedSurface>& open_faces,
                                           const std::vector<nf::Shell>& shells, const nf::Plane& plane) {
  std::vector<nf::NurbsCurve> out;
  std::vector<const nf::TrimmedSurface*> loose;
  for (const nf::TrimmedSurface& f : open_faces) loose.push_back(&f);
  for (const nf::Shell& s : shells) {
    try {
      for (const nf::SectionLoop& loop : nf::section(s, plane).loops) {
        std::vector<nf::NurbsCurve> pieces;
        for (const nf::SectionCurve& c : loop.curves) pieces.push_back(c.curve3d);
        try {
          out.push_back(kernel::join_chain(pieces));
        } catch (const std::exception&) {
          out.insert(out.end(), pieces.begin(), pieces.end());
        }
      }
    } catch (const std::exception&) {
      for (const nf::TrimmedSurface& f : s.faces()) loose.push_back(&f);
    }
  }
  for (const nf::TrimmedSurface* f : loose) {
    nf::SurfaceIntersection cut;
    try {
      cut = nf::planar_section(f->surface(), plane);
    } catch (const std::exception&) {
      continue;
    }
    for (const nf::IntersectionCurve& c : cut.curves) {
      if (f->is_untrimmed()) {
        out.push_back(c.curve);
        continue;
      }
      // keep the parts inside the trimmed region: split where the inside test changes
      const double t0 = c.curve.domain_start(), t1 = c.curve.domain_end();
      const int n = 200;
      auto inside = [&](double t) {
        const nf::Vec3 uv = c.pcurve1.evaluate(t);
        return f->contains(uv.x, uv.y);
      };
      double start = t0;
      bool in = inside(t0);
      for (int i = 1; i <= n; ++i) {
        const double t = t0 + (t1 - t0) * i / n;
        const bool now = i == n ? !in : inside(t);
        if (now != in || i == n) {
          if (in && t - start > 1e-9 * (t1 - t0)) out.push_back(c.curve.sub_curve(start, t));
          start = t;
          in = now;
        }
      }
    }
  }
  return out;
}

/// Section: the plane through two clicked points and the view direction.
class SectionCommand : public GeometryInputCommand {
 public:
  QString id() const override { return QStringLiteral("section"); }
  QString title() const override { return QObject::tr("Section"); }
  QString prompt() const override {
    return start_ ? QObject::tr("Section: end of the section line")
                  : QObject::tr("Section: start of the section line (the plane is perpendicular to the view)");
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (!start_) {
      start_ = p;
      plane_ = plane;
      return Result::Continue;
    }
    const nf::Vec3 along = in_plane(p, *start_, plane_);
    if (nf::norm(along) < kEps) return Result::Rejected;
    const nf::Plane cut{V(*start_), nf::normalized(nf::cross(along, V(plane_.n)))};
    return finished(add_curves(entities_, plane_sections(open_faces_, shells_, cut)),
                    QObject::tr("Section: the plane does not cut the selection"));
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (!start_) return {};
    return {{*start_, c}};
  }
  std::optional<Point3> basePoint() const override { return start_; }

 protected:
  bool accepts() const override { return !faces_.empty(); }
  QString requirement() const override { return QObject::tr("surfaces or solids"); }

 private:
  std::optional<Point3> start_;
  PlaneFrame plane_;
};

/// Contour: parallel sections – base point, a point in the direction of the planes' normal, the
/// spacing (number) – across the whole selection.
class ContourCommand : public GeometryInputCommand {
 public:
  QString id() const override { return QStringLiteral("contour"); }
  QString title() const override { return QObject::tr("Contour"); }
  QString prompt() const override {
    if (!base_) return QObject::tr("Contour: base point");
    if (!dir_) return QObject::tr("Contour: direction of the contour planes' normal");
    return QObject::tr("Contour: spacing (number)");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!base_) {
      base_ = p;
      return Result::Continue;
    }
    if (!dir_) {
      const nf::Vec3 d = V(p) - V(*base_);
      if (nf::norm(d) < kEps) return Result::Rejected;
      dir_ = nf::normalized(d);
      return Result::Continue;
    }
    return Result::Rejected;
  }
  Result number(double spacing) override {
    if (!dir_ || spacing <= 0) return Result::Rejected;
    // the heights of the selection along the direction
    double lo = 1e300, hi = -1e300;
    for (const document::Entity& e : selection_) {
      for (const auto& line : kernel::wire(*e.geometry, 4000)) {
        for (const nf::Vec3& q : line) {
          const double h = nf::dot(q - V(*base_), *dir_);
          lo = std::min(lo, h);
          hi = std::max(hi, h);
        }
      }
    }
    const double k0 = std::ceil(lo / spacing), k1 = std::floor(hi / spacing);
    if (k1 - k0 > 1000) {
      message_ = QObject::tr("Contour: more than 1000 planes – choose a larger spacing");
      return Result::Rejected;
    }
    std::size_t made = 0;
    for (double k = k0; k <= k1; k += 1.0) {
      made += add_curves(entities_, plane_sections(open_faces_, shells_, {V(*base_) + *dir_ * (k * spacing), *dir_}));
    }
    return finished(made, QObject::tr("Contour: no plane cuts the selection"));
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (!base_ || dir_) return {};
    return {{*base_, c}};
  }
  std::optional<Point3> basePoint() const override { return base_; }

 protected:
  bool accepts() const override { return !faces_.empty(); }
  QString requirement() const override { return QObject::tr("surfaces or solids"); }

 private:
  std::optional<Point3> base_;
  std::optional<nf::Vec3> dir_;
};

// ------------------------------------------------------------------------------ Duplicate
/// Duplicate edge: the selected edges of solids and surfaces as curves (pick edges with sub-
/// element selection); Duplicate border: the boundary loops of the selected surfaces – of a
/// shell its free (open) edges, joined into loops where they chain.
class DuplicateCommand : public GeometryInputCommand {
 public:
  explicit DuplicateCommand(bool border) : border_(border) {}
  QString id() const override { return border_ ? QStringLiteral("dupborder") : QStringLiteral("dupedge"); }
  QString title() const override { return border_ ? QObject::tr("Duplicate border") : QObject::tr("Duplicate edge"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    std::size_t made = 0;
    if (!border_) {
      made = add_curves(entities_, curves_);  // the picked edges arrive as curves
      return finished(made, QObject::tr("Duplicate edge: select edges of solids or surfaces"));
    }
    for (const document::Entity& e : selection_) {
      if (const auto* s = std::get_if<nf::Shell>(e.geometry.get())) {
        std::vector<nf::NurbsCurve> open;
        for (std::size_t i : s->free_edges()) open.push_back(s->edges()[i].curve);
        made += add_curves(entities_, chains(open));
      } else if (curve_of(e) == nullptr) {
        for (const nf::TrimmedSurface& f : kernel::faces_of(*e.geometry)) {
          for (const auto& loop : f.boundary_curves()) made += add_curves(entities_, chains(loop));
        }
      }
    }
    return finished(made, QObject::tr("Duplicate border: the selection has no open border"));
  }

 protected:
  bool accepts() const override { return border_ ? !faces_.empty() : !curves_.empty(); }
  QString requirement() const override {
    return border_ ? QObject::tr("surfaces or open shells")
                   : QObject::tr("edges (click an edge of a solid or surface to pick it)");
  }

 private:
  /// The curves joined into chains where their ends meet.
  static std::vector<nf::NurbsCurve> chains(std::vector<nf::NurbsCurve> curves) {
    try {
      return {kernel::join_chain(curves)};
    } catch (const std::exception&) {
      return curves;  // several loops: as they are
    }
  }
  bool border_;
};

// ------------------------------------------------------------------------------ Isocurves
/// Extract isocurve: the u and / or v isocurve of a surface through a clicked point (type 1: u
/// only, 2: v only, 3: both); repeats until Enter.
class ExtractIsocurveCommand : public GeometryInputCommand {
 public:
  QString id() const override { return QStringLiteral("extract_isocurve"); }
  QString title() const override { return QObject::tr("Extract isocurve"); }
  QString prompt() const override {
    static const char* names[] = {"", "u", "v", "u and v"};
    return QObject::tr("Isocurve (%1): click a point on the surface (type 1: u, 2: v, 3: both; Enter: done)")
        .arg(QString::fromLatin1(names[which_]));
  }
  Result number(double v) override {
    if (v != 1 && v != 2 && v != 3) return Result::Rejected;
    which_ = static_cast<int>(v);
    return Result::Continue;
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    const auto iso = curves_at(p);
    if (iso.empty()) return Result::Rejected;
    count_ += add_curves(entities_, iso);
    return Result::Continue;
  }
  Result finish() override { return count_ > 0 ? Result::Done : Result::Cancelled; }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    std::vector<Polyline3> out;
    for (const nf::NurbsCurve& iso : curves_at(c)) out.push_back(sample(iso, 64));
    return out;
  }

 protected:
  bool accepts() const override { return !faces_.empty(); }
  QString requirement() const override { return QObject::tr("surfaces"); }

 private:
  /// The isocurves through the point of the nearest face (u: constant u, along v).
  std::vector<nf::NurbsCurve> curves_at(const Point3& p) const {
    const nf::TrimmedSurface* best = nullptr;
    nf::SurfacePoint at;
    double d = std::numeric_limits<double>::infinity();
    for (const nf::TrimmedSurface& f : faces_) {
      try {
        const nf::SurfacePoint q = nf::closest_point(f.surface(), V(p));
        if (q.distance < d) {
          d = q.distance;
          at = q;
          best = &f;
        }
      } catch (const std::exception&) {
      }
    }
    if (best == nullptr) return {};
    std::vector<nf::NurbsCurve> out;
    if (which_ & 1) out.push_back(best->surface().iso_curve_u(at.u));
    if (which_ & 2) out.push_back(best->surface().iso_curve_v(at.v));
    return out;
  }
  int which_ = 3;
  std::size_t count_ = 0;
};

/// Extract wireframe: the isocurves of the selected surfaces at their knot lines (borders
/// included) – the net of their spans.
class ExtractWireframeCommand : public GeometryInputCommand {
 public:
  QString id() const override { return QStringLiteral("extract_wireframe"); }
  QString title() const override { return QObject::tr("Extract wireframe"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    std::size_t made = 0;
    for (const nf::TrimmedSurface& f : faces_) {
      const nf::NurbsSurface& s = f.surface();
      for (double u : unique(s.knots_u(), s.domain_u())) made += add_curves(entities_, {s.iso_curve_u(u)});
      for (double v : unique(s.knots_v(), s.domain_v())) made += add_curves(entities_, {s.iso_curve_v(v)});
    }
    return finished(made, QObject::tr("Extract wireframe: select surfaces"));
  }

 protected:
  bool accepts() const override { return !faces_.empty(); }
  QString requirement() const override { return QObject::tr("surfaces"); }

 private:
  static std::vector<double> unique(const std::vector<double>& knots, std::array<double, 2> domain) {
    std::vector<double> out;
    for (double k : knots) {
      if (k < domain[0] || k > domain[1]) continue;
      if (out.empty() || k - out.back() > 1e-12 * std::max(1.0, std::abs(k))) out.push_back(k);
    }
    return out;
  }
};

// ------------------------------------------------------------------------------ Offset on surface
/// Offset curve on surface: one selected curve on (near) one selected surface, the geodesic
/// offset at the typed distance (negative: the other side).
class OffsetOnSurfaceCommand : public GeometryInputCommand {
 public:
  QString id() const override { return QStringLiteral("offset_on_surface"); }
  QString title() const override { return QObject::tr("Offset curve on surface"); }
  QString prompt() const override {
    return QObject::tr("Offset on surface: distance (positive: left of the curve seen from the surface normal)");
  }
  Result number(double d) override {
    if (d == 0) return Result::Rejected;
    try {
      const nf::NurbsSurface& s = faces_.front().surface();
      const double tol = 1e-6 * std::max(1.0, extent(selection_));
      const nf::ProjectedCurve on = nf::project_curve(curves_.front(), s, {0, 0, 0}, tol);
      entities_.push_back(document::make_entity(nf::offset_on_surface(s, on.pcurve, d, tol).curve));
      return Result::Done;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }

 protected:
  bool accepts() const override { return curves_.size() == 1 && faces_.size() == 1; }
  QString requirement() const override { return QObject::tr("one curve and the surface it lies on"); }
};

// ------------------------------------------------------------------------------ Curve Boolean
/// Curve Boolean: closed planar curves in the construction plane as regions – 1 union,
/// 2 intersection, 3 difference (the first minus the others). The result loops are new curves.
class CurveBooleanCommand : public GeometryInputCommand {
 public:
  QString id() const override { return QStringLiteral("curve_boolean"); }
  QString title() const override { return QObject::tr("Curve Boolean"); }
  QString prompt() const override {
    return QObject::tr("Curve Boolean: 1 union, 2 intersection, 3 difference (first minus the others)");
  }
  Result number(double v) override {
    if (v != 1 && v != 2 && v != 3) return Result::Rejected;
    const nf::BooleanOp op = v == 1 ? nf::BooleanOp::Union : v == 2 ? nf::BooleanOp::Intersection
                                                                      : nf::BooleanOp::Difference;
    try {
      // into the plane's coordinates (x, y), the Boolean, and back
      const PlaneFrame& f = viewPlane();
      const nf::Vec3 o = V(f.origin), u = V(f.u), w = V(f.v), n = V(f.n);
      const nf::Transform to({u.x, u.y, u.z, -nf::dot(u, o), w.x, w.y, w.z, -nf::dot(w, o),
                              n.x, n.y, n.z, -nf::dot(n, o)});
      const nf::Transform back({u.x, w.x, n.x, o.x, u.y, w.y, n.y, o.y, u.z, w.z, n.z, o.z});
      const double size = std::max(1.0, extent(selection_));
      std::vector<nf::Region> regions;
      for (const nf::NurbsCurve& c : curves_) {
        const nf::NurbsCurve flat = c.transformed(to);
        for (const nf::Vec3& q : flat.sample(32)) {
          if (std::abs(q.z) > 1e-6 * size) {
            message_ = QObject::tr("Curve Boolean: the curves must lie in the construction plane of the view");
            return Result::Rejected;
          }
        }
        if (nf::distance(flat.evaluate(flat.domain_start()), flat.evaluate(flat.domain_end())) > 1e-6 * size) {
          message_ = QObject::tr("Curve Boolean: every curve must be closed");
          return Result::Rejected;
        }
        regions.push_back({{flat}});
      }
      nf::Region result = regions.front();
      for (std::size_t i = 1; i < regions.size(); ++i) result = nf::region_boolean(result, regions[i], op, 1e-9 * size);
      std::size_t made = 0;
      for (const auto& loop : result) {
        std::vector<nf::NurbsCurve> pieces;
        for (const nf::NurbsCurve& c : loop) pieces.push_back(c.transformed(back));
        try {
          made += add_curves(entities_, {kernel::join_chain(pieces, 1e-6 * size)});
        } catch (const std::exception&) {
          made += add_curves(entities_, pieces);
        }
      }
      return finished(made, QObject::tr("Curve Boolean: the result is empty"));
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }

 protected:
  bool accepts() const override { return curves_.size() >= 2; }
  QString requirement() const override { return QObject::tr("two or more closed curves in one plane"); }
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"project", {"proj"}, [] { return std::make_unique<ProjectCommand>(false); }},
      {"pull", {}, [] { return std::make_unique<ProjectCommand>(true); }},
      {"section", {}, [] { return std::make_unique<SectionCommand>(); }},
      {"contour", {}, [] { return std::make_unique<ContourCommand>(); }},
      {"dupedge", {}, [] { return std::make_unique<DuplicateCommand>(false); }},
      {"dupborder", {}, [] { return std::make_unique<DuplicateCommand>(true); }},
      {"extract_isocurve", {"extractisocurve", "iso"}, [] { return std::make_unique<ExtractIsocurveCommand>(); }},
      {"extract_wireframe", {"extractwireframe"}, [] { return std::make_unique<ExtractWireframeCommand>(); }},
      {"offset_on_surface", {"offsetcrvonsrf", "offsetonsrf"}, [] { return std::make_unique<OffsetOnSurfaceCommand>(); }},
      {"curve_boolean", {"crvboolean", "curveboolean"}, [] { return std::make_unique<CurveBooleanCommand>(); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_derived_curve_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList derived_curve_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
