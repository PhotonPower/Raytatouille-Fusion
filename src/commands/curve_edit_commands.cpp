// Editing curves (docs/commands.md, "Editing curves"): Extend, Divide, Divide by length, Rebuild,
// Change degree, Flip, Close, Seam, Insert knot, Remove knot, Smooth, Fair, Match, Simplify,
// Arc blend. Commands that change a curve replace its geometry (one undo step); Divide adds
// points, Arc blend a curve.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <exception>
#include <functional>
#include <limits>
#include <nurbforge/analysis/closest_point.hpp>
#include <nurbforge/analysis/properties.hpp>
#include <nurbforge/geometry/primitives.hpp>
#include <stdexcept>
#include <tuple>
#include <nurbforge/modeling/extend.hpp>
#include <nurbforge/modeling/surface_tools.hpp>
#include <nurbforge/nurbs/join.hpp>

#include "commands/command_util.hpp"

namespace nfcad::commands {

namespace {

using namespace util;

/// Largest distance between two curves at `n` samples of the first (closest points on the
/// second): a bound for the change a command made.
double deviation(const nf::NurbsCurve& from, const nf::NurbsCurve& to, std::size_t n = 200) {
  double d = 0;
  for (const nf::Vec3& p : from.sample(n)) d = std::max(d, nf::closest_point(to, p).distance);
  return d;
}

double size_of(const nf::NurbsCurve& c) {
  nf::Vec3 lo{1e300, 1e300, 1e300}, hi{-1e300, -1e300, -1e300};
  for (const nf::Vec3& p : c.control_points()) {
    lo = {std::min(lo.x, p.x), std::min(lo.y, p.y), std::min(lo.z, p.z)};
    hi = {std::max(hi.x, p.x), std::max(hi.y, p.y), std::max(hi.z, p.z)};
  }
  return std::max(nf::distance(lo, hi), 1e-9);
}

bool is_closed(const nf::NurbsCurve& c) {
  return nf::distance(c.evaluate(c.domain_start()), c.evaluate(c.domain_end())) <= 1e-9 * size_of(c);
}

/// The selected curves (and their ids), in selection order.
class EditCurvesCommand : public Command {
 public:
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (const auto* c = std::get_if<nf::NurbsCurve>(e.geometry.get())) {
        curves_.push_back(*c);
        ids_.push_back(e.id);
      }
    }
    if (curves_.size() < min_ || (max_ > 0 && curves_.size() > max_)) {
      message_ = QObject::tr("%1: select %2").arg(title(), requirement_);
      return false;
    }
    return prepare();
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }

 protected:
  EditCurvesCommand(std::size_t min, std::size_t max, QString requirement)
      : min_(min), max_(max), requirement_(std::move(requirement)) {}
  virtual bool prepare() { return true; }
  void replaceCurve(std::size_t i, const nf::NurbsCurve& c) {
    replace_.emplace_back(ids_[i], std::make_shared<const document::Geometry>(c));
    curves_[i] = c;
  }
  /// The index of the selected curve nearest p, and the parameter there.
  std::pair<std::size_t, nf::CurvePoint> nearest(const Point3& p) const {
    std::size_t best = 0;
    nf::CurvePoint at;
    double d = std::numeric_limits<double>::infinity();
    for (std::size_t i = 0; i < curves_.size(); ++i) {
      const nf::CurvePoint q = nf::closest_point(curves_[i], V(p));
      if (q.distance < d) {
        d = q.distance;
        at = q;
        best = i;
      }
    }
    return {best, at};
  }
  /// Runs `edit` on every curve; on failure the reason in message_ and nothing changed.
  Result each(const std::function<nf::NurbsCurve(const nf::NurbsCurve&)>& edit) {
    try {
      for (std::size_t i = 0; i < curves_.size(); ++i) replaceCurve(i, edit(curves_[i]));
      return Result::Done;
    } catch (const std::exception& e) {
      replace_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::vector<nf::NurbsCurve> curves_;
  std::vector<document::EntityId> ids_;

 private:
  std::size_t min_, max_;
  QString requirement_;
};

// ------------------------------------------------------------------------------ Extend
/// Extend: click near the end of a selected curve, then the extension length (a number, or a
/// point: its distance from the end); the natural continuation of the curve.
class ExtendCommand : public EditCurvesCommand {
 public:
  ExtendCommand() : EditCurvesCommand(1, 0, QObject::tr("curves")) {}
  QString id() const override { return QStringLiteral("extend"); }
  QString title() const override { return QObject::tr("Extend curve"); }
  QString prompt() const override {
    return end_ ? QObject::tr("Extend: length (number or a point)")
                : QObject::tr("Extend: click near the end to extend");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (!end_) {
      const auto [i, at] = nearest(p);
      const nf::NurbsCurve& c = curves_[i];
      index_ = i;
      end_ = at.u - c.domain_start() < c.domain_end() - at.u ? nf::CurveEnd::Start : nf::CurveEnd::End;
      return Result::Continue;
    }
    return create(nf::distance(V(p), end_point()));
  }
  Result number(double v) override { return end_ ? create(v) : Result::Rejected; }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (!end_) return {};
    try {
      const nf::NurbsCurve ext = nf::extend(curves_[index_], *end_, nf::distance(V(c), end_point()));
      return {sample(ext, 128)};
    } catch (const std::exception&) {
      return {};
    }
  }
  std::optional<Point3> basePoint() const override {
    return end_ ? std::optional(P(end_point())) : std::nullopt;
  }

 private:
  nf::Vec3 end_point() const {
    const nf::NurbsCurve& c = curves_[index_];
    return c.evaluate(*end_ == nf::CurveEnd::Start ? c.domain_start() : c.domain_end());
  }
  Result create(double length) {
    if (length <= 0) return Result::Rejected;
    try {
      replaceCurve(index_, nf::extend(curves_[index_], *end_, length));
      return Result::Done;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::size_t index_ = 0;
  std::optional<nf::CurveEnd> end_;
};

// ------------------------------------------------------------------------------ Divide
/// Divide: points on the selected curves – a number of equal segments (by arc length), or every
/// typed length from the start (Divide by length).
class DivideCommand : public EditCurvesCommand {
 public:
  explicit DivideCommand(bool by_length)
      : EditCurvesCommand(1, 0, QObject::tr("curves")), by_length_(by_length) {}
  QString id() const override { return by_length_ ? QStringLiteral("divide_length") : QStringLiteral("divide"); }
  QString title() const override { return by_length_ ? QObject::tr("Divide by length") : QObject::tr("Divide"); }
  QString prompt() const override {
    return by_length_ ? QObject::tr("Divide by length: segment length")
                      : QObject::tr("Divide: number of segments");
  }
  Result number(double v) override {
    if (v <= 0 || (!by_length_ && (std::floor(v) != v || v > 10000))) return Result::Rejected;
    try {
      for (const nf::NurbsCurve& c : curves_) {
        const double total = nf::arc_length(c);
        const std::size_t n = by_length_ ? static_cast<std::size_t>(std::floor(total / v + 1e-9))
                                         : static_cast<std::size_t>(v);
        if (n > 100000) throw std::invalid_argument("more than 100000 points");
        const double step = by_length_ ? v : total / static_cast<double>(n);
        const std::size_t last = (!by_length_ && is_closed(c)) ? n - 1 : n;  // a closed curve: no double point
        for (std::size_t k = 0; k <= last; ++k) {
          const double s = std::min(step * static_cast<double>(k), total);
          entities_.push_back(document::make_entity(c.evaluate(nf::parameter_at_length(c, s))));
        }
      }
      return Result::Done;
    } catch (const std::exception& e) {
      entities_.clear();
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }

 private:
  bool by_length_;
};

// ------------------------------------------------------------------------------ Rebuild, Change degree
/// Rebuild: the selected curves with the typed number of control points, then the degree
/// (Enter: 3); uniform knots, a least-squares fit. The status line gives the largest deviation.
class RebuildCommand : public EditCurvesCommand {
 public:
  RebuildCommand() : EditCurvesCommand(1, 0, QObject::tr("curves")) {}
  QString id() const override { return QStringLiteral("rebuild"); }
  QString title() const override { return QObject::tr("Rebuild curve"); }
  QString prompt() const override {
    if (!count_) {
      return QObject::tr("Rebuild: number of control points (now %1)").arg(curves_.front().num_control_points());
    }
    return QObject::tr("Rebuild (%1 points): degree (Enter: 3)").arg(*count_);
  }
  Result number(double v) override {
    if (std::floor(v) != v || v < 1) return Result::Rejected;
    if (!count_) {
      if (v < 2 || v > 10000) return Result::Rejected;
      count_ = static_cast<std::size_t>(v);
      return Result::Continue;
    }
    return create(static_cast<std::size_t>(v));
  }
  Result finish() override { return count_ ? create(3) : Result::Cancelled; }

 private:
  Result create(std::size_t degree) {
    if (degree + 1 > *count_) {
      message_ = QObject::tr("Rebuild: degree %1 needs at least %2 control points").arg(degree).arg(degree + 1);
      return Result::Rejected;
    }
    double worst = 0;
    const Result r = each([&](const nf::NurbsCurve& c) {
      const nf::RebuiltCurve rb = nf::rebuild_curve(c, *count_, degree);
      worst = std::max(worst, rb.max_error);
      return rb.curve;
    });
    if (r == Result::Done) message_ = QObject::tr("Rebuild: largest deviation %1").arg(worst, 0, 'g', 3);
    return r;
  }
  std::optional<std::size_t> count_;
};

/// Change degree: raising is exact (the shape stays); lowering fits within 0.1 % of the curve's
/// size, else the curve is rebuilt with as many control points as before.
class ChangeDegreeCommand : public EditCurvesCommand {
 public:
  ChangeDegreeCommand() : EditCurvesCommand(1, 0, QObject::tr("curves")) {}
  QString id() const override { return QStringLiteral("change_degree"); }
  QString title() const override { return QObject::tr("Change degree"); }
  QString prompt() const override {
    return QObject::tr("Change degree: new degree (now %1)").arg(curves_.front().degree());
  }
  Result number(double v) override {
    if (std::floor(v) != v || v < 1 || v > 11) return Result::Rejected;
    const auto p = static_cast<std::size_t>(v);
    return each([&](const nf::NurbsCurve& c) {
      if (p == c.degree()) return c;
      if (p > c.degree()) return c.elevate_degree(p - c.degree());
      nf::NurbsCurve out = c;
      try {
        while (out.degree() > p) out = out.reduce_degree(1e-3 * size_of(c));
        return out;
      } catch (const std::exception&) {
        return nf::rebuild_curve(c, std::max(c.num_control_points(), p + 1), p).curve;
      }
    });
  }
};

// ------------------------------------------------------------------------------ Flip, Close
/// Flip: reverses the direction of the selected curves (and the normals of selected surfaces).
class FlipCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("flip"); }
  QString title() const override { return QObject::tr("Flip direction"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (const auto* c = std::get_if<nf::NurbsCurve>(e.geometry.get())) {
        replace_.emplace_back(e.id, std::make_shared<const document::Geometry>(c->reversed()));
      } else if (const auto* f = std::get_if<nf::TrimmedSurface>(e.geometry.get())) {
        replace_.emplace_back(e.id, std::make_shared<const document::Geometry>(f->flipped()));
      } else if (const auto* s = std::get_if<nf::NurbsSurface>(e.geometry.get())) {
        replace_.emplace_back(e.id, std::make_shared<const document::Geometry>(nf::TrimmedSurface(*s).flipped()));
      }
    }
    if (replace_.empty()) {
      message_ = QObject::tr("Flip: select curves or surfaces");
      return false;
    }
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }
};

/// Close: an open curve whose ends are near (within 1 % of its length) gets its end moved onto
/// its start; otherwise a straight segment closes it.
class CloseCommand : public EditCurvesCommand {
 public:
  CloseCommand() : EditCurvesCommand(1, 0, QObject::tr("open curves")) {}
  QString id() const override { return QStringLiteral("close"); }
  QString title() const override { return QObject::tr("Close curve"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    return each([](const nf::NurbsCurve& c) { return closed(c); });
  }

  static nf::NurbsCurve closed(const nf::NurbsCurve& c) {
    const nf::Vec3 a = c.evaluate(c.domain_start()), b = c.evaluate(c.domain_end());
    const double gap = nf::distance(a, b);
    if (gap <= 1e-12 * size_of(c)) return c;
    if (gap <= 0.01 * nf::arc_length(c) && c.is_clamped()) {
      std::vector<nf::Vec3> pts = c.control_points();
      pts.back() = pts.front();
      return {c.degree(), c.knots(), pts, c.weights()};
    }
    return nf::join(c, nf::make_line(b, a));
  }
};

// ------------------------------------------------------------------------------ Seam
/// Seam: moves the start (and end) of a selected closed curve to a clicked point on it.
class SeamCommand : public EditCurvesCommand {
 public:
  SeamCommand() : EditCurvesCommand(1, 1, QObject::tr("one closed curve")) {}
  QString id() const override { return QStringLiteral("seam"); }
  QString title() const override { return QObject::tr("Curve seam"); }
  QString prompt() const override { return QObject::tr("Seam: click the new start point on the curve"); }
  Result point(const Point3& p, const PlaneFrame&) override {
    const nf::NurbsCurve& c = curves_.front();
    const double u = nf::closest_point(c, V(p)).u;
    const double span = c.domain_end() - c.domain_start();
    if (u - c.domain_start() < 1e-9 * span || c.domain_end() - u < 1e-9 * span) return Result::Done;  // already
    try {
      const auto [first, second] = c.split(u);
      replaceCurve(0, nf::join(second, first, 1e-6 * size_of(c)));
      return Result::Done;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    const nf::Vec3 at = nf::closest_point(curves_.front(), V(c)).point;
    return {{c, P(at)}};
  }

 protected:
  bool prepare() override {
    if (is_closed(curves_.front())) return true;
    message_ = QObject::tr("Seam: the curve is not closed");
    return false;
  }
};

// ------------------------------------------------------------------------------ Knots
/// Insert knot: knots at the clicked points of the selected curve (the shape stays); Remove
/// knot: the interior knot nearest each click (the shape changes); Enter: done.
class KnotCommand : public EditCurvesCommand {
 public:
  explicit KnotCommand(bool insert) : EditCurvesCommand(1, 1, QObject::tr("one curve")), insert_(insert) {}
  QString id() const override { return insert_ ? QStringLiteral("insert_knot") : QStringLiteral("remove_knot"); }
  QString title() const override { return insert_ ? QObject::tr("Insert knot") : QObject::tr("Remove knot"); }
  QString prompt() const override {
    return insert_ ? QObject::tr("Insert knot: click on the curve (Enter: done)")
                   : QObject::tr("Remove knot: click near a knot (Enter: done)");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    const nf::NurbsCurve& c = curves_.front();
    try {
      if (insert_) {
        replaceCurve(0, c.insert_knot(nf::closest_point(c, V(p)).u));
      } else {
        const auto k = nearest_knot(c, V(p));
        if (!k) {
          message_ = QObject::tr("Remove knot: the curve has no interior knot");
          return Result::Rejected;
        }
        replaceCurve(0, c.remove_knot(*k, 1, std::numeric_limits<double>::max()));
      }
      ++count_;
      return Result::Continue;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  Result finish() override { return count_ > 0 ? Result::Done : Result::Cancelled; }
  std::vector<Polyline3> preview(const Point3& cursor, const PlaneFrame&) const override {
    const nf::NurbsCurve& c = curves_.front();
    if (insert_) return {{cursor, P(nf::closest_point(c, V(cursor)).point)}};
    const auto k = nearest_knot(c, V(cursor));
    if (!k) return {};
    return {{cursor, P(c.evaluate(*k))}};
  }
  /// The interior knot whose curve point lies nearest p.
  static std::optional<double> nearest_knot(const nf::NurbsCurve& c, const nf::Vec3& p) {
    std::optional<double> best;
    double d = std::numeric_limits<double>::infinity();
    for (double k : c.knots()) {
      if (k <= c.domain_start() || k >= c.domain_end()) continue;
      const double dk = nf::distance(c.evaluate(k), p);
      if (dk < d) {
        d = dk;
        best = k;
      }
    }
    return best;
  }

 private:
  bool insert_;
  int count_ = 0;
};

// ------------------------------------------------------------------------------ Smooth, Fair
/// Moves every interior control point towards the mean of its neighbours by `factor` (the ends
/// stay; a closed curve's seam point too).
nf::NurbsCurve smoothed(const nf::NurbsCurve& c, double factor) {
  std::vector<nf::Vec3> p = c.control_points();
  const std::vector<nf::Vec3> q = p;
  for (std::size_t i = 1; i + 1 < p.size(); ++i) p[i] = q[i] + ((q[i - 1] + q[i + 1]) * 0.5 - q[i]) * factor;
  return {c.degree(), c.knots(), p, c.weights()};
}

/// Smooth: one smoothing step of the control points (factor 0 … 1, Enter: 0.5); repeat with the
/// next command for more.
class SmoothCommand : public EditCurvesCommand {
 public:
  SmoothCommand() : EditCurvesCommand(1, 0, QObject::tr("curves")) {}
  QString id() const override { return QStringLiteral("smooth"); }
  QString title() const override { return QObject::tr("Smooth curve"); }
  QString prompt() const override { return QObject::tr("Smooth: factor 0 … 1 (Enter: 0.5)"); }
  Result number(double v) override {
    if (v <= 0 || v > 1) return Result::Rejected;
    return each([&](const nf::NurbsCurve& c) { return smoothed(c, v); });
  }
  Result finish() override { return number(0.5); }
};

/// Fair: smooths the control points step by step as long as the curve stays within the typed
/// tolerance of the original (ends fixed) – removes wiggles, keeps the shape.
class FairCommand : public EditCurvesCommand {
 public:
  FairCommand() : EditCurvesCommand(1, 0, QObject::tr("curves")) {}
  QString id() const override { return QStringLiteral("fair"); }
  QString title() const override { return QObject::tr("Fair curve"); }
  QString prompt() const override { return QObject::tr("Fair: tolerance (largest change of the curve)"); }
  Result number(double tol) override {
    if (tol <= 0) return Result::Rejected;
    return each([&](const nf::NurbsCurve& c) { return faired(c, tol); });
  }

  static nf::NurbsCurve faired(const nf::NurbsCurve& c, double tol) {
    // smoothing steps, each as large as the tolerance allows (halved down to 1/64)
    nf::NurbsCurve out = c;
    double factor = 0.25;
    for (int step = 0; step < 200 && factor >= 0.25 / 64; ++step) {
      const nf::NurbsCurve next = smoothed(out, factor);
      if (deviation(next, c) > tol) {
        factor *= 0.5;
        continue;
      }
      out = next;
    }
    return out;
  }
};

// ------------------------------------------------------------------------------ Match
/// The end `end` of the first curve and the end of the second nearest to it (the pair of ends
/// closest to each other, `ends`).
std::pair<nf::CurveEnd, nf::CurveEnd> closest_ends(const nf::NurbsCurve& a, const nf::NurbsCurve& b) {
  std::pair<nf::CurveEnd, nf::CurveEnd> best{nf::CurveEnd::End, nf::CurveEnd::Start};
  double d = std::numeric_limits<double>::infinity();
  for (auto ea : {nf::CurveEnd::Start, nf::CurveEnd::End}) {
    for (auto eb : {nf::CurveEnd::Start, nf::CurveEnd::End}) {
      const double dd = nf::distance(a.evaluate(ea == nf::CurveEnd::Start ? a.domain_start() : a.domain_end()),
                                     b.evaluate(eb == nf::CurveEnd::Start ? b.domain_start() : b.domain_end()));
      if (dd < d) {
        d = dd;
        best = {ea, eb};
      }
    }
  }
  return best;
}

/// Changes the end of `a` (at its domain end) so that it meets `b` at its start with position
/// (continuity 0), tangent direction (1) and curvature vector (2): the last continuity + 1
/// control points are solved from the end derivatives, which are linear in them (a must be
/// non-rational and clamped). Its speed at the end is kept.
nf::NurbsCurve match_end(nf::NurbsCurve a, const nf::NurbsCurve& b, int continuity) {
  if (a.is_rational()) throw std::invalid_argument("the curve to change is rational – rebuild it first");
  a = a.clamped();
  // enough degree and control points: the start must stay where it is
  if (a.degree() < static_cast<std::size_t>(continuity)) a = a.elevate_degree(continuity - a.degree());
  while (a.num_control_points() < static_cast<std::size_t>(continuity) + 3) {
    const nf::KnotVector& k = a.knots();
    double widest = 0, at = 0;
    for (std::size_t i = a.degree(); i < a.num_control_points(); ++i) {
      if (k[i + 1] - k[i] > widest) {
        widest = k[i + 1] - k[i];
        at = 0.5 * (k[i] + k[i + 1]);
      }
    }
    a = a.insert_knot(at);
  }
  const std::size_t n = a.num_control_points(), m = static_cast<std::size_t>(continuity) + 1;
  const double ue = a.domain_end(), ub = b.domain_start();
  const std::vector<nf::Vec3> da = a.derivatives(ue, 2), db = b.derivatives(ub, 2);
  // targets: B's position; A's speed along B's direction; B's curvature vector at that speed
  const double lambda = nf::norm(db[1]) > 0 ? nf::norm(da[1]) / nf::norm(db[1]) : 1.0;
  const nf::Vec3 target[3] = {db[0], db[1] * lambda, db[2] * (lambda * lambda)};
  // basis derivatives of the last m control points at the end (unit control points)
  double N[3][3] = {};
  for (std::size_t j = 0; j < m; ++j) {
    std::vector<nf::Vec3> unit(n, nf::Vec3{0, 0, 0});
    unit[n - m + j] = {1, 0, 0};
    const nf::NurbsCurve e(a.degree(), a.knots(), unit);
    const auto d = e.derivatives(ue, 2);
    for (std::size_t k = 0; k < m; ++k) N[k][j] = d[k].x;
  }
  // the other control points' share of the end derivatives
  std::vector<nf::Vec3> rest = a.control_points();
  for (std::size_t j = 0; j < m; ++j) rest[n - m + j] = {0, 0, 0};
  const auto fixed = nf::NurbsCurve(a.degree(), a.knots(), rest).derivatives(ue, 2);
  // solve N x = target - fixed for each coordinate (Gaussian elimination, m <= 3)
  std::vector<nf::Vec3> ctrl = a.control_points();
  double M[3][4];
  for (int c = 0; c < 3; ++c) {
    for (std::size_t k = 0; k < m; ++k) {
      for (std::size_t j = 0; j < m; ++j) M[k][j] = N[k][j];
      const nf::Vec3 rhs = target[k] - fixed[k];
      M[k][m] = c == 0 ? rhs.x : c == 1 ? rhs.y : rhs.z;
    }
    for (std::size_t i = 0; i < m; ++i) {
      std::size_t piv = i;
      for (std::size_t r = i + 1; r < m; ++r) {
        if (std::abs(M[r][i]) > std::abs(M[piv][i])) piv = r;
      }
      if (std::abs(M[piv][i]) < 1e-300) throw std::runtime_error("the end cannot be matched");
      for (std::size_t q = 0; q <= m; ++q) std::swap(M[i][q], M[piv][q]);
      for (std::size_t r = 0; r < m; ++r) {
        if (r == i) continue;
        const double f = M[r][i] / M[i][i];
        for (std::size_t q = i; q <= m; ++q) M[r][q] -= f * M[i][q];
      }
    }
    for (std::size_t j = 0; j < m; ++j) {
      const double x = M[j][m] / M[j][j];
      nf::Vec3& p = ctrl[n - m + j];
      (c == 0 ? p.x : c == 1 ? p.y : p.z) = x;
    }
  }
  return {a.degree(), a.knots(), ctrl};
}

/// Match: the end of the first selected curve nearest the second is changed to meet the second
/// with G0 (position), G1 (tangent) or G2 (curvature; default); the second stays.
class MatchCommand : public EditCurvesCommand {
 public:
  MatchCommand() : EditCurvesCommand(2, 2, QObject::tr("two curves: the one to change, then the one to match")) {}
  QString id() const override { return QStringLiteral("match"); }
  QString title() const override { return QObject::tr("Match curve"); }
  QString prompt() const override {
    return QObject::tr("Match: continuity 0 (position), 1 (tangent) or 2 (curvature) – Enter: 2");
  }
  Result number(double v) override {
    if (v != 0 && v != 1 && v != 2) return Result::Rejected;
    try {
      replaceCurve(0, matched(curves_[0], curves_[1], static_cast<int>(v)));
      return Result::Done;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  Result finish() override { return number(2); }

  static nf::NurbsCurve matched(const nf::NurbsCurve& a, const nf::NurbsCurve& b, int continuity) {
    const auto [ea, eb] = closest_ends(a, b);
    // in the standard situation: a ends where b starts
    const nf::NurbsCurve a1 = ea == nf::CurveEnd::End ? a : a.reversed();
    const nf::NurbsCurve b1 = eb == nf::CurveEnd::Start ? b : b.reversed();
    const nf::NurbsCurve m = match_end(a1, b1, continuity);
    return ea == nf::CurveEnd::End ? m : m.reversed();
  }
};

// ------------------------------------------------------------------------------ Simplify
/// Simplify: the Bézier pieces of the selected curves that are straight or circular (within
/// 1e-6 of the curve's size) become exact lines and arcs; neighbouring pieces on one line or
/// circle become one. The curve keeps its shape.
class SimplifyCommand : public EditCurvesCommand {
 public:
  SimplifyCommand() : EditCurvesCommand(1, 0, QObject::tr("curves")) {}
  QString id() const override { return QStringLiteral("simplify"); }
  QString title() const override { return QObject::tr("Simplify curve"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override { return each([](const nf::NurbsCurve& c) { return simplified(c); }); }

  static nf::NurbsCurve simplified(const nf::NurbsCurve& c) {
    const double tol = 1e-6 * size_of(c);
    struct Piece {
      enum Kind { Line, Arc, Other } kind;
      nf::NurbsCurve curve;
      nf::Vec3 a, b, mid;  // ends and (for arcs) a point between
      nf::Vec3 centre{};
      double radius = 0;
      nf::Vec3 normal{};
    };
    std::vector<Piece> pieces;
    for (const nf::NurbsCurve& s : c.decompose_bezier()) {
      const nf::Vec3 a = s.evaluate(s.domain_start()), b = s.evaluate(s.domain_end());
      const nf::Vec3 mid = s.evaluate(0.5 * (s.domain_start() + s.domain_end()));
      const auto samples = s.sample(24);
      // a line: every sample on the chord
      if (nf::distance(a, b) > tol) {
        const nf::Vec3 dir = nf::normalized(b - a);
        bool straight = true;
        for (const nf::Vec3& q : samples) straight = straight && nf::norm(nf::cross(q - a, dir)) <= tol;
        if (straight) {
          pieces.push_back({Piece::Line, nf::make_line(a, b), a, b, mid});
          continue;
        }
      }
      // an arc: the circle through the ends and the middle holds every sample
      try {
        // centre: equidistant from a, mid, b in their plane
        const nf::Vec3 ab = b - a, am = mid - a;
        const nf::Vec3 w = nf::cross(ab, am);
        if (nf::norm(w) <= tol * nf::norm(ab)) throw std::invalid_argument("collinear");
        const nf::Vec3 n = nf::normalized(nf::cross(mid - a, b - a));
        const nf::Vec3 centre = a + (nf::cross(w, ab) * nf::dot(am, am) + nf::cross(am, w) * nf::dot(ab, ab)) /
                                        (2.0 * nf::dot(w, w));
        const double r = nf::distance(centre, a);
        bool round = true;
        for (const nf::Vec3& q : samples) round = round && std::abs(nf::distance(q, centre) - r) <= tol &&
                                                  std::abs(nf::dot(q - centre, n)) <= tol;
        if (round) {
          pieces.push_back({Piece::Arc, nf::make_arc_3pt(a, mid, b), a, b, mid, centre, r, n});
          continue;
        }
      } catch (const std::exception&) {
      }
      pieces.push_back({Piece::Other, s, a, b, mid});
    }
    // merge neighbouring lines on one line and arcs on one circle
    std::vector<nf::NurbsCurve> merged;
    for (std::size_t i = 0; i < pieces.size();) {
      Piece p = pieces[i];
      std::size_t j = i + 1;
      if (p.kind == Piece::Line) {
        while (j < pieces.size() && pieces[j].kind == Piece::Line &&
               nf::norm(nf::cross(pieces[j].b - p.a, nf::normalized(p.b - p.a))) <= tol &&
               nf::dot(pieces[j].b - pieces[j].a, p.b - p.a) > 0) {
          p.b = pieces[j].b;
          ++j;
        }
        merged.push_back(nf::make_line(p.a, p.b));
      } else if (p.kind == Piece::Arc) {
        nf::Vec3 through = p.mid;
        while (j < pieces.size() && pieces[j].kind == Piece::Arc && nf::distance(pieces[j].centre, p.centre) <= tol &&
               std::abs(pieces[j].radius - p.radius) <= tol && nf::norm(nf::cross(pieces[j].normal, p.normal)) <= 1e-9 &&
               nf::dot(pieces[j].normal, p.normal) > 0) {
          through = p.b;  // the old joint lies on the merged arc
          p.b = pieces[j].b;
          ++j;
        }
        // a full circle cannot be one 3-point arc: keep the pieces then
        if (j > i + 1 && nf::distance(p.a, p.b) <= tol) {
          for (std::size_t k = i; k < j; ++k) merged.push_back(pieces[k].curve);
        } else {
          merged.push_back(j > i + 1 ? nf::make_arc_3pt(p.a, through, p.b) : p.curve);
        }
      } else {
        merged.push_back(p.curve);
      }
      i = j;
    }
    nf::NurbsCurve out = merged.front();
    for (std::size_t k = 1; k < merged.size(); ++k) out = nf::join(out, merged[k], 1e-6 * size_of(c));
    return out;
  }
};

// ------------------------------------------------------------------------------ Arc blend
/// Arc blend: two circular arcs (a biarc with equal tangent lengths) between the closest ends of
/// two selected curves, tangent to both.
class ArcBlendCommand : public EditCurvesCommand {
 public:
  ArcBlendCommand() : EditCurvesCommand(2, 2, QObject::tr("two curves")) {}
  QString id() const override { return QStringLiteral("arc_blend"); }
  QString title() const override { return QObject::tr("Arc blend"); }
  QString prompt() const override { return title(); }
  bool immediate() const override { return true; }
  Result finish() override {
    try {
      entities_.push_back(document::make_entity(blend(curves_[0], curves_[1])));
      return Result::Done;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }

  static nf::NurbsCurve blend(const nf::NurbsCurve& a, const nf::NurbsCurve& b) {
    const auto [ea, eb] = closest_ends(a, b);
    const nf::NurbsCurve a1 = ea == nf::CurveEnd::End ? a : a.reversed();
    const nf::NurbsCurve b1 = eb == nf::CurveEnd::Start ? b : b.reversed();
    const nf::Vec3 p0 = a1.evaluate(a1.domain_end()), p1 = b1.evaluate(b1.domain_start());
    const nf::Vec3 t0 = nf::normalized(a1.tangent(a1.domain_end())), t1 = nf::normalized(b1.tangent(b1.domain_start()));
    const nf::Vec3 d = p1 - p0;
    if (nf::norm(d) < 1e-12) throw std::invalid_argument("the ends coincide");
    // equal tangent lengths alpha: |d - alpha (t0 + t1)| = 2 alpha
    const double tt = nf::dot(t0, t1), dv = nf::dot(d, t0 + t1), dd = nf::dot(d, d);
    double alpha;
    if (std::abs(1.0 - tt) < 1e-12) {
      if (std::abs(dv) < 1e-12) throw std::invalid_argument("the ends face each other side by side");
      alpha = dd / (2.0 * dv);
    } else {
      alpha = (-dv + std::sqrt(dv * dv + 2.0 * (1.0 - tt) * dd)) / (2.0 * (1.0 - tt));
    }
    const nf::Vec3 q0 = p0 + t0 * alpha, q1 = p1 - t1 * alpha, joint = (q0 + q1) * 0.5;
    const auto arc = [](const nf::Vec3& s, const nf::Vec3& t, const nf::Vec3& e) {
      try {
        return nf::make_arc_tangent(s, t, e);
      } catch (const std::exception&) {
        return nf::make_line(s, e);  // straight: the end on the tangent line
      }
    };
    const nf::NurbsCurve first = arc(p0, t0, joint);
    const nf::NurbsCurve second = arc(joint, nf::normalized(q1 - q0), p1);
    return nf::join(first, second, 1e-9 * std::max(1.0, nf::norm(d)));
  }
};

// ------------------------------------------------------------------------------ control points
/// Points on / off: shows or hides the control points (grips) and control polygon of the
/// selected curves – an attribute, saved with the document. Points off without a selection:
/// every curve.
class PointsCommand : public Command {
 public:
  explicit PointsCommand(bool on) : on_(on) {}
  QString id() const override { return on_ ? QStringLiteral("points_on") : QStringLiteral("points_off"); }
  QString title() const override { return on_ ? QObject::tr("Points on") : QObject::tr("Points off"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool usesGrips() const override { return !on_; }  // a curve picked by its grips counts
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    std::vector<const document::Entity*> targets;
    for (const document::Entity& e : selection) targets.push_back(&e);
    std::vector<document::Entity> gripped;
    if (doc_ != nullptr) {
      for (const GripSet& g : grips_) {
        if (const document::Entity* e = doc_->entity(g.id)) gripped.push_back(*e);
      }
      if (!on_ && selection.empty() && grips_.empty()) {
        for (const auto& [id, e] : doc_->entities()) gripped.push_back(e);
      }
    }
    for (const document::Entity& e : gripped) targets.push_back(&e);
    for (const document::Entity* e : targets) {
      if (std::get_if<nf::NurbsCurve>(e->geometry.get()) == nullptr && std::get_if<nf::NurbsSurface>(e->geometry.get()) == nullptr &&
          std::get_if<nf::TrimmedSurface>(e->geometry.get()) == nullptr) {
        continue;  // curves and single surfaces have control points
      }
      const bool now = e->attributes.value(QString::fromLatin1(kPointsOnKey)).toBool();
      if (now == on_) continue;
      QVariantMap a = e->attributes;
      if (on_) {
        a.insert(QString::fromLatin1(kPointsOnKey), true);
      } else {
        a.remove(QString::fromLatin1(kPointsOnKey));
      }
      attributes_.emplace_back(e->id, a);
    }
    if (!on_) select_ = std::vector<document::SelectionItem>{};  // the grips leave the selection
    if (on_ && attributes_.empty()) {
      message_ = QObject::tr("Points on: select curves or surfaces");
      return false;
    }
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }

 private:
  bool on_;
};

/// Select points: every grip of the selected curves whose points are shown, or of all such
/// curves when none is selected.
class SelectPointsCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("select_points"); }
  QString title() const override { return QObject::tr("Select points"); }
  QString prompt() const override { return title(); }
  bool usesSelection() const override { return true; }
  bool usesGrips() const override { return true; }
  bool immediate() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    std::vector<document::Entity> curves = selection;
    if (doc_ != nullptr) {
      for (const GripSet& g : grips_) {
        if (const document::Entity* e = doc_->entity(g.id)) curves.push_back(*e);
      }
      if (curves.empty()) {
        for (const auto& [id, e] : doc_->entities()) curves.push_back(e);
      }
    }
    std::vector<document::SelectionItem> items;
    for (const document::Entity& e : curves) {
      const auto* c = std::get_if<nf::NurbsCurve>(e.geometry.get());
      if (c == nullptr || !e.attributes.value(QString::fromLatin1(kPointsOnKey)).toBool()) continue;
      for (std::size_t i = 0; i < c->num_control_points(); ++i) {
        items.push_back({e.id, {document::SubElement::Kind::ControlPoint, static_cast<int>(i)}});
      }
    }
    if (items.empty()) {
      message_ = QObject::tr("Select points: no curve shows its points (Points on)");
      return false;
    }
    select_ = std::move(items);
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result finish() override { return Result::Done; }
};

/// Weight: the typed weight (> 0) for the selected control points; 1 everywhere makes the curve
/// polynomial again, other weights rational (a weight above 1 pulls the curve towards its point).
class WeightCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("weight"); }
  QString title() const override { return QObject::tr("Weight"); }
  QString prompt() const override { return QObject::tr("Weight of the selected control points (> 0; 1: plain)"); }
  bool usesSelection() const override { return true; }
  bool usesGrips() const override { return true; }
  bool begin(const std::vector<document::Entity>&) override {
    if (grips_.empty()) {
      message_ = QObject::tr("Weight: select control points (Points on, then click them)");
      return false;
    }
    return true;
  }
  Result number(double w) override {
    if (w <= 0) return Result::Rejected;
    for (const GripSet& g : grips_) {
      const auto* c = std::get_if<nf::NurbsCurve>(g.geometry.get());
      if (c == nullptr) continue;
      std::vector<double> weights = c->weights();
      if (weights.size() != c->num_control_points()) weights.assign(c->num_control_points(), 1.0);
      for (int i : g.indices) {
        if (i >= 0 && static_cast<std::size_t>(i) < weights.size()) weights[static_cast<std::size_t>(i)] = w;
      }
      replace_.emplace_back(g.id, std::make_shared<const document::Geometry>(
                                      nf::NurbsCurve(c->degree(), c->knots(), c->control_points(), weights)));
    }
    return Result::Done;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
};

/// Insert control point: a click near the control polygon of the selected curve (or the curve
/// whose grips are selected) adds a control point there – a knot is inserted on that leg and its
/// new control point moved to the clicked spot, so the shape changes a little; Enter: done.
class InsertControlPointCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("insert_control_point"); }
  QString title() const override { return QObject::tr("Insert control point"); }
  QString prompt() const override {
    return QObject::tr("Insert control point: click near the control polygon (Enter: done)");
  }
  bool usesSelection() const override { return true; }
  bool usesGrips() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (const auto* c = std::get_if<nf::NurbsCurve>(e.geometry.get())) {
        curve_ = *c;
        id_ = e.id;
        break;
      }
    }
    if (!curve_ && !grips_.empty()) {
      if (const auto* c = std::get_if<nf::NurbsCurve>(grips_.front().geometry.get())) {
        curve_ = *c;
        id_ = grips_.front().id;
      }
    }
    if (!curve_) {
      message_ = QObject::tr("Insert control point: select a curve");
      return false;
    }
    return true;
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    try {
      curve_ = inserted(*curve_, V(p));
      replace_.emplace_back(id_, std::make_shared<const document::Geometry>(*curve_));
      ++count_;
      return Result::Continue;
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
  }
  Result finish() override { return count_ > 0 ? Result::Done : Result::Cancelled; }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    const auto [a, b, q] = leg(*curve_, V(c));
    return {{P(a), P(b)}, {c, P(q)}};
  }

  /// The control-polygon leg nearest p: its ends and the nearest point on it.
  static std::tuple<nf::Vec3, nf::Vec3, nf::Vec3> leg(const nf::NurbsCurve& c, const nf::Vec3& p) {
    const auto& pts = c.control_points();
    std::tuple<nf::Vec3, nf::Vec3, nf::Vec3> best{pts[0], pts[0], pts[0]};
    double d = std::numeric_limits<double>::infinity();
    for (std::size_t j = 0; j + 1 < pts.size(); ++j) {
      const nf::Vec3 ab = pts[j + 1] - pts[j];
      const double t = std::clamp(nf::dot(p - pts[j], ab) / std::max(nf::dot(ab, ab), 1e-300), 0.0, 1.0);
      const nf::Vec3 q = pts[j] + ab * t;
      if (nf::distance(p, q) < d) {
        d = nf::distance(p, q);
        best = {pts[j], pts[j + 1], q};
      }
    }
    return best;
  }

  /// A knot inserted between the Greville abscissae of the nearest leg's control points, and the
  /// new control point (the one nearest the clicked spot on the leg) moved there.
  static nf::NurbsCurve inserted(const nf::NurbsCurve& c, const nf::Vec3& p) {
    const auto& pts = c.control_points();
    const auto& k = c.knots();
    const std::size_t deg = std::max<std::size_t>(c.degree(), 1);
    auto greville = [&](std::size_t i) {
      double s = 0;
      for (std::size_t r = 1; r <= deg; ++r) s += k[i + r];
      return s / static_cast<double>(deg);
    };
    std::size_t j = 0;
    double d = std::numeric_limits<double>::infinity();
    for (std::size_t i = 0; i + 1 < pts.size(); ++i) {
      const nf::Vec3 ab = pts[i + 1] - pts[i];
      const double t = std::clamp(nf::dot(p - pts[i], ab) / std::max(nf::dot(ab, ab), 1e-300), 0.0, 1.0);
      const double di = nf::distance(p, pts[i] + ab * t);
      if (di < d) {
        d = di;
        j = i;
      }
    }
    const double u = std::clamp(0.5 * (greville(j) + greville(j + 1)), c.domain_start(), c.domain_end());
    if (u <= c.domain_start() || u >= c.domain_end()) throw std::invalid_argument("no room for a control point there");
    nf::NurbsCurve out = c.insert_knot(u);
    const nf::Vec3 q = std::get<2>(leg(c, p));
    std::vector<nf::Vec3> ctrl = out.control_points();
    std::size_t nearest = 0;
    for (std::size_t i = 1; i < ctrl.size(); ++i) {
      if (nf::distance(ctrl[i], q) < nf::distance(ctrl[nearest], q)) nearest = i;
    }
    ctrl[nearest] = q;
    return {out.degree(), out.knots(), ctrl, out.weights()};
  }

 private:
  std::optional<nf::NurbsCurve> curve_;
  document::EntityId id_ = 0;
  int count_ = 0;
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"extend", {"extendcrv"}, [] { return std::make_unique<ExtendCommand>(); }},
      {"divide", {}, [] { return std::make_unique<DivideCommand>(false); }},
      {"divide_length", {"dividebylength", "divlen"}, [] { return std::make_unique<DivideCommand>(true); }},
      {"rebuild", {}, [] { return std::make_unique<RebuildCommand>(); }},
      {"change_degree", {"changedegree"}, [] { return std::make_unique<ChangeDegreeCommand>(); }},
      {"flip", {"dir"}, [] { return std::make_unique<FlipCommand>(); }},
      {"close", {"closecrv"}, [] { return std::make_unique<CloseCommand>(); }},
      {"seam", {"crvseam"}, [] { return std::make_unique<SeamCommand>(); }},
      {"insert_knot", {"insertknot"}, [] { return std::make_unique<KnotCommand>(true); }},
      {"remove_knot", {"removeknot"}, [] { return std::make_unique<KnotCommand>(false); }},
      {"smooth", {}, [] { return std::make_unique<SmoothCommand>(); }},
      {"fair", {}, [] { return std::make_unique<FairCommand>(); }},
      {"match", {"matchcrv"}, [] { return std::make_unique<MatchCommand>(); }},
      {"simplify", {"simplifycrv"}, [] { return std::make_unique<SimplifyCommand>(); }},
      {"arc_blend", {"arcblend", "arctoblend"}, [] { return std::make_unique<ArcBlendCommand>(); }},
      {"points_on", {"pointson", "pon", "surfaceeditpt"}, [] { return std::make_unique<PointsCommand>(true); }},
      {"points_off", {"pointsoff", "poff"}, [] { return std::make_unique<PointsCommand>(false); }},
      {"select_points", {"selpoints", "cvselection", "selcv"}, [] { return std::make_unique<SelectPointsCommand>(); }},
      {"weight", {}, [] { return std::make_unique<WeightCommand>(); }},
      {"insert_control_point", {"insertcontrolpoint", "insertcp"}, [] { return std::make_unique<InsertControlPointCommand>(); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_curve_edit_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList curve_edit_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
