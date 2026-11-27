// Triangle meshes as entities and ShrinkWrap (mesh_commands.cpp).
#include <QTest>
#include <cmath>
#include <nurbforge/nurbforge.hpp>

#include "commands/command.hpp"
#include "document/nfcad_io.hpp"
#include "kernel/geometry_ops.hpp"
#include "kernel/properties.hpp"
#include "tessellation/tessellator.hpp"

using nfcad::commands::Command;
using nfcad::commands::create_command;
using nfcad::document::Entity;
using nfcad::document::Geometry;
using R = Command::Result;

namespace {

Entity entity(Geometry g, nfcad::document::EntityId id = 1) {
  Entity e = nfcad::document::make_entity(std::move(g));
  e.id = id;
  return e;
}

/// A shrink wrap around a 1 × 2 × 3 box (resolution 0.1, offset 0).
nf::TriangleMesh wrapped_box() {
  auto c = create_command(QStringLiteral("shrinkwrap"));
  if (!c->begin({entity(nf::make_box({0, 0, 0}, {1, 2, 3}))})) return {};
  if (c->number(0.1) != R::Continue) return {};
  if (c->finish() != R::Done) qWarning("%s", qPrintable(c->message()));  // closed solid: offset 0
  auto made = c->takeEntities();
  return made.empty() ? nf::TriangleMesh{} : std::get<nf::TriangleMesh>(*made[0].geometry);
}

}  // namespace

class TestMesh : public QObject {
  Q_OBJECT
 private slots:
  void shrinkWrapOfABox() {
    const nf::TriangleMesh m = wrapped_box();
    QVERIFY(!m.triangles.empty());
    QVERIFY(m.is_watertight() && m.is_consistently_oriented());
    QVERIFY2(std::abs(m.volume() - 6.0) < 0.3, qPrintable(QString::number(m.volume())));
  }

  void prompts() {
    auto c = create_command(QStringLiteral("shrink_wrap"));
    QVERIFY(!c->begin({entity(nf::make_line({0, 0, 0}, {1, 0, 0}))}));  // nothing to wrap
    // an open surface: the default offset is at least 0.75 × resolution
    c = create_command(QStringLiteral("shrinkwrap"));
    QVERIFY(c->begin({entity(nf::make_rectangle({0, 0, 0}, {1, 0, 0}, {0, 1, 0}))}));
    QVERIFY(c->prompt().contains(QStringLiteral("0.014")));  // diagonal / 100
    QCOMPARE(c->number(-1), R::Rejected);
    QCOMPARE(c->number(0.1), R::Continue);
    QVERIFY(c->prompt().contains(QStringLiteral("0.076")));
    QCOMPARE(c->finish(), R::Done);
    const auto made = c->takeEntities();
    QVERIFY(std::get<nf::TriangleMesh>(*made[0].geometry).is_watertight());  // a flat closed pillow
  }

  void meshIsAnEntity() {
    const nf::TriangleMesh m = wrapped_box();
    const Geometry g = m;
    // saved and read back
    const Geometry back = nfcad::document::geometry_from_json(nfcad::document::geometry_to_json(g));
    const auto& mb = std::get<nf::TriangleMesh>(back);
    QCOMPARE(mb.triangles.size(), m.triangles.size());
    QCOMPARE(mb.nodes.size(), m.nodes.size());
    QCOMPARE(mb.nodes[5].y, m.nodes[5].y);
    // moved; mirrored: the normals still point out
    const auto moved = std::get<nf::TriangleMesh>(nfcad::kernel::transformed(g, nf::Transform::translation({10, 0, 0})));
    QCOMPARE(moved.nodes[0].x, m.nodes[0].x + 10);
    const auto mirrored = std::get<nf::TriangleMesh>(nfcad::kernel::transformed(g, nf::Transform::mirror({0, 0, 0}, {1, 0, 0})));
    QVERIFY(std::abs(mirrored.volume() - m.volume()) < 1e-9);
    QVERIFY(!nfcad::kernel::wire(g).empty());
    // drawn: all triangles in one face
    const auto dm = nfcad::tessellation::tessellate(g, nfcad::tessellation::default_params(g));
    QCOMPARE(dm.triangleCount(), m.triangles.size());
    QCOMPARE(dm.faceCount(), std::size_t{1});
    QVERIFY(dm.edges.empty());  // closed: no open edges
    // properties
    bool closed = false;
    for (const auto& [k, v] : nfcad::kernel::describe(g, {})) {
      if (k == QStringLiteral("Closed")) closed = v.startsWith(QStringLiteral("yes"));
    }
    QVERIFY(closed);
    // a broken mesh is reported by Check
    nf::TriangleMesh bad = m;
    bad.triangles.pop_back();
    auto check = create_command(QStringLiteral("check"));
    check->begin({entity(bad)});
    QVERIFY2(check->message().contains(QStringLiteral("open mesh")), qPrintable(check->message()));
  }
};

QTEST_GUILESS_MAIN(TestMesh)
#include "test_mesh.moc"
