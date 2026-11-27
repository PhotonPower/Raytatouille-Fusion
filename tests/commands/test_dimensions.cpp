// Dimensions (document/dimension.cpp, commands/dimension_commands.cpp).
#include <QTest>
#include <cmath>
#include <numbers>
#include <nurbforge/nurbforge.hpp>

#include "commands/command.hpp"
#include "document/dimension.hpp"
#include "kernel/geometry_ops.hpp"

using nfcad::commands::Command;
using nfcad::commands::create_command;
using nfcad::commands::PlaneFrame;
using nfcad::commands::Point3;
using nfcad::document::DimensionKind;
using nfcad::document::dimension_view;
using nfcad::document::Entity;
using nfcad::document::Geometry;
using R = Command::Result;

namespace {

const PlaneFrame kTop{};

Entity entity(Geometry g, nfcad::document::EntityId id = 1) {
  Entity e = nfcad::document::make_entity(std::move(g));
  e.id = id;
  return e;
}

std::unique_ptr<Command> started(const char* name, std::vector<Entity> sel = {}) {
  auto c = create_command(QString::fromLatin1(name));
  c->setViewPlane(kTop);
  if (!c->begin(sel)) {
    qWarning("%s: %s", name, qPrintable(c->message()));
    return nullptr;
  }
  return c;
}

/// Clicks the points; the last one must finish the command. Returns the new dimension.
Entity clicked(Command& c, const std::vector<Point3>& pts) {
  for (std::size_t i = 0; i < pts.size(); ++i) {
    const R r = c.point(pts[i], kTop);
    if (r != (i + 1 == pts.size() ? R::Done : R::Continue)) qWarning("point %zu: %s", i, qPrintable(c.message()));
  }
  auto made = c.takeEntities();
  return made.empty() ? Entity{} : made.front();
}

double value(const Entity& e) { return dimension_view(e) ? dimension_view(e)->value : -1.0; }
QString text(const Entity& e) { return dimension_view(e) ? dimension_view(e)->text : QString(); }

}  // namespace

class TestDimensions : public QObject {
  Q_OBJECT
 private slots:
  void formatting() {
    QCOMPARE(nfcad::document::format_length(10.0), QStringLiteral("10"));
    QCOMPARE(nfcad::document::format_length(12.5), QStringLiteral("12.5"));
    QCOMPARE(nfcad::document::format_length(3.14159), QStringLiteral("3.14"));
    QCOMPARE(nfcad::document::format_length(-0.001), QStringLiteral("0"));
    QCOMPARE(nfcad::document::format_angle(45.04), QStringLiteral("45°"));
  }

  void linear() {
    auto c = started("dim");
    // pulled up: horizontal, measures dx only
    Entity d = clicked(*c, {{0, 0, 0}, {3, 4, 0}, {1, 6, 0}});
    QCOMPARE(*nfcad::document::dimension_kind(d), DimensionKind::Linear);
    QVERIFY(std::abs(value(d) - 3.0) < 1e-12);
    QCOMPARE(text(d), QStringLiteral("3"));
    // pulled sideways: vertical
    c = started("dimlinear");
    d = clicked(*c, {{0, 0, 0}, {3, 4, 0}, {6, 1, 0}});
    QVERIFY(std::abs(value(d) - 4.0) < 1e-12);
    // the dimension line passes through the location
    const auto& p = std::get<nf::NurbsCurve>(*d.geometry).control_points();
    QVERIFY(std::abs(p[1].x - 6.0) < 1e-12 && std::abs(p[2].x - 6.0) < 1e-12);
  }

  void alignedFollowsTransforms() {
    auto c = started("dimaligned");
    Entity d = clicked(*c, {{0, 0, 0}, {3, 4, 0}, {0, 2, 0}});
    QVERIFY(std::abs(value(d) - 5.0) < 1e-12);
    // scaled by 2 (as Scale does: the control points): the value doubles
    d.geometry = std::make_shared<const Geometry>(nfcad::kernel::transformed(*d.geometry, nf::Transform::scaling({0, 0, 0}, 2.0)));
    QVERIFY(std::abs(value(d) - 10.0) < 1e-9);
    QCOMPARE(text(d), QStringLiteral("10"));
  }

  void angle() {
    auto c = started("dimangle");
    // 60° between the x axis and a line at 60°; location inside: 60°
    const double s = std::sqrt(3.0) / 2;
    Entity d = clicked(*c, {{0, 0, 0}, {2, 0, 0}, {1, 2 * s, 0}, {1.5, 0.5, 0}});
    QVERIFY2(std::abs(value(d) - 60.0) < 1e-9, qPrintable(QString::number(value(d))));
    QCOMPARE(text(d), QStringLiteral("60°"));
    // location on the other side of the second line: the supplementary angle
    c = started("dimangle");
    d = clicked(*c, {{0, 0, 0}, {2, 0, 0}, {1, 2 * s, 0}, {-1, 0.5, 0}});
    QVERIFY(std::abs(value(d) - 120.0) < 1e-9);
    // collinear points are refused
    c = started("dimangle");
    QCOMPARE(c->point({0, 0, 0}, kTop), R::Continue);
    QCOMPARE(c->point({1, 0, 0}, kTop), R::Continue);
    QCOMPARE(c->point({2, 0, 0}, kTop), R::Rejected);
  }

  void circles() {
    const Entity circle = entity(nf::make_circle({1, 1, 0}, {0, 0, 1}, 2.0));
    auto c = started("dimradius", {circle});
    Entity d = clicked(*c, {{5, 1, 0}});
    QVERIFY(std::abs(value(d) - 2.0) < 1e-9);
    QCOMPARE(text(d), QStringLiteral("R2"));
    c = started("dimdiameter", {circle});
    d = clicked(*c, {{1, 0, 0}});
    QVERIFY(std::abs(value(d) - 4.0) < 1e-9);
    QCOMPARE(text(d), QStringLiteral("⌀4"));
    // a quarter arc of radius 2: length pi
    const Entity arc = entity(nf::make_arc_3pt({2, 0, 0}, {std::sqrt(2.0), std::sqrt(2.0), 0}, {0, 2, 0}));
    c = started("dimarclength", {arc});
    d = clicked(*c, {{3, 3, 0}});
    QVERIFY2(std::abs(value(d) - std::numbers::pi) < 1e-9, qPrintable(QString::number(value(d))));
    QVERIFY(!started("dimarclength", {circle}));  // a full circle has no arc length
    QVERIFY(!started("dimradius", {entity(nf::make_line({0, 0, 0}, {1, 0, 0}))}));
  }

  void ordinate() {
    auto c = started("dimordinate");
    Entity d = clicked(*c, {{3, 4, 0}, {3.2, 7, 0}});  // leader up: the x coordinate
    QVERIFY(std::abs(value(d) - 3.0) < 1e-12);
    QCOMPARE(text(d), QStringLiteral("X 3"));
    c = started("dimordinate");
    d = clicked(*c, {{3, 4, 0}, {6, 4.5, 0}});
    QCOMPARE(text(d), QStringLiteral("Y 4"));
  }

  void leaderAndText() {
    auto c = started("leader");
    QCOMPARE(c->point({0, 0, 0}, kTop), R::Continue);
    QCOMPARE(c->finish(), R::Cancelled);  // one point: nothing
    c = started("leader");
    QCOMPARE(c->point({0, 0, 0}, kTop), R::Continue);
    QCOMPARE(c->point({2, 1, 0}, kTop), R::Continue);
    QVERIFY(!c->wantsText());
    QCOMPARE(c->finish(), R::Continue);
    QVERIFY(c->wantsText());
    QCOMPARE(c->text(QStringLiteral("Bore H7")), R::Done);
    Entity leader = c->takeEntities().front();
    leader.id = 7;
    QCOMPARE(text(leader), QStringLiteral("Bore H7"));
    QCOMPARE(dimension_view(leader)->arrows.size(), std::size_t{1});

    // DimText: replaces the value, "<>" keeps it; Enter: the value again
    Entity d = clicked(*started("dimaligned"), {{0, 0, 0}, {4, 0, 0}, {0, 1, 0}});
    d.id = 8;
    c = started("dimtext", {d, leader});
    QVERIFY(c && c->wantsText());
    QCOMPARE(c->text(QStringLiteral("<> ±0.1")), R::Done);
    auto edit = c->takeEdit();
    QCOMPARE(edit.attributes.size(), std::size_t{2});
    d.attributes = edit.attributes[0].second;
    QCOMPARE(text(d), QStringLiteral("4 ±0.1"));
    c = started("dimtext", {d, leader});
    QCOMPARE(c->finish(), R::Done);
    edit = c->takeEdit();
    QCOMPARE(edit.attributes.size(), std::size_t{1});  // the leader keeps its text
    d.attributes = edit.attributes[0].second;
    QCOMPARE(text(d), QStringLiteral("4"));
    QVERIFY(!started("dimtext", {entity(nf::make_line({0, 0, 0}, {1, 0, 0}))}));
  }

  void notADimension() {
    QVERIFY(!dimension_view(entity(nf::make_line({0, 0, 0}, {1, 0, 0}))));
    // a dimension whose points no longer fit its kind (e.g. rebuilt) is drawn as a plain curve
    Entity d = entity(nf::make_polyline({{0, 0, 0}, {1, 0, 0}}));
    d.attributes.insert(QString::fromLatin1(nfcad::document::kDimensionKey), QStringLiteral("aligned"));
    QVERIFY(!dimension_view(d));
  }
};

QTEST_GUILESS_MAIN(TestDimensions)
#include "test_dimensions.moc"
