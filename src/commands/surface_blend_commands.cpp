// Transitions between surfaces (docs/commands.md, "Blends and continuity"): Blend surface,
// Match surface, Chamfer surfaces, Merge surfaces, Merge faces, Fillet / Chamfer / Variable
// fillet of solid edges, Connect surfaces, Tween surfaces.
#include <QObject>
#include <algorithm>
#include <array>
#include <cmath>
#include <exception>
#include <functional>
#include <limits>
#include <nurbforge/analysis/closest_point.hpp>
#include <nurbforge/modeling/blend.hpp>
#include <nurbforge/modeling/extend.hpp>
#include <nurbforge/modeling/fillet.hpp>
#include <nurbforge/modeling/surface_tools.hpp>
#include <nurbforge/nurbs/join.hpp>
#include <nurbforge/topology/edge_blend.hpp>
#include <nurbforge/topology/solid_ops.hpp>
#include <nurbforge/topology/trimmed_surface.hpp>

#include "commands/command_util.hpp"

namespace nfcad::commands {

namespace {

using namespace util;

constexpr std::array<nf::SurfaceSide, 4> kSides = {nf::SurfaceSide::UMin, nf::SurfaceSide::UMax, nf::SurfaceSide::VMin,
                                                   nf::SurfaceSide::VMax};

/// The boundary curve of a surface at one side.
nf::NurbsCurve side_curve(const nf::NurbsSurface& s, nf::SurfaceSide side) {
  switch (side) {
    case nf::SurfaceSide::UMin: return s.iso_curve_u(s.domain_u()[0]);
    case nf::SurfaceSide::UMax: return s.iso_curve_u(s.domain_u()[1]);
    case nf::SurfaceSide::VMin: return s.iso_curve_v(s.domain_v()[0]);
    case nf::SurfaceSide::VMax: break;
  }
  return s.iso_curve_v(s.domain_v()[1]);
}

/// The side of the surface whose edge passes nearest p.
nf::SurfaceSide nearest_side(const nf::NurbsSurface& s, const nf::Vec3& p) {
  nf::SurfaceSide best = nf::SurfaceSide::UMin;
  double d = std::numeric_limits<double>::infinity();
  for (nf::SurfaceSide side : kSides) {
    const double ds = nf::closest_point(side_curve(s, side), p).distance;
    if (ds < d) {
      d = ds;
      best = side;
    }
  }
  return best;
}

double size_of(const nf::NurbsSurface& s) {
  nf::Vec3 lo{1e300, 1e300, 1e300}, hi{-1e300, -1e300, -1e300};
  for (const nf::Vec3& p : s.control_points()) {
    lo = {std::min(lo.x, p.x), std::min(lo.y, p.y), std::min(lo.z, p.z)};
    hi = {std::max(hi.x, p.x), std::max(hi.y, p.y), std::max(hi.z, p.z)};
  }
  return std::max(nf::distance(lo, hi), 1e-9);
}

/// The selected surfaces (a trimmed one: its underlying surface) and their entities.
class SurfacesCommand : public Command {
 public:
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (const auto* s = std::get_if<nf::NurbsSurface>(e.geometry.get())) {
        surfaces_.push_back(*s);
        ids_.push_back(e.id);
      } else if (const auto* f = std::get_if<nf::TrimmedSurface>(e.geometry.get())) {
        surfaces_.push_back(f->surface());
        ids_.push_back(e.id);
        trimmed_.push_back(e.id);
      }
    }
    if (surfaces_.size() != count_) {
      message_ = QObject::tr("%1: select %2").arg(title(), requirement_);
      return false;
    }
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }

 protected:
  SurfacesCommand(std::size_t count, QString requirement) : count_(count), requirement_(std::move(requirement)) {}
  Result failed(const std::exception& e) {
    entities_.clear();
    replace_.clear();
    message_ = failure(title(), e);
    return Result::Rejected;
  }
  std::vector<nf::NurbsSurface> surfaces_;
  std::vector<document::EntityId> ids_;
  std::vector<document::EntityId> trimmed_;

 private:
  std::size_t count_;
  QString requirement_;
};

// ------------------------------------------------------------------------------ Blend / Match
/// Blend surface: click near the edge of each of two surfaces; a surface continuing both with
/// G0, G1 or G2 (typed first; default G2). Match surface: the first surface is changed at the
/// clicked edge to join the second's clicked edge with that continuity.
class BlendMatchCommand : public SurfacesCommand {
 public:
  explicit BlendMatchCommand(bool match)
      : SurfacesCommand(2, match ? QObject::tr("the surface to change, then the one to match") : QObject::tr("two surfaces")),
        match_(match) {}
  QString id() const override { return match_ ? QStringLiteral("matchsrf") : QStringLiteral("blendsrf"); }
  QString title() const override { return match_ ? QObject::tr("Match surface") : QObject::tr("Blend surface"); }
  QString prompt() const override {
    const QString g = QStringLiteral("G%1").arg(continuity_);
    return side0_ ? QObject::tr("%1 (%2): click near the edge of the second surface").arg(title(), g)
                  : QObject::tr("%1 (%2): click near the edge of the first surface (type 0, 1 or 2: continuity)")
                        .arg(title(), g);
  }
  Result number(double v) override {
    if (v != 0 && v != 1 && v != 2) return Result::Rejected;
    continuity_ = static_cast<int>(v);
    return Result::Continue;
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!side0_) {
      side0_ = nearest_side(surfaces_[0], V(p));
      return Result::Continue;
    }
    const nf::SurfaceSide side1 = nearest_side(surfaces_[1], V(p));
    try {
      if (match_) {
        const nf::NurbsSurface m = nf::match_surface(surfaces_[0], *side0_, surfaces_[1], side1, continuity_);
        replace_.emplace_back(ids_[0], std::make_shared<const document::Geometry>(m));
      } else {
        entities_.push_back(document::make_entity(nf::blend_surfaces(surfaces_[0], *side0_, surfaces_[1], side1, continuity_)));
      }
      return Result::Done;
    } catch (const std::exception& e) {
      return failed(e);
    }
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    // the edge the click would take
    const nf::NurbsSurface& s = side0_ ? surfaces_[1] : surfaces_[0];
    return {sample(side_curve(s, nearest_side(s, V(c))), 64)};
  }

 private:
  bool match_;
  int continuity_ = 2;
  std::optional<nf::SurfaceSide> side0_;
};

// ------------------------------------------------------------------------------ Chamfer surfaces
/// Chamfer surfaces: a ruled chamfer between two intersecting surfaces at the typed distance
/// from their intersection on both (the wedge as for Fillet surfaces: the first that works).
class ChamferSurfacesCommand : public SurfacesCommand {
 public:
  ChamferSurfacesCommand() : SurfacesCommand(2, QObject::tr("two intersecting surfaces")) {}
  QString id() const override { return QStringLiteral("chamfersrf"); }
  QString title() const override { return QObject::tr("Chamfer surfaces"); }
  QString prompt() const override { return QObject::tr("Chamfer surfaces: distance from the intersection"); }
  Result number(double d) override {
    if (d <= 0) return Result::Rejected;
    std::string last;
    for (const auto& [s1, s2] : {std::pair{1, 1}, {-1, -1}, {1, -1}, {-1, 1}}) {
      try {
        nf::SurfaceChamferOptions o;
        o.side1 = s1;
        o.side2 = s2;
        o.tolerance = 1e-6 * std::max(size_of(surfaces_[0]), size_of(surfaces_[1]));
        entities_.push_back(document::make_entity(nf::chamfer_surfaces(surfaces_[0], surfaces_[1], d, d, o).surface));
        return Result::Done;
      } catch (const std::exception& e) {
        last = e.what();
      }
    }
    return failed(std::runtime_error(last));
  }
};

// ------------------------------------------------------------------------------ Merge
/// Reversed along u (the same surface, u running the other way).
nf::NurbsSurface reversed_u(const nf::NurbsSurface& s) {
  const std::size_t nu = s.num_u(), nv = s.num_v();
  std::vector<nf::Vec3> pts(nu * nv);
  std::vector<double> w(nu * nv);
  for (std::size_t i = 0; i < nu; ++i) {
    for (std::size_t j = 0; j < nv; ++j) {
      pts[i * nv + j] = s.control_point(nu - 1 - i, j);
      w[i * nv + j] = s.weight(nu - 1 - i, j);
    }
  }
  nf::KnotVector k = s.knots_u();
  const double a = k.front(), b = k.back();
  std::reverse(k.begin(), k.end());
  for (double& x : k) x = a + b - x;
  return {s.degree_u(), s.degree_v(), k, s.knots_v(), nu, nv, pts, w};
}

/// The surface turned so that `side` becomes its UMax side.
nf::NurbsSurface with_side_at_umax(const nf::NurbsSurface& s, nf::SurfaceSide side) {
  switch (side) {
    case nf::SurfaceSide::UMax: return s;
    case nf::SurfaceSide::UMin: return reversed_u(s);
    case nf::SurfaceSide::VMax: return s.transposed();
    case nf::SurfaceSide::VMin: break;
  }
  return reversed_u(s.transposed());
}

/// Merge surfaces: two untrimmed surfaces sharing a whole edge become one surface (joined across
/// that edge; the second turned as needed).
class MergeSurfacesCommand : public SurfacesCommand {
 public:
  MergeSurfacesCommand() : SurfacesCommand(2, QObject::tr("two untrimmed surfaces with a common edge")) {}
  QString id() const override { return QStringLiteral("mergesrf"); }
  QString title() const override { return QObject::tr("Merge surfaces"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    if (!trimmed_.empty()) return failed(std::invalid_argument("the surfaces must be untrimmed"));
    try {
      const nf::NurbsSurface m = merged(surfaces_[0], surfaces_[1]);
      entities_.push_back(document::make_entity(m));
      remove_ = ids_;
      return Result::Done;
    } catch (const std::exception& e) {
      return failed(e);
    }
  }

  static nf::NurbsSurface merged(const nf::NurbsSurface& a, const nf::NurbsSurface& b) {
    const double tol = 1e-6 * std::max(size_of(a), size_of(b));
    for (nf::SurfaceSide sa : kSides) {
      const nf::NurbsCurve ea = side_curve(a, sa);
      for (nf::SurfaceSide sb : kSides) {
        const nf::NurbsCurve eb = side_curve(b, sb);
        bool same = true;
        for (const nf::Vec3& p : ea.sample(16)) same = same && nf::closest_point(eb, p).distance <= tol;
        for (const nf::Vec3& p : eb.sample(16)) same = same && nf::closest_point(ea, p).distance <= tol;
        if (!same) continue;
        // a's shared side at UMax, b's at UMin, both edges running the same way
        const nf::NurbsSurface a1 = with_side_at_umax(a, sa);
        nf::NurbsSurface b1 = reversed_u(with_side_at_umax(b, sb));
        const nf::NurbsCurve ea1 = side_curve(a1, nf::SurfaceSide::UMax), eb1 = side_curve(b1, nf::SurfaceSide::UMin);
        if (nf::distance(ea1.evaluate(ea1.domain_start()), eb1.evaluate(eb1.domain_start())) > tol) {
          b1 = reversed_u(b1.transposed()).transposed();  // v the other way
        }
        return nf::join_u(a1, b1, tol);
      }
    }
    throw std::invalid_argument("the surfaces have no common edge");
  }
};

/// Merge faces: the faces of the selected solids that continue each other (coplanar or smooth
/// across their edge) are merged into larger faces.
class MergeFacesCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("merge"); }
  QString title() const override { return QObject::tr("Merge faces"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (const auto* s = std::get_if<nf::Shell>(e.geometry.get())) {
        try {
          const nf::Shell m = nf::merge_faces(*s);
          if (m.faces().size() < s->faces().size()) {
            replace_.emplace_back(e.id, std::make_shared<const document::Geometry>(m));
            merged_ += s->faces().size() - m.faces().size();
          }
        } catch (const std::exception& ex) {
          message_ = failure(title(), ex);
          return false;
        }
      }
    }
    if (replace_.empty()) {
      message_ = QObject::tr("Merge faces: nothing to merge in the selected solids");
      return false;
    }
    message_ = QObject::tr("Merge faces: %1 faces fewer").arg(merged_);
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }

 private:
  std::size_t merged_ = 0;
};

// ------------------------------------------------------------------------------ Edges of solids
/// Fillet / Chamfer edges: the picked edges (Ctrl+Shift-click) of a solid, rounded with the typed
/// radius or cut with the typed distance. Variable fillet: click points on the edges and type
/// the radius after each; Enter applies them.
class EdgeBlendCommand : public Command {
 public:
  enum class Kind { Fillet, Chamfer, Variable };
  explicit EdgeBlendCommand(Kind kind) : kind_(kind) {}
  QString id() const override {
    switch (kind_) {
      case Kind::Fillet: return QStringLiteral("filletedge");
      case Kind::Chamfer: return QStringLiteral("chamferedge");
      case Kind::Variable: break;
    }
    return QStringLiteral("variableblend");
  }
  QString title() const override {
    switch (kind_) {
      case Kind::Fillet: return QObject::tr("Fillet edges");
      case Kind::Chamfer: return QObject::tr("Chamfer edges");
      case Kind::Variable: break;
    }
    return QObject::tr("Variable fillet");
  }
  QString prompt() const override {
    switch (kind_) {
      case Kind::Fillet: return QObject::tr("Fillet edges: radius");
      case Kind::Chamfer: return QObject::tr("Chamfer edges: distance");
      case Kind::Variable: break;
    }
    return pending_ ? QObject::tr("Variable fillet: radius at this point")
                    : QObject::tr("Variable fillet: click a point on the edges (%1 so far; Enter: apply)").arg(sizes_.size());
  }
  bool usesSelection() const override { return true; }
  bool usesEdges() const override { return true; }
  bool begin(const std::vector<document::Entity>&) override {
    if (edges_.size() != 1) {
      message_ = QObject::tr("%1: pick edges of one solid (Ctrl+Shift-click)").arg(title());
      return false;
    }
    return true;
  }
  Result number(double v) override {
    if (v <= 0) return Result::Rejected;
    if (kind_ != Kind::Variable) return apply(v);
    if (!pending_) return Result::Rejected;
    sizes_.push_back({*pending_, v});
    pending_.reset();
    return Result::Continue;
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (kind_ != Kind::Variable || pending_) return Result::Rejected;
    // the nearest point on the picked edges
    const auto& shell = std::get<nf::Shell>(*edges_.front().geometry);
    double d = std::numeric_limits<double>::infinity();
    nf::Vec3 on{};
    for (int i : edges_.front().indices) {
      const nf::CurvePoint q = nf::closest_point(shell.edges()[static_cast<std::size_t>(i)].curve, V(p));
      if (q.distance < d) {
        d = q.distance;
        on = q.point;
      }
    }
    pending_ = on;
    return Result::Continue;
  }
  Result finish() override {
    if (kind_ != Kind::Variable || sizes_.empty()) return Result::Cancelled;
    return apply(sizes_.front().size);
  }

 private:
  Result apply(double size) {
    try {
      const auto& shell = std::get<nf::Shell>(*edges_.front().geometry);
      std::vector<std::size_t> edges;
      for (int i : edges_.front().indices) {
        if (i >= 0 && static_cast<std::size_t>(i) < shell.edges().size()) edges.push_back(static_cast<std::size_t>(i));
      }
      nf::EdgeBlendOptions o;
      o.sizes = sizes_;
      const nf::Shell out = kind_ == Kind::Chamfer ? nf::chamfer_edges(shell, edges, size, o)
                                                   : nf::fillet_edges(shell, edges, size, o);
      replace_.emplace_back(edges_.front().id, std::make_shared<const document::Geometry>(out));
      select_ = std::vector<document::SelectionItem>{};  // the old edge indices are gone
      return Result::Done;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  Kind kind_;
  std::vector<nf::BlendSize> sizes_;
  std::optional<nf::Vec3> pending_;
};

// ------------------------------------------------------------------------------ Connect
/// Connect surfaces: two surfaces are extended at their edges facing each other until they meet
/// and trimmed back to their intersection.
class ConnectSurfacesCommand : public SurfacesCommand {
 public:
  ConnectSurfacesCommand() : SurfacesCommand(2, QObject::tr("two untrimmed surfaces")) {}
  QString id() const override { return QStringLiteral("connectsrf"); }
  QString title() const override { return QObject::tr("Connect surfaces"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    if (!trimmed_.empty()) return failed(std::invalid_argument("the surfaces must be untrimmed"));
    try {
      const auto [a, b] = connected(surfaces_[0], surfaces_[1]);
      replace_.emplace_back(ids_[0], std::make_shared<const document::Geometry>(a));
      replace_.emplace_back(ids_[1], std::make_shared<const document::Geometry>(b));
      return Result::Done;
    } catch (const std::exception& e) {
      return failed(e);
    }
  }

  static std::pair<nf::TrimmedSurface, nf::TrimmedSurface> connected(const nf::NurbsSurface& a, const nf::NurbsSurface& b) {
    // the facing sides: the edge of each nearest the other surface
    auto facing = [](const nf::NurbsSurface& s, const nf::NurbsSurface& other) {
      nf::SurfaceSide best = nf::SurfaceSide::UMin;
      double d = std::numeric_limits<double>::infinity();
      for (nf::SurfaceSide side : kSides) {
        const nf::NurbsCurve e = side_curve(s, side);
        double ds = 0;
        for (const nf::Vec3& p : e.sample(9)) ds += nf::closest_point(other, p).distance;
        if (ds < d) {
          d = ds;
          best = side;
        }
      }
      return best;
    };
    const double reach = 2.0 * (size_of(a) + size_of(b));
    const nf::NurbsSurface ea = nf::extend(a, facing(a, b), reach, nf::Extension::Linear);
    const nf::NurbsSurface eb = nf::extend(b, facing(b, a), reach, nf::Extension::Linear);
    auto keep = [](const nf::NurbsSurface& extended, const nf::NurbsSurface& original, const nf::NurbsSurface& cutter) {
      const auto du = original.domain_u(), dv = original.domain_v();
      const double uc = 0.5 * (du[0] + du[1]), vc = 0.5 * (dv[0] + dv[1]);
      for (const nf::TrimmedSurface& piece : nf::split(extended, cutter)) {
        if (piece.contains(uc, vc)) return piece;
      }
      throw std::invalid_argument("the extended surfaces do not meet");
    };
    return {keep(ea, a, eb), keep(eb, b, ea)};
  }
};

// ------------------------------------------------------------------------------ Tween surfaces
/// Tween surfaces: surfaces between two selected ones (the typed number, Enter: one). Surfaces of
/// the same structure are interpolated exactly; others are rebuilt on a common grid first.
class TweenSurfacesCommand : public SurfacesCommand {
 public:
  TweenSurfacesCommand() : SurfacesCommand(2, QObject::tr("two surfaces")) {}
  QString id() const override { return QStringLiteral("tweensrf"); }
  QString title() const override { return QObject::tr("Tween surfaces"); }
  QString prompt() const override { return QObject::tr("Tween surfaces: number of surfaces (Enter: 1)"); }
  Result number(double v) override {
    if (std::floor(v) != v || v < 1 || v > 1000) return Result::Rejected;
    try {
      for (const nf::NurbsSurface& s : tweens(surfaces_[0], surfaces_[1], static_cast<std::size_t>(v))) {
        entities_.push_back(document::make_entity(s));
      }
      return Result::Done;
    } catch (const std::exception& e) {
      return failed(e);
    }
  }
  Result finish() override { return number(1); }

  static bool plain(const nf::NurbsSurface& s) {
    return std::all_of(s.weights().begin(), s.weights().end(), [](double w) { return w == 1.0; });
  }
  static std::vector<nf::NurbsSurface> tweens(nf::NurbsSurface a, nf::NurbsSurface b, std::size_t count) {
    const bool same = a.degree_u() == b.degree_u() && a.degree_v() == b.degree_v() && a.num_u() == b.num_u() &&
                      a.num_v() == b.num_v() && a.knots_u() == b.knots_u() && a.knots_v() == b.knots_v() &&
                      plain(a) && plain(b);
    if (!same) {
      const std::size_t nu = std::max<std::size_t>({a.num_u(), b.num_u(), 4}), nv = std::max<std::size_t>({a.num_v(), b.num_v(), 4});
      a = nf::rebuild_surface(a, nu, nv).surface;
      b = nf::rebuild_surface(b, nu, nv).surface;
    }
    std::vector<nf::NurbsSurface> out;
    for (std::size_t k = 1; k <= count; ++k) {
      const double s = double(k) / double(count + 1);
      std::vector<nf::Vec3> pts;
      for (std::size_t i = 0; i < a.control_points().size(); ++i) {
        pts.push_back(a.control_points()[i] * (1.0 - s) + b.control_points()[i] * s);
      }
      out.emplace_back(a.degree_u(), a.degree_v(), a.knots_u(), a.knots_v(), a.num_u(), a.num_v(), pts);
    }
    return out;
  }
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"blendsrf", {}, [] { return std::make_unique<BlendMatchCommand>(false); }},
      {"matchsrf", {}, [] { return std::make_unique<BlendMatchCommand>(true); }},
      {"chamfersrf", {}, [] { return std::make_unique<ChamferSurfacesCommand>(); }},
      {"mergesrf", {}, [] { return std::make_unique<MergeSurfacesCommand>(); }},
      {"merge", {"mergefaces", "mergeallfaces"}, [] { return std::make_unique<MergeFacesCommand>(); }},
      {"filletedge", {"blendedge"}, [] { return std::make_unique<EdgeBlendCommand>(EdgeBlendCommand::Kind::Fillet); }},
      {"chamferedge", {"bevel"}, [] { return std::make_unique<EdgeBlendCommand>(EdgeBlendCommand::Kind::Chamfer); }},
      {"variableblend", {"variablefilletedge"}, [] { return std::make_unique<EdgeBlendCommand>(EdgeBlendCommand::Kind::Variable); }},
      {"connectsrf", {}, [] { return std::make_unique<ConnectSurfacesCommand>(); }},
      {"tweensrf", {"tweensurface", "tweensurfaces"}, [] { return std::make_unique<TweenSurfacesCommand>(); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_surface_blend_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList surface_blend_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
