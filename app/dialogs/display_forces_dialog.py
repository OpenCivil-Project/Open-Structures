from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QRadioButton, QGroupBox, QLineEdit, 
                             QPushButton, QGridLayout, QWidget, QSpinBox, QButtonGroup)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

class DisplayForcesDialog(QDialog):
                                                                            
    apply_forces_signal = pyqtSignal(dict)

    def __init__(self, model, parent=None, available_cases=None, base_path=''):
        super().__init__(parent)
        self.model = model
        self.available_cases = available_cases or []
        self.base_path = base_path
        self.setWindowTitle("Display Frame Forces/Stresses")
        self.setMinimumWidth(450)
        
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        
        gb_case = QGroupBox("Case/Combo")
        grid_case = QGridLayout(gb_case)
        
        grid_case.addWidget(QLabel("Case/Combo Name"), 0, 0)
        self.cb_case = QComboBox()
        
        if hasattr(self.model, 'load_cases') and self.model.load_cases:
            if self.available_cases:
                                                                                
                valid_cases = [c for c in self.available_cases if c in self.model.load_cases]
                self.cb_case.addItems(valid_cases if valid_cases else list(self.model.load_cases.keys()))
            else:
                                                                  
                self.cb_case.addItems(list(self.model.load_cases.keys()))
        elif self.available_cases:
            self.cb_case.addItems(self.available_cases)
        else:
            self.cb_case.addItems(["DEAD", "LIVE", "MODAL"])
            
        grid_case.addWidget(self.cb_case, 0, 1)
        
        main_layout.addWidget(gb_case)

        gb_multi = QGroupBox("Multivalued Options")
        grid_multi = QGridLayout(gb_multi)
        
        self.rb_envelope = QRadioButton("Envelope (Max or Min)")
        self.rb_step = QRadioButton("Step")
        self.rb_step.setChecked(True)
        
        self.sb_step = QSpinBox()
        self.sb_step.setMinimum(1)
        self.sb_step.setMaximum(100)
        
        grid_multi.addWidget(self.rb_envelope, 0, 0)
        grid_multi.addWidget(self.rb_step, 1, 0)
        grid_multi.addWidget(self.sb_step, 1, 1)
        
        main_layout.addWidget(gb_multi)

        gb_type = QGroupBox("Display Type")
        layout_type = QHBoxLayout(gb_type)
        
        self.rb_force = QRadioButton("Force")
        self.rb_stress = QRadioButton("Stress")
        self.rb_force.setChecked(True)
        
        layout_type.addWidget(self.rb_force)
        layout_type.addWidget(self.rb_stress)
        
        main_layout.addWidget(gb_type)

        gb_comp = QGroupBox("Component")
        grid_comp = QGridLayout(gb_comp)
        
        self.rb_axial = QRadioButton("Axial Force")
        self.rb_torsion = QRadioButton("Torsion")
        self.rb_shear22 = QRadioButton("Shear 3-3")
        self.rb_shear33 = QRadioButton("Shear 2-2")
        self.rb_moment22 = QRadioButton("Moment 3-3")
        self.rb_moment33 = QRadioButton("Moment 2-2")
        
        self.rb_moment33.setChecked(True)
        
        grid_comp.addWidget(self.rb_axial, 0, 0)
        grid_comp.addWidget(self.rb_torsion, 0, 1)
        grid_comp.addWidget(self.rb_shear22, 1, 0)
        grid_comp.addWidget(self.rb_moment22, 1, 1)
        grid_comp.addWidget(self.rb_shear33, 2, 0)
        grid_comp.addWidget(self.rb_moment33, 2, 1)
        
        main_layout.addWidget(gb_comp)

        gb_scale = QGroupBox("Scaling for Diagram")
        grid_scale = QGridLayout(gb_scale)
        
        self.rb_auto_scale = QRadioButton("Automatic")
        self.rb_user_scale = QRadioButton("User Defined")
        self.rb_auto_scale.setChecked(True)
        
        self.le_scale_value = QLineEdit()
        self.le_scale_value.setEnabled(False)
        
        self.rb_auto_scale.toggled.connect(lambda: self.le_scale_value.setEnabled(self.rb_user_scale.isChecked()))
        
        grid_scale.addWidget(self.rb_auto_scale, 0, 0)
        grid_scale.addWidget(self.rb_user_scale, 1, 0)
        grid_scale.addWidget(self.le_scale_value, 1, 1)
        
        main_layout.addWidget(gb_scale)

        gb_options = QGroupBox("Options for Diagram")
        layout_options = QHBoxLayout(gb_options)
        
        self.rb_fill = QRadioButton("Fill Diagram")
        self.rb_show_values = QRadioButton("Show Values")
        self.rb_fill.setChecked(True)
        
        layout_options.addWidget(self.rb_fill)
        layout_options.addWidget(self.rb_show_values)
        
        main_layout.addWidget(gb_options)

        layout_btns = QVBoxLayout()
        
        self.btn_reset_default = QPushButton("Reset Form to Default Values")
        self.btn_reset_window = QPushButton("Reset Form to Current Window Settings")
        self.btn_reset_window.setEnabled(False)              
        
        layout_btns.addWidget(self.btn_reset_default)
        layout_btns.addWidget(self.btn_reset_window)
        
        main_layout.addLayout(layout_btns)

        layout_bottom_btns = QHBoxLayout()
        
        self.btn_ok = QPushButton("OK")
        self.btn_close = QPushButton("Close")
        self.btn_apply = QPushButton("Apply")
        
        layout_bottom_btns.addWidget(self.btn_ok)
        layout_bottom_btns.addWidget(self.btn_close)
        layout_bottom_btns.addWidget(self.btn_apply)
        
        main_layout.addLayout(layout_bottom_btns)

        self.btn_close.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self.apply_settings)
        self.btn_ok.clicked.connect(self.on_ok)

    def get_current_settings(self):
        """Reads the UI and packages the user's choices into a dictionary."""
                                                  
        component = 'M3'          
        if self.rb_axial.isChecked(): component = 'P'
        elif self.rb_shear22.isChecked(): component = 'V2'
        elif self.rb_shear33.isChecked(): component = 'V3'
        elif self.rb_moment22.isChecked(): component = 'M2'
        elif self.rb_moment33.isChecked(): component = 'M3'
        
        scale_factor = None
        if self.rb_user_scale.isChecked():
            try:
                scale_factor = float(self.le_scale_value.text())
            except ValueError:
                scale_factor = None                                                 
                
        show_labels = self.rb_show_values.isChecked()
        style = 'show_values' if show_labels else 'fill'

        load_case = self.cb_case.currentText()

        return {
            'component': component,
            'scale_factor': scale_factor,
            'style': style,
            'load_case': load_case,
            'base_path': self.base_path,
            'show_labels': show_labels,
        }

    def apply_settings(self):
        """Fires the signal to main.py without closing the window."""
        settings = self.get_current_settings()
                                                               
        self.apply_forces_signal.emit(settings)

    def on_ok(self):
        """Fires the signal and closes the window."""
        self.apply_settings()
        self.accept()
