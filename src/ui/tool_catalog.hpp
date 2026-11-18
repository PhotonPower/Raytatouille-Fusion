#pragma once

#include <QKeySequence>
#include <QString>
#include <vector>

namespace nfcad::ui {

/// One tool button in the tool column (docs/ui-concept.md, "Tool column").
struct ToolDef {
  QString id;          ///< command id, also icon file name: resources/icons/<group>/<id>.svg
  QString label;       ///< tooltip / menu text
  QString short_label; ///< fallback text on the button while no icon exists
  QKeySequence shortcut; ///< a real (registered) shortcut only, e.g. Delete
  QString alias;         ///< command name / alias to type + Enter (not a shortcut); may be empty
};

struct ToolGroupDef {
  QString id;
  QString title;
  bool expanded_by_default = false;
  std::vector<ToolDef> tools;
};

/// All tool groups in display order.
[[nodiscard]] const std::vector<ToolGroupDef>& tool_catalog();

/// Tooltip of a tool button: the label, a real shortcut in parentheses and the alias to type
/// ("Line\nType: l + Enter").
[[nodiscard]] QString tool_tip(const ToolDef& tool);

}  // namespace nfcad::ui
