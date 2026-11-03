"""
app/dialogs/hinge_dialog.py

Frame Hinge Properties -- definition + storage only.

Scope (intentional, see conversation with Ahmed 2026-09-25):
  - Hinge type is locked to "Fiber P-M2-M3" -- the only type supported today.
  - Fiber option is either "Default From Section" (fibers generated later
    from whatever Section the hinge ends up assigned to, pulling that
    section's ReinforcementData / Material / Mander confinement data --
    nothing computed or cached here) or "User Defined" (fibers are typed
    in by hand, row by row, in FiberLayoutDialog below -- still just data
    entry, no generation math, no validation against the section).
  - HingeProperty (core/properties.py) stores: name, hinge_type, behavior,
    fiber_option, hinge_length, hinge_length_relative, and -- only when
    fiber_option is "User Defined" -- the hand-entered fiber rows.
  - The section preview on the right is a UI convenience (lets you look
    at candidate sections while picking a hinge length). Only its section
    NAME is remembered (HingeProperty.preview_section) so the dialog reopens
    on it; the hinge is still not tied to that section.
  - Hinge ASSIGNMENT (attaching a HingeProperty to a frame at a location)
    and hinge RESULTS are both out of scope for this pass.
"""

import math
from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QComboBox, QDoubleSpinBox, QCheckBox,
    QRadioButton, QButtonGroup, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMessageBox, QWidget, QDialogButtonBox
)
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication
from core.opensees_port.os_capabilities import is_opensees
from app.ui.theme import COLORS, section_map_palette, on_theme_changed, off_theme_changed
from core.properties import (
    HingeProperty, compute_rebar_positions, RectangularSection,
    is_confined_concrete, ensure_unconfined_twin
)

def _draw_axis_arrow(painter, tail, head, label):
    """Small arrow from tail to head with a V-shaped head and a text label past the tip."""
    painter.drawLine(tail, head)
    angle = math.atan2(head.y() - tail.y(), head.x() - tail.x())
    barb = 6
    for offset in (150, -150):
        a = angle + math.radians(offset)
        barb_pt = QPointF(head.x() + barb * math.cos(a), head.y() + barb * math.sin(a))
        painter.drawLine(head, barb_pt)
    label_pt = QPointF(head.x() + 6 * math.cos(angle), head.y() + 6 * math.sin(angle) - 2)
    painter.drawText(label_pt, label)

class SectionPreviewWidget(QWidget):
    """
    Lightweight read-only preview of a frame Section's cross-section shape,
    with an optional fiber-dot overlay. Not tied to hinge fiber generation --
    just a visual aid while defining a hinge.

    The scale/center are locked to the SECTION SHAPE only, never the fiber
    points -- so typing a fiber coordinate way outside the section doesn't
    shrink or re-center the whole view. Fibers are just plotted at their
    real position against that fixed frame, even if that puts a dot outside
    the shape (or off the visible widget entirely). Only falls back to
    framing off the fiber points when there's no section chosen yet, so the
    preview isn't blank before you've picked one.
    """
    fiber_clicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.section = None
        self.fibers = []                                                           
        self.rebar_sizes = []                                                
        self.rebars = []                                                               
        self._hover_model_pt = None                                    
        self.selected_fiber_index = -1
        self.setMinimumSize(220, 220)
        self.setMouseTracking(True)
        self._apply_theme()

    def _apply_theme(self, *_):
        pal = section_map_palette()
        self.setStyleSheet(f"background-color: {pal['bg']}; border: 1px solid {COLORS['border']};")
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_theme()
        on_theme_changed(self._apply_theme)

    def hideEvent(self, event):
        off_theme_changed(self._apply_theme)
        super().hideEvent(event)

    def set_selected_fiber(self, index):
        self.selected_fiber_index = index
        self.update()

    def mousePressEvent(self, event):
        transform = self._compute_transform()
        if transform is not None and self.fibers:
            pos = event.position()
            min_dist = float('inf')
            best_idx = -1
                                                                 
            for i, f in enumerate(self.fibers):
                pt = self._to_px(f.get("coord3", 0.0), f.get("coord2", 0.0), transform)
                dist = math.hypot(pt.x() - pos.x(), pt.y() - pos.y())
                if dist < 6.0 and dist < min_dist:
                    min_dist = dist
                    best_idx = i

            if best_idx != -1:
                self.set_selected_fiber(best_idx)
                self.fiber_clicked.emit(best_idx)
                
        super().mousePressEvent(event)

    def set_section(self, section):
        self.section = section
        self._recompute_rebars()
        self.update()

    def set_fibers(self, fibers):
        self.fibers = fibers or []
        self.update()

    def set_rebar_sizes(self, rebar_sizes):
        self.rebar_sizes = rebar_sizes or []
        self._recompute_rebars()
        self.update()

    def _recompute_rebars(self):
        """Longitudinal rebar dots for whatever reinforcement is defined on
        the current section, purely a visual reference -- see
        core/properties.py:compute_rebar_positions()."""
        self.rebars = (
            compute_rebar_positions(self.section, self.rebar_sizes)
            if self.section is not None else []
        )

    def _compute_transform(self):
        """Returns (scale, cy, cz, cx_px, cy_px) or None if there's nothing to frame."""
                                                                       
        basis = []
        if self.section is not None:
            shape_coords = self.section.get_shape_coords()
            if shape_coords:
                basis.extend(shape_coords)
                
        basis.extend([(f.get("coord3", 0.0), f.get("coord2", 0.0)) for f in self.fibers])
        basis.extend([(y, z) for y, z, dia in self.rebars])
        
        if not basis:
            return None

        ys = [p[0] for p in basis]
        zs = [p[1] for p in basis]
        y_min, y_max = min(ys), max(ys)
        z_min, z_max = min(zs), max(zs)
        span_y = max(y_max - y_min, 1e-6)
        span_z = max(z_max - z_min, 1e-6)

        margin_sides = 24
        margin_top = 24
        margin_bottom = 60                                                    
        
        avail_w = self.width() - 2 * margin_sides
        avail_h = self.height() - margin_top - margin_bottom
        scale = min(avail_w / span_y, avail_h / span_z)

        cy = (y_min + y_max) / 2.0
        cz = (z_min + z_max) / 2.0
        
        cy_px = margin_top + (avail_h / 2.0)
        
        return scale, cy, cz, self.width() / 2.0, cy_px

    @staticmethod
    def _to_px(y, z, transform):
        scale, cy, cz, cx_px, cy_px = transform
                                                                                         
        return QPointF(cx_px + (y - cy) * scale, cy_px - (z - cz) * scale)

    @staticmethod
    def _to_model(px, py, transform):
        scale, cy, cz, cx_px, cy_px = transform
        return (px - cx_px) / scale + cy, (cy_px - py) / scale + cz

    def mouseMoveEvent(self, event):
        transform = self._compute_transform()
        pos = event.position()
        self._hover_model_pt = self._to_model(pos.x(), pos.y(), transform) if transform else None
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_model_pt = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pal = section_map_palette()
        text_col = QColor(pal["text"])
        axis_col = QColor(pal["axis"])
        grid_col = QColor(axis_col)
        grid_col.setAlpha(35)

        transform = self._compute_transform()
        if transform is None:
            painter.setPen(text_col)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No section selected")
            return

        origin_px = self._to_px(0.0, 0.0, transform)
        painter.setPen(QPen(grid_col, 1))
        painter.drawLine(QPointF(0, origin_px.y()), QPointF(self.width(), origin_px.y()))
        painter.drawLine(QPointF(origin_px.x(), 0), QPointF(origin_px.x(), self.height()))

        shape_coords = self.section.get_shape_coords() if self.section is not None else []
        if shape_coords:
            poly = QPolygonF([self._to_px(y, z, transform) for y, z in shape_coords])
            painter.setPen(QPen(QColor(pal["outline"]), 2))
            painter.setBrush(QBrush(QColor.fromRgbF(*pal["fill"])))
            painter.drawPolygon(poly)
            
            reinf = getattr(self.section, "reinforcement", None)
                                                                     
            if reinf is not None and getattr(self.section, "b", None) is not None:
                                         
                tie_dia = 0.01
                for r in self.rebar_sizes:
                    if r.get("id") == reinf.tie_bar_size:
                        tie_dia = r.get("diameter", 0.01)
                        break
                
                offset = reinf.clear_cover + (tie_dia / 2.0)
                core_b = self.section.b - 2 * offset
                core_h = self.section.h - 2 * offset
                
                if core_b > 0 and core_h > 0:
                    y_max, y_min = core_b / 2.0, -core_b / 2.0
                    z_max, z_min = core_h / 2.0, -core_h / 2.0
                    
                    tie_poly = QPolygonF([
                        self._to_px(y_max, z_max, transform),
                        self._to_px(y_min, z_max, transform),
                        self._to_px(y_min, z_min, transform),
                        self._to_px(y_max, z_min, transform)
                    ])
                    
                    tie_pen = QPen(QColor("#00c853"), 2, Qt.PenStyle.DashLine)
                    tie_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                    painter.setPen(tie_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPolygon(tie_poly)
                                           
        elif self.section is not None:
            painter.setPen(text_col)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No drawable shape\nfor this section")

        if self.rebars:
            painter.setPen(QPen(QColor("#000000"), 1))
            painter.setBrush(QBrush(QColor("#d81f1f")))
            scale = transform[0]
            for y, z, dia in self.rebars:
                pt = self._to_px(y, z, transform)
                r_px = max(2.0, (dia * scale) / 2.0)
                painter.drawEllipse(pt, r_px, r_px)

        if self.fibers:
            for i, f in enumerate(self.fibers):
                pt = self._to_px(f.get("coord3", 0.0), f.get("coord2", 0.0), transform)
                if i == self.selected_fiber_index:
                                                            
                    painter.setPen(QPen(QColor("#ffaa00"), 2))
                    painter.setBrush(QBrush(QColor("#ffaa00")))
                    painter.drawEllipse(pt, 5, 5)
                else:
                                    
                    painter.setPen(QPen(QColor("#170bc0"), 1))
                    painter.setBrush(QBrush(QColor("#170bc0")))
                    painter.drawEllipse(pt, 3, 3)

        painter.setPen(text_col)
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        caption = ""
        if self.section is not None:
            mat_label = ""
            if getattr(self.section, "material", None) is not None:
                mat_label = f"  ({self.section.material.mat_type})"
            caption = f"{self.section.name}{mat_label}"
        if self.rebars:
            caption = (caption + "  --  " if caption else "") + f"{len(self.rebars)} bar(s)"
        if self.fibers:
            caption = (caption + "  --  " if caption else "") + f"{len(self.fibers)} fiber(s)"
        if caption:
            painter.drawText(6, self.height() - 8, caption)

        if self._hover_model_pt is not None:
            y, z = self._hover_model_pt
            painter.setPen(text_col)
            painter.drawText(6, self.height() - 24, f"{y:.4f}, {z:.4f}")

        painter.setPen(QPen(axis_col, 2))
        arrow_len = 22
        corner_x = self.width() - 18 - arrow_len
        corner_y = self.height() - 18 - arrow_len
        origin = QPointF(corner_x, corner_y + arrow_len)
        _draw_axis_arrow(painter, origin, QPointF(corner_x, corner_y), "2")
        _draw_axis_arrow(painter, origin, QPointF(corner_x - arrow_len, corner_y + arrow_len), "3")

def generate_property_preserving_fibers(section, rebar_sizes, cover_material=None):
    """
    Property-preserving fiber mesh for a rectangular RC
    section: exact rebar fibers (tabulated bar areas), a 3x3 confined-
    core grid, and an 8-point unconfined-cover ring -- each piece sized/
    placed so its own total area and moments of inertia about the
    centroid exactly reproduce the corresponding continuous region's
    real properties (core net of rebar; cover as the full hollow ring,
    unconfined concrete carries no rebar in this model).

    Only supports RectangularSection with reinforcement.config ==
    "rectangular" (or no reinforcement at all -- see below). Caller is
    expected to have already checked the section type/config; this
    raises ValueError on a degenerate result (e.g. cover thicker than
    the section) rather than guessing.

    If the section has no reinforcement, or compute_rebar_positions()
    finds nothing to place (e.g. a beam-type ReinforcementData), Step A
    and the cover ring are skipped and offset=0, so the core equals the
    gross section and the 3x3 grid alone reproduces its full properties
    -- the same math, just with zero steel to net out.

    cover_material: material NAME for the 8-point cover ring. None keeps the
    section material (old behaviour); the hinge dialog passes the unconfined
    twin so cover concrete never gets the confined curve. Core fibers always
    use the section's own material; rebar fibers use the longitudinal bar material.

    Returns a list of {"area", "coord2", "coord3", "material"} dicts,
    coord2 = vertical (local axis 2), coord3 = horizontal (local axis
    3) -- same convention as everywhere else in this file.
    """
    b, h = section.b, section.h
    reinf = section.reinforcement

    rebars = compute_rebar_positions(section, rebar_sizes)                      

    def lookup_bar(bar_id, dia_fallback, area_fallback):
        for r in rebar_sizes or []:
            if r["id"] == bar_id:
                return r["diameter"], r["area"]
        return dia_fallback, area_fallback

    fibers = []
    sum_a = 0.0
    sum_a_y2 = 0.0
    sum_a_z2 = 0.0
    long_material = reinf.long_bar_material if reinf is not None else None

    if rebars:

        _, long_area = lookup_bar(reinf.long_bar_size, 0.02, math.pi * (0.02 / 2.0) ** 2)
        for y, z, dia in rebars:
            fibers.append({"area": long_area, "coord2": z, "coord3": y, "material": long_material})
            sum_a += long_area
            sum_a_y2 += long_area * y ** 2
            sum_a_z2 += long_area * z ** 2

        tie_dia, _ = lookup_bar(reinf.tie_bar_size, 0.01, 0.0)
        offset = reinf.clear_cover + (tie_dia / 2.0)
    else:
        offset = 0.0

    core_b = b - 2 * offset
    core_h = h - 2 * offset
    if core_b <= 0 or core_h <= 0:
        raise ValueError("Cover/tie offset leaves no room for a concrete core -- check clear cover and tie size.")

    a_core_gross = core_b * core_h
    a_net = a_core_gross - sum_a
    if a_net <= 0:
        raise ValueError("Rebar area exceeds the core's gross area -- check bar size/count and clear cover.")

    i33_core_gross = (core_h * core_b ** 3) / 12.0
    i22_core_gross = (core_b * core_h ** 3) / 12.0
    i33_net = i33_core_gross - sum_a_y2
    i22_net = i22_core_gross - sum_a_z2
    if i33_net <= 0 or i22_net <= 0:
        raise ValueError("Rebar layout leaves no net core inertia to distribute -- check bar positions/sizes.")

    y_coord = math.sqrt(i33_net / (0.6 * a_net))
    z_coord = math.sqrt(i22_net / (0.6 * a_net))

    core_material = section.material.name
    cover_material_name = cover_material or core_material

    for zc in (-z_coord, 0.0, z_coord):
        for yc in (-y_coord, 0.0, y_coord):
            area = (2.0 * a_net / 10.0) if (yc == 0.0 and zc == 0.0) else (a_net / 10.0)
            fibers.append({"area": area, "coord2": zc, "coord3": yc, "material": core_material})

    if offset > 0:
                                                                      
        a_cov = b * h - core_b * core_h
        i33_cov = (h * b ** 3) / 12.0 - i33_core_gross
        i22_cov = (b * h ** 3) / 12.0 - i22_core_gross

        a_side = h * offset / 2.0
        a_top = b * offset / 2.0
        a_corner = (a_cov - offset * (b + h)) / 4.0
        if a_corner <= 0:
            raise ValueError("Cover ring too thick to split into corner/edge fibers -- check clear cover and tie size.")

        yc = math.sqrt(i33_cov / (2.0 * a_side + 4.0 * a_corner))
        zc = math.sqrt(i22_cov / (2.0 * a_top + 4.0 * a_corner))

        cover_chunks = [
                                        
            (a_top, 0.0, zc),
            (a_top, 0.0, -zc),
            (a_side, -yc, 0.0),
            (a_side, yc, 0.0),
            (a_corner, yc, zc),
            (a_corner, -yc, zc),
            (a_corner, yc, -zc),
            (a_corner, -yc, -zc),
        ]
        for area, yc_pt, zc_pt in cover_chunks:
            fibers.append({"area": area, "coord2": zc_pt, "coord3": yc_pt, "material": cover_material_name})

    return fibers

class HingePropertyDialog(QDialog):
    """
    Define/Modify a single Frame Hinge Property.
    hinge_prop=None -> creating a new one (name auto-suggested).
    hinge_prop=<HingeProperty> -> editing that instance's values.
    """

    def __init__(self, model, parent=None, hinge_prop=None):
        super().__init__(parent)
        self.model = model
        self.editing_prop = hinge_prop                                     

        self.setWindowTitle("Frame Hinge Property Data")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)

        top_row = QHBoxLayout()
        root.addLayout(top_row)

        left_col = QVBoxLayout()
        top_row.addLayout(left_col, stretch=1)

        name_group = QGroupBox("Hinge Property Name")
        name_layout = QFormLayout(name_group)
        self.name_edit = QLineEdit()
        default_name = hinge_prop.name if hinge_prop else model.get_next_hinge_name()
        self.name_edit.setText(default_name)
        name_layout.addRow("Name:", self.name_edit)
        left_col.addWidget(name_group)

        type_group = QGroupBox("Hinge Type")
        type_layout = QVBoxLayout(type_group)

        behavior_row = QHBoxLayout()
        self.force_controlled_radio = QRadioButton("Force Controlled (Brittle)")
        self.deformation_controlled_radio = QRadioButton("Deformation Controlled (Ductile)")
        self.deformation_controlled_radio.setChecked(True)
        self.force_controlled_radio.toggled.connect(self._on_force_controlled_toggled)
        behavior_btn_group = QButtonGroup(self)
        behavior_btn_group.addButton(self.force_controlled_radio)
        behavior_btn_group.addButton(self.deformation_controlled_radio)
        behavior_row.addWidget(self.force_controlled_radio)
        behavior_row.addWidget(self.deformation_controlled_radio)
        type_layout.addLayout(behavior_row)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Fiber P-M2-M3")
        self.type_combo.setEnabled(False)
        self.type_combo.setToolTip(
            "Only Fiber P-M2-M3 hinges are supported right now.\n"
            "Other types (Axial P, Shear V2/V3, Moment M2/M3, the\n"
            "Interacting variants) may be added later."
        )
        type_layout.addWidget(self.type_combo)
        left_col.addWidget(type_group)

        fiber_group = QGroupBox("Fiber Definition Options")
        fiber_layout = QVBoxLayout(fiber_group)
        self.default_radio = QRadioButton("Default From Section")
        self.user_defined_radio = QRadioButton("User Defined")
        starting_option = hinge_prop.fiber_option if hinge_prop else "Default From Section"
        self.user_defined_radio.setChecked(starting_option == "User Defined")
        self.default_radio.setChecked(starting_option != "User Defined")
        fiber_btn_group = QButtonGroup(self)
        fiber_btn_group.addButton(self.default_radio)
        fiber_btn_group.addButton(self.user_defined_radio)

        default_row = QHBoxLayout()
        default_row.addWidget(self.default_radio)
        self.calculate_btn = QPushButton("Calculate")
        self.calculate_btn.setToolTip(
            "Generate a property-preserving fiber mesh (rebar + confined core\n"
            "+ unconfined cover) from the previewed section's own reinforcement,\n"
            "then switch to User Defined so you can review or hand-edit it."
        )
        self.calculate_btn.clicked.connect(self._on_calculate_fibers)
        default_row.addWidget(self.calculate_btn)
        default_row.addStretch()
        fiber_layout.addLayout(default_row)

        cover_row = QHBoxLayout()
        cover_row.addWidget(QLabel("Cover material:"))
        self.cover_combo = QComboBox()
        self.cover_combo.setToolTip(
            "Material for the unconfined cover fibers when Calculate runs.\n"
            "Auto: if the section's concrete is confined, an exact copy named\n"
            "'<material>_unconfined' (Mander type Unconfined) is created/refreshed\n"
            "and used. Or pick any concrete material yourself."
        )
        cover_row.addWidget(self.cover_combo, stretch=1)
        fiber_layout.addLayout(cover_row)
                                                                                   
        self._derived_snapshot = {
            n: m for n, m in self.model.materials.items() if getattr(m, "derived_from", "")
        }
        self._refresh_cover_combo()
        saved_cover = getattr(hinge_prop, "cover_material", "") if hinge_prop else ""
        if saved_cover:
            i = self.cover_combo.findData(saved_cover)
            if i >= 0:
                self.cover_combo.setCurrentIndex(i)

        fiber_layout.addWidget(self.user_defined_radio)

        self.fibers = [dict(f) for f in hinge_prop.fibers] if hinge_prop else []

        self.edit_fibers_btn = QPushButton(self._fiber_button_label())
        self.edit_fibers_btn.clicked.connect(self._on_edit_fibers)
        self.edit_fibers_btn.setEnabled(self.user_defined_radio.isChecked())
        self.user_defined_radio.toggled.connect(self._on_fiber_option_toggled)
        fiber_layout.addWidget(self.edit_fibers_btn)

        left_col.addWidget(fiber_group)

        length_group = QGroupBox("Hinge Length")
        length_layout = QFormLayout(length_group)
        self.length_spin = QDoubleSpinBox()
        self.length_spin.setDecimals(4)
        self.length_spin.setRange(0.0001, 100000.0)
        self.length_spin.setSingleStep(0.01)
        self.length_spin.setValue(hinge_prop.hinge_length if hinge_prop else 0.1)
        self.relative_check = QCheckBox("Relative Length")
        self.relative_check.setChecked(
            hinge_prop.hinge_length_relative if hinge_prop else True
        )
        self.relative_check.setToolTip(
            "Checked: length is a fraction (0-1) of the assigned frame's length.\n"
            "Unchecked: length is an absolute value in model length units."
        )
        self.relative_check.toggled.connect(self._on_relative_toggled)
        length_layout.addRow("Length:", self.length_spin)
        length_layout.addRow("", self.relative_check)
        left_col.addWidget(length_group)
        self._on_relative_toggled(self.relative_check.isChecked())

        left_col.addStretch()

        preview_group = QGroupBox("Preview Section")
        preview_layout = QVBoxLayout(preview_group)
        self.section_combo = QComboBox()
        self.section_combo.addItem("(none)")
        for sec_name in sorted(model.sections.keys()):
            self.section_combo.addItem(sec_name)
        self.section_combo.currentTextChanged.connect(self._on_section_changed)
        preview_layout.addWidget(self.section_combo)

        self.preview_widget = SectionPreviewWidget()
        self.preview_widget.set_rebar_sizes(getattr(model, "rebar_sizes", []))
        preview_layout.addWidget(self.preview_widget, stretch=1)
        top_row.addWidget(preview_group, stretch=1)

        saved_sec = getattr(hinge_prop, "preview_section", "") if hinge_prop else ""
        idx = self.section_combo.findText(saved_sec) if saved_sec else -1
        if idx > 0:
            self.section_combo.setCurrentIndex(idx)

        self._on_fiber_option_toggled(self.user_defined_radio.isChecked())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_force_controlled_toggled(self, checked):

        if checked:
            self.deformation_controlled_radio.setChecked(True)
            QMessageBox.warning(
                self, "Hinge Behavior",
                "Hinge behavior was switched to Deformation Controlled.\n"
                "Force Controlled behavior is not allowed for the specified hinge type."
            )

    def _on_relative_toggled(self, checked):
        if checked:
            self.length_spin.setRange(0.0001, 1.0)
            if self.length_spin.value() > 1.0:
                self.length_spin.setValue(0.1)
        else:
            self.length_spin.setRange(0.0001, 100000.0)

    def _on_section_changed(self, name):
        section = self.model.sections.get(name)
        self.preview_widget.set_section(section)

    def _refresh_cover_combo(self):
        keep = self.cover_combo.currentData() if self.cover_combo.count() else None
        self.cover_combo.clear()
        self.cover_combo.addItem("Auto (unconfined copy)", None)
        for name in sorted(self.model.materials.keys()):
            if getattr(self.model.materials[name], "mat_type", "").lower() == "concrete":
                self.cover_combo.addItem(name, name)
        if keep is not None:
            i = self.cover_combo.findData(keep)
            if i >= 0:
                self.cover_combo.setCurrentIndex(i)

    def _resolve_cover_material(self, section):
        """Cover-ring material NAME for Calculate (None = same as section material)."""
        chosen = self.cover_combo.currentData()
        if chosen is not None:
            return chosen

        mat = section.material
        has_cover_ring = bool(compute_rebar_positions(section, self.model.rebar_sizes))
        if not has_cover_ring or getattr(mat, "mat_type", "").lower() != "concrete":
            return None

        if not is_confined_concrete(mat):
            QMessageBox.warning(
                self, "No Confined Material Detected",
                f"No confined (Mander) behavior is defined on '{mat.name}'.\n"
                f"Applying what is detected: core and cover fibers both use '{mat.name}'."
            )
            return None

        twin, _status = ensure_unconfined_twin(self.model, mat)                                  
        self._refresh_cover_combo()
        return twin.name

    def reject(self):
        for n in [n for n, m in self.model.materials.items()
                  if getattr(m, "derived_from", "") and n not in self._derived_snapshot]:
            del self.model.materials[n]
        self.model.materials.update(self._derived_snapshot)
        super().reject()

    def _on_calculate_fibers(self):
        sec_name = self.section_combo.currentText()
        section = self.model.sections.get(sec_name)
        if section is None:
            QMessageBox.warning(
                self, "No Section Selected",
                "Pick a section in the preview panel first -- the fiber\n"
                "mesh is generated from that section's own shape and\n"
                "reinforcement."
            )
            return

        if not isinstance(section, RectangularSection) or (
            section.reinforcement is not None and section.reinforcement.config != "rectangular"
        ):
            QMessageBox.warning(
                self, "Unsupported Section",
                "Automatic fiber generation currently only supports\n"
                "rectangular sections with rectangular (or no) reinforcement."
            )
            return

        try:
            cover_name = self._resolve_cover_material(section)
            fibers = generate_property_preserving_fibers(
                section, self.model.rebar_sizes, cover_material=cover_name
            )
        except ValueError as e:
            QMessageBox.critical(self, "Fiber Generation Failed", str(e))
            return

        self.fibers = fibers
        self.user_defined_radio.setChecked(True)
        self.edit_fibers_btn.setText(self._fiber_button_label())
        self.preview_widget.set_fibers(self.fibers)

    def _fiber_button_label(self):
        count = len(self.fibers)
        return f"Edit Fiber Table... ({count} defined)" if count else "Edit Fiber Table..."

    def _on_fiber_option_toggled(self, user_defined_checked):
        self.edit_fibers_btn.setEnabled(user_defined_checked)
        self.preview_widget.set_fibers(self.fibers if user_defined_checked else [])

    def _on_edit_fibers(self):
        dlg = FiberLayoutDialog(self.model, self.preview_widget.section, self.fibers, self)
        if dlg.exec():
            self.fibers = dlg.fibers
            self.edit_fibers_btn.setText(self._fiber_button_label())
            if self.user_defined_radio.isChecked():
                self.preview_widget.set_fibers(self.fibers)

    def _on_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a hinge property name.")
            return

        existing = self.model.hinge_properties.get(name)
        is_rename = self.editing_prop is not None and self.editing_prop.name != name
        if existing is not None and (self.editing_prop is None or is_rename):
            QMessageBox.warning(
                self, "Duplicate Name",
                f"A hinge property named '{name}' already exists."
            )
            return

        fiber_option = "User Defined" if self.user_defined_radio.isChecked() else "Default From Section"
                                                                                        
        fibers = list(self.fibers)
        if not fibers:
            reply = QMessageBox.question(
                self, "No Fibers Calculated",
                "This hinge has no fibers yet. The solver skips hinges without fibers\n"
                "(it won't regenerate them from the section), so it would do nothing.\n\n"
                "Pick a preview section and press Calculate first.\n\nSave it anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        cover_material = self.cover_combo.currentData() or ""
        sec_text = self.section_combo.currentText()
        preview_section = sec_text if sec_text in self.model.sections else ""

        if self.editing_prop is not None:
                                                                          
            if is_rename:
                del self.model.hinge_properties[self.editing_prop.name]
            self.editing_prop.name = name
            self.editing_prop.behavior = "Deformation Controlled"
            self.editing_prop.fiber_option = fiber_option
            self.editing_prop.fibers = fibers
            self.editing_prop.hinge_length = self.length_spin.value()
            self.editing_prop.hinge_length_relative = self.relative_check.isChecked()
            self.editing_prop.preview_section = preview_section
            self.editing_prop.cover_material = cover_material
            self.model.add_hinge_property(self.editing_prop)
            self.result_prop = self.editing_prop
        else:
            new_prop = HingeProperty(
                name=name,
                hinge_type="Fiber P-M2-M3",
                behavior="Deformation Controlled",
                fiber_option=fiber_option,
                fibers=fibers,
                hinge_length=self.length_spin.value(),
                hinge_length_relative=self.relative_check.isChecked(),
                preview_section=preview_section,
                cover_material=cover_material,
            )
            self.model.add_hinge_property(new_prop)
            self.result_prop = new_prop

        self.accept()

class CopyableFiberTableWidget(QTableWidget):
    """QTableWidget that supports Ctrl+C to copy data from embedded cell widgets."""
    
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection_to_clipboard()
        else:
            super().keyPressEvent(event)

    def copy_selection_to_clipboard(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return

        rows = sorted(set(i.row() for i in indexes))
        cols = sorted(set(i.column() for i in indexes))
        selected_set = set((i.row(), i.column()) for i in indexes)

        lines = []

        header_item = self.horizontalHeaderItem
        lines.append("\t".join(
            (header_item(c).text() if header_item(c) else "") for c in cols
        ))

        for r in rows:
            line_vals = []
            for c in cols:
                if (r, c) in selected_set:
                    widget = self.cellWidget(r, c)
                    if isinstance(widget, QDoubleSpinBox):
                        line_vals.append(str(widget.value()))
                    elif isinstance(widget, QComboBox):
                        line_vals.append(widget.currentText())
                    else:
                        line_vals.append("")
                else:
                    line_vals.append("")
            lines.append("\t".join(line_vals))

        QApplication.clipboard().setText("\n".join(lines))

class FiberLayoutDialog(QDialog):
    """
    Hand-entered fiber table for a User Defined hinge. Each row is one
    fiber: cross-sectional area, its position in the section's local
    2-3 axes, and which of the model's existing materials it's made of.
    Pure data entry -- nothing here generates, validates, or snaps
    fibers to the section; the preview overlay is just a visual check.
    """

    COLUMNS = ["Area", "Coord 3", "Coord 2", "Material"]

    def __init__(self, model, preview_section, fibers, parent=None):
        super().__init__(parent)
        self.model = model
        self.preview_section = preview_section
        self.fibers = [dict(f) for f in fibers]

        self.setWindowTitle("Fiber Table")
        self.setMinimumSize(640, 420)

        root = QHBoxLayout(self)

        left = QVBoxLayout()
        root.addLayout(left, stretch=2)

        left.addWidget(QLabel(
            "Each row is one fiber: area, its position in the section's\n"
            "local 2-3 axes, and the material it's made of."
        ))

        self.table = CopyableFiberTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        left.addWidget(self.table)

        row_btns = QHBoxLayout()
        add_row_btn = QPushButton("Add Fiber")
        add_row_btn.clicked.connect(self._on_add_row)
        remove_row_btn = QPushButton("Remove Selected")
        remove_row_btn.clicked.connect(self._on_remove_row)
        row_btns.addWidget(add_row_btn)
        row_btns.addWidget(remove_row_btn)
        row_btns.addStretch()
        left.addLayout(row_btns)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        left.addWidget(buttons)

        right = QVBoxLayout()
        root.addLayout(right, stretch=1)
        right.addWidget(QLabel("Preview"))
        self.preview_widget = SectionPreviewWidget()
        self.preview_widget.set_rebar_sizes(getattr(model, "rebar_sizes", []))
        self.preview_widget.set_section(self.preview_section)
        right.addWidget(self.preview_widget, stretch=1)

        for f in self.fibers:
            self._add_row_widgets(f)
        self._refresh_preview()

        self.table.currentCellChanged.connect(self._on_table_cell_changed)
        self.preview_widget.fiber_clicked.connect(self._on_preview_fiber_clicked)

    def _material_names(self):
        return sorted(self.model.materials.keys())

    def _on_table_cell_changed(self, current_row, current_col, prev_row, prev_col):
        """Highlight the corresponding fiber in the preview when clicking a table row."""
        self.preview_widget.set_selected_fiber(current_row)

    def _on_preview_fiber_clicked(self, index):
        """Select the corresponding table row when clicking a fiber in the preview."""
        if 0 <= index < self.table.rowCount():
            self.table.selectRow(index)

    def _add_row_widgets(self, fiber):
        row = self.table.rowCount()
        self.table.insertRow(row)

        area_spin = QDoubleSpinBox()
        area_spin.setDecimals(6)
        area_spin.setRange(0.0, 1.0e6)
        area_spin.setValue(fiber.get("area", 0.0))
        area_spin.valueChanged.connect(self._refresh_preview)
        self.table.setCellWidget(row, 0, area_spin)

        c3_spin = QDoubleSpinBox()
        c3_spin.setDecimals(6)
        c3_spin.setRange(-1.0e6, 1.0e6)
        c3_spin.setValue(fiber.get("coord3", 0.0))
        c3_spin.valueChanged.connect(self._refresh_preview)
        self.table.setCellWidget(row, 1, c3_spin)

        c2_spin = QDoubleSpinBox()
        c2_spin.setDecimals(6)
        c2_spin.setRange(-1.0e6, 1.0e6)
        c2_spin.setValue(fiber.get("coord2", 0.0))
        c2_spin.valueChanged.connect(self._refresh_preview)
        self.table.setCellWidget(row, 2, c2_spin)

        mat_combo = QComboBox()
        names = self._material_names()
        mat_combo.addItems(names)
        wanted = fiber.get("material", "")
        if wanted in names:
            mat_combo.setCurrentText(wanted)
        self.table.setCellWidget(row, 3, mat_combo)

    def _on_add_row(self):
        names = self._material_names()
        default_material = names[0] if names else ""
        self._add_row_widgets({"area": 0.0, "coord2": 0.0, "coord3": 0.0, "material": default_material})
        self._refresh_preview()

    def _on_remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._refresh_preview()

    def _collect_fibers(self):
        rows = []
        for row in range(self.table.rowCount()):
            rows.append({
                "area": self.table.cellWidget(row, 0).value(),
                "coord3": self.table.cellWidget(row, 1).value(),                          
                "coord2": self.table.cellWidget(row, 2).value(),                          
                "material": self.table.cellWidget(row, 3).currentText(),
            })
        return rows

    def _refresh_preview(self, *_):
        self.preview_widget.set_fibers(self._collect_fibers())

    def _on_accept(self):
        self.fibers = self._collect_fibers()
        self.accept()

class HingePropertyManagerDialog(QDialog):
    """
    "Define Frame Hinge Properties" list manager.
    
    """

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Define Frame Hinge Properties")
        self.setMinimumSize(560, 380)

        root = QHBoxLayout(self)

        left = QVBoxLayout()
        root.addLayout(left, stretch=1)

        left.addWidget(QLabel("Defined Hinge Properties"))
        if is_opensees(model):
            note = QLabel("OpenSees does not use frame hinge properties - its fibers come from each "
                          "section's reinforcement. Switch the Analysis Engine to Native to edit hinges.")
            note.setWordWrap(True)
            left.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Length"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_modify)
        left.addWidget(self.table)

        right = QVBoxLayout()
        root.addLayout(right)
        right.addWidget(QLabel("Click to:"))

        add_btn = QPushButton("Add New Property...")
        add_btn.clicked.connect(self._on_add)
        right.addWidget(add_btn)

        modify_btn = QPushButton("Modify/Show Property...")
        modify_btn.clicked.connect(self._on_modify)
        right.addWidget(modify_btn)

        delete_btn = QPushButton("Delete Property")
        delete_btn.clicked.connect(self._on_delete)
        right.addWidget(delete_btn)

        right.addStretch()

        close_btn = QPushButton("OK")
        close_btn.clicked.connect(self.accept)
        right.addWidget(close_btn)
        if is_opensees(model):
            for _w in (self.table, add_btn, modify_btn, delete_btn):
                _w.setEnabled(False)
                _w.setToolTip("Not used while the Analysis Engine is OpenSees.")

        self._refresh_table()

    def _refresh_table(self):
        self.table.setRowCount(0)
        for hp in sorted(self.model.hinge_properties.values(), key=lambda h: h.name):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(hp.name))
            self.table.setItem(row, 1, QTableWidgetItem(hp.hinge_type))
            length_str = f"{hp.hinge_length:g}" + (" (rel)" if hp.hinge_length_relative else "")
            self.table.setItem(row, 2, QTableWidgetItem(length_str))

    def _selected_hinge(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        name = self.table.item(row, 0).text()
        return self.model.hinge_properties.get(name)

    def _on_add(self):
        dlg = HingePropertyDialog(self.model, self)
        if dlg.exec():
            self._refresh_table()

    def _on_modify(self):
        hp = self._selected_hinge()
        if hp is None:
            QMessageBox.information(self, "No Selection", "Select a hinge property to modify first.")
            return
        dlg = HingePropertyDialog(self.model, self, hinge_prop=hp)
        if dlg.exec():
            self._refresh_table()

    def _on_delete(self):
        hp = self._selected_hinge()
        if hp is None:
            QMessageBox.information(self, "No Selection", "Select a hinge property to delete first.")
            return
        confirm = QMessageBox.question(
            self, "Delete Hinge Property",
            f"Delete hinge property '{hp.name}'?"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            del self.model.hinge_properties[hp.name]
            self._refresh_table()
