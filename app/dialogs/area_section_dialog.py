"""
app/dialogs/area_section_dialog.py
===================================
Four dialogs matching SAP2000 exactly:

  ShellSectionDialog          – Shell Section Data
  PlaneSectionDialog          – Plane Section Data
  AsolidSectionDialog         – Axisymmetric Solid (Asolid) Section Data
  AreaSectionsManagerDialog   – Area Sections manager (list + CRUD)

Usage (from main.py or wherever):
    from app.dialogs.area_section_dialog import AreaSectionsManagerDialog
    dlg = AreaSectionsManagerDialog(self.model, parent=self)
    dlg.exec()
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QComboBox, QRadioButton, QCheckBox, QPushButton,
    QButtonGroup, QFrame, QListWidget, QSizePolicy, QAbstractItemView,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from core.integrity_checks import check_area_section_in_use

try:
    from app.ui.theme import apply_dialog_style
except ImportError:
    def apply_dialog_style(d): pass                                                  

from core.properties import ShellSection, PlaneSection, AsolidSection

class _ColorSwatch(QPushButton):
    """
    Tiny square button that shows the section display colour.
    Click → QColorDialog.
    """
    def __init__(self, color="#FF00FF", parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to change display colour")
        self._color = QColor(color)
        self._refresh()

    def color(self) -> QColor: return self._color
    def hex(self)   -> str:    return self._color.name()

    def set_color(self, c):
        self._color = QColor(c) if not isinstance(c, QColor) else c
        self._refresh()

    def _refresh(self):
        h = self._color.name()
        self.setStyleSheet(
            f"QPushButton {{ background-color:{h}; border:1px solid #888888;"
            f"  border-radius:2px; }}"
            f"QPushButton:hover {{ border:1px solid #333333; }}"
        )

    def mousePressEvent(self, ev):
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self._color, self, "Select Display Colour")
        if c.isValid():
            self._color = c
            self._refresh()

def _hsep():
    """Thin horizontal separator line."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f

def _stub(text):
    """Disabled placeholder button (feature not yet implemented)."""
    b = QPushButton(text)
    b.setEnabled(False)
    return b

def _mat_row(model):
    """
    Returns (layout, plus_button, combo) for the Material Name row.
    The '+' button is a stub for now; combo is populated from model.materials.
    """
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

class ShellSectionDialog(QDialog):
    """
    Matches SAP2000 → Define → Section Properties → Area Sections
    → Add/Modify → Shell.

    Covers all six shell types:
        Shell-Thin, Shell-Thick, Plate-Thin, Plate-Thick,
        Membrane, Shell-Layered/Nonlinear
    """
    _TYPES = [
        "Shell - Thin",
        "Shell - Thick",
        "Plate - Thin",
        "Plate Thick",
        "Membrane",
        "Shell - Layered/Nonlinear",
    ]

    def __init__(self, model, section: ShellSection = None, parent=None):
        super().__init__(parent)
        self.model   = model
        self._source = section                                              
        self.setWindowTitle("Shell Section Data")
        self.setMinimumWidth(540)
        apply_dialog_style(self)
        self._build_ui()
        if section:
            self._populate(section)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(6)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Section Name"))
        self.eName = QLineEdit()
        self.eName.setMinimumWidth(200)
        r1.addWidget(self.eName)
        r1.addStretch()
        r1.addWidget(QLabel("Display Color"))
        self.swatch = _ColorSwatch("#FF00FF")
        r1.addWidget(self.swatch)
        root.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Section Notes"))
        r2.addWidget(_stub("Modify/Show..."))
        r2.addStretch()
        root.addLayout(r2)

        root.addWidget(_hsep())

        body = QHBoxLayout()
        body.setSpacing(8)

        grp_type = QGroupBox("Type")
        tvl = QVBoxLayout(grp_type)
        tvl.setSpacing(4)
        self._tbg = QButtonGroup(self)
        for t in self._TYPES:
            rb = QRadioButton(t)
            tvl.addWidget(rb)
            self._tbg.addButton(rb)
        self._tbg.buttons()[0].setChecked(True)
        tvl.addStretch()
        self.btnLayer = _stub("Modify/Show Layer Definition...")
        tvl.addWidget(self.btnLayer)

        left = QVBoxLayout()
        left.addWidget(grp_type)
        left.addStretch()

        right = QVBoxLayout()
        right.setSpacing(6)

        grp_th = QGroupBox("Thickness")
        tf = QFormLayout(grp_th)
        tf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.eMembrane = QLineEdit("0.1")
        self.eBending  = QLineEdit("0.1")
        tf.addRow("Membrane", self.eMembrane)
        tf.addRow("Bending",  self.eBending)
        right.addWidget(grp_th)

        grp_mat = QGroupBox("Material")
        mf = QFormLayout(grp_mat)
        mf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        mat_layout, self._btnPlusMat, self.cboMat = _mat_row(self.model)
        mf.addRow("Material Name", mat_layout)
        self.eMatAngle = QLineEdit("0.")
        mf.addRow("Material Angle", self.eMatAngle)
        right.addWidget(grp_mat)

        grp_tdp = QGroupBox("Time Dependent Properties")
        tdpv = QVBoxLayout(grp_tdp)
        tdpv.addWidget(_stub("Set Time Dependent Properties..."))
        right.addWidget(grp_tdp)

        sm_row = QHBoxLayout()
        sm_row.setSpacing(6)

        grp_sm = QGroupBox("Stiffness Modifiers")
        smv = QVBoxLayout(grp_sm)
        smv.addWidget(_stub("Set Modifiers..."))
        sm_row.addWidget(grp_sm)

        grp_tp = QGroupBox("Temp Dependent Properties")
        tpv = QVBoxLayout(grp_tp)
        tpv.addWidget(_stub("Thermal Properties..."))
        sm_row.addWidget(grp_tp)

        right.addLayout(sm_row)

        body.addLayout(left, 2)
        body.addLayout(right, 3)
        root.addLayout(body)

        grp_d = QGroupBox("Concrete Shell Section Design Parameters")
        dv = QVBoxLayout(grp_d)
        dv.addWidget(_stub("Modify/Show Shell Design Parameters..."))
        root.addWidget(grp_d)

        br = QHBoxLayout()
        br.addStretch()
        self.btnOK  = QPushButton("OK")
        self.btnOK.setObjectName("primary")
        self.btnCxl = QPushButton("Cancel")
        self.btnOK.clicked.connect(self._on_ok)
        self.btnCxl.clicked.connect(self.reject)
        br.addWidget(self.btnOK)
        br.addWidget(self.btnCxl)
        root.addLayout(br)

        for rb in self._tbg.buttons():
            rb.toggled.connect(self._on_type_toggled)

    def _on_type_toggled(self, checked):
        if checked:
            self.btnLayer.setEnabled(
                self._selected_type() == "Shell - Layered/Nonlinear"
            )

    def _selected_type(self) -> str:
        for b in self._tbg.buttons():
            if b.isChecked():
                return b.text()
        return "Shell - Thin"

    def _populate(self, s: ShellSection):
        self.eName.setText(s.name)
        self.swatch.set_color(s.display_color)
        for b in self._tbg.buttons():
            if b.text() == s.shell_type:
                b.setChecked(True)
                break
        self.eMembrane.setText(str(s.membrane_thickness))
        self.eBending.setText(str(s.bending_thickness))
        if s.material:
            i = self.cboMat.findText(s.material.name)
            if i >= 0:
                self.cboMat.setCurrentIndex(i)
        self.eMatAngle.setText(str(s.material_angle))

    def _on_ok(self):
        name = self.eName.text().strip()
        if not name:
            QMessageBox.warning(self, "Input Error", "Section Name cannot be empty.")
            return
        if self._source is None and name in self.model.area_sections:
            QMessageBox.warning(self, "Duplicate Name",
                                f"A section named '{name}' already exists.")
            return
        try:
            mem = float(self.eMembrane.text())
            ben = float(self.eBending.text())
            ang = float(self.eMatAngle.text())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid numeric value.")
            return

        mat = self.model.materials.get(self.cboMat.currentText())
        sec = ShellSection(name, mat, self._selected_type(),
                           mem, ben, ang, self.swatch.hex())

        if self._source and self._source.name != name:
            self.model.area_sections.pop(self._source.name, None)

        self.model.area_sections[name] = sec
        self.accept()

class TributarySlabSectionDialog(QDialog):
    """
    Tributary Area slab definition — sibling of Shell/Plane/Asolid.
    Deliberately minimal: Name, Thickness, Material only.
    Produces a ShellSection stamped with .modeling_type = "Tributary Area".
    """

    _DEFAULT_SHELL_TYPE = "Membrane"

    def __init__(self, model, section: ShellSection = None, parent=None):
        super().__init__(parent)
        self.model   = model
        self._source = section
        self.setWindowTitle("Slab Data - Tributary Area")
        self.setMinimumWidth(360)
        apply_dialog_style(self)
        self._build_ui()
        if section:
            self._populate(section)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(6)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Section Name"))
        self.eName = QLineEdit()
        self.eName.setMinimumWidth(200)
        r1.addWidget(self.eName)
        r1.addStretch()
        r1.addWidget(QLabel("Display Color"))
        self.swatch = _ColorSwatch("#FF00FF")
        r1.addWidget(self.swatch)
        root.addLayout(r1)

        root.addWidget(_hsep())

        grp = QGroupBox("Tributary Slab Data")
        tf = QFormLayout(grp)
        tf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.eThickness = QLineEdit("0.1")
        tf.addRow("Slab Thickness (h)", self.eThickness)

        mat_layout, self._btnPlusMat, self.cboMat = _mat_row(self.model)
        tf.addRow("Material Name", mat_layout)
        self.eMatAngle = QLineEdit("0.")
        tf.addRow("Material Angle", self.eMatAngle)

        root.addWidget(grp)

        note = QLabel("Tributary load transfer only — not a FEM shell.\n"
                       "Used to convert this slab's load into beam loads.")
        note.setStyleSheet("color: #666; font-style: italic;")
        root.addWidget(note)

        br = QHBoxLayout()
        br.addStretch()
        self.btnOK  = QPushButton("OK")
        self.btnOK.setObjectName("primary")
        self.btnCxl = QPushButton("Cancel")
        self.btnOK.clicked.connect(self._on_ok)
        self.btnCxl.clicked.connect(self.reject)
        br.addWidget(self.btnOK)
        br.addWidget(self.btnCxl)
        root.addLayout(br)

    def _populate(self, s: ShellSection):
        self.eName.setText(s.name)
        self.swatch.set_color(s.display_color)
        self.eThickness.setText(str(s.membrane_thickness))
        if s.material:
            i = self.cboMat.findText(s.material.name)
            if i >= 0:
                self.cboMat.setCurrentIndex(i)
        self.eMatAngle.setText(str(s.material_angle))

    def _on_ok(self):
        name = self.eName.text().strip()
        if not name:
            QMessageBox.warning(self, "Input Error", "Section Name cannot be empty.")
            return
        if self._source is None and name in self.model.area_sections:
            QMessageBox.warning(self, "Duplicate Name",
                                f"A section named '{name}' already exists.")
            return
        try:
            th  = float(self.eThickness.text())
            ang = float(self.eMatAngle.text())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid numeric value.")
            return

        mat = self.model.materials.get(self.cboMat.currentText())
        sec = ShellSection(name, mat, self._DEFAULT_SHELL_TYPE,
                           th, th, ang, self.swatch.hex())
        
        sec.modeling_type = "Tributary Area"

        if self._source and self._source.name != name:
            self.model.area_sections.pop(self._source.name, None)

        self.model.area_sections[name] = sec
        self.accept()

class PlaneSectionDialog(QDialog):
    """
    Matches SAP2000's Plane Section Data dialog.
    Covers: Plane-Stress, Plane-Strain, with optional Incompatible Modes.
    """

    def __init__(self, model, section: PlaneSection = None, parent=None):
        super().__init__(parent)
        self.model   = model
        self._source = section
        self.setWindowTitle("Plane Section Data")
        self.setMinimumWidth(370)
        apply_dialog_style(self)
        self._build_ui()
        if section:
            self._populate(section)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(6)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Section Name"))
        self.eName = QLineEdit()
        self.eName.setMinimumWidth(160)
        r1.addWidget(self.eName)
        root.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Section Notes"))
        r2.addWidget(_stub("Modify/Show..."))
        r2.addStretch()
        r2.addWidget(QLabel("Display Color"))
        self.swatch = _ColorSwatch("#FF00FF")
        r2.addWidget(self.swatch)
        root.addLayout(r2)

        root.addWidget(_hsep())

        grp_type = QGroupBox("Type")
        tvl = QVBoxLayout(grp_type)
        self._tbg = QButtonGroup(self)
        self.rbStress = QRadioButton("Plane-Stress")
        self.rbStrain = QRadioButton("Plane-Strain")
        self.rbStress.setChecked(True)
        self._tbg.addButton(self.rbStress)
        self._tbg.addButton(self.rbStrain)
        tvl.addWidget(self.rbStress)
        tvl.addWidget(self.rbStrain)
        self.chkIncompat = QCheckBox("Incompatible Modes")
        self.chkIncompat.setChecked(True)
        tvl.addWidget(self.chkIncompat)
        root.addWidget(grp_type)

        grp_mat = QGroupBox("Material")
        mf = QFormLayout(grp_mat)
        mf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        mat_layout, self._btnPlusMat, self.cboMat = _mat_row(self.model)
        mf.addRow("Material Name", mat_layout)
        self.eMatAngle = QLineEdit("0.")
        mf.addRow("Material Angle", self.eMatAngle)
        root.addWidget(grp_mat)

        grp_th = QGroupBox("Thickness")
        thf = QFormLayout(grp_th)
        thf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.eThickness = QLineEdit("0.1")
        thf.addRow("Thickness", self.eThickness)
        root.addWidget(grp_th)

        sm_row = QHBoxLayout()
        sm_row.setSpacing(6)

        grp_sm = QGroupBox("Stiffness Modifiers")
        smv = QVBoxLayout(grp_sm)
        smv.addWidget(_stub("Set Modifiers..."))
        sm_row.addWidget(grp_sm)

        grp_tp = QGroupBox("Temp Dependent Properties")
        tpv = QVBoxLayout(grp_tp)
        tpv.addWidget(_stub("Thermal Properties..."))
        sm_row.addWidget(grp_tp)

        root.addLayout(sm_row)

        br = QHBoxLayout()
        br.addStretch()
        self.btnOK  = QPushButton("OK")
        self.btnOK.setObjectName("primary")
        self.btnCxl = QPushButton("Cancel")
        self.btnOK.clicked.connect(self._on_ok)
        self.btnCxl.clicked.connect(self.reject)
        br.addWidget(self.btnOK)
        br.addWidget(self.btnCxl)
        root.addLayout(br)

    def _populate(self, s: PlaneSection):
        self.eName.setText(s.name)
        self.swatch.set_color(s.display_color)
        self.rbStress.setChecked(s.plane_type == "Plane-Stress")
        self.rbStrain.setChecked(s.plane_type == "Plane-Strain")
        self.chkIncompat.setChecked(s.incompatible_modes)
        if s.material:
            i = self.cboMat.findText(s.material.name)
            if i >= 0:
                self.cboMat.setCurrentIndex(i)
        self.eMatAngle.setText(str(s.material_angle))
        self.eThickness.setText(str(s.thickness))

    def _on_ok(self):
        name = self.eName.text().strip()
        if not name:
            QMessageBox.warning(self, "Input Error", "Section Name cannot be empty.")
            return
        if self._source is None and name in self.model.area_sections:
            QMessageBox.warning(self, "Duplicate Name",
                                f"A section named '{name}' already exists.")
            return
        try:
            thick = float(self.eThickness.text())
            ang   = float(self.eMatAngle.text())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid numeric value.")
            return

        ptype = "Plane-Stress" if self.rbStress.isChecked() else "Plane-Strain"
        mat   = self.model.materials.get(self.cboMat.currentText())
        sec   = PlaneSection(name, mat, ptype,
                             self.chkIncompat.isChecked(),
                             thick, ang, self.swatch.hex())

        if self._source and self._source.name != name:
            self.model.area_sections.pop(self._source.name, None)

        self.model.area_sections[name] = sec
        self.accept()

class AsolidSectionDialog(QDialog):
    """
    Matches SAP2000's Axisymmetric Solid (Asolid) Section Data dialog.
    """

    def __init__(self, model, section: AsolidSection = None, parent=None):
        super().__init__(parent)
        self.model   = model
        self._source = section
        self.setWindowTitle("Axisymmetric Solid (Asolid) Section Data")
        self.setMinimumWidth(400)
        apply_dialog_style(self)
        self._build_ui()
        if section:
            self._populate(section)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(6)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Section Name"))
        self.eName = QLineEdit()
        self.eName.setMinimumWidth(160)
        r1.addWidget(self.eName)
        root.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Section Notes"))
        r2.addWidget(_stub("Modify/Show..."))
        r2.addStretch()
        r2.addWidget(QLabel("Display Color"))
        self.swatch = _ColorSwatch("#FFFF00")                                            
        r2.addWidget(self.swatch)
        root.addLayout(r2)

        root.addWidget(_hsep())

        grp_type = QGroupBox("Type")
        tvl = QVBoxLayout(grp_type)
        self.chkIncompat = QCheckBox("Incompatible Modes")
        self.chkIncompat.setChecked(True)
        tvl.addWidget(self.chkIncompat)
        root.addWidget(grp_type)

        grp_mat = QGroupBox("Material")
        mf = QFormLayout(grp_mat)
        mf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        mat_layout, self._btnPlusMat, self.cboMat = _mat_row(self.model)
        mf.addRow("Material Name", mat_layout)
        self.eMatAngle = QLineEdit("0.")
        mf.addRow("Material Angle", self.eMatAngle)
        root.addWidget(grp_mat)

        grp_cs = QGroupBox("Symmetric about Z in this Coordinate System")
        csf = QFormLayout(grp_cs)
        csf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.cboCS = QComboBox()
        self.cboCS.addItems(["GLOBAL", "LOCAL"])
        csf.addRow("Coordinate System", self.cboCS)
        root.addWidget(grp_cs)

        grp_th = QGroupBox("Thickness")
        thv = QVBoxLayout(grp_th)
        arc_form = QFormLayout()
        arc_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.eArc = QLineEdit("0.")
        arc_form.addRow("Arc  (Degrees)", self.eArc)
        thv.addLayout(arc_form)
        lbl_note = QLabel("Note: A value of 0 for Arc means 1 radian")
        lbl_note.setStyleSheet(
            "color:#555555; font-style:italic; font-size:8pt; padding-top:2px;"
        )
        thv.addWidget(lbl_note)
        root.addWidget(grp_th)

        sm_row = QHBoxLayout()
        sm_row.setSpacing(6)

        grp_sm = QGroupBox("Stiffness Modifiers")
        smv = QVBoxLayout(grp_sm)
        smv.addWidget(_stub("Set Modifiers..."))
        sm_row.addWidget(grp_sm)

        grp_tp = QGroupBox("Temp Dependent Properties")
        tpv = QVBoxLayout(grp_tp)
        tpv.addWidget(_stub("Thermal Properties..."))
        sm_row.addWidget(grp_tp)

        root.addLayout(sm_row)

        br = QHBoxLayout()
        br.addStretch()
        self.btnOK  = QPushButton("OK")
        self.btnOK.setObjectName("primary")
        self.btnCxl = QPushButton("Cancel")
        self.btnOK.clicked.connect(self._on_ok)
        self.btnCxl.clicked.connect(self.reject)
        br.addWidget(self.btnOK)
        br.addWidget(self.btnCxl)
        root.addLayout(br)

    def _populate(self, s: AsolidSection):
        self.eName.setText(s.name)
        self.swatch.set_color(s.display_color)
        self.chkIncompat.setChecked(s.incompatible_modes)
        if s.material:
            i = self.cboMat.findText(s.material.name)
            if i >= 0:
                self.cboMat.setCurrentIndex(i)
        self.eMatAngle.setText(str(s.material_angle))
        i = self.cboCS.findText(s.coord_system)
        if i >= 0:
            self.cboCS.setCurrentIndex(i)
        self.eArc.setText(str(s.arc_degrees))

    def _on_ok(self):
        name = self.eName.text().strip()
        if not name:
            QMessageBox.warning(self, "Input Error", "Section Name cannot be empty.")
            return
        if self._source is None and name in self.model.area_sections:
            QMessageBox.warning(self, "Duplicate Name",
                                f"A section named '{name}' already exists.")
            return
        try:
            arc = float(self.eArc.text())
            ang = float(self.eMatAngle.text())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid numeric value.")
            return

        mat = self.model.materials.get(self.cboMat.currentText())
        sec = AsolidSection(name, mat,
                            self.chkIncompat.isChecked(),
                            self.cboCS.currentText(),
                            arc, ang, self.swatch.hex())

        if self._source and self._source.name != name:
            self.model.area_sections.pop(self._source.name, None)

        self.model.area_sections[name] = sec
        self.accept()

_DIALOG_MAP = {
    "Shell":                  ShellSectionDialog,
    "Plane":                  PlaneSectionDialog,
    "Asolid":                 AsolidSectionDialog,
    "Slab (Tributary/Yield)": TributarySlabSectionDialog,
}

_CLASS_MAP = {
    ShellSection:  "Shell",
    PlaneSection:  "Plane",
    AsolidSection: "Asolid",
}

class AreaSectionsManagerDialog(QDialog):
    """
    Matches SAP2000's Area Sections manager dialog.
    Provides a list of all area sections with Add / Copy / Modify / Delete.
    Opens the correct sub-dialog automatically based on section type.
    """

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Area Sections")
        self.setMinimumWidth(470)
        self.setMinimumHeight(310)
        apply_dialog_style(self)
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)

        body = QHBoxLayout()
        body.setSpacing(10)

        left = QVBoxLayout()
        left.addWidget(QLabel("Sections"))
        self.lst = QListWidget()
        self.lst.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lst.setMinimumWidth(150)
        left.addWidget(self.lst)
        body.addLayout(left, 2)

        right = QVBoxLayout()
        right.setSpacing(6)

        right.addWidget(QLabel("Select Section Type To Add"))
        self.cboType = QComboBox()
        self.cboType.addItems(["Shell", "Plane", "Asolid", "Slab (Tributary/Yield)"])
        right.addWidget(self.cboType)

        right.addWidget(QLabel("Click to:"))

        self.btnAdd    = QPushButton("Add New Section...")
        self.btnCopy   = QPushButton("Add Copy of Section...")
        self.btnModify = QPushButton("Modify/Show Section...")
        self.btnDelete = QPushButton("Delete Section")

        for b in [self.btnAdd, self.btnCopy, self.btnModify, self.btnDelete]:
            right.addWidget(b)

        right.addStretch()
        body.addLayout(right, 3)

        root.addLayout(body)
        root.addWidget(_hsep())

        br = QHBoxLayout()
        br.addStretch()
        self.btnOK  = QPushButton("OK")
        self.btnOK.setObjectName("primary")
        self.btnCxl = QPushButton("Cancel")
        self.btnOK.clicked.connect(self.accept)
        self.btnCxl.clicked.connect(self.reject)
        br.addWidget(self.btnOK)
        br.addWidget(self.btnCxl)
        root.addLayout(br)

        self.btnAdd.clicked.connect(self._on_add)
        self.btnCopy.clicked.connect(self._on_copy)
        self.btnModify.clicked.connect(self._on_modify)
        self.btnDelete.clicked.connect(self._on_delete)
        self.lst.itemSelectionChanged.connect(self._update_button_states)
        self.lst.itemDoubleClicked.connect(self._on_modify)

    def _refresh_list(self):
        self.lst.clear()
        for name in self.model.area_sections:
            self.lst.addItem(name)
        self._update_button_states()

    def _selected_section(self):
        items = self.lst.selectedItems()
        if not items:
            return None
        return self.model.area_sections.get(items[0].text())

    def _update_button_states(self):
        has = self._selected_section() is not None
        self.btnCopy.setEnabled(has)
        self.btnModify.setEnabled(has)
        self.btnDelete.setEnabled(has)

    def _open_section_dialog(self, type_key: str, existing=None):
        DlgClass = _DIALOG_MAP.get(type_key)
        if DlgClass is None:
            return
        dlg = DlgClass(self.model, existing, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_list()
                                             
            target_name = list(self.model.area_sections.keys())[-1] if existing is None\
                          else existing.name
            items = self.lst.findItems(target_name, Qt.MatchFlag.MatchExactly)
            if items:
                self.lst.setCurrentItem(items[0])

    def _on_add(self):
        self._open_section_dialog(self.cboType.currentText())

    def _on_copy(self, *_):
        src = self._selected_section()
        if src is None:
            return

        base = src.name + "_Copy"
        new_name = base
        n = 1
        while new_name in self.model.area_sections:
            new_name = f"{base}{n}"
            n += 1

        if isinstance(src, ShellSection):
            new_sec = ShellSection(new_name, src.material, src.shell_type,
                                   src.membrane_thickness, src.bending_thickness,
                                   src.material_angle, src.display_color)
        elif isinstance(src, PlaneSection):
            new_sec = PlaneSection(new_name, src.material, src.plane_type,
                                   src.incompatible_modes, src.thickness,
                                   src.material_angle, src.display_color)
        else:                  
            new_sec = AsolidSection(new_name, src.material, src.incompatible_modes,
                                    src.coord_system, src.arc_degrees,
                                    src.material_angle, src.display_color)

        new_sec.stiffness_modifiers = dict(src.stiffness_modifiers)
        if hasattr(src, 'modeling_type'):
            new_sec.modeling_type = src.modeling_type
        self.model.area_sections[new_name] = new_sec
        self._refresh_list()

        items = self.lst.findItems(new_name, Qt.MatchFlag.MatchExactly)
        if items:
            self.lst.setCurrentItem(items[0])

    def _on_modify(self, *_):
        src = self._selected_section()
        if src is None:
            return
            
        if getattr(src, 'modeling_type', None) == "Tributary Area":
            type_key = "Slab (Tributary/Yield)"
        else:
            type_key = _CLASS_MAP.get(type(src), "Shell")
            
        self._open_section_dialog(type_key, existing=src)

    def _on_delete(self):
        src = self._selected_section()
        if src is None:
            return

        in_use, msg = check_area_section_in_use(self.model, src.name)
        if in_use:
            QMessageBox.warning(self, "Section In Use", msg)
            return

        reply = QMessageBox.question(
            self, "Delete Section",
            f"Delete section '{src.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.model.area_sections.pop(src.name, None)
            self._refresh_list()
