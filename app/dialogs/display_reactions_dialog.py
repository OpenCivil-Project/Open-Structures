from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QComboBox, QRadioButton, QPushButton)
from PyQt6.QtCore import pyqtSignal

class DisplayReactionsDialog(QDialog):
    """
    Dialog to configure and display joint reactions in Open // Structures.
    Includes an option to toggle the physics sign convention.
    """
                                                                                                   
    apply_reactions_signal = pyqtSignal(dict)
    last_settings = {}

    def __init__(self, available_cases, base_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Display Joint Reactions")
        self.setMinimumWidth(320)
        
        self.available_cases = available_cases
        self.base_path = base_path

        self.envelope_combo = QComboBox()
        self.envelope_combo.addItems(["Max", "Min"])
        
        self.init_ui()
        self.load_last_settings()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        
        grp_case = QGroupBox("Case/Combo Name")
        vbox_case = QVBoxLayout()
        self.combo_cases = QComboBox()
        self.combo_cases.addItems(self.available_cases)
        vbox_case.addWidget(self.combo_cases)
        grp_case.setLayout(vbox_case)
        main_layout.addWidget(grp_case)

        grp_type = QGroupBox("Display Type")
        vbox_type = QVBoxLayout()
        self.radio_arrows = QRadioButton("Show as Arrows")
        self.radio_arrows.setChecked(True)
        self.radio_tabulated = QRadioButton("Show as Tabulated")
        vbox_type.addWidget(self.radio_arrows)
        vbox_type.addWidget(self.radio_tabulated)
        grp_type.setLayout(vbox_type)
        main_layout.addWidget(grp_type)

        grp_env = QGroupBox("Envelope (LTHA / Combos)")
        vbox_env = QVBoxLayout()
        vbox_env.addWidget(self.envelope_combo)
        grp_env.setLayout(vbox_env)
        main_layout.addWidget(grp_env)

        grp_sign = QGroupBox("Sign Convention")
        vbox_sign = QVBoxLayout()
        self.radio_ground = QRadioButton("Ground on Structure (Standard)")
        self.radio_ground.setChecked(True)
        self.radio_struct = QRadioButton("Structure on Ground (Reversed)")
        vbox_sign.addWidget(self.radio_ground)
        vbox_sign.addWidget(self.radio_struct)
        grp_sign.setLayout(vbox_sign)
        main_layout.addWidget(grp_sign)

        btn_layout = QHBoxLayout()
        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self.on_apply)
        
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_apply)
        btn_layout.addWidget(btn_close)
        main_layout.addLayout(btn_layout)

    def load_last_settings(self):
        """Restores the last used parameters for a smoother user experience."""
        if DisplayReactionsDialog.last_settings:
            settings = DisplayReactionsDialog.last_settings
            
            idx = self.combo_cases.findText(settings.get('load_case', ''))
            if idx >= 0:
                self.combo_cases.setCurrentIndex(idx)

            if settings.get('display_type') == 'tabulated':
                self.radio_tabulated.setChecked(True)
            else:
                self.radio_arrows.setChecked(True)

            env_idx = self.envelope_combo.findText(settings.get('envelope', 'max').capitalize())
            if env_idx >= 0:
                self.envelope_combo.setCurrentIndex(env_idx)

            if settings.get('sign_convention') == 'structure_on_ground':
                self.radio_struct.setChecked(True)
            else:
                self.radio_ground.setChecked(True)

    def on_apply(self):
        """Packages the current UI states into a dictionary and emits the signal."""
        display_type = 'tabulated' if self.radio_tabulated.isChecked() else 'arrows'
        envelope = self.envelope_combo.currentText().lower()
        sign_conv = 'structure_on_ground' if self.radio_struct.isChecked() else 'ground_on_structure'

        settings = {
            'load_case': self.combo_cases.currentText(),
            'base_path': self.base_path,
            'display_type': display_type,
            'envelope': envelope,
            'sign_convention': sign_conv
        }

        DisplayReactionsDialog.last_settings = settings
        self.apply_reactions_signal.emit(settings)
