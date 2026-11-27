#pragma once

#include <QString>
#include <functional>
#include <optional>
#include <vector>

#include <nurbforge/geometry/transform.hpp>

#include "document/entity.hpp"
#include "document/selection.hpp"

namespace nfcad::kernel {

/// Geometry moved / rotated / scaled / mirrored (exact; trim loops stay in parameter space).
[[nodiscard]] document::Geometry transformed(const document::Geometry& g, const nf::Transform& t);

/// A geometry deformed by a point map (Bend, Twist, Flow …). Affine maps (`refine` false) map the
/// control points – exact. Curved maps: a curve's points are mapped and interpolated again at
/// their parameters (cubic, at least 4·`spans` points); a surface is raised to degree 3 and
/// refined to 2·`spans` spans per direction, and its control points are mapped (the parameters,
/// and so its trims, stay). Trimmed faces keep
/// their trims (parameters); the faces of a shell are deformed one by one and sewn again within
/// 1e-4 of the model's size. Weights stay.
[[nodiscard]] document::Geometry morphed(const document::Geometry& g, const std::function<nf::Vec3(const nf::Vec3&)>& map,
                                         bool refine = true, std::size_t spans = 16);

/// Light wireframe of a geometry for rubber-band previews: curves and shell edges sampled, at
/// most `max_points` points in total.
[[nodiscard]] std::vector<std::vector<nf::Vec3>> wire(const document::Geometry& g,
                                                      std::size_t max_points = 4000);

enum class BooleanOp { Union, Intersection, Difference };

/// Boolean of closed shells: Union / Intersection fold over all inputs, Difference subtracts
/// the others from the first. Throws std::runtime_error with a readable message.
[[nodiscard]] nf::Shell boolean(const std::vector<nf::Shell>& shells, BooleanOp op);

/// A picked part: an edge of a shell as its curve, a face as its trimmed surface, a control point
/// of a curve as a point; nothing for
/// other geometry or an index out of range.
[[nodiscard]] std::optional<document::Geometry> part_of(const document::Geometry& g,
                                                        const document::SubElement& sub);

/// The curve with its control points `indices` transformed (grips moved); indices out of range
/// are ignored.
[[nodiscard]] nf::NurbsCurve with_control_points_moved(const nf::NurbsCurve& c, const std::vector<int>& indices,
                                                       const nf::Transform& t);
/// The same for any geometry with control points (curves, surfaces – a face keeps its trims);
/// nullopt for others.
[[nodiscard]] std::optional<document::Geometry> with_control_points_moved(const document::Geometry& g,
                                                                          const std::vector<int>& indices,
                                                                          const nf::Transform& t);

/// Faces of a surface-like geometry (surface, trimmed surface, shell); empty for others.
[[nodiscard]] std::vector<nf::TrimmedSurface> faces_of(const document::Geometry& g);

/// Closes the planar boundary loops (free edges) of the faces with trimmed planar caps and
/// sews everything into one shell (e.g. an extruded closed profile becomes a solid). Throws
/// std::runtime_error if there is no planar open loop.
[[nodiscard]] nf::Shell cap_planar_holes(const std::vector<nf::TrimmedSurface>& faces,
                                         double tolerance = 1e-6);

/// Planar faces bounded by closed curves in one plane: a curve inside an even number of others is
/// an outer boundary, one inside an odd number a hole of the curve directly around it. Throws
/// std::runtime_error for open or non-planar curves or curves in different planes.
[[nodiscard]] std::vector<nf::TrimmedSurface> planar_faces(const std::vector<nf::NurbsCurve>& curves);

/// Chains curves end to start (reversing where needed, any input order) and joins them.
/// Throws std::runtime_error if they do not form one chain.
[[nodiscard]] nf::NurbsCurve join_chain(std::vector<nf::NurbsCurve> curves, double tolerance = 1e-6);

/// Writes the shells of `entities` to a STEP file (AP214, mm). Returns the number of shells
/// written; non-shell entities are skipped. Throws on I/O errors.
std::size_t export_step(const QString& path, const std::vector<const document::Entity*>& entities);

}  // namespace nfcad::kernel
