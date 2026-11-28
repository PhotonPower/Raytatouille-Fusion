#include "commands/command_util.hpp"

#include <QCoreApplication>
#include <QCursor>
#include <QEventLoop>
#include <QFutureWatcher>
#include <QGuiApplication>
#include <QtConcurrent/QtConcurrentRun>

namespace nfcad::commands::util {

void run_responsive(const std::function<void()>& work) {
  auto* gui = qobject_cast<QGuiApplication*>(QCoreApplication::instance());
  if (gui == nullptr) {
    work();
    return;
  }
  std::exception_ptr error;
  QFutureWatcher<void> watcher;
  QEventLoop loop;
  QObject::connect(&watcher, &QFutureWatcher<void>::finished, &loop, &QEventLoop::quit);
  QGuiApplication::setOverrideCursor(Qt::BusyCursor);
  watcher.setFuture(QtConcurrent::run([&work, &error] {
    try {
      work();
    } catch (...) {
      error = std::current_exception();
    }
  }));
  if (!watcher.isFinished()) loop.exec(QEventLoop::ExcludeUserInputEvents);
  watcher.waitForFinished();
  QGuiApplication::restoreOverrideCursor();
  if (error) std::rethrow_exception(error);
}

}  // namespace nfcad::commands::util
