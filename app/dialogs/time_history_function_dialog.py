import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QGroupBox, QPushButton, QFormLayout,
                             QMessageBox, QFileDialog, QSpinBox, QRadioButton,
                             QButtonGroup, QWidget)
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from app.ui.theme import apply_dialog_style

class TimeHistoryFunctionDialog(QDialog):
    """
    Editor for a single Time History accelerogram function.
    Mirrors the layout/pattern of ResponseSpectrumDialog.

    Saves data as:
        {
            "type":       "FromFile",
            "name":       "THFUNC1",
            "file_path":  "/path/to/accel.csv",
            "dt":         0.005,
            "header_skip": 0,
            "accel_col":  0,          # 0-based column index
            "values":     [...]       # cached float list, loaded on OK
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Time History Function Definition")
        self.resize(1000, 600)

        self._raw_values = []                                           

        main_layout = QHBoxLayout(self)

        left = QVBoxLayout()
        main_layout.addLayout(left, stretch=1)

        form_name = QFormLayout()
        self.input_name = QLineEdit("THFUNC1")
        form_name.addRow("Function Name:", self.input_name)
        left.addLayout(form_name)

        grp_file = QGroupBox("Function File")
        f_file = QFormLayout(grp_file)

        h_browse = QHBoxLayout()
        self.input_path = QLineEdit()
        self.input_path.setReadOnly(True)
        self.input_path.setPlaceholderText("No file specified or file not found.")
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.setFixedWidth(80)
        self.btn_browse.clicked.connect(self._browse_file)
        h_browse.addWidget(self.input_path)
        h_browse.addWidget(self.btn_browse)
        f_file.addRow("File Name:", h_browse)

        self.lbl_loaded = QLabel("No file specified or file not found.")
        self.lbl_loaded.setStyleSheet("color: gray; font-style: italic;")
        f_file.addRow("File Loaded From:", self.lbl_loaded)

        self.spin_header = QSpinBox()
        self.spin_header.setRange(0, 100)
        self.spin_header.setValue(0)
        self.spin_header.valueChanged.connect(self._reload_and_plot)
        f_file.addRow("Header Lines to Skip:", self.spin_header)

        self.spin_col = QSpinBox()
        self.spin_col.setRange(0, 20)
        self.spin_col.setValue(0)
        self.spin_col.setToolTip("0-based column index for acceleration values")
        self.spin_col.valueChanged.connect(self._reload_and_plot)
        f_file.addRow("Acceleration Column (0-based):", self.spin_col)

        left.addWidget(grp_file)

        grp_vals = QGroupBox("Values are:")
        f_vals = QVBoxLayout(grp_vals)

        self.radio_equal = QRadioButton("Values at Equal Intervals of")
        self.radio_time  = QRadioButton("Time and Function Values (col 0 = time)")
        self.radio_equal.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.radio_equal)
        bg.addButton(self.radio_time)

        h_dt = QHBoxLayout()
        h_dt.addWidget(self.radio_equal)
        self.input_dt = QLineEdit("0.005")
        self.input_dt.setFixedWidth(90)
        h_dt.addWidget(self.input_dt)
        h_dt.addWidget(QLabel("s"))
        h_dt.addStretch()
        f_vals.addLayout(h_dt)
        f_vals.addWidget(self.radio_time)

        left.addWidget(grp_vals)
        left.addStretch()

        h_btns = QHBoxLayout()
        self.btn_ok     = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_cancel.clicked.connect(self.reject)
        h_btns.addWidget(self.btn_ok)
        h_btns.addWidget(self.btn_cancel)
        left.addLayout(h_btns)

        right = QVBoxLayout()
        main_layout.addLayout(right, stretch=2)

        right.addWidget(QLabel("Function Graph"))

        graph_container = QWidget()
        graph_layout = QVBoxLayout(graph_container)
        graph_layout.setContentsMargins(0, 0, 0, 0)

        self.figure = Figure(figsize=(5, 4), dpi=100)
        self.canvas_mpl = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Acceleration (m/s²)")
        self.ax.set_title("No data loaded")
        self.ax.grid(True, linestyle='--', alpha=0.5)
        self.figure.tight_layout()

        graph_layout.addWidget(self.canvas_mpl)
        right.addWidget(graph_container)

        self.lbl_stats = QLabel("")
        self.lbl_stats.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.lbl_stats)

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Accelerogram File", "",
            "CSV / Text Files (*.csv *.txt *.dat);;All Files (*)"
        )
        if not path:
            return
        self.input_path.setText(path)
        self.lbl_loaded.setText(path)
        self.lbl_loaded.setStyleSheet("color: black; font-style: normal;")
        self._reload_and_plot()

    def _read_file(self):
        """
        Reads the file and returns a list of floats based on current settings.
        Returns [] on any failure.
        """
        path = self.input_path.text().strip()
        if not path:
            return []

        import csv, os
        if not os.path.exists(path):
            return []

        header_skip = self.spin_header.value()
        col_idx     = self.spin_col.value()
        use_time_col = self.radio_time.isChecked()

        values = []
        try:
            with open(path, 'r') as f:
                sample = f.read(2048)
                f.seek(0)
                delimiter = '\t' if '\t' in sample else ','
                reader = csv.reader(f, delimiter=delimiter)

                for row_i, row in enumerate(reader):
                    if row_i < header_skip:
                        continue
                    if not row:
                        continue

                    target_col = col_idx
                    if use_time_col and target_col == 0:
                        target_col = 1                                      

                    if len(row) <= target_col:
                        continue
                    try:
                        values.append(float(row[target_col]))
                    except ValueError:
                        continue
        except Exception:
            return []

        return values

    def _reload_and_plot(self):
        """Re-reads file with current settings and refreshes graph."""
        self._raw_values = self._read_file()
        self._update_graph()

    def _update_graph(self):
        self.ax.clear()
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Acceleration (m/s²)")
        self.ax.grid(True, linestyle='--', alpha=0.5)

        vals = self._raw_values
        if not vals:
            self.ax.set_title("No data loaded")
            self.lbl_stats.setText("")
            self.figure.tight_layout()
            self.canvas_mpl.draw()
            return

        try:
            dt = float(self.input_dt.text())
        except ValueError:
            dt = 0.005

        t = np.arange(len(vals)) * dt
        a = np.array(vals)

        self.ax.plot(t, a, color='steelblue', linewidth=0.8)
        self.ax.axhline(0, color='gray', linewidth=0.6, linestyle='--')
        self.ax.set_title(f"{self.input_name.text()} — {len(vals)} points")

        pga = float(np.max(np.abs(a)))
        self.lbl_stats.setText(
            f"Points: {len(vals)}    Duration: {t[-1]:.2f}s    PGA: {pga:.4f} m/s²"
        )
        self.figure.tight_layout()
        self.canvas_mpl.draw()

    def populate(self, data: dict):
        """Fill the dialog from a saved data dict (for Modify/Show)."""
        self.input_name.setText(data.get("name", "THFUNC1"))
        self.input_path.setText(data.get("file_path", ""))
        self.lbl_loaded.setText(data.get("file_path", "No file specified or file not found."))

        dt = data.get("dt", 0.005)
        self.input_dt.setText(str(dt))
        self.spin_header.setValue(data.get("header_skip", 0))
        self.spin_col.setValue(data.get("accel_col", 0))

        if data.get("time_col_mode", False):
            self.radio_time.setChecked(True)
        else:
            self.radio_equal.setChecked(True)

        cached = data.get("values", [])
        if cached:
            self._raw_values = cached
        else:
            self._raw_values = self._read_file()

        self._update_graph()

    def get_data(self) -> dict:
        """Returns the data dict to store in model.th_functions."""
        try:
            dt = float(self.input_dt.text())
        except ValueError:
            dt = 0.005

        return {
            "type":          "FromFile",
            "name":          self.input_name.text().strip(),
            "file_path":     self.input_path.text().strip(),
            "dt":            dt,
            "header_skip":   self.spin_header.value(),
            "accel_col":     self.spin_col.value(),
            "time_col_mode": self.radio_time.isChecked(),
            "values":        list(self._raw_values),                                    
        }

    def _on_ok(self):
        name = self.input_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Function name cannot be empty.")
            return

        if not self._raw_values:
            self._raw_values = self._read_file()

        if not self._raw_values:
            reply = QMessageBox.question(
                self, "No Data",
                "No acceleration data could be read from the file.\n"
                "Save anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        self.accept()
