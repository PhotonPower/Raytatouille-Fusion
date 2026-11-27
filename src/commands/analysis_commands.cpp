// Analysis (docs/commands.md, "Analysis"): the viewport analyses Zebra, EMap, CurvatureAnalysis,
// DraftAngleAnalysis (shown by every viewport until switched off); GCon (continuity of two curves
// or two surfaces), AreaCentroid, Check and SelBadObjects.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <exception>
#include <functional>
#include <numbers>
#include <nurbforge/analysis/closest_point.hpp>
#include <nurbforge/analysis/properties.hpp>

#include "commands/command_util.hpp"
#include "kernel/geometry_ops.hpp"

namespace nfcad::commands {

namespace {

using namespace util;
using render::Analysis;

constexpr double kDeg = 180.0 / std::numbers::pi;

QString num(double v) { return QString::number(v, 'g', 6); }

// ------------------------------------------------------------------------------ viewport analyses
/// Zebra / EMap (no input; run again: off), CurvatureAnalysis (measure, range from the surfaces),
/// DraftAngleAnalysis (angle; pull direction = the construction plane's normal), AnalysisOff.
class AnalysisCommand : public Command {
 public:
  explicit AnalysisCommand(Analysis::Kind kind) : kind_(kind) {}
  QString id() const override {
    switch (kind_) {
      case Analysis::Kind::Zebra: return QStringLiteral("zebra");
      case Analysis::Kind::EMap: return QStringLiteral("emap");
      case Analysis::Kind::Curvature: return QStringLiteral("curvatureanalysis");
      case Analysis::Kind::Draft: return QStringLiteral("draftangleanalysis");
      case Analysis::Kind::None: break;
    }
    return QStringLiteral("analysisoff");
  }
  QString title() const override {
    switch (kind_) {
      case Analysis::Kind::Zebra: return QObject::tr("Zebra");
      case Analysis::Kind::EMap: return QObject::tr("Environment map");
      case Analysis::Kind::Curvature: return QObject::tr("Curvature analysis");
      case Analysis::Kind::Draft: return QObject::tr("Draft angle analysis");
      case Analysis::Kind::None: break;
    }
    return QObject::tr("Analysis off");
  }
  QString prompt() const override {
    if (kind_ == Analysis::Kind::Curvature) {
      return QObject::tr("Curvature analysis: 1 Gaussian, 2 mean, 3 maximum, 4 minimum (Enter: Gaussian)");
    }
    if (kind_ == Analysis::Kind::Draft) return QObject::tr("Draft angle analysis: minimum draft in degrees (Enter: 3)");
    return title();
  }
  bool usesSelection() const override { return true; }
  bool immediate() const override {
    return kind_ == Analysis::Kind::Zebra || kind_ == Analysis::Kind::EMap || kind_ == Analysis::Kind::None;
  }
  bool begin(const std::vector<document::Entity>& selection) override {
    selection_ = selection;
    return true;
  }
  Result number(double v) override {
    if (kind_ == Analysis::Kind::Curvature) {
      if (v != std::floor(v) || v < 1 || v > 4) return Result::Rejected;
      return made(static_cast<Analysis::Measure>(static_cast<int>(v) - 1));
    }
    if (kind_ == Analysis::Kind::Draft) {
      if (v < 0 || v >= 90) return Result::Rejected;
      return draft(v);
    }
    return Result::Rejected;
  }
  Result finish() override {
    if (kind_ == Analysis::Kind::Curvature) return made(Analysis::Measure::Gaussian);
    if (kind_ == Analysis::Kind::Draft) return draft(3.0);
    analysis_ = Analysis{};
    analysis_->kind = kind_;
    toggles_ = kind_ != Analysis::Kind::None;
    return Result::Done;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  std::optional<Analysis> viewAnalysis() const override { return analysis_; }
  bool analysisToggles() const override { return toggles_; }

  /// Range of a curvature measure over the faces: ±(95th percentile of |value|) for Gaussian and
  /// mean curvature, 0 … 95th percentile for the maximum and minimum |k|.
  static std::pair<float, float> range(const std::vector<nf::TrimmedSurface>& faces, Analysis::Measure m) {
    std::vector<float> values;
    for (const nf::TrimmedSurface& f : faces) {
      const nf::NurbsSurface& s = f.surface();
      const auto du = s.domain_u(), dv = s.domain_v();
      for (int i = 0; i <= 16; ++i) {
        for (int j = 0; j <= 16; ++j) {
          const double u = du[0] + (du[1] - du[0]) * i / 16.0, v = dv[0] + (dv[1] - dv[0]) * j / 16.0;
          if (!f.is_untrimmed() && !f.contains(u, v)) continue;
          try {
            const nf::SurfaceCurvature k = nf::curvature(s, u, v);
            const float x = render::curvature_measure(m, static_cast<float>(k.k1), static_cast<float>(k.k2));
            if (std::isfinite(x)) values.push_back(std::abs(x));
          } catch (...) {
          }
        }
      }
    }
    float top = 0;
    if (!values.empty()) {
      const std::size_t at = std::min(values.size() - 1, static_cast<std::size_t>(0.95 * double(values.size())));
      std::nth_element(values.begin(), values.begin() + std::ptrdiff_t(at), values.end());
      top = values[at];
    }
    if (top < 1e-12F) top = 1.0F;
    const bool signed_measure = m == Analysis::Measure::Gaussian || m == Analysis::Measure::Mean;
    return {signed_measure ? -top : 0.0F, top};
  }

 private:
  /// The faces to analyse: the selection, else every object of the document.
  std::vector<nf::TrimmedSurface> faces() const {
    std::vector<nf::TrimmedSurface> out;
    auto add = [&](const document::Entity& e) {
      for (nf::TrimmedSurface& f : kernel::faces_of(*e.geometry)) out.push_back(std::move(f));
    };
    if (!selection_.empty()) {
      for (const document::Entity& e : selection_) add(e);
    } else if (doc_ != nullptr) {
      for (const auto& [id, e] : doc_->entities()) add(e);
    }
    return out;
  }
  Result made(Analysis::Measure m) {
    const auto [lo, hi] = range(faces(), m);
    analysis_ = Analysis{};
    analysis_->kind = Analysis::Kind::Curvature;
    analysis_->measure = m;
    analysis_->lo = lo;
    analysis_->hi = hi;
    static const char* names[] = {QT_TR_NOOP("Gaussian curvature"), QT_TR_NOOP("Mean curvature"),
                                  QT_TR_NOOP("Maximum curvature"), QT_TR_NOOP("Minimum curvature")};
    message_ = QObject::tr("%1: blue %2 … green %3 … red %4")
                   .arg(QObject::tr(names[static_cast<int>(m)]), num(lo), num(0.5 * (lo + hi)), num(hi));
    return Result::Done;
  }
  Result draft(double angle) {
    analysis_ = Analysis{};
    analysis_->kind = Analysis::Kind::Draft;
    analysis_->draft_angle = static_cast<float>(angle);
    const nf::Vec3 n = V(viewPlane().n);
    analysis_->direction[0] = static_cast<float>(n.x);
    analysis_->direction[1] = static_cast<float>(n.y);
    analysis_->direction[2] = static_cast<float>(n.z);
    message_ = QObject::tr("Draft angle along the construction-plane normal: green ≥ %1°, red below, blue ≤ −%1° "
                           "(the other side)")
                   .arg(num(angle));
    return Result::Done;
  }
  Analysis::Kind kind_;
  std::vector<document::Entity> selection_;
  std::optional<Analysis> analysis_;
  bool toggles_ = false;
};

// ------------------------------------------------------------------------------ GCon
/// Continuity of a junction from its deviations.
QString continuity(double gap, double angle_deg, double curvature_diff, double size) {
  if (gap > 1e-4 * size) return QObject::tr("not touching");
  if (angle_deg > 0.1) return QStringLiteral("G0");
  if (curvature_diff > 1e-2) return QStringLiteral("G1");
  return QStringLiteral("G2");
}

/// GCon: continuity where two curves meet (at their closest ends) or along the common edge of two
/// surfaces: the gap, the angle between the tangents (normals) and the relative difference of
/// the curvatures (across the edge), and the verdict G0 / G1 / G2.
class GConCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("gcon"); }
  QString title() const override { return QObject::tr("Continuity"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    if (selection.size() != 2) {
      message_ = QObject::tr("Continuity: select two curves or two surfaces");
      return false;
    }
    try {
      const auto* a = std::get_if<nf::NurbsCurve>(selection[0].geometry.get());
      const auto* b = std::get_if<nf::NurbsCurve>(selection[1].geometry.get());
      if (a != nullptr && b != nullptr) {
        message_ = curves(*a, *b);
        return true;
      }
      const auto fa = kernel::faces_of(*selection[0].geometry), fb = kernel::faces_of(*selection[1].geometry);
      if (fa.size() == 1 && fb.size() == 1) {
        message_ = surfaces(fa.front(), fb.front());
        return true;
      }
      message_ = QObject::tr("Continuity: select two curves or two single surfaces");
      return false;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return false;
    }
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }

  static QString curves(const nf::NurbsCurve& a, const nf::NurbsCurve& b) {
    // the closest pair of ends; the tangents pointing away from the junction on a, into b
    double best = 1e300;
    double ua = 0, ub = 0;
    for (const double x : {a.domain_start(), a.domain_end()}) {
      for (const double y : {b.domain_start(), b.domain_end()}) {
        const double d = nf::distance(a.evaluate(x), b.evaluate(y));
        if (d < best) {
          best = d;
          ua = x;
          ub = y;
        }
      }
    }
    const double size = std::max({1.0, bbox_size(a), bbox_size(b)});
    nf::Vec3 ta = nf::normalized(a.tangent(ua)), tb = nf::normalized(b.tangent(ub));
    if (ua == a.domain_start()) ta = -ta;  // leaving a at its start: backwards
    if (ub == b.domain_end()) tb = -tb;    // entering b at its end: backwards
    const double angle = std::acos(std::clamp(nf::dot(ta, tb), -1.0, 1.0)) * kDeg;
    const nf::Vec3 ka = curvature_vector(a, ua), kb = curvature_vector(b, ub);
    const double scale = std::max({nf::norm(ka), nf::norm(kb), 1e-12});
    const double dk = nf::norm(ka - kb) / scale;
    return QObject::tr("Continuity %1: gap %2, tangent angle %3°, curvature difference %4 % (curvatures %5, %6)")
        .arg(continuity(best, angle, nf::norm(ka) + nf::norm(kb) < 1e-9 ? 0 : dk, size), num(best), num(angle),
             num(100 * dk), num(nf::norm(ka)), num(nf::norm(kb)));
  }

  static QString surfaces(const nf::TrimmedSurface& a, const nf::TrimmedSurface& b) {
    const nf::NurbsSurface& sa = a.surface();
    const nf::NurbsSurface& sb = b.surface();
    double size = 1;
    for (const nf::Vec3& p : sa.control_points()) size = std::max(size, nf::norm(p));
    // samples of a's boundary (outer loop, parameter space) that lie on b
    double gap = 0, angle = 0, dk = 0;
    int contacts = 0;
    // a's boundary in the parameter plane: the outer loop, or the domain's rectangle
    std::vector<nf::NurbsCurve> boundary = a.outer().curves;
    if (a.is_untrimmed() || boundary.empty()) {
      const auto du = sa.domain_u(), dv = sa.domain_v();
      const nf::Vec3 c00{du[0], dv[0], 0}, c10{du[1], dv[0], 0}, c11{du[1], dv[1], 0}, c01{du[0], dv[1], 0};
      boundary = {nf::make_line(c00, c10), nf::make_line(c10, c11), nf::make_line(c11, c01), nf::make_line(c01, c00)};
    }
    for (const nf::NurbsCurve& c : boundary) {
      for (int k = 1; k < 16; ++k) {  // not the corners
        const double t = c.domain_start() + (c.domain_end() - c.domain_start()) * k / 16.0;
        const nf::Vec3 uv = c.evaluate(t);
        const nf::Vec3 p = sa.evaluate(uv.x, uv.y);
        const nf::SurfacePoint q = nf::closest_point(sb, p);
        const double d = nf::distance(p, q.point);
        if (d > 1e-3 * size) continue;
        ++contacts;
        gap = std::max(gap, d);
        nf::Vec3 na = sa.normal(uv.x, uv.y), nb = sb.normal(q.u, q.v);
        if (nf::dot(na, nb) < 0) nb = -nb;
        angle = std::max(angle, std::acos(std::clamp(nf::dot(na, nb), -1.0, 1.0)) * kDeg);
        // normal curvature across the edge (perpendicular to the edge tangent in the tangent plane)
        const auto d1 = sa.first_derivatives(uv.x, uv.y);
        const nf::Vec3 duv = c.tangent(t);
        const nf::Vec3 edge = nf::normalized(d1[1] * duv.x + d1[2] * duv.y);
        const nf::Vec3 across = nf::normalized(nf::cross(na, edge));
        const double ka = normal_curvature(sa, uv.x, uv.y, across, na);
        const double kb = normal_curvature(sb, q.u, q.v, across, na);
        const double scale = std::max({std::abs(ka), std::abs(kb), 1e-12});
        if (std::abs(ka) + std::abs(kb) > 1e-9) dk = std::max(dk, std::abs(ka - kb) / scale);
      }
    }
    if (contacts < 3) return QObject::tr("Continuity: the surfaces do not share an edge (of the first surface)");
    return QObject::tr("Continuity %1 along the edge: gap %2, normal angle %3°, curvature difference across %4 %")
        .arg(continuity(gap, angle, dk, size), num(gap), num(angle), num(100 * dk));
  }

 private:
  static double bbox_size(const nf::NurbsCurve& c) {
    double s = 0;
    for (const nf::Vec3& p : c.control_points()) s = std::max(s, nf::norm(p));
    return s;
  }
  /// Curvature vector κ·N of a curve at u.
  static nf::Vec3 curvature_vector(const nf::NurbsCurve& c, double u) {
    const auto d = c.derivatives(u, 2);
    const double s2 = nf::dot(d[1], d[1]);
    if (s2 < 1e-300) return {0, 0, 0};
    return (d[2] - d[1] * (nf::dot(d[1], d[2]) / s2)) / s2;
  }
  /// Normal curvature of s at (u, v) in the tangent direction t, signed against the normal n.
  static double normal_curvature(const nf::NurbsSurface& s, double u, double v, const nf::Vec3& t, const nf::Vec3& n) {
    const nf::SurfaceCurvature k = nf::curvature(s, u, v);
    const double c = nf::dot(t, k.dir1), sn = nf::dot(t, k.dir2);
    const double value = k.k1 * c * c + k.k2 * sn * sn;
    return nf::dot(k.normal, n) < 0 ? -value : value;
  }
};

// ------------------------------------------------------------------------------ AreaCentroid
/// Area centroid of the selected surfaces, solids' faces and closed planar curves (their area);
/// a point is added there.
class AreaCentroidCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("areacentroid"); }
  QString title() const override { return QObject::tr("Area centroid"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    std::vector<nf::TrimmedSurface> faces;
    std::vector<nf::NurbsCurve> curves;
    for (const document::Entity& e : selection) {
      if (const auto* c = std::get_if<nf::NurbsCurve>(e.geometry.get())) {
        curves.push_back(*c);
      } else {
        for (nf::TrimmedSurface& f : kernel::faces_of(*e.geometry)) faces.push_back(std::move(f));
      }
    }
    try {
      if (!curves.empty()) {
        for (nf::TrimmedSurface& f : kernel::planar_faces(curves)) faces.push_back(std::move(f));
      }
      const auto [area, centroid] = area_centroid(faces);
      if (area <= 0) throw std::runtime_error(QObject::tr("select surfaces or closed planar curves").toStdString());
      entities_.push_back(document::make_entity(centroid));
      message_ = QObject::tr("Area %1   centroid (%2, %3, %4)").arg(num(area), num(centroid.x), num(centroid.y), num(centroid.z));
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return false;
    }
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }

  static std::pair<double, nf::Vec3> area_centroid(const std::vector<nf::TrimmedSurface>& faces) {
    double area = 0;
    nf::Vec3 moment{0, 0, 0};
    for (const nf::TrimmedSurface& f : faces) {
      const nf::NurbsSurface& s = f.surface();
      const double a = f.area();
      double size = 1;
      for (const nf::Vec3& p : s.control_points()) size = std::max(size, nf::norm(p));
      const double tol = 1e-10 * std::max(a, 1e-12) * size;
      double m[3];
      for (int k = 0; k < 3; ++k) {
        m[k] = f.integrate(
            [&](double u, double v) {
              const auto d = s.first_derivatives(u, v);
              const double da = nf::norm(nf::cross(d[1], d[2]));
              return (k == 0 ? d[0].x : k == 1 ? d[0].y : d[0].z) * da;
            },
            1e-10, tol);
      }
      area += a;
      moment = moment + nf::Vec3{m[0], m[1], m[2]};
    }
    return {area, area > 0 ? moment / area : nf::Vec3{0, 0, 0}};
  }
};

// ------------------------------------------------------------------------------ Check
/// Problems of one object: errors (bad objects) and remarks.
struct Findings {
  QStringList errors;
  QStringList notes;
};

Findings check(const document::Geometry& g) {
  Findings out;
  auto weights_ok = [](const std::vector<double>& w) {
    return std::all_of(w.begin(), w.end(), [](double x) { return std::isfinite(x) && x > 0; });
  };
  auto points_ok = [](const std::vector<nf::Vec3>& pts) {
    return std::all_of(pts.begin(), pts.end(), [](const nf::Vec3& p) { return std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z); });
  };
  auto surface = [&](const nf::NurbsSurface& s, const QString& what) {
    if (!points_ok(s.control_points())) out.errors << QObject::tr("%1: control points not finite").arg(what);
    if (!weights_ok(s.weights())) out.errors << QObject::tr("%1: weights not positive").arg(what);
    int undefined = 0;
    const auto du = s.domain_u(), dv = s.domain_v();
    for (int i = 1; i < 8; ++i) {  // inside only: collapsed edges (poles) are fine
      for (int j = 1; j < 8; ++j) {
        try {
          (void)s.normal(du[0] + (du[1] - du[0]) * i / 8.0, dv[0] + (dv[1] - dv[0]) * j / 8.0);
        } catch (...) {
          ++undefined;
        }
      }
    }
    if (undefined > 0) out.errors << QObject::tr("%1: no normal at %2 of 49 inner points").arg(what).arg(undefined);
  };
  auto face = [&](const nf::TrimmedSurface& f, const QString& what) {
    surface(f.surface(), what);
    if (f.is_untrimmed()) return;
    try {
      if (!(f.area() > 0)) out.errors << QObject::tr("%1: trimmed area not positive").arg(what);
    } catch (const std::exception& e) {
      out.errors << QObject::tr("%1: %2").arg(what, QString::fromUtf8(e.what()));
    }
  };
  std::visit(
      [&](const auto& v) {
        using T = std::decay_t<decltype(v)>;
        if constexpr (std::is_same_v<T, nf::Vec3>) {
          if (!points_ok({v})) out.errors << QObject::tr("point not finite");
        } else if constexpr (std::is_same_v<T, nf::NurbsCurve>) {
          if (!points_ok(v.control_points())) out.errors << QObject::tr("control points not finite");
          if (!weights_ok(v.weights())) out.errors << QObject::tr("weights not positive");
          if (nf::arc_length(v) < 1e-12) out.errors << QObject::tr("zero length");
        } else if constexpr (std::is_same_v<T, nf::NurbsSurface>) {
          surface(v, QObject::tr("surface"));
        } else if constexpr (std::is_same_v<T, nf::TrimmedSurface>) {
          face(v, QObject::tr("surface"));
        } else {
          for (std::size_t i = 0; i < v.faces().size(); ++i) face(v.faces()[i], QObject::tr("face %1").arg(i));
          if (const auto nm = v.non_manifold_edges(); !nm.empty()) {
            out.errors << QObject::tr("%1 non-manifold edges").arg(nm.size());
          }
          if (!v.is_consistently_oriented()) out.errors << QObject::tr("faces not consistently oriented");
          if (const auto free = v.free_edges(); !free.empty()) {
            out.notes << QObject::tr("open: %1 naked edges").arg(free.size());
          } else if (v.is_consistently_oriented() && v.volume() < 0) {
            out.errors << QObject::tr("closed, but the normals point inwards (negative volume)");
          }
        }
      },
      g);
  return out;
}

/// Check: the problems of the selected objects. SelBadObjects (all objects): selects those with
/// errors.
class CheckCommand : public Command {
 public:
  explicit CheckCommand(bool select) : select_bad_(select) {}
  QString id() const override { return select_bad_ ? QStringLiteral("selbadobjects") : QStringLiteral("check"); }
  QString title() const override { return select_bad_ ? QObject::tr("Select bad objects") : QObject::tr("Check"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    std::vector<const document::Entity*> objects;
    if (select_bad_ && doc_ != nullptr) {
      for (const auto& [id, e] : doc_->entities()) objects.push_back(&e);
    } else {
      for (const document::Entity& e : selection) objects.push_back(&e);
    }
    if (objects.empty()) {
      message_ = QObject::tr("Check: select objects");
      return false;
    }
    std::vector<document::SelectionItem> bad;
    QStringList lines;
    for (const document::Entity* e : objects) {
      const Findings f = check(*e->geometry);
      if (!f.errors.isEmpty()) bad.push_back({e->id, {}});
      if (!f.errors.isEmpty() || !f.notes.isEmpty()) {
        const QString name = e->name.isEmpty() ? QObject::tr("object %1").arg(e->id) : e->name;
        lines << QObject::tr("%1: %2").arg(name, (f.errors + f.notes).join(QStringLiteral(", ")));
      }
    }
    if (select_bad_) {
      select_ = bad;
      message_ = bad.empty() ? QObject::tr("No bad objects") : QObject::tr("%n bad object(s) selected – %1", "", int(bad.size())).arg(lines.join(QStringLiteral("; ")));
    } else {
      message_ = lines.isEmpty() ? QObject::tr("Check: %n object(s), no problems", "", int(objects.size()))
                                 : QObject::tr("Check: %1").arg(lines.join(QStringLiteral("; ")));
    }
    bad_ = bad.size();
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }
  [[nodiscard]] std::size_t badCount() const { return bad_; }

 private:
  bool select_bad_;
  std::size_t bad_ = 0;
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"zebra", {}, [] { return std::make_unique<AnalysisCommand>(Analysis::Kind::Zebra); }},
      {"emap", {}, [] { return std::make_unique<AnalysisCommand>(Analysis::Kind::EMap); }},
      {"curvatureanalysis", {"curvanalysis"}, [] { return std::make_unique<AnalysisCommand>(Analysis::Kind::Curvature); }},
      {"draftangleanalysis", {"draftangle"}, [] { return std::make_unique<AnalysisCommand>(Analysis::Kind::Draft); }},
      {"analysisoff", {"noanalysis"}, [] { return std::make_unique<AnalysisCommand>(Analysis::Kind::None); }},
      {"gcon", {"continuity"}, [] { return std::make_unique<GConCommand>(); }},
      {"areacentroid", {}, [] { return std::make_unique<AreaCentroidCommand>(); }},
      {"check", {}, [] { return std::make_unique<CheckCommand>(false); }},
      {"selbadobjects", {}, [] { return std::make_unique<CheckCommand>(true); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_analysis_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList analysis_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
