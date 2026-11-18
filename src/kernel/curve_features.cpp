#include "kernel/curve_features.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <exception>
#include <nurbforge/analysis/closest_point.hpp>
#include <nurbforge/analysis/intersect.hpp>
#include <nurbforge/analysis/properties.hpp>

namespace nfcad::kernel {

namespace {

constexpr double kRelTol = 1e-7;

std::optional<nf::Vec3> unit(const nf::Vec3& v) {
  const double n = nf::norm(v);
  if (n < 1e-14) return std::nullopt;
  return v / n;
}

/// Circle through three points: centre and unit normal.
std::optional<std::pair<nf::Vec3, nf::Vec3>> circle_3pt(const nf::Vec3& a, const nf::Vec3& b,
                                                         const nf::Vec3& c) {
  const nf::Vec3 ab = b - a;
  const nf::Vec3 ac = c - a;
  const nf::Vec3 n = nf::cross(ab, ac);
  const double n2 = nf::dot(n, n);
  if (n2 < 1e-24) return std::nullopt;
  const nf::Vec3 centre =
      a + (nf::cross(n, ab) * nf::dot(ac, ac) + nf::cross(ac, n) * nf::dot(ab, ab)) / (2.0 * n2);
  return std::make_pair(centre, n / std::sqrt(n2));
}

std::vector<nf::Vec3> samples(const nf::NurbsCurve& c, int n) {
  std::vector<nf::Vec3> out;
  const double a = c.domain_start();
  const double b = c.domain_end();
  for (int i = 0; i <= n; ++i) out.push_back(c.evaluate(a + (b - a) * i / n));
  return out;
}

/// Area centroid of a closed planar curve (sampled polygon, Newell normal); empty if not planar.
std::optional<nf::Vec3> planar_centroid(const nf::NurbsCurve& c) {
  // dense sampling per span keeps the centroid accurate for curved closed loops
  const auto pts = samples(c, 512);
  nf::Vec3 newell{0, 0, 0};
  for (std::size_t i = 0; i + 1 < pts.size(); ++i) newell += nf::cross(pts[i], pts[i + 1]);
  const auto n = unit(newell);
  if (!n) return std::nullopt;
  double size = 0.0;
  for (const auto& p : pts) size = std::max(size, nf::distance(p, pts.front()));
  const double d0 = nf::dot(pts.front(), *n);
  for (const auto& p : pts) {
    if (std::abs(nf::dot(p, *n) - d0) > 1e-6 * std::max(size, 1e-12)) return std::nullopt;
  }
  // fan triangulation from the first point
  nf::Vec3 sum{0, 0, 0};
  double area = 0.0;
  for (std::size_t i = 1; i + 1 < pts.size(); ++i) {
    const double a = 0.5 * nf::dot(nf::cross(pts[i] - pts[0], pts[i + 1] - pts[0]), *n);
    sum += (pts[0] + pts[i] + pts[i + 1]) * (a / 3.0);
    area += a;
  }
  if (std::abs(area) < 1e-18) return std::nullopt;
  return sum / area;
}

/// Unit tangents just before and just after parameter u.
std::pair<std::optional<nf::Vec3>, std::optional<nf::Vec3>> side_tangents(const nf::NurbsCurve& c,
                                                                           double u, double h) {
  const double a = c.domain_start();
  const double b = c.domain_end();
  return {unit(c.derivatives(std::max(a, u - h), 1)[1]), unit(c.derivatives(std::min(b, u + h), 1)[1])};
}

bool is_kink(const std::optional<nf::Vec3>& left, const std::optional<nf::Vec3>& right) {
  if (!left || !right) return true;  // a vanishing tangent: treat as a corner
  return nf::dot(*left, *right) < std::cos(1e-4);
}

/// Break points of a curve: parameters of its corners inside the domain (see CurveFeatures).
std::vector<double> corner_parameters(const nf::NurbsCurve& c) {
  std::vector<double> out;
  const double a = c.domain_start();
  const double b = c.domain_end();
  const double h = 1e-7 * (b - a);
  const auto [values, mult] = nf::unique_knots(c.knots());
  for (std::size_t i = 0; i < values.size(); ++i) {
    const double u = values[i];
    if (u <= a + h || u >= b - h) continue;
    if (static_cast<std::size_t>(mult[i]) < c.degree()) continue;  // smooth there (C1 or better)
    if (c.degree() == 1) {
      out.push_back(u);  // every vertex of a polyline
      continue;
    }
    const auto [left, right] = side_tangents(c, u, h);
    if (is_kink(left, right)) out.push_back(u);
  }
  return out;
}

}  // namespace

std::optional<CircleInfo> as_circle(const nf::NurbsCurve& c) {
  if (c.degree() < 2) return std::nullopt;
  const auto pts = samples(c, 12);
  const auto circle = circle_3pt(pts[0], pts[4], pts[8]);
  if (!circle) return std::nullopt;
  const auto& [centre, normal] = *circle;
  const double r = nf::distance(pts[0], centre);
  for (const auto& p : pts) {
    if (std::abs(nf::distance(p, centre) - r) > kRelTol * r) return std::nullopt;
    if (std::abs(nf::dot(p - centre, normal)) > kRelTol * r) return std::nullopt;
  }
  // also between the samples (a spline may pass through the samples only)
  const double a = c.domain_start();
  const double b = c.domain_end();
  for (int i = 0; i < 12; ++i) {
    const nf::Vec3 p = c.evaluate(a + (b - a) * (i + 0.37) / 12.0);
    if (std::abs(nf::distance(p, centre) - r) > kRelTol * r) return std::nullopt;
  }
  CircleInfo info{centre, normal, r, nf::distance(pts.front(), pts.back()) < kRelTol * r};
  return info;
}

CurveFeatures curve_features(const nf::NurbsCurve& c) {
  CurveFeatures f;
  const nf::Vec3 a = c.evaluate(c.domain_start());
  const nf::Vec3 b = c.evaluate(c.domain_end());
  double size = 0.0;
  for (const auto& p : c.control_points()) size = std::max(size, nf::distance(p, a));
  f.closed = nf::distance(a, b) <= 1e-9 * std::max(size, 1.0);
  const double u0 = c.domain_start();
  const double u1 = c.domain_end();
  const std::vector<double> breaks = corner_parameters(c);
  for (const double u : breaks) f.corners.push_back(c.evaluate(u));
  bool seam_corner = false;
  if (f.closed) {
    const double h = 1e-7 * (u1 - u0);
    seam_corner = c.degree() == 1 ||
                  is_kink(side_tangents(c, u1, h).first, side_tangents(c, u0, h).second);
    if (seam_corner) f.corners.push_back(a);
  } else {
    f.start = a;
    f.end = b;
  }
  // the middle of the curve piece [s, t] (half its arc length; straight: the midpoint)
  auto piece_mid = [&](double s, double t) {
    if (c.degree() == 1) return (c.evaluate(s) + c.evaluate(t)) * 0.5;
    try {
      return c.evaluate(nf::parameter_at_length(c, nf::arc_length(c, u0, s) +
                                                       0.5 * nf::arc_length(c, s, t)));
    } catch (const std::exception&) {
      return c.evaluate(0.5 * (s + t));
    }
  };
  if (!breaks.empty() || seam_corner) {
    // segments between consecutive corners / ends
    std::vector<double> ends = {u0};
    ends.insert(ends.end(), breaks.begin(), breaks.end());
    ends.push_back(u1);
    const bool wrap = f.closed && !seam_corner;  // the first and the last piece are one segment
    for (std::size_t i = wrap ? 1 : 0; i + (wrap ? 2 : 1) < ends.size(); ++i) {
      f.segment_mids.push_back(piece_mid(ends[i], ends[i + 1]));
    }
    if (wrap) {
      // (degree >= 2: closed polylines always have a corner at the seam)
      const double s = breaks.back();
      const double t = breaks.front();
      try {
        const double l1 = nf::arc_length(c, s, u1);
        const double half = 0.5 * (l1 + nf::arc_length(c, u0, t));
        f.segment_mids.push_back(c.evaluate(
            half <= l1 ? nf::parameter_at_length(c, nf::arc_length(c, u0, s) + half)
                       : nf::parameter_at_length(c, half - l1)));
      } catch (const std::exception&) {
        f.segment_mids.push_back(c.evaluate(t));
      }
    }
  } else if (!f.closed) {
    try {
      f.mid = c.evaluate(nf::parameter_at_length(c, 0.5 * nf::arc_length(c)));
    } catch (const std::exception&) {
      f.mid = c.evaluate(0.5 * (u0 + u1));
    }
  }
  if (const auto circle = as_circle(c)) {
    f.centre = circle->centre;
    const std::array<nf::Vec3, 3> axes = {nf::Vec3{1, 0, 0}, nf::Vec3{0, 1, 0}, nf::Vec3{0, 0, 1}};
    for (const nf::Vec3& axis : axes) {
      const auto dir = unit(nf::cross(circle->normal, axis));
      if (!dir) continue;  // circle plane perpendicular to this axis: no cut points
      for (const double sign : {1.0, -1.0}) {
        const nf::Vec3 q = circle->centre + *dir * (sign * circle->radius);
        if (!circle->full && nf::distance(closest_on_curve(c, q), q) > 1e-6 * circle->radius) {
          continue;  // not on the arc
        }
        const bool dup = std::any_of(f.quadrants.begin(), f.quadrants.end(), [&](const nf::Vec3& o) {
          return nf::distance(o, q) < 1e-9 * circle->radius;
        });
        if (!dup) f.quadrants.push_back(q);
      }
    }
  } else if (f.closed) {
    f.centre = planar_centroid(c);
  }
  return f;
}

nf::Vec3 closest_on_curve(const nf::NurbsCurve& c, const nf::Vec3& p) {
  try {
    return nf::closest_point(c, p).point;
  } catch (const std::exception&) {
    return p;
  }
}

std::vector<nf::Vec3> curve_intersections(const nf::NurbsCurve& a, const nf::NurbsCurve& b) {
  std::vector<nf::Vec3> out;
  try {
    for (const auto& x : nf::intersect(a, b)) out.push_back(x.point);
  } catch (const std::exception&) {
  }
  return out;
}

std::vector<std::vector<nf::NurbsCurve>> edge_curves(const document::Geometry& g) {
  std::vector<std::vector<nf::NurbsCurve>> out;
  std::visit(
      [&](const auto& v) {
        using T = std::decay_t<decltype(v)>;
        if constexpr (std::is_same_v<T, nf::NurbsCurve>) {
          out.push_back({v});
        } else if constexpr (std::is_same_v<T, nf::NurbsSurface>) {
          try {
            out = nf::TrimmedSurface(v).boundary_curves();
          } catch (const std::exception&) {
          }
        } else if constexpr (std::is_same_v<T, nf::TrimmedSurface>) {
          try {
            out = v.boundary_curves();
          } catch (const std::exception&) {
          }
        } else if constexpr (std::is_same_v<T, nf::Shell>) {
          for (const nf::ShellEdge& e : v.edges()) out.push_back({e.curve});
        }
      },
      g);
  return out;
}

std::vector<nf::Vec3> corners(const document::Geometry& g) {
  std::vector<nf::Vec3> out;
  auto loop_corners = [&](const nf::TrimmedSurface& f) {
    try {
      for (const auto& loop : f.boundary_curves()) {
        if (loop.size() < 2) continue;  // a single closed curve (e.g. a circular hole) has no corner
        for (const auto& c : loop) out.push_back(c.evaluate(c.domain_start()));
      }
    } catch (const std::exception&) {
    }
  };
  std::visit(
      [&](const auto& v) {
        using T = std::decay_t<decltype(v)>;
        if constexpr (std::is_same_v<T, nf::Shell>) {
          out = v.vertices();
        } else if constexpr (std::is_same_v<T, nf::TrimmedSurface>) {
          loop_corners(v);
        } else if constexpr (std::is_same_v<T, nf::NurbsSurface>) {
          loop_corners(nf::TrimmedSurface(v));
        }
      },
      g);
  return out;
}

}  // namespace nfcad::kernel
