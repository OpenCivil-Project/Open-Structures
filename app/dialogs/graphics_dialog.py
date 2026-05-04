from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSlider, QSpinBox, QCheckBox, QPushButton, 
                             QColorDialog, QTabWidget, QWidget, QGroupBox,
                             QDoubleSpinBox)                            
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

class ColorButton(QPushButton):
    """A helper button that shows the selected color."""
    def __init__(self, color_tuple, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 25)
        self.color = self._tuple_to_qcolor(color_tuple)
        self._update_style()
        self.clicked.connect(self.pick_color)

    def _tuple_to_qcolor(self, t):
                                                     
        return QColor(int(t[0]*255), int(t[1]*255), int(t[2]*255), int(t[3]*255))

    def _qcolor_to_tuple(self, c):
                                            
        return (c.redF(), c.greenF(), c.blueF(), c.alphaF())

    def _update_style(self):
                                        
        c = self.color
                                                        
        text_color = "white" if (c.red() + c.green() + c.blue()) / 3 < 128 else "black"
        self.setStyleSheet(f"background-color: {c.name()}; border: 1px solid #555; color: {text_color};")
        self.setText("Pick")

    def pick_color(self):
        new_c = QColorDialog.getColor(self.color, self.parent(), "Select Color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if new_c.isValid():
            self.color = new_c
            self._update_style()

    def get_color_tuple(self):
        return self._qcolor_to_tuple(self.color)

class GraphicsOptionsDialog(QDialog):
    def __init__(self, parent=None, current_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Graphics Options")
        self.resize(400, 350)
        self.settings = current_settings or {}
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        tab_gen = QWidget()
        v_gen = QVBoxLayout(tab_gen)
        
        h_bg = QHBoxLayout()
        h_bg.addWidget(QLabel("Background Color:"))
        self.btn_bg = ColorButton(self.settings.get("background_color", (1,1,1,1)), self)
        h_bg.addWidget(self.btn_bg)
        v_gen.addLayout(h_bg)

        h_aa = QHBoxLayout()
        h_aa.addWidget(QLabel("Anti-aliasing (MSAA):"))
        self.sl_aa = QSlider(Qt.Orientation.Horizontal)
        self.sl_aa.setRange(0, 3)  
        self.sl_aa.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sl_aa.setValue(self.settings.get("msaa_level", 2))
        h_aa.addWidget(self.sl_aa)
        self.lbl_aa = QLabel("8x")
        h_aa.addWidget(self.lbl_aa)
        self.sl_aa.valueChanged.connect(self._on_aa_changed)
        v_gen.addLayout(h_aa)
        lbl_note = QLabel("⚠️ Changes apply after restart")
        lbl_note.setStyleSheet("color: gray; font-size: 10px;")
        v_gen.addWidget(lbl_note)

        self.btn_restart = QPushButton("Restart Now")
        self.btn_restart.setStyleSheet("color: black; background-color: #ffffff; padding: 4px 8px;")
        self.btn_restart.clicked.connect(self._on_restart)
        v_gen.addWidget(self.btn_restart)

        self._on_aa_changed(self.sl_aa.value())
        
        v_gen.addStretch()
        self.tabs.addTab(tab_gen, "General")

        tab_nodes = QWidget()
        v_nodes = QVBoxLayout(tab_nodes)
        
        h_ns = QHBoxLayout()
        h_ns.addWidget(QLabel("Node Size (px):"))
        self.spin_node_size = QSpinBox()
        self.spin_node_size.setRange(2, 20)
        self.spin_node_size.setValue(self.settings.get("node_size", 6))
        h_ns.addWidget(self.spin_node_size)
        v_nodes.addLayout(h_ns)

        h_nc = QHBoxLayout()
        h_nc.addWidget(QLabel("Node Color:"))
        self.btn_node_col = ColorButton(self.settings.get("node_color", (1,1,0,1)), self)
        h_nc.addWidget(self.btn_node_col)
        v_nodes.addLayout(h_nc)

        v_nodes.addStretch()
        self.tabs.addTab(tab_nodes, "Joints")

        tab_frames = QWidget()
        v_frames = QVBoxLayout(tab_frames)
        
        g_wire = QGroupBox("Wireframe (Stick Mode)")
        l_wire = QVBoxLayout(g_wire)
        h_lw = QHBoxLayout()
        h_lw.addWidget(QLabel("Line Width:"))
        
        self.spin_line_width = QDoubleSpinBox()
        self.spin_line_width.setRange(0.1, 10.0)
        self.spin_line_width.setSingleStep(0.5)
        self.spin_line_width.setValue(float(self.settings.get("line_width", 2.0)))
        
        h_lw.addWidget(self.spin_line_width)
        l_wire.addLayout(h_lw)
        v_frames.addWidget(g_wire)

        g_ext = QGroupBox("Extruded (Solid Mode)")
        l_ext = QVBoxLayout(g_ext)
        
        h_op = QHBoxLayout()
        h_op.addWidget(QLabel("Face Transparency:"))                      
        self.sl_ext_op = QSlider(Qt.Orientation.Horizontal)
        self.sl_ext_op.setRange(0, 100)            
        self.sl_ext_op.setValue(int(self.settings.get("extrude_opacity", 0.35) * 100))
        h_op.addWidget(self.sl_ext_op)
        l_ext.addLayout(h_op)

        self.chk_edges = QCheckBox("Show Edges")
        self.chk_edges.setChecked(self.settings.get("show_edges", False))
        l_ext.addWidget(self.chk_edges)

        h_edge_op = QHBoxLayout()
        h_edge_op.addWidget(QLabel("Edge Transparency:"))
        self.sl_edge_op = QSlider(Qt.Orientation.Horizontal)
        self.sl_edge_op.setRange(0, 100)
        self.sl_edge_op.setValue(int(self.settings.get("edge_opacity", 0.08) * 100))               
        h_edge_op.addWidget(self.sl_edge_op)
        l_ext.addLayout(h_edge_op)
                                          
        h_ec = QHBoxLayout()
        h_ec.addWidget(QLabel("Edge Color:"))
        self.btn_edge_col = ColorButton(self.settings.get("edge_color", (0,0,0,1)), self)
        h_ec.addWidget(self.btn_edge_col)
        l_ext.addLayout(h_ec)
        
        h_ew = QHBoxLayout()
        h_ew.addWidget(QLabel("Edge Width:"))
        
        self.spin_edge_width = QDoubleSpinBox()
        self.spin_edge_width.setRange(0.1, 5.0)
        self.spin_edge_width.setSingleStep(0.05)
        self.spin_edge_width.setDecimals(2)
        self.spin_edge_width.setValue(float(self.settings.get("edge_width", 1.0)))
        
        h_ew.addWidget(self.spin_edge_width)
        l_ext.addLayout(h_ew)

        v_frames.addWidget(g_ext)
        v_frames.addStretch()
        self.tabs.addTab(tab_frames, "Frames")

        tab_slabs = QWidget()
        v_slabs = QVBoxLayout(tab_slabs)
        
        h_sop = QHBoxLayout()
        h_sop.addWidget(QLabel("Slab Transparency:"))
        self.sl_slab_op = QSlider(Qt.Orientation.Horizontal)
        self.sl_slab_op.setRange(0, 100)
        self.sl_slab_op.setValue(int(self.settings.get("slab_opacity", 0.4) * 100))
        h_sop.addWidget(self.sl_slab_op)
        v_slabs.addLayout(h_sop)
        
        v_slabs.addStretch()
        self.tabs.addTab(tab_slabs, "Slabs")

        h_btns = QHBoxLayout()
        h_btns.addStretch()
        self.btn_ok = QPushButton("OK")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.clicked.connect(self.on_apply)
        
        h_btns.addWidget(self.btn_ok)
        h_btns.addWidget(self.btn_cancel)
        h_btns.addWidget(self.btn_apply)
        layout.addLayout(h_btns)

    def _on_aa_changed(self, val):
        labels = {0: "Off", 1: "4x", 2: "8x", 3: "16x"}
        self.lbl_aa.setText(labels[val])
        
    def _on_restart(self):
        import subprocess, sys, os
        
        parent = self.parent()
        
        if parent and hasattr(parent, "update_graphics_settings"):
            parent.update_graphics_settings(self.get_settings())
        
        file_path = None
        if parent and hasattr(parent, "model") and parent.model:
            file_path = getattr(parent.model, "file_path", None)

        if getattr(sys, 'frozen', False):
            args = [sys.executable]
        else:
            args = [sys.executable, os.path.abspath(sys.argv[0])]
            
        if file_path and os.path.exists(file_path):
            args.append(os.path.abspath(file_path))

        if parent:
            if not parent.close():
                                                                                             
                return 

        subprocess.Popen(args)
        self.accept()

    def get_settings(self):
        """Collects all values from widgets and returns the dict."""
        return {
            "background_color": self.btn_bg.get_color_tuple(),
            "msaa_level": self.sl_aa.value(),
            
            "node_size": self.spin_node_size.value(),
            "node_color": self.btn_node_col.get_color_tuple(),
            
            "line_width": self.spin_line_width.value(),
            
            "extrude_opacity": self.sl_ext_op.value() / 100.0,
            "show_edges": self.chk_edges.isChecked(),
            "edge_opacity": self.sl_edge_op.value() / 100.0,                      
            "edge_color": self.btn_edge_col.get_color_tuple(),
                                   
            "edge_width": self.spin_edge_width.value(),
            
            "slab_opacity": self.sl_slab_op.value() / 100.0,
        }

    def on_apply(self):
        if self.parent() and hasattr(self.parent(), "update_graphics_settings"):
            self.parent().update_graphics_settings(self.get_settings())
