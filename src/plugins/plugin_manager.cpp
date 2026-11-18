#include "plugins/plugin_manager.hpp"

#include "plugins/block_router.hpp"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QSettings>
#include <QStandardPaths>
#include <algorithm>
#include <memory>

#include "plugins/signature.hpp"

namespace nfcad::plugins {

PluginManager::PluginManager(document::Document* doc, document::Selection* selection,
                             results::ResultStore* results, QObject* parent)
    : QObject(parent), doc_(doc), selection_(selection), results_(results) {
  // the node workflow's requests between plugins (ADR 0010)
  router_ = new BlockRouter(
      [this] {
        std::vector<PluginHost*> out;
        for (const auto& h : hosts_) out.push_back(h.get());
        return out;
      },
      [this](PluginHost* h) { h->start(python(), nfcadPythonPath()); }, this);
}

PluginManager::~PluginManager() {
  for (auto& h : hosts_) h->stop();
}

QString PluginManager::python() const {
  const QString set = QSettings().value(QStringLiteral("plugins/python")).toString();
  if (!set.isEmpty()) return set;
  const QString env = qEnvironmentVariable("NFCAD_PYTHON");
  if (!env.isEmpty()) return env;
#ifdef NFCAD_PYTHON_SOURCE_DIR
  // development build: the repository's .venv (docs/plugin-api.md)
  for (const char* rel : {"/../.venv/bin/python", "/../.venv/Scripts/python.exe"}) {
    const QString dev = QDir::cleanPath(QStringLiteral(NFCAD_PYTHON_SOURCE_DIR) + QString::fromLatin1(rel));
    if (QFileInfo::exists(dev)) return dev;
  }
#endif
#ifdef Q_OS_WIN
  // python.org installs python.exe and the launcher py.exe; python3.exe / python.exe under
  // \WindowsApps\ are the Store's stubs, which only open the Microsoft Store
  for (const char* name : {"python", "py", "python3"}) {
    const QString found = QStandardPaths::findExecutable(QString::fromLatin1(name));
    if (!found.isEmpty() && !found.contains(QStringLiteral("WindowsApps"), Qt::CaseInsensitive)) return found;
  }
#else
  for (const char* name : {"python3", "python"}) {
    const QString found = QStandardPaths::findExecutable(QString::fromLatin1(name));
    if (!found.isEmpty()) return found;
  }
#endif
  return QStringLiteral("python3");
}

void PluginManager::setPython(const QString& path) {
  QSettings().setValue(QStringLiteral("plugins/python"), path);
  for (auto& h : hosts_) h->stop();
}

QString PluginManager::installFolder() {
  const QString env = qEnvironmentVariable("NFCAD_PLUGIN_INSTALL_DIR");
  if (!env.isEmpty()) return env;
  return QDir(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)).filePath(QStringLiteral("plugins"));
}

Installation PluginManager::install(const QString& package) {
  for (auto& h : hosts_) h->stop();  // an installed version may be running from its folder
  Installation r = install_plugin(package, installFolder(), trustedKeys(), developerMode());
  reload();
  return r;
}

QString PluginManager::uninstall(const QString& id) {
  for (auto& h : hosts_) h->stop();
  const QString error = uninstall_plugin(installFolder(), id);
  reload();
  return error;
}

bool PluginManager::isInstalled(const PluginHost* host) const {
  return QFileInfo(host->manifest().source_directory).absolutePath() == QDir(installFolder()).absolutePath();
}

QStringList PluginManager::requirements() const {
  QStringList out{QStringLiteral("numpy")};  // the nfcad package uses it for arrays
  for (const auto& h : hosts_) {
    for (const QString& r : h->manifest().requirements) {
      if (!out.contains(r)) out << r;
    }
  }
  return out;
}

EnvironmentReport PluginManager::checkEnvironment() const {
  return check_environment(python(), requirements());
}

QString PluginManager::bundledFolder() {
  const QDir app(QCoreApplication::applicationDirPath());
  // only the places of an installation (not the source tree of a development build)
  for (const char* rel : {"../Resources/python/plugins", "../share/raytatouille-fusion/python/plugins", "../python/plugins"}) {
    const QString dir = app.filePath(QString::fromLatin1(rel));
    if (QFileInfo::exists(QDir(dir).filePath(QStringLiteral("../nfcad/__init__.py")))) return QDir(dir).absolutePath();
  }
  return {};
}

QStringList PluginManager::folders() const {
  QStringList out = QSettings().value(QStringLiteral("plugins/folders")).toStringList();
  for (const QString& p : qEnvironmentVariable("NFCAD_PLUGIN_PATH").split(QDir::listSeparator(), Qt::SkipEmptyParts)) {
    if (!out.contains(p)) out << p;
  }
#ifdef NFCAD_PYTHON_SOURCE_DIR
  if (out.isEmpty()) {  // development build: the examples and the plugins of the repository
    out << QStringLiteral(NFCAD_PYTHON_SOURCE_DIR "/examples") << QStringLiteral(NFCAD_PYTHON_SOURCE_DIR "/plugins");
  }
#endif
  if (!out.contains(installFolder())) out.prepend(installFolder());  // installed plugins win over same ids
  const QString bundled = bundledFolder();
  if (!bundled.isEmpty() && !out.contains(bundled)) out << bundled;  // last: one's own folders win
  return out;
}

void PluginManager::setFolders(const QStringList& folders) {
  QSettings().setValue(QStringLiteral("plugins/folders"), folders);
  reload();
}

QString PluginManager::nfcadPythonPath() {
  const QString env = qEnvironmentVariable("NFCAD_PYTHONPATH");
  if (!env.isEmpty()) return env;
  const QDir app(QCoreApplication::applicationDirPath());
  const QStringList candidates = {
      app.filePath(QStringLiteral("../Resources/python")),           // macOS bundle
      app.filePath(QStringLiteral("../share/raytatouille-fusion/python")),  // Linux
      app.filePath(QStringLiteral("../python")),                      // Windows (<prefix>/bin/..)
#ifdef NFCAD_PYTHON_SOURCE_DIR
      QStringLiteral(NFCAD_PYTHON_SOURCE_DIR),                        // development build
#endif
  };
  for (const QString& c : candidates) {
    if (QFileInfo::exists(QDir(c).filePath(QStringLiteral("nfcad/__init__.py")))) return QDir(c).absolutePath();
  }
  return {};
}

bool PluginManager::developerMode() const {
  return QSettings().value(QStringLiteral("plugins/developerMode"), false).toBool() ||
         qEnvironmentVariable("NFCAD_DEVELOPER_MODE") == QLatin1String("1");
}

void PluginManager::setDeveloperMode(bool on) {
  QSettings().setValue(QStringLiteral("plugins/developerMode"), on);
  reload();
}

QStringList PluginManager::trustedKeys() const {
  return trusted_override_ ? *trusted_override_ : built_in_publisher_keys();
}

void PluginManager::reload() {
  for (auto& h : hosts_) h->stop();
  hosts_.clear();
  problems_.clear();
  runtime_ = std::make_unique<QTemporaryDir>();  // the previous copies are removed
  const bool developer = developerMode();
  const QStringList keys = trustedKeys();
  int copies = 0;
  const QString bundled = bundledFolder();
  for (const QString& folder : folders()) {
    const QDir dir(folder);
    // part of the installed application (write-protected like the executable): no signature needed
    const bool shipped = !bundled.isEmpty() && dir.absolutePath() == bundled;
    const QStringList subdirs = dir.entryList(QDir::Dirs | QDir::NoDotAndDotDot, QDir::Name);
    for (const QString& sub : subdirs) {
      const QString path = dir.filePath(sub);
      if (!QFileInfo::exists(QDir(path).filePath(QStringLiteral("plugin.json")))) continue;
      // signed: check a private copy and run that; otherwise only in developer mode, from the folder
      const QString copy = !shipped && runtime_->isValid() ? runtime_->filePath(QString::number(++copies)) : QString();
      const Verification v = copy.isEmpty() ? Verification{} : verify_plugin(path, keys, copy);
      if (!v.ok() && !developer && !shipped) {
        problems_ << tr("%1: %2 – not loaded (only signed plugins; unsigned ones in developer mode)")
                         .arg(QDir::toNativeSeparators(path), v.message.isEmpty() ? tr("cannot be checked") : v.message);
        continue;
      }
      QString error;
      auto m = read_manifest(v.ok() ? copy : path, &error);
      if (!m) {
        problems_ << QStringLiteral("%1: %2").arg(path, error);
        continue;
      }
      m->source_directory = QDir(path).absolutePath();
      m->trusted = v.ok() || shipped;
      if (!m->trusted) {
        m->trust_note = v.status == Verification::Status::Unsigned ? tr("unsigned") : tr("signature invalid");
        problems_ << tr("%1: %2 – loaded because developer mode is on").arg(QDir::toNativeSeparators(path), v.message);
      }
      if (plugin(m->id) != nullptr) {
        if (shipped) continue;  // the user's own folder has this plugin: it replaces the bundled one
        problems_ << tr("%1: plugin id '%2' is used twice").arg(path, m->id);
        continue;
      }
      hosts_.push_back(std::make_unique<PluginHost>(*m, doc_, selection_, results_, this));
      router_->attach(hosts_.back().get());
    }
  }
  emit pluginsChanged();
}

PluginHost* PluginManager::plugin(const QString& id) const {
  for (const auto& h : hosts_) {
    if (h->manifest().id == id) return h.get();
  }
  return nullptr;
}

std::vector<PluginHost*> PluginManager::previewOrder(const std::vector<PluginHost*>& hosts, const QString& type,
                                                    const QString& provider) {
  std::vector<PluginHost*> out;
  auto add = [&out](PluginHost* h) {
    if (h != nullptr && std::find(out.begin(), out.end(), h) == out.end()) out.push_back(h);
  };
  for (PluginHost* h : hosts) {
    if (!provider.isEmpty() && h->manifest().id == provider) add(h);
  }
  for (PluginHost* h : hosts) {
    if (h->provides(type)) add(h);
  }
  for (PluginHost* h : hosts) {
    if (h->draws(type)) add(h);
  }
  return out;
}

std::vector<PluginHost*> PluginManager::previewers(const QString& type, const QString& provider) const {
  std::vector<PluginHost*> all;
  for (const auto& h : hosts_) all.push_back(h.get());
  return previewOrder(all, type, provider);
}

void PluginManager::preview(const QString& type, const QString& provider, const QJsonObject& request, QObject* context,
                            std::function<void(const QJsonObject&)> done) {
  // one after the other: a plugin that does not draw the type passes it on
  auto ask = std::make_shared<std::function<void(std::vector<PluginHost*>, QString)>>();
  *ask = [this, request, context, done, type, weak = std::weak_ptr(ask)](std::vector<PluginHost*> left, QString why) {
    if (left.empty()) {
      done(QJsonObject{{"ok", false},
                       {"unsupported", true},
                       {"error", why.isEmpty() ? tr("no plugin draws blocks of type %1").arg(type) : why}});
      return;
    }
    PluginHost* h = left.front();
    left.erase(left.begin());
    if (!h->running()) h->start(python(), nfcadPythonPath());
    h->preview(request, context, [done, left, why, next = weak.lock()](const QJsonObject& answer) {
      if (answer["unsupported"].toBool() && next) {
        (*next)(left, why.isEmpty() ? answer["error"].toString() : why);
      } else {
        done(answer);
      }
    });
  };
  (*ask)(previewers(type, provider), {});
}

int PluginManager::run(PluginHost* host, const QString& action, const QJsonObject& params, const QJsonObject& target) {
  if (!host->running()) host->start(python(), nfcadPythonPath());
  const int job = host->run(action, params, target);
  if (job != 0) emit jobStarted(host, job);
  return job;
}

}  // namespace nfcad::plugins
