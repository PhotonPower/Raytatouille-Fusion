#include <QDockWidget>
#include <QFileOpenEvent>
#include <QGraphicsRectItem>
#include <QMenu>
#include <QMouseEvent>
#include <QTemporaryDir>
#include <QJsonArray>
#include <QJsonObject>
#include <QComboBox>
#include <QSettings>
#include <QLabel>
#include <QMenuBar>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QStatusBar>
#include <QStandardPaths>
#include <QTest>
#include <QToolBar>
#include <QTreeWidget>
#include <memory>

#include "document/nfcad_io.hpp"
#include "app/main_window.hpp"
#include "document/document.hpp"
#include "document/entity.hpp"
#include "document/selection.hpp"
#include "plugins/plugin_manager.hpp"
#include "ui/plugin_panel.hpp"
#include "ui/plugin_settings_dialog.hpp"
#include "results/result_store.hpp"
#include "ui/image_view.hpp"
#include "ui/node_editor.hpp"
#include "ui/results_panel.hpp"
#include "ui/tool_box.hpp"

class TestMainWindowPlugins : public QObject {
  Q_OBJECT
 private slots:
  void closingWithUndoHistory() {
    // regression (M8): destroying the window with an undo history emitted cleanChanged into
    // the half-destroyed window (assert in debug builds, undefined behaviour in release)
    QStandardPaths::setTestModeEnabled(true);
    auto w = std::make_unique<nfcad::app::MainWindow>();
    auto* doc = w->findChild<nfcad::document::Document*>();
    doc->addEntities({nfcad::document::make_entity(nf::Vec3{1, 2, 3}, QStringLiteral("p"))}, QStringLiteral("add"));
    QVERIFY(doc->isModified());
    w.reset();  // must not crash
  }

  void hideAndUnhideButtons() {
    // the View toolbar's Hide (H) hides and deselects the selection, Unhide (Shift+H) shows it again
    QStandardPaths::setTestModeEnabled(true);
    nfcad::app::MainWindow w;
    auto* doc = w.findChild<nfcad::document::Document*>();
    auto* selection = w.findChild<nfcad::document::Selection*>();
    const auto ids = doc->addEntities({nfcad::document::make_entity(nf::Vec3{0, 0, 0}, QStringLiteral("a")),
                                       nfcad::document::make_entity(nf::Vec3{1, 0, 0}, QStringLiteral("b"))},
                                      QStringLiteral("add"));
    auto* bar = w.findChild<QToolBar*>(QStringLiteral("viewToolBar"));
    auto* hide = w.findChild<QAction*>(QStringLiteral("hideAction"));
    auto* unhide = w.findChild<QAction*>(QStringLiteral("unhideAction"));
    QVERIFY(bar && hide && unhide);
    QVERIFY(bar->actions().contains(hide) && bar->actions().contains(unhide));
    QCOMPARE(hide->shortcut(), QKeySequence(Qt::Key_H));
    QCOMPARE(unhide->shortcut(), QKeySequence(Qt::SHIFT | Qt::Key_H));

    hide->trigger();  // nothing selected: nothing happens
    QVERIFY(doc->isDisplayed(*doc->entity(ids[0])) && doc->isDisplayed(*doc->entity(ids[1])));
    selection->apply({{ids[0], {}}}, nfcad::document::Selection::Mode::Replace);
    hide->trigger();
    QVERIFY(!doc->isDisplayed(*doc->entity(ids[0])));
    QVERIFY(doc->isDisplayed(*doc->entity(ids[1])));
    QVERIFY(selection->empty());  // a later Delete must not take the hidden object along
    unhide->trigger();
    QVERIFY(doc->isDisplayed(*doc->entity(ids[0])));
  }

  void workflowWindowComesBack() {
    // the node workflow dock opens when a plugin sets a workflow, and again after the user
    // closed it, even if the workflow did not change ("Workflow from system" twice)
    QStandardPaths::setTestModeEnabled(true);
    nfcad::app::MainWindow w;
    w.setAttribute(Qt::WA_DontShowOnScreen);
    w.show();
    auto* doc = w.findChild<nfcad::document::Document*>();
    auto* dock = w.findChild<QDockWidget*>(QStringLiteral("workflowDock"));
    QVERIFY(doc != nullptr && dock != nullptr);
    QVERIFY(!dock->isVisible());
    const QJsonObject wf{{"model", QJsonObject{{"format", "rtt-fusion-graph"}, {"version", 2},
                                               {"nodes", QJsonArray{QJsonObject{{"id", "a"}, {"type", "rtt.source"}}}},
                                               {"connections", QJsonArray{}}}}};
    doc->setWorkflow(wf);
    doc->requestWorkflowShown();
    QVERIFY(dock->isVisible());
    dock->close();
    QVERIFY(!dock->isVisible());
    doc->setWorkflow(wf);  // unchanged: no workflowChanged
    doc->requestWorkflowShown();
    QVERIFY(dock->isVisible());
    // the View menu reopens it as well
    dock->close();
    dock->toggleViewAction()->trigger();
    QVERIFY(dock->isVisible());
  }

  void workflowOfAnOpenedFileIsShown() {
    // opening a document with a node workflow shows it (the workflow used to be set silently after
    // documentReset, so the window got the empty state of before), and a plugin that sets the same
    // workflow again ("Workflow from system" on an unchanged system) shows it in the window too
    QStandardPaths::setTestModeEnabled(true);
    QTemporaryDir dir;
    const QString path = dir.filePath(QStringLiteral("with_workflow.rttf"));
    const QJsonObject wf{{"model", QJsonObject{{"format", "rtt-fusion-graph"}, {"version", 2},
                                               {"nodes", QJsonArray{QJsonObject{{"id", "a"}, {"type", "rtt.source"}},
                                                                    QJsonObject{{"id", "b"}, {"type", "rtt.detector"}}}},
                                               {"connections", QJsonArray{}}}}};
    {
      nfcad::document::Document saved;
      saved.setWorkflow(wf);
      saved.setPluginParameters(QStringLiteral("raytracer"), QJsonObject{{"system", "x.rtt.json"}});
      QVERIFY(nfcad::document::save_nfcad(saved, path).isEmpty());
    }
    nfcad::app::MainWindow w;
    w.setAttribute(Qt::WA_DontShowOnScreen);
    w.show();
    QVERIFY(w.openFile(path, true));
    auto* doc = w.findChild<nfcad::document::Document*>();
    auto* dock = w.findChild<QDockWidget*>(QStringLiteral("workflowDock"));
    auto* editor = w.findChild<nfcad::ui::NodeEditor*>();
    QVERIFY(doc != nullptr && dock != nullptr && editor != nullptr);
    QCOMPARE(doc->pluginParameters(QStringLiteral("raytracer"))["system"].toString(), QStringLiteral("x.rtt.json"));
    QVERIFY(dock->isVisible());
    QVERIFY(editor->nodeItem(QStringLiteral("a")) != nullptr && editor->nodeItem(QStringLiteral("b")) != nullptr);
    // a window that shows another state gets the document's workflow when a plugin asks
    editor->setWorkflow({});
    doc->setWorkflow(doc->workflow());  // unchanged: no workflowChanged
    doc->requestWorkflowShown();
    QVERIFY(editor->nodeItem(QStringLiteral("a")) != nullptr);
  }

  void oldWorkflowOfAnOpenedFile() {
    // a document with an old socket graph (version 1): the editor does not edit it but says that
    // it is converted (Workflow plugin, Convert to model); until then the graph stays as it is
    QStandardPaths::setTestModeEnabled(true);
    QTemporaryDir dir;
    const QString path = dir.filePath(QStringLiteral("old_workflow.rttf"));
    const QJsonObject wf{{"graph", QJsonObject{{"format", "rtt-fusion-graph"}, {"version", 1},
                                               {"nodes", QJsonArray{QJsonObject{{"id", "a"}, {"type", "rtt.source"}}}},
                                               {"links", QJsonArray{}}}}};
    {
      nfcad::document::Document saved;
      saved.setWorkflow(wf);
      QVERIFY(nfcad::document::save_nfcad(saved, path).isEmpty());
    }
    nfcad::app::MainWindow w;
    w.setAttribute(Qt::WA_DontShowOnScreen);
    w.show();
    QVERIFY(w.openFile(path, true));
    auto* doc = w.findChild<nfcad::document::Document*>();
    auto* editor = w.findChild<nfcad::ui::NodeEditor*>();
    QVERIFY(doc != nullptr && editor != nullptr);
    QVERIFY(editor->oldGraph());
    QVERIFY(editor->nodeItem(QStringLiteral("a")) == nullptr);  // a note instead of the blocks
    QCOMPARE(doc->workflow()["graph"], wf["graph"]);
    editor->addNode(QStringLiteral("rtt.detector"), QPointF(0, 0));  // not edited: no model beside it
    QVERIFY(!doc->workflow().contains(QStringLiteral("model")));
    QCOMPARE(doc->workflow()["graph"], wf["graph"]);
  }

  void escapeLeavesAGroup() {
    // Escape belongs to the node editor while it is inside a group (the main window's Escape,
    // "no tool", would take it first); the level's name at the top left goes back too
    QStandardPaths::setTestModeEnabled(true);
    nfcad::app::MainWindow w;
    w.setAttribute(Qt::WA_DontShowOnScreen);
    w.show();
    auto* doc = w.findChild<nfcad::document::Document*>();
    auto* editor = w.findChild<nfcad::ui::NodeEditor*>();
    QVERIFY(doc != nullptr && editor != nullptr);
    const QJsonObject inner{{"nodes", QJsonArray{QJsonObject{{"id", "m"}, {"type", "rtt.mirror"}}}},
                            {"connections", QJsonArray{}}, {"links", QJsonArray{}}, {"branches", QJsonArray{}},
                            {"ports", QJsonObject{}}};
    const QJsonObject model{{"format", "rtt-fusion-graph"}, {"version", 2},
                            {"nodes", QJsonArray{QJsonObject{{"id", "g"}, {"type", "group"}, {"variant", "main"},
                                                             {"variants", QJsonObject{{"main", inner}}}}}},
                            {"connections", QJsonArray{}}, {"links", QJsonArray{}}, {"branches", QJsonArray{}}};
    doc->setWorkflow(QJsonObject{{"model", model}});
    doc->requestWorkflowShown();
    QVERIFY(editor->enterGroup(QStringLiteral("g")));
    // the main window active, as in use: only then its Escape shortcut competes
    w.activateWindow();
    QVERIFY(QTest::qWaitForWindowActive(&w));
    editor->setFocus();
    QTest::keyClick(editor, Qt::Key_Escape);  // through the shortcut map, as a real key press
    QVERIFY(editor->scope().isEmpty());
    QVERIFY(editor->enterGroup(QStringLiteral("g")));
    auto* crumb = editor->viewport()->findChild<QLabel*>();
    QVERIFY(crumb != nullptr && crumb->isVisible());
    QTest::mouseClick(crumb, Qt::LeftButton);
    QVERIFY(editor->scope().isEmpty());
  }

  void displayWindow() {
    // a display block's window shows the results with its key, dockable
    QStandardPaths::setTestModeEnabled(true);
    nfcad::app::MainWindow w;
    w.setAttribute(Qt::WA_DontShowOnScreen);
    w.show();
    auto* store = w.findChild<nfcad::results::ResultStore*>();
    QVERIFY(store != nullptr);
    const auto set = store->createSet(QStringLiteral("Workflow"));
    nfcad::results::Image im;
    im.width = 2;
    im.height = 2;
    im.values = {0, 1, 2, 3};
    im.x1 = 1;
    im.y1 = 1;
    store->addImage(set, QStringLiteral("other"), im);
    const auto keyed = store->addImage(set, QStringLiteral("camera"), im);
    store->setKey(keyed, QStringLiteral("workflow:show"));
    QDockWidget* dock = w.openDisplay(QStringLiteral("show"), QStringLiteral("display.image"), QStringLiteral("Camera"));
    QVERIFY(dock != nullptr && dock->isVisible());
    QVERIFY(dock->windowTitle().contains(QStringLiteral("Camera")));
    QVERIFY(dock->features().testFlag(QDockWidget::DockWidgetFloatable) && dock->features().testFlag(QDockWidget::DockWidgetMovable));
    auto* view = qobject_cast<nfcad::ui::ImageView*>(dock->widget());
    QVERIFY(view != nullptr && view->current() != nullptr);
    QCOMPARE(view->current()->id, keyed);
    QCOMPARE(w.openDisplay(QStringLiteral("show"), QStringLiteral("display.image"), QStringLiteral("Camera")), dock);  // one per block
  }

  void displayResultsOpenNoGeneralWindow() {
    // results of display blocks (key "workflow:…") belong to their own windows: the general
    // image and plot windows do not pop up for them, as they do for other results
    QStandardPaths::setTestModeEnabled(true);
    nfcad::app::MainWindow w;
    w.setAttribute(Qt::WA_DontShowOnScreen);
    w.show();
    auto* store = w.findChild<nfcad::results::ResultStore*>();
    auto dock = [&w](const char* name) { return w.findChild<QDockWidget*>(QString::fromLatin1(name)); };
    QVERIFY(store != nullptr && dock("imageDock") != nullptr && dock("plotDock") != nullptr);
    const auto set = store->createSet(QStringLiteral("Workflow"));
    nfcad::results::Image im;
    im.width = 2;
    im.height = 2;
    im.values = {0, 1, 2, 3};
    im.x1 = 1;
    im.y1 = 1;
    nfcad::results::Curve c;
    c.x = {0, 1};
    c.y = {1, 2};
    store->addImage(set, QStringLiteral("camera"), im, QStringLiteral("workflow:show"));
    store->addCurve(set, QStringLiteral("sweep"), c, QStringLiteral("workflow:plot"));
    QVERIFY(!dock("imageDock")->isVisible());
    QVERIFY(!dock("plotDock")->isVisible());
    store->addImage(set, QStringLiteral("trace"), im);  // an ordinary result: shown
    store->addCurve(set, QStringLiteral("merit"), c);
    QVERIFY(dock("imageDock")->isVisible());
    QVERIFY(dock("plotDock")->isVisible());
  }

  void demoPluginFromTheMenu() {
    if (QStandardPaths::findExecutable(QStringLiteral("python3")).isEmpty() &&
        QStandardPaths::findExecutable(QStringLiteral("python")).isEmpty() && qEnvironmentVariableIsEmpty("NFCAD_PYTHON")) {
      QSKIP("no Python interpreter found");
    }
    QStandardPaths::setTestModeEnabled(true);  // settings of this test only
    qputenv("NFCAD_PLUGIN_PATH", QByteArray(NFCAD_EXAMPLES_DIR));
    qputenv("NFCAD_DEVELOPER_MODE", "1");  // the example plugin in the repository is not signed
    nfcad::app::MainWindow w;
    bool banner = false;  // developer mode is always visible
    for (auto* l : w.statusBar()->findChildren<QLabel*>()) banner = banner || (l->text().contains(QStringLiteral("DEVELOPER MODE")) && !l->isHidden());
    QVERIFY(banner);
    // the plugin menu fills once the demo plugin said hello
    QMenu* plugins = nullptr;
    for (QAction* a : w.menuBar()->actions()) {
      if (a->menu() != nullptr && a->text().contains(QStringLiteral("Plugins"))) plugins = a->menu();
    }
    QVERIFY(plugins != nullptr);
    QAction* rays = nullptr;
    QTRY_VERIFY_WITH_TIMEOUT(
        [&] {
          for (QAction* a : plugins->actions()) {
            if (a->menu() == nullptr) continue;
            for (QAction* b : a->menu()->actions()) {
              if (b->text() == QStringLiteral("Ray fan from the origin")) rays = b;
            }
          }
          return rays != nullptr;
        }(),
        20000);
    // Uninstall lists the plugin from the folder, greyed out with where it comes from
    QMenu* uninstall = nullptr;
    for (QAction* a : plugins->actions()) {
      if (a->menu() != nullptr && a->text().contains(QStringLiteral("Uninstall"))) uninstall = a->menu();
    }
    QVERIFY(uninstall != nullptr);
    bool listed = false;
    for (QAction* a : uninstall->actions()) {
      if (a->text().contains(QStringLiteral("Demo plugin"))) {
        listed = true;
        QVERIFY(!a->isEnabled());
        QVERIFY(a->toolTip().contains(QStringLiteral("examples")));
      }
    }
    QVERIFY(listed);
    // the plugin also got a group in the tool column
    auto* toolbox = w.findChild<nfcad::ui::ToolBox*>();
    QVERIFY(toolbox != nullptr);
    bool group = false;
    for (auto* g : toolbox->findChildren<nfcad::ui::ToolGroup*>()) group = group || g->groupId() == QStringLiteral("plugin_demo");
    QVERIFY(group);

    rays->trigger();
    auto* tree = w.findChild<nfcad::ui::ResultsPanel*>()->findChild<QTreeWidget*>();
    QTRY_COMPARE_WITH_TIMEOUT(tree->topLevelItemCount(), 1, 20000);
    QCOMPARE(tree->topLevelItem(0)->text(0), QStringLiteral("Demo rays"));
    QTRY_VERIFY_WITH_TIMEOUT(w.statusBar()->currentMessage().contains(QStringLiteral("300 rays")), 10000);

    // the settings dialog: environment check against the plugins' requirements
    nfcad::ui::PluginSettingsDialog dialog(w.findChild<nfcad::plugins::PluginManager*>(), &w);
    for (auto* b : dialog.findChildren<QPushButton*>()) {
      if (b->text() == QStringLiteral("Check environment")) b->click();
    }
    auto* report = dialog.findChild<QPlainTextEdit*>();
    QVERIFY(report->toPlainText().contains(QStringLiteral("numpy")));
    if (const QByteArray dir = qgetenv("NFCAD_SNAPSHOT_DIR"); !dir.isEmpty()) {
      dialog.grab().save(QString::fromLocal8Bit(dir) + QStringLiteral("/plugin_settings.png"));
    }

    // Plugins → Show in the side panels: a hidden plugin leaves the tool box and the Plugin
    // panel, its actions stay in the menu; the choice is kept in the settings
    auto menu_named = [&](QMenu* in, const QString& text) -> QMenu* {
      for (QAction* a : in->actions()) {
        if (a->menu() != nullptr && a->text().contains(text)) return a->menu();
      }
      return nullptr;
    };
    QMenu* show = menu_named(plugins, QStringLiteral("Show in the side panels"));
    QVERIFY(show != nullptr);
    QAction* demo = nullptr;
    for (QAction* a : show->actions()) {
      if (a->text().contains(QStringLiteral("Demo plugin"))) demo = a;
    }
    QVERIFY(demo != nullptr && demo->isCheckable() && demo->isChecked());
    demo->setChecked(false);
    auto has_group = [&] {
      bool found = false;
      for (auto* g : toolbox->findChildren<nfcad::ui::ToolGroup*>()) found = found || g->groupId() == QStringLiteral("plugin_demo");
      return found;
    };
    QTRY_VERIFY_WITH_TIMEOUT(!has_group(), 5000);
    auto* chooser = w.findChild<nfcad::ui::PluginPanel*>()->findChild<QComboBox*>();
    QCOMPARE(chooser->findData(QStringLiteral("demo")), -1);
    QMenu* demo_menu = menu_named(plugins, QStringLiteral("Demo plugin"));
    QVERIFY(demo_menu != nullptr && !demo_menu->actions().isEmpty());
    // and back
    show = menu_named(plugins, QStringLiteral("Show in the side panels"));
    for (QAction* a : show->actions()) {
      if (a->text().contains(QStringLiteral("Demo plugin"))) a->setChecked(true);
    }
    QTRY_VERIFY_WITH_TIMEOUT(has_group(), 5000);
    QVERIFY(chooser->findData(QStringLiteral("demo")) >= 0);
  }

  void workflowEditsAreUndoSteps() {
    // every edit in the node editor is one undo step; dragging a block is one at the release
    QStandardPaths::setTestModeEnabled(true);
    nfcad::app::MainWindow w;
    w.setAttribute(Qt::WA_DontShowOnScreen);
    w.resize(1400, 900);
    w.show();
    auto* doc = w.findChild<nfcad::document::Document*>();
    auto* editor = w.findChild<nfcad::ui::NodeEditor*>();
    QVERIFY(doc != nullptr && editor != nullptr);
    const QJsonObject wf{{"model", QJsonObject{{"format", "rtt-fusion-graph"}, {"version", 2},
                                               {"nodes", QJsonArray{QJsonObject{{"id", "a"}, {"type", "rtt.source"},
                                                                                {"position", QJsonArray{0, 0}}},
                                                                    QJsonObject{{"id", "b"}, {"type", "rtt.detector"},
                                                                                {"position", QJsonArray{400, 160}}}}},
                                               {"connections", QJsonArray{}}}}};
    doc->setWorkflow(wf);
    doc->requestWorkflowShown();
    doc->markSaved();
    QApplication::processEvents();  // fitAll
    auto node = [](const QJsonObject& workflow, const QString& id) {
      for (const QJsonValue& v : workflow["model"].toObject()["nodes"].toArray()) {
        if (v.toObject()["id"].toString() == id) return v.toObject();
      }
      return QJsonObject{};
    };
    QCOMPARE(doc->undoStack()->count(), 0);
    editor->setMuted(QStringLiteral("b"), true);
    QCOMPARE(doc->undoStack()->count(), 1);
    QVERIFY(doc->isModified());
    QVERIFY(node(doc->workflow(), QStringLiteral("b"))["muted"].toBool());
    doc->undoStack()->undo();
    QCOMPARE(doc->workflow(), wf);
    QVERIFY(!doc->isModified());
    QVERIFY(!node(editor->workflow(), QStringLiteral("b"))["muted"].toBool());  // the editor follows
    doc->undoStack()->redo();
    QVERIFY(node(editor->workflow(), QStringLiteral("b"))["muted"].toBool());

    // drag block a: many mouse moves, one undo step
    QGraphicsRectItem* a = editor->nodeItem(QStringLiteral("a"));
    QVERIFY(a != nullptr);
    const QPoint from = editor->mapFromScene(a->sceneBoundingRect().center());
    QWidget* vp = editor->viewport();
    QTest::mousePress(vp, Qt::LeftButton, {}, from);
    for (int k = 1; k <= 10; ++k) {
      const QPoint p = from + QPoint(6 * k, 3 * k);
      QMouseEvent move(QEvent::MouseMove, QPointF(p), QPointF(vp->mapToGlobal(p)), Qt::NoButton, Qt::LeftButton,
                       Qt::NoModifier);
      QApplication::sendEvent(vp, &move);
    }
    QTest::mouseRelease(vp, Qt::LeftButton, {}, from + QPoint(60, 30));
    QCOMPARE(doc->undoStack()->count(), 2);
    const QJsonArray moved = node(doc->workflow(), QStringLiteral("a"))["position"].toArray();
    QVERIFY(moved != QJsonArray({0, 0}));
    doc->undoStack()->undo();
    QCOMPARE(node(doc->workflow(), QStringLiteral("a"))["position"].toArray(), QJsonArray({0, 0}));
    QCOMPARE(node(editor->workflow(), QStringLiteral("a"))["position"].toArray(), QJsonArray({0, 0}));
  }

  void recentFilesAndFileOpenEvents() {
    // File → Open Recent, and documents opened in the Finder (QFileOpenEvent to the application)
    QStandardPaths::setTestModeEnabled(true);
    const QString organization = QCoreApplication::organizationName();
    QCoreApplication::setOrganizationName(QStringLiteral("RaytatouilleFusionTest"));  // not the user's list
    QSettings().remove(QStringLiteral("recentFiles"));
    QTemporaryDir dir;
    const QString a = dir.filePath(QStringLiteral("a.rttf"));
    const QString b = dir.filePath(QStringLiteral("b.rttf"));
    {
      nfcad::document::Document d;
      d.addEntities({nfcad::document::make_entity(nf::Vec3{1, 2, 3}, QStringLiteral("p"))}, QStringLiteral("add"));
      QVERIFY(nfcad::document::save_nfcad(d, a).isEmpty());
      QVERIFY(nfcad::document::save_nfcad(d, b).isEmpty());
    }
    {
      nfcad::app::MainWindow w;
      w.setAttribute(Qt::WA_DontShowOnScreen);
      w.show();
      auto* doc = w.findChild<nfcad::document::Document*>();
      w.openRequested(a);
      QCOMPARE(doc->filePath(), a);
      QCOMPARE(nfcad::app::MainWindow::recentFiles(), QStringList{a});

      QFileOpenEvent open(b);
      QApplication::sendEvent(qApp, &open);
      QTRY_COMPARE(doc->filePath(), b);
      QCOMPARE(nfcad::app::MainWindow::recentFiles(), (QStringList{b, a}));

      auto* menu = w.findChild<QMenu*>(QStringLiteral("recentMenu"));
      QVERIFY(menu != nullptr);
      emit menu->aboutToShow();
      QCOMPARE(menu->actions().size(), 4);  // b, a, separator, Clear list
      QVERIFY(menu->actions()[0]->text().endsWith(QStringLiteral("b.rttf")));
      menu->actions()[1]->trigger();
      QCOMPARE(doc->filePath(), a);
      QCOMPARE(nfcad::app::MainWindow::recentFiles(), (QStringList{a, b}));

      emit menu->aboutToShow();
      auto* clear = menu->findChild<QAction*>(QStringLiteral("clearRecent"));
      QVERIFY(clear != nullptr && clear->isEnabled());
      clear->trigger();
      QVERIFY(nfcad::app::MainWindow::recentFiles().isEmpty());
    }
    QSettings().remove(QStringLiteral("recentFiles"));
    QCoreApplication::setOrganizationName(organization);
  }
};

QTEST_MAIN(TestMainWindowPlugins)
#include "test_main_window_plugins.moc"
