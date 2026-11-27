#include "document/dimension.hpp"

#include <QObject>
#include <QStringList>
#include <algorithm>
#include <cmath>
#include <numbers>

namespace nfcad::document {

namespace {

constexpr double kTiny = 1e-12;

struct KindName {
  DimensionKind kind;
  const char* name;
};
constexpr KindName kNames[] = {
    {DimensionKind::Linear, "linear"},       {DimensionKind::Aligned, "aligned"},
    {DimensionKind::Angle, "angle"},         {DimensionKind::ArcLength, "arclength"},
    {DimensionKind::Radius, "radius"},       {DimensionKind::Diameter, "diameter"},
    {DimensionKind::Ordinate, "ordinate"},   {DimensionKind::Leader, "leader"},
};

std::optional<DimensionKind> kind_of(const QVariantMap& attributes) {
  const QString name = attributes.value(QString::fromLatin1(kDimensionKey)).toString();
  if (name.isEmpty()) return std::nullopt;
  for (const KindName& k : kNames) {
    if (name == QLatin1String(k.name)) return k.kind;
  }
  return std::nullopt;
}

double angle_between(const nf::Vec3& a, const nf::Vec3& b) {
  return std::atan2(nf::norm(nf::cross(a, b)), nf::dot(a, b));
}

/// Centre of the circle through three points; empty if they are (nearly) collinear.
std::optional<nf::Vec3> circumcentre(const nf::Vec3& a, const nf::Vec3& b, const nf::Vec3& c) {
  const nf::Vec3 u = a - c;
  const nf::Vec3 w = b - c;
  const nf::Vec3 n = nf::cross(u, w);
  const double nn = nf::dot(n, n);
  if (nn < kTiny * std::max(1.0, nf::dot(u, u) * nf::dot(w, w))) return std::nullopt;
  return c + nf::cross(nf::dot(u, u) * w - nf::dot(w, w) * u, n) / (2.0 * nn);
}

/// Centre and opening angle (radians) of the dimension arc a1 … a2.
std::optional<std::pair<nf::Vec3, double>> arc_of(const std::vector<nf::Vec3>& p) {
  if (p.size() != static_cast<std::size_t>(kDimensionArcPoints) + 2) return std::nullopt;
  const nf::Vec3& a1 = p[1];
  const nf::Vec3& am = p[1 + kDimensionArcPoints / 2];
  const nf::Vec3& a2 = p[kDimensionArcPoints];
  const auto c = circumcentre(a1, am, a2);
  if (!c) return std::nullopt;
  return std::pair{*c, angle_between(a1 - *c, am - *c) + angle_between(am - *c, a2 - *c)};
}

QString trimmed_number(double v, int decimals) {
  if (std::abs(v) < 0.5 * std::pow(10.0, -decimals)) v = 0.0;  // no "-0"
  QString s = QString::number(v, 'f', decimals);
  if (s.contains(QLatin1Char('.'))) {
    while (s.endsWith(QLatin1Char('0'))) s.chop(1);
    if (s.endsWith(QLatin1Char('.'))) s.chop(1);
  }
  return s;
}

}  // namespace

Entity make_dimension(DimensionKind kind, const std::vector<nf::Vec3>& points, const QString& text) {
  // uniform knots: points may coincide (an extension line of length zero)
  nf::KnotVector knots{0.0};
  for (std::size_t i = 0; i < points.size(); ++i) knots.push_back(static_cast<double>(i));
  knots.push_back(static_cast<double>(points.size() - 1));
  Entity e = make_entity(nf::NurbsCurve(1, std::move(knots), points), dimension_kind_name(kind));
  e.attributes.insert(QString::fromLatin1(kDimensionKey), QString::fromLatin1(kNames[static_cast<int>(kind)].name));
  if (!text.isEmpty()) e.attributes.insert(QString::fromLatin1(kDimensionTextKey), text);
  return e;
}

QString dimension_kind_name(DimensionKind kind) {
  switch (kind) {
    case DimensionKind::Linear: return QObject::tr("Linear dimension");
    case DimensionKind::Aligned: return QObject::tr("Aligned dimension");
    case DimensionKind::Angle: return QObject::tr("Angle dimension");
    case DimensionKind::ArcLength: return QObject::tr("Arc length dimension");
    case DimensionKind::Radius: return QObject::tr("Radius dimension");
    case DimensionKind::Diameter: return QObject::tr("Diameter dimension");
    case DimensionKind::Ordinate: return QObject::tr("Ordinate dimension");
    case DimensionKind::Leader: return QObject::tr("Leader");
  }
  return {};
}

std::optional<DimensionKind> dimension_kind(const Entity& e) { return kind_of(e.attributes); }

std::optional<double> dimension_value(DimensionKind kind, const std::vector<nf::Vec3>& p,
                                      const QVariantMap& attributes) {
  switch (kind) {
    case DimensionKind::Linear:
    case DimensionKind::Aligned:
      if (p.size() != 4) return std::nullopt;
      return nf::norm(p[2] - p[1]);
    case DimensionKind::Angle: {
      const auto arc = arc_of(p);
      if (!arc) return std::nullopt;
      return arc->second * 180.0 / std::numbers::pi;
    }
    case DimensionKind::ArcLength: {
      const auto arc = arc_of(p);
      if (!arc) return std::nullopt;
      return arc->second * nf::norm(p.front() - arc->first);
    }
    case DimensionKind::Radius:
      if (p.size() != 4) return std::nullopt;
      return nf::norm(p[1] - p[0]);
    case DimensionKind::Diameter:
      if (p.size() != 4) return std::nullopt;
      return nf::norm(p[1] - p[0]);
    case DimensionKind::Ordinate: {
      if (p.size() != 2) return std::nullopt;
      const auto o = vec_from_text(attributes.value(QString::fromLatin1(kDimensionOriginKey)).toString());
      const auto a = vec_from_text(attributes.value(QString::fromLatin1(kDimensionAxisKey)).toString());
      if (!o || !a) return std::nullopt;
      return nf::dot(p[0] - *o, *a);
    }
    case DimensionKind::Leader:
      if (p.size() < 2) return std::nullopt;
      return 0.0;
  }
  return std::nullopt;
}

std::optional<DimensionView> dimension_view(const QVariantMap& attributes, const Geometry& g) {
  const auto kind = kind_of(attributes);
  const auto* curve = std::get_if<nf::NurbsCurve>(&g);
  if (!kind || curve == nullptr || curve->degree() != 1) return std::nullopt;
  const std::vector<nf::Vec3>& p = curve->control_points();
  const auto value = dimension_value(*kind, p, attributes);
  if (!value) return std::nullopt;

  DimensionView v;
  v.kind = *kind;
  v.value = *value;
  QString shown;
  switch (*kind) {
    case DimensionKind::Linear:
    case DimensionKind::Aligned:
      v.arrows = {{p[1], p[2]}, {p[2], p[1]}};
      v.text_at = 0.5 * (p[1] + p[2]);
      v.text_from = p[1];
      shown = format_length(*value);
      break;
    case DimensionKind::Angle:
    case DimensionKind::ArcLength: {
      const std::size_t n = kDimensionArcPoints;
      v.arrows = {{p[1], p[2]}, {p[n], p[n - 1]}};
      v.text_at = p[1 + n / 2];
      v.text_from = p[n / 2];
      shown = *kind == DimensionKind::Angle ? format_angle(*value)
                                            : QStringLiteral("⌒") + format_length(*value);
      break;
    }
    case DimensionKind::Radius:
      v.arrows = {{p[1], p[0]}};
      v.on_line = false;
      v.text_at = p[3];
      v.text_from = p[2];
      shown = QStringLiteral("R") + format_length(*value);
      break;
    case DimensionKind::Diameter:
      v.arrows = {{p[0], p[1]}, {p[1], p[0]}};
      v.on_line = false;
      v.text_at = p[3];
      v.text_from = p[2];
      shown = QStringLiteral("⌀") + format_length(*value);
      break;
    case DimensionKind::Ordinate:
      v.on_line = false;
      v.text_at = p[1];
      v.text_from = p[0];
      shown = format_length(*value);
      break;
    case DimensionKind::Leader:
      v.arrows = {{p[0], p[1]}};
      v.on_line = false;
      v.text_at = p.back();
      v.text_from = p[p.size() - 2];
      break;
  }
  // plane: the largest cross product of two segments from the first point
  nf::Vec3 best{0, 0, 0};
  double size = 0.0;
  for (std::size_t i = 1; i < p.size(); ++i) size = std::max(size, nf::norm(p[i] - p[0]));
  for (std::size_t i = 1; i < p.size(); ++i) {
    for (std::size_t j = i + 1; j < p.size(); ++j) {
      const nf::Vec3 n = nf::cross(p[i] - p[0], p[j] - p[0]);
      if (nf::norm(n) > nf::norm(best)) best = n;
    }
  }
  if (nf::norm(best) > 1e-6 * size * size) v.normal = best / nf::norm(best);
  if (*kind == DimensionKind::Ordinate) {  // in the plane of the leader and the axis
    if (const auto a = vec_from_text(attributes.value(QString::fromLatin1(kDimensionAxisKey)).toString())) {
      const nf::Vec3 n = nf::cross(*a, p[1] - p[0]);
      if (nf::norm(n) > 1e-12) v.normal = n / nf::norm(n);
    }
  }
  const QString text = attributes.value(QString::fromLatin1(kDimensionTextKey)).toString();
  v.text = text.isEmpty() ? shown : QString(text).replace(QStringLiteral("<>"), shown);
  return v;
}

std::optional<DimensionView> dimension_view(const Entity& e) {
  if (!e.geometry) return std::nullopt;
  return dimension_view(e.attributes, *e.geometry);
}

QString format_length(double v) { return trimmed_number(v, 2); }

QString format_angle(double degrees) { return trimmed_number(degrees, 1) + QStringLiteral("°"); }

QString vec_text(const nf::Vec3& v) {
  return QStringLiteral("%1 %2 %3").arg(v.x, 0, 'g', 17).arg(v.y, 0, 'g', 17).arg(v.z, 0, 'g', 17);
}

std::optional<nf::Vec3> vec_from_text(const QString& s) {
  const QStringList parts = s.split(QLatin1Char(' '), Qt::SkipEmptyParts);
  if (parts.size() != 3) return std::nullopt;
  double c[3];
  for (int i = 0; i < 3; ++i) {
    bool ok = false;
    c[i] = parts[i].toDouble(&ok);
    if (!ok || !std::isfinite(c[i])) return std::nullopt;
  }
  return nf::Vec3{c[0], c[1], c[2]};
}

}  // namespace nfcad::document
