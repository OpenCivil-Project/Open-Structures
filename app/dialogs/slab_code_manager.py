"""
app/dialogs/slab_code_manager.py
=================================
Separate from ShellSectionDialog on purpose:

  TS500SlabDialog        – editor for a single Code-Based slab definition
                            (Name / Thickness / Material only — we are NOT
                            doing a Prota-style yield-line design here, this
                            is just "equivalent slab -> transfers load to
                            beams as thickness+material", so the data model
                            stays deliberately thin).
  SlabCodeManagerDialog   – list + Add/Modify/Delete manager, same shape as
                            ResponseSpectrumManagerDialog.

Storage: model.slab_codes[name] = {'name':.., 'thickness':.., 'material':..}
Solver-facing shape is unchanged from what ShellSectionDialog used to stamp
onto sec.modeling_type / eMembrane — this is a relocation, not a redesign.

Usage (from main.py or wherever Area Sections is opened from):
    from app.dialogs.slab_code_manager import SlabCodeManagerDialog
    dlg = SlabCodeManagerDialog(self.model, parent=self)
    dlg.exec()
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QPushButton, QLabel, QGroupBox, QMessageBox,
                             QComboBox, QAbstractItemView, QFormLayout,
                             QLineEdit, QSizePolicy)
from PyQt6.QtCore import Qt

try:
    from app.ui.theme import apply_dialog_style
except ImportError:
    def apply_dialog_style(d): pass

def _mat_row(model):
    """Same helper as area_section_dialog._mat_row — Material Name row."""
    layout = QHBoxLayout()
    layout.setSpacing(4)
    btn = QPushButton("+")
    btn.setFixedSize(22, 22)
    btn.setEnabled(False)
    btn.setToolTip("Define new material")
    combo = QComboBox()
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    for name in model.materials:
        combo.addItem(name)
    layout.addWidget(btn)
    layout.addWidget(combo)
    return layout, btn, combo

class TS500SlabDialog(QDialog):
    """
    Editor for a single TS500 (Code Based) slab definition.
    Deliberately minimal: Name, Thickness, Material. We are not doing
    Prota-style rebar/moment-capacity design — this just defines the
    equivalent slab used to transfer loads onto beams.
    """

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("TS500 Slab Definition")
        self.setMinimumWidth(360)
        apply_dialog_style(self)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)

        grp = QGroupBox("TS500 Slab Data")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.input_name = QLineEdit()
        form.addRow("Name", self.input_name)

        self.in_thickness = QLineEdit("0.1")
        form.addRow("Slab Thickness (h)", self.in_thickness)

        mat_layout, self._btnPlusMat, self.cboMat = _mat_row(self.model)
        form.addRow("Material", mat_layout)

        root.addWidget(grp)

        br = QHBoxLayout()
        br.addStretch()
        self.btnOK = QPushButton("OK")
        self.btnOK.setObjectName("primary")
        self.btnCxl = QPushButton("Cancel")
        self.btnOK.clicked.connect(self._on_ok)
        self.btnCxl.clicked.connect(self.reject)
        br.addWidget(self.btnOK)
        br.addWidget(self.btnCxl)
        root.addLayout(br)

    def get_data(self):
        return {
            'name': self.input_name.text().strip(),
            'thickness': float(self.in_thickness.text()),
            'material': self.cboMat.currentText(),
        }

    def _on_ok(self):
        name = self.input_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Input Error", "Name cannot be empty.")
            return
        try:
            float(self.in_thickness.text())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Thickness must be numeric.")
            return
        self.accept()

class SlabCodeManagerDialog(QDialog):
    """
    Matches the ResponseSpectrumManagerDialog pattern:
    list of defined slab codes, pick a type to add (TS500 only for now,
    room to extend later), Add / Modify / Delete.
    """

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

        if not hasattr(self.model, 'slab_codes'):
            self.model.slab_codes = {}

        self.setWindowTitle("Define Slab Codes")
        self.resize(600, 400)

        layout = QHBoxLayout(self)

        grp_list = QGroupBox("Slab Codes")
        v_list = QVBoxLayout(grp_list)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v_list.addWidget(self.list_widget)

        layout.addWidget(grp_list, stretch=1)

        right_layout = QVBoxLayout()

        grp_type = QGroupBox("Choose Code Type to Add")
        v_type = QVBoxLayout(grp_type)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["TS500"])
        v_type.addWidget(self.combo_type)
        right_layout.addWidget(grp_type)

        grp_actions = QGroupBox("Click to:")
        v_actions = QVBoxLayout(grp_actions)

        self.btn_add = QPushButton("Add New Slab Code...")
        self.btn_add.clicked.connect(self.add_slab_code)

        self.btn_mod = QPushButton("Modify/Show Slab Code...")
        self.btn_mod.clicked.connect(self.modify_slab_code)

        self.btn_del = QPushButton("Delete Slab Code")
        self.btn_del.clicked.connect(self.delete_slab_code)

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
        for name in self.model.slab_codes.keys():
            self.list_widget.addItem(name)

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def add_slab_code(self):
        """Opens the Editor with default values."""
        ftype = self.combo_type.currentText()
        if ftype != "TS500":
            QMessageBox.information(self, "Info", "Only TS500 is supported in this version.")
            return

        idx = 1
        while f"SLAB{idx}" in self.model.slab_codes:
            idx += 1
        default_name = f"SLAB{idx}"

        dlg = TS500SlabDialog(self.model, parent=self)
        dlg.input_name.setText(default_name)

        if dlg.exec():
            data = dlg.get_data()
            new_name = data['name']

            if new_name in self.model.slab_codes:
                QMessageBox.warning(self, "Error", f"Slab code '{new_name}' already exists.")
                return

            self.model.slab_codes[new_name] = data
            self.refresh_list()

    def modify_slab_code(self):
        """Opens the Editor with existing values."""
        item = self.list_widget.currentItem()
        if not item:
            return

        code_name = item.text()
        data = self.model.slab_codes[code_name]

        dlg = TS500SlabDialog(self.model, parent=self)
        self.populate_dialog(dlg, data)

        if dlg.exec():
            new_data = dlg.get_data()
            new_name = new_data['name']

            if new_name != code_name:
                del self.model.slab_codes[code_name]

            self.model.slab_codes[new_name] = new_data
            self.refresh_list()

    def delete_slab_code(self):
        item = self.list_widget.currentItem()
        if not item:
            return

        code_name = item.text()
        del self.model.slab_codes[code_name]
        self.refresh_list()

    def populate_dialog(self, dlg, data):
        """Helper to fill the editor with saved data."""
        dlg.input_name.setText(data.get('name', ''))
        dlg.in_thickness.setText(str(data.get('thickness', 0.1)))
        mat_name = data.get('material', '')
        i = dlg.cboMat.findText(mat_name)
        if i >= 0:
            dlg.cboMat.setCurrentIndex(i)
