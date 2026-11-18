// Saving results to files, see result_export.hpp.
#include "results/result_export.hpp"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QObject>
#include <QRegularExpression>
#include <QSaveFile>
#include <QSet>
#include <algorithm>
#include <cmath>
#include <limits>

#include "results/colormap.hpp"

namespace nfcad::results {

namespace {

QString number(double v) {
  if (std::isnan(v)) return QStringLiteral("nan");
  if (std::isinf(v)) return v > 0 ? QStringLiteral("inf") : QStringLiteral("-inf");
  return QString::number(v, 'g', 9);
}

/// A CSV cell: quoted if it holds a separator, a quote or a line break.
QString cell(const QString& text) {
  if (!text.contains(QLatin1Char(',')) && !text.contains(QLatin1Char('"')) && !text.contains(QLatin1Char('\n')) &&
      !text.contains(QLatin1Char('\r'))) {
    return text;
  }
  QString quoted = text;
  quoted.replace(QLatin1String("\""), QLatin1String("\"\""));
  return QLatin1Char('"') + quoted + QLatin1Char('"');
}

QString row(const QStringList& cells) {
  QStringList out;
  out.reserve(cells.size());
  for (const QString& c : cells) out << cell(c);
  return out.join(QLatin1Char(',')) + QLatin1Char('\n');
}

/// A comment line (line breaks of the text become spaces).
QString comment(const QString& text) {
  QString t = text;
  t.replace(QLatin1Char('\n'), QLatin1Char(' '));
  t.replace(QLatin1Char('\r'), QLatin1Char(' '));
  return QStringLiteral("# ") + t + QLatin1Char('\n');
}

template <typename Value>
void grid(QString& out, int width, int height, Value value) {
  for (int j = 0; j < height; ++j) {
    QStringList line;
    line.reserve(width);
    for (int i = 0; i < width; ++i) line << number(value(i, j));
    out += line.join(QLatin1Char(',')) + QLatin1Char('\n');
  }
}

QString image_csv(const QString& name, const Image& im) {
  QString out = comment(name);
  if (!im.description.isEmpty()) out += comment(im.description);
  if (!im.unit.isEmpty()) out += comment(QObject::tr("unit: %1").arg(im.unit));
  out += comment(QStringLiteral("%1 x %2 values; x (%3) from %4 to %5, y (%6) from %7 to %8 (cell edges)")
                     .arg(im.width)
                     .arg(im.height)
                     .arg(im.x_label.isEmpty() ? QStringLiteral("x") : im.x_label, number(im.x0), number(im.x1),
                          im.y_label.isEmpty() ? QStringLiteral("y") : im.y_label, number(im.y0), number(im.y1)));
  out += comment(QStringLiteral("one line per row from y0 upwards, one column per x"));
  if (static_cast<std::size_t>(im.width) * static_cast<std::size_t>(im.height) > im.values.size()) return out;
  grid(out, im.width, im.height, [&](int i, int j) { return static_cast<double>(im.value(i, j)); });
  return out;
}

QString field_csv(const QString& name, const FaceField& f) {
  QString out = comment(name);
  if (!f.unit.isEmpty()) out += comment(QObject::tr("unit: %1").arg(f.unit));
  out += comment(QStringLiteral("entity %1, face %2: %3 x %4 values over the face parameters u, v in [0, 1]")
                     .arg(f.entity)
                     .arg(f.face)
                     .arg(f.width)
                     .arg(f.height));
  out += comment(QStringLiteral("one line per v from 0 upwards, one column per u"));
  const auto n = static_cast<std::size_t>(std::max(f.width, 0)) * static_cast<std::size_t>(std::max(f.height, 0));
  if (f.values.size() < n) return out;  // a picture without values: only the PNG
  grid(out, f.width, f.height, [&](int i, int j) {
    return static_cast<double>(f.values[static_cast<std::size_t>(j) * static_cast<std::size_t>(f.width) +
                                        static_cast<std::size_t>(i)]);
  });
  return out;
}

QString lines_csv(const LineSet& l) {
  const bool values = !l.values.empty() && l.values.size() == l.pointCount();
  QString out = row(values ? QStringList{QStringLiteral("polyline"), QStringLiteral("x"), QStringLiteral("y"),
                                         QStringLiteral("z"),
                                         l.unit.isEmpty() ? QStringLiteral("value") : QStringLiteral("value (%1)").arg(l.unit)}
                           : QStringList{QStringLiteral("polyline"), QStringLiteral("x"), QStringLiteral("y"),
                                         QStringLiteral("z")});
  for (std::size_t k = 0; k < l.polylineCount(); ++k) {
    for (std::uint32_t p = l.starts[k]; p < l.starts[k + 1] && 3 * p + 2 < l.points.size(); ++p) {
      out += QString::number(k) + QLatin1Char(',') + number(l.points[3 * p]) + QLatin1Char(',') +
             number(l.points[3 * p + 1]) + QLatin1Char(',') + number(l.points[3 * p + 2]);
      if (values) out += QLatin1Char(',') + number(l.values[p]);
      out += QLatin1Char('\n');
    }
  }
  return out;
}

bool write_file(const QString& path, const QByteArray& bytes, QString* error) {
  QSaveFile f(path);
  if (!f.open(QIODevice::WriteOnly) || f.write(bytes) != bytes.size() || !f.commit()) {
    if (error != nullptr) *error = QObject::tr("cannot write %1: %2").arg(QDir::toNativeSeparators(path), f.errorString());
    return false;
  }
  return true;
}

}  // namespace

QImage image_pixels(const Image& im, bool log, double* lo, double* hi) {
  if (im.width <= 0 || im.height <= 0) return {};
  const auto n = static_cast<std::size_t>(im.width) * static_cast<std::size_t>(im.height);
  QImage out(im.width, im.height, QImage::Format_RGB32);
  if (im.coloured() && im.rgb.size() >= 3 * n) {  // the colours as they are
    for (int j = 0; j < im.height; ++j) {
      auto* line = reinterpret_cast<QRgb*>(out.scanLine(im.height - 1 - j));  // row 0 = y0 at the bottom
      const unsigned char* c = im.rgb.data() + 3 * static_cast<std::size_t>(j) * static_cast<std::size_t>(im.width);
      for (int i = 0; i < im.width; ++i, c += 3) line[i] = qRgb(c[0], c[1], c[2]);
    }
    return out;
  }
  if (im.values.size() < n) return {};
  const Range r = im.effectiveRange();
  double a = r.min;
  double b = r.max;
  if (log) {  // 4 decades below the peak, or the smallest positive value
    double positive = std::numeric_limits<double>::max();
    for (float v : im.values) {
      if (v > 0) positive = std::min(positive, static_cast<double>(v));
    }
    b = std::log10(std::max(r.max, 1e-300));
    a = std::max(b - 4.0, std::log10(std::min(positive, std::max(r.max, 1e-300))));
    if (!(b > a)) a = b - 1.0;
  }
  for (int j = 0; j < im.height; ++j) {
    auto* line = reinterpret_cast<QRgb*>(out.scanLine(im.height - 1 - j));
    for (int i = 0; i < im.width; ++i) {
      double v = im.value(i, j);
      if (log) v = v > 0 ? std::log10(v) : a;
      const double t = std::isfinite(v) ? std::clamp((v - a) / (b - a), 0.0, 1.0) : 0.0;
      line[i] = colormap_color(im.colormap, t).rgb();
    }
  }
  if (lo != nullptr) *lo = a;
  if (hi != nullptr) *hi = b;
  return out;
}

QImage field_pixels(const FaceField& f) {
  if (f.width <= 0 || f.height <= 0) return {};
  const std::vector<unsigned char> rgba = f.texture();
  QImage out(f.width, f.height, QImage::Format_RGBA8888);
  for (int j = 0; j < f.height; ++j) {  // v upwards: row 0 at the bottom
    const auto* src = rgba.data() + 4 * static_cast<std::size_t>(j) * static_cast<std::size_t>(f.width);
    std::copy(src, src + 4 * static_cast<std::ptrdiff_t>(f.width), out.scanLine(f.height - 1 - j));
  }
  return out;
}

QString to_csv(const ResultItem& item) {
  switch (item.kind) {
    case ResultItem::Kind::Image: return item.image ? image_csv(item.name, *item.image) : QString();
    case ResultItem::Kind::Field: return item.field ? field_csv(item.name, *item.field) : QString();
    case ResultItem::Kind::Lines: return item.lines ? lines_csv(*item.lines) : QString();
    case ResultItem::Kind::Curve: {
      if (!item.curve) return {};
      const Curve& c = *item.curve;
      QString out = row({c.x_label.isEmpty() ? QStringLiteral("x") : c.x_label,
                         c.y_label.isEmpty() ? QStringLiteral("y") : c.y_label});
      for (std::size_t k = 0; k < std::min(c.x.size(), c.y.size()); ++k) {
        out += number(c.x[k]) + QLatin1Char(',') + number(c.y[k]) + QLatin1Char('\n');
      }
      return out;
    }
    case ResultItem::Kind::Table: {
      if (!item.table) return {};
      QString out = row(item.table->columns);
      for (const QStringList& r : item.table->rows) out += row(r);
      return out;
    }
    case ResultItem::Kind::Bars: {
      if (!item.bars) return {};
      const Bars& b = *item.bars;
      QString out = row({QStringLiteral("label"), b.y_label.isEmpty() ? QStringLiteral("value") : b.y_label});
      for (qsizetype k = 0; k < b.labels.size() && static_cast<std::size_t>(k) < b.values.size(); ++k) {
        out += cell(b.labels[k]) + QLatin1Char(',') + number(b.values[static_cast<std::size_t>(k)]) + QLatin1Char('\n');
      }
      return out;
    }
  }
  return {};
}

QStringList save_formats(const ResultItem& item) {
  if (item.kind == ResultItem::Kind::Field && item.field && item.field->values.empty()) {
    return {QStringLiteral("png")};  // a picture on the face, no numbers
  }
  if (item.kind == ResultItem::Kind::Image || item.kind == ResultItem::Kind::Field) {
    return {QStringLiteral("png"), QStringLiteral("csv")};
  }
  return {QStringLiteral("csv")};
}

bool save_item(const ResultItem& item, const QString& path, QString* error, bool log) {
  const QString suffix = QFileInfo(path).suffix().toLower();
  if (!save_formats(item).contains(suffix)) {
    if (error != nullptr) {
      *error = QObject::tr("%1 cannot be saved as .%2 (possible: %3)")
                   .arg(item.name, suffix, save_formats(item).join(QStringLiteral(", ")));
    }
    return false;
  }
  if (suffix == QLatin1String("png")) {
    const QImage pixels = item.kind == ResultItem::Kind::Image ? (item.image ? image_pixels(*item.image, log) : QImage())
                                                               : (item.field ? field_pixels(*item.field) : QImage());
    if (pixels.isNull()) {
      if (error != nullptr) *error = QObject::tr("%1 has no pixels").arg(item.name);
      return false;
    }
    QSaveFile f(path);
    if (!f.open(QIODevice::WriteOnly) || !pixels.save(&f, "PNG") || !f.commit()) {
      if (error != nullptr) *error = QObject::tr("cannot write %1: %2").arg(QDir::toNativeSeparators(path), f.errorString());
      return false;
    }
    return true;
  }
  return write_file(path, to_csv(item).toUtf8(), error);
}

QString file_name_for(const QString& name, const QString& suffix) {
  static const QRegularExpression bad(QStringLiteral(R"([<>:"/\\|?*\x00-\x1f])"));
  QString base = name;
  base.replace(bad, QStringLiteral("_"));
  base = base.trimmed();
  while (base.endsWith(QLatin1Char('.'))) base.chop(1);  // Windows drops trailing dots
  if (base.isEmpty()) base = QStringLiteral("result");
  return base + QLatin1Char('.') + suffix;
}

QStringList save_set(const ResultSet& set, const QString& dir, QString* error) {
  QStringList written;
  if (!QDir().mkpath(dir)) {
    if (error != nullptr) *error = QObject::tr("cannot create the folder %1").arg(QDir::toNativeSeparators(dir));
    return {};
  }
  QSet<QString> used;
  for (const ResultItem& item : set.items) {
    // two items of the same name: "name (2)"
    const QString stem = file_name_for(item.name, QStringLiteral("x")).chopped(2);
    QString base = stem;
    for (int k = 2; used.contains(base.toLower()); ++k) base = stem + QStringLiteral(" (%1)").arg(k);
    used.insert(base.toLower());
    for (const QString& suffix : save_formats(item)) {
      const QString path = QDir(dir).filePath(base + QLatin1Char('.') + suffix);
      if (!save_item(item, path, error)) return {};
      written << path;
    }
  }
  return written;
}

}  // namespace nfcad::results
