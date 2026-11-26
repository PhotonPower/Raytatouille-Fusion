#pragma once

#include <QPointF>
#include <QRectF>
#include <optional>
#include <vector>

#include "document/selection.hpp"
#include "results/result_types.hpp"
#include "tessellation/display_mesh.hpp"
#include "viewport/camera.hpp"

namespace nfcad::pick {

/// A pickable entity: its display mesh (with pick index).
struct Target {
  document::EntityId id = 0;
  const tessellation::DisplayMesh* mesh = nullptr;
  document::GeometryPtr geometry;  ///< exact geometry (snap refinement)
  /// Control points shown as grips (a curve with PointsOn); null or empty: none.
  const std::vector<QVector3D>* grips = nullptr;
};

struct Query {
  QPointF cursor_px;
  float radius_px = 6.0F;    ///< tolerance for curves, edges and points
  bool faces = true;         ///< faces are pickable (surfaces / shaded mode)
  bool isocurves = false;    ///< iso-curves select their face (wireframe mode)
  bool sub_elements = false; ///< report faces / edges / vertices (else whole entities)
};

struct Hit {
  document::SelectionItem item;  ///< sub is set only if Query::sub_elements
  QVector3D point;               ///< world position of the hit
  float depth = 0.0F;            ///< distance along the pick ray
  float distance_px = 0.0F;      ///< screen distance to the cursor (0 for face hits)
  enum class Kind { Point, Curve, Face } kind = Kind::Face;
};

/// Best object under the cursor (docs/ui-concept.md, "Selection"): grips (shown control points,
/// reported as SubElement::Kind::ControlPoint and never hidden by faces) before points, points
/// before curves and edges before faces; within a kind the smallest screen distance, then the smallest depth.
/// Curves and edges hidden behind a face (in a mode with faces) are not picked.
[[nodiscard]] std::optional<Hit> pick(const std::vector<Target>& targets,
                                      const viewport::Camera& camera, const Query& query);

/// Closest face under the cursor (ray hit), with the face index if `sub_elements`.
[[nodiscard]] std::optional<Hit> pick_face(const std::vector<Target>& targets,
                                           const viewport::Camera& camera, const QPointF& cursor_px,
                                           bool sub_elements = false);

/// World length of one pixel at the farthest corner of a box (conservative pick radius).
[[nodiscard]] float farthest_world_per_pixel(const viewport::Camera& camera,
                                             const tessellation::Box3& box);

/// A result drawing to pick as a whole: the line items of a run (results::ResultItem with
/// lines; drawn where its placement puts them).
struct LineTarget {
  std::uint64_t id = 0;  ///< the run
  const results::ResultItem* item = nullptr;
};

struct LineHit {
  std::uint64_t id = 0;       ///< the run
  float distance_px = 0.0F;   ///< screen distance to the cursor
  float depth = 0.0F;         ///< distance along the pick ray of the closest point
  bool on_top = true;         ///< drawn over the model (not hidden by faces)
};

/// The result drawing with a polyline segment closest to the cursor within `radius_px` (lost
/// rays end at their NaN point); ties: the smaller depth.
[[nodiscard]] std::optional<LineHit> pick_lines(const std::vector<LineTarget>& targets,
                                                const viewport::Camera& camera, const QPointF& cursor_px,
                                                float radius_px = 6.0F);

/// Whether a result drawing hit wins over the entity hit at the same cursor: over a face if the
/// drawing is on top or in front of it, over a curve or point if it is closer on the screen.
[[nodiscard]] bool line_hit_wins(const LineHit& line, const std::optional<Hit>& entity);

/// Window (all display geometry inside the rectangle) or crossing selection (any part inside
/// or crossing it). Rectangle in screen pixels.
[[nodiscard]] std::vector<document::EntityId> pick_rect(const std::vector<Target>& targets,
                                                        const viewport::Camera& camera,
                                                        const QRectF& rect, bool crossing);

/// The grips (shown control points) inside the rectangle, as control-point selection items.
[[nodiscard]] std::vector<document::SelectionItem> pick_rect_grips(const std::vector<Target>& targets,
                                                                   const viewport::Camera& camera,
                                                                   const QRectF& rect);

}  // namespace nfcad::pick
