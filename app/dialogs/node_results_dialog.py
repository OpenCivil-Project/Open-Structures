from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGridLayout, QFrame, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from core.units import unit_registry

class NodeResultsDialog(QDialog):
    signal_mode_changed = pyqtSignal(str) 

    def __init__(self, node_id, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Joint {node_id} Results")
        self.setWindowFlags(Qt.WindowType.Tool) 
        self.resize(350, 260) 
        
        self.node_id = str(node_id)
        self.model = model
        self.results = model.results
        self._graph_dlg = None

        self.init_ui()
        self.load_initial_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        top_layout = QHBoxLayout()
        lbl_case = QLabel("Load Case/Mode:")
        lbl_case.setStyleSheet("font-weight: bold; color: #555;")
        self.combo_cases = QComboBox()
        self.combo_cases.currentIndexChanged.connect(self.on_case_changed)
        top_layout.addWidget(lbl_case)
        top_layout.addWidget(self.combo_cases)
        layout.addLayout(top_layout)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        grid = QGridLayout()
        grid.setSpacing(10)
        
        len_unit = unit_registry.length_unit_name                     
        
        self.txt_ux = QLabel(f"Trans X [{len_unit}]:")
        self.txt_uy = QLabel(f"Trans Y [{len_unit}]:")
        self.txt_uz = QLabel(f"Trans Z [{len_unit}]:")
        
        self.txt_rx = QLabel("Rot X [rad]:") 
        self.txt_ry = QLabel("Rot Y [rad]:") 
        self.txt_rz = QLabel("Rot Z [rad]:") 

        val_style = "color: #0078D7; font-family: Consolas; font-weight: bold; font-size: 11pt;"
        self.lbl_ux = QLabel("0.0000"); self.lbl_ux.setStyleSheet(val_style)
        self.lbl_uy = QLabel("0.0000"); self.lbl_uy.setStyleSheet(val_style)
        self.lbl_uz = QLabel("0.0000"); self.lbl_uz.setStyleSheet(val_style)
        
        self.lbl_rx = QLabel("0.0000"); self.lbl_rx.setStyleSheet(val_style)
        self.lbl_ry = QLabel("0.0000"); self.lbl_ry.setStyleSheet(val_style)
        self.lbl_rz = QLabel("0.0000"); self.lbl_rz.setStyleSheet(val_style)

        for lbl in [self.lbl_ux, self.lbl_uy, self.lbl_uz, self.lbl_rx, self.lbl_ry, self.lbl_rz]:
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        grid.addWidget(self.txt_ux, 0, 0); grid.addWidget(self.lbl_ux, 0, 1)
        grid.addWidget(self.txt_uy, 1, 0); grid.addWidget(self.lbl_uy, 1, 1)
        grid.addWidget(self.txt_uz, 2, 0); grid.addWidget(self.lbl_uz, 2, 1)
        
        grid.addWidget(self.txt_rx, 0, 2); grid.addWidget(self.lbl_rx, 0, 3)
        grid.addWidget(self.txt_ry, 1, 2); grid.addWidget(self.lbl_ry, 1, 3)
        grid.addWidget(self.txt_rz, 2, 2); grid.addWidget(self.lbl_rz, 2, 3)
        
        layout.addLayout(grid)
        
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color: #666; font-size: 11px; margin-top: 10px;")
        self.lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_info)

        self.btn_graph = QPushButton("Nodal Time History Graph")
        self.btn_graph.setVisible(False)
        self.btn_graph.clicked.connect(self._open_graph)
        layout.addWidget(self.btn_graph)

        layout.addStretch()

    def load_initial_data(self):
        self.combo_cases.blockSignals(True)
        self.combo_cases.clear()
        
        info_type = self.results.get("info", {}).get("type", "")
        is_eigenvalue_run = info_type in ["Modal Analysis", "Buckling Analysis"]
        
        if "displacements" in self.results and self.results["displacements"] and not is_eigenvalue_run:
            display_name = "Analysis Result"
            if "rsa_info" in self.results:
                method = self.results["rsa_info"].get("method", "SRSS")
                display_name = f"RSA Final Envelope ({method})"
            elif info_type == "Linear Static":
                display_name = "Linear Static Displacements"
            elif info_type == "Linear Time History Analysis":
                display_name = "LTHA Peak Envelope"
            
            self.combo_cases.addItem(display_name, "MAIN_RESULT")

            if info_type == "Linear Time History Analysis":
                self.combo_cases.addItem("LTHA Live Playback", "LTHA_LIVE")

        if "mode_shapes" in self.results:
            if info_type == "Buckling Analysis":
                factors = self.results.get("tables", {}).get("buckling_factors", [])
                for row in factors:
                    mode_num = row['mode']
                    lam = row['lambda']
                    self.combo_cases.addItem(f"Mode {mode_num} (λ = {lam:.4f})", f"Mode {mode_num}")
            else:
                periods = self.results.get("tables", {}).get("periods", [])
                for row in periods:
                    mode_num = row['mode']
                    T = row['T']
                    self.combo_cases.addItem(f"Mode {mode_num} (T={T:.4f}s)", f"Mode {mode_num}")

        self.combo_cases.blockSignals(False)
        
        if self.combo_cases.count() > 0:
            self.on_case_changed(0)
        else:
            self.lbl_info.setText("No results found for this node.")

    def on_case_changed(self, index):
        if index < 0: return
        key = self.combo_cases.currentData()
        vector = [0.0] * 6
        
        if key == "MAIN_RESULT":
            self.signal_mode_changed.emit("MAIN_RESULT") 
            self.btn_graph.setVisible(False)
                                                                                          
            base_dict = self.results.get("_base_displacements", self.results.get("displacements", {}))
            vector = base_dict.get(self.node_id, [0.0]*6)
            self.lbl_info.setText("Displaying Peak Static Envelope.")
            
        elif key == "LTHA_LIVE":
            self.signal_mode_changed.emit("LTHA_LIVE")        
            vector = self.results.get("displacements", {}).get(self.node_id, [0.0]*6)
            self.lbl_info.setText("Displaying Live Timestep.")
            self.btn_graph.setVisible(True)

        elif str(key).startswith("Mode"):
            shapes = self.results.get("mode_shapes", {})
            mode_data = shapes.get(key, {})
            vector = mode_data.get(self.node_id, [0.0]*6)
            
            info_type = self.results.get("info", {}).get("type", "")
            if info_type == "Buckling Analysis":
                self.lbl_info.setText("Displaying Buckling Mode Shape.")
            else:
                self.lbl_info.setText("Displaying Normalized Mode Shape.")
                
            self.signal_mode_changed.emit(key)
            
        self._update_labels(vector)

    def _update_labels(self, vector):
        ux_m, uy_m, uz_m = vector[0], vector[1], vector[2]
        rx, ry, rz = vector[3], vector[4], vector[5]

        ux_disp = unit_registry.to_display_length(ux_m)
        uy_disp = unit_registry.to_display_length(uy_m)
        uz_disp = unit_registry.to_display_length(uz_m)

        def fmt(val):
            if abs(val) < 1e-10: return "0.0000"
            if abs(val) < 1e-4: return f"{val:.4e}"
            return f"{val:.4f}"

        self.lbl_ux.setText(fmt(ux_disp))
        self.lbl_uy.setText(fmt(uy_disp))
        self.lbl_uz.setText(fmt(uz_disp))
        
        self.lbl_rx.setText(fmt(rx))
        self.lbl_ry.setText(fmt(ry))
        self.lbl_rz.setText(fmt(rz))

    def _open_graph(self):
        """Open (or raise) the time history graph dialog."""
        canvas = getattr(self, 'canvas', None)
        if canvas is None:
            return
        if self._graph_dlg is None or not self._graph_dlg.isVisible():
            from app.dialogs.ltha_node_graph_dialog import LTHANodeGraphDialog
            self._graph_dlg = LTHANodeGraphDialog(self.node_id, canvas, parent=self)
                                                                                     
            canvas.animation_manager.signal_ltha_frame_update.connect(
                self._graph_dlg.update_cursor)
                                                     
            self._graph_dlg.finished.connect(
                lambda: canvas.animation_manager.signal_ltha_frame_update.disconnect(
                    self._graph_dlg.update_cursor))
            self._graph_dlg.show()
        else:
            self._graph_dlg.raise_()
            self._graph_dlg.activateWindow()

    def update_graph_cursor(self, t_index):
        """Forward animation tick to graph dialog if it's open."""
        if self._graph_dlg is not None and self._graph_dlg.isVisible():
            self._graph_dlg.update_cursor(t_index)

    def update_live_values(self, t_index=None):
        if self.combo_cases.currentData() != "LTHA_LIVE":
            return

        canvas = getattr(self, 'canvas', None)

        if canvas is not None and not getattr(canvas.animation_manager, 'is_running', True):
            return

        if (t_index is not None
                and canvas is not None
                and hasattr(canvas, 'ltha_tensor')
                and hasattr(canvas, 'ltha_node_map')):
                                                                                             
            node_idx = canvas.ltha_node_map.get(self.node_id)
            if node_idx is not None:
                self._update_labels(canvas.ltha_tensor[node_idx, t_index, :])
                return

        vector = self.results.get("displacements", {}).get(self.node_id, [0.0]*6)
        self._update_labels(vector)
