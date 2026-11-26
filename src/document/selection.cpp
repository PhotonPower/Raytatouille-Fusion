#include "document/selection.hpp"

#include "document/document.hpp"

#include <algorithm>

namespace nfcad::document {

QString sub_element_name(const SubElement& s) {
  switch (s.kind) {
    case SubElement::Kind::Face: return QObject::tr("face %1").arg(s.index);
    case SubElement::Kind::Edge: return QObject::tr("edge %1").arg(s.index);
    case SubElement::Kind::Vertex: return QObject::tr("vertex %1").arg(s.index);
    case SubElement::Kind::ControlPoint: return QObject::tr("control point %1").arg(s.index);
    case SubElement::Kind::None: break;
  }
  return {};
}

Selection::Selection(QObject* parent) : QObject(parent) {}

void Selection::attach(Document* doc) {
  doc_ = doc;
  connect(doc, &Document::entityRemoved, this, &Selection::dropEntity);
  // an object whose layer is locked (or that moved to a locked layer) leaves the selection
  connect(doc, &Document::entityChanged, this, [this](EntityId id) {
    if (doc_->isLocked(id)) dropEntity(id);
  });
  connect(doc, &Document::documentReset, this, [this] {
    hovered_.reset();
    hovered_result_.reset();
    clear();
  });
}

bool Selection::isSelected(EntityId id) const { return items_.contains({id, {}}); }

std::vector<SubElement> Selection::selectedParts(EntityId id) const {
  std::vector<SubElement> out;
  for (auto it = items_.lower_bound({id, {}}); it != items_.end() && it->entity == id; ++it) {
    if (it->sub.kind != SubElement::Kind::None) out.push_back(it->sub);
  }
  return out;
}

std::vector<EntityId> Selection::entities() const {
  std::vector<EntityId> out;
  for (const SelectionItem& i : items_) {
    if (out.empty() || out.back() != i.entity) out.push_back(i.entity);
  }
  return out;
}

void Selection::apply(const std::vector<SelectionItem>& items, Mode mode) {
  std::set<SelectionItem> next = mode == Mode::Replace ? std::set<SelectionItem>{} : items_;
  for (const SelectionItem& i : items) {
    if (doc_ != nullptr && mode != Mode::Remove && doc_->isLocked(i.entity)) continue;  // locked layer
    switch (mode) {
      case Mode::Replace:
      case Mode::Add: next.insert(i); break;
      case Mode::Remove: next.erase(i); break;
      case Mode::Toggle:
        if (!next.erase(i)) next.insert(i);
        break;
    }
  }
  const bool drop_results = mode == Mode::Replace && !results_.empty();
  if (next == items_ && !drop_results) return;
  if (drop_results) results_.clear();
  items_ = std::move(next);
  if (mode == Mode::Replace) order_.clear();
  for (const SelectionItem& i : items) {
    if (items_.contains(i) && std::find(order_.begin(), order_.end(), i) == order_.end()) {
      order_.push_back(i);
    }
  }
  syncOrder();
  ++version_;
  emit changed();
}

void Selection::clear() { apply({}, Mode::Replace); }

void Selection::applyResults(const std::vector<std::uint64_t>& sets, Mode mode) {
  std::set<std::uint64_t> next = mode == Mode::Replace ? std::set<std::uint64_t>{} : results_;
  for (std::uint64_t s : sets) {
    switch (mode) {
      case Mode::Replace:
      case Mode::Add: next.insert(s); break;
      case Mode::Remove: next.erase(s); break;
      case Mode::Toggle:
        if (!next.erase(s)) next.insert(s);
        break;
    }
  }
  const bool drop_entities = mode == Mode::Replace && !items_.empty();
  if (next == results_ && !drop_entities) return;
  results_ = std::move(next);
  if (drop_entities) {
    items_.clear();
    order_.clear();
  }
  ++version_;
  emit changed();
}

void Selection::retainResults(const std::function<bool(std::uint64_t)>& exists) {
  if (hovered_result_ && !exists(*hovered_result_)) setHoveredResult(std::nullopt);
  if (std::erase_if(results_, [&](std::uint64_t s) { return !exists(s); }) > 0) {
    ++version_;
    emit changed();
  }
}

void Selection::setHoveredResult(std::optional<std::uint64_t> set) {
  if (set == hovered_result_) return;
  hovered_result_ = set;
  ++version_;
  emit hoverChanged();
}

void Selection::setHovered(std::optional<SelectionItem> item) {
  if (item == hovered_) return;
  hovered_ = item;
  ++version_;
  emit hoverChanged();
}

void Selection::syncOrder() {
  std::erase_if(order_, [this](const SelectionItem& i) { return !items_.contains(i); });
}

void Selection::dropEntity(EntityId id) {
  bool changed_any = false;
  for (auto it = items_.lower_bound({id, {}}); it != items_.end() && it->entity == id;) {
    it = items_.erase(it);
    changed_any = true;
  }
  if (hovered_ && hovered_->entity == id) setHovered(std::nullopt);
  syncOrder();
  if (changed_any) {
    ++version_;
    emit changed();
  }
}

}  // namespace nfcad::document
