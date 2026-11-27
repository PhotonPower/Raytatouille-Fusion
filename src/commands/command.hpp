#pragma once

#include <QString>
#include <QStringList>
#include <memory>
#include <nurbforge/geometry/transform.hpp>
#include <optional>
#include <utility>
#include <vector>

#include "render/display_mode.hpp"
#include "document/document.hpp"
#include "document/entity.hpp"
#include "document/selection.hpp"
#include "snap/snap_types.hpp"

namespace nfcad::commands {

using Point3 = snap::SnapPoint;
using Polyline3 = std::vector<Point3>;

/// Construction plane of the view in which a point was given (orthonormal u, v; n = u × v).
struct PlaneFrame {
  Point3 origin{0, 0, 0};
  Point3 u{1, 0, 0};
  Point3 v{0, 1, 0};
  Point3 n{0, 0, 1};
  // camera of that view (Silhouette, Make2D, Outline)
  Point3 view{0, 0, -1};        ///< viewing direction, from the viewer into the scene (unit)
  Point3 up{0, 1, 0};           ///< screen up (unit, normal to `view`)
  Point3 target{0, 0, 0};       ///< orbit centre
  std::optional<Point3> eye{};  ///< eye point of a perspective view; empty: parallel view
};

/// Selected control points ("grips") of one curve whose points are shown: the entity and the
/// indices of its selected control points.
struct GripSet {
  document::EntityId id = 0;
  document::GeometryPtr geometry;
  std::vector<int> indices;
};

/// Key of the entity attribute that shows a curve's control points (PointsOn / PointsOff).
inline constexpr const char* kPointsOnKey = "nfcad.points_on";

/// An interactive command (docs/commands.md): a state machine that asks for points and numbers,
/// shows a rubber-band preview and produces entities. No widgets – the CommandController in
/// app/ feeds it with clicked / typed input.
class Command {
 public:
  enum class Result {
    Continue,   ///< waiting for more input
    Done,       ///< finished; take the entities / message
    Cancelled,  ///< nothing created
    Rejected,   ///< input not accepted in this state (state unchanged); message(): why
  };

  virtual ~Command() = default;
  [[nodiscard]] virtual QString id() const = 0;
  [[nodiscard]] virtual QString title() const = 0;   ///< undo text, e.g. "Line"
  [[nodiscard]] virtual QString prompt() const = 0;  ///< e.g. "Line: end point"

  virtual Result point(const Point3& p, const PlaneFrame& plane) = 0;
  /// A typed number (radius, number of sides, turns, ...). Rejected: the controller then uses
  /// it as a distance from basePoint() towards the cursor.
  virtual Result number(double /*value*/) { return Result::Rejected; }
  /// Enter / right-click.
  virtual Result finish() { return Result::Cancelled; }
  /// Commands that ask for text (Leader, DimText): while true, a non-empty input line goes to
  /// text() as typed instead of being parsed as a point, number or command.
  [[nodiscard]] virtual bool wantsText() const { return false; }
  virtual Result text(const QString& /*text*/) { return Result::Rejected; }

  /// Rubber band for the cursor position.
  [[nodiscard]] virtual std::vector<Polyline3> preview(const Point3& /*cursor*/,
                                                       const PlaneFrame& /*plane*/) const {
    return {};
  }
  /// Reference for relative input (@dx,dy,dz), ortho and typed distances.
  [[nodiscard]] virtual std::optional<Point3> basePoint() const { return std::nullopt; }
  /// Points of the object being drawn that the cursor may snap to as End (e.g. the vertices of
  /// a polyline in progress: snapping its start closes it). Not yet in the document.
  [[nodiscard]] virtual std::vector<Point3> snapPoints() const { return {}; }

  /// Construction plane of the view the user works in: the active view when the command starts,
  /// then the view under the cursor (kept current by the controller). Typed input that needs a
  /// plane before any point was clicked (e.g. Extrude's distance) uses it.
  void setViewPlane(const PlaneFrame& plane) { view_plane_ = plane; }
  [[nodiscard]] const PlaneFrame& viewPlane() const { return view_plane_; }

  /// Commands on the selection (transforms, Booleans): called once at the start with the
  /// selected entities in selection order. Return false (and set message_) if unsuitable.
  [[nodiscard]] virtual bool usesSelection() const { return false; }
  virtual bool begin(const std::vector<document::Entity>& /*selection*/) { return true; }
  /// True if the command is complete right after begin() (e.g. Booleans).
  [[nodiscard]] virtual bool immediate() const { return false; }
  /// Commands that also take picked parts of objects: a selected edge of a shell arrives in
  /// begin() as a curve entity, a selected face as a trimmed-surface entity (id 0: not in the
  /// document; the parts follow the whole objects, in selection order).
  [[nodiscard]] virtual bool usesSubElements() const { return false; }
  /// Commands that act on selected control points (grips): the controller hands them over with
  /// setGrips() before begin(); begin() may then get no whole entities.
  [[nodiscard]] virtual bool usesGrips() const { return false; }
  void setGrips(std::vector<GripSet> grips) { grips_ = std::move(grips); }
  /// Commands that act on picked edges of solids (fillet / chamfer edges): the controller hands
  /// over the selected edges per shell (GripSet with edge indices) before begin().
  [[nodiscard]] virtual bool usesEdges() const { return false; }
  void setEdges(std::vector<GripSet> edges) { edges_ = std::move(edges); }
  /// Commands that act on picked faces of solids (Extract surface): the selected faces per shell.
  [[nodiscard]] virtual bool usesFaces() const { return false; }
  /// A surface analysis the viewports show once the command is done (Zebra …); nullopt: none.
  [[nodiscard]] virtual std::optional<render::Analysis> viewAnalysis() const { return std::nullopt; }
  /// The analysis is switched off instead if the viewports already show the same kind.
  [[nodiscard]] virtual bool analysisToggles() const { return false; }
  void setFaces(std::vector<GripSet> faces) { picked_faces_ = std::move(faces); }
  /// Commands that read a file (Heightfield: an image): a non-empty file-dialog filter makes the
  /// controller ask for the file before begin() and hand it over with setFile().
  [[nodiscard]] virtual QString fileFilter() const { return {}; }
  void setFile(QString path) { file_ = std::move(path); }
  /// The document, read-only (commands that look beyond the selection, e.g. Points off for all).
  void setDocument(const document::Document* doc) { doc_ = doc; }
  /// The selection the command asks for when it is done (e.g. Select points); empty: unchanged.
  [[nodiscard]] std::optional<std::vector<document::SelectionItem>> takeSelection() {
    return std::exchange(select_, std::nullopt);
  }

  /// Commands that move the selection rigidly (Move, Rotate) also move selected result drawings
  /// (rays, a plugin's camera – docs/plugins.md, "Result drawings in the views"): before begin()
  /// the controller gives them the drawings' polylines (preview; non-empty: there are drawings,
  /// so begin() accepts a selection without entities), and applies takeMotion() to them.
  [[nodiscard]] virtual bool movesDrawings() const { return false; }
  void setDrawingWire(std::vector<std::vector<nf::Vec3>> wire) { drawing_wire_ = std::move(wire); }
  /// The rigid motion applied since the last call (for the selected drawings).
  [[nodiscard]] std::optional<nf::Transform> takeMotion() { return std::exchange(motion_, std::nullopt); }

  /// Entities created since the last call.
  [[nodiscard]] std::vector<document::Entity> takeEntities() { return std::exchange(entities_, {}); }
  /// All changes since the last call: created entities, removed ids, replaced geometry
  /// (the controller applies them as one undo step).
  [[nodiscard]] document::Edit takeEdit() {
    return {std::exchange(entities_, {}), std::exchange(remove_, {}), std::exchange(replace_, {}),
            std::exchange(attributes_, {})};
  }
  /// Result text (e.g. a measured distance); after Rejected: why the input was not accepted
  /// (empty if there is no specific reason).
  [[nodiscard]] QString message() const { return message_; }
  /// message() and clears it (the controller reads the reason of a Rejected input once).
  [[nodiscard]] QString takeMessage() { return std::exchange(message_, {}); }

 protected:
  std::vector<document::Entity> entities_;
  std::vector<document::EntityId> remove_;
  std::vector<std::pair<document::EntityId, document::GeometryPtr>> replace_;
  std::vector<std::pair<document::EntityId, QVariantMap>> attributes_;
  std::vector<GripSet> grips_;
  std::vector<GripSet> edges_;
  std::vector<GripSet> picked_faces_;
  const document::Document* doc_ = nullptr;
  std::optional<std::vector<document::SelectionItem>> select_;
  QString file_;
  QString message_;
  PlaneFrame view_plane_;
  std::vector<std::vector<nf::Vec3>> drawing_wire_;
  std::optional<nf::Transform> motion_;
};

/// Creates a command by id or alias (case-insensitive): point/pt, line/l, polyline/pl,
/// rectangle/rec, polygon/pol, circle/c, circle3p/c3, arc/a, helix/h, distance/dist.
/// Returns null for unknown names.
[[nodiscard]] std::unique_ptr<Command> create_command(const QString& name);
/// Ids of all commands.
[[nodiscard]] QStringList command_ids();

namespace detail {
// Factories of the command groups (drawing_commands.cpp, solid_commands.cpp,
// transform_commands.cpp); create_command searches them in this order.
std::unique_ptr<Command> create_solid_command(const QString& name);
std::unique_ptr<Command> create_curve_command(const QString& name);
QStringList curve_command_ids();
std::unique_ptr<Command> create_derived_curve_command(const QString& name);
std::unique_ptr<Command> create_curve_edit_command(const QString& name);
std::unique_ptr<Command> create_surface_create_command(const QString& name);
std::unique_ptr<Command> create_surface_blend_command(const QString& name);
std::unique_ptr<Command> create_surface_edit_command(const QString& name);
std::unique_ptr<Command> create_deform_command(const QString& name);
std::unique_ptr<Command> create_analysis_command(const QString& name);
QStringList analysis_command_ids();
std::unique_ptr<Command> create_view_drawing_command(const QString& name);
std::unique_ptr<Command> create_dimension_command(const QString& name);
QStringList dimension_command_ids();
QStringList view_drawing_command_ids();
QStringList deform_command_ids();
QStringList surface_edit_command_ids();
QStringList surface_blend_command_ids();
QStringList surface_create_command_ids();
QStringList curve_edit_command_ids();
QStringList derived_curve_command_ids();
std::unique_ptr<Command> create_transform_command(const QString& name);
std::unique_ptr<Command> create_surface_command(const QString& name);
QStringList surface_command_ids();
std::unique_ptr<Command> create_edit_command(const QString& name);
QStringList edit_command_ids();
QStringList solid_command_ids();
QStringList transform_command_ids();
}  // namespace detail

}  // namespace nfcad::commands
