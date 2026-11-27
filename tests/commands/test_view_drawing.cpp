// Silhouette, Make2D, Outline (view_drawing_commands.cpp) and ChamferSrf (surface_commands.cpp).
#include <QTest>
#include <cmath>
#include <nurbforge/nurbforge.hpp>

#include "commands/command.hpp"

using nfcad::commands::Command;
using nfcad::commands::create_command;
using nfcad::commands::PlaneFrame;
using nfcad::document::Entity;
using nfcad::document::Geometry;
using R = Command::Result;

namespace {

Entity entity(Geometry g, nfcad::document::EntityId id = 1) {
  Entity e = nfcad::document::make_entity(std::move(g));
  e.id = id;
  return e;
}

/// Parallel view along `view` (from the viewer into the scene).
PlaneFrame looking(nf::Vec3 view, nf::Vec3 up) {
  view = view / nf::norm(view);
  up = up - nf::dot(up, view) * view;
  up = up / nf::norm(up);
  PlaneFrame f;
  f.view = {view.x, view.y, view.z};
  f.up = {up.x, up.y, up.z};
  return f;
}

std::unique_ptr<Command> started(const char* name, std::vector<Entity> sel, const PlaneFrame& f = {}) {
  auto c = create_command(QString::fromLatin1(name));
  c->setViewPlane(f);
  if (!c->begin(sel)) {
    qWarning("%s: %s", name, qPrintable(c->message()));
    return nullptr;
  }
  return c;
}

const nf::NurbsCurve& curve(const Entity& e) { return std::get<nf::NurbsCurve>(*e.geometry); }

/// Largest |distance from the z axis - r| and |z| over samples of a curve.
std::pair<double, double> off_circle(const nf::NurbsCurve& c, double r) {
  double dr = 0, dz = 0;
  const double a = c.domain_start(), b = c.domain_end();
  for (int i = 0; i <= 50; ++i) {
    const nf::Vec3 p = c.evaluate(a + (b - a) * i / 50.0);
    dr = std::max(dr, std::abs(std::hypot(p.x, p.y) - r));
    dz = std::max(dz, std::abs(p.z));
  }
  return {dr, dz};
}

}  // namespace

class TestViewDrawing : public QObject {
  Q_OBJECT
 private slots:
  void silhouetteOfSphere() {
    auto c = started("silhouette", {entity(nf::make_sphere({0, 0, 0}, 2.0))});
    QVERIFY(c && c->immediate());
    QCOMPARE(c->finish(), R::Done);
    const auto made = c->takeEntities();
    QVERIFY(!made.empty());
    for (const Entity& e : made) {  // the equator (possibly in pieces at seams)
      const auto [dr, dz] = off_circle(curve(e), 2.0);
      QVERIFY2(dr < 1e-4 && dz < 1e-4, qPrintable(QStringLiteral("%1 %2").arg(dr).arg(dz)));
    }
  }

  void make2dOfBox() {
    const Entity box = entity(nf::make_box({0, 0, 0}, {1, 2, 3}));
    // top view: the rectangle; vertical edges project to points, the bottom lies under the top
    auto c = started("make2d", {box});
    QVERIFY(c);
    auto made = c->takeEntities();
    QCOMPARE(made.size(), std::size_t{4});
    for (const Entity& e : made) QVERIFY(!e.color);
    // along the diagonal: 9 visible edges, 3 hidden ones (grey), all in the XY plane
    c = started("make2d", {box}, looking({-1, -1, -1}, {0, 0, 1}));
    QVERIFY(c);
    made = c->takeEntities();
    const auto hidden = std::count_if(made.begin(), made.end(), [](const Entity& e) { return e.color.has_value(); });
    QCOMPARE(made.size() - hidden, std::size_t{9});
    QCOMPARE(hidden, 3);
    for (const Entity& e : made) {
      for (const nf::Vec3& p : curve(e).control_points()) QVERIFY(std::abs(p.z) < 1e-9);
    }
  }

  void outlines() {
    auto c = started("outline", {entity(nf::make_sphere({0, 0, 0}, 2.0))});
    QVERIFY(c);
    auto made = c->takeEntities();
    QCOMPARE(made.size(), std::size_t{1});
    QVERIFY(nf::is_closed(curve(made[0]), 1e-6));
    const auto [dr, dz] = off_circle(curve(made[0]), 2.0);
    QVERIFY2(dr < 1e-4 && dz < 1e-9, qPrintable(QStringLiteral("%1 %2").arg(dr).arg(dz)));
    // a box seen along its diagonal: one hexagon in the plane through the origin normal to it
    c = started("outline", {entity(nf::make_box({0, 0, 0}, {1, 1, 1}))}, looking({-1, -1, -1}, {0, 0, 1}));
    QVERIFY(c);
    made = c->takeEntities();
    QCOMPARE(made.size(), std::size_t{1});
    const nf::NurbsCurve& hex = curve(made[0]);
    QVERIFY(nf::is_closed(hex, 1e-6));
    const double a = hex.domain_start(), b = hex.domain_end();
    for (int i = 0; i <= 30; ++i) {
      const nf::Vec3 p = hex.evaluate(a + (b - a) * i / 30.0);
      QVERIFY(std::abs(p.x + p.y + p.z) < 1e-9);
    }
  }

  void nothingToDraw() {
    QVERIFY(!started("make2d", {entity(nf::make_line({0, 0, 0}, {1, 0, 0}))}));
    // a plane seen edge-on has no silhouette
    QVERIFY(!started("silhouette", {entity(nf::make_rectangle({0, 0, 0}, {1, 0, 0}, {0, 0, 1}))},
                     looking({0, 1, 0}, {0, 0, 1})));
  }

  void chamferSurfaces() {
    const Entity floor = entity(nf::make_rectangle({-5, -5, 0}, {10, 0, 0}, {0, 10, 0}), 1);
    const Entity wall = entity(nf::make_rectangle({0, -5, -5}, {0, 10, 0}, {0, 0, 10}), 2);
    auto c = started("chamfersrf", {floor, wall});
    QVERIFY(c);
    QCOMPARE(c->number(1.0), R::Continue);
    QCOMPARE(c->number(2.0), R::Done);
    auto made = c->takeEntities();
    const auto& s = std::get<nf::NurbsSurface>(*made[0].geometry);
    // u = 0 on the floor at distance 1 from the wall, u = 1 on the wall 2 above / below the floor
    const auto [v0, v1] = s.domain_v();
    for (double f : {0.2, 0.7}) {
      const double v = v0 + f * (v1 - v0);
      const nf::Vec3 p0 = s.evaluate(0.0, v);
      const nf::Vec3 p1 = s.evaluate(1.0, v);
      QVERIFY(std::abs(std::abs(p0.x) - 1.0) < 1e-5 && std::abs(p0.z) < 1e-5);
      QVERIFY(std::abs(p1.x) < 1e-5 && std::abs(std::abs(p1.z) - 2.0) < 1e-5);
    }
    // Enter after one distance: the same on both
    c = started("chamfer_surface", {floor, wall});
    QCOMPARE(c->number(0.5), R::Continue);
    QCOMPARE(c->finish(), R::Done);
    made = c->takeEntities();
    const auto& s2 = std::get<nf::NurbsSurface>(*made[0].geometry);
    const nf::Vec3 p1 = s2.evaluate(1.0, 0.5 * (s2.domain_v()[0] + s2.domain_v()[1]));
    QVERIFY(std::abs(std::abs(p1.z) - 0.5) < 1e-5);
    QVERIFY(!started("chamfersrf", {floor}));
  }
};

QTEST_GUILESS_MAIN(TestViewDrawing)
#include "test_view_drawing.moc"
