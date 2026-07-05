from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QRadioButton, QGroupBox, 
                             QComboBox, QGridLayout, QMessageBox, QFrame)
from PyQt6.QtCore import Qt

from core.solver.RSA.tsc2018_generator import TSC2018SpectrumGenerator

class TSC2018Dialog(QDialog):
    def __init__(self, load_pattern, parent=None):
        super().__init__(parent)
        self.load_pattern = load_pattern
        self.setWindowTitle(f"TSC-2018 Seismic Load Pattern - {load_pattern.name}")
        self.resize(750, 550)
        
        self.generator = TSC2018SpectrumGenerator()

        if not hasattr(self.load_pattern, 'tsc_data') or not self.load_pattern.tsc_data:
            from core.model import TSC2018Data
            self.load_pattern.tsc_data = TSC2018Data()
            
        self.data = self.load_pattern.tsc_data

        main_layout = QHBoxLayout(self)

        left_layout = QVBoxLayout()

        grp_dir = QGroupBox("Load Direction and Diaphragm Eccentricity")
        v_dir = QVBoxLayout()
        self.rb_x = QRadioButton("Global X Direction")
        self.rb_y = QRadioButton("Global Y Direction")
        if self.data.direction == "X": self.rb_x.setChecked(True)
        else: self.rb_y.setChecked(True)
        
        h_ecc = QHBoxLayout()
        h_ecc.addWidget(QLabel("Ecc. Ratio (All Diaph.):"))
        self.inp_ecc = QLineEdit(str(self.data.eccentricity))
        self.inp_ecc.setFixedWidth(60)
        h_ecc.addStretch()
        h_ecc.addWidget(self.inp_ecc)

        v_dir.addWidget(self.rb_x)
        v_dir.addWidget(self.rb_y)
        v_dir.addLayout(h_ecc)
        grp_dir.setLayout(v_dir)
        left_layout.addWidget(grp_dir)

        grp_time = QGroupBox("Time Period")
        grid_time = QGridLayout()
        
        self.rb_approx = QRadioButton("Approx. Period")
        self.rb_prog = QRadioButton("Program Calc")
        self.rb_user = QRadioButton("User Defined")
        
        cap_explanation = "The computed modal period cannot exceed the code-mandated empirical upper limit (Ta_max) based on Ct."
        self.rb_prog.setToolTip(cap_explanation)
        
        if self.data.period_method == "Approx": self.rb_approx.setChecked(True)
        elif self.data.period_method == "User": self.rb_user.setChecked(True)
        else: self.rb_prog.setChecked(True)

        grid_time.addWidget(self.rb_approx, 0, 0)
        grid_time.addWidget(self.rb_prog, 1, 0)
        
        lbl_cap_note = QLabel("<i>(Subject to empirical upper limit cap)</i>")
        lbl_cap_note.setStyleSheet("color: #666666; font-size: 11px;")
        grid_time.addWidget(lbl_cap_note, 2, 0)

        grid_time.addWidget(self.rb_user, 3, 0)

        grid_time.addWidget(QLabel("Ct (m), x ="), 0, 1, 2, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.combo_ct = QComboBox()
        self.combo_ct.addItems(["0.10; 0.75", "0.08; 0.75", "0.07; 0.75"])
        ct_str = f"{self.data.ct:.2f}; 0.75" if hasattr(self.data, 'ct') else "0.10; 0.75"
        self.combo_ct.setCurrentText(ct_str)
        grid_time.addWidget(self.combo_ct, 0, 2, 2, 1, Qt.AlignmentFlag.AlignVCenter)

        grid_time.addWidget(QLabel("T (sec) ="), 3, 1, 1, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.inp_t = QLineEdit(str(self.data.user_t))
        grid_time.addWidget(self.inp_t, 3, 2)
        
        self.rb_user.toggled.connect(lambda: self.inp_t.setEnabled(self.rb_user.isChecked()))
        self.rb_user.toggled.connect(lambda: self.combo_ct.setDisabled(self.rb_user.isChecked()))
        
        self.inp_t.setEnabled(self.rb_user.isChecked())
        self.combo_ct.setDisabled(self.rb_user.isChecked())

        grp_time.setLayout(grid_time)
        left_layout.addWidget(grp_time)

        grp_elev = QGroupBox("Lateral Load Elevation Range")
        v_elev = QVBoxLayout()
        self.rb_elev_prog = QRadioButton("Program Calculated")
        self.rb_elev_user = QRadioButton("User Specified")
        self.rb_elev_prog.setChecked(True)                  
        
        h_elev_inputs = QGridLayout()
        h_elev_inputs.addWidget(QLabel("Max Z"), 0, 0)
        self.inp_max_z = QLineEdit("0.")
        self.inp_max_z.setEnabled(False)
        h_elev_inputs.addWidget(self.inp_max_z, 0, 1)
        
        h_elev_inputs.addWidget(QLabel("Min Z"), 1, 0)
        self.inp_min_z = QLineEdit("0.")
        self.inp_min_z.setEnabled(False)
        h_elev_inputs.addWidget(self.inp_min_z, 1, 1)

        v_elev.addWidget(self.rb_elev_prog)
        v_elev.addWidget(self.rb_elev_user)
        v_elev.addLayout(h_elev_inputs)
        grp_elev.setLayout(v_elev)
        left_layout.addWidget(grp_elev)

        left_layout.addStretch()
        main_layout.addLayout(left_layout)

        right_layout = QVBoxLayout()

        grp_coeff = QGroupBox("Seismic Coefficients")
        grid_coeff = QGridLayout()
        
        grid_coeff.addWidget(QLabel("0.2 Sec Spectral Accel, Ss:"), 0, 0)
        self.inp_ss = QLineEdit(str(self.data.ss))
        self.inp_ss.editingFinished.connect(self.update_calculations)
        grid_coeff.addWidget(self.inp_ss, 0, 1)

        grid_coeff.addWidget(QLabel("1 Sec Spectral Accel, S1:"), 1, 0)
        self.inp_s1 = QLineEdit(str(self.data.s1))
        self.inp_s1.editingFinished.connect(self.update_calculations)
        grid_coeff.addWidget(self.inp_s1, 1, 1)

        grid_coeff.addWidget(QLabel("Long-Period Transition:"), 2, 0)
        self.inp_tl = QLineEdit(str(self.data.tl))
        grid_coeff.addWidget(self.inp_tl, 2, 1)
        
        line1 = QFrame(); line1.setFrameShape(QFrame.Shape.HLine)
        grid_coeff.addWidget(line1, 3, 0, 1, 2)

        grid_coeff.addWidget(QLabel("Site Class:"), 4, 0)
        self.combo_site = QComboBox()
        self.combo_site.addItems(["ZA", "ZB", "ZC", "ZD", "ZE", "ZF"])
        self.combo_site.setCurrentText(self.data.site_class)
        self.combo_site.currentTextChanged.connect(self.update_calculations)
        grid_coeff.addWidget(self.combo_site, 4, 1)
        
        grid_coeff.addWidget(QLabel("Site Coefficient, Fs"), 5, 0)
        self.lbl_fs = QLabel("0.0")
        grid_coeff.addWidget(self.lbl_fs, 5, 1)

        grid_coeff.addWidget(QLabel("Site Coefficient, F1"), 6, 0)
        self.lbl_f1 = QLabel("0.0")
        grid_coeff.addWidget(self.lbl_f1, 6, 1)

        grp_coeff.setLayout(grid_coeff)
        right_layout.addWidget(grp_coeff)

        grp_calc = QGroupBox("Calculated Coefficients")
        grid_calc = QGridLayout()
        
        grid_calc.addWidget(QLabel("SDS = Fs * Ss"), 0, 0)
        self.lbl_sds = QLineEdit("0.0")
        self.lbl_sds.setReadOnly(True)
        grid_calc.addWidget(self.lbl_sds, 0, 1)

        grid_calc.addWidget(QLabel("SD1 = F1 * S1"), 1, 0)
        self.lbl_sd1 = QLineEdit("0.0")
        self.lbl_sd1.setReadOnly(True)
        grid_calc.addWidget(self.lbl_sd1, 1, 1)

        grp_calc.setLayout(grid_calc)
        right_layout.addWidget(grp_calc)

        grp_factors = QGroupBox("Factors")
        grid_factors = QGridLayout()
        
        grid_factors.addWidget(QLabel("Response Modification, R:"), 0, 0)
        self.inp_r = QLineEdit(str(self.data.r))
        grid_factors.addWidget(self.inp_r, 0, 1)

        grid_factors.addWidget(QLabel("System Overstrength, D:"), 1, 0)
        self.inp_d = QLineEdit(str(self.data.d))
        grid_factors.addWidget(self.inp_d, 1, 1)

        grid_factors.addWidget(QLabel("Occupancy Importance, I:"), 2, 0)
        self.inp_i = QLineEdit(str(self.data.importance))
        grid_factors.addWidget(self.inp_i, 2, 1)

        grp_factors.setLayout(grid_factors)
        right_layout.addWidget(grp_factors)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")
        btn_ok.setFixedWidth(100)
        btn_ok.clicked.connect(self.save_and_accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        
        right_layout.addLayout(btn_layout)
        main_layout.addLayout(right_layout)

        self.update_calculations()

    def get_float(self, line_edit):
        try: return float(line_edit.text())
        except ValueError: return 0.0

    def update_calculations(self):
        """Runs the math via TSC2018SpectrumGenerator and updates labels on the fly."""
        ss = self.get_float(self.inp_ss)
        s1 = self.get_float(self.inp_s1)
        site_class = self.combo_site.currentText()

        fs, f1 = self.generator.get_coeffs(ss, s1, site_class)
        
        sds = ss * fs
        sd1 = s1 * f1

        self.lbl_fs.setText(f"{fs:.3g}")
        self.lbl_f1.setText(f"{f1:.3g}")
        self.lbl_sds.setText(f"{sds:.4g}")
        self.lbl_sd1.setText(f"{sd1:.4g}")

    def save_and_accept(self):
        try:
            self.data.direction = "X" if self.rb_x.isChecked() else "Y"
            self.data.eccentricity = float(self.inp_ecc.text())
            
            if self.rb_approx.isChecked(): self.data.period_method = "Approx"
            elif self.rb_user.isChecked(): self.data.period_method = "User"
            else: self.data.period_method = "Program Calc"
            
            ct_str = self.combo_ct.currentText().split(";")[0]
            self.data.ct = float(ct_str)
            self.data.user_t = float(self.inp_t.text())
            
            self.data.ss = float(self.inp_ss.text())
            self.data.s1 = float(self.inp_s1.text())
            self.data.tl = float(self.inp_tl.text())
            self.data.site_class = self.combo_site.currentText()
            
            self.data.r = float(self.inp_r.text())
            self.data.d = float(self.inp_d.text())
            self.data.importance = float(self.inp_i.text())
            
            self.accept()
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please ensure all fields contain valid numbers.")
