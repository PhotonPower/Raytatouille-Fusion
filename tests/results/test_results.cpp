#include <QDir>
#include <QFileInfo>
#include <QFile>
#include <QSignalSpy>
#include <QJsonArray>
#include <QTemporaryDir>
#include <numbers>
#include <QTest>
#include <cmath>
#include <nurbforge/nurbforge.hpp>

#include "app/demo_results.hpp"
#include "document/document.hpp"
#include "render/scene.hpp"
#include "results/colormap.hpp"
#include "results/result_edit.hpp"
#include "results/result_export.hpp"
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

  void keyedLinesReplaceTheEarlierDrawing() {
    // a drawing with a key (the Path Tracer's camera) replaces the one before: its line items go,
    // a set left empty with it too; other items of that set and unkeyed lines stay
    results::ResultStore store;
    results::LineSet l;
    l.points = {0, 0, 0, 1, 0, 0};
    const auto first = store.createSet(QStringLiteral("Camera"));
    store.addLines(first, QStringLiteral("pyramid"), l, QStringLiteral("cam"));
    const auto trace = store.createSet(QStringLiteral("Trace"));
    store.addLines(trace, QStringLiteral("rays"), l);
    store.addLines(trace, QStringLiteral("marker"), l, QStringLiteral("cam"));
    const auto second = store.createSet(QStringLiteral("Camera"));
    const auto pyramid = store.addLines(second, QStringLiteral("pyramid"), l, QStringLiteral("cam"));
    store.addLines(second, QStringLiteral("frame"), l, QStringLiteral("cam"));  // same set: both stay
    QVERIFY(store.set(first) == nullptr);
    QCOMPARE(store.set(trace)->items.size(), std::size_t{1});
    QCOMPARE(store.set(trace)->items.front().name, QStringLiteral("rays"));
    QCOMPARE(store.set(second)->items.size(), std::size_t{2});
    QCOMPARE(store.item(pyramid)->key, QStringLiteral("cam"));
    QCOMPARE(store.addLines(9999, QStringLiteral("nowhere"), l, QStringLiteral("cam")), results::ResultId{0});
    QCOMPARE(store.set(second)->items.size(), std::size_t{2});  // an unknown set removes nothing
  }

  void savesResultsAsCsvAndPng() {
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    results::ResultStore store;
    const auto set = store.createSet(QStringLiteral("Run: 1/2"));
    results::Image im;
    im.width = 3;
    im.height = 2;
    im.values = {1.0F, 2.5F, NAN, 4.0F, 5.0F, 6.0F};
    im.unit = QStringLiteral("W/mm²");
    im.colormap = results::Colormap::Grey;
    const auto image = store.addImage(set, QStringLiteral("camera"), im);
    results::Curve c{{0.0, 0.5}, {1.0, 1.0 / 3.0}, QStringLiteral("t / s"), QStringLiteral("I, a.u.")};
    const auto curve = store.addCurve(set, QStringLiteral("sweep"), c);
    store.addTable(set, QStringLiteral("orders"),
                   results::Table{{"m", "note"}, {QStringList{"-1", "a, \"b\""}, QStringList{"0", "c"}}});
    store.addBars(set, QStringLiteral("orders"), results::Bars{{"-1", "0"}, {0.25, 0.5}, "η"});
    results::LineSet l;
    l.points = {0, 0, 0, 1, 0, 0, 0, 1, 0, NAN, NAN, NAN};
    l.starts = {0, 2, 4};
    l.values = {1, 2, 3, 4};
    const auto lines = store.addLines(set, QStringLiteral("rays"), l);

    // the image values: comments, then one line per row from y0 up (numpy.loadtxt reads it)
    const QString image_csv = results::to_csv(*store.item(image));
    QVERIFY(image_csv.startsWith(QStringLiteral("# camera\n")));
    QVERIFY(image_csv.contains(QStringLiteral("# unit: W/mm²\n")));
    QVERIFY(image_csv.endsWith(QStringLiteral("1,2.5,nan\n4,5,6\n")));
    QCOMPARE(results::to_csv(*store.item(curve)), QStringLiteral("t / s,\"I, a.u.\"\n0,1\n0.5,0.333333333\n"));
    QCOMPARE(results::to_csv(store.set(set)->items[2]), QStringLiteral("m,note\n-1,\"a, \"\"b\"\"\"\n0,c\n"));
    QCOMPARE(results::to_csv(store.set(set)->items[3]), QStringLiteral("label,η\n-1,0.25\n0,0.5\n"));
    QCOMPARE(results::to_csv(*store.item(lines)),
             QStringLiteral("polyline,x,y,z,value\n0,0,0,0,1\n0,1,0,0,2\n1,0,1,0,3\n1,nan,nan,nan,4\n"));

    // PNG: the pixels as the Image window shows them, y0 at the bottom
    const QString png = dir.filePath(QStringLiteral("camera.png"));
    QVERIFY(results::save_item(*store.item(image), png));
    const QImage back(png);
    QCOMPARE(back.size(), QSize(3, 2));
    QCOMPARE(back.pixelColor(0, 1), QColor(0, 0, 0));        // 1: the minimum, bottom left
    QCOMPARE(back.pixelColor(2, 0), QColor(255, 255, 255));  // 6: the maximum, top right
    QString error;
    QVERIFY(!results::save_item(*store.item(curve), dir.filePath(QStringLiteral("x.png")), &error));
    QVERIFY(error.contains(QStringLiteral("csv")));

    // a whole run: one file per item (images also as PNG), names made safe, duplicates numbered
    const QStringList files = results::save_set(*store.set(set), dir.filePath(QStringLiteral("run")), &error);
    QCOMPARE(files.size(), 6);
    QStringList names;
    for (const QString& f : files) names << QFileInfo(f).fileName();
    QCOMPARE(names, (QStringList{"camera.png", "camera.csv", "sweep.csv", "orders.csv", "orders (2).csv", "rays.csv"}));
    QFile f(files[2]);
    QVERIFY(f.open(QIODevice::ReadOnly));
    QCOMPARE(QString::fromUtf8(f.readAll()), results::to_csv(*store.item(curve)));
    QCOMPARE(results::file_name_for(QStringLiteral("Run: 1/2."), QStringLiteral("csv")), QStringLiteral("Run_ 1_2.csv"));
  }

  void boundParametersFollowTheCamera() {
    // a camera at (0, -100, 0) looking at the origin along +Y, up +Z (as the Path Tracer draws it)
    const QJsonObject binding{
        {"points", QJsonObject{{"pos", QJsonArray{0, -100, 0}}, {"target", QJsonArray{0, 0, 0}}}},
        {"view", QJsonObject{{"forward", QJsonArray{0, 1, 0}},
                             {"up", QJsonArray{0, 0, 1}},
                             {"up_param", "up"},
                             {"roll_param", "roll"},
                             {"choices", QJsonObject{{"+Z", QJsonArray{0, 0, 1}},
                                                     {"-Z", QJsonArray{0, 0, -1}},
                                                     {"+Y", QJsonArray{0, 1, 0}},
                                                     {"-Y", QJsonArray{0, -1, 0}},
                                                     {"+X", QJsonArray{1, 0, 0}},
                                                     {"-X", QJsonArray{-1, 0, 0}}}},
                             {"order", QJsonArray{"+Z", "-Z", "+Y", "-Y", "+X", "-X"}}}}};
    auto point = [](const QJsonObject& o, const char* name) {
      const QJsonArray a = o[QLatin1String(name)].toArray();
      return nf::Vec3{a[0].toDouble(), a[1].toDouble(), a[2].toDouble()};
    };
    constexpr double kQuarter = std::numbers::pi / 2;
    // moved: the points go along, the orientation stays
    QString note;
    QJsonObject v = results::bound_parameters(binding, nf::Transform::translation({10, 0, 5}), &note);
    QVERIFY(nf::distance(point(v, "pos"), {10, -100, 5}) < 1e-12);
    QVERIFY(nf::distance(point(v, "target"), {10, 0, 5}) < 1e-12);
    QCOMPARE(v["up"].toString(), QStringLiteral("+Z"));
    QCOMPARE(v["roll"].toDouble(), 0.0);
    QCOMPARE(note, QStringLiteral("up +Z"));
    // turned about Z (the construction plane of the top view): up stays +Z without roll
    v = results::bound_parameters(binding, nf::Transform::rotation({0, 0, 0}, {0, 0, 1}, kQuarter));
    QVERIFY(nf::distance(point(v, "pos"), {100, 0, 0}) < 1e-9);
    QCOMPARE(v["up"].toString(), QStringLiteral("+Z"));
    QCOMPARE(v["roll"].toDouble(), 0.0);
    // turned about the view direction by 30°: +Z with a roll of +30° (right-handed about the view)
    v = results::bound_parameters(binding, nf::Transform::rotation({0, 0, 0}, {0, 1, 0}, std::numbers::pi / 6), &note);
    QCOMPARE(v["up"].toString(), QStringLiteral("+Z"));
    QVERIFY(std::abs(v["roll"].toDouble() - 30.0) < 1e-9);
    QCOMPARE(note, QStringLiteral("up +Z, roll 30.00°"));
    // tilted to look up along +Z: +Z is the view direction now, the up becomes -Y without roll
    v = results::bound_parameters(binding, nf::Transform::rotation({0, -100, 0}, {1, 0, 0}, kQuarter));
    QVERIFY(nf::distance(point(v, "target"), {0, -100, 100}) < 1e-9);
    QCOMPARE(v["up"].toString(), QStringLiteral("-Y"));
    QCOMPARE(v["roll"].toDouble(), 0.0);
    // a plugin without a roll parameter: the nearest choice, and the note says the turn is lost
    QJsonObject view = binding["view"].toObject();
    view.remove(QStringLiteral("roll_param"));
    QJsonObject no_roll = binding;
    no_roll["view"] = view;
    v = results::bound_parameters(no_roll, nf::Transform::rotation({0, 0, 0}, {0, 1, 0}, std::numbers::pi / 6), &note);
    QCOMPARE(v["up"].toString(), QStringLiteral("+Z"));
    QVERIFY(!v.contains(QStringLiteral("roll")));
    QVERIFY(note.contains(QStringLiteral("cannot be kept")));
    QVERIFY(results::bound_parameters({}, nf::Transform::translation({1, 0, 0})).isEmpty());
  }

  void drawingsMoveAndDeleteAsUndoSteps() {
    document::Document doc;
    results::ResultStore store;
    doc.setPluginParameters(QStringLiteral("cam"), QJsonObject{{"fov", 40}});
    results::LineSet l;
    l.points = {0, -100, 0, 0, 0, 0};
    const auto camera = store.createSet(QStringLiteral("Camera"), QStringLiteral("cam"));
    const auto pyramid = store.addLines(camera, QStringLiteral("pyramid"), l, QStringLiteral("cam:camera"));
    store.setBinding(pyramid, QJsonObject{{"points", QJsonObject{{"pos", QJsonArray{0, -100, 0}}}}});
    QSignalSpy shown(&doc, &document::Document::pluginParametersSet);

    // moved twice: the motions compose, the bound parameter follows, the others stay
    for (int k = 0; k < 2; ++k) {
      QString note;
      auto step = results::move_results(store, &doc, {camera}, nf::Transform::translation({5, 0, 0}),
                                        QStringLiteral("Move"), &note);
      QVERIFY(step);
      doc.undoStack()->push(step.release());
    }
    QVERIFY(nf::distance(results::placed_point(*store.item(pyramid), 0), {10, -100, 0}) < 1e-12);
    const QJsonArray pos = doc.pluginParameters(QStringLiteral("cam"))["pos"].toArray();
    QVERIFY(pos.size() == 3 && pos[0].toDouble() == 10.0 && pos[1].toDouble() == -100.0 && pos[2].toDouble() == 0.0);
    QCOMPARE(doc.pluginParameters(QStringLiteral("cam"))["fov"].toInt(), 40);
    QCOMPARE(shown.count(), 2);  // the plugin panel shows the values
    // where it is shown: saved and converted to curves there
    QVERIFY(results::to_csv(*store.item(pyramid)).contains(QStringLiteral("0,10,-100,0\n")));
    const auto curves = results::ResultStore::promote(*store.item(pyramid)->lines, 1, 10, store.item(pyramid)->placement);
    QVERIFY(nf::distance(std::get<nf::NurbsCurve>(*curves.front().geometry).evaluate(0.0), {10, -100, 0}) < 1e-12);
    doc.undoStack()->undo();
    doc.undoStack()->undo();
    QVERIFY(results::is_identity(store.item(pyramid)->placement));
    QCOMPARE(doc.pluginParameters(QStringLiteral("cam")), (QJsonObject{{"fov", 40}}));
    QVERIFY(!results::move_results(store, &doc, {12345}, nf::Transform(), QStringLiteral("Move")));

    // deleted: the drawing goes – a run with other results keeps them; undo puts all back in place
    const auto trace = store.createSet(QStringLiteral("Trace"));
    const auto rays = store.addLines(trace, QStringLiteral("rays"), l);
    results::Curve c;
    store.addCurve(trace, QStringLiteral("spot"), c);
    const auto last = store.createSet(QStringLiteral("Last"));
    auto del = results::delete_results(store, {trace, camera}, QStringLiteral("Delete"));
    QVERIFY(del);
    doc.undoStack()->push(del.release());
    QVERIFY(store.set(camera) == nullptr);
    QCOMPARE(store.set(trace)->items.size(), std::size_t{1});
    QCOMPARE(store.sets().size(), std::size_t{2});
    doc.undoStack()->undo();
    QCOMPARE(store.sets().size(), std::size_t{3});
    QCOMPARE(store.sets()[0].id, camera);
    QCOMPARE(store.sets()[1].id, trace);
    QCOMPARE(store.sets()[2].id, last);
    QVERIFY(store.item(rays) != nullptr && store.item(pyramid) != nullptr);
    QCOMPARE(store.item(pyramid)->binding["points"].toObject().size(), 1);
    QVERIFY(!results::delete_results(store, {last}, QStringLiteral("Delete")));  // no drawing
    // an item added after the restore gets a fresh id
    QVERIFY(store.addLines(last, QStringLiteral("more"), l) > rays);
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
