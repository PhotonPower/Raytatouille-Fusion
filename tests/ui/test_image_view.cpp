#include <QCheckBox>
#include <QComboBox>
#include <QImage>
#include <QTest>
#include <QWheelEvent>

#include "results/result_store.hpp"
#include "ui/image_view.hpp"

using namespace nfcad;

namespace {
results::Image spot(int w, int h) {
  results::Image im;
  im.width = w;
  im.height = h;
  im.values.assign(static_cast<std::size_t>(w) * h, 0.0F);
  im.values[static_cast<std::size_t>(h / 2) * w + w / 2] = 1000.0F;  // one bright pixel
  im.values[0] = 0.01F;                                              // faint light (log scale)
  im.x0 = -6.4;
  im.x1 = 6.4;
  im.y0 = -4.8;
  im.y1 = 4.8;
  im.x_label = QStringLiteral("x / mm");
  im.y_label = QStringLiteral("y / mm");
  im.unit = QStringLiteral("W/mm²");
  return im;
}
}  // namespace

class TestImageView : public QObject {
  Q_OBJECT
 private slots:
  void showsTheNewestImage() {
    results::ResultStore store;
    ui::ImageView view(&store);
    view.resize(500, 420);
    QVERIFY(view.current() == nullptr);
    const auto run = store.createSet(QStringLiteral("Camera image"));
    store.addImage(run, QStringLiteral("CAM"), spot(64, 48));
    QVERIFY(view.current() != nullptr);
    QCOMPARE(view.current()->name, QStringLiteral("CAM"));
    QVERIFY(!view.findChild<QComboBox*>()->isVisibleTo(&view));  // one image: no list
    store.addImage(run, QStringLiteral("PUP"), spot(32, 32));
    QCOMPARE(view.current()->name, QStringLiteral("PUP"));  // the newest
    QCOMPARE(view.findChild<QComboBox*>()->count(), 2);
    QVERIFY(view.findChild<QComboBox*>()->isVisibleTo(&view));
    // the user's choice stays while new runs arrive
    view.findChild<QComboBox*>()->setCurrentIndex(0);
    QCOMPARE(view.current()->name, QStringLiteral("CAM"));
  }

  void rendersLinearLogZoom() {
    results::ResultStore store;
    ui::ImageView view(&store);
    view.resize(500, 420);
    store.addImage(store.createSet(QStringLiteral("run")), QStringLiteral("CAM"), spot(64, 48));
    const QImage linear = view.grab().toImage();
    QVERIFY(!linear.isNull());
    view.setLogScale(true);
    const QImage log = view.grab().toImage();
    QVERIFY(linear != log);  // the faint pixel shows on the log scale
    auto* canvas = view.findChild<ui::ImageCanvas*>();
    const QPointF centre(canvas->width() / 2.0, canvas->height() / 2.0);
    QWheelEvent wheel(centre, canvas->mapToGlobal(centre), {}, QPoint(0, 600), Qt::NoButton, Qt::NoModifier,
                      Qt::NoScrollPhase, false);
    QCoreApplication::sendEvent(canvas, &wheel);
    const QImage zoomed = view.grab().toImage();
    QVERIFY(zoomed != log);
    QTest::mouseDClick(canvas, Qt::LeftButton, {}, centre.toPoint());
    QCOMPARE(view.grab().toImage(), log);  // double-click: all of it again
    if (const QByteArray dir = qgetenv("NFCAD_SNAPSHOT_DIR"); !dir.isEmpty()) {
      zoomed.save(QString::fromLocal8Bit(dir) + QStringLiteral("/image_view_zoomed.png"));
    }
  }

  void showsColoursAsTheyAre() {
    results::ResultStore store;
    ui::ImageView view(&store);
    view.resize(500, 420);
    results::Image im = spot(64, 48);
    im.rgb.assign(3 * im.values.size(), 0);
    for (int j = 0; j < 48; ++j) {  // left half red, right half green; the top row blue
      for (int i = 0; i < 64; ++i) im.rgb[3 * (static_cast<std::size_t>(j) * 64 + i) + (j == 47 ? 2 : i < 32 ? 0 : 1)] = 255;
    }
    store.addImage(store.createSet(QStringLiteral("run")), QStringLiteral("colour"), std::move(im));
    auto* canvas = view.findChild<ui::ImageCanvas*>();
    const QImage shown = canvas->grab().toImage();
    int red = 0, green = 0, blue = 0, blue_row = shown.height(), red_row = 0;
    for (int y = 0; y < shown.height(); ++y) {
      for (int x = 0; x < shown.width(); ++x) {
        const QColor c = shown.pixelColor(x, y);
        red += c == QColor(255, 0, 0) ? 1 : 0;
        green += c == QColor(0, 255, 0) ? 1 : 0;
        if (c == QColor(0, 0, 255)) {
          ++blue;
          blue_row = std::min(blue_row, y);
        } else if (c == QColor(255, 0, 0)) {
          red_row = std::max(red_row, y);
        }
      }
    }
    QVERIFY2(red > 1000 && green > 1000 && blue > 20, qPrintable(QStringLiteral("%1 %2 %3").arg(red).arg(green).arg(blue)));
    QVERIFY(std::abs(red - green) < red / 10);
    QVERIFY(blue_row < red_row);  // the last row of the image is on top
    // no scale: the log switch is off and changes nothing
    QVERIFY(!view.findChild<QCheckBox*>()->isEnabled());
    view.setLogScale(true);
    QCOMPARE(canvas->grab().toImage(), shown);
    // a scalar image has its scale again
    store.addImage(store.createSet(QStringLiteral("run 2")), QStringLiteral("CAM"), spot(64, 48));
    QVERIFY(view.findChild<QCheckBox*>()->isEnabled());
  }
};

QTEST_MAIN(TestImageView)
#include "test_image_view.moc"
