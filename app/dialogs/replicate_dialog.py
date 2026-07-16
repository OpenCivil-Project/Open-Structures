from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QCheckBox, QGroupBox, 
                             QTabWidget, QWidget, QDialogButtonBox, QMessageBox)
from PyQt6.QtCore import pyqtSignal

class ReplicateDialog(QDialog):
                                                        
    signal_pick_points = pyqtSignal()
    signal_apply = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Replicate")
        self.resize(350, 400)
        self.setModal(False)
        
        self.dx = 0.0
        self.dy = 0.0
        self.dz = 0.0
        self.num = 1
        self.delete_original = False
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        tabs = QTabWidget()
        self.tab_linear = QWidget()
        tabs.addTab(self.tab_linear, "Linear")
        layout.addWidget(tabs)
        
        lin_layout = QVBoxLayout(self.tab_linear)
        
        grp_inc = QGroupBox("Increments (Global)")
        inc_layout = QVBoxLayout()
        
        row_x = QHBoxLayout()
        row_x.addWidget(QLabel("dx:"))
        self.input_dx = QLineEdit("0.0")
        row_x.addWidget(self.input_dx)
        inc_layout.addLayout(row_x)

        row_y = QHBoxLayout()
        row_y.addWidget(QLabel("dy:"))
        self.input_dy = QLineEdit("0.0")
        row_y.addWidget(self.input_dy)
        inc_layout.addLayout(row_y)

        row_z = QHBoxLayout()
        row_z.addWidget(QLabel("dz:"))
        self.input_dz = QLineEdit("0.0")
        row_z.addWidget(self.input_dz)
        inc_layout.addLayout(row_z)

        btn_pick = QPushButton("Pick Two Points on Model")
        btn_pick.clicked.connect(self.on_pick_clicked)
        inc_layout.addWidget(btn_pick)
        
        grp_inc.setLayout(inc_layout)
        lin_layout.addWidget(grp_inc)

        grp_data = QGroupBox("Increment Data")
        data_layout = QHBoxLayout()
        data_layout.addWidget(QLabel("Number:"))
        self.input_num = QLineEdit("1")
        data_layout.addWidget(self.input_num)
        grp_data.setLayout(data_layout)
        lin_layout.addWidget(grp_data)

        grp_opt = QGroupBox("Options")
        opt_layout = QVBoxLayout()
        self.chk_delete = QCheckBox("Delete Original Objects")
        opt_layout.addWidget(self.chk_delete)
        grp_opt.setLayout(opt_layout)
        lin_layout.addWidget(grp_opt)

        lin_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Apply |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.on_ok_clicked)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.on_apply_clicked)
        layout.addWidget(buttons)

    def on_pick_clicked(self):
        """Hides dialog and emits signal to Main Window"""
        self.hide()
        self.signal_pick_points.emit()

    def set_increments(self, dx, dy, dz):
        """Called by Main Window after picking points"""
        self.input_dx.setText(f"{dx:.3f}")
        self.input_dy.setText(f"{dy:.3f}")
        self.input_dz.setText(f"{dz:.3f}")
        self.show()                 
        self.raise_()

    def _parse_inputs(self):
        """Reads and validates the input fields. Returns True on success.
        Shows a message and returns False on bad input, instead of failing silently."""
        try:
            dx = float(self.input_dx.text())
            dy = float(self.input_dy.text())
            dz = float(self.input_dz.text())
            num = int(self.input_num.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input",
                                "dx, dy, and dz must be numbers, and Number must be a whole number.")
            return False

        if num < 1:
            QMessageBox.warning(self, "Invalid Input", "Number must be at least 1.")
            return False

        self.dx = dx
        self.dy = dy
        self.dz = dz
        self.num = num
        self.delete_original = self.chk_delete.isChecked()
        return True

    def on_ok_clicked(self):
        if self._parse_inputs():
            self.signal_apply.emit()
            self.accept()

    def on_apply_clicked(self):
        if self._parse_inputs():
            self.signal_apply.emit()
