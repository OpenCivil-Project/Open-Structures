"""
model_tree.py
Dynamic model-browser sidebar for OpenCivil.

Design intent (per Ahmed):
- No hardcoded per-category UI logic. The tree discovers what's on the
  live StructuralModel instance and builds itself from that. Add a new
  `self.whatever = {}` container to StructuralModel and it shows up here
  with zero changes to this file.
- Single click on a leaf -> select that entity on the canvas (reuses
  existing selection + draw_both_canvases pipeline).
- Double click on a leaf -> expand/collapse "detail" children (loads,
  section, material) resolved generically off the object's own
  attributes, not a hardcoded per-type switch.
- Delete -> reuses main_window.delete_current_selection() /
  CmdDeleteSelection, so undo/redo just works.
"""

from PyQt6.QtWidgets import (QDockWidget, QTreeWidget, QTreeWidgetItem, QWidget,
                              QVBoxLayout, QLineEdit, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from app.ui.theme import apply_dock_style, COLORS

_IGNORE_ATTRS = {"functions", "th_functions", "plot_functions", "graphics_settings"}

_LABEL_OVERRIDES = {
    "nodes": "Joints",
    "elements": "Frame Elements",
    "area_elements": "Area Elements",
    "load_combos": "Load Combinations",
}

CATEGORY = "category"
ENTITY = "entity"
DETAIL = "detail"

def _label_for(attr_name):
    return _LABEL_OVERRIDES.get(attr_name, attr_name.replace("_", " ").title())

def _is_scalar(value):
    return value is None or isinstance(value, (str, int, float, bool))

def _is_leaf(value):
    """True if this value is the end of the chain - nothing further to
    drill into. A short list/tuple of scalars (coords, a color triple)
    counts as a leaf too so it renders inline instead of costing another
    double-click for no benefit."""
    if _is_scalar(value):
        return True
    if isinstance(value, (list, tuple)):
        return len(value) == 0 or all(_is_scalar(v) for v in value)
    if isinstance(value, dict):
        return len(value) == 0
    if hasattr(value, "__dict__"):
        return False
    return True                                                            

def _format_leaf(value):
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(_format_leaf(v) for v in value) + ")"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)

def _iter_children(value):
    """Generic one-level walk of ANY value - dict, list/tuple, or a
    plain object's own instance attributes via vars(). No per-class
    knowledge required: this is what lets 'go deeper' work on Materials,
    Sections, Loads, or anything else without adding a branch here."""
    if isinstance(value, dict):
        return list(value.items())
    if isinstance(value, (list, tuple)):
        return [(f"[{i}]", v) for i, v in enumerate(value)]
    if hasattr(value, "__dict__"):
        return [(k, v) for k, v in vars(value).items() if not k.startswith("_")]
    return []

class _SelectableTreeWidget(QTreeWidget):
    """QTreeWidget that emits a plain signal on Delete/Backspace, so the
    dock doesn't need a keyPressEvent override wired through Qt's normal
    widget subclassing (kept as a tiny separate class rather than
    overriding ModelTreeDock itself, since QDockWidget doesn't get key
    events the child widget gets)."""
    delete_key_pressed = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_key_pressed.emit()
            return
        super().keyPressEvent(event)

def _display_name(obj, fallback_id):
    """Best-effort human label for an entity: .name if present, else id."""
    name = getattr(obj, "name", None)
    if isinstance(obj, dict):
                                                                                 
        name = obj.get("name") or obj.get("id")
    if name:
        return f"{name}"
    return f"#{fallback_id}"

class ModelTreeReader:
    """Pure data layer: introspects a StructuralModel, no Qt here."""

    def __init__(self, model):
        self.model = model

    def categories(self):
        """
        Yields (attr_name, label, {id: obj}) for every non-empty
        dict container on the model that isn't in the ignore list.
        Discovered dynamically via vars(model) - not a fixed list.
        """
        if self.model is None:
            return
        for attr_name, value in vars(self.model).items():
            if attr_name.startswith("_") or attr_name in _IGNORE_ATTRS:
                continue
            if isinstance(value, dict) and value:
                yield attr_name, _label_for(attr_name), value
            elif attr_name == "rebar_sizes" and isinstance(value, list) and value:
                                                                             
                yield attr_name, _label_for(attr_name), {b["id"]: b for b in value if "id" in b}

    def details_for(self, attr_name, entity_id, obj):
        """
        First-level children for an entity's double-click expansion.
        Everything the object itself owns (section, material, name,
        beta, coords, whatever) comes for free from _iter_children -
        that's the generic walk, works for ANY entity type with zero
        per-type code here.

        The one thing that can't come from vars(obj): loads. They live
        in a separate flat list on the model (model.loads) rather than
        as an attribute of the entity, so they need an explicit lookup
        by id - this is the only entity-specific knowledge in this file.
        """
        details = list(_iter_children(obj))

        loads = getattr(self.model, "loads", [])
        matched = [
            ld for ld in loads
            if entity_id in (
                getattr(ld, "element_id", None),
                getattr(ld, "node_id", None),
                getattr(ld, "cable_id", None),
            )
        ]
        if matched:
            details.append(("Loads", matched))

        return details

class ModelTreeDock(QDockWidget):
    """
    Dockable, closable/minimizable sidebar. Owns a QTreeWidget rebuilt
    from ModelTreeReader whenever the model changes, and kept in sync
    with canvas selection in both directions.
    """

    selection_requested = pyqtSignal(dict)                                                                                                          
    delete_requested = pyqtSignal()

    _CATEGORY_TO_SELECTION_KEY = {
        "nodes": "nodes",
        "elements": "elements",
        "area_elements": "areas",
        "links": "links",
        "tendons": "tendons",
        "cables": "cables",
    }

    def __init__(self, main_window, parent=None):
        super().__init__("Model Browser", parent)
        self.main_window = main_window
        self.reader = None

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter...")
        self.search_box.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_box)

        self.tree = _SelectableTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.delete_key_pressed.connect(self.delete_requested.emit)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.tree)

        self.setWidget(container)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        apply_dock_style(self)

        self._id_to_item = {}                                                             

    def refresh(self):
        """Full rebuild from the current model. Call on any model change."""
        model = getattr(self.main_window, "model", None)
        self.reader = ModelTreeReader(model)
        self.tree.clear()
        self._id_to_item.clear()

        for attr_name, label, contents in self.reader.categories():
            cat_item = QTreeWidgetItem([f"{label} ({len(contents)})"])
            cat_item.setData(0, Qt.ItemDataRole.UserRole, (CATEGORY, attr_name, None))
            cat_font = cat_item.font(0)
            cat_font.setBold(True)
            cat_item.setFont(0, cat_font)
            cat_item.setForeground(0, QColor(COLORS["text_secondary"]))
            self.tree.addTopLevelItem(cat_item)

            for entity_id, obj in contents.items():
                leaf = QTreeWidgetItem([_display_name(obj, entity_id)])
                leaf.setData(0, Qt.ItemDataRole.UserRole, (ENTITY, attr_name, entity_id))
                cat_item.addChild(leaf)
                self._id_to_item[(attr_name, entity_id)] = leaf

    def _on_item_clicked(self, item, _col):
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload or payload[0] != ENTITY:
            return
        _kind, attr_name, entity_id = payload
        sel_key = self._CATEGORY_TO_SELECTION_KEY.get(attr_name)
        if sel_key is None:
            return                                                               
        self.selection_requested.emit({sel_key: [entity_id]})

    def _on_item_double_clicked(self, item, _col):
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        kind = payload[0]

        if kind not in (ENTITY, DETAIL):
            return

        if item.childCount():
            item.takeChildren()
            return

        if kind == ENTITY:
            if self.reader is None:
                return
            _kind, attr_name, entity_id = payload
            obj = getattr(self.reader.model, attr_name, {}).get(entity_id)
            if obj is None:
                return
            pairs = self.reader.details_for(attr_name, entity_id, obj)
        elif kind == DETAIL:
            _kind, value = payload
            if _is_leaf(value):
                return                                   
            pairs = _iter_children(value)

        self._populate_children(item, pairs)

    def _populate_children(self, item, pairs):
        """Renders one level of (label, value) pairs generically. A leaf
        value prints inline as 'label: value'; anything else prints just
        the label and becomes double-clickable to go one level deeper -
        this is what makes the whole chain drillable without knowing in
        advance how deep any given branch goes."""
        for label, value in pairs:
            if _is_leaf(value):
                text = f"{label}: {_format_leaf(value)}"
            elif isinstance(value, (list, tuple)):
                text = f"{label} [{len(value)}]"
            else:
                text = f"{label} ({type(value).__name__})"
            child = QTreeWidgetItem([text])
            child.setData(0, Qt.ItemDataRole.UserRole, (DETAIL, value))
            item.addChild(child)
        item.setExpanded(True)

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload or payload[0] != ENTITY:
            return
        if item not in self.tree.selectedItems():
            self.tree.setCurrentItem(item)                                                      
        menu = QMenu(self.tree)
        delete_action = menu.addAction("Delete")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen == delete_action:
            self.delete_requested.emit()

    def _apply_filter(self, text):
        text = text.lower().strip()
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
                                                                        
            category_matches = bool(text) and text in cat_item.text(0).lower()
            visible_children = 0
            for j in range(cat_item.childCount()):
                leaf = cat_item.child(j)
                match = category_matches or (text in leaf.text(0).lower())
                leaf.setHidden(bool(text) and not match)
                if not leaf.isHidden():
                    visible_children += 1
            cat_item.setHidden(bool(text) and visible_children == 0)
            if text:
                cat_item.setExpanded(visible_children > 0)

    def sync_selection(self, sel_nodes=None, sel_elems=None, sel_areas=None,
                        sel_links=None, sel_tendons=None, sel_cables=None):
        """Highlight tree items matching the canvas's current selection."""
        self.tree.clearSelection()
        pairs = []
        for attr_name, ids in (
            ("nodes", sel_nodes), ("elements", sel_elems), ("area_elements", sel_areas),
            ("links", sel_links), ("tendons", sel_tendons), ("cables", sel_cables),
        ):
            for eid in (ids or []):
                pairs.append((attr_name, eid))

        first = None
        for pair in pairs:
            item = self._id_to_item.get(pair)
            if item:
                item.setSelected(True)
                first = first or item
        if first:
            self.tree.scrollToItem(first)

    def selected_entity_ids(self):
        """Returns a dict of category attr_name -> [ids] for whatever's
        checked/selected in the tree right now, for delete."""
        out = {}
        for item in self.tree.selectedItems():
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if payload and payload[0] == ENTITY:
                _kind, attr_name, entity_id = payload
                out.setdefault(attr_name, []).append(entity_id)
        return out
