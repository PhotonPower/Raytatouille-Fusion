// Dimensions (docs/commands.md, "Dimensions"): linear (horizontal / vertical in the construction
// plane), aligned, angle, radius, diameter, arc length, ordinate, leader, and DimText (text of
// selected dimensions). The dimensions are curve entities (document/dimension.hpp): selected,
// moved, hidden and deleted like curves; their value is measured whenever it is shown.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <functional>
#include <numbers>

#include "commands/command_util.hpp"
#include "document/dimension.hpp"
#include "kernel/curve_features.hpp"

namespace nfcad::commands {

namespace {

using namespace util;
using document::DimensionKind;
using document::make_dimension;
using Points = std::vector<nf::Vec3>;

constexpr double kEps = 1e-9;

nf::Vec3 unit(const nf::Vec3& v) {
  const double l = nf::norm(v);
  return l > kEps ? v / l : nf::Vec3{0, 0, 0};
}

Polyline3 polyline(const Points& p) {
  Polyline3 out;
  out.reserve(p.size());
  for (const nf::Vec3& v : p) out.push_back(P(v));
  return out;
}

/// Points of an arc of radius r around c from the unit direction s, turning by the signed angle
/// phi about the unit normal n.
Points arc_points(const nf::Vec3& c, const nf::Vec3& s, const nf::Vec3& n, double r, double phi) {
  const nf::Vec3 w = nf::cross(n, s);
  Points out;
  for (int k = 0; k < document::kDimensionArcPoints; ++k) {
    const double t = phi * k / (document::kDimensionArcPoints - 1);
    out.push_back(c + r * (std::cos(t) * s + std::sin(t) * w));
  }
  return out;
}

double signed_angle(const nf::Vec3& a, const nf::Vec3& b, const nf::Vec3& n) {
  return std::atan2(nf::dot(nf::cross(a, b), n), nf::dot(a, b));
}

/// Base of the dimensions given by clicked points: the points so far, a preview of the
/// dimension for the cursor as the last point, created by the last point.
class PointDimensionCommand : public Command {
 public:
  PointDimensionCommand(QString id, QString title, DimensionKind kind, QStringList prompts)
      : id_(std::move(id)), title_(std::move(title)), kind_(kind), prompts_(std::move(prompts)) {}
  QString id() const override { return id_; }
  QString title() const override { return title_; }
  QString prompt() const override {
    return QStringLiteral("%1: %2").arg(title_, prompts_[std::min<qsizetype>(pts_.size(), prompts_.size() - 1)]);
  }
  Result point(const Point3& p, const PlaneFrame& plane) override {
    if (pts_.empty()) plane_ = plane;
    for (const nf::Vec3& q : pts_) {
      if (nf::distance(q, V(p)) < kEps) return Result::Rejected;
    }
    if (pts_.size() + 1 < static_cast<std::size_t>(prompts_.size())) {
      if (!accept(V(p))) return Result::Rejected;
      pts_.push_back(V(p));
      return Result::Continue;
    }
    const auto points = build(V(p));
    if (!points) {
      if (message_.isEmpty()) message_ = QObject::tr("%1: choose another location").arg(title_);
      return Result::Rejected;
    }
    entities_.push_back(make_dimension(kind_, *points));
    extra(entities_.back());
    message_ = QStringLiteral("%1: %2").arg(title_, document::dimension_view(entities_.back())->text);
    return Result::Done;
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (pts_.empty()) return {};
    if (pts_.size() + 1 < static_cast<std::size_t>(prompts_.size())) {
      Points p = pts_;
      p.push_back(V(c));
      return {polyline(p)};
    }
    const auto points = build(V(c));
    if (!points) return {};
    return {polyline(*points)};
  }
  std::optional<Point3> basePoint() const override {
    if (pts_.empty()) return std::nullopt;
    return P(pts_.back());
  }

 protected:
  /// Checks a point before the last one (e.g. not collinear).
  virtual bool accept(const nf::Vec3&) const { return true; }
  /// Control points of the dimension for the last point; empty if it does not fit.
  [[nodiscard]] virtual std::optional<Points> build(const nf::Vec3& last) const = 0;
  /// Further attributes of the new dimension.
  virtual void extra(document::Entity&) const {}

  Points pts_;
  PlaneFrame plane_;

 private:
  QString id_;
  QString title_;
  DimensionKind kind_;
  QStringList prompts_;
};

// ------------------------------------------------------------------------------ linear / aligned
/// Linear: horizontal or vertical in the construction plane, whichever way the location is
/// pulled; Aligned: parallel to the two points.
class LinearDimensionCommand : public PointDimensionCommand {
 public:
  explicit LinearDimensionCommand(bool aligned)
      : PointDimensionCommand(aligned ? QStringLiteral("dimaligned") : QStringLiteral("dimlinear"),
                              aligned ? QObject::tr("Aligned dimension") : QObject::tr("Linear dimension"),
                              aligned ? DimensionKind::Aligned : DimensionKind::Linear,
                              {QObject::tr("first point"), QObject::tr("second point"),
                               QObject::tr("location of the dimension line")}),
        aligned_(aligned) {}

 protected:
  std::optional<Points> build(const nf::Vec3& loc) const override {
    const nf::Vec3 p1 = pts_[0];
    const nf::Vec3 p2 = pts_[1];
    if (aligned_) {
      const nf::Vec3 e = unit(p2 - p1);
      const nf::Vec3 off = (loc - p1) - nf::dot(loc - p1, e) * e;
      return Points{p1, p1 + off, p2 + off, p2};
    }
    const nf::Vec3 u = V(plane_.u);
    const nf::Vec3 v = V(plane_.v);
    const nf::Vec3 n = V(plane_.n);
    const nf::Vec3 d = loc - 0.5 * (p1 + p2);
    const bool horizontal = std::abs(nf::dot(d, v)) >= std::abs(nf::dot(d, u));
    const nf::Vec3 e = horizontal ? u : v;
    const nf::Vec3 g = horizontal ? v : u;
    if (std::abs(nf::dot(p2 - p1, e)) < kEps) return std::nullopt;
    const auto onto = [&](const nf::Vec3& p) { return p + nf::dot(loc - p, g) * g + nf::dot(loc - p, n) * n; };
    return Points{p1, onto(p1), onto(p2), p2};
  }

 private:
  bool aligned_;
};

// ------------------------------------------------------------------------------ angle
/// Vertex, a point on each arm, location of the arc: of the four angles between the two lines
/// the one in which the location lies.
class AngleDimensionCommand : public PointDimensionCommand {
 public:
  AngleDimensionCommand()
      : PointDimensionCommand(QStringLiteral("dimangle"), QObject::tr("Angle dimension"), DimensionKind::Angle,
                              {QObject::tr("vertex"), QObject::tr("point on the first line"),
                               QObject::tr("point on the second line"), QObject::tr("location of the arc")}) {}

 protected:
  bool accept(const nf::Vec3& p) const override {
    if (pts_.size() < 2) return true;
    return nf::norm(nf::cross(unit(pts_[1] - pts_[0]), unit(p - pts_[0]))) > 1e-6;  // not collinear
  }
  std::optional<Points> build(const nf::Vec3& loc) const override {
    const nf::Vec3 c = pts_[0];
    const nf::Vec3 d1 = unit(pts_[1] - c);
    const nf::Vec3 d2 = unit(pts_[2] - c);
    const nf::Vec3 n = unit(nf::cross(d1, d2));
    nf::Vec3 dl = loc - c;
    dl = dl - nf::dot(dl, n) * n;
    const double r = nf::norm(dl);
    if (r < kEps) return std::nullopt;
    for (const auto& [sa, sb] : {std::pair{1.0, 1.0}, {-1.0, 1.0}, {-1.0, -1.0}, {1.0, -1.0}}) {
      const nf::Vec3 a = sa * d1;
      const nf::Vec3 b = sb * d2;
      const double ab = nf::dot(nf::cross(a, b), n);
      const double alpha = nf::dot(nf::cross(dl, b), n) / ab;
      const double beta = nf::dot(nf::cross(a, dl), n) / ab;
      if (alpha < 0 || beta < 0) continue;
      Points out{sa > 0 ? pts_[1] : c};
      const Points arc = arc_points(c, a, unit(nf::cross(a, b)), r, std::acos(std::clamp(nf::dot(a, b), -1.0, 1.0)));
      out.insert(out.end(), arc.begin(), arc.end());
      out.push_back(sb > 0 ? pts_[2] : c);
      return out;
    }
    return std::nullopt;
  }
};

// ------------------------------------------------------------------------------ ordinate
/// The coordinate of a point along an axis of the construction plane: pulling the leader up or
/// down shows the u (x) coordinate, sideways the v (y) coordinate.
class OrdinateDimensionCommand : public PointDimensionCommand {
 public:
  OrdinateDimensionCommand()
      : PointDimensionCommand(QStringLiteral("dimordinate"), QObject::tr("Ordinate dimension"), DimensionKind::Ordinate,
                              {QObject::tr("point"), QObject::tr("end of the leader (up / down: x, sideways: y)")}) {}

 protected:
  std::optional<Points> build(const nf::Vec3& loc) const override {
    const nf::Vec3 p = pts_[0];
    const nf::Vec3 d = loc - p;
    const nf::Vec3 lead = vertical(loc) ? V(plane_.v) : V(plane_.u);
    if (std::abs(nf::dot(d, lead)) < kEps) return std::nullopt;
    return Points{p, p + nf::dot(d, lead) * lead};
  }
  void extra(document::Entity& e) const override {
    const nf::Vec3 end = std::get<nf::NurbsCurve>(*e.geometry).control_points()[1];
    const nf::Vec3 axis = vertical(end) ? V(plane_.u) : V(plane_.v);
    e.attributes.insert(QString::fromLatin1(document::kDimensionOriginKey), document::vec_text(V(plane_.origin)));
    e.attributes.insert(QString::fromLatin1(document::kDimensionAxisKey), document::vec_text(axis));
    const QString name = vertical(end) ? QStringLiteral("X") : QStringLiteral("Y");
    e.attributes.insert(QString::fromLatin1(document::kDimensionTextKey), name + QStringLiteral(" <>"));
  }

 private:
  bool vertical(const nf::Vec3& loc) const {
    const nf::Vec3 d = loc - pts_[0];
    return std::abs(nf::dot(d, V(plane_.v))) >= std::abs(nf::dot(d, V(plane_.u)));
  }
};

// ------------------------------------------------------------------------------ circles
/// Radius, Diameter, Arc length of a selected circle or arc: the location of the text (radius,
/// diameter: the direction of the line from the centre, then a landing under the text; arc
/// length: the radius of the dimension arc).
class CircleDimensionCommand : public Command {
 public:
  explicit CircleDimensionCommand(DimensionKind kind) : kind_(kind) {}
  QString id() const override {
    switch (kind_) {
      case DimensionKind::Radius: return QStringLiteral("dimradius");
      case DimensionKind::Diameter: return QStringLiteral("dimdiameter");
      default: break;
    }
    return QStringLiteral("dimarclength");
  }
  QString title() const override { return document::dimension_kind_name(kind_); }
  QString prompt() const override { return QObject::tr("%1: location").arg(title()); }
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      const auto* c = std::get_if<nf::NurbsCurve>(e.geometry.get());
      if (c == nullptr || document::dimension_kind(e)) continue;
      if (auto info = kernel::as_circle(*c)) {
        if (kind_ == DimensionKind::ArcLength && info->full) continue;
        circle_ = *info;
        start_ = c->evaluate(c->domain_start());
        mid_ = c->evaluate(0.5 * (c->domain_start() + c->domain_end()));
        end_ = c->evaluate(c->domain_end());
        return true;
      }
    }
    message_ = kind_ == DimensionKind::ArcLength ? QObject::tr("%1: select an arc").arg(title())
                                                 : QObject::tr("%1: select a circle or an arc").arg(title());
    return false;
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    const auto points = build(V(p));
    if (!points) return Result::Rejected;
    entities_.push_back(make_dimension(kind_, *points));
    message_ = QStringLiteral("%1: %2").arg(title(), document::dimension_view(entities_.back())->text);
    return Result::Done;
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    const auto points = build(V(c));
    if (!points) return {};
    return {polyline(*points)};
  }

 private:
  std::optional<Points> build(const nf::Vec3& loc) const {
    const nf::Vec3 c = circle_.centre;
    const nf::Vec3 n = circle_.normal;
    nf::Vec3 d = loc - c;
    d = d - nf::dot(d, n) * n;
    const double l = nf::norm(d);
    if (l < kEps) return std::nullopt;
    const nf::Vec3 u = d / l;
    const double r = circle_.radius;
    if (kind_ != DimensionKind::ArcLength) {
      // landing: a shoulder under the text, horizontal in the view, towards the outside
      nf::Vec3 h = V(viewPlane().u);
      h = h - nf::dot(h, n) * n;
      if (nf::norm(h) < 1e-6) h = V(viewPlane().v) - nf::dot(V(viewPlane().v), n) * n;
      h = unit(h);
      if (nf::dot(h, u) < 0) h = -1.0 * h;
      const nf::Vec3 end = c + l * u;
      const nf::Vec3 landing = end + 0.35 * r * h;
      if (kind_ == DimensionKind::Radius) return Points{c, c + r * u, end, landing};
      return Points{c - r * u, c + r * u, end, landing};
    }
    // arc length: concentric arc through the location, from the arc's start to its end
    const nf::Vec3 s = unit(start_ - c);
    const nf::Vec3 m = unit(mid_ - c);
    const nf::Vec3 e = unit(end_ - c);
    const double phi = signed_angle(s, m, n) + signed_angle(m, e, n);
    Points out{start_};
    const Points arc = arc_points(c, s, n, l, phi);
    out.insert(out.end(), arc.begin(), arc.end());
    out.push_back(end_);
    return out;
  }

  DimensionKind kind_;
  kernel::CircleInfo circle_;
  nf::Vec3 start_, mid_, end_;
};

// ------------------------------------------------------------------------------ leader
class LeaderCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("leader"); }
  QString title() const override { return QObject::tr("Leader"); }
  QString prompt() const override {
    if (texting_) return QObject::tr("Leader: text");
    if (pts_.empty()) return QObject::tr("Leader: arrow tip");
    return pts_.size() < 2 ? QObject::tr("Leader: next point") : QObject::tr("Leader: next point (Enter: text)");
  }
  Result point(const Point3& p, const PlaneFrame&) override {
    if (texting_) return Result::Rejected;
    if (!pts_.empty() && nf::distance(pts_.back(), V(p)) < kEps) return Result::Rejected;
    pts_.push_back(V(p));
    return Result::Continue;
  }
  Result finish() override {
    if (texting_) {
      message_ = QObject::tr("Leader: type the text");
      return Result::Rejected;
    }
    if (pts_.size() < 2) return Result::Cancelled;
    texting_ = true;
    return Result::Continue;
  }
  bool wantsText() const override { return texting_; }
  Result text(const QString& t) override {
    entities_.push_back(make_dimension(DimensionKind::Leader, pts_, t));
    return Result::Done;
  }
  std::vector<Polyline3> preview(const Point3& c, const PlaneFrame&) const override {
    if (pts_.empty()) return {};
    Points p = pts_;
    if (!texting_) p.push_back(V(c));
    return {polyline(p)};
  }
  std::optional<Point3> basePoint() const override {
    if (pts_.empty()) return std::nullopt;
    return P(pts_.back());
  }

 private:
  Points pts_;
  bool texting_ = false;
};

// ------------------------------------------------------------------------------ DimText
/// Text of the selected dimensions: typed text replaces the value ("<>" in it: the value);
/// Enter without text shows the measured value again.
class DimTextCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("dimtext"); }
  QString title() const override { return QObject::tr("Dimension text"); }
  QString prompt() const override {
    return QObject::tr("Dimension text: new text (<> = the value; Enter: the value again)");
  }
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    for (const document::Entity& e : selection) {
      if (document::dimension_kind(e)) dims_.push_back(e);
    }
    if (dims_.empty()) message_ = QObject::tr("Dimension text: select dimensions");
    return !dims_.empty();
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  bool wantsText() const override { return true; }
  Result text(const QString& t) override { return set(t); }
  Result finish() override { return set({}); }

 private:
  Result set(const QString& t) {
    for (const document::Entity& e : dims_) {
      QVariantMap a = e.attributes;
      const bool leader = document::dimension_kind(e) == DimensionKind::Leader;
      if (t.isEmpty() && leader) continue;  // a leader keeps its text
      if (t.isEmpty()) {
        a.remove(QString::fromLatin1(document::kDimensionTextKey));
      } else {
        a.insert(QString::fromLatin1(document::kDimensionTextKey), t);
      }
      attributes_.emplace_back(e.id, std::move(a));
    }
    if (attributes_.empty()) return Result::Cancelled;
    return Result::Done;
  }
  std::vector<document::Entity> dims_;
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"dimlinear", {"dim", "dimhorizontal", "dimvertical"}, [] { return std::make_unique<LinearDimensionCommand>(false); }},
      {"dimaligned", {}, [] { return std::make_unique<LinearDimensionCommand>(true); }},
      {"dimangle", {"dimangular"}, [] { return std::make_unique<AngleDimensionCommand>(); }},
      {"dimradius", {}, [] { return std::make_unique<CircleDimensionCommand>(DimensionKind::Radius); }},
      {"dimdiameter", {}, [] { return std::make_unique<CircleDimensionCommand>(DimensionKind::Diameter); }},
      {"dimarclength", {"dimarc"}, [] { return std::make_unique<CircleDimensionCommand>(DimensionKind::ArcLength); }},
      {"dimordinate", {"dimord"}, [] { return std::make_unique<OrdinateDimensionCommand>(); }},
      {"leader", {}, [] { return std::make_unique<LeaderCommand>(); }},
      {"dimtext", {"dimedit"}, [] { return std::make_unique<DimTextCommand>(); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_dimension_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList dimension_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
