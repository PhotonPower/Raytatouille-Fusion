// Editing curves (curve_edit_commands.cpp): Extend, Divide, Rebuild, Change degree, Flip, Close,
// Seam, knots, Smooth, Fair.
#include <QTest>
#include <cmath>
#include <numbers>
#include <nurbforge/nurbforge.hpp>

#include "commands/command.hpp"

using nfcad::commands::Command;
using nfcad::commands::create_command;
using nfcad::commands::PlaneFrame;
using nfcad::document::Entity;
using R = Command::Result;

namespace {

const PlaneFrame kTop{};

Entity entity(nfcad::document::Geometry g, nfcad::document::EntityId id = 1) {
  Entity e = nfcad::document::make_entity(std::move(g));
  e.id = id;
  return e;
}

std::unique_ptr<Command> started(const char* name, std::vector<Entity> sel) {
  auto c = create_command(QString::fromLatin1(name));
  if (!c || !c->begin(sel)) return nullptr;
  return c;
}

/// The curve the command put in place of entity 1.
nf::NurbsCurve replaced(Command& c) {
  const auto edit = c.takeEdit();
  return std::get<nf::NurbsCurve>(*edit.replace.back().second);
}

/// A wiggly cubic through the x axis.
nf::NurbsCurve wiggly() {
  std::vector<nf::Vec3> p;
  for (int i = 0; i <= 10; ++i) p.push_back({double(i), (i % 2 ? 0.3 : -0.3), 0});
  return nf::NurbsCurve::from_points(3, p);
}

}  // namespace

class TestCurveEdit : public QObject {
  Q_OBJECT
 private slots:
  void extendAtTheClickedEnd() {
    auto c = started("extendcrv", {entity(nf::make_line({0, 0, 0}, {2, 0, 0}))});
    QVERIFY(c);
    QCOMPARE(c->point({1.9, 0.1, 0}, kTop), R::Continue);  // near the end
    QVERIFY(!c->preview({3, 0, 0}, kTop).empty());
    QCOMPARE(c->number(1.5), R::Done);
    const auto e = replaced(*c);
    QVERIFY(nf::distance(e.evaluate(e.domain_end()), {3.5, 0, 0}) < 1e-9);
    QVERIFY(nf::distance(e.evaluate(e.domain_start()), {0, 0, 0}) < 1e-9);
    // an arc stays an arc
    c = started("extend", {entity(nf::make_circle({0, 0, 0}, {0, 0, 1}, 1.0).sub_curve(0.0, 0.25))});
    const auto arc = nf::make_circle({0, 0, 0}, {0, 0, 1}, 1.0).sub_curve(0.0, 0.25);
    c->point(nfcad::commands::Point3{arc.evaluate(0.0).x, arc.evaluate(0.0).y, 0}, kTop);
    QCOMPARE(c->number(0.5), R::Done);
    for (const auto& q : replaced(*c).sample(20)) QVERIFY(std::abs(std::hypot(q.x, q.y) - 1.0) < 1e-9);
  }

  void divideByCountAndLength() {
    const Entity line = entity(nf::make_line({0, 0, 0}, {10, 0, 0}));
    auto c = started("divide", {line});
    QCOMPARE(c->number(2.5), R::Rejected);
    QCOMPARE(c->number(4), R::Done);
    auto pts = c->takeEntities();
    QCOMPARE(pts.size(), std::size_t{5});
    QVERIFY(nf::distance(std::get<nf::Vec3>(*pts[1].geometry), {2.5, 0, 0}) < 1e-9);
    c = started("divlen", {line});
    QCOMPARE(c->number(3), R::Done);
    pts = c->takeEntities();
    QCOMPARE(pts.size(), std::size_t{4});  // 0, 3, 6, 9
    QVERIFY(nf::distance(std::get<nf::Vec3>(*pts[3].geometry), {9, 0, 0}) < 1e-9);
    // a closed curve: no point twice
    c = started("divide", {entity(nf::make_circle({0, 0, 0}, {0, 0, 1}, 1.0))});
    QCOMPARE(c->number(6), R::Done);
    QCOMPARE(c->takeEntities().size(), std::size_t{6});
  }

  void rebuildAndChangeDegree() {
    const Entity w = entity(wiggly());
    auto c = started("rebuild", {w});
    QCOMPARE(c->number(6), R::Continue);   // control points
    QCOMPARE(c->number(7), R::Rejected);   // degree 7 needs 8 points
    QCOMPARE(c->finish(), R::Done);        // degree 3
    const auto r = replaced(*c);
    QCOMPARE(r.num_control_points(), std::size_t{6});
    QCOMPARE(r.degree(), std::size_t{3});
    QVERIFY(c->message().contains(QStringLiteral("deviation")));
    c = started("changedegree", {w});
    QCOMPARE(c->number(5), R::Done);  // raised: the same shape
    const auto up = replaced(*c);
    QCOMPARE(up.degree(), std::size_t{5});
    for (double u : {0.1, 0.37, 0.8}) QVERIFY(nf::distance(up.evaluate(u), wiggly().evaluate(u)) < 1e-9);
    c = started("changedegree", {entity(nf::make_line({0, 0, 0}, {1, 1, 0}).elevate_degree(2))});
    QCOMPARE(c->number(1), R::Done);  // lowered: a straight cubic becomes a line exactly
    QCOMPARE(replaced(*c).degree(), std::size_t{1});
  }

  void flipCloseAndSeam() {
    auto c = started("flip", {entity(nf::make_line({0, 0, 0}, {1, 0, 0}))});
    QVERIFY(c && c->immediate());
    QCOMPARE(c->finish(), R::Done);
    const auto f = replaced(*c);
    QVERIFY(nf::distance(f.evaluate(f.domain_start()), {1, 0, 0}) < 1e-12);
    // a large gap: a closing segment; a tiny one: the end moves onto the start
    c = started("closecrv", {entity(nf::make_polyline({{0, 0, 0}, {2, 0, 0}, {2, 2, 0}}))});
    QCOMPARE(c->finish(), R::Done);
    const auto k = replaced(*c);
    QVERIFY(nf::distance(k.evaluate(k.domain_end()), {0, 0, 0}) < 1e-9);
    QVERIFY(std::abs(nf::arc_length(k) - (4 + 2 * std::sqrt(2.0))) < 1e-9);
    c = started("close", {entity(nf::make_polyline({{0, 0, 0}, {2, 0, 0}, {2, 2, 0}, {0, 2, 0}, {0, 0.01, 0}}))});
    QCOMPARE(c->finish(), R::Done);
    const auto m = replaced(*c);
    QCOMPARE(m.num_control_points(), std::size_t{5});  // no extra segment
    QVERIFY(nf::distance(m.evaluate(m.domain_end()), {0, 0, 0}) < 1e-12);
    // seam of a circle at (0, 1)
    QVERIFY(!started("seam", {entity(nf::make_line({0, 0, 0}, {1, 0, 0}))}));
    c = started("crvseam", {entity(nf::make_circle({0, 0, 0}, {0, 0, 1}, 1.0))});
    QCOMPARE(c->point({0, 1.2, 0}, kTop), R::Done);
    const auto s = replaced(*c);
    QVERIFY(nf::distance(s.evaluate(s.domain_start()), {0, 1, 0}) < 1e-9);
    QVERIFY(nf::distance(s.evaluate(s.domain_end()), {0, 1, 0}) < 1e-9);
    for (const auto& q : s.sample(30)) QVERIFY(std::abs(std::hypot(q.x, q.y) - 1.0) < 1e-9);
  }

  void insertAndRemoveKnots() {
    const nf::NurbsCurve w = wiggly();
    auto c = started("insertknot", {entity(w)});
    QCOMPARE(c->point({5.2, 0.4, 0}, kTop), R::Continue);
    QCOMPARE(c->finish(), R::Done);
    const auto more = replaced(*c);
    QCOMPARE(more.num_control_points(), w.num_control_points() + 1);
    for (double u : {0.2, 0.5, 0.9}) QVERIFY(nf::distance(more.evaluate(u), w.evaluate(u)) < 1e-9);  // same shape
    c = started("removeknot", {entity(w)});
    QCOMPARE(c->point({5, 0, 0}, kTop), R::Continue);
    QCOMPARE(c->finish(), R::Done);
    QCOMPARE(replaced(*c).num_control_points(), w.num_control_points() - 1);
    QVERIFY(!started("removeknot", {entity(w), entity(w, 2)}));  // one curve
  }

  void smoothAndFair() {
    const nf::NurbsCurve w = wiggly();
    auto c = started("smooth", {entity(w)});
    QCOMPARE(c->number(1.5), R::Rejected);
    QCOMPARE(c->finish(), R::Done);  // factor 0.5
    const auto s = replaced(*c);
    double before = 0, after = 0;
    for (std::size_t i = 1; i + 1 < w.num_control_points(); ++i) {
      before += std::abs(w.control_points()[i].y);
      after += std::abs(s.control_points()[i].y);
    }
    QVERIFY(after < 0.6 * before);  // the wiggles shrink
    QVERIFY(nf::distance(s.evaluate(s.domain_end()), w.evaluate(w.domain_end())) < 1e-12);  // ends kept
    c = started("fair", {entity(w)});
    QCOMPARE(c->number(0.05), R::Done);
    const auto f = replaced(*c);
    double worst = 0;
    for (const auto& p : f.sample(200)) worst = std::max(worst, nf::closest_point(w, p).distance);
    QVERIFY(worst <= 0.05 + 1e-9);  // within the tolerance
    QVERIFY(f.control_points()[5].y != w.control_points()[5].y);  // and changed
  }
};

QTEST_GUILESS_MAIN(TestCurveEdit)
#include "test_curve_edit.moc"
