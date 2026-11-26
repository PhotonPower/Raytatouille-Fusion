#pragma once

#include <QColor>
#include <QVector3D>
#include <QObject>
#include <unordered_map>

#include "document/document.hpp"
#include "document/selection.hpp"
#include "pick/picking.hpp"
#include "tessellation/tessellation_service.hpp"

namespace nfcad::render {

/// Display model shared by all viewports: per entity its display mesh, colour and visibility.
/// Follows the document and requests tessellations; contains no GPU resources
/// (each viewport uploads what it needs, render/scene_renderer).
class Scene : public QObject {
  Q_OBJECT
 public:
  struct Item {
    tessellation::DisplayMeshPtr mesh;  ///< null until the tessellation is ready
    document::GeometryPtr geometry;     ///< to detect geometry changes
    QColor color;
    bool visible = true;
    bool locked = false;  ///< on a locked layer: drawn and snapped to, but not selectable
    /// Control points of a curve whose points are shown (PointsOn), in order; else empty.
    std::vector<QVector3D> grips;
  };

  Scene(document::Document* doc, tessellation::TessellationService* service,
        QObject* parent = nullptr);

  [[nodiscard]] const std::unordered_map<document::EntityId, Item>& items() const {
    return items_;
  }
  /// Bounds of all visible, tessellated items (invalid if there are none).
  [[nodiscard]] tessellation::Box3 bounds() const;
  /// Bounds of selected entities and sub-elements (faces, edges, B-rep vertices); invalid if
  /// none of them is visible and tessellated.
  [[nodiscard]] tessellation::Box3 bounds(const std::vector<document::SelectionItem>& items) const;
  /// Visible, tessellated items for snapping (also those on locked layers).
  [[nodiscard]] std::vector<pick::Target> pickTargets() const;
  /// Visible, tessellated items that can be selected (not on a locked layer): hover and selection.
  [[nodiscard]] std::vector<pick::Target> selectableTargets() const;
  /// Number of triangles of all tessellated items.
  [[nodiscard]] std::size_t triangleCount() const;

 signals:
  void changed();

 private:
  void add(document::EntityId id);
  void update(document::EntityId id);
  void remove(document::EntityId id);
  void rebuild();
  void onMeshReady(document::EntityId id, std::uint64_t revision,
                   tessellation::DisplayMeshPtr mesh);

  document::Document* doc_;
  tessellation::TessellationService* service_;
  std::unordered_map<document::EntityId, Item> items_;
};

}  // namespace nfcad::render
