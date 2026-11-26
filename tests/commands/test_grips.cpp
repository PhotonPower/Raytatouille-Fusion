// Control points (grips): Points on / off, Select points, Weight, and the moving commands on
// selected control points.
#include <QTest>
#include <nurbforge/nurbforge.hpp>

#include "commands/command.hpp"
#include "document/document.hpp"

using nfcad::commands::Command;
using nfcad::commands::create_command;
using nfcad::commands::GripSet;
using nfcad::commands::kPointsOnKey;
using nfcad::commands::PlaneFrame;
using nfcad::document::Entity;
using nfcad::document::SubElement;
using R = Command::Result;

namespace {

const PlaneFrame kTop{};

nf::NurbsCurve cubic() {
  return nf::NurbsCurve::from_points(3, {{0, 0, 0}, {1, 1, 0}, {2, -1, 0}, {3, 0, 0}});
}

Entity curve_entity(nfcad::document::EntityId id, bool points_on = false) {
  Entity e = nfcad::document::make_entity(cubic());
  e.id = id;
  if (points_on) e.attributes.insert(QString::fromLatin1(kPointsOnKey), true);
  return e;
}

nf::NurbsCurve geometry(const std::pair<nfcad::document::EntityId, nfcad::document::GeometryPtr>& r) {
  return std::get<nf::NurbsCurve>(*r.second);
}

}  // namespace

class TestGrips : public QObject {
  Q_OBJECT
 private slots:
  void pointsOnAndOff() {
    auto c = create_command(QStringLiteral("pon"));
    QVERIFY(c->begin({curve_entity(3)}));
    QCOMPARE(c->finish(), R::Done);
    auto edit = c->takeEdit();
    QCOMPARE(edit.attributes.size(), std::size_t{1});
    QVERIFY(edit.attributes[0].second.value(QString::fromLatin1(kPointsOnKey)).toBool());
    QVERIFY(!create_command(QStringLiteral("pon"))->begin({curve_entity(3, true)}));  // already on
    // Points off without a selection: every curve in the document, and the grips leave the selection
    nfcad::document::Document doc;
    Entity on = curve_entity(0, true);
    const auto id = doc.insert(on);
    doc.insert(nfcad::document::make_entity(cubic()));  // off already
    c = create_command(QStringLiteral("poff"));
    c->setDocument(&doc);
    QVERIFY(c->begin({}));
    QCOMPARE(c->finish(), R::Done);
    edit = c->takeEdit();
    QCOMPARE(edit.attributes.size(), std::size_t{1});
    QCOMPARE(edit.attributes[0].first, id);
    QVERIFY(!edit.attributes[0].second.contains(QString::fromLatin1(kPointsOnKey)));
    const auto sel = c->takeSelection();
    QVERIFY(sel && sel->empty());
    // applied and undone through the document
    doc.apply(std::move(edit), QStringLiteral("Points off"));
    QVERIFY(!doc.entity(id)->attributes.contains(QString::fromLatin1(kPointsOnKey)));
    doc.undoStack()->undo();
    QVERIFY(doc.entity(id)->attributes.value(QString::fromLatin1(kPointsOnKey)).toBool());
  }

  void selectPoints() {
    nfcad::document::Document doc;
    const auto id = doc.insert(curve_entity(0, true));
    doc.insert(nfcad::document::make_entity(cubic()));
    auto c = create_command(QStringLiteral("selpoints"));
    c->setDocument(&doc);
    QVERIFY(c->begin({}));
    QCOMPARE(c->finish(), R::Done);
    const auto sel = c->takeSelection();
    QVERIFY(sel);
    QCOMPARE(sel->size(), std::size_t{4});
    QCOMPARE(sel->at(2), (nfcad::document::SelectionItem{id, {SubElement::Kind::ControlPoint, 2}}));
  }

  void moveRotateScaleGrips() {
    const Entity e = curve_entity(7, true);
    auto c = create_command(QStringLiteral("move"));
    QVERIFY(c->usesGrips());
    c->setGrips({GripSet{7, e.geometry, {1, 2}}});
    QVERIFY(c->begin({}));  // only grips selected
    c->point({0, 0, 0}, kTop);
    QVERIFY(c->preview({0, 2, 0}, kTop).size() >= 2);  // the moved curve and its polygon
    QCOMPARE(c->point({0, 2, 0}, kTop), R::Done);
    auto edit = c->takeEdit();
    QCOMPARE(edit.replace.size(), std::size_t{1});
    const auto moved = geometry(edit.replace[0]);
    QVERIFY(nf::distance(moved.control_points()[0], {0, 0, 0}) < 1e-12);  // not selected: stays
    QVERIFY(nf::distance(moved.control_points()[1], {1, 3, 0}) < 1e-12);
    QVERIFY(nf::distance(moved.control_points()[2], {2, 1, 0}) < 1e-12);
    // the curve selected as a whole too: it moves once, as a whole
    c = create_command(QStringLiteral("move"));
    c->setGrips({GripSet{7, e.geometry, {1}}});
    QVERIFY(c->begin({e}));
    c->point({0, 0, 0}, kTop);
    c->point({1, 0, 0}, kTop);
    edit = c->takeEdit();
    QCOMPARE(edit.replace.size(), std::size_t{1});
    QVERIFY(nf::distance(geometry(edit.replace[0]).control_points()[0], {1, 0, 0}) < 1e-12);
    // Scale about the origin by 2: the grip only
    c = create_command(QStringLiteral("scale"));
    c->setGrips({GripSet{7, e.geometry, {3}}});
    QVERIFY(c->begin({}));
    c->point({0, 0, 0}, kTop);
    QCOMPARE(c->number(2), R::Done);
    edit = c->takeEdit();
    QVERIFY(nf::distance(geometry(edit.replace[0]).control_points()[3], {6, 0, 0}) < 1e-12);
    // Copy does not take grips
    QVERIFY(!create_command(QStringLiteral("copy"))->usesGrips());
  }

  void weightOfControlPoints() {
    const Entity e = curve_entity(4, true);
    auto c = create_command(QStringLiteral("weight"));
    QVERIFY(!c->begin({e}));  // a whole curve: select its control points
    c = create_command(QStringLiteral("weight"));
    c->setGrips({GripSet{4, e.geometry, {1}}});
    QVERIFY(c->begin({}));
    QCOMPARE(c->number(0), R::Rejected);
    QCOMPARE(c->number(3), R::Done);
    const auto w = geometry(c->takeEdit().replace[0]);
    QVERIFY(w.is_rational());
    QCOMPARE(w.weights()[1], 3.0);
    QCOMPARE(w.weights()[0], 1.0);
    // a heavier control point pulls the curve towards it
    QVERIFY(nf::closest_point(w, {1, 1, 0}).distance < nf::closest_point(cubic(), {1, 1, 0}).distance);
  }
};

QTEST_GUILESS_MAIN(TestGrips)
#include "test_grips.moc"
