// Curves from other geometry (derived_curve_commands.cpp): Project, Pull, Section, Contour,
// Duplicate edge / border, isocurves, wireframe, offset on surface, Curve Boolean.
#include <QTest>
#include <cmath>
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

std::vector<nf::NurbsCurve> curves(const std::vector<Entity>& made) {
  std::vector<nf::NurbsCurve> out;
  for (const Entity& e : made) out.push_back(std::get<nf::NurbsCurve>(*e.geometry));
  return out;
}

/// Bounding box of the sampled curves: {min, max}.
std::pair<nf::Vec3, nf::Vec3> box(const std::vector<nf::NurbsCurve>& cs) {
  nf::Vec3 lo{1e300, 1e300, 1e300}, hi{-1e300, -1e300, -1e300};
  for (const auto& c : cs) {
    for (const auto& p : c.sample(200)) {
      lo = {std::min(lo.x, p.x), std::min(lo.y, p.y), std::min(lo.z, p.z)};
      hi = {std::max(hi.x, p.x), std::max(hi.y, p.y), std::max(hi.z, p.z)};
    }
  }
  return {lo, hi};
}

double length(const std::vector<nf::NurbsCurve>& cs) {
  double l = 0;
  for (const auto& c : cs) l += nf::arc_length(c);
  return l;
}

std::unique_ptr<Command> started(const char* name, std::vector<Entity> sel) {
  auto c = create_command(QString::fromLatin1(name));
  c->setViewPlane(kTop);
  if (!c->begin(sel)) return nullptr;
  return c;
}

Entity square(double x0, double y0, double a) {
  return make_entity(nf::make_rectangle_curve({x0, y0, 0}, {a, 0, 0}, {0, a, 0}));
}

}  // namespace

class TestDerivedCurves : public QObject {
  Q_OBJECT
 private slots:
  void projectAlongTheViewAndPull() {
    const Entity plate = make_entity(nf::make_rectangle({-5, -5, 0}, {10, 0, 0}, {0, 10, 0}));
    const Entity line = make_entity(nf::make_line({-1, 0, 3}, {2, 1, 4}));
    for (const char* name : {"project", "pull"}) {
      auto c = started(name, {line, plate});
      QVERIFY(c && c->immediate());
      QCOMPARE(c->finish(), R::Done);
      const auto made = curves(c->takeEntities());
      QCOMPARE(made.size(), std::size_t{1});
      QVERIFY(nf::distance(made[0].evaluate(made[0].domain_start()), {-1, 0, 0}) < 1e-6);
      QVERIFY(nf::distance(made[0].evaluate(made[0].domain_end()), {2, 1, 0}) < 1e-6);
    }
    QVERIFY(!started("project", {line}));  // nothing to project onto
  }

  void sectionAndContourOfABox() {
    const Entity box_ = make_entity(nf::make_box({0, 0, 0}, {1, 2, 3}));
    auto c = started("section", {box_});
    QVERIFY(c);
    QCOMPARE(c->point({0.5, -1, 0}, kTop), R::Continue);
    QCOMPARE(c->point({0.5, 5, 0}, kTop), R::Done);  // the plane x = 0.5
    const auto loop = curves(c->takeEntities());
    QCOMPARE(loop.size(), std::size_t{1});            // one closed loop
    QVERIFY(std::abs(length(loop) - 10.0) < 1e-6);    // 2 + 3 + 2 + 3
    const nf::NurbsCurve& l = loop[0];
    QVERIFY(nf::distance(l.evaluate(l.domain_start()), l.evaluate(l.domain_end())) < 1e-6);
    // contours along z every 1.2 from z = 0.1: z = 0.1, 1.3, 2.5
    c = started("contour", {box_});
    c->point({0, 0, 0.1}, kTop);
    c->point({0, 0, 1.1}, kTop);
    QCOMPARE(c->number(1.2), R::Done);
    const auto rings = curves(c->takeEntities());
    QCOMPARE(rings.size(), std::size_t{3});
    QVERIFY(std::abs(length(rings) - 18.0) < 1e-6);  // 3 × (1 + 2 + 1 + 2)
  }

  void duplicateBorderAndEdge() {
    const Entity plate = make_entity(nf::make_rectangle({0, 0, 0}, {2, 0, 0}, {0, 1, 0}));
    auto c = started("dupborder", {plate});
    QVERIFY(c);
    QCOMPARE(c->finish(), R::Done);
    const auto border = curves(c->takeEntities());
    QCOMPARE(border.size(), std::size_t{1});
    QVERIFY(std::abs(length(border) - 6.0) < 1e-9);
    // a picked edge arrives as its curve (kernel::part_of), Duplicate edge keeps it
    const nf::Shell b = nf::make_box({0, 0, 0}, {1, 1, 1});
    const auto edge = nfcad::kernel::part_of(b, {nfcad::document::SubElement::Kind::Edge, 0});
    QVERIFY(edge && std::holds_alternative<nf::NurbsCurve>(*edge));
    QVERIFY(!nfcad::kernel::part_of(b, {nfcad::document::SubElement::Kind::Edge, 999}));
    const auto face = nfcad::kernel::part_of(b, {nfcad::document::SubElement::Kind::Face, 2});
    QVERIFY(face && std::holds_alternative<nf::TrimmedSurface>(*face));
    c = started("dupedge", {make_entity(*edge)});
    QVERIFY(c);
    QCOMPARE(c->finish(), R::Done);
    QCOMPARE(c->takeEntities().size(), std::size_t{1});
    QVERIFY(!started("dupedge", {make_entity(b)}));  // a whole solid: pick its edges
  }

  void isocurvesAndWireframe() {
    const Entity plate = make_entity(nf::make_rectangle({0, 0, 0}, {4, 0, 0}, {0, 2, 0}));
    auto c = started("iso", {plate});
    QVERIFY(c);
    QVERIFY(!c->preview({1, 1, 0}, kTop).empty());
    QCOMPARE(c->point({1, 0.5, 0}, kTop), R::Continue);  // both directions
    QCOMPARE(c->number(1), R::Continue);                 // u only
    QCOMPARE(c->point({3, 1, 0}, kTop), R::Continue);
    QCOMPARE(c->finish(), R::Done);
    const auto iso = curves(c->takeEntities());
    QCOMPARE(iso.size(), std::size_t{3});
    const auto [lo, hi] = box({iso[2]});
    QVERIFY(std::abs(lo.x - 3) < 1e-9 && std::abs(hi.x - 3) < 1e-9);  // x = 3, along y
    c = started("extractwireframe", {plate});
    QCOMPARE(c->finish(), R::Done);
    QCOMPARE(c->takeEntities().size(), std::size_t{4});  // a bilinear patch: its four borders
  }

  void offsetOnASurface() {
    const Entity plate = make_entity(nf::make_rectangle({-5, -5, 0}, {10, 0, 0}, {0, 10, 0}));
    const Entity line = make_entity(nf::make_line({-2, 0, 0}, {2, 0, 0}));
    auto c = started("offsetcrvonsrf", {line, plate});
    QVERIFY(c);
    QCOMPARE(c->number(1.5), R::Done);
    const auto off = curves(c->takeEntities());
    for (const auto& p : off[0].sample(10)) QVERIFY(std::abs(std::abs(p.y) - 1.5) < 1e-5);
  }

  void curveBooleans() {
    const std::vector<Entity> two{square(0, 0, 2), square(1, 1, 2)};
    struct Case { double op; double perimeter; nf::Vec3 lo, hi; };
    for (const Case& k : {Case{1, 12, {0, 0, 0}, {3, 3, 0}}, Case{2, 4, {1, 1, 0}, {2, 2, 0}},
                          Case{3, 8, {0, 0, 0}, {2, 2, 0}}}) {
      auto c = started("crvboolean", two);
      QVERIFY(c);
      QCOMPARE(c->number(k.op), R::Done);
      const auto out = curves(c->takeEntities());
      QVERIFY2(std::abs(length(out) - k.perimeter) < 1e-6, qPrintable(QString::number(length(out))));
      const auto [lo, hi] = box(out);
      QVERIFY(nf::distance(lo, k.lo) < 1e-6 && nf::distance(hi, k.hi) < 1e-6);
    }
    auto open = started("crvboolean", {square(0, 0, 1), make_entity(nf::make_line({0, 0, 0}, {1, 1, 0}))});
    QCOMPARE(open->number(1), R::Rejected);  // not closed
  }
};

QTEST_GUILESS_MAIN(TestDerivedCurves)
#include "test_derived_curves.moc"
