#include <QTest>
#include <cmath>
#include <numbers>
#include <nurbforge/nurbforge.hpp>

#include "commands/command.hpp"
#include "commands/input_parser.hpp"

using nfcad::commands::Command;
using nfcad::commands::create_command;
using nfcad::commands::parse_input;
using nfcad::commands::ParsedInput;
using nfcad::commands::PlaneFrame;
using nfcad::commands::Point3;
using R = Command::Result;

namespace {

const PlaneFrame kTop{};                                         // XY
const PlaneFrame kFront{{0, 0, 0}, {1, 0, 0}, {0, 0, 1}, {0, -1, 0}};  // XZ

const nf::NurbsCurve& curve_of(const std::vector<nfcad::document::Entity>& e) {
  return std::get<nf::NurbsCurve>(*e.front().geometry);
}

bool near(const Point3& a, const Point3& b, double tol = 1e-12) {
  return std::abs(a.x - b.x) < tol && std::abs(a.y - b.y) < tol && std::abs(a.z - b.z) < tol;
}

}  // namespace

class TestCommands : public QObject {
  Q_OBJECT
 private slots:
  // ---- input parser
  void parseAbsoluteAndPlane() {
    auto r = parse_input(QStringLiteral(" 1.5, -2, 3 "), kFront, std::nullopt);
    QCOMPARE(r.kind, ParsedInput::Kind::Point);
    QVERIFY(near(r.point, {1.5, -2, 3}));  // three values: world coordinates
    r = parse_input(QStringLiteral("4,5"), kFront, std::nullopt);
    QVERIFY(near(r.point, {4, 0, 5}));  // two values: in the front plane (x, z)
  }

  void parseRelativeAndPolar() {
    const Point3 base{10, 10, 0};
    auto r = parse_input(QStringLiteral("@1,2,3"), kTop, base);
    QVERIFY(near(r.point, {11, 12, 3}));
    r = parse_input(QStringLiteral("@3,4"), kTop, base);
    QVERIFY(near(r.point, {13, 14, 0}));
    r = parse_input(QStringLiteral("@10<90"), kTop, base);
    QVERIFY(near(r.point, {10, 20, 0}, 1e-12));
    r = parse_input(QStringLiteral("2<180"), kTop, base);  // absolute polar from the origin
    QVERIFY(near(r.point, {-2, 0, 0}, 1e-12));
  }

  void parseNumbersNamesErrors() {
    auto r = parse_input(QStringLiteral("12.5"), kTop, std::nullopt);
    QCOMPARE(r.kind, ParsedInput::Kind::Number);
    QCOMPARE(r.number, 12.5);
    r = parse_input(QStringLiteral("Circle"), kTop, std::nullopt);
    QCOMPARE(r.kind, ParsedInput::Kind::Name);
    QCOMPARE(r.name, QStringLiteral("circle"));
    QCOMPARE(parse_input(QStringLiteral("@1,2"), kTop, std::nullopt).kind, ParsedInput::Kind::Invalid);
    QCOMPARE(parse_input(QStringLiteral("1,x"), kTop, std::nullopt).kind, ParsedInput::Kind::Invalid);
    QCOMPARE(parse_input(QStringLiteral("1,2,3,4"), kTop, std::nullopt).kind, ParsedInput::Kind::Invalid);
    QCOMPARE(parse_input(QStringLiteral("  "), kTop, std::nullopt).kind, ParsedInput::Kind::Empty);
  }

  // ---- commands
  void factory() {
    QVERIFY(create_command(QStringLiteral("L")));
    QCOMPARE(create_command(QStringLiteral("pl"))->id(), QStringLiteral("polyline"));
    QVERIFY(!create_command(QStringLiteral("nonsense")));
    QCOMPARE(nfcad::commands::command_ids().size(), 87);
    for (const QString& id : nfcad::commands::command_ids()) {
      QVERIFY2(create_command(id), qPrintable(id));
      QCOMPARE(create_command(id)->id(), id);
    }
  }

  void line() {
    auto c = create_command(QStringLiteral("line"));
    QCOMPARE(c->point({0, 0, 0}, kTop), R::Continue);
    QVERIFY(c->basePoint());
    QCOMPARE(c->preview({1, 1, 0}, kTop).size(), std::size_t{1});
    QCOMPARE(c->point({0, 0, 0}, kTop), R::Rejected);  // zero length
    QCOMPARE(c->point({3, 4, 0}, kTop), R::Done);
    const auto e = c->takeEntities();
    QCOMPARE(e.size(), std::size_t{1});
    QVERIFY(nf::distance(curve_of(e).evaluate(curve_of(e).domain_end()), {3, 4, 0}) < 1e-15);
  }

  void polylineCloseAndFinish() {
    auto c = create_command(QStringLiteral("polyline"));
    QCOMPARE(c->finish(), R::Cancelled);
    c = create_command(QStringLiteral("polyline"));
    c->point({0, 0, 0}, kTop);
    c->point({4, 0, 0}, kTop);
    c->point({4, 3, 0}, kTop);
    QCOMPARE(c->point({0, 0, 0}, kTop), R::Done);  // back to the start: closed
    const auto closed = c->takeEntities();
    const auto& pl = curve_of(closed);
    QCOMPARE(pl.num_control_points(), std::size_t{4});
    c = create_command(QStringLiteral("polyline"));
    c->point({0, 0, 0}, kTop);
    c->point({1, 0, 0}, kTop);
    QCOMPARE(c->finish(), R::Done);
  }

  void rectangleInFrontPlane() {
    auto c = create_command(QStringLiteral("rectangle"));
    c->point({1, 0, 1}, kFront);
    QCOMPARE(c->point({5, 7, 3}, kFront), R::Done);  // y offset ignored: rectangle in the plane
    const auto rect = c->takeEntities();
    const auto& r = curve_of(rect);
    for (const auto& p : r.control_points()) QCOMPARE(p.y, 0.0);
    QVERIFY(nf::distance(r.control_points()[2], {5, 0, 3}) < 1e-12);
  }

  void circleByPointAndNumber() {
    auto c = create_command(QStringLiteral("circle"));
    QCOMPARE(c->number(3.0), R::Rejected);  // no centre yet
    c->point({1, 1, 0}, kTop);
    QCOMPARE(c->number(2.5), R::Done);
    const auto made = c->takeEntities();
    const auto& circle = curve_of(made);
    QVERIFY(std::abs(nf::distance(circle.evaluate(0.3), {1, 1, 0}) - 2.5) < 1e-12);
    c = create_command(QStringLiteral("circle"));
    c->point({0, 0, 0}, kTop);
    QCOMPARE(c->point({3, 4, 9}, kTop), R::Done);  // radius measured in the plane: 5
    QVERIFY(std::abs(nf::norm(curve_of(c->takeEntities()).evaluate(0.7)) - 5.0) < 1e-12);
  }

  void circle3pRejectsCollinear() {
    auto c = create_command(QStringLiteral("c3"));
    c->point({0, 0, 0}, kTop);
    c->point({1, 0, 0}, kTop);
    QCOMPARE(c->point({2, 0, 0}, kTop), R::Rejected);
    QCOMPARE(c->point({1, 1, 0}, kTop), R::Done);
  }

  void arcThroughPoint() {
    auto c = create_command(QStringLiteral("arc"));
    c->point({1, 0, 0}, kTop);   // start
    c->point({-1, 0, 0}, kTop);  // end
    QCOMPARE(c->point({0, 1, 0}, kTop), R::Done);  // through: upper half circle
    const auto made = c->takeEntities();
    const auto& arc = curve_of(made);
    QVERIFY(nf::distance(arc.evaluate(arc.domain_start()), {1, 0, 0}) < 1e-12);
    QVERIFY(nf::distance(arc.evaluate(arc.domain_end()), {-1, 0, 0}) < 1e-12);
    const auto mid = arc.evaluate(0.5 * (arc.domain_start() + arc.domain_end()));
    QVERIFY(mid.y > 0.99);
  }

  void polygonSidesAndRadius() {
    auto c = create_command(QStringLiteral("polygon"));
    QCOMPARE(c->number(2.5), R::Rejected);
    QCOMPARE(c->number(5), R::Continue);
    c->point({0, 0, 0}, kTop);
    QCOMPARE(c->point({2, 0, 0}, kTop), R::Done);
    const auto made = c->takeEntities();
    const auto& pg = curve_of(made);
    QCOMPARE(pg.num_control_points(), std::size_t{6});  // 5 corners + closing point
    QVERIFY(nf::distance(pg.control_points()[0], {2, 0, 0}) < 1e-12);
  }

  void helix() {
    auto c = create_command(QStringLiteral("helix"));
    QCOMPARE(c->number(3), R::Continue);  // turns
    c->point({0, 0, 0}, kTop);
    c->point({0, 0, 6}, kTop);
    QVERIFY(!c->preview({2, 0, 0}, kTop).empty());
    QCOMPARE(c->number(2.0), R::Done);  // radius
    const auto made = c->takeEntities();
    const auto& h = curve_of(made);
    const auto end = h.evaluate(h.domain_end());
    QVERIFY(std::abs(end.z - 6.0) < 1e-6);
    QVERIFY(std::abs(std::hypot(end.x, end.y) - 2.0) < 1e-6);
  }

  // ---- curves (control points, conic sections, spiral, sketch, through points)
  void controlPointCurve() {
    auto c = create_command(QStringLiteral("crv"));
    QCOMPARE(c->id(), QStringLiteral("curve"));
    for (const Point3& p : {Point3{0, 0, 0}, Point3{1, 1, 0}, Point3{2, 0, 0}, Point3{3, 1, 0}}) {
      QCOMPARE(c->point(p, kTop), R::Continue);
    }
    QCOMPARE(c->preview({4, 0, 0}, kTop).size(), std::size_t{2});  // curve and control polygon
    QCOMPARE(c->finish(), R::Done);
    const auto made_crv = c->takeEntities();
    const auto& crv = curve_of(made_crv);
    QCOMPARE(crv.degree(), std::size_t{3});
    QVERIFY(nf::distance(crv.control_points()[1], {1, 1, 0}) < 1e-12);  // control points, not passed
    QVERIFY(nf::distance(crv.evaluate(crv.domain_end()), {3, 1, 0}) < 1e-12);
    // clicking the first point again closes it
    c = create_command(QStringLiteral("curve"));
    for (const Point3& p : {Point3{0, 0, 0}, Point3{1, 0, 0}, Point3{1, 1, 0}}) c->point(p, kTop);
    QCOMPARE(c->point({0, 0, 0}, kTop), R::Done);
    const auto made_closed = c->takeEntities();
    const auto& closed = curve_of(made_closed);
    QVERIFY(nf::distance(closed.evaluate(closed.domain_start()), closed.evaluate(closed.domain_end())) < 1e-12);
    QCOMPARE(create_command(QStringLiteral("interpcrv"))->id(), QStringLiteral("spline"));
  }

  void ellipseIsExact() {
    auto c = create_command(QStringLiteral("el"));
    c->point({1, 1, 0}, kTop);
    c->point({4, 1, 0}, kTop);                // a = 3 along x
    QCOMPARE(c->number(2.0), R::Done);        // b = 2
    const auto made_e = c->takeEntities();
    const auto& e = curve_of(made_e);
    QVERIFY(e.is_rational());
    for (const auto& q : e.sample(50)) {
      QVERIFY(std::abs((q.x - 1) * (q.x - 1) / 9 + (q.y - 1) * (q.y - 1) / 4 - 1) < 1e-12);
      QVERIFY(std::abs(q.z) < 1e-15);
    }
    // the second axis from a point: its distance from the first axis
    c = create_command(QStringLiteral("ellipse"));
    c->point({0, 0, 0}, kFront);
    c->point({2, 0, 0}, kFront);
    QCOMPARE(c->point({5, 0, 1}, kFront), R::Done);  // b = 1, in the XZ plane
    const auto made_f = c->takeEntities();
    const auto& f = curve_of(made_f);
    for (const auto& q : f.sample(20)) QVERIFY(std::abs(q.x * q.x / 4 + q.z * q.z - 1) < 1e-12);
  }

  void spiralRadii() {
    auto c = create_command(QStringLiteral("spi"));
    QCOMPARE(c->number(2), R::Continue);  // turns
    c->point({0, 0, 0}, kTop);
    QCOMPARE(c->number(1.0), R::Continue);  // start radius
    QVERIFY(!c->preview({3, 0, 0}, kTop).empty());
    QCOMPARE(c->number(3.0), R::Done);      // end radius
    const auto made_s = c->takeEntities();
    const auto& s = curve_of(made_s);
    const auto a = s.evaluate(s.domain_start());
    const auto b = s.evaluate(s.domain_end());
    QVERIFY(std::abs(std::hypot(a.x, a.y) - 1.0) < 1e-6);
    QVERIFY(std::abs(std::hypot(b.x, b.y) - 3.0) < 1e-6);
    QVERIFY(std::abs(b.z) < 1e-9);
  }

  void parabolaThroughFocus() {
    auto c = create_command(QStringLiteral("para"));
    c->point({0, 0, 0}, kTop);
    c->point({0, 1, 0}, kTop);             // focus: f = 1, opening along +y
    QCOMPARE(c->number(2.0), R::Done);    // half width
    const auto made_p = c->takeEntities();
    const auto& p = curve_of(made_p);
    for (const auto& q : p.sample(40)) QVERIFY(std::abs(q.y - q.x * q.x / 4) < 1e-12);
    QVERIFY(nf::distance(p.evaluate(p.domain_end()), {2, 1, 0}) < 1e-12);
  }

  void hyperbolaThroughThePoint() {
    auto c = create_command(QStringLiteral("hyp"));
    c->point({0, 0, 0}, kTop);
    c->point({1, 0, 0}, kTop);                        // vertex: a = 1
    QCOMPARE(c->point({0.5, 1, 0}, kTop), R::Rejected);  // not beyond the vertex
    QCOMPARE(c->point({2, 1.5, 0}, kTop), R::Done);
    const auto made_h = c->takeEntities();
    const auto& h = curve_of(made_h);
    const double b2 = 1.5 * 1.5 / 3.0;
    for (const auto& q : h.sample(40)) QVERIFY(std::abs(q.x * q.x - q.y * q.y / b2 - 1) < 1e-12);
    const auto mid = h.evaluate(0.5 * (h.domain_start() + h.domain_end()));
    QVERIFY(nf::distance(mid, {1, 0, 0}) < 1e-12);  // the vertex
  }

  void conicByRho() {
    auto c = create_command(QStringLiteral("conic"));
    c->point({0, 0, 0}, kTop);
    c->point({2, 0, 0}, kTop);
    c->point({1, 1, 0}, kTop);  // apex
    QCOMPARE(c->number(1.5), R::Rejected);
    QCOMPARE(c->number(0.5), R::Done);  // a parabola: the shoulder halfway to the apex
    const auto made_k = c->takeEntities();
    const auto& k = curve_of(made_k);
    QVERIFY(nf::distance(k.evaluate(0.5 * (k.domain_start() + k.domain_end())), {1, 0.5, 0}) < 1e-12);
    // rho from a point: its position between the chord's midpoint and the apex
    c = create_command(QStringLiteral("conic"));
    c->point({0, 0, 0}, kTop);
    c->point({2, 0, 0}, kTop);
    c->point({1, 1, 0}, kTop);
    QCOMPARE(c->point({1, 0.7, 0}, kTop), R::Done);
    const auto made_h = c->takeEntities();
    const auto& h = curve_of(made_h);
    QVERIFY(std::abs(h.weights()[1] - 0.7 / 0.3) < 1e-12);  // a hyperbola
  }

  void sketchFollowsTheCursor() {
    auto c = create_command(QStringLiteral("sk"));
    c->point({1, 0, 0}, kTop);
    for (int i = 1; i < 60; ++i) {  // the cursor moves along a quarter circle
      const double t = 0.5 * std::numbers::pi * i / 60.0;
      (void)c->preview({std::cos(t), std::sin(t), 0}, kTop);
    }
    QCOMPARE(c->point({0, 1, 0}, kTop), R::Done);
    const auto made_s = c->takeEntities();
    const auto& s = curve_of(made_s);
    QVERIFY(nf::distance(s.evaluate(s.domain_start()), {1, 0, 0}) < 1e-12);
    QVERIFY(nf::distance(s.evaluate(s.domain_end()), {0, 1, 0}) < 1e-12);
    for (const auto& q : s.sample(30)) QVERIFY(std::abs(std::hypot(q.x, q.y) - 1.0) < 0.01);
    QVERIFY(s.num_control_points() < 30);  // a fit, not every cursor position
  }

  void curveThroughSelectedPoints() {
    auto c = create_command(QStringLiteral("crvpts"));
    std::vector<nfcad::document::Entity> sel;
    for (const nf::Vec3& p : {nf::Vec3{0, 0, 0}, nf::Vec3{1, 2, 0}, nf::Vec3{3, 2, 1}, nf::Vec3{4, 0, 0}}) {
      sel.push_back(nfcad::document::make_entity(p));
    }
    QVERIFY(c->usesSelection() && c->immediate());
    QVERIFY(c->begin(sel));
    QCOMPARE(c->finish(), R::Done);
    const auto made_crv = c->takeEntities();
    const auto& crv = curve_of(made_crv);
    QVERIFY(nf::closest_point(crv, {3, 2, 1}).distance < 1e-9);  // passes the points
    auto single = create_command(QStringLiteral("crvpts"));
    QVERIFY(!single->begin({sel[0]}));
  }

  // ---- curves from curves
  static std::vector<nfcad::document::Entity> lines(std::initializer_list<std::pair<nf::Vec3, nf::Vec3>> ends) {
    std::vector<nfcad::document::Entity> out;
    nfcad::document::EntityId id = 1;
    for (const auto& [a, b] : ends) {
      out.push_back(nfcad::document::make_entity(nf::make_line(a, b)));
      out.back().id = id++;
    }
    return out;
  }

  void blendClosestEndsAndClicks() {
    const auto sel = lines({{{0, 0, 0}, {1, 0, 0}}, {{2, 1, 0}, {3, 1, 0}}});
    auto c = create_command(QStringLiteral("blendcrv"));
    QVERIFY(c->begin(sel));
    QVERIFY(!c->preview({0, 0, 0}, kTop).empty());
    QCOMPARE(c->finish(), R::Done);  // Enter: the closest ends, G2
    const auto made_g2 = c->takeEntities();
    const auto& g2 = curve_of(made_g2);
    QCOMPARE(g2.degree(), std::size_t{5});
    QVERIFY(nf::distance(g2.evaluate(g2.domain_start()), {1, 0, 0}) < 1e-12);
    QVERIFY(nf::distance(g2.evaluate(g2.domain_end()), {2, 1, 0}) < 1e-12);
    QVERIFY(nf::norm(nf::cross(g2.tangent(g2.domain_start()), {1, 0, 0})) < 1e-9);  // tangent to a
    // clicked ends, G1: from the start of a to the end of b
    c = create_command(QStringLiteral("blend"));
    QVERIFY(c->begin(sel));
    QCOMPARE(c->number(3), R::Rejected);
    QCOMPARE(c->number(1), R::Continue);
    QCOMPARE(c->point({-0.1, 0, 0}, kTop), R::Continue);
    QCOMPARE(c->point({3.2, 1, 0}, kTop), R::Done);
    const auto made_g1 = c->takeEntities();
    const auto& g1 = curve_of(made_g1);
    QCOMPARE(g1.degree(), std::size_t{3});
    QVERIFY(nf::distance(g1.evaluate(g1.domain_start()), {0, 0, 0}) < 1e-12);
    QVERIFY(nf::distance(g1.evaluate(g1.domain_end()), {3, 1, 0}) < 1e-12);
  }

  void chamferTwoCurvesAndCorners() {
    const auto sel = lines({{{0, 0, 0}, {2, 0, 0}}, {{2, 0, 0}, {2, 2, 0}}});
    auto c = create_command(QStringLiteral("cha"));
    QVERIFY(c->begin(sel));
    QCOMPARE(c->number(-1), R::Rejected);
    QCOMPARE(c->number(0.5), R::Done);
    const auto edit = c->takeEdit();
    QCOMPARE(edit.add.size(), std::size_t{1});
    const auto& cut = std::get<nf::NurbsCurve>(*edit.add.front().geometry);
    QVERIFY(nf::distance(cut.evaluate(cut.domain_start()), {1.5, 0, 0}) < 1e-12);
    QVERIFY(nf::distance(cut.evaluate(cut.domain_end()), {2, 0.5, 0}) < 1e-12);
    QCOMPARE(edit.replace.size(), std::size_t{2});  // both lines trimmed to the cut
    // one curve: every corner
    std::vector<nfcad::document::Entity> one{nfcad::document::make_entity(
        nf::make_polyline({{0, 0, 0}, {2, 0, 0}, {2, 2, 0}}))};
    one.front().id = 7;
    c = create_command(QStringLiteral("chamfercorners"));
    QVERIFY(c->begin(one));
    QCOMPARE(c->number(0.5), R::Done);
    const auto e2 = c->takeEdit();
    QCOMPARE(e2.replace.size(), std::size_t{1});
    const auto& cornered = std::get<nf::NurbsCurve>(*e2.replace.front().second);
    QVERIFY(nf::closest_point(cornered, {1.75, 0.25, 0}).distance < 1e-9);  // on the cut
    QCOMPARE(create_command(QStringLiteral("filletcorners"))->id(), QStringLiteral("fillet_curve"));
  }

  void tweenBetweenCurves() {
    const auto sel = lines({{{0, 0, 0}, {4, 0, 0}}, {{4, 2, 0}, {0, 2, 0}}});  // the second runs back
    auto c = create_command(QStringLiteral("tween"));
    QVERIFY(c->begin(sel));
    QCOMPARE(c->number(2.5), R::Rejected);
    QCOMPARE(c->number(3), R::Done);
    const auto made = c->takeEntities();
    QCOMPARE(made.size(), std::size_t{3});
    const auto& mid = std::get<nf::NurbsCurve>(*made[1].geometry);
    QVERIFY(nf::distance(mid.evaluate(mid.domain_start()), {0, 1, 0}) < 1e-12);  // turned round
    QVERIFY(nf::distance(mid.evaluate(mid.domain_end()), {4, 1, 0}) < 1e-12);
    c = create_command(QStringLiteral("tweencurves"));
    QVERIFY(c->begin(sel));
    QCOMPARE(c->finish(), R::Done);  // Enter: one
    QCOMPARE(c->takeEntities().size(), std::size_t{1});
  }

  void tangentFromAPointAndBetweenCurves() {
    std::vector<nfcad::document::Entity> circle{nfcad::document::make_entity(nf::make_circle({0, 0, 0}, {0, 0, 1}, 1.0))};
    circle.front().id = 1;
    auto c = create_command(QStringLiteral("tan"));
    QVERIFY(c->begin(circle));
    QCOMPARE(c->point({2, 0, 0}, kTop), R::Continue);  // from (2, 0): touching at (1/2, ±sqrt(3)/2)
    QVERIFY(!c->preview({0.5, 1, 0}, kTop).empty());
    QCOMPARE(c->point({0.5, 1, 0}, kTop), R::Done);    // the upper one
    const auto made_t = c->takeEntities();
    const auto& t = curve_of(made_t);
    QVERIFY(nf::distance(t.evaluate(t.domain_end()), {0.5, std::sqrt(3.0) / 2, 0}) < 1e-9);
    // two circles: the outer tangent above
    std::vector<nfcad::document::Entity> two{circle[0],
                                             nfcad::document::make_entity(nf::make_circle({4, 0, 0}, {0, 0, 1}, 1.0))};
    two[1].id = 2;
    c = create_command(QStringLiteral("tangent"));
    QVERIFY(c->begin(two));
    QCOMPARE(c->point({2, 1.1, 0}, kTop), R::Done);
    const auto made_o = c->takeEntities();
    const auto& o = curve_of(made_o);
    for (const auto& q : o.sample(5)) QVERIFY(std::abs(q.y - 1.0) < 1e-9);
  }

  void perpendicularToACurve() {
    std::vector<nfcad::document::Entity> line{nfcad::document::make_entity(nf::make_line({0, 0, 0}, {4, 0, 0}))};
    line.front().id = 1;
    auto c = create_command(QStringLiteral("perp"));
    QVERIFY(c->begin(line));
    QCOMPARE(c->point({1, 2, 0}, kTop), R::Continue);
    QCOMPARE(c->point({3, 0, 0}, kTop), R::Rejected);  // on the curve
    QCOMPARE(c->point({3, -1, 0}, kTop), R::Continue);
    QCOMPARE(c->finish(), R::Done);
    const auto made = c->takeEntities();
    QCOMPARE(made.size(), std::size_t{2});
    const auto& first = std::get<nf::NurbsCurve>(*made[0].geometry);
    QVERIFY(nf::distance(first.evaluate(first.domain_end()), {1, 0, 0}) < 1e-9);
  }

  void distanceMessage() {
    auto c = create_command(QStringLiteral("distance"));
    c->point({0, 0, 0}, kTop);
    QCOMPARE(c->point({3, 4, 12}, kTop), R::Done);
    QVERIFY(c->message().startsWith(QStringLiteral("Distance 13")));
    QVERIFY(c->takeEntities().empty());
  }

  void pointCommandKeepsGoing() {
    auto c = create_command(QStringLiteral("point"));
    QCOMPARE(c->point({1, 2, 3}, kTop), R::Continue);
    QCOMPARE(c->takeEntities().size(), std::size_t{1});
    QCOMPARE(c->point({4, 5, 6}, kTop), R::Continue);
    QCOMPARE(c->finish(), R::Done);
  }
};

QTEST_GUILESS_MAIN(TestCommands)
#include "test_commands.moc"
