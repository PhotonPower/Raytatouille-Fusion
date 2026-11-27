#pragma once

#include <QColor>
#include <QString>
#include <QVariantMap>
#include <cstdint>
#include <memory>
#include <optional>
#include <variant>

#include <nurbforge/geometry/primitives.hpp>
#include <nurbforge/mesh/triangle_mesh.hpp>
#include <nurbforge/nurbs/curve.hpp>
#include <nurbforge/nurbs/surface.hpp>
#include <nurbforge/topology/shell.hpp>
#include <nurbforge/topology/trimmed_surface.hpp>

namespace nfcad::document {

using EntityId = std::uint64_t;
using LayerId = std::uint32_t;
using GroupId = std::uint32_t;  ///< 0: top level (no group)

/// Layer of a new entity that has none yet: the document puts it on its current layer when it
/// is added (Document::addEntities, apply, insert). Never stored in a document.
inline constexpr LayerId kCurrentLayer = 0xFFFFFFFFu;

/// Geometry of an entity: exact Nurbforge values (immutable, ADR 0003); a triangle mesh is the
/// one approximate kind (the result of mesh-level tools such as Shrink wrap).
using Geometry =
    std::variant<nf::Vec3, nf::NurbsCurve, nf::NurbsSurface, nf::TrimmedSurface, nf::Shell, nf::TriangleMesh>;

/// Shared, immutable geometry: entities, undo commands and tessellation workers share it.
using GeometryPtr = std::shared_ptr<const Geometry>;

enum class GeometryKind { Point, Curve, Surface, TrimmedSurface, Shell, Mesh };

[[nodiscard]] inline GeometryKind kind_of(const Geometry& g) {
  return static_cast<GeometryKind>(g.index());
}

[[nodiscard]] QString kind_name(GeometryKind kind);

struct Entity {
  EntityId id = 0;  ///< assigned by Document; 0 = not yet in a document
  QString name;
  LayerId layer = kCurrentLayer;  ///< kCurrentLayer: the document's current layer when added
  std::optional<QColor> color;  ///< empty: layer colour
  bool visible = true;
  GroupId group = 0;           ///< model tree (docs/plugins.md, P1)
  /// Free key/value data, saved with the document. Plugins use namespaced keys, e.g.
  /// "rtt.role" = "mirror", "sim.inactive" = true (excluded from computations).
  QVariantMap attributes;
  GeometryPtr geometry;
  std::uint64_t revision = 0;  ///< increases with every change of geometry or display attributes
};

[[nodiscard]] Entity make_entity(Geometry geometry, QString name = {});
/// Point entity (for widget code that does not use Nurbforge types).
[[nodiscard]] Entity make_point_entity(double x, double y, double z, QString name = {});

}  // namespace nfcad::document
