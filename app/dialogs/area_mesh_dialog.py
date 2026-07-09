from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QSpinBox, QDoubleSpinBox, QPushButton, QLabel,
    QRadioButton, QButtonGroup, QCheckBox, QGroupBox, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from app.ui.theme import apply_dialog_style

class AreaMeshDialog(QDialog):
                                                   
    signal_apply_mesh = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Automatic Area Mesh")
        self.setMinimumWidth(340)
        self.setWindowFlag(Qt.WindowType.Tool)
        
        apply_dialog_style(self)
        self._build_ui()
        self._toggle_inputs()                    

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        root.addWidget(QLabel("Select meshing parameters for the selected Area Objects:"))

        self.radio_div = QRadioButton("Mesh by Divisions (N x M)")
        self.radio_size = QRadioButton("Mesh by Max Element Size")
        
        self.radio_div.setChecked(True)          
        
        self.bg = QButtonGroup(self)
        self.bg.addButton(self.radio_div)
        self.bg.addButton(self.radio_size)
        
        self.radio_div.toggled.connect(self._toggle_inputs)

        self.form_div_widget = QWidget()
        form_div = QFormLayout(self.form_div_widget)
        form_div.setContentsMargins(20, 0, 0, 0)                  
        
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 100)
        self.spin_n.setValue(2)
        
        self.spin_m = QSpinBox()
        self.spin_m.setRange(1, 100)
        self.spin_m.setValue(2)

        form_div.addRow("Along Edge 1 to 2 (N):", self.spin_n)
        form_div.addRow("Along Edge 1 to 3 (M):", self.spin_m)

        self.form_size_widget = QWidget()
        form_size = QFormLayout(self.form_size_widget)
        form_size.setContentsMargins(20, 0, 0, 0)
        
        self.spin_size_x = QDoubleSpinBox()
        self.spin_size_x.setRange(0.01, 1000.0)
        self.spin_size_x.setValue(0.5)
        self.spin_size_x.setSingleStep(0.1)
        
        self.spin_size_y = QDoubleSpinBox()
        self.spin_size_y.setRange(0.01, 1000.0)
        self.spin_size_y.setValue(0.5)
        self.spin_size_y.setSingleStep(0.1)

        form_size.addRow("Max Size Along 1-2:", self.spin_size_x)
        form_size.addRow("Max Size Along 1-3:", self.spin_size_y)

        root.addWidget(self.radio_div)
        root.addWidget(self.form_div_widget)
        root.addWidget(self.radio_size)
        root.addWidget(self.form_size_widget)

        self.chk_frames = QCheckBox("Add Points to Selected/Adjacent Frames")
        self.chk_frames.setToolTip("Divides any bordering frame elements so they share the new mesh nodes.")
        self.chk_frames.setChecked(True)
        root.addWidget(self.chk_frames)

        self.lbl_note = QLabel("Note: 'Code Based' slabs are skipped during meshing.")
        self.lbl_note.setStyleSheet("color:#555555; font-style:italic; font-size:8pt;")
        root.addWidget(self.lbl_note)
                                         
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setObjectName("primary")
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("secondary")
        
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_close.clicked.connect(self.close)
        
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(self.btn_close)
        root.addLayout(btn_layout)

    def _toggle_inputs(self):
        """Enables/Disables spinboxes based on radio selection."""
        is_div = self.radio_div.isChecked()
        self.form_div_widget.setEnabled(is_div)
        self.form_size_widget.setEnabled(not is_div)

    def _on_apply(self):
        """Packages the UI state into a dictionary and emits it."""
        settings = {
            "mode": "divisions" if self.radio_div.isChecked() else "size",
            "n": self.spin_n.value(),
            "m": self.spin_m.value(),
            "max_x": self.spin_size_x.value(),
            "max_y": self.spin_size_y.value(),
            "divide_frames": self.chk_frames.isChecked()
        }
        self.signal_apply_mesh.emit(settings)
