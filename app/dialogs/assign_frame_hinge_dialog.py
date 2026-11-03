from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QComboBox, QGroupBox,
                             QRadioButton, QGridLayout, QMessageBox,
                             QButtonGroup, QTableWidget, QTableWidgetItem,
                             QHeaderView)
from PyQt6.QtCore import Qt, QTimer
from app.commands import CmdAssignFrameHinge
from core.opensees_port.os_capabilities import is_opensees

class AssignFrameHingeDialog(QDialog):
    """
    Minimal 'Assign Frame Hinges' dialog: pick a (user-defined) hinge
    property and a relative distance, apply to the selected frame(s).
    No Auto Hinge support - hinge properties (FH1, FH2, ...) are
    defined elsewhere (model.hinge_properties) and just picked here.
    Data-only: this does not touch the solver or the OpenSees converter.
    """
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.model = main_window.model

        self.setWindowTitle("Assign Frame Hinges")
        self.resize(420, 430)
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        self.selected_ids = self.main_window.selected_ids

        layout = QVBoxLayout(self)

        self.lbl_engine_note = QLabel(
            "OpenSees does not use frame hinges - its fibers come from each section's "
            "reinforcement. Switch the Analysis Engine to Native to assign hinges. "
            "Existing assignments are kept."
        )
        self.lbl_engine_note.setWordWrap(True)
        layout.addWidget(self.lbl_engine_note)

        grp_def = QGroupBox("Hinge Assignment")
        grid = QGridLayout()

        grid.addWidget(QLabel("Hinge Property:"), 0, 0)
        self.combo_hinge = QComboBox()
        self.combo_hinge.addItems(list(self.model.hinge_properties.keys()))
        grid.addWidget(self.combo_hinge, 0, 1)

        grid.addWidget(QLabel("Relative Distance (0 - 1):"), 1, 0)
        self.in_dist = QLineEdit("0.5")
        grid.addWidget(self.in_dist, 1, 1)

        grp_def.setLayout(grid)
        layout.addWidget(grp_def)

        if not self.model.hinge_properties:
            self.lbl_none = QLabel(
                "<i>No hinge properties defined yet - define one first, "
                "then come back here to assign it.</i>"
            )
            self.lbl_none.setWordWrap(True)
            layout.addWidget(self.lbl_none)
            self.combo_hinge.setEnabled(False)

        opt_layout = QHBoxLayout()
        self.rb_add = QRadioButton("Add")
        self.rb_replace = QRadioButton("Replace")
        self.rb_delete = QRadioButton("Delete")
        self.rb_replace.setChecked(True)
        self.grp_mode = QButtonGroup(self)
        for rb in (self.rb_add, self.rb_replace, self.rb_delete):
            self.grp_mode.addButton(rb)
            opt_layout.addWidget(rb)
        layout.addLayout(opt_layout)

        layout.addWidget(QLabel("Hinges currently on selected frame(s):"))
        self.lbl_hinges = QLabel("")
        self.lbl_hinges.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.lbl_hinges)
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Frame", "Hinge Property", "Rel. Distance"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.clicked.connect(self.apply_hinge)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self._last_fingerprint = None
        self.refresh_table()

        self._sync_engine_state()

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(300)
        self.poll_timer.timeout.connect(self._check_for_changes)
        self.poll_timer.start()

    def _sync_engine_state(self):
        """Grey out the assignment controls while the Analysis Engine is OpenSees.
        Re-checked on every poll tick because this dialog is non-modal and the
        engine can be switched while it is open."""
        os_on = is_opensees(self.model)
        self.lbl_engine_note.setVisible(os_on)
        for w in (self.in_dist, self.rb_add, self.rb_replace, self.rb_delete, self.btn_apply):
            w.setEnabled(not os_on)
        self.combo_hinge.setEnabled(not os_on and bool(self.model.hinge_properties))

    def closeEvent(self, event):
        self.poll_timer.stop()
        super().closeEvent(event)

    def _check_for_changes(self):
        self._sync_engine_state()
        sel = tuple(sorted(self.main_window.selected_ids))
        hinge_ids = tuple(sorted(self.model.frame_hinges.keys()))
        fingerprint = (sel, hinge_ids)
        if fingerprint != self._last_fingerprint:
            self.refresh_table()

    def refresh_table(self):
        self.table.setRowCount(0)
        selected = list(self.main_window.selected_ids)

        self._last_fingerprint = (
            tuple(sorted(selected)),
            tuple(sorted(self.model.frame_hinges.keys())),
        )

        if not selected:
            self.lbl_hinges.setText("(no frames selected)")
            return

        rows = []
        for h in self.model.frame_hinges.values():
            if h.element_id in selected:
                el = self.model.elements.get(h.element_id)
                frame_label = getattr(el, 'label', None) or f"#{h.element_id}"
                rows.append((str(frame_label), h.hinge_name, h.rel_dist))

        self.lbl_hinges.setText(
            f"{len(selected)} frame(s) selected, {len(rows)} hinge assignment(s)"
        )

        rows.sort(key=lambda r: (r[0], r[2]))

        if not rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem("No hinges on selected frame(s)"))
            self.table.setSpan(row, 0, 1, 3)
            return

        for frame_label, hinge_name, rel_dist in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(frame_label))
            self.table.setItem(row, 1, QTableWidgetItem(hinge_name))
            self.table.setItem(row, 2, QTableWidgetItem(f"{rel_dist:.3f}"))

    def apply_hinge(self):
        if is_opensees(self.model):
            return
        if not self.model.hinge_properties:
            QMessageBox.warning(self, "No Hinge Properties",
                                 "Define a hinge property first.")
            return

        current_selection = self.main_window.selected_ids
        if not current_selection:
            QMessageBox.warning(self, "Selection", "No frames selected.")
            return

        try:
            rel_dist = float(self.in_dist.text())
            if not (0.0 <= rel_dist <= 1.0):
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Input Error",
                                 "Relative distance must be a number between 0 and 1.")
            return

        hinge_name = self.combo_hinge.currentText()

        mode = "replace"
        if self.rb_add.isChecked(): mode = "add"
        elif self.rb_delete.isChecked(): mode = "delete"

        cmd = CmdAssignFrameHinge(
            self.model, self.main_window, list(current_selection),
            hinge_name, rel_dist, mode
        )
        self.main_window.add_command(cmd)

        self.main_window.status.showMessage(
            f"Assigned Hinges to {len(current_selection)} frame(s)."
        )

        self.refresh_table()
