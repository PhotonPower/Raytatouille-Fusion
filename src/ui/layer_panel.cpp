#include "ui/layer_panel.hpp"

#include <QColorDialog>
#include <QGridLayout>
#include <QHeaderView>
#include <QMenu>
#include <QMessageBox>
#include <QPainter>
#include <QPixmap>
#include <QPushButton>
#include <QTimer>
#include <QTreeWidget>
#include <QVBoxLayout>

#include "document/document.hpp"
#include "document/selection.hpp"

namespace nfcad::ui {

namespace {
enum Column { kName = 0, kLock = 1, kColor = 2 };
constexpr int kLayerIdRole = Qt::UserRole + 1;

QIcon swatch(const QColor& c) {
  QPixmap pm(14, 14);
  pm.fill(Qt::transparent);
  QPainter p(&pm);
  p.setPen(QColor(20, 20, 20));
  p.setBrush(c);
  p.drawRect(0, 0, 13, 13);
  return QIcon(pm);
}

bool ask_with_box(QWidget* parent, const QString& layer, std::size_t objects, document::LayerContents* contents) {
  QMessageBox box(QMessageBox::Question, QObject::tr("Delete layer"),
                  QObject::tr("Layer \"%1\" has %n object(s). What happens to them?", nullptr,
                              static_cast<int>(objects))
                      .arg(layer),
                  QMessageBox::Cancel, parent);
  QPushButton* move = box.addButton(QObject::tr("Move to Default"), QMessageBox::AcceptRole);
  QPushButton* remove = box.addButton(QObject::tr("Delete objects"), QMessageBox::DestructiveRole);
  box.setDefaultButton(move);
  box.exec();
  if (box.clickedButton() == move) {
    *contents = document::LayerContents::MoveToDefault;
    return true;
  }
  if (box.clickedButton() == remove) {
    *contents = document::LayerContents::Delete;
    return true;
  }
  return false;
}
}  // namespace

LayerPanel::LayerPanel(document::Document* doc, document::Selection* selection, QWidget* parent)
    : QWidget(parent), doc_(doc), selection_(selection) {
  ask_contents = [this](const QString& layer, std::size_t objects, document::LayerContents* contents) {
    return ask_with_box(this, layer, objects, contents);
  };
  auto* layout = new QVBoxLayout(this);
  layout->setContentsMargins(4, 4, 4, 4);
  tree_ = new QTreeWidget(this);
  tree_->setColumnCount(3);
  tree_->setHeaderLabels({tr("Layer"), tr("Lock"), tr("Colour")});
  tree_->headerItem()->setToolTip(kName, tr("Check box: visible; bold: the current layer (new objects go there)"));
  tree_->headerItem()->setToolTip(kLock, tr("Locked: the objects are shown but cannot be selected or changed"));
  tree_->setRootIsDecorated(false);
  tree_->setContextMenuPolicy(Qt::CustomContextMenu);
  // only the name is edited as text (double-click or Rename); the colour has its dialog
  tree_->setEditTriggers(QAbstractItemView::NoEditTriggers);
  tree_->header()->setStretchLastSection(false);
  tree_->header()->setSectionResizeMode(kName, QHeaderView::Stretch);
  tree_->header()->setSectionResizeMode(kLock, QHeaderView::ResizeToContents);
  tree_->header()->setSectionResizeMode(kColor, QHeaderView::ResizeToContents);
  layout->addWidget(tree_);

  auto* buttons = new QGridLayout;
  auto* add = new QPushButton(tr("New layer"), this);
  add->setObjectName(QStringLiteral("newLayer"));
  delete_ = new QPushButton(tr("Delete layer…"), this);
  delete_->setObjectName(QStringLiteral("deleteLayer"));
  delete_->setToolTip(tr("Deletes the highlighted layer; its objects move to Default or are deleted.\n"
                         "The Default layer cannot be deleted."));
  current_ = new QPushButton(tr("Make current"), this);
  current_->setObjectName(QStringLiteral("makeCurrent"));
  current_->setToolTip(tr("New objects (drawn, imported, made by plugins) go to the current layer"));
  auto* assign = new QPushButton(tr("Move selection here"), this);
  assign->setObjectName(QStringLiteral("moveSelection"));
  assign->setToolTip(tr("Moves the selected objects to the highlighted layer"));
  buttons->addWidget(add, 0, 0);
  buttons->addWidget(delete_, 0, 1);
  buttons->addWidget(current_, 1, 0);
  buttons->addWidget(assign, 1, 1);
  layout->addLayout(buttons);

  connect(add, &QPushButton::clicked, this, [this] {
    const auto n = doc_->layers().size();
    doc_->addLayer({0, tr("Layer %1").arg(n), QColor::fromHsv(static_cast<int>(n * 67 % 360), 120, 220), true});
  });
  connect(delete_, &QPushButton::clicked, this, &LayerPanel::deleteHighlighted);
  connect(current_, &QPushButton::clicked, this, &LayerPanel::makeHighlightedCurrent);
  connect(assign, &QPushButton::clicked, this, [this] {
    if (tree_->currentItem() == nullptr) return;
    doc_->assignLayer(selection_->entities(), highlightedLayer());
  });
  connect(tree_, &QTreeWidget::itemChanged, this, &LayerPanel::onItemChanged);
  connect(tree_, &QTreeWidget::itemDoubleClicked, this, &LayerPanel::onItemDoubleClicked);
  connect(tree_, &QTreeWidget::currentItemChanged, this, &LayerPanel::updateButtons);
  connect(tree_, &QTreeWidget::customContextMenuRequested, this, &LayerPanel::showContextMenu);
  connect(doc_, &document::Document::layersChanged, this, &LayerPanel::rebuild);
  rebuild();
}

std::uint32_t LayerPanel::highlightedLayer() const {
  const QTreeWidgetItem* item = tree_->currentItem();
  return item != nullptr ? item->data(kName, kLayerIdRole).toUInt() : 0;
}

void LayerPanel::rebuild() {
  rebuilding_ = true;
  const QVariant current = tree_->currentItem() != nullptr
                               ? tree_->currentItem()->data(kName, kLayerIdRole)
                               : QVariant();
  tree_->clear();
  for (const document::Layer& l : doc_->layers()) {
    auto* item = new QTreeWidgetItem(tree_);
    item->setText(kName, l.name);
    item->setData(kName, kLayerIdRole, l.id);
    item->setFlags(item->flags() | Qt::ItemIsEditable | Qt::ItemIsUserCheckable);
    item->setCheckState(kName, l.visible ? Qt::Checked : Qt::Unchecked);
    item->setCheckState(kLock, l.locked ? Qt::Checked : Qt::Unchecked);
    item->setToolTip(kLock, tr("Locked: the objects are shown but cannot be selected or changed"));
    item->setIcon(kColor, swatch(l.color));
    item->setToolTip(kColor, tr("Double-click to change the colour"));
    if (l.id == doc_->currentLayer()) {
      QFont bold = item->font(kName);
      bold.setBold(true);
      item->setFont(kName, bold);
      item->setToolTip(kName, tr("Current layer: new objects go here"));
    }
    if (current.isValid() && current.toUInt() == l.id) tree_->setCurrentItem(item);
  }
  rebuilding_ = false;
  updateButtons();
}

void LayerPanel::updateButtons() {
  const QTreeWidgetItem* item = tree_->currentItem();
  const std::uint32_t id = highlightedLayer();
  delete_->setEnabled(item != nullptr && id != 0);  // Default stays
  current_->setEnabled(item != nullptr && id != doc_->currentLayer());
}

void LayerPanel::onItemChanged(QTreeWidgetItem* item, int column) {
  if (rebuilding_ || (column != kName && column != kLock)) return;
  const auto id = static_cast<document::LayerId>(item->data(kName, kLayerIdRole).toUInt());
  const bool visible = item->checkState(kName) == Qt::Checked;
  const bool locked = item->checkState(kLock) == Qt::Checked;
  const QString name = item->text(kName).trimmed();
  // Applied after Qt has finished with the click / edit: the document change rebuilds this
  // tree, which must not happen inside QTreeWidgetItem::setData (the item would be deleted).
  QTimer::singleShot(0, this, [this, id, visible, locked, name] {
    doc_->setLayerVisible(id, visible);
    doc_->setLayerLocked(id, locked);
    if (!name.isEmpty()) {
      doc_->renameLayer(id, name);
    } else {
      rebuild();  // an empty name is not taken: show the old one again
    }
  });
}

void LayerPanel::onItemDoubleClicked(QTreeWidgetItem* item, int column) {
  if (column == kName) {
    tree_->editItem(item, kName);
    return;
  }
  if (column != kColor) return;
  const auto id = static_cast<document::LayerId>(item->data(kName, kLayerIdRole).toUInt());
  const document::Layer* l = doc_->layer(id);
  if (l == nullptr) return;
  const QColor c = QColorDialog::getColor(l->color, this, tr("Layer colour"));
  if (c.isValid()) doc_->setLayerColor(id, c);
}

void LayerPanel::deleteHighlighted() {
  if (tree_->currentItem() == nullptr) return;
  const document::LayerId id = highlightedLayer();
  const document::Layer* l = doc_->layer(id);
  if (l == nullptr || id == 0) return;
  auto contents = document::LayerContents::MoveToDefault;
  const std::size_t n = doc_->entityCount(id);
  if (n > 0 && !ask_contents(l->name, n, &contents)) return;
  doc_->removeLayer(id, contents);
}

void LayerPanel::makeHighlightedCurrent() {
  if (tree_->currentItem() != nullptr) doc_->setCurrentLayer(highlightedLayer());
}

void LayerPanel::showContextMenu(const QPoint& pos) {
  QTreeWidgetItem* item = tree_->itemAt(pos);
  if (item == nullptr) return;
  tree_->setCurrentItem(item);
  const auto id = static_cast<document::LayerId>(item->data(kName, kLayerIdRole).toUInt());
  const document::Layer* l = doc_->layer(id);
  if (l == nullptr) return;
  QMenu menu(this);
  QAction* current = menu.addAction(tr("Make current"), this, &LayerPanel::makeHighlightedCurrent);
  current->setEnabled(id != doc_->currentLayer());
  menu.addAction(tr("Rename"), this, [this, item] { tree_->editItem(item, kName); });
  menu.addAction(tr("Colour…"), this, [this, item] { onItemDoubleClicked(item, kColor); });
  menu.addAction(l->locked ? tr("Unlock") : tr("Lock"), this,
                 [this, id, locked = !l->locked] { doc_->setLayerLocked(id, locked); });
  menu.addAction(tr("Move selection here"), this, [this, id] { doc_->assignLayer(selection_->entities(), id); });
  menu.addSeparator();
  QAction* remove = menu.addAction(tr("Delete layer…"), this, &LayerPanel::deleteHighlighted);
  remove->setEnabled(id != 0);
  menu.exec(tree_->viewport()->mapToGlobal(pos));
}

}  // namespace nfcad::ui
