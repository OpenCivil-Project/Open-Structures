import math
import re
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QTableWidget, QTableWidgetItem, QPushButton, 
                             QGroupBox, QHeaderView, QRadioButton, QButtonGroup,
                             QFrame, QDoubleSpinBox, QSpinBox, QMessageBox, QWidget, QComboBox)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont
from core.units import unit_registry

class GridPreviewWidget(QFrame):
    """
    A mini-canvas that draws the grid system in real-time.
    Supports XY, XZ, and YZ planes.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(280, 280)                       
        self.setStyleSheet("background-color: white; border: 1px solid #999;")
        
        self.h_grids = []                                
        self.v_grids = []                              
        self.plane = "XY"
        self.bubble_size = 1.0
        self.bubble_alpha = 1.0

    def update_data(self, h_data, v_data, plane, bubble_size, bubble_alpha=1.0):
        self.h_grids = h_data
        self.v_grids = v_data
        self.plane = plane
        self.bubble_size = bubble_size
        self.bubble_alpha = bubble_alpha
        self.update()                  

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        
        painter.fillRect(0, 0, w, h, Qt.GlobalColor.white)
        painter.setPen(Qt.GlobalColor.gray)
        painter.drawText(5, 15, f"View: {self.plane} Plane")
        
        if not self.h_grids or not self.v_grids:
            painter.drawText(w//2 - 30, h//2, "No Grid Data")
            return

        hs = [val for _, val, _ in self.h_grids]
        vs = [val for _, val, _ in self.v_grids]
        
        min_h, max_h = min(hs), max(hs)
        min_v, max_v = min(vs), max(vs)
        
        span_h = max_h - min_h
        span_v = max_v - min_v
        
        margin_h = max(span_h * 0.15, 2.0 * self.bubble_size) 
        margin_v = max(span_v * 0.15, 2.0 * self.bubble_size)
        
        view_min_h = min_h - margin_h
        view_max_h = max_h + margin_h
        view_min_v = min_v - margin_v
        view_max_v = max_v + margin_v
        
        def to_screen(gh, gv):
            sh = (gh - view_min_h) / (view_max_h - view_min_h) * w
            sv = h - (gv - view_min_v) / (view_max_v - view_min_v) * h
            return sh, sv

        grid_pen = QPen(QColor(180, 180, 180), 1, Qt.PenStyle.SolidLine)             
        painter.setPen(grid_pen)
        
        for _, h_val, _ in self.h_grids:
            x1, y1 = to_screen(h_val, view_min_v)
            x2, y2 = to_screen(h_val, view_max_v)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
            
        for _, v_val, _ in self.v_grids:
            x1, y1 = to_screen(view_min_h, v_val)
            x2, y2 = to_screen(view_max_h, v_val)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        b_radius = 5 + (self.bubble_size * 2) 
        
        painter.setFont(QFont("Arial", 8))
        bubble_color = QColor(240, 240, 240)
        bubble_color.setAlphaF(self.bubble_alpha)
        painter.setBrush(QBrush(bubble_color))
        painter.setPen(Qt.GlobalColor.black)

        for gid, h_val, bub_loc in self.h_grids:
            if bub_loc in ["End", "Both"]:           
                sx, sy = to_screen(h_val, max_v)
                center = QPointF(sx, sy - b_radius * 2) 
                painter.drawEllipse(center, b_radius, b_radius)
                painter.drawText(QRectF(sx - b_radius, sy - b_radius*3, b_radius*2, b_radius*2), 
                                 Qt.AlignmentFlag.AlignCenter, str(gid))
                                 
            if bub_loc in ["Start", "Both"]:              
                sx, sy = to_screen(h_val, min_v)
                center = QPointF(sx, sy + b_radius * 2) 
                painter.drawEllipse(center, b_radius, b_radius)
                painter.drawText(QRectF(sx - b_radius, sy + b_radius, b_radius*2, b_radius*2), 
                                 Qt.AlignmentFlag.AlignCenter, str(gid))

        for gid, v_val, bub_loc in self.v_grids:
            if bub_loc in ["Start", "Both"]:            
                sx, sy = to_screen(min_h, v_val)
                center = QPointF(sx - b_radius * 2, sy)
                painter.drawEllipse(center, b_radius, b_radius)
                painter.drawText(QRectF(sx - b_radius*3, sy - b_radius, b_radius*2, b_radius*2), 
                                 Qt.AlignmentFlag.AlignCenter, str(gid))
                                 
            if bub_loc in ["End", "Both"]:             
                sx, sy = to_screen(max_h, v_val)
                center = QPointF(sx + b_radius * 2, sy)
                painter.drawEllipse(center, b_radius, b_radius)
                painter.drawText(QRectF(sx + b_radius, sy - b_radius, b_radius*2, b_radius*2), 
                                 Qt.AlignmentFlag.AlignCenter, str(gid))

class GridEditorDialog(QDialog):
    def __init__(self, current_grid, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Define Grid System Data")
        self.resize(1200, 700)                         
        
        self.x_data = [] 
        self.y_data = []
        self.z_data = []
        
        self.current_mode = "ordinate" 
        self.initial_bubble_size = getattr(current_grid, 'bubble_size', 1.25)
        self.initial_bubble_alpha = getattr(current_grid, 'bubble_alpha', 1.0)
        self.parse_grid_obj(current_grid)

        self.setup_ui()
        self.populate_all_tables()
        self.update_preview()

    def parse_grid_obj(self, grid_obj):
        """Loads data from the Smart Grid object and converts to Display Units."""
        def to_list(lines_dict, prefix):
            rows = []
            if not lines_dict: return rows
            
            if isinstance(lines_dict[0], float):
                for i, val in enumerate(lines_dict):
                                              
                    disp_val = unit_registry.to_display_length(val)
                    rows.append([f"{prefix}{i+1}", disp_val, "Primary", True, "Start"])
            else:
                for item in lines_dict:
                                              
                    disp_val = unit_registry.to_display_length(item['ord'])
                    rows.append([
                        item['id'], 
                        disp_val, 
                        "Primary",                         
                        item['visible'], 
                        item['bubble']
                    ])
            return rows
        
        self.x_data = to_list(grid_obj.x_lines, "")
        self.y_data = to_list(grid_obj.y_lines, "")
        self.z_data = to_list(grid_obj.z_lines, "Z")

    def setup_ui(self):
        layout = QHBoxLayout(self)
        
        left_panel = QVBoxLayout()
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("System Name:"))
        name_layout.addWidget(QLabel("<b>GLOBAL</b>"))
        name_layout.addStretch()
        left_panel.addLayout(name_layout)

        self.table_x = self.create_grid_group("X Grid Data", "x")
        self.table_y = self.create_grid_group("Y Grid Data", "y")
        self.table_z = self.create_grid_group("Z Grid Data", "z")
        
        left_panel.addWidget(self.table_x['group'])
        left_panel.addWidget(self.table_y['group'])
        left_panel.addWidget(self.table_z['group'])
        
        right_panel = QVBoxLayout()
        
        prev_ctrl = QHBoxLayout()
        prev_ctrl.addWidget(QLabel("Preview View:"))
        self.combo_plane = QComboBox()
        self.combo_plane.addItems(["XY Plane (Plan)", "XZ Plane (Elevation)", "YZ Plane (Elevation)"])
        self.combo_plane.currentIndexChanged.connect(self.update_preview)
        prev_ctrl.addWidget(self.combo_plane)
        right_panel.addLayout(prev_ctrl)

        self.preview = GridPreviewWidget()
        right_panel.addWidget(self.preview)
        
        right_panel.addSpacing(20)

        opt_group = QGroupBox("Display Grids as")
        vbox = QVBoxLayout()
        self.rb_ordinate = QRadioButton("Ordinates")
        self.rb_spacing = QRadioButton("Spacing")
        self.rb_ordinate.setChecked(True)
        
        self.rb_ordinate.toggled.connect(lambda: self.toggle_mode("ordinate"))
        self.rb_spacing.toggled.connect(lambda: self.toggle_mode("spacing"))
        
        vbox.addWidget(self.rb_ordinate)
        vbox.addWidget(self.rb_spacing)
        opt_group.setLayout(vbox)
        right_panel.addWidget(opt_group)
        
        bub_layout = QHBoxLayout()
        bub_layout.addWidget(QLabel("Bubble Size:"))
        self.spin_bubble = QDoubleSpinBox()
        self.spin_bubble.setRange(0.001, 100.0)
        self.spin_bubble.setDecimals(3)
        self.spin_bubble.setValue(self.initial_bubble_size)
        self.spin_bubble.setSingleStep(0.05)
        self.spin_bubble.valueChanged.connect(self.update_preview)
        bub_layout.addWidget(self.spin_bubble)
        right_panel.addLayout(bub_layout)

        bub_alpha_layout = QHBoxLayout()
        bub_alpha_layout.addWidget(QLabel("Bubble Opacity:"))
        self.spin_bubble_alpha = QSpinBox()
        self.spin_bubble_alpha.setRange(10, 100)
        self.spin_bubble_alpha.setValue(round(self.initial_bubble_alpha * 100))
        self.spin_bubble_alpha.setSingleStep(5)
        self.spin_bubble_alpha.setSuffix("%")
        self.spin_bubble_alpha.valueChanged.connect(self.update_preview)
        bub_alpha_layout.addWidget(self.spin_bubble_alpha)
        right_panel.addLayout(bub_alpha_layout)

        self._all_visible = True
        self.btn_global_viz = QPushButton("Hide All Gridlines")
        self.btn_global_viz.setToolTip("Toggle visibility of every gridline across all axes at once")
        self.btn_global_viz.clicked.connect(self.toggle_all_axes_visibility)
        right_panel.addWidget(self.btn_global_viz)
        
        right_panel.addStretch()
        
        btn_box = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_ok)
        btn_box.addWidget(btn_cancel)
        right_panel.addLayout(btn_box)

        layout.addLayout(left_panel, 3)                         
        layout.addLayout(right_panel, 1)

    def create_grid_group(self, title, axis_key):
        gb = QGroupBox(title)
        layout = QHBoxLayout()
        
        table = QTableWidget()
        table.setColumnCount(5)
                               
        self.update_table_header(table, "Ordinate") 
        table.verticalHeader().setVisible(False)
        table.itemChanged.connect(self.on_table_changed) 
        
        btn_layout = QVBoxLayout()
        btn_add = QPushButton("Add")
        btn_del = QPushButton("Delete")

        btn_viz = QPushButton("Show/Hide All")
        btn_viz.clicked.connect(lambda: self.toggle_all_visibility(axis_key))

        btn_bub = QPushButton("Cycle All Bubbles")
        btn_bub.setToolTip("Cycles all gridlines in this axis through End, Start, Both, and None")
        btn_bub.clicked.connect(lambda: self.toggle_all_bubbles(axis_key))

        btn_add.clicked.connect(lambda: self.add_grid_line(axis_key))
        btn_del.clicked.connect(lambda: self.delete_grid_line(axis_key))
        
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_del)
        btn_layout.addWidget(btn_viz)
        btn_layout.addWidget(btn_bub)                                 
        btn_layout.addStretch()
        
        layout.addWidget(table)
        layout.addLayout(btn_layout)
        gb.setLayout(layout)
        return {'group': gb, 'table': table}

    def update_table_header(self, table, val_title):
        """Updates the 2nd column header dynamically."""
                                                              
        unit = unit_registry.length_unit_name           
        labels = ["Grid ID", f"{val_title} ({unit})", "Line Type", "Visible", "Bubble Loc"]
        table.setHorizontalHeaderLabels(labels)
                      
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

    def toggle_mode(self, new_mode):
        if self.current_mode == new_mode: return
        self.save_tables_to_data()
        self.current_mode = new_mode
        
        title = "Ordinate" if new_mode == "ordinate" else "Spacing"
        self.update_table_header(self.table_x['table'], title)
        self.update_table_header(self.table_y['table'], title)
        self.update_table_header(self.table_z['table'], title)
        
        self.populate_all_tables()

    def get_display_values(self, data_list):
        """Converts ordinates to the current display mode."""
        ordinates = [row[1] for row in data_list]
        if self.current_mode == "ordinate":
            return ordinates
        else:
            spacings = []
            for i in range(len(ordinates) - 1):
                spacings.append(round(ordinates[i+1] - ordinates[i], 4))
            spacings.append(0.0) 
            return spacings

    def populate_all_tables(self):
        self.populate_table(self.table_x['table'], self.x_data)
        self.populate_table(self.table_y['table'], self.y_data)
        self.populate_table(self.table_z['table'], self.z_data)

    def populate_table(self, table, data):
        table.blockSignals(True) 
        table.setRowCount(0)
        display_vals = self.get_display_values(data)
        
        for i, row in enumerate(data):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(str(row[0])))
            table.setItem(i, 1, QTableWidgetItem(f"{display_vals[i]:.6f}"))
            table.setItem(i, 2, QTableWidgetItem(row[2]))
            table.setItem(i, 3, QTableWidgetItem("Yes" if row[3] else "No"))
            
            combo = QComboBox()
            combo.addItems(["End", "Start", "Both", "None"])
            combo.setCurrentText(row[4])
            combo.setStyleSheet("QComboBox { border: none; padding-left: 4px; background: transparent; } QComboBox::drop-down { border: none; }")
            
            combo.currentTextChanged.connect(lambda text: self.save_tables_to_data())
            
            table.setCellWidget(i, 4, combo)
            
        table.blockSignals(False)

    def save_tables_to_data(self):
        self.x_data = self.read_table(self.table_x['table'], self.x_data)
        self.y_data = self.read_table(self.table_y['table'], self.y_data)
        self.z_data = self.read_table(self.table_z['table'], self.z_data)
        self.update_preview()

    def read_table(self, table, old_data):
        new_data = []
        rows = table.rowCount()
        raw_vals = []
        ids = []
        
        for r in range(rows):
            it_id = table.item(r, 0)
            it_val = table.item(r, 1)
            ids.append(it_id.text() if it_id else "")
            try: val = float(it_val.text()) if it_val else 0.0
            except: val = 0.0
            raw_vals.append(val)
            
        final_ordinates = []
        if self.current_mode == "ordinate":
            final_ordinates = raw_vals
        else:
                                                     
            current_pos = old_data[0][1] if old_data else 0.0
            final_ordinates.append(current_pos)
                                                        
            for i in range(len(raw_vals) - 1):
                current_pos += raw_vals[i]
                final_ordinates.append(current_pos)

        for r in range(rows):
                                                                 
            it_type = table.item(r, 2)
            l_type = it_type.text() if it_type else "Primary"
            
            it_vis = table.item(r, 3)
                                                     
            is_visible = (it_vis.text() == "Yes") if it_vis else True
            
            combo_bub = table.cellWidget(r, 4)
            bub_loc = combo_bub.currentText() if combo_bub else "End"
            
            new_data.append([ids[r], final_ordinates[r], l_type, is_visible, bub_loc])
            
        return new_data

    def on_table_changed(self, item):
        self.save_tables_to_data()

    def update_preview(self):
        idx = self.combo_plane.currentIndex()
        
        if idx == 0:           
            h_data = [(row[0], row[1], row[4]) for row in self.x_data]                  
            v_data = [(row[0], row[1], row[4]) for row in self.y_data]                
            plane_name = "XY"
        elif idx == 1:           
            h_data = [(row[0], row[1], row[4]) for row in self.x_data]                  
            v_data = [(row[0], row[1], row[4]) for row in self.z_data]                
            plane_name = "XZ"
        else:           
            h_data = [(row[0], row[1], row[4]) for row in self.y_data]                  
            v_data = [(row[0], row[1], row[4]) for row in self.z_data]                
            plane_name = "YZ"

        self.preview.update_data(h_data, v_data, plane_name, self.spin_bubble.value(), self.spin_bubble_alpha.value() / 100.0)

    def add_grid_line(self, axis):
        if axis == 'x': data = self.x_data; tbl = self.table_x['table']
        elif axis == 'y': data = self.y_data; tbl = self.table_y['table']
        else: data = self.z_data; tbl = self.table_z['table']
        
        if len(data) >= 2:
            last_ord = data[-1][1]
            prev_ord = data[-2][1]
            spacing = last_ord - prev_ord
            
            if abs(spacing) < 0.001: spacing = unit_registry.to_display_length(3.0)
        else:
            last_ord = data[-1][1] if data else 0.0
            base_spacing = 3.0 if axis == 'z' else 5.0 
                                              
            spacing = unit_registry.to_display_length(base_spacing)

        new_ord = last_ord + spacing

        last_id = data[-1][0] if data else "0"
        match = re.match(r"([A-Za-z]*)(\d+)", last_id)
        if match:
            prefix, num = match.groups()
            new_id = f"{prefix}{int(num)+1}"
        else:
            new_id = f"{len(data)+1}"
                             
        data.append([new_id, new_ord, "Primary", True, "End"])
        
        self.populate_table(tbl, data)
        self.save_tables_to_data()

    def delete_grid_line(self, axis):
        if axis == 'x': data = self.x_data; tbl = self.table_x['table']
        elif axis == 'y': data = self.y_data; tbl = self.table_y['table']
        else: data = self.z_data; tbl = self.table_z['table']
        
        row = tbl.currentRow()
        if row < 0: return 
        del data[row]
        self.populate_table(tbl, data)
        self.save_tables_to_data()

    def get_final_grids(self):
        """Returns list of dicts for the new GridLines class (converted back to base SI units)."""
        def pack(data_list):
            sorted_data = sorted(data_list, key=lambda x: x[1])
            packed = []
            for row in sorted_data:
                                                        
                base_val = unit_registry.from_display_length(row[1])
                packed.append({
                    'id': row[0],
                    'ord': base_val,
                    'visible': row[3],
                    'bubble': row[4]
                })
            return packed

        return {
            "x": pack(self.x_data),
            "y": pack(self.y_data),
            "z": pack(self.z_data),
            "bubble_size": self.spin_bubble.value(),
            "bubble_alpha": self.spin_bubble_alpha.value() / 100.0
        }
    
    def toggle_all_axes_visibility(self):
        """Master toggle — hides or shows every gridline across all three axes."""
        self._all_visible = not self._all_visible
        target_text = "Yes" if self._all_visible else "No"
        self.btn_global_viz.setText("Hide All Gridlines" if self._all_visible else "Show All Gridlines")

        for tbl in (self.table_x['table'], self.table_y['table'], self.table_z['table']):
            tbl.blockSignals(True)
            for r in range(tbl.rowCount()):
                tbl.setItem(r, 3, QTableWidgetItem(target_text))
            tbl.blockSignals(False)

        self.save_tables_to_data()

    def toggle_all_visibility(self, axis):
                                  
        if axis == 'x': tbl = self.table_x['table']
        elif axis == 'y': tbl = self.table_y['table']
        else: tbl = self.table_z['table']

        rows = tbl.rowCount()
        if rows == 0: return

        first_item = tbl.item(0, 3)
        current_state = (first_item.text() == "Yes")
        target_text = "No" if current_state else "Yes"
        
        tbl.blockSignals(True)                          
        for r in range(rows):
            tbl.setItem(r, 3, QTableWidgetItem(target_text))
        tbl.blockSignals(False)
        
        self.save_tables_to_data()

    def toggle_all_bubbles(self, axis):
        """Cycles all bubble dropdowns in a specific table to the next state."""
                                                          
        if axis == 'x': tbl = self.table_x['table']
        elif axis == 'y': tbl = self.table_y['table']
        else: tbl = self.table_z['table']

        rows = tbl.rowCount()
        if rows == 0: return

        first_combo = tbl.cellWidget(0, 4)
        if not first_combo: return
        
        current_state = first_combo.currentText()
        sequence = ["End", "Start", "Both", "None"]
        
        try:
            next_index = (sequence.index(current_state) + 1) % len(sequence)
        except ValueError:
            next_index = 0
            
        target_state = sequence[next_index]

        for r in range(rows):
            combo = tbl.cellWidget(r, 4)
            if combo:
                                                                                   
                combo.blockSignals(True) 
                combo.setCurrentText(target_state)
                combo.blockSignals(False)
        
        self.save_tables_to_data()
