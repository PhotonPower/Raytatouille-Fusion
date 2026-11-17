#include <QSignalSpy>
#include <QTest>
#include <cmath>
#include <nurbforge/nurbforge.hpp>

#include "app/demo_results.hpp"
#include "document/document.hpp"
#include "render/scene.hpp"
#include "results/colormap.hpp"
#include "results/result_io.hpp"
#include "results/result_store.hpp"
#include "tessellation/tessellation_service.hpp"
#include "viewport/viewport.hpp"

using namespace nfcad;

class TestResults : public QObject {
  Q_OBJECT
 private slots:
  void colormaps() {
    using results::Colormap;
    const auto lo = results::colormap_rgba(Colormap::Viridis, 0.0);
    const auto hi = results::colormap_rgba(Colormap::Viridis, 1.0);
    QCOMPARE(int(lo[0]), 68);
    QCOMPARE(int(hi[1]), 231);
    QCOMPARE(results::colormap_rgba(Colormap::Grey, 0.5)[0], static_cast<unsigned char>(128));
    QCOMPARE(results::colormap_rgba(Colormap::Inferno, NAN)[3], static_cast<unsigned char>(0));
    QCOMPARE(results::colormap_rgba(Colormap::Grey, 7.0)[0], static_cast<unsigned char>(255));  // clamped
    QCOMPARE(results::colormap_from_name(QStringLiteral("Inferno")), Colormap::Inferno);
  }

  void fieldTextureAndRange() {
    results::FaceField f;
    f.width = 2;
    f.height = 1;
    f.values = {1.0F, 3.0F};
    f.colormap = results::Colormap::Grey;
    QCOMPARE(f.effectiveRange().min, 1.0);
    QCOMPARE(f.effectiveRange().max, 3.0);
    const auto t = f.texture();
    QCOMPARE(t.size(), std::size_t{8});
    QCOMPARE(int(t[0]), 0);
    QCOMPARE(int(t[4]), 255);
    f.range = results::Range{0.0, 6.0};
    QCOMPARE(int(f.texture()[4]), 128);
  }

  void keyedResultsAreKeptWithTheDocument() {
    // the newest result of each key with its fingerprint: saved, restored as "Saved results",
    // equal in every number; unkeyed results and broken entries are left out
    results::ResultStore store;
    const auto old_set = store.createSet(QStringLiteral("run 1"));
    results::Image old_im;
    old_im.width = old_im.height = 1;
    old_im.values.assign(1, 9.0F);  // (GCC 14: a one-element initializer list trips -Warray-bounds)
    store.addImage(old_set, QStringLiteral("old"), old_im, QStringLiteral("workflow:cam"));
    const auto set = store.createSet(QStringLiteral("run 2"));
    results::Image im;
    im.width = 3;
    im.height = 2;
    im.values = {1.0F, 2.5F, NAN, 4.0F, 5.0F, 6.0F};
    im.rgb = std::vector<unsigned char>(18, 7);
    im.x0 = -1.5;
    im.x1 = 1.5;
    im.y0 = -0.25;
    im.y1 = 0.75;
    im.x_label = QStringLiteral("x / mm");
    im.unit = QStringLiteral("W/mm²");
    im.range = results::Range{0.5, 5.5};
    im.colormap = results::Colormap::Grey;
    const auto image = store.addImage(set, QStringLiteral("camera"), im, QStringLiteral("workflow:cam"));
    store.setStamp(image, QStringLiteral("abc123"));
    results::Curve c;
    c.x = {0.0, 0.1, 0.2};
    c.y = {1.0, 1.0 / 3.0, -2e-300};
    c.y_label = QStringLiteral("I");
    store.setStamp(store.addCurve(set, QStringLiteral("sweep"), c, QStringLiteral("workflow:plot")),
                   QStringLiteral("def456"));
    results::Table t;
    t.columns = QStringList{QStringLiteral("m"), QStringLiteral("η")};
    t.rows = {QStringList{QStringLiteral("-1"), QStringLiteral("0.25")}};
    store.addTable(set, QStringLiteral("orders"), t, QStringLiteral("workflow:tab"));
    results::Bars b;
    b.labels = QStringList{QStringLiteral("a"), QStringLiteral("b")};
    b.values = {0.5, 0.25};
    store.addBars(set, QStringLiteral("bars"), b, QStringLiteral("workflow:tab"));
    results::Curve loose;
    loose.x.assign(1, 0.0);
    loose.y.assign(1, 1.0);
    store.addCurve(set, QStringLiteral("not kept"), loose);

    const QJsonArray saved = results::saved_results(store);
    QCOMPARE(saved.size(), 4);  // newest image, curve, table, bars – not the old image, not the loose curve
    QJsonArray with_junk = saved;
    with_junk.append(QJsonObject{{"key", "workflow:x"}, {"kind", "image"}, {"image", QJsonObject{{"width", 4}}}});
    with_junk.append(QJsonObject{{"kind", "curve"}});

    results::ResultStore back;
    QCOMPARE(results::restore_results(back, with_junk), 4);
    QCOMPARE(back.sets().size(), std::size_t{1});
    QCOMPARE(back.sets().front().name, QStringLiteral("Saved results"));
    const auto images = back.itemsWithKey(QStringLiteral("workflow:cam"), results::ResultItem::Kind::Image);
    QCOMPARE(images.size(), std::size_t{1});
    const results::Image& r = *images.front()->image;
    QCOMPARE(images.front()->stamp, QStringLiteral("abc123"));
    QCOMPARE(images.front()->name, QStringLiteral("camera"));
    QCOMPARE(r.width, 3);
    QCOMPARE(r.values[1], 2.5F);
    QVERIFY(std::isnan(r.values[2]));
    QCOMPARE(r.rgb, im.rgb);
    QCOMPARE(r.x0, -1.5);
    QCOMPARE(r.y1, 0.75);
    QCOMPARE(r.x_label, im.x_label);
    QCOMPARE(r.unit, im.unit);
    QCOMPARE(r.colormap, results::Colormap::Grey);
    QVERIFY(r.range && r.range->min == 0.5 && r.range->max == 5.5);
    const auto curves = back.itemsWithKey(QStringLiteral("workflow:plot"), results::ResultItem::Kind::Curve);
    QCOMPARE(curves.size(), std::size_t{1});
    QCOMPARE(curves.front()->curve->y, c.y);  // exactly, also 1/3 and a subnormal
    QCOMPARE(back.itemsWithKey(QStringLiteral("workflow:tab"), results::ResultItem::Kind::Table).front()->table->rows,
             t.rows);
    QCOMPARE(back.itemsWithKey(QStringLiteral("workflow:tab"), results::ResultItem::Kind::Bars).front()->bars->values,
             b.values);
    const QJsonObject stamps = results::result_stamps(back);
    QCOMPARE(stamps.value(QStringLiteral("workflow:cam")).toString(), QStringLiteral("abc123"));
    QCOMPARE(stamps.value(QStringLiteral("workflow:plot")).toString(), QStringLiteral("def456"));
    QVERIFY(!stamps.contains(QStringLiteral("workflow:tab")));  // no fingerprint given
    QCOMPARE(results::restore_results(back, QJsonArray{}), 0);
  }

  void storeVisibilityAndCurves() {
    results::ResultStore store;
    QSignalSpy changed(&store, &results::ResultStore::changed);
    const auto set = store.createSet(QStringLiteral("run 1"));
    results::LineSet l;
    l.points = {0, 0, 0, 1, 0, 0, 2, 1, 0};
    const auto lines = store.addLines(set, QStringLiteral("rays"), l);
    QCOMPARE(store.item(lines)->lines->polylineCount(), std::size_t{1});  // starts filled in
    const auto curve = store.addCurve(set, QStringLiteral("merit"), {});
    QSignalSpy updated(&store, &results::ResultStore::curveUpdated);
    store.appendToCurve(curve, 1.0, 0.5);
    store.appendToCurve(curve, 2.0, 0.25);
    QCOMPARE(updated.count(), 2);
    QCOMPARE(store.item(curve)->curve->y.size(), std::size_t{2});
    QCOMPARE(store.visibleItems(results::ResultItem::Kind::Lines).size(), std::size_t{1});
    store.setSetVisible(set, false);
    QVERIFY(store.visibleItems(results::ResultItem::Kind::Lines).empty());
    store.removeSet(set);
    QVERIFY(store.sets().empty());
    QVERIFY(changed.count() >= 5);
  }

  void promoteRaysToCurves() {
    results::LineSet l;
    // ray 0: 3 points; ray 1: lost after the second point (NaN); ray 2: 2 points
    l.points = {0, 0, 0, 1, 0, 0, 1, 1, 0,  0, 0, 1, 1, 0, 1, NAN, NAN, NAN,  0, 0, 2, 0, 1, 2};
    l.starts = {0, 3, 6, 8};
    auto all = results::ResultStore::promote(l, 1, 100);
    QCOMPARE(all.size(), std::size_t{3});
    const auto& c1 = std::get<nf::NurbsCurve>(*all[1].geometry);
    QCOMPARE(c1.num_control_points(), std::size_t{2});  // stopped at the lost point
    QCOMPARE(results::ResultStore::promote(l, 2, 100).size(), std::size_t{2});
    QCOMPARE(results::ResultStore::promote(l, 1, 1).size(), std::size_t{1});
  }

  void renderDemoOffscreen() {
    // renders a view with rays and a field into an image (no window); saved for review with
    // NFCAD_SNAPSHOT_DIR. Skipped where no GPU backend is available (CI).
    document::Document doc;
    tessellation::TessellationService service;
    render::Scene scene(&doc, &service);
    results::ResultStore store;
    QSignalSpy idle(&service, &tessellation::TessellationService::idle);
    const auto ids = doc.addEntities(
        {document::make_entity(nf::make_rectangle({-10, -10, 0}, {20, 0, 0}, {0, 20, 0}))},
        QStringLiteral("add"));
    QVERIFY(idle.wait(10000));
    QVERIFY(app::make_demo_results(store, scene, ids[0]).isEmpty());
    QCOMPARE(store.sets().front().items.size(), std::size_t{3});

    viewport::Viewport v(viewport::ViewKind::Perspective);
    v.resize(640, 480);
    v.setScene(&scene);
    v.setResults(&store);
    v.zoomExtents();
    const QImage img = v.grabFramebuffer();
    if (img.isNull()) QSKIP("no RHI backend for offscreen rendering");
    // the field (inferno: dark red / yellow) must be visible somewhere
    int warm = 0;
    for (int y = 0; y < img.height(); y += 4) {
      for (int x = 0; x < img.width(); x += 4) {
        const QColor c = img.pixelColor(x, y);
        warm += (c.red() > 150 && c.blue() < 90) ? 1 : 0;
      }
    }
    QVERIFY2(warm > 20, qPrintable(QString::number(warm)));
    if (const QByteArray dir = qgetenv("NFCAD_SNAPSHOT_DIR"); !dir.isEmpty()) {
      img.save(QString::fromLocal8Bit(dir) + QStringLiteral("/results_demo.png"));
    }
  }
};

QTEST_MAIN(TestResults)
#include "test_results.moc"
