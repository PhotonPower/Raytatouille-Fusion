// Solid operations and deformations (deform_commands.cpp).
#include <QTest>
#include <cmath>
#include <numbers>
#include <nurbforge/nurbforge.hpp>

#include "commands/command.hpp"
#include "kernel/geometry_ops.hpp"

using nfcad::commands::Command;
using nfcad::commands::create_command;
using nfcad::commands::GripSet;
using nfcad::commands::PlaneFrame;
using nfcad::document::Entity;
using nfcad::document::Geometry;
using R = Command::Result;

namespace {

const PlaneFrame kTop{};
constexpr double kPi = std::numbers::pi;

Entity entity(Geometry g, nfcad::document::EntityId id = 1) {
  Entity e = nfcad::document::make_entity(std::move(g));
  e.id = id;
  return e;
}

std::unique_ptr<Command> started(const char* name, std::vector<Entity> sel) {
  auto c = create_command(QString::fromLatin1(name));
  c->setViewPlane(kTop);
  if (!c->begin(sel)) return nullptr;
  return c;
}

Geometry replaced(Command& c) { return *c.takeEdit().replace.back().second; }

nf::Vec3 end_of(const Geometry& g) {
  const auto& c = std::get<nf::NurbsCurve>(g);
  return c.evaluate(c.domain_end());
}

}  // namespace

class TestDeform : public QObject {
  Q_OBJECT
 private slots:
  void bendALine() {
    auto c = started("bend", {entity(nf::make_line({0, 0, 0}, {4, 0, 0}))});
    c->point({0, 0, 0}, kTop);
    c->point({4, 0, 0}, kTop);
    QCOMPARE(c->point({0, 1, 0}, kTop), R::Continue);  // towards +y
    QCOMPARE(c->number(90), R::Done);                  // a quarter circle of radius 8/π
    const Geometry g = replaced(*c);
    const double r = 8 / kPi;
    QVERIFY(nf::distance(end_of(g), {r, r, 0}) < 1e-9);
    const auto& arc = std::get<nf::NurbsCurve>(g);
    for (const auto& p : arc.sample(20)) QVERIFY(std::abs(nf::distance(p, {0, r, 0}) - r) < 2e-3);  // on the circle
  }

  void twistAndTaper() {
    auto c = started("twist", {entity(nf::make_line({0, 1, 0}, {4, 1, 0}))});
    c->point({0, 0, 0}, kTop);
    c->point({4, 0, 0}, kTop);
    QCOMPARE(c->number(90), R::Done);
    QVERIFY(nf::distance(end_of(replaced(*c)), {4, 0, 1}) < 1e-9);
    c = started("taper", {entity(nf::make_line({0, 1, 0}, {4, 1, 0}))});
    c->point({0, 0, 0}, kTop);
    c->point({4, 0, 0}, kTop);
    QCOMPARE(c->number(2), R::Done);
    QVERIFY(nf::distance(end_of(replaced(*c)), {4, 2, 0}) < 1e-9);
  }

  void shearAndStretchAreExact() {
    const Entity box = entity(nf::make_box({0, 0, 0}, {2, 2, 2}));
    auto c = started("shear", {box});
    c->point({0, 0, 0}, kTop);
    c->point({1, 0, 0}, kTop);
    QCOMPARE(c->number(45), R::Done);
    const auto sheared = std::get<nf::Shell>(replaced(*c));
    QVERIFY(sheared.is_closed());
    QVERIFY(std::abs(sheared.volume() - 8.0) < 1e-9);  // shearing keeps the volume
    c = started("shear", {entity(nf::Vec3{1, 1, 0})});
    c->point({0, 0, 0}, kTop);
    c->point({1, 0, 0}, kTop);
    c->number(45);
    QVERIFY(nf::distance(std::get<nf::Vec3>(replaced(*c)), {2, 1, 0}) < 1e-12);
    c = started("stretch", {box});
    c->point({0, 0, 0}, kTop);
    c->point({2, 0, 0}, kTop);
    QVERIFY(!c->preview({4, 0, 0}, kTop).empty());
    QCOMPARE(c->point({4, 0, 0}, kTop), R::Done);  // twice as long in x
    QVERIFY(std::abs(std::get<nf::Shell>(replaced(*c)).volume() - 16.0) < 1e-9);
  }

  void maelstrom() {
    auto c = started("maelstrom", {entity(nf::Vec3{1, 0, 0})});
    c->point({0, 0, 0}, kTop);
    QCOMPARE(c->number(2), R::Continue);   // radius
    QCOMPARE(c->number(90), R::Done);      // half way out: 45°
    const double h = std::sqrt(0.5);
    QVERIFY(nf::distance(std::get<nf::Vec3>(replaced(*c)), {h, h, 0}) < 1e-12);
  }

  void booleanSplit() {
    auto c = started("booleansplit", {entity(nf::make_box({0, 0, 0}, {2, 2, 2}), 1),
                                      entity(nf::make_box({1, -1, -1}, {2, 4, 4}), 2)});
    QVERIFY(c);
    QCOMPARE(c->finish(), R::Done);
    const auto edit = c->takeEdit();
    QCOMPARE(edit.add.size(), std::size_t{2});
    QCOMPARE(edit.remove, std::vector<nfcad::document::EntityId>{1});  // the cutter stays
    for (const auto& part : edit.add) QVERIFY(std::abs(std::get<nf::Shell>(*part.geometry).volume() - 4.0) < 1e-6);
  }

  void shellAHemisphere() {
    const nf::Shell upper = nf::split(nf::make_sphere({0, 0, 0}, 2.0), nf::Plane{{0, 0, 0}, {0, 0, 1}}).first;
    QVERIFY(upper.is_closed());
    int flat = -1;
    for (std::size_t i = 0; i < upper.faces().size(); ++i) {
      if (upper.faces()[i].label() == "cut") flat = static_cast<int>(i);
    }
    QVERIFY(flat >= 0);
    auto c = create_command(QStringLiteral("shell"));
    c->setFaces({GripSet{3, std::make_shared<const Geometry>(upper), {flat}}});
    QVERIFY(c->begin({}));
    QCOMPARE(c->number(0.2), R::Done);
    const auto cup = std::get<nf::Shell>(replaced(*c));
    QVERIFY(cup.is_closed());
    QVERIFY(std::abs(std::abs(cup.volume()) - 2.0 / 3.0 * kPi * (8.0 - 1.8 * 1.8 * 1.8)) < 1e-3);
  }
};

QTEST_GUILESS_MAIN(TestDeform)
#include "test_deform.moc"
