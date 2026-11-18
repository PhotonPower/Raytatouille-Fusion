# macOS resources (M8)

- `Info.plist.in` – the application's `Info.plist` template (Qt's `Info.plist.app.in` plus the
  document types): `CFBundleDocumentTypes` and the UTIs for `.rttf` / `.nfcad` (documents),
  `.step` / `.stp` (opened as a new document) and `.nfplugin` (installed). A file opened in the
  Finder reaches the application as `QFileOpenEvent` (`MainWindow::eventFilter`).
- Planned: `.icns` app icon, entitlements for signing and notarisation.
