// Analysis commands (analysis_commands.cpp) and control points of surfaces.
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
using nfcad::document::Geometry;
using nfcad::render::Analysis;
using R = Command::Result;

namespace {

const PlaneFrame kTop{};

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

QString gcon(Geometry a, Geometry b) {
  auto c = started("gcon", {entity(std::move(a), 1), entity(std::move(b), 2)});
  return c ? c->message() : QStringLiteral("(rejected)");
}

}  // namespace

class TestAnalysis : public QObject {
  Q_OBJECT
 private slots:
  void viewAnalyses() {
    auto c = started("zebra", {});
    QVERIFY(c && c->immediate());
    QCOMPARE(c->finish(), R::Done);
    QVERIFY(c->viewAnalysis() && c->viewAnalysis()->kind == Analysis::Kind::Zebra);
    QVERIFY(c->analysisToggles());
    // a sphere of radius 2: Gaussian curvature 1/4 everywhere, |k| 1/2
    const Entity sphere = entity(nf::make_sphere({0, 0, 0}, 2.0));
    c = started("curvatureanalysis", {sphere});
    QCOMPARE(c->finish(), R::Done);
    auto a = *c->viewAnalysis();
    QVERIFY(a.kind == Analysis::Kind::Curvature && a.measure == Analysis::Measure::Gaussian);
    QVERIFY(std::abs(a.hi - 0.25F) < 1e-3F && std::abs(a.lo + 0.25F) < 1e-3F);
    c = started("curvatureanalysis", {sphere});
    QCOMPARE(c->number(5), R::Rejected);
    QCOMPARE(c->number(3), R::Done);
    a = *c->viewAnalysis();
    QVERIFY(a.measure == Analysis::Measure::Maximum && a.lo == 0.0F && std::abs(a.hi - 0.5F) < 1e-3F);
    c = started("draftangleanalysis", {});
    QCOMPARE(c->number(5), R::Done);
    a = *c->viewAnalysis();
    QVERIFY(a.kind == Analysis::Kind::Draft && a.draft_angle == 5.0F && a.direction[2] == 1.0F);
    QVERIFY(!c->analysisToggles());
    c = started("analysisoff", {});
    QCOMPARE(c->finish(), R::Done);
    QVERIFY(c->viewAnalysis()->kind == Analysis::Kind::None);
    QCOMPARE(nfcad::render::curvature_measure(Analysis::Measure::Minimum, -3.0F, 2.0F), 2.0F);
  }

  void continuityOfCurves() {
    const double h = std::sqrt(0.5);
    const nf::NurbsCurve arc1 = nf::make_arc_3pt({0, 1, 0}, {h, h, 0}, {1, 0, 0});
    const nf::NurbsCurve arc2 = nf::make_arc_3pt({1, 0, 0}, {h, -h, 0}, {0, -1, 0});
    QVERIFY(gcon(nf::make_line({-1, 1, 0}, {0, 1, 0}), arc1).startsWith(QStringLiteral("Continuity G1")));
    QVERIFY(gcon(arc1, arc2).startsWith(QStringLiteral("Continuity G2")));
    QVERIFY(gcon(nf::make_line({0, 0, 0}, {1, 0, 0}), nf::make_line({1, 0, 0}, {1, 1, 0})).startsWith(QStringLiteral("Continuity G0")));
    QVERIFY(gcon(nf::make_line({0, 0, 0}, {1, 0, 0}), nf::make_line({2, 0, 0}, {3, 0, 0})).contains(QStringLiteral("not touching")));
  }

  void continuityOfSurfaces() {
    const auto a = nf::make_rectangle({0, 0, 0}, {1, 0, 0}, {0, 1, 0});
    QVERIFY(gcon(a, nf::make_rectangle({1, 0, 0}, {1, 0, 0}, {0, 1, 0})).startsWith(QStringLiteral("Continuity G2")));
    QVERIFY(gcon(a, nf::make_rectangle({1, 0, 0}, {0, 0, 1}, {0, 1, 0})).startsWith(QStringLiteral("Continuity G0")));
    QVERIFY(gcon(a, nf::make_rectangle({3, 0, 0}, {1, 0, 0}, {0, 1, 0})).contains(QStringLiteral("do not share")));
  }

  void areaCentroid() {
    auto c = started("areacentroid", {entity(nf::make_rectangle({0, 0, 0}, {4, 0, 0}, {0, 2, 0}))});
    QVERIFY(c);
    QCOMPARE(c->finish(), R::Done);
    auto made = c->takeEntities();
    QVERIFY(nf::distance(std::get<nf::Vec3>(*made.front().geometry), {2, 1, 0}) < 1e-6);
    c = started("areacentroid", {entity(nf::make_circle({1, 1, 0}, {0, 0, 1}, 1.0))});
    QVERIFY(c);
    made = c->takeEntities();
    QVERIFY(nf::distance(std::get<nf::Vec3>(*made.front().geometry), {1, 1, 0}) < 1e-6);
    QVERIFY(c->message().contains(QStringLiteral("3.14159")));
  }

  void check() {
    const nf::Shell box = nf::make_box({0, 0, 0}, {1, 1, 1});
    auto c = started("check", {entity(box)});
    QVERIFY(c && c->message().contains(QStringLiteral("no problems")));
    std::vector<nf::TrimmedSurface> flipped, open;
    for (const auto& f : box.faces()) flipped.push_back(f.flipped());
    open.assign(box.faces().begin(), box.faces().end() - 1);
    c = started("check", {entity(nf::Shell::sew(flipped, 1e-6), 1), entity(nf::Shell::sew(open, 1e-6), 2)});
    QVERIFY(c->message().contains(QStringLiteral("inwards")));
    QVERIFY(c->message().contains(QStringLiteral("naked edges")));
  }

  void surfaceControlPoints() {
    const nf::TrimmedSurface face(nf::make_rectangle({0, 0, 0}, {2, 0, 0}, {0, 2, 0}));
    const auto hole = nf::TrimmedSurface(face).with_hole(nf::make_circle({1, 1, 0}, {0, 0, 1}, 0.3));
    const Geometry g = hole;
    const auto& s = hole.surface();
    const int last = static_cast<int>(s.control_points().size()) - 1;
    const auto p = nfcad::kernel::part_of(g, {nfcad::document::SubElement::Kind::ControlPoint, last});
    QVERIFY(p && nf::distance(std::get<nf::Vec3>(*p), s.control_points().back()) < 1e-12);
    const auto moved = nfcad::kernel::with_control_points_moved(g, {last}, nf::Transform::translation({0, 0, 1}));
    QVERIFY(moved);
    const auto& m = std::get<nf::TrimmedSurface>(*moved);
    QVERIFY(std::abs(m.surface().control_points().back().z - 1.0) < 1e-12);
    QCOMPARE(m.holes().size(), std::size_t{1});  // the trim stays
  }
};

QTEST_GUILESS_MAIN(TestAnalysis)
#include "test_analysis.moc"
