"""
os_model_panel.py   (put next to material_dialog.py, e.g. app/dialogs/)

Catalog-driven "OpenSees material model" picker.  The combo and every parameter field are
generated from core/opensees_port/os_materials.py, so adding a model to the catalog adds it
here automatically -- no dialog edits.

    panel = OsModelPanel("concrete")            # or "steel"
    panel.set_state("Concrete02", {"lam": 0.1}, rupture=False)
    model, params, rupture = panel.get_state()  # params only holds fields the user actually filled in

Blank numeric field = "auto" (derived from the material's own curve, see each model's tooltip).
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QCheckBox,
                             QLabel, QPushButton)
from PyQt6.QtCore import pyqtSignal

from core.opensees_port import os_materials as osm

class OsModelPanel(QWidget):
    preview_requested = pyqtSignal()
    model_changed = pyqtSignal()

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind                                                         
        self._catalog = osm.models_for(kind)
        self._fields = {}                                                 
        self._shown = None
        self._saved = {}                                                                                                   

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.combo = QComboBox()
        for name, entry in self._catalog.items():
            self.combo.addItem(entry["label"], name)
        root.addWidget(self.combo)

        self.lbl_tip = QLabel("")
        self.lbl_tip.setWordWrap(True)
        root.addWidget(self.lbl_tip)

        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.form_host)

        self.chk_rupture = None
        if kind == "steel":
            self.chk_rupture = QCheckBox("Bar rupture at \u00b1\u03b5_su  (MinMax wrapper)")
            self.chk_rupture.setToolTip("Wraps the steel in OpenSees MinMax: stress drops to zero beyond +/- eps_su "
                                        "(tension and compression). Off = bars never fail.")
            root.addWidget(self.chk_rupture)

        self.btn_preview = QPushButton("Preview OpenSees response...")
        self.btn_preview.setToolTip("Runs a cyclic strain history on this single material in OpenSees and plots "
                                    "stress-strain, so you can check the model before running a structure.")
        self.btn_preview.clicked.connect(self.preview_requested.emit)
        root.addWidget(self.btn_preview)

        self.combo.currentIndexChanged.connect(self._on_model_changed)
        self._rebuild()

    def current_model(self):
        return self.combo.currentData()

    def set_state(self, model, params=None, rupture=False):
        idx = self.combo.findData(model)
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo.blockSignals(False)
        self._saved = {self.current_model(): dict(params or {})}
        self._rebuild(self._saved[self.current_model()])
        if self.chk_rupture is not None:
            self.chk_rupture.setChecked(bool(rupture))

    def get_state(self):
        return (self.current_model(), self._collect(),
                bool(self.chk_rupture.isChecked()) if self.chk_rupture is not None else False)

    def set_os_enabled(self, on):
        self.setEnabled(bool(on))

    def _on_model_changed(self, *_):
        self._saved[self._shown] = self._collect(self._shown)                                                        
        self._rebuild(self._saved.get(self.current_model(), {}))
        self.model_changed.emit()

    def _collect(self, model=None):
        out = {}
        model = model or self._shown
        for key, w in self._fields.items():
            spec = next(s for s in self._catalog[model]["params"] if s["key"] == key)
            if spec["kind"] == "bool":
                out[key] = w.isChecked()
            elif spec["kind"].startswith("choice:"):
                out[key] = w.currentText()
            else:
                txt = w.text().strip()
                if txt:
                    try:
                        out[key] = float(txt)
                    except ValueError:
                        pass                                                               
        return out

    def _rebuild(self, values=None):
        values = values or {}
                                                             
        while self.form.rowCount():
            self.form.removeRow(0)
        self._fields = {}
        self._shown = self.current_model()
        entry = self._catalog[self.current_model()]
        self.lbl_tip.setText(entry["tip"])
        for spec in entry["params"]:
            kind, key = spec["kind"], spec["key"]
            val = values.get(key, None)
            if kind == "bool":
                w = QCheckBox()
                w.setChecked(bool(val if val is not None else spec["default"]))
            elif kind.startswith("choice:"):
                w = QComboBox()
                w.addItems(kind.split(":", 1)[1].split(","))
                cur = val if val is not None else spec["default"]
                w.setCurrentIndex(max(0, w.findText(str(cur))))
            else:
                w = QLineEdit()
                if spec["default"] is None:
                    w.setPlaceholderText("auto")
                else:
                    w.setPlaceholderText(f"{spec['default']:g}  (default)")
                if val is not None:
                    w.setText(f"{val:g}")
            w.setToolTip(spec["tip"] or spec["label"])
            self._fields[key] = w
            self.form.addRow(spec["label"], w)
        self.form_host.setVisible(bool(entry["params"]))

