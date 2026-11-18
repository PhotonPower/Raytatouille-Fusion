#pragma once

#include <QWidget>
#include <cstdint>
#include <functional>

class QPushButton;
class QTreeWidget;
class QTreeWidgetItem;

namespace nfcad::document {
class Document;
class Selection;
enum class LayerContents;
}  // namespace nfcad::document

namespace nfcad::ui {

/// Right dock: the layers with visibility (check box), name (editable), lock and colour
/// (double-click the swatch). The current layer – where new objects go – is shown in bold;
/// buttons and the context menu add, delete and make a layer current and move the selection to
/// the highlighted layer.
class LayerPanel : public QWidget {
  Q_OBJECT
 public:
  LayerPanel(document::Document* doc, document::Selection* selection, QWidget* parent = nullptr);

  /// Asks what happens to the objects of a layer that is deleted (tests replace it); returns
  /// false to cancel. Default: a message box with "Move to Default" / "Delete objects" / Cancel.
  std::function<bool(const QString& layer, std::size_t objects, document::LayerContents* contents)> ask_contents;

  /// The layer highlighted in the list (0 if none).
  [[nodiscard]] std::uint32_t highlightedLayer() const;
  /// Deletes the highlighted layer (asks what happens to its objects).
  void deleteHighlighted();
  /// Makes the highlighted layer the current one.
  void makeHighlightedCurrent();

 private:
  void rebuild();
  void onItemChanged(QTreeWidgetItem* item, int column);
  void onItemDoubleClicked(QTreeWidgetItem* item, int column);
  void showContextMenu(const QPoint& pos);
  void updateButtons();

  document::Document* doc_;
  document::Selection* selection_;
  QTreeWidget* tree_ = nullptr;
  QPushButton* delete_ = nullptr;
  QPushButton* current_ = nullptr;
  bool rebuilding_ = false;
};

}  // namespace nfcad::ui
