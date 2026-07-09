from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QCheckBox,
                             QPushButton, QGroupBox, QRadioButton, QButtonGroup,
                             QScrollArea, QWidget, QLabel)
from PyQt6.QtCore import Qt

class ViewOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Display Options")
        self.resize(500, 480)
        self.setModal(False)

        self.main_window = parent
        self.pattern_checkboxes = {}

        self._build_ui()
        self._load_from_active_canvas()

    def _get_active_canvas(self):
        if self.main_window:
            return getattr(self.main_window, 'active_canvas', None)
        return None

    def _canvas_label(self):
        cvs = self._get_active_canvas()
        if self.main_window and cvs:
            if cvs is getattr(self.main_window, 'canvas', None):
                return "Canvas 1"
            elif cvs is getattr(self.main_window, 'canvas2', None):
                return "Canvas 2"
        return "Canvas"

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        self.lbl_target = QLabel()
        self.lbl_target.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_target.setStyleSheet("font-weight: bold; padding: 3px;")
        main_layout.addWidget(self.lbl_target)

        content_layout = QHBoxLayout()

        left_layout = QVBoxLayout()

        gen_group = QGroupBox("General")
        gen_vbox = QVBoxLayout()
        self.cb_extrude = QCheckBox("Extrude Frames")
        self.cb_areas = QCheckBox("Show Shells / Areas")
        self.cb_areas.setToolTip("Show Floors and Walls")
        self.cb_grid = QCheckBox("Show Grid")
        self.cb_ghost = QCheckBox("Ghost Structure (Stage View)")
        self.cb_ghost.setToolTip("Show off-plane elements as transparent ghosts in stage views")
        for w in (self.cb_extrude, self.cb_areas, self.cb_grid, self.cb_ghost):
            gen_vbox.addWidget(w)
        gen_group.setLayout(gen_vbox)

        joint_group = QGroupBox("Joints")
        joint_vbox = QVBoxLayout()
        self.cb_nodes = QCheckBox("Show Joints")
        self.cb_supports = QCheckBox("Show Supports")
        self.cb_constraints = QCheckBox("Show Diaphragms")
        self.cb_constraints.setToolTip("Show Master Nodes and Spiderwebs")
        self.cb_constraints.setStyleSheet("color: green;")
        for w in (self.cb_nodes, self.cb_supports, self.cb_constraints):
            joint_vbox.addWidget(w)
        joint_group.setLayout(joint_vbox)

        left_layout.addWidget(gen_group)
        left_layout.addWidget(joint_group)
        left_layout.addStretch()

        right_layout = QVBoxLayout()

        frame_group = QGroupBox("Frames / Cables")
        frame_vbox = QVBoxLayout()
        self.chk_axes = QCheckBox("Local Axes")
        self.chk_axes.setStyleSheet("color: blue;")
        self.cb_releases = QCheckBox("Releases (Partial Fixity)")
        for w in (self.chk_axes, self.cb_releases):
            frame_vbox.addWidget(w)
        frame_group.setLayout(frame_vbox)

        loads_group = QGroupBox("Loads")
        loads_vbox = QVBoxLayout()
        self.cb_show_loads = QCheckBox("Show Loads")
        self.cb_show_loads.toggled.connect(self.toggle_load_options)
        loads_vbox.addWidget(self.cb_show_loads)

        self.cb_tributary_loads = QCheckBox("Show Tributary Area Loads")
        self.cb_tributary_heatmap = QCheckBox("Show Tributary Heatmap / Yield Lines")
        self.cb_tributary_heatmap.toggled.connect(self._on_heatmap_toggled)
        self.cb_extrude.toggled.connect(self._on_extrude_toggled)
        self.cb_tributary_loads.setChecked(False)                      
        loads_vbox.addWidget(self.cb_tributary_loads)
        loads_vbox.addWidget(self.cb_tributary_heatmap)                    

        loads_vbox.addWidget(QLabel("Load Type:"))
        self.rb_nodal = QRadioButton("Nodal Only")
        self.rb_frame = QRadioButton("Frame Only")
        self.rb_both  = QRadioButton("Both")
        self.rb_both.setChecked(True)
        self.load_type_group = QButtonGroup()
        for rb in (self.rb_nodal, self.rb_frame, self.rb_both):
            self.load_type_group.addButton(rb)
            loads_vbox.addWidget(rb)

        loads_vbox.addWidget(QLabel("Visible Patterns:"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(110)
        self.scroll_widget = QWidget()
        self.pattern_layout = QVBoxLayout(self.scroll_widget)
        scroll.setWidget(self.scroll_widget)
        loads_vbox.addWidget(scroll)
        loads_group.setLayout(loads_vbox)

        right_layout.addWidget(frame_group)
        right_layout.addWidget(loads_group)
        right_layout.addStretch()

        content_layout.addLayout(left_layout, 1)
        content_layout.addLayout(right_layout, 1)
        main_layout.addLayout(content_layout)

        btn_layout = QHBoxLayout()
        btn_sync = QPushButton("↺  Sync from Active Canvas")
        btn_sync.setToolTip("Reload settings from whichever canvas is currently active")
        btn_sync.clicked.connect(self._load_from_active_canvas)

        btn_apply  = QPushButton("Apply")
        btn_apply.clicked.connect(self.on_apply)
        btn_ok     = QPushButton("OK")
        btn_ok.clicked.connect(self.on_ok)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_sync)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_apply)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        main_layout.addLayout(btn_layout)

    def _update_target_label(self):
        self.lbl_target.setText(f"{self._canvas_label()}")

    def _load_from_active_canvas(self):
        cvs = self._get_active_canvas()
        self._update_target_label()
        if not cvs:
            return

        self.cb_extrude.setChecked(cvs.view_extruded)
        self.cb_areas.setChecked(cvs.show_slabs)
        self.cb_grid.setChecked(cvs.show_grid)
        self.cb_ghost.setChecked(cvs.show_ghost_structure)
        self.cb_nodes.setChecked(cvs.show_joints)
        self.cb_supports.setChecked(cvs.show_supports)
        self.cb_constraints.setChecked(cvs.show_constraints)
        self.cb_releases.setChecked(cvs.show_releases)
        self.cb_show_loads.setChecked(cvs.show_loads)
        self.cb_tributary_loads.setChecked(getattr(cvs, 'show_tributary_loads', False))
        self.cb_tributary_heatmap.setChecked(getattr(cvs, 'show_tributary_heatmap', False))
        
        self.chk_axes.setChecked(cvs.show_local_axes)

        lt = getattr(cvs, 'load_type_filter', 'both')
        if lt == 'nodal':   self.rb_nodal.setChecked(True)
        elif lt == 'frame': self.rb_frame.setChecked(True)
        else:               self.rb_both.setChecked(True)

        self._rebuild_pattern_checkboxes(cvs)
        self.toggle_load_options(cvs.show_loads)

    def _rebuild_pattern_checkboxes(self, cvs):
        for i in reversed(range(self.pattern_layout.count())):
            w = self.pattern_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        self.pattern_checkboxes = {}

        model = getattr(self.main_window, 'model', None)
        if not model:
            return

        saved = getattr(cvs, 'visible_load_patterns', None)
        for name in model.load_patterns.keys():
            cb = QCheckBox(name)
            cb.setChecked(True if not saved else name in saved)
            self.pattern_checkboxes[name] = cb
            self.pattern_layout.addWidget(cb)

    def get_data(self):
        if self.rb_nodal.isChecked():   load_type = "nodal"
        elif self.rb_frame.isChecked(): load_type = "frame"
        else:                           load_type = "both"

        visible_patterns = [n for n, cb in self.pattern_checkboxes.items() if cb.isChecked()]
        if not visible_patterns:
            visible_patterns = ['__NONE__']

        return {
            'extrude':           self.cb_extrude.isChecked(),
            'areas':             self.cb_areas.isChecked(),
            'grid':              self.cb_grid.isChecked(),
            'ghost':             self.cb_ghost.isChecked(),
            'joints':            self.cb_nodes.isChecked(),
            'supports':          self.cb_supports.isChecked(),
            'constraints':       self.cb_constraints.isChecked(),
            'releases':          self.cb_releases.isChecked(),
            'loads':             self.cb_show_loads.isChecked(),
            'tributary_loads':   self.cb_tributary_loads.isChecked(),
            'tributary_heatmap': self.cb_tributary_heatmap.isChecked(),
            'axes':              self.chk_axes.isChecked(),
            'load_type':         load_type,
            'visible_patterns':  visible_patterns,
        }

    def toggle_load_options(self, enabled):
        for w in (self.rb_nodal, self.rb_frame, self.rb_both):
            w.setEnabled(enabled)
        for cb in self.pattern_checkboxes.values():
            cb.setEnabled(enabled)

    def _on_heatmap_toggled(self, checked):
        if checked and self.cb_extrude.isChecked():
            self.cb_extrude.setChecked(False)

    def _on_extrude_toggled(self, checked):
        if checked and self.cb_tributary_heatmap.isChecked():
            self.cb_tributary_heatmap.setChecked(False)

    def on_apply(self):
        self._update_target_label()
        if self.main_window:
            self.main_window.apply_view_options(self.get_data())

    def on_ok(self):
        self.on_apply()
        self.accept()
