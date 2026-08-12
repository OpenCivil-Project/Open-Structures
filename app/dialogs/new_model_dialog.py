import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, 
                             QPushButton, QGroupBox, QFormLayout, QStackedWidget, 
                             QListWidget, QWidget, QGridLayout)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from app.ui.theme import apply_dialog_style

# Length scales for local dialog unit conversion
LENGTH_SCALES = {
    "m":  1.0,
    "cm": 100.0,
    "mm": 1_000.0,
    "ft": 3.28084,
    "in": 39.3701,
}

class SmartDoubleInput(QLineEdit):
    """A unit-aware line edit that handles unit suffixes and scientific notation."""
    def __init__(self, val=0.0, prop_type="length", current_unit="m", parent=None):
        super().__init__(parent)
        self.setProperty("prop_type", prop_type)
        self.unit = current_unit
        self._value = val
        self.editingFinished.connect(self._sync_text)
        self._render_text()
        
    def _get_suffix(self) -> str:
        prop = self.property("prop_type")
        if prop == "area": return f" {self.unit}²"
        if prop == "inertia": return f" {self.unit}⁴"
        if prop == "length": return f" {self.unit}"
        return ""

    def value(self) -> float:
        """Strips the suffix to parse the clean number from user input."""
        txt = self.text().replace(self._get_suffix(), "").strip()
        try:
            self._value = float(txt)
        except ValueError:
            pass
        return self._value

    def setValue(self, val: float):
        """Programmatically sets the value without re-reading the UI text."""
        self._value = val
        self._render_text()

    def setUnit(self, new_unit: str):
        """Updates the unit suffix and re-renders."""
        self.unit = new_unit
        self._render_text()

    def _sync_text(self):
        """Called when the user finishes typing."""
        self.value()
        self._render_text()

    def _render_text(self):
        v = self._value
        if abs(v) > 0 and (abs(v) < 1e-3 or abs(v) > 1e4):
            txt = f"{v:.4e}"
        else:
            txt = f"{v:.4f}"
        self.setText(txt + self._get_suffix())


class NewModelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Model Initialization")
        self.resize(600, 450)
        apply_dialog_style(self)
        
        self.selected_units = "kN, m, C"
        self.grid_data = {} 
        self.accepted_data = False 
        self.template_type = "Grid Only" 
        
        self.all_length_inputs = []

        main_layout = QHBoxLayout(self)

        left_layout = QVBoxLayout()
        self.template_list = QListWidget()
        self.template_list.addItems(["Blank", "Grid Only", "2D Frame", "3D Frame"])
        self.template_list.setCurrentRow(1) 
        self.template_list.currentRowChanged.connect(self.on_template_changed)
        self.template_list.setMaximumWidth(150)
        left_layout.addWidget(QLabel("<b>Model Templates</b>"))
        left_layout.addWidget(self.template_list)
        main_layout.addLayout(left_layout)

        right_layout = QVBoxLayout()

        unit_group = QGroupBox("Project Units")
        unit_layout = QFormLayout()
        self.unit_combo = QComboBox()
        self.unit_combo.addItems([
            "kN, m, C", 
            "N, m, C", 
            "N, mm, C", 
            "kN, mm, C",
            "Tonf, m, C",
            "kgf, m, C",
            "kip, ft, F"
        ])
        unit_layout.addRow("Default Units:", self.unit_combo)
        unit_group.setLayout(unit_layout)
        right_layout.addWidget(unit_group)

        # Initialize the active unit scaling based on default combobox selection
        current_len_unit = self._get_len_unit(self.unit_combo.currentText())
        self._l_scale = LENGTH_SCALES.get(current_len_unit, 1.0)

        self.stack = QStackedWidget()

        self.page_blank = QWidget()
        blank_layout = QVBoxLayout(self.page_blank)
        blank_layout.addWidget(QLabel("Start with a completely empty workspace.\nNo grids or structural elements will be created."))
        blank_layout.addStretch()

        self.page_grid = QWidget()
        grid_layout = QFormLayout(self.page_grid)
        
        self.input_x_num = QSpinBox(); self.input_x_num.setRange(1, 100); self.input_x_num.setValue(4)
        self.input_x_dist = self.mk_len_input(6.0)
        
        self.input_y_num = QSpinBox(); self.input_y_num.setRange(1, 100); self.input_y_num.setValue(1)
        self.input_y_dist = self.mk_len_input(1.0)
        
        self.input_z_num = QSpinBox(); self.input_z_num.setRange(1, 100); self.input_z_num.setValue(3)
        self.input_z_dist = self.mk_len_input(3.0)

        grid_layout.addRow(QLabel("<b>X Direction</b>"))
        grid_layout.addRow("Number of Grid Lines:", self.input_x_num)
        grid_layout.addRow("Spacing:", self.input_x_dist)
        
        grid_layout.addRow(QLabel("<b>Y Direction</b>"))
        grid_layout.addRow("Number of Grid Lines:", self.input_y_num)
        grid_layout.addRow("Spacing:", self.input_y_dist)
        
        grid_layout.addRow(QLabel("<b>Z Direction (Height)</b>"))
        grid_layout.addRow("Number of Grid Lines:", self.input_z_num)
        grid_layout.addRow("Spacing:", self.input_z_dist)

        self.page_2d = QWidget()
        p2d_layout = QFormLayout(self.page_2d)
        self.input_2d_stories = QSpinBox(); self.input_2d_stories.setRange(1, 100); self.input_2d_stories.setValue(2)
        self.input_2d_bays = QSpinBox(); self.input_2d_bays.setRange(1, 100); self.input_2d_bays.setValue(3)
        self.input_2d_story_ht = self.mk_len_input(3.0)
        self.input_2d_bay_wd = self.mk_len_input(6.0)
        
        p2d_layout.addRow("Number of Stories (Z):", self.input_2d_stories)
        p2d_layout.addRow("Story Height:", self.input_2d_story_ht)
        p2d_layout.addRow("Number of Bays (X):", self.input_2d_bays)
        p2d_layout.addRow("Bay Width:", self.input_2d_bay_wd)

        self.page_3d = QWidget()
        p3d_layout = QFormLayout(self.page_3d)
        self.input_3d_stories = QSpinBox(); self.input_3d_stories.setRange(1, 100); self.input_3d_stories.setValue(2)
        self.input_3d_story_ht = self.mk_len_input(3.0)
        
        self.input_3d_bays_x = QSpinBox(); self.input_3d_bays_x.setRange(1, 100); self.input_3d_bays_x.setValue(3)
        self.input_3d_bay_wd_x = self.mk_len_input(6.0)
        
        self.input_3d_bays_y = QSpinBox(); self.input_3d_bays_y.setRange(1, 100); self.input_3d_bays_y.setValue(2)
        self.input_3d_bay_wd_y = self.mk_len_input(6.0)

        p3d_layout.addRow("Number of Stories (Z):", self.input_3d_stories)
        p3d_layout.addRow("Story Height:", self.input_3d_story_ht)
        p3d_layout.addRow(QLabel("<b>X Direction</b>"))
        p3d_layout.addRow("Number of Bays:", self.input_3d_bays_x)
        p3d_layout.addRow("Bay Width:", self.input_3d_bay_wd_x)
        p3d_layout.addRow(QLabel("<b>Y Direction</b>"))
        p3d_layout.addRow("Number of Bays:", self.input_3d_bays_y)
        p3d_layout.addRow("Bay Width:", self.input_3d_bay_wd_y)

        self.stack.addWidget(self.page_blank) 
        self.stack.addWidget(self.page_grid)  
        self.stack.addWidget(self.page_2d)    
        self.stack.addWidget(self.page_3d)    
        
        right_layout.addWidget(self.stack)

        # Informational Note
        note_lbl = QLabel("Note: Enter standard decimals (5000) or scientific notation (5e3). Lengths automatically convert when project units change.")
        note_lbl.setStyleSheet("color: gray; font-size: 10px; font-style: italic;")
        note_lbl.setWordWrap(True)
        right_layout.addWidget(note_lbl)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self.on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        right_layout.addLayout(btn_layout)

        main_layout.addLayout(right_layout)
        
        # Connect signals last so initialization doesn't trigger it prematurely
        self.unit_combo.currentTextChanged.connect(self.on_unit_changed)

    def _get_len_unit(self, combo_text: str) -> str:
        """Extracts the length unit from a string like 'kN, m, C'."""
        parts = combo_text.split(",")
        if len(parts) > 1:
            return parts[1].strip()
        return "m"

    def mk_len_input(self, initial_m: float) -> SmartDoubleInput:
        """Creates a unit-aware input scaled to the active combobox unit."""
        current_unit = self._get_len_unit(self.unit_combo.currentText())
        scale = self._l_scale
        inp = SmartDoubleInput(initial_m * scale, "length", current_unit)
        self.all_length_inputs.append(inp)
        return inp

    def _get_si(self, inp: SmartDoubleInput) -> float:
        """Safely reads the widget's pure value and converts it strictly back to SI base (meters)."""
        val = inp.value() 
        return val / self._l_scale

    def on_unit_changed(self, text):
        new_unit = self._get_len_unit(text)
        new_scale = LENGTH_SCALES.get(new_unit, 1.0)
        ratio = new_scale / self._l_scale
        
        for inp in self.all_length_inputs:
            current_val = inp.value()
            inp.setUnit(new_unit)
            inp.setValue(current_val * ratio)
            
        self._l_scale = new_scale

    def on_template_changed(self, index):
        self.stack.setCurrentIndex(index)
        self.template_type = self.template_list.currentItem().text()

    def on_ok(self):
        """Validates input and saves data based on selected template, ensuring SI units for distance."""
        self.selected_units = self.unit_combo.currentText()
        
        if self.template_type == "Blank":
            self.grid_data = {
                'x_num': 1, 'x_dist': 1.0,
                'y_num': 1, 'y_dist': 1.0,
                'z_num': 1, 'z_dist': 1.0,
            }
        elif self.template_type == "Grid Only":
            self.grid_data = {
                'x_num': self.input_x_num.value(),
                'x_dist': self._get_si(self.input_x_dist),
                'y_num': self.input_y_num.value(),
                'y_dist': self._get_si(self.input_y_dist),
                'z_num': self.input_z_num.value(),
                'z_dist': self._get_si(self.input_z_dist),
            }
        elif self.template_type == "2D Frame":
            self.grid_data = {
                'x_num': self.input_2d_bays.value() + 1,
                'x_dist': self._get_si(self.input_2d_bay_wd),
                'y_num': 1,
                'y_dist': 1.0,
                'z_num': self.input_2d_stories.value() + 1,
                'z_dist': self._get_si(self.input_2d_story_ht),
                'generate_frame': '2D'
            }
        elif self.template_type == "3D Frame":
            self.grid_data = {
                'x_num': self.input_3d_bays_x.value() + 1,
                'x_dist': self._get_si(self.input_3d_bay_wd_x),
                'y_num': self.input_3d_bays_y.value() + 1,
                'y_dist': self._get_si(self.input_3d_bay_wd_y),
                'z_num': self.input_3d_stories.value() + 1,
                'z_dist': self._get_si(self.input_3d_story_ht),
                'generate_frame': '3D'
            }
            
        self.accepted_data = True
        self.accept()