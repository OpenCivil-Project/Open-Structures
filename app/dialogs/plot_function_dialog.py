"""
Plot Function Display Dialog — OpenCivil Time History Plot System.

Self-contained: reads result files via plot_function_sources.py, optionally
taps into AnimationManager for two-way scrub sync (same hub DeformedShapeDialog
uses), never touches the model or any other dialog's state.

Intended wiring in main.py (later):
    if has_ltha_results(self.model):
        self.btn_plot_functions.setEnabled(not editable)   # same gate as btn_deform
    ...
    dlg = PlotFunctionDisplayDialog(self, self.model, self.canvas.animation_manager)
    dlg.exec()

Requires: pyqtgraph  (pip install pyqtgraph --break-system-packages)
"""

import os
import csv
import glob
import json

import numpy as np
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QComboBox, QMessageBox, QFileDialog, QLineEdit, QSpinBox,
    QDoubleSpinBox, QRadioButton, QButtonGroup, QCheckBox, QGroupBox,
    QSplitter, QWidget, QFormLayout, QGridLayout, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor

import pyqtgraph as pg

from core.units import unit_registry, UnitConverter
from app.ui.theme import apply_dialog_style, COLORS
from plot_function_sources import (
    LTHACaseData, PLOT_FUNCTION_TYPES, DOF_LABELS,
    JointResponseSource, ReactionSource, BaseReactionSource, GroundMotionSource,
)

UNIT_SYSTEMS = [
    "kN, m, C", "N, m, C", "N, mm, C", "kN, mm, C",
    "Tonf, m, C", "kgf, m, C", "kip, ft, F",
]

pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')
                                                                          
pg.setConfigOption('antialias', False)

CURVE_COLORS = [
    "#1f3d5c", "#b5451b", "#3f6b3f", "#7a4b8a",
    "#a68a2e", "#3a7a8c", "#8c3a5c", "#555555",
]

FORCE_COMPONENTS = ["FX", "FY", "FZ", "MX", "MY", "MZ"]

def discover_ltha_cases(model):
    """
    Returns [(case_name, results_json_path), ...] for every completed case
    on this model whose analysis type is LTHA. Non-LTHA cases from the same
    batch run (static, modal, RSA, etc.) are silently excluded.
    """
    cases = []
    file_path = getattr(model, 'file_path', None)
    if not file_path:
        return cases

    base_name = os.path.splitext(file_path)[0]
    paths = getattr(model, 'valid_result_paths', None) or glob.glob(f"{base_name}_*_results.json")

    for path in sorted(paths):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception:
            continue

        if data.get("status") != "SUCCESS":
            continue
        if data.get("info", {}).get("type") != "Linear Time History Analysis":
            continue

        fname = os.path.basename(path)
        prefix = os.path.basename(base_name) + "_"
        case_name = fname[len(prefix):].replace("_results.json", "")
        cases.append((case_name, path))

    return cases

def has_ltha_results(model):
    """For main.py: gate the launch button on this — True only if a batch
    run produced at least one successful LTHA case."""
    return len(discover_ltha_cases(model)) > 0

class AddPlotFunctionDialog(QDialog):
    """Builds one or more configured PlotFunctionSource objects — one per
    joint ID when the Joint ID field has a comma-separated list. Fields
    swap based on type."""

    def __init__(self, parent=None, case_data: LTHACaseData = None, main_window=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.case_data = case_data
        self.main_window = main_window
        self.result_sources = []
        self.setWindowTitle("Define Plot Function")
        self.setMinimumWidth(380)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Function Type"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(list(PLOT_FUNCTION_TYPES.keys()))
        self.type_combo.currentTextChanged.connect(self._rebuild_fields)
        layout.addWidget(self.type_combo)

        self.fields_container = QWidget()
        self.fields_layout = QFormLayout(self.fields_container)
        layout.addWidget(self.fields_container)

        layout.addWidget(QLabel("Name (optional)"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Auto-generated if left blank")
        layout.addWidget(self.name_edit)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._rebuild_fields(self.type_combo.currentText())

    def _make_joint_id_row(self):
        """Joint ID field + 'Select from Model...' button, shared by Joint
        Response and Joint Reaction. Accepts a comma-separated list so one
        Add covers several joints at once."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        self.joint_id_edit = QLineEdit()
        self.joint_id_edit.setPlaceholderText("e.g. 12, 45, 132")
        row_layout.addWidget(self.joint_id_edit, 1)

        select_btn = QPushButton("Select from Model...")
        select_btn.setObjectName("secondary")
        select_btn.setEnabled(self.main_window is not None)
        select_btn.setToolTip(
            "Pick joints directly in the 3D view"
            if self.main_window is not None else
            "Not available — dialog wasn't given a model window reference"
        )
        select_btn.clicked.connect(self._on_select_from_model)
        row_layout.addWidget(select_btn)

        return row

    def _clear_fields(self):
        while self.fields_layout.count():
            item = self.fields_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _rebuild_fields(self, type_name):
        self._clear_fields()

        if type_name == "Joint Response":
            self.fields_layout.addRow("Joint ID(s)", self._make_joint_id_row())

            self.vector_group = QButtonGroup(self)
            vec_row = QHBoxLayout()
            for i, label in enumerate(["Displ", "Vel", "Accel"]):
                rb = QRadioButton(label)
                self.vector_group.addButton(rb)               
                if i == 0:
                    rb.setChecked(True)                        
                self.vector_group.addButton(rb)
                vec_row.addWidget(rb)
            vec_widget = QWidget()
            vec_widget.setLayout(vec_row)
            self.fields_layout.addRow("Vector Type", vec_widget)
            self.vector_group.buttonClicked.connect(self._on_vector_type_changed)

            self.component_combo = QComboBox()
            self.component_combo.addItems(DOF_LABELS)
            self.fields_layout.addRow("Component", self.component_combo)

            self.absolute_check = QCheckBox("Absolute (relative + ground motion)")
            self.fields_layout.addRow("", self.absolute_check)

        elif type_name == "Joint Reaction":
            self.fields_layout.addRow("Joint ID(s)", self._make_joint_id_row())
            self.component_combo = QComboBox()
            self.component_combo.addItems(FORCE_COMPONENTS)
            self.fields_layout.addRow("Component", self.component_combo)

        elif type_name == "Base Reaction":
            self.component_combo = QComboBox()
            self.component_combo.addItems(FORCE_COMPONENTS)
            self.fields_layout.addRow("Component", self.component_combo)

        elif type_name == "Ground Motion":
            self.direction_combo = QComboBox()
            directions = self.case_data.directions if self.case_data else ["X", "Y", "Z"]
            self.direction_combo.addItems(directions)
            self.fields_layout.addRow("Direction", self.direction_combo)

    def _on_vector_type_changed(self, button):
                                                                            
        is_displ = (button.text() == "Displ")
        self.absolute_check.setEnabled(not is_displ)
        if is_displ:
            self.absolute_check.setChecked(False)

    @staticmethod
    def _parse_joint_ids(raw_text):
        """'12, 45,132' -> ['12', '45', '132'], de-duplicated, order preserved."""
        ids = []
        for tok in raw_text.replace(";", ",").split(","):
            tok = tok.strip()
            if tok and tok not in ids:
                ids.append(tok)
        return ids

    def _on_ok(self):
        type_name = self.type_combo.currentText()
        base_name = self.name_edit.text().strip() or None
        sources = []

        try:
            if type_name == "Joint Response":
                joint_ids = self._parse_joint_ids(self.joint_id_edit.text())
                if not joint_ids:
                    raise ValueError("Enter at least one Joint ID, or use Select from Model.")
                vector_type = self.vector_group.checkedButton().text()
                for jid in joint_ids:
                    name = f"{base_name} - {jid}" if (base_name and len(joint_ids) > 1) else base_name
                    sources.append(JointResponseSource(
                        joint_id=jid,
                        vector_type=vector_type,
                        component=self.component_combo.currentText(),
                        absolute=self.absolute_check.isChecked(),
                        name=name,
                    ))
            elif type_name == "Joint Reaction":
                joint_ids = self._parse_joint_ids(self.joint_id_edit.text())
                if not joint_ids:
                    raise ValueError("Enter at least one Joint ID, or use Select from Model.")
                for jid in joint_ids:
                    name = f"{base_name} - {jid}" if (base_name and len(joint_ids) > 1) else base_name
                    sources.append(ReactionSource(
                        joint_id=jid,
                        component=self.component_combo.currentText(),
                        name=name,
                    ))
            elif type_name == "Base Reaction":
                sources.append(BaseReactionSource(
                    component=self.component_combo.currentText(), name=base_name
                ))
            elif type_name == "Ground Motion":
                sources.append(GroundMotionSource(
                    direction=self.direction_combo.currentText(), name=base_name
                ))
            else:
                raise ValueError("Unknown function type.")
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Function", str(e))
            return

        self.result_sources = sources
        self.accept()

    def get_sources(self):
        return self.result_sources

    def _on_select_from_model(self):
        if not self.main_window:
            return
                                                                           
        my_pos = self.pos()
        self.hide()

        self._hidden_parent = self.parent()
        if self._hidden_parent is not None:
            self._hidden_parent.hide()

        picker = SelectJointsDialog(self.main_window, parent=self.main_window)
        picker.move(my_pos)
        picker.finished.connect(lambda result: self._on_picker_finished(result, picker))
        picker.show()

    def _on_picker_finished(self, result, picker):
        if result == int(QDialog.DialogCode.Accepted):
            picked = picker.picked_joint_ids()
            if picked:
                existing = self._parse_joint_ids(self.joint_id_edit.text())
                merged = existing + [j for j in picked if j not in existing]
                self.joint_id_edit.setText(", ".join(merged))
        picker.deleteLater()

        if getattr(self, '_hidden_parent', None) is not None:
            self._hidden_parent.show()
            self._hidden_parent.raise_()
            self._hidden_parent = None

        self.show()
        self.raise_()
        self.activateWindow()

class SelectJointsDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.main_window = main_window
        self._original_selection = list(getattr(main_window, 'selected_node_ids', []))
        self._picked_ids = []

        self.setWindowTitle("Select Joints")
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(300, 140)

        layout = QVBoxLayout(self)

        msg = QLabel("Click joints in the 3D view (Ctrl+click to add more), then press OK.")
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
            main_window.status.showMessage("Selecting joints for Plot Function — click in the 3D view, then OK.")

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

    def _restore_original_selection(self):
        mw = self.main_window
        if not hasattr(mw, 'selected_node_ids'):
            return
        mw.selected_node_ids = list(self._original_selection)
        for cvs in [getattr(mw, 'canvas', None), getattr(mw, 'canvas2', None)]:
            if cvs is not None and hasattr(cvs, 'update_selection_overlay'):
                cvs.update_selection_overlay(
                    getattr(mw, 'selected_ids', []),
                    mw.selected_node_ids,
                    getattr(mw, 'selected_area_ids', [])
                )

    def _on_ok(self):
        self._poll_timer.stop()
                                                                            
        self._picked_ids = [str(n) for n in getattr(self.main_window, 'selected_node_ids', [])]
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

class PlotFunctionDisplayDialog(QDialog):

    def __init__(self, parent=None, model=None, animation_manager=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.model = model
        self.main_window = parent                                           
        self.animation_manager = animation_manager
        self.current_case = None                        
        self.defined_functions = []                                 
        self.curve_items = {}                                     
        self._suppress_scrub_emit = False
        self._scrub_sync_available = False

        self.local_units = UnitConverter()
        self.local_units.set_unit_system(unit_registry.current_unit_label)

        self.setWindowTitle("Plot Function Trace Display")
        self.resize(1240, 660)
        self._build_ui()
        self._deserialize_functions()
        self._load_cases()

        if self.animation_manager is not None:
            self.animation_manager.signal_ltha_frame_update.connect(self._on_external_scrub)

    def done(self, r):
        """Save the defined plot functions onto the model every time this
        dialog closes — OK, Close button, or the window X — not just on
        explicit accept."""
        self._save_functions_to_model()
        super().done(r)

    _SOURCE_KIND_FIELDS = {
        "JointResponseSource": ("joint_id", "vector_type", "component", "absolute"),
        "ReactionSource": ("joint_id", "component"),
        "BaseReactionSource": ("component",),
        "GroundMotionSource": ("direction",),
    }

    def _serialize_functions(self):
        """Turns the current func_list into plain JSON-safe dicts, including
        each item's checked state, keyed by source class name."""
        _SOURCE_CLASSES = {
            "JointResponseSource": JointResponseSource,
            "ReactionSource": ReactionSource,
            "BaseReactionSource": BaseReactionSource,
            "GroundMotionSource": GroundMotionSource,
        }
        out = []
        for i in range(self.func_list.count()):
            item = self.func_list.item(i)
            source = item.data(Qt.ItemDataRole.UserRole)
            kind = None
            for name, cls in _SOURCE_CLASSES.items():
                if isinstance(source, cls):
                    kind = name
                    break
            if kind is None:
                continue

            d = {
                "kind": kind,
                "checked": item.checkState() == Qt.CheckState.Checked,
                "name": getattr(source, "name", None),
            }
            for field in self._SOURCE_KIND_FIELDS[kind]:
                d[field] = getattr(source, field, None)
            out.append(d)
        return out

    def _save_functions_to_model(self):
        if self.model is None:
            return
        self.model.plot_functions = self._serialize_functions()

    def _deserialize_functions(self):
        """Restores previously-defined plot functions from the model, so
        they survive closing and reopening this dialog."""
        if self.model is None:
            return
        saved = getattr(self.model, "plot_functions", None) or []

        self.func_list.blockSignals(True)
        for d in saved:
            kind = d.get("kind")
            try:
                if kind == "JointResponseSource":
                    source = JointResponseSource(
                        joint_id=d["joint_id"], vector_type=d["vector_type"],
                        component=d["component"], absolute=d.get("absolute", False),
                        name=d.get("name"),
                    )
                elif kind == "ReactionSource":
                    source = ReactionSource(
                        joint_id=d["joint_id"], component=d["component"], name=d.get("name"),
                    )
                elif kind == "BaseReactionSource":
                    source = BaseReactionSource(component=d["component"], name=d.get("name"))
                elif kind == "GroundMotionSource":
                    source = GroundMotionSource(direction=d["direction"], name=d.get("name"))
                else:
                    continue
            except (KeyError, TypeError):
                continue

            self.defined_functions.append(source)
            item = QListWidgetItem(source.display_name())
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if d.get("checked", True) else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, source)
            self.func_list.addItem(item)
        self.func_list.blockSignals(False)

    def _build_ui(self):
        outer = QVBoxLayout(self)

        case_row = QHBoxLayout()
        case_row.addWidget(QLabel("Load Case (LTHA):"))
        self.case_combo = QComboBox()
        self.case_combo.currentIndexChanged.connect(self._on_case_changed)
        case_row.addWidget(self.case_combo, 1)

        case_row.addWidget(QLabel("Units:"))
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(UNIT_SYSTEMS)
        self.unit_combo.setCurrentText(self.local_units.current_unit_label)
        self.unit_combo.setToolTip("Display units for this dialog only — does not change the global setting.")
        self.unit_combo.currentTextChanged.connect(self._on_unit_changed)
        case_row.addWidget(self.unit_combo)

        outer.addLayout(case_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Plot Functions  (check to display)"))
        self.func_list = QListWidget()
        self.func_list.itemChanged.connect(self._on_item_check_changed)
        left_layout.addWidget(self.func_list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add...")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._on_add_function)
        remove_btn = QPushButton("Remove")
        remove_btn.setObjectName("danger")
        remove_btn.clicked.connect(self._on_remove_function)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        left_layout.addLayout(btn_row)

        self.warning_label = QLabel("")
        self.warning_label.setStyleSheet(f"color: {COLORS['danger']};")
        self.warning_label.setWordWrap(True)
        left_layout.addWidget(self.warning_label)

        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.readout_label = QLabel("t = --")
        self.readout_label.setStyleSheet("font-family: Consolas, monospace;")
        right_layout.addWidget(self.readout_label)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.setLabel('left', 'Value')
        self.legend = self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.getAxis('bottom').setPen(pg.mkPen('k'))
        self.plot_widget.getAxis('left').setPen(pg.mkPen('k'))

        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#c0392b', width=1))
        self.vline.setVisible(False)
        self.plot_widget.addItem(self.vline, ignoreBounds=True)

        self.plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)

        right_layout.addWidget(self.plot_widget, 1)

        bottom_row = QHBoxLayout()

        self.btn_play = QPushButton("Play")
        self.btn_play.setObjectName("primary")
        self.btn_play.setCheckable(True) 
        self.btn_play.clicked.connect(self._toggle_playback)
        self.btn_play.setEnabled(False)                                          
        bottom_row.addWidget(self.btn_play)

        reset_btn = QPushButton("Reset View")
        reset_btn.setObjectName("secondary")
        reset_btn.clicked.connect(self._on_reset_view)
        bottom_row.addWidget(reset_btn)
        bottom_row.addStretch()
        export_csv_btn = QPushButton("Export CSV...")
        export_csv_btn.setObjectName("secondary")
        export_csv_btn.clicked.connect(self._export_csv)
        export_xlsx_btn = QPushButton("Export Excel...")
        export_xlsx_btn.setObjectName("secondary")
        export_xlsx_btn.clicked.connect(self._export_excel)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(export_csv_btn)
        bottom_row.addWidget(export_xlsx_btn)
        bottom_row.addWidget(close_btn)
        right_layout.addLayout(bottom_row)

        splitter.addWidget(right)

        ranges = self._build_range_panel()
        splitter.addWidget(ranges)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([240, 780, 220])

    def _build_range_panel(self):
        panel = QWidget()
        panel.setMaximumWidth(240)
        layout = QVBoxLayout(panel)

        time_grp = QGroupBox("Time Range")
        time_form = QFormLayout(time_grp)
        self.time_from_spin = QDoubleSpinBox()
        self.time_from_spin.setRange(-1e9, 1e9)
        self.time_from_spin.setDecimals(4)
        self.time_to_spin = QDoubleSpinBox()
        self.time_to_spin.setRange(-1e9, 1e9)
        self.time_to_spin.setDecimals(4)
        self.time_from_spin.valueChanged.connect(self._on_range_changed)
        self.time_to_spin.valueChanged.connect(self._on_range_changed)
        time_form.addRow("From", self.time_from_spin)
        time_form.addRow("To", self.time_to_spin)
        time_reset_btn = QPushButton("Reset Defaults")
        time_reset_btn.setObjectName("secondary")
        time_reset_btn.clicked.connect(self._on_reset_time_range)
        time_form.addRow(time_reset_btn)
        layout.addWidget(time_grp)

        axis_grp = QGroupBox("Axis Range Override")
        axis_grid = QGridLayout(axis_grp)
        axis_grid.addWidget(QLabel(""), 0, 0)
        axis_grid.addWidget(QLabel("Min"), 0, 1)
        axis_grid.addWidget(QLabel("Max"), 0, 2)

        self.x_override_check = QCheckBox("Horizontal")
        self.x_min_spin = QDoubleSpinBox(); self.x_min_spin.setRange(-1e9, 1e9); self.x_min_spin.setDecimals(4)
        self.x_max_spin = QDoubleSpinBox(); self.x_max_spin.setRange(-1e9, 1e9); self.x_max_spin.setDecimals(4)
        axis_grid.addWidget(self.x_override_check, 1, 0)
        axis_grid.addWidget(self.x_min_spin, 1, 1)
        axis_grid.addWidget(self.x_max_spin, 1, 2)

        self.y_override_check = QCheckBox("Vertical")
        self.y_min_spin = QDoubleSpinBox(); self.y_min_spin.setRange(-1e12, 1e12); self.y_min_spin.setDecimals(4)
        self.y_max_spin = QDoubleSpinBox(); self.y_max_spin.setRange(-1e12, 1e12); self.y_max_spin.setDecimals(4)
        axis_grid.addWidget(self.y_override_check, 2, 0)
        axis_grid.addWidget(self.y_min_spin, 2, 1)
        axis_grid.addWidget(self.y_max_spin, 2, 2)

        for w in (self.x_override_check, self.y_override_check):
            w.toggled.connect(self._on_range_changed)
        for w in (self.x_min_spin, self.x_max_spin, self.y_min_spin, self.y_max_spin):
            w.valueChanged.connect(self._on_range_changed)

        layout.addWidget(axis_grp)

        labels_grp = QGroupBox("Axis Labels")
        labels_form = QFormLayout(labels_grp)
        self.x_label_edit = QLineEdit()
        self.x_label_edit.setPlaceholderText("Time (s)")
        self.y_label_edit = QLineEdit()
        self.y_label_edit.setPlaceholderText("Value")
        self.x_label_edit.textChanged.connect(self._on_axis_labels_changed)
        self.y_label_edit.textChanged.connect(self._on_axis_labels_changed)
        labels_form.addRow("Horizontal", self.x_label_edit)
        labels_form.addRow("Vertical", self.y_label_edit)
        layout.addWidget(labels_grp)

        self.grid_check = QCheckBox("Grid Overlay")
        self.grid_check.setChecked(True)
        self.grid_check.toggled.connect(self._on_grid_toggled)
        layout.addWidget(self.grid_check)

        max_grp = QGroupBox("Max Values (|peak|)")
        max_grp_layout = QVBoxLayout(max_grp)
        max_grp_layout.setContentsMargins(4, 4, 4, 4)

        self.max_values_container = QWidget()
        self.max_values_layout = QVBoxLayout(self.max_values_container)
        self.max_values_layout.setContentsMargins(2, 2, 2, 2)
        self.max_values_layout.setSpacing(2)
        self.max_values_layout.addStretch()

        max_scroll = QScrollArea()
        max_scroll.setWidgetResizable(True)
        max_scroll.setWidget(self.max_values_container)
        max_scroll.setMinimumHeight(140)
        layout.addWidget(max_grp)
        max_grp_layout.addWidget(max_scroll)

        layout.addStretch()
        return panel

    def _update_max_values_panel(self):
        """Rebuilds the corner Max Values list from whatever is currently
        plotted. Scrollable so it holds tens of functions without growing
        the dialog."""
        while self.max_values_layout.count() > 1:
            item = self.max_values_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for i, (source, curve) in enumerate(self.curve_items.items()):
            xdata, ydata = curve.getData()
            if ydata is None or len(ydata) == 0:
                continue
            peak = float(np.max(np.abs(ydata)))
            row = QLabel(f"{source.display_name()}: {peak:.4g}")
            row.setStyleSheet(
                f"color: {CURVE_COLORS[i % len(CURVE_COLORS)]}; "
                f"font-family: Consolas, monospace; font-size: 11px;"
            )
            row.setWordWrap(True)
            self.max_values_layout.insertWidget(self.max_values_layout.count() - 1, row)

    def _on_reset_view(self):
                                                                             
        self.x_override_check.setChecked(False)
        self.y_override_check.setChecked(False)
        self._on_reset_time_range()
        self.plot_widget.autoRange()

    def _on_reset_time_range(self):
        t_max = self.current_case.time[-1] if (self.current_case is not None and self.current_case.n_steps > 0) else 0.0
        for spin in (self.time_from_spin, self.time_to_spin):
            spin.blockSignals(True)
        self.time_from_spin.setValue(0.0)
        self.time_to_spin.setValue(t_max)
        for spin in (self.time_from_spin, self.time_to_spin):
            spin.blockSignals(False)
        self._apply_ranges()

    def _on_range_changed(self, *_):
        self._apply_ranges()

    def _apply_ranges(self):
        """Time Range sets the default X window; Axis Range Override, when
        checked, takes precedence over it for that axis."""
        if self.x_override_check.isChecked():
            self.plot_widget.setXRange(self.x_min_spin.value(), self.x_max_spin.value(), padding=0)
        else:
            lo, hi = self.time_from_spin.value(), self.time_to_spin.value()
            if hi > lo:
                self.plot_widget.setXRange(lo, hi, padding=0)

        if self.y_override_check.isChecked():
            self.plot_widget.setYRange(self.y_min_spin.value(), self.y_max_spin.value(), padding=0)

        self.x_min_spin.setEnabled(self.x_override_check.isChecked())
        self.x_max_spin.setEnabled(self.x_override_check.isChecked())
        self.y_min_spin.setEnabled(self.y_override_check.isChecked())
        self.y_max_spin.setEnabled(self.y_override_check.isChecked())

    def _on_axis_labels_changed(self, *_):
        x_text = self.x_label_edit.text().strip()
        y_text = self.y_label_edit.text().strip()
        if x_text:
            self.plot_widget.setLabel('bottom', x_text)
        else:
            self.plot_widget.setLabel('bottom', 'Time', units='s')
        if y_text:
            self.plot_widget.setLabel('left', y_text)
        else:
            self.plot_widget.setLabel('left', 'Value')

    def _on_grid_toggled(self, checked):
        self.plot_widget.showGrid(x=checked, y=checked, alpha=0.15)

    def _load_cases(self):
        self.case_combo.blockSignals(True)
        self.case_combo.clear()
        cases = discover_ltha_cases(self.model) if self.model else []
        for case_name, path in cases:
            self.case_combo.addItem(case_name, path)
        self.case_combo.blockSignals(False)

        if cases:
            self.case_combo.setCurrentIndex(0)
            self._on_case_changed(0)
        else:
            QMessageBox.information(
                self, "No LTHA Results",
                "No completed Linear Time History cases were found for this model."
            )

    def _on_case_changed(self, index):
        if index < 0:
            self.current_case = None
            return
        path = self.case_combo.itemData(index)
        try:
            self.current_case = LTHACaseData(path)
        except Exception as e:
            QMessageBox.warning(self, "Error Loading Case", str(e))
            self.current_case = None
            return

        self._scrub_sync_available = (
            self.animation_manager is not None
            and getattr(self.animation_manager, 'ltha_mode', False)
            and self.animation_manager.ltha_n_steps == self.current_case.n_steps
        )

        if hasattr(self, 'btn_play'):
            self.btn_play.setEnabled(self._scrub_sync_available)
            self._sync_play_button_state()

        self._on_reset_time_range()                                                    
        self._render_plot()

    def _toggle_playback(self, checked):
        """Toggles the animation state when the play button is clicked."""
        if not self._scrub_sync_available or not self.animation_manager:
            return
            
        if hasattr(self.main_window, 'toggle_animation'):
            self.main_window.toggle_animation(checked, False)
        elif hasattr(self.animation_manager, 'is_running'):
                                     
            if checked and hasattr(self.animation_manager, 'start'):
                self.animation_manager.start()
            elif not checked and hasattr(self.animation_manager, 'stop'):
                self.animation_manager.stop()
                
        self._sync_play_button_state()
        
    def _sync_play_button_state(self):
        """Updates the button text and check state based on actual animation manager status."""
        if not hasattr(self, 'btn_play'): 
            return
            
        is_running = getattr(self.animation_manager, 'is_running', False)
        
        self.btn_play.blockSignals(True)
        self.btn_play.setChecked(is_running)
        self.btn_play.setText("⏸ Pause" if is_running else "▶ Play")
        self.btn_play.blockSignals(False)

    def _on_unit_changed(self, new_label):
        self.local_units.set_unit_system(new_label)
        self._render_plot()

    def _on_add_function(self):
                                                                                        
        self._add_dlg = AddPlotFunctionDialog(self, case_data=self.current_case, main_window=self.main_window)
        
        def handle_accept():
            self.func_list.blockSignals(True)
            for source in self._add_dlg.get_sources():
                self.defined_functions.append(source)
                item = QListWidgetItem(source.display_name())
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, source)
                self.func_list.addItem(item)
            self.func_list.blockSignals(False)
            self._render_plot()
            
        self._add_dlg.accepted.connect(handle_accept)
        self._add_dlg.exec()

    def _on_remove_function(self):
        for item in self.func_list.selectedItems():
            source = item.data(Qt.ItemDataRole.UserRole)
            if source in self.defined_functions:
                self.defined_functions.remove(source)
            self.func_list.takeItem(self.func_list.row(item))
        self._render_plot()

    def _on_item_check_changed(self, item):
        self._render_plot()

    def _checked_sources(self):
        sources = []
        for i in range(self.func_list.count()):
            item = self.func_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                sources.append(item.data(Qt.ItemDataRole.UserRole))
        return sources

    def _render_plot(self):
        self.plot_widget.clear()
        self.plot_widget.addItem(self.vline, ignoreBounds=True)
        self.curve_items = {}
        self.legend.clear()

        if self.current_case is None:
            self._update_max_values_panel()
            return

        errors = []
        unit_kinds = set()

        for i, source in enumerate(self._checked_sources()):
            try:
                t, values, label = source.get_series(self.current_case)
            except Exception as e:
                errors.append(f"{source.display_name()}: {e}")
                continue

            values_disp, unit_label = self._display_series(source, values)
            unit_kinds.add(unit_label)
            curve_label = f"{label} ({unit_label})" if unit_label else label

            color = CURVE_COLORS[i % len(CURVE_COLORS)]
            pen = pg.mkPen(color=color, width=1.5)
            curve = self.plot_widget.plot(t, values_disp, pen=pen, name=curve_label)
                                                                         
            curve.setDownsampling(auto=True, method='peak')
            curve.setClipToView(True)
            self.curve_items[source] = curve

        if errors:
            self.warning_label.setText("Could not plot: " + "; ".join(errors))
        elif len(unit_kinds) > 1:
            self.warning_label.setText(
                "Note: plotted functions have different units — axis scale is shared."
            )
        else:
            self.warning_label.setText("")

        if hasattr(self, 'x_label_edit'):
            self._on_axis_labels_changed()
            self._on_grid_toggled(self.grid_check.isChecked())
            self._apply_ranges()

        self._update_max_values_panel()

    def _display_series(self, source, values):
        """
        Scale a raw-SI series into this dialog's local display units.
        Returns (scaled_values, unit_label). Single source of truth for
        conversion — used by the plot, the cursor readout (which reads the
        already-scaled curve data), and CSV/Excel export.
        """
        u = self.local_units

        if isinstance(source, JointResponseSource):
            if source.vector_type == "Displ":
                return u.to_display_length(values), u.length_unit_name
            elif source.vector_type == "Vel":
                                                                       
                return values * u.length_scale, f"{u.length_unit_name}/s"
            else:         
                return u.to_display_acceleration(values), u.acceleration_unit

        if isinstance(source, (ReactionSource, BaseReactionSource)):
            if source.component.startswith("F"):
                return u.to_display_force(values), u.force_unit_name
            else:
                                                                             
                return values * u.force_scale * u.length_scale, f"{u.force_unit_name}\u00b7{u.length_unit_name}"

        if isinstance(source, GroundMotionSource):
            return u.to_display_acceleration(values), u.acceleration_unit

        return values, ""

    def _update_readout(self, t_index):
        """Reads values off the bar's actual snapped position (t_index),
        never off raw mouse/pixel coordinates."""
        if self.current_case is None:
            self.readout_label.setText("t = --")
            return

        t = t_index * self.current_case.dt
        parts = [f"t = {t:6.3f} s"]
        for source, curve in self.curve_items.items():
            xdata, ydata = curve.getData()
            if xdata is None or len(xdata) == 0:
                continue
            idx = int(np.clip(np.searchsorted(xdata, t), 0, len(xdata) - 1))
            parts.append(f"{source.display_name()} = {ydata[idx]:.4g}")
        self.readout_label.setText("   |   ".join(parts))

    def _on_mouse_clicked(self, evt):
        if self.current_case is None:
            return
        if evt.button() != Qt.MouseButton.LeftButton:
            return
        pos = evt.scenePos()
        if not self.plot_widget.sceneBoundingRect().contains(pos):
            return
        mouse_point = self.plot_widget.getPlotItem().vb.mapSceneToView(pos)
        t = max(0.0, mouse_point.x())
        t_index = int(round(t / self.current_case.dt))
        t_index = max(0, min(t_index, self.current_case.n_steps - 1))

        self.vline.setPos(t_index * self.current_case.dt)
        self.vline.setVisible(True)
        self._update_readout(t_index)

        if self._scrub_sync_available:
            self._suppress_scrub_emit = True
            self.animation_manager.scrub_to_step(t_index)
            self._suppress_scrub_emit = False

    def _on_external_scrub(self, t_index):
        """Fired when playback or another dialog (e.g. DeformedShapeDialog's
        scrubber) moves the timestep — keep our cursor and readout in sync."""
        if self.current_case is None or not self._scrub_sync_available:
            return
        self.vline.setPos(t_index * self.current_case.dt)
        self.vline.setVisible(True)
        self._update_readout(t_index)

        self._sync_play_button_state()

    def _gather_export_table(self):
        sources = [s for s in self._checked_sources() if s in self.curve_items]
        if not sources or self.current_case is None:
            return None, None

        n = self.current_case.n_steps
        header = ["Time (s)"]
        columns = [self.current_case.time[:n]]

        for source in sources:
            try:
                t, values, label = source.get_series(self.current_case)
            except Exception:
                continue
            padded = np.full(n, np.nan)
            m = min(n, len(values))
            padded[:m] = values[:m]
            header.append(label)
            columns.append(padded)

        return header, columns

    def _export_csv(self):
        header, columns = self._gather_export_table()
        if header is None:
            QMessageBox.information(self, "Nothing to Export", "Check at least one function to plot first.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")
        if not path:
            return

        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for row in zip(*columns):
                writer.writerow([f"{v:.6g}" for v in row])

    def _export_excel(self):
        header, columns = self._gather_export_table()
        if header is None:
            QMessageBox.information(self, "Nothing to Export", "Check at least one function to plot first.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export Excel", "", "Excel Files (*.xlsx)")
        if not path:
            return

        try:
            import openpyxl
        except ImportError:
            QMessageBox.warning(self, "Missing Dependency", "openpyxl is required for Excel export.")
            return

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = self.current_case.case_name if self.current_case else "Plot"
        ws.append(header)
        for row in zip(*columns):
            ws.append(list(row))
        wb.save(path)
