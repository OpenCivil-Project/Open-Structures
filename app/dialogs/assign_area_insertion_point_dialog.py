from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QGroupBox, QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QUndoCommand
from core.units import unit_registry

class CmdAssignAreaInsertion(QUndoCommand):
    """Sets area.insertion_offset (internal length units, along shell local 3)."""

    def __init__(self, model, main_window, area_ids, offset):
        super().__init__("Assign Area Insertion Point")
        self.model = model
        self.main_window = main_window
        self.area_ids = list(area_ids)
        self.new_offset = float(offset)
        self.old_offsets = {
            aid: getattr(model.area_elements[aid], 'insertion_offset', 0.0)
            for aid in self.area_ids if aid in model.area_elements
        }

    def _apply(self, values):
        for aid, val in values.items():
            ae = self.model.area_elements.get(aid)
            if ae is not None:
                ae.insertion_offset = val
        mw = self.main_window
        mw.canvas.invalidate_area_vbo()
        if hasattr(mw, 'canvas2'):
            mw.canvas2.invalidate_area_vbo()
        mw.refresh_canvas()

    def redo(self):
        self._apply({aid: self.new_offset for aid in self.old_offsets})

    def undo(self):
        self._apply(self.old_offsets)

class AssignAreaInsertionPointDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.model = main_window.model

        self.setWindowTitle("Assign Area Insertion Point")
        self.resize(360, 200)
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)

        grp = QGroupBox("Shell Offset")
        g_layout = QVBoxLayout()

        row = QHBoxLayout()
        row.addWidget(QLabel("Offset along local 3:"))
        self.le_offset = QLineEdit("0.0")
        row.addWidget(self.le_offset)
        u_lbl = unit_registry.current_unit_label.split(",")[1].strip()
        row.addWidget(QLabel(u_lbl))
        g_layout.addLayout(row)

        hint = QLabel("Positive moves the shell mid-surface toward +local 3\n"
                      "relative to the drawn joints. 0 = no offset.")
        hint.setStyleSheet("color: #6c757d;")
        g_layout.addWidget(hint)

        grp.setLayout(g_layout)
        layout.addWidget(grp)

        btns = QHBoxLayout()
        self.btn_get = QPushButton("Get From Selected")
        self.btn_get.clicked.connect(self.get_from_selected)
        self.btn_reset = QPushButton("Reset Form")
        self.btn_reset.clicked.connect(lambda: self.le_offset.setText("0.0"))
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.clicked.connect(self.apply_changes)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btns.addWidget(self.btn_get)
        btns.addWidget(self.btn_reset)
        btns.addStretch()
        btns.addWidget(self.btn_apply)
        btns.addWidget(self.btn_close)
        layout.addLayout(btns)

    def get_from_selected(self):
        ids = getattr(self.main_window, 'selected_area_ids', [])
        if not ids:
            return
        ae = self.model.area_elements.get(ids[0])
        if ae is None:
            return
        val = getattr(ae, 'insertion_offset', 0.0) * unit_registry.length_scale
        self.le_offset.setText(f"{val:g}")

    def apply_changes(self):
        ids = list(getattr(self.main_window, 'selected_area_ids', []))
        if not ids:
            QMessageBox.warning(self, "Selection Error", "Please select at least one Area Element.")
            return
        try:
            value = float(self.le_offset.text()) / unit_registry.length_scale
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter a valid numeric value.")
            return

        cmd = CmdAssignAreaInsertion(self.model, self.main_window, ids, value)
        self.main_window.add_command(cmd)
        self.main_window.status.showMessage(f"Updated Insertion Point for {len(ids)} Area(s).")
