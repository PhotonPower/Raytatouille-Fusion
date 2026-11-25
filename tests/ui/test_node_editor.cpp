#include <QApplication>
#include <QDialog>
#include <QLineEdit>
#include <QTimer>
#include <QFile>
#include <QGraphicsRectItem>
#include <QGraphicsTextItem>
#include <QImage>
#include <QJsonArray>
#include <QListWidget>
#include <QMenu>
#include <QTabWidget>
#include <QKeyEvent>
#include <QJsonDocument>
#include <QLineF>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QWheelEvent>

#include <cmath>

#include "document/document.hpp"
#include "document/nfcad_io.hpp"
#include "ui/branch_panel.hpp"
#include "ui/node_editor.hpp"

using nfcad::ui::NodeEditor;

namespace {
QJsonObject linnik() {
  // an old socket graph (version 1), made by RTT-Fusion from its Linnik structure
  // (graph_from_raytatouille + catalogue): CAD converts such a workflow when it opens it
  QFile f(QStringLiteral(NFCAD_TEST_DATA "/workflow_linnik.json"));
  if (!f.open(QIODevice::ReadOnly)) return {};
  return QJsonDocument::fromJson(f.readAll()).object();
}

QJsonObject model_linnik() {
  // made by the Raytracer plugin from RTT-Fusion's Linnik structure (R24: model, branches)
  QFile f(QStringLiteral(NFCAD_TEST_DATA "/workflow_model_linnik.json"));
  if (!f.open(QIODevice::ReadOnly)) return {};
  return QJsonDocument::fromJson(f.readAll()).object();
}

QJsonObject node(const QJsonObject& wf, const QString& id) {
  for (const QJsonValue& v : wf["model"].toObject()["nodes"].toArray()) {
    if (v.toObject()["id"].toString() == id) return v.toObject();
  }
  return {};
}
}  // namespace

class TestNodeEditor : public QObject {
  Q_OBJECT
 private slots:
  void oldGraphIsANote() {
    // an old socket graph (version 1) that was not converted into a model: a note instead of the
    // blocks, and no edit (no model beside it) – CAD converts it when it opens the document
    NodeEditor e;
    e.setWorkflow(linnik());
    QVERIFY(e.oldGraph() && !e.modelMode());
    QVERIFY(e.nodeItem(QStringLiteral("Sample")) == nullptr);
    bool note = false;
    for (QGraphicsItem* item : e.scene()->items()) {
      if (auto* t = dynamic_cast<QGraphicsTextItem*>(item)) note = note || t->toPlainText().contains(QStringLiteral("version 1"));
    }
    QVERIFY(note);
    QSignalSpy edited(&e, &NodeEditor::edited);
    e.addNode(QStringLiteral("rtt.detector"), QPointF(0, 0));
    e.setMuted(QStringLiteral("Sample"), true);
    QCOMPARE(edited.count(), 0);
    QCOMPARE(e.workflow(), linnik());
  }

  void editing() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    QSignalSpy edited(&e, &NodeEditor::edited);
    // a new detector from the catalogue, with the type's default parameters
    const QString det = e.addNode(QStringLiteral("rtt.detector"), QPointF(100, 300));
    QCOMPARE(node(e.workflow(), det)["params"].toObject()["pixels"].toInt(), 512);
    // mute, then remove the sample: its connection goes with it
    e.setMuted(QStringLiteral("Sample"), true);
    QVERIFY(node(e.workflow(), QStringLiteral("Sample"))["muted"].toBool());
    e.removeNode(QStringLiteral("Sample"));
    QCOMPARE(e.connectionCount(), 8);
    QVERIFY(e.nodeItem(QStringLiteral("Sample")) == nullptr);
    QCOMPARE(edited.count(), 3);  // addNode, mute, remove
    // a new workflow is a model (version 2)
    NodeEditor fresh;
    fresh.setWorkflow(QJsonObject{{"types", model_linnik()["types"]}});
    fresh.addNode(QStringLiteral("rtt.source"), QPointF(0, 0));
    QVERIFY(fresh.modelMode() && !fresh.workflow().contains(QStringLiteral("graph")));
    QCOMPARE(fresh.workflow()["model"].toObject()["version"].toInt(), 2);
  }

  void diagnosticsAreMarked() {
    QJsonObject wf = model_linnik();
    wf["diagnostics"] = QJsonArray{QJsonObject{{"code", "graph.cycle"}, {"severity", "error"},
                                               {"message", "feedback"}, {"location", "Sample.Objective_A"}}};
    NodeEditor e;
    e.setWorkflow(wf);
    QVERIFY(e.nodeItem(QStringLiteral("Sample"))->pen().widthF() > 2.0);
    QVERIFY(e.nodeItem(QStringLiteral("Sample"))->toolTip().contains(QStringLiteral("graph.cycle")));
    QVERIFY(e.nodeItem(QStringLiteral("Camera"))->pen().widthF() < 2.0);
    // an edit makes the diagnostics stale
    e.setMuted(QStringLiteral("Camera"), true);
    QVERIFY(!e.workflow().contains("diagnostics"));
  }

  void planIsShown() {
    // the planner's conversions per block (RTT-Fusion R17) and the warnings of the last run at the
    // block (R30); the representations per connection: connectionDirections
    QJsonObject wf = model_linnik();
    QJsonObject plan = wf["plan"].toObject();
    plan["conversions"] = QJsonArray{QJsonObject{{"node", "Sample"}, {"from", "a"}, {"to", "b"}, {"chain", "HR"},
                                                 {"operators", QJsonArray{"field_to_rays"}}}};
    plan["node_notes"] = QJsonObject{{"Sample", QJsonArray{"exec.spectrum_rays: the orders overlap"}}};
    wf["plan"] = plan;
    NodeEditor e;
    e.setWorkflow(wf);
    QVERIFY(e.nodeItem(QStringLiteral("Sample"))->toolTip().contains(QStringLiteral("a → b: HR (field_to_rays)")));
    QVERIFY(e.nodeItem(QStringLiteral("Sample"))->toolTip().contains(QStringLiteral("exec.spectrum_rays: the orders overlap")));
    // an edit makes the plan stale: it stays visible, grey, until the next check
    e.setMuted(QStringLiteral("Sample"), true);
    QVERIFY(e.workflow()["plan"].toObject()["stale"].toBool());
  }

  void transportMenuOffersWhatRuns() {
    // the transports with what they are; those the installation cannot compute are disabled
    QJsonObject wf = model_linnik();
    wf["available"] = QJsonArray{"H", "R", "S"};
    NodeEditor e;
    e.setWorkflow(wf);
    QVERIFY(e.transportOffered(QStringLiteral("auto")) && e.transportOffered(QStringLiteral("S")));
    QVERIFY(!e.transportOffered(QStringLiteral("G")) && !e.transportOffered(QStringLiteral("P")));
    QMenu menu;
    QString chosen;
    e.addTransportActions(&menu, QStringLiteral("S"), [&chosen](const QString& t) { chosen = t; });
    const QList<QAction*> actions = menu.actions();
    QCOMPARE(actions.size(), 7);
    QStringList letters;
    for (QAction* a : actions) letters << a->data().toString();
    QCOMPARE(letters, (QStringList{"auto", "R", "H", "S", "G", "T", "P"}));
    QAction* s = actions[3];
    QCOMPARE(s->text(), QStringLiteral("S – plane-wave spectra"));
    QVERIFY(s->isEnabled() && s->isChecked() && !actions[0]->isChecked());
    QVERIFY(!actions[4]->isEnabled() && actions[4]->toolTip().contains(QStringLiteral("not computed")));
    s->trigger();
    QCOMPARE(chosen, QStringLiteral("S"));
    // a connection set to S (both directions) through the editor
    e.setConnectionTransport(0, QStringLiteral("both"), chosen);
    QCOMPARE(e.workflow()["model"].toObject()["connections"].toArray()[0].toObject()["transport"].toString(), QStringLiteral("S"));
    // without fieldtracing only R (and auto); a document without the list offers everything
    wf["available"] = QJsonArray{"R"};
    e.setWorkflow(wf);
    QVERIFY(!e.transportOffered(QStringLiteral("H")) && !e.transportOffered(QStringLiteral("S")));
    wf.remove(QStringLiteral("available"));
    e.setWorkflow(wf);
    QVERIFY(e.transportOffered(QStringLiteral("S")) && e.transportOffered(QStringLiteral("T")));
  }

  void replaceAndParameters() {
    // concept 1: the sample mirror becomes a FourierGrating sample; its parameters directly and
    // through the dialog (the ports: modelReplaceKeepsPorts)
    NodeEditor e;
    e.setWorkflow(model_linnik());
    QVERIFY(e.replacementsFor(QStringLiteral("Sample")).contains(QStringLiteral("fusion.grating")));
    QSignalSpy edited(&e, &NodeEditor::edited);
    QVERIFY(e.replaceNode(QStringLiteral("Sample"), QStringLiteral("fusion.grating")));
    QCOMPARE(edited.count(), 1);
    QCOMPARE(e.connectionCount(), 9);
    const QJsonObject sample = node(e.workflow(), QStringLiteral("Sample"));
    QCOMPARE(sample["type"].toString(), QStringLiteral("fusion.grating"));
    QVERIFY(sample["params"].toObject().contains(QStringLiteral("table")));
    e.setParams(QStringLiteral("Sample"), QJsonObject{{"table", "/tmp/grating.json"}, {"orders", QJsonArray{-1, 0, 1}}});
    QCOMPARE(node(e.workflow(), QStringLiteral("Sample"))["params"].toObject()["table"].toString(), QStringLiteral("/tmp/grating.json"));
    QTimer::singleShot(0, &e, [] {
      for (QWidget* w : QApplication::topLevelWidgets()) {
        auto* d = qobject_cast<QDialog*>(w);
        if (d == nullptr || !d->isVisible()) continue;
        for (QLineEdit* line : d->findChildren<QLineEdit*>()) {
          if (line->text() == QStringLiteral("/tmp/grating.json")) line->setText(QStringLiteral("/tmp/other.json"));
        }
        d->accept();
      }
    });
    e.editParams(QStringLiteral("Sample"));
    const QJsonObject p = node(e.workflow(), QStringLiteral("Sample"))["params"].toObject();
    QCOMPARE(p["table"].toString(), QStringLiteral("/tmp/other.json"));
    QCOMPARE(p["orders"].toArray(), (QJsonArray{-1, 0, 1}));
  }

  void connectionsCanBeHit() {
    // a connection is hit on its curve (right-click: transport), not on the empty canvas
    NodeEditor e;
    e.resize(1500, 420);
    e.setAttribute(Qt::WA_DontShowOnScreen);
    e.setWorkflow(model_linnik());
    e.show();
    e.fitAll();
    auto* connection = e.connectionItem(0);
    QVERIFY(connection != nullptr);
    const QPoint at = e.mapFromScene(connection->path().pointAtPercent(0.5));
    QCOMPARE(e.connectionAt(at), 0);
    QCOMPARE(e.connectionAt(QPoint(5, 5)), -1);
  }

  void displayBlocksAndRunning() {
    QJsonObject wf = model_linnik();
    QJsonObject g = wf["model"].toObject();
    QJsonArray nodes = g["nodes"].toArray();
    nodes.append(QJsonObject{{"id", "show"}, {"type", "display.image"}, {"name", "Camera window"}, {"position", QJsonArray{0, 600}}});
    g["nodes"] = nodes;
    wf["model"] = g;
    NodeEditor e;
    e.resize(1500, 600);
    e.setAttribute(Qt::WA_DontShowOnScreen);
    e.setWorkflow(wf);
    e.show();
    e.fitAll();
    QSignalSpy requested(&e, &NodeEditor::displayRequested);
    const QPoint at = e.mapFromScene(e.nodeItem(QStringLiteral("show"))->sceneBoundingRect().center());
    QTest::mouseDClick(e.viewport(), Qt::LeftButton, {}, at);
    QCOMPARE(requested.count(), 1);
    QCOMPARE(requested.at(0).at(0).toString(), QStringLiteral("show"));
    QCOMPARE(requested.at(0).at(1).toString(), QStringLiteral("display.image"));
    // the running block: a bright, wide frame
    e.setRunning(QStringLiteral("Sample"));
    QVERIFY(e.nodeItem(QStringLiteral("Sample"))->pen().widthF() >= 3.0);
    e.setRunning({});
    QVERIFY(e.nodeItem(QStringLiteral("Sample"))->pen().widthF() < 2.0);
  }

  void upToDateMarks() {
    // green tick / red cross: an edit marks the block and everything behind it on its branches
    // out of date
    NodeEditor e;
    e.setWorkflow(model_linnik());
    QJsonObject all;
    for (const QJsonValue& v : e.workflow()["model"].toObject()["nodes"].toArray()) all[v.toObject()["id"].toString()] = true;
    e.setStates(all);
    QCOMPARE(e.state(QStringLiteral("Sample")), 1);
    e.setParams(QStringLiteral("Sample"), QJsonObject{{"offset", QJsonArray{0, 0, 0.001}}});
    for (const char* stale : {"Sample", "Objective_A", "Beam_splitter", "Camera", "Pupil_camera"}) {
      QCOMPARE(e.state(QString::fromLatin1(stale)), 0);
    }
    QCOMPARE(e.state(QStringLiteral("source")), 1);  // in front of the change
    QCOMPARE(e.state(QStringLiteral("Illumination_stop")), 1);
    // moving a block changes nothing
    QJsonObject g = e.workflow()["model"].toObject();
    e.setStates(all);
    QJsonArray nodes = g["nodes"].toArray();
    QJsonObject n0 = nodes[0].toObject();
    n0["position"] = QJsonArray{999, 999};
    nodes[0] = n0;
    g["nodes"] = nodes;
    QJsonObject wf = e.workflow();
    wf["model"] = g;
    e.setWorkflow(wf);  // not an edit
    e.setStates(all);
    e.setMuted(QStringLiteral("Reference"), true);
    QCOMPARE(e.state(QStringLiteral("Reference")), 0);
    QCOMPARE(e.state(QStringLiteral("Illumination_stop")), 1);  // in front of the reference arm
    e.setStates({});
    QCOMPARE(e.state(QStringLiteral("Sample")), -1);
  }

  // ---------------------------------------------------------------- model (RTT-Fusion R24)

  void modelShowsPorts() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    QVERIFY(e.modelMode());
    QCOMPARE(e.connectionCount(), 9);  // one per pair of neighbours (13 directed links before)
    QCOMPARE(e.linkCount(), 0);        // no data links yet
    for (int k = 0; k < 9; ++k) QVERIFY(e.connectionItem(k) != nullptr);
    // the objective: one point per port, light comes in from the splitter (left), the sample right
    QVERIFY(e.portOnLeft(QStringLiteral("Objective_A"), QStringLiteral("Beam_splitter")));
    QVERIFY(!e.portOnLeft(QStringLiteral("Objective_A"), QStringLiteral("Sample")));
    QCOMPARE(e.branchNames(), (QStringList{"measurement", "reference", "measurement_pupil"}));
    if (const QByteArray dir = qgetenv("NFCAD_SNAPSHOT_DIR"); !dir.isEmpty()) {
      e.resize(1400, 700);
      e.highlightBranch(QStringLiteral("measurement"));
      e.fitAll();
      e.grab().toImage().save(QString::fromLocal8Bit(dir) + QStringLiteral("/node_editor_model.png"));
      e.scene()->clearSelection();
      for (const char* id : {"Beam_splitter", "Objective_A", "Sample", "Objective_B"}) e.nodeItem(QString::fromLatin1(id))->setSelected(true);
      e.zoomSelected();
      e.grab().toImage().save(QString::fromLocal8Bit(dir) + QStringLiteral("/node_editor_model_zoom.png"));
    }
  }

  void connectionsFollowMovedBlocks() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    int index = -1;  // the connection objective A – sample
    const QJsonArray connections = e.workflow()["model"].toObject()["connections"].toArray();
    for (int k = 0; k < connections.size(); ++k) {
      if (connections[k].toObject()["ports"].toArray().contains(QJsonArray{"Sample", "Objective_A"})) index = k;
    }
    QVERIFY(index >= 0);
    const QPointF end_before = e.connectionItem(index)->path().pointAtPercent(1.0);
    const QPointF start_before = e.connectionItem(index)->path().pointAtPercent(0.0);
    e.nodeItem(QStringLiteral("Sample"))->moveBy(80.0, 120.0);  // as a drag does
    const QPointF end = e.connectionItem(index)->path().pointAtPercent(1.0);
    const QPointF start = e.connectionItem(index)->path().pointAtPercent(0.0);
    // the end at the sample moved with it, the end at the objective stayed
    const bool sample_last = QLineF(end, end_before + QPointF(80.0, 120.0)).length() < 1e-6;
    const bool sample_first = QLineF(start, start_before + QPointF(80.0, 120.0)).length() < 1e-6;
    QVERIFY(sample_last || sample_first);
    QVERIFY(sample_last ? QLineF(start, start_before).length() < 1e-6 : QLineF(end, end_before).length() < 1e-6);
  }

  void connectionDirections() {
    // per direction a branch uses: an arrow and the planned representation; the tooltip names
    // the blocks; after an edit the plan stays, marked out of date
    NodeEditor e;
    e.setWorkflow(model_linnik());
    auto index_of = [&e](const QJsonArray& a, const QJsonArray& b) {
      const QJsonArray connections = e.workflow()["model"].toObject()["connections"].toArray();
      for (int k = 0; k < connections.size(); ++k) {
        const QJsonArray ends = connections[k].toObject()["ports"].toArray();
        if (ends.contains(a) && ends.contains(b)) return k;
      }
      return -1;
    };
    auto arrows = [&e](int k) {
      QStringList out;
      for (QGraphicsItem* child : e.connectionItem(k)->childItems()) {
        for (QGraphicsItem* t : child->childItems()) {
          if (auto* text = dynamic_cast<QGraphicsSimpleTextItem*>(t)) out << text->text();
        }
      }
      return out;
    };
    const int both = index_of(QJsonArray{"Objective_A", "Sample"}, QJsonArray{"Sample", "Objective_A"});
    const int one = index_of(QJsonArray{"source", "Illumination_stop"}, QJsonArray{"Illumination_stop", "source"});
    QVERIFY(both >= 0 && one >= 0);
    QStringList two = arrows(both);
    QCOMPARE(two.size(), 2);  // there and back to the sample
    QVERIFY(two.join(QLatin1Char(' ')).contains(QStringLiteral("▶")) && two.join(QLatin1Char(' ')).contains(QStringLiteral("◀")));
    QCOMPARE(arrows(one).size(), 1);  // the source only sends
    QVERIFY(e.connectionItem(both)->toolTip().contains(QStringLiteral("Objective A → Sample: R")));
    QVERIFY(e.connectionItem(both)->toolTip().contains(QStringLiteral("Sample → Objective A: R")));
    e.setParams(QStringLiteral("Sample"), QJsonObject{{"offset", QJsonArray{0, 0, 0.001}}});
    QVERIFY(e.connectionItem(both)->toolTip().contains(QStringLiteral("(out of date)")));
    QCOMPARE(arrows(both).size(), 2);  // still shown
    // what the last run carried, its conversions and warnings per direction (R30e)
    QJsonObject wf = e.workflow();
    QJsonObject plan = wf["plan"].toObject();
    plan.remove(QStringLiteral("stale"));
    const QString c = QString::number(both);
    plan["connections_used"] = QJsonObject{{c, QJsonObject{{"forward", "S"}}}};
    plan["connections_used_reason"] = QJsonObject{{c, QJsonObject{{"forward", "S – toS gave spectra"}}}};
    plan["connections_notes"] = QJsonObject{{c, QJsonObject{{"forward", QJsonArray{"exec.spectrum_cut: 3e-3"}}}}};
    wf["plan"] = plan;
    e.setWorkflow(wf);
    QVERIFY(arrows(both).join(QLatin1Char(' ')).contains(QStringLiteral("R→S ⚠")));
    QVERIFY(e.connectionItem(both)->toolTip().contains(QStringLiteral("last run: S (S – toS gave spectra)")));
    QVERIFY(e.connectionItem(both)->toolTip().contains(QStringLiteral("⚠ exec.spectrum_cut: 3e-3")));
    // a fixed transport shows with a star
    e.setConnectionTransport(both, QStringLiteral("forward"), QStringLiteral("H"));
    QVERIFY(arrows(both).join(QLatin1Char(' ')).contains(QStringLiteral("H*")));  // also with an old plan
    if (const QByteArray dir = qgetenv("NFCAD_SNAPSHOT_DIR"); !dir.isEmpty()) {
      e.resize(1400, 700);
      e.highlightBranch(QStringLiteral("measurement"));
      e.scene()->clearSelection();
      for (const char* id : {"Beam_splitter", "Objective_A", "Sample", "Objective_B"}) e.nodeItem(QString::fromLatin1(id))->setSelected(true);
      e.zoomSelected();
      e.grab().toImage().save(QString::fromLocal8Bit(dir) + QStringLiteral("/node_editor_directions.png"));
    }
  }

  void connectionsAndTransports() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    QSignalSpy edited(&e, &NodeEditor::edited);
    QVERIFY(!e.addConnection(QStringLiteral("Objective_A"), QStringLiteral("Sample"), QStringLiteral("Reference"),
                             QStringLiteral("Objective_B")));  // both ports are taken
    e.removeConnection(3);
    QCOMPARE(e.connectionCount(), 8);
    QVERIFY(e.addConnection(QStringLiteral("Objective_A"), QStringLiteral("Sample"), QStringLiteral("Sample"),
                            QStringLiteral("Objective_A")));
    QCOMPARE(e.connectionCount(), 9);
    const int last = 8;
    e.setConnectionTransport(last, QStringLiteral("forward"), QStringLiteral("H"));
    QJsonObject t = e.workflow()["model"].toObject()["connections"].toArray()[last].toObject()["transport"].toObject();
    QCOMPARE(t["forward"].toString(), QStringLiteral("H"));
    QCOMPARE(t["back"].toString(), QStringLiteral("auto"));
    e.setConnectionTransport(last, QStringLiteral("both"), QStringLiteral("auto"));
    QVERIFY(!e.workflow()["model"].toObject()["connections"].toArray()[last].toObject().contains("transport"));
    QVERIFY(edited.count() >= 4);
  }

  void branchesHighlightAndRecord() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    e.highlightBranch(QStringLiteral("reference"));
    QCOMPARE(e.nodeItem(QStringLiteral("Objective_B"))->pen().widthF(), 3.0);
    QVERIFY(e.nodeItem(QStringLiteral("Objective_A"))->pen().widthF() < 3.0);  // not on it
    // record the reference arm to the pupil camera: click the port each block is left by
    e.beginBranch();
    QVERIFY(!e.recordPort(QStringLiteral("Beam_splitter"), QStringLiteral("Objective_B")));  // not a source
    QVERIFY(e.recordPort(QStringLiteral("source"), QStringLiteral("Illumination_stop")));
    QVERIFY(e.recordPort(QStringLiteral("Illumination_stop"), QStringLiteral("Beam_splitter")));
    QVERIFY(!e.recordPort(QStringLiteral("Objective_B"), QStringLiteral("Reference")));  // light is at the splitter
    QVERIFY(e.recordPort(QStringLiteral("Beam_splitter"), QStringLiteral("Objective_B")));
    QVERIFY(e.recordPort(QStringLiteral("Objective_B"), QStringLiteral("Reference")));
    QVERIFY(e.recordPort(QStringLiteral("Reference"), QStringLiteral("Objective_B")));
    QVERIFY(e.recordPort(QStringLiteral("Objective_B"), QStringLiteral("Beam_splitter")));
    QVERIFY(e.recordPort(QStringLiteral("Beam_splitter"), QStringLiteral("Pupil_camera")));
    QVERIFY(!e.branchComplete());
    QSignalSpy recorded(&e, &NodeEditor::branchRecorded);
    QVERIFY(e.recordDetector(QStringLiteral("Pupil_camera")));
    QCOMPARE(recorded.count(), 1);
    QVERIFY(!e.finishBranch(QStringLiteral("reference")));  // the name is taken
    QVERIFY(e.finishBranch(QStringLiteral("reference_pupil")));
    QVERIFY(e.branchNames().contains(QStringLiteral("reference_pupil")));
    const QJsonArray steps = e.workflow()["model"].toObject()["branches"].toArray().last().toObject()["steps"].toArray();
    QCOMPARE(steps.size(), 8);
    QCOMPARE(steps[4].toArray(), (QJsonArray{"Reference", "Objective_B", "Objective_B"}));  // the mirror
    QVERIFY(steps.last().toArray().at(2).isNull());
    e.removeBranch(QStringLiteral("measurement"));
    QVERIFY(!e.branchNames().contains(QStringLiteral("measurement")));
    // Escape cancels a recording
    e.beginBranch();
    QVERIFY(e.recordingBranch());
    QKeyEvent esc(QEvent::KeyPress, Qt::Key_Escape, Qt::NoModifier);
    QApplication::sendEvent(&e, &esc);
    QVERIFY(!e.recordingBranch());
  }

  void branchPanel() {
    NodeEditor e;
    nfcad::ui::BranchPanel panel(&e);
    panel.ask_name = [](const QString& suggestion) { return suggestion; };
    e.setWorkflow(model_linnik());
    QCOMPARE(panel.list()->count(), 3);
    panel.list()->setCurrentRow(1);
    QCOMPARE(e.highlightedBranch(), QStringLiteral("reference"));
    e.beginBranch();
    for (const auto& [n, p] : std::initializer_list<std::pair<const char*, const char*>>{
             {"source", "Illumination_stop"}, {"Illumination_stop", "Beam_splitter"},
             {"Beam_splitter", "Objective_A"}, {"Objective_A", "Sample"}, {"Sample", "Objective_A"},
             {"Objective_A", "Beam_splitter"}, {"Beam_splitter", "Pupil_camera"}}) {
      QVERIFY(e.recordPort(QString::fromLatin1(n), QString::fromLatin1(p)));
    }
    QVERIFY(e.recordDetector(QStringLiteral("Pupil_camera")));  // the panel names it "branch 1"
    QCOMPARE(panel.list()->count(), 4);
    QVERIFY(e.branchNames().contains(QStringLiteral("branch 1")));
  }

  void modelReplaceKeepsPorts() {
    // the mirror's Raytatouille data (element and traversals) go with it, keyed by the new port
    QJsonObject wf = model_linnik();
    QJsonObject model = wf["model"].toObject();
    QJsonArray nodes = model["nodes"].toArray();
    const QJsonObject mirror{{"/root/children/4", QJsonObject{{"type", "mirror"}, {"name", "Sample"}}}};
    const QJsonArray reflect{QJsonObject{{"surface", "SMP"}, {"kind", "reflect"}}};
    for (int k = 0; k < nodes.size(); ++k) {
      QJsonObject n = nodes[k].toObject();
      if (n["id"].toString() != QStringLiteral("Sample")) continue;
      QJsonObject p = n["params"].toObject();
      p["rtt"] = mirror;
      p["runs"] = QJsonObject{{"Objective_A>Objective_A|", reflect}, {"Objective_A>Objective_A|order 1", reflect}};
      n["params"] = p;
      nodes[k] = n;
    }
    model["nodes"] = nodes;
    wf["model"] = model;
    NodeEditor e;
    e.setWorkflow(wf);
    if (!e.replacementsFor(QStringLiteral("Sample")).contains(QStringLiteral("fusion.grating"))) {
      QSKIP("the block library of the fixture has no grating");
    }
    QVERIFY(e.replaceNode(QStringLiteral("Sample"), QStringLiteral("fusion.grating")));
    const QJsonObject m = e.workflow()["model"].toObject();
    for (const QJsonValue& v : m["nodes"].toArray()) {
      if (v.toObject()["id"].toString() != QStringLiteral("Sample")) continue;
      const QJsonObject p = v.toObject()["params"].toObject();
      QCOMPARE(p["rtt"].toObject(), mirror);
      QCOMPARE(p["runs"].toObject(), (QJsonObject{{"front>front|", reflect}}));
    }
    bool connected = false;
    for (const QJsonValue& v : m["connections"].toArray()) {
      const QJsonArray ends = v.toObject()["ports"].toArray();
      connected = connected || ends.contains(QJsonArray{"Sample", "front"});
    }
    QVERIFY(connected);  // the objective's connection moved to the grating's port
    for (const QJsonValue& b : m["branches"].toArray()) {
      for (const QJsonValue& s : b.toObject()["steps"].toArray()) {
        if (s.toArray().at(0).toString() == QStringLiteral("Sample")) {
          QCOMPARE(s.toArray(), (QJsonArray{"Sample", "front", "front"}));
        }
      }
    }
  }

  void replaceByTheBranchesWithTwoPorts() {
    // a grating with a front and a back port (RTT-Fusion#120): a mirror's single port becomes
    // front; a block the branches pass through (the tube lens: entered from the beam splitter,
    // left towards the camera) gets front where the light enters and back where it leaves; a block
    // passed both ways (an objective of the Linnik) has no unique map and is not offered
    QJsonObject wf = model_linnik();
    QJsonArray types = wf["types"].toArray();
    for (int k = 0; k < types.size(); ++k) {
      QJsonObject t = types[k].toObject();
      if (t["type"].toString() != QStringLiteral("fusion.grating")) continue;
      t["ports"] = QJsonArray{QJsonObject{{"name", "front"}, {"in", "in"}, {"out", "out"}, {"side", "front"}},
                              QJsonObject{{"name", "back"}, {"out", "back_out"}, {"side", "back"}}};
      t["scatter"] = QJsonArray{QJsonArray{"front", "front", "full", QJsonArray{}},
                                QJsonArray{"front", "back", "full", QJsonArray{}}};
      types[k] = t;
    }
    wf["types"] = types;
    NodeEditor e;
    e.setWorkflow(wf);
    const QString tube = QStringLiteral("Tube_and_camera_Tube_lens_Tube_lens");
    QVERIFY(e.replacementsFor(QStringLiteral("Sample")).contains(QStringLiteral("fusion.grating")));
    QVERIFY(e.replacementsFor(tube).contains(QStringLiteral("fusion.grating")));
    QVERIFY(!e.replacementsFor(QStringLiteral("Objective_A")).contains(QStringLiteral("fusion.grating")));
    QVERIFY(e.replaceNode(QStringLiteral("Sample"), QStringLiteral("fusion.grating")));
    QVERIFY(e.replaceNode(tube, QStringLiteral("fusion.grating")));
    const QJsonObject m = e.workflow()["model"].toObject();
    for (const QJsonValue& b : m["branches"].toArray()) {
      for (const QJsonValue& st : b.toObject()["steps"].toArray()) {
        const QJsonArray step = st.toArray();
        if (step.at(0).toString() == QStringLiteral("Sample")) QCOMPARE(step, (QJsonArray{"Sample", "front", "front"}));
        if (step.at(0).toString() == tube) QCOMPARE(step, (QJsonArray{tube, "front", "back"}));
      }
    }
    QSet<QString> tube_ports;
    for (const QJsonValue& v : m["connections"].toArray()) {
      for (const QJsonValue& end : v.toObject()["ports"].toArray()) {
        if (end.toArray().at(0).toString() == tube) tube_ports.insert(end.toArray().at(1).toString());
      }
    }
    QCOMPARE(tube_ports, (QSet<QString>{"front", "back"}));
  }

  void fieldsOfAPluginNode() {
    // ADR Nachtrag 1: the plugin describes the data of a node (JSON pointers into its params);
    // the dialog edits them in a tab per element and writes back only what was changed
    const QString radius = QStringLiteral("/rtt/~1root~1children~11/surfaces/0/shape/base/radius/value");
    const QString coeff = QStringLiteral("/rtt/~1root~1children~11/surfaces/0/shape/base/coefficients/0");
    QJsonObject lens{{"type", "lens"},
                     {"name", "L1"},
                     {"surfaces", QJsonArray{QJsonObject{{"id", "S1"},
                                                         {"shape", QJsonObject{{"base", QJsonObject{{"type", "even_asphere"},
                                                                                                    {"radius", QJsonObject{{"value", 30.0}, {"variable", true}}},
                                                                                                    {"coefficients", QJsonArray{1.2345678901234567e-06}}}}}}}}}};
    QJsonObject node{{"id", "L"},
                     {"type", "rtt.section"},
                     {"params", QJsonObject{{"rtt", QJsonObject{{"/root/children/1", lens}}}}},
                     {"fields", QJsonArray{QJsonObject{{"name", radius}, {"type", "number"}, {"label", "S1 radius"}, {"group", "L1"}, {"unit", "mm"}},
                                           QJsonObject{{"name", coeff}, {"type", "number"}, {"label", "S1 a4"}, {"group", "L1"}}}}};
    QJsonObject model{{"format", "rtt-fusion-graph"}, {"version", 2}, {"nodes", QJsonArray{node}},
                      {"connections", QJsonArray{}}, {"links", QJsonArray{}}, {"branches", QJsonArray{}}};
    NodeEditor e;
    e.setWorkflow(QJsonObject{{"model", model}});
    auto value = [&e](const QString& pointer) {
      QJsonValue v = e.workflow()["model"].toObject()["nodes"].toArray()[0].toObject()["params"];
      for (QString part : pointer.mid(1).split(QLatin1Char('/'))) {
        part.replace(QStringLiteral("~1"), QStringLiteral("/"));
        v = v.isArray() ? v.toArray().at(part.toInt()) : v.toObject()[part];
      }
      return v;
    };
    e.setParams(QStringLiteral("L"), QJsonObject{{radius, 31.5}});
    QCOMPARE(value(radius).toDouble(), 31.5);
    QCOMPARE(value(radius.chopped(5) + QStringLiteral("variable")).toBool(), true);  // the rest stays
    QTimer::singleShot(0, &e, [radius] {
      for (QWidget* w : QApplication::topLevelWidgets()) {
        auto* d = qobject_cast<QDialog*>(w);
        if (d == nullptr || !d->isVisible()) continue;
        QVERIFY(d->findChild<QTabWidget*>() != nullptr);  // a tab per element
        auto* line = d->findChild<QLineEdit*>(radius);
        QVERIFY(line != nullptr);
        line->setText(QStringLiteral("42"));
        d->accept();
      }
    });
    e.editParams(QStringLiteral("L"));
    QCOMPARE(value(radius).toDouble(), 42.0);
    QCOMPARE(value(coeff).toDouble(), 1.2345678901234567e-06);  // shown with 12 digits, not rewritten
  }

  // ---------------------------------------------------------------- groups and channels (R28)

  void groupsFromTheSelection() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    const QJsonObject before = e.workflow()["model"].toObject();
    QString why;
    QVERIFY(e.groupBlocks({QStringLiteral("source"), QStringLiteral("Illumination_stop")}, QStringLiteral("x"), &why).isEmpty());
    QVERIFY(why.contains(QStringLiteral("source")));  // branches begin outside a group
    const QString gid = e.groupBlocks({QStringLiteral("Objective_A"), QStringLiteral("Sample")}, QStringLiteral("Measuring arm"));
    QCOMPARE(gid, QStringLiteral("Measuring_arm"));
    if (const QByteArray dir = qgetenv("NFCAD_SNAPSHOT_DIR"); !dir.isEmpty()) {  // for a check with RTT-Fusion
      QFile out(QString::fromLocal8Bit(dir) + QStringLiteral("/grouped_arm.json"));
      if (out.open(QIODevice::WriteOnly)) out.write(QJsonDocument(e.workflow()["model"].toObject()).toJson());
    }
    QVERIFY(e.nodeItem(gid) != nullptr && e.nodeItem(QStringLiteral("Sample")) == nullptr);
    const QJsonObject model = e.workflow()["model"].toObject();
    const QJsonObject group = node(QJsonObject{{"model", model}}, gid);
    const QJsonObject inner = group["variants"].toObject()["main"].toObject();
    QCOMPARE(inner["nodes"].toArray().size(), 2);
    QCOMPARE(inner["connections"].toArray().size(), 1);  // objective – sample
    QCOMPARE(inner["ports"].toObject().keys(), QStringList{QStringLiteral("Objective_A.Beam_splitter")});
    QCOMPARE(inner["branches"].toArray().size(), 1);  // the measuring arm and its pupil branch share it
    for (const QJsonValue& b : model["branches"].toArray()) {
      for (const QJsonValue& st : b.toObject()["steps"].toArray()) {
        if (st.toArray().at(0).toString() == gid) {
          QCOMPARE(st.toArray(), (QJsonArray{gid, "Objective_A.Beam_splitter", "Objective_A.Beam_splitter", "measurement"}));
        }
      }
    }
    // inside the group: its blocks and its inner branch; edits land in the variant
    QVERIFY(e.enterGroup(gid));
    QCOMPARE(e.scope(), QStringList{gid});
    QVERIFY(e.nodeItem(QStringLiteral("Sample")) != nullptr);
    QCOMPARE(e.branchNames(), QStringList{QStringLiteral("measurement")});
    e.setParams(QStringLiteral("Sample"), QJsonObject{{"offset", QJsonArray{0, 0, 0.002}}});
    e.leaveGroup();
    QVERIFY(e.scope().isEmpty());
    const QJsonObject edited = node(QJsonObject{{"model", e.workflow()["model"].toObject()}}, gid);
    const QJsonArray inner_nodes = edited["variants"].toObject()["main"].toObject()["nodes"].toArray();
    bool offset = false;
    for (const QJsonValue& n : inner_nodes) offset = offset || n.toObject()["params"].toObject().contains("offset");
    QVERIFY(offset);
    // ungroup: the blocks and the branches as before (the offset stays)
    QVERIFY(e.ungroup(gid));
    const QJsonObject again = e.workflow()["model"].toObject();
    QCOMPARE(again["branches"], before["branches"]);
    QCOMPARE(again["connections"].toArray().size(), before["connections"].toArray().size());
    QVERIFY(e.nodeItem(QStringLiteral("Sample")) != nullptr);
  }

  void variantsAndCondensing() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    const QString gid = e.groupBlocks({QStringLiteral("Objective_B"), QStringLiteral("Reference")}, QStringLiteral("ref"));
    QJsonObject wf = e.workflow();
    QJsonObject model = wf["model"].toObject();
    QJsonArray nodes = model["nodes"].toArray();
    for (int k = 0; k < nodes.size(); ++k) {
      QJsonObject n = nodes[k].toObject();
      if (n["id"].toString() != gid) continue;
      QJsonObject variants = n["variants"].toObject();
      variants["copy"] = variants["main"];  // a second variant with the same ports
      n["variants"] = variants;
      nodes[k] = n;
    }
    model["nodes"] = nodes;
    wf["model"] = model;
    e.setWorkflow(wf);
    QCOMPARE(e.variants(gid), (QStringList{"copy", "main"}));
    e.setVariant(gid, QStringLiteral("copy"));
    QCOMPARE(node(QJsonObject{{"model", e.workflow()["model"].toObject()}}, gid)["variant"].toString(), QStringLiteral("copy"));
    e.setCondensed(gid, true);
    QVERIFY(node(QJsonObject{{"model", e.workflow()["model"].toObject()}}, gid).contains("condense"));
    e.setCondensed(gid, false);
    QVERIFY(!node(QJsonObject{{"model", e.workflow()["model"].toObject()}}, gid).contains("condense"));
  }

  void newRenameDeleteVariants() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    const QString gid = e.groupBlocks({QStringLiteral("Objective_B"), QStringLiteral("Reference")}, QStringLiteral("ref"));
    auto group = [&] { return node(QJsonObject{{"model", e.workflow()["model"].toObject()}}, gid); };
    // a new variant: a copy of the active one, then active
    QCOMPARE(e.addVariant(gid, QStringLiteral("ideal")), QStringLiteral("ideal"));
    QCOMPARE(group()["variant"].toString(), QStringLiteral("ideal"));
    QCOMPARE(group()["variants"].toObject()["ideal"], group()["variants"].toObject()["main"]);
    QCOMPARE(e.addVariant(gid, QStringLiteral("ideal")), QStringLiteral("ideal 2"));  // unique
    // an edit inside goes into the active variant only
    QVERIFY(e.enterGroup(gid));
    e.setParams(QStringLiteral("Reference"), QJsonObject{{"offset", QJsonArray{0, 0, 0.001}}});
    e.leaveGroup();
    QVERIFY(group()["variants"].toObject()["ideal 2"] != group()["variants"].toObject()["main"]);
    QCOMPARE(group()["variants"].toObject()["ideal"], group()["variants"].toObject()["main"]);
    // rename (the active one follows), refuse empty or taken names
    QVERIFY(e.renameVariant(gid, QStringLiteral("ideal 2"), QStringLiteral("shifted")));
    QCOMPARE(group()["variant"].toString(), QStringLiteral("shifted"));
    QVERIFY(!e.renameVariant(gid, QStringLiteral("shifted"), QStringLiteral("main")));
    QVERIFY(!e.renameVariant(gid, QStringLiteral("shifted"), QStringLiteral("  ")));
    QCOMPARE(e.variants(gid), (QStringList{"ideal", "main", "shifted"}));
    // delete: the active one gives way, the last one stays
    QVERIFY(e.removeVariant(gid, QStringLiteral("shifted")));
    QVERIFY(e.variants(gid).contains(group()["variant"].toString()));
    QVERIFY(e.removeVariant(gid, QStringLiteral("ideal")));
    QVERIFY(!e.removeVariant(gid, QStringLiteral("main")));
    QCOMPARE(e.variants(gid), QStringList{QStringLiteral("main")});
    QVERIFY(e.addVariant(QStringLiteral("Beam_splitter"), QStringLiteral("x")).isEmpty());  // no group
  }

  void highlightedBranchGoesInside() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    const QString gid = e.groupBlocks({QStringLiteral("Objective_A"), QStringLiteral("Sample")}, QStringLiteral("arm"));
    nfcad::ui::BranchPanel panel(&e);
    e.highlightBranch(QStringLiteral("measurement_pupil"));
    QVERIFY(e.enterGroup(gid));
    // inside: the inner branch the outer branch's step names, shown in the list and on the blocks
    QCOMPARE(e.highlightedBranch(), QStringLiteral("measurement"));
    QCOMPARE(panel.list()->currentItem()->text(), QStringLiteral("measurement"));
    QCOMPARE(e.nodeItem(QStringLiteral("Sample"))->pen().widthF(), 3.0);
    e.leaveGroup();
    QCOMPARE(e.highlightedBranch(), QStringLiteral("measurement_pupil"));  // back as it was
    // nothing highlighted outside, or a branch not through the group: nothing inside
    e.highlightBranch(QStringLiteral("reference"));
    QVERIFY(e.enterGroup(gid));
    QVERIFY(e.highlightedBranch().isEmpty());
    e.leaveGroup();
    QCOMPARE(e.highlightedBranch(), QStringLiteral("reference"));
  }

  void stepChannels() {
    NodeEditor e;
    e.setWorkflow(model_linnik());
    // a Raytatouille section offers ghosts at its surfaces
    const QStringList ghosts = e.channelChoices(QStringLiteral("measurement"), 3);  // Objective_A
    QCOMPARE(ghosts.first(), QString());
    QVERIFY(ghosts.size() > 1 && ghosts[1].startsWith(QStringLiteral("ghost:")));
    e.setStepChannel(QStringLiteral("measurement"), 3, ghosts[1]);
    QCOMPARE(e.branchSteps(QStringLiteral("measurement"))[3].toArray().at(3).toString(), ghosts[1]);
    e.setStepChannel(QStringLiteral("measurement"), 3, QString());
    QCOMPARE(e.branchSteps(QStringLiteral("measurement"))[3].toArray().size(), 3);
    // a group offers its inner branches; recording through it picks the fitting one
    const QString gid = e.groupBlocks({QStringLiteral("Objective_B"), QStringLiteral("Reference")}, QStringLiteral("ref"));
    int at = -1;
    const QJsonArray steps = e.branchSteps(QStringLiteral("reference"));
    for (int k = 0; k < steps.size(); ++k) {
      if (steps[k].toArray().at(0).toString() == gid) at = k;
    }
    QCOMPARE(e.channelChoices(QStringLiteral("reference"), at), (QStringList{QString(), QStringLiteral("reference")}));
    e.beginBranch();
    for (const auto& [n, p] : std::initializer_list<std::pair<QString, QString>>{
             {QStringLiteral("source"), QStringLiteral("Illumination_stop")},
             {QStringLiteral("Illumination_stop"), QStringLiteral("Beam_splitter")},
             {QStringLiteral("Beam_splitter"), QStringLiteral("Objective_B")},
             {gid, QStringLiteral("Objective_B.Beam_splitter")},
             {QStringLiteral("Beam_splitter"), QStringLiteral("Pupil_camera")}}) {
      QVERIFY2(e.recordPort(n, p), qPrintable(n));
    }
    QVERIFY(e.recordDetector(QStringLiteral("Pupil_camera")));
    QVERIFY(e.finishBranch(QStringLiteral("reference_pupil")));
    const QJsonArray recorded = e.branchSteps(QStringLiteral("reference_pupil"));
    QCOMPARE(recorded[3].toArray(), (QJsonArray{gid, "Objective_B.Beam_splitter", "Objective_B.Beam_splitter", "reference"}));
    // the branch list shows the steps; a double-click sets the channel
    nfcad::ui::BranchPanel panel(&e);
    panel.ask_channel = [](const QStringList& choices, const QString&) { return choices.last(); };
    e.highlightBranch(QStringLiteral("measurement"));
    panel.refresh();
    QCOMPARE(panel.steps()->count(), e.branchSteps(QStringLiteral("measurement")).size());
    emit panel.steps()->itemDoubleClicked(panel.steps()->item(3));
    QVERIFY(e.branchSteps(QStringLiteral("measurement"))[3].toArray().at(3).toString().startsWith(QStringLiteral("ghost:")));
    if (const QByteArray dir = qgetenv("NFCAD_SNAPSHOT_DIR"); !dir.isEmpty()) {  // for a check with RTT-Fusion
      QFile out(QString::fromLocal8Bit(dir) + QStringLiteral("/grouped_model.json"));
      if (out.open(QIODevice::WriteOnly)) out.write(QJsonDocument(e.workflow()["model"].toObject()).toJson());
    }
  }

  void savedWithTheDocument() {
    nfcad::document::Document doc;
    doc.setWorkflow(model_linnik());
    QVERIFY(doc.isModified());
    QTemporaryDir dir;
    const QString path = dir.filePath(QStringLiteral("w.rttf"));
    QVERIFY(nfcad::document::save_nfcad(doc, path).isEmpty());
    nfcad::document::Document back;
    QCOMPARE(nfcad::document::load_nfcad(back, path), QString());
    QCOMPARE(back.workflow(), model_linnik());
  }

  void navigation() {
    // as in the CAD views: zoom to the cursor, pan by scroll and drag, zoom extents
    NodeEditor e;
    e.resize(800, 400);
    e.setAttribute(Qt::WA_DontShowOnScreen);
    e.setWorkflow(model_linnik());
    e.show();
    e.fitAll();
    const QPoint cursor(200, 150);
    const QPointF under = e.mapToScene(cursor);
    const double z0 = e.zoom();
    // mouse wheel one notch up: closer, the scene point under the cursor stays there
    QWheelEvent wheel(QPointF(cursor), QPointF(e.viewport()->mapToGlobal(cursor)), QPoint(), QPoint(0, 120),
                      Qt::NoButton, Qt::NoModifier, Qt::NoScrollPhase, false);
    QApplication::sendEvent(e.viewport(), &wheel);
    QVERIFY(e.zoom() > z0 * 1.1);
    QVERIFY(QLineF(e.mapToScene(cursor), under).length() < 2.0 / e.zoom());
    // zoom is limited
    for (int k = 0; k < 60; ++k) e.zoomAt(QPointF(cursor), 2.0);
    QVERIFY(e.zoom() <= 8.0 + 1e-9);
    // two-finger trackpad scroll pans (no zoom)
    const double z1 = e.zoom();
    const QPointF before = e.mapToScene(QPoint(400, 200));
    QWheelEvent scroll(QPointF(cursor), QPointF(e.viewport()->mapToGlobal(cursor)), QPoint(40, 0), QPoint(0, 0),
                       Qt::NoButton, Qt::NoModifier, Qt::ScrollUpdate, false);
    QApplication::sendEvent(e.viewport(), &scroll);
    QCOMPARE(e.zoom(), z1);
    QVERIFY(std::abs((before - e.mapToScene(QPoint(400, 200))).x() - 40.0 / z1) < 2.0 / z1);
    // a right drag pans far beyond the blocks (open canvas) and opens no menu
    const QPointF b2 = e.mapToScene(QPoint(400, 200));
    QTest::mousePress(e.viewport(), Qt::RightButton, {}, QPoint(400, 200));
    for (int x = 410; x <= 700; x += 10) {
      QMouseEvent move(QEvent::MouseMove, QPointF(x, 200), QPointF(e.viewport()->mapToGlobal(QPoint(x, 200))),
                       Qt::NoButton, Qt::RightButton, Qt::NoModifier);
      QApplication::sendEvent(e.viewport(), &move);
    }
    QTest::mouseRelease(e.viewport(), Qt::RightButton, {}, QPoint(700, 200));
    QVERIFY(std::abs((b2 - e.mapToScene(QPoint(400, 200))).x() - 300.0 / e.zoom()) < 2.0 / e.zoom());
    // zoom extents with Z E
    QTest::keyClick(&e, Qt::Key_Z);
    QTest::keyClick(&e, Qt::Key_E);
    QVERIFY(std::abs(e.zoom() - z0) < 1e-6);
  }

  void zoomSelected() {
    NodeEditor e;
    e.resize(800, 400);
    e.setAttribute(Qt::WA_DontShowOnScreen);
    e.setWorkflow(model_linnik());
    e.show();
    e.fitAll();
    const double all = e.zoom();
    // without a selection: all blocks
    e.zoomSelected();
    QVERIFY(std::abs(e.zoom() - all) < 1e-9);
    // one block selected: it fills the view, centred
    QGraphicsRectItem* sample = e.nodeItem(QStringLiteral("Sample"));
    sample->setSelected(true);
    QTest::keyClick(&e, Qt::Key_Z);
    QTest::keyClick(&e, Qt::Key_S);
    QVERIFY(e.zoom() > 2.0 * all);
    const QPoint centre = e.mapFromScene(sample->sceneBoundingRect().center());
    QVERIFY(std::abs(centre.x() - e.viewport()->width() / 2) < 3);
    QVERIFY(std::abs(centre.y() - e.viewport()->height() / 2) < 3);
    const QRect r = e.mapFromScene(sample->sceneBoundingRect()).boundingRect();
    QVERIFY(e.viewport()->rect().contains(r));
    // the editor takes Z, E and S before the main window's shortcuts
    QKeyEvent override(QEvent::ShortcutOverride, Qt::Key_Z, Qt::NoModifier);
    QApplication::sendEvent(&e, &override);
    QVERIFY(override.isAccepted());
  }

  void snapshot() {
    NodeEditor e;
    e.resize(1500, 420);
    QJsonObject wf = model_linnik();
    // optional: the workflow of a document (.rttf) for a look at a real case
    if (const QByteArray doc = qgetenv("NFCAD_SNAPSHOT_WORKFLOW_DOC"); !doc.isEmpty()) {
      QFile f(QString::fromLocal8Bit(doc));
      if (f.open(QIODevice::ReadOnly)) wf = QJsonDocument::fromJson(f.readAll()).object()["workflow"].toObject();
      e.resize(1800, 700);
    }
    e.setWorkflow(wf);
    e.show();
    QVERIFY(QTest::qWaitForWindowExposed(&e) || true);
    e.fitAll();
    const QImage img = e.grab().toImage();
    QVERIFY(!img.isNull());
    if (const QByteArray dir = qgetenv("NFCAD_SNAPSHOT_DIR"); !dir.isEmpty()) {
      img.save(QString::fromLocal8Bit(dir) + QStringLiteral("/node_editor.png"));
    }
  }
};

QTEST_MAIN(TestNodeEditor)
#include "test_node_editor.moc"
