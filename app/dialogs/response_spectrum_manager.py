import sys
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, 
                             QPushButton, QLabel, QGroupBox, QMessageBox, 
                             QComboBox, QAbstractItemView)
from PyQt6.QtCore import Qt

from app.dialogs.response_spectrum_dialog import ResponseSpectrumDialog
from app.ui.theme import apply_dialog_style

class ResponseSpectrumManagerDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.model = model
        
        if not hasattr(self.model, 'functions'):
            self.model.functions = {}

        self.setWindowTitle("Define Response Spectrum Functions")
        self.resize(600, 400)
        
        layout = QHBoxLayout(self)

        grp_list = QGroupBox("Response Spectra")
        v_list = QVBoxLayout(grp_list)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v_list.addWidget(self.list_widget)
        
        layout.addWidget(grp_list, stretch=1)

        right_layout = QVBoxLayout()
        
        grp_type = QGroupBox("Choose Function Type to Add")
        v_type = QVBoxLayout(grp_type)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["TSC-2018", "User Defined (Coming Soon)"])
        v_type.addWidget(self.combo_type)
        right_layout.addWidget(grp_type)

        grp_actions = QGroupBox("Click to:")
        v_actions = QVBoxLayout(grp_actions)
        
        self.btn_add = QPushButton("Add New Function...")
        self.btn_add.clicked.connect(self.add_function)
        
        self.btn_mod = QPushButton("Modify/Show Spectrum...")
        self.btn_mod.clicked.connect(self.modify_function)
        
        self.btn_del = QPushButton("Delete Spectrum")
        self.btn_del.clicked.connect(self.delete_function)
        
        v_actions.addWidget(self.btn_add)
        v_actions.addWidget(self.btn_mod)
        v_actions.addWidget(self.btn_del)
        right_layout.addWidget(grp_actions)
        
        right_layout.addStretch()
        
        h_ok = QHBoxLayout()
        self.btn_ok = QPushButton("OK")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        h_ok.addWidget(self.btn_ok)
        h_ok.addWidget(self.btn_cancel)
        right_layout.addLayout(h_ok)

        layout.addLayout(right_layout, stretch=1)
        
        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        for name in self.model.functions.keys():
            self.list_widget.addItem(name)
            
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def add_function(self):
        """Opens the Editor with default values."""
                    
        ftype = self.combo_type.currentText()
        if ftype != "TSC-2018":
            QMessageBox.information(self, "Info", "Only TSC-2018 is supported in this version.")
            return

        idx = 1
        while f"FUNC{idx}" in self.model.functions:
            idx += 1
        default_name = f"FUNC{idx}"
        
        dlg = ResponseSpectrumDialog(parent=self)
        dlg.input_name.setText(default_name)
        
        if dlg.exec():
            data = dlg.get_data()
            new_name = data['name']
            
            if new_name in self.model.functions:
                QMessageBox.warning(self, "Error", f"Function '{new_name}' already exists.")
                return

            self.model.functions[new_name] = data
            self.refresh_list()

    def modify_function(self):
        """Opens the Editor with existing values."""
        item = self.list_widget.currentItem()
        if not item: return
        
        func_name = item.text()
        data = self.model.functions[func_name]
        
        dlg = ResponseSpectrumDialog(parent=self)
        self.populate_dialog(dlg, data)
        
        if dlg.exec():
            new_data = dlg.get_data()
            new_name = new_data['name']
            
            if new_name != func_name:
                del self.model.functions[func_name]
            
            self.model.functions[new_name] = new_data
            self.refresh_list()

    def delete_function(self):
        item = self.list_widget.currentItem()
        if not item: return
        
        func_name = item.text()
        del self.model.functions[func_name]
        self.refresh_list()

    def populate_dialog(self, dlg, data):
        """Helper to fill the editor with saved data."""
        dlg.input_name.setText(data.get('name', ''))
        dlg.in_ss.setText(str(data.get('Ss', 0.55)))
        dlg.in_s1.setText(str(data.get('S1', 0.22)))
        dlg.in_tl.setText(str(data.get('TL', 6.0)))
        dlg.in_R.setText(str(data.get('R', 8.0)))
        dlg.in_D.setText(str(data.get('D', 3.0)))
        dlg.in_I.setText(str(data.get('I', 1.0)))
        dlg.combo_site.setCurrentText(data.get('SiteClass', 'ZB'))
        dlg.in_damp.setText(str(data.get('Damping', 0.05)))
        
        dlg.combo_dir.setCurrentText(data.get('Direction', 'Horizontal'))
        
        dlg.update_graph()
