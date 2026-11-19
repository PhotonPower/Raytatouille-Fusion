#pragma once

#include <QColor>
#include <QImage>
#include <QJsonObject>
#include <QList>
#include <QPointF>
#include <QRectF>
#include <QStringList>
#include <QWidget>
#include <optional>
#include <vector>

class QPainter;
class QPalette;

namespace nfcad::ui {

/// A 2-D vector drawing of the sub-model of a block of the node workflow – the overview tab of
/// its parameter dialog (docs/plugin-api.md, "Block previews"). A plugin's `preview_block`
/// returns it as JSON, format "nfcad-drawing" version 1: polygons (filled by material),
/// polylines, texts, dimensions and arrows in drawing coordinates (`unit`, y up). CAD draws it
/// scaled to the tab, with the colours of the palette (light or dark); the plugin needs no
/// plotting library.
struct Drawing {
  enum class Kind { Polygon, Polyline, Text, Dimension, Arrow };
  struct Item {
    Kind kind = Kind::Polyline;
    /// polygon, polyline: the vertices; dimension, arrow: from, to; text: the anchor
    QList<QPointF> points;
    QString text;      ///< text; label of a dimension, arrow or polygon
    QString material;  ///< polygon: fills with the material's colour, listed in the legend
    QString role;      ///< colour and pen by meaning (see kRoles)
    QColor color;      ///< explicit stroke / text colour (invalid: by role)
    QColor fill;       ///< explicit fill of a polygon (invalid: by material)
    bool dashed = false;
    bool hatched = false;    ///< polygon: hatched (a half-space, a part not drawn exactly)
    double width = 0.0;      ///< pen width in pixels (0: by role)
    QString align;           ///< text: "left", "center" (default), "right"
    QString valign;          ///< text: "top", "middle" (default), "bottom"
  };
  struct Material {
    QString name;
    QString label;  ///< legend text (default: the name)
    QColor fill;    ///< invalid: a colour from the name
  };

  QString title;
  QStringList notes;     ///< lines under the drawing
  QString unit;          ///< of all coordinates ("mm", "µm"); shown at the axes
  QString x_axis = QStringLiteral("x");
  QString y_axis = QStringLiteral("y");
  bool equal_aspect = true;  ///< one scale for both axes ("aspect": "equal"), else "fit"
  bool axes = true;          ///< ticks and axis names
  std::vector<Item> items;
  std::vector<Material> materials;  ///< legend, in this order; polygons add theirs

  /// The box around all items (drawing coordinates); empty without items.
  [[nodiscard]] QRectF bounds() const;
  /// The fill of a material: its legend entry's, else a colour from its name.
  [[nodiscard]] QColor materialFill(const QString& name, const QPalette& palette) const;
};

/// The roles a plugin may give lines, arrows and texts: "outline" (default; the text colour),
/// "surface", "axis" (dash-dot), "ray", "light", "stop", "detector", "dimension", "guide"
/// (dotted), "note" (muted), "error".
inline constexpr const char* kRoles[] = {"outline", "surface", "axis",      "ray",   "light", "stop",
                                         "detector", "dimension", "guide", "note", "error"};

/// Limits a drawing must keep (a faulty plugin must not stall the dialog).
inline constexpr int kMaxDrawingItems = 20000;
inline constexpr int kMaxDrawingPoints = 400000;

/// Reads a drawing. Returns nullopt with the reasons in `problems` if `json` is none (wrong
/// format, no items array, a malformed item, numbers that are not finite, too large). Unknown
/// item types are skipped with a note in `problems` – a newer plugin still draws.
[[nodiscard]] std::optional<Drawing> parse_drawing(const QJsonObject& json, QStringList* problems = nullptr);

/// The drawing of a block without one from a plugin: the block as a box with its light ports
/// (left: where light comes in first, right: out) and data sockets, its type, description and
/// first parameters; `reason` (why there is no plugin drawing) as a note. JSON as parse_drawing
/// reads it.
[[nodiscard]] QJsonObject schematic_drawing(const QJsonObject& node, const QJsonObject& type,
                                            const QString& reason = {});

/// Paints the drawing into `rect` (title, plot with axes, legend, notes) with `palette`.
void paint_drawing(QPainter& painter, const QRectF& rect, const Drawing& drawing, const QPalette& palette,
                   const QString& error = {});

/// The overview tab of a block's parameter dialog: a drawing, "computing…" while a new one is on
/// its way (the old one stays visible), and an error under the title. Context menu: copy the
/// image, save it as PNG.
class DrawingView : public QWidget {
  Q_OBJECT
 public:
  explicit DrawingView(QWidget* parent = nullptr);
  [[nodiscard]] QSize sizeHint() const override { return {520, 380}; }
  [[nodiscard]] QSize minimumSizeHint() const override { return {240, 180}; }

  /// Shows `drawing`; `error` (e.g. why the plugin could not draw) under its title.
  void setDrawing(const Drawing& drawing, const QString& error = {});
  /// A new drawing is being computed: `text` over the old one (or alone).
  void setBusy(const QString& text);
  [[nodiscard]] bool busy() const { return !busy_.isEmpty(); }
  [[nodiscard]] const std::optional<Drawing>& drawing() const { return drawing_; }
  [[nodiscard]] const QString& error() const { return error_; }
  /// The drawing as an image of `size` (logical pixels; `scale` device pixels per pixel) with
  /// the palette of the view.
  [[nodiscard]] QImage render(const QSize& size, double scale = 1.0) const;

 protected:
  void paintEvent(QPaintEvent* event) override;
  void contextMenuEvent(QContextMenuEvent* event) override;

 private:
  std::optional<Drawing> drawing_;
  QString error_;
  QString busy_;
};

}  // namespace nfcad::ui
