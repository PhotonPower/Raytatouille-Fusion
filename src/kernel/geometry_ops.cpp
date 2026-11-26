#include "kernel/geometry_ops.hpp"

#include <QObject>
#include <exception>
#include <algorithm>
#include <array>
#include <cmath>
#include <nurbforge/geometry/primitives.hpp>
#include <nurbforge/io/step.hpp>
#include <nurbforge/nurbs/join.hpp>
#include <nurbforge/topology/boolean.hpp>
#include <stdexcept>

namespace nfcad::kernel {

namespace {
nf::TrimmedSurface transform_face(const nf::TrimmedSurface& f, const nf::Transform& t) {
  nf::NurbsSurface s = f.surface().transformed(t);
  if (f.is_untrimmed()) return nf::TrimmedSurface(std::move(s)).with_label(f.label());
  return nf::TrimmedSurface(std::move(s), f.outer(), f.holes()).with_label(f.label());
}
}  // namespace

document::Geometry transformed(const document::Geometry& g, const nf::Transform& t) {
  return std::visit(
      [&](const auto& v) -> document::Geometry {
        using T = std::decay_t<decltype(v)>;
        if constexpr (std::is_same_v<T, nf::Vec3>) {
          return t.apply(v);
        } else if constexpr (std::is_same_v<T, nf::TrimmedSurface>) {
          return transform_face(v, t);
        } else {
          return v.transformed(t);
        }
      },
      g);
}

std::vector<std::vector<nf::Vec3>> wire(const document::Geometry& g, std::size_t max_points) {
  std::vector<std::vector<nf::Vec3>> out;
  std::vector<const nf::NurbsCurve*> curves;
  std::vector<nf::NurbsCurve> owned;
  std::visit(
      [&](const auto& v) {
        using T = std::decay_t<decltype(v)>;
        if constexpr (std::is_same_v<T, nf::Vec3>) {
          const double h = 0.5;
          out.push_back({v - nf::Vec3{h, 0, 0}, v + nf::Vec3{h, 0, 0}});
          out.push_back({v - nf::Vec3{0, h, 0}, v + nf::Vec3{0, h, 0}});
        } else if constexpr (std::is_same_v<T, nf::NurbsCurve>) {
          curves.push_back(&v);
        } else if constexpr (std::is_same_v<T, nf::NurbsSurface>) {
          owned.push_back(v.iso_curve_u(v.domain_u()[0]));
          owned.push_back(v.iso_curve_u(v.domain_u()[1]));
          owned.push_back(v.iso_curve_v(v.domain_v()[0]));
          owned.push_back(v.iso_curve_v(v.domain_v()[1]));
        } else if constexpr (std::is_same_v<T, nf::TrimmedSurface>) {
          try {
            for (auto& loop : v.boundary_curves(1e-4)) {
              for (auto& c : loop) owned.push_back(std::move(c));
            }
          } catch (const std::exception&) {
          }
        } else {
          for (const nf::ShellEdge& e : v.edges()) curves.push_back(&e.curve);
        }
      },
      g);
  for (const auto& c : owned) curves.push_back(&c);
  if (curves.empty()) return out;
  const std::size_t per = std::max<std::size_t>(2, max_points / curves.size());
  for (const nf::NurbsCurve* c : curves) {
    const std::size_t n = c->degree() == 1 ? c->num_control_points() : std::min<std::size_t>(per, 64);
    out.push_back(c->degree() == 1 ? c->control_points() : c->sample(n));
  }
  return out;
}

nf::Shell boolean(const std::vector<nf::Shell>& shells, BooleanOp op) {
  if (shells.size() < 2) throw std::runtime_error(QObject::tr("select at least two solids").toStdString());
  for (const nf::Shell& s : shells) {
    if (!s.is_closed()) {
      throw std::runtime_error(QObject::tr("Booleans need closed solids").toStdString());
    }
  }
  const nf::BooleanOp nop = op == BooleanOp::Union          ? nf::BooleanOp::Union
                            : op == BooleanOp::Intersection ? nf::BooleanOp::Intersection
                                                            : nf::BooleanOp::Difference;
  nf::Shell result = shells.front();
  for (std::size_t i = 1; i < shells.size(); ++i) result = nf::boolean(result, shells[i], nop);
  if (result.faces().empty()) {
    throw std::runtime_error(QObject::tr("the result is empty").toStdString());
  }
  return result;
}

std::optional<document::Geometry> part_of(const document::Geometry& g, const document::SubElement& sub) {
  if (const auto* c = std::get_if<nf::NurbsCurve>(&g); c != nullptr && sub.kind == document::SubElement::Kind::ControlPoint &&
                                                       sub.index >= 0 && static_cast<std::size_t>(sub.index) < c->num_control_points()) {
    return c->control_points()[static_cast<std::size_t>(sub.index)];
  }
  const auto* sh = std::get_if<nf::Shell>(&g);
  if (sh == nullptr || sub.index < 0) return std::nullopt;
  const auto i = static_cast<std::size_t>(sub.index);
  if (sub.kind == document::SubElement::Kind::Edge && i < sh->edges().size()) return sh->edges()[i].curve;
  if (sub.kind == document::SubElement::Kind::Face && i < sh->faces().size()) return sh->faces()[i];
  return std::nullopt;
}

nf::NurbsCurve with_control_points_moved(const nf::NurbsCurve& c, const std::vector<int>& indices,
                                         const nf::Transform& t) {
  std::vector<nf::Vec3> pts = c.control_points();
  for (int i : indices) {
    if (i >= 0 && static_cast<std::size_t>(i) < pts.size()) {
      pts[static_cast<std::size_t>(i)] = t.apply(pts[static_cast<std::size_t>(i)]);
    }
  }
  return {c.degree(), c.knots(), pts, c.weights()};
}

std::vector<nf::TrimmedSurface> faces_of(const document::Geometry& g) {
  if (const auto* s = std::get_if<nf::NurbsSurface>(&g)) return {nf::TrimmedSurface(*s)};
  if (const auto* f = std::get_if<nf::TrimmedSurface>(&g)) return {*f};
  if (const auto* sh = std::get_if<nf::Shell>(&g)) return sh->faces();
  return {};
}

nf::NurbsCurve join_chain(std::vector<nf::NurbsCurve> curves, double tolerance) {
  if (curves.empty()) throw std::runtime_error("no curves");
  auto start = [](const nf::NurbsCurve& c) { return c.evaluate(c.domain_start()); };
  auto end = [](const nf::NurbsCurve& c) { return c.evaluate(c.domain_end()); };
  nf::NurbsCurve chain = curves.front();
  curves.erase(curves.begin());
  while (!curves.empty()) {
    bool found = false;
    for (std::size_t i = 0; i < curves.size() && !found; ++i) {
      const nf::NurbsCurve& c = curves[i];
      if (nf::distance(end(chain), start(c)) <= tolerance) {
        chain = nf::join(chain, c, tolerance);
      } else if (nf::distance(end(chain), end(c)) <= tolerance) {
        chain = nf::join(chain, c.reversed(), tolerance);
      } else if (nf::distance(start(chain), end(c)) <= tolerance) {
        chain = nf::join(c, chain, tolerance);
      } else if (nf::distance(start(chain), start(c)) <= tolerance) {
        chain = nf::join(c.reversed(), chain, tolerance);
      } else {
        continue;
      }
      curves.erase(curves.begin() + static_cast<std::ptrdiff_t>(i));
      found = true;
    }
    if (!found) throw std::runtime_error(QObject::tr("the curves do not form one chain").toStdString());
  }
  return chain;
}

nf::Shell cap_planar_holes(const std::vector<nf::TrimmedSurface>& faces, double tolerance) {
  const nf::Shell open = nf::Shell::sew(faces, tolerance);
  const auto free = open.free_edges();
  if (free.empty()) throw std::runtime_error(QObject::tr("there are no open edges").toStdString());

  // chain the free edges into loops via their vertices
  std::vector<bool> used(free.size(), false);
  std::vector<std::vector<nf::NurbsCurve>> loops;
  for (std::size_t s = 0; s < free.size(); ++s) {
    if (used[s]) continue;
    used[s] = true;
    const nf::ShellEdge& first = open.edges()[free[s]];
    std::vector<nf::NurbsCurve> loop{first.curve};
    const std::size_t start_v = first.v0;
    std::size_t v = first.v1;
    while (v != start_v) {
      bool advanced = false;
      for (std::size_t k = 0; k < free.size() && !advanced; ++k) {
        if (used[k]) continue;
        const nf::ShellEdge& e = open.edges()[free[k]];
        if (e.v0 == v) {
          loop.push_back(e.curve);
          v = e.v1;
        } else if (e.v1 == v) {
          loop.push_back(e.curve.reversed());
          v = e.v0;
        } else {
          continue;
        }
        used[k] = true;
        advanced = true;
      }
      if (!advanced) break;  // not closed
    }
    if (v == start_v) loops.push_back(std::move(loop));
  }

  std::vector<nf::TrimmedSurface> all = faces;
  std::size_t caps = 0;
  for (const auto& loop : loops) {
    // plane of the loop (Newell normal of samples), planarity check
    std::vector<nf::Vec3> pts;
    for (const auto& c : loop) {
      for (const nf::Vec3& p : c.sample(32)) pts.push_back(p);
    }
    nf::Vec3 n{0, 0, 0};
    nf::Vec3 centre{0, 0, 0};
    for (std::size_t i = 0; i < pts.size(); ++i) {
      n += nf::cross(pts[i], pts[(i + 1) % pts.size()]);
      centre += pts[i];
    }
    centre = centre / static_cast<double>(pts.size());
    if (nf::norm(n) < 1e-14) continue;
    n = n / nf::norm(n);
    double size = 0.0;
    for (const nf::Vec3& p : pts) size = std::max(size, nf::distance(p, centre));
    bool planar = true;
    for (const nf::Vec3& p : pts) planar = planar && std::abs(nf::dot(p - centre, n)) <= 1e-7 * std::max(size, 1.0);
    if (!planar) continue;

    // planar rectangle covering the loop; the loop curves mapped affinely into its (u, v)
    const nf::Vec3 ux = nf::any_perpendicular(n);
    const nf::Vec3 vy = nf::cross(n, ux);
    double u0 = 1e300, u1 = -1e300, v0 = 1e300, v1 = -1e300;
    for (const nf::Vec3& p : pts) {
      u0 = std::min(u0, nf::dot(p - centre, ux));
      u1 = std::max(u1, nf::dot(p - centre, ux));
      v0 = std::min(v0, nf::dot(p - centre, vy));
      v1 = std::max(v1, nf::dot(p - centre, vy));
    }
    const double margin = 0.05 * std::max(u1 - u0, v1 - v0);
    u0 -= margin;
    u1 += margin;
    v0 -= margin;
    v1 += margin;
    const nf::Vec3 origin = centre + ux * u0 + vy * v0;
    const nf::NurbsSurface plane = nf::make_rectangle(origin, ux * (u1 - u0), vy * (v1 - v0));
    nf::TrimLoop trim;
    for (const nf::NurbsCurve& c : loop) {
      std::vector<nf::Vec3> uv;
      for (const nf::Vec3& p : c.control_points()) {
        uv.emplace_back(nf::dot(p - origin, ux) / (u1 - u0), nf::dot(p - origin, vy) / (v1 - v0), 0.0);
      }
      trim.curves.emplace_back(c.degree(), c.knots(), uv, c.weights());
    }
    all.emplace_back(plane, trim);
    ++caps;
  }
  if (caps == 0) throw std::runtime_error(QObject::tr("no planar open loop to cap").toStdString());
  return nf::Shell::sew(all, tolerance).oriented();
}

std::vector<nf::TrimmedSurface> planar_faces(const std::vector<nf::NurbsCurve>& curves) {
  if (curves.empty()) throw std::runtime_error(QObject::tr("no curves").toStdString());
  // the common plane: Newell normal of all samples, centre, extent
  std::vector<std::vector<nf::Vec3>> samples;
  nf::Vec3 n{0, 0, 0}, centre{0, 0, 0};
  std::size_t count = 0;
  for (const nf::NurbsCurve& c : curves) {
    if (nf::distance(c.evaluate(c.domain_start()), c.evaluate(c.domain_end())) > 1e-7 * std::max(1.0, nf::norm(c.control_points().front()))) {
      throw std::runtime_error(QObject::tr("a curve is not closed").toStdString());
    }
    samples.push_back(c.sample(96));
    samples.back().pop_back();  // the closing point repeats the first
    const auto& pts = samples.back();
    for (std::size_t i = 0; i < pts.size(); ++i) {
      n += nf::cross(pts[i], pts[(i + 1) % pts.size()]);
      centre += pts[i];
      ++count;
    }
  }
  if (nf::norm(n) < 1e-14) throw std::runtime_error(QObject::tr("the curves enclose no area").toStdString());
  n = n / nf::norm(n);
  centre = centre / static_cast<double>(count);
  double size = 0;
  for (const auto& pts : samples) {
    for (const nf::Vec3& p : pts) size = std::max(size, nf::distance(p, centre));
  }
  for (const auto& pts : samples) {
    for (const nf::Vec3& p : pts) {
      if (std::abs(nf::dot(p - centre, n)) > 1e-7 * std::max(size, 1.0)) {
        throw std::runtime_error(QObject::tr("the curves do not lie in one plane").toStdString());
      }
    }
  }
  const nf::Vec3 ux = nf::any_perpendicular(n);
  const nf::Vec3 vy = nf::cross(n, ux);
  using P2 = std::array<double, 2>;
  std::vector<std::vector<P2>> poly;
  for (const auto& pts : samples) {
    std::vector<P2> q;
    for (const nf::Vec3& p : pts) q.push_back({nf::dot(p - centre, ux), nf::dot(p - centre, vy)});
    poly.push_back(std::move(q));
  }
  auto inside = [](const P2& p, const std::vector<P2>& q) {
    bool in = false;
    for (std::size_t i = 0, j = q.size() - 1; i < q.size(); j = i++) {
      if ((q[i][1] > p[1]) != (q[j][1] > p[1]) &&
          p[0] < (q[j][0] - q[i][0]) * (p[1] - q[i][1]) / (q[j][1] - q[i][1]) + q[i][0]) {
        in = !in;
      }
    }
    return in;
  };
  auto area = [](const std::vector<P2>& q) {
    double a = 0;
    for (std::size_t i = 0, j = q.size() - 1; i < q.size(); j = i++) a += q[j][0] * q[i][1] - q[i][0] * q[j][1];
    return 0.5 * a;
  };
  const std::size_t m = curves.size();
  std::vector<int> depth(m, 0);
  std::vector<std::size_t> parent(m, m);  // the smallest curve around it
  for (std::size_t i = 0; i < m; ++i) {
    for (std::size_t j = 0; j < m; ++j) {
      if (i == j || !inside(poly[i].front(), poly[j])) continue;
      ++depth[i];
      if (parent[i] == m || std::abs(area(poly[j])) < std::abs(area(poly[parent[i]]))) parent[i] = j;
    }
  }
  std::vector<nf::TrimmedSurface> out;
  for (std::size_t o = 0; o < m; ++o) {
    if (depth[o] % 2 != 0) continue;
    // the plane rectangle over the outer curve; the loops mapped affinely into its (u, v)
    double u0 = 1e300, u1 = -1e300, v0 = 1e300, v1 = -1e300;
    for (const P2& p : poly[o]) {
      u0 = std::min(u0, p[0]);
      u1 = std::max(u1, p[0]);
      v0 = std::min(v0, p[1]);
      v1 = std::max(v1, p[1]);
    }
    const double margin = 0.05 * std::max(u1 - u0, v1 - v0);
    u0 -= margin;
    u1 += margin;
    v0 -= margin;
    v1 += margin;
    const nf::Vec3 origin = centre + ux * u0 + vy * v0;
    const nf::NurbsSurface plane = nf::make_rectangle(origin, ux * (u1 - u0), vy * (v1 - v0));
    auto loop_of = [&](std::size_t k, bool ccw) {
      nf::NurbsCurve c = (area(poly[k]) > 0) == ccw ? curves[k] : curves[k].reversed();
      std::vector<nf::Vec3> uv;
      for (const nf::Vec3& p : c.control_points()) {
        uv.emplace_back(nf::dot(p - origin, ux) / (u1 - u0), nf::dot(p - origin, vy) / (v1 - v0), 0.0);
      }
      nf::TrimLoop loop;
      loop.curves.emplace_back(c.degree(), c.knots(), uv, c.weights());
      return loop;
    };
    std::vector<nf::TrimLoop> holes;
    for (std::size_t h = 0; h < m; ++h) {
      if (parent[h] == o && depth[h] == depth[o] + 1) holes.push_back(loop_of(h, false));
    }
    out.emplace_back(plane, loop_of(o, true), holes);
  }
  return out;
}

std::size_t export_step(const QString& path, const std::vector<const document::Entity*>& entities) {
  std::vector<nf::Shell> shells;
  nf::StepOptions options;
  options.name = "Raytatouille Fusion";
  for (const document::Entity* e : entities) {
    if (const auto* s = std::get_if<nf::Shell>(e->geometry.get())) {
      shells.push_back(*s);
      options.shell_names.push_back(e->name.isEmpty() ? "shell_" + std::to_string(e->id)
                                                      : e->name.toStdString());
    } else if (const auto* f = std::get_if<nf::TrimmedSurface>(e->geometry.get())) {
      shells.push_back(nf::Shell::sew({*f}));
      options.shell_names.push_back(e->name.toStdString());
    } else if (const auto* sf = std::get_if<nf::NurbsSurface>(e->geometry.get())) {
      shells.push_back(nf::Shell::sew({nf::TrimmedSurface(*sf)}));
      options.shell_names.push_back(e->name.toStdString());
    }
  }
  if (!shells.empty()) nf::write_step(path.toStdString(), shells, options);
  return shells.size();
}

}  // namespace nfcad::kernel
