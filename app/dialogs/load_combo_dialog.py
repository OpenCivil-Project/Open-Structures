from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QPushButton, QLabel, QComboBox, QTableWidget,
                             QTableWidgetItem, QGroupBox, QMessageBox, QHeaderView,
                             QLineEdit)
from PyQt6.QtCore import Qt
from core.model import LoadCombination
from app.ui.theme import apply_dialog_style

class LoadComboDetailDialog(QDialog):
    """The 'Modify/Show' window for a single load combination."""
    def __init__(self, model, combo, parent=None, is_new=False):
        super().__init__(parent)
        self.model = model
        self.combo = combo
        self.original_name = combo.name
        self.is_new = is_new

        self.setWindowTitle("Load Combination Data")
        self.resize(500, 450)
        apply_dialog_style(self)

        layout = QVBoxLayout(self)

        # --- General Data ---
        grp_top = QGroupBox("General")
        v_top = QVBoxLayout(grp_top)
        
        h_name = QHBoxLayout()
        h_name.addWidget(QLabel("Load Combination Name:"))
        self.input_name = QLineEdit(self.combo.name)
        self.input_name.setStyleSheet("font-weight: bold;")
        h_name.addWidget(self.input_name)
        v_top.addLayout(h_name)

        h_type = QHBoxLayout()
        h_type.addWidget(QLabel("Combination Type:"))
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Linear Add", "Envelope", "Absolute Add", "SRSS"])
        self.combo_type.setCurrentText(self.combo.combo_type)
        h_type.addWidget(self.combo_type)
        v_top.addLayout(h_type)

        layout.addWidget(grp_top)

        # --- Definition Table ---
        self.group_def = QGroupBox("Define Combination")
        v_def = QVBoxLayout(self.group_def)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Load Case Name", "Scale Factor"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v_def.addWidget(self.table)

        h_tbl_btns = QHBoxLayout()
        self.btn_add_row = QPushButton("Add")
        self.btn_add_row.clicked.connect(self.add_row)
        self.btn_del_row = QPushButton("Delete")
        self.btn_del_row.setObjectName("danger")
        self.btn_del_row.clicked.connect(self.delete_row)
        
        h_tbl_btns.addStretch()
        h_tbl_btns.addWidget(self.btn_add_row)
        h_tbl_btns.addWidget(self.btn_del_row)
        v_def.addLayout(h_tbl_btns)

        layout.addWidget(self.group_def)

        # --- Dialog Buttons ---
        h_btns = QHBoxLayout()
        h_btns.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setFixedWidth(100)
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.on_ok)
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        
        h_btns.addWidget(btn_ok)
        h_btns.addWidget(btn_cancel)
        layout.addLayout(h_btns)

        self.populate_table()

    def populate_table(self):
        self.table.setRowCount(0)
        for case_name, scale in self.combo.cases:
            self.add_row(case_name, scale)

    def add_row(self, case_name=None, scale=1.0):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        cmb = QComboBox()
        
        # --- NEW CODE: Filter out Modal, Buckling, and LTHA ---
        valid_cases = []
        if self.model.load_cases:
            for name, lc in self.model.load_cases.items():
                # Check the case type and skip the invalid ones
                if lc.case_type not in ["Modal", "Buckling", "LTHA"]:
                    valid_cases.append(name)
        
        # Populate the combo box with only the valid cases
        if valid_cases:
            cmb.addItems(valid_cases)
        else:
            cmb.addItem("None")
            
        # Set the current text if we are loading an existing combination
        if case_name and case_name in valid_cases:
            cmb.setCurrentText(case_name)
            
        self.table.setCellWidget(row, 0, cmb)
        self.table.setItem(row, 1, QTableWidgetItem(str(scale)))

    def delete_row(self):
        cr = self.table.currentRow()
        if cr >= 0:
            self.table.removeRow(cr)

    def on_ok(self):
        new_name = self.input_name.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Error", "Name cannot be empty.")
            return
        if new_name != self.original_name and new_name in self.model.load_combos:
            QMessageBox.warning(self, "Error", "Combo name already exists.")
            return
        self.accept()

    def get_data(self):
        c = LoadCombination(self.input_name.text().strip(), self.combo_type.currentText())
        for r in range(self.table.rowCount()):
            cmb = self.table.cellWidget(r, 0)
            if not cmb: continue
            try:
                scale = float(self.table.item(r, 1).text())
            except:
                scale = 1.0
            c.cases.append((cmb.currentText(), scale))
        return c


class LoadComboManagerDialog(QDialog):
    """The Main List Window (Define Load Combinations)"""
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Define Load Combinations")
        self.resize(500, 300)
        apply_dialog_style(self)

        layout = QHBoxLayout(self)

        self.list_widget = QListWidget()
        self.refresh_list()
        layout.addWidget(self.list_widget)

        v_btns = QVBoxLayout()

        btn_add = QPushButton("Add New Combo...")
        btn_add.clicked.connect(self.add_combo)

        btn_mod = QPushButton("Modify/Show Combo...")
        btn_mod.clicked.connect(self.modify_combo)

        btn_del = QPushButton("Delete Combo")
        btn_del.clicked.connect(self.delete_combo)

        v_btns.addWidget(btn_add)
        v_btns.addWidget(btn_mod)
        v_btns.addWidget(btn_del)
        v_btns.addStretch()

        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        v_btns.addWidget(btn_ok)

        layout.addLayout(v_btns)

    def refresh_list(self):
        self.list_widget.clear()
        for name in self.model.load_combos.keys():
            self.list_widget.addItem(name)

    def add_combo(self):
        idx = 1
        while f"COMB{idx}" in self.model.load_combos:
            idx += 1
        temp_combo = LoadCombination(f"COMB{idx}")
        dlg = LoadComboDetailDialog(self.model, temp_combo, self, is_new=True)
        if dlg.exec():
            final_combo = dlg.get_data()
            self.model.load_combos[final_combo.name] = final_combo
            self.refresh_list()

    def modify_combo(self):
        item = self.list_widget.currentItem()
        if not item: return
        old_name = item.text()
        if old_name in self.model.load_combos:
            original_combo = self.model.load_combos[old_name]
            dlg = LoadComboDetailDialog(self.model, original_combo, self, is_new=False)
            if dlg.exec():
                new_combo = dlg.get_data()
                if new_combo.name != old_name:
                    del self.model.load_combos[old_name]
                self.model.load_combos[new_combo.name] = new_combo
                self.refresh_list()

    def delete_combo(self):
        item = self.list_widget.currentItem()
        if not item: return
        name = item.text()
        del self.model.load_combos[name]
        self.refresh_list()