from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QListWidget,
                             QListWidgetItem, QGroupBox, QAbstractItemView,
                             QMessageBox)
from PyQt6.QtCore import Qt, QTimer
from core.units import unit_registry

def detect_stories(model, tolerance_internal):
    """
    Clusters node Z values into stories using tolerance in internal (SI) units.
    Returns:
        clusters : list of float  — representative Z for each story (internal)
        stories  : dict {cluster_z: {'frames': [], 'areas': []}}
    """
    if not model or not model.nodes:
        return [], {}

    z_values = sorted(set(round(n.z, 10) for n in model.nodes.values()))

    clusters = []
    for z in z_values:
        if clusters and abs(z - clusters[-1]) <= tolerance_internal:
                                             
            clusters[-1] = (clusters[-1] + z) / 2.0
        else:
            clusters.append(z)

    stories = {z: {'frames': [], 'areas': []} for z in clusters}
    
    for eid, elem in model.elements.items():
        top_z = max(elem.node_i.z, elem.node_j.z)
        nearest = min(clusters, key=lambda c: abs(c - top_z))
        stories[nearest]['frames'].append(eid)
        
    if hasattr(model, 'area_elements'):
        for aid, ae in model.area_elements.items():
            top_z = max(n.z for n in ae.nodes)
            nearest = min(clusters, key=lambda c: abs(c - top_z))
            stories[nearest]['areas'].append(aid)

    return clusters, stories

class SelectByStoryDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self._clusters = []
        self._stories  = {}
        self._last_snapshot = set()

        self.setWindowTitle("Select by Story")
        self.resize(340, 460)
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)

        tol_grp = QGroupBox("Detection Settings")
        tol_lay = QHBoxLayout()
        tol_lay.addWidget(QLabel("Z Tolerance:"))

        self.tol_edit = QLineEdit("0.05")
        self.tol_edit.setFixedWidth(70)
        tol_lay.addWidget(self.tol_edit)

        self.lbl_unit = QLabel(unit_registry.length_unit_name)
        tol_lay.addWidget(self.lbl_unit)
        tol_lay.addStretch()

        self.btn_detect = QPushButton("Detect Stories")
        self.btn_detect.clicked.connect(self._detect)
        tol_lay.addWidget(self.btn_detect)

        tol_grp.setLayout(tol_lay)
        layout.addWidget(tol_grp)

        list_grp = QGroupBox("Detected Stories")
        list_lay = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        list_lay.addWidget(self.list_widget)
        list_grp.setLayout(list_lay)
        layout.addWidget(list_grp)

        btn_lay = QHBoxLayout()
        self.btn_select   = QPushButton("Select")
        self.btn_deselect = QPushButton("Deselect")
        self.btn_close    = QPushButton("Close")
        self.btn_select.clicked.connect(self._do_select)
        self.btn_deselect.clicked.connect(self._do_deselect)
        self.btn_close.clicked.connect(self.close)
        btn_lay.addWidget(self.btn_select)
        btn_lay.addWidget(self.btn_deselect)
        btn_lay.addWidget(self.btn_close)
        layout.addLayout(btn_lay)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(150)
        self._poll_timer.timeout.connect(self._check_selection_changed)
        self._poll_timer.start()

        self._detect()

    def _detect(self):
        try:
            tol_display = float(self.tol_edit.text())
            if tol_display <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Input Error",
                                "Please enter a valid positive tolerance value.")
            return

        tol_internal = unit_registry.from_display_length(tol_display)

        self._clusters, self._stories = detect_stories(
            self.main_window.model, tol_internal)

        self._rebuild_list()

    def _rebuild_list(self):
        previously_selected = {
            self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list_widget.count())
            if self.list_widget.item(i).isSelected()
        }

        self.list_widget.clear()

        if not self._clusters:
            placeholder = QListWidgetItem("No stories detected.")
            placeholder.setForeground(Qt.GlobalColor.gray)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)
            self._set_buttons_enabled(False)
            return

        unit = unit_registry.length_unit_name

        for idx, z in enumerate(sorted(self._clusters)):
            story_data = self._stories.get(z, {'frames': [], 'areas': []})
            count     = len(story_data['frames']) + len(story_data['areas'])
            z_display = unit_registry.to_display_length(z)
            label     = f"Story {idx + 1}  (Z = {z_display:.3f} {unit})  — {count} elements"
            item      = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, z)                     
            if z in previously_selected:
                item.setSelected(True)
            self.list_widget.addItem(item)

        self._set_buttons_enabled(True)

    def _set_buttons_enabled(self, state):
        self.btn_select.setEnabled(state)
        has_selection = bool(self.main_window.selected_ids) or bool(getattr(self.main_window, 'selected_area_ids', []))
        self.btn_deselect.setEnabled(state and has_selection)

    def _check_selection_changed(self):
        """Update unit label and deselect button state on external changes."""
        self.lbl_unit.setText(unit_registry.length_unit_name)

        current_frames = tuple(self.main_window.selected_ids)
        current_areas = tuple(getattr(self.main_window, 'selected_area_ids', []))
        current = (current_frames, current_areas)
        
        if current != getattr(self, '_last_snapshot', None):
            self._last_snapshot = current
            has_selection = bool(current_frames) or bool(current_areas)
            self.btn_deselect.setEnabled(has_selection and bool(self._clusters))

    def _selected_cluster_zs(self):
        return [
            self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list_widget.count())
            if self.list_widget.item(i).isSelected()
        ]

    def _elem_ids_for_selected_stories(self):
        selected_zs = self._selected_cluster_zs()
        ids = []
        for z in selected_zs:
            ids.extend(self._stories.get(z, []))
        return ids

    def _refresh_overlay(self):
        mw = self.main_window
        for cvs in [mw.canvas, mw.canvas2]:
            cvs.update_selection_overlay(mw.selected_ids, mw.selected_node_ids, getattr(mw, 'selected_area_ids', []))
        
        n_frames = len(mw.selected_ids)
        n_areas = len(getattr(mw, 'selected_area_ids', []))
        mw.status.showMessage(
            f"Selected: {n_frames} Frame{'s' if n_frames != 1 else ''}, "
            f"{n_areas} Area{'s' if n_areas != 1 else ''}, "
            f"{len(mw.selected_node_ids)} Joints")

    def _do_select(self):
        selected_zs = self._selected_cluster_zs()
        if not selected_zs:
            return
        mw = self.main_window
        
        for z in selected_zs:
            story_data = self._stories.get(z, {'frames': [], 'areas': []})
            
            for eid in story_data['frames']:
                if eid not in mw.selected_ids:
                    mw.selected_ids.append(eid)
                    
            if not hasattr(mw, 'selected_area_ids'): mw.selected_area_ids = []
            for aid in story_data['areas']:
                if aid not in mw.selected_area_ids:
                    mw.selected_area_ids.append(aid)
                    
        self._refresh_overlay()

    def _do_deselect(self):
        selected_zs = self._selected_cluster_zs()
        if not selected_zs:
            return
        mw = self.main_window
        
        frames_to_remove = set()
        areas_to_remove = set()
        
        for z in selected_zs:
            story_data = self._stories.get(z, {'frames': [], 'areas': []})
            frames_to_remove.update(story_data['frames'])
            areas_to_remove.update(story_data['areas'])
            
        mw.selected_ids = [eid for eid in mw.selected_ids if eid not in frames_to_remove]
        if hasattr(mw, 'selected_area_ids'):
            mw.selected_area_ids = [aid for aid in mw.selected_area_ids if aid not in areas_to_remove]
            
        self._refresh_overlay()
        
    def closeEvent(self, event):
        self._poll_timer.stop()
        super().closeEvent(event)
