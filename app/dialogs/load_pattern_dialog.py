from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTableWidget, QTableWidgetItem, QPushButton,
                             QLineEdit, QComboBox, QMessageBox, QHeaderView,
                             QAbstractItemView)
from PyQt6.QtCore import Qt

from app.ui.theme import apply_dialog_style                      

class LoadPatternDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Define Load Patterns")
        self.resize(650, 400)

        apply_dialog_style(self)                                                      

        layout = QVBoxLayout(self)

        input_layout = QHBoxLayout()

        v_name = QVBoxLayout()
        v_name.addWidget(QLabel("Load Pattern Name:"))
        self.input_name = QLineEdit("LIVE")
        self.input_name.setPlaceholderText("Name")
        v_name.addWidget(self.input_name)
        input_layout.addLayout(v_name)

        v_type = QVBoxLayout()
        v_type.addWidget(QLabel("Type:"))
        self.input_type = QComboBox()
        self.input_type.addItems(["DEAD", "LIVE", "SUPERDEAD", "WIND", "QUAKE", "SNOW"])
        self.input_type.currentTextChanged.connect(self.auto_set_multiplier)
        v_type.addWidget(self.input_type)
        input_layout.addLayout(v_type)

        v_mult = QVBoxLayout()
        v_mult.addWidget(QLabel("Self Wt Mult:"))
        self.input_sw = QLineEdit("0.0")
        self.input_sw.setFixedWidth(80)
        v_mult.addWidget(self.input_sw)
        input_layout.addLayout(v_mult)

        v_auto = QVBoxLayout()
        v_auto.addWidget(QLabel("Auto Lateral Load:"))
        self.input_auto = QComboBox()
        self.input_auto.addItems(["None", "User Loads", "TSC-2018"])
        self.input_auto.setEnabled(False) # Disabled by default (unless QUAKE is selected)
        v_auto.addWidget(self.input_auto)
        input_layout.addLayout(v_auto)

        v_btns = QVBoxLayout()
        v_btns.addSpacing(18)

        h_action_btns = QHBoxLayout()
        btn_add = QPushButton("Add New")
        btn_add.setObjectName("primary")                             
        btn_add.clicked.connect(self.add_pattern)

        self.btn_modify = QPushButton("Modify")
                                                 
        self.btn_modify.clicked.connect(self.modify_pattern)

        h_action_btns.addWidget(btn_add)
        h_action_btns.addWidget(self.btn_modify)
        v_btns.addLayout(h_action_btns)

        self.btn_modify_lateral = QPushButton("Modify Lateral Load Pattern...")
        self.btn_modify_lateral.clicked.connect(self.open_seismic_dialog)
        self.btn_modify_lateral.setEnabled(False) 
        v_btns.addWidget(self.btn_modify_lateral)
        
        input_layout.addLayout(v_btns)

        layout.addLayout(input_layout)
        layout.addSpacing(10)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Load Pattern Name", "Type", "Self Wt. Multiplier", "Auto Lateral Load"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_delete = QPushButton("Delete Pattern")
        btn_delete.clicked.connect(self.delete_pattern)

        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")                                                        
        btn_ok.setFixedWidth(100)
        btn_ok.clicked.connect(self.save_and_accept)

        btn_layout.addWidget(btn_delete)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

        self.refresh_table()

    def save_and_accept(self):
        """Auto-commits any pending UI changes before closing."""
        name = self.input_name.text().strip().upper()
        # If the currently typed name exists in the model, force a modification
        if name in self.model.load_patterns:
            self.modify_pattern()
        self.accept()

    def auto_set_multiplier(self, type_text):
        self.input_sw.setText("1.0" if type_text == "DEAD" else "0.0")
        
        # Only enable Auto Lateral Load for Seismic (QUAKE)
        if type_text == "QUAKE":
            self.input_auto.setEnabled(True)
        else:
            self.input_auto.setEnabled(False)
            self.input_auto.setCurrentText("None")

    def on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0: return
        pat_type = self.table.item(row, 1).text()
        
        self.input_name.setText(self.table.item(row, 0).text())
        self.input_type.blockSignals(True)
        self.input_type.setCurrentText(pat_type)
        self.input_type.blockSignals(False)
        self.input_sw.setText(self.table.item(row, 2).text())
        
        # Strictly enable the dropdown ONLY for QUAKE
        self.input_auto.setEnabled(pat_type == "QUAKE")

        auto_text = self.table.item(row, 3).text()
        self.input_auto.setCurrentText(auto_text)

        # Toggle lateral button (Only enable if it's NOT 'None' AND it's QUAKE)
        if hasattr(self, 'btn_modify_lateral'):
            self.btn_modify_lateral.setEnabled(pat_type == "QUAKE" and auto_text != "None")

    def refresh_table(self):
        self.table.setRowCount(0)
        for name, lp in self.model.load_patterns.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(lp.name))
            self.table.setItem(row, 1, QTableWidgetItem(lp.pattern_type))
            self.table.setItem(row, 2, QTableWidgetItem(str(lp.self_weight_multiplier)))
            
            # Fetch auto lateral property (default to None if it doesn't exist yet)
            auto_type = getattr(lp, 'auto_lateral', "None")
            self.table.setItem(row, 3, QTableWidgetItem(auto_type))

    def add_pattern(self):
        name = self.input_name.text().strip().upper()
        if not name: return QMessageBox.warning(self, "Error", "Name cannot be empty.")
        if name in self.model.load_patterns: return QMessageBox.warning(self, "Error", f"Pattern '{name}' already exists.")
        
        try: mult = float(self.input_sw.text())
        except ValueError: return QMessageBox.warning(self, "Error", "Multiplier must be a number.")
        
        self.model.add_load_pattern(name, self.input_type.currentText(), mult)
        
        # Save the Auto Lateral Selection
        lp = self.model.load_patterns[name]
        lp.auto_lateral = self.input_auto.currentText()
        
        self.refresh_table()

    def modify_pattern(self):
        name = self.input_name.text().strip().upper()
        if not name or name not in self.model.load_patterns: return
        
        try: mult = float(self.input_sw.text())
        except ValueError: return QMessageBox.warning(self, "Error", "Multiplier must be a number.")
        
        lp = self.model.load_patterns[name]
        lp.pattern_type = self.input_type.currentText()
        lp.self_weight_multiplier = mult
        lp.auto_lateral = self.input_auto.currentText()
        
        self.refresh_table()
        items = self.table.findItems(name, Qt.MatchFlag.MatchExactly)
        if items: self.table.setCurrentItem(items[0])

    def open_seismic_dialog(self):
        row = self.table.currentRow()
        if row < 0: return
        pat_name = self.table.item(row, 0).text()
        lp = self.model.load_patterns[pat_name]
        
        auto_type = getattr(lp, 'auto_lateral', "None")
        
        if auto_type == "User Loads":
            from app.dialogs.user_seismic_dialog import UserSeismicDialog
            dialog = UserSeismicDialog(lp, self.model, self)
            dialog.exec()
            
        elif auto_type == "TSC-2018":
            from app.dialogs.tsc2018_dialog import TSC2018Dialog
            dialog = TSC2018Dialog(lp, self)
            dialog.exec()


    def delete_pattern(self):
        current_row = self.table.currentRow()
        if current_row < 0: return
        name = self.table.item(current_row, 0).text()
        del self.model.load_patterns[name]
        self.refresh_table()
        self.input_name.clear()
