from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox,
                             QFormLayout, QPushButton, QGroupBox, QHBoxLayout,
                             QRadioButton, QButtonGroup, QDoubleSpinBox, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal

from app.ui.theme import apply_dialog_style, COLORS, SIZES

class DrawBeamColumnDialog(QDialog):

    signal_dialog_closed = pyqtSignal()
    signal_type_changed = pyqtSignal(str)                       

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        apply_dialog_style(self)

        self.setWindowTitle("Quick Beam / Column")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(320)

        main_layout = QVBoxLayout(self)

        type_group = QGroupBox("Member Type")
        type_layout = QHBoxLayout()
        self.beam_radio   = QRadioButton("Beam  (horizontal)")
        self.col_radio    = QRadioButton("Column  (vertical)")
        self.beam_radio.setChecked(True)
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self.beam_radio)
        self._type_group.addButton(self.col_radio)
        type_layout.addWidget(self.beam_radio)
        type_layout.addWidget(self.col_radio)
        type_group.setLayout(type_layout)
        main_layout.addWidget(type_group)

        self.prop_group = QGroupBox("Member Properties")
        form_layout = QFormLayout()

        self.section_combo = QComboBox()
        self.refresh_sections()
        form_layout.addRow("Section:", self.section_combo)

        self.release_combo = QComboBox()
        self.release_combo.addItems(["Continuous", "Pinned-Pinned"])
        form_layout.addRow("End Releases:", self.release_combo)

        self.prop_group.setLayout(form_layout)
        main_layout.addWidget(self.prop_group)

        angle_group = QGroupBox("Angle Orientation")
        angle_layout = QVBoxLayout()
        
        spin_layout = QHBoxLayout()
        spin_layout.addWidget(QLabel("Rotate Local Axis:"))
        self.spin_angle = QDoubleSpinBox()
        self.spin_angle.setRange(-360.0, 360.0)
        self.spin_angle.setSingleStep(90.0)                             
        self.spin_angle.setValue(0.0)
        self.spin_angle.setSuffix(" °")
        spin_layout.addWidget(self.spin_angle)
        angle_layout.addLayout(spin_layout)

        btn_help_layout = QHBoxLayout()
        self.btn_0 = QPushButton("0°")
        self.btn_0.setObjectName("secondary")
        self.btn_0.clicked.connect(lambda: self.spin_angle.setValue(0.0))
        self.btn_90 = QPushButton("90°")
        self.btn_90.setObjectName("secondary")
        self.btn_90.clicked.connect(lambda: self.spin_angle.setValue(90.0))
        btn_help_layout.addWidget(self.btn_0)
        btn_help_layout.addWidget(self.btn_90)
        angle_layout.addLayout(btn_help_layout)
        
        angle_group.setLayout(angle_layout)
        main_layout.addWidget(angle_group)

        self.insertion_group = QGroupBox("Insertion & Offsets (Beams Only)")
        insertion_layout = QVBoxLayout()
        
        self.chk_apply_offset = QCheckBox("Apply Top-Center Offset (Flush with Slab)")
        self.chk_apply_offset.setChecked(True)
        insertion_layout.addWidget(self.chk_apply_offset)

        self.chk_no_transform = QCheckBox("Do Not Transform Stiffness")
        self.chk_no_transform.setChecked(False)
        insertion_layout.addWidget(self.chk_no_transform)
        
        self.insertion_group.setLayout(insertion_layout)
        main_layout.addWidget(self.insertion_group)

        inst_group = QGroupBox("Drawing Controls")
        inst_layout = QVBoxLayout()
        lbl = QLabel("• <b>Hover</b> over a grid line to highlight<br>"
                     "• <b>Left Click:</b> Place member<br>"
                     "• <b>Esc:</b> Exit draw mode")
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: {SIZES['font_size_small']}pt;")
        inst_layout.addWidget(lbl)
        inst_group.setLayout(inst_layout)
        main_layout.addWidget(inst_group)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("secondary")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)
        main_layout.addLayout(btn_layout)

        self.beam_radio.toggled.connect(self._on_type_changed)
        self.chk_apply_offset.toggled.connect(self._on_offset_toggled)
        
        self._on_type_changed(True)

    def _on_type_changed(self, _checked):
        is_beam = self.beam_radio.isChecked()
        self.insertion_group.setVisible(is_beam)
        self.signal_type_changed.emit('beam' if is_beam else 'column')

    def _on_offset_toggled(self, checked):
                                                                                
        self.chk_no_transform.setVisible(checked)

    def get_member_type(self):
        return 'beam' if self.beam_radio.isChecked() else 'column'

    def refresh_sections(self):
        current = self.section_combo.currentText()
        self.section_combo.clear()
        if not self.model.sections:
            self.section_combo.addItem("Default")
        else:
            self.section_combo.addItems(list(self.model.sections.keys()))
        idx = self.section_combo.findText(current)
        if idx >= 0:
            self.section_combo.setCurrentIndex(idx)

    def get_selected_section(self):
        name = self.section_combo.currentText()
        if name in self.model.sections:
            return self.model.sections[name]
        return None
        
    def get_rotation_angle(self):
        return self.spin_angle.value()

    def get_apply_offset(self):
        return self.chk_apply_offset.isChecked()

    def get_no_transform(self):
        return self.chk_no_transform.isChecked()

    def get_release_arrays(self):
        if self.release_combo.currentText() == "Pinned-Pinned":
            rel_i = [False, False, False, False, True, True]
            rel_j = [False, False, False, False, True, True]
        else:
            rel_i = [False, False, False, False, False, False]
            rel_j = [False, False, False, False, False, False]
        return rel_i, rel_j

    def closeEvent(self, event):
        self.signal_dialog_closed.emit()
        super().closeEvent(event)
