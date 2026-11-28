#include <QTest>
#include <QThread>
#include <QTimer>
#include <stdexcept>

#include "commands/command_util.hpp"

using nfcad::commands::util::run_responsive;

class TestRunResponsive : public QObject {
  Q_OBJECT
 private slots:
  void eventLoopRunsMeanwhile() {
    int ticks = 0;
    QTimer timer;
    QObject::connect(&timer, &QTimer::timeout, [&] { ++ticks; });
    timer.start(10);
    bool on_worker = false;
    int result = 0;
    run_responsive([&] {
      on_worker = QThread::currentThread() != qApp->thread();
      QThread::msleep(200);
      result = 42;
    });
    QCOMPARE(result, 42);
    QVERIFY(on_worker);
    QVERIFY2(ticks >= 3, qPrintable(QString::number(ticks)));  // the window would have redrawn
  }

  void exceptionsReachTheCaller() {
    bool caught = false;
    try {
      run_responsive([] { throw std::runtime_error("shrink_wrap: too many nodes"); });
    } catch (const std::runtime_error& e) {
      caught = QString::fromUtf8(e.what()).contains(QLatin1String("too many"));
    }
    QVERIFY(caught);
  }
};

QTEST_MAIN(TestRunResponsive)
#include "test_run_responsive.moc"
