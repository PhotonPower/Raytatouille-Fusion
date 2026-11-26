#include <QElapsedTimer>
#include <QSignalSpy>
#include <QTest>
#include <cmath>
#include <numbers>
#include <nurbforge/nurbforge.hpp>

#include "document/document.hpp"
#include "document/selection.hpp"
#include "kernel/properties.hpp"
#include "pick/picking.hpp"
#include "tessellation/tessellator.hpp"
#include "viewport/view_kind.hpp"

using nfcad::document::SelectionItem;
using nfcad::document::SubElement;
using nfcad::pick::Hit;
using nfcad::pick::Query;
using nfcad::pick::Target;
using nfcad::tessellation::DisplayMesh;
using nfcad::viewport::Camera;
using nfcad::viewport::ViewKind;

namespace {

DisplayMesh mesh(const nfcad::document::Geometry& g) {
  nfcad::tessellation::TessParams p;
  p.chord = 0.01;
  return nfcad::tessellation::tessellate(g, p);
}

Camera top_camera() {
  const auto preset = nfcad::viewport::view_preset(ViewKind::Top);
  Camera c;
  c.setViewportSize({800, 600});
  c.setView(preset.forward, preset.up);
  c.setProjection(preset.projection);
  c.setTarget({0, 0, 0});
  c.setHalfHeight(30.0F);  // 0.1 world units per pixel
  c.setSceneRadius(100.0F);
  return c;
}

QPointF px(const Camera& c, const QVector3D& p) { return *c.project(p); }

}  // namespace

class TestPicking : public QObject {
  Q_OBJECT

  // id 1: box 20 x 20 x 4 at the origin (top face z = 4)
  // id 2: line above the box at z = 10 along x through y = 5
  // id 3: line below the box at z = -5 along x through y = -5
  // id 4: point at (25, 0, 0)
  DisplayMesh box_ = mesh(nf::make_box({-10, -10, 0}, {20, 20, 4}));
  DisplayMesh above_ = mesh(nf::make_line({-20, 5, 10}, {20, 5, 10}));
  DisplayMesh below_ = mesh(nf::make_line({-20, -5, -5}, {20, -5, -5}));
  DisplayMesh point_ = mesh(nf::Vec3{25, 0, 0});
  std::vector<Target> targets_ = {{1, &box_, nullptr, nullptr}, {2, &above_, nullptr, nullptr}, {3, &below_, nullptr, nullptr}, {4, &point_, nullptr, nullptr}};

 private slots:
  void bvhIndexBuilt() {
    QVERIFY(!box_.triangle_bvh.empty());
    QVERIFY(!box_.segment_bvh.empty());
    QCOMPARE(box_.faceCount(), std::size_t{6});
    QCOMPARE(box_.corners.size(), std::size_t{8 * 3});
  }

  void faceUnderCursor() {
    const Camera c = top_camera();
    Query q;
    q.cursor_px = px(c, {3, 1, 4});
    const auto hit = nfcad::pick::pick(targets_, c, q);
    QVERIFY(hit);
    QCOMPARE(hit->item.entity, nfcad::document::EntityId{1});
    QCOMPARE(hit->kind, Hit::Kind::Face);
    QVERIFY(std::abs(hit->point.z() - 4.0F) < 1e-3F);  // top face
  }

  void curveBeforeFace() {
    const Camera c = top_camera();
    Query q;
    q.cursor_px = px(c, {0, 5, 10}) + QPointF(0, 3);  // 3 px off the line, above the box
    const auto hit = nfcad::pick::pick(targets_, c, q);
    QVERIFY(hit);
    QCOMPARE(hit->item.entity, nfcad::document::EntityId{2});
    QCOMPARE(hit->kind, Hit::Kind::Curve);
    QVERIFY(std::abs(hit->distance_px - 3.0F) < 0.5F);
  }

  void hiddenCurveNotPickedWithFaces() {
    const Camera c = top_camera();
    Query q;
    q.cursor_px = px(c, {0, -5, -5});
    auto hit = nfcad::pick::pick(targets_, c, q);
    QVERIFY(hit);
    QCOMPARE(hit->item.entity, nfcad::document::EntityId{1});  // the box hides the line
    q.faces = false;                                          // wireframe
    hit = nfcad::pick::pick(targets_, c, q);
    QVERIFY(hit);
    QCOMPARE(hit->item.entity, nfcad::document::EntityId{3});
  }

  void pointAndMiss() {
    const Camera c = top_camera();
    Query q;
    q.cursor_px = px(c, {25, 0, 0}) + QPointF(2, -2);
    auto hit = nfcad::pick::pick(targets_, c, q);
    QVERIFY(hit);
    QCOMPARE(hit->item.entity, nfcad::document::EntityId{4});
    QCOMPARE(hit->kind, Hit::Kind::Point);
    q.cursor_px = px(c, {28, 20, 0});
    QVERIFY(!nfcad::pick::pick(targets_, c, q));
  }

  void subElements() {
    const Camera c = top_camera();
    Query q;
    q.sub_elements = true;
    q.cursor_px = px(c, {3, 1, 4});
    auto hit = nfcad::pick::pick(targets_, c, q);
    QVERIFY(hit);
    QCOMPARE(hit->item.sub.kind, SubElement::Kind::Face);
    // edge of the top face along x at y = -10 (not the line entities)
    q.cursor_px = px(c, {2, -10, 4}) + QPointF(0, -2);
    hit = nfcad::pick::pick(targets_, c, q);
    QVERIFY(hit);
    QCOMPARE(hit->item.entity, nfcad::document::EntityId{1});
    QCOMPARE(hit->item.sub.kind, SubElement::Kind::Edge);
    // corner vertex
    q.cursor_px = px(c, {10, 10, 4}) + QPointF(1, 1);
    hit = nfcad::pick::pick(targets_, c, q);
    QVERIFY(hit);
    QCOMPARE(hit->item.sub.kind, SubElement::Kind::Vertex);
  }

  void windowAndCrossing() {
    const Camera c = top_camera();
    // window around the box only
    QRectF r(px(c, {-12, 12, 0}), px(c, {12, -12, 0}));
    auto ids = nfcad::pick::pick_rect(targets_, c, r, false);
    QCOMPARE(ids, std::vector<nfcad::document::EntityId>{1});
    // small rectangle inside the top face: crossing selects the box, window nothing
    r = QRectF(px(c, {-2, 2, 0}), px(c, {2, -2, 0}));
    QVERIFY(nfcad::pick::pick_rect(targets_, c, r, false).empty());
    ids = nfcad::pick::pick_rect(targets_, c, r, true);
    QCOMPARE(ids, std::vector<nfcad::document::EntityId>{1});
    // crossing through the middle of the lines selects both lines and the box
    r = QRectF(px(c, {-1, 15, 0}), px(c, {1, -15, 0}));
    ids = nfcad::pick::pick_rect(targets_, c, r, true);
    std::sort(ids.begin(), ids.end());
    QCOMPARE(ids, (std::vector<nfcad::document::EntityId>{1, 2, 3}));
  }

  void selectionModes() {
    nfcad::document::Selection s;
    QSignalSpy changed(&s, &nfcad::document::Selection::changed);
    const SelectionItem a{1, {}};
    const SelectionItem b{2, {}};
    const SelectionItem face{3, {SubElement::Kind::Face, 2}};
    s.apply({a}, nfcad::document::Selection::Mode::Replace);
    s.apply({b, face}, nfcad::document::Selection::Mode::Add);
    QCOMPARE(s.items().size(), std::size_t{3});
    QVERIFY(s.isSelected(1));
    QVERIFY(!s.isSelected(3));
    QCOMPARE(s.selectedParts(3).size(), std::size_t{1});
    QCOMPARE(s.entities(), (std::vector<nfcad::document::EntityId>{1, 2, 3}));
    s.apply({a}, nfcad::document::Selection::Mode::Remove);
    s.apply({face}, nfcad::document::Selection::Mode::Toggle);
    QCOMPARE(s.items().size(), std::size_t{1});
    s.apply({b}, nfcad::document::Selection::Mode::Add);  // no change -> no signal
    QCOMPARE(changed.count(), 4);
  }

  void selectionFollowsDocument() {
    nfcad::document::Document doc;
    nfcad::document::Selection s;
    s.attach(&doc);
    const auto ids = doc.addEntities({nfcad::document::make_entity(nf::Vec3{0, 0, 0}),
                                      nfcad::document::make_entity(nf::Vec3{1, 0, 0})},
                                     QStringLiteral("add"));
    s.apply({{ids[0], {}}, {ids[1], {}}}, nfcad::document::Selection::Mode::Replace);
    s.setHovered(SelectionItem{ids[0], {}});
    doc.removeEntities({ids[0]}, QStringLiteral("del"));
    QCOMPARE(s.items().size(), std::size_t{1});
    QVERIFY(!s.hovered());
  }

  void resultDrawingsPickedAsAWhole() {
    // a run's rays: one polyline along x at y = 15 (beside the box), one lost after its first
    // point; drawn on top of the model
    nfcad::results::ResultItem rays;
    auto set = std::make_shared<nfcad::results::LineSet>();
    set->points = {-20, 15, 0, 20, 15, 0, 0, 25, 0, NAN, NAN, NAN};
    set->starts = {0, 2, 4};
    rays.lines = set;
    const std::vector<nfcad::pick::LineTarget> targets = {{7, &rays}};
    const Camera c = top_camera();
    auto hit = nfcad::pick::pick_lines(targets, c, px(c, {5, 15.2F, 0}));
    QVERIFY(hit);
    QCOMPARE(hit->id, std::uint64_t{7});
    QVERIFY(hit->distance_px < 3.0F);
    QVERIFY(!nfcad::pick::pick_lines(targets, c, px(c, {0, 25, 0})));  // the lost ray has no segment
    QVERIFY(!nfcad::pick::pick_lines(targets, c, px(c, {5, 0, 0})));
    // moved in the views: picked where it is shown
    rays.placement = nf::Transform::translation({0, -15, 0});
    QVERIFY(!nfcad::pick::pick_lines(targets, c, px(c, {5, 15, 0})));
    hit = nfcad::pick::pick_lines(targets, c, px(c, {5, 0, 0}));
    QVERIFY(hit);
    // over the box: rays on top win over its face, depth-tested ones only in front of it
    Query q;
    q.cursor_px = px(c, {5, 0, 4});
    const auto face = nfcad::pick::pick(targets_, c, q);
    QVERIFY(face && face->kind == Hit::Kind::Face);
    QVERIFY(nfcad::pick::line_hit_wins(*hit, face));
    hit->on_top = false;  // at z = 0, below the top face at z = 4
    QVERIFY(!nfcad::pick::line_hit_wins(*hit, face));
    QVERIFY(nfcad::pick::line_hit_wins(*hit, std::nullopt));

    // the selection keeps drawings apart from entities: selecting one replaces the other
    nfcad::document::Selection s;
    s.apply({SelectionItem{3, {}}}, nfcad::document::Selection::Mode::Replace);
    s.applyResults({7}, nfcad::document::Selection::Mode::Replace);
    QVERIFY(s.empty() && s.isResultSelected(7));
    s.applyResults({8}, nfcad::document::Selection::Mode::Add);
    s.apply({SelectionItem{3, {}}}, nfcad::document::Selection::Mode::Add);  // adding keeps them
    QCOMPARE(s.results().size(), std::size_t{2});
    s.retainResults([](std::uint64_t id) { return id == 8; });
    QVERIFY(!s.isResultSelected(7) && s.isResultSelected(8));
    s.apply({SelectionItem{3, {}}}, nfcad::document::Selection::Mode::Replace);
    QVERIFY(!s.hasResults());
  }

  void assignLayerUndo() {
    nfcad::document::Document doc;
    const auto layer = doc.addLayer({0, QStringLiteral("L"), QColor(Qt::green), true});
    const auto ids = doc.addEntities({nfcad::document::make_entity(nf::Vec3{0, 0, 0})},
                                     QStringLiteral("add"));
    doc.assignLayer(ids, layer);
    QCOMPARE(doc.entity(ids[0])->layer, layer);
    doc.undoStack()->undo();
    QCOMPARE(doc.entity(ids[0])->layer, nfcad::document::LayerId{0});
  }

  void pickTimingOnDenseMesh() {
    // Dense mesh (64 segments per span limit: 65 536 triangles): hover picking must stay
    // interactive (ADR 0007). Measured: ~1 us per pick (release), ~10 us (debug).
    nfcad::tessellation::TessParams p;
    p.chord = 0.00002;
    const DisplayMesh dense = nfcad::tessellation::tessellate(nf::make_sphere({0, 0, 0}, 9.0), p);
    const std::vector<Target> targets = {{1, &dense, nullptr, nullptr}};
    Camera c = top_camera();
    Query q;
    QElapsedTimer t;
    t.start();
    int hits = 0;
    constexpr int kPicks = 2000;
    for (int i = 0; i < kPicks; ++i) {
      q.cursor_px = QPointF(300 + i % 200, 200 + (i / 10) % 200);
      hits += nfcad::pick::pick(targets, c, q) ? 1 : 0;
    }
    const double us = static_cast<double>(t.nsecsElapsed()) / 1000.0 / kPicks;
    qInfo("%zu triangles: %.1f us per pick (%d hits)", dense.triangleCount(), us, hits);
    QVERIFY(dense.triangleCount() > 50000);
    QVERIFY(hits > 0);
    QVERIFY2(us < 5000.0, qPrintable(QString::number(us)));
  }

  void properties() {
    const auto circle = nfcad::kernel::describe(nf::make_circle({0, 0, 0}, {0, 0, 1}, 2.0));
    auto value = [](const nfcad::kernel::PropertyList& l, const QString& k) {
      for (const auto& [key, v] : l) {
        if (key == k) return v;
      }
      return QString();
    };
    QVERIFY(std::abs(value(circle, QStringLiteral("Length")).toDouble() - 4.0 * std::numbers::pi) < 1e-6);
    QCOMPARE(value(circle, QStringLiteral("Closed")), QStringLiteral("yes"));
    const nf::Shell box = nf::make_box({0, 0, 0}, {1, 2, 3});
    const auto shell = nfcad::kernel::describe(box);
    QCOMPARE(value(shell, QStringLiteral("Faces")), QStringLiteral("6"));
    QVERIFY(std::abs(value(shell, QStringLiteral("Volume")).toDouble() - 6.0) < 1e-6);
    const auto face = nfcad::kernel::describe(box, {SubElement::Kind::Face, 0});
    QVERIFY(value(face, QStringLiteral("Type")).startsWith(QStringLiteral("Face 0")));
    QCOMPARE(nfcad::kernel::knots_text({0, 0, 0, 0.5, 1, 1, 1}),
             QStringLiteral("0 (×3), 0.5, 1 (×3)"));
  }

  void gripsComeFirstAndAreNotHidden() {
    // a curve with its control points shown, partly above, partly below the box
    const DisplayMesh curve = mesh(nf::make_line({-20, 0, -8}, {20, 0, -8}));
    const std::vector<QVector3D> grips{{-20, 0, -8}, {0, 0, -8}, {20, 0, -8}};
    std::vector<Target> targets = targets_;
    targets.push_back({5, &curve, nullptr, &grips});
    const Camera cam = top_camera();
    Query q;
    q.cursor_px = px(cam, {0, 0, -8});  // the middle grip lies under the box's top face
    auto hit = nfcad::pick::pick(targets, cam, q);
    QVERIFY(hit);
    QCOMPARE(hit->item, (SelectionItem{5, {SubElement::Kind::ControlPoint, 1}}));
    q.cursor_px = px(cam, {-15, 0, -8});  // on the curve beside the box, away from the grips
    hit = nfcad::pick::pick(targets, cam, q);
    QVERIFY(hit && hit->item.entity == 5 && hit->item.sub.kind == SubElement::Kind::None);
    // the window takes the grips inside
    const QRectF window(px(cam, {-25, 2, 0}), px(cam, {5, -2, 0}));
    const auto inside = nfcad::pick::pick_rect_grips(targets, cam, window);
    QCOMPARE(inside.size(), std::size_t{2});
    QCOMPARE(inside[1], (SelectionItem{5, {SubElement::Kind::ControlPoint, 1}}));
    // the property panel describes a control point
    const auto props = nfcad::kernel::describe(nfcad::document::Geometry{nf::make_line({0, 0, 0}, {1, 0, 0})},
                                               {SubElement::Kind::ControlPoint, 1});
    QCOMPARE(props.front().second, QStringLiteral("Control point 1 of a curve"));
  }
};

QTEST_GUILESS_MAIN(TestPicking)
#include "test_picking.moc"
