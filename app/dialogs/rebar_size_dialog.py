import copy
import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QGroupBox, QFormLayout, QLineEdit, 
                             QComboBox, QMessageBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QAbstractItemView, QCheckBox)
from PyQt6.QtCore import Qt

from core.units import unit_registry
from app.ui.theme import apply_dialog_style

LENGTH_SCALES = {
    "m":  1.0,
    "cm": 100.0,
    "mm": 1_000.0,
    "ft": 3.28084,
    "in": 39.3701,
}

DEFAULT_REBARS = [
    {"id": "#3", "area": 7.096e-5, "diameter": 0.009525},
    {"id": "#4", "area": 1.290e-4, "diameter": 0.0127},
    {"id": "#5", "area": 2.000e-4, "diameter": 0.015875},
    {"id": "#6", "area": 2.839e-4, "diameter": 0.01905},
    {"id": "#7", "area": 3.871e-4, "diameter": 0.022225},
    {"id": "#8", "area": 5.097e-4, "diameter": 0.0254},
    {"id": "#9", "area": 6.452e-4, "diameter": 0.028575},
    {"id": "#10", "area": 8.194e-4, "diameter": 0.032258},
    {"id": "#11", "area": 1.006e-3, "diameter": 0.035814},
    {"id": "#14", "area": 1.452e-3, "diameter": 0.043002},
    {"id": "#18", "area": 2.581e-3, "diameter": 0.057328},
                                                                     
    {"id": "10M", "area": 1.000e-4, "diameter": 0.0113},
    {"id": "15M", "area": 2.000e-4, "diameter": 0.0160},
    {"id": "20M", "area": 3.000e-4, "diameter": 0.0195},
    {"id": "25M", "area": 5.000e-4, "diameter": 0.0252},
    {"id": "30M", "area": 7.000e-4, "diameter": 0.0299},
    {"id": "35M", "area": 1.000e-3, "diameter": 0.0357},
    {"id": "45M", "area": 1.500e-3, "diameter": 0.0437},
    {"id": "55M", "area": 2.500e-3, "diameter": 0.0564},
]

class RebarSizeManagerDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Reinforcing Bar Sizes")
        self.resize(550, 420)
        self.model = model
        
        if not hasattr(self.model, "rebar_sizes") or not self.model.rebar_sizes:
            self.model.rebar_sizes = copy.deepcopy(DEFAULT_REBARS)
            
        self.working_copy = copy.deepcopy(self.model.rebar_sizes)

        root = QHBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(14, 14, 14, 14)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Bar ID", "Diameter", "Area"])                          
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        root.addWidget(self.table, stretch=2)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(10)

        unit_group = QGroupBox("Display Units")
        unit_form = QFormLayout(unit_group)
        self.combo_length = QComboBox()
        self.combo_length.addItems(list(LENGTH_SCALES.keys()))
        self.combo_length.setCurrentText(unit_registry.length_unit_name)
        self.combo_length.currentTextChanged.connect(self._refresh_ui)
        unit_form.addRow("Length:", self.combo_length)
        right_layout.addWidget(unit_group)

        edit_group = QGroupBox("Bar Properties")
        edit_form = QFormLayout(edit_group)
        
        self.check_auto_area = QCheckBox("Auto-calculate Area from Diameter")
        self.check_auto_area.setChecked(True)
        self.check_auto_area.toggled.connect(self._toggle_auto_area)
        
        self.input_id = QLineEdit()
        self.input_dia = QLineEdit()
        self.input_area = QLineEdit()
        
        self.input_dia.textEdited.connect(self._calc_area_from_dia)
        
        self.lbl_dia = QLabel()
        self.lbl_area = QLabel()

        edit_form.addRow("", self.check_auto_area)
        edit_form.addRow("Bar ID:", self.input_id)
        edit_form.addRow(self.lbl_dia, self.input_dia)
        edit_form.addRow(self.lbl_area, self.input_area)
        right_layout.addWidget(edit_group)

        btn_layout = QVBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_mod = QPushButton("Modify")
        self.btn_del = QPushButton("Delete")
        self.btn_reset = QPushButton("Reset to Defaults")
        
        self.btn_add.clicked.connect(self._add_bar)
        self.btn_mod.clicked.connect(self._modify_bar)
        self.btn_del.clicked.connect(self._delete_bar)
        self.btn_reset.clicked.connect(self._reset_defaults)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_mod)
        btn_layout.addWidget(self.btn_del)
        btn_layout.addSpacing(10)
        btn_layout.addWidget(self.btn_reset)
        right_layout.addLayout(btn_layout)

        right_layout.addStretch()

        dlg_btns = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self._save_and_close)
        btn_cancel.clicked.connect(self.reject)
        dlg_btns.addStretch()
        dlg_btns.addWidget(btn_ok)
        dlg_btns.addWidget(btn_cancel)
        right_layout.addLayout(dlg_btns)

        root.addLayout(right_layout, stretch=1)

        self._refresh_ui()
        self._toggle_auto_area(True)                                              

    def _l_scale(self):
        return LENGTH_SCALES.get(self.combo_length.currentText(), 1.0)

    def _toggle_auto_area(self, checked):
        self.input_area.setReadOnly(checked)
        self.input_area.setStyleSheet("background-color: #e9ecef; color: #6c757d;" if checked else "")
        if checked:
            self._calc_area_from_dia(self.input_dia.text())

    def _calc_area_from_dia(self, text):
        if not self.check_auto_area.isChecked():
            return
        try:
            dia = float(text)
            area = math.pi * (dia ** 2) / 4.0
            self.input_area.setText(f"{area:.4g}")
        except ValueError:
            pass                                                        

    def _refresh_ui(self):
        """Redraws table and labels entirely from the SI working copy."""
        l_unit = self.combo_length.currentText()
        self.lbl_dia.setText(f"Diameter ({l_unit}):")
        self.lbl_area.setText(f"Area ({l_unit}²):")

        self.table.blockSignals(True)
        self.table.setRowCount(len(self.working_copy))
        
        l_scale = self._l_scale()
        a_scale = l_scale ** 2

        for row, bar in enumerate(self.working_copy):
            disp_dia = bar["diameter"] * l_scale
            disp_area = bar["area"] * a_scale
            
            self.table.setItem(row, 0, QTableWidgetItem(bar["id"]))
            self.table.setItem(row, 1, QTableWidgetItem(f"{disp_dia:.4g}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{disp_area:.4g}"))
            
        self.table.blockSignals(False)
        self._on_table_select()

    def _on_table_select(self):
        selected = self.table.selectedItems()
        if not selected:
            self.input_id.clear()
            self.input_dia.clear()
            self.input_area.clear()
            return
            
        row = selected[0].row()
        bar = self.working_copy[row]
        
        l_scale = self._l_scale()
        a_scale = l_scale ** 2
        
        self.input_id.setText(bar["id"])
        self.input_dia.setText(f"{bar['diameter'] * l_scale:.4g}")
        self.input_area.setText(f"{bar['area'] * a_scale:.4g}")

    def _get_input_si(self):
        """Reads input fields, converts to SI, and returns a dict."""
        bar_id = self.input_id.text().strip()
        if not bar_id:
            raise ValueError("Bar ID cannot be empty.")
            
        try:
            disp_dia = float(self.input_dia.text())
            disp_area = float(self.input_area.text())
        except ValueError:
            raise ValueError("Area and Diameter must be numeric.")

        l_scale = self._l_scale()
        a_scale = l_scale ** 2
        
        return {
            "id": bar_id,
            "diameter": disp_dia / l_scale,
            "area": disp_area / a_scale
        }

    def _add_bar(self):
        try:
            new_bar = self._get_input_si()
            if any(b["id"] == new_bar["id"] for b in self.working_copy):
                QMessageBox.warning(self, "Duplicate", f"Bar ID '{new_bar['id']}' already exists.")
                return
                
            self.working_copy.append(new_bar)
            self._refresh_ui()
            
            self.table.selectRow(len(self.working_copy) - 1)
        except ValueError as e:
            QMessageBox.critical(self, "Input Error", str(e))

    def _modify_bar(self):
        selected = self.table.selectedItems()
        if not selected: return
        row = selected[0].row()
        old_id = self.working_copy[row]["id"]
        
        try:
            mod_bar = self._get_input_si()
            if mod_bar["id"] != old_id and any(b["id"] == mod_bar["id"] for b in self.working_copy):
                QMessageBox.warning(self, "Duplicate", f"Bar ID '{mod_bar['id']}' already exists.")
                return
                
            self.working_copy[row] = mod_bar
            self._refresh_ui()
            self.table.selectRow(row)
        except ValueError as e:
            QMessageBox.critical(self, "Input Error", str(e))

    def _delete_bar(self):
        selected = self.table.selectedItems()
        if not selected: return
        row = selected[0].row()
        
        del self.working_copy[row]
        self._refresh_ui()

    def _reset_defaults(self):
        self.working_copy = copy.deepcopy(DEFAULT_REBARS)
        self._refresh_ui()

    def _save_and_close(self):
        self.model.rebar_sizes = copy.deepcopy(self.working_copy)
        self.accept()
