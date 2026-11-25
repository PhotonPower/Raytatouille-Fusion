#pragma once

#include <optional>

#include <QJsonObject>
#include <QObject>
#include <QUndoStack>
#include <map>
#include <vector>

#include "document/entity.hpp"

namespace nfcad::document {

/// A combined change applied as one undo step (commands: transforms, Booleans, ...).
struct Edit {
  std::vector<Entity> add;
  std::vector<EntityId> remove;
  std::vector<std::pair<EntityId, GeometryPtr>> replace;  ///< new geometry for an entity
  [[nodiscard]] bool empty() const { return add.empty() && remove.empty() && replace.empty(); }
};

/// Node of the model tree; groups nest (parent 0 = top level).
struct Group {
  GroupId id = 0;
  QString name;
  GroupId parent = 0;
  bool visible = true;
};

/// Changes already applied live (a plugin run) that become one undo step together.
struct LiveChanges {
  std::vector<EntityId> added;                               ///< still in the document
  std::vector<Entity> removed;                               ///< as they were before the run
  std::vector<GroupId> added_groups;                         ///< in creation order
  std::vector<Group> removed_groups;                         ///< empty groups, in removal order
  std::vector<std::pair<EntityId, GeometryPtr>> old_geometry;
  std::vector<std::pair<EntityId, QVariantMap>> old_attributes;
  /// the workflow before the run, if the run changed its model (ADR Nachtrag 1: the workflow
  /// is the truth – a plugin writing into it, e.g. an optimisation, is undone with the run)
  std::optional<QJsonObject> old_workflow;
};

struct Layer {
  LayerId id = 0;
  QString name;
  QColor color;
  bool visible = true;
  bool locked = false;  ///< its objects are shown but cannot be selected (and so not changed)
};

/// What happens to the objects of a layer that is deleted.
enum class LayerContents { MoveToDefault, Delete };

/// The model: entities and layers, undo stack, file path (docs/architecture.md).
/// All changes that the user can undo go through commands on undoStack(); the low-level
/// insert/erase functions below are used by those commands and by loading.
class Document : public QObject {
  Q_OBJECT
 public:
  explicit Document(QObject* parent = nullptr);

  // ---- queries
  [[nodiscard]] const std::map<EntityId, Entity>& entities() const { return entities_; }
  [[nodiscard]] const Entity* entity(EntityId id) const;
  [[nodiscard]] const std::vector<Layer>& layers() const { return layers_; }
  [[nodiscard]] const Layer* layer(LayerId id) const;
  /// Effective display colour: entity colour or its layer's colour.
  [[nodiscard]] QColor displayColor(const Entity& e) const;
  /// Visible if the entity, its layer and all its groups are visible.
  [[nodiscard]] bool isDisplayed(const Entity& e) const;
  /// On a locked layer: shown, but not selectable (and so not changed by commands).
  [[nodiscard]] bool isLocked(const Entity& e) const;
  [[nodiscard]] bool isLocked(EntityId id) const;
  /// The layer new objects go to (drawn, imported, made by plugins); saved with the document.
  [[nodiscard]] LayerId currentLayer() const { return current_layer_; }
  /// Number of entities on a layer.
  [[nodiscard]] std::size_t entityCount(LayerId layer) const;

  // ---- model tree (groups)
  [[nodiscard]] const std::vector<Group>& groups() const { return groups_; }
  [[nodiscard]] const Group* group(GroupId id) const;
  /// True if `id` or one of its ancestors is hidden.
  [[nodiscard]] bool groupHidden(GroupId id) const;
  /// Entities directly or indirectly in a group.
  [[nodiscard]] std::vector<EntityId> entitiesInGroup(GroupId id) const;
  /// Creates a group (one undo step) and moves the entities into it; returns its id.
  GroupId groupEntities(const std::vector<EntityId>& ids, const QString& name, GroupId parent = 0);
  /// Removes a group (one undo step); its entities and subgroups move to its parent.
  void ungroup(GroupId id);
  /// Renames a group (one undo step).
  void renameGroup(GroupId id, const QString& name);
  /// Visibility of entities and groups: a state, not an undo step (like layer visibility), but
  /// saved with the document, so a change marks it modified – as do all visibility changes below.
  void setEntityVisible(EntityId id, bool visible);
  void setGroupVisible(GroupId id, bool visible);
  /// Hides everything except the given entities (and shows them and their groups).
  void isolate(const std::vector<EntityId>& ids);
  /// Shows the entities hidden one by one (Hide, Isolate); layers and groups keep their switches.
  /// Returns how many were hidden.
  std::size_t showHiddenEntities();
  void showAll();

  // ---- attributes (undoable)
  void setAttribute(EntityId id, const QString& key, const QVariant& value);  ///< null: remove

  /// Records changes that were already applied without undo (live updates of a plugin run) as
  /// one undo step: the added entities, the previous geometry and attributes of changed ones.
  void recordApplied(const QString& text, const LiveChanges& changes);

  // ---- low level (undo commands, loading)
  GroupId insertGroup(Group g);  ///< keeps g.id if free, else assigns one
  void eraseGroup(GroupId id);
  void setGroupName(GroupId id, const QString& name);
  void setEntityGroup(EntityId id, GroupId group);
  void setEntityAttributes(EntityId id, QVariantMap attributes);

  [[nodiscard]] QUndoStack* undoStack() { return &undo_; }
  [[nodiscard]] QString filePath() const { return file_path_; }
  void setFilePath(const QString& path) { file_path_ = path; }
  [[nodiscard]] bool isModified() const { return !undo_.isClean() || settings_dirty_; }
  /// After saving: the document counts as unmodified.
  void markSaved();

  // ---- plugin parameters (P4): values of a plugin's parameter panel, saved with the document
  [[nodiscard]] QJsonObject pluginParameters(const QString& plugin) const {
    return plugin_parameters_.value(plugin).toObject();
  }
  [[nodiscard]] const QJsonObject& allPluginParameters() const { return plugin_parameters_; }
  void setPluginParameters(const QString& plugin, const QJsonObject& values);
  /// Something the document keeps besides its content changed (e.g. a new kept result): it now
  /// counts as modified until saved.
  void markKeptChanged();
  void setAllPluginParameters(const QJsonObject& all);  ///< loading

  // ---- node workflow (RTT-Fusion R24): {"model": rtt-fusion-graph version 2, "types": [...],
  // "diagnostics": [...], "plan": ...}, saved with the document; edited in the node editor and by
  // plugins. An old document may hold {"graph": version 1} instead: converted when it is opened.
  [[nodiscard]] const QJsonObject& workflow() const { return workflow_; }
  /// Sets the workflow without an undo step (a plugin's live changes, which become part of the
  /// run's undo step, and what it derives for the editor); marks the document modified.
  void setWorkflow(const QJsonObject& workflow);
  /// An edit of the workflow by the user (node editor): one undo step.
  void editWorkflow(const QJsonObject& workflow, const QString& text = {});
  /// Low level (undo commands): sets the workflow and emits workflowChanged.
  void replaceWorkflow(const QJsonObject& workflow);
  void setWorkflowLoaded(const QJsonObject& workflow) { workflow_ = workflow; }  ///< loading
  /// Asks the GUI to show the node workflow (a plugin set it, even if it did not change).
  void requestWorkflowShown() { emit workflowShowRequested(); }
  /// The block of the node workflow that a plugin computes now (empty: none); not stored.
  void reportWorkflowRunning(const QString& node) { emit workflowRunning(node); }
  /// Up to date (true) / out of date (false) per block, from the plugin's kept results.
  void reportWorkflowState(const QJsonObject& states) { emit workflowState(states); }

  // ---- user operations (undoable)
  /// Adds entities in one undo step; returns their ids.
  std::vector<EntityId> addEntities(std::vector<Entity> entities, const QString& text);
  void removeEntities(const std::vector<EntityId>& ids, const QString& text);
  /// Applies an Edit as one undo step; returns the ids of the added entities.
  std::vector<EntityId> apply(Edit edit, const QString& text);
  /// Moves entities to a layer (one undo step).
  void assignLayer(const std::vector<EntityId>& ids, LayerId layer);

  // ---- layers (user operations): new, rename, colour and delete are undo steps; visibility,
  // lock and the current layer are states (saved with the document, they mark it modified)
  /// Adds a layer (one undo step); returns its id.
  LayerId addLayer(Layer layer);
  void renameLayer(LayerId id, const QString& name);
  void setLayerColor(LayerId id, const QColor& color);
  /// Deletes a layer (one undo step); its objects move to Default or are deleted. The Default
  /// layer (id 0) cannot be deleted (returns false).
  bool removeLayer(LayerId id, LayerContents contents);
  void setLayerVisible(LayerId id, bool visible);
  void setLayerLocked(LayerId id, bool locked);
  void setCurrentLayer(LayerId id);

  // ---- low level (used by undo commands and loading; not undoable)
  /// Inserts an entity. Assigns a new id if e.id == 0.
  EntityId insert(Entity e);
  /// Removes an entity and returns it (for undo).
  Entity erase(EntityId id);
  /// Inserts a layer at `index` (−1: at the end); keeps layer.id if free, else assigns one.
  LayerId insertLayer(Layer layer, int index = -1);
  /// Removes a layer; the current layer falls back to Default if it was this one.
  void eraseLayer(LayerId id);
  /// Name and colour of a layer (visibility and lock stay).
  void changeLayer(LayerId id, const QString& name, const QColor& color);
  /// Sets the current layer without marking the document modified (undo of a deletion).
  void restoreCurrentLayer(LayerId id);
  /// Replaces an entity's geometry (low level, used by undo commands); returns the old one.
  GeometryPtr setGeometry(EntityId id, GeometryPtr geometry);
  /// Sets an entity's layer (low level, used by the undo command).
  void setEntityLayer(EntityId id, LayerId layer);
  /// Removes everything, keeps the default layer, clears the undo stack.
  void clear();
  /// Replaces the content (after loading a file); clears the undo stack. The plugin parameters and
  /// the node workflow of a loaded file are set before `documentReset` is emitted, so that whoever
  /// reacts to it (the node workflow window) sees the loaded state.
  void reset(std::vector<Layer> layers, std::vector<Entity> entities, std::vector<Group> groups = {},
             QJsonObject plugin_parameters = {}, QJsonObject workflow = {}, LayerId current_layer = 0);

 signals:
  void entityAdded(nfcad::document::EntityId id);
  void entityRemoved(nfcad::document::EntityId id);
  void entityChanged(nfcad::document::EntityId id);
  /// Layers were added, removed, renamed, recoloured, shown, hidden, locked, or the current
  /// layer changed.
  void layersChanged();
  /// Groups were added, removed, renamed or changed visibility.
  void groupsChanged();
  /// The modified state changed without an undo step (plugin parameters, saving).
  void modificationChanged(bool modified);
  /// The node workflow was replaced or edited.
  void workflowChanged();
  /// A plugin set its own parameters (ctx.set_params): the panel shows the new values. Not
  /// emitted for edits in the panel itself.
  void pluginParametersSet(const QString& plugin);
  void workflowShowRequested();
  void workflowRunning(const QString& node);
  void workflowState(const QJsonObject& states);
  /// Everything changed (clear / load): views rebuild from scratch.
  void documentReset();

 private:
  void touchLayer(LayerId id);
  void touchEntities(const std::vector<EntityId>& ids);
  /// A change saved with the document but not on the undo stack: modified until saved.
  void markDirty();
  /// The layer of a new entity (kCurrentLayer → the current layer, unknown → Default).
  [[nodiscard]] LayerId resolveLayer(LayerId layer) const;

  std::map<EntityId, Entity> entities_;
  std::vector<Layer> layers_;
  std::vector<Group> groups_;
  QJsonObject plugin_parameters_;
  QJsonObject workflow_;
  LayerId current_layer_ = 0;
  bool settings_dirty_ = false;
  EntityId next_id_ = 1;
  QUndoStack undo_;
  QString file_path_;
};

}  // namespace nfcad::document
