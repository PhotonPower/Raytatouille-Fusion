#include "ui/block_drawing.hpp"

#include <QApplication>
#include <QClipboard>
#include <QContextMenuEvent>
#include <QFileDialog>
#include <QFontMetricsF>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMenu>
#include <QPainter>
#include <QPainterPath>
#include <QPalette>
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace nfcad::ui {

namespace {

bool finite(double v) { return std::isfinite(v); }

/// [x, y] → point; false if it is not a pair of finite numbers.
bool read_point(const QJsonValue& v, QPointF* out) {
  const QJsonArray a = v.toArray();
  if (a.size() != 2 || !a[0].isDouble() || !a[1].isDouble()) return false;
  const double x = a[0].toDouble();
  const double y = a[1].toDouble();
  if (!finite(x) || !finite(y)) return false;
  *out = {x, y};
  return true;
}

bool read_points(const QJsonValue& v, QList<QPointF>* out) {
  if (!v.isArray()) return false;
  for (const QJsonValue& p : v.toArray()) {
    QPointF q;
    if (!read_point(p, &q)) return false;
    out->append(q);
  }
  return true;
}

QColor read_color(const QJsonValue& v) {
  if (!v.isString()) return {};
  return QColor::fromString(v.toString());
}

bool dark(const QPalette& palette) { return palette.color(QPalette::Window).lightness() < 128; }

QColor role_color(const QString& role, const QPalette& palette) {
  const bool d = dark(palette);
  const QColor text = palette.color(QPalette::WindowText);
  if (role == QLatin1String("ray")) return d ? QColor(255, 120, 100) : QColor(200, 40, 40);
  if (role == QLatin1String("light")) return d ? QColor(255, 196, 70) : QColor(190, 110, 0);
  if (role == QLatin1String("detector")) return d ? QColor(110, 175, 255) : QColor(25, 90, 200);
  if (role == QLatin1String("error")) return d ? QColor(255, 110, 110) : QColor(190, 20, 20);
  if (role == QLatin1String("axis") || role == QLatin1String("dimension") || role == QLatin1String("guide") ||
      role == QLatin1String("note")) {
    QColor c = text;
    c.setAlphaF(role == QLatin1String("note") ? 0.75F : 0.6F);
    return c;
  }
  return text;
}

QPen role_pen(const Drawing::Item& item, const QPalette& palette) {
  QPen pen(item.color.isValid() ? item.color : role_color(item.role, palette));
  double width = 1.2;
  if (item.role == QLatin1String("stop")) width = 2.6;
  if (item.role == QLatin1String("detector")) width = 2.4;
  if (item.role == QLatin1String("surface")) width = 1.6;
  if (item.role == QLatin1String("ray")) width = 1.3;
  if (item.role == QLatin1String("light")) width = 1.8;
  if (item.width > 0) width = std::min(item.width, 12.0);
  pen.setWidthF(width);
  pen.setCosmetic(true);
  if (item.role == QLatin1String("axis")) pen.setStyle(Qt::DashDotLine);
  if (item.role == QLatin1String("guide")) pen.setStyle(Qt::DotLine);
  if (item.dashed) pen.setStyle(Qt::DashLine);
  return pen;
}

/// 1, 2 or 5 times a power of ten, about `rough`.
double nice_step(double rough) {
  if (!(rough > 0) || !finite(rough)) return 1.0;
  const double e = std::pow(10.0, std::floor(std::log10(rough)));
  const double f = rough / e;
  return (f < 1.5 ? 1.0 : f < 3.5 ? 2.0 : f < 7.5 ? 5.0 : 10.0) * e;
}

QString number(double v, double step) {
  if (std::abs(v) < step * 1e-6) v = 0.0;
  const int decimals = std::clamp(static_cast<int>(-std::floor(std::log10(step) + 1e-9)), 0, 8);
  return QString::number(v, 'f', decimals);
}

void arrow_head(QPainter& p, const QPointF& tip, const QPointF& from, double size) {
  const QPointF d = tip - from;
  const double len = std::hypot(d.x(), d.y());
  if (len < 1e-9) return;
  const QPointF u = d / len;
  const QPointF n(-u.y(), u.x());
  QPolygonF head;
  head << tip << tip - u * size + n * size * 0.4 << tip - u * size - n * size * 0.4;
  p.save();
  p.setBrush(p.pen().color());
  QPen pen = p.pen();
  pen.setStyle(Qt::SolidLine);
  p.setPen(pen);
  p.drawPolygon(head);
  p.restore();
}

/// Draws `text` at `at` aligned as given ("left" means the text starts at `at`).
void draw_text(QPainter& p, const QPointF& at, const QString& text, const QString& align, const QString& valign) {
  const QFontMetricsF fm(p.font());
  QRectF box(0, 0, fm.horizontalAdvance(text) + 2, fm.height());
  double x = at.x() - box.width() / 2;
  if (align == QLatin1String("left")) x = at.x() + 2;
  if (align == QLatin1String("right")) x = at.x() - box.width() - 2;
  double y = at.y() - box.height() / 2;
  if (valign == QLatin1String("top")) y = at.y() + 1;
  if (valign == QLatin1String("bottom")) y = at.y() - box.height() - 1;
  box.moveTo(x, y);
  p.drawText(box, Qt::AlignCenter, text);
}

QString compact(const QJsonValue& v) {
  if (v.isString()) return v.toString();
  if (v.isDouble()) return QString::number(v.toDouble(), 'g', 6);
  if (v.isBool()) return v.toBool() ? QStringLiteral("true") : QStringLiteral("false");
  if (v.isArray()) {
    const QString s = QString::fromUtf8(QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact));
    return s.size() > 40 ? s.left(37) + QStringLiteral("…") : s;
  }
  return {};
}

}  // namespace

// ------------------------------------------------------------------------------ the drawing

QRectF Drawing::bounds() const {
  bool any = false;
  double x0 = 0;
  double x1 = 0;
  double y0 = 0;
  double y1 = 0;
  for (const Item& item : items) {
    for (const QPointF& q : item.points) {
      if (!any) {
        x0 = x1 = q.x();
        y0 = y1 = q.y();
        any = true;
      }
      x0 = std::min(x0, q.x());
      x1 = std::max(x1, q.x());
      y0 = std::min(y0, q.y());
      y1 = std::max(y1, q.y());
    }
  }
  return any ? QRectF(QPointF(x0, y0), QPointF(x1, y1)) : QRectF();
}

QColor Drawing::materialFill(const QString& name, const QPalette& palette) const {
  for (const Material& m : materials) {
    if (m.name == name && m.fill.isValid()) return m.fill;
  }
  const QString key = name.section(QLatin1Char(':'), -1).toLower();
  const bool d = dark(palette);
  if (key.isEmpty() || key == QLatin1String("air") || key == QLatin1String("vacuum")) {
    QColor c = palette.color(QPalette::WindowText);
    c.setAlphaF(0.06F);
    return c;
  }
  // a hue from the name (FNV-1a: the same in every process): the same material has the same
  // colour in every drawing
  std::uint32_t h = 2166136261U;
  for (const QChar c : key) h = (h ^ c.unicode()) * 16777619U;
  const int hue = static_cast<int>(h % 360U);
  QColor c = QColor::fromHsl(hue, d ? 120 : 150, d ? 110 : 175);
  c.setAlphaF(d ? 0.75F : 0.7F);
  return c;
}

std::optional<Drawing> parse_drawing(const QJsonObject& json, QStringList* problems) {
  QStringList local;
  QStringList& why = problems != nullptr ? *problems : local;
  auto fail = [&why](const QString& m) -> std::optional<Drawing> {
    why << m;
    return std::nullopt;
  };
  if (json.contains("format") && json["format"].toString() != QLatin1String("nfcad-drawing")) {
    return fail(QObject::tr("not a drawing (format %1)").arg(json["format"].toString()));
  }
  if (!json["items"].isArray()) return fail(QObject::tr("a drawing needs an array 'items'"));
  const QJsonArray items = json["items"].toArray();
  if (items.size() > kMaxDrawingItems) {
    return fail(QObject::tr("too many items (%1, at most %2)").arg(items.size()).arg(kMaxDrawingItems));
  }
  Drawing d;
  d.title = json["title"].toString();
  for (const QJsonValue& n : json["notes"].toArray()) d.notes << n.toString();
  d.unit = json["unit"].toString();
  const QJsonArray axes = json["axes"].toArray();
  if (axes.size() == 2) {
    d.x_axis = axes[0].toString(d.x_axis);
    d.y_axis = axes[1].toString(d.y_axis);
  }
  if (json.contains("axes") && (json["axes"].isNull() || json["axes"].isBool())) d.axes = json["axes"].toBool();
  const QString aspect = json["aspect"].toString(QStringLiteral("equal"));
  if (aspect != QLatin1String("equal") && aspect != QLatin1String("fit")) {
    return fail(QObject::tr("aspect must be 'equal' or 'fit', not '%1'").arg(aspect));
  }
  d.equal_aspect = aspect == QLatin1String("equal");
  int points = 0;
  for (int k = 0; k < items.size(); ++k) {
    const QJsonObject o = items[k].toObject();
    const QString type = o["type"].toString();
    Drawing::Item item;
    const QString where = QObject::tr("item %1 (%2)").arg(k).arg(type);
    if (type == QLatin1String("polygon") || type == QLatin1String("polyline")) {
      item.kind = type == QLatin1String("polygon") ? Drawing::Kind::Polygon : Drawing::Kind::Polyline;
      if (!read_points(o["points"], &item.points)) return fail(where + QObject::tr(": points must be [[x, y], …] of finite numbers"));
      const int least = item.kind == Drawing::Kind::Polygon ? 3 : 2;
      if (item.points.size() < least) return fail(where + QObject::tr(": needs at least %1 points").arg(least));
    } else if (type == QLatin1String("text")) {
      item.kind = Drawing::Kind::Text;
      QPointF at;
      if (!read_point(o["at"], &at)) return fail(where + QObject::tr(": 'at' must be [x, y]"));
      item.points = {at};
      if (!o["text"].isString()) return fail(where + QObject::tr(": needs a 'text'"));
    } else if (type == QLatin1String("dimension") || type == QLatin1String("arrow")) {
      item.kind = type == QLatin1String("dimension") ? Drawing::Kind::Dimension : Drawing::Kind::Arrow;
      QPointF a;
      QPointF b;
      if (!read_point(o["from"], &a) || !read_point(o["to"], &b)) return fail(where + QObject::tr(": 'from' and 'to' must be [x, y]"));
      item.points = {a, b};
    } else {
      why << QObject::tr("%1: unknown item type, skipped").arg(where);
      continue;
    }
    points += static_cast<int>(item.points.size());
    if (points > kMaxDrawingPoints) return fail(QObject::tr("too many points (more than %1)").arg(kMaxDrawingPoints));
    item.text = o["text"].toString(o["label"].toString());
    item.material = o["material"].toString();
    item.role = o["role"].toString();
    item.color = read_color(o["color"]);
    item.fill = read_color(o["fill"]);
    item.dashed = o["dashed"].toBool();
    item.hatched = o["hatched"].toBool();
    item.width = o["width"].toDouble();
    if (!finite(item.width) || item.width < 0) item.width = 0;
    item.align = o["align"].toString();
    item.valign = o["valign"].toString();
    d.items.push_back(item);
  }
  for (const QJsonValue& v : json["materials"].toArray()) {
    const QJsonObject o = v.toObject();
    if (o["name"].toString().isEmpty()) continue;
    d.materials.push_back({o["name"].toString(), o["label"].toString(o["name"].toString()), read_color(o["fill"])});
  }
  // every material of a polygon is in the legend
  for (const Drawing::Item& item : d.items) {
    if (item.kind != Drawing::Kind::Polygon || item.material.isEmpty()) continue;
    const bool listed = std::any_of(d.materials.begin(), d.materials.end(),
                                    [&item](const Drawing::Material& m) { return m.name == item.material; });
    if (!listed) d.materials.push_back({item.material, item.material, {}});
  }
  return d;
}

// ------------------------------------------------------------------------------ fallback

QJsonObject schematic_drawing(const QJsonObject& node, const QJsonObject& type, const QString& reason) {
  // the light ports: left where light comes in first ("front"), right where it leaves
  QJsonArray ports = node["ports"].toArray();
  if (ports.isEmpty()) ports = type["ports"].toArray();
  QJsonArray sockets = node["sockets"].toArray();
  if (sockets.isEmpty()) sockets = type["sockets"].toArray();
  QStringList left;
  QStringList right;
  QStringList data_in;
  QStringList data_out;
  if (!ports.isEmpty()) {
    for (int k = 0; k < ports.size(); ++k) {
      const QJsonObject p = ports[k].toObject();
      const QString side = p["side"].toString();
      const bool on_left = side == QLatin1String("front") || (side.isEmpty() && (k % 2 == 0 || ports.size() == 1));
      (on_left && side != QLatin1String("back") ? left : right) << p["name"].toString();
    }
  }
  for (const QJsonValue& v : sockets) {
    const QJsonObject s = v.toObject();
    const bool in = s["direction"].toString() == QLatin1String("in");
    const QString label = s["label"].toString(s["name"].toString());
    if (s["kind"].toString() == QLatin1String("light")) {
      if (ports.isEmpty()) (in ? left : right) << label;
    } else {
      (in ? data_in : data_out) << label;
    }
  }
  const int rows = static_cast<int>(std::max<qsizetype>({left.size(), right.size(), 2}));
  const double w = 8.0;
  const double h = 1.2 * rows + 0.8;
  QJsonArray items;
  auto pt = [](double x, double y) { return QJsonArray{x, y}; };
  items.append(QJsonObject{{"type", "polygon"},
                           {"points", QJsonArray{pt(0, 0), pt(w, 0), pt(w, h), pt(0, h)}},
                           {"fill", "#00000000"}});
  items.append(QJsonObject{{"type", "text"}, {"at", pt(w / 2, h / 2 + 0.3)}, {"text", node["name"].toString(node["id"].toString())}});
  items.append(QJsonObject{{"type", "text"}, {"at", pt(w / 2, h / 2 - 0.4)}, {"text", node["type"].toString()}, {"role", "note"}});
  auto side_ports = [&](const QStringList& names, bool on_left) {
    for (int k = 0; k < names.size(); ++k) {
      const double y = h - (h / (names.size() + 1)) * (k + 1);
      const double x = on_left ? 0.0 : w;
      const double out = on_left ? -1.4 : 1.4;
      items.append(QJsonObject{{"type", "arrow"}, {"from", pt(x + out, y)}, {"to", pt(x, y)}, {"role", "light"}});
      items.append(QJsonObject{{"type", "arrow"}, {"from", pt(x, y - 0.25)}, {"to", pt(x + out, y - 0.25)}, {"role", "light"}, {"dashed", true}});
      items.append(QJsonObject{{"type", "text"}, {"at", pt(x + out, y + 0.3)}, {"text", names[k]},
                               {"align", on_left ? "right" : "left"}});
    }
  };
  side_ports(left, true);
  side_ports(right, false);
  auto data_ports = [&](const QStringList& names, bool in) {
    for (int k = 0; k < names.size(); ++k) {
      const double x = (w / (names.size() + 1)) * (k + 1);
      const double y = in ? h : 0.0;
      const double out = in ? 1.0 : -1.0;
      items.append(QJsonObject{{"type", "arrow"},
                               {"from", pt(x, in ? y + out : y)},
                               {"to", pt(x, in ? y : y + out)},
                               {"role", "guide"}});
      items.append(QJsonObject{{"type", "text"}, {"at", pt(x, y + out * 1.25)}, {"text", names[k]}, {"role", "note"}});
    }
  };
  data_ports(data_in, true);
  data_ports(data_out, false);
  QJsonArray notes;
  if (!type["description"].toString().isEmpty()) notes.append(type["description"].toString());
  QStringList values;
  const QJsonObject params = node["params"].toObject();
  for (const QJsonValue& v : type["params"].toArray()) {
    const QString name = v.toObject()["name"].toString();
    const QString text = compact(params.contains(name) ? params[name] : v.toObject()["default"]);
    if (!text.isEmpty() && values.size() < 6) values << QStringLiteral("%1 = %2").arg(name, text);
  }
  if (!values.isEmpty()) notes.append(values.join(QStringLiteral(", ")));
  if (!reason.isEmpty()) notes.append(reason);
  return QJsonObject{{"format", "nfcad-drawing"},
                     {"version", 1},
                     {"title", node["name"].toString(node["id"].toString())},
                     {"axes", false},
                     {"aspect", "equal"},
                     {"items", items},
                     {"notes", notes}};
}

// ------------------------------------------------------------------------------ painting

void paint_drawing(QPainter& p, const QRectF& rect, const Drawing& drawing, const QPalette& palette, const QString& error) {
  p.save();
  p.setRenderHint(QPainter::Antialiasing);
  p.setRenderHint(QPainter::TextAntialiasing);
  const QColor text = palette.color(QPalette::WindowText);
  QFont base = p.font();
  QFont small = base;
  small.setPointSizeF(std::max(7.0, base.pointSizeF() * 0.85));
  QFont bold = base;
  bold.setBold(true);
  const QFontMetricsF fm(base);
  const QFontMetricsF fms(small);
  QRectF area = rect.adjusted(8, 6, -8, -6);
  // title and error on top
  if (!drawing.title.isEmpty()) {
    p.setFont(bold);
    p.setPen(text);
    p.drawText(QRectF(area.left(), area.top(), area.width(), fm.height()), Qt::AlignLeft | Qt::AlignVCenter,
               QFontMetricsF(bold).elidedText(drawing.title, Qt::ElideRight, area.width()));
    area.setTop(area.top() + fm.height() + 4);
  }
  if (!error.isEmpty()) {
    p.setFont(small);
    p.setPen(role_color(QStringLiteral("error"), palette));
    const QRectF box = fms.boundingRect(QRectF(area.left(), area.top(), area.width(), 1000), Qt::TextWordWrap, error);
    p.drawText(QRectF(area.left(), area.top(), area.width(), box.height()), Qt::TextWordWrap, error);
    area.setTop(area.top() + box.height() + 4);
  }
  // measured first, drawn after the plot: notes under it, the legend right of it (if there is
  // room) or under it
  const QString notes = drawing.notes.join(QLatin1Char('\n'));
  double notes_h = 0;
  if (!notes.isEmpty()) {
    notes_h = std::min(fms.boundingRect(QRectF(0, 0, area.width(), 1000), Qt::TextWordWrap, notes).height(),
                       area.height() * 0.35);
    area.setBottom(area.bottom() - notes_h - 4);
  }
  const auto& materials = drawing.materials;
  double widest = 0;
  for (const auto& m : materials) widest = std::max(widest, fms.horizontalAdvance(m.label));
  const double swatch = fms.height() * 0.9;
  const double entry_w = std::min(widest + swatch + 12, 220.0);
  const double line = fms.height() + 3;
  const bool legend_beside = !materials.empty() && area.width() > 420 && area.width() - entry_w > 240;
  const int per_row = std::max(1, static_cast<int>(area.width() / entry_w));
  const int rows = legend_beside ? 0 : (static_cast<int>(materials.size()) + per_row - 1) / per_row;
  QRectF plot = area;
  if (legend_beside) plot.setRight(area.right() - entry_w - 14);
  plot.setBottom(plot.bottom() - rows * line);
  const double axis_room = drawing.axes ? 2 * fms.height() + 8 : 0.0;
  if (drawing.axes) plot.adjust(fms.horizontalAdvance(QStringLiteral("-00.000")) + 10, 4, -6, -axis_room);
  QRectF b = drawing.bounds();
  if (plot.width() < 20 || plot.height() < 20 || drawing.items.empty()) {
    p.restore();
    return;
  }
  // a margin around the content; a box without width or height gets one
  const double span = std::max(b.width(), b.height());
  const double pad = span > 1e-9 ? span * 0.05 : 0.5;
  if (b.width() <= span * 1e-3) b.adjust(-pad, 0, pad, 0);
  if (b.height() <= span * 1e-3) b.adjust(0, -pad, 0, pad);
  b.adjust(-b.width() * 0.04, -b.height() * 0.04, b.width() * 0.04, b.height() * 0.04);
  double sx = plot.width() / b.width();
  double sy = plot.height() / b.height();
  if (drawing.equal_aspect) sx = sy = std::min(sx, sy);
  // centred across, at the top
  const double ox = plot.center().x() - b.center().x() * sx;
  const double oy = plot.top() + b.bottom() * sy;
  auto map = [&](const QPointF& q) { return QPointF(ox + q.x() * sx, oy - q.y() * sy); };
  const QRectF used(map(b.topLeft()).x(), map(b.bottomRight()).y(), b.width() * sx, b.height() * sy);
  double below = used.bottom() + axis_room + 4;  // where the legend (below) and the notes go
  if (!materials.empty()) {
    p.setFont(small);
    for (int k = 0; k < static_cast<int>(materials.size()); ++k) {
      const auto& m = materials[static_cast<std::size_t>(k)];
      const double x = legend_beside ? used.right() + 14 : area.left() + (k % per_row) * entry_w;
      const double y = legend_beside ? used.top() + k * line : below + (k / per_row) * line;
      if (legend_beside && y + line > area.bottom()) break;
      p.setPen(QPen(text, 0.8));
      p.setBrush(drawing.materialFill(m.name, palette));
      p.drawRect(QRectF(x, y + (line - swatch) / 2, swatch, swatch));
      p.setPen(text);
      p.drawText(QRectF(x + swatch + 6, y, entry_w - swatch - 8, line), Qt::AlignLeft | Qt::AlignVCenter,
                 fms.elidedText(m.label, Qt::ElideRight, entry_w - swatch - 8));
    }
    below += rows * line;
  }
  if (!notes.isEmpty()) {
    p.setFont(small);
    QColor muted = text;
    muted.setAlphaF(0.8F);
    p.setPen(muted);
    p.drawText(QRectF(area.left(), below, area.width(), notes_h), Qt::TextWordWrap, notes);
  }
  if (drawing.axes) {
    QColor frame = text;
    frame.setAlphaF(0.45F);
    p.setPen(QPen(frame, 0.8));
    p.setBrush(Qt::NoBrush);
    p.drawRect(used);
    p.setFont(small);
    const double xs = nice_step(b.width() / std::max(2.0, used.width() / 80));
    const double ys = nice_step(b.height() / std::max(2.0, used.height() / 50));
    for (double x = std::ceil(b.left() / xs) * xs; x <= b.right() + xs * 1e-9; x += xs) {
      const double px = map({x, 0}).x();
      p.setPen(QPen(frame, 0.8));
      p.drawLine(QPointF(px, used.bottom()), QPointF(px, used.bottom() + 4));
      p.setPen(text);
      draw_text(p, QPointF(px, used.bottom() + 5), number(x, xs), {}, QStringLiteral("top"));
    }
    for (double y = std::ceil(b.top() / ys) * ys; y <= b.bottom() + ys * 1e-9; y += ys) {
      const double py = map({0, y}).y();
      p.setPen(QPen(frame, 0.8));
      p.drawLine(QPointF(used.left() - 4, py), QPointF(used.left(), py));
      p.setPen(text);
      draw_text(p, QPointF(used.left() - 5, py), number(y, ys), QStringLiteral("right"), {});
    }
    const QString unit = drawing.unit.isEmpty() ? QString() : QStringLiteral(" (%1)").arg(drawing.unit);
    draw_text(p, QPointF(used.center().x(), used.bottom() + fms.height() + 6), drawing.x_axis + unit, {}, QStringLiteral("top"));
    p.save();
    p.translate(used.left() - fms.horizontalAdvance(QStringLiteral("-00.000")) - 6, used.center().y());
    p.rotate(-90);
    draw_text(p, QPointF(0, 0), drawing.y_axis + unit, {}, QStringLiteral("bottom"));
    p.restore();
  }
  p.save();
  p.setClipRect(used.adjusted(-2, -2, 2, 2).united(plot));
  // filled polygons first, lines over them, texts last
  for (const Drawing::Item& item : drawing.items) {
    if (item.kind != Drawing::Kind::Polygon) continue;
    QPolygonF poly;
    for (const QPointF& q : item.points) poly << map(q);
    const QColor fill = item.fill.isValid() ? item.fill : drawing.materialFill(item.material, palette);
    p.setPen(item.role.isEmpty() && !item.color.isValid() ? QPen(text, 0.9) : role_pen(item, palette));
    p.setBrush(fill);
    p.drawPolygon(poly);
    if (item.hatched) {
      QColor h = text;
      h.setAlphaF(0.35F);
      p.setBrush(QBrush(h, Qt::BDiagPattern));
      p.setPen(Qt::NoPen);
      p.drawPolygon(poly);
    }
  }
  p.setBrush(Qt::NoBrush);
  for (const Drawing::Item& item : drawing.items) {
    if (item.kind == Drawing::Kind::Polyline) {
      QPolygonF path;
      for (const QPointF& q : item.points) path << map(q);
      p.setPen(role_pen(item, palette));
      p.drawPolyline(path);
    } else if (item.kind == Drawing::Kind::Arrow) {
      Drawing::Item styled = item;
      if (styled.role.isEmpty()) styled.role = QStringLiteral("light");
      p.setPen(role_pen(styled, palette));
      const QPointF a = map(item.points[0]);
      const QPointF c = map(item.points[1]);
      p.drawLine(a, c);
      arrow_head(p, c, a, 9);
    } else if (item.kind == Drawing::Kind::Dimension) {
      Drawing::Item styled = item;
      if (styled.role.isEmpty()) styled.role = QStringLiteral("dimension");
      p.setPen(role_pen(styled, palette));
      const QPointF a = map(item.points[0]);
      const QPointF c = map(item.points[1]);
      p.drawLine(a, c);
      arrow_head(p, c, a, 7);
      arrow_head(p, a, c, 7);
    }
  }
  p.restore();
  p.setFont(small);
  for (const Drawing::Item& item : drawing.items) {
    if (item.text.isEmpty()) continue;
    if (item.kind == Drawing::Kind::Text) {
      p.setPen(item.color.isValid() ? item.color : role_color(item.role, palette));
      draw_text(p, map(item.points[0]), item.text, item.align, item.valign);
    } else if (item.kind == Drawing::Kind::Dimension) {
      const QPointF a = map(item.points[0]);
      const QPointF c = map(item.points[1]);
      const QPointF mid = (a + c) / 2;
      const bool vertical = std::abs(c.x() - a.x()) < std::abs(c.y() - a.y());
      p.setPen(item.color.isValid() ? item.color : text);
      if (vertical) {
        draw_text(p, mid + QPointF(4, 0), item.text, QStringLiteral("left"), {});
      } else {
        draw_text(p, mid - QPointF(0, 2), item.text, {}, QStringLiteral("bottom"));
      }
    } else if (item.kind == Drawing::Kind::Arrow) {
      p.setPen(item.color.isValid() ? item.color : role_color(item.role.isEmpty() ? QStringLiteral("light") : item.role, palette));
      const QPointF a = map(item.points[0]);
      draw_text(p, a, item.text, item.align.isEmpty() ? QStringLiteral("left") : item.align,
                item.valign.isEmpty() ? QStringLiteral("bottom") : item.valign);
    } else if (item.kind == Drawing::Kind::Polygon || item.kind == Drawing::Kind::Polyline) {
      QPointF c;
      for (const QPointF& q : item.points) c += q;
      c /= static_cast<double>(item.points.size());
      p.setPen(text);
      draw_text(p, map(c), item.text, item.align, item.valign);
    }
  }
  p.restore();
}

// ------------------------------------------------------------------------------ the view

DrawingView::DrawingView(QWidget* parent) : QWidget(parent) {
  setAutoFillBackground(true);
  setBackgroundRole(QPalette::Base);
}

void DrawingView::setDrawing(const Drawing& drawing, const QString& error) {
  drawing_ = drawing;
  error_ = error;
  busy_.clear();
  update();
}

void DrawingView::setBusy(const QString& text) {
  busy_ = text;
  update();
}

QImage DrawingView::render(const QSize& size, double scale) const {
  QImage image(size * scale, QImage::Format_ARGB32_Premultiplied);
  image.setDevicePixelRatio(scale);
  QPalette pal = palette();
  pal.setColor(QPalette::Window, pal.color(QPalette::Base));
  image.fill(pal.color(QPalette::Base));
  if (drawing_) {
    QPainter p(&image);
    p.setFont(font());
    paint_drawing(p, QRectF(QPointF(0, 0), QSizeF(size)), *drawing_, pal, error_);
  }
  return image;
}

void DrawingView::paintEvent(QPaintEvent* /*event*/) {
  QPainter p(this);
  QPalette pal = palette();
  pal.setColor(QPalette::Window, pal.color(QPalette::Base));
  if (drawing_) paint_drawing(p, QRectF(rect()), *drawing_, pal, error_);
  if (!busy_.isEmpty()) {
    QColor muted = pal.color(QPalette::WindowText);
    muted.setAlphaF(0.7F);
    p.setPen(muted);
    if (drawing_) {
      p.drawText(QRectF(rect()).adjusted(8, 6, -8, -6), Qt::AlignRight | Qt::AlignTop, busy_);
    } else {
      p.drawText(QRectF(rect()), Qt::AlignCenter, busy_);
    }
  }
}

void DrawingView::contextMenuEvent(QContextMenuEvent* event) {
  if (!drawing_) return;
  QMenu menu(this);
  menu.addAction(tr("Copy image"), this, [this] {
    QApplication::clipboard()->setImage(render(size(), 2.0));
  });
  menu.addAction(tr("Save image…"), this, [this] {
    const QString file = QFileDialog::getSaveFileName(this, tr("Save overview"), {}, tr("PNG image (*.png)"));
    if (!file.isEmpty()) render(size(), 2.0).save(file);
  });
  menu.exec(event->globalPos());
}

}  // namespace nfcad::ui
