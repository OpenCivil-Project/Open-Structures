from PyQt6.QtCore import QThread, pyqtSignal

class ForceComputationWorker(QThread):
    """Background thread to prevent GUI freeze during force matrix math and array generation."""
    signal_finished = pyqtSignal(bool, dict, list, int)                                   

    def __init__(self, token, model, component, scale_factor, displacements, matrices_path,
                 show_labels, show_labels_mode, text_size, active_view_plane,
                 show_ghost_structure, selected_ids, is_envelope, step_number):
        super().__init__()
        self.token = token
        self.model = model
        self.component = component
        self.scale_factor = scale_factor
        self.displacements = displacements
        self.matrices_path = matrices_path
        self.show_labels = show_labels
        self.show_labels_mode = show_labels_mode
        self.text_size = text_size
        self.active_view_plane = active_view_plane
        self.show_ghost_structure = show_ghost_structure
        self.selected_ids = selected_ids
        self.is_envelope = is_envelope
        self.step_number = step_number

    def run(self):
        from core.force_diagram import ForceDiagramBuilder
        
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
            step_number=self.step_number
        )
        
        success = builder.build()
        
        if success:
            vbo_data = {
                'fill_verts':  builder.fill_verts,
                'fill_colors': builder.fill_colors,
                'fill_faces':  builder.fill_faces,
                'line_pos':    builder.line_pos,
                'line_colors': builder.line_colors,
            }
            self.signal_finished.emit(True, vbo_data, builder.labels, self.token)
        else:
            self.signal_finished.emit(False, {}, [], self.token)
