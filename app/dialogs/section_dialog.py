import os
import pandas as pd                                                                     
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QListWidget, QPushButton, QFormLayout, QLineEdit, 
                             QDoubleSpinBox, QComboBox, QColorDialog, QMessageBox,
                             QGroupBox, QGridLayout, QWidget, QFrame, QStackedWidget,
                             QFileDialog)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QPolygonF
from core.units import unit_registry
from core.properties import (RectangularSection, ISection, Material, 
                             GeneralSection, CircularSection, 
                             PipeSection, TubeSection, TrapezoidalSection,
                             ArbitrarySection)
from app.section_designer.section_designer_dialog import SectionDesignerDialog
from core.integrity_checks import check_section_in_use
from app.dialogs.section_manager_dialog import ShapeCard, AddFrameSectionPropertyDialog
from app.ui.theme import apply_dialog_style

# Length scales for local dialog unit conversion
LENGTH_SCALES = {
    "m":  1.0,
    "cm": 100.0,
    "mm": 1_000.0,
    "ft": 3.28084,
    "in": 39.3701,
}

class SmartDoubleInput(QLineEdit):
    """A unit-aware line edit that handles unit suffixes and scientific notation."""
    def __init__(self, val=0.0, prop_type="length", current_unit="m", parent=None):
        super().__init__(parent)
        self.setProperty("prop_type", prop_type)
        self.unit = current_unit
        self._value = val
        self.editingFinished.connect(self._sync_text)
        self._render_text()
        
    def _get_suffix(self) -> str:
        prop = self.property("prop_type")
        if prop == "area": return f" {self.unit}²"
        if prop == "inertia": return f" {self.unit}⁴"
        if prop == "length": return f" {self.unit}"
        return ""

    def value(self) -> float:
        """Strips the suffix to parse the clean number from user input."""
        txt = self.text().replace(self._get_suffix(), "").strip()
        try:
            self._value = float(txt)
        except ValueError:
            pass
        return self._value

    def setValue(self, val: float):
        """Programmatically sets the value without re-reading the UI text."""
        self._value = val
        self._render_text()

    def setUnit(self, new_unit: str):
        """Updates the unit suffix and re-renders."""
        self.unit = new_unit
        self._render_text()

    def _sync_text(self):
        """Called when the user finishes typing."""
        self.value()
        self._render_text()

    def _render_text(self):
        v = self._value
        if abs(v) > 0 and (abs(v) < 1e-3 or abs(v) > 1e4):
            txt = f"{v:.4e}"
        else:
            txt = f"{v:.4f}"
        self.setText(txt + self._get_suffix())


class AISCSelectionDialog(QDialog):
    """Dialog to select a specific shape from the loaded AISC list."""
    def __init__(self, shape_list, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Select AISC Section")
        self.resize(300, 500)
        self.selected_row = None
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Available Metric W-Shapes:"))
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search (e.g., W1100...)")
        self.search_box.textChanged.connect(self.filter_list)
        layout.addWidget(self.search_box)

        self.list_widget = QListWidget()
        self.shape_data = shape_list                       
        
        self.list_items = []
        for item in shape_list:
            name = item['name']
            self.list_widget.addItem(name)
            self.list_items.append(name)
            
        layout.addWidget(self.list_widget)
        
        btns = QHBoxLayout()
        btn_ok = QPushButton("Import")
        btn_ok.clicked.connect(self.accept_selection)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok); btns.addWidget(btn_cancel)
        layout.addLayout(btns)

    def filter_list(self, text):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def accept_selection(self):
        row = self.list_widget.currentRow()
        if row < 0: return
        selected_text = self.list_widget.currentItem().text()
        
        for data in self.shape_data:
            if data['name'] == selected_text:
                self.selected_row = data
                break
        
        self.accept()

class SectionPreviewWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 200)
        self.setStyleSheet("background-color: white; border: 1px solid #999;")
        self.params = {"type": "rect", "b": 0.3, "h": 0.5, "color": (0.7,0.7,0.7)}

    def update_params(self, params):
        self.params = params
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w/2, h/2
        
        painter.setPen(QPen(QColor(220, 220, 220), 1))
        for i in range(0, w, 20): painter.drawLine(i, 0, i, h)
        for i in range(0, h, 20): painter.drawLine(0, i, w, i)
        
        origin_x = w - 15                                           
        origin_y = h - 10
        axis_len = 35

        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        
        painter.drawLine(origin_x, origin_y, origin_x - axis_len, origin_y)
                         
        painter.drawLine(origin_x - axis_len, origin_y, origin_x - axis_len + 5, origin_y - 3)
        painter.drawLine(origin_x - axis_len, origin_y, origin_x - axis_len + 5, origin_y + 3)
        
        painter.drawLine(origin_x, origin_y, origin_x, origin_y - axis_len)
                         
        painter.drawLine(origin_x, origin_y - axis_len, origin_x - 3, origin_y - axis_len + 5)
        painter.drawLine(origin_x, origin_y - axis_len, origin_x + 3, origin_y - axis_len + 5)

        font = painter.font()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        
        painter.drawText(origin_x - axis_len - 14, origin_y + 4, "3")
                                                      
        painter.drawText(origin_x - 4, origin_y - axis_len - 8, "2")
        
        p = self.params
        if p["type"] == "general":
                                                
            painter.setPen(QPen(Qt.GlobalColor.gray, 1, Qt.PenStyle.DashLine))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Custom Properties\n(Wireframe Only)")
            return
        rgb = [int(c * 255) for c in p.get("color", (0.5,0.5,0.5))[:3]]
        painter.setBrush(QBrush(QColor(*rgb)))
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        
        if p["type"] == "rect":
            b, h_dim = p["b"], p["h"]
            max_dim = max(b, h_dim)
            if max_dim == 0: return
            scale = 140.0 / max_dim
            draw_w, draw_h = b*scale, h_dim*scale
            painter.drawRect(QRectF(cx - draw_w/2, cy - draw_h/2, draw_w, draw_h))
            
        elif p["type"] == "i_sec":
            H = p["H"]; w_top = p["w_top"]; w_bot = p["w_bot"]
            max_dim = max(H, w_top, w_bot)
            if max_dim == 0: return
            scale = 140.0 / max_dim
            
            sH = H * scale
            sw_top = w_top * scale; st_top = p["t_top"] * scale
            sw_bot = w_bot * scale; st_bot = p["t_bot"] * scale
            st_web = p["t_web"] * scale
            
            top_y = cy - sH/2
            bot_y = cy + sH/2
            
            painter.drawRect(QRectF(cx - sw_top/2, top_y, sw_top, st_top))
                           
            if sw_bot > 0 and st_bot > 0:
                painter.drawRect(QRectF(cx - sw_bot/2, bot_y - st_bot, sw_bot, st_bot))
                 
            web_h = sH - st_top - st_bot
            if web_h > 0:
                painter.drawRect(QRectF(cx - st_web/2, top_y + st_top, st_web, web_h))

        elif p["type"] == "circ":
            d = p["circ_d"]
            if d == 0: return
            scale = 140.0 / d
            draw_d = d * scale
            painter.drawEllipse(QRectF(cx - draw_d/2, cy - draw_d/2, draw_d, draw_d))
            
        elif p["type"] == "pipe":
            d = p["pipe_d"]
            t = p["pipe_t"]
            if d == 0: return
            scale = 140.0 / d
            draw_d = d * scale
            draw_t = t * scale
            
            path = QPainterPath()
            path.addEllipse(QRectF(cx - draw_d/2, cy - draw_d/2, draw_d, draw_d))
            if draw_d > 2 * draw_t:
                inner_d = draw_d - 2 * draw_t
                path.addEllipse(QRectF(cx - inner_d/2, cy - inner_d/2, inner_d, inner_d))
            
            path.setFillRule(Qt.FillRule.OddEvenFill)
            painter.drawPath(path)
            
        elif p["type"] == "tube":
            d = p["tube_d"]
            b = p["tube_b"]
            tf = p["tube_tf"]
            tw = p["tube_tw"]
            max_dim = max(d, b)
            if max_dim == 0: return
            scale = 140.0 / max_dim
            
            draw_d, draw_b = d * scale, b * scale
            draw_tf, draw_tw = tf * scale, tw * scale
            
            path = QPainterPath()
            path.addRect(QRectF(cx - draw_b/2, cy - draw_d/2, draw_b, draw_d))
            if draw_d > 2 * draw_tf and draw_b > 2 * draw_tw:
                inner_d = draw_d - 2 * draw_tf
                inner_b = draw_b - 2 * draw_tw
                path.addRect(QRectF(cx - inner_b/2, cy - inner_d/2, inner_b, inner_d))
                
            path.setFillRule(Qt.FillRule.OddEvenFill)
            painter.drawPath(path)
            
        elif p["type"] == "trap":
            d = p["trap_d"]
            btop = p["trap_btop"]
            bbot = p["trap_bbot"]
            max_dim = max(d, btop, bbot)
            if max_dim == 0: return
            scale = 140.0 / max_dim
            
            draw_d = d * scale
            draw_btop = btop * scale
            draw_bbot = bbot * scale
            
            top_y = cy - draw_d/2
            bot_y = cy + draw_d/2
            
            poly = QPolygonF([
                QPointF(cx - draw_btop/2, top_y),
                QPointF(cx + draw_btop/2, top_y),
                QPointF(cx + draw_bbot/2, bot_y),
                QPointF(cx - draw_bbot/2, bot_y)
            ])
            painter.drawPolygon(poly)

        elif p["type"] == "arbitrary":
            verts = p.get("vertices", [])
            if not verts:
                painter.setPen(QPen(Qt.GlobalColor.gray, 1, Qt.PenStyle.DashLine))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Arbitrary\n(No Preview)")
            else:
                ys = [v[0] for v in verts]
                zs = [v[1] for v in verts]
                span = max(max(ys) - min(ys), max(zs) - min(zs))
                if span > 0:
                    sc = 140.0 / span
                    cy_off = (min(ys) + max(ys)) / 2
                    cz_off = (min(zs) + max(zs)) / 2
                    poly = QPolygonF([
                        QPointF(cx + (v[0] - cy_off) * sc, cy - (v[1] - cz_off) * sc)
                        for v in verts
                    ])
                    painter.drawPolygon(poly)

        painter.setBrush(Qt.GlobalColor.red)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 3, 3)

class SectionModifiersDialog(QDialog):
    def __init__(self, current_modifiers, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Property/Stiffness Modifiers")
        self.resize(350, 350)
        self.modifiers = current_modifiers.copy()
        
        layout = QVBoxLayout(self)
        gp = QGroupBox("Analysis Factors (Multipliers)")
        form = QFormLayout()
        
        self.inputs = {}
        labels = {
            "A": "Cross-section Area",
            "As2": "Shear Area (Local 2)",
            "As3": "Shear Area (Local 3)",
            "J": "Torsional Constant",
            "I2": "Moment of Inertia (Local 2)",
            "I3": "Moment of Inertia (Local 3)",
            "Mass": "Mass",
            "Weight": "Weight"
        }
        
        for key, text in labels.items():
            sb = QDoubleSpinBox()
            sb.setRange(0.0001, 1000.0)
            sb.setSingleStep(0.1)
            sb.setDecimals(4)
            sb.setValue(self.modifiers.get(key, 1.0))
            form.addRow(text, sb)
            self.inputs[key] = sb
            
        gp.setLayout(form)
        layout.addWidget(gp)
        
        btns = QHBoxLayout()
        btn_ok = QPushButton("OK"); btn_ok.clicked.connect(self.save)
        btn_cancel = QPushButton("Cancel"); btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok); btns.addWidget(btn_cancel)
        layout.addLayout(btns)
        
    def save(self):
        for key, sb in self.inputs.items():
            self.modifiers[key] = sb.value()
        self.accept()

class SectionPropertiesInfoDialog(QDialog):
    def __init__(self, props, length_unit="m", parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Section Properties")
        self.resize(600, 400)
        
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setSpacing(10)
        u = length_unit
        
        def add_row(row_idx, label, key, unit):
            val = props.get(key, 0.0)
            lbl = QLabel(f"{label} ({unit}):")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            if abs(val) < 1e-3 and val != 0: txt = f"{val:.4e}"
            else: txt = f"{val:.4f}"
                
            line = QLineEdit(txt)
            line.setReadOnly(True)
            line.setStyleSheet("background-color: #f0f0f0; color: #333;")
            
            col = (row_idx % 3) * 2
            row = row_idx // 3
            grid.addWidget(lbl, row, col)
            grid.addWidget(line, row, col + 1)

        items = [
            ("Area", "A", f"{u}²"),           ("J (Torsion)", "J", f"{u}⁴"),         ("Mass", "Mass", "kg/m"),
            ("I33 (Major)", "I33", f"{u}⁴"),  ("S33 (Modulus)", "S33", f"{u}³"),     ("Z33 (Plastic)", "Z33", f"{u}³"),
            ("I22 (Minor)", "I22", f"{u}⁴"),  ("S22 (Modulus)", "S22", f"{u}³"),     ("Z22 (Plastic)", "Z22", f"{u}³"),
            ("As2 (Shear)", "As2", f"{u}²"),  ("r22 (Radius)", "r22", f"{u}"),       ("r33 (Radius)", "r33", f"{u}"),
            ("As3 (Shear)", "As3", f"{u}²"),
        ]

        for i, (lbl, key, unit) in enumerate(items):
            add_row(i, lbl, key, unit)
        
        layout.addLayout(grid)
        btn = QPushButton("Done")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
        
class AddSectionDialog(QDialog):
                                                                      
    def __init__(self, model, parent=None, section_data=None, preselected_index=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Define Section")
                                   
        self.resize(700, 500)
        
        self.model = model
        self.section_data = section_data
        
        self.selected_color = (0.259, 0.110, 0.749, 1.0)
        self.current_modifiers = {"A":1.0, "As2":1.0, "As3":1.0, "J":1.0, "I2":1.0, "I3":1.0, "Mass":1.0, "Weight":1.0}

        self.all_inputs = [] 
        self._l_scale = LENGTH_SCALES.get(unit_registry.length_unit_name, 1.0)

        self.setup_ui()
        self.connect_signals()

        if preselected_index is not None:
            self.type_combo.setCurrentIndex(preselected_index)
            self.stack.setCurrentIndex(preselected_index)
            self.update_preview()

        if self.section_data:
            self.setWindowTitle("Modify Section Property")
            self.load_section_data()
        else:
            self.setWindowTitle("Add New Section Property")
            base_name = "SEC"
            idx = 1
            while f"{base_name}{idx}" in self.model.sections:
                idx += 1
            self.name_edit.setText(f"{base_name}{idx}")

        self.update_color_button()
        self.update_preview()
        
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        top = QHBoxLayout()
        form = QFormLayout()
        self.name_edit = QLineEdit("FSEC1")
        form.addRow("Section Name:", self.name_edit)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "Rectangular", 
            "I-Section / T-Section", 
            "Circular", 
            "Pipe", 
            "Tube", 
            "Trapezoidal", 
            "General / Custom"
        ])               
        form.addRow("Shape:", self.type_combo)

        self.btn_designer = QPushButton("Section Designer (Beta)…")
        self.btn_designer.clicked.connect(self._open_section_designer)
        form.addRow("", self.btn_designer)

        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(50, 25)
        
        top.addLayout(form, 1)
        
        unit_group = QGroupBox("Input Units")
        unit_group.setToolTip("Dialog-only — project units are not affected")
        unit_layout = QHBoxLayout(unit_group)
        unit_layout.addWidget(QLabel("Length:"))
        
        self.combo_length = QComboBox()
        self.combo_length.addItems(list(LENGTH_SCALES.keys()))
        self.combo_length.setCurrentText(unit_registry.length_unit_name)
        self.combo_length.currentTextChanged.connect(self._on_unit_changed)
        
        unit_layout.addWidget(self.combo_length)
        unit_layout.addStretch()

        right_top_layout = QVBoxLayout()
        right_top_layout.addWidget(unit_group)
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        color_layout.addWidget(self.btn_color)
        color_layout.addStretch()
        right_top_layout.addLayout(color_layout)
        
        top.addLayout(right_top_layout)
        main_layout.addLayout(top)

        mid = QHBoxLayout()
        input_grp = QGroupBox("Dimensions & Material")
        in_layout = QVBoxLayout()
        
        self.mat_combo = QComboBox()
        for m in self.model.materials: self.mat_combo.addItem(m)
        in_layout.addWidget(QLabel("Material:"))
        in_layout.addWidget(self.mat_combo)
        
        self.stack = QStackedWidget()
        
        pg_rect = QWidget(); fr = QFormLayout()
        self.h_spin = self.mk_spin(0.5); fr.addRow("Depth (t3):", self.h_spin)
        self.b_spin = self.mk_spin(0.3); fr.addRow("Width (t2):", self.b_spin)
        pg_rect.setLayout(fr)
        self.stack.addWidget(pg_rect)
        
        pg_i = QWidget(); fi = QFormLayout()
        self.i_h_spin = self.mk_spin(0.6); fi.addRow("Total Depth (H):", self.i_h_spin)
        self.i_wtop_spin = self.mk_spin(0.3); fi.addRow("Top Flange Width:", self.i_wtop_spin)
        self.i_ttop_spin = self.mk_spin(0.02); fi.addRow("Top Flange Thick:", self.i_ttop_spin)
        self.i_tw_spin = self.mk_spin(0.015); fi.addRow("Web Thickness:", self.i_tw_spin)
        self.i_wbot_spin = self.mk_spin(0.3); fi.addRow("Bot Flange Width:", self.i_wbot_spin)
        self.i_tbot_spin = self.mk_spin(0.02); fi.addRow("Bot Flange Thick:", self.i_tbot_spin)
        pg_i.setLayout(fi)
        self.stack.addWidget(pg_i)

        pg_circ = QWidget(); fc = QFormLayout()
        self.circ_d_spin = self.mk_spin(0.5); fc.addRow("Diameter (t3):", self.circ_d_spin)
        pg_circ.setLayout(fc)
        self.stack.addWidget(pg_circ)

        pg_pipe = QWidget(); fp = QFormLayout()
        self.pipe_d_spin = self.mk_spin(0.5); fp.addRow("Outer Diameter (t3):", self.pipe_d_spin)
        self.pipe_t_spin = self.mk_spin(0.02); fp.addRow("Wall Thickness (tw):", self.pipe_t_spin)
        pg_pipe.setLayout(fp)
        self.stack.addWidget(pg_pipe)

        pg_tube = QWidget(); ft = QFormLayout()
        self.tube_d_spin = self.mk_spin(0.5); ft.addRow("Depth (t3):", self.tube_d_spin)
        self.tube_b_spin = self.mk_spin(0.3); ft.addRow("Width (t2):", self.tube_b_spin)
        self.tube_tf_spin = self.mk_spin(0.02); ft.addRow("Flange Thick (tf):", self.tube_tf_spin)
        self.tube_tw_spin = self.mk_spin(0.02); ft.addRow("Web Thick (tw):", self.tube_tw_spin)
        pg_tube.setLayout(ft)
        self.stack.addWidget(pg_tube)

        pg_trap = QWidget(); ftr = QFormLayout()
        self.trap_d_spin = self.mk_spin(0.5); ftr.addRow("Depth (t3):", self.trap_d_spin)
        self.trap_btop_spin = self.mk_spin(0.3); ftr.addRow("Top Width (t2):", self.trap_btop_spin)
        self.trap_bbot_spin = self.mk_spin(0.4); ftr.addRow("Bot Width (t2b):", self.trap_bbot_spin)
        pg_trap.setLayout(ftr)
        self.stack.addWidget(pg_trap)

        pg_gen = QWidget()
        fg = QGridLayout()                                 
        self.gen_a = self.mk_prop_spin("area");      fg.addWidget(QLabel("Area (A):"), 0, 0);   fg.addWidget(self.gen_a, 0, 1)
        self.gen_j = self.mk_prop_spin("inertia");   fg.addWidget(QLabel("Torsion (J):"), 1, 0); fg.addWidget(self.gen_j, 1, 1)
        self.gen_i33 = self.mk_prop_spin("inertia"); fg.addWidget(QLabel("I33 (Major):"), 2, 0); fg.addWidget(self.gen_i33, 2, 1)
        self.gen_i22 = self.mk_prop_spin("inertia"); fg.addWidget(QLabel("I22 (Minor):"), 3, 0); fg.addWidget(self.gen_i22, 3, 1)
        self.gen_as2 = self.mk_prop_spin("area");    fg.addWidget(QLabel("Shear Area 2:"), 4, 0); fg.addWidget(self.gen_as2, 4, 1)
        self.gen_as3 = self.mk_prop_spin("area");    fg.addWidget(QLabel("Shear Area 3:"), 5, 0); fg.addWidget(self.gen_as3, 5, 1)
        pg_gen.setLayout(fg)
        self.stack.addWidget(pg_gen)    
        
        in_layout.addWidget(self.stack)
        input_grp.setLayout(in_layout)

        note_lbl = QLabel("Note: Enter standard decimals (5000) or scientific notation (5e3). Values dynamically convert when units change.")
        note_lbl.setStyleSheet("color: gray; font-size: 10px; font-style: italic;")
        note_lbl.setWordWrap(True)
        in_layout.addWidget(note_lbl)
        
        prev_layout = QVBoxLayout()
        self.preview_widget = SectionPreviewWidget()
        self.btn_props = QPushButton("Section Properties...")
        self.btn_mods = QPushButton("Property Modifiers...")
        
        prev_layout.addWidget(QLabel("Preview"), 0, Qt.AlignmentFlag.AlignCenter)
        prev_layout.addWidget(self.preview_widget, 0, Qt.AlignmentFlag.AlignCenter)
        prev_layout.addStretch()
        prev_layout.addWidget(self.btn_props)
        prev_layout.addWidget(self.btn_mods)
        
        mid.addWidget(input_grp, 1)
        mid.addLayout(prev_layout, 1)
        main_layout.addLayout(mid)
        
        btns = QHBoxLayout()
        self.btn_ok = QPushButton("OK"); self.btn_cancel = QPushButton("Cancel")
        btns.addStretch(); btns.addWidget(self.btn_ok); btns.addWidget(self.btn_cancel)
        main_layout.addLayout(btns)

    def mk_spin(self, val_meters):
        return self.mk_prop_spin("length", val_meters)

    def mk_prop_spin(self, prop_type="area", initial_si_val=0.0):
        current_unit = self.combo_length.currentText()
        
        # Calculate initial display scale
        if prop_type == "area":       scale = self._l_scale ** 2
        elif prop_type == "inertia":  scale = self._l_scale ** 4
        else:                         scale = self._l_scale
            
        inp = SmartDoubleInput(initial_si_val * scale, prop_type, current_unit)
        self.all_inputs.append(inp)
        return inp
        
    def mk_spin_length(self, val_meters):
        return self.mk_spin(val_meters)

    def _get_si(self, inp: SmartDoubleInput) -> float:
        """Safely reads the widget's pure value and converts it strictly back to SI base (meters)."""
        val = inp.value() # Use the widget's safe value parser
            
        prop = inp.property("prop_type")
        if prop == "area":       
            return val / (self._l_scale ** 2)
        elif prop == "inertia":  
            return val / (self._l_scale ** 4)
        else:                    
            return val / self._l_scale

    def _on_unit_changed(self):
        old_scale = self._l_scale
        si_vals = {}
        
        # 1. Read current UI text and convert TO strict SI
        for inp in self.all_inputs:
            val = inp.value()
                
            prop = inp.property("prop_type")
            if prop == "area":       si_vals[inp] = val / (old_scale ** 2)
            elif prop == "inertia":  si_vals[inp] = val / (old_scale ** 4)
            else:                    si_vals[inp] = val / old_scale
            
        # 2. Update to new unit scale
        self._l_scale = LENGTH_SCALES[self.combo_length.currentText()]
        new_unit = self.combo_length.currentText()
        
        # 3. Convert SI back to NEW unit and display
        for inp in self.all_inputs:
            prop = inp.property("prop_type")
            si_val = si_vals[inp]
            
            if prop == "area":       new_val = si_val * (self._l_scale ** 2)
            elif prop == "inertia":  new_val = si_val * (self._l_scale ** 4)
            else:                    new_val = si_val * self._l_scale
            
            inp.setUnit(new_unit) # Update the unit string
            inp.setValue(new_val) # Triggers the formatting with the new suffix
            
        self.update_preview()

    def connect_signals(self):
        self.type_combo.currentIndexChanged.connect(self.on_type_changed)
        self.btn_ok.clicked.connect(self.save)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_color.clicked.connect(self.pick_color)
        self.btn_mods.clicked.connect(self.show_modifiers)
        self.btn_props.clicked.connect(self.show_properties)
        for s in [self.h_spin, self.b_spin, self.i_h_spin, self.i_wtop_spin, 
                  self.i_ttop_spin, self.i_tw_spin, self.i_wbot_spin, self.i_tbot_spin,
                  self.circ_d_spin, self.pipe_d_spin, self.pipe_t_spin, 
                  self.tube_d_spin, self.tube_b_spin, self.tube_tf_spin, self.tube_tw_spin,
                  self.trap_d_spin, self.trap_btop_spin, self.trap_bbot_spin]:
            s.editingFinished.connect(self.update_preview)

    def on_type_changed(self, idx):
        self.stack.setCurrentIndex(idx)
        self.update_preview()

    def _open_section_designer(self):
        existing = self.section_data if isinstance(self.section_data, ArbitrarySection) else None
        dlg = SectionDesignerDialog(self.model, section_data=existing, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.model.add_section(dlg.result_section)
            self.accept()

    def update_preview(self):
        idx = self.type_combo.currentIndex()
        if idx == 0: st = "rect"
        elif idx == 1: st = "i_sec"
        elif idx == 2: st = "circ"
        elif idx == 3: st = "pipe"
        elif idx == 4: st = "tube"
        elif idx == 5: st = "trap"
        else: st = "general"                                              
        
        p = {
            "type": st, "color": self.selected_color,
            "b": self._get_si(self.b_spin), 
            "h": self._get_si(self.h_spin),
            "H": self._get_si(self.i_h_spin), 
            "w_top": self._get_si(self.i_wtop_spin),
            "t_top": self._get_si(self.i_ttop_spin), 
            "t_web": self._get_si(self.i_tw_spin),
            "w_bot": self._get_si(self.i_wbot_spin), 
            "t_bot": self._get_si(self.i_tbot_spin),
                                
            "circ_d": self._get_si(self.circ_d_spin),
            "pipe_d": self._get_si(self.pipe_d_spin), 
            "pipe_t": self._get_si(self.pipe_t_spin),
            "tube_d": self._get_si(self.tube_d_spin), 
            "tube_b": self._get_si(self.tube_b_spin),
            "tube_tf": self._get_si(self.tube_tf_spin), 
            "tube_tw": self._get_si(self.tube_tw_spin),
            "trap_d": self._get_si(self.trap_d_spin), 
            "trap_btop": self._get_si(self.trap_btop_spin),
            "trap_bbot": self._get_si(self.trap_bbot_spin)
        }
        self.preview_widget.update_params(p)

    def pick_color(self):
        r, g, b = [int(c*255) for c in self.selected_color[:3]]
        c = QColorDialog.getColor(QColor(r,g,b), self, "Select Color")
        if c.isValid():
            self.selected_color = (c.redF(), c.greenF(), c.blueF(), 1.0)
            self.update_color_button()

    def update_color_button(self):
        r, g, b = [int(c*255) for c in self.selected_color[:3]]
        self.btn_color.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid gray;")
        self.update_preview()

    def show_modifiers(self):
        d = SectionModifiersDialog(self.current_modifiers, self)
        if d.exec(): self.current_modifiers = d.modifiers

    def save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Please enter a Section Name.")
            return
        
        original_name = self.section_data.name if self.section_data else None
        if name != original_name and name in self.model.sections:
            reply = QMessageBox.question(
                self, "Duplicate Name", 
                f"A section named '{name}' already exists. Do you want to overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        mat_name = self.mat_combo.currentText()
        if not mat_name:
            QMessageBox.critical(self, "Material Missing", "No Material Selected!")
            return
        
        mat = self.model.materials[mat_name]
        
        exact_props = None
        if self.section_data:
            exact_props = {
                'A': self.section_data.A,
                'J': self.section_data.J,
                'I22': self.section_data.I22,
                'I33': self.section_data.I33,
                'As2': self.section_data.Asy,
                'As3': self.section_data.Asz
            }

        idx = self.type_combo.currentIndex()
        
        if idx == 0:               
            sec = RectangularSection(
                name, mat, 
                self._get_si(self.b_spin), 
                self._get_si(self.h_spin)
            )
        
        elif idx == 1:             
            sec = ISection(
                name, mat, 
                self._get_si(self.i_h_spin), 
                self._get_si(self.i_wtop_spin), 
                self._get_si(self.i_ttop_spin),
                self._get_si(self.i_wbot_spin), 
                self._get_si(self.i_tbot_spin), 
                self._get_si(self.i_tw_spin),
                props=exact_props
            )

        elif idx == 2:            
            sec = CircularSection(
                name, mat, 
                self._get_si(self.circ_d_spin)
            )
            
        elif idx == 3:        
            sec = PipeSection(
                name, mat, 
                self._get_si(self.pipe_d_spin), 
                self._get_si(self.pipe_t_spin)
            )
            
        elif idx == 4:        
            sec = TubeSection(
                name, mat, 
                self._get_si(self.tube_d_spin), 
                self._get_si(self.tube_b_spin), 
                self._get_si(self.tube_tf_spin), 
                self._get_si(self.tube_tw_spin)
            )
            
        elif idx == 5:               
            sec = TrapezoidalSection(
                name, mat, 
                self._get_si(self.trap_d_spin), 
                self._get_si(self.trap_btop_spin), 
                self._get_si(self.trap_bbot_spin)
            )

        elif idx == 6:           
            props = {
                'A':   self._get_si(self.gen_a),
                'J':   self._get_si(self.gen_j),
                'I33': self._get_si(self.gen_i33),
                'I22': self._get_si(self.gen_i22),
                'Asy': self._get_si(self.gen_as2),
                'Asz': self._get_si(self.gen_as3)
            }
            sec = GeneralSection(name, mat, props)
            
        sec.color = self.selected_color
        sec.modifiers = self.current_modifiers.copy()
        
        self.model.add_section(sec)
        
        count = 0
        for element in self.model.elements.values():
            if element.section.name == name:
                element.section = sec
                count += 1
        if count > 0: print(f"Updated {count} elements.")

        self.accept()

    def show_properties(self):
        dummy_mat = Material("Temp", 1, 0.2, 7850, "steel")
        temp_name = self.name_edit.text() if self.name_edit.text() else "TempSec"
        
        idx = self.type_combo.currentIndex()
        
        exact_props = None
        if self.section_data:
            exact_props = {
                'A': self.section_data.A,
                'J': self.section_data.J,
                'I22': self.section_data.I22,
                'I33': self.section_data.I33,
                'As2': self.section_data.Asy,
                'As3': self.section_data.Asz
            }
                                                         
        if idx == 0:
            sec = RectangularSection(temp_name, dummy_mat, self._get_si(self.b_spin), self._get_si(self.h_spin))
        elif idx == 1:
            sec = ISection(temp_name, dummy_mat, 
                        self._get_si(self.i_h_spin), self._get_si(self.i_wtop_spin), 
                        self._get_si(self.i_ttop_spin), self._get_si(self.i_wbot_spin), 
                        self._get_si(self.i_tbot_spin), self._get_si(self.i_tw_spin),
                        props=exact_props)   
        elif idx == 2:
            sec = CircularSection(temp_name, dummy_mat, self._get_si(self.circ_d_spin))
        elif idx == 3:
            sec = PipeSection(temp_name, dummy_mat, self._get_si(self.pipe_d_spin), self._get_si(self.pipe_t_spin))
        elif idx == 4:
            sec = TubeSection(temp_name, dummy_mat, self._get_si(self.tube_d_spin), self._get_si(self.tube_b_spin), self._get_si(self.tube_tf_spin), self._get_si(self.tube_tw_spin))
        elif idx == 5:
            sec = TrapezoidalSection(temp_name, dummy_mat, self._get_si(self.trap_d_spin), self._get_si(self.trap_btop_spin), self._get_si(self.trap_bbot_spin))
        elif idx == 6:          
            props = {
                'A': self._get_si(self.gen_a), 'J': self._get_si(self.gen_j),
                'I33': self._get_si(self.gen_i33), 'I22': self._get_si(self.gen_i22),
                'Asy': self._get_si(self.gen_as2), 'Asz': self._get_si(self.gen_as3)
            }
            sec = GeneralSection(temp_name, dummy_mat, props)
            
        u_len = self.combo_length.currentText()
        props = {
            "A": sec.A, 
            "J": sec.J, 
            "I33": sec.I33,                       
            "I22": sec.I22,                       
            "As2": sec.Asy,                                    
            "As3": sec.Asz,                                    
            "S33": sec.S33,                       
            "S22": sec.S22,                       
            "Z33": sec.Z33,                       
            "Z22": sec.Z22,                       
            "r33": sec.r33,                       
            "r22": sec.r22                        
        }
        SectionPropertiesInfoDialog(props, length_unit=u_len, parent=self).exec()

    def load_section_data(self):
        self.name_edit.setText(self.section_data.name)
        self.selected_color = self.section_data.color
        self.current_modifiers = self.section_data.modifiers.copy()
        
        idx = self.mat_combo.findText(self.section_data.material.name)
        if idx >= 0: self.mat_combo.setCurrentIndex(idx)
        
        scale = self._l_scale
        
        if isinstance(self.section_data, RectangularSection):
            self.type_combo.setCurrentIndex(0)
            self.b_spin.setValue(self.section_data.b * scale)
            self.h_spin.setValue(self.section_data.h * scale)
            
        elif isinstance(self.section_data, ISection):
            self.type_combo.setCurrentIndex(1)
            self.i_h_spin.setValue(self.section_data.h * scale)
            self.i_wtop_spin.setValue(self.section_data.w_top * scale)
            self.i_ttop_spin.setValue(self.section_data.t_top * scale)
            self.i_tw_spin.setValue(self.section_data.t_web * scale)
            self.i_wbot_spin.setValue(self.section_data.w_bot * scale)
            self.i_tbot_spin.setValue(self.section_data.t_bot * scale)

        elif isinstance(self.section_data, CircularSection):
            self.type_combo.setCurrentIndex(2)
            self.circ_d_spin.setValue(self.section_data.d * scale)
            
        elif isinstance(self.section_data, PipeSection):
            self.type_combo.setCurrentIndex(3)
            self.pipe_d_spin.setValue(self.section_data.d * scale)
            self.pipe_t_spin.setValue(self.section_data.t * scale)
            
        elif isinstance(self.section_data, TubeSection):
            self.type_combo.setCurrentIndex(4)
            self.tube_d_spin.setValue(self.section_data.d * scale)
            self.tube_b_spin.setValue(self.section_data.b * scale)
            self.tube_tf_spin.setValue(self.section_data.tf * scale)
            self.tube_tw_spin.setValue(self.section_data.tw * scale)
            
        elif isinstance(self.section_data, TrapezoidalSection):
            self.type_combo.setCurrentIndex(5)
            self.trap_d_spin.setValue(self.section_data.d * scale)
            self.trap_btop_spin.setValue(self.section_data.w_top * scale)
            self.trap_bbot_spin.setValue(self.section_data.w_bot * scale)
        
        elif isinstance(self.section_data, ArbitrarySection):
            self.type_combo.setEnabled(False)
            self.stack.setEnabled(False)
            self.mat_combo.setEnabled(False)
            self.name_edit.setEnabled(False)
            self.btn_ok.setEnabled(False)
            self.btn_designer.setText("Open in Section Designer…")
            self.preview_widget.update_params({
                "type": "arbitrary",
                "color": self.selected_color,
                "vertices": self.section_data.get_shape_coords(),
            })
            return                            

        elif isinstance(self.section_data, GeneralSection):
            self.type_combo.setCurrentIndex(6)
            self.gen_a.setValue(getattr(self.section_data, 'A', 0.0) * (scale**2))
            self.gen_j.setValue(getattr(self.section_data, 'J', 0.0) * (scale**4))
            
            self.gen_i33.setValue(getattr(self.section_data, 'I33', 0.0) * (scale**4)) 
            self.gen_i22.setValue(getattr(self.section_data, 'I22', 0.0) * (scale**4)) 
            self.gen_as2.setValue(getattr(self.section_data, 'Asy', 0.0) * (scale**2)) 
            self.gen_as3.setValue(getattr(self.section_data, 'Asz', 0.0) * (scale**2))

class SectionManagerDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Frame Sections")
        self.resize(350, 400)
        self.model = model
        
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        
        btn_layout = QHBoxLayout()
        v_btns = QVBoxLayout()
        
        self.btn_add = QPushButton("Add New Property...")
        self.btn_add.clicked.connect(self.add_section)
        
        self.btn_copy = QPushButton("Add Copy of Property...")
        self.btn_copy.clicked.connect(self.copy_section)
        
        self.btn_mod = QPushButton("Modify/Show Property...")
        self.btn_mod.clicked.connect(self.modify_section)
        
        self.btn_del = QPushButton("Delete Property")
        self.btn_del.clicked.connect(self.delete_section)
        
        v_btns.addWidget(self.btn_add)
        v_btns.addWidget(self.btn_copy)
        v_btns.addWidget(self.btn_mod)
        v_btns.addWidget(self.btn_del)
        v_btns.addStretch()
        
        layout.addLayout(btn_layout)
        layout.addLayout(v_btns)
        
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)
        
        self.refresh_list()

    def copy_section(self):
        """Duplicates the selected section and opens the editor."""
        item = self.list_widget.currentItem()
        if not item: return
        original_name = item.text()
        
        original_sec = self.model.sections.get(original_name)
        if not original_sec: return
        
        import copy
        new_sec = copy.deepcopy(original_sec)
        
        base_name = original_name + "_Copy"
        idx = 1
        test_name = base_name
        while test_name in self.model.sections:
            test_name = f"{base_name}{idx}"
            idx += 1
        new_sec.name = test_name
        
        if AddSectionDialog(self.model, parent=self, section_data=new_sec).exec():
            self.refresh_list()

    def refresh_list(self):
        current_row = self.list_widget.currentRow()
        self.list_widget.clear()
        for name in self.model.sections:
            self.list_widget.addItem(name)
        if current_row >= 0 and current_row < self.list_widget.count():
            self.list_widget.setCurrentRow(current_row)

    def add_section(self):
        if not self.model.materials:
            QMessageBox.warning(self, "No Materials", "You must define a Material before defining a Section.")
            return
            
        dlg = AddFrameSectionPropertyDialog(main_manager=self, parent=self)
        dlg.exec()

    def import_aisc_section(self):
        import sys
        
        if not self.model.materials:
            QMessageBox.warning(self, "No Materials", "You must define a Material before importing.")
            return

        start_dir = ""
        if getattr(sys, 'frozen', False):
            if hasattr(sys, '_MEIPASS'):
                start_dir = os.path.join(sys._MEIPASS, "resources")
            elif not start_dir:
                start_dir = os.path.join(os.path.dirname(sys.executable), "resources")
        else:
            start_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../resources")

        path, _ = QFileDialog.getOpenFileName(self, "Open Section Database", start_dir, "Excel/CSV Files (*.xlsx *.xls *.csv)")
        if not path: return
        
        try:
            if path.endswith('.csv'): df = pd.read_csv(path)
            else: df = pd.read_excel(path, sheet_name='Database v16.0')
            
            def get_val(row, col):
                return float(row[col]) if col in row else 0.0

            filtered_shapes = []
            
            for index, row in df.iterrows():
                if row.get('Type') == 'W':
                    shape_name = str(row['AISC_Manual_Label.1'])
                    
                    h = get_val(row, 'd.1') / 1000.0
                    bf = get_val(row, 'bf.1') / 1000.0
                    tf = get_val(row, 'tf.1') / 1000.0
                    tw = get_val(row, 'tw.1') / 1000.0
                    
                    shape_data = {
                        'name': shape_name,
                        'h': h, 'w_top': bf, 't_top': tf, 'w_bot': bf, 't_bot': tf, 't_web': tw,
                    }

                    props = {
                        'A': get_val(row, 'A.1') / 1e6,
                        'I22': get_val(row, 'Ix.1') * 1e-6, 
                        'I33': get_val(row, 'Iy.1') * 1e-6, 
                        'J': get_val(row, 'J.1') * 1e-9, 
                        'As3': (h * tw),
                        'As2': (5/6) * (2 * bf * tf) 
                    }
                    
                    shape_data['props'] = props
                    filtered_shapes.append(shape_data)

            sel_dlg = AISCSelectionDialog(filtered_shapes, self)
            if sel_dlg.exec():
                data = sel_dlg.selected_row
                dummy_mat = list(self.model.materials.values())[0]
                
                temp_section = ISection(
                    data['name'], dummy_mat,
                    data['h'], data['w_top'], data['t_top'],
                    data['w_bot'], data['t_bot'], data['t_web'],
                    props=data['props']                                  
                )
                
                if AddSectionDialog(self.model, parent=self, section_data=temp_section).exec():
                    self.refresh_list()

        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to read file:\n{str(e)}")
            
    def modify_section(self):
        item = self.list_widget.currentItem()
        if not item: return
        name = item.text()
        sec = self.model.sections.get(name)
        if not sec: return

        if isinstance(sec, ArbitrarySection):
            dlg = SectionDesignerDialog(self.model, section_data=sec, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                result = dlg.result_section
                self.model.sections[result.name] = result
                for el in self.model.elements.values():
                    if el.section.name == name:
                        el.section = result
                self.refresh_list()
        elif AddSectionDialog(self.model, parent=self, section_data=sec).exec():
            self.refresh_list()

    def delete_section(self):
        item = self.list_widget.currentItem()
        if not item: return
        name = item.text()

        in_use, msg = check_section_in_use(self.model, name)
        if in_use:
            QMessageBox.warning(self, "Section In Use", msg)
            return

        if QMessageBox.question(self, 'Delete', f"Delete section '{name}'?", 
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            del self.model.sections[name]
            self.refresh_list()