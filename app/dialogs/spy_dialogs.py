import sys
import json
import os
import numpy as np
import functools
import copy
from core.result_file_cache import load_json_cached

def get_cached_matrices(path):
    if not os.path.exists(path): return {}
    return load_json_cached(path)
    
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QLabel, QWidget, QComboBox, QSlider,
                             QScrollArea, QFrame, QPushButton)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.text import Text as MplText
from mpl_toolkits.mplot3d import Axes3D

from core.units import unit_registry
from app.ui.theme import (
    apply_dialog_style, style_plot_axes, on_theme_changed, off_theme_changed,
    COLORS as THEME,
)
from core.opensees_port.os_force_recovery import (
    is_opensees_result, recover_member_forces, select_opensees_force_state,
)
from PyQt6.QtCore import Qt, pyqtSignal

def _load_combination_name(results, model):
    """Resolve a combination before interpreting inherited solver metadata."""
    name = (results or {}).get('info', {}).get('case_name', '')
    combos = getattr(model, 'load_combos', {}) or {}
    if name in combos:
        return name
    for suffix in (' (Max)', ' (Min)'):
        if name.endswith(suffix) and name[:-len(suffix)] in combos:
            return name[:-len(suffix)]
    return None

def _force_state_label(results, step_number):
    """Describe the saved-state ordinal separately from the solver step."""
    if step_number is None:
        return 'Final state'
    label = f'Saved state {step_number}'
    states = results.get('saved_states') or []
    index = int(step_number) - 1
    if 0 <= index < len(states) and isinstance(states[index], dict):
        solver_step = states[index].get('step')
        if solver_step is not None:
            label += f' — step {solver_step}'
    return label

def _populate_force_state_combo(combo, results, step_number=None):
    """Populate once per case; changing a selection never rebuilds this control."""
    was_blocked = combo.blockSignals(True)
    try:
        combo.clear()
        combo.addItem('Final state', None)
        for ordinal, state in enumerate(results.get('saved_states') or [], start=1):
            label = _force_state_label(results, ordinal)
            if not isinstance(state, dict) or not isinstance(state.get('opensees_forces'), dict):
                label += ' (forces unavailable)'
            combo.addItem(label, ordinal)
        index = combo.findData(step_number) if step_number is not None else 0
        if index < 0:
                                                                              
            combo.addItem(f'{_force_state_label(results, step_number)} (unavailable)', step_number)
            index = combo.count() - 1
        combo.setCurrentIndex(index)
        combo.setEnabled(combo.count() > 1)
    finally:
        combo.blockSignals(was_blocked)

STATE_SLIDER_MAX_STATES = 50000

def _slider_qss():
    """Slider look built from the live theme colours (QSlider is not in the master stylesheet)."""
    return f"""
        QSlider::groove:horizontal {{ height: 6px; background: {THEME['border']}; border-radius: 3px; }}
        QSlider::handle:horizontal {{ background: {THEME['accent']}; border: 1px solid {THEME['accent_pressed']};
                                     width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; }}
        QSlider::sub-page:horizontal {{ background: {THEME['accent']}; border-radius: 3px; }}
        QSlider::groove:horizontal:disabled {{ background: {THEME['border_light']}; }}
        QSlider::handle:horizontal:disabled {{ background: {THEME['text_disabled']}; border-color: {THEME['text_disabled']}; }}
        QSlider::sub-page:horizontal:disabled {{ background: {THEME['text_disabled']}; }}
    """

def _value_label_qss():
    return (f"font-size: 9pt; color: {THEME['text_primary']}; padding: 4px 8px; "
            f"background: {THEME['bg_input']}; border: 1px solid {THEME['border']}; border-radius: 4px;")

def _scrollable(widget):
    """Wrap a widget in a frameless, resizable scroll area."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(widget)
    return area

def _clear_layout(layout):
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()

def _fit_table(table, min_col_width=80):
    """Give the table its full size so the surrounding scroll area does the scrolling."""
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setMinimumHeight(table.verticalHeader().length() + table.horizontalHeader().height() + 6)
    table.setMinimumWidth(table.columnCount() * min_col_width)

class ForceStateSelector(QWidget):
    """Result-state picker for nonlinear OpenSees results.

    The combo box always lists every state; when the list is of manageable size a
    slider steps through the same list. Moving either one only stages the choice -
    the Apply button commits it. `applied` carries the saved-state ordinal, or None
    for the final state.
    """
    applied = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._applied_step = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.addWidget(QLabel('Result state:'))
        self.combo = QComboBox()
        self.combo.setObjectName('opensees_force_state')
        self.combo.setToolTip('Choose final forces or a recorded nonlinear state. Step numbers are the actual solver steps.')
        row.addWidget(self.combo, 1)
        self.btn_apply = QPushButton('Apply')
        self.btn_apply.setObjectName('primary')
        self.btn_apply.setAutoDefault(False)
        self.btn_apply.setToolTip('Show the selected result state')
        self.btn_apply.setEnabled(False)
        row.addWidget(self.btn_apply)
        outer.addLayout(row)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setPageStep(1)
        self.slider.setVisible(False)
        outer.addWidget(self.slider)
        self.restyle()

        self.combo.currentIndexChanged.connect(self._on_combo)
        self.slider.valueChanged.connect(self._on_slider)
        self.btn_apply.clicked.connect(self._on_apply)

    def restyle(self):
        self.slider.setStyleSheet(_slider_qss())

    def populate(self, results, step_number=None):
        """Fill the list for a result and mark the shown state as the applied one."""
        _populate_force_state_combo(self.combo, results, step_number)
        self._applied_step = self.combo.currentData()
        self._sync_slider()
        self._update_apply_state()

    def current_step(self):
        return self.combo.currentData()

    def mark_applied(self, step):
        self._applied_step = step
        self._update_apply_state()

    def _sync_slider(self):
        last = self.combo.count() - 1
        was_blocked = self.slider.blockSignals(True)
        try:
            self.slider.setRange(0, max(0, last))
            self.slider.setValue(max(0, self.combo.currentIndex()))
            self.slider.setTickInterval(max(1, last // 20))
            self.slider.setPageStep(max(1, last // 100))
        finally:
            self.slider.blockSignals(was_blocked)
        self.slider.setVisible(1 <= last <= STATE_SLIDER_MAX_STATES)

    def _on_combo(self, index):
        was_blocked = self.slider.blockSignals(True)
        self.slider.setValue(max(0, index))
        self.slider.blockSignals(was_blocked)
        self._update_apply_state()

    def _on_slider(self, value):
        was_blocked = self.combo.blockSignals(True)
        self.combo.setCurrentIndex(value)
        self.combo.blockSignals(was_blocked)
        self._update_apply_state()

    def _update_apply_state(self):
        self.btn_apply.setEnabled(self.combo.isEnabled() and self.combo.currentData() != self._applied_step)

    def _on_apply(self):
        step = self.combo.currentData()
        self._applied_step = step
        self._update_apply_state()
        self.applied.emit(step)

class ForceAnalysisContext:
    """Share immutable file data and member loads during one display build.

    The analyzer still performs the same calculations, in the same load order.
    Only unrelated loads and repeated whole-project file reads are removed.
    """

    def __init__(self, model, cancelled=None):
        self.cancelled = cancelled or (lambda: False)
        self._files = {}
        self._cqc_weights = {}
        self.loads_by_element = {}
        for load in getattr(model, 'loads', []):
            if self.cancelled():
                break
            element_id = (load.get('element_id') if isinstance(load, dict) else
                          getattr(load, 'element_id', None))
            try:
                self.loads_by_element.setdefault(element_id, []).append(load)
            except TypeError:
                                                                            
                continue

    def load_json(self, path):
        key = os.path.normcase(os.path.abspath(os.fspath(path)))
        if key not in self._files:
            self._files[key] = load_json_cached(path)
        return self._files[key]

    def cqc_weights(self, omega, zeta):
        key = (tuple(omega), zeta)
        if key not in self._cqc_weights:
            self._cqc_weights[key] = _cqc_pair_weights(omega, zeta)
        return self._cqc_weights[key]

def _cqc_pair_weights(omega, zeta):
    """Use the original scalar formula once for each ordered modal pair."""
    weights = np.empty((len(omega), len(omega)), dtype=float)
    for i in range(len(omega)):
        for j in range(len(omega)):
            if omega[i] == 0 or omega[j] == 0:
                rho = 1.0 if omega[i] == omega[j] else 0.0
            else:
                r = omega[i] / omega[j]
                den = (1.0 - r**2)**2 + 4.0 * zeta**2 * r * (1.0 + r)**2
                rho = (8.0 * zeta**2 * (1.0 + r) * r**1.5) / den if den != 0.0 else 1.0
            weights[i, j] = rho
    return weights

class MemberAnalyzer:
    """
    Standalone element force analyzer — the single source of truth for NVM results.
    """

    RESULT_COMPONENTS = ('P', 'T', 'V2', 'V3', 'M2', 'M3',
                         'Defl_2_Rel', 'Defl_3_Rel', 'Defl_2_Abs', 'Defl_3_Abs',
                         'end_forces')

    def __init__(self, element, model, num_stations=21,
                 displacements=None, matrices_path=None, results_dict=None, step_number=None,
                 results_path=None, _combo_stack=(), _analysis_context=None):
        self.el          = element
        self.model       = model
        self.n_stations  = num_stations
        self.results_dict = results_dict

        self.L_clear  = self.el.length()
        self.stations = np.linspace(0, self.L_clear, num_stations)
        
        self.P  = np.zeros(num_stations)
        self.T  = np.zeros(num_stations)
        self.V2 = np.zeros(num_stations)
        self.V3 = np.zeros(num_stations)
        self.M2 = np.zeros(num_stations)
        self.M3 = np.zeros(num_stations)
        
        self.Defl_2_Rel = np.zeros(num_stations)
        self.Defl_3_Rel = np.zeros(num_stations)
        self.Defl_2_Abs = np.zeros(num_stations)
        self.Defl_3_Abs = np.zeros(num_stations)
        
        self.end_forces = np.zeros(12)

        self._k   = None
        self._t   = None
        self._fef = np.zeros(12)
        self._f_final = None
        self._matrices_loaded = False
        self.forces_loaded = False
        self.force_recovery_error = None
        self.matrices_path = os.fspath(matrices_path) if matrices_path else None
        self.results_path = os.fspath(results_path) if results_path else None
        self._combo_stack = _combo_stack
        self._analysis_context = _analysis_context

        self._displacements = displacements
        if self._is_cancelled():
            return

        active_results = results_dict if results_dict is not None else (getattr(model, 'results', {}) or {})
        self.is_opensees = is_opensees_result(active_results, model)
        if _load_combination_name(active_results, model) is not None:
            self._calculate_combination(active_results, step_number)
            return
        if self.is_opensees:
            self._load_opensees_forces(active_results, step_number)
            return

        self._load_matrices(matrices_path)
        self._calculate()
        self.forces_loaded = self._matrices_loaded

    def _is_cancelled(self):
        return self._analysis_context is not None and self._analysis_context.cancelled()

    def _load_opensees_forces(self, results, step_number=None):
        """Recover forces solely from the exported OpenSees response."""
        for name in ('Defl_2_Rel', 'Defl_3_Rel', 'Defl_2_Abs', 'Defl_3_Abs'):
            setattr(self, name, np.full(self.n_stations, np.nan))
        try:
            state = select_opensees_force_state(results, step_number)
            record = state['opensees_forces'].get(str(self.el.id))
            if record is None:
                raise ValueError(f"OpenSees force data for element {self.el.id} is unavailable. Rerun the analysis to export member forces.")
            recovered = recover_member_forces(record, num_stations=self.n_stations)
            self._opensees_force_record = record
            for name in ('stations', 'P', 'T', 'V2', 'V3', 'M2', 'M3', 'end_forces'):
                setattr(self, name, np.asarray(recovered[name], dtype=float))
            self.L_clear = float(recovered['L_clear'])
            for name in ('Defl_2_Rel', 'Defl_3_Rel', 'Defl_2_Abs', 'Defl_3_Abs'):
                setattr(self, name, np.full(len(self.stations), np.nan))
            self.forces_loaded = True
        except (KeyError, TypeError, ValueError) as exc:
            self.force_recovery_error = f"OpenSees member forces unavailable: {exc}"
            if 'rerun' not in self.force_recovery_error.lower():
                self.force_recovery_error += " Rerun the analysis to export member forces."

    def _load_matrices(self, matrices_path):
        if self.is_opensees:
            return
        resolved = None
        active_results   = self.results_dict if self.results_dict is not None else (getattr(self.model, 'results', {}) or {})
        active_mat_path  = (active_results.get("matrices_path") or active_results.get("matrices_file"))

        if matrices_path and os.path.exists(matrices_path):
            resolved = matrices_path
        elif active_mat_path and os.path.exists(active_mat_path):
            resolved = active_mat_path
        elif hasattr(self.model, "file_path") and self.model.file_path:
            fallback = self.model.file_path.replace(".mf", "_matrices.json")
            if os.path.exists(fallback):
                resolved = fallback

        if not resolved:
            return

        self.matrices_path = resolved

        try:
            data = (self._analysis_context.load_json(resolved) if self._analysis_context is not None
                    else get_cached_matrices(resolved))
            str_id = str(self.el.id)
            if str_id in data:
                self._k   = np.array(data[str_id]["k"])
                self._t   = np.array(data[str_id]["t"])
                self._fef = np.array(data[str_id]["fef"])
                                                                            
                f_final = data[str_id].get("f_final")
                self._f_final = np.array(f_final) if f_final is not None else None
                self._matrices_loaded = True
        except Exception as e:
            print(f"[MemberAnalyzer] Error loading matrices: {e}")

    def _combination_base_path(self, results, combo_name):
        active_name = results.get('info', {}).get('case_name', '')
                                                                            
        if self.results_path:
            suffix = f'_{active_name}_results.json'
            if self.results_path.endswith(suffix):
                return self.results_path[:-len(suffix)]
        if getattr(self.model, 'file_path', None):
            return os.path.splitext(self.model.file_path)[0]
        for path in (self.results_path, self.matrices_path,
                     results.get('matrices_path'), results.get('matrices_file')):
            if not path:
                continue
            path = os.fspath(path)
            for name in (active_name, combo_name):
                for kind in ('results', 'matrices'):
                    suffix = f'_{name}_{kind}.json'
                    if path.endswith(suffix):
                        return path[:-len(suffix)]
            if path.endswith('_matrices.json'):
                return path[:-len('_matrices.json')]
        raise ValueError('The model or result file path is required to locate constituent results.')

    @staticmethod
    def _sample_opensees_combination(sub, stations):
        """Evaluate the exported segment polynomials at the common section cuts."""
        segments = sub._opensees_force_record['segments']
        ends = np.asarray([segment['end'] for segment in segments], dtype=float)
        left_face = np.r_[stations[:-1] == stations[1:], False]
        indices = np.where(left_face, np.searchsorted(ends, stations, side='left'),
                           np.searchsorted(ends, stations, side='right'))
        indices = np.clip(indices, 0, len(segments) - 1)
        values = np.zeros((len(stations), 6))
        for index, segment in enumerate(segments):
            mask = indices == index
            a, b, length = (float(segment[key]) for key in ('start', 'end', 'length'))
            t = (stations[mask] - a) / (b - a)
            x = t * length
            f = np.asarray(segment['local_forces'], dtype=float)
            rotation = np.asarray(segment['to_opencivil'], dtype=float)
            w = -(f[:3] + f[6:9]) / length
            force = (1 - t[:, None]) * f[:3] - t[:, None] * f[6:9]
            moment = (1 - t[:, None]) * f[3:6] - t[:, None] * f[9:12]
            moment[:, 1] += w[2] * x * (x - length) / 2
            moment[:, 2] -= w[1] * x * (x - length) / 2
            force = force @ rotation.T
            moment = moment @ rotation.T
            values[mask] = np.column_stack((-force[:, 0], moment[:, 0], force[:, 1],
                                            -force[:, 2], moment[:, 1], moment[:, 2]))
        output = dict(zip(('P', 'T', 'V2', 'V3', 'M2', 'M3'), values.T))
        for name in ('Defl_2_Rel', 'Defl_3_Rel', 'Defl_2_Abs', 'Defl_3_Abs'):
            output[name] = np.full(len(stations), np.nan)
        return output

    @classmethod
    def _align_combination_values(cls, sub, stations, component):
        """Recover each response at the same cuts, including both faces of jumps."""
        values = np.asarray(getattr(sub, component), dtype=float)
        source = np.asarray(sub.stations, dtype=float)
        if np.array_equal(source, stations):
            return values
        cache = getattr(sub, '_combination_sample_cache', None)
        if cache is None or not np.array_equal(cache[0], stations):
            if hasattr(sub, '_combination_terms'):
                sampled = {}
                for name in cls.RESULT_COMPONENTS[:-1]:
                    extreme = np.maximum if sub._combination_is_max else np.minimum
                    fill = ((-np.inf if sub._combination_is_max else np.inf)
                            if sub._combination_type == 'Envelope' and not sub._combination_has_zero
                            else 0.0)
                    combined = np.full(len(stations), fill)
                    for child, scale, is_rsa in sub._combination_terms:
                        scaled = cls._align_combination_values(child, stations, name) * scale
                        if is_rsa:
                            scaled = np.abs(scaled) * (1 if sub._combination_is_max else -1)
                        combined = (combined + scaled if sub._combination_type == 'Linear Add'
                                    else extreme(combined, scaled))
                    sampled[name] = combined
            elif hasattr(sub, '_opensees_force_record'):
                sampled = cls._sample_opensees_combination(sub, stations)
            else:
                                                                            
                recovered = copy.copy(sub)
                recovered.n_stations = len(stations)
                for name in cls.RESULT_COMPONENTS:
                    size = 12 if name == 'end_forces' else len(stations)
                    setattr(recovered, name, np.zeros(size))
                recovered._calculate(stations=stations)
                sampled = {name: getattr(recovered, name) for name in cls.RESULT_COMPONENTS[:-1]}
            sub._combination_sample_cache = (stations.copy(), sampled)
        return sub._combination_sample_cache[1][component]

    def _calculate_combination(self, results, step_number=None):
        combo_name = _load_combination_name(results, self.model)
        try:
            if step_number is not None:
                raise ValueError('Load combinations use final constituent results; select Final state.')
            if combo_name in self._combo_stack:
                raise ValueError('Circular load combination dependency: ' +
                                 ' -> '.join(self._combo_stack + (combo_name,)))
            combo = self.model.load_combos[combo_name]
            combo_type = getattr(combo, 'combo_type', 'Linear Add')
            if combo_type not in ('Linear Add', 'Envelope'):
                raise ValueError(f'Unsupported combination type: {combo_type}.')
            if not combo.cases:
                raise ValueError('The combination has no constituent cases.')
            base_path = self._combination_base_path(results, combo_name)
            is_max = results.get('info', {}).get('case_name', '') != f'{combo_name} (Min)'
            self.is_opensees = False
            terms = []
            has_zero = False
            for case_name, factor in combo.cases:
                if self._is_cancelled():
                    return
                scale = float(factor)
                if not np.isfinite(scale):
                    raise ValueError(f'Invalid scale factor for {case_name}.')
                if scale == 0:
                    has_zero = True
                    continue
                case_name = str(case_name).strip()
                base_file = f'{base_path}_{case_name}_results.json'
                max_file = f'{base_path}_{case_name} (Max)_results.json'
                min_file = f'{base_path}_{case_name} (Min)_results.json'
                is_nested = case_name in (getattr(self.model, 'load_combos', {}) or {})
                if is_nested:
                                                                          
                    files = ([max_file, min_file] if combo_type == 'Envelope' else
                             [max_file if is_max == (scale > 0) else min_file])
                elif combo_type == 'Envelope':
                    files = [path for path in (max_file, min_file) if os.path.exists(path)]
                else:
                                                                               
                    bound_file = max_file if is_max == (scale > 0) else min_file
                    files = [bound_file] if os.path.exists(bound_file) else []
                if not files and os.path.exists(base_file):
                    files = [base_file]
                if not files:
                    raise ValueError(f'Results for constituent {case_name} are unavailable. Rerun its analysis.')
                for path in files:
                    if self._is_cancelled():
                        return
                    stored_path = path if os.path.exists(path) else base_file
                    if is_nested and not os.path.exists(stored_path):
                        sub_results = {'info': {'type': 'Load Combination'}}
                    else:
                        sub_results = (self._analysis_context.load_json(stored_path)
                                       if self._analysis_context is not None else
                                       load_json_cached(stored_path))
                    if is_nested:
                                                                              
                        sub_results = dict(sub_results)
                        sub_results['info'] = dict(sub_results.get('info', {}))
                        sub_results['info']['case_name'] = (
                            f'{case_name} (Max)' if path == max_file else f'{case_name} (Min)')
                    mat_file = path.replace('_results.json', '_matrices.json')
                    if not os.path.exists(mat_file):
                        mat_file = self.matrices_path
                    sub = MemberAnalyzer(
                        self.el, self.model, self.n_stations, matrices_path=mat_file,
                        results_dict=sub_results, results_path=path,
                        _combo_stack=self._combo_stack + (combo_name,),
                        _analysis_context=self._analysis_context)
                    if not sub.forces_loaded:
                        raise ValueError(f'{case_name}: ' + (sub.force_recovery_error or
                                         'Member matrices/forces are unavailable. Rerun its analysis.'))
                    self.is_opensees = self.is_opensees or sub.is_opensees
                    is_rsa = (_load_combination_name(sub_results, self.model) is None and
                              (sub_results.get('info', {}).get('type') in
                               ('Response Spectrum', 'Response Spectrum Combined') or
                               'rsa_info' in sub_results))
                    terms.append((sub, scale, is_rsa))

            if not terms:
                self.forces_loaded = True
                return
            reference = terms[0][0]
            counts = {}
            for sub, _, _ in terms:
                source = np.asarray(sub.stations, dtype=float)
                if (len(source) == 0 or not np.all(np.isfinite(source)) or
                        np.any(np.diff(source) < 0)):
                    raise ValueError('Constituent stations are invalid.')
                if (not np.allclose(source[[0, -1]], reference.stations[[0, -1]], rtol=1e-9, atol=1e-9) or
                        not np.isclose(sub.L_clear, reference.L_clear, rtol=1e-9, atol=1e-9)):
                    raise ValueError('Constituent member spans differ; their diagrams cannot be combined.')
                for station, count in zip(*np.unique(source, return_counts=True)):
                    counts[station] = max(counts.get(station, 0), int(count))
            self.stations = np.repeat(sorted(counts), [counts[x] for x in sorted(counts)])
            self.L_clear = reference.L_clear
            self._combination_terms = terms
            self._combination_type = combo_type
            self._combination_is_max = is_max
            self._combination_has_zero = has_zero
            extreme = np.maximum if is_max else np.minimum
            for component in self.RESULT_COMPONENTS:
                size = 12 if component == 'end_forces' else len(self.stations)
                fill = ((-np.inf if is_max else np.inf)
                        if combo_type == 'Envelope' and not has_zero else 0.0)
                combined = np.full(size, fill)
                for sub, scale, is_rsa in terms:
                    values = (sub.end_forces if component == 'end_forces' else
                              self._align_combination_values(sub, self.stations, component))
                    scaled = values * scale
                    if is_rsa:
                                                                                
                        scaled = np.abs(scaled) * (1.0 if is_max else -1.0)
                    combined = (combined + scaled if combo_type == 'Linear Add' else
                                extreme(combined, scaled))
                setattr(self, component, combined)
            self.forces_loaded = True
        except (OSError, KeyError, TypeError, ValueError) as exc:
            self.force_recovery_error = f'Load combination {combo_name} unavailable: {exc}'
                                                                                
            for component in self.RESULT_COMPONENTS:
                size = 12 if component == 'end_forces' else len(self.stations)
                setattr(self, component, np.full(size, np.nan))
            self.forces_loaded = False

    def _calculate(self, stations=None):
        if not self._matrices_loaded:
            return

        res = self.results_dict if self.results_dict is not None else (getattr(self.model, 'results', {}) or {})
        active_case_name = res.get("info", {}).get("case_name", "")

        el     = self.el
        n1_str = str(el.node_i.id)
        n2_str = str(el.node_j.id)

        L_full = el.length()
        ri = getattr(el, 'end_offset_i', 0.0)
        rj = getattr(el, 'end_offset_j', 0.0)
        L_clear = L_full - ri - rj
        self.L_clear = L_clear
        self.stations = (np.linspace(ri, L_full - rj, self.n_stations) if stations is None else
                         np.asarray(stations, dtype=float))

        if "rsa_info" in res:
            rsa = res["rsa_info"]
            dir_comb = rsa.get("dir_comb", "SRSS")
            dirs_data = rsa.get("directions", [rsa])

            P_final = np.zeros(self.n_stations); V2_final = np.zeros(self.n_stations); V3_final = np.zeros(self.n_stations)
            T_final = np.zeros(self.n_stations)
            M2_final = np.zeros(self.n_stations); M3_final = np.zeros(self.n_stations)
            final_end_forces = np.zeros(12)

            for d_info in dirs_data:
                if self._is_cancelled():
                    return
                method = d_info.get("method", "SRSS")
                zeta = d_info.get("zeta", 0.05)
                omega = d_info.get("omega_array", [])
                u_raw = d_info.get("uncombined_u", {})
                
                n_modes = len(omega)
                if n_modes == 0: continue

                u1_modes = u_raw.get(n1_str, [np.zeros(6)] * n_modes)
                u2_modes = u_raw.get(n2_str, [np.zeros(6)] * n_modes)

                P_modes = np.zeros((n_modes, self.n_stations)); V2_modes = np.zeros((n_modes, self.n_stations))
                V3_modes = np.zeros((n_modes, self.n_stations)); M2_modes = np.zeros((n_modes, self.n_stations))
                M3_modes = np.zeros((n_modes, self.n_stations))
                T_modes = np.zeros((n_modes, self.n_stations))
                per_mode_forces = np.zeros((n_modes, 12))

                for i in range(n_modes):
                    if self._is_cancelled():
                        return
                    u_global_mode = np.concatenate([u1_modes[i], u2_modes[i]])
                    end_f_mode = self._k @ (self._t @ u_global_mode)
                    per_mode_forces[i] = end_f_mode
                    Fx1, Fy1, Fz1 = end_f_mode[0:3]
                    Mx1, My1, Mz1 = end_f_mode[3:6]

                    for j, x_abs in enumerate(self.stations):
                        x_c = x_abs - ri
                        T_modes[i, j] = Mx1
                        P_modes[i, j] = -Fx1
                        V2_modes[i, j] = Fy1
                        V3_modes[i, j] = -Fz1
                        M3_modes[i, j] = Mz1 - Fy1 * x_c
                        M2_modes[i, j] = My1 + Fz1 * x_c

                P_dir = np.zeros(self.n_stations); V2_dir = np.zeros(self.n_stations); V3_dir = np.zeros(self.n_stations)
                T_dir = np.zeros(self.n_stations)
                M2_dir = np.zeros(self.n_stations); M3_dir = np.zeros(self.n_stations)
                d_end_forces = np.zeros(12)

                if method == "CQC" and n_modes > 0:
                    weights = (self._analysis_context.cqc_weights(omega, zeta)
                               if self._analysis_context is not None else
                               _cqc_pair_weights(omega, zeta))
                    modal_values = np.concatenate((per_mode_forces, T_modes, P_modes,
                                                   V2_modes, V3_modes, M2_modes, M3_modes), axis=1)
                    totals = np.zeros(modal_values.shape[1])
                                                                             
                    for i in range(n_modes):
                        if self._is_cancelled():
                            return
                        terms = (modal_values[i] * weights[i, :, None]) * modal_values
                        terms[0] = totals + terms[0]
                        np.add.accumulate(terms, axis=0, out=terms)
                        totals = terms[-1].copy()
                    combined = np.sqrt(np.abs(totals))
                    d_end_forces = combined[:12]
                    T_dir, P_dir, V2_dir, V3_dir, M2_dir, M3_dir = combined[12:].reshape(6, self.n_stations)
                else:
                    d_end_forces = np.sqrt(np.sum(per_mode_forces**2, axis=0))
                    T_dir = np.sqrt(np.sum(T_modes**2, axis=0))
                    P_dir = np.sqrt(np.sum(P_modes**2, axis=0))
                    V2_dir = np.sqrt(np.sum(V2_modes**2, axis=0))
                    V3_dir = np.sqrt(np.sum(V3_modes**2, axis=0))
                    M2_dir = np.sqrt(np.sum(M2_modes**2, axis=0))
                    M3_dir = np.sqrt(np.sum(M3_modes**2, axis=0))

                if dir_comb == "SRSS":
                    final_end_forces += d_end_forces**2
                    T_final += T_dir**2
                    P_final += P_dir**2; V2_final += V2_dir**2; V3_final += V3_dir**2; M2_final += M2_dir**2; M3_final += M3_dir**2
                else:
                    final_end_forces += np.abs(d_end_forces)
                    T_final += np.abs(T_dir)
                    P_final += np.abs(P_dir); V2_final += np.abs(V2_dir); V3_final += np.abs(V3_dir); M2_final += np.abs(M2_dir); M3_final += np.abs(M3_dir)

            if dir_comb == "SRSS":
                self.end_forces = np.sqrt(final_end_forces)
                self.T = np.sqrt(T_final)
                self.P = np.sqrt(P_final); self.V2 = np.sqrt(V2_final); self.V3 = np.sqrt(V3_final); self.M2 = np.sqrt(M2_final); self.M3 = np.sqrt(M3_final)
            else:
                self.end_forces = final_end_forces
                self.T = T_final
                self.P = P_final; self.V2 = V2_final; self.V3 = V3_final; self.M2 = M2_final; self.M3 = M3_final
                
        else:         
            if self._displacements is not None:
                disp_dict = self._displacements
            else:
                disp_dict = res.get("_base_displacements", res.get("displacements", {}))

            u1 = np.array(disp_dict.get(n1_str, [0.0] * 6))
            u2 = np.array(disp_dict.get(n2_str, [0.0] * 6))
            u_global = np.concatenate([u1, u2])

            if self._f_final is not None:
                self.end_forces = self._f_final
            else:
                self.end_forces = self._k @ (self._t @ u_global) + self._fef
            Fx1, Fy1, Fz1 = self.end_forces[0], self.end_forces[1], self.end_forces[2]
            Mx1, My1, Mz1 = self.end_forces[3], self.end_forces[4], self.end_forces[5]

            Myj, Mzj = self.end_forces[10], self.end_forces[11]

            u_local = self._t @ u_global
            u1_l, v1, w1, thx1, thy1, thz1 = u_local[0:6]
            u2_l, v2, w2, thx2, thy2, thz2 = u_local[6:12]

            R_3x3 = self._t[0:3, 0:3]
            p1_coords = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
            p2_coords = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
            
            line_loads = []
            point_loads = []

            pattern_scales = {}
            if active_case_name in getattr(self.model, 'load_cases', {}):
                active_case = self.model.load_cases[active_case_name]
                for pat_name, case_scale in active_case.loads:
                    pattern_scales[pat_name] = pattern_scales.get(pat_name, 0.0) + case_scale

            for pat_name, net_scale in pattern_scales.items():
                if pat_name in getattr(self.model, 'load_patterns', {}):
                    pat = self.model.load_patterns[pat_name]
                    if getattr(pat, 'self_weight_multiplier', 0) > 0:
                        area = getattr(el.section, 'A', 0)
                        density = getattr(el.section.material, 'density', 0)
                        w_sw_mag = area * density * pat.self_weight_multiplier * net_scale
                        w_sw_local = R_3x3 @ np.array([0.0, 0.0, -w_sw_mag])
                        if np.any(np.abs(w_sw_local) > 1e-9):
                            line_loads.append({
                                'dists': [0.0, L_full],
                                'vecs': [w_sw_local.copy(), w_sw_local.copy()]
                            })

            member_loads = (getattr(self.model, 'loads', []) if self._analysis_context is None else
                            self._analysis_context.loads_by_element.get(int(el.id), ()))
            for raw_load in member_loads:
                if self._is_cancelled():
                    return
                                                                                   
                is_dict = isinstance(raw_load, dict)
                def get_p(k, default=None): return raw_load.get(k, default) if is_dict else getattr(raw_load, k, default)
                def has_p(k): return k in raw_load if is_dict else hasattr(raw_load, k)

                if get_p('element_id') == int(el.id):
                    load_pat = get_p('pattern', get_p('pattern_name'))
                    if load_pat not in pattern_scales: continue
                    net_scale = pattern_scales[load_pat]
                    
                    l_type = get_p('type', get_p('load_type', ''))
                    is_local = str(get_p('coord_system', get_p('coord', 'Global'))).lower() == 'local'
                    
                    if l_type == 'member_dist' or (has_p('wx') and not has_p('force')):
                        mags = np.array(get_p('magnitudes', [0, 0, 0, 0])) * net_scale
                        dists = np.array(get_p('distances', [0, 0.25, 0.75, 1.0]))
                        has_trap = any(abs(m) > 1e-9 for m in mags)
                        
                        if has_trap:
                            is_rel = get_p('is_relative', True)
                            if is_rel: dists = dists * L_full
                            dir_str = str(get_p('load_direction', 'Gravity')).upper()
                            w_vectors = []
                            for m in mags:
                                vec = np.zeros(3)
                                if "GRAVITY" in dir_str: vec[2] = m
                                elif "X" in dir_str or "1" in dir_str: vec[0] = m
                                elif "Y" in dir_str or "2" in dir_str: vec[1] = m
                                elif "Z" in dir_str or "3" in dir_str: vec[2] = m
                                if not is_local: vec = R_3x3 @ vec
                                if get_p('projected', False) and not is_local:
                                    dx = p2_coords[0] - p1_coords[0]
                                    dy = p2_coords[1] - p1_coords[1]
                                    L_horiz = np.sqrt(dx**2 + dy**2)
                                    if L_full > 1e-9: vec = vec * (L_horiz / L_full)
                                w_vectors.append(vec)
                            line_loads.append({'dists': dists, 'vecs': w_vectors})
                        else:
                            w_vec = np.array([get_p('wx', 0), get_p('wy', 0), get_p('wz', 0)]) * net_scale
                            if not is_local: w_vec = R_3x3 @ w_vec
                            if get_p('projected', False) and not is_local:
                                dx = p2_coords[0] - p1_coords[0]
                                dy = p2_coords[1] - p1_coords[1]
                                L_horiz = np.sqrt(dx**2 + dy**2)
                                if L_full > 1e-9: w_vec = w_vec * (L_horiz / L_full)
                            line_loads.append({'dists': [0.0, L_full], 'vecs': [w_vec, w_vec]})
                            
                    elif l_type == 'member_point' or has_p('force'):
                        is_rel = get_p('is_rel', get_p('is_relative', False))
                        dist_val = get_p('dist', 0.0)
                        if is_rel and dist_val > 1.0: dist_val /= 100.0
                        a = dist_val * L_full if is_rel else dist_val
                        a_clear = a - ri
                        
                        if 0 <= a_clear <= L_clear:
                            dir_str = str(get_p('direction', get_p('dir', get_p('axis', 'Z')))).upper()

                            sign = 1.0
                            idx = 2
                            if "GRAVITY" in dir_str:
                                idx = 2
                                sign = -1.0
                                is_local = False
                            elif "X" in dir_str or "1" in dir_str: idx = 0
                            elif "Y" in dir_str or "2" in dir_str: idx = 1
                            elif "Z" in dir_str or "3" in dir_str: idx = 2
                            
                            vec = np.zeros(3)
                            vec[idx] = get_p('force', 0.0) * sign * net_scale
                            
                            if not is_local: 
                                vec = R_3x3 @ vec
                                
                            l_type_str = str(get_p('load_type', get_p('l_type', 'Force'))).upper()
                            if 'MOMENT' in l_type_str: 
                                point_loads.append({'a_clear': a_clear, 'F': np.zeros(3), 'M': vec})
                            else: 
                                point_loads.append({'a_clear': a_clear, 'F': vec, 'M': np.zeros(3)})

            E = getattr(el.section.material, 'E', 1.0)
            I33 = getattr(el.section, 'I33', 1.0)
            I22 = getattr(el.section, 'I22', 1.0)

            for i, x_abs in enumerate(self.stations):
                if self._is_cancelled():
                    return
                x_c = x_abs - ri
                xi = x_c / L_clear if L_clear > 0 else 0
                
                w_P_tot = 0.0; w_V2_tot = 0.0; w_V3_tot = 0.0
                w_M3_tot = 0.0; w_M2_tot = 0.0
                
                w_loc_sum = np.zeros(3)
                len_sum = 0.0
                
                for ll in line_loads:
                    dists = ll['dists']
                    vecs = ll['vecs']
                    for k in range(len(dists) - 1):
                        x1_dist = dists[k]; x2_dist = dists[k+1]
                        
                        w_vec1 = vecs[k]; w_vec2 = vecs[k+1]
                        
                        if x2_dist - x1_dist < 1e-9: continue
                        
                        s_start = max(ri, x1_dist)
                        s_end = min(x_abs, x2_dist)
                        
                        if s_start < s_end:
                            t_start = (s_start - x1_dist) / (x2_dist - x1_dist)
                            t_end = (s_end - x1_dist) / (x2_dist - x1_dist)
                            ws = w_vec1 + t_start * (w_vec2 - w_vec1)
                            we = w_vec1 + t_end * (w_vec2 - w_vec1)
                            
                            L_seg = s_end - s_start
                            F_vec = 0.5 * (ws + we) * L_seg
                            
                            w_P_tot += F_vec[0]
                            w_V2_tot += F_vec[1]
                            w_V3_tot += F_vec[2]
                            
                            arm_rect = x_abs - 0.5 * (s_start + s_end)
                            M_rect = ws * L_seg * arm_rect
                            
                            arm_tri = x_abs - (s_start + (2.0/3.0) * L_seg)
                            M_tri = 0.5 * (we - ws) * L_seg * arm_tri
                            
                            M_vec = M_rect + M_tri
                            w_M3_tot += M_vec[1]
                            w_M2_tot += M_vec[2]
                            
                            w_loc_sum += 0.5 * (ws + we) * L_seg
                            len_sum += L_seg
                            
                w_loc_avg = w_loc_sum / len_sum if len_sum > 1e-9 else np.zeros(3)
                
                P_val = -Fx1 - w_P_tot
                V2_val = Fy1 + w_V2_tot
                V3_val = -(Fz1 + w_V3_tot)
                M3_val = Mz1 - Fy1 * x_c - w_M3_tot
                M2_val = My1 + Fz1 * x_c + w_M2_tot
                
                for pl in point_loads:
                    a_c = pl['a_clear']
                    right_cut = (stations is not None and i > 0 and
                                 self.stations[i] == self.stations[i - 1] and
                                 (i == self.n_stations - 1 or self.stations[i] != self.stations[i + 1]))
                    if x_c > a_c or (right_cut and np.isclose(x_c, a_c, rtol=0, atol=1e-9)):
                        dist_x = x_c - a_c
                        P_val -= pl['F'][0]; V2_val += pl['F'][1]; V3_val -= pl['F'][2]                              
                        M3_val += -pl['F'][1] * dist_x + pl['M'][2]                                
                        M2_val += pl['F'][2] * dist_x + pl['M'][1]
                        
                self.P[i] = P_val; self.V2[i] = V2_val; self.V3[i] = V3_val; self.M3[i] = M3_val; self.M2[i] = M2_val
                self.T[i] = Mx1

                N1 = 1 - 3*xi**2 + 2*xi**3
                N2 = x_c * (1 - 2*xi + xi**2)
                N3 = 3*xi**2 - 2*xi**3
                N4 = x_c * (xi**2 - xi)
                
                defl_2_abs = N1*v1 + N2*thz1 + N3*v2 + N4*thz2
                defl_3_abs = N1*w1 + N2*(-thy1) + N3*w2 + N4*(-thy2) 
                
                chord_2 = v1 + (v2 - v1) * xi
                chord_3 = w1 + (w2 - w1) * xi
                
                defl_bubble_2 = (w_loc_avg[1] * (x_c**2) * ((L_clear - x_c)**2)) / (24 * E * I33) if I33 > 0 else 0
                defl_bubble_3 = (w_loc_avg[2] * (x_c**2) * ((L_clear - x_c)**2)) / (24 * E * I22) if I22 > 0 else 0
                
                self.Defl_2_Rel[i] = (defl_2_abs - chord_2) + defl_bubble_2
                self.Defl_3_Rel[i] = (defl_3_abs - chord_3) + defl_bubble_3
                self.Defl_2_Abs[i] = defl_2_abs + defl_bubble_2
                self.Defl_3_Abs[i] = defl_3_abs + defl_bubble_3

            if self.n_stations > 1 and self._f_final is not None:
                frac = (self.stations - self.stations[0])
                span = frac[-1] if frac[-1] > 1e-9 else 1.0
                frac = frac / span

                M2_target_j = -Myj
                M3_target_j = -Mzj
                self.M2 = self.M2 + frac * (M2_target_j - self.M2[-1])
                self.M3 = self.M3 + frac * (M3_target_j - self.M3[-1])

class MatrixSpyDialog(QDialog):
    def __init__(self, element_id, model, matrices_path, parent=None, results_path=None, step_number=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(f"Element {element_id} - Internal Matrices Spy")
        apply_dialog_style(self)
        self.resize(900, 600)
        self.element_id = str(element_id)
        self.model = model
        self.step_number = step_number
        self.matrices_path = matrices_path
                                                                                 
        paired_path = results_path
        if paired_path is None and matrices_path:
            matrix_name = os.fspath(matrices_path)
            if matrix_name.endswith('_matrices.json'):
                paired_path = matrix_name[:-len('_matrices.json')] + '_results.json'
        active_results = getattr(model, 'results', {}) or {}
        self.results = self._load_json(paired_path) if paired_path else active_results
        self.results_path = paired_path
        self.is_combination = _load_combination_name(self.results, model) is not None
        self._combination_analyzer = None
        if self.is_combination:
            self.step_number = None
        self.is_opensees = is_opensees_result(self.results or active_results, model)
        if self.is_combination:
            self._combination_analyzer = MemberAnalyzer(
                model.elements[int(self.element_id)], model,
                matrices_path=matrices_path, results_dict=self.results,
                results_path=self.results_path)
            self.is_opensees = self._combination_analyzer.is_opensees
        self.matrices_data = {} if self.is_opensees else self._load_json(matrices_path)
        
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        if self.is_opensees or self.is_combination:
            force_engine = 'OpenSees' if self.is_opensees else 'Native'
            self.setWindowTitle(f"Element {element_id} - {force_engine} Forces")
            forces_tab = QWidget()
            forces_layout = QVBoxLayout(forces_tab)
            tabs.addTab(forces_tab, 'Combination Forces' if self.is_combination else 'OpenSees Forces')
            self.state_selector = ForceStateSelector()
            self.state_selector.populate({} if self.is_combination else self.results, self.step_number)
            self.state_selector.setVisible(not self.is_combination)
            self.force_state_combo = self.state_selector.combo
            forces_layout.addWidget(self.state_selector)
            self.force_source_label = QLabel()
            forces_layout.addWidget(self.force_source_label)
            self.force_data_widget = QWidget()
            self.force_data_layout = QVBoxLayout(self.force_data_widget)
            forces_layout.addWidget(_scrollable(self.force_data_widget), 1)
            self._refresh_opensees_forces()
            self.state_selector.applied.connect(self._on_force_state_applied)
            self._init_theme_listener()
            return
        
        self.tab_k = QWidget(); self.tab_k_layout = QVBoxLayout(self.tab_k)
        tabs.addTab(_scrollable(self.tab_k), "Local Stiffness [k]")
        
        self.tab_t = QWidget(); self.tab_t_layout = QVBoxLayout(self.tab_t)
        tabs.addTab(_scrollable(self.tab_t), "Transformation [T]")
        
        self.tab_fef = QWidget(); self.tab_fef_layout = QVBoxLayout(self.tab_fef)
        tabs.addTab(_scrollable(self.tab_fef), "Fixed End Forces (FEE)")

        self._populate_ui()
        self._init_theme_listener()

    def _load_json(self, path):
        if not path or not os.path.exists(path): return {}
        with open(path, 'r') as f: return json.load(f)

    def _on_force_state_applied(self, step):
        self.step_number = step
        self._refresh_opensees_forces()
        self.state_selector.mark_applied(step)

    def _init_theme_listener(self):
        on_theme_changed(self._on_theme_changed)
        self.finished.connect(self._drop_theme_listener)

    def _drop_theme_listener(self, *_):
        off_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, *_):
        try:
            apply_dialog_style(self)
            if self.is_opensees or self.is_combination:
                self.state_selector.restyle()
                return
            for lay in (self.tab_k_layout, self.tab_t_layout, self.tab_fef_layout):
                _clear_layout(lay)
            self._populate_ui()
        except RuntimeError:                                                           
            self._drop_theme_listener()

    def _refresh_opensees_forces(self):
        state_label = ('Load combination' if self.is_combination else
                       _force_state_label(self.results, self.step_number))
        force_engine = 'OpenSees' if self.is_opensees else 'Native'
        self.force_source_label.setText(
            f'Force recovery: {force_engine} | {state_label}')
        while self.force_data_layout.count():
            widget = self.force_data_layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._populate_opensees_forces(self.force_data_layout, self.step_number)

    def _populate_opensees_forces(self, layout, step_number):
        note = QLabel(
            "Combined member end forces in OpenCivil local axes, evaluated from constituent results."
            if self.is_combination else
            "OpenSees resisting forces at the first and last beam faces, expressed in OpenCivil member local axes. Stiffness, transformation and fixed-end force matrices are not exported by this solver.")
        note.setWordWrap(True)
        layout.addWidget(note)
        try:
            if self.is_combination:
                analyzer = self._combination_analyzer
                if not analyzer.forces_loaded:
                    raise ValueError(analyzer.force_recovery_error)
                forces = analyzer.end_forces
            else:
                state = select_opensees_force_state(self.results, step_number)
                record = state['opensees_forces'].get(self.element_id)
                if not record:
                    raise ValueError(f"No OpenSees force data for element {self.element_id}.")
                forces = np.asarray(record['end_forces'], dtype=float)
            if forces.shape != (12,) or not np.all(np.isfinite(forces)):
                raise ValueError("The exported OpenSees end force vector is invalid.")
        except (KeyError, TypeError, ValueError) as exc:
            message = f"{exc}"
            if 'rerun' not in message.lower():
                message += ' Rerun the analysis to export member forces.'
            error = QLabel(message)
            error.setWordWrap(True)
            layout.addWidget(error)
            return

        order = QLabel("Order: [Fxi, Fyi, Fzi, Mxi, Myi, Mzi, Fxj, Fyj, Fzj, Mxj, Myj, Mzj]. Here i and j denote the first and last beam faces; signed components have been transformed to OpenCivil local x, y, z axes.")
        order.setWordWrap(True)
        layout.addWidget(order)
        table = QTableWidget(12, 3)
        table.setHorizontalHeaderLabels(['Component', 'Value', 'Unit'])
        labels = ('Fx', 'Fy', 'Fz', 'Mx', 'My', 'Mz')
        for row, force in enumerate(forces):
            is_moment = row % 6 >= 3
            value = unit_registry.to_display_force(force)
            units = unit_registry.force_unit_name
            if is_moment:
                value *= unit_registry.length_scale
                units += f"·{unit_registry.length_unit_name}"
            component = f"{labels[row % 6]} ({'i' if row < 6 else 'j'})"
            for col, text in enumerate((component, f'{value:.6g}', units)):
                table.setItem(row, col, QTableWidgetItem(text))
        _fit_table(table)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

    def _populate_ui(self):
        if self.element_id not in self.matrices_data:
            self.tab_k_layout.addWidget(QLabel("No matrix data found."))
            return
        data = self.matrices_data[self.element_id]
        self._add_matrix_table(self.tab_k_layout, data['k'], "12x12 Local Stiffness")
        self._add_matrix_table(self.tab_t_layout, data['t'], "12x12 Transformation Matrix")
        fef_col = [[x] for x in data['fef']]
        self._add_matrix_table(self.tab_fef_layout, fef_col, "12x1 Fixed End Force Vector")

    def _add_matrix_table(self, layout, matrix_data, title):
        if not matrix_data: return
        lbl = QLabel(title); lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(lbl)
        rows = len(matrix_data); cols = len(matrix_data[0])
        table = QTableWidget(rows, cols)
        for r in range(rows):
            for c in range(cols):
                val = matrix_data[r][c]
                txt = f"{val:.4e}" if (abs(val)>1e7 or (abs(val)<1e-4 and abs(val)>0)) else f"{val:.4f}"
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if abs(val) < 1e-9: item.setForeground(QColor(THEME['text_disabled']))
                table.setItem(r, c, item)
        _fit_table(table, 85)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

class FBDViewerDialog(QDialog):
                                                   
    _FALLBACK_COLORS = {
        'beam': '#000000',                  
        'node': '#000000',                   
        'axial': '#000000',                    
        'shear': "#000000",                     
        'moment': '#000000',                       
        'torsion': '#000000',
        'deflection': '#000000'                                        
    }
    
    inspection_location_changed = pyqtSignal(object, float)
    inspection_closed = pyqtSignal()

    @property
    def COLORS(self):
        """Diagram ink follows the live theme (dark ink on light, light ink on dark)."""
        ink = THEME['text_primary']
        return {key: ink for key in self._FALLBACK_COLORS}

    def __init__(self, element_id, model, results_path, matrices_path, parent=None, step_number=None):
        super().__init__(parent)
        self.setWindowTitle(f"Element {element_id} - Free Body Diagrams")
        apply_dialog_style(self)
        self.resize(650, 700)
        self.setMinimumSize(460, 420)
        
        self.element_id = str(element_id)
        self.model = model
        
        self.element = self.model.elements[int(self.element_id)] 

        self.results_path = results_path
        self.matrices_path = matrices_path
        self.step_number = step_number
        
        self.results = self._load_json(results_path)
        self.is_opensees = is_opensees_result(self.results, model)
        self.matrices = {} if self.is_opensees else self._load_json(matrices_path)
        
        self.beam_length = self.element.length()                               
        self.beam_length_display = unit_registry.to_display_length(self.beam_length)
        
        self._run_analyzer()
        
        self.force_unit = unit_registry.force_unit_name
        self.length_unit = unit_registry.length_unit_name
        self.moment_unit = f"{self.force_unit}·{self.length_unit}"
        
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._scroll.setWidget(content)
        outer_layout.addWidget(self._scroll)
        layout = QVBoxLayout(content)

        info_text = (f"Element Length: {self.beam_length_display:.3f} {self.length_unit}  |  "
                    f"Units: Force [{self.force_unit}], Moment [{self.moment_unit}]")
        unit_label = QLabel(info_text)
        unit_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        unit_label.setObjectName("hint")
        unit_label.setContentsMargins(5, 5, 5, 5)
        layout.addWidget(unit_label)

        self.force_source_label = QLabel()
        layout.addWidget(self.force_source_label)
        self._update_force_source_label()

        self.force_status_label = QLabel(self.force_recovery_error or '')
        self.force_status_label.setWordWrap(True)
        self.force_status_label.setVisible(bool(self.force_recovery_error))
        layout.addWidget(self.force_status_label)

        self.case_combo = QComboBox()
        layout.addWidget(self.case_combo)
        self._populate_case_switcher(results_path)
        self.case_combo.currentIndexChanged.connect(self._on_case_switched)

        self.state_selector = ForceStateSelector()
        self.force_state_combo = self.state_selector.combo
        layout.addWidget(self.state_selector)
        self._populate_force_state_switcher()
        self.state_selector.applied.connect(self._on_force_state_changed)
        on_theme_changed(self._on_theme_changed)
        self.finished.connect(self._drop_theme_listener)
        
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(560)
        layout.addWidget(self.tabs)
        
        self.add_axial_tab()
        self.add_Minor_axis_tab()
        self.add_Major_axis_tab()
        self.add_torsion_tab()
        self.add_nvm_tab()
        
    def _load_json(self, path):
        if not path or not os.path.exists(path): return {}
        with open(path, 'r') as f: return json.load(f)

    def _populate_case_switcher(self, current_results_path):
        import glob
        import json
        self.case_combo.blockSignals(True)
        self.case_combo.clear()

        active_case = self.results.get("info", {}).get("case_name", "")

        valid_paths = getattr(self.model, 'valid_result_paths', [])
        is_single_case = len(valid_paths) <= 1

        if is_single_case:
            self.case_combo.addItem(active_case, active_case)
            self.case_combo.setCurrentIndex(0)
            self.case_combo.setEnabled(False)                                           
            self.case_combo.blockSignals(False)
            return                       
                                                  
        if active_case and f"_{active_case}_results.json" in current_results_path:
            self._base_file_path = current_results_path.replace(f"_{active_case}_results.json", "")
        else:
            self._base_file_path = current_results_path.replace("_results.json", "")
            if "_" in self._base_file_path.split(os.sep)[-1]:
                self._base_file_path = self._base_file_path.rsplit("_", 1)[0]

        valid_cases = []
        
        search_pattern = f"{self._base_file_path}_*_results.json"
        for file_path in glob.glob(search_pattern):
            filename = os.path.basename(file_path)
            base_name = os.path.basename(self._base_file_path)
            case_name = filename.replace(base_name + "_", "").replace("_results.json", "")
            
            c_type = "Linear Static"
            if hasattr(self.model, 'load_cases') and case_name in self.model.load_cases:
                case_obj = self.model.load_cases[case_name]
                c_type = getattr(case_obj, 'case_type', getattr(case_obj, 'type', 'Linear Static'))
            elif hasattr(self.model, 'load_combos') and case_name in self.model.load_combos:
                c_type = 'Load Combination'
                
            if c_type in ["Modal", "Buckling", "LTHA"]:
                continue

            valid_cases.append(case_name)
        current_idx = -1
        
        for i, case_name in enumerate(valid_cases):
            self.case_combo.addItem(case_name, case_name)
            if case_name == active_case:
                current_idx = i

        if current_idx >= 0:
            self.case_combo.setCurrentIndex(current_idx)

        self.case_combo.blockSignals(False)

    def _update_force_source_label(self):
        engine = 'OpenSees' if self.is_opensees else 'Native'
        self.setWindowTitle(f"Element {self.element_id} - Free Body Diagrams [{engine}]")
        is_combo = _load_combination_name(self.results, self.model) is not None
        state_label = (' | Load combination' if is_combo else
                       f' | {_force_state_label(self.results, self.step_number)}' if self.is_opensees else '')
        self.force_source_label.setText(f"Force recovery: {engine}{state_label}")

    def _populate_force_state_switcher(self):
        is_combo = _load_combination_name(self.results, self.model) is not None
        if is_combo:
            self.step_number = None
        self.state_selector.setVisible(self.is_opensees and not is_combo)
        self.state_selector.populate(self.results if self.is_opensees and not is_combo else {}, self.step_number)

    def _on_force_state_changed(self):
        if not self.is_opensees:
            return
        selected = self.force_state_combo.currentData()
        if selected == self.step_number:
            return
        self.step_number = selected
        self._refresh_force_views()
        self.state_selector.mark_applied(selected)

    def _on_case_switched(self):
        import glob
        target_case = self.case_combo.currentData()
        if not target_case: return

        new_results = f"{self._base_file_path}_{target_case}_results.json"
        new_matrices = f"{self._base_file_path}_{target_case}_matrices.json"

        self.results = self._load_json(new_results)
        self.is_opensees = is_opensees_result(self.results, self.model)
        if self.is_opensees:
            new_matrices = None
            self.matrices = {}
        else:
            if not os.path.exists(new_matrices):
                search = glob.glob(f"{self._base_file_path}_*_matrices.json")
                if search: new_matrices = search[0]
            self.matrices = self._load_json(new_matrices)

        self.results_path = new_results
        self.matrices_path = new_matrices
        self.step_number = None
        self._populate_force_state_switcher()
        self._refresh_force_views()

    def _refresh_force_views(self):
        """Refresh forces after a case/state change while retaining inspection controls."""
        self._run_analyzer()
        self._update_force_source_label()
        self.force_status_label.setText(self.force_recovery_error or '')
        self.force_status_label.setVisible(bool(self.force_recovery_error))
        self._rebuild_tabs()

    def _rebuild_tabs(self):
        """Rebuild every tab from the current data, keeping tab, axis and inspection position."""
        prev_tab_index = self.tabs.currentIndex()
        prev_nvm_axis_idx = self.nvm_combo.currentIndex()
        prev_defl_idx = self.defl_combo.currentIndex()
        if self.nvm_slider.maximum() > 0:
            self._inspection_fraction = self.nvm_slider.value() / self.nvm_slider.maximum()
        prev_slider_fraction = getattr(self, '_inspection_fraction', 0.0)

        while self.tabs.count() > 0:
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()

        self.add_axial_tab()
        self.add_Minor_axis_tab()
        self.add_Major_axis_tab()
        self.add_torsion_tab()
        self.add_nvm_tab()

        self.nvm_combo.blockSignals(True)
        self.nvm_combo.setCurrentIndex(prev_nvm_axis_idx)
        self.nvm_combo.blockSignals(False)

        self.defl_combo.blockSignals(True)
        self.defl_combo.setCurrentIndex(prev_defl_idx)
        self.defl_combo.blockSignals(False)

        self.update_nvm_plot()
        self.nvm_slider.setValue(round(prev_slider_fraction * self.nvm_slider.maximum()))

        self.tabs.setCurrentIndex(prev_tab_index)

    def _drop_theme_listener(self, *_):
        off_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, *_):
        """Live Light/Dark switch: restyle the dialog and redraw every figure."""
        try:
            apply_dialog_style(self)
            self.state_selector.restyle()
            self._rebuild_tabs()
        except RuntimeError:                                                           
            self._drop_theme_listener()

    def _run_analyzer(self):
        """Forces the FBD Viewer to use the exact same MemberAnalyzer as the 3D graphics."""
        self.forces_base = None
        self.forces = None
        self._nvm_cache = None
        self.force_recovery_error = None
        if _load_combination_name(self.results, self.model) is not None:
            self.step_number = None
        
        if int(self.element_id) not in self.model.elements: return
        
        analyzer = MemberAnalyzer(
            element=self.element,
            model=self.model,
            num_stations=101,
            matrices_path=self.matrices_path,
            results_dict=self.results,
            step_number=self.step_number,
            results_path=self.results_path,
        )
        self.is_opensees = analyzer.is_opensees
        self.force_recovery_error = analyzer.force_recovery_error
        if not analyzer.forces_loaded:
            if not self.force_recovery_error:
                self.force_recovery_error = 'No member force data found for this result.'
            return
        
        self.forces_base = analyzer.end_forces
        self.forces = np.zeros(12)
        for i in range(12):
            if i % 6 < 3:                                 
                self.forces[i] = unit_registry.to_display_force(self.forces_base[i])
            else:                                  
                self.forces[i] = unit_registry.to_display_force(self.forces_base[i])
                if self.is_opensees:
                    self.forces[i] *= unit_registry.length_scale
                
        self._nvm_cache = (
            analyzer.stations, analyzer.P, analyzer.V2, analyzer.V3, analyzer.M2, analyzer.M3,
            analyzer.Defl_2_Rel, analyzer.Defl_3_Rel, analyzer.Defl_2_Abs, analyzer.Defl_3_Abs,
            analyzer.T
        )

    def add_nvm_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.nvm_fig = Figure(figsize=(8, 5.5), dpi=100, facecolor=THEME['bg_panel'])
        self.nvm_canvas = FigureCanvas(self.nvm_fig)
        self.nvm_canvas.setMinimumSize(560, 520)
        self.nvm_canvas.mpl_connect('resize_event', self._on_canvas_resize)
        layout.addWidget(self.nvm_canvas)

        self.nvm_combo = QComboBox()
        self.nvm_combo.addItems(["Minor Axis (P, V3, M2, Deflection)", "Major Axis (P, V2, M3, Deflection)", "Torsion Axis (P, --, T, --)"])
        
        self.defl_combo = QComboBox()
        self.defl_combo.addItems(["Relative to Beam Ends", "Absolute"])
        self.defl_combo.setEnabled(not self.is_opensees)
        if self.is_opensees:
            self.defl_combo.setToolTip('Deflection is unavailable in this OpenSees force output.')

        combo_layout = QHBoxLayout()
        combo_layout.addWidget(self.nvm_combo)
        combo_layout.addWidget(self.defl_combo)
        combo_layout.addStretch()                          
        layout.addLayout(combo_layout)

        slider_widget = QWidget()
        self.slider_layout = QHBoxLayout(slider_widget)
        self.slider_layout.setContentsMargins(0, 0, 0, 0)
        
        self.nvm_slider = QSlider(Qt.Orientation.Horizontal)
        station_count = len(self._nvm_cache[0]) if self._nvm_cache is not None else 0
        self.nvm_slider.setRange(0, max(0, station_count - 1))
        self.nvm_slider.setEnabled(station_count > 0)
        self.nvm_slider.setValue(0)
        
        self.nvm_slider.setStyleSheet(_slider_qss())
        self.slider_layout.addWidget(self.nvm_slider)
        layout.addWidget(slider_widget)

        self.nvm_val_label = QLabel(self.force_recovery_error or "Move the slider to inspect values at any position along the beam.")
        self.nvm_val_label.setWordWrap(True)
        self.nvm_val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nvm_val_label.setStyleSheet(_value_label_qss())
        layout.addWidget(self.nvm_val_label)

        self.tabs.addTab(tab, "NVM & Deflection")

        self._nvm_axes   = None                         
        self._nvm_arrays = None                                         
        self._nvm_vlines = []                                  

        self.nvm_combo.currentIndexChanged.connect(self.update_nvm_plot)
        self.defl_combo.currentIndexChanged.connect(self.update_nvm_plot)
        self.nvm_slider.valueChanged.connect(self._update_nvm_slider)

        self.update_nvm_plot()

    def _on_canvas_resize(self, event):
        """Rebuild the background cache if the window resizes to prevent graphical tearing."""
        if not hasattr(self, '_nvm_vlines') or not self._nvm_vlines: return
            
        for vl in self._nvm_vlines:
            vl.set_visible(False)
            
        self.nvm_canvas.draw()
        self._bg_cache = self.nvm_canvas.copy_from_bbox(self.nvm_fig.bbox)
        
        for vl in self._nvm_vlines:
            vl.set_visible(True)
            
        self._sync_slider_layout()
        
    def _sync_slider_layout(self):
        """Align the QSlider handle exactly with the Matplotlib axes."""
        if not hasattr(self, '_nvm_axes') or not self._nvm_axes: return
        bbox = self._nvm_axes[3].get_position() 
        canvas_w = self.nvm_canvas.width()
        left_margin = max(0, int(bbox.x0 * canvas_w) - 8)
        right_margin = max(0, int(canvas_w - (bbox.x1 * canvas_w)) - 8)
        self.slider_layout.setContentsMargins(left_margin, 0, right_margin, 0)

    def update_nvm_plot(self):
        if self.forces_base is None: return
        self.nvm_fig.clear()

        self.nvm_fig.subplots_adjust(right=0.95, left=0.1, hspace=0.45)

        stations, P, V2, V3, M2, M3, Defl_2_Rel, Defl_3_Rel, Defl_2_Abs, Defl_3_Abs, T = self._nvm_cache

        L_scale = getattr(unit_registry, 'length_scale', 1.0)
        def to_F(v): return np.array([unit_registry.to_display_force(x) for x in v])
        def to_M(v): return np.array([unit_registry.to_display_force(x) * L_scale for x in v])
        def to_L(v): return np.array([unit_registry.to_display_length(x) for x in v])

        is_absolute = self.defl_combo.currentIndex() == 1

        idx = self.nvm_combo.currentIndex()
        if idx == 0:
            shear  = to_F(V3 if self.is_opensees else V2)
            moment = to_M(M2 if self.is_opensees else M3)
            defl   = to_L(Defl_2_Abs) if is_absolute else to_L(Defl_2_Rel)
            shear_lbl = f'Shear Force ({"V3" if self.is_opensees else "V2"}) [{self.force_unit}]'
            mom_lbl   = f'Bending Moment ({"M2" if self.is_opensees else "M3"}) [{self.moment_unit}]'
            defl_lbl  = f'{"Absolute" if is_absolute else "Relative"} Deflection (u2) [{self.length_unit}]'

        elif idx == 1:
            shear  = to_F(V2 if self.is_opensees else V3)
            moment = to_M(M3 if self.is_opensees else M2)
            defl   = to_L(Defl_3_Abs) if is_absolute else to_L(Defl_3_Rel)
            shear_lbl = f'Shear Force (V2) [{self.force_unit}]'
            mom_lbl   = f'Bending Moment (M3) [{self.moment_unit}]'
            defl_lbl  = f'{"Absolute" if is_absolute else "Relative"} Deflection (u3) [{self.length_unit}]'

        else:                                             
            shear  = np.zeros_like(P)
            moment = to_M(T)
            defl   = np.zeros_like(P)
            shear_lbl = f'Shear Force (--)'
            mom_lbl   = f'Torsional Moment (Mx) [{self.moment_unit}]'
            defl_lbl  = f'Twist (--)'

        if self.is_opensees:
            defl = np.full_like(P, np.nan)
            defl_lbl = 'Deflection'

        axial  = to_F(P)
        x_disp = stations * L_scale

        self._nvm_arrays = (x_disp, axial, shear, moment, defl)

        C_POS  = '#4a90d9'                               
        C_NEG  = '#d9534f'                                   
        C_LINE = THEME['text_primary']                       
        C_ZERO = THEME['text_secondary']

        def fill_signed(ax, x, y):
            ax.plot(x, y, color=C_LINE, linewidth=1.8, zorder=3)
            ax.fill_between(x, 0, y, where=(y >= 0), color=C_POS, alpha=0.55, interpolate=True)
            ax.fill_between(x, 0, y, where=(y <  0), color=C_NEG, alpha=0.55, interpolate=True)

        ax1 = self.nvm_fig.add_subplot(411)
        fill_signed(ax1, x_disp, axial)
        ax1.axhline(0, color=C_ZERO, linewidth=0.8)
        ax1.set_title(f'Axial Force (P) [{self.force_unit}]', fontsize=9, fontweight='bold')
        ax1.grid(True, linestyle='--', alpha=0.5)

        ax2 = self.nvm_fig.add_subplot(412)
        fill_signed(ax2, x_disp, shear)
        ax2.axhline(0, color=C_ZERO, linewidth=0.8)
        ax2.set_title(shear_lbl, fontsize=9, fontweight='bold')
        ax2.grid(True, linestyle='--', alpha=0.5)

        ax3 = self.nvm_fig.add_subplot(413)
        fill_signed(ax3, x_disp, moment)
        ax3.axhline(0, color=C_ZERO, linewidth=0.8)
        ax3.set_title(mom_lbl, fontsize=9, fontweight='bold')
        ax3.grid(True, linestyle='--', alpha=0.5)
        ax3.invert_yaxis()

        ax4 = self.nvm_fig.add_subplot(414)
        if self.is_opensees:
            ax4.set_xlim(ax1.get_xlim())
            ax4.text(0.5, 0.5, 'Unavailable in this OpenSees force output.',
                     transform=ax4.transAxes, ha='center', va='center', fontsize=9,
                     color=THEME['text_secondary'])
            ax4.set_yticks([])
        else:
            ax4.plot(x_disp, defl, color=THEME['accent'], linewidth=2.2, zorder=3)
            ax4.axhline(0, color=C_ZERO, linewidth=0.8, linestyle='--')
        ax4.set_title(defl_lbl, fontsize=9, fontweight='bold')
        ax4.grid(True, linestyle='--', alpha=0.5)

        for _ax in (ax1, ax2, ax3, ax4):
            style_plot_axes(self.nvm_fig, _ax)

        self._nvm_axes = (ax1, ax2, ax3, ax4)

        vline_kw = dict(color=THEME['accent'], linewidth=1.5, linestyle='--', zorder=6)
        self._nvm_vlines = [ax.axvline(x_disp[0], **vline_kw) for ax in self._nvm_axes]

        self.nvm_fig.tight_layout()

        for vl in self._nvm_vlines:
            vl.set_visible(False)
        
        self.nvm_canvas.draw()
        self._bg_cache = self.nvm_canvas.copy_from_bbox(self.nvm_fig.bbox)
        
        for vl in self._nvm_vlines:
            vl.set_visible(True)
                                             
        self._sync_slider_layout()
        self._update_nvm_slider(self.nvm_slider.value())
                                             
        def sync_slider_width():
            if not self._nvm_axes: return
            bbox = self._nvm_axes[3].get_position() 
            canvas_w = self.nvm_canvas.width()
            
            left_margin = int(bbox.x0 * canvas_w) - 8
            right_margin = int(canvas_w - (bbox.x1 * canvas_w)) - 8
            
            left_margin = max(0, left_margin)
            right_margin = max(0, right_margin)
            
            self.slider_layout.setContentsMargins(left_margin, 0, right_margin, 0)

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, sync_slider_width)

        self._update_nvm_slider(self.nvm_slider.value())

    def _update_nvm_slider(self, value):
        """Move the inspection line across all 4 NVM plots with zero lag."""
        if self._nvm_arrays is None or self._nvm_axes is None:
            return

        x_disp, axial, shear, moment, defl = self._nvm_arrays
        station_idx = int(np.clip(value, 0, len(x_disp) - 1))
        x_val = x_disp[station_idx]

        p_val = axial[station_idx]
        v_val = shear[station_idx]
        m_val = moment[station_idx]
        d_val = defl[station_idx]

        idx = self.nvm_combo.currentIndex()
        mom_sym = "T" if idx == 2 else "M"
        deflection_text = (f"δ = {d_val:+.6f} {self.length_unit}" if np.isfinite(d_val)
                           else 'Deflection unavailable in this force output')

        self.nvm_val_label.setText(
            f"x = {x_val:.3f} {self.length_unit}  │  "
            f"P = {p_val:+.4f} {self.force_unit}  │  "
            f"V = {v_val:+.4f} {self.force_unit}  │  "
            f"{mom_sym} = {m_val:+.4f} {self.moment_unit}  │  "
            f"{deflection_text}"
        )

        try:
            if hasattr(self, '_bg_cache'):
                self.nvm_canvas.restore_region(self._bg_cache)
                for vl in self._nvm_vlines:
                    vl.set_xdata([x_val, x_val])
                    vl.axes.draw_artist(vl)
                self.nvm_canvas.blit(self.nvm_fig.bbox)
                self.nvm_canvas.flush_events()
            else:
                raise ValueError
        except ValueError:
            for vl in self._nvm_vlines:
                vl.set_xdata([x_val, x_val])
            self.nvm_canvas.draw_idle()

        ratio = value / 100.0
        if self.is_opensees:
            station = self._nvm_cache[0][station_idx]
            ratio = float(np.clip(station / self.beam_length, 0.0, 1.0)) if self.beam_length > 0 else 0.0
        self.inspection_location_changed.emit(self.element, ratio)

    def _nvm_endpoints(self):
        """Return display-unit NVM values at x=0 (i) and x=L (j).
        Returns dict with keys: P_i, P_j, V2_i, V2_j, V3_i, V3_j,
                                M2_i, M2_j, M3_i, M3_j  (all in display units)
        """
        if self._nvm_cache is None:
            return None
        stations, P, V2, V3, M2, M3, *_ = self._nvm_cache
        L_scale = getattr(unit_registry, 'length_scale', 1.0)
        def fF(v): return unit_registry.to_display_force(v)
        def fM(v): return unit_registry.to_display_force(v) * L_scale
        return dict(
            P_i=fF(P[0]),   P_j=fF(P[-1]),
            V2_i=fF(V2[0]), V2_j=fF(V2[-1]),
            V3_i=fF(V3[0]), V3_j=fF(V3[-1]),
            M2_i=fM(M2[0]), M2_j=fM(M2[-1]),
            M3_i=fM(M3[0]), M3_j=fM(M3[-1]),
        )

    def _force_end_locations(self):
        """Return displayed force locations and labels at the analyzed ends."""
        if self.is_opensees and self._nvm_cache is not None:
            stations = self._nvm_cache[0]
            return (unit_registry.to_display_length(stations[0]),
                    unit_registry.to_display_length(stations[-1]), 'i face', 'j face')
        return 0.0, self.beam_length_display, 'i', 'j'

    def _theme_fig_text(self, fig):
        """Matplotlib text defaults to black; recolour it for the active theme."""
        for t in fig.findobj(MplText):
            t.set_color(THEME['text_primary'])

    def _add_value_table(self, ax_table, rows, col_labels=('Location', 'Symbol', 'Value', 'Unit')):
        """Render a clean summary table in the given axes."""
        self._theme_fig_text(ax_table.figure)
        ax_table.axis('off')
        tbl = ax_table.table(
            cellText=rows,
            colLabels=col_labels,
            colWidths=[0.40, 0.15, 0.25, 0.20] if self.is_opensees else None,
            loc='center',
            cellLoc='center'
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(10)
        tbl.scale(1, 1.8)

        for c in range(len(col_labels)):
            cell = tbl[0, c]
            cell.set_facecolor(THEME['bg_table_header'])
            cell.set_edgecolor(THEME['border'])
            cell.set_text_props(color=THEME['text_primary'], fontweight='bold')

        for r in range(1, len(rows) + 1):
            for c in range(len(col_labels)):
                cell = tbl[r, c]
                cell.set_facecolor(THEME['bg_table_alt'] if r % 2 == 0 else THEME['bg_panel'])
                cell.set_edgecolor(THEME['border'])
                cell.set_text_props(color=THEME['text_primary'])

    def add_axial_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        figure = Figure(figsize=(8, 5), dpi=100, facecolor=THEME['bg_panel'], layout='constrained')
        canvas = FigureCanvas(figure)
        canvas.setMinimumSize(520, 340)
        layout.addWidget(canvas)
        self.tabs.addTab(tab, "Axial Force (P)")

        if self.forces is None: return

        gs = figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax = figure.add_subplot(gs[0])
        ax_table = figure.add_subplot(gs[1])
        
        x_i_display, L_display, i_label, j_label = self._force_end_locations()
        L_norm = 10                                 
        
        ax.plot([0, L_norm], [0, 0], color=self.COLORS['beam'], linewidth=3, solid_capstyle='round')
        ax.plot([0, 0], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)          
        ax.plot([L_norm, L_norm], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)          
        
        ax.text(0, -0.8, f'{i_label}\n({x_i_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        ax.text(L_norm, -0.8, f'{j_label}\n({L_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        
        fx_i = self.forces[0]
        fx_j = self.forces[6]
        
        self._draw_axial_arrow(ax, 0, fx_i, 'left', L_norm)
        self._draw_axial_arrow(ax, L_norm, fx_j, 'right', L_norm)

        ax.set_ylim(-2, 2)
        ax.set_xlim(-3, L_norm + 3)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title(f'Axial Force Diagram (Fx) [{self.force_unit}]', 
                    fontsize=12, fontweight='bold', pad=20)
        
        nvm = self._nvm_endpoints()
        p_i = nvm['P_i'] if nvm else abs(unit_registry.to_display_force(self.forces_base[0]))
        p_j = nvm['P_j'] if nvm else abs(unit_registry.to_display_force(self.forces_base[6]))
        self._add_value_table(ax_table, [
            [f'{i_label}  (x = {x_i_display:.2f} {self.length_unit})',  'P', f'{abs(p_i):.4f}', self.force_unit],
            [f'{j_label}  (x = {L_display:.2f} {self.length_unit})', 'P', f'{abs(p_j):.4f}', self.force_unit],
        ])
        
        canvas.draw()

    def add_Minor_axis_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        figure = Figure(figsize=(8, 6), dpi=100, facecolor=THEME['bg_panel'], layout='constrained')
        canvas = FigureCanvas(figure)
        canvas.setMinimumSize(520, 340)
        layout.addWidget(canvas)
        self.tabs.addTab(tab, "Minor Axis (V3-M2)")

        if self.forces is None: return

        gs = figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax = figure.add_subplot(gs[0])
        ax_table = figure.add_subplot(gs[1])
        
        x_i_display, L_display, i_label, j_label = self._force_end_locations()
        L_norm = 10
        
        ax.plot([0, L_norm], [0, 0], color=self.COLORS['beam'], linewidth=3, solid_capstyle='round')
        ax.plot([0, 0], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        ax.plot([L_norm, L_norm], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        
        ax.text(0, -0.6, f'{i_label}\n({x_i_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        ax.text(L_norm, -0.6, f'{j_label}\n({L_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        
        fy_i = self.forces[2 if self.is_opensees else 1]
        fy_j = self.forces[8 if self.is_opensees else 7]
        
        self._draw_shear_arrow(ax, 0, fy_i, 'left', L_norm)
        self._draw_shear_arrow(ax, L_norm, fy_j if self.is_opensees else -fy_j, 'right', L_norm)
        
        mz_i = self.forces[4 if self.is_opensees else 5]
        mz_j = self.forces[10 if self.is_opensees else 11]
        
        self._draw_moment(ax, 0, mz_i, 'left', L_norm)
        self._draw_moment(ax, L_norm, mz_j, 'right', L_norm)

        ax.set_ylim(-3.5, 3.5)
        ax.set_xlim(-3, L_norm + 3)
        ax.set_aspect('equal')
        ax.axis('off')
        axis_forces = 'Fz' if self.is_opensees else 'Fy'
        axis_moments = 'My' if self.is_opensees else 'Mz'
        ax.set_title(f'Minor Axis Bending - {axis_forces} [{self.force_unit}], {axis_moments} [{self.moment_unit}]', 
                    fontsize=12, fontweight='bold', pad=20)
        
        nvm = self._nvm_endpoints()
        v2_i = nvm['V2_i'] if nvm else abs(self.forces[1])
        v2_j = nvm['V2_j'] if nvm else abs(self.forces[7])
        m3_i = nvm['M3_i'] if nvm else abs(self.forces[5])
        m3_j = nvm['M3_j'] if nvm else abs(self.forces[11])
        if self.is_opensees and nvm:
            v2_i, v2_j = nvm['V3_i'], nvm['V3_j']
            m3_i, m3_j = nvm['M2_i'], nvm['M2_j']
        self._add_value_table(ax_table, [
                                                             
            [f'{i_label}  (x = {x_i_display:.2f} {self.length_unit})',  'V3', f'{abs(v2_i):.4f}', self.force_unit],
            [f'{j_label}  (x = {L_display:.2f} {self.length_unit})', 'V3', f'{abs(v2_j):.4f}', self.force_unit],
            [f'{i_label}  (x = {x_i_display:.2f} {self.length_unit})',  'M2', f'{abs(m3_i):.4f}', self.moment_unit],
            [f'{j_label}  (x = {L_display:.2f} {self.length_unit})', 'M2', f'{abs(m3_j):.4f}', self.moment_unit],
        ])
        
        canvas.draw()

    def add_Major_axis_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        figure = Figure(figsize=(8, 6), dpi=100, facecolor=THEME['bg_panel'], layout='constrained')
        canvas = FigureCanvas(figure)
        canvas.setMinimumSize(520, 340)
        layout.addWidget(canvas)
        self.tabs.addTab(tab, "Major Axis (M3-V2)")

        if self.forces is None: return

        gs = figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax = figure.add_subplot(gs[0])
        ax_table = figure.add_subplot(gs[1])
        
        x_i_display, L_display, i_label, j_label = self._force_end_locations()
        L_norm = 10
        
        ax.plot([0, L_norm], [0, 0], color=self.COLORS['beam'], linewidth=3, solid_capstyle='round')
        ax.plot([0, 0], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        ax.plot([L_norm, L_norm], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        
        ax.text(0, -0.6, f'{i_label}\n({x_i_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        ax.text(L_norm, -0.6, f'{j_label}\n({L_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        
        fz_i = self.forces[1 if self.is_opensees else 2]
        fz_j = self.forces[7 if self.is_opensees else 8]
        
        self._draw_shear_arrow(ax, 0, fz_i, 'left', L_norm)
        self._draw_shear_arrow(ax, L_norm, fz_j, 'right', L_norm)
        
        my_i = self.forces[5 if self.is_opensees else 4]
        my_j = self.forces[11 if self.is_opensees else 10]
        
        self._draw_moment(ax, 0, -my_i if self.is_opensees else my_i, 'left', L_norm)
        self._draw_moment(ax, L_norm, -my_j if self.is_opensees else my_j, 'right', L_norm)

        ax.set_ylim(-3.5, 3.5)
        ax.set_xlim(-3, L_norm + 3)
        ax.set_aspect('equal')
        ax.axis('off')
        axis_forces = 'Fy' if self.is_opensees else 'Fz'
        axis_moments = 'Mz' if self.is_opensees else 'My'
        ax.set_title(f'Major Axis Bending - {axis_forces} [{self.force_unit}], {axis_moments} [{self.moment_unit}]', 
                    fontsize=12, fontweight='bold', pad=20)
        
        nvm = self._nvm_endpoints()
        v3_i = nvm['V3_i'] if nvm else abs(self.forces[2])
        v3_j = nvm['V3_j'] if nvm else abs(self.forces[8])
        m2_i = nvm['M2_i'] if nvm else abs(self.forces[4])
        m2_j = nvm['M2_j'] if nvm else abs(self.forces[10])
        if self.is_opensees and nvm:
            v3_i, v3_j = nvm['V2_i'], nvm['V2_j']
            m2_i, m2_j = nvm['M3_i'], nvm['M3_j']
        self._add_value_table(ax_table, [
                                                             
            [f'{i_label}  (x = {x_i_display:.2f} {self.length_unit})',  'V2', f'{abs(v3_i):.4f}', self.force_unit],
            [f'{j_label}  (x = {L_display:.2f} {self.length_unit})', 'V2', f'{abs(v3_j):.4f}', self.force_unit],
            [f'{i_label}  (x = {x_i_display:.2f} {self.length_unit})',  'M3', f'{abs(m2_i):.4f}', self.moment_unit],
            [f'{j_label}  (x = {L_display:.2f} {self.length_unit})', 'M3', f'{abs(m2_j):.4f}', self.moment_unit],
        ])
        
        canvas.draw()

    def add_torsion_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        figure = Figure(figsize=(8, 5), dpi=100, facecolor=THEME['bg_panel'], layout='constrained')
        canvas = FigureCanvas(figure)
        canvas.setMinimumSize(520, 340)
        layout.addWidget(canvas)
        self.tabs.addTab(tab, "Torsion (T)")

        if self.forces is None: return

        gs = figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.05)
        ax = figure.add_subplot(gs[0])
        ax_table = figure.add_subplot(gs[1])
        
        x_i_display, L_display, i_label, j_label = self._force_end_locations()
        L_norm = 10
        
        ax.plot([0, L_norm], [0, 0], color=self.COLORS['beam'], linewidth=3, solid_capstyle='round')
        ax.plot([0, 0], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        ax.plot([L_norm, L_norm], [-0.3, 0.3], color=self.COLORS['node'], linewidth=2.5)
        
        ax.text(0, -0.8, f'{i_label}\n({x_i_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        ax.text(L_norm, -0.8, f'{j_label}\n({L_display:.2f})', ha='center', va='top', fontsize=10, fontweight='bold')
        
        mx_i = self.forces[3]
        mx_j = self.forces[9]
        
        self._draw_torsion(ax, 0, mx_i, 'left', L_norm)
        self._draw_torsion(ax, L_norm, mx_j, 'right', L_norm)

        ax.set_ylim(-2, 2)
        ax.set_xlim(-3, L_norm + 3)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title(f'Torsional Moment Diagram (Mx) [{self.moment_unit}]', 
                    fontsize=12, fontweight='bold', pad=20)
        
        self._add_value_table(ax_table, [
            [f'{i_label}  (x = {x_i_display:.2f} {self.length_unit})',  'Mx', f'{abs(mx_i):.4f}', self.moment_unit],
            [f'{j_label}  (x = {L_display:.2f} {self.length_unit})', 'Mx', f'{abs(mx_j):.4f}', self.moment_unit],
        ])
        
        canvas.draw()

    def _draw_axial_arrow(self, ax, x_pos, force, side, beam_length=10):
        if abs(force) < 0.001: return
        arrow_len = 1.2
        y_pos = 0.5
        s = 1 if force > 0 else -1
        dx = s * arrow_len if side == 'left' else s * arrow_len

        ax.arrow(
            x_pos, y_pos, dx * 0.85, 0, head_width=0.25, head_length=0.15,
            fc=self.COLORS['axial'], ec=self.COLORS['axial'], linewidth=2, length_includes_head=True
        )

    def _draw_shear_arrow(self, ax, x_pos, force, side, beam_length=10):
        if abs(force) < 0.001: return
        arrow_len = 1.0
        dy = arrow_len if force > 0 else -arrow_len
        
        ax.arrow(x_pos, 0, 0, dy * 0.85, head_width=0.2, head_length=0.15,
                fc=self.COLORS['shear'], ec=self.COLORS['shear'], linewidth=2, length_includes_head=True)

    def _draw_moment(self, ax, x_pos, moment, side, beam_length=10):
        if abs(moment) < 0.001: return
        radius = 0.5
        theta = np.linspace(0, 1.5 * np.pi, 30)

        if moment < 0:
            arc_x = x_pos + radius * np.cos(theta)
            arc_y = radius * np.sin(theta)
        else:
            arc_x = x_pos + radius * np.cos(-theta)
            arc_y = radius * np.sin(-theta)

        ax.plot(arc_x, arc_y, color=self.COLORS['moment'], linewidth=2)

        ax.annotate('', xy=(arc_x[-1], arc_y[-1]), xytext=(arc_x[-3], arc_y[-3]),
            arrowprops=dict(arrowstyle='->', color=self.COLORS['moment'], lw=2))

    def _draw_torsion(self, ax, x_pos, torque, side, beam_length=10):
        if abs(torque) < 0.001: return
        ax.plot([x_pos, x_pos], [-0.8, 0.8], color=self.COLORS['torsion'], linewidth=2, linestyle='--', alpha=0.6)
        
        theta = np.linspace(0, 2 * np.pi, 20)
        radius = 0.4
        circ_x = x_pos + radius * np.cos(theta)
        circ_y = radius * np.sin(theta)
        
        ax.plot(circ_x, circ_y, color=self.COLORS['torsion'], linewidth=2, linestyle='-', alpha=0.8)
        
        direction = '⟲' if torque > 0 else '⟳'
        ax.text(x_pos, 0, direction, ha='center', va='center', fontsize=18, color=self.COLORS['torsion'], fontweight='bold')

    def closeEvent(self, event):
        """Hides the red dot when the user closes the FBD dialog."""
        off_theme_changed(self._on_theme_changed)
        self.inspection_closed.emit()
        super().closeEvent(event)
