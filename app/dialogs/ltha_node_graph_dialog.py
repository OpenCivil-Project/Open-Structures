from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QFrame, QPushButton)
from PyQt6.QtCore import Qt
import pyqtgraph as pg
from pyqtgraph import mkPen, mkBrush
import numpy as np
from core.units import unit_registry

DOF_LABELS = ["UX", "UY", "UZ", "RX", "RY", "RZ"]

MODE_FULL_RECORD = "full"
MODE_SEISMOGRAPH = "seis"

class LTHANodeGraphDialog(QDialog):
    """
    Displacement vs Time graph for a single node during LTHA playback.

    Two display modes:
      Full Record  — entire time-history shown, cursor tracks playback/scrubber
      Seismograph  — curve draws live as the animation plays, like an EEG
    """

    def __init__(self, node_id, canvas, parent=None):
        super().__init__(parent)
        self.node_id      = str(node_id)
        self.canvas       = canvas
        self.current_dof  = 0
        self.display_mode = MODE_FULL_RECORD

        self._data  = None
        self._times = None

        self._seis_t          = []
        self._seis_val        = []
        self._last_seis_step  = -1

        self.setWindowTitle(f"Joint {node_id} — Time History")
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.resize(700, 380)

        self._init_ui()
        self._load_full_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        top = QHBoxLayout()

        top.addWidget(QLabel("DOF:"))
        self.combo_dof = QComboBox()
        self.combo_dof.addItems(DOF_LABELS)
        self.combo_dof.setFixedWidth(68)
        self.combo_dof.currentIndexChanged.connect(self._on_dof_changed)
        top.addWidget(self.combo_dof)

        top.addSpacing(14)

        self.btn_full = QPushButton("Full Record")
        self.btn_seis = QPushButton("Seismograph")
        for btn in (self.btn_full, self.btn_seis):
            btn.setCheckable(True)
            btn.setFixedHeight(24)
        self.btn_full.setChecked(True)
        self.btn_full.clicked.connect(lambda: self._set_mode(MODE_FULL_RECORD))
        self.btn_seis.clicked.connect(lambda: self._set_mode(MODE_SEISMOGRAPH))
        top.addWidget(self.btn_full)
        top.addWidget(self.btn_seis)

        top.addStretch()

        self.lbl_current = QLabel("t = —   |   val = —")
        self.lbl_current.setStyleSheet(
            "font-family: Consolas; color: #0055AA;"
            "font-weight: bold; font-size: 11px;")
        top.addWidget(self.lbl_current)

        top.addSpacing(16)

        self.lbl_peak = QLabel("Peak: —")
        self.lbl_peak.setStyleSheet(
            "font-family: Consolas; color: #CC4400;"
            "font-weight: bold; font-size: 11px;")
        top.addWidget(self.lbl_peak)

        layout.addLayout(top)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        self.plot_widget = pg.PlotWidget(background='w')
        self.plot_widget.hideButtons()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.20)
        self.plot_widget.setLabel('bottom', 'Time (s)')

        pi = self.plot_widget.getPlotItem()
        for ax in ('left', 'bottom', 'right', 'top'):
            axis = pi.getAxis(ax)
            if axis:
                axis.setPen(mkPen('k'))
                axis.setTextPen(mkPen('k'))

        self._zero_line = pg.InfiniteLine(
            pos=0, angle=0, pen=mkPen('#bbbbbb', width=1))
        self.plot_widget.addItem(self._zero_line)

        self._curve_full = self.plot_widget.plot(
            pen=mkPen('#0055AA', width=1.8))

        self._curve_seis = self.plot_widget.plot(
            pen=mkPen('#0055AA', width=1.8))
        self._curve_seis.setVisible(False)

        self._peak_scatter = pg.ScatterPlotItem(
            size=9, brush=mkBrush('#CC4400'), pen=mkPen(None))
        self.plot_widget.addItem(self._peak_scatter)

        self._cursor = pg.InfiniteLine(
            pos=0, angle=90,
            pen=mkPen('#CC4400', width=1.8,
                      style=Qt.PenStyle.DashLine))
        self.plot_widget.addItem(self._cursor)

        layout.addWidget(self.plot_widget)

    def _load_full_data(self):
        dof = self.current_dof
        n   = getattr(self.canvas, 'ltha_n_steps', 0)
        dt  = getattr(self.canvas, 'ltha_dt', 0.01)
        if n == 0:
            return

        raw = self._get_raw_series(dof, n)
        if raw is None:
            return

        if dof < 3:
            self._data = np.array(
                [unit_registry.to_display_length(float(v)) for v in raw],
                dtype=np.float64)
            unit_str = unit_registry.length_unit_name
        else:
            self._data   = raw.astype(np.float64)
            unit_str = "rad"

        self._times = np.arange(n) * dt
        self._curve_full.setData(self._times, self._data)
        self.plot_widget.setLabel('left', f"{DOF_LABELS[dof]} ({unit_str})")

        if len(self._data):
            peak_idx = int(np.argmax(np.abs(self._data)))
            peak_val = self._data[peak_idx]
            peak_t   = self._times[peak_idx]
            self._peak_scatter.setData(x=[peak_t], y=[peak_val])
            self.lbl_peak.setText(
                f"Peak: {self._fmt(peak_val)} @ {peak_t:.2f} s")

        self.plot_widget.autoRange()

    def _get_raw_series(self, dof, n_steps):
        if (hasattr(self.canvas, 'ltha_tensor')
                and self.canvas.ltha_tensor is not None
                and hasattr(self.canvas, 'ltha_node_map')):
            node_idx = self.canvas.ltha_node_map.get(self.node_id)
            if node_idx is not None:
                return self.canvas.ltha_tensor[node_idx, :n_steps, dof]

        history = getattr(self.canvas, 'ltha_history', None)
        if history and self.node_id in history:
            return history[self.node_id][:n_steps, dof]

        return None

    def update_cursor(self, t_index):
        """Called on every animation tick AND on scrubber drag."""
        dt    = getattr(self.canvas, 'ltha_dt', 0.01)
        t_sec = t_index * dt

        if self.display_mode == MODE_FULL_RECORD:
            self._update_full_record(t_index, t_sec)
        else:
            self._update_seismograph(t_index, t_sec)

    def _update_full_record(self, t_index, t_sec):
        if self._data is None:
            return
        t_index = max(0, min(t_index, len(self._data) - 1))
        self._cursor.setValue(t_sec)
        val = self._data[t_index]
        self.lbl_current.setText(
            f"t = {t_sec:.2f} s   |   "
            f"{DOF_LABELS[self.current_dof]} = {self._fmt(val)}")

    def _update_seismograph(self, t_index, t_sec):
                                     
        if t_index < self._last_seis_step:
            self._seis_t.clear()
            self._seis_val.clear()
        self._last_seis_step = t_index

        n   = getattr(self.canvas, 'ltha_n_steps', 0)
        raw = self._get_raw_series(self.current_dof, n)
        if raw is None or t_index >= len(raw):
            return

        dof     = self.current_dof
        val_raw = float(raw[t_index])
        val     = (unit_registry.to_display_length(val_raw)
                   if dof < 3 else val_raw)

        self._seis_t.append(t_sec)
        self._seis_val.append(val)
        self._curve_seis.setData(self._seis_t, self._seis_val)

        self.lbl_current.setText(
            f"t = {t_sec:.2f} s   |   "
            f"{DOF_LABELS[dof]} = {self._fmt(val)}")

        if self._seis_val:
            peak = max(self._seis_val, key=abs)
            self.lbl_peak.setText(f"Peak so far: {self._fmt(peak)}")
                                               
            y_range = max(abs(peak) * 1.2, 1e-6)
            self.plot_widget.setYRange(-y_range, y_range, padding=0)

        if len(self._seis_t) > 1:
            x_min = max(0.0, t_sec - 10.0)
            self.plot_widget.setXRange(x_min, t_sec + 0.5, padding=0)

    def _set_mode(self, mode):
        self.display_mode = mode
        self.btn_full.setChecked(mode == MODE_FULL_RECORD)
        self.btn_seis.setChecked(mode == MODE_SEISMOGRAPH)

        is_full = (mode == MODE_FULL_RECORD)
        self._curve_full.setVisible(is_full)
        self._peak_scatter.setVisible(is_full)
        self._cursor.setVisible(is_full)
        self._curve_seis.setVisible(not is_full)

        if is_full:
            self._load_full_data()
            self.plot_widget.autoRange()
            self.lbl_peak.setText("Peak: —")
        else:
            self._seis_t.clear()
            self._seis_val.clear()
            self._last_seis_step = -1
            self._curve_seis.setData([], [])
            self.plot_widget.autoRange()
            self.lbl_peak.setText("Peak so far: —")

    def _on_dof_changed(self, index):
        self.current_dof = index
        unit_str = (unit_registry.length_unit_name if index < 3 else "rad")
        self.plot_widget.setLabel('left', f"{DOF_LABELS[index]} ({unit_str})")
        if self.display_mode == MODE_SEISMOGRAPH:
            self._seis_t.clear()
            self._seis_val.clear()
            self._last_seis_step = -1
            self._curve_seis.setData([], [])
        self._load_full_data()

    @staticmethod
    def _fmt(val):
        if abs(val) < 1e-10: return "0.0000"
        if abs(val) < 1e-4:  return f"{val:.4e}"
        return f"{val:.4f}"
