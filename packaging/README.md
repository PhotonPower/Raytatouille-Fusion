# Packaging (M7)

| Platform | Files | Built by |
|---|---|---|
| Windows 11 | `windows/raytatouille-fusion.iss` (Inno Setup) | `.github/workflows/package.yml`, job `windows` |
| AlmaLinux / RHEL 10 | `linux/raytatouille-fusion.spec` (RPM) | job `almalinux10` |
| macOS | `macos/make_dmg.sh` (unsigned DMG; signing in M8) | job `macos` |

All start from `cmake --install <build> --component app`, which installs only the application
(not the Nurbforge kernel's development files) and, on Windows and macOS, deploys Qt into the
staging directory. See the build guides in `docs/build/`.

File types: the macOS bundle declares `.rttf` / `.nfcad`, STEP and `.nfplugin`
(`resources/macos/Info.plist.in`, set as `MACOSX_BUNDLE_INFO_PLIST`); on Linux the install puts
the MIME types (`resources/linux/*.mime.xml` → `share/mime/packages/`) next to the desktop file,
which names them. The RPM lists the file; the shared-mime-info file trigger updates the database.
