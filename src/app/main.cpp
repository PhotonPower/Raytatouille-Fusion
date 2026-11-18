#include <QApplication>
#include <QCommandLineParser>
#include <QFile>
#include <QPalette>
#include <QSettings>
#include <QStyleFactory>
#include <QStyleHints>

#include "app/main_window.hpp"
#include "support/crash_handler.hpp"
#include "support/settings_migration.hpp"

namespace {

// The theme is dark (dark.qss). The style sheet colours only some widgets; everything else (menu
// bar, menus, labels in the panels, dialogs) takes the palette. Under a light system theme that
// was dark text on the style sheet's dark background (Windows), so the palette is made dark too.
void use_dark_palette() {
  QGuiApplication::styleHints()->setColorScheme(Qt::ColorScheme::Dark);  // macOS: the native dark look
#ifndef Q_OS_MACOS
  // Windows / Linux: Fusion with the colours of dark.qss (docs/ui-concept.md, "Visual style")
  QApplication::setStyle(QStyleFactory::create(QStringLiteral("Fusion")));
  QPalette p;
  const QColor window(0x25, 0x28, 0x2d), text(0xd8, 0xdc, 0xe2), base(0x1c, 0x1e, 0x22), button(0x30, 0x34, 0x3b);
  const QColor disabled(0x6b, 0x71, 0x7a);
  p.setColor(QPalette::Window, window);
  p.setColor(QPalette::WindowText, text);
  p.setColor(QPalette::Base, base);
  p.setColor(QPalette::AlternateBase, QColor(0x2c, 0x30, 0x36));
  p.setColor(QPalette::Text, QColor(0xe6, 0xe9, 0xee));
  p.setColor(QPalette::Button, button);
  p.setColor(QPalette::ButtonText, text);
  p.setColor(QPalette::BrightText, Qt::white);
  p.setColor(QPalette::ToolTipBase, QColor(0x2c, 0x30, 0x36));
  p.setColor(QPalette::ToolTipText, QColor(0xe6, 0xe9, 0xee));
  p.setColor(QPalette::PlaceholderText, QColor(0x8a, 0x90, 0x99));
  p.setColor(QPalette::Highlight, QColor(0x3d, 0x5a, 0x80));
  p.setColor(QPalette::HighlightedText, Qt::white);
  p.setColor(QPalette::Link, QColor(0x6f, 0xa8, 0xdc));
  p.setColor(QPalette::LinkVisited, QColor(0xa0, 0x8c, 0xd0));
  p.setColor(QPalette::Light, QColor(0x3a, 0x3f, 0x47));
  p.setColor(QPalette::Midlight, QColor(0x33, 0x37, 0x3e));
  p.setColor(QPalette::Mid, QColor(0x2a, 0x2d, 0x33));
  p.setColor(QPalette::Dark, QColor(0x18, 0x1a, 0x1d));
  p.setColor(QPalette::Shadow, QColor(0x10, 0x11, 0x13));
  for (const auto role : {QPalette::WindowText, QPalette::Text, QPalette::ButtonText}) {
    p.setColor(QPalette::Disabled, role, disabled);
  }
  p.setColor(QPalette::Disabled, QPalette::Highlight, QColor(0x3a, 0x3f, 0x47));
  QApplication::setPalette(p);
#endif
}

}  // namespace

int main(int argc, char* argv[]) {
  QApplication app(argc, argv);
  QApplication::setOrganizationName(QStringLiteral("PhotonPower"));
  QApplication::setOrganizationDomain(QStringLiteral("photonpower.github.io"));
  QApplication::setApplicationName(QStringLiteral("Raytatouille Fusion"));
  QApplication::setApplicationVersion(QStringLiteral(NFCAD_VERSION));

  // local crash reports (nothing is sent), settings of older versions
  nfcad::support::CrashHandler::install(nfcad::support::CrashHandler::defaultFolder(), QStringLiteral(NFCAD_VERSION));
  if (QSettings settings; true) {
    nfcad::support::migrate_settings(settings, {QApplication::organizationDomain(), QApplication::organizationName()});
  }

  QCommandLineParser parser;
  parser.setApplicationDescription(
      QStringLiteral("Raytatouille Fusion – CAD front end for Nurbforge and its computation kernels"));
  parser.addHelpOption();
  parser.addVersionOption();
  parser.addPositionalArgument(QStringLiteral("file"),
                               QStringLiteral("Document (.rttf, or .nfcad from before 1.0) or STEP file to open, or a plugin package (.nfplugin) to install"));
  const QCommandLineOption benchmark(
      QStringLiteral("benchmark"),
      QStringLiteral("Open the file, orbit the 3D view for <frames> frames, print timings, quit."),
      QStringLiteral("frames"));
  parser.addOption(benchmark);
  const QCommandLineOption display_mode(
      QStringLiteral("display-mode"),
      QStringLiteral("Initial display mode of all views: wireframe, surfaces or shaded."),
      QStringLiteral("mode"));
  parser.addOption(display_mode);
  parser.process(app);

  use_dark_palette();
  if (QFile style(QStringLiteral(":/styles/dark.qss")); style.open(QIODevice::ReadOnly)) {
    app.setStyleSheet(QString::fromUtf8(style.readAll()));
  }

  nfcad::app::MainWindow window;
  if (parser.isSet(benchmark)) window.runBenchmarkWhenReady(parser.value(benchmark).toInt());
  if (parser.isSet(display_mode)) window.setDisplayModeAll(parser.value(display_mode));
  window.show();
  window.reportPreviousCrash();
  if (!parser.positionalArguments().isEmpty()) {
    if (!window.openFile(parser.positionalArguments().constFirst(), parser.isSet(benchmark))) {
      return 1;
    }
  }
  return QApplication::exec();
}
