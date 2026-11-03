import copy
import logging

from PyQt6.QtCore import QThread, pyqtSignal

class ForceComputationWorker(QThread):
    """Background thread to prevent GUI freeze during force matrix math and array generation."""
    signal_finished = pyqtSignal(bool, dict, list, int)                                   

    def __init__(self, token, model, component, scale_factor, displacements, matrices_path,
                 show_labels, show_labels_mode, text_size, active_view_plane,
                 show_ghost_structure, selected_ids, is_envelope, step_number,
                 text_builder=None, background_labels=None, text_revision=None,
                 grid_labels=None):
        super().__init__()
        self.token = token
                                                                           
        self.model = copy.copy(model)
        self.model.results = dict(getattr(model, 'results', {}) or {})
        self.model._force_source_model = model
        self.component = component
        self.scale_factor = scale_factor
        self.displacements = displacements
        self.matrices_path = matrices_path
        self.show_labels = show_labels
        self.show_labels_mode = show_labels_mode
        self.text_size = text_size
        self.active_view_plane = dict(active_view_plane) if active_view_plane else None
        self.show_ghost_structure = show_ghost_structure
        self.selected_ids = list(selected_ids or [])
        self.is_envelope = is_envelope
        self.step_number = step_number
        self.background_labels = list(background_labels or [])
        self.grid_labels = list(grid_labels or [])
        self.text_revision = text_revision
        self.text_builder = None
        if text_builder is not None:
                                                                          
            self.text_builder = copy.copy(text_builder)
            self.text_builder._char_to_row = dict(text_builder._char_to_row)
            self.text_builder._uv_rows = list(text_builder._uv_rows)

    def run(self):
        try:
            self._build_diagram()
        except Exception:
            logging.getLogger(__name__).exception('Force display generation failed')
            if not self.isInterruptionRequested():
                self.signal_finished.emit(False, {}, [], self.token)

    def _build_diagram(self):
        from core.force_diagram import ForceDiagramBuilder
        from app.graphic._vbo_force_load import prepare_force_geometry

        if self.isInterruptionRequested():
            return
        
        builder = ForceDiagramBuilder(
            self.model,
            component=self.component,
            scale_factor=self.scale_factor,
            displacements=self.displacements,
            matrices_path=self.matrices_path,
            show_labels=self.show_labels,
            show_labels_mode=self.show_labels_mode,
            text_size=self.text_size,
            active_view_plane=self.active_view_plane,                    
            show_ghost_structure=self.show_ghost_structure,
            selected_ids=self.selected_ids,
            is_envelope=self.is_envelope,
            step_number=self.step_number,
            cancelled=self.isInterruptionRequested,
        )
        
        success = builder.build()
        if self.isInterruptionRequested():
            return
        
        if success:
            vbo_data = {
                'fill_verts':  builder.fill_verts,
                'fill_colors': builder.fill_colors,
                'fill_faces':  builder.fill_faces,
                'line_pos':    builder.line_pos,
                'line_colors': builder.line_colors,
            }
            vbo_data['prepared'] = prepare_force_geometry(
                builder.fill_verts, builder.fill_colors, builder.fill_faces,
                builder.line_pos, builder.line_colors,
            )
            if self.text_builder is not None:
                vbo_data['text_geometry'] = self.text_builder.build_text_geometry(
                    self.background_labels + builder.labels + self.grid_labels,
                    default_text_height=0.25,
                )
                vbo_data['text_revision'] = self.text_revision
            if self.isInterruptionRequested():
                return
            self.signal_finished.emit(True, vbo_data, builder.labels, self.token)
        else:
            self.signal_finished.emit(False, {}, [], self.token)
