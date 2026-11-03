import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QGroupBox, QPushButton, QFormLayout,
                             QMessageBox, QFileDialog, QSpinBox, QRadioButton,
                             QButtonGroup, QWidget, QSizePolicy)
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from app.ui.theme import (apply_dialog_style, style_plot_axes, PlotNavigator, COLORS,
                          on_theme_changed, off_theme_changed)

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
        self.resize(1300, 780)

        self._raw_values = []                                           

        main_layout = QHBoxLayout(self)

        left = QVBoxLayout()
        main_layout.addLayout(left, stretch=2)

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
        self._style_loaded(False)
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
        self.input_dt.editingFinished.connect(self._update_graph)
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
        main_layout.addLayout(right, stretch=5)

        self.figure = Figure(figsize=(5, 4), dpi=100)
        self.canvas_mpl = FigureCanvas(self.figure)
        self.canvas_mpl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ax = self.figure.add_subplot(111)
        self.nav = PlotNavigator(self.canvas_mpl, self.ax)
        self.canvas_mpl.setToolTip("Mouse wheel: zoom   |   Drag: pan   |   Double-click: reset view")
        self.canvas_mpl.mpl_connect("motion_notify_event", self._on_mouse_move)
        self._t = np.array([])
        self._a = np.array([])
        self._draw_empty()

        head = QHBoxLayout()
        head.addWidget(QLabel("Function Graph"))
        head.addStretch(1)
        self.btn_reset_view = QPushButton("Reset View")
        self.btn_reset_view.setObjectName("secondary")
        self.btn_reset_view.setToolTip("Back to the full record (or double-click the plot)")
        self.btn_reset_view.clicked.connect(self.nav.reset_view)
        head.addWidget(self.btn_reset_view)
        right.addLayout(head)

        right.addWidget(self.canvas_mpl, stretch=1)

        foot = QHBoxLayout()
        self.lbl_cursor = QLabel("")
        foot.addWidget(self.lbl_cursor)
        foot.addStretch(1)
        self.lbl_stats = QLabel("")
        self.lbl_stats.setAlignment(Qt.AlignmentFlag.AlignRight)
        foot.addWidget(self.lbl_stats)
        right.addLayout(foot)

        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _name):
        apply_dialog_style(self)
        self._style_loaded(bool(self.input_path.text().strip()))
        zoom = (self.ax.get_xlim(), self.ax.get_ylim()) if self.nav.user_zoomed else None
        self._update_graph()
        if zoom is not None:
            self.ax.set_xlim(*zoom[0])
            self.ax.set_ylim(*zoom[1])
            self.nav.user_zoomed = True
            self.canvas_mpl.draw_idle()

    def _on_mouse_move(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None or len(self._t) == 0:
            self.lbl_cursor.setText("")
            return
        i = int(np.clip(np.searchsorted(self._t, ev.xdata), 0, len(self._t) - 1))
        if i > 0 and abs(self._t[i - 1] - ev.xdata) < abs(self._t[i] - ev.xdata):
            i -= 1
        self.lbl_cursor.setText(f"t = {self._t[i]:.3f} s    a = {self._a[i]:.5g} m/s²")

    def done(self, r):
        off_theme_changed(self._on_theme_changed)
        super().done(r)

    def _style_loaded(self, has_file):
        if has_file:
            self.lbl_loaded.setStyleSheet(f"color: {COLORS['text_primary']}; font-style: normal;")
        else:
            self.lbl_loaded.setStyleSheet(f"color: {COLORS['text_secondary']}; font-style: italic;")

    def _draw_empty(self):
        self.ax.clear()
        style_plot_axes(self.figure, self.ax)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Acceleration (m/s²)")
        self.ax.set_title("No data loaded", fontsize=9)
        self._t = np.array([])
        self._a = np.array([])
        self.figure.tight_layout()
        self.nav.mark_home()
        self.canvas_mpl.draw_idle()

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Accelerogram File", "",
            "CSV / Text Files (*.csv *.txt *.dat);;All Files (*)"
        )
        if not path:
            return
        self.input_path.setText(path)
        self.lbl_loaded.setText(path)
        self._style_loaded(True)
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
        vals = self._raw_values
        if not vals:
            self._draw_empty()
            self.lbl_stats.setText("")
            return

        self.ax.clear()
        style_plot_axes(self.figure, self.ax)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Acceleration (m/s²)")

        try:
            dt = float(self.input_dt.text())
        except ValueError:
            dt = 0.005

        t = np.arange(len(vals)) * dt
        a = np.array(vals)

        self.ax.plot(t, a, color=COLORS["accent"], linewidth=0.8)
        self.ax.axhline(0, color=COLORS["text_secondary"], linewidth=0.8)
        self.ax.set_title(f"{self.input_name.text()} — {len(vals)} points", fontsize=9)

        self._t, self._a = t, a
        if len(t) > 1:
            self.ax.set_xlim(t[0], t[-1])
        pga = float(np.max(np.abs(a)))
        self.lbl_stats.setText(
            f"Points: {len(vals)}    Duration: {t[-1]:.2f}s    PGA: {pga:.4f} m/s²"
        )
        self.figure.tight_layout()
        self.nav.mark_home()
        self.canvas_mpl.draw_idle()

    def populate(self, data: dict):
        """Fill the dialog from a saved data dict (for Modify/Show)."""
        self.input_name.setText(data.get("name", "THFUNC1"))
        self.input_path.setText(data.get("file_path", ""))
        self.lbl_loaded.setText(data.get("file_path", "No file specified or file not found."))
        self._style_loaded(bool(data.get("file_path", "")))

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
