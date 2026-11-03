"""
Small chooser shown by Join Frames only when the selected frames don't all
share the same section/beta/offsets/etc. Lets the user pick which one of
the selected frames' properties the merged frame should inherit.
(End releases are handled separately/automatically — they always come
from whichever selected frame sits at each true outer end.)
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton
)

from app.ui.theme import apply_dialog_style

class SelectFramePropertiesDialog(QDialog):

    def __init__(self, frame_ids, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Join Frames — Mismatched Properties")
        apply_dialog_style(self)
        self.setMinimumWidth(360)

        self._frame_ids = list(frame_ids)
        self.chosen_id = self._frame_ids[0]

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        msg = QLabel(
            "The selected frames don't all share the same section, local axis "
            "angle, offsets, or rigid-zone factor.\n\n"
            "Choose which frame's properties the merged frame should keep "
            "(end releases are taken automatically from whichever frame is "
            "at each end)."
        )
        msg.setWordWrap(True)
        root.addWidget(msg)

        row = QHBoxLayout()
        row.addWidget(QLabel("Keep properties from:"))
        self.combo = QComboBox()
        for eid in self._frame_ids:
            el = model.elements.get(eid)
            label = getattr(el, 'label', None) or f"F{eid}"
            sec_name = getattr(getattr(el, 'section', None), 'name', '?')
            self.combo.addItem(f"{label}  (Section: {sec_name})", eid)
        row.addWidget(self.combo, 1)
        root.addLayout(row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(btn_ok)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        root.addLayout(btn_row)

    def _on_ok(self):
        self.chosen_id = self.combo.currentData()
        self.accept()
