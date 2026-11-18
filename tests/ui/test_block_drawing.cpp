#include <QApplication>
#include <QDialog>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLineEdit>
#include <QPainter>
#include <QPushButton>
#include <QTabWidget>
#include <QTest>
#include <QTimer>
#include <cmath>
#include <functional>

#include "ui/block_drawing.hpp"
#include "ui/node_editor.hpp"

using nfcad::ui::Drawing;
using nfcad::ui::DrawingView;
using nfcad::ui::NodeEditor;
using nfcad::ui::parse_drawing;
using nfcad::ui::schematic_drawing;

namespace {
QJsonArray pt(double x, double y) { return QJsonArray{x, y}; }

QJsonObject lens_drawing() {
  return QJsonObject{
      {"format", "nfcad-drawing"},
      {"version", 1},
      {"title", "L1"},
      {"unit", "mm"},
      {"axes", QJsonArray{"z", "y"}},
      {"items", QJsonArray{QJsonObject{{"type", "polygon"},
                                       {"points", QJsonArray{pt(0, -5), pt(2, -5), pt(2.5, 0), pt(2, 5), pt(0, 5)}},
                                       {"material", "N-BK7"}},
                           QJsonObject{{"type", "polyline"}, {"points", QJsonArray{pt(-2, 0), pt(10, 0)}}, {"role", "axis"}},
                           QJsonObject{{"type", "polyline"}, {"points", QJsonArray{pt(-2, 3), pt(1, 3), pt(9, 0)}}, {"role", "ray"}},
                           QJsonObject{{"type", "text"}, {"at", pt(1, 5.5)}, {"text", "L1"}, {"valign", "bottom"}},
                           QJsonObject{{"type", "dimension"}, {"from", pt(0, -6)}, {"to", pt(2, -6)}, {"text", "2 mm"}},
                           QJsonObject{{"type", "arrow"}, {"from", pt(-2, 4)}, {"to", pt(0, 4)}, {"text", "light"}}}},
      {"materials", QJsonArray{QJsonObject{{"name", "N-BK7"}, {"label", "N-BK7 · n = 1.5168"}}}},
      {"notes", QJsonArray{"R1 = 50 mm"}}};
}

/// Pixels of `image` that differ from its corner (the background).
int drawn_pixels(const QImage& image) {
  const QRgb bg = image.pixel(0, 0);
  int n = 0;
  for (int y = 0; y < image.height(); ++y) {
    for (int x = 0; x < image.width(); ++x) n += image.pixel(x, y) != bg ? 1 : 0;
  }
  return n;
}

/// Runs `body` on the parameter dialog `open` shows (and closes it).
void with_dialog(QObject* context, const std::function<void(QDialog*)>& body) {
  QTimer::singleShot(0, context, [body] {
    for (QWidget* w : QApplication::topLevelWidgets()) {
      if (auto* d = qobject_cast<QDialog*>(w); d != nullptr && d->isVisible()) {
        body(d);
        d->accept();
        return;
      }
    }
  });
}
}  // namespace

class TestBlockDrawing : public QObject {
  Q_OBJECT
 private slots:
  void parsesADrawing() {
    QStringList problems;
    const auto d = parse_drawing(lens_drawing(), &problems);
    QVERIFY(d.has_value());
    QVERIFY(problems.isEmpty());
    QCOMPARE(d->items.size(), std::size_t{6});
    QCOMPARE(d->title, QStringLiteral("L1"));
    QCOMPARE(d->unit, QStringLiteral("mm"));
    QCOMPARE(d->x_axis, QStringLiteral("z"));
    QVERIFY(d->equal_aspect && d->axes);
    QCOMPARE(d->items[0].kind, Drawing::Kind::Polygon);
    QCOMPARE(d->items[0].material, QStringLiteral("N-BK7"));
    QCOMPARE(d->items[4].kind, Drawing::Kind::Dimension);
    QCOMPARE(d->items[4].points[1], QPointF(2, -6));
    QCOMPARE(d->materials.size(), std::size_t{1});
    QCOMPARE(d->materials[0].label, QStringLiteral("N-BK7 · n = 1.5168"));
    QCOMPARE(d->bounds(), QRectF(QPointF(-2, -6), QPointF(10, 5.5)));
    // a material only a polygon names is in the legend too
    QJsonObject o = lens_drawing();
    o.remove("materials");
    QCOMPARE(parse_drawing(o)->materials[0].label, QStringLiteral("N-BK7"));
    // the same material has the same colour, air is nearly transparent
    const QPalette pal;
    QCOMPARE(d->materialFill("SF5", pal), d->materialFill("SF5", pal));
    QVERIFY(d->materialFill("air", pal).alphaF() < 0.2F);
  }

  void refusesMalformedDrawings() {
    auto refused = [](const QJsonObject& o, const QString& why) {
      QStringList problems;
      const bool none = !parse_drawing(o, &problems).has_value();
      return none && problems.join(QLatin1Char(' ')).contains(why);
    };
    QJsonObject o = lens_drawing();
    o["format"] = "svg";
    QVERIFY(refused(o, QStringLiteral("not a drawing")));
    QVERIFY(refused(QJsonObject{{"title", "x"}}, QStringLiteral("items")));
    o = lens_drawing();
    o["aspect"] = "stretched";
    QVERIFY(refused(o, QStringLiteral("aspect")));
    auto with_item = [](const QJsonObject& item) {
      QJsonObject d = lens_drawing();
      QJsonArray items = d["items"].toArray();
      items.append(item);
      d["items"] = items;
      return d;
    };
    QVERIFY(refused(with_item({{"type", "polygon"}, {"points", QJsonArray{pt(0, 0), pt(1, 1)}}}), QStringLiteral("at least 3")));
    QVERIFY(refused(with_item({{"type", "polyline"}, {"points", QJsonArray{pt(0, 0), QJsonArray{1, "a"}}}}), QStringLiteral("finite")));
    QVERIFY(refused(with_item({{"type", "polyline"}, {"points", QJsonArray{pt(0, 0), QJsonArray{1, 2, 3}}}}), QStringLiteral("points")));
    QVERIFY(refused(with_item({{"type", "text"}, {"at", pt(0, 0)}}), QStringLiteral("text")));
    QVERIFY(refused(with_item({{"type", "arrow"}, {"from", pt(0, 0)}}), QStringLiteral("'to'")));
    // too large for the dialog
    QJsonArray many;
    for (int k = 0; k <= nfcad::ui::kMaxDrawingItems; ++k) many.append(QJsonObject{{"type", "text"}, {"at", pt(k, 0)}, {"text", "x"}});
    QVERIFY(refused(QJsonObject{{"items", many}}, QStringLiteral("too many items")));
    QJsonArray long_line;
    for (int k = 0; k <= nfcad::ui::kMaxDrawingPoints; ++k) long_line.append(pt(k, 0));
    QVERIFY(refused(QJsonObject{{"items", QJsonArray{QJsonObject{{"type", "polyline"}, {"points", long_line}}}}},
                    QStringLiteral("too many points")));
    // an item type of a newer plugin is skipped, the drawing stays
    QStringList problems;
    const auto d = parse_drawing(with_item({{"type", "hologram"}}), &problems);
    QVERIFY(d.has_value());
    QCOMPARE(d->items.size(), std::size_t{6});
    QVERIFY(problems.join(QLatin1Char(' ')).contains(QStringLiteral("unknown item type")));
    // bad colours and widths are ignored
    const auto c = parse_drawing(with_item({{"type", "polyline"}, {"points", QJsonArray{pt(0, 0), pt(1, 1)}}, {"color", "nocolour"}, {"width", -3}}));
    QVERIFY(c.has_value() && !c->items.back().color.isValid() && c->items.back().width == 0.0);
  }

  void schematicOfABlock() {
    const QJsonObject type{{"type", "rtt.section"},
                           {"description", "Sequential surfaces"},
                           {"params", QJsonArray{QJsonObject{{"name", "location"}, {"type", "text"}, {"default", ""}}}},
                           {"ports", QJsonArray{QJsonObject{{"name", "front"}, {"side", "front"}},
                                                QJsonObject{{"name", "back"}, {"side", "back"}}}},
                           {"sockets", QJsonArray{QJsonObject{{"name", "drive"}, {"direction", "in"}, {"kind", "data"}}}}};
    const QJsonObject node{{"id", "O"}, {"name", "Objective"}, {"type", "rtt.section"}, {"params", QJsonObject{{"location", "/root/children/3"}}}};
    QStringList problems;
    const auto d = parse_drawing(schematic_drawing(node, type, QStringLiteral("no plugin draws it")), &problems);
    QVERIFY(d.has_value());
    QVERIFY(problems.isEmpty());
    QVERIFY(!d->axes);
    QCOMPARE(d->title, QStringLiteral("Objective"));
    QStringList texts;
    int arrows = 0;
    for (const auto& item : d->items) {
      if (item.kind == Drawing::Kind::Text) texts << item.text;
      if (item.kind == Drawing::Kind::Arrow) ++arrows;
    }
    QVERIFY(texts.contains(QStringLiteral("front")) && texts.contains(QStringLiteral("back")) && texts.contains(QStringLiteral("drive")));
    QCOMPARE(arrows, 5);  // in and out at two ports, the data input
    QVERIFY(d->notes.join(QLatin1Char(' ')).contains(QStringLiteral("location = /root/children/3")));
    QVERIFY(d->notes.join(QLatin1Char(' ')).contains(QStringLiteral("no plugin draws it")));
    // a socket graph block without ports: light sockets left (in) and right (out)
    const QJsonObject old{{"id", "d"}, {"type", "x"}, {"sockets", QJsonArray{QJsonObject{{"name", "in"}, {"direction", "in"}, {"kind", "light"}}}}};
    QVERIFY(parse_drawing(schematic_drawing(old, {})).has_value());
  }

  void drawsInLightAndDarkPalettes() {
    DrawingView view;
    view.resize(500, 360);
    view.setDrawing(*parse_drawing(lens_drawing()), QStringLiteral("a warning"));
    QCOMPARE(view.error(), QStringLiteral("a warning"));
    const QImage light = view.render(view.size());
    QVERIFY(drawn_pixels(light) > 2000);
    QPalette dark;
    dark.setColor(QPalette::Base, QColor(30, 30, 30));
    dark.setColor(QPalette::Window, QColor(30, 30, 30));
    dark.setColor(QPalette::WindowText, QColor(230, 230, 230));
    view.setPalette(dark);
    const QImage night = view.render(view.size());
    QCOMPARE(QColor(night.pixel(0, 0)), QColor(30, 30, 30));
    QVERIFY(drawn_pixels(night) > 2000);
    // a narrow view puts the legend below; still drawn
    QVERIFY(drawn_pixels(view.render(QSize(260, 300))) > 800);
    // a hi-dpi image has twice the pixels
    QCOMPARE(view.render(QSize(100, 80), 2.0).size(), QSize(200, 160));
    view.setBusy(QStringLiteral("computing"));
    QVERIFY(view.busy());
    // a drawing with one point only (a box without size) does not divide by zero
    const auto dot = parse_drawing(QJsonObject{{"items", QJsonArray{QJsonObject{{"type", "text"}, {"at", pt(1, 1)}, {"text", "x"}}}}});
    view.setDrawing(*dot);
    QVERIFY(!view.render(QSize(200, 200)).isNull());
  }

  void plugins_drawingsParseAndRender() {
    // the drawings of the plugins' producers (tests/python/test_block_previews.py --write): a
    // singlet and a doublet of the Raytracer, a grating of the FourierGrating plugin
    const QString out = qEnvironmentVariable("NFCAD_DRAWING_PNG_DIR");  // to look at them
    for (const QString& name : {QStringLiteral("lens"), QStringLiteral("doublet"), QStringLiteral("fg_grating")}) {
      QFile f(QStringLiteral(NFCAD_TEST_DATA "/drawings/%1.json").arg(name));
      QVERIFY2(f.open(QIODevice::ReadOnly), qPrintable(name));
      QStringList problems;
      const auto d = parse_drawing(QJsonDocument::fromJson(f.readAll()).object(), &problems);
      QVERIFY2(d.has_value(), qPrintable(problems.join(QStringLiteral("; "))));
      QVERIFY2(problems.isEmpty(), qPrintable(problems.join(QStringLiteral("; "))));
      QVERIFY(!d->materials.empty());
      DrawingView view;
      view.setDrawing(*d);
      const QImage image = view.render(QSize(640, 420), 2.0);
      QVERIFY(drawn_pixels(image) > 20000);
      if (!out.isEmpty()) {
        QVERIFY(image.save(QDir(out).filePath(name + QStringLiteral(".png"))));
        QPalette dark;
        dark.setColor(QPalette::Base, QColor(32, 33, 36));
        dark.setColor(QPalette::Window, QColor(32, 33, 36));
        dark.setColor(QPalette::WindowText, QColor(225, 225, 225));
        view.setPalette(dark);
        QVERIFY(view.render(QSize(640, 420), 2.0).save(QDir(out).filePath(name + QStringLiteral("_dark.png"))));
      }
    }
  }

  void dialogAsksThePluginsWithTheDialogsValues() {
    const QString radius = QStringLiteral("/rtt/~1root~1children~11/surfaces/0/shape/base/radius");
    const QJsonObject lens{{"type", "lens"},
                           {"name", "L1"},
                           {"surfaces", QJsonArray{QJsonObject{{"id", "S1"}, {"shape", QJsonObject{{"base", QJsonObject{{"type", "conic"}, {"radius", 30.0}}}}}}}}};
    const QJsonObject node{{"id", "L"},
                           {"type", "rtt.section"},
                           {"params", QJsonObject{{"rtt", QJsonObject{{"/root/children/1", lens}}}}},
                           {"fields", QJsonArray{QJsonObject{{"name", radius}, {"type", "number"}, {"label", "S1 radius"}, {"group", "L1"}, {"unit", "mm"}}}}};
    const QJsonObject model{{"format", "rtt-fusion-graph"}, {"version", 2}, {"nodes", QJsonArray{node}}, {"connections", QJsonArray{}}, {"links", QJsonArray{}}};
    const QJsonObject types{{"type", "rtt.section"}, {"provider", "raytracer"}, {"params", QJsonArray{}}};
    NodeEditor e;
    e.setWorkflow(QJsonObject{{"model", model}, {"types", QJsonArray{types}}});
    QCOMPARE(e.previewRequest(QStringLiteral("L"), {{radius, 42.0}})["node"].toObject()["params"].toObject()["rtt"]
                 .toObject()["/root/children/1"].toObject()["surfaces"].toArray()[0].toObject()["shape"]
                 .toObject()["base"].toObject()["radius"].toDouble(),
             42.0);
    QList<QJsonObject> requests;
    QString asked_provider;
    NodeEditor::PreviewDone pending;
    e.block_preview = [&](const QString& type, const QString& provider, const QJsonObject& request, QObject*,
                          NodeEditor::PreviewDone done) {
      QCOMPARE(type, QStringLiteral("rtt.section"));
      asked_provider = provider;
      requests << request;
      pending = std::move(done);
    };
    with_dialog(&e, [&](QDialog* d) {
      auto* tabs = d->findChild<QTabWidget*>();
      QVERIFY(tabs != nullptr);
      QCOMPARE(tabs->tabText(0), QStringLiteral("Overview"));  // first: what the block is
      QCOMPARE(tabs->count(), 2);
      auto* view = d->findChild<DrawingView*>();
      QVERIFY(view != nullptr);
      QCOMPARE(requests.size(), 1);  // drawn when the dialog opens on the overview
      QVERIFY(view->busy());
      QCOMPARE(asked_provider, QStringLiteral("raytracer"));
      QCOMPARE(requests[0]["model"].toObject()["nodes"].toArray().size(), 1);
      // the plugin answers: shown
      pending(QJsonObject{{"ok", true}, {"drawing", lens_drawing()}});
      QVERIFY(!view->busy());
      QCOMPARE(view->drawing()->title, QStringLiteral("L1"));
      // a changed value, then Update: the request has the dialog's value (not yet applied)
      auto* line = d->findChild<QLineEdit*>(radius);
      line->setText(QStringLiteral("55"));
      for (QPushButton* b : d->findChildren<QPushButton*>()) {
        if (b->text() == QStringLiteral("Update")) b->click();
      }
      QCOMPARE(requests.size(), 2);
      QCOMPARE(requests[1]["node"].toObject()["params"].toObject()["rtt"].toObject()["/root/children/1"].toObject()["surfaces"]
                   .toArray()[0].toObject()["shape"].toObject()["base"].toObject()["radius"].toDouble(),
               55.0);
      // an error: the block's schematic with the error
      pending(QJsonObject{{"ok", false}, {"error", "raytatouille is missing"}});
      QCOMPARE(view->error(), QStringLiteral("raytatouille is missing"));
      QVERIFY(!view->drawing()->axes);  // the schematic
      // an invalid drawing: also the schematic, with why
      refresh_and_answer(d, pending, QJsonObject{{"ok", true}, {"drawing", QJsonObject{{"items", 3}}}});
      QVERIFY(view->error().contains(QStringLiteral("not valid")));
      // no plugin draws the type: the schematic, no error
      refresh_and_answer(d, pending, QJsonObject{{"ok", false}, {"unsupported", true}, {"error", "nobody"}});
      QVERIFY(view->error().isEmpty());
      QVERIFY(view->drawing()->notes.join(QLatin1Char(' ')).contains(QStringLiteral("nobody")));
      // a late answer to an older request is dropped
      NodeEditor::PreviewDone old = pending;
      refresh_and_answer(d, pending, {});
      old(QJsonObject{{"ok", true}, {"drawing", lens_drawing()}});
      QVERIFY(view->busy());
    });
    e.editParams(QStringLiteral("L"));
    QCOMPARE(requests.size(), 5);
    // closed on a parameter tab: the next dialog opens there and draws only when asked
    with_dialog(&e, [&](QDialog* d) { d->findChild<QTabWidget*>()->setCurrentIndex(1); });
    e.editParams(QStringLiteral("L"));
    const auto before = requests.size();
    with_dialog(&e, [&](QDialog* d) {
      auto* tabs = d->findChild<QTabWidget*>();
      QCOMPARE(tabs->currentIndex(), 1);
      QCOMPARE(requests.size(), before);
      tabs->setCurrentIndex(0);  // shown: drawn now
      QCOMPARE(requests.size(), before + 1);
    });
    e.editParams(QStringLiteral("L"));
    // without plugins (no block_preview): the schematic at once
    e.block_preview = nullptr;
    with_dialog(&e, [](QDialog* d) {
      auto* view = d->findChild<DrawingView*>();
      QVERIFY(view->drawing().has_value() && !view->busy());
    });
    e.editParams(QStringLiteral("L"));
  }

 private:
  static void refresh_and_answer(QDialog* d, NodeEditor::PreviewDone& pending, const QJsonObject& answer) {
    for (QPushButton* b : d->findChildren<QPushButton*>()) {
      if (b->text() == QStringLiteral("Update")) b->click();
    }
    if (!answer.isEmpty()) pending(answer);
  }
};

QTEST_MAIN(TestBlockDrawing)
#include "test_block_drawing.moc"
