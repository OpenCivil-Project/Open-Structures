import sys
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QComboBox, QGroupBox, QTableWidget, 
                             QTableWidgetItem, QPushButton, QHeaderView, 
                             QFormLayout, QFrame, QMessageBox, QWidget)
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import numpy as np
from PyQt6.QtWidgets import QFileDialog
                         
from core.solver.RSA.tsc2018_generator import TSC2018SpectrumGenerator
from app.ui.theme import apply_dialog_style

class ResponseSpectrumDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Response Spectrum TSC-2018 Function Definition")
        self.resize(1100, 700)                              
        
        self.generator = TSC2018SpectrumGenerator()
        self.main_layout = QHBoxLayout(self)

        self.left_panel = QVBoxLayout()
        self.main_layout.addLayout(self.left_panel, stretch=1)

        form_name = QFormLayout()
        self.input_name = QLineEdit("FUNC1")
        form_name.addRow("Function Name:", self.input_name)
        self.left_panel.addLayout(form_name)

        grp_params = QGroupBox("Parameters")
        layout_params = QFormLayout(grp_params)
        
        self.in_ss = self.create_input("0.55")
        self.in_s1 = self.create_input("0.22")
        self.in_tl = self.create_input("6.0")
        self.in_R = self.create_input("8.0")
        self.in_D = self.create_input("3.0")
        self.in_I = self.create_input("1.0")
        
        layout_params.addRow("0.2 Sec Spectral Accel, Ss", self.in_ss)
        layout_params.addRow("1 Sec Spectral Accel, S1", self.in_s1)
        layout_params.addRow("Long-Period Transition Period", self.in_tl)
        layout_params.addRow("Response Modification, R", self.in_R)
        layout_params.addRow("System Overstrength, D", self.in_D)
        layout_params.addRow("Occupancy Importance, I", self.in_I)

        self.combo_site = QComboBox()
        self.combo_site.addItems(["ZA", "ZB", "ZC", "ZD", "ZE"])
        self.combo_site.setCurrentText("ZB")
        self.combo_site.currentTextChanged.connect(self.update_graph)
        layout_params.addRow("Site Class", self.combo_site)

        self.combo_dir = QComboBox()
        self.combo_dir.addItems(["Horizontal", "Vertical"])
        self.combo_dir.currentTextChanged.connect(self.update_graph)
        layout_params.addRow("Design Spectrum Direction", self.combo_dir)

        self.combo_interp = QComboBox()
        self.combo_interp.addItems(["Linear (Standard)", "Cubic / Exact (TBDY)"])
        self.combo_interp.setToolTip("Linear: Matches SAP2000's straight-line approximation.\nExact: Uses the curved 1/R formula from TBDY-2018.")
        layout_params.addRow("Interpolation Method", self.combo_interp)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        layout_params.addRow(line)
        self.lbl_fs = QLabel("0.0"); layout_params.addRow("Site Coefficient, Fs", self.lbl_fs)
        self.lbl_f1 = QLabel("0.0"); layout_params.addRow("Site Coefficient, F1", self.lbl_f1)
        
        line2 = QFrame(); line2.setFrameShape(QFrame.Shape.HLine)
        layout_params.addRow(line2)
        self.lbl_sds = QLabel("0.0"); layout_params.addRow("Calculated SDS = Fs * Ss", self.lbl_sds)
        self.lbl_sd1 = QLabel("0.0"); layout_params.addRow("Calculated SD1 = F1 * S1", self.lbl_sd1)

        self.left_panel.addWidget(grp_params)
        self.left_panel.addStretch()

        btn_box = QHBoxLayout()
        self.btn_ok = QPushButton("OK"); self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("Cancel"); self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_ok); btn_box.addWidget(self.btn_cancel)
        self.left_panel.addLayout(btn_box)

        self.btn_export = QPushButton("Export to CSV")
        self.btn_export.clicked.connect(self.export_spectrum)
        btn_box.addWidget(self.btn_export)

        self.right_panel = QVBoxLayout()
        self.main_layout.addLayout(self.right_panel, stretch=2)

        damp_layout = QHBoxLayout()
        damp_layout.addStretch()
        damp_layout.addWidget(QLabel("Function Damping Ratio"))
        self.in_damp = QLineEdit("0.05")
        self.in_damp.setFixedWidth(60)
        damp_layout.addWidget(self.in_damp)
        self.right_panel.addLayout(damp_layout)

        graph_split = QHBoxLayout()
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Period", "Acceleration"])
        self.table.setFixedWidth(200)
        self.table.verticalHeader().setVisible(False)
        graph_split.addWidget(self.table)

        graph_container = QWidget()
        graph_layout = QVBoxLayout(graph_container)
        graph_layout.setContentsMargins(0,0,0,0)

        self.figure = Figure(figsize=(5, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setStyleSheet("background-color: white; border: none;")             
        
        graph_layout.addWidget(self.toolbar)                     
        graph_layout.addWidget(self.canvas)                    
        
        self.ax = self.figure.add_subplot(111)
        
        graph_split.addWidget(graph_container)
        self.right_panel.addLayout(graph_split)

        self.lbl_coords = QLabel("0.0, 0.0")
        self.lbl_coords.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.right_panel.addWidget(self.lbl_coords)

        self.update_graph()

    def create_input(self, default_val):
        le = QLineEdit(default_val)
        le.editingFinished.connect(self.update_graph)
        return le

    def get_float(self, line_edit):
        try: return float(line_edit.text())
        except ValueError: return 0.0

    def get_data(self):
        return {
            "type": "TSC-2018",
            "name": self.input_name.text(),
            "Ss": self.get_float(self.in_ss), "S1": self.get_float(self.in_s1),
            "TL": self.get_float(self.in_tl), "R": self.get_float(self.in_R),
            "D": self.get_float(self.in_D), "I": self.get_float(self.in_I),
            "SiteClass": self.combo_site.currentText(),
            "Direction": self.combo_dir.currentText(),
            "Interpolation": "Linear" if "Linear" in self.combo_interp.currentText() else "Exact",
            "Damping": self.get_float(self.in_damp),
        }

    def export_spectrum(self):
        """Exports the current spectrum curve to a CSV file"""
        import csv
        
        filepath, _ = QFileDialog.getSaveFileName(
            self, 
            "Export Response Spectrum", 
            f"{self.input_name.text()}_spectrum.csv",
            "CSV Files (*.csv)"
        )
        
        if not filepath:
            return                  
        
        ss = self.get_float(self.in_ss)
        s1 = self.get_float(self.in_s1)
        tl = self.get_float(self.in_tl)
        R = self.get_float(self.in_R)
        D = self.get_float(self.in_D)
        I = self.get_float(self.in_I)
        site_class = self.combo_site.currentText()
        direction = self.combo_dir.currentText()
        
        periods, accels, params = self.generator.generate_spectrum_curve(
            ss, s1, site_class, R, D, I, tl, direction=direction
        )
        
        try:
            with open(filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                
                writer.writerow(['Response Spectrum - TBDY 2018'])
                writer.writerow(['Function Name:', self.input_name.text()])
                writer.writerow(['Direction:', direction])
                writer.writerow(['Site Class:', site_class])
                writer.writerow(['Ss:', ss, 'S1:', s1, 'TL:', tl])
                writer.writerow(['R:', R, 'D:', D, 'I:', I])
                writer.writerow(['SDS:', params['SDS'], 'SD1:', params['SD1']])
                writer.writerow([])              
                
                writer.writerow(['Period (sec)', 'Spectral Acceleration (g)'])
                for t, sa in zip(periods, accels):
                    writer.writerow([f'{t:.4f}', f'{sa:.5f}'])
            
            QMessageBox.information(self, "Success", f"Spectrum exported to:\n{filepath}")
        
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Could not write file:\n{e}")

    def update_graph(self):
                       
        ss = self.get_float(self.in_ss); s1 = self.get_float(self.in_s1)
        tl = self.get_float(self.in_tl); R = self.get_float(self.in_R)
        D = self.get_float(self.in_D); I = self.get_float(self.in_I)
        site_class = self.combo_site.currentText()
        direction = self.combo_dir.currentText()

        periods, accels, params = self.generator.generate_spectrum_curve(
            ss, s1, site_class, R, D, I, tl, direction=direction
        )

        self.lbl_fs.setText(f"{params['Fs']:.3f}")
        self.lbl_f1.setText(f"{params['F1']:.3f}")
        self.lbl_sds.setText(f"{params['SDS']:.3f}")
        self.lbl_sd1.setText(f"{params['SD1']:.3f}")

        self.ax.clear()
        self.ax.grid(True, which='both', linestyle='--', linewidth=0.5, alpha=0.7)
        self.ax.set_xlabel("Period (sec)")
        self.ax.set_ylabel("Spectral Accel (g)")
        title = f"Response Spectrum TSC-2018 ({direction})"
        self.ax.set_title(title, fontsize=10)
        
        color = 'blue' if direction == "Horizontal" else 'red'
        self.ax.plot(periods, accels, color=color, linewidth=1.5)
        
        self.ax.set_aspect('auto') 
        self.figure.tight_layout()
        
        self.canvas.draw()

        self.table.setRowCount(len(periods))
        
        for r, (t, sa) in enumerate(zip(periods, accels)):
                                                             
            self.table.setItem(r, 0, QTableWidgetItem(f"{t:.4f}"))
            self.table.setItem(r, 1, QTableWidgetItem(f"{sa:.4f}"))
            
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    dlg = ResponseSpectrumDialog()
    dlg.show()
    sys.exit(app.exec())
