// Editing surfaces (surface_edit_commands.cpp): areas and volumes against closed forms.
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

double area(const Geometry& g) {
  double a = 0;
  for (const auto& f : nfcad::kernel::faces_of(g)) a += f.area();
  return a;
}

nf::TrimmedSurface holed() {  // a 4 × 4 square with a hole of radius 1
  return nfcad::kernel::planar_faces({nf::make_rectangle_curve({0, 0, 0}, {4, 0, 0}, {0, 4, 0}),
                                      nf::make_circle({2, 2, 0}, {0, 0, 1}, 1.0)})
      .front();
}

}  // namespace

class TestSurfaceEdit : public QObject {
  Q_OBJECT
 private slots:
  void untrim() {
    auto c = started("untrim", {entity(holed())});
    QVERIFY(c);
    QCOMPARE(c->point({3.1, 2, 0}, kTop), R::Done);  // near the hole
    QVERIFY(std::abs(area(replaced(*c)) - 16.0) < 1e-6);
    c = started("untrim", {entity(holed())});
    QCOMPARE(c->finish(), R::Done);  // every trim: the plane under it
    const Geometry g = replaced(*c);
    QVERIFY(std::holds_alternative<nf::NurbsSurface>(g));
    QVERIFY(area(g) > 16.0);
  }

  void extractFaces() {
    const nf::Shell box = nf::make_box({0, 0, 0}, {1, 1, 1});
    auto c = create_command(QStringLiteral("extractsrf"));
    QVERIFY(c->usesFaces());
    QVERIFY(!c->begin({}));
    c->setFaces({GripSet{5, std::make_shared<const Geometry>(box), {0, 2}}});
    QVERIFY(c->begin({}));
    QCOMPARE(c->finish(), R::Done);
    const auto edit = c->takeEdit();
    QCOMPARE(edit.add.size(), std::size_t{2});
    const auto& rest = std::get<nf::Shell>(*edit.replace[0].second);
    QCOMPARE(rest.faces().size(), std::size_t{4});
    QVERIFY(!rest.is_closed());
  }

  void shrinkToTheTrim() {
    auto c = started("shrink", {entity(holed())});
    QCOMPARE(c->finish(), R::Done);
    const auto f = std::get<nf::TrimmedSurface>(replaced(*c));
    QVERIFY(std::abs(nf::area(f.surface()) - 16.0) < 1e-9);  // the surface now just holds the trim
    QVERIFY(std::abs(f.area() - (16.0 - kPi)) < 1e-6);      // the face is unchanged
  }

  void extendSurface() {
    auto c = started("extendsrf", {entity(nf::make_rectangle({0, 0, 0}, {2, 0, 0}, {0, 1, 0}))});
    QVERIFY(!c->preview({2, 0.5, 0}, kTop).empty());
    QCOMPARE(c->point({2.05, 0.5, 0}, kTop), R::Continue);  // the edge x = 2
    QCOMPARE(c->number(1), R::Done);
    QVERIFY(std::abs(area(replaced(*c)) - 3.0) < 1e-9);
    QVERIFY(!started("extendsrf", {entity(holed())}));  // trimmed
  }

  void rebuildAndDegree() {
    auto c = started("rebuildsrf", {entity(nf::make_rectangle({0, 0, 0}, {2, 0, 0}, {0, 1, 0}))});
    QCOMPARE(c->number(5), R::Continue);
    QCOMPARE(c->number(6), R::Done);
    const auto r = std::get<nf::NurbsSurface>(replaced(*c));
    QCOMPARE(r.num_u(), std::size_t{5});
    QCOMPARE(r.num_v(), std::size_t{6});
    c = started("rebuilduv", {entity(r)});
    QCOMPARE(c->number(2), R::Continue);  // v
    QCOMPARE(c->number(8), R::Done);
    const auto uv = std::get<nf::NurbsSurface>(replaced(*c));
    QCOMPARE(uv.num_u(), std::size_t{5});  // kept
    QCOMPARE(uv.num_v(), std::size_t{8});
    c = started("changedegreesrf", {entity(nf::make_rectangle({0, 0, 0}, {2, 0, 0}, {0, 1, 0}))});
    QCOMPARE(c->number(3), R::Continue);
    QCOMPARE(c->finish(), R::Done);
    const auto d = std::get<nf::NurbsSurface>(replaced(*c));
    QCOMPARE(d.degree_u(), std::size_t{3});
    QCOMPARE(d.degree_v(), std::size_t{3});
    QVERIFY(std::abs(nf::area(d) - 2.0) < 1e-9);  // the same surface
  }

  void slabs() {
    // an open line: a wall 4 long, 0.5 thick, 2 high
    auto c = started("slab", {entity(nf::make_line({0, 0, 0}, {4, 0, 0}))});
    QCOMPARE(c->number(0.5), R::Continue);
    QCOMPARE(c->point({2, 1, 0}, kTop), R::Continue);  // left of the line
    const auto r1 = c->number(2);
    QVERIFY2(r1 == R::Done, qPrintable(c->message()));
    auto made = c->takeEntities();
    QVERIFY(std::abs(std::get<nf::Shell>(*made.front().geometry).volume() - 4.0) < 1e-6);
    // a circle: a ring outside it
    c = started("slab", {entity(nf::make_circle({0, 0, 0}, {0, 0, 1}, 2.0))});
    c->number(0.5);
    QCOMPARE(c->point({3, 0, 0}, kTop), R::Continue);
    const auto r2 = c->number(1);
    QVERIFY2(r2 == R::Done, qPrintable(c->message()));
    made = c->takeEntities();
    QVERIFY(std::abs(std::abs(std::get<nf::Shell>(*made.front().geometry).volume()) - kPi * (2.5 * 2.5 - 4.0)) < 1e-4);
  }

  void thickenAndHollow() {
    auto c = started("thicken", {entity(nf::make_rectangle({0, 0, 0}, {2, 0, 0}, {0, 1, 0}))});
    QCOMPARE(c->number(0.5), R::Done);
    const auto t = std::get<nf::Shell>(replaced(*c));
    QVERIFY(t.is_closed());
    QVERIFY(std::abs(t.volume() - 1.0) < 1e-6);
    c = started("makehollow", {entity(nf::make_sphere({0, 0, 0}, 2.0))});
    QVERIFY(c);
    QCOMPARE(c->number(0.5), R::Done);
    const auto h = std::get<nf::Shell>(replaced(*c));
    QVERIFY(std::abs(h.volume() - 4.0 / 3.0 * kPi * (8.0 - 1.5 * 1.5 * 1.5)) < 1e-3);
    QVERIFY(!started("makehollow", {entity(nf::make_rectangle({0, 0, 0}, {1, 0, 0}, {0, 1, 0}))}));  // not closed
  }
};

QTEST_GUILESS_MAIN(TestSurfaceEdit)
#include "test_surface_edit.moc"
