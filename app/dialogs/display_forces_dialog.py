from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QRadioButton, QGroupBox, QLineEdit, 
                             QPushButton, QGridLayout, QWidget, QSpinBox, QComboBox,
                             QScrollArea, QFrame, QSlider)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from app.ui.theme import apply_dialog_style
from app.result_file_loader import ResultFileLoader
from core.result_file_cache import get_cached_json
from core.opensees_port.os_force_recovery import is_opensees_result

STEP_SLIDER_MAX_STEPS = 50000

class DisplayForcesDialog(QDialog):
    last_settings = {}
                                                                            
    apply_forces_signal = pyqtSignal(dict)

    def __init__(self, model, parent=None, available_cases=None, base_path=''):
        super().__init__(parent)
        apply_dialog_style(self)
        self.model = model
        self.available_cases = available_cases or []
        self.base_path = base_path
        self._result_loader = None
        self._pending_result_case = None
        self._result_request_token = 0
        self._loading_result = False
        self._initializing_result = True
        self._restore_settings_after_load = True
        self.setWindowTitle("Display Frame Forces/Stresses")
        self.setMinimumWidth(450)
        self.setMinimumHeight(300)
        self.resize(480, 650)
        
        self.init_ui()
        self.load_last_settings()
        self._initializing_result = False
        self._set_result_loading(self._loading_result)

    def init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        scroll.setWidget(content)
        outer_layout.addWidget(scroll, 1)

        main_layout = QVBoxLayout(content)

        main_layout.setSpacing(4) 
        main_layout.setContentsMargins(10, 10, 10, 10) 
        
        gb_case = QGroupBox("Load Case / Combination")
        layout_case = QHBoxLayout(gb_case)

        layout_case.setSpacing(4)
        layout_case.setContentsMargins(5, 10, 5, 5) 
        
        self.cb_case = QComboBox()

        gb_case = QGroupBox("Load Case / Combination")
        layout_case = QHBoxLayout(gb_case)
        self.cb_case = QComboBox()
        
        valid_cases = []
        self._case_types = {}          
        
        import os, glob
        if hasattr(self.model, 'file_path') and self.model.file_path:
            base_path = self.model.file_path.replace(".mf", "")
            search_pattern = f"{base_path}_*_results.json"
            
            for file_path in glob.glob(search_pattern):
                filename = os.path.basename(file_path)
                prefix = os.path.basename(base_path) + "_"
                case_name = filename[len(prefix):].replace("_results.json", "")
                
                base_case = case_name.rsplit(" (Max)", 1)[0].rsplit(" (Min)", 1)[0]
                
                is_valid = False
                c_type = 'Linear Static'
                if hasattr(self.model, 'load_cases') and base_case in self.model.load_cases:
                    c_type = getattr(self.model.load_cases[base_case], 'case_type', 'Linear Static')
                    if c_type not in ["Modal", "Buckling"]:
                        is_valid = True
                elif hasattr(self.model, 'load_combos') and base_case in self.model.load_combos:
                    c_type = 'Load Combination'
                    is_valid = True
                        
                if is_valid and case_name not in valid_cases:
                    valid_cases.append(case_name)
                    self._case_types[case_name] = c_type
                    
            valid_cases.sort()
        else:
                                                       
            for c_name in self.available_cases:
                is_valid = False
                c_type = 'Linear Static'
                if hasattr(self.model, 'load_cases') and c_name in self.model.load_cases:
                    c_type = getattr(self.model.load_cases[c_name], 'case_type', 'Linear Static')
                    if c_type not in ["Modal", "Buckling"]:
                        is_valid = True
                elif hasattr(self.model, 'load_combos') and c_name in self.model.load_combos:
                    c_type = 'Load Combination'
                    is_valid = True
                    
                if is_valid:
                    valid_cases.append(c_name)
                    self._case_types[c_name] = c_type
                                                                                           
        self.cb_case.addItems(valid_cases)
        
        current_case = ""
        if hasattr(self.model, 'results') and self.model.results:
            current_case = self.model.results.get("info", {}).get("case_name", "")
        if current_case in valid_cases:
            self.cb_case.setCurrentText(current_case)

        if len(valid_cases) <= 1:
            self.cb_case.setEnabled(False)

        self._results_base_path = None
        if hasattr(self.model, 'file_path') and self.model.file_path:
            self._results_base_path = self.model.file_path.replace(".mf", "")
        elif self.base_path:
            self._results_base_path = self.base_path

        layout_case.addWidget(self.cb_case)
        main_layout.addWidget(gb_case)

        self.force_source_label = QLabel()
        main_layout.addWidget(self.force_source_label)
        self._update_force_source_label(self.cb_case.currentText())
        
        self.gb_multi = QGroupBox("Multivalued Options")
        grid_multi = QGridLayout(self.gb_multi)
        
        self.rb_envelope = QRadioButton("Envelope (Max or Min)")
        self.rb_step = QRadioButton("Step")
        self.rb_step.setChecked(True)
        
        self.sb_step = QSpinBox()
        self.sb_step.setMinimum(1)
        self.sb_step.setMaximum(1)          
        
        grid_multi.addWidget(self.rb_envelope, 0, 0)
        grid_multi.addWidget(self.rb_step, 1, 0)
        grid_multi.addWidget(self.sb_step, 1, 1)
        self.saved_state_label = QLabel()
        self.saved_state_label.setWordWrap(True)
        self.sl_step = QSlider(Qt.Orientation.Horizontal)
        self.sl_step.setRange(1, 1)
        self.sl_step.setPageStep(1)
        self.sl_step.setVisible(False)
        self.sl_step.valueChanged.connect(self.sb_step.setValue)
        grid_multi.addWidget(self.sl_step, 2, 0, 1, 2)
        grid_multi.addWidget(self.saved_state_label, 3, 0, 1, 2)
        self.sb_step.valueChanged.connect(self._update_saved_state_details)
        self.rb_step.toggled.connect(self._update_saved_state_details)
        
        main_layout.addWidget(self.gb_multi)

        self._update_multivalued_box(self.cb_case.currentText())
        self._sync_step_slider()
        self.cb_case.currentTextChanged.connect(self._on_case_changed)

        gb_type = QGroupBox("Display Type")
        layout_type = QHBoxLayout(gb_type)
        
        self.rb_force = QRadioButton("Force")
        self.rb_stress = QRadioButton("Stress")
        self.rb_force.setChecked(True)
        
        layout_type.addWidget(self.rb_force)
        layout_type.addWidget(self.rb_stress)
        
        main_layout.addWidget(gb_type)

        gb_comp = QGroupBox("Component")
        grid_comp = QGridLayout(gb_comp)
        
        self.rb_axial = QRadioButton("Axial Force")
        self.rb_torsion = QRadioButton("Torsion")
        self.rb_shear22 = QRadioButton("Shear 3-3")
        self.rb_shear33 = QRadioButton("Shear 2-2")
        self.rb_moment22 = QRadioButton("Moment 3-3")
        self.rb_moment33 = QRadioButton("Moment 2-2")
        
        self.rb_moment33.setChecked(True)
        
        grid_comp.addWidget(self.rb_axial, 0, 0)
        grid_comp.addWidget(self.rb_torsion, 0, 1)
        grid_comp.addWidget(self.rb_shear22, 1, 0)
        grid_comp.addWidget(self.rb_moment22, 1, 1)
        grid_comp.addWidget(self.rb_shear33, 2, 0)
        grid_comp.addWidget(self.rb_moment33, 2, 1)
        
        main_layout.addWidget(gb_comp)

        gb_scale = QGroupBox("Scaling for Diagram")
        grid_scale = QGridLayout(gb_scale)
        
        self.rb_auto_scale = QRadioButton("Automatic")
        self.rb_user_scale = QRadioButton("User Defined")
        self.rb_auto_scale.setChecked(True)
        
        self.le_scale_value = QLineEdit()
        self.le_scale_value.setEnabled(False)
        
        self.rb_auto_scale.toggled.connect(lambda: self.le_scale_value.setEnabled(self.rb_user_scale.isChecked()))
        
        grid_scale.addWidget(self.rb_auto_scale, 0, 0)
        grid_scale.addWidget(self.rb_user_scale, 1, 0)
        grid_scale.addWidget(self.le_scale_value, 1, 1)
        
        main_layout.addWidget(gb_scale)

        gb_options = QGroupBox("Options for Diagram")
        layout_options = QVBoxLayout(gb_options)
        
        row_opts = QHBoxLayout()
        self.rb_fill = QRadioButton("Fill Diagram")
        self.rb_show_values = QRadioButton("Show Values")
        self.rb_fill.setChecked(True)
        row_opts.addWidget(self.rb_fill)
        row_opts.addWidget(self.rb_show_values)
        layout_options.addLayout(row_opts)

        self.widget_show_sub = QWidget()
        sub_layout = QHBoxLayout(self.widget_show_sub)
        sub_layout.setContentsMargins(20, 0, 0, 0)                  
        self.rb_show_all = QRadioButton("Show All")
        self.rb_show_sel = QRadioButton("Show on Select")
        self.rb_show_all.setChecked(True)
        sub_layout.addWidget(self.rb_show_all)
        sub_layout.addWidget(self.rb_show_sel)
        self.widget_show_sub.setEnabled(False)
        
        self.rb_show_values.toggled.connect(self.widget_show_sub.setVisible)
        self.rb_show_values.toggled.connect(self.widget_show_sub.setEnabled)
        layout_options.addWidget(self.widget_show_sub)
        
        main_layout.addWidget(gb_options)

        gb_text = QGroupBox("Text Size")
        grid_text = QGridLayout(gb_text)
        
        self.rb_auto_text = QRadioButton("Automatic")
        self.rb_user_text = QRadioButton("User Defined")
        self.rb_auto_text.setChecked(True)
        
        self.le_text_value = QLineEdit()
        self.le_text_value.setEnabled(False)
        self.rb_user_text.toggled.connect(self.le_text_value.setEnabled)
        
        grid_text.addWidget(self.rb_auto_text, 0, 0)
        grid_text.addWidget(self.rb_user_text, 1, 0)
        grid_text.addWidget(self.le_text_value, 1, 1)
        
        main_layout.addWidget(gb_text)

        layout_btns = QVBoxLayout()
        
        self.btn_reset_default = QPushButton("Reset Form to Default Values")
        self.btn_reset_window = QPushButton("Reset Form to Current Window Settings")
        self.btn_reset_window.setEnabled(False)              
        
        layout_btns.addWidget(self.btn_reset_default)
        layout_btns.addWidget(self.btn_reset_window)
        
        main_layout.addLayout(layout_btns)

        layout_bottom_btns = QHBoxLayout()
        
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setObjectName("primary")
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("secondary")
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setObjectName("secondary")
        
        layout_bottom_btns.addWidget(self.btn_ok)
        layout_bottom_btns.addWidget(self.btn_close)
        layout_bottom_btns.addWidget(self.btn_apply)
        
        footer = QWidget()
        footer.setLayout(layout_bottom_btns)
        layout_bottom_btns.setContentsMargins(10, 6, 10, 10)
        outer_layout.addWidget(footer)

        self.btn_close.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self.apply_settings)
        self.btn_ok.clicked.connect(self.on_ok)

    def _update_force_source_label(self, case_name):
        """Identify the selected saved result without changing analysis settings."""
        self._result_request_token += 1
        self._pending_result_case = None
        self.is_opensees = False
        self._selected_case_results = {}
        self._opensees_saved_states = []
        data = getattr(self.model, 'results', {}) or {}
        if self._results_base_path:
            path = f"{self._results_base_path}_{case_name}_results.json"
            try:
                data = get_cached_json(path)
            except (OSError, ValueError):
                self._show_result_unavailable()
                return
            if data is None:
                self._set_result_loading(True)
                self.force_source_label.setText('Loading saved result…')
                self._pending_result_case = (case_name, path, self._result_request_token)
                self._start_pending_result_load()
                return
        elif not data or data.get('info', {}).get('case_name') != case_name:
            self._show_result_unavailable()
            return
        self._accept_case_result(data)

    def _set_result_loading(self, loading):
        self._loading_result = loading
        for name in ('btn_apply', 'btn_ok'):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(not loading)

    def _show_result_unavailable(self):
        self._set_result_loading(False)
        self.force_source_label.setText('Force recovery: result unavailable')
        self.setWindowTitle('Display Frame Forces/Stresses')

    def _accept_case_result(self, data):
        self._set_result_loading(False)
        self.is_opensees = is_opensees_result(data, self.model)
        self._selected_case_results = data
        if self.is_opensees:
            self._opensees_saved_states = data.get('saved_states') or []
        engine = 'OpenSees' if self.is_opensees else 'Native'
        self.force_source_label.setText(f'Force recovery: {engine}')
        self.setWindowTitle(f'Display Frame Forces/Stresses [{engine}]')

    def _start_pending_result_load(self):
        if self._result_loader is not None or self._pending_result_case is None:
            return
        case_name, path, token = self._pending_result_case
        self._pending_result_case = None
        loader = ResultFileLoader(path)
        loader.case_name, loader.token = case_name, token
        loader.signals.finished.connect(self._on_result_loaded)
        self._result_loader = loader
        loader.start()

    def _on_result_loaded(self, loader, path, data, error):
        self._result_loader = None
        if loader.token == self._result_request_token:
            if error is not None or not isinstance(data, dict):
                self._show_result_unavailable()
            else:
                self._accept_case_result(data)
                self._update_multivalued_box(loader.case_name)
                if self._restore_settings_after_load:
                    self.load_last_settings()
                self._sync_step_slider()
        self._start_pending_result_load()

    def _on_case_changed(self, case_name):
        self._restore_settings_after_load = self._initializing_result
        self._update_force_source_label(case_name)
        self._update_multivalued_box(case_name)
        self._sync_step_slider()

    def _sync_step_slider(self):
        """Mirror the step spin box on a slider; hide it when the step list is huge."""
        n = self.sb_step.maximum()
        was_blocked = self.sl_step.blockSignals(True)
        self.sl_step.setRange(1, max(1, n))
        self.sl_step.setValue(self.sb_step.value())
        self.sl_step.setTickInterval(max(1, n // 20))
        self.sl_step.setPageStep(max(1, n // 100))
        self.sl_step.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sl_step.blockSignals(was_blocked)
        self.sl_step.setVisible(2 <= n <= STEP_SLIDER_MAX_STEPS)
        self.sl_step.setEnabled(self.sb_step.isEnabled())

    def _update_saved_state_details(self, *args):
        self._refresh_saved_state_details()
        self._sync_step_slider()

    def _refresh_saved_state_details(self):
        if not getattr(self, '_opensees_nonlinear', False):
            return
        states = self._opensees_saved_states
        self.sb_step.setEnabled(bool(states) and self.rb_step.isChecked())
        if not states:
            self.saved_state_label.setText('No saved states in this result. Run with Multiple States to inspect individual steps.')
        elif not self.rb_step.isChecked():
            self.saved_state_label.setText(f'Final converged state. {len(states)} saved states available.')
        else:
            index = self.sb_step.value() - 1
            state = states[index] if isinstance(states[index], dict) else {}
            text = f'Saved state {index + 1} of {len(states)} — analysis step {state.get("step", index + 1)}'
            if 'opensees_forces' not in state:
                text += '. Forces missing: rerun this analysis to save step forces.'
            self.saved_state_label.setText(text)

    def _update_multivalued_box(self, case_name):
        """Expose saved nonlinear states without changing native LTHA options."""
        c_type = self._case_types.get(case_name, 'Linear Static')
        result_type = self._selected_case_results.get('info', {}).get('type', c_type)
        self._opensees_nonlinear = self.is_opensees and result_type == 'Nonlinear Static'
        self.saved_state_label.setVisible(self._opensees_nonlinear)
        if self._opensees_nonlinear:
            self.gb_multi.setTitle('Nonlinear Saved States')
            self.gb_multi.setVisible(True)
            self.rb_envelope.setText('Final converged state')
            self.rb_step.setText('Saved state')
            self.rb_step.setEnabled(bool(self._opensees_saved_states))
            self.rb_envelope.setChecked(True)
            self.sb_step.setMaximum(max(1, len(self._opensees_saved_states)))
            self.sb_step.setValue(max(1, len(self._opensees_saved_states)))
            self._update_saved_state_details()
            return

        self.gb_multi.setTitle('Multivalued Options')
        self.rb_envelope.setText('Envelope (Max or Min)')
        self.rb_step.setText('Step')
        self.rb_step.setEnabled(True)
        self.sb_step.setEnabled(True)
        is_ltha = (c_type == 'LTHA')
        self.gb_multi.setVisible(is_ltha)

        if not is_ltha or not self._results_base_path:
            return

        try:
            n_steps = self._selected_case_results.get("info", {}).get("n_steps", 1)
            self.sb_step.setMaximum(max(1, int(n_steps)))
        except (TypeError, ValueError):
                                                                            
            self.sb_step.setMaximum(1)

    def get_current_settings(self):
        """Reads the UI and packages the user's choices into a dictionary."""
                                                  
        component = 'M3'          
        if self.rb_axial.isChecked(): component = 'P'
        elif self.rb_torsion.isChecked(): component = 'T'
        elif self.rb_shear22.isChecked(): component = 'V2'
        elif self.rb_shear33.isChecked(): component = 'V3'
        elif self.rb_moment22.isChecked(): component = 'M2'
        elif self.rb_moment33.isChecked(): component = 'M3'
        
        scale_factor = None
        if self.rb_user_scale.isChecked():
            try:
                scale_factor = float(self.le_scale_value.text())
            except ValueError:
                scale_factor = None                                                 
                
        show_labels = self.rb_show_values.isChecked()
        style = 'show_values' if show_labels else 'fill'

        show_labels_mode = 'selected' if self.rb_show_sel.isChecked() else 'all'
        
        text_size = None
        if self.rb_user_text.isChecked():
            try:
                text_size = float(self.le_text_value.text())
            except ValueError:
                text_size = None

        load_case = self.cb_case.currentText()

        is_envelope = self.rb_envelope.isChecked()
        step_number = self.sb_step.value() if not is_envelope else None
        if self.is_opensees:
            if not (self._opensees_nonlinear and self._opensees_saved_states and self.rb_step.isChecked()):
                step_number = None
                                                                            
            is_envelope = step_number is None

        return {
            'component': component,
            'scale_factor': scale_factor,
            'style': style,
            'load_case': load_case,
            'base_path': self.base_path,
            'show_labels': show_labels,
            'show_labels_mode': show_labels_mode,
            'text_size': text_size,
            'is_envelope': is_envelope,
            'step_number': step_number,
        }
    
    def load_last_settings(self):
        """Restore previous dialog values."""
        s = DisplayForcesDialog.last_settings

        if not s:
            return
        
        if s.get("load_case"):
            idx = self.cb_case.findText(s["load_case"])
            if idx >= 0:
                self.cb_case.setCurrentIndex(idx)

        if s.get("scale_factor") is not None:
            self.rb_user_scale.setChecked(True)
            self.le_scale_value.setText(str(s["scale_factor"]))
        else:
            self.rb_auto_scale.setChecked(True)

        if s.get("text_size") is not None:
            self.rb_user_text.setChecked(True)
            self.le_text_value.setText(str(s["text_size"]))
        else:
            self.rb_auto_text.setChecked(True)

        if s.get("show_labels"):
            self.rb_show_values.setChecked(True)

            if s.get("show_labels_mode") == "selected":
                self.rb_show_sel.setChecked(True)
            else:
                self.rb_show_all.setChecked(True)
        else:
            self.rb_fill.setChecked(True)

        if s.get("is_envelope"):
            self.rb_envelope.setChecked(True)
        else:
            self.rb_step.setChecked(True)
            if s.get("step_number") is not None:
                self.sb_step.setValue(int(s["step_number"]))

        component = s.get("component", "M3")

        if component == "P":
            self.rb_axial.setChecked(True)
        elif component == "T":                                   
            self.rb_torsion.setChecked(True)
        elif component == "V2":
            self.rb_shear22.setChecked(True)
        elif component == "V3":
            self.rb_shear33.setChecked(True)
        elif component == "M2":
            self.rb_moment22.setChecked(True)
        else:
            self.rb_moment33.setChecked(True)

        if self.is_opensees and self._opensees_nonlinear and not self._opensees_saved_states:
            self.rb_envelope.setChecked(True)
        self._update_saved_state_details()

    def save_last_settings(self):
        """Save current dialog values."""
        DisplayForcesDialog.last_settings = self.get_current_settings()

    def apply_settings(self):
        """Fires the signal to main.py without closing the window."""
        if self._loading_result:
            return
        settings = self.get_current_settings()
        self.save_last_settings()   
                                                               
        self.apply_forces_signal.emit(settings)

    def on_ok(self):
        """Fires the signal and closes the window."""
        self.apply_settings()
        self.accept()
