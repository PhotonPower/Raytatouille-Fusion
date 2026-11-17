// Keyed results in the document, see result_io.hpp.
#include "results/result_io.hpp"

#include <QByteArray>
#include <QSet>
#include <cstring>
#include <vector>

#include "results/result_store.hpp"

namespace nfcad::results {

namespace {

template <typename T>
QString encode(const std::vector<T>& v) {
  return QString::fromLatin1(
      QByteArray(reinterpret_cast<const char*>(v.data()), static_cast<qsizetype>(v.size() * sizeof(T))).toBase64());
}

template <typename T>
bool decode(const QJsonValue& value, std::vector<T>& out) {
  const QByteArray bytes = QByteArray::fromBase64(value.toString().toLatin1());
  if (bytes.size() % static_cast<qsizetype>(sizeof(T)) != 0) return false;
  out.resize(static_cast<std::size_t>(bytes.size()) / sizeof(T));
  if (!out.empty()) std::memcpy(out.data(), bytes.constData(), static_cast<std::size_t>(bytes.size()));
  return true;
}

QJsonObject image_json(const Image& im) {
  QJsonObject o{{"width", im.width},
                {"height", im.height},
                {"values", encode(im.values)},
                {"extent", QJsonArray{im.x0, im.x1, im.y0, im.y1}},
                {"x_label", im.x_label},
                {"y_label", im.y_label},
                {"colormap", colormap_name(im.colormap)},
                {"unit", im.unit},
                {"description", im.description}};
  if (!im.rgb.empty()) o["rgb"] = encode(im.rgb);
  if (im.range) o["range"] = QJsonArray{im.range->min, im.range->max};
  return o;
}

bool image_from(const QJsonObject& o, Image& im) {
  im.width = o["width"].toInt();
  im.height = o["height"].toInt();
  if (!decode(o["values"], im.values) || im.width <= 0 || im.height <= 0 ||
      im.values.size() != static_cast<std::size_t>(im.width) * static_cast<std::size_t>(im.height)) {
    return false;
  }
  if (o.contains(QLatin1String("rgb")) && (!decode(o["rgb"], im.rgb) || im.rgb.size() != 3 * im.values.size())) {
    return false;
  }
  const QJsonArray e = o["extent"].toArray();
  if (e.size() == 4) {
    im.x0 = e[0].toDouble();
    im.x1 = e[1].toDouble();
    im.y0 = e[2].toDouble();
    im.y1 = e[3].toDouble();
  }
  im.x_label = o["x_label"].toString();
  im.y_label = o["y_label"].toString();
  im.colormap = colormap_from_name(o["colormap"].toString());
  im.unit = o["unit"].toString();
  im.description = o["description"].toString();
  const QJsonArray r = o["range"].toArray();
  if (r.size() == 2) im.range = Range{r[0].toDouble(), r[1].toDouble()};
  return true;
}

const char* kind_name(ResultItem::Kind k) {
  switch (k) {
    case ResultItem::Kind::Image: return "image";
    case ResultItem::Kind::Curve: return "curve";
    case ResultItem::Kind::Table: return "table";
    case ResultItem::Kind::Bars: return "bars";
    default: return "";
  }
}

constexpr ResultItem::Kind kSaved[] = {ResultItem::Kind::Image, ResultItem::Kind::Curve, ResultItem::Kind::Table,
                                       ResultItem::Kind::Bars};

QStringList keys_of(const ResultStore& store) {
  QStringList keys;
  QSet<QString> seen;
  for (const ResultSet& s : store.sets()) {
    for (const ResultItem& i : s.items) {
      if (!i.key.isEmpty() && !seen.contains(i.key)) {
        seen.insert(i.key);
        keys << i.key;
      }
    }
  }
  return keys;
}

}  // namespace

QJsonArray saved_results(const ResultStore& store) {
  QJsonArray out;
  for (const QString& key : keys_of(store)) {
    for (const ResultItem::Kind kind : kSaved) {
      for (const ResultItem* i : store.itemsWithKey(key, kind)) {
        QJsonObject o{{"key", i->key}, {"name", i->name}, {"kind", kind_name(kind)}};
        if (!i->stamp.isEmpty()) o["stamp"] = i->stamp;
        if (kind == ResultItem::Kind::Image && i->image) {
          o["image"] = image_json(*i->image);
        } else if (kind == ResultItem::Kind::Curve && i->curve) {
          o["curve"] = QJsonObject{{"x", encode(i->curve->x)},
                                   {"y", encode(i->curve->y)},
                                   {"x_label", i->curve->x_label},
                                   {"y_label", i->curve->y_label}};
        } else if (kind == ResultItem::Kind::Table && i->table) {
          QJsonArray rows;
          for (const QStringList& r : i->table->rows) rows.append(QJsonArray::fromStringList(r));
          o["table"] = QJsonObject{{"columns", QJsonArray::fromStringList(i->table->columns)}, {"rows", rows}};
        } else if (kind == ResultItem::Kind::Bars && i->bars) {
          o["bars"] = QJsonObject{{"labels", QJsonArray::fromStringList(i->bars->labels)},
                                  {"values", encode(i->bars->values)},
                                  {"y_label", i->bars->y_label}};
        } else {
          continue;
        }
        out.append(o);
      }
    }
  }
  return out;
}

int restore_results(ResultStore& store, const QJsonArray& saved) {
  if (saved.isEmpty()) return 0;
  ResultId set = 0;
  int restored = 0;
  for (const QJsonValue& v : saved) {
    const QJsonObject o = v.toObject();
    const QString kind = o["kind"].toString(), key = o["key"].toString(), name = o["name"].toString();
    if (key.isEmpty()) continue;
    if (set == 0) set = store.createSet(QStringLiteral("Saved results"), QStringLiteral("document"));
    ResultId id = 0;
    if (kind == QLatin1String("image")) {
      Image im;
      if (!image_from(o["image"].toObject(), im)) continue;
      id = store.addImage(set, name, std::move(im), key);
    } else if (kind == QLatin1String("curve")) {
      const QJsonObject c = o["curve"].toObject();
      Curve curve;
      if (!decode(c["x"], curve.x) || !decode(c["y"], curve.y) || curve.x.size() != curve.y.size()) continue;
      curve.x_label = c["x_label"].toString();
      curve.y_label = c["y_label"].toString();
      id = store.addCurve(set, name, std::move(curve), key);
    } else if (kind == QLatin1String("table")) {
      const QJsonObject t = o["table"].toObject();
      Table table;
      for (const QJsonValue& c : t["columns"].toArray()) table.columns << c.toString();
      bool ok = true;
      for (const QJsonValue& r : t["rows"].toArray()) {
        QStringList row;
        for (const QJsonValue& c : r.toArray()) row << c.toString();
        ok = ok && row.size() == table.columns.size();
        table.rows.push_back(row);
      }
      if (!ok) continue;
      id = store.addTable(set, name, std::move(table), key);
    } else if (kind == QLatin1String("bars")) {
      const QJsonObject b = o["bars"].toObject();
      Bars bars;
      for (const QJsonValue& l : b["labels"].toArray()) bars.labels << l.toString();
      if (!decode(b["values"], bars.values) || bars.values.size() != static_cast<std::size_t>(bars.labels.size())) continue;
      bars.y_label = b["y_label"].toString();
      id = store.addBars(set, name, std::move(bars), key);
    } else {
      continue;
    }
    store.setStamp(id, o["stamp"].toString());
    ++restored;
  }
  return restored;
}

QJsonObject result_stamps(const ResultStore& store) {
  QJsonObject out;
  for (const QString& key : keys_of(store)) {
    for (const ResultItem::Kind kind : kSaved) {
      const auto items = store.itemsWithKey(key, kind);
      if (!items.empty() && !items.front()->stamp.isEmpty()) {
        out.insert(key, items.front()->stamp);
        break;
      }
    }
  }
  return out;
}

}  // namespace nfcad::results
