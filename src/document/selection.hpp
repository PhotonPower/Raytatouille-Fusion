#pragma once

#include <QObject>
#include <QPointer>
#include <functional>
#include <optional>
#include <set>
#include <vector>

#include "document/entity.hpp"

namespace nfcad::document {

class Document;

/// Part of an entity: a face, an edge or a B-rep vertex of a shell or face (index into the
/// display mesh's sub-elements, which follow the B-rep numbering), or a control point of a curve
/// whose points are shown (its index among the control points, "grip").
struct SubElement {
  enum class Kind : std::uint8_t { None, Face, Edge, Vertex, ControlPoint };
  Kind kind = Kind::None;
  int index = -1;
  friend auto operator<=>(const SubElement&, const SubElement&) = default;
};

struct SelectionItem {
  EntityId entity = 0;
  SubElement sub;  ///< Kind::None: the whole entity
  friend auto operator<=>(const SelectionItem&, const SelectionItem&) = default;
};

[[nodiscard]] QString sub_element_name(const SubElement& s);

/// Selected and hovered items (M3). Kept consistent with the document: removed entities and
/// those on a locked layer leave the selection, and objects on a locked layer cannot be
/// selected. Not part of the undo history.
///
/// Besides entities, result drawings can be selected: the line items of a run (rays, the Path
/// Tracer's camera), by the run's id (results::ResultId) – docs/plugins.md, "Result drawings in
/// the views". empty() and the entity queries ignore them.
class Selection : public QObject {
  Q_OBJECT
 public:
  enum class Mode { Replace, Add, Remove, Toggle };

  explicit Selection(QObject* parent = nullptr);
  /// Follows entity removal / document reset and keeps locked objects out.
  void attach(class Document* doc);

  [[nodiscard]] const std::set<SelectionItem>& items() const { return items_; }
  /// Items in the order they were selected (Boolean difference: first minus the others).
  [[nodiscard]] const std::vector<SelectionItem>& ordered() const { return order_; }
  [[nodiscard]] bool empty() const { return items_.empty(); }
  [[nodiscard]] bool isSelected(EntityId id) const;  ///< whole entity selected
  /// Selected sub-elements of an entity.
  [[nodiscard]] std::vector<SubElement> selectedParts(EntityId id) const;
  /// Entities with any selected item (whole or parts).
  [[nodiscard]] std::vector<EntityId> entities() const;

  /// Mode::Replace also deselects the result drawings.
  void apply(const std::vector<SelectionItem>& items, Mode mode);
  /// Deselects everything (entities and result drawings).
  void clear();

  // ---- result drawings (runs by id)
  [[nodiscard]] const std::set<std::uint64_t>& results() const { return results_; }
  [[nodiscard]] bool hasResults() const { return !results_.empty(); }
  [[nodiscard]] bool isResultSelected(std::uint64_t set) const { return results_.contains(set); }
  /// Selects result drawings like apply(); Mode::Replace also deselects the entities.
  void applyResults(const std::vector<std::uint64_t>& sets, Mode mode);
  /// Drops the runs that no longer exist (the result store changed).
  void retainResults(const std::function<bool(std::uint64_t)>& exists);

  [[nodiscard]] std::optional<SelectionItem> hovered() const { return hovered_; }
  void setHovered(std::optional<SelectionItem> item);
  /// The result drawing under the cursor (a run's id).
  [[nodiscard]] std::optional<std::uint64_t> hoveredResult() const { return hovered_result_; }
  void setHoveredResult(std::optional<std::uint64_t> set);

  /// Incremented on every change (renderers compare it to skip work).
  [[nodiscard]] std::uint64_t version() const { return version_; }

 signals:
  void changed();
  void hoverChanged();

 private:
  void dropEntity(EntityId id);
  void syncOrder();
  QPointer<Document> doc_;
  std::set<SelectionItem> items_;
  std::vector<SelectionItem> order_;
  std::optional<SelectionItem> hovered_;
  std::set<std::uint64_t> results_;
  std::optional<std::uint64_t> hovered_result_;
  std::uint64_t version_ = 0;
};

}  // namespace nfcad::document
