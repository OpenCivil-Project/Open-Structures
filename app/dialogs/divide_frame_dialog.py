"""
Divide Selected Frames dialog.

  - Divide into Specified Number of Frames (Number of Frames, Last/First Length Ratio)
  - Break at Intersections with Selected Joints and Straight Frames
    (Area Edges / Solid Edges are not supported in this version — this
    model has no solid elements, and area-edge intersection wasn't
    implemented; see core/model.py divide_frame_at_intersections)
  - Divide at Specified Distance from I-end of Frame (Distance Type, Distance)
  - Divide at Intersection with a Coordinate Plane (Coordinate Plane, Intersection with Plane at)
  - Divide at Intersection with Visible Grid Planes in the Current Coordinate System

Usage (see main.py on_edit_divide_frames / on_divide_frame_apply):

    dlg = DivideFrameDialog(self)
    dlg.signal_apply.connect(self.on_divide_frame_apply)
    dlg.show()

    # in the handler:
    mode, kwargs = dlg.get_divide_spec()
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QRadioButton, QButtonGroup, QLabel, QComboBox, QSpinBox,
    QDoubleSpinBox, QPushButton, QWidget
)

from app.ui.theme import apply_dialog_style

class DivideFrameDialog(QDialog):

    signal_apply = pyqtSignal()

    MODE_NUMBER = "number"
    MODE_INTERSECTIONS = "intersections"
    MODE_DISTANCE = "distance"
    MODE_COORD_PLANE = "coord_plane"
    MODE_GRID_PLANES = "grid_planes"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Divide Selected Frames")
        apply_dialog_style(self)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        group = QGroupBox("Divide Options for Selected Straight Frame Objects")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnMinimumWidth(1, 130)

        self.radio_group = QButtonGroup(self)

        row = 0

        self.rb_number = QRadioButton("Divide into Specified Number of Frames")
        self.radio_group.addButton(self.rb_number)
        grid.addWidget(self.rb_number, row, 0, 1, 2)
        row += 1

        grid.addWidget(self._indented("Number of Frames"), row, 0)
        self.spin_num_frames = QSpinBox()
        self.spin_num_frames.setRange(2, 999)
        self.spin_num_frames.setValue(2)
        grid.addWidget(self.spin_num_frames, row, 1)
        row += 1

        grid.addWidget(self._indented("Last/First Length Ratio"), row, 0)
        self.spin_ratio = QDoubleSpinBox()
        self.spin_ratio.setDecimals(4)
        self.spin_ratio.setRange(0.0001, 1000.0)
        self.spin_ratio.setValue(1.0)
        grid.addWidget(self.spin_ratio, row, 1)
        row += 1

        self.rb_intersections = QRadioButton(
            "Break at Intersections with Selected Joints and Straight Frames"
        )
        self.radio_group.addButton(self.rb_intersections)
        grid.addWidget(self.rb_intersections, row, 0, 1, 2)
        row += 1

        note = QLabel(
            "Uses any other currently selected joints/frames as break points.\n"
            "Area Edges and Solid Edges are not supported in this version."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #777777; font-size: 8pt;")
        grid.addWidget(note, row, 0, 1, 2)
        row += 1

        self.rb_distance = QRadioButton("Divide at Specified Distance from I-end of Frame")
        self.radio_group.addButton(self.rb_distance)
        grid.addWidget(self.rb_distance, row, 0, 1, 2)
        row += 1

        grid.addWidget(self._indented("Distance Type"), row, 0)
        self.combo_distance_type = QComboBox()
        self.combo_distance_type.addItems(["Relative", "Absolute"])
        grid.addWidget(self.combo_distance_type, row, 1)
        row += 1

        grid.addWidget(self._indented("Distance"), row, 0)
        self.spin_distance = QDoubleSpinBox()
        self.spin_distance.setDecimals(4)
        self.spin_distance.setRange(0.0001, 1000000.0)
        self.spin_distance.setValue(0.5)
        grid.addWidget(self.spin_distance, row, 1)
        row += 1

        self.rb_coord_plane = QRadioButton("Divide at Intersection with a Coordinate Plane in the Current Coordinate System")
        self.radio_group.addButton(self.rb_coord_plane)
        grid.addWidget(self.rb_coord_plane, row, 0, 1, 2)
        row += 1

        grid.addWidget(self._indented("Coordinate Plane"), row, 0)
        self.combo_plane = QComboBox()
        self.combo_plane.addItems(["XY", "YZ", "XZ"])
        grid.addWidget(self.combo_plane, row, 1)
        row += 1

        grid.addWidget(self._indented("Intersection with Plane at"), row, 0)
        self.spin_plane_coord = QDoubleSpinBox()
        self.spin_plane_coord.setDecimals(4)
        self.spin_plane_coord.setRange(-1000000.0, 1000000.0)
        self.spin_plane_coord.setValue(0.0)
        grid.addWidget(self.spin_plane_coord, row, 1)
        row += 1

        self.rb_grid_planes = QRadioButton("Divide at Intersection with Visible Grid Planes in the Current Coordinate System")
        self.radio_group.addButton(self.rb_grid_planes)
        grid.addWidget(self.rb_grid_planes, row, 0, 1, 2)
        row += 1

        root.addWidget(group)

        self._number_widgets = [self.spin_num_frames, self.spin_ratio]
        self._distance_widgets = [self.combo_distance_type, self.spin_distance]
        self._plane_widgets = [self.combo_plane, self.spin_plane_coord]

        self.rb_number.toggled.connect(self._update_enabled_state)
        self.rb_intersections.toggled.connect(self._update_enabled_state)
        self.rb_distance.toggled.connect(self._update_enabled_state)
        self.rb_coord_plane.toggled.connect(self._update_enabled_state)
        self.rb_grid_planes.toggled.connect(self._update_enabled_state)

        self.rb_number.setChecked(True)
        self._update_enabled_state()

        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        btn_reset = QPushButton("Reset Form to Default Values")
        btn_reset.setObjectName("secondary")
        btn_reset.clicked.connect(self._reset_defaults)
        reset_row.addWidget(btn_reset)
        reset_row.addStretch(1)
        root.addLayout(reset_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(self.btn_ok)

        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("secondary")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)

        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setObjectName("secondary")
        self.btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(self.btn_apply)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

    def _indented(self, text):
        lbl = QLabel("      " + text)
        return lbl

    def _update_enabled_state(self):
        for w in self._number_widgets:
            w.setEnabled(self.rb_number.isChecked())
        for w in self._distance_widgets:
            w.setEnabled(self.rb_distance.isChecked())
        for w in self._plane_widgets:
            w.setEnabled(self.rb_coord_plane.isChecked())

    def _reset_defaults(self):
        self.rb_number.setChecked(True)
        self.spin_num_frames.setValue(2)
        self.spin_ratio.setValue(1.0)
        self.combo_distance_type.setCurrentIndex(0)
        self.spin_distance.setValue(0.5)
        self.combo_plane.setCurrentIndex(0)
        self.spin_plane_coord.setValue(0.0)

    def _on_apply(self):
        self.signal_apply.emit()

    def _on_ok(self):
        self.signal_apply.emit()
        self.close()

    def get_divide_spec(self):
        """
        Returns (mode, kwargs) describing the currently selected divide
        option, ready to hand to the matching StructuralModel.divide_frame_*
        method (mode maps 1:1 to the method name suffix).
        """
        if self.rb_number.isChecked():
            return self.MODE_NUMBER, {
                "num_frames": self.spin_num_frames.value(),
                "last_first_ratio": self.spin_ratio.value(),
            }
        if self.rb_intersections.isChecked():
            return self.MODE_INTERSECTIONS, {}
        if self.rb_distance.isChecked():
            return self.MODE_DISTANCE, {
                "distance": self.spin_distance.value(),
                "is_relative": (self.combo_distance_type.currentText() == "Relative"),
            }
        if self.rb_coord_plane.isChecked():
            return self.MODE_COORD_PLANE, {
                "plane": self.combo_plane.currentText(),
                "coordinate": self.spin_plane_coord.value(),
            }
        return self.MODE_GRID_PLANES, {}
