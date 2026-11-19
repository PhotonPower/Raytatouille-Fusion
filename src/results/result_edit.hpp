#pragma once

#include <QJsonObject>
#include <QString>
#include <QUndoCommand>
#include <map>
#include <memory>
#include <nurbforge/geometry/transform.hpp>
#include <vector>

#include "results/result_types.hpp"

namespace nfcad::document {
class Document;
}

namespace nfcad::results {

class ResultStore;

/// Result drawings in the views as objects (docs/plugins.md, "Result drawings in the views"):
/// the line items of a run are one object that can be selected, moved, rotated and deleted.
/// Moving is a display transform of the drawing (ResultItem::placement); a drawing with a
/// binding writes its new place back into the parameters of the plugin that drew it.

/// Parameter values a bound drawing stands for at `placement` (ResultItem::binding):
/// - "points": {name: [x, y, z]} – point parameters, moved with the drawing;
/// - "view": {"forward": [..], "up": [..], "up_param": name, "roll_param": name,
///   "choices": {label: [x, y, z]}, "order": [labels]} – a camera's orientation (`forward`, `up`:
///   unit vectors as drawn): the choice of `up_param` that needs the least turn about the moved
///   view direction (ties: first in "order"), and `roll_param` that turn (degrees, right-handed
///   about the view direction) from the choice's up – made orthogonal to the view – to the moved
///   camera's up. So any rigid motion is expressed exactly; without `roll_param` the note says
///   when a turn about the view is lost.
/// Returns {name: value}; empty without a binding. `note`: a short description for the status
/// bar (e.g. "up +Z, roll 12.5°").
[[nodiscard]] QJsonObject bound_parameters(const QJsonObject& binding, const nf::Transform& placement,
                                           QString* note = nullptr);

/// The undo step that moves the drawings (line items) of the runs `sets` by `motion` – their
/// placement becomes motion × placement – and writes what bound drawings stand for into the
/// parameters of the plugins that drew them (the run's source; `doc` may be null: no
/// parameters). Null if the runs have no drawing. `note`: what the bindings wrote, for the
/// status bar (empty without bindings). The step applies when pushed (QUndoStack::push).
[[nodiscard]] std::unique_ptr<QUndoCommand> move_results(ResultStore& store, document::Document* doc,
                                                         const std::vector<ResultId>& sets,
                                                         const nf::Transform& motion, const QString& text,
                                                         QString* note = nullptr);

/// The undo step that deletes the drawings (line items) of the runs `sets` – a run with nothing
/// else in it goes as a whole; undo puts the runs back as they were. Null if there is nothing to
/// delete.
[[nodiscard]] std::unique_ptr<QUndoCommand> delete_results(ResultStore& store, const std::vector<ResultId>& sets,
                                                           const QString& text);

/// Line items of a run in the views (visible run and item), for picking and previews.
[[nodiscard]] std::vector<const ResultItem*> drawn_lines(const ResultStore& store, ResultId set);

/// Polylines of the runs' drawings where they are shown, for a rubber-band preview: at most
/// about `max_points` points (every n-th polyline of a large ray set).
[[nodiscard]] std::vector<std::vector<nf::Vec3>> drawing_wire(const ResultStore& store,
                                                               const std::vector<ResultId>& sets,
                                                               std::size_t max_points = 20000);

}  // namespace nfcad::results
