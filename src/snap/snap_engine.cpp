#include "snap/snap_engine.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

#include <nurbforge/analysis/closest_point.hpp>

#include "kernel/curve_features.hpp"

namespace nfcad::snap {

namespace {

constexpr float kInf = std::numeric_limits<float>::infinity();
constexpr std::size_t kMaxIntersectionSegments = 48;

QVector3D q3(const nf::Vec3& p) {
  return {static_cast<float>(p.x), static_cast<float>(p.y), static_cast<float>(p.z)};
}
nf::Vec3 n3(const QVector3D& p) { return {p.x(), p.y(), p.z()}; }

/// Proper intersection of two 2D segments: parameters on both, or empty.
std::optional<std::pair<double, double>> segments_2d(const QPointF& a, const QPointF& b,
                                                     const QPointF& c, const QPointF& d) {
  const QPointF r = b - a;
  const QPointF s = d - c;
  const double den = r.x() * s.y() - r.y() * s.x();
  if (std::abs(den) < 1e-12) return std::nullopt;
  const QPointF ac = c - a;
  const double t = (ac.x() * s.y() - ac.y() * s.x()) / den;
  const double u = (ac.x() * r.y() - ac.y() * r.x()) / den;
  if (t < 0.0 || t > 1.0 || u < 0.0 || u > 1.0) return std::nullopt;
  return std::make_pair(t, u);
}

std::pair<double, double> point_segment_2d(const QPointF& p, const QPointF& a, const QPointF& b) {
  const QPointF ab = b - a;
  const double len2 = QPointF::dotProduct(ab, ab);
  const double s = len2 > 0.0 ? std::clamp(QPointF::dotProduct(p - a, ab) / len2, 0.0, 1.0) : 0.0;
  const QPointF c = a + ab * s;
  return {std::hypot(p.x() - c.x(), p.y() - c.y()), s};
}

/// Gap below which two curves are taken to really cross (the modelling tolerance).
constexpr double kCrossingGap = 1e-6;

/// The curve of `curves` nearest to `p` and the parameter of its foot point.
std::optional<std::pair<const nf::NurbsCurve*, double>> foot_on(const std::vector<nf::NurbsCurve>& curves,
                                                                const nf::Vec3& p) {
  std::optional<std::pair<const nf::NurbsCurve*, double>> best;
  double best_d = std::numeric_limits<double>::max();
  for (const nf::NurbsCurve& c : curves) {
    try {
      const nf::CurvePoint f = nf::closest_point(c, p);
      if (f.distance < best_d) {
        best_d = f.distance;
        best = std::make_pair(&c, f.u);
      }
    } catch (const std::exception&) {
    }
  }
  return best;
}

/// The crossing of two curves near the display crossing `pa` (on A) / `pb` (on B): Gauss-Newton
/// on a(s) - b(t) = 0 from the foot points. Local and cheap, unlike a global curve/curve
/// intersection, which subdivides nearly coincident curves down to its size limit and must not run
/// on every mouse move. Empty when the curves do not meet there (gap above kCrossingGap).
std::optional<nf::Vec3> refine_crossing(const std::vector<nf::NurbsCurve>& as,
                                        const std::vector<nf::NurbsCurve>& bs, const nf::Vec3& pa,
                                        const nf::Vec3& pb) {
  const auto fa = foot_on(as, pa);
  const auto fb = foot_on(bs, pb);
  if (!fa || !fb) return std::nullopt;
  const nf::NurbsCurve& a = *fa->first;
  const nf::NurbsCurve& b = *fb->first;
  double s = fa->second;
  double t = fb->second;
  try {
    for (int it = 0; it < 64; ++it) {
      const std::vector<nf::Vec3> da = a.derivatives(s, 1);
      const std::vector<nf::Vec3> db = b.derivatives(t, 1);
      const nf::Vec3 r = da[0] - db[0];
      // normal equations of J = [a'(s), -b'(t)]
      // (slightly damped: at a tangential crossing the tangents are parallel)
      const double damp = 1e-9 * (nf::dot(da[1], da[1]) + nf::dot(db[1], db[1]));
      const double m11 = nf::dot(da[1], da[1]) + damp;
      const double m12 = -nf::dot(da[1], db[1]);
      const double m22 = nf::dot(db[1], db[1]) + damp;
      const double g1 = nf::dot(da[1], r);
      const double g2 = -nf::dot(db[1], r);
      const double det = m11 * m22 - m12 * m12;
      if (!(det > 0.0)) return std::nullopt;  // degenerate (zero tangent)
      const double ds = -(m22 * g1 - m12 * g2) / det;
      const double dt = -(m11 * g2 - m12 * g1) / det;
      const double s1 = std::clamp(s + ds, a.domain_start(), a.domain_end());
      const double t1 = std::clamp(t + dt, b.domain_start(), b.domain_end());
      const bool done = std::abs(s1 - s) <= 1e-14 * (1.0 + std::abs(s)) &&
                        std::abs(t1 - t) <= 1e-14 * (1.0 + std::abs(t));
      s = s1;
      t = t1;
      if (done) break;
    }
    const nf::Vec3 qa = a.evaluate(s);
    const nf::Vec3 qb = b.evaluate(t);
    if (nf::distance(qa, qb) > kCrossingGap) return std::nullopt;
    return 0.5 * (qa + qb);
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

nf::Vec3 nearest_on(const std::vector<nf::NurbsCurve>& curves, const nf::Vec3& p) {
  nf::Vec3 best = p;
  double best_d = std::numeric_limits<double>::max();
  for (const nf::NurbsCurve& c : curves) {
    const nf::Vec3 q = kernel::closest_on_curve(c, p);
    const double d = nf::distance(q, p);
    if (d < best_d) {
      best_d = d;
      best = q;
    }
  }
  return best;
}

}  // namespace

void SnapEngine::clear() {
  caches_.clear();
}

const SnapEngine::Cache& SnapEngine::cache(const pick::Target& t) {
  const auto it = caches_.find(t.id);
  if (it != caches_.end() && it->second.geometry == t.geometry) return it->second;
  Cache c;
  c.geometry = t.geometry;
  const document::Geometry& g = *t.geometry;
  auto add_curve_features = [&](const nf::NurbsCurve& curve, bool edge) {
    const kernel::CurveFeatures f = kernel::curve_features(curve);
    if (!edge && f.start) c.fixed.push_back({*f.start, SnapType::End, false});
    if (!edge && f.end) c.fixed.push_back({*f.end, SnapType::End, false});
    // polylines, rectangles, polygons: every corner is an End, every segment has a Mid
    // (corners of face edges are Face corners)
    if (!edge) {
      for (const nf::Vec3& p : f.corners) c.fixed.push_back({p, SnapType::End, false});
    }
    if (f.mid) c.fixed.push_back({*f.mid, SnapType::Mid, edge});
    for (const nf::Vec3& p : f.segment_mids) c.fixed.push_back({p, SnapType::Mid, edge});
    if (f.centre) c.fixed.push_back({*f.centre, SnapType::Centre, edge});
    for (const nf::Vec3& qd : f.quadrants) c.fixed.push_back({qd, SnapType::Quadrant, edge});
  };
  if (const auto* p = std::get_if<nf::Vec3>(&g)) {
    c.fixed.push_back({*p, SnapType::Point, false});
  } else if (const auto* curve = std::get_if<nf::NurbsCurve>(&g)) {
    c.curve_entity = true;
    c.curves = {{*curve}};
    add_curve_features(*curve, false);
  } else {
    c.curves = kernel::edge_curves(g);
    for (const auto& list : c.curves) {
      for (const nf::NurbsCurve& edge : list) add_curve_features(edge, true);
    }
    for (const nf::Vec3& corner : kernel::corners(g)) {
      c.fixed.push_back({corner, SnapType::FaceCorner, false});
    }
  }
  return caches_.insert_or_assign(t.id, std::move(c)).first->second;
}

std::vector<SnapResult> SnapEngine::query(const std::vector<pick::Target>& targets,
                                          const viewport::Camera& camera, const SnapQuery& q) {
  std::vector<SnapResult> out;
  const viewport::Ray ray = camera.pickRay(q.cursor_px);
  const QVector3D inv(ray.direction.x() != 0.0F ? 1.0F / ray.direction.x() : 1e30F,
                      ray.direction.y() != 0.0F ? 1.0F / ray.direction.y() : 1e30F,
                      ray.direction.z() != 0.0F ? 1.0F / ray.direction.z() : 1e30F);
  auto depth_of = [&](const nf::Vec3& p) {
    return QVector3D::dotProduct(q3(p) - ray.origin, ray.direction);
  };
  auto add = [&](const nf::Vec3& p, SnapType type, document::EntityId e,
                 document::EntityId other = 0, bool apparent = false) {
    if (!q.mask.test(type)) return;
    const auto s = camera.project(q3(p));
    if (!s) return;
    const auto d = static_cast<float>(std::hypot(s->x() - q.cursor_px.x(), s->y() - q.cursor_px.y()));
    if (d > q.radius_px) return;
    out.push_back({{p.x, p.y, p.z}, type, e, other, apparent, d, depth_of(p)});
  };
  const bool edges_on = q.mask.test(SnapType::FaceEdge);

  struct NearSeg {
    const pick::Target* target;
    const Cache* cache;
    std::uint32_t polyline;
    QVector3D a, b;
    QPointF sa, sb;
    double dist;
    double s;
  };
  std::vector<NearSeg> near;

  for (const pick::Target& t : targets) {
    const tessellation::DisplayMesh& m = *t.mesh;
    if (!m.bounds.valid() || !t.geometry) continue;
    const float inflate = q.radius_px * pick::farthest_world_per_pixel(camera, m.bounds);
    tessellation::Box3 grown = m.bounds;
    grown.min -= QVector3D(inflate, inflate, inflate);
    grown.max += QVector3D(inflate, inflate, inflate);
    if (tessellation::ray_box(ray.origin, inv, grown, kInf) < 0.0F) continue;

    const Cache& c = cache(t);
    for (const Fixed& f : c.fixed) {
      if (f.edge && !edges_on) continue;
      add(f.p, f.type, t.id);
    }
    if (m.segment_bvh.empty() || (!c.curve_entity && !edges_on)) continue;
    m.segment_bvh.raycast(ray.origin, ray.direction, inflate, kInf,
                          [&](std::uint32_t si, float& /*t_max*/) {
      const auto& seg = m.segments[si];
      if (seg.iso) return;
      const auto [a, b] = m.segmentPoints(seg);
      const auto sa = camera.project(a);
      const auto sb = camera.project(b);
      if (!sa || !sb) return;
      const auto [dist, s] = point_segment_2d(q.cursor_px, *sa, *sb);
      if (dist > q.radius_px) return;
      near.push_back({&t, &c, seg.polyline, a, b, *sa, *sb, dist, s});
    });
  }

  // ---- Near: exact foot point on the closest curve of each polyline
  if (q.mask.test(SnapType::Near)) {
    std::map<std::pair<document::EntityId, std::uint32_t>, const NearSeg*> best;
    for (const NearSeg& n : near) {
      auto& b = best[{n.target->id, n.polyline}];
      if (b == nullptr || n.dist < b->dist) b = &n;
    }
    for (const auto& [key, n] : best) {
      const nf::Vec3 approx = n3(n->a + (n->b - n->a) * static_cast<float>(n->s));
      const nf::Vec3 p = n->polyline < n->cache->curves.size()
                             ? nearest_on(n->cache->curves[n->polyline], approx)
                             : approx;
      add(p, SnapType::Near, n->target->id);
    }
  }

  // ---- Intersection: crossing display segments, refined with the exact curves
  if (q.mask.test(SnapType::Intersection)) {
    std::sort(near.begin(), near.end(), [](const NearSeg& a, const NearSeg& b) { return a.dist < b.dist; });
    if (near.size() > kMaxIntersectionSegments) near.resize(kMaxIntersectionSegments);
    const bool parallel = camera.projection() == viewport::Camera::Projection::Orthographic;
    for (std::size_t i = 0; i < near.size(); ++i) {
      for (std::size_t j = i + 1; j < near.size(); ++j) {
        const NearSeg& A = near[i];
        const NearSeg& B = near[j];
        if (A.target == B.target && A.polyline == B.polyline) continue;
        // edges of one face / shell only meet at its vertices (FaceCorner snaps)
        if (A.target == B.target && !A.cache->curve_entity) continue;
        const auto x = segments_2d(A.sa, A.sb, B.sa, B.sb);
        if (!x) continue;
        const QVector3D pa = A.a + (A.b - A.a) * static_cast<float>(x->first);
        const QVector3D pb = B.a + (B.b - B.a) * static_cast<float>(x->second);
        const float tol = 4.0F * camera.worldPerPixelAt(pa);
        const bool has_curves = A.polyline < A.cache->curves.size() &&
                                B.polyline < B.cache->curves.size();
        if ((pa - pb).length() < tol && has_curves) {
          // real intersection: refined locally on the exact curves
          const auto p = refine_crossing(A.cache->curves[A.polyline], B.cache->curves[B.polyline],
                                         n3(pa), n3(pb));
          if (p && nf::distance(*p, n3(pa)) < 10.0 * tol) {
            add(*p, SnapType::Intersection, A.target->id, B.target->id);
          }
        } else if (parallel) {
          // apparent intersection: the point on the curve nearer to the viewer
          const bool a_front = QVector3D::dotProduct(pa - pb, ray.direction) < 0.0F;
          const NearSeg& F = a_front ? A : B;
          const QVector3D pf = a_front ? pa : pb;
          const nf::Vec3 p = F.polyline < F.cache->curves.size()
                                 ? nearest_on(F.cache->curves[F.polyline], n3(pf))
                                 : n3(pf);
          add(p, SnapType::Intersection, A.target->id, B.target->id, true);
        }
      }
    }
  }

  // ---- points of the object being drawn (e.g. the start of a polyline in progress)
  for (const SnapPoint& p : q.command_points) add({p.x, p.y, p.z}, SnapType::End, 0);

  // ---- Grid points of the construction plane
  if (q.mask.test(SnapType::Grid) && q.grid) {
    const auto& [plane, spacing] = *q.grid;
    if (const auto hit = viewport::intersect_plane(ray, plane.origin, plane.normal()); hit && spacing > 0.0F) {
      const QVector3D rel = *hit - plane.origin;
      const double u = std::round(QVector3D::dotProduct(rel, plane.u) / spacing) * spacing;
      const double v = std::round(QVector3D::dotProduct(rel, plane.v) / spacing) * spacing;
      const nf::Vec3 o = n3(plane.origin);
      add(o + n3(plane.u) * u + n3(plane.v) * v, SnapType::Grid, 0);
    }
  }

  // ---- hidden candidates (behind the face under the cursor)
  if (q.faces_occlude && !out.empty()) {
    if (const auto face = pick::pick_face(targets, camera, q.cursor_px)) {
      const float tol = 2.0F * q.radius_px * camera.worldPerPixelAt(face->point);
      std::erase_if(out, [&](const SnapResult& r) { return r.depth > face->depth + tol; });
    }
  }

  std::sort(out.begin(), out.end(), [](const SnapResult& a, const SnapResult& b) {
    const int ra = priority_rank(a.type);
    const int rb = priority_rank(b.type);
    if (ra != rb) return ra < rb;
    if (std::abs(a.distance_px - b.distance_px) > 0.5F) return a.distance_px < b.distance_px;
    return a.depth < b.depth;
  });
  // the same point found several times (shared corners, segment pairs): keep the first
  std::vector<SnapResult> unique;
  for (const SnapResult& r : out) {
    const bool dup = std::any_of(unique.begin(), unique.end(), [&](const SnapResult& u) {
      return u.type == r.type && (u.position() - r.position()).length() <=
                                     1e-6F * std::max(1.0F, u.position().length());
    });
    if (!dup) unique.push_back(r);
  }
  return unique;
}

}  // namespace nfcad::snap
