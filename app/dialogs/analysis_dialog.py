import sys
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QLabel, QHeaderView,
                             QAbstractItemView, QGroupBox, QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QUndoCommand

from app.ui.theme import apply_dialog_style, COLORS                      
from app.dialogs.load_case_dialog import LoadCaseDetailDialog

class CmdRunPrefsChanged(QUndoCommand):
    """Marks the model dirty when the Run Analysis selection changes (values already applied)."""
    def __init__(self):
        super().__init__("Run Analysis Selection")
    def undo(self): pass
    def redo(self): pass

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
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.doubleClicked.connect(self.on_show_case_clicked)
                                                           
        v_cases.addWidget(self.table)

        h_tbl_btns = QHBoxLayout()

        self.btn_toggle = QPushButton("Toggle Run / Do Not Run")
        self.btn_toggle.clicked.connect(self.toggle_case_action)
                                 
        self.btn_show = QPushButton("Show Case...")
        self.btn_show.setEnabled(False)
        self.btn_show.clicked.connect(self.on_show_case_clicked)

        h_tbl_btns.addStretch()
        h_tbl_btns.addWidget(self.btn_toggle)
        h_tbl_btns.addWidget(self.btn_show)

        v_cases.addLayout(h_tbl_btns)
        layout.addWidget(grp_cases)

        grp_options = QGroupBox("Analysis Options")
        v_options = QVBoxLayout(grp_options)

        self.chk_messages = QCheckBox("Show Analysis Log")
        self.chk_messages.setChecked(bool(getattr(self.model, 'show_analysis_log', True)))
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

        names = [c.get('name', 'Unknown') if isinstance(c, dict) else getattr(c, 'name', 'Unknown')
                 for c in case_list]
        first_name = names[0] if names else None

        has_batch = bool(getattr(self.model, 'load_cases', None))
        has_combos_now = bool(getattr(self.model, 'load_combos', None))
        batch_name = "Run All Cases & Combinations" if has_combos_now else "Run All Load Cases"

        saved = getattr(self.model, 'last_run_case', None) or AnalysisDialog._last_run_case
        if saved in ("Run All Load Cases", "Run All Cases & Combinations") and has_batch:
            default_case = batch_name
        elif saved in names:
            default_case = saved
        else:
            default_case = first_name

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

    def on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0:
            self.btn_show.setEnabled(False)
            return
        item = self.table.item(row, 0)
        if not item:
            self.btn_show.setEnabled(False)
            return
        case_name = item.text()
        is_real_case = hasattr(self.model, 'load_cases') and case_name in self.model.load_cases
        self.btn_show.setEnabled(is_real_case)

    def on_show_case_clicked(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        case_name = item.text()
        if not hasattr(self.model, 'load_cases') or case_name not in self.model.load_cases:
            return

        case_obj = self.model.load_cases[case_name]
        dlg = LoadCaseDetailDialog(self.model, case_obj, self, is_new=False)
        if dlg.exec():
            new_case = dlg.get_data()
            if new_case.name != case_name:
                del self.model.load_cases[case_name]
            self.model.load_cases[new_case.name] = new_case
            self.populate_table()

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

    def _store_prefs(self, case_name):
        """Keep the selected case and log checkbox on the model so they are saved in the .mf file."""
        show_log = self.chk_messages.isChecked()
        changed = (getattr(self.model, 'last_run_case', None) != case_name or
                   getattr(self.model, 'show_analysis_log', True) != show_log)
        AnalysisDialog._last_run_case = case_name
        self.model.last_run_case = case_name
        self.model.show_analysis_log = show_log
        if changed:
            stack = getattr(self.parent(), 'undo_stack', None)
            if stack is not None:
                stack.push(CmdRunPrefsChanged())

    def reject(self):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 3).text() == "Run":
                self._store_prefs(self.table.item(r, 0).text())
                break
        super().reject()

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
            
        self._store_prefs(target_case)
        self.signal_run_analysis.emit(target_case, self.chk_messages.isChecked())
        self.accept()
