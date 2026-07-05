import sys
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QLabel, QHeaderView,
                             QAbstractItemView, QGroupBox, QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon

from app.ui.theme import apply_dialog_style, COLORS                      

class AnalysisDialog(QDialog):

    signal_run_analysis = pyqtSignal(str, bool)
    _last_run_case = None

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Run Analysis")
        self.resize(700, 500)
        self.setModal(True)

        apply_dialog_style(self)                                                  

        layout = QVBoxLayout(self)

        grp_cases = QGroupBox("Load Cases")
        v_cases = QVBoxLayout(grp_cases)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Case Name", "Type", "Status", "Action"])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                                                           
        v_cases.addWidget(self.table)

        h_tbl_btns = QHBoxLayout()

        self.btn_toggle = QPushButton("Toggle Run / Do Not Run")
        self.btn_toggle.clicked.connect(self.toggle_case_action)
                                 
        self.btn_show = QPushButton("Show Case...")
        self.btn_show.setEnabled(False)

        self.btn_delete_res = QPushButton("Delete Results")
        self.btn_delete_res.setEnabled(False)

        h_tbl_btns.addStretch()
        h_tbl_btns.addWidget(self.btn_toggle)
        h_tbl_btns.addWidget(self.btn_show)
        h_tbl_btns.addWidget(self.btn_delete_res)

        v_cases.addLayout(h_tbl_btns)
        layout.addWidget(grp_cases)

        grp_options = QGroupBox("Analysis Options")
        v_options = QVBoxLayout(grp_options)

        self.chk_messages = QCheckBox("Show Analysis Log")
        self.chk_messages.setChecked(True)
        v_options.addWidget(self.chk_messages)

        self.chk_lock = QCheckBox("Lock Model During Analysis (Prevent Editing)")
        self.chk_lock.setChecked(True)
        self.chk_lock.setEnabled(False)
        v_options.addWidget(self.chk_lock)

        layout.addWidget(grp_options)

        h_btns = QHBoxLayout()
        h_btns.addStretch()

        self.btn_run = QPushButton("Run Now")
        self.btn_run.setFixedWidth(120)
        self.btn_run.setObjectName("primary")                                                   
        self.btn_run.clicked.connect(self.on_run_clicked)

        self.btn_cancel = QPushButton("Close")
        self.btn_cancel.setFixedWidth(120)
                                                                         
        self.btn_cancel.clicked.connect(self.reject)

        h_btns.addWidget(self.btn_run)
        h_btns.addWidget(self.btn_cancel)
        layout.addLayout(h_btns)

        self.populate_table()
        self.btn_run.setDefault(True)
        self.btn_run.setFocus()

    def populate_table(self):
        self.table.setRowCount(0)

        case_list = []
        if hasattr(self.model, 'load_cases') and self.model.load_cases:
            case_list.extend(list(self.model.load_cases.values()))

        if not case_list:
            case_list = [{"name": "DEAD", "type": "Linear Static"}]

        first_name = None
        for c in case_list:
            first_name = c.get('name', 'Unknown') if isinstance(c, dict) else getattr(c, 'name', 'Unknown')
            break
        default_case = AnalysisDialog._last_run_case or first_name

        for row, case in enumerate(case_list):
            if isinstance(case, dict):
                name = case.get('name', 'Unknown')
                c_type = case.get('type', 'Linear Static')
            else:
                name = getattr(case, 'name', 'Unknown')
                c_type = getattr(case, 'case_type', getattr(case, 'type', 'Linear Static'))

            status = "Not Run"
            action = "Run" if name == default_case else "Do Not Run"

            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(name)))
            self.table.setItem(row, 1, QTableWidgetItem(str(c_type)))
            self.table.setItem(row, 2, QTableWidgetItem(status))

            act_item = QTableWidgetItem(action)
            act_item.setForeground(QColor(COLORS["accent"] if action == "Run" else COLORS["text_primary"]))
            font = act_item.font()
            font.setBold(action == "Run")
            act_item.setFont(font)
            self.table.setItem(row, 3, act_item)
            self.table.item(row, 2).setForeground(QColor(COLORS["text_secondary"]))

        if hasattr(self.model, 'load_cases') and self.model.load_cases:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            has_combos = hasattr(self.model, 'load_combos') and self.model.load_combos
            name = "Run All Cases & Combinations" if has_combos else "Run All Load Cases"
            c_type = "Batch Run"
            status = "Ready"
            action = "Run" if name == default_case else "Do Not Run"

            for col, text in enumerate([name, c_type, status]):
                item = QTableWidgetItem(text)
                if col == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(row, col, item)

            act_item = QTableWidgetItem(action)
            act_item.setForeground(QColor(COLORS["accent"] if action == "Run" else COLORS["text_primary"]))
            font = act_item.font()
            font.setBold(action == "Run")
            act_item.setFont(font)
            self.table.setItem(row, 3, act_item)

        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def toggle_case_action(self):
        row = self.table.currentRow()
        if row < 0:
            return

        current_item = self.table.item(row, 3)

        if current_item.text() == "Run":
            current_item.setText("Do Not Run")
            current_item.setForeground(QColor(COLORS["text_primary"]))
            font = current_item.font(); font.setBold(False); current_item.setFont(font)
        else:
            for r in range(self.table.rowCount()):
                item = self.table.item(r, 3)
                item.setText("Do Not Run")
                item.setForeground(QColor(COLORS["text_primary"]))
                font = item.font(); font.setBold(False); item.setFont(font)

            current_item.setText("Run")
            current_item.setForeground(QColor(COLORS["accent"]))
            font = current_item.font(); font.setBold(True); current_item.setFont(font)

    def on_run_clicked(self):
        cases_to_run = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 3).text() == "Run":
                cases_to_run.append(self.table.item(r, 0).text())

        if not cases_to_run:
            QMessageBox.warning(self, "No Cases", "Please select at least one load case to run.")
            return

        target_case = cases_to_run[0]
        if target_case == "Run All Load Cases":
            target_case = "Run All Cases & Combinations"
            
        AnalysisDialog._last_run_case = target_case
        self.signal_run_analysis.emit(target_case, self.chk_messages.isChecked())
        self.accept()
