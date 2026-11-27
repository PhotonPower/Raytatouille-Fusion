#include "viewport/dimension_overlay.hpp"

#include <QPainter>
#include <QPainterPath>
#include <QTransform>
#include <cmath>

#include "document/selection.hpp"
#include "render/scene.hpp"
#include "render/scene_renderer.hpp"
#include "viewport/camera.hpp"

namespace nfcad::viewport {

namespace {

constexpr double kArrowLength = 11.0;  // px
constexpr double kArrowHalfWidth = 3.5;
constexpr double kTextGap = 4.0;

QVector3D q(const nf::Vec3& v) { return {static_cast<float>(v.x), static_cast<float>(v.y), static_cast<float>(v.z)}; }

QPointF unit(const QPointF& d) {
  const double l = std::hypot(d.x(), d.y());
  return l > 1e-9 ? d / l : QPointF{};
}

}  // namespace

DimensionOverlay::DimensionOverlay(QWidget* parent, const Camera* camera) : QWidget(parent), camera_(camera) {
  setAttribute(Qt::WA_TransparentForMouseEvents);
  setAttribute(Qt::WA_NoSystemBackground);
}

std::optional<document::EntityId> DimensionOverlay::textAt(const QPointF& px) const {
  for (auto it = labels_.rbegin(); it != labels_.rend(); ++it) {
    if (it->box.containsPoint(px, Qt::OddEvenFill)) return it->id;
  }
  return std::nullopt;
}

void DimensionOverlay::paintEvent(QPaintEvent* /*event*/) {
  labels_.clear();
  if (scene_ == nullptr || camera_ == nullptr) return;
  QPainter p(this);
  p.setRenderHint(QPainter::Antialiasing);
  QFont font = p.font();
  font.setPointSizeF(font.pointSizeF() * 1.05);
  p.setFont(font);
  const QFontMetricsF fm(font);
  const auto hovered = selection_ != nullptr ? selection_->hovered() : std::nullopt;

  for (const auto& [id, item] : scene_->items()) {
    if (!item.visible || !item.dimension) continue;
    const document::DimensionView& d = *item.dimension;
    if (d.normal) {  // seen edge-on: only the line
      const QVector3D f = camera_->forward();
      if (std::abs(f.x() * d.normal->x + f.y() * d.normal->y + f.z() * d.normal->z) < 0.15) continue;
    }
    QColor color = item.color;
    if (selection_ != nullptr && selection_->isSelected(id)) {
      color = render::kSelectedColor;
    } else if (hovered && hovered->entity == id && hovered->sub.kind == document::SubElement::Kind::None) {
      color = render::kHoverColor;
    }
    p.setPen(Qt::NoPen);
    p.setBrush(color);
    for (const document::DimensionArrow& a : d.arrows) {
      const auto tip = camera_->project(q(a.tip));
      const auto from = camera_->project(q(a.from));
      if (!tip || !from) continue;
      const QPointF dir = unit(*tip - *from);
      if (dir.isNull()) continue;
      const QPointF perp(-dir.y(), dir.x());
      const QPointF base = *tip - kArrowLength * dir;
      p.drawPolygon(QPolygonF{{*tip, base + kArrowHalfWidth * perp, base - kArrowHalfWidth * perp}});
    }
    if (d.text.isEmpty()) continue;
    const auto at = camera_->project(q(d.text_at));
    const auto from = camera_->project(q(d.text_from));
    if (!at) continue;
    QPointF dir = from ? unit(*at - *from) : QPointF{};
    const double w = fm.horizontalAdvance(d.text);
    const double h = fm.height();
    QTransform t;
    QRectF box;
    if (d.on_line) {
      // centred above the line, reading from left to right (vertical lines: bottom to top)
      if (dir.isNull()) dir = {1, 0};
      if (dir.x() < -1e-9 || (std::abs(dir.x()) <= 1e-9 && dir.y() > 0)) dir = -dir;
      t.translate(at->x(), at->y());
      t.rotateRadians(std::atan2(dir.y(), dir.x()));
      box = QRectF(-0.5 * w, -h - kTextGap, w, h);
    } else {
      // beyond the end, on the side the line points to
      t.translate(at->x(), at->y());
      box = dir.x() >= 0 ? QRectF(kTextGap, -0.5 * h, w, h) : QRectF(-kTextGap - w, -0.5 * h, w, h);
    }
    p.save();
    p.setTransform(t, true);
    p.setPen(color);
    p.drawText(box, Qt::AlignCenter, d.text);
    p.restore();
    if (!item.locked) labels_.push_back({id, t.map(QPolygonF(box))});
  }
}

}  // namespace nfcad::viewport
