#include <QSet>
#include <QSignalSpy>
#include <QTest>
#include <QToolButton>

#include "commands/command.hpp"
#include "ui/tool_box.hpp"
#include "ui/tool_catalog.hpp"

using nfcad::ui::ToolGroup;

class TestToolCatalog : public QObject {
  Q_OBJECT
 private slots:
  void idsAreUnique() {
    QSet<QString> ids;
    for (const auto& group : nfcad::ui::tool_catalog()) {
      QVERIFY(!group.tools.empty());
      for (const auto& tool : group.tools) {
        QVERIFY2(!ids.contains(tool.id), qPrintable(tool.id));
        ids.insert(tool.id);
      }
    }
  }

  void aliasesStartTheirCommand() {
    // the tooltip shows the alias to type (not a fake one-letter shortcut); it must start the
    // tool's command
    for (const auto& group : nfcad::ui::tool_catalog()) {
      for (const auto& tool : group.tools) {
        if (tool.id == QLatin1String("delete")) {  // the Edit menu's Delete, a real shortcut
          QVERIFY(tool.alias.isEmpty() && !tool.shortcut.isEmpty());
          continue;
        }
        QVERIFY2(!tool.alias.isEmpty(), qPrintable(tool.id));
        QVERIFY2(tool.shortcut.isEmpty(), qPrintable(tool.id));  // no unregistered shortcuts
        const auto cmd = nfcad::commands::create_command(tool.alias);
        QVERIFY2(cmd != nullptr, qPrintable(tool.alias));
        QCOMPARE(cmd->id(), tool.id);
        QVERIFY(nfcad::ui::tool_tip(tool).contains(QStringLiteral("Type: %1 + Enter").arg(tool.alias)));
      }
    }
    const auto& line = nfcad::ui::tool_catalog().front().tools[1];
    QCOMPARE(nfcad::ui::tool_tip(line), QStringLiteral("Line\nType: l + Enter"));
  }

  void groupCollapsesAndEmits() {
    ToolGroup group(nfcad::ui::tool_catalog().front());
    group.resize(150, 400);
    group.show();
    QVERIFY(group.isExpanded());
    QSignalSpy expanded(&group, &ToolGroup::expandedChanged);
    group.setExpanded(false);
    QCOMPARE(expanded.count(), 1);
    QVERIFY(!group.isExpanded());

    QSignalSpy triggered(&group, &ToolGroup::toolTriggered);
    group.setExpanded(true);
    auto* button = group.findChild<QToolButton*>(QStringLiteral("toolButton"));
    QVERIFY(button != nullptr);
    button->click();
    QCOMPARE(triggered.count(), 1);
  }
};

QTEST_MAIN(TestToolCatalog)
#include "test_tool_catalog.moc"
