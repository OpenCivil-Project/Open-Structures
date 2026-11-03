"""
protocol_dialog.py   (app/dialogs/)

"Generate Load Path" dialog: builds a displacement (or load-factor) history from a protocol type
using core/opensees_port/load_protocols.py, and hands the list of numbers back to the caller.

    dlg = ProtocolGeneratorDialog(parent, unit_name="mm", title="Generate Displacement History")
    if dlg.exec(): values = dlg.values        # in the SAME unit the dialog showed (display units)
Use unit_name="" for a unitless load-factor history.
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLineEdit, QSpinBox,
                             QCheckBox, QLabel, QPushButton, QMessageBox)
from app.ui.theme import apply_dialog_style
from core.opensees_port import load_protocols as lp

class ProtocolGeneratorDialog(QDialog):
    def __init__(self, parent=None, unit_name="", title="Generate Load Path", step=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle(title)
        self.setModal(True)
        self.values = []
        self._unit = unit_name
        self._step = step                                                                                        

        root = QVBoxLayout(self)
        form = QFormLayout()
        u = f" ({unit_name})" if unit_name else ""

        self.cmb_kind = QComboBox()
        self.cmb_kind.addItems(lp.PROTOCOL_KINDS)
        form.addRow("Protocol:", self.cmb_kind)

        self.ed_target = QLineEdit("0.05")
        self.ed_amp = QLineEdit("0.01")
        self.ed_amps = QLineEdit("0.005, 0.01, 0.02, 0.03")
        self.ed_height = QLineEdit("1.0")
        self.ed_drifts = QLineEdit(", ".join(f"{d:g}" for d in lp.ACI_374_1_DRIFTS_PCT))
        self.spin_cycles = QSpinBox(); self.spin_cycles.setRange(1, 50); self.spin_cycles.setValue(3)
        self.chk_pos = QCheckBox("Start in the positive direction"); self.chk_pos.setChecked(True)

        self.rows = {
            "target": ("Target" + u + ":", self.ed_target),
            "amp": ("Amplitude" + u + ":", self.ed_amp),
            "amps": ("Amplitudes" + u + " (comma separated):", self.ed_amps),
            "height": ("Height for drift" + u + ":", self.ed_height),
            "drifts": ("Drift levels (%):", self.ed_drifts),
            "cycles": ("Cycles per level:", self.spin_cycles),
        }
        self._labels = {}
        for k, (txt, w) in self.rows.items():
            lbl = QLabel(txt); self._labels[k] = lbl
            form.addRow(lbl, w)
        form.addRow(self.chk_pos)
        root.addLayout(form)

        self.lbl_info = QLabel("")
        root.addWidget(self.lbl_info)

        btns = QHBoxLayout(); btns.addStretch()
        ok = QPushButton("Generate"); ok.setObjectName("primary"); ok.clicked.connect(self._accept)
        cancel = QPushButton("Cancel"); cancel.setObjectName("secondary"); cancel.clicked.connect(self.reject)
        btns.addWidget(ok); btns.addWidget(cancel)
        root.addLayout(btns)

        self.cmb_kind.currentTextChanged.connect(self._sync)
        self._sync()

    def _sync(self, *_):
        show = {"Monotonic": ("target",),
                "Symmetric cycles": ("amp", "cycles"),
                "Increasing amplitude": ("amps", "cycles"),
                "Drift-based (ACI 374.1)": ("height", "drifts", "cycles"),
                "One-sided cycles": ("amps", "cycles")}[self.cmb_kind.currentText()]
        for k, (_t, w) in self.rows.items():
            vis = k in show
            w.setVisible(vis); self._labels[k].setVisible(vis)
        self.chk_pos.setVisible(self.cmb_kind.currentText() in ("Symmetric cycles", "Increasing amplitude",
                                                               "Drift-based (ACI 374.1)"))

    def _accept(self):
        kind = self.cmb_kind.currentText()
        try:
            kw = {"cycles": self.spin_cycles.value(), "positive_first": self.chk_pos.isChecked()}
            if kind == "Monotonic":
                kw["target"] = float(self.ed_target.text())
            elif kind == "Symmetric cycles":
                kw["amplitude"] = float(self.ed_amp.text())
            elif kind in ("Increasing amplitude", "One-sided cycles"):
                kw["amplitudes"] = lp.parse_list(self.ed_amps.text())
            else:
                kw["height"] = float(self.ed_height.text())
                kw["drifts_pct"] = lp.parse_list(self.ed_drifts.text())
            vals = lp.generate(kind, **kw)
        except (ValueError, KeyError):
            QMessageBox.warning(self, "Generate", "One of the entries is not a valid number.")
            return
        if not vals:
            QMessageBox.warning(self, "Generate", "The protocol is empty.")
            return
        self.values = vals
        self.accept()
