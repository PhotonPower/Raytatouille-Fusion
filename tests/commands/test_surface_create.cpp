// Creating surfaces (surface_create_commands.cpp), each against a closed form.
#include <QImage>
#include <QTemporaryDir>
#include <QTest>
#include <cmath>
#include <numbers>
#include <nurbforge/nurbforge.hpp>

#include "commands/command.hpp"
#include "kernel/geometry_ops.hpp"

using nfcad::commands::Command;
using nfcad::commands::create_command;
using nfcad::commands::PlaneFrame;
using nfcad::document::Entity;
using nfcad::document::make_entity;
using R = Command::Result;

namespace {

const PlaneFrame kTop{};
constexpr double kPi = std::numbers::pi;

std::unique_ptr<Command> started(const char* name, std::vector<Entity> sel = {}) {
  auto c = create_command(QString::fromLatin1(name));
  c->setViewPlane(kTop);
  if (c->usesSelection() && !c->begin(sel)) return nullptr;
  return c;
}

template <class G>
G only(Command& c) {
  const auto made = c.takeEntities();
  if (made.size() != 1) throw std::runtime_error("not one result");
  return std::get<G>(*made.front().geometry);
}

Entity line(nf::Vec3 a, nf::Vec3 b) { return make_entity(nf::make_line(a, b)); }

}  // namespace

class TestSurfaceCreate : public QObject {
  Q_OBJECT
 private slots:
  void surfaceFromPoints() {
    auto c = started("srfpt");
    for (const nf::Vec3& p : {nf::Vec3{0, 0, 0}, nf::Vec3{2, 0, 0}, nf::Vec3{2, 1, 0}}) {
      QCOMPARE(c->point({p.x, p.y, p.z}, kTop), R::Continue);
    }
    QCOMPARE(c->point({0, 1, 1}, kTop), R::Done);  // a warped quad
    const auto s = only<nf::NurbsSurface>(*c);
    QVERIFY(nf::distance(s.evaluate(1, 1), {2, 1, 0}) < 1e-12 || nf::distance(s.evaluate(0, 1), {2, 1, 0}) < 1e-12 ||
            nf::distance(s.evaluate(1, 0), {2, 1, 0}) < 1e-12);
    c = started("srfpt");
    c->point({0, 0, 0}, kTop);
    c->point({2, 0, 0}, kTop);
    c->point({0, 2, 0}, kTop);
    QCOMPARE(c->finish(), R::Done);  // a triangle
    QVERIFY(std::abs(nf::area(only<nf::NurbsSurface>(*c)) - 2.0) < 1e-9);
  }

  void edgeSurfaces() {
    // two lines: ruled (the second runs the other way)
    auto c = started("edgesrf", {line({0, 0, 0}, {2, 0, 0}), line({2, 1, 1}, {0, 1, 1})});
    QCOMPARE(c->finish(), R::Done);
    QVERIFY(std::abs(nf::area(only<nf::NurbsSurface>(*c)) - 2 * std::sqrt(2.0)) < 1e-9);
    // a square of four edges, shuffled and partly reversed: the flat square
    c = started("edgesrf", {line({0, 0, 0}, {2, 0, 0}), line({0, 2, 0}, {2, 2, 0}), line({0, 2, 0}, {0, 0, 0}),
                            line({2, 0, 0}, {2, 2, 0})});
    QCOMPARE(c->finish(), R::Done);
    QVERIFY(std::abs(nf::area(only<nf::NurbsSurface>(*c)) - 4.0) < 1e-9);
    // three edges: a triangle
    c = started("edgesrf", {line({0, 0, 0}, {2, 0, 0}), line({2, 0, 0}, {0, 2, 0}), line({0, 2, 0}, {0, 0, 0})});
    QCOMPARE(c->finish(), R::Done);
    QVERIFY(std::abs(nf::area(only<nf::NurbsSurface>(*c)) - 2.0) < 1e-6);
    QVERIFY(!started("edgesrf", {line({0, 0, 0}, {1, 0, 0})}));
  }

  void planarSurfaceWithHole() {
    auto c = started("planarsrf", {make_entity(nf::make_rectangle_curve({0, 0, 0}, {4, 0, 0}, {0, 4, 0})),
                                   make_entity(nf::make_circle({2, 2, 0}, {0, 0, 1}, 1.0))});
    QCOMPARE(c->finish(), R::Done);
    const auto f = only<nf::TrimmedSurface>(*c);
    QVERIFY(std::abs(f.area() - (16.0 - kPi)) < 1e-6);
    QCOMPARE(f.holes().size(), std::size_t{1});
    c = started("planarsrf", {line({0, 0, 0}, {1, 0, 0})});
    QCOMPARE(c->finish(), R::Rejected);  // not closed
  }

  void patchThroughPoints() {
    std::vector<Entity> pts;
    for (int i = 0; i <= 6; ++i) {
      for (int j = 0; j <= 6; ++j) {
        const double x = i / 3.0 - 1, y = j / 3.0 - 1;
        pts.push_back(make_entity(nf::Vec3{x, y, 0.2 * (x * x + y * y)}));
      }
    }
    auto c = started("patch", pts);
    QCOMPARE(c->number(0.0), R::Done);
    QVERIFY(c->message().contains(QStringLiteral("distance")));
    const auto s = only<nf::NurbsSurface>(*c);
    QVERIFY(nf::closest_point(s, {0.5, 0.5, 0.1}).distance < 1e-3);
  }

  void railRevolveFollowsTheRail() {
    const auto rail = nf::NurbsCurve(2, {0, 0, 0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1, 1, 1},
                                     {{2, 0, 0}, {2, 1, 0}, {0, 1, 0}, {-2, 1, 0}, {-2, 0, 0}, {-2, -1, 0}, {0, -1, 0}, {2, -1, 0}, {2, 0, 0}},
                                     {1, std::sqrt(0.5), 1, std::sqrt(0.5), 1, std::sqrt(0.5), 1, std::sqrt(0.5), 1});  // ellipse 2 × 1
    auto c = started("railrevolve", {line({0, 0, 2}, {2, 0, 0}), make_entity(rail)});
    QVERIFY(c);
    c->point({0, 0, 0}, kTop);
    QCOMPARE(c->point({0, 0, 1}, kTop), R::Done);
    const auto s = only<nf::NurbsSurface>(*c);
    for (double v : {0.1, 0.3, 0.6}) {
      // the profile's far end on the rail
      const auto d = s.domain_v();
      const nf::Vec3 p = s.evaluate(s.domain_u()[1], d[0] + v * (d[1] - d[0]));
      QVERIFY(nf::closest_point(rail, p).distance < 1e-4);
    }
  }

  void extrusions() {
    // along a curve: the profile translated, exact
    auto c = started("extrudealong", {line({0, 0, 0}, {1, 0, 0}), make_entity(nf::make_arc_3pt({0, 0, 0}, {1, 1, 0}, {2, 0, 0}))});
    QCOMPARE(c->finish(), R::Done);
    const auto t = only<nf::NurbsSurface>(*c);
    QVERIFY(nf::distance(t.evaluate(t.domain_u()[1], t.domain_v()[1]), {3, 0, 0}) < 1e-12);
    // to a point: a circular cone
    c = started("extrudetopoint", {make_entity(nf::make_circle({0, 0, 0}, {0, 0, 1}, 1.0))});
    QCOMPARE(c->point({0, 0, 1}, kTop), R::Done);
    QVERIFY(std::abs(nf::area(only<nf::NurbsSurface>(*c)) - kPi * std::sqrt(2.0)) < 1e-6);
    // tapered by 10°: the top square grows by tan(10°) on every side
    c = started("extrudetapered", {make_entity(nf::make_rectangle_curve({0, 0, 0}, {2, 0, 0}, {0, 2, 0}))});
    QCOMPARE(c->number(10), R::Continue);
    QCOMPARE(c->number(1), R::Done);
    const auto walls = c->takeEntities();
    QCOMPARE(walls.size(), std::size_t{4});
    double top = 0;
    for (const auto& w : walls) {
      const auto& s = std::get<nf::NurbsSurface>(*w.geometry);
      for (const nf::Vec3& p : s.control_points()) top = std::max(top, p.x);
    }
    QVERIFY(std::abs(top - (2 + std::tan(10 * kPi / 180))) < 1e-9);
  }

  void extrudeSurfaceAndPipe() {
    auto c = started("extrudesrf", {make_entity(nf::make_rectangle({0, 0, 0}, {2, 0, 0}, {0, 1, 0}))});
    QCOMPARE(c->number(3), R::Done);
    const auto box = only<nf::Shell>(*c);
    QVERIFY(box.is_closed());
    QVERIFY(std::abs(box.volume() - 6.0) < 1e-6);
    c = started("pipe", {line({0, 0, 0}, {0, 0, 10})});
    QCOMPARE(c->number(1), R::Continue);
    QCOMPARE(c->finish(), R::Done);  // the same end radius
    QVERIFY(std::abs(only<nf::Shell>(*c).volume() - 10 * kPi) < 1e-3);
  }

  void pointGrid() {
    std::vector<Entity> pts;
    for (int i = 0; i < 3; ++i) {
      for (int j = 0; j < 4; ++j) pts.push_back(make_entity(nf::Vec3{double(j), double(i), (i == 1 && j == 1) ? 1.0 : 0.0}));
    }
    auto c = started("frompointgrid", pts);
    QCOMPARE(c->number(5), R::Rejected);  // 12 points are no rows of 5
    QCOMPARE(c->number(4), R::Done);
    const auto s = only<nf::NurbsSurface>(*c);
    QVERIFY(nf::closest_point(s, {1, 1, 1}).distance < 1e-9);  // through the points
  }

  void ellipsoidAndParaboloid() {
    auto c = started("ellipsoid");
    c->point({0, 0, 0}, kTop);
    c->point({2, 0, 0}, kTop);
    QCOMPARE(c->number(1), R::Continue);
    QCOMPARE(c->number(0.5), R::Done);
    const auto e = only<nf::Shell>(*c);
    QVERIFY(std::abs(e.volume() - 4.0 / 3.0 * kPi * 2 * 1 * 0.5) < 1e-6);
    for (const auto& f : e.faces()) {
      for (const auto& p : f.surface().control_points()) QVERIFY(std::abs(p.x) <= 2 + 1e-9 && std::abs(p.z) <= 0.5 + 1e-9);
    }
    c = started("paraboloid");
    c->point({0, 0, 0}, kTop);
    c->point({0, 0, 1}, kTop);  // f = 1
    QCOMPARE(c->number(2), R::Done);
    const auto p = only<nf::NurbsSurface>(*c);
    for (double u : {0.1, 0.4, 0.8}) {
      for (double v : {0.2, 0.5, 0.9}) {
        const auto du = p.domain_u(), dv = p.domain_v();
        const nf::Vec3 q = p.evaluate(du[0] + u * (du[1] - du[0]), dv[0] + v * (dv[1] - dv[0]));
        QVERIFY(std::abs(q.z - (q.x * q.x + q.y * q.y) / 4.0) < 1e-12);  // exact
      }
    }
  }

  void drapeOverASphere() {
    auto c = started("drape", {make_entity(nf::make_sphere({0, 0, 0}, 1.0))});
    QVERIFY(c);
    QCOMPARE(c->number(13), R::Continue);  // 13 × 13 rays: one through the centre
    QCOMPARE(c->point({-2, -2, 0}, kTop), R::Continue);
    QCOMPARE(c->point({2, 2, 0}, kTop), R::Done);
    const auto s = only<nf::NurbsSurface>(*c);
    const auto du = s.domain_u(), dv = s.domain_v();
    const nf::Vec3 top = s.evaluate(0.5 * (du[0] + du[1]), 0.5 * (dv[0] + dv[1]));
    QVERIFY(nf::distance(top, {0, 0, 1}) < 1e-6);  // the ray through the centre meets the pole
    const nf::Vec3 corner = s.evaluate(du[0], dv[0]);
    QVERIFY(corner.z < 0.9 && corner.z > -1e-9);  // a missed ray: the lowest height hit
    c = started("drape", {make_entity(nf::make_sphere({0, 0, 0}, 1.0))});
    c->point({5, 5, 0}, kTop);
    QCOMPARE(c->point({6, 6, 0}, kTop), R::Rejected);  // nothing below
  }

  void heightfieldFromAnImage() {
    QImage image(8, 4, QImage::Format_Grayscale8);
    for (int x = 0; x < 8; ++x) {
      for (int y = 0; y < 4; ++y) image.setPixel(x, y, qRgb(x * 255 / 7, x * 255 / 7, x * 255 / 7));  // black → white
    }
    QTemporaryDir dir;
    const QString path = dir.filePath(QStringLiteral("ramp.png"));
    QVERIFY(image.save(path));
    auto c = create_command(QStringLiteral("heightfield"));
    QVERIFY(!c->fileFilter().isEmpty());
    c->setFile(path);
    c->point({0, 0, 0}, kTop);
    c->point({7, 3, 0}, kTop);
    QCOMPARE(c->number(2), R::Done);
    const auto s = only<nf::NurbsSurface>(*c);
    const auto du = s.domain_u(), dv = s.domain_v();
    QVERIFY(std::abs(s.evaluate(du[0], dv[0]).z) < 1e-6);        // black corner on the plane
    QVERIFY(std::abs(s.evaluate(du[1], dv[1]).z - 2.0) < 1e-6);  // white at the height
    QVERIFY(std::abs(s.evaluate(0.5 * (du[0] + du[1]), dv[0]).z - 1.0) < 0.05);  // a ramp
    c = create_command(QStringLiteral("heightfield"));
    c->setFile(dir.filePath(QStringLiteral("missing.png")));
    c->point({0, 0, 0}, kTop);
    c->point({1, 1, 0}, kTop);
    QCOMPARE(c->number(1), R::Rejected);
  }

  void developableLoft() {
    // a half circle and a skew line: the plain ruled surface is curved, the developable one not
    const nf::NurbsCurve arc = nf::make_arc_3pt({2, 0, 0}, {0, 2, 0}, {-2, 0, 0});
    const nf::NurbsCurve top = nf::make_line({1.5, 1, 2}, {-1, 0.5, 2});
    auto c = started("devloft", {make_entity(arc), make_entity(top)});
    QCOMPARE(c->finish(), R::Done);
    const auto dev = only<nf::NurbsSurface>(*c);
    const auto plain = nf::ruled(arc, top);
    double k_dev = 0, k_plain = 0;
    for (double u : {0.25, 0.5, 0.75}) {
      for (double v : {0.3, 0.7}) {
        auto at = [&](const nf::NurbsSurface& s) {
          const auto du = s.domain_u(), dv = s.domain_v();
          return std::abs(nf::curvature(s, du[0] + u * (du[1] - du[0]), dv[0] + v * (dv[1] - dv[0])).gaussian);
        };
        k_dev = std::max(k_dev, at(dev));
        k_plain = std::max(k_plain, at(plain));
      }
    }
    QVERIFY2(k_dev < 0.02 * k_plain, qPrintable(QStringLiteral("%1 vs %2").arg(k_dev).arg(k_plain)));
  }

  void aliases() {
    QCOMPARE(create_command(QStringLiteral("networksrf"))->id(), QStringLiteral("gordon"));
    QCOMPARE(create_command(QStringLiteral("birail"))->id(), QStringLiteral("sweep2"));
    QCOMPARE(create_command(QStringLiteral("extrudecrv"))->id(), QStringLiteral("extrude"));
  }
};

QTEST_GUILESS_MAIN(TestSurfaceCreate)
#include "test_surface_create.moc"
