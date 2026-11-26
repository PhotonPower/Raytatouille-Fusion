// Editing curves (docs/commands.md, "Editing curves"): Extend, Divide, Divide by length, Rebuild,
// Change degree, Flip, Close, Seam, Insert knot, Remove knot, Smooth, Fair. Commands that change
// a curve replace its geometry (one undo step); Divide adds points.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <exception>
#include <functional>
#include <limits>
#include <nurbforge/analysis/closest_point.hpp>
#include <nurbforge/analysis/properties.hpp>
#include <nurbforge/geometry/primitives.hpp>
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
    nf::NurbsCurve out = c;
    for (int step = 0; step < 200; ++step) {
      const nf::NurbsCurve next = smoothed(out, 0.25);
      if (deviation(next, c) > tol) break;
      out = next;
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
