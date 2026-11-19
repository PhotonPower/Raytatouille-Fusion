#include <QJsonArray>
#include <QLineEdit>
#include <QSignalSpy>
#include <QStatusBar>
#include <QTest>
#include <algorithm>
#include <nurbforge/nurbforge.hpp>

#include "app/command_controller.hpp"
#include "document/document.hpp"
#include "document/selection.hpp"
#include "render/scene.hpp"
#include "results/result_store.hpp"
#include "snap/snap_engine.hpp"
#include "tessellation/tessellation_service.hpp"
#include "viewport/viewport.hpp"
#include "viewport/viewport_grid.hpp"

using nfcad::app::CommandController;

namespace {
const nf::NurbsCurve& last_curve(const nfcad::document::Document& doc) {
  return std::get<nf::NurbsCurve>(*doc.entities().rbegin()->second.geometry);
}
void move(nfcad::viewport::Viewport& v, QPointF pos) {
  QMouseEvent e(QEvent::MouseMove, pos, v.mapToGlobal(pos), Qt::NoButton, Qt::NoButton,
                Qt::NoModifier);
  QApplication::sendEvent(&v, &e);
}
}  // namespace

class TestCommandController : public QObject {
  Q_OBJECT
 private slots:
  void typedLineCircleUndoRepeat() {
    nfcad::document::Document doc;
    nfcad::viewport::ViewportGrid grid;
    grid.resize(1000, 800);
    QLineEdit line;
    QStatusBar status;
    CommandController c(&doc, nullptr, &grid, &line, &status);

    // type a command name, then absolute and relative coordinates
    c.submit(QStringLiteral("line"));
    QVERIFY(c.active());
    QVERIFY(line.placeholderText().contains(QStringLiteral("start")));
    c.submit(QStringLiteral("1,2,3"));
    c.submit(QStringLiteral("@10,0,0"));
    QVERIFY(!c.active());
    QCOMPARE(doc.entities().size(), std::size_t{1});
    const auto& l = last_curve(doc);
    QVERIFY(nf::distance(l.evaluate(l.domain_end()), {11, 2, 3}) < 1e-12);

    // circle by alias, centre and typed radius
    c.submit(QStringLiteral("c"));
    c.submit(QStringLiteral("5,5,0"));
    c.submit(QStringLiteral("2.5"));
    QCOMPARE(doc.entities().size(), std::size_t{2});
    QVERIFY(std::abs(nf::distance(last_curve(doc).evaluate(0.2), {5, 5, 0}) - 2.5) < 1e-12);

    // undo: one step per command
    doc.undoStack()->undo();
    QCOMPARE(doc.entities().size(), std::size_t{1});

    // Enter on an empty line repeats the last command; Esc-like cancel
    c.submit(QString());
    QCOMPARE(c.activeId(), QStringLiteral("circle"));
    c.cancel();
    QVERIFY(!c.active());

    // errors leave the state unchanged
    c.submit(QStringLiteral("nonsense"));
    QVERIFY(!c.active());
    c.submit(QStringLiteral("line"));
    c.submit(QStringLiteral("@1,1"));  // relative without a base point
    QVERIFY(c.active());
    c.cancel();
  }

  void orthoAndTypedLength() {
    nfcad::document::Document doc;
    nfcad::tessellation::TessellationService service;
    nfcad::render::Scene scene(&doc, &service);
    nfcad::viewport::ViewportGrid grid;
    grid.setScene(&scene);
    grid.resize(1000, 800);
    QLineEdit line;
    QStatusBar status;
    CommandController c(&doc, nullptr, &grid, &line, &status);
    nfcad::viewport::Viewport* top = grid.views()[1];  // Top (XY)
    QCOMPARE(top->kind(), nfcad::viewport::ViewKind::Top);
    top->resize(500, 400);
    top->zoomExtents();

    c.setOrtho(true);
    c.start(QStringLiteral("line"));
    c.submit(QStringLiteral("0,0"));
    // cursor somewhere up-right, mostly along +x: ortho keeps the direction on the x axis
    move(*top, *top->camera().project({6.0F, 1.5F, 0.0F}));
    c.submit(QStringLiteral("4"));  // length 4 along the (ortho) cursor direction
    QVERIFY(!c.active());
    const auto& l = last_curve(doc);
    const auto end = l.evaluate(l.domain_end());
    QVERIFY2(nf::distance(end, {4, 0, 0}) < 1e-6,
             qPrintable(QStringLiteral("%1 %2 %3").arg(end.x).arg(end.y).arg(end.z)));
  }

  void selectionCommands() {
    nfcad::document::Document doc;
    nfcad::document::Selection selection;
    selection.attach(&doc);
    nfcad::viewport::ViewportGrid grid;
    QLineEdit line;
    QStatusBar status;
    CommandController c(&doc, &selection, &grid, &line, &status);

    c.start(QStringLiteral("move"));  // nothing selected
    QVERIFY(!c.active());
    QVERIFY(status.currentMessage().contains(QStringLiteral("select")));

    const auto ids = doc.addEntities(
        {nfcad::document::make_entity(nf::make_box({-5, -5, 0}, {10, 10, 4})),
         nfcad::document::make_entity(nf::make_cylinder({0, 0, -1}, {0, 0, 1}, 2.0, 6.0))},
        QStringLiteral("add"));
    // order matters: box first, then the cylinder that is subtracted
    selection.apply({{ids[0], {}}}, nfcad::document::Selection::Mode::Replace);
    selection.apply({{ids[1], {}}}, nfcad::document::Selection::Mode::Add);
    c.submit(QStringLiteral("bd"));
    QVERIFY(!c.active());
    QCOMPARE(doc.entities().size(), std::size_t{1});
    const auto result = doc.entities().begin()->first;
    QVERIFY(selection.empty());  // the inputs left the selection

    selection.apply({{result, {}}}, nfcad::document::Selection::Mode::Replace);
    c.submit(QStringLiteral("move"));
    c.submit(QStringLiteral("0,0,0"));
    c.submit(QStringLiteral("@0,0,10"));
    QVERIFY(!c.active());
    const auto& shell = std::get<nf::Shell>(*doc.entity(result)->geometry);
    QVERIFY(std::abs(shell.mass_properties().centroid.z - 12.0) < 1e-6);
  }

  void movesAndRotatesSelectedDrawings() {
    // a plugin's camera drawing, bound to its position: Move and Rotate move the drawing and
    // write the camera's new place into the plugin's parameters, one undo step each
    nfcad::document::Document doc;
    nfcad::document::Selection selection;
    selection.attach(&doc);
    nfcad::results::ResultStore store;
    nfcad::viewport::ViewportGrid grid;
    QLineEdit line;
    QStatusBar status;
    CommandController c(&doc, &selection, &grid, &line, &status);
    c.setResults(&store);
    nfcad::results::LineSet l;
    l.points = {0, -100, 0, 0, 0, 0};
    const auto run = store.createSet(QStringLiteral("Camera"), QStringLiteral("cam"));
    const auto item = store.addLines(run, QStringLiteral("pyramid"), l);
    store.setBinding(item, QJsonObject{{"points", QJsonObject{{"pos", QJsonArray{0, -100, 0}}}}});
    selection.applyResults({run}, nfcad::document::Selection::Mode::Replace);
    auto pos = [&] {
      const QJsonArray a = doc.pluginParameters(QStringLiteral("cam"))["pos"].toArray();
      return a.size() == 3 ? nf::Vec3{a[0].toDouble(), a[1].toDouble(), a[2].toDouble()} : nf::Vec3{NAN, NAN, NAN};
    };

    c.submit(QStringLiteral("move"));
    QVERIFY(c.active());  // drawings alone are something to move
    c.submit(QStringLiteral("0,0,0"));
    c.submit(QStringLiteral("@10,0,0"));
    QVERIFY(!c.active());
    QVERIFY(nf::distance(pos(), {10, -100, 0}) < 1e-12);
    c.submit(QStringLiteral("rotate"));
    c.submit(QStringLiteral("0,0,0"));
    c.submit(QStringLiteral("90"));  // about the normal of the construction plane (+Z)
    QVERIFY(!c.active());
    QVERIFY2(nf::distance(pos(), {100, 10, 0}) < 1e-9, qPrintable(QString::number(pos().x)));
    QVERIFY(nf::distance(nfcad::results::placed_point(*store.item(item), 1), {0, 10, 0}) < 1e-9);
    QCOMPARE(doc.undoStack()->count(), 2);
    doc.undoStack()->undo();
    QVERIFY(nf::distance(pos(), {10, -100, 0}) < 1e-12);
    doc.undoStack()->undo();
    QVERIFY(doc.pluginParameters(QStringLiteral("cam")).isEmpty());
    QVERIFY(nfcad::results::is_identity(store.item(item)->placement));

    // copies, scaling and mirroring are for objects
    c.submit(QStringLiteral("scale"));
    QVERIFY(!c.active());
    QVERIFY(status.currentMessage().contains(QStringLiteral("moved and rotated")));
    // an object and a drawing move together, as one undo step
    const auto ids = doc.addEntities({nfcad::document::make_entity(nf::Vec3{1, 2, 3})}, QStringLiteral("add"));
    selection.apply({{ids[0], {}}}, nfcad::document::Selection::Mode::Add);
    selection.applyResults({run}, nfcad::document::Selection::Mode::Add);
    c.submit(QStringLiteral("move"));
    c.submit(QStringLiteral("0,0,0"));
    c.submit(QStringLiteral("@0,0,5"));
    QVERIFY(nf::distance(std::get<nf::Vec3>(*doc.entity(ids[0])->geometry), {1, 2, 8}) < 1e-12);
    QVERIFY(nf::distance(pos(), {0, -100, 5}) < 1e-12);
    QCOMPARE(doc.undoStack()->count(), 2);  // add, move
    doc.undoStack()->undo();
    QVERIFY(nf::distance(std::get<nf::Vec3>(*doc.entity(ids[0])->geometry), {1, 2, 3}) < 1e-12);
    QVERIFY(nfcad::results::is_identity(store.item(item)->placement));
  }

  void extrudeTypedDistanceInTheActiveView() {
    // a typed distance extrudes along the normal of the active view's construction plane
    nfcad::document::Document doc;
    nfcad::document::Selection selection;
    selection.attach(&doc);
    nfcad::viewport::ViewportGrid grid;
    grid.resize(1000, 800);
    QLineEdit line;
    QStatusBar status;
    CommandController c(&doc, &selection, &grid, &line, &status);
    const auto ids = doc.addEntities({nfcad::document::make_entity(nf::make_line({0, 0, 0}, {2, 0, 0}))},
                                     QStringLiteral("add"));
    nfcad::viewport::Viewport* front = grid.views()[0];
    QCOMPARE(front->kind(), nfcad::viewport::ViewKind::Front);
    front->resize(500, 400);
    QTest::mouseClick(front, Qt::MiddleButton, Qt::NoModifier, {250, 200});  // activates it
    QCOMPARE(grid.activeView(), front);
    selection.apply({{ids[0], {}}}, nfcad::document::Selection::Mode::Replace);
    c.submit(QStringLiteral("ext"));
    QVERIFY(c.active());
    c.submit(QStringLiteral("3"));
    QVERIFY(!c.active());
    const nf::NurbsSurface* made = nullptr;
    for (const auto& [id, e] : doc.entities()) {
      if (const auto* s = std::get_if<nf::NurbsSurface>(e.geometry.get())) made = s;
    }
    QVERIFY(made != nullptr);
    double min_y = 0.0;
    for (const nf::Vec3& p : made->control_points()) {
      QVERIFY(std::abs(p.z) < 1e-12);  // Front: along -Y, not +Z
      min_y = std::min(min_y, p.y);
    }
    QVERIFY(std::abs(min_y + 3.0) < 1e-12);
  }

  void rejectedInputShowsTheReason() {
    nfcad::document::Document doc;
    nfcad::document::Selection selection;
    selection.attach(&doc);
    nfcad::viewport::ViewportGrid grid;
    QLineEdit line;
    QStatusBar status;
    CommandController c(&doc, &selection, &grid, &line, &status);
    const auto ids = doc.addEntities({nfcad::document::make_entity(nf::make_line({-5, 0, 0}, {0, 0, 0})),
                                      nfcad::document::make_entity(nf::make_line({0, 0, 0}, {0, 5, 0}))},
                                     QStringLiteral("add"));
    selection.apply({{ids[0], {}}, {ids[1], {}}}, nfcad::document::Selection::Mode::Replace);
    c.submit(QStringLiteral("fillet"));
    QVERIFY(c.active());
    c.submit(QStringLiteral("10"));
    QVERIFY(c.active());  // the command waits for another radius
    QVERIFY2(status.currentMessage().contains(QStringLiteral("too large")), qPrintable(status.currentMessage()));
    QVERIFY(!status.currentMessage().contains(QStringLiteral("Input not accepted")));
    c.submit(QStringLiteral("1"));
    QVERIFY(!c.active());
  }

  void rightClickRepeatsTheLastCommand() {
    nfcad::document::Document doc;
    nfcad::viewport::ViewportGrid grid;
    grid.resize(1000, 800);
    QLineEdit line;
    QStatusBar status;
    CommandController c(&doc, nullptr, &grid, &line, &status);
    nfcad::viewport::Viewport* top = grid.views()[1];
    top->resize(500, 400);
    QTest::mouseClick(top, Qt::RightButton, Qt::NoModifier, {250, 200});
    QVERIFY(!c.active());  // no last command yet
    c.submit(QStringLiteral("line"));
    c.submit(QStringLiteral("0,0"));
    c.submit(QStringLiteral("1,0"));
    QVERIFY(!c.active());
    QTest::mouseClick(top, Qt::RightButton, Qt::NoModifier, {250, 200});
    QCOMPARE(c.activeId(), QStringLiteral("line"));
    QTest::mouseClick(top, Qt::RightButton, Qt::NoModifier, {250, 200});  // finishes (cancels) it
    QVERIFY(!c.active());
    // a right drag pans / orbits and repeats nothing
    QTest::mousePress(top, Qt::RightButton, Qt::NoModifier, {250, 200});
    move(*top, {300, 220});
    QTest::mouseRelease(top, Qt::RightButton, Qt::NoModifier, {300, 220});
    QVERIFY(!c.active());
  }

  void polylineClosesBySnappingItsStart() {
    nfcad::document::Document doc;
    nfcad::tessellation::TessellationService service;
    nfcad::render::Scene scene(&doc, &service);
    nfcad::snap::SnapEngine engine;
    nfcad::viewport::ViewportGrid grid;
    grid.setScene(&scene);
    grid.setSnapEngine(&engine);
    grid.resize(1000, 800);
    QLineEdit line;
    QStatusBar status;
    CommandController c(&doc, nullptr, &grid, &line, &status);
    nfcad::viewport::Viewport* top = grid.views()[1];
    top->resize(500, 400);
    top->zoomExtents();

    c.start(QStringLiteral("polyline"));
    c.submit(QStringLiteral("0,0"));
    c.submit(QStringLiteral("10,0"));
    c.submit(QStringLiteral("10,10"));
    // click a few pixels next to the start: the cursor snaps to it (End) and closes the polyline
    const QPointF start = *top->camera().project({0.0F, 0.0F, 0.0F});
    const QPoint near = (start + QPointF(3, -2)).toPoint();
    move(*top, near);
    QVERIFY(!top->snapCandidates().empty());
    QCOMPARE(top->snapCandidates().front().type, nfcad::snap::SnapType::End);
    QTest::mouseClick(top, Qt::LeftButton, Qt::NoModifier, near);
    QVERIFY(!c.active());
    const auto& pl = last_curve(doc);
    QCOMPARE(pl.control_points().size(), std::size_t{4});
    QVERIFY(nf::distance(pl.evaluate(pl.domain_end()), {0, 0, 0}) == 0.0);
  }

  void distanceMessageInStatusBar() {
    nfcad::document::Document doc;
    nfcad::viewport::ViewportGrid grid;
    QLineEdit line;
    QStatusBar status;
    CommandController c(&doc, nullptr, &grid, &line, &status);
    c.start(QStringLiteral("dist"));
    c.submit(QStringLiteral("0,0,0"));
    c.submit(QStringLiteral("0,3,4"));
    QVERIFY(status.currentMessage().startsWith(QStringLiteral("Distance 5")));
    QVERIFY(doc.entities().empty());
  }
};

QTEST_MAIN(TestCommandController)
#include "test_command_controller.moc"
