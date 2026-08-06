from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QPushButton, QGroupBox, QMessageBox,
                             QAbstractItemView)

from app.dialogs.time_history_function_dialog import TimeHistoryFunctionDialog
from app.ui.theme import apply_dialog_style

class TimeHistoryManagerDialog(QDialog):
    """
    Manager for Time History accelerogram functions.
    Mirrors ResponseSpectrumManagerDialog exactly.
    Functions are stored in model.th_functions (separate from model.functions
    which holds RSA spectra) — surgical, nothing else is touched.
    """

    def __init__(self, model, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.model = model

        if not hasattr(self.model, 'th_functions'):
            self.model.th_functions = {}

        self.setWindowTitle("Define Time History Functions")
        self.resize(600, 400)

        layout = QHBoxLayout(self)

        grp_list = QGroupBox("Time History Functions")
        v_list = QVBoxLayout(grp_list)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v_list.addWidget(self.list_widget)

        layout.addWidget(grp_list, stretch=1)

        right_layout = QVBoxLayout()

        grp_actions = QGroupBox("Click to:")
        v_actions = QVBoxLayout(grp_actions)

        self.btn_add = QPushButton("Add New Function...")
        self.btn_add.clicked.connect(self.add_function)

        self.btn_mod = QPushButton("Modify/Show Function...")
        self.btn_mod.clicked.connect(self.modify_function)

        self.btn_del = QPushButton("Delete Function")
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
        for name in self.model.th_functions.keys():
            self.list_widget.addItem(name)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def add_function(self):
                                          
        idx = 1
        while f"THFUNC{idx}" in self.model.th_functions:
            idx += 1
        default_name = f"THFUNC{idx}"

        dlg = TimeHistoryFunctionDialog(parent=self)
        dlg.input_name.setText(default_name)

        if dlg.exec():
            data = dlg.get_data()
            new_name = data['name']

            if new_name in self.model.th_functions:
                QMessageBox.warning(self, "Error",
                                    f"Function '{new_name}' already exists.")
                return

            self.model.th_functions[new_name] = data
            self.refresh_list()

    def modify_function(self):
        item = self.list_widget.currentItem()
        if not item:
            return

        func_name = item.text()
        data = self.model.th_functions[func_name]

        dlg = TimeHistoryFunctionDialog(parent=self)
        dlg.populate(data)

        if dlg.exec():
            new_data = dlg.get_data()
            new_name = new_data['name']

            if new_name != func_name:
                del self.model.th_functions[func_name]

            self.model.th_functions[new_name] = new_data
            self.refresh_list()

    def delete_function(self):
        item = self.list_widget.currentItem()
        if not item:
            return

        func_name = item.text()
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete function '{func_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.model.th_functions[func_name]
            self.refresh_list()
