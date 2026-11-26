// Transitions between surfaces (surface_blend_commands.cpp).
#include <QTest>
#include <cmath>
#include <numbers>
#include <nurbforge/nurbforge.hpp>

#include "commands/command.hpp"

using nfcad::commands::Command;
using nfcad::commands::create_command;
using nfcad::commands::GripSet;
using nfcad::commands::PlaneFrame;
using nfcad::document::Entity;
using R = Command::Result;

namespace {

const PlaneFrame kTop{};
constexpr double kPi = std::numbers::pi;

Entity entity(nfcad::document::Geometry g, nfcad::document::EntityId id) {
  Entity e = nfcad::document::make_entity(std::move(g));
  e.id = id;
  return e;
}

Entity rect(nf::Vec3 o, nf::Vec3 u, nf::Vec3 v, nfcad::document::EntityId id) {
  return entity(nf::make_rectangle(o, u, v), id);
}

std::unique_ptr<Command> started(const char* name, std::vector<Entity> sel) {
  auto c = create_command(QString::fromLatin1(name));
  c->setViewPlane(kTop);
  if (!c->begin(sel)) return nullptr;
  return c;
}

nf::NurbsSurface edge_of_u(const nf::NurbsSurface& s) { return s; }

}  // namespace

class TestSurfaceBlend : public QObject {
  Q_OBJECT
 private slots:
  void blendBetweenPlates() {
    auto c = started("blendsrf", {rect({0, 0, 0}, {1, 0, 0}, {0, 1, 0}, 1), rect({2, 0, 1}, {1, 0, 0}, {0, 1, 0}, 2)});
    QVERIFY(c);
    QVERIFY(!c->preview({1, 0.5, 0}, kTop).empty());
    QCOMPARE(c->point({1, 0.5, 0}, kTop), R::Continue);  // the edge x = 1 of the first
    QCOMPARE(c->point({2, 0.5, 1}, kTop), R::Done);      // the edge x = 2 of the second
    const auto made = c->takeEntities();
    const auto& b = std::get<nf::NurbsSurface>(*made.front().geometry);
    // its ends are the two edges
    const auto du = b.domain_u(), dv = b.domain_v();
    QVERIFY(std::abs(b.evaluate(0.5 * (du[0] + du[1]), dv[0]).x - 1) < 1e-9);
    QVERIFY(std::abs(b.evaluate(0.5 * (du[0] + du[1]), dv[1]).x - 2) < 1e-9);
    QVERIFY(std::abs(b.evaluate(0.5 * (du[0] + du[1]), dv[1]).z - 1) < 1e-9);
  }

  void matchMovesTheEdge() {
    auto c = started("matchsrf", {rect({0, 0, 0}, {1, 0, 0}, {0, 1, 0}, 1), rect({1.2, 0, 0.3}, {1, 0, 0}, {0, 1, 0}, 2)});
    QCOMPARE(c->number(0), R::Continue);
    c->point({1, 0.5, 0}, kTop);
    QCOMPARE(c->point({1.2, 0.5, 0.3}, kTop), R::Done);
    const auto edit = c->takeEdit();
    QCOMPARE(edit.replace.size(), std::size_t{1});
    const auto& m = std::get<nf::NurbsSurface>(*edit.replace[0].second);
    QVERIFY(nf::closest_point(m, {1.2, 0.5, 0.3}).distance < 1e-9);  // its edge now on the target's
    QVERIFY(nf::closest_point(m, {0, 0.5, 0}).distance < 1e-9);      // the far edge stays
  }

  void mergeSurfacesAndFaces() {
    // the second plate runs the other way: merged, its inputs removed
    auto c = started("mergesrf", {rect({0, 0, 0}, {1, 0, 0}, {0, 1, 0}, 1), rect({2, 1, 0}, {-1, 0, 0}, {0, -1, 0}, 2)});
    QCOMPARE(c->finish(), R::Done);
    const auto edit = c->takeEdit();
    QCOMPARE(edit.remove.size(), std::size_t{2});
    QVERIFY(std::abs(nf::area(std::get<nf::NurbsSurface>(*edit.add.front().geometry)) - 2.0) < 1e-9);
    QVERIFY(!started("mergesrf", {rect({0, 0, 0}, {1, 0, 0}, {0, 1, 0}, 1), rect({3, 0, 0}, {1, 0, 0}, {0, 1, 0}, 2)})
                 ->finish() == R::Done);
    // two coplanar faces sewn into an open shell merge into one
    const nf::Shell two = nf::Shell::sew({nf::TrimmedSurface(nf::make_rectangle({0, 0, 0}, {1, 0, 0}, {0, 1, 0})),
                                          nf::TrimmedSurface(nf::make_rectangle({1, 0, 0}, {1, 0, 0}, {0, 1, 0}))},
                                         1e-6);
    c = started("merge", {entity(two, 3)});
    QVERIFY(c);
    QCOMPARE(c->finish(), R::Done);
    QCOMPARE(std::get<nf::Shell>(*c->takeEdit().replace[0].second).faces().size(), std::size_t{1});
    QVERIFY(!started("merge", {entity(nf::make_box({0, 0, 0}, {1, 1, 1}), 4)}));  // nothing to merge
  }

  void filletAndChamferEdges() {
    const nf::Shell box = nf::make_box({0, 0, 0}, {1, 1, 1});
    const std::size_t e = nf::edges_between(box, "top", "front").front();
    auto c = create_command(QStringLiteral("filletedge"));
    QVERIFY(c->usesEdges());
    QVERIFY(!c->begin({}));  // no edges picked
    c->setEdges({GripSet{9, std::make_shared<const nfcad::document::Geometry>(box), {static_cast<int>(e)}}});
    QVERIFY(c->begin({}));
    QCOMPARE(c->number(0.2), R::Done);
    const auto f = std::get<nf::Shell>(*c->takeEdit().replace[0].second);
    QVERIFY(f.is_closed());
    QVERIFY(std::abs(f.volume() - (1.0 - (1 - kPi / 4) * 0.04)) < 1e-5);
    c = create_command(QStringLiteral("bevel"));
    c->setEdges({GripSet{9, std::make_shared<const nfcad::document::Geometry>(box), {static_cast<int>(e)}}});
    QVERIFY(c->begin({}));
    QCOMPARE(c->number(0.2), R::Done);
    QVERIFY(std::abs(std::get<nf::Shell>(*c->takeEdit().replace[0].second).volume() - (1.0 - 0.02)) < 1e-6);
    // variable: 0.1 at one end, 0.3 at the other
    c = create_command(QStringLiteral("variableblend"));
    c->setEdges({GripSet{9, std::make_shared<const nfcad::document::Geometry>(box), {static_cast<int>(e)}}});
    QVERIFY(c->begin({}));
    const nf::NurbsCurve& edge = box.edges()[e].curve;
    const nf::Vec3 a = edge.evaluate(edge.domain_start()), b = edge.evaluate(edge.domain_end());
    QCOMPARE(c->point({a.x, a.y, a.z}, kTop), R::Continue);
    QCOMPARE(c->number(0.1), R::Continue);
    QCOMPARE(c->point({b.x, b.y, b.z}, kTop), R::Continue);
    QCOMPARE(c->number(0.3), R::Continue);
    QCOMPARE(c->finish(), R::Done);
    const auto v = std::get<nf::Shell>(*c->takeEdit().replace[0].second);
    QVERIFY(v.is_closed());
    QVERIFY(v.volume() < 1.0 - (1 - kPi / 4) * 0.01 && v.volume() > 1.0 - (1 - kPi / 4) * 0.09);
  }

  void connectTwoPlates() {
    // a horizontal plate up to x = 1 and a vertical one at x = 2 reaching down to z = -1
    auto c = started("connectsrf", {rect({0, 0, 0}, {1, 0, 0}, {0, 1, 0}, 1), rect({2, 0, -1}, {0, 1, 0}, {0, 0, 1.5}, 2)});
    QVERIFY(c);
    QCOMPARE(c->finish(), R::Done);
    const auto edit = c->takeEdit();
    QCOMPARE(edit.replace.size(), std::size_t{2});
    const auto& a = std::get<nf::TrimmedSurface>(*edit.replace[0].second);
    const auto& b = std::get<nf::TrimmedSurface>(*edit.replace[1].second);
    QVERIFY(std::abs(a.area() - 2.0) < 1e-6);  // extended to x = 2
    QVERIFY(std::abs(b.area() - 1.0) < 1e-6);  // cut at z = 0, the lower part kept
  }

  void tweenSurfaces() {
    auto c = started("tweensrf", {rect({0, 0, 0}, {1, 0, 0}, {0, 1, 0}, 1), rect({0, 0, 2}, {1, 0, 0}, {0, 1, 0}, 2)});
    QCOMPARE(c->finish(), R::Done);
    const auto made = c->takeEntities();
    QCOMPARE(made.size(), std::size_t{1});
    const auto& t = std::get<nf::NurbsSurface>(*made.front().geometry);
    for (const auto& p : t.control_points()) QVERIFY(std::abs(p.z - 1.0) < 1e-12);
    (void)edge_of_u(t);
  }
};

QTEST_GUILESS_MAIN(TestSurfaceBlend)
#include "test_surface_blend.moc"
