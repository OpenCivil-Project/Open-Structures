from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QPushButton, QGroupBox, QLineEdit, 
                             QRadioButton, QButtonGroup, QFormLayout, 
                             QMessageBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QAbstractItemView)
from PyQt6.QtCore import Qt
from app.ui.theme import apply_dialog_style, COLORS
from core.units import unit_registry, UnitConverter

def _card_qss():
    """Matches the rounded, lightly-bordered panel look used in the geometry dialog."""
    return (
        f"QGroupBox {{ border: 1px solid {COLORS['border']}; border-radius: 6px; "
        f"margin-top: 10px; padding-top: 6px; font-weight: 600; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; "
        f"padding: 0 4px; color: {COLORS['accent']}; }}"
    )

class TendonLoadDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        apply_dialog_style(self)
        self.setWindowTitle("Tendon Load")
        self.setMinimumWidth(550)
        
        root = QVBoxLayout(self)
        root.setSpacing(10)
        
        top_row = QHBoxLayout()
        
        pat_group = QGroupBox("Load Pattern Name")
        pat_group.setStyleSheet(_card_qss())
        pat_layout = QVBoxLayout(pat_group)                                               
        
        self.combo_pattern = QComboBox()
        self.combo_pattern.addItems(list(self.model.load_patterns.keys()) if self.model else ["DEAD"])
        pat_layout.addWidget(self.combo_pattern)
        
        top_row.addWidget(pat_group, stretch=2)
        
        unit_group = QGroupBox("Units")
        unit_group.setStyleSheet(_card_qss())
        unit_layout = QVBoxLayout(unit_group)
        self.combo_units = QComboBox()
        self.combo_units.addItems(["kN, m, C", "N, m, C", "N, mm, C", "Tonf, m, C", "kgf, m, C", "kip, ft, F", "kip, in, F"])
        
        idx = self.combo_units.findText(unit_registry.current_unit_label)
        if idx >= 0: 
            self.combo_units.setCurrentIndex(idx)
            
        unit_layout.addWidget(self.combo_units)
        top_row.addWidget(unit_group, stretch=1)
        root.addLayout(top_row)
        
        mid_row = QHBoxLayout()
        
        jack_group = QGroupBox("Jack From This Location")
        jack_group.setStyleSheet(_card_qss())
        jack_layout = QVBoxLayout(jack_group)
        self.bg_jack = QButtonGroup(self)
        self.rb_i_end = QRadioButton("I-End (Start) of Tendon")
        self.rb_j_end = QRadioButton("J-End (End) of Tendon")
        self.rb_both = QRadioButton("Both Ends Simultaneously")
        self.rb_i_end.setChecked(True)
        for rb in (self.rb_i_end, self.rb_j_end, self.rb_both):
            self.bg_jack.addButton(rb)
            jack_layout.addWidget(rb)
        mid_row.addWidget(jack_group)
        
        type_group = QGroupBox("Load Type")
        type_group.setStyleSheet(_card_qss())
        type_layout = QVBoxLayout(type_group)
        self.bg_type = QButtonGroup(self)
        self.rb_force = QRadioButton("Force")
        self.rb_stress = QRadioButton("Stress")
        self.rb_stress.setChecked(True)
        for rb in (self.rb_force, self.rb_stress):
            self.bg_type.addButton(rb)
            type_layout.addWidget(rb)
        type_layout.addStretch()
        mid_row.addWidget(type_group)
        
        load_group = QGroupBox("Tendon Load")
        load_group.setStyleSheet(_card_qss())
        load_layout = QVBoxLayout(load_group)
        self.lbl_load = QLabel("Stress (kN/m²)")
        self.in_load = QLineEdit("0.0")
        load_layout.addWidget(self.lbl_load)
        load_layout.addWidget(self.in_load)
        load_layout.addStretch()
        mid_row.addWidget(load_group)
        
        root.addLayout(mid_row)
        
        fric_group = QGroupBox("Friction and Anchorage Losses")
        fric_group.setStyleSheet(_card_qss())
        fric_layout = QFormLayout(fric_group)
        fric_layout.setHorizontalSpacing(40)
        
        self.lbl_curve = QLabel("Curvature Coefficient (Unitless)")
        self.lbl_wobble = QLabel("Wobble Coefficient (1/m)")
        self.lbl_slip = QLabel("Anchorage Set Slip (m)")
        
        self.in_curve = QLineEdit("0.15")
        self.in_wobble = QLineEdit("3.281E-03")
        self.in_slip = QLineEdit("6.350E-03")
        
        fric_layout.addRow(self.lbl_curve, self.in_curve)
        fric_layout.addRow(self.lbl_wobble, self.in_wobble)
        fric_layout.addRow(self.lbl_slip, self.in_slip)
        root.addWidget(fric_group)
        
        loss_group = QGroupBox("Other Loss Parameters")
        loss_group.setStyleSheet(_card_qss())
        loss_layout = QFormLayout(loss_group)
        loss_layout.setHorizontalSpacing(40)
        
        self.lbl_elastic = QLabel("Elastic Shortening Stress (kN/m²)")
        self.lbl_creep = QLabel("Creep Stress (kN/m²)")
        self.lbl_shrink = QLabel("Shrinkage Stress (kN/m²)")
        self.lbl_relax = QLabel("Steel Relaxation Stress (kN/m²)")
        
        self.in_elastic = QLineEdit("0.0")
        self.in_creep = QLineEdit("0.0")
        self.in_shrink = QLineEdit("0.0")
        self.in_relax = QLineEdit("0.0")
        
        loss_layout.addRow(self.lbl_elastic, self.in_elastic)
        loss_layout.addRow(self.lbl_creep, self.in_creep)
        loss_layout.addRow(self.lbl_shrink, self.in_shrink)
        loss_layout.addRow(self.lbl_relax, self.in_relax)
        
        note_lbl = QLabel(
            "When tendons are modeled as elements, the Other Loss Parameters "
            "(elastic, creep, shrinkage, and relaxation losses) apply in addition to the "
            "losses computed by analysis."
        )
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 8pt; margin-top: 10px;")
        loss_layout.addRow(note_lbl)
        root.addWidget(loss_group)
        
        bot_row = QHBoxLayout()
        
        opt_group = QGroupBox("Options")
        opt_group.setStyleSheet(_card_qss())
        opt_layout = QVBoxLayout(opt_group)
        self.bg_opt = QButtonGroup(self)
        self.rb_replace = QRadioButton("Replace Existing Loads")
        self.rb_delete = QRadioButton("Delete Existing Loads")
        self.rb_replace.setChecked(True)
        for rb in (self.rb_replace, self.rb_delete):
            self.bg_opt.addButton(rb)
            opt_layout.addWidget(rb)
        bot_row.addWidget(opt_group)
        
        bot_row.addStretch()
        
        btn_col = QVBoxLayout()
        self.btn_show_loss = QPushButton("Show Prestress Losses")
        self.btn_show_loss.clicked.connect(self._show_losses_stub)
        
        ok_cancel_row = QHBoxLayout()
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondary")
        self.btn_cancel.clicked.connect(self.reject)
        ok_cancel_row.addWidget(self.btn_ok)
        ok_cancel_row.addWidget(self.btn_cancel)
        
        btn_col.addWidget(self.btn_show_loss)
        btn_col.addLayout(ok_cancel_row)
        btn_col.addStretch()
        
        bot_row.addLayout(btn_col)
        root.addLayout(bot_row)
        
        self.combo_units.currentTextChanged.connect(self._update_labels)
        self.rb_force.toggled.connect(self._update_labels)
        self.rb_stress.toggled.connect(self._update_labels)
        self._update_labels()

    def _update_labels(self):
        """Dynamically translates UI labels based on selected units."""
        local_unit = UnitConverter()
        local_unit.set_unit_system(self.combo_units.currentText())
        
        u_force = local_unit.force_unit_name
        u_len = local_unit.length_unit_name
        u_press = local_unit.pressure_unit

        if self.rb_force.isChecked():
            self.lbl_load.setText(f"Force ({u_force})")
        else:
            self.lbl_load.setText(f"Stress ({u_press})")
            
        self.lbl_wobble.setText(f"Wobble Coefficient (1/{u_len})")
        self.lbl_slip.setText(f"Anchorage Set Slip ({u_len})")
        
        self.lbl_elastic.setText(f"Elastic Shortening Stress ({u_press})")
        self.lbl_creep.setText(f"Creep Stress ({u_press})")
        self.lbl_shrink.setText(f"Shrinkage Stress ({u_press})")
        self.lbl_relax.setText(f"Steel Relaxation Stress ({u_press})")

    def _show_losses_stub(self):
        QMessageBox.information(self, "Tendon Response Form", "Tendon response and prestress loss charts will be available once the full solver hookup is complete.")

    def get_data(self):
        """Converts user input from the displayed unit system strictly to SI (N, m) for storage."""
        local_unit = UnitConverter()
        local_unit.set_unit_system(self.combo_units.currentText())
        
        load_type = "Force" if self.rb_force.isChecked() else "Stress"
        raw_load = float(self.in_load.text() or 0.0)
        
        if load_type == "Force":
            si_load = local_unit.from_display_force(raw_load)
        else:
            si_load = local_unit.from_display_pressure(raw_load)
            
        si_wobble = float(self.in_wobble.text() or 0.0) * local_unit.length_scale
        si_slip = local_unit.from_display_length(float(self.in_slip.text() or 0.0))
        
        return {
            "pattern": self.combo_pattern.currentText(),
            "jack_location": "I-End" if self.rb_i_end.isChecked() else ("J-End" if self.rb_j_end.isChecked() else "Both Ends"),
            "load_type": load_type,
            "load_value": si_load,
            "curvature_coeff": float(self.in_curve.text() or 0.0),
            "wobble_coeff": si_wobble,
            "anchorage_slip": si_slip,
            "elastic_stress": local_unit.from_display_pressure(float(self.in_elastic.text() or 0.0)),
            "creep_stress": local_unit.from_display_pressure(float(self.in_creep.text() or 0.0)),
            "shrinkage_stress": local_unit.from_display_pressure(float(self.in_shrink.text() or 0.0)),
            "relaxation_stress": local_unit.from_display_pressure(float(self.in_relax.text() or 0.0)),
            "action": "Replace" if self.rb_replace.isChecked() else "Delete"
        }

class TendonLoadDisplayDialog(QDialog):
    """Editable dialog to display and modify assigned tendon load properties."""
    def __init__(self, load_data, tendon_id, parent=None):
        super().__init__(parent)
                                                                      
        import copy
        self.load_data = copy.deepcopy(load_data)
        self.action_taken = "None"
        
        apply_dialog_style(self)
        self.setWindowTitle(f"Tendon Load Assignment Data For Line Object {tendon_id}")
        self.resize(680, 420)
        
        root = QHBoxLayout(self)
        root.setSpacing(15)
        
        table_group = QGroupBox("Tabular Data")
        table_group.setStyleSheet(_card_qss())
        tg = QVBoxLayout(table_group)
        
        self.table = QTableWidget(11, 2)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(self.table.styleSheet() + f"QTableWidget {{ background-color: {COLORS['bg_panel']}; }}")
        
        tg.addWidget(self.table)
        root.addWidget(table_group, stretch=5)
        
        right_panel = QVBoxLayout()
        
        unit_group = QGroupBox("Units")
        unit_group.setStyleSheet(_card_qss())
        ug = QVBoxLayout(unit_group)
        self.combo_units = QComboBox()
        self.combo_units.addItems(["kN, m, C", "N, m, C", "N, mm, C", "Tonf, m, C", "kgf, m, C", "kip, ft, F", "kip, in, F"])
        
        idx = self.combo_units.findText(unit_registry.current_unit_label)
        if idx >= 0: 
            self.combo_units.setCurrentIndex(idx)

        self._last_unit = self.combo_units.currentText()
        self.combo_units.currentTextChanged.connect(self._on_unit_changed)
        ug.addWidget(self.combo_units)
        right_panel.addWidget(unit_group)
        
        note = QLabel(
            "Note:\nThis tendon is modeled using elements. The elastic, creep, "
            "shrinkage, and relaxation loss items apply in addition to the losses "
            "computed by analysis."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 8pt; margin-top: 10px;")
        right_panel.addWidget(note)
        
        right_panel.addStretch()
        
        self.btn_show_loss = QPushButton("Show Prestress Losses")
        self.btn_show_loss.clicked.connect(self._show_losses_stub)
        right_panel.addWidget(self.btn_show_loss)
        
        self.btn_delete = QPushButton("Delete Load")
        self.btn_delete.setObjectName("danger")
        self.btn_delete.clicked.connect(self._on_delete)
        right_panel.addWidget(self.btn_delete)
        
        self.btn_done = QPushButton("Save / Done")
        self.btn_done.setObjectName("primary")
        self.btn_done.clicked.connect(self._on_done)
        right_panel.addWidget(self.btn_done)
        
        root.addLayout(right_panel, stretch=2)
        
        self._populate_table()

    def _sync_to_data(self):
        """Pulls the currently typed table values back into the SI load_data dictionary."""
        if self.table.rowCount() == 0 or not hasattr(self, '_last_unit'): return True
        
        local_unit = UnitConverter()
        local_unit.set_unit_system(self._last_unit)
        
        try:
            is_force = self.load_data.get("load_type") == "Force"
            raw_load = float(self.table.item(3, 1).text())
            si_load = local_unit.from_display_force(raw_load) if is_force else local_unit.from_display_pressure(raw_load)
            
            curve = float(self.table.item(4, 1).text())
            wobble = float(self.table.item(5, 1).text()) * local_unit.length_scale
            slip = local_unit.from_display_length(float(self.table.item(6, 1).text()))
            
            elast = local_unit.from_display_pressure(float(self.table.item(7, 1).text()))
            creep = local_unit.from_display_pressure(float(self.table.item(8, 1).text()))
            shrink = local_unit.from_display_pressure(float(self.table.item(9, 1).text()))
            relax = local_unit.from_display_pressure(float(self.table.item(10, 1).text()))
            
            self.load_data["load_value"] = si_load
            self.load_data["curvature_coeff"] = curve
            self.load_data["wobble_coeff"] = wobble
            self.load_data["anchorage_slip"] = slip
            self.load_data["elastic_stress"] = elast
            self.load_data["creep_stress"] = creep
            self.load_data["shrinkage_stress"] = shrink
            self.load_data["relaxation_stress"] = relax
            
            return True
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please ensure all editable fields contain valid numbers.")
            return False

    def _on_unit_changed(self, new_unit):
                                                                          
        if not self._sync_to_data():
            self.combo_units.blockSignals(True)
            self.combo_units.setCurrentText(self._last_unit)
            self.combo_units.blockSignals(False)
            return
            
        self._last_unit = new_unit
        self._populate_table()

    def _on_delete(self):
        self.action_taken = "Delete"
        self.accept()

    def _on_done(self):
        if not self._sync_to_data():
            return
            
        if abs(self.load_data.get("load_value", 0.0)) < 1e-9:
            self.action_taken = "Delete"
        else:
            self.action_taken = "Modify"
            
        self.accept()

    def _populate_table(self):
        """Builds the table dynamically while locking the top 3 rows."""
        from PyQt6.QtGui import QColor
        
        local_unit = UnitConverter()
        local_unit.set_unit_system(self._last_unit)
        
        u_force = local_unit.force_unit_name
        u_len = local_unit.length_unit_name
        u_press = local_unit.pressure_unit
        
        is_force = self.load_data.get("load_type") == "Force"
        lbl_val = f"Tendon End Force ({u_force})" if is_force else f"Tendon End Stress ({u_press})"
        
        raw_val = self.load_data.get('load_value', 0.0)
        disp_val = local_unit.to_display_force(raw_val) if is_force else local_unit.to_display_pressure(raw_val)
        
        disp_wobble = self.load_data.get('wobble_coeff', 0.0) / local_unit.length_scale
        disp_slip = local_unit.to_display_length(self.load_data.get('anchorage_slip', 0.0))
        
        rows = [
            ("Load Pattern", self.load_data.get("pattern", "")),
            ("Load Type", self.load_data.get("load_type", "")),
            ("Jack From This Location", self.load_data.get("jack_location", "")),
            (lbl_val, f"{disp_val:.2f}"),
            ("Curvature Coefficient (Unitless)", f"{self.load_data.get('curvature_coeff', 0.0)}"),
            (f"Wobble Coefficient (1/{u_len})", f"{disp_wobble:.3E}"),
            (f"Anchorage Set Slip ({u_len})", f"{disp_slip:.3E}"),
            (f"Loss - Elastic Shortening Stress ({u_press})", f"{local_unit.to_display_pressure(self.load_data.get('elastic_stress', 0.0)):.2f}"),
            (f"Loss - Creep Stress ({u_press})", f"{local_unit.to_display_pressure(self.load_data.get('creep_stress', 0.0)):.2f}"),
            (f"Loss - Shrinkage Stress ({u_press})", f"{local_unit.to_display_pressure(self.load_data.get('shrinkage_stress', 0.0)):.2f}"),
            (f"Loss - Steel Relaxation Stress ({u_press})", f"{local_unit.to_display_pressure(self.load_data.get('relaxation_stress', 0.0)):.2f}")
        ]
        
        self.table.blockSignals(True)
        for r, (prop, val) in enumerate(rows):
            item_prop = QTableWidgetItem(prop)
            item_prop.setFlags(item_prop.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_prop.setForeground(Qt.GlobalColor.darkBlue)
            self.table.setItem(r, 0, item_prop)
            
            item_val = QTableWidgetItem(str(val))
            item_val.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            if r < 3: 
                item_val.setFlags(item_val.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item_val.setBackground(QColor(COLORS['bg_disabled']))
            self.table.setItem(r, 1, item_val)
        self.table.blockSignals(False)

    def _show_losses_stub(self):
        QMessageBox.information(self, "Tendon Response Form", "Tendon response and prestress loss charts will be available once the full solver hookup is complete.")
