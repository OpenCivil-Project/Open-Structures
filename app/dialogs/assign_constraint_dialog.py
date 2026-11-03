from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QListWidget, QPushButton,
                             QMessageBox, QGroupBox, QComboBox, QLineEdit,
                             QLabel, QRadioButton, QCheckBox, QButtonGroup)
from PyQt6.QtCore import Qt
from app.commands import CmdAssignDiaphragm
from app.ui.theme import apply_dialog_style

class DiaphragmConstraintDialog(QDialog):
    """
    A dialog for defining diaphragm constraints.

    X, Y, and Z axis are all wired up to the solver (exact rigid-body DOF
    elimination in assembler.py, axis-aware). Auto axis, Semi-rigid, and
    per-level assignment are shown for layout/familiarity but disabled -
    no math/logic exists for those yet.
    """

    def __init__(self, parent, existing_names, default_name=""):
        super().__init__(parent)
        apply_dialog_style(self)

        self.existing_names = existing_names
        self.result_name = None
        self.result_axis = "Z"

        self.setWindowTitle("Diaphragm Constraint")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QGridLayout()
        form.addWidget(QLabel("Constraint Name"), 0, 0)
        self.edit_name = QLineEdit(default_name)
        form.addWidget(self.edit_name, 0, 1)

        form.addWidget(QLabel("Coordinate System"), 1, 0)
        self.combo_coord = QComboBox()
        self.combo_coord.addItem("GLOBAL")
        self.combo_coord.setToolTip(
            "Only the Global coordinate system is currently supported."
        )
        form.addWidget(self.combo_coord, 1, 1)
        layout.addLayout(form)

        gp_axis = QGroupBox("Constraint Axis")
        axis_layout = QGridLayout()

        self.radio_x = QRadioButton("X Axis")
        self.radio_y = QRadioButton("Y Axis")
        self.radio_z = QRadioButton("Z Axis")
        self.radio_auto = QRadioButton("Auto")

        self.axis_group = QButtonGroup(self)
        for rb in (self.radio_x, self.radio_y, self.radio_z, self.radio_auto):
            self.axis_group.addButton(rb)

        self.radio_z.setChecked(True)

        self.radio_auto.setEnabled(False)
        self.radio_auto.setToolTip("Not implemented yet.")

        axis_layout.addWidget(self.radio_x, 0, 0)
        axis_layout.addWidget(self.radio_auto, 0, 1)
        axis_layout.addWidget(self.radio_y, 1, 0)
        axis_layout.addWidget(self.radio_z, 2, 0)

        gp_axis.setLayout(axis_layout)
        layout.addWidget(gp_axis)

        gp_semi = QGroupBox("Semi-rigid Diaphragm Option")
        semi_layout = QVBoxLayout()

        self.chk_semi_rigid = QCheckBox("Semi-rigid")
        self.chk_semi_rigid.setEnabled(False)
        self.chk_semi_rigid.setToolTip("Not implemented yet.")
        semi_layout.addWidget(self.chk_semi_rigid)

        note = QLabel(
            "Note: Defined for application of seismic and wind loads. "
            "Option is only active when the Coordinate System is Global "
            "and the Constraint Axis is Z."
        )
        note.setWordWrap(True)
        note.setObjectName("hint")
        semi_layout.addWidget(note)

        gp_semi.setLayout(semi_layout)
        layout.addWidget(gp_semi)

        self.chk_per_level = QCheckBox(
            "Assign a different diaphragm constraint to each different\n"
            "selected Z level"
        )
        self.chk_per_level.setEnabled(False)
        self.chk_per_level.setToolTip("Not implemented yet.")
        layout.addWidget(self.chk_per_level)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondary")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_ok)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

    def _on_ok(self):
        name = self.edit_name.text().strip().upper()
        if not name:
            QMessageBox.warning(self, "Error", "Please enter a Constraint Name.")
            return
        if name in self.existing_names:
            QMessageBox.warning(self, "Error", "Name already exists.")
            return

        if self.radio_x.isChecked():
            axis = "X"
        elif self.radio_y.isChecked():
            axis = "Y"
        else:
            axis = "Z"

        self.result_name = name
        self.result_axis = axis
        self.accept()

class AssignConstraintDialog(QDialog):
    def __init__(self, main_window):

        super().__init__(main_window)
        apply_dialog_style(self)

        self.main_window = main_window
        self.model = main_window.model

        self.setWindowTitle("Joint Constraints")
        self.resize(420, 480)

        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        define_row = QHBoxLayout()

        gp_list = QGroupBox("Constraints")
        gp_list_layout = QVBoxLayout()

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        gp_list_layout.addWidget(self.list_widget)

        self.btn_del = QPushButton("Delete")
        self.btn_del.setObjectName("danger")
        self.btn_del.clicked.connect(self.delete_constraint)
        gp_list_layout.addWidget(self.btn_del)

        gp_list.setLayout(gp_list_layout)
        define_row.addWidget(gp_list, stretch=1)

        gp_add = QGroupBox("Add New Constraint")
        gp_add_layout = QVBoxLayout()
        gp_add_layout.addStretch()

        gp_add_layout.addWidget(QLabel("Type: Diaphragm"))

        self.btn_add = QPushButton("Add New Constraint...")
        self.btn_add.setObjectName("primary")
        self.btn_add.clicked.connect(self.add_constraint)
        gp_add_layout.addWidget(self.btn_add)

        gp_add_layout.addStretch()
        gp_add.setLayout(gp_add_layout)
        define_row.addWidget(gp_add, stretch=1)

        layout.addLayout(define_row)

        gp_assign = QGroupBox("Assign to Selected Joints")
        assign_layout = QHBoxLayout()

        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setObjectName("primary")
        self.btn_apply.clicked.connect(self.apply_constraint)

        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setObjectName("danger")
        self.btn_disconnect.setToolTip("Remove Constraint from Selection")
        self.btn_disconnect.clicked.connect(self.remove_constraint)

        assign_layout.addWidget(self.btn_apply)
        assign_layout.addWidget(self.btn_disconnect)
        gp_assign.setLayout(assign_layout)
        layout.addWidget(gp_assign)

        close_row = QHBoxLayout()
        close_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("secondary")
        self.btn_close.clicked.connect(self.close)
        close_row.addWidget(self.btn_close)
        layout.addLayout(close_row)

        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        for name in sorted(self.model.constraints.keys()):
            self.list_widget.addItem(name)

    def add_constraint(self):
        """Defines a new Diaphragm constraint (X, Y, or Z axis)."""
        dlg = DiaphragmConstraintDialog(
            self,
            existing_names=self.model.constraints,
            default_name=self._next_default_name(),
        )
        if dlg.exec():
            self.model.add_constraint(dlg.result_name, axis=dlg.result_axis)
            self.refresh_list()

    def _next_default_name(self):
        """Suggests the next unused 'D<n>' name, e.g. D1, D2, ..."""
        n = 1
        while f"D{n}" in self.model.constraints:
            n += 1
        return f"D{n}"

    def delete_constraint(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        name = item.text()

        assigned_nodes = [n.id for n in self.model.nodes.values() if getattr(n, 'diaphragm_name', None) == name]
        
        if assigned_nodes:
            reply = QMessageBox.question(
                self, "Constraint In Use",
                f"Constraint '{name}' is currently assigned to {len(assigned_nodes)} joint(s).\n\n"
                "Do you want to disconnect it from those joints and delete the definition?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            for nid in assigned_nodes:
                self.model.nodes[nid].diaphragm_name = None

        del self.model.constraints[name]
        self.refresh_list()
        self.main_window.status.showMessage(f"Constraint '{name}' deleted.")
        self.main_window.refresh_canvas()

    def apply_constraint(self):
        """Applies the selected constraint to the currently selected nodes."""
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.warning(self, "Selection Error", "Please select a Constraint from the list above.")
            return

        dia_name = item.text()
        selected_nodes = self.main_window.selected_node_ids

        if not selected_nodes:
            QMessageBox.warning(self, "Selection Error", "Please select Joints in the model to assign.")
            return

        cmd = CmdAssignDiaphragm(
            self.model,
            self.main_window,
            list(selected_nodes),
            dia_name
        )
        self.main_window.add_command(cmd)

        self.main_window.status.showMessage(f"Assigned {dia_name} to {len(selected_nodes)} Joints.")

    def remove_constraint(self):
        """Removes any constraint assignment from selected nodes."""
        selected_nodes = self.main_window.selected_node_ids
        if not selected_nodes:
            QMessageBox.warning(self, "Selection Error", "Please select Joints in the model to disconnect constraints from.")
            return

        cmd = CmdAssignDiaphragm(
            self.model,
            self.main_window,
            list(selected_nodes),
            None
        )
        self.main_window.add_command(cmd)

        self.main_window.status.showMessage(f"Removed Constraints from {len(selected_nodes)} Joints.")
        self.main_window.refresh_canvas()
