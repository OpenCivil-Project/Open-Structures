from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, 
                             QPushButton, QLabel, QComboBox, QTableWidget, 
                             QTableWidgetItem, QGroupBox, QCheckBox,
                             QMessageBox, QHeaderView, QLineEdit, QWidget)
from PyQt6.QtCore import Qt
                                                                 
from core.model import MassSource
from app.ui.theme import apply_dialog_style

class MassSourceDataDialog(QDialog):
    """
    The 'Define/Modify Mass Source' window.
    Mimics SAP2000 'Mass Source Data' dialog.
    """
    def __init__(self, model, mass_source, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.model = model
        self.mass_source = mass_source
        self.original_name = mass_source.name
        
        self.setWindowTitle("Mass Source Data")
        self.resize(500, 500)
        
        layout = QVBoxLayout(self)
        
        h_name = QHBoxLayout()
        h_name.addWidget(QLabel("Mass Source Name"))
        self.input_name = QLineEdit(self.mass_source.name)
        h_name.addWidget(self.input_name)
        layout.addLayout(h_name)
        
        grp_src = QGroupBox("Mass Source")
        v_src = QVBoxLayout(grp_src)
        
        self.chk_self_mass = QCheckBox("Element Self Mass and Additional Mass")
        self.chk_self_mass.setChecked(self.mass_source.include_self_mass)
        v_src.addWidget(self.chk_self_mass)
        
        self.chk_patterns = QCheckBox("Specified Load Patterns")
        self.chk_patterns.setChecked(self.mass_source.include_patterns)
                                                                                 
        self.chk_patterns.toggled.connect(self.toggle_patterns)
        v_src.addWidget(self.chk_patterns)
        
        layout.addWidget(grp_src)
        
        self.grp_multipliers = QGroupBox("Mass Multipliers for Load Patterns")
        v_mult = QVBoxLayout(self.grp_multipliers)
        
        h_sel = QHBoxLayout()
        h_sel.addWidget(QLabel("Load Pattern"))
        self.combo_pattern = QComboBox()
        self.combo_pattern.addItems(self.model.load_patterns.keys())
        h_sel.addWidget(self.combo_pattern)
        
        h_sel.addWidget(QLabel("Multiplier"))
        self.input_mult = QLineEdit("1")
        self.input_mult.setFixedWidth(60)
        h_sel.addWidget(self.input_mult)
        
        self.btn_add = QPushButton("Add")
        self.btn_add.clicked.connect(self.add_pattern)
        h_sel.addWidget(self.btn_add)
        
        v_mult.addLayout(h_sel)
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Load Pattern", "Multiplier"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        v_mult.addWidget(self.table)
        
        h_mod = QHBoxLayout()
        h_mod.addStretch()
        
        self.btn_modify = QPushButton("Modify")
        self.btn_modify.clicked.connect(self.modify_pattern)
        h_mod.addWidget(self.btn_modify)
        
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.delete_pattern)
        h_mod.addWidget(self.btn_delete)
        
        v_mult.addLayout(h_mod)
        layout.addWidget(self.grp_multipliers)
        
        h_btns = QHBoxLayout()
        h_btns.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.on_ok)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        
        h_btns.addWidget(btn_ok)
        h_btns.addWidget(btn_cancel)
        layout.addLayout(h_btns)
        
        self.populate_table()
        self.toggle_patterns(self.chk_patterns.isChecked())

    def toggle_patterns(self, state):
        self.grp_multipliers.setEnabled(state)

    def populate_table(self):
        self.table.setRowCount(0)
        for pat, mult in self.mass_source.load_patterns:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(pat))
            self.table.setItem(row, 1, QTableWidgetItem(str(mult)))

    def add_pattern(self):
        pat = self.combo_pattern.currentText()
        if not pat: return
        
        try:
            mult = float(self.input_mult.text())
        except ValueError:
            QMessageBox.warning(self, "Error", "Multiplier must be a number.")
            return

        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() == pat:
                self.table.item(r, 1).setText(str(mult))                  
                return

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(pat))
        self.table.setItem(row, 1, QTableWidgetItem(str(mult)))

    def modify_pattern(self):
        row = self.table.currentRow()
        if row < 0: return
        
        try:
            mult = float(self.input_mult.text())
            self.table.item(row, 1).setText(str(mult))
                                                                                                                    
            pat_current = self.table.item(row, 0).text()
            if pat_current != self.combo_pattern.currentText():
                                                                                                   
                 self.table.item(row, 0).setText(self.combo_pattern.currentText())
        except ValueError:
            pass

    def delete_pattern(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def on_ok(self):
                                  
        new_name = self.input_name.text().strip()
        if not new_name:
             QMessageBox.warning(self, "Error", "Name required.")
             return
        
        incl_self_mass = self.chk_self_mass.isChecked()
        incl_patterns = self.chk_patterns.isChecked()

        if incl_self_mass and incl_patterns:
            double_count_risk = False
                                                        
            for r in range(self.table.rowCount()):
                pat_name = self.table.item(r, 0).text()
                
                if pat_name in self.model.load_patterns:
                    lp = self.model.load_patterns[pat_name]
                                                                                      
                    if lp.self_weight_multiplier > 0:
                        double_count_risk = True
                        break
            
            if double_count_risk:
                reply = QMessageBox.question(
                    self, 
                    "Warning: Potential Double Counting", 
                    "You have selected both 'Element Self Mass' and a Load Pattern that includes self-weight > 0.\n\n"
                    "This may result in self-weight being counted twice in the mass matrix.\n\n"
                    "Are you sure you want to proceed?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.No:
                    return
             
        self.mass_source.name = new_name
        self.mass_source.include_self_mass = self.chk_self_mass.isChecked()
        self.mass_source.include_patterns = self.chk_patterns.isChecked()
        
        self.mass_source.load_patterns = []
        if self.mass_source.include_patterns:
            for r in range(self.table.rowCount()):
                pat = self.table.item(r, 0).text()
                try:
                    mult = float(self.table.item(r, 1).text())
                    self.mass_source.load_patterns.append((pat, mult))
                except: pass
        
        self.accept()

class MassSourceManagerDialog(QDialog):
    """
    The 'Define Mass Source' List Window.
    """
    def __init__(self, model, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.model = model
        
        if not hasattr(self.model, 'mass_sources'):
            self.model.mass_sources = {}
                                     
            if "MSSSRC1" not in self.model.mass_sources:
                 def_ms = MassSource("MSSSRC1")
                 self.model.mass_sources["MSSSRC1"] = def_ms

        if not hasattr(self.model, 'active_mass_source'):
            self.model.active_mass_source = "MSSSRC1"

        self.setWindowTitle("Mass Source")
        self.resize(500, 400)
        
        layout = QHBoxLayout(self)
        
        grp_list = QGroupBox("Mass Sources")
        v_list = QVBoxLayout(grp_list)
        self.list_widget = QListWidget()
        v_list.addWidget(self.list_widget)
        layout.addWidget(grp_list)
        
        v_ctrl = QVBoxLayout()
        v_ctrl.addWidget(QLabel("Click to:"))
        
        btn_add = QPushButton("Add New Mass Source...")
        btn_add.clicked.connect(self.add_source)
        v_ctrl.addWidget(btn_add)
        
        btn_copy = QPushButton("Add Copy of Mass Source...")
        btn_copy.clicked.connect(self.copy_source)
        v_ctrl.addWidget(btn_copy)
        
        btn_mod = QPushButton("Modify/Show Mass Source...")
        btn_mod.clicked.connect(self.modify_source)
        v_ctrl.addWidget(btn_mod)
        
        btn_del = QPushButton("Delete Mass Source")
        btn_del.clicked.connect(self.delete_source)
        v_ctrl.addWidget(btn_del)
        
        v_ctrl.addStretch()
        
        grp_def = QGroupBox("Default Mass Source")
        v_def = QVBoxLayout(grp_def)
        self.combo_default = QComboBox()
        self.combo_default.currentTextChanged.connect(self.set_default)
        v_def.addWidget(self.combo_default)
        v_ctrl.addWidget(grp_def)
        
        h_ok = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        h_ok.addWidget(btn_ok)
        h_ok.addWidget(btn_cancel)
        v_ctrl.addLayout(h_ok)
        
        layout.addLayout(v_ctrl)
        
        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        self.combo_default.blockSignals(True)
        self.combo_default.clear()
        
        for name in self.model.mass_sources.keys():
            self.list_widget.addItem(name)
            self.combo_default.addItem(name)
            
        if hasattr(self.model, 'active_mass_source'):
            self.combo_default.setCurrentText(self.model.active_mass_source)
            
        self.combo_default.blockSignals(False)

    def add_source(self):
                       
        idx = 1
        while f"MSSSRC{idx}" in self.model.mass_sources:
            idx += 1
        new_name = f"MSSSRC{idx}"
        
        new_ms = MassSource(new_name)
        
        dlg = MassSourceDataDialog(self.model, new_ms, self)
        if dlg.exec():
                               
            if new_ms.name in self.model.mass_sources:
                 QMessageBox.warning(self, "Error", "Name already exists. Reverting to default.")
                 new_ms.name = new_name
            
            self.model.mass_sources[new_ms.name] = new_ms
            self.refresh_list()

    def copy_source(self):
        item = self.list_widget.currentItem()
        if not item: return
        src = self.model.mass_sources[item.text()]
        
        import copy
        new_ms = copy.deepcopy(src)
        new_ms.name = src.name + "_Copy"
        
        dlg = MassSourceDataDialog(self.model, new_ms, self)
        if dlg.exec():
            self.model.mass_sources[new_ms.name] = new_ms
            self.refresh_list()

    def modify_source(self):
        item = self.list_widget.currentItem()
        if not item: return
        old_name = item.text()
        src = self.model.mass_sources[old_name]
        
        dlg = MassSourceDataDialog(self.model, src, self)
        if dlg.exec():
                             
            if src.name != old_name:
                del self.model.mass_sources[old_name]
                self.model.mass_sources[src.name] = src
                
                if self.model.active_mass_source == old_name:
                    self.model.active_mass_source = src.name
            
            self.refresh_list()

    def delete_source(self):
        item = self.list_widget.currentItem()
        if not item: return
        name = item.text()
        
        if len(self.model.mass_sources) <= 1:
            QMessageBox.warning(self, "Error", "Cannot delete the last Mass Source.")
            return
            
        del self.model.mass_sources[name]
        self.refresh_list()

    def set_default(self, name):
        if name in self.model.mass_sources:
            self.model.active_mass_source = name
