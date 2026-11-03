"""
Virtual Measurements (Drifts / Responses) Dialog.
Allows users to define custom linear combinations of nodal degrees of freedom.
"""

import uuid

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QComboBox, QMessageBox, QLineEdit, QRadioButton, QButtonGroup,
    QSplitter, QWidget, QFormLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut

from app.ui.theme import apply_dialog_style, COLORS
from core.units import unit_registry

AUTO_DRIFT_TAG = "_auto_smart_drift_batch"

_DRIFT_AXIS_TO_DOF = {"U1": "U1", "U2": "U2", "U3": "U3"}

def _axis_choice_to_dof(axis_choice):
    """'Drift X (U1)' / etc. -> 'U1' / 'U2' / 'U3'."""
    for dof in ("U1", "U2", "U3"):
        if dof in axis_choice:
            return dof
    return "U1"

def _resolve_candidate_elements(model, selected_elem_ids, selected_node_ids):
    """
    Candidate elements = whatever frames are directly selected, plus any
    element whose *both* endpoints are among the selected joints. The
    second clause is what makes a pure-joint selection work too; it's a
    harmless no-op superset when the frames were already selected directly
    (e.g. via a canvas box-select, which populates both lists at once).
    """
    node_set = set(selected_node_ids)
    candidates = set(selected_elem_ids)
    for eid, el in model.elements.items():
        if el.node_i.id in node_set and el.node_j.id in node_set:
            candidates.add(eid)
    return candidates

def _find_column_elements(model, elem_ids, tolerance):
    """
    Elements from elem_ids whose two end nodes sit within `tolerance` of
    each other in X,Y — i.e. are genuinely vertical (or near-vertical)
    frame segments. This is element/topology based, not naive node-XY
    clustering, so it can't be fooled by two unrelated nodes that happen
    to share X,Y without an element actually connecting them.
    """
    verticals = []
    for eid in elem_ids:
        el = model.elements.get(eid)
        if el is None:
            continue
        dx = el.node_i.x - el.node_j.x
        dy = el.node_i.y - el.node_j.y
        if (dx * dx + dy * dy) ** 0.5 <= tolerance:
            verticals.append(el)
    return verticals

def _chain_column_lines(vertical_elements):
    """
    Groups vertical elements into column lines by shared-node connectivity
    (union-find), then returns each line as its nodes sorted bottom-to-top
    by Z. Sorting is per-line, not against any global story list, so this
    still works for columns that don't span every floor (mezzanines,
    setbacks, partial-height columns).
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    node_lookup = {}
    for el in vertical_elements:
        node_lookup[el.node_i.id] = el.node_i
        node_lookup[el.node_j.id] = el.node_j
        union(el.node_i.id, el.node_j.id)

    groups = {}
    for nid in node_lookup:
        groups.setdefault(find(nid), []).append(nid)

    lines = []
    for nids in groups.values():
        if len(nids) < 2:
            continue
        nodes = sorted((node_lookup[n] for n in nids), key=lambda n: n.z)
        lines.append(nodes)
    return lines

def _nearest_grid_label(value, grid_lines):
    """Nearest gridline id to `value` along one axis, or None if that axis
    has no gridlines defined. Coordinates and grid ordinates are both
    stored in the model's internal (base) units, so no conversion needed."""
    if not grid_lines:
        return None
    best = min(grid_lines, key=lambda gl: abs(gl['ord'] - value))
    return best['id']

def _name_for_pair(model, bot_node, top_node, axis_choice):
    grid = getattr(model, 'grid', None)
    x_label = _nearest_grid_label(bot_node.x, getattr(grid, 'x_lines', None)) if grid else None
    y_label = _nearest_grid_label(bot_node.y, getattr(grid, 'y_lines', None)) if grid else None
                                                                          
    story_label = _nearest_grid_label(bot_node.z, getattr(grid, 'z_lines', None)) if grid else None

    if x_label is not None and y_label is not None:
        col_label = f"Col {x_label}{y_label}"
    else:
        col_label = f"Col ({bot_node.x:.2f}, {bot_node.y:.2f})"

    story_part = f" - {story_label}" if story_label is not None else ""
    axis_part = f" ({axis_choice[:7]})"
    return f"{col_label}{story_part}{axis_part}"

def generate_bulk_drift_measurements(model, selected_elem_ids, selected_node_ids,
                                      tolerance, axis_choice):
    """
    Pure-data core of Bulk Smart Drift (no Qt, easy to test standalone).
    Returns a dict of new measurements shaped exactly like
    VirtualMeasurementsDialog.working_data entries — {name, type, factors}
    — each additionally stamped with AUTO_DRIFT_TAG=True.
    """
    dof = _axis_choice_to_dof(axis_choice)

    candidate_elem_ids = _resolve_candidate_elements(model, selected_elem_ids, selected_node_ids)
    verticals = _find_column_elements(model, candidate_elem_ids, tolerance)
    lines = _chain_column_lines(verticals)

    new_measurements = {}
    for nodes in lines:
        for bot_node, top_node in zip(nodes, nodes[1:]):
            name = _name_for_pair(model, bot_node, top_node, axis_choice)
            new_measurements[str(uuid.uuid4())] = {
                "name": name,
                "type": "Translational",
                "factors": {
                    str(top_node.id): {dof: 1.0},
                    str(bot_node.id): {dof: -1.0},
                },
                AUTO_DRIFT_TAG: True,
            }
    return new_measurements

class CopyableEditableTableWidget(QTableWidget):
    """
    QTableWidget with Excel-style Ctrl+C and Ctrl+V.
    Allows pasting factors directly from spreadsheet calculations.
    """
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
        elif event.matches(QKeySequence.StandardKey.Paste):
            self.paste_selection()
        elif event.key() == Qt.Key.Key_Delete:
            self.clear_selection_contents()
        else:
            super().keyPressEvent(event)

    def copy_selection(self):
        indexes = self.selectedIndexes()
        if not indexes: return

        rows = sorted(set(i.row() for i in indexes))
        cols = sorted(set(i.column() for i in indexes))
        selected_set = set((i.row(), i.column()) for i in indexes)

        lines = []
        for r in rows:
            line_vals = []
            for c in cols:
                if (r, c) in selected_set:
                    item = self.item(r, c)
                    line_vals.append(item.text() if item else "")
                else:
                    line_vals.append("")
            lines.append("\t".join(line_vals))

        QApplication.clipboard().setText("\n".join(lines))

    def paste_selection(self):
        text = QApplication.clipboard().text()
        if not text: return

        rows = text.strip('\n').split('\n')
        current_row = self.currentRow()
        current_col = self.currentColumn()

        if current_row < 0 or current_col < 0:
            return

        for r_offset, row in enumerate(rows):
            columns = row.split('\t')
            target_row = current_row + r_offset
            
            if target_row >= self.rowCount():
                self.insertRow(target_row)
                
            for c_offset, val in enumerate(columns):
                target_col = current_col + c_offset
                if target_col < self.columnCount():
                    self.setItem(target_row, target_col, QTableWidgetItem(val))

    def clear_selection_contents(self):
        for item in self.selectedItems():
            item.setText("")

class SelectJointsDialog(QDialog):
    """3D viewport picker, adapted directly from Plot Functions."""
    def __init__(self, main_window, max_selection=None, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.main_window = main_window
        self.max_selection = max_selection
        self._original_selection = list(getattr(main_window, 'selected_node_ids', []))
        self._picked_ids = []

        self.setWindowTitle("Select Joints")
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(300, 140)

        layout = QVBoxLayout(self)
        msg = QLabel("Click joints in the 3D view (Ctrl+click to add more), then press OK.")
        if max_selection:
            msg.setText(f"Select EXACTLY {max_selection} joints in the 3D view, then press OK.")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self.count_label)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        if hasattr(main_window, 'status'):
            main_window.status.showMessage("Selecting joints in 3D view...")

        self.main_window.selected_node_ids = []
        self._restore_original_selection(force_update=True)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(150)
        self._poll_timer.timeout.connect(self._update_count)
        self._poll_timer.start()
        self._update_count()

    def _update_count(self):
        n = len(getattr(self.main_window, 'selected_node_ids', []))
        self.count_label.setText(f"{n} joint{'s' if n != 1 else ''} currently selected")

    def picked_joint_ids(self):
        return list(self._picked_ids)

    def _restore_original_selection(self, force_update=False):
        mw = self.main_window
        if not hasattr(mw, 'selected_node_ids'):
            return
        if not force_update:
            mw.selected_node_ids = list(self._original_selection)
        for cvs in [getattr(mw, 'canvas', None), getattr(mw, 'canvas2', None)]:
            if cvs is not None and hasattr(cvs, 'update_selection_overlay'):
                cvs.update_selection_overlay(
                    getattr(mw, 'selected_ids', []),
                    mw.selected_node_ids,
                    getattr(mw, 'selected_area_ids', [])
                )

    def _on_ok(self):
        current_selection = getattr(self.main_window, 'selected_node_ids', [])
        if self.max_selection and len(current_selection) != self.max_selection:
            QMessageBox.warning(self, "Invalid Selection", f"Please select exactly {self.max_selection} joints.")
            return

        self._poll_timer.stop()
        self._picked_ids = [str(n) for n in current_selection]
        self._restore_original_selection()
        self.accept()

    def _on_cancel(self):
        self._poll_timer.stop()
        self._restore_original_selection()
        self.reject()

    def closeEvent(self, event):
        self._poll_timer.stop()
        self._restore_original_selection()
        super().closeEvent(event)

class BulkSmartDriftDialog(QDialog):
    """Tiny modal for the one setting bulk generation needs: a tolerance.
    Axis is taken from the main dialog's existing Drift X/Y/Z combo, so it
    isn't duplicated here."""
    def __init__(self, default_tol_display, unit_name, n_candidates, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Bulk Drift")
        self.setModal(True)
        self.resize(360, 160)
        self.tolerance_display = None

        layout = QVBoxLayout(self)
        msg = QLabel(
            f"{n_candidates} frame(s)/joint(s) currently selected on the 3D "
            f"model.\n\nVertical elements (within tolerance) will be chained "
            f"into column lines, and one drift measurement will be generated "
            f"per story per column, using the axis currently chosen above."
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("XY Tolerance:"))
        self.tol_edit = QLineEdit(f"{default_tol_display:g}")
        self.tol_edit.setFixedWidth(80)
        tol_row.addWidget(self.tol_edit)
        tol_row.addWidget(QLabel(unit_name))
        tol_row.addStretch()
        layout.addLayout(tol_row)

        note = QLabel(
            "Adds new measurements on top of whatever's already in the list "
            "— nothing gets removed. Running this again on the same "
            "selection will add duplicates."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(note)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("Generate")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_ok(self):
        try:
            val = float(self.tol_edit.text())
            if val <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter a valid positive tolerance value.")
            return
        self.tolerance_display = val
        self.accept()

class VirtualMeasurementsDialog(QDialog):
    def __init__(self, model, main_window, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.model = model
        self.main_window = main_window
        self.setWindowTitle("Virtual Measurements (Drifts / Responses)")
        self.resize(950, 500)

        if not hasattr(self.model, 'virtual_measurements'):
            self.model.virtual_measurements = {}

        import copy
        self.working_data = copy.deepcopy(self.model.virtual_measurements)
        self.current_item_id = None

        self._build_ui()
        self._populate_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_layout.addWidget(QLabel("Defined Measurements"))
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.currentItemChanged.connect(self._on_list_selection_changed)
        left_layout.addWidget(self.list_widget, 1)

        remove_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.list_widget)
        remove_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        remove_shortcut.activated.connect(self._on_remove)

        btn_row_left = QHBoxLayout()
        btn_add = QPushButton("Add New")
        btn_add.setObjectName("primary")
        btn_add.clicked.connect(self._on_add)
        btn_remove = QPushButton("Remove")
        btn_remove.setObjectName("danger")
        btn_remove.setToolTip("Removes all selected measurements. Ctrl/Shift+click "
                               "to multi-select, or press Delete.")
        btn_remove.clicked.connect(self._on_remove)
        btn_row_left.addWidget(btn_add)
        btn_row_left.addWidget(btn_remove)
        left_layout.addLayout(btn_row_left)

        btn_bulk_drift = QPushButton("Bulk Drift...")
        btn_bulk_drift.setObjectName("secondary")
        btn_bulk_drift.setToolTip(
            "Uses the frames/joints currently selected in the 3D model. "
            "Detects vertical column lines and generates one drift "
            "measurement per story per column, along the axis chosen above."
        )
        btn_bulk_drift.clicked.connect(self._on_bulk_smart_drift)
        left_layout.addWidget(btn_bulk_drift)

        splitter.addWidget(left_panel)

        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(10, 0, 0, 0)

        form_layout = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_name_changed)
        form_layout.addRow("Measurement Name:", self.name_edit)

        self.type_group = QButtonGroup(self)
        type_widget = QWidget()
        type_layout = QHBoxLayout(type_widget)
        type_layout.setContentsMargins(0, 0, 0, 0)
        
        self.rb_trans = QRadioButton("Translational")
        self.rb_rot = QRadioButton("Rotational")
        self.type_group.addButton(self.rb_trans)
        self.type_group.addButton(self.rb_rot)
        self.rb_trans.setChecked(True)
        
        type_layout.addWidget(self.rb_trans)
        type_layout.addWidget(self.rb_rot)
        type_layout.addStretch()
        form_layout.addRow("Response Type:", type_widget)
        
        right_layout.addLayout(form_layout)

        tools_row = QHBoxLayout()
        btn_pick = QPushButton("Pick Nodes from 3D Model")
        btn_pick.setObjectName("secondary")
        btn_pick.clicked.connect(self._on_pick_nodes)
        
        btn_auto_drift = QPushButton("Drift Generator")
        btn_auto_drift.setObjectName("primary")
        btn_auto_drift.setToolTip("Pick exactly 2 nodes. Assigns +1.0 to the top node, -1.0 to the bottom node.")
        btn_auto_drift.clicked.connect(self._on_auto_drift)
        
        self.drift_axis_combo = QComboBox()
        self.drift_axis_combo.addItems(["Drift X (U1)", "Drift Y (U2)", "Drift Z (U3)"])
        
        btn_add_row = QPushButton("+ Row")
        btn_add_row.setObjectName("secondary")
        btn_add_row.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))

        tools_row.addWidget(btn_pick)
        tools_row.addStretch()
        tools_row.addWidget(QLabel("Axis:"))
        tools_row.addWidget(self.drift_axis_combo)
        tools_row.addWidget(btn_auto_drift)
        tools_row.addSpacing(20)
        tools_row.addWidget(btn_add_row)
        right_layout.addLayout(tools_row)

        self.table = CopyableEditableTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Joint ID", "U1", "U2", "U3", "R1", "R2", "R3"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        right_layout.addWidget(self.table, 1)

        splitter.addWidget(self.right_panel)
        splitter.setSizes([250, 700])

        self.right_panel.setEnabled(False)

        layout.addSpacing(10)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _populate_list(self):
        self.list_widget.clear()
        for v_id, data in self.working_data.items():
            item = QListWidgetItem(data["name"])
            item.setData(Qt.ItemDataRole.UserRole, v_id)
            self.list_widget.addItem(item)
            
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _save_current_editor_state(self):
        if not self.current_item_id or self.current_item_id not in self.working_data:
            return

        data = self.working_data[self.current_item_id]
        data["name"] = self.name_edit.text().strip() or "Unnamed"
        data["type"] = "Translational" if self.rb_trans.isChecked() else "Rotational"
        
        factors = {}
        for r in range(self.table.rowCount()):
            j_item = self.table.item(r, 0)
            if not j_item or not j_item.text().strip():
                continue
                
            jid = j_item.text().strip()
            row_factors = {}
            dofs = ["U1", "U2", "U3", "R1", "R2", "R3"]
            
            has_value = False
            for c, dof in enumerate(dofs, start=1):
                val_item = self.table.item(r, c)
                if val_item and val_item.text().strip():
                    try:
                        val = float(val_item.text().strip())
                        if val != 0.0:
                            row_factors[dof] = val
                            has_value = True
                    except ValueError:
                        pass
                        
            if has_value:
                factors[jid] = row_factors
                
        data["factors"] = factors

    def _on_list_selection_changed(self, current, previous):
        if previous:
            self._save_current_editor_state()
                                                                           
            prev_id = previous.data(Qt.ItemDataRole.UserRole)
            if prev_id in self.working_data:
                previous.setText(self.working_data[prev_id]["name"])

        if not current:
            self.current_item_id = None
            self.right_panel.setEnabled(False)
            self.table.setRowCount(0)
            self.name_edit.clear()
            return

        self.right_panel.setEnabled(True)
        self.current_item_id = current.data(Qt.ItemDataRole.UserRole)
        data = self.working_data[self.current_item_id]

        self.name_edit.blockSignals(True)
        self.name_edit.setText(data["name"])
        self.name_edit.blockSignals(False)

        if data.get("type") == "Rotational":
            self.rb_rot.setChecked(True)
        else:
            self.rb_trans.setChecked(True)

        self.table.setRowCount(0)
        factors = data.get("factors", {})
        
        for jid, dof_dict in factors.items():
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(jid)))
            
            dofs = ["U1", "U2", "U3", "R1", "R2", "R3"]
            for c, dof in enumerate(dofs, start=1):
                val = dof_dict.get(dof, 0.0)
                if val != 0.0:
                    self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def _on_name_changed(self, text):
        item = self.list_widget.currentItem()
        if item:
            item.setText(text.strip() or "Unnamed")

    def _on_add(self):
        self._save_current_editor_state()
        
        import uuid
        new_id = str(uuid.uuid4())
        name = f"Measurement {len(self.working_data) + 1}"
        
        self.working_data[new_id] = {
            "name": name,
            "type": "Translational",
            "factors": {}
        }
        
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, new_id)
        self.list_widget.addItem(item)
        self.list_widget.setCurrentItem(item)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _on_remove(self):
        items = self.list_widget.selectedItems()
        if not items:
            return

        if len(items) > 1:
            reply = QMessageBox.question(
                self, "Remove Measurements",
                f"Remove {len(items)} selected measurements?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        removed_ids = {item.data(Qt.ItemDataRole.UserRole) for item in items}
        if self.current_item_id in removed_ids:
            self.current_item_id = None

        for item in sorted(items, key=lambda it: self.list_widget.row(it), reverse=True):
            self.list_widget.takeItem(self.list_widget.row(item))

        for v_id in removed_ids:
            self.working_data.pop(v_id, None)

    def _launch_picker(self, callback, max_selection=None):
        my_pos = self.pos()
        self.hide()

        picker = SelectJointsDialog(self.main_window, max_selection=max_selection, parent=self.main_window)
        picker.move(my_pos)
        
        def on_picker_finished(result):
            picked_ids = picker.picked_joint_ids() if result == int(QDialog.DialogCode.Accepted) else None
            picker.deleteLater()
            
            self.show()
            self.raise_()
            self.activateWindow()
            
            if picked_ids:
                callback(picked_ids)
                
        picker.finished.connect(on_picker_finished)
        picker.show()

    def _on_pick_nodes(self):
        self._launch_picker(self._handle_picked_nodes)

    def _handle_picked_nodes(self, picked_ids):
        existing_ids = []
        for r in range(self.table.rowCount()):
            j_item = self.table.item(r, 0)
            if j_item and j_item.text().strip():
                existing_ids.append(j_item.text().strip())

        for jid in picked_ids:
            if jid not in existing_ids:
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(jid))

    def _on_auto_drift(self):
        self._launch_picker(self._handle_auto_drift, max_selection=2)

    def _handle_auto_drift(self, picked_ids):
        if len(picked_ids) != 2:
            return

        nodes = []
        for jid in picked_ids:
            n = self.model.nodes.get(int(jid)) if jid.isdigit() else self.model.nodes.get(jid)
            if n:
                nodes.append(n)

        if len(nodes) != 2:
            QMessageBox.warning(self, "Error", "Could not locate the selected nodes in the model database.")
            return

        nodes.sort(key=lambda nd: nd.z, reverse=True)
        top_node = nodes[0]
        bot_node = nodes[1]

        axis_choice = self.drift_axis_combo.currentText()
        if "U1" in axis_choice: col_idx = 1
        elif "U2" in axis_choice: col_idx = 2
        else: col_idx = 3

        self.table.setRowCount(0)

        self.table.insertRow(0)
        self.table.setItem(0, 0, QTableWidgetItem(str(top_node.id)))
        self.table.setItem(0, col_idx, QTableWidgetItem("1.0"))

        self.table.insertRow(1)
        self.table.setItem(1, 0, QTableWidgetItem(str(bot_node.id)))
        self.table.setItem(1, col_idx, QTableWidgetItem("-1.0"))

        if self.name_edit.text().startswith("Measurement "):
            self.name_edit.setText(f"Drift {top_node.id}-{bot_node.id} ({axis_choice[:7]})")
            
    def _on_bulk_smart_drift(self):
        self._save_current_editor_state()

        selected_elem_ids = set(getattr(self.main_window, 'selected_ids', []))
        selected_node_ids = set(getattr(self.main_window, 'selected_node_ids', []))
        candidate_elem_ids = _resolve_candidate_elements(self.model, selected_elem_ids, selected_node_ids)

        if not candidate_elem_ids:
            QMessageBox.information(
                self, "Nothing Selected",
                "Select some frames (or joints) on the 3D model first, then "
                "run Bulk Drift again."
            )
            return

        default_tol_display = unit_registry.to_display_length(0.005)
        opt_dlg = BulkSmartDriftDialog(
            default_tol_display, unit_registry.length_unit_name,
            len(candidate_elem_ids), parent=self
        )
        if opt_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        tolerance = unit_registry.from_display_length(opt_dlg.tolerance_display)
        axis_choice = self.drift_axis_combo.currentText()

        new_measurements = generate_bulk_drift_measurements(
            self.model, selected_elem_ids, selected_node_ids, tolerance, axis_choice
        )

        if not new_measurements:
            QMessageBox.information(
                self, "No Columns Found",
                "No vertical elements (within tolerance) were found in the "
                "current selection."
            )
            return

        self.working_data.update(new_measurements)
        self._populate_list()

        if hasattr(self.main_window, 'status'):
            self.main_window.status.showMessage(
                f"Bulk Drift: added {len(new_measurements)} measurement(s)."
            )

    def accept(self):
        self._save_current_editor_state()
        self.model.virtual_measurements = self.working_data
        super().accept()
