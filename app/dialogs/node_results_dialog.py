from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGridLayout,
    QFrame, QSlider, QSpinBox, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.units import unit_registry

class NodeResultsDialog(QDialog):
    signal_mode_changed = pyqtSignal(str) 

    def __init__(self, node_id, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Joint {node_id} Results")
        self.setWindowFlags(Qt.WindowType.Tool) 
        self.resize(380, 300) 
        
        self.node_id = str(node_id)
        self.model = model
        self.results = model.results
        self.canvas = getattr(parent, 'canvas', None)
        self._syncing_scrubber = False

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
        
        self.scrubber_widget = QWidget()
        scrub_layout = QHBoxLayout(self.scrubber_widget)
        scrub_layout.setContentsMargins(0, 2, 0, 2)
        self.lbl_step_title = QLabel("Step:")
        self.lbl_step_title.setStyleSheet("font-weight: bold; color: #555;")
        self.slider_step = QSlider(Qt.Orientation.Horizontal)
        self.spin_step = QSpinBox()
        self.slider_step.valueChanged.connect(self._on_scrubber_changed)
        self.spin_step.valueChanged.connect(self._on_scrubber_changed)
        scrub_layout.addWidget(self.lbl_step_title)
        scrub_layout.addWidget(self.slider_step, 1)
        scrub_layout.addWidget(self.spin_step)
        self.scrubber_widget.setVisible(False)
        layout.addWidget(self.scrubber_widget)

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
        self.lbl_ux = QLabel("0.000000"); self.lbl_ux.setStyleSheet(val_style)
        self.lbl_uy = QLabel("0.000000"); self.lbl_uy.setStyleSheet(val_style)
        self.lbl_uz = QLabel("0.000000"); self.lbl_uz.setStyleSheet(val_style)
        
        self.lbl_rx = QLabel("0.000000"); self.lbl_rx.setStyleSheet(val_style)
        self.lbl_ry = QLabel("0.000000"); self.lbl_ry.setStyleSheet(val_style)
        self.lbl_rz = QLabel("0.000000"); self.lbl_rz.setStyleSheet(val_style)

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

        layout.addStretch()

    def load_initial_data(self):
        import os, glob, json
        self.combo_cases.blockSignals(True)
        self.combo_cases.clear()
        
        if not getattr(self.model, 'file_path', None):
            return 
            
        base_name = os.path.splitext(self.model.file_path)[0]
        result_files = getattr(self.model, 'valid_result_paths', [])
        if not result_files:
            result_files = glob.glob(f"{base_name}_*_results.json")
        
        current_case_name = self.results.get("info", {}).get("case_name", "")
        target_idx = 0

        for path in sorted(result_files):
            fname = os.path.basename(path)
            prefix = os.path.basename(base_name) + "_"
            case_name = fname[len(prefix):].replace("_results.json", "")
            
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
            except:
                continue

            info_type = data.get("info", {}).get("type", "")
            
            if info_type in ["Modal Analysis", "Buckling Analysis"]:
                shapes = data.get("mode_shapes", {})
                for mode_key in shapes.keys():
                    display_name = f"{case_name} - {mode_key}"
                    self.combo_cases.addItem(display_name, {"path": path, "mode": mode_key})
                    if case_name == current_case_name:
                        target_idx = self.combo_cases.count() - 1
            else:
                display_name = f"{case_name}"
                is_nl_multistep = (info_type == "Nonlinear Static" and bool(data.get("saved_states")))
                if "rsa_info" in data:
                    display_name += f" (RSA Envelope)"
                elif info_type == "Linear Time History Analysis":
                    display_name += f" (LTHA Envelope)"
                elif info_type == "Nonlinear Static":
                    geom_type = data.get("info", {}).get("geom_nonlin", "None")
                    display_name += f" ({geom_type})"
                      
                mode_for_item = "LTHA_LIVE" if is_nl_multistep else "MAIN"
                self.combo_cases.addItem(display_name, {"path": path, "mode": mode_for_item})
                if case_name == current_case_name:
                    target_idx = self.combo_cases.count() - 1

                if info_type == "Linear Time History Analysis":
                    self.combo_cases.addItem(f"{case_name} - LTHA Live", {"path": path, "mode": "LTHA_LIVE"})
                    if case_name == current_case_name and getattr(self.canvas, 'ltha_mode', False):
                        target_idx = self.combo_cases.count() - 1

        self.combo_cases.blockSignals(False)
        
        if self.combo_cases.count() > 0:
            self.combo_cases.setCurrentIndex(target_idx)
            self.on_case_changed(target_idx)
        else:
            self.lbl_info.setText("No results found for this node.")

    def on_case_changed(self, index):
        import json
        if index < 0: return
        
        canvas = getattr(self, 'canvas', None)
        if canvas:
            if hasattr(canvas, 'clear_force_diagrams'):
                canvas.clear_force_diagrams()
            if hasattr(canvas, 'clear_reaction_diagram'):
                canvas.clear_reaction_diagram(self.model)

        data_info = self.combo_cases.currentData()
        if not isinstance(data_info, dict): return

        if canvas and hasattr(canvas, 'set_selection_ltha_live'):
            canvas.set_selection_ltha_live(data_info["mode"] == "LTHA_LIVE")
        
        try:
            with open(data_info["path"], 'r') as f:
                new_res = json.load(f)
                if "displacements" in new_res:
                    new_res["_base_displacements"] = new_res["displacements"].copy()
                self.results = new_res
                self.model.results = new_res
        except:
            return
            
        key = data_info["mode"]
        vector = [0.0] * 6
        
        if key == "MAIN":
            self.scrubber_widget.setVisible(False)
            self.signal_mode_changed.emit("MAIN_RESULT") 
            base_dict = self.results.get("_base_displacements", self.results.get("displacements", {}))
            vector = base_dict.get(self.node_id, [0.0]*6)
            self.lbl_info.setText("Displaying Peak Static Envelope.")
            self._update_labels(vector)
            
        elif key == "LTHA_LIVE":
            self.signal_mode_changed.emit("LTHA_LIVE")
            saved_states = self.results.get("saved_states")
            if saved_states:
                n_steps = len(saved_states)
                self.lbl_step_title.setText("Step:")
                init_step = int(getattr(canvas, 'ltha_current_step', n_steps - 1)) if canvas else (n_steps - 1)
            else:
                n_steps = int(getattr(canvas, 'ltha_n_steps', 1)) if canvas else 1
                self.lbl_step_title.setText("Step:")
                init_step = int(getattr(canvas, 'ltha_current_step', 0)) if canvas else 0

            init_step = max(0, min(init_step, max(n_steps - 1, 0)))
            self._syncing_scrubber = True
            for w in (self.slider_step, self.spin_step):
                w.setRange(0, max(n_steps - 1, 0))
                w.setValue(init_step)
            self._syncing_scrubber = False
            self.scrubber_widget.setVisible(n_steps > 1)
            self.update_live_values(init_step)

        elif str(key).startswith("Mode"):
            self.scrubber_widget.setVisible(False)
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

    def _on_scrubber_changed(self, value):
        if self._syncing_scrubber:
            return
        self._syncing_scrubber = True
        self.slider_step.setValue(value)
        self.spin_step.setValue(value)
        self._syncing_scrubber = False

        self.update_live_values(int(value))

        canvas = getattr(self, 'canvas', None)
        mgr = getattr(canvas, 'animation_manager', None) if canvas else None
        if mgr and getattr(canvas, 'ltha_mode', False):
            self._syncing_scrubber = True
            try:
                mgr.scrub_to_step(int(value))
            finally:
                self._syncing_scrubber = False
        
    def _update_labels(self, vector):
        ux_m, uy_m, uz_m = vector[0], vector[1], vector[2]
        rx, ry, rz = vector[3], vector[4], vector[5]

        ux_disp = unit_registry.to_display_length(ux_m)
        uy_disp = unit_registry.to_display_length(uy_m)
        uz_disp = unit_registry.to_display_length(uz_m)

        def fmt(val):
            return f"{val:.6f}"

        self.lbl_ux.setText(fmt(ux_disp))
        self.lbl_uy.setText(fmt(uy_disp))
        self.lbl_uz.setText(fmt(uz_disp))
        
        self.lbl_rx.setText(fmt(rx))
        self.lbl_ry.setText(fmt(ry))
        self.lbl_rz.setText(fmt(rz))

    def update_live_values(self, t_index=None):
        data_info = self.combo_cases.currentData()
        if not isinstance(data_info, dict) or data_info.get("mode") != "LTHA_LIVE":
            return

        canvas = getattr(self, 'canvas', None)
        if t_index is None:
            t_index = self.spin_step.value()
        t_index = int(t_index)

        if not self._syncing_scrubber:
            self._syncing_scrubber = True
            self.slider_step.setValue(max(0, min(t_index, self.slider_step.maximum())))
            self.spin_step.setValue(max(0, min(t_index, self.spin_step.maximum())))
            self._syncing_scrubber = False

        saved_states = self.results.get("saved_states")
        if saved_states and 0 <= t_index < len(saved_states):
            st = saved_states[t_index]
            vector = st.get("displacements", {}).get(self.node_id, [0.0]*6)
            step_no = st.get("step", t_index + 1)
            step_frac = st.get("step_frac")
            frac_txt = f"  —  Load Frac: {step_frac:.3f}" if step_frac is not None else ""
            self.lbl_info.setText(f"Step {step_no} ({t_index + 1} of {len(saved_states)}){frac_txt}")
            self._update_labels(vector)
            return

        if canvas is not None:
            dt = float(getattr(canvas, 'ltha_dt', 0.01))
            n_steps = int(getattr(canvas, 'ltha_n_steps', 0))
            if hasattr(canvas, 'ltha_tensor') and canvas.ltha_tensor is not None and hasattr(canvas, 'ltha_node_map'):
                node_idx = canvas.ltha_node_map.get(self.node_id)
                if node_idx is not None and 0 <= t_index < canvas.ltha_tensor.shape[1]:
                    self.lbl_info.setText(f"Live Timestep: t = {t_index * dt:.3f} s ({t_index + 1} of {n_steps})")
                    self._update_labels(canvas.ltha_tensor[node_idx, t_index, :])
                    return
            ltha_hist = getattr(canvas, 'ltha_history', None) or {}
            if self.node_id in ltha_hist and 0 <= t_index < len(ltha_hist[self.node_id]):
                self.lbl_info.setText(f"Live Timestep: t = {t_index * dt:.3f} s ({t_index + 1} of {n_steps})")
                self._update_labels(ltha_hist[self.node_id][t_index])
                return

        vector = self.results.get("displacements", {}).get(self.node_id, [0.0]*6)
        self._update_labels(vector)
