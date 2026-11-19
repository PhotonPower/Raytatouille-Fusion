// Result drawings as objects in the views, see result_edit.hpp.
#include "results/result_edit.hpp"

#include <QJsonArray>
#include <QObject>
#include <algorithm>
#include <cmath>
#include <limits>
#include <numbers>

#include "document/document.hpp"
#include "results/result_store.hpp"

namespace nfcad::results {

namespace {

std::optional<nf::Vec3> vec(const QJsonValue& v) {
  const QJsonArray a = v.toArray();
  if (a.size() != 3) return std::nullopt;
  return nf::Vec3{a[0].toDouble(), a[1].toDouble(), a[2].toDouble()};
}

QJsonArray json(const nf::Vec3& v) {
  // 1e-9 mm and below is rounding noise of the motion: written as 0
  auto clean = [](double x) { return std::abs(x) < 1e-9 ? 0.0 : x; };
  return QJsonArray{clean(v.x), clean(v.y), clean(v.z)};
}

nf::Vec3 unit(const nf::Vec3& v) {
  const double n = nf::norm(v);
  return n > 0 ? v / n : v;
}

}  // namespace

QJsonObject bound_parameters(const QJsonObject& binding, const nf::Transform& placement, QString* note) {
  QJsonObject out;
  const QJsonObject points = binding["points"].toObject();
  for (auto it = points.begin(); it != points.end(); ++it) {
    if (const auto p = vec(it.value())) out.insert(it.key(), json(placement.apply(*p)));
  }
  const QJsonObject view = binding["view"].toObject();
  const auto f0 = vec(view["forward"]);
  const auto u0 = vec(view["up"]);
  const QString up_param = view["up_param"].toString();
  const QString roll_param = view["roll_param"].toString();
  if (f0 && u0 && !up_param.isEmpty()) {
    const nf::Vec3 f = unit(placement.apply_vector(*f0));
    const nf::Vec3 u = unit(placement.apply_vector(*u0));
    // the choice whose up (made orthogonal to the view) needs the least roll; ties: the order
    // of the choices (the plugin lists the current one first)
    QString best;
    double best_roll = std::numeric_limits<double>::max();
    const QJsonObject choices = view["choices"].toObject();
    QStringList order = view["order"].toVariant().toStringList();
    for (const QString& k : choices.keys()) {
      if (!order.contains(k)) order << k;
    }
    for (const QString& label : order) {
      const auto a = vec(choices[label]);
      if (!a) continue;
      const nf::Vec3 base = *a - f * nf::dot(*a, f);
      if (nf::norm(base) < 1e-6) continue;  // parallel to the view: no up direction
      const nf::Vec3 b = unit(base);
      const double roll = std::atan2(nf::dot(nf::cross(b, u), f), nf::dot(b, u));
      if (std::abs(roll) < std::abs(best_roll) - 1e-12) {
        best_roll = roll;
        best = label;
      }
    }
    if (!best.isEmpty()) {
      double deg = best_roll * 180.0 / std::numbers::pi;
      if (std::abs(deg) < 1e-7) deg = 0.0;
      out.insert(up_param, best);
      if (!roll_param.isEmpty()) out.insert(roll_param, deg);
      if (note != nullptr) {
        *note = roll_param.isEmpty() || deg == 0.0
                    ? QObject::tr("up %1").arg(best)
                    : QObject::tr("up %1, roll %2°").arg(best).arg(deg, 0, 'f', 2);
        if (roll_param.isEmpty() && std::abs(deg) > 0.01) {
          *note += QObject::tr(" – the turn about the view (%1°) cannot be kept").arg(deg, 0, 'f', 2);
        }
      }
    }
  }
  return out;
}

namespace {

/// Undo step: placements of line items and the plugin parameters their bindings write.
class PlaceResults : public QUndoCommand {
 public:
  struct Change {
    ResultId item = 0;
    nf::Transform before;
    nf::Transform after;
  };
  using Parameters = std::map<QString, std::pair<QJsonObject, QJsonObject>>;  // plugin -> before, after

  PlaceResults(ResultStore* store, document::Document* doc, std::vector<Change> changes, Parameters parameters,
               const QString& text)
      : QUndoCommand(text),
        store_(store),
        doc_(doc),
        changes_(std::move(changes)),
        parameters_(std::move(parameters)) {}
  void undo() override { apply(false); }
  void redo() override { apply(true); }

 private:
  void apply(bool forward) {
    // a run deleted in the meantime ("Delete run") has nothing to move: only the parameters
    for (const Change& c : changes_) store_->setPlacement(c.item, forward ? c.after : c.before);
    if (doc_ == nullptr) return;
    for (const auto& [plugin, values] : parameters_) {
      doc_->setPluginParameters(plugin, forward ? values.second : values.first);
      emit doc_->pluginParametersSet(plugin);  // the plugin panel shows the new values
    }
  }
  ResultStore* store_;
  document::Document* doc_;
  std::vector<Change> changes_;
  Parameters parameters_;
};

/// Undo step: the runs as they were before their drawings were deleted.
class DeleteResults : public QUndoCommand {
 public:
  DeleteResults(ResultStore* store, std::vector<std::pair<ResultSet, std::size_t>> before, const QString& text)
      : QUndoCommand(text), store_(store), before_(std::move(before)) {}
  void redo() override {
    for (const auto& [set, index] : before_) store_->removeLines(set.id);
  }
  void undo() override {
    // by increasing position: each run goes back where it was
    for (const auto& [set, index] : before_) store_->restoreSet(set, index);
  }

 private:
  ResultStore* store_;
  std::vector<std::pair<ResultSet, std::size_t>> before_;  ///< runs and their positions, by position
};

}  // namespace

std::vector<const ResultItem*> drawn_lines(const ResultStore& store, ResultId set) {
  std::vector<const ResultItem*> out;
  const ResultSet* s = store.set(set);
  if (s == nullptr || !s->visible) return out;
  for (const ResultItem& i : s->items) {
    if (i.kind == ResultItem::Kind::Lines && i.visible && i.lines) out.push_back(&i);
  }
  return out;
}

std::vector<std::vector<nf::Vec3>> drawing_wire(const ResultStore& store, const std::vector<ResultId>& sets,
                                                std::size_t max_points) {
  std::size_t total = 0;
  for (ResultId id : sets) {
    for (const ResultItem* i : drawn_lines(store, id)) total += i->lines->pointCount();
  }
  const std::size_t every = std::max<std::size_t>(1, (total + max_points - 1) / std::max<std::size_t>(max_points, 1));
  std::vector<std::vector<nf::Vec3>> out;
  for (ResultId id : sets) {
    for (const ResultItem* i : drawn_lines(store, id)) {
      const LineSet& l = *i->lines;
      for (std::size_t k = 0; k < l.polylineCount(); k += every) {
        std::vector<nf::Vec3> pl;
        for (std::uint32_t p = l.starts[k]; p < l.starts[k + 1]; ++p) {
          if (std::isnan(l.points[3 * p])) break;  // a lost ray ends here
          pl.push_back(placed_point(*i, p));
        }
        if (pl.size() >= 2) out.push_back(std::move(pl));
      }
    }
  }
  return out;
}

std::unique_ptr<QUndoCommand> move_results(ResultStore& store, document::Document* doc,
                                           const std::vector<ResultId>& sets, const nf::Transform& motion,
                                           const QString& text, QString* note) {
  std::vector<PlaceResults::Change> changes;
  PlaceResults::Parameters parameters;
  QStringList notes;
  for (ResultId id : sets) {
    const ResultSet* s = store.set(id);
    if (s == nullptr) continue;
    for (const ResultItem& i : s->items) {
      if (i.kind != ResultItem::Kind::Lines) continue;
      const nf::Transform after = motion * i.placement;
      changes.push_back({i.id, i.placement, after});
      if (doc == nullptr || i.binding.isEmpty() || s->source.isEmpty()) continue;
      QString what;
      const QJsonObject values = bound_parameters(i.binding, after, &what);
      if (values.isEmpty()) continue;
      auto [entry, fresh] = parameters.try_emplace(s->source);
      if (fresh) entry->second = {doc->pluginParameters(s->source), doc->pluginParameters(s->source)};
      for (auto v = values.begin(); v != values.end(); ++v) entry->second.second.insert(v.key(), v.value());
      if (!what.isEmpty()) notes << QStringLiteral("%1: %2").arg(i.name, what);
    }
  }
  if (changes.empty()) return nullptr;
  if (note != nullptr) *note = notes.join(QStringLiteral("; "));
  return std::make_unique<PlaceResults>(&store, doc, std::move(changes), std::move(parameters), text);
}

std::unique_ptr<QUndoCommand> delete_results(ResultStore& store, const std::vector<ResultId>& sets,
                                             const QString& text) {
  std::vector<std::pair<ResultSet, std::size_t>> before;
  for (ResultId id : sets) {
    const ResultSet* s = store.set(id);
    if (s == nullptr) continue;
    if (std::none_of(s->items.begin(), s->items.end(),
                     [](const ResultItem& i) { return i.kind == ResultItem::Kind::Lines; })) {
      continue;
    }
    before.emplace_back(*s, store.indexOf(id));
  }
  if (before.empty()) return nullptr;
  std::sort(before.begin(), before.end(), [](const auto& a, const auto& b) { return a.second < b.second; });
  return std::make_unique<DeleteResults>(&store, std::move(before), text);
}

}  // namespace nfcad::results
