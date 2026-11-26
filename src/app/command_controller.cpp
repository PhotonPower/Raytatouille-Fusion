#include "app/command_controller.hpp"

#include <QLineEdit>
#include <QStatusBar>
#include <algorithm>
#include <cmath>

#include "commands/input_parser.hpp"
#include "document/document.hpp"
#include "document/selection.hpp"
#include "kernel/geometry_ops.hpp"
#include "results/result_edit.hpp"
#include "results/result_store.hpp"
#include "viewport/viewport.hpp"
#include "viewport/viewport_grid.hpp"

namespace nfcad::app {

using commands::Command;
using commands::ParsedInput;
using commands::Point3;

CommandController::CommandController(document::Document* doc, document::Selection* selection,
                                     viewport::ViewportGrid* grid, QLineEdit* line,
                                     QStatusBar* status, QObject* parent)
    : QObject(parent), doc_(doc), selection_(selection), grid_(grid), line_(line), status_(status) {
  for (viewport::Viewport* v : grid_->views()) {
    connect(v, &viewport::Viewport::pointerMoved, this,
            [this, v](const snap::SnapPoint& p, bool valid, bool snapped) { onPointer(v, p, valid, snapped); });
    connect(v, &viewport::Viewport::pointPicked, this,
            [this, v](const snap::SnapPoint& p, bool snapped, snap::SnapType) { onPicked(v, p, snapped); });
    connect(v, &viewport::Viewport::pointInputFinished, this, &CommandController::finishOrRepeat);
    // right click with no running command: repeat the last one (like Enter on an empty line)
    connect(v, &viewport::Viewport::rightClicked, this, [this] {
      if (!command_) finishOrRepeat();
    });
    connect(v, &viewport::Viewport::enterPressed, this, &CommandController::finishOrRepeat);
    connect(v, &viewport::Viewport::gripsDragged, this, &CommandController::moveGrips);
    connect(v, &viewport::Viewport::textTyped, this, [this](const QString& text) {
      line_->setFocus();
      line_->insert(text);
    });
  }
  connect(line_, &QLineEdit::returnPressed, this, [this] {
    const QString text = line_->text();
    line_->clear();
    submit(text);
  });
}

namespace {
/// A single point for a callback (not repeated with Enter).
class PickPointCommand : public Command {
 public:
  PickPointCommand(QString prompt, std::function<void(const Point3&)> done)
      : prompt_(std::move(prompt)), done_(std::move(done)) {}
  QString id() const override { return QStringLiteral("pick_point"); }
  QString title() const override { return QObject::tr("Pick point"); }
  QString prompt() const override { return prompt_; }
  Result point(const Point3& p, const commands::PlaneFrame&) override {
    if (done_) done_(p);
    return Result::Done;
  }

 private:
  QString prompt_;
  std::function<void(const Point3&)> done_;
};
}  // namespace

CommandController::~CommandController() = default;

void CommandController::pickPoint(const QString& prompt, std::function<void(const Point3&)> done) {
  if (command_) cancel();
  command_ = std::make_unique<PickPointCommand>(prompt, std::move(done));  // last_name_ unchanged
  grid_->setPointInput(true);
  if (grid_->activeView() != nullptr) grid_->activeView()->setFocus();
  emit activeChanged(true);
  refresh();
}

QString CommandController::activeId() const { return command_ ? command_->id() : QString(); }

bool CommandController::start(const QString& name) {
  auto cmd = commands::create_command(name);
  if (!cmd) return false;
  if (command_) cancel();
  last_name_ = cmd->id();
  drawings_.clear();
  drawing_note_.clear();
  cmd->setDocument(doc_);
  if (cmd->usesSelection()) {
    // selected result drawings (rays, a plugin's camera): Move and Rotate take them along
    std::vector<std::uint64_t> drawings;
    if (selection_ != nullptr && results_ != nullptr) {
      for (std::uint64_t id : selection_->results()) {
        if (!results::drawn_lines(*results_, id).empty()) drawings.push_back(id);
      }
    }
    if (cmd->movesDrawings() && !drawings.empty()) {
      cmd->setDrawingWire(results::drawing_wire(*results_, drawings));
      drawings_ = drawings;
    }
    // whole entities in selection order (Boolean difference: first minus the others); for the
    // commands that take them, the picked edges and faces of shells after them
    std::vector<document::Entity> picked;
    std::vector<document::Entity> parts;
    std::vector<commands::GripSet> grips;
    if (selection_ != nullptr) {
      for (const document::SelectionItem& i : selection_->ordered()) {
        const document::Entity* e = doc_->entity(i.entity);
        if (e == nullptr) continue;
        if (i.sub.kind == document::SubElement::Kind::None) {
          picked.push_back(*e);
        } else if (i.sub.kind == document::SubElement::Kind::ControlPoint) {
          if (!cmd->usesGrips()) continue;
          // the selected control points, per curve (grips)
          if (grips.empty() || grips.back().id != e->id) {
            const auto same = std::find_if(grips.begin(), grips.end(), [&](const commands::GripSet& g) { return g.id == e->id; });
            if (same == grips.end()) {
              grips.push_back({e->id, e->geometry, {}});
            } else {
              std::rotate(same, same + 1, grips.end());
            }
          }
          grips.back().indices.push_back(i.sub.index);
        } else if (cmd->usesSubElements()) {
          if (auto part = kernel::part_of(*e->geometry, i.sub)) parts.push_back(document::make_entity(std::move(*part)));
        }
      }
    }
    picked.insert(picked.end(), parts.begin(), parts.end());
    if (!grips.empty()) cmd->setGrips(std::move(grips));
    // commands that need the view's plane already in begin() / finish() (Project: its direction)
    if (grid_->activeView() != nullptr) cmd->setViewPlane(frameOf(grid_->activeView()));
    if (picked.empty() && !drawings.empty() && !cmd->movesDrawings()) {
      status_->showMessage(tr("%1: result drawings can only be moved and rotated").arg(cmd->title()), 6000);
      return true;
    }
    if (!cmd->begin(picked)) {
      status_->showMessage(cmd->message(), 6000);
      return true;  // known command, but nothing to do
    }
    if (cmd->immediate()) {
      command_ = std::move(cmd);
      handle(command_->finish());
      return true;
    }
  }
  command_ = std::move(cmd);
  // typed input before the cursor visits a view refers to the active view's construction plane
  if (grid_->activeView() != nullptr) plane_ = frameOf(grid_->activeView());
  command_->setViewPlane(plane_);
  grid_->setPointInput(true);
  if (grid_->activeView() != nullptr) grid_->activeView()->setFocus();
  emit activeChanged(true);
  refresh();
  return true;
}

void CommandController::cancel() {
  if (!command_) return;
  end(tr("%1 cancelled").arg(command_->title()));
}

void CommandController::finishOrRepeat() {
  if (!command_) {
    if (!last_name_.isEmpty()) start(last_name_);
    return;
  }
  handle(command_->finish());
}

void CommandController::submit(const QString& text) {
  const std::optional<Point3> base = command_ ? command_->basePoint() : std::nullopt;
  const ParsedInput in = commands::parse_input(text, plane_, base);
  switch (in.kind) {
    case ParsedInput::Kind::Empty:
      finishOrRepeat();
      return;
    case ParsedInput::Kind::Name:
      if (!start(in.name)) status_->showMessage(tr("Unknown command '%1'").arg(in.name), 5000);
      return;
    case ParsedInput::Kind::Invalid:
      status_->showMessage(in.error, 5000);
      return;
    case ParsedInput::Kind::Point:
      if (!command_) {
        status_->showMessage(tr("No command is waiting for a point"), 4000);
        return;
      }
      handle(command_->point(in.point, plane_));
      return;
    case ParsedInput::Kind::Number: {
      if (!command_) return;
      command_->setViewPlane(plane_);
      const Command::Result r = command_->number(in.number);
      if (r != Command::Result::Rejected || !command_->message().isEmpty()) {
        handle(r);  // done, or rejected with a reason
        return;
      }
      // a length along the direction from the base point to the cursor
      if (base && cursor_valid_) {
        const Point3 c = constrained(cursor_, false);
        const double dx = c.x - base->x;
        const double dy = c.y - base->y;
        const double dz = c.z - base->z;
        const double len = std::sqrt(dx * dx + dy * dy + dz * dz);
        if (len > 0.0 && in.number > 0.0) {
          const double s = in.number / len;
          handle(command_->point({base->x + s * dx, base->y + s * dy, base->z + s * dz}, plane_));
          return;
        }
      }
      status_->showMessage(tr("A number is not expected here"), 4000);
      return;
    }
  }
}

void CommandController::setOrtho(bool on) {
  if (ortho_ == on) return;
  ortho_ = on;
  emit orthoChanged(on);
  refresh();
}

commands::PlaneFrame CommandController::frameOf(const viewport::Viewport* view) const {
  const viewport::CPlane& c = view->cplane();
  const QVector3D n = c.normal();
  auto p = [](const QVector3D& v) { return Point3{v.x(), v.y(), v.z()}; };
  return {p(c.origin), p(c.u), p(c.v), p(n)};
}

Point3 CommandController::constrained(const Point3& p, bool snapped) const {
  if (!ortho_ || snapped || !command_) return p;
  const auto base = command_->basePoint();
  if (!base) return p;
  // ortho (F8): along the construction-plane axis closest to the cursor direction
  const double d[3] = {p.x - base->x, p.y - base->y, p.z - base->z};
  const double du = d[0] * plane_.u.x + d[1] * plane_.u.y + d[2] * plane_.u.z;
  const double dv = d[0] * plane_.v.x + d[1] * plane_.v.y + d[2] * plane_.v.z;
  const Point3& a = std::abs(du) >= std::abs(dv) ? plane_.u : plane_.v;
  const double s = std::abs(du) >= std::abs(dv) ? du : dv;
  return {base->x + s * a.x, base->y + s * a.y, base->z + s * a.z};
}

void CommandController::onPointer(viewport::Viewport* view, const Point3& p, bool valid,
                                  bool snapped) {
  plane_ = frameOf(view);
  if (command_) command_->setViewPlane(plane_);
  cursor_ = constrained(p, snapped);
  cursor_valid_ = valid;
  refresh();
}

void CommandController::onPicked(viewport::Viewport* view, const Point3& p, bool snapped) {
  if (!command_) return;
  plane_ = frameOf(view);
  command_->setViewPlane(plane_);
  handle(command_->point(constrained(p, snapped), plane_));
}

void CommandController::moveGrips(const QVector3D& delta) {
  if (command_ || selection_ == nullptr) return;  // a running command owns the input
  const nf::Transform move = nf::Transform::translation({delta.x(), delta.y(), delta.z()});
  document::Edit edit;
  for (document::EntityId id : selection_->entities()) {
    std::vector<int> indices;
    for (const document::SubElement& s : selection_->selectedParts(id)) {
      if (s.kind == document::SubElement::Kind::ControlPoint) indices.push_back(s.index);
    }
    const document::Entity* e = doc_->entity(id);
    if (indices.empty() || e == nullptr) continue;
    if (const auto* c = std::get_if<nf::NurbsCurve>(e->geometry.get())) {
      edit.replace.emplace_back(id, std::make_shared<const document::Geometry>(
                                        kernel::with_control_points_moved(*c, indices, move)));
    }
  }
  if (!edit.empty()) doc_->apply(std::move(edit), tr("Move control points"));
}

void CommandController::flush() {
  if (!command_) return;
  document::Edit edit = command_->takeEdit();
  std::unique_ptr<QUndoCommand> drawings;
  if (const auto motion = command_->takeMotion(); motion && results_ != nullptr && !drawings_.empty()) {
    drawings = results::move_results(*results_, doc_, drawings_, *motion, command_->title(), &drawing_note_);
  }
  if (const auto select = command_->takeSelection(); select && selection_ != nullptr) {
    if (!edit.empty()) doc_->apply(std::move(edit), command_->title());
    selection_->apply(*select, document::Selection::Mode::Replace);
    return;
  }
  if (!drawings) {
    if (!edit.empty()) doc_->apply(std::move(edit), command_->title());
    return;
  }
  // objects and drawings moved together: one undo step
  QUndoStack* undo = doc_->undoStack();
  undo->beginMacro(command_->title());
  if (!edit.empty()) doc_->apply(std::move(edit), command_->title());
  undo->push(drawings.release());
  undo->endMacro();
}

void CommandController::handle(Command::Result r) {
  if (!command_) return;
  switch (r) {
    case Command::Result::Continue:
      flush();
      refresh();
      break;
    case Command::Result::Done: {
      flush();
      const QString message = command_->message();
      // e.g. "Viewing pyramid: up +Z, roll 12.50°" – what a moved camera wrote into its plugin
      end(message.isEmpty() && !drawing_note_.isEmpty() ? tr("%1 – %2").arg(command_->title(), drawing_note_)
                                                        : message);
      break;
    }
    case Command::Result::Cancelled:
      end(tr("%1 cancelled").arg(command_->title()));
      break;
    case Command::Result::Rejected: {
      // the command's reason (e.g. "Fillet: radius 5 too large for these curves"), else the prompt
      const QString why = command_->takeMessage();
      if (why.isEmpty()) {
        status_->showMessage(tr("Input not accepted – %1").arg(command_->prompt()), 4000);
      } else {
        status_->showMessage(why, 8000);
      }
      break;
    }
  }
}

void CommandController::end(const QString& message) {
  command_.reset();
  grid_->setPointInput(false);
  for (viewport::Viewport* v : grid_->views()) {
    v->setPreview({});
    v->setCommandSnapPoints({});
  }
  line_->setPlaceholderText(tr("Command:"));
  if (!message.isEmpty()) status_->showMessage(message, message.startsWith(tr("Distance")) ? 0 : 5000);
  emit activeChanged(false);
}

void CommandController::refresh() {
  if (!command_) return;
  line_->setPlaceholderText(command_->prompt() + (ortho_ ? tr("   [Ortho]") : QString()));
  std::vector<std::vector<QVector3D>> preview;
  if (cursor_valid_) {
    for (const commands::Polyline3& pl : command_->preview(cursor_, plane_)) {
      std::vector<QVector3D> v;
      v.reserve(pl.size());
      for (const Point3& p : pl) {
        v.emplace_back(static_cast<float>(p.x), static_cast<float>(p.y), static_cast<float>(p.z));
      }
      preview.push_back(std::move(v));
    }
  }
  const std::vector<Point3> snap_points = command_->snapPoints();
  for (viewport::Viewport* v : grid_->views()) {
    v->setPreview(preview);
    v->setCommandSnapPoints(snap_points);
  }
}

}  // namespace nfcad::app
