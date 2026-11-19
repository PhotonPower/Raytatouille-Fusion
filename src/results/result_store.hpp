#pragma once

#include <QObject>
#include <vector>

#include "results/result_types.hpp"

namespace nfcad::document {
class Document;
}

namespace nfcad::results {

/// The result sets of the session (docs/plugins.md, P2): created by plugins (P3) or scripts,
/// shown by the viewports (line sets, face fields), the plot dock (curves) and the Results
/// panel. Results reference entities by id; results of removed entities are hidden.
class ResultStore : public QObject {
  Q_OBJECT
 public:
  explicit ResultStore(QObject* parent = nullptr);

  [[nodiscard]] const std::vector<ResultSet>& sets() const { return sets_; }
  [[nodiscard]] const ResultSet* set(ResultId id) const;

  ResultId createSet(const QString& name, const QString& source = {});
  /// `key`: a drawing that replaces older ones – the line items with this key in other result
  /// sets are removed (and sets left empty by that), e.g. the camera of the Path Tracer drawn
  /// again after its parameters changed.
  ResultId addLines(ResultId set, const QString& name, LineSet lines, const QString& key = {});
  ResultId addField(ResultId set, const QString& name, FaceField field);
  /// `key`: as `setKey`, but set before the item is announced (one `changed` with the key – a
  /// window that ignores keyed results never sees the item without it)
  ResultId addCurve(ResultId set, const QString& name, Curve curve, const QString& key = {});
  ResultId addImage(ResultId set, const QString& name, Image image, const QString& key = {});
  ResultId addTable(ResultId set, const QString& name, Table table, const QString& key = {});
  ResultId addBars(ResultId set, const QString& name, Bars bars, const QString& key = {});
  /// Sets the key of an item (ResultItem::key).
  void setKey(ResultId item, const QString& key);
  /// Sets the fingerprint of an item (ResultItem::stamp).
  void setStamp(ResultId item, const QString& stamp);
  /// Items with `key` (of `kind`) from the newest result set that has any (empty if none).
  [[nodiscard]] std::vector<const ResultItem*> itemsWithKey(const QString& key, ResultItem::Kind kind) const;
  /// Appends points to a curve (live plots, e.g. a merit function per iteration).
  void appendToCurve(ResultId item, double x, double y);

  void setSetVisible(ResultId set, bool visible);
  void setItemVisible(ResultId item, bool visible);
  /// Where a line item is shown (ResultItem::placement).
  void setPlacement(ResultId item, const nf::Transform& placement);
  /// What a line item stands for in its plugin's parameters (ResultItem::binding).
  void setBinding(ResultId item, const QJsonObject& binding);
  void removeSet(ResultId set);
  /// Removes the line items of a run (its drawing in the views); the run goes too if nothing
  /// else is left in it.
  void removeLines(ResultId set);
  /// Puts a run back as it was (undo): replaces the run with this id, or inserts it at `index`.
  void restoreSet(ResultSet set, std::size_t index);
  /// Position of a run in sets() (sets().size() if unknown).
  [[nodiscard]] std::size_t indexOf(ResultId set) const;
  /// The run an item belongs to (0 if unknown).
  [[nodiscard]] ResultId setOf(ResultId item) const;
  void clear();

  /// Visible items of visible sets.
  [[nodiscard]] std::vector<const ResultItem*> visibleItems(ResultItem::Kind kind) const;
  [[nodiscard]] const ResultItem* item(ResultId id) const;

  /// Creates CAD polylines from every n-th polyline of a line set (at most `max_count`), where
  /// the drawing is shown (`placement`); returns the entities (the caller adds them as one undo
  /// step).
  [[nodiscard]] static std::vector<document::Entity> promote(const LineSet& lines, std::size_t every,
                                                             std::size_t max_count,
                                                             const nf::Transform& placement = {});

 signals:
  void changed();
  /// A curve got new points (the plot redraws without rebuilding the lists).
  void curveUpdated(nfcad::results::ResultId item);

 private:
  ResultItem* mutableItem(ResultId id);
  ResultId add(ResultId set, ResultItem item);
  /// Removes the line items with `key` outside `keep_set` (and sets left empty); no signal.
  void dropKeyedLines(const QString& key, ResultId keep_set);

  std::vector<ResultSet> sets_;
  ResultId next_ = 1;
};

}  // namespace nfcad::results
