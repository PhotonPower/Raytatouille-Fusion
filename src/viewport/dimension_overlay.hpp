#pragma once

#include <QWidget>
#include <optional>
#include <vector>

#include "document/entity.hpp"

namespace nfcad::render {
class Scene;
}
namespace nfcad::document {
class Selection;
}

namespace nfcad::viewport {

class Camera;

/// Arrows and texts of the dimensions (document/dimension.hpp) drawn over a viewport, in the
/// colour of their entity (selected / hovered: highlighted); their polylines are drawn by the
/// scene renderer like any curve. Hidden entities are left out. A click on a text picks the
/// dimension (textAt).
class DimensionOverlay : public QWidget {
  Q_OBJECT
 public:
  DimensionOverlay(QWidget* parent, const Camera* camera);
  void setScene(const render::Scene* scene) { scene_ = scene; }
  void setSelection(const document::Selection* selection) { selection_ = selection; }
  /// The selectable dimension whose text lies under `px` (as last painted).
  [[nodiscard]] std::optional<document::EntityId> textAt(const QPointF& px) const;

 protected:
  void paintEvent(QPaintEvent* event) override;

 private:
  struct Label {
    document::EntityId id;
    QPolygonF box;
  };
  const Camera* camera_;
  const render::Scene* scene_ = nullptr;
  const document::Selection* selection_ = nullptr;
  std::vector<Label> labels_;
};

}  // namespace nfcad::viewport
