// Layers (current layer, lock, delete), the undo steps of layers and group names, and the
// modified state of visibility changes.
#include <QApplication>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPushButton>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QTreeWidget>
#include <functional>
#include <nurbforge/nurbforge.hpp>

#include "document/document.hpp"
#include "document/nfcad_io.hpp"
#include "document/selection.hpp"
#include "render/scene.hpp"
#include "tessellation/tessellation_service.hpp"
#include "ui/layer_panel.hpp"

using nfcad::document::Document;
using nfcad::document::Entity;
using nfcad::document::EntityId;
using nfcad::document::GroupId;
using nfcad::document::Layer;
using nfcad::document::LayerContents;
using nfcad::document::LayerId;
using nfcad::document::make_entity;
using nfcad::document::Selection;

namespace {
std::vector<EntityId> two(Document& doc) {
  return doc.addEntities({make_entity(nf::Vec3{0, 0, 0}, QStringLiteral("a")),
                          make_entity(nf::Vec3{1, 0, 0}, QStringLiteral("b"))},
                         QStringLiteral("add"));
}

Layer layer(const QString& name, QColor color = QColor(Qt::red)) { return {0, name, std::move(color), true}; }
}  // namespace

class TestLayers : public QObject {
  Q_OBJECT
 private slots:
  void newRenameRecolourAreUndoSteps() {
    Document doc;
    const LayerId l = doc.addLayer(layer(QStringLiteral("L1")));
    QVERIFY(l != 0);
    QVERIFY(doc.isModified());
    QCOMPARE(doc.undoStack()->count(), 1);
    doc.renameLayer(l, QStringLiteral("Optics"));
    doc.setLayerColor(l, QColor(Qt::blue));
    QCOMPARE(doc.undoStack()->count(), 3);
    QCOMPARE(doc.layer(l)->name, QStringLiteral("Optics"));
    QCOMPARE(doc.layer(l)->color, QColor(Qt::blue));

    doc.undoStack()->undo();
    QCOMPARE(doc.layer(l)->color, QColor(Qt::red));
    doc.undoStack()->undo();
    QCOMPARE(doc.layer(l)->name, QStringLiteral("L1"));
    doc.undoStack()->undo();
    QVERIFY(doc.layer(l) == nullptr);
    QVERIFY(!doc.isModified());  // back where it started
    doc.undoStack()->redo();
    QCOMPARE(doc.layer(l)->name, QStringLiteral("L1"));  // the same id again
    // nothing changed: no undo step
    const int n = doc.undoStack()->count();
    doc.renameLayer(l, QStringLiteral("L1"));
    doc.renameLayer(l, QString());  // empty names are not taken
    QCOMPARE(doc.undoStack()->count(), n);
  }

  void groupRenameIsAnUndoStep() {
    Document doc;
    const auto ids = two(doc);
    const GroupId g = doc.groupEntities(ids, QStringLiteral("parts"));
    doc.markSaved();
    doc.renameGroup(g, QStringLiteral("optics"));
    QCOMPARE(doc.group(g)->name, QStringLiteral("optics"));
    QVERIFY(doc.isModified());
    doc.undoStack()->undo();
    QCOMPARE(doc.group(g)->name, QStringLiteral("parts"));
    QVERIFY(!doc.isModified());
  }

  void visibilityMarksTheDocumentModified() {
    // visibility, lock and the current layer are saved with the document: no undo steps, but
    // closing asks to save
    Document doc;
    const auto ids = two(doc);
    const GroupId g = doc.groupEntities({ids[0]}, QStringLiteral("g"));
    const LayerId l = doc.addLayer(layer(QStringLiteral("L1")));
    doc.markSaved();
    const int steps = doc.undoStack()->count();
    auto check = [&](const char* what, const std::function<void()>& change) {
      doc.markSaved();
      QSignalSpy modified(&doc, &Document::modificationChanged);
      change();
      QVERIFY2(doc.isModified(), what);
      QVERIFY2(modified.count() >= 1, what);
      QCOMPARE(doc.undoStack()->count(), steps);
    };
    check("layer hidden", [&] { doc.setLayerVisible(l, false); });
    check("layer locked", [&] { doc.setLayerLocked(l, true); });
    check("current layer", [&] { doc.setCurrentLayer(l); });
    check("object hidden", [&] { doc.setEntityVisible(ids[1], false); });
    check("unhide", [&] { QCOMPARE(doc.showHiddenEntities(), std::size_t{1}); });
    check("group hidden", [&] { doc.setGroupVisible(g, false); });
    check("isolate", [&] { doc.isolate({ids[1]}); });
    check("show all", [&] { doc.showAll(); });
    // no change: not modified
    doc.markSaved();
    doc.showAll();
    doc.setLayerVisible(l, true);
    doc.setEntityVisible(ids[0], true);
    QVERIFY(!doc.isModified());
  }

  void newObjectsGoToTheCurrentLayer() {
    Document doc;
    QCOMPARE(doc.currentLayer(), LayerId{0});
    const LayerId l = doc.addLayer(layer(QStringLiteral("L1")));
    doc.setCurrentLayer(l);
    // drawn (commands: addEntities / apply)
    const auto ids = two(doc);
    QCOMPARE(doc.entity(ids[0])->layer, l);
    nfcad::document::Edit edit;
    edit.add.push_back(make_entity(nf::Vec3{2, 0, 0}));
    Entity kept = make_entity(nf::Vec3{3, 0, 0});
    kept.layer = 0;  // a result that keeps the layer of its source (Boolean)
    edit.add.push_back(kept);
    const auto added = doc.apply(std::move(edit), QStringLiteral("edit"));
    QCOMPARE(doc.entity(added[0])->layer, l);
    QCOMPARE(doc.entity(added[1])->layer, LayerId{0});
    // made by a plugin (live insert)
    const EntityId live = doc.insert(make_entity(nf::Vec3{4, 0, 0}));
    QCOMPARE(doc.entity(live)->layer, l);
    // undo / redo puts objects back on the layer they were made on
    doc.setCurrentLayer(0);
    doc.undoStack()->undo();
    doc.undoStack()->undo();
    doc.undoStack()->redo();
    QCOMPARE(doc.entity(ids[1])->layer, l);
    // a deleted current layer falls back to Default
    QVERIFY(doc.removeLayer(l, LayerContents::MoveToDefault));
    QCOMPARE(doc.entity(ids[1])->layer, LayerId{0});
    QCOMPARE(doc.currentLayer(), LayerId{0});
  }

  void deleteLayer() {
    Document doc;
    const LayerId keep = doc.addLayer(layer(QStringLiteral("keep")));
    const LayerId l = doc.addLayer(layer(QStringLiteral("doomed"), QColor(Qt::green)));
    const LayerId after = doc.addLayer(layer(QStringLiteral("after")));
    doc.setCurrentLayer(l);
    const auto ids = two(doc);
    QCOMPARE(doc.entityCount(l), std::size_t{2});
    QVERIFY(!doc.removeLayer(0, LayerContents::MoveToDefault));  // Default stays
    QVERIFY(!doc.removeLayer(99, LayerContents::MoveToDefault));

    // objects to Default: one undo step for both
    const int steps = doc.undoStack()->count();
    QVERIFY(doc.removeLayer(l, LayerContents::MoveToDefault));
    QCOMPARE(doc.undoStack()->count(), steps + 1);
    QVERIFY(doc.layer(l) == nullptr);
    QCOMPARE(doc.entity(ids[0])->layer, LayerId{0});
    QCOMPARE(doc.displayColor(*doc.entity(ids[0])), doc.layer(0)->color);
    doc.undoStack()->undo();
    QCOMPARE(doc.layers()[2].id, l);  // in its place again
    QCOMPARE(doc.layers()[3].id, after);
    QCOMPARE(doc.entity(ids[0])->layer, l);
    QCOMPARE(doc.displayColor(*doc.entity(ids[0])), QColor(Qt::green));
    QCOMPARE(doc.currentLayer(), l);

    // objects deleted
    QVERIFY(doc.removeLayer(l, LayerContents::Delete));
    QVERIFY(doc.entity(ids[0]) == nullptr && doc.entity(ids[1]) == nullptr);
    QVERIFY(doc.layer(keep) != nullptr);
    doc.undoStack()->undo();
    QVERIFY(doc.entity(ids[0]) != nullptr);
    QCOMPARE(doc.entity(ids[1])->layer, l);
    doc.undoStack()->redo();
    QVERIFY(doc.entity(ids[0]) == nullptr);
  }

  void lockedObjectsCannotBeSelected() {
    Document doc;
    Selection selection;
    selection.attach(&doc);
    nfcad::tessellation::TessellationService service;
    nfcad::render::Scene scene(&doc, &service);
    const LayerId l = doc.addLayer(layer(QStringLiteral("frame")));
    doc.setCurrentLayer(l);
    const auto ids = two(doc);
    selection.apply({{ids[0], {}}, {ids[1], {}}}, Selection::Mode::Replace);
    QCOMPARE(selection.entities().size(), std::size_t{2});

    doc.setLayerLocked(l, true);  // what was selected leaves the selection
    QVERIFY(selection.empty());
    QVERIFY(doc.isLocked(ids[0]));
    QVERIFY(doc.isDisplayed(*doc.entity(ids[0])));  // still shown
    QVERIFY(scene.items().at(ids[0]).locked);
    selection.apply({{ids[0], {}}}, Selection::Mode::Replace);
    QVERIFY(selection.empty());
    selection.apply({{ids[0], {}}}, Selection::Mode::Toggle);
    QVERIFY(selection.empty());

    doc.setLayerLocked(l, false);
    QVERIFY(!scene.items().at(ids[0]).locked);
    selection.apply({{ids[0], {}}}, Selection::Mode::Replace);
    QCOMPARE(selection.entities().size(), std::size_t{1});
    // moved to a locked layer: out of the selection
    const LayerId locked = doc.addLayer(layer(QStringLiteral("locked")));
    doc.setLayerLocked(locked, true);
    doc.assignLayer({ids[0]}, locked);
    QVERIFY(selection.empty());
  }

  void savedWithTheDocument() {
    QTemporaryDir dir;
    const QString path = dir.filePath(QStringLiteral("layers.rttf"));
    Document doc;
    const LayerId l = doc.addLayer(layer(QStringLiteral("locked")));
    const LayerId c = doc.addLayer(layer(QStringLiteral("current")));
    doc.setLayerLocked(l, true);
    doc.setCurrentLayer(c);
    two(doc);
    QVERIFY(nfcad::document::save_nfcad(doc, path).isEmpty());

    Document back;
    QJsonObject extra;
    QCOMPARE(nfcad::document::load_nfcad(back, path, &extra), QString());
    QVERIFY(back.layer(l)->locked);
    QVERIFY(!back.layer(c)->locked);
    QCOMPARE(back.currentLayer(), c);
    QVERIFY(!back.isModified());
    QVERIFY(!extra.contains(QStringLiteral("current_layer")));  // the document's own section

    // files without the keys (before) and with an unknown current layer still load
    const QString old = dir.filePath(QStringLiteral("old.rttf"));
    QFile f(old);
    QVERIFY(f.open(QIODevice::WriteOnly));
    const QJsonObject file{
        {"format", "nfcad"}, {"version", 2}, {"units", "mm"}, {"current_layer", 7},
        {"layers", QJsonArray{QJsonObject{{"id", 0}, {"name", "Default"}, {"color", "#bec6d2"}, {"visible", true}},
                              QJsonObject{{"id", 1}, {"name", "L"}, {"color", "#ff0000"}, {"visible", true}}}},
        {"entities", QJsonArray{QJsonObject{{"id", "3"}, {"name", "p"}, {"layer", 1}, {"visible", true},
                                            {"geometry", QJsonObject{{"type", "point"}, {"point", QJsonArray{1, 2, 3}}}}}}}};
    f.write(QJsonDocument(file).toJson());
    f.close();
    Document before;
    QCOMPARE(nfcad::document::load_nfcad(before, old), QString());
    QCOMPARE(before.currentLayer(), LayerId{0});
    QVERIFY(!before.layer(1)->locked);
    QCOMPARE(before.entity(3)->layer, LayerId{1});

    // an unlocked layer and the Default current layer write nothing new (older readers)
    Document plain;
    two(plain);
    QVERIFY(nfcad::document::save_nfcad(plain, path).isEmpty());
    QFile written(path);
    QVERIFY(written.open(QIODevice::ReadOnly));
    const QJsonObject root = QJsonDocument::fromJson(written.readAll()).object();
    QVERIFY(!root.contains(QStringLiteral("current_layer")));
    QVERIFY(!root["layers"].toArray()[0].toObject().contains(QStringLiteral("locked")));
  }

  void panel() {
    Document doc;
    Selection selection;
    selection.attach(&doc);
    nfcad::ui::LayerPanel panel(&doc, &selection);
    auto* tree = panel.findChild<QTreeWidget*>();
    auto* add = panel.findChild<QPushButton*>(QStringLiteral("newLayer"));
    auto* remove = panel.findChild<QPushButton*>(QStringLiteral("deleteLayer"));
    auto* current = panel.findChild<QPushButton*>(QStringLiteral("makeCurrent"));
    QVERIFY(tree != nullptr && add != nullptr && remove != nullptr && current != nullptr);

    add->click();  // an undo step
    QCOMPARE(tree->topLevelItemCount(), 2);
    QCOMPARE(doc.undoStack()->count(), 1);
    const auto l = static_cast<LayerId>(doc.layers()[1].id);

    tree->setCurrentItem(tree->topLevelItem(0));
    QVERIFY(!remove->isEnabled());  // Default cannot be deleted
    QVERIFY(!current->isEnabled());  // it is the current layer
    QVERIFY(tree->topLevelItem(0)->font(0).bold());

    tree->setCurrentItem(tree->topLevelItem(1));
    QVERIFY(remove->isEnabled() && current->isEnabled());
    current->click();
    QCOMPARE(doc.currentLayer(), l);
    QVERIFY(tree->topLevelItem(1)->font(0).bold());
    const auto ids = two(doc);
    QCOMPARE(doc.entity(ids[0])->layer, l);

    // lock by the check box of the second column
    QVERIFY(tree->model()->setData(tree->model()->index(1, 1), Qt::Checked, Qt::CheckStateRole));
    QTRY_VERIFY(doc.layer(l)->locked);
    // rename by editing the name
    tree->topLevelItem(1)->setText(0, QStringLiteral("Mounts"));
    QTRY_COMPARE(doc.layer(l)->name, QStringLiteral("Mounts"));

    // delete: the panel asks what happens to the objects
    QString asked;
    panel.ask_contents = [&asked](const QString& name, std::size_t n, LayerContents* contents) {
      asked = QStringLiteral("%1:%2").arg(name).arg(n);
      *contents = LayerContents::MoveToDefault;
      return true;
    };
    tree->setCurrentItem(tree->topLevelItem(1));
    remove->click();
    QCOMPARE(asked, QStringLiteral("Mounts:2"));
    QVERIFY(doc.layer(l) == nullptr);
    QCOMPARE(tree->topLevelItemCount(), 1);
    QCOMPARE(doc.entity(ids[0])->layer, LayerId{0});
    doc.undoStack()->undo();
    QCOMPARE(tree->topLevelItemCount(), 2);
    QCOMPARE(doc.entity(ids[0])->layer, l);
    // cancelled: nothing happens
    panel.ask_contents = [](const QString&, std::size_t, LayerContents*) { return false; };
    tree->setCurrentItem(tree->topLevelItem(1));
    remove->click();
    QVERIFY(doc.layer(l) != nullptr);
  }
};

QTEST_MAIN(TestLayers)
#include "test_layers.moc"
