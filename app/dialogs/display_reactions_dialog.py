from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QComboBox, QRadioButton, QPushButton)
from PyQt6.QtCore import pyqtSignal

class DisplayReactionsDialog(QDialog):
    """
    Dialog to configure and display joint reactions in Open / Structure.
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
        
        self.init_ui()
        self.load_last_settings()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        
        grp_case = QGroupBox("Case/Combo Name")
        vbox_case = QVBoxLayout()
        self.combo_case = QComboBox()
        self.combo_case.addItems(self.available_cases)
        vbox_case.addWidget(self.combo_case)
        grp_case.setLayout(vbox_case)
        main_layout.addWidget(grp_case)
        
        grp_sign = QGroupBox("Sign Convention")
        vbox_sign = QVBoxLayout()
        self.radio_ground_on_struct = QRadioButton("Ground on Structure")
        self.radio_struct_on_ground = QRadioButton("Structure on Ground")
        self.radio_ground_on_struct.setChecked(True)                               
        
        vbox_sign.addWidget(self.radio_ground_on_struct)
        vbox_sign.addWidget(self.radio_struct_on_ground)
        grp_sign.setLayout(vbox_sign)
        main_layout.addWidget(grp_sign)

        grp_display = QGroupBox("Display Type")
        vbox_display = QVBoxLayout()
        self.radio_arrows = QRadioButton("Arrows")
        self.radio_tabulated = QRadioButton("Tabulated")
        self.radio_arrows.setChecked(True)
        
        vbox_display.addWidget(self.radio_arrows)
        vbox_display.addWidget(self.radio_tabulated)
        grp_display.setLayout(vbox_display)
        main_layout.addWidget(grp_display)
        
        hbox_btns = QHBoxLayout()
        self.btn_ok = QPushButton("OK")
        self.btn_close = QPushButton("Close")
        self.btn_apply = QPushButton("Apply")
        
        hbox_btns.addStretch()
        hbox_btns.addWidget(self.btn_ok)
        hbox_btns.addWidget(self.btn_close)
        hbox_btns.addWidget(self.btn_apply)
        main_layout.addLayout(hbox_btns)
        
        self.btn_ok.clicked.connect(self.on_ok)
        self.btn_apply.clicked.connect(self.apply_settings)
        self.btn_close.clicked.connect(self.reject)

    def get_current_settings(self):
        display_type = 'arrows' if self.radio_arrows.isChecked() else 'tabulated'
        sign_conv = 'ground_on_structure' if self.radio_ground_on_struct.isChecked() else 'structure_on_ground'
        
        return {
            'load_case': self.combo_case.currentText(),
            'display_type': display_type,
            'sign_convention': sign_conv,
            'base_path': self.base_path
        }

    def save_last_settings(self):
        DisplayReactionsDialog.last_settings = self.get_current_settings()

    def load_last_settings(self):
        if DisplayReactionsDialog.last_settings:
            settings = DisplayReactionsDialog.last_settings
            
            idx = self.combo_case.findText(settings.get('load_case', ''))
            if idx >= 0:
                self.combo_case.setCurrentIndex(idx)
                
            if settings.get('display_type') == 'tabulated':
                self.radio_tabulated.setChecked(True)
            else:
                self.radio_arrows.setChecked(True)
                
            if settings.get('sign_convention') == 'structure_on_ground':
                self.radio_struct_on_ground.setChecked(True)
            else:
                self.radio_ground_on_struct.setChecked(True)

    def apply_settings(self):
        self.save_last_settings()
        self.apply_reactions_signal.emit(self.get_current_settings())

    def on_ok(self):
        self.apply_settings()
        self.accept()
