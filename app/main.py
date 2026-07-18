import sys
import os
import math
import ctypes
import time
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QAction, QPixmap,QCursor, QVector3D, QColor, QIcon
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                             QMessageBox, QFileDialog, QSplashScreen, QLabel, 
                             QComboBox,QProgressBar, QProgressDialog, QSplitter, QSizePolicy, QFrame)
from PyQt6.QtWidgets import QMenu
from PyQt6.QtGui import QCursor
from PyQt6.QtGui import QUndoStack  
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices, QSoundEffect
from PyQt6.QtCore import QUrl
from PyQt6.QtMultimediaWidgets import QVideoWidget  
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, pyqtSignal
import qtawesome as qta
from PyQt6.QtGui import QAction, QPixmap, QCursor, QVector3D, QColor, QIcon, QPainter, QFont
from PyQt6.QtGui import QActionGroup
import pyqtgraph.opengl as gl
if getattr(sys, 'frozen', False):

    if hasattr(sys, '_MEIPASS'):
        root_dir = sys._MEIPASS
    else:
        root_dir = os.path.dirname(sys.executable)

    current_dir = root_dir 
else:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)

sys.path.append(root_dir)

from app.commands import CmdDrawFrame, CmdDeleteSelection, CmdReplicate, CmdAssignInsertion, CmdDrawAreaElement
from core.model import StructuralModel, LoadCase
from app.canvas import MCanvas3D
from app.dialogs.material_dialog import MaterialManagerDialog
from app.dialogs.draw_dialog import DrawFrameDialog
from app.dialogs.load_pattern_dialog import LoadPatternDialog
from app.dialogs.draw_cross_brace_dialog import DrawCrossBraceDialog
from app.dialogs.draw_beam_column_dialog import DrawBeamColumnDialog
from app.dialogs.view_options_dialog import ViewOptionsDialog
from app.dialogs.graphics_dialog import GraphicsOptionsDialog
from core.units import unit_registry
from app.dialogs.assign_frame_point_load_dialog import AssignFramePointLoadDialog
from app.dialogs.analysis_dialog import AnalysisDialog
from app.solver_worker import SolverWorker
from app.dialogs.deformed_shape_dialog import DeformedShapeDialog
from app.dialogs.mass_source_dialog import MassSourceManagerDialog
from app.auth import GoogleAuthManager, UserProfileWidget
from app.dialogs.time_history_manager import TimeHistoryManagerDialog
from app.dialogs.solid_analysis_dialog import SolidAnalysisDialog
from app.dialogs.update_dialog import UpdateDialog
from core.terminal_panel import TerminalPanel
from app.ipc import IPCManager
from app.dialogs.analysis_progress_dialog import AnalysisProgressDialog
from app.dialogs.area_mesh_dialog import AreaMeshDialog
from release_notes import RELEASE_NOTES, NOTICES
from app.dialogs.display_reactions_dialog import DisplayReactionsDialog
from app.dialogs.model_io_dialog import ModelIODialog, LAUNCH_ON_ANALYSIS

class OpenStructureSplash(QSplashScreen):
    def __init__(self, pixmap):
        super().__init__(pixmap)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        
        w = pixmap.width()
        h = pixmap.height()
        bar_height = 10 
        
        self.label_status = QLabel(self)
        self.label_status.setGeometry(20, h - bar_height - 35, w - 40, 30) 
        self.label_status.setText("Initializing...")
        
        self.label_status.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px; 
                font-weight: 600;
                background-color: transparent;
            }
        """)

        self.progressBar = QProgressBar(self)
        self.progressBar.setGeometry(0, h - bar_height, w, bar_height)
        self.progressBar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #1e1e1e;
            }
            QProgressBar::chunk {
                background-color: #0078D7; 
            }
        """)
        self.progressBar.setTextVisible(False) 
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)

    def progress(self, value, message=None):
        self.progressBar.setValue(value)
        if message:
            self.label_status.setText(message)
                         
        QApplication.processEvents()

class VideoSplash(QWidget):
    finished = pyqtSignal()

    def __init__(self, video_path):
        super().__init__()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.resize(800, 450) 
        self.center_on_screen()

        self.video_widget = QVideoWidget(self)
                                                                                    
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)

        self.player.setVideoOutput(self.video_widget)
        self.player.setAudioOutput(self.audio_output)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_widget)

        self.player.setSource(QUrl.fromLocalFile(video_path))
        self.audio_output.setVolume(0.7)

        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.player.errorOccurred.connect(self.finished.emit)

    def start(self):
        self.player.setPlaybackRate(2.0)
        self.player.play()

    def cleanup_player(self):
        """Aggressively tears down FFmpeg to prevent ghost processes."""
        if hasattr(self, 'player') and self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl()) 
                                                                        
            self.player.setVideoOutput(None) 
            self.player.setAudioOutput(None)
            self.player.deleteLater()
            self.player = None
            
        if hasattr(self, 'audio_output') and self.audio_output is not None:
            self.audio_output.deleteLater()
            self.audio_output = None

    def on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.cleanup_player()
            self.finished.emit()

    def center_on_screen(self):
        qr = self.frameGeometry()
        cp = QApplication.primaryScreen().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

from PyQt6.QtCore import QObject, QEvent, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import QDialog

class GlobalDialogAnimator(QObject):
    """Intercepts all QDialogs globally and applies a fade-in animation."""
    def eventFilter(self, obj, event):
                                                            
        if event.type() == QEvent.Type.Show and isinstance(obj, QDialog):
            if not obj.property("_ghost_animated"):
                obj.setProperty("_ghost_animated", True)
                
                obj.setWindowOpacity(0.0)
                
                anim = QPropertyAnimation(obj, b"windowOpacity", obj)
                anim.setDuration(200) 
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
                
                obj._ghost_anim = anim
                anim.start()
        
        elif event.type() == QEvent.Type.Hide and isinstance(obj, QDialog):
            obj.setProperty("_ghost_animated", False)
                
        return super().eventFilter(obj, event)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.model = None 

        self.undo_stack = QUndoStack(self)
        self.undo_stack.indexChanged.connect(self._on_model_changed)

        self.graphics_settings = {
            "background_color": (1.0, 1.0, 1.0, 1.0), 
            "antialias": True,
            "node_size": 6,
            "node_color": (1.0, 0.0, 0.0, 1.0),     
            "line_width": 2.0,
            "extrude_opacity": 0.35,
            "show_edges": True,
            "msaa_level": 2,
            "edge_width": 1.5,
            "edge_color": (0.0, 0.0, 0.0, 1.0),      
            "slab_opacity": 0.4
        }

        import json as _json
        _prefs_path = os.path.join(os.path.expanduser("~"), ".Open//Structures_prefs.json")
        if os.path.exists(_prefs_path):
            try:
                with open(_prefs_path) as _f:
                    _saved = _json.load(_f)
                    for _k in ("background_color", "node_color", "edge_color"):
                        if _k in _saved and isinstance(_saved[_k], list):
                            _saved[_k] = tuple(_saved[_k])
                                                                               
                    if _saved.get("node_color") == (1.0, 1.0, 0.0, 1.0):
                        _saved["node_color"] = (1.0, 0.0, 0.0, 1.0)
                    self.graphics_settings.update(_saved)
            except Exception:
                pass
        
        self.setWindowTitle("Open//Structures v0.7.82")
        self.resize(1200, 800)

        icon_path = os.path.join(root_dir, "app", "graphic", "logo.png") 
        
        if not os.path.exists(icon_path):
             icon_path = os.path.join(current_dir, "logo.ico")

        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.draw_mode_active = False
        self.draw_link2_mode_active = False
        self.draw_link1_mode_active = False
        self.draw_link2_dialog = None
        self.draw_link1_dialog = None
        self.draw_start_node = None 
        self.draw_dialog = None
        self.cross_brace_mode_active = False
        self.cross_brace_dialog = None
        self.beam_col_mode_active = False
        self.beam_col_dialog = None
        self.selected_ids = []
        self.selected_node_ids = []
        self.selected_area_ids = []
        
        self.picking_replicate = False 
        self.replicate_p1 = None      
        self.replicate_dialog = None

        self.sound_effect = QSoundEffect()
        
        self.sound_effect.setLoopCount(QSoundEffect.Loop.Infinite.value) 
        
        self.sound_effect.setVolume(0.5) 

        sound_path = os.path.join(root_dir, "app", "graphic", "animation_loop.wav")
        if os.path.exists(sound_path):
            self.sound_effect.setSource(QUrl.fromLocalFile(sound_path))
        else:
            print(f"Warning: Sound file not found at {sound_path}")

        self.draw_area_mode_active = False
        self.draw_area_dialog = None
        self._current_area_nodes = []

        self.draw_link2_mode_active = False
        self.draw_link1_mode_active = False
        self.draw_link2_dialog = None
        self.draw_link1_dialog = None
        
        self.init_ui()
        QApplication.instance().applicationStateChanged.connect(self._on_app_state_changed)
        self.set_interface_state(False)
    
    def init_ui(self):
        """Organizes all UI components"""

        def create_plane_icon(text):
            pixmap = QPixmap(32, 32)
            pixmap.fill(QColor(0, 0, 0, 0)) 
            painter = QPainter(pixmap)
            painter.setPen(QColor('#6c757d')) 
            painter.setFont(QFont('Segoe UI', 15, QFont.Weight.Bold))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
            painter.end()
            return QIcon(pixmap)
        
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenu::separator {
                height: 2px;
                background: #b7bec7;
                margin: 6px 10px;
            }
        """)

        file_menu = menubar.addMenu("File")
        
        new_action = QAction(qta.icon('fa5s.file-medical', color='#6c757d'), "New Model...", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.on_new_model)
        file_menu.addAction(new_action)
        
        open_action = QAction(qta.icon('fa5s.folder-open', color='#6c757d'), "Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.on_open_model)
        file_menu.addAction(open_action)

        self.action_save = QAction(qta.icon('fa5s.save', color='#6c757d'), "Save As...", self)
        self.action_save.setShortcut("Ctrl+S")
        self.action_save.triggered.connect(self.on_save_model)
        file_menu.addAction(self.action_save)
        
        file_menu.addSeparator()

        self.menu_edit = menubar.addMenu("Edit")

        self.undo_action = self.undo_stack.createUndoAction(self, "Undo")
        self.undo_action.setIcon(qta.icon('fa5s.undo', color='#6c757d', disabled_color='#cccccc'))
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.setToolTip("Undo (Ctrl+Z)")
        self.menu_edit.addAction(self.undo_action)

        self.redo_action = self.undo_stack.createRedoAction(self, "Redo")
        self.redo_action.setIcon(qta.icon('fa5s.redo', color='#6c757d', disabled_color='#cccccc'))
        self.redo_action.setShortcut("Ctrl+Y")                                          
        self.redo_action.setToolTip("Redo (Ctrl+Y)")
        self.menu_edit.addAction(self.redo_action)
        
        self.menu_edit.addSeparator()

        relabel_action = QAction(qta.icon('fa5s.tags', color='#6c757d'), "Auto-Relabel Members...", self)
        def show_relabel_ui():
            from app.dialogs.relabel_dialog import RelabelDialog
            dlg = RelabelDialog(self)
            dlg.exec()
        relabel_action.triggered.connect(show_relabel_ui)
        self.menu_edit.addAction(relabel_action)
                                  
        reset_labels_action = QAction(qta.icon('fa5s.undo-alt', color='#6c757d'), "Reset Labels to Default", self)
        def reset_all_labels():
            if not self.model: return
            
            for n in self.model.nodes.values():
                n.label = f"N{n.id}"
                
            for el in self.model.elements.values():
                el.label = f"F{el.id}"
                
            if hasattr(self.model, 'area_elements'):
                for ae in self.model.area_elements.values():
                    ae.label = f"A{ae.id}"
                    
            if hasattr(self.model, 'slabs'):
                for sl in self.model.slabs.values():
                    sl.label = f"S{sl.id}"
                    
            self.status.showMessage("All labels successfully reverted to default.")
            self.refresh_canvas()
            
        reset_labels_action.triggered.connect(reset_all_labels)
        self.menu_edit.addAction(reset_labels_action)

        self.menu_edit.addSeparator()
                                  
        rep_action = QAction(qta.icon('fa5s.copy', color='#6c757d'), "Replicate...", self)
        rep_action.setShortcut("Ctrl+R") 
        rep_action.triggered.connect(self.on_edit_replicate)
        self.menu_edit.addAction(rep_action)

        self.menu_edit.addSeparator()

        merge_action = QAction(qta.icon('fa5s.compress-arrows-alt', color='#6c757d'), "Merge Joints...", self)
        merge_action.triggered.connect(self.on_edit_merge)
        self.menu_edit.addAction(merge_action)

        self.menu_define = menubar.addMenu("Define")

        grid_action = QAction(qta.icon('fa5s.th', color='#6c757d'), "Grid System...", self)
        grid_action.triggered.connect(self.open_grid_editor)
        self.menu_define.addAction(grid_action)
        self.menu_define.addSeparator()

        mat_action = QAction(qta.icon('fa5s.cubes', color='#6c757d'), "Material Properties...", self)
        mat_action.triggered.connect(self.on_define_materials)
        self.menu_define.addAction(mat_action)

        self.menu_define.addSeparator()
        
        sec_action = QAction(qta.icon('fa5s.shapes', color='#6c757d'), "Frame Properties...", self)
        sec_action.triggered.connect(self.on_define_sections) 
        self.menu_define.addAction(sec_action)

        area_sec_action = QAction(qta.icon('fa5s.vector-square', color='#6c757d'), "Area Sections...", self)
        area_sec_action.triggered.connect(self.on_define_area_sections)
        self.menu_define.addAction(area_sec_action)

        link_action = QAction(qta.icon('fa5s.link', color='#6c757d'), "Link/Support Properties...", self)
        link_action.triggered.connect(self.on_define_link_properties) 
        self.menu_define.addAction(link_action)

        self.menu_define.addSeparator()

        mass_action = QAction(qta.icon('fa5s.weight-hanging', color='#6c757d'), "Mass Source...", self)
        mass_action.triggered.connect(self.on_define_mass_source)
        self.menu_define.addAction(mass_action)

        self.menu_define.addSeparator()

        load_pat_action = QAction(qta.icon('fa5s.list-ul', color='#6c757d'), "Load Patterns...", self)
        load_pat_action.triggered.connect(self.on_define_load_patterns)
        self.menu_define.addAction(load_pat_action)

        load_case_action = QAction(qta.icon('fa5s.tasks', color='#6c757d'), "Load Cases...", self)
        load_case_action.triggered.connect(self.on_define_load_cases)
        self.menu_define.addAction(load_case_action)

        load_combo_action = QAction(qta.icon('fa5s.layer-group', color='#6c757d'), "Load Combinations...", self)
        load_combo_action.triggered.connect(self.on_define_load_combos)
        self.menu_define.addAction(load_combo_action)

        self.menu_define.addSeparator()
        
        self.menu_functions = self.menu_define.addMenu("Functions")
                                                              
        self.menu_functions.setIcon(qta.icon('fa5s.chart-line', color='#6c757d'))
        
        rsa_action = QAction(qta.icon('fa5s.wave-square', color='#6c757d'), "Response Spectrum...", self)
        rsa_action.triggered.connect(self.on_define_response_spectrum)
        self.menu_functions.addAction(rsa_action)

        th_action = QAction(qta.icon('fa5s.history', color='#6c757d'), "Time History...", self)
        th_action.triggered.connect(self.on_define_time_history_functions)
        self.menu_functions.addAction(th_action)
        
        self.menu_define.addSeparator()

        self.menu_draw = menubar.addMenu("Draw")
        
        draw_action = QAction(qta.icon('fa5s.pencil-alt', color='#6c757d'), "Draw Frame/Cable...", self)
        draw_action.triggered.connect(self.on_draw_frame)
        self.menu_draw.addAction(draw_action)

        self.menu_draw.addSeparator()

        draw_area_action = QAction(qta.icon('fa5s.vector-square', color='#6c757d'), "Draw Poly Area...", self)
        draw_area_action.triggered.connect(self.on_draw_poly_area)
        self.menu_draw.addAction(draw_area_action)

        self.menu_draw.addSeparator()

        cross_brace_action = QAction(qta.icon('fa5s.times', color='#6c757d'), "Quick Cross Brace...", self)
        cross_brace_action.triggered.connect(self.on_draw_cross_brace)
        self.menu_draw.addAction(cross_brace_action)

        self.menu_draw.addSeparator()

        beam_col_action = QAction(qta.icon('fa5s.i-cursor', color='#6c757d'), "Quick Beam / Column...", self)
        beam_col_action.triggered.connect(self.on_draw_beam_column)
        self.menu_draw.addAction(beam_col_action)

        self.menu_draw.addSeparator()

        draw_link2_action = QAction(qta.icon('fa5s.expand-alt', color='#6c757d'), "Draw 2-Joint Link...", self)
        draw_link2_action.triggered.connect(self.on_draw_link2)
        self.menu_draw.addAction(draw_link2_action)

        draw_link1_action = QAction(qta.icon('fa5s.thumbtack', color='#6c757d'), "Draw 1-Joint Link...", self)
        draw_link1_action.triggered.connect(self.on_draw_link1)
        self.menu_draw.addAction(draw_link1_action)

        self.toolbar = self.addToolBar("Views")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(20, 20))

        self.toolbar.setStyleSheet("""
            QToolButton {
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 3px;
            }
            QToolButton:hover {
                background-color: #e9ecef; /* Soft grey on hover */
            }
            QToolButton:checked {
                background-color: #d6e4f0; /* Professional light blue when toggled ON */
                border: 1px solid #b3cce6;
            }
            QToolButton:pressed {
                background-color: #ced4da;
            }
        """)

        act_new = QAction(qta.icon('fa5s.file-medical', color='#6c757d'), "New Model", self)
        act_new.setToolTip("New Model  (Ctrl+N)")
        act_new.triggered.connect(self.on_new_model)
        self.toolbar.addAction(act_new)

        act_open = QAction(qta.icon('fa5s.folder-open', color='#6c757d'), "Open", self)
        act_open.setToolTip("Open Model  (Ctrl+O)")
        act_open.triggered.connect(self.on_open_model)
        self.toolbar.addAction(act_open)

        act_save = QAction(qta.icon('fa5s.save', color='#6c757d'), "Save", self)
        act_save.setToolTip("Save Model  (Ctrl+S)")
        act_save.triggered.connect(self.on_save_model)
        self.toolbar.addAction(act_save)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        tb_undo = QAction(qta.icon('fa5s.undo', color='#6c757d'), "Undo", self)
        tb_undo.setToolTip("Undo  (Ctrl+Z)")
        self.toolbar.addAction(self.undo_action)

        tb_redo = QAction(qta.icon('fa5s.redo', color='#6c757d'), "Redo", self)
        tb_redo.setToolTip("Redo  (Ctrl+Y)")
        self.toolbar.addAction(self.redo_action)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        act_grid = QAction(qta.icon('fa5s.th', color='#6c757d'), "Grid System", self)
        act_grid.setToolTip("Edit Grid System")
        act_grid.triggered.connect(self.open_grid_editor)
        self.toolbar.addAction(act_grid)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        act_zoom_in =  QAction(qta.icon('fa5s.search-plus', color='#6c757d'), "Zoom In", self)
        act_zoom_in.setToolTip("Zoom In")
        act_zoom_in.triggered.connect(self._toolbar_zoom_in)
        self.toolbar.addAction(act_zoom_in)

        act_zoom_out = QAction(qta.icon('fa5s.search-minus', color='#6c757d'), "Zoom Out", self)
        act_zoom_out.setToolTip("Zoom Out")
        act_zoom_out.triggered.connect(self._toolbar_zoom_out)
        self.toolbar.addAction(act_zoom_out)

        self.btn_pan = QAction(qta.icon('fa5s.hand-paper', color='#6c757d'), "Pan Tool", self)
        self.btn_pan.setToolTip("Pan View (Auto-reverts to mouse after dragging)")
        self.btn_pan.setCheckable(True)
        self.btn_pan.triggered.connect(self._toggle_pan)
        self.toolbar.addAction(self.btn_pan)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        btn_iso = QAction(create_plane_icon("ISO"), "ISO View", self)
        btn_iso.triggered.connect(self.set_view_iso) 
        self.toolbar.addAction(btn_iso)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        btn_3d = QAction(create_plane_icon("3D"), "3D View", self)
        btn_3d.triggered.connect(self.set_view_3d)
        self.toolbar.addAction(btn_3d)
        
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.btn_xy = QAction(create_plane_icon("XY"), "XY Plan", self)
        self.btn_xy.setCheckable(True)
        self.btn_xy.triggered.connect(lambda: self.set_view_2d("XY"))
        self.toolbar.addAction(self.btn_xy)

        self.btn_xz = QAction(create_plane_icon("XZ"), "XZ Elev", self)
        self.btn_xz.setCheckable(True)
        self.btn_xz.triggered.connect(lambda: self.set_view_2d("XZ"))
        self.toolbar.addAction(self.btn_xz)

        self.btn_yz = QAction(create_plane_icon("YZ"), "YZ Elev", self)
        self.btn_yz.setCheckable(True)
        self.btn_yz.triggered.connect(lambda: self.set_view_2d("YZ"))
        self.toolbar.addAction(self.btn_yz)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.btn_up = QAction(qta.icon('fa5s.chevron-up', color='#6c757d'), "UP", self)
        self.btn_up.triggered.connect(lambda: self.move_view_layer(1))
        self.toolbar.addAction(self.btn_up)
        
        self.btn_down = QAction(qta.icon('fa5s.chevron-down', color='#6c757d'), "Down", self)
        self.btn_down.triggered.connect(lambda: self.move_view_layer(-1))
        self.toolbar.addAction(self.btn_down)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.run_action = QAction(qta.icon('fa5s.play', color="#0078D7"), "Run Analysis...", self)
        self.run_action.setToolTip("Run Analysis Setup (F5)")
        self.run_action.setShortcut("F5") 
        self.run_action.triggered.connect(self.on_run_analysis_dialog)
        self.toolbar.addAction(self.run_action)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.btn_lock = QAction(qta.icon('fa5s.unlock', color='#6c757d'), "", self)
        self.btn_lock.setToolTip("Model is editable.")
        self.btn_lock.triggered.connect(self.on_lock_clicked)
        self.toolbar.addAction(self.btn_lock)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.btn_deform = QAction(qta.icon('fa5s.wave-square', color='#6c757d', disabled_color="#ffffff"), "Deformed Shape", self)
        self.btn_deform.setCheckable(True)                                 
        self.btn_deform.setToolTip("Toggle Deformed Shape ON/OFF (Results Mode Only)")
        self.btn_deform.triggered.connect(self._toolbar_toggle_deform)
        self.btn_deform.setEnabled(False)
        self.toolbar.addAction(self.btn_deform)

        self.btn_play_anim = QAction(qta.icon('fa5s.film', color='#6c757d', disabled_color='#cccccc'), "Play Animation", self)
        self.btn_play_anim.setToolTip("Play / Pause Animation (Results Mode Only)")
        self.btn_play_anim.triggered.connect(self._toolbar_toggle_animation)
        self.btn_play_anim.setEnabled(False)
        self.toolbar.addAction(self.btn_play_anim)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.btn_opts = QAction(qta.icon('fa5s.cog', color='#6c757d'), "Display", self)
        self.btn_opts.setShortcut("Ctrl+W")
        self.btn_opts.triggered.connect(self.on_view_options)
        self.toolbar.addAction(self.btn_opts)

        self.user_widget_action = None 

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.btn_cli = QAction(qta.icon('fa5s.terminal', color="#6c757d"), "Terminal", self)
        self.btn_cli.setToolTip("Toggle Terminal  (Ctrl+`)")
        self.btn_cli.setShortcut("Ctrl+`")
        self.btn_cli.triggered.connect(self._toggle_terminal)
        self.toolbar.addAction(self.btn_cli)

        self.btn_dual_view = QAction(qta.icon('fa5s.columns', color="#6c757d"), "Dual Viewport", self)
        self.btn_dual_view.setToolTip("Toggle Dual Viewport")
        self.btn_dual_view.setCheckable(True)
        self.btn_dual_view.setChecked(False)
        self.btn_dual_view.triggered.connect(self._toggle_dual_view)
        self.toolbar.addAction(self.btn_dual_view)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)

        from PyQt6.QtGui import QActionGroup                                                 
        
        self.sidebar = self.addToolBar("Draw Tools")
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.sidebar)
        self.sidebar.setMovable(False)
        self.sidebar.setIconSize(QSize(20, 20))
        
        self.sidebar.setStyleSheet(self.toolbar.styleSheet())

        self.draw_action_group = QActionGroup(self)
        self.draw_action_group.setExclusive(True)

        self.act_select = QAction(qta.icon('fa5s.mouse-pointer', color='#6c757d'), "Select Mode", self)
        self.act_select.setToolTip("Select Objects (Esc)")
        self.act_select.setCheckable(True)
        self.act_select.setChecked(True)                
        self.act_select.triggered.connect(self._on_sidebar_select_mode)
        self.draw_action_group.addAction(self.act_select)
        self.sidebar.addAction(self.act_select)

        self.sidebar.addSeparator()

        self.act_draw_frame = QAction(qta.icon('fa5s.pencil-alt', color='#6c757d'), "Draw Frame", self)
        self.act_draw_frame.setToolTip("Draw Frame/Cable")
        self.act_draw_frame.setCheckable(True)
        self.act_draw_frame.triggered.connect(self.on_draw_frame)
        self.draw_action_group.addAction(self.act_draw_frame)
        self.sidebar.addAction(self.act_draw_frame)

        self.act_quick_beam = QAction(qta.icon('fa5s.i-cursor', color='#6c757d'), "Quick Beam/Column", self)
        self.act_quick_beam.setToolTip("Quick Draw Beam/Column")
        self.act_quick_beam.setCheckable(True)
        self.act_quick_beam.triggered.connect(self.on_draw_beam_column)
        self.draw_action_group.addAction(self.act_quick_beam)
        self.sidebar.addAction(self.act_quick_beam)

        self.act_quick_brace = QAction(qta.icon('fa5s.times', color='#6c757d'), "Quick Cross Brace", self)
        self.act_quick_brace.setToolTip("Quick Draw Cross Brace")
        self.act_quick_brace.setCheckable(True)
        self.act_quick_brace.triggered.connect(self.on_draw_cross_brace)
        self.draw_action_group.addAction(self.act_quick_brace)
        self.sidebar.addAction(self.act_quick_brace)

        self.act_draw_link2 = QAction(qta.icon('fa5s.expand-alt', color='#6c757d'), "Draw 2-Joint Link", self)
        self.act_draw_link2.setToolTip("Draw 2-Joint Link")
        self.act_draw_link2.setCheckable(True)
        self.act_draw_link2.triggered.connect(self.on_draw_link2)
        self.draw_action_group.addAction(self.act_draw_link2)
        self.sidebar.addAction(self.act_draw_link2)

        self.act_draw_link1 = QAction(qta.icon('fa5s.thumbtack', color='#6c757d'), "Draw 1-Joint Link", self)
        self.act_draw_link1.setToolTip("Draw 1-Joint (Grounded) Link")
        self.act_draw_link1.setCheckable(True)
        self.act_draw_link1.triggered.connect(self.on_draw_link1)
        self.draw_action_group.addAction(self.act_draw_link1)
        self.sidebar.addAction(self.act_draw_link1)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.canvas = MCanvas3D()
        self.canvas2 = MCanvas3D()
        self.active_canvas = self.canvas

        self.canvas.display_config  = self.graphics_settings
        self.canvas2.display_config = self.graphics_settings

        self.canvas_frame1 = QFrame()
        self.canvas_frame1.setLayout(QVBoxLayout())
        self.canvas_frame1.layout().setContentsMargins(2,2,2,2)
        self.canvas_frame1.layout().addWidget(self.canvas)

        self.canvas_frame2 = QFrame()
        self.canvas_frame2.setLayout(QVBoxLayout())
        self.canvas_frame2.layout().setContentsMargins(2,2,2,2)
        self.canvas_frame2.layout().addWidget(self.canvas2)

        self.canvas_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas_splitter.addWidget(self.canvas_frame1)
        self.canvas_splitter.addWidget(self.canvas_frame2)
        self.canvas_splitter.setSizes([600, 600])
        self.canvas_splitter.setChildrenCollapsible(False)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.canvas_splitter)
        self.splitter.setChildrenCollapsible(False)
        self.layout.addWidget(self.splitter)

        self.canvas2_visible = False
        self.canvas_frame2.setVisible(False)
        self._update_active_border()

        from PyQt6.QtCore import QEvent
        self.canvas.installEventFilter(self)
        self.canvas2.installEventFilter(self)

        self._create_welcome_overlay()

        self.terminal_panel = TerminalPanel(
            model=None,
            on_model_modified=self.refresh_canvas,
            on_file_opened=self._on_cli_file_opened,          
            on_model_saved=self._on_cli_model_saved,
            on_solve_requested=self.start_analysis_sequence,
            on_unlock=self.on_lock_clicked,
            parent=self
        )
        self.splitter.addWidget(self.terminal_panel)
        self.splitter.setSizes([700, 0])   

        self.menu_assign = menubar.addMenu("Assign")

        self.menu_assign_area = self.menu_assign.addMenu("Area") 
        self.menu_assign_area.setIcon(qta.icon('fa5s.vector-square', color='#6c757d'))                                              
        
        self.menu_assign.addSeparator() 
        
        self.action_area_mesh = QAction(qta.icon('fa5s.th', color='#6c757d'), "Automatic Area Mesh...", self)
        self.action_area_mesh.triggered.connect(self.on_assign_area_mesh)
        self.menu_assign_area.addAction(self.action_area_mesh)
 
        self.menu_assign_area.addSeparator()

        
        self.action_area_uniform_load = QAction(
            qta.icon('fa5s.arrows-alt-v', color='#6c757d'), "Uniform Load...", self)
        self.action_area_uniform_load.triggered.connect(self.on_assign_area_uniform_load)
        self.menu_assign_area.addAction(self.action_area_uniform_load)
 
        self.action_area_gravity_load = QAction(
            qta.icon('fa5s.weight', color='#6c757d'), "Gravity Load...", self)
        self.action_area_gravity_load.triggered.connect(self.on_assign_area_gravity_load)
        self.menu_assign_area.addAction(self.action_area_gravity_load)
        
        self.menu_select = menubar.addMenu("Select")

        all_action = QAction(qta.icon('fa5s.border-all', color='#6c757d'), "All", self)
        all_action.setShortcut("Ctrl+A")
        all_action.triggered.connect(self.on_select_all)
        self.menu_select.addAction(all_action)

        invert_action = QAction(qta.icon('fa5s.adjust', color='#6c757d'), "Invert", self)
        invert_action.setShortcut("Ctrl+I")
        invert_action.triggered.connect(self.on_invert_selection)
        self.menu_select.addAction(invert_action)

        none_action = QAction(qta.icon('fa5s.times-circle', color='#6c757d'), "None", self)
        none_action.setShortcut("Escape")
        none_action.triggered.connect(self.on_select_none)
        self.menu_select.addAction(none_action)

        self.menu_select.addSeparator()

        props_menu = self.menu_select.addMenu("Select by Properties")
        props_menu.setIcon(qta.icon('fa5s.filter', color='#6c757d'))

        sec_select_action = QAction(qta.icon('fa5s.shapes', color='#6c757d'),
                                    "Frame Sections...", self)
        sec_select_action.triggered.connect(self.on_select_by_section)
        props_menu.addAction(sec_select_action)

        area_sec_select_action = QAction(qta.icon('fa5s.vector-square', color='#6c757d'),
                                         "Area Sections...", self)
        area_sec_select_action.triggered.connect(self.on_select_by_area_section)
        props_menu.addAction(area_sec_select_action)

        story_select_action = QAction(qta.icon('fa5s.layer-group', color='#6c757d'),
                                      "Stories...", self)
        story_select_action.triggered.connect(self.on_select_by_story)
        props_menu.addAction(story_select_action)

        self.deselect_menu = self.menu_select.addMenu("Deselect by Properties")
        self.deselect_menu.setIcon(qta.icon('fa5s.minus-square', color='#6c757d'))

        sec_deselect_action = QAction(qta.icon('fa5s.shapes', color='#6c757d'),
                                      "Frame Sections...", self)
        sec_deselect_action.triggered.connect(self.on_deselect_by_section)
        self.deselect_menu.addAction(sec_deselect_action)
        
        area_sec_deselect_action = QAction(qta.icon('fa5s.vector-square', color='#6c757d'),
                                           "Area Sections...", self)
        area_sec_deselect_action.triggered.connect(self.on_deselect_by_area_section)
        self.deselect_menu.addAction(area_sec_deselect_action)

        self.menu_select.aboutToShow.connect(self._update_select_menu_state)
        
        joint_menu = self.menu_assign.addMenu("Joint")
        joint_menu.setIcon(qta.icon('fa5s.dot-circle', color='#6c757d'))
        
        restraint_action = QAction(qta.icon('fa5s.anchor', color='#6c757d'), "Restraints...", self)
        restraint_action.triggered.connect(self.on_assign_restraints)
        joint_menu.addAction(restraint_action)

        constraint_action = QAction(qta.icon('fa5s.link', color='#6c757d'), "Diaphragms / Constraints...", self)
        constraint_action.triggered.connect(self.on_assign_constraints)
        joint_menu.addAction(constraint_action)

        joint_menu.addSeparator()

        spring_action = QAction(qta.icon('fa5s.compress-arrows-alt', color='#6c757d'), "Joint Springs...", self)
        spring_action.triggered.connect(self.on_assign_joint_springs)
        joint_menu.addAction(spring_action)

        joint_menu.addSeparator()

        load_action = QAction(qta.icon('fa5s.arrow-down', color='#6c757d'), "Point Loads...", self)
        load_action.triggered.connect(self.on_assign_joint_load)
        joint_menu.addAction(load_action)

        disp_action = QAction(qta.icon('fa5s.arrows-alt', color='#6c757d'), "Joint Displacements...", self)
        disp_action.triggered.connect(self.on_assign_joint_displacement)
        joint_menu.addAction(disp_action)

        self.menu_assign.addSeparator()

        frame_menu = self.menu_assign.addMenu("Frame")
        frame_menu.setIcon(qta.icon('fa5s.minus', color='#6c757d'))

        frame_point_action = QAction(qta.icon('fa5s.compress-arrows-alt', color='#6c757d'), "Point Loads...", self)
        frame_point_action.triggered.connect(self.on_assign_frame_point_load)
        frame_menu.addAction(frame_point_action)

        frame_load_action = QAction(qta.icon('fa5s.stream', color='#6c757d'), "Distributed Loads...", self)
        frame_load_action.triggered.connect(self.on_assign_frame_load)
        frame_menu.addAction(frame_load_action)

        frame_menu.addSeparator()

        frame_rel_action = QAction(qta.icon('fa5s.unlink', color='#6c757d'), "Releases & Partial Fixity...", self)
        frame_rel_action.triggered.connect(self.on_assign_releases)
        frame_menu.addAction(frame_rel_action)

        ins_point_action = QAction(qta.icon('fa5s.crosshairs', color='#6c757d'), "Insertion Point...", self)
        ins_point_action.triggered.connect(self.on_assign_insertion_point)
        frame_menu.addAction(ins_point_action)

        end_offset_action = QAction(qta.icon('fa5s.arrows-alt-h', color='#6c757d'), "End Length Offsets...", self)
        end_offset_action.triggered.connect(self.on_assign_end_offsets)
        frame_menu.addAction(end_offset_action)

        frame_menu.addSeparator()

        local_axis_action = QAction(qta.icon('fa5s.location-arrow', color='#6c757d'), "Local Axes...", self)
        local_axis_action.triggered.connect(self.on_assign_local_axis)
        frame_menu.addAction(local_axis_action)

        self.menu_analyze = menubar.addMenu("Analyze")

        self.menu_analyze.addAction(self.run_action)
        self.menu_analyze.addSeparator()

        self.solid_run_action = QAction(qta.icon('fa5s.cube', color='#6c757d'), "Run Solid Analysis...", self)
        self.solid_run_action.triggered.connect(self.on_run_solid_analysis)
        self.menu_analyze.addAction(self.solid_run_action)

        self.menu_analyze.addSeparator()

        self.menu_analyze.addAction(self.btn_deform)

        self.action_deform_opts = QAction("Deformed Shape Options...", self)
        self.action_deform_opts.triggered.connect(self.on_view_deformed_shape)
        self.action_deform_opts.setEnabled(False)
        self.menu_analyze.addAction(self.action_deform_opts)

        self.menu_analyze.addSeparator()

        self.action_display_forces = QAction(
            qta.icon('fa5s.chart-bar', color='#6c757d'),
            "Display Frame Forces...",
            self
        )
        self.action_display_forces.setEnabled(False)                               
        self.action_display_forces.triggered.connect(self.on_display_frame_forces)
        self.menu_analyze.addAction(self.action_display_forces)

        self.menu_analyze.addSeparator()

        self.action_display_reactions = QAction(
            qta.icon('fa5s.anchor', color='#6c757d'),
            "Display Joint Reactions...",
            self
        )
        self.action_display_reactions.setEnabled(False)
        if hasattr(self, 'sound_effect') and self.sound_effect.isPlaying():
            self.sound_effect.stop()
        self.action_display_reactions.triggered.connect(self.on_display_joint_reactions)
        self.menu_analyze.addAction(self.action_display_reactions)

        self.menu_analyze.addSeparator()
        self.res_action = QAction(qta.icon('fa5s.table', color='#6c757d'), "Show Result Tables...", self)
        self.res_action.setShortcut("Ctrl+T")
        self.res_action.triggered.connect(self.on_show_modal_results)
        self.menu_analyze.addAction(self.res_action)

        self.menu_options = menubar.addMenu("Options")
        
        gfx_action = QAction(qta.icon('fa5s.desktop', color='#6c757d'), "Graphics Preferences...", self)
        gfx_action.triggered.connect(self.on_graphics_options)
        self.menu_options.addAction(gfx_action)

        self.menu_help = menubar.addMenu("Help")
        
        update_action = QAction(qta.icon('fa5s.cloud-download-alt', color='#6c757d'), "Check for Updates...", self)
        update_action.triggered.connect(self.on_check_updates)
        self.menu_help.addAction(update_action)

        self.canvas.signal_canvas_clicked.connect(self.handle_canvas_click) 
        self.canvas.signal_right_clicked.connect(self.handle_right_click) 
        self.canvas.signal_box_selection.connect(self.handle_box_selection)
        self.canvas.signal_area_box_selection.connect(self.handle_area_box_selection)
        self.canvas.signal_mouse_moved.connect(self.on_mouse_moved)

        self.canvas2.signal_canvas_clicked.connect(
            lambda x, y, z: self.handle_canvas_click(x, y, z) if self.active_canvas is self.canvas2 else None
        )
        self.canvas2.signal_right_clicked.connect(
            lambda: self.handle_right_click() if self.active_canvas is self.canvas2 else None
        )
        self.canvas2.signal_box_selection.connect(self._handle_box_selection_canvas2)
        self.canvas2.signal_area_box_selection.connect(
            lambda ids, add, de: self.handle_area_box_selection(ids, add, de) if self.active_canvas is self.canvas2 else None
        )
        self.canvas2.signal_mouse_moved.connect(self.on_mouse_moved)
        
        self.setup_statusbar()

    def on_select_by_story(self):
        if not self.model:
            return
        if not hasattr(self, '_sel_by_story_dlg') or not self._sel_by_story_dlg.isVisible():
            from app.dialogs.select_by_story_dialog import SelectByStoryDialog
            self._sel_by_story_dlg = SelectByStoryDialog(self)
            self._sel_by_story_dlg.show()
        else:
            self._sel_by_story_dlg.raise_()

    def _on_app_state_changed(self, state):
        if state == Qt.ApplicationState.ApplicationInactive:
                                                                           
            self._hidden_dialogs = []
            for widget in QApplication.topLevelWidgets():
                if (isinstance(widget, QDialog) 
                        and widget.isVisible() 
                        and not widget.isModal()):
                    widget.hide()
                    self._hidden_dialogs.append(widget)

        elif state == Qt.ApplicationState.ApplicationActive:
                                               
            for dlg in getattr(self, '_hidden_dialogs', []):
                if dlg is not None and not dlg.isModal():
                    dlg.show()
            self._hidden_dialogs = []

    def on_select_all(self):
        if not self.model: return
        self.selected_ids = list(self.model.elements.keys())
        self.selected_node_ids = list(self.model.nodes.keys())
        self.selected_area_ids = list(self.model.area_elements.keys()) if hasattr(self.model, 'area_elements') else []
        self.selected_link_ids = list(self.model.links.keys()) if hasattr(self.model, 'links') else []          
        
        self._refresh_selection_overlay()
        self.status.showMessage(
            f"Selected All: {len(self.selected_ids)} Frames, "
            f"{len(self.selected_node_ids)} Joints, "
            f"{len(self.selected_area_ids)} Areas, "
            f"{len(self.selected_link_ids)} Links")

    def on_select_none(self):
        if not self.model:
            return
        self.selected_ids = []
        self.selected_node_ids = []
        self.selected_area_ids = []
        self.selected_link_ids = []
        
        if hasattr(self, 'canvas'):                                                                                                 
            self.canvas.clear_hover_popup()
                                                     
        self._refresh_selection_overlay()
        self.status.showMessage("Selection Cleared")

    def on_invert_selection(self):
        if not self.model:
            return
        all_eids = set(self.model.elements.keys())
        all_nids = set(self.model.nodes.keys())
        self.selected_ids = list(all_eids - set(self.selected_ids))
        self.selected_node_ids = list(all_nids - set(self.selected_node_ids))
        
        if hasattr(self.model, 'area_elements'):
            all_aids = set(self.model.area_elements.keys())
            self.selected_area_ids = list(all_aids - set(self.selected_area_ids))
            
        self._refresh_selection_overlay()
        self.status.showMessage(
            f"Inverted: {len(self.selected_ids)} Frames, "
            f"{len(self.selected_node_ids)} Joints, "
            f"{len(self.selected_area_ids)} Areas")

    def _refresh_selection_overlay(self):
        for cvs in [self.canvas, self.canvas2]:
            cvs.update_selection_overlay(self.selected_ids, self.selected_node_ids, self.selected_area_ids, getattr(self, 'selected_link_ids', []))

    def _toolbar_zoom_in(self):
        """Zoom in button — simulates a scroll-up at canvas centre."""
        w, h = self.active_canvas.width(), self.active_canvas.height()
        self.active_canvas.camera.zoom(120, w / 2, h / 2, w, h)

    def _toolbar_zoom_out(self):
        """Zoom out button — simulates a scroll-down at canvas centre."""
        w, h = self.active_canvas.width(), self.active_canvas.height()
        self.active_canvas.camera.zoom(-120, w / 2, h / 2, w, h)

    def _toolbar_toggle_animation(self):
        """▶ Animate button — opens the deformed shape dialog if needed,
        then toggles play/pause directly."""
        if not self.model or not self.model.has_results:
            QMessageBox.warning(self, "No Results", "Please run the analysis first.")
            return
                                                                  
        self.on_view_deformed_shape()
                                                       
        dlg = getattr(self, '_deformed_dlg', None)
        if dlg and dlg.isVisible():
            checked = not dlg.btn_animate.isChecked()
            dlg.btn_animate.setChecked(checked)
            dlg.on_toggle_anim()

    def on_mouse_moved(self, x, y, z):
        self.lbl_coords.setText(f"X: {x:.2f}  Y: {y:.2f}  Z: {z:.2f}")
        if getattr(self, 'draw_area_mode_active', False) and len(self._current_area_nodes) > 0:
            self.active_canvas.update_area_preview(list(self._current_area_nodes), x, y, z)

    def setup_statusbar(self):
        
        self.status = self.statusBar()
        self.status.showMessage("Welcome. Please create or open a model.")
        
        self.lbl_coords = QLabel("X: 0.00  Y: 0.00  Z: 0.00")
        self.lbl_coords.setStyleSheet("padding-right: 15px; color: #333;")
        self.status.addPermanentWidget(self.lbl_coords)

        self.combo_units = QComboBox()
        self.combo_units.addItems([
            "kN, m, C", 
            "N, m, C", 
            "N, mm, C", 
            "kN, mm, C",
            "Tonf, m, C",
            "kgf, m, C",
            "kip, ft, F"
        ])
                          
        self.combo_units.setCurrentIndex(0)
        self.combo_units.setToolTip("Global Display Units")
        
        self.combo_units.currentIndexChanged.connect(self.on_units_changed)
        
        self.status.addPermanentWidget(self.combo_units)

    def _create_welcome_overlay(self):
        from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget, QLabel, QFrame
        from PyQt6.QtCore import Qt

        TAG_STYLES = {
            "new": (
                "color: #005A9E; font-family: Consolas, monospace; font-weight: bold;",
                "[+] NEW "
            ),
            "fix": (
                "color: #6F7681; font-family: Consolas, monospace; font-weight: bold;",
                "[~] FIX "
            ),
            "impr": (
                "color: #6F7681; font-family: Consolas, monospace; font-weight: bold;",
                "[•] IMPR"
            ),
        }

        self.welcome_overlay = QWidget(self.canvas_splitter)
        self.welcome_overlay.setObjectName("welcome_overlay_root")
        
        self.welcome_overlay.setStyleSheet("""
            #welcome_overlay_root {
                background-color: #FFFFFF;
                border: 1px solid #D1D1D1;
                border-radius: 4px;
            }
        """)

        root_layout = QVBoxLayout(self.welcome_overlay)
        root_layout.setContentsMargins(32, 32, 32, 24)
        root_layout.setSpacing(0)

        branding = QLabel()
        branding.setAlignment(Qt.AlignmentFlag.AlignLeft)
        branding.setTextFormat(Qt.TextFormat.RichText)
        branding.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        branding.setText(
            "<div style='font-family: \"Segoe UI\", sans-serif;'>"
            "<div style='font-size: 26px; font-weight: 300; color: #111111; letter-spacing: 1px;'>"
            "Open<span style='font-weight: 700; color: #005A9E;'>//Structures</span></div>"
            "<div style='font-size: 11px; color: #666666; margin-top: 4px; font-weight: 600; letter-spacing: 1px;'>"
            "STRUCTURAL ANALYSIS &amp; DESIGN PLATFORM</div>"
            "<div style='margin-top: 24px; font-size: 13px; color: #333333;'>Status: Ready. No model loaded.</div>"
            "<div style='margin-top: 12px; font-size: 12px; color: #333333;'>"
            "<span style='color: #005A9E; font-family: Consolas, monospace; font-weight: 600;'>Ctrl+N</span> New Model "
            "&nbsp;&nbsp;&nbsp;&nbsp; "
            "<span style='color: #005A9E; font-family: Consolas, monospace; font-weight: 600;'>Ctrl+O</span> Open File"
            "</div></div>"
        )
        root_layout.addWidget(branding)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #DDE1E6; max-height: 1px; margin-top: 20px; margin-bottom: 16px;")
        root_layout.addWidget(sep)

        whats_new_lbl = QLabel("SYSTEM LOG // RELEASE NOTES")
        whats_new_lbl.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 10px; font-weight: 700; color: #767676; letter-spacing: 1.5px; margin-bottom: 8px;"
        )
        root_layout.addWidget(whats_new_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QWidget#notes_container { background: transparent; }
            QScrollBar:vertical {
                background: #F3F3F3; width: 10px; margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #CDCDCD; min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #A6A6A6;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        notes_container = QWidget()
        notes_container.setObjectName("notes_container")
        notes_layout = QVBoxLayout(notes_container)
        notes_layout.setContentsMargins(0, 0, 16, 0)
        notes_layout.setSpacing(0)

        if NOTICES:
            notice_box = QWidget()
            notice_box.setObjectName("notice_box")                       
            
            notice_box.setStyleSheet("""
                #notice_box {
                background-color: #F7F8FA;
                border-left: 3px solid #005A9E;
                border-radius: 3px;
            }
            """)
            
            notice_layout = QVBoxLayout(notice_box)
            notice_layout.setContentsMargins(12, 12, 12, 12)
            notice_layout.setSpacing(6)

            for title, detail in NOTICES:
                title_lbl = QLabel(
                    f"<span style='font-family: \"Segoe UI\"; font-size: 12px; font-weight: 700; color: #005A9E;'>"
                    f"NOTICE: {title}</span>"
                )
                title_lbl.setTextFormat(Qt.TextFormat.RichText)
                notice_layout.addWidget(title_lbl)

                detail_lbl = QLabel(
                    f"<span style='font-family: \"Segoe UI\"; font-size: 12px; color: #333333;'>{detail}</span>"
                )
                detail_lbl.setTextFormat(Qt.TextFormat.RichText)
                detail_lbl.setWordWrap(True)
                notice_layout.addWidget(detail_lbl)

            notes_layout.addWidget(notice_box)
            notes_layout.addSpacing(16)

        for i, release in enumerate(RELEASE_NOTES):
            ver_lbl = QLabel(
                f"<span style='font-family: Consolas, monospace; font-weight: 700; font-size: 13px; color: #005A9E;'>"
                f"v{release['version']}</span>"
                f"&nbsp;&nbsp;<span style='font-family: Consolas, monospace; font-size: 11px; color: #767676;'>"
                f"{release['date']}</span>"
            )
            ver_lbl.setTextFormat(Qt.TextFormat.RichText)
            ver_lbl.setContentsMargins(0, 8 if i > 0 else 0, 0, 6)
            notes_layout.addWidget(ver_lbl)

            for tag, text in release["items"]:
                tag_style, tag_text = TAG_STYLES.get(tag, TAG_STYLES["impr"])
                item_lbl = QLabel(
                    f"<span style='font-size: 12px;'>"
                    f"<span style='{tag_style}'>{tag_text}</span>"
                    f"&nbsp;&nbsp;<span style='font-family: \"Segoe UI\"; color: #111111;'>{text}</span></span>"
                )
                item_lbl.setTextFormat(Qt.TextFormat.RichText)
                item_lbl.setWordWrap(True)
                item_lbl.setContentsMargins(0, 2, 0, 2)
                notes_layout.addWidget(item_lbl)

            if i < len(RELEASE_NOTES) - 1:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.HLine)
                div.setStyleSheet("background-color: #DDE1E6; max-height: 1px; margin-top: 12px; margin-bottom: 8px;")
                notes_layout.addWidget(div)

        notes_layout.addStretch()
        scroll.setWidget(notes_container)
        root_layout.addWidget(scroll, 1)

        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        _opacity_effect = QGraphicsOpacityEffect(self.welcome_overlay)
        _opacity_effect.setOpacity(1.0)
        self.welcome_overlay.setGraphicsEffect(_opacity_effect)
        self._welcome_opacity = _opacity_effect

        self.welcome_overlay.raise_()
        self.welcome_overlay.show()
        self._reposition_welcome_overlay()

    def _reposition_welcome_overlay(self):

        if not hasattr(self, 'welcome_overlay'):
            return
        
        if hasattr(self, '_welcome_anim') and self._welcome_anim.state() == QPropertyAnimation.State.Running:
            return

        frame = self.canvas_frame1
        fw = frame.width()
        fh = frame.height()
        fx = frame.pos().x()
        fy = frame.pos().y()
        w = min(420, fw - 40)
        h = min(420, fh - 60)   
        x = fx + (fw - w) // 2
        y = fy + (fh - h) // 2
        self.welcome_overlay.setGeometry(x, y, w, h)

    def _show_welcome_overlay_animated(self):
        from PyQt6.QtCore import QRect, QParallelAnimationGroup
        overlay = self.welcome_overlay
        self._reposition_welcome_overlay()
        center_geo = overlay.geometry()
        start_geo = QRect(
            center_geo.x() + 60,
            center_geo.y(),
            center_geo.width(),
            center_geo.height()
        )
        overlay.setGeometry(start_geo)
        self._welcome_opacity.setOpacity(0.0)
        overlay.show()

        geo_anim = QPropertyAnimation(overlay, b"geometry")
        geo_anim.setDuration(400)
        geo_anim.setStartValue(start_geo)
        geo_anim.setEndValue(center_geo)
        geo_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        fade_anim = QPropertyAnimation(self._welcome_opacity, b"opacity")
        fade_anim.setDuration(400)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._welcome_anim = QParallelAnimationGroup()
        self._welcome_anim.addAnimation(geo_anim)
        self._welcome_anim.addAnimation(fade_anim)
        self._welcome_anim.finished.connect(self._reposition_welcome_overlay)
        self._welcome_anim.start()

    def _hide_welcome_overlay_animated(self):
        from PyQt6.QtCore import QRect, QParallelAnimationGroup
        overlay = self.welcome_overlay
        start_geo = overlay.geometry()
        end_geo = QRect(
            start_geo.x() + 60,
            start_geo.y(),
            start_geo.width(),
            start_geo.height()
        )

        geo_anim = QPropertyAnimation(overlay, b"geometry")
        geo_anim.setDuration(300)
        geo_anim.setStartValue(start_geo)
        geo_anim.setEndValue(end_geo)
        geo_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        fade_anim = QPropertyAnimation(self._welcome_opacity, b"opacity")
        fade_anim.setDuration(300)
        fade_anim.setStartValue(1.0)
        fade_anim.setEndValue(0.0)
        fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        self._welcome_anim = QParallelAnimationGroup()
        self._welcome_anim.addAnimation(geo_anim)
        self._welcome_anim.addAnimation(fade_anim)
        self._welcome_anim.finished.connect(lambda: overlay.setVisible(False))
        self._welcome_anim.start()

    def set_interface_state(self, editable: bool):
        """
        editable = True:  PRE-PROCESSING (Draw, Assign, Edit enabled).
        editable = False: POST-PROCESSING (Locked. Only View & Info enabled).
        """
                                                               
        if hasattr(self, 'welcome_overlay'):
            if self.model is None:
                self.welcome_overlay.setVisible(True)
                self._reposition_welcome_overlay()
            elif self.welcome_overlay.isVisible():
                self._hide_welcome_overlay_animated()

        self.menu_define.setEnabled(editable)
        self.menu_draw.setEnabled(editable)
        self.menu_assign.setEnabled(editable)
        self.run_action.setEnabled(editable)
        self.solid_run_action.setEnabled(editable)
        self.res_action.setEnabled(not editable)
        self.menu_analyze.setEnabled(editable or self.model is not None)

        if hasattr(self, 'btn_deform'):
            self.btn_deform.setEnabled(not editable)
        if hasattr(self, 'btn_play_anim'):
            self.btn_play_anim.setEnabled(not editable)

        if hasattr(self, 'action_deform_opts'):
            self.action_deform_opts.setEnabled(not editable)

        if hasattr(self, 'menu_edit'):
            self.menu_edit.setEnabled(editable)

        if hasattr(self, 'menu_select'):        
            self.menu_select.setEnabled(editable)
        
        if not editable:
                                   
            self.canvas.setBackgroundColor('#F8F9FA')                  
            if self.model is None:
                self.status.showMessage("Ready. Create a new model or open an existing file to begin.")
            else:
                self.status.showMessage("Model Locked. Results Mode.")
        else:
                       
            bg_tuple = self.graphics_settings.get("background_color", (1.0, 1.0, 1.0, 1.0))
            c = QColor()
            c.setRgbF(bg_tuple[0], bg_tuple[1], bg_tuple[2], bg_tuple[3])
            self.canvas.setBackgroundColor(c)
            self.status.showMessage("Model Unlocked. Ready to edit.")

    def on_units_changed(self, index):
        unit_text = self.combo_units.currentText()
        
        unit_registry.set_unit_system(unit_text)
        
        self.status.showMessage(f"Units changed to: {unit_text}")
        
        if self.model:
                                                                              
            self.canvas._force_draw_model(self.model)
            if getattr(self, 'canvas2_visible', False):
                self.canvas2._force_draw_model(self.model)

            last = getattr(self, '_last_force_diagram_settings', {})
            for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
                if cvs and last.get(cvs) and getattr(cvs, 'force_diagram_active', False):
                    prev = self.active_canvas
                    self.active_canvas = cvs
                    self.apply_force_diagrams_from_dialog(last[cvs])
                    self.active_canvas = prev
                    
    def set_view_3d(self):
        self._reset_plane_buttons()
        self.active_canvas._view_mode = "3D"
        self.active_canvas.active_view_plane = None
        if self.model: self.draw_both_canvases()
        self.active_canvas.set_standard_view("3D")
        self.status.showMessage("View: Full 3D")
        if self.cross_brace_dialog:
            self.cross_brace_dialog.update_plane_status(None)

        self.update_linked_planes()

    def _reset_plane_buttons(self):
        for btn in [self.btn_xy, self.btn_xz, self.btn_yz]:
            btn.setChecked(False)
        self.active_canvas._plane_state = 0

    def set_view_2d(self, axis):
        cvs = self.active_canvas
        is_same_axis = (cvs._view_mode == axis)

        if not is_same_axis:
                                                                              
            self._reset_plane_buttons()
            cvs._view_mode = axis
            cvs._grid_index = 0
            cvs.show_ghost_structure = True
            cvs._plane_state = 1
            getattr(self, f'btn_{axis.lower()}').setChecked(True)
            self.update_view_layer()
            self.status.showMessage(f"View: {axis} — Plane (Ghost ON)")
    
        elif cvs._plane_state == 1:
                                                                              
            cvs.show_ghost_structure = False
            cvs._plane_state = 2
            self.refresh_canvas()
            self.status.showMessage(f"View: {axis} — Strict Plane Only")

        elif cvs._plane_state == 2:
                                                                               
            cvs._plane_state = 3
            cvs.show_ghost_structure = False                          
            cvs.set_standard_view(axis)
            self.refresh_canvas()
            self.status.showMessage(f"View: {axis} — Ortho 2D")

        else:
                                                                               
            cvs.show_ghost_structure = True
            cvs._plane_state = 1
            cvs._grid_index = 0
            self.update_view_layer()
            self.status.showMessage(f"View: {axis} — Plane (Ghost ON)")
        
        self._restore_force_diagram_if_active()
        self.update_linked_planes()

        self.update_linked_planes()
        
    def _restore_force_diagram_if_active(self):
        last = getattr(self, '_last_force_diagram_settings', {})
        cvs = self.active_canvas
        settings = last.get(cvs)
        
        if settings and (getattr(cvs, 'force_diagram_active', False) or cvs._pending_force_upload is not None):
            self.apply_force_diagrams_from_dialog(settings)

    def move_view_layer(self, direction):
        if self.active_canvas._view_mode in ["3D", "ISO"]: return
        
        self.active_canvas._grid_index += direction
        self.update_view_layer()
        self.update_linked_planes()

    def update_view_layer(self):
        cvs = self.active_canvas
        grids = self.model.grid
        if cvs._view_mode == "XY":
            grid_list = grids.z_grids; axis = 'z'
        elif cvs._view_mode == "XZ":
            grid_list = grids.y_grids; axis = 'y'
        elif cvs._view_mode == "YZ":
            grid_list = grids.x_grids; axis = 'x'
        else: return

        if not grid_list: return 

        cvs._grid_index = max(0, min(cvs._grid_index, len(grid_list) - 1))
        val = grid_list[cvs._grid_index]
        cvs.active_view_plane = {'axis': axis, 'value': val}
        if self.model: self.draw_both_canvases()
        self.status.showMessage(f"Filtered View: {cvs._view_mode} @ {axis.upper()}={val:.2f}m")
        if self.cross_brace_dialog:
            self.cross_brace_dialog.update_plane_status(cvs.active_view_plane)
        self._restore_force_diagram_if_active()

    def set_view_iso(self):
        self._reset_plane_buttons()
        self.active_canvas._view_mode = "3D"
        self.active_canvas.active_view_plane = None
        if self.model: self.draw_both_canvases()
        self.active_canvas.set_standard_view("ISO")
        self.status.showMessage("View: Orthogonal Isometric")
        if self.cross_brace_dialog:
            self.cross_brace_dialog.update_plane_status(None)

        self.update_linked_planes()

    def _purge_results_and_visuals(self):
        """Silently purges all post-processing visuals, locks, and GPU buffers for a fresh file."""
        self.is_locked = False
        self.btn_deform.setEnabled(False)
        self.btn_deform.setChecked(False)
        self.action_display_forces.setEnabled(False)
        self.action_display_reactions.setEnabled(False)
        
        self.btn_lock.setIcon(qta.icon('fa5s.unlock', color='#6c757d'))
        self.btn_lock.setToolTip("Model is editable.")
        
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs is not None:
                if hasattr(cvs, 'clear_force_diagrams'):
                    cvs.clear_force_diagrams()
                if hasattr(self.active_canvas, 'clear_reaction_diagram'):
                    self.active_canvas.clear_reaction_diagram()
                cvs.view_deflected = False
                cvs.anim_factor = 0.0
                cvs.invalidate_animation_cache()
                if hasattr(cvs, 'animation_manager') and cvs.animation_manager:
                    cvs.animation_manager.stop_animation()
                if hasattr(cvs, 'clear_ltha_history'):
                    cvs.clear_ltha_history()

    def on_new_model(self):
        from app.dialogs.new_model_dialog import NewModelDialog
        dialog = NewModelDialog(self)
        if dialog.exec(): 
            if dialog.accepted_data:
                self._purge_results_and_visuals()                
                data = dialog.grid_data
                self.model = StructuralModel("New Project")
                self.terminal_panel.set_model(self.model)
                self.undo_stack.clear()

                try:
                    from core.properties import Material, RectangularSection, ISection
                    
                    mat_conc = Material("C30", 3.2e10, 0.2, 24000.0, "Concrete", 0.0, 0.0)
                    self.model.add_material(mat_conc)

                    mat_steel = Material("S275", 2.0e11, 0.3, 78500.0, "Steel", 275e6, 430e6)
                    self.model.add_material(mat_steel)

                    default_color = (0.259, 0.110, 0.749, 1.0)

                    sec_beam = RectangularSection("B30x50", mat_conc, 0.3, 0.5)
                    sec_beam.color = default_color                       
                    self.model.add_section(sec_beam)
                    
                    sec_col = ISection("IPE300", mat_steel, 0.300, 0.150, 0.0107, 0.150, 0.0107, 0.0071)
                    sec_col.color = default_color                       
                    self.model.add_section(sec_col)
                    
                    print("> GUI: Default materials and sections loaded successfully.")
                except Exception as e:
                    print(f"> GUI Error: {e}")

                if not hasattr(self.model, 'mass_sources'):
                    self.model.mass_sources = {}
                    from core.model import MassSource
                    def_ms = MassSource("MSSSRC1")
                    self.model.mass_sources["MSSSRC1"] = def_ms
                    self.model.active_mass_source = "MSSSRC1"
                    
                self.model.file_path = None
                self.model.grid.create_uniform('x', 0.0, data['x_num'] - 1, data['x_dist'])
                self.model.grid.create_uniform('y', 0.0, data['y_num'] - 1, data['y_dist'])
                self.model.grid.create_uniform('z', 0.0, data['z_num'] - 1, data['z_dist'])   
                self.combo_units.blockSignals(True)
                self.combo_units.setCurrentText(dialog.selected_units)
                self.combo_units.blockSignals(False)

                self.on_units_changed(0) 

                self.model.functions = {
                    "FUNC1": {
                        "name": "FUNC1", "type": "TSC-2018", 
                        "Ss": 1.5, "S1": 0.4, "SiteClass": "ZC", 
                        "R": 8.0, "D": 3.0, "I": 1.0, "TL": 6.0
                    }
                }
                
                rsa_case = LoadCase("RSA_X", "Response Spectrum")
                rsa_case.function = "FUNC1"
                rsa_case.direction = "X"
                self.model.load_cases["RSA_X"] = rsa_case

                self.set_interface_state(True)
                
                self.set_view_3d() 
                
                self.status.showMessage(f"New Model Created. Units: {dialog.selected_units}")
                self.update_window_title()

    def on_save_model(self):
        if not self.model:
            return False
    
        current_path = getattr(self.model, 'file_path', None)
    
        if current_path:
            filename = current_path
        else:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save Model", "",
                "Open//Structures Files (*.mf);;All Files (*)"
            )
    
        if not filename:
            return False
    
        if not filename.endswith(".mf"):
            filename += ".mf"
    
        dlg = ModelIODialog("Saving the Project...", filename, parent=self)
        dlg.show()
        QApplication.processEvents()
    
        try:
            dlg.stage("Collecting viewport settings...")
            self.graphics_settings['view_extruded']        = self.canvas.view_extruded
            self.graphics_settings['show_slabs']           = self.canvas.show_slabs
            self.graphics_settings['show_joints']          = self.canvas.show_joints
            self.graphics_settings['show_supports']        = self.canvas.show_supports
            self.graphics_settings['show_loads']           = self.canvas.show_loads
            self.graphics_settings['show_local_axes']      = self.canvas.show_local_axes
            self.graphics_settings['show_constraints']     = self.canvas.show_constraints
            self.graphics_settings['show_releases']        = self.canvas.show_releases
            self.graphics_settings['load_type_filter']     = self.canvas.load_type_filter
            self.graphics_settings['visible_load_patterns']= self.canvas.visible_load_patterns
            QApplication.processEvents()
    
            dlg.stage("Preparing model data...")
            model_graphics = self.graphics_settings.copy()
            model_graphics.pop("msaa_level", None)
            self.model.graphics_settings = model_graphics
            QApplication.processEvents()
    
            def _report(msg):
                dlg.stage(msg)
                QApplication.processEvents()

            self.model.save_to_file(filename, progress=_report)
                                     
            dlg.stage("Finalizing...")
            self.model.file_path        = filename
            self.model.active_model_path = filename
            self.undo_stack.setClean()
            self.status.showMessage(f"Saved: {filename}")
            self.update_window_title()
            QApplication.processEvents()
    
            dlg.finish(success=True)
            return True
    
        except Exception as e:
            dlg.keep_open()                                                                 
            dlg.stage(f"Error: {str(e)[:80]}")
            dlg.finish(success=False)
            QMessageBox.critical(self, "Save Error", str(e))
            return False

    def on_open_model(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open Model", "",
            "Open//Structures Files (*.mf);;All Files (*)"
        )
        if not filename:
            return
    
        dlg = ModelIODialog("Opening the Project...", filename, parent=self)
        dlg.show()
        QApplication.processEvents()

        if hasattr(self, 'canvas'): self.canvas.setUpdatesEnabled(False)
        if hasattr(self, 'canvas_2d'): self.canvas_2d.setUpdatesEnabled(False)
    
        try:
            dlg.stage("Clearing current session...")
            self._purge_results_and_visuals()
            dlg.stage("Connecting terminal interface...")
            self.model = StructuralModel("Loaded Project")
            self.terminal_panel.set_model(self.model)
            QApplication.processEvents()

            file_size_kb = os.path.getsize(filename) / 1024.0
            dlg.stage(f"Disk write complete ({file_size_kb:.1f} KB)")
    
            def _report(msg):
                dlg.stage(msg)
                QApplication.processEvents()

            self.model.load_from_file(filename, progress=_report)
                                     
            self.undo_stack.clear()
            self.model.file_path = filename
            QApplication.processEvents()
    
            dlg.stage("Restoring viewport settings...")
            if self.model.graphics_settings:
                current_msaa = self.graphics_settings.get("msaa_level", 2)
                self.graphics_settings.update(self.model.graphics_settings)
                self.graphics_settings["msaa_level"] = current_msaa
                self._apply_canvas_view_settings(self.graphics_settings)
                self.update_graphics_settings(self.graphics_settings)
            QApplication.processEvents()
    
            dlg.stage("Applying unit system...")
            if hasattr(self.model, 'saved_unit_system'):
                self.combo_units.blockSignals(True)
                self.combo_units.setCurrentText(self.model.saved_unit_system)
                self.combo_units.blockSignals(False)
                self.on_units_changed(0)
            QApplication.processEvents()
    
            self.draw_both_canvases(progress=_report)
            self.update_yield_lines()                                                                            
            self.canvas.set_standard_view("3D")
            self.set_interface_state(True)
            self.update_window_title()
            self.status.showMessage(f"Loaded: {filename}")
            QApplication.processEvents()
    
            dlg.finish(success=True)
    
        except Exception as e:
            dlg.keep_open()                                                                 
            dlg.stage(f"Error: {str(e)[:80]}")
            dlg.finish(success=False)
            QMessageBox.critical(self, "Load Error", f"Corrupt file or version mismatch.\n{e}")

        finally:
                                                                   
                if hasattr(self, 'canvas'): 
                    self.canvas.setUpdatesEnabled(True)
                    self.canvas.update()
                if hasattr(self, 'canvas_2d'): 
                    self.canvas_2d.setUpdatesEnabled(True)
                    self.canvas_2d.update()

    def on_define_materials(self):
        if not self.model: return
        dialog = MaterialManagerDialog(self.model, self)
        dialog.exec()

    def on_define_sections(self):
        if not self.model: return
        from app.dialogs.section_dialog import SectionManagerDialog
        dialog = SectionManagerDialog(self.model, self)
        dialog.exec()
        self.draw_both_canvases()

    def on_define_area_sections(self):
        if not self.model: return
        from app.dialogs.area_section_dialog import AreaSectionsManagerDialog
        dialog = AreaSectionsManagerDialog(self.model, self)
        dialog.exec()
        self.draw_both_canvases()

    def on_define_load_patterns(self):
        if not self.model: return
        dialog = LoadPatternDialog(self.model, self)
        dialog.exec()

    def _on_sidebar_select_mode(self):
        """Kills any active drawing modes and returns to pure selection state."""
                                                    
        if getattr(self, 'draw_mode_active', False):
            if getattr(self, 'draw_dialog', None): self.draw_dialog.hide()
            self.on_draw_finished()
            
        if getattr(self, 'cross_brace_mode_active', False):
            if getattr(self, 'cross_brace_dialog', None): self.cross_brace_dialog.hide()
            self.on_cross_brace_finished()
            
        if getattr(self, 'beam_col_mode_active', False):
            if getattr(self, 'beam_col_dialog', None): self.beam_col_dialog.hide()
            self.on_beam_col_finished()
            
        self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        if getattr(self, 'canvas2_visible', False):
            self.canvas2.setCursor(Qt.CursorShape.ArrowCursor)
            
        self.status.showMessage("Ready (Selection Mode)")

        if getattr(self, 'draw_area_mode_active', False):
            if getattr(self, 'draw_area_dialog', None): self.draw_area_dialog.hide()
            self.on_draw_poly_area_finished()

        if getattr(self, 'draw_link2_mode_active', False):
            if getattr(self, 'draw_link2_dialog', None): self.draw_link2_dialog.hide()
            self.on_draw_link2_finished()

        if getattr(self, 'draw_link1_mode_active', False):
            if getattr(self, 'draw_link1_dialog', None): self.draw_link1_dialog.hide()
            self.on_draw_link1_finished()

    def on_define_link_properties(self):
        if not self.model: return
        from app.dialogs.define_link_dialog import LinkManagerDialog
        
        dialog = LinkManagerDialog(self.model, self)
        dialog.exec()
        
        self.status.showMessage("Link Properties updated.")

    def on_draw_link2(self):
        if not hasattr(self.model, 'link_properties') or not self.model.link_properties:
            QMessageBox.warning(self, "Error", "Define a Link Property first!")
            if hasattr(self, 'act_select'): self.act_select.setChecked(True)
            return
            
        self.draw_link2_mode_active = True
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs: cvs.snapping_enabled = True
        self.draw_start_node = None
        self.status.showMessage("Draw 2-Joint Link: Select Start Point...")
        
        if self.draw_link2_dialog is None:
            from app.dialogs.draw_link_dialogs import DrawLink2JDialog
            self.draw_link2_dialog = DrawLink2JDialog(self.model, self)
            self.draw_link2_dialog.signal_dialog_closed.connect(self.on_draw_link2_finished)
            
        self.draw_link2_dialog.refresh_properties()
        self.draw_link2_dialog.show()

    def on_draw_link2_finished(self):
        self.draw_link2_mode_active = False
        self.draw_start_node = None
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs:
                cvs.snapping_enabled = False 
                cvs.hide_preview_line()
                cvs._draw_start = None
        self.status.showMessage("Ready")
        if hasattr(self, 'act_select'): self.act_select.setChecked(True)

    def on_draw_link1(self):
        if not hasattr(self.model, 'link_properties') or not self.model.link_properties:
            QMessageBox.warning(self, "Error", "Define a Link Property first!")
            if hasattr(self, 'act_select'): self.act_select.setChecked(True)
            return
            
        self.draw_link1_mode_active = True
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs: cvs.snapping_enabled = True
        self.status.showMessage("Draw 1-Joint Link: Click a joint to assign...")
        
        if self.draw_link1_dialog is None:
            from app.dialogs.draw_link_dialogs import DrawLink1JDialog
            self.draw_link1_dialog = DrawLink1JDialog(self.model, self)
            self.draw_link1_dialog.signal_dialog_closed.connect(self.on_draw_link1_finished)
            
        self.draw_link1_dialog.refresh_properties()
        self.draw_link1_dialog.show()

    def on_draw_link1_finished(self):
        self.draw_link1_mode_active = False
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs: cvs.snapping_enabled = False
        self.status.showMessage("Ready")
        if hasattr(self, 'act_select'): self.act_select.setChecked(True)

    def _frame_exists_between(self, p1, p2):
        """Return True if an element already connects the same two points (either direction)."""
        tol = 1e-6
        for elem in self.model.elements.values():
            ni, nj = elem.node_i, elem.node_j
            fwd = (abs(ni.x-p1[0])<tol and abs(ni.y-p1[1])<tol and abs(ni.z-p1[2])<tol and
                   abs(nj.x-p2[0])<tol and abs(nj.y-p2[1])<tol and abs(nj.z-p2[2])<tol)
            rev = (abs(ni.x-p2[0])<tol and abs(ni.y-p2[1])<tol and abs(ni.z-p2[2])<tol and
                   abs(nj.x-p1[0])<tol and abs(nj.y-p1[1])<tol and abs(nj.z-p1[2])<tol)
            if fwd or rev:
                return True
        return False

    def _get_brace_cell_corners(self, x, y, z):
        """
        Given a snapped grid corner and the active view plane, returns the
        4 corners of the grid cell extending in the +axis direction.
        corners[0]→corners[2] = diagonal A (↗), corners[1]→corners[3] = diagonal B (↖)
        Returns None if no valid adjacent cell exists.
        """
        if not self.canvas.active_view_plane:
            return None
        grids = self.model.grid
        axis = self.canvas.active_view_plane['axis']
        val  = self.canvas.active_view_plane['value']

        def next_val(v, sorted_list):
            for gv in sorted_list:
                if gv > v + 0.001:
                    return gv
            return None

        xs = sorted(grids.x_grids)
        ys = sorted(grids.y_grids)
        zs = sorted(grids.z_grids)

        if axis == 'z':                                   
            x_hi = next_val(x, xs)
            y_hi = next_val(y, ys)
            if x_hi is None or y_hi is None:
                return None
            return [
                (x,    y,    val),                  
                (x_hi, y,    val),                  
                (x_hi, y_hi, val),                  
                (x,    y_hi, val),                  
            ]
        elif axis == 'x':                                 
            y_hi = next_val(y, ys)
            z_hi = next_val(z, zs)
            if y_hi is None or z_hi is None:
                return None
            return [
                (val, y,    z),                     
                (val, y_hi, z),                     
                (val, y_hi, z_hi),                  
                (val, y,    z_hi),                  
            ]
        elif axis == 'y':                                 
            x_hi = next_val(x, xs)
            z_hi = next_val(z, zs)
            if x_hi is None or z_hi is None:
                return None
            return [
                (x,    val, z),                     
                (x_hi, val, z),                     
                (x_hi, val, z_hi),                  
                (x,    val, z_hi),                  
            ]
        return None

    def keyPressEvent(self, event):

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if getattr(self, 'draw_area_mode_active', False):
                self._finalize_poly_area()
                return

        if event.key() == Qt.Key.Key_Escape:
            if self.draw_mode_active:
                if self.draw_dialog:
                    self.draw_dialog.hide()
                self.on_draw_finished()
                if hasattr(self, 'act_select'):
                    self.act_select.setChecked(True)
                return                              
            if self.cross_brace_mode_active:
                if self.cross_brace_dialog:
                    self.cross_brace_dialog.hide()
                self.on_cross_brace_finished()
                if hasattr(self, 'act_select'):
                    self.act_select.setChecked(True)
                return
            if self.beam_col_mode_active:
                if self.beam_col_dialog:
                    self.beam_col_dialog.hide()
                self.on_beam_col_finished()
                if hasattr(self, 'act_select'):
                    self.act_select.setChecked(True)
                return
                                               
            if hasattr(self, 'act_select'):
                self.act_select.setChecked(True)
            self.on_select_none()
            return

        elif event.key() == Qt.Key.Key_Delete:
            if getattr(self, 'is_locked', False):
                self.status.showMessage("⚠️ Cannot delete objects while Analysis Results are active. Unlock model first.")
                return
            self.delete_current_selection()

        super().keyPressEvent(event)
        
    def _place_beam_column_at(self):
        import numpy as np
        seg = self.active_canvas._beam_col_hover_seg
        if seg is None: return

        section = self.beam_col_dialog.get_selected_section()
        if not section: return

        p1, p2 = seg
        rel_i, rel_j  = self.beam_col_dialog.get_release_arrays()
        member_type   = self.beam_col_dialog.get_member_type()
        rotation      = self.beam_col_dialog.get_rotation_angle()
        
        if self._frame_exists_between(tuple(p1), tuple(p2)):
            self.status.showMessage("⚠️ Cannot place element: an element already exists here.")
            return

        card_point = 10
        no_trans = False
        if member_type == 'beam' and self.beam_col_dialog.get_apply_offset():
            card_point = 8             
            no_trans = self.beam_col_dialog.get_no_transform()

        label = "Draw Quick Beam" if member_type == 'beam' else "Draw Quick Column"
        cmd = CmdDrawFrame(self.model, self, tuple(p1), tuple(p2), section, 
                           rel_i, rel_j, rotation, card_point, no_trans, description=label)
        self.add_command(cmd)
        self.status.showMessage(f"{label} placed. Click another segment or Esc to exit.")

    def _draw_cross_brace_at(self, x, y, z):
        section = self.cross_brace_dialog.get_selected_section()
        if not section:
            self.status.showMessage("Error: No Section selected.")
            return

        corners = self.active_canvas._brace_hover_cell
        if corners is None:
            self.status.showMessage("No grid cell detected — move mouse over a valid cell.")
            return

        rel_i, rel_j  = self.cross_brace_dialog.get_release_arrays()
        brace_type     = self.cross_brace_dialog.get_brace_type()

        placed = 0
        skipped = 0
        self.undo_stack.beginMacro("Draw Cross Brace")

        if brace_type in ("x", "diag_a"):
            if self._frame_exists_between(corners[0], corners[2]):
                skipped += 1
            else:
                cmd = CmdDrawFrame(self.model, self, corners[0], corners[2], section, rel_i, rel_j)
                self.undo_stack.push(cmd)
                placed += 1

        if brace_type in ("x", "diag_b"):
            if self._frame_exists_between(corners[1], corners[3]):
                skipped += 1
            else:
                cmd = CmdDrawFrame(self.model, self, corners[1], corners[3], section, rel_i, rel_j)
                self.undo_stack.push(cmd)
                placed += 1

        self.undo_stack.endMacro()

        if skipped > 0 and placed == 0:
            self.status.showMessage("⚠️ Cannot place brace: element(s) already exist on this cell.")
        elif skipped > 0:
            self.status.showMessage(f"Cross Brace placed ({skipped} diagonal(s) skipped — already exist). Click another cell or Esc to exit.")
        else:
            self.status.showMessage("Cross Brace placed. Click another cell or Esc to exit.")

    def on_draw_poly_area(self):
        if not self.model.area_sections:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", "Define an Area Section Property first!")
            if hasattr(self, 'act_select'):
                self.act_select.setChecked(True)
            return
            
        self.draw_area_mode_active = True
        self._current_area_nodes = []
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs: cvs.snapping_enabled = True
        
        if self.draw_area_dialog is None:
            from app.dialogs.draw_poly_area_dialog import DrawPolyAreaDialog
            self.draw_area_dialog = DrawPolyAreaDialog(self.model, self)
        
        self.draw_area_dialog.refresh_sections()
        self.draw_area_dialog.show()
        self.status.showMessage("Draw Poly Area: Click nodes sequentially to define corners...")

    def on_draw_poly_area_finished(self):
        self.draw_area_mode_active = False
        self._current_area_nodes = []
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs: 
                cvs.hide_area_preview()
                cvs.snapping_enabled = False
        self.status.showMessage("Ready")
        if hasattr(self, 'act_select'):
            self.act_select.setChecked(True)

    def _finalize_poly_area(self):
        if len(self._current_area_nodes) >= 3:
            sec = self.draw_area_dialog.get_selected_section()
            if sec:
                cmd = CmdDrawAreaElement(self.model, self, list(self._current_area_nodes), sec)
                self.add_command(cmd)
                self.status.showMessage(f"Area Element drawn with {len(self._current_area_nodes)} nodes.")
            else:
                self.status.showMessage("Error: No Section Selected.")
        else:
            self.status.showMessage("Area canceled: Requires at least 3 nodes to form a face.")
            
        self._current_area_nodes = []
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs: cvs.hide_area_preview()

    def handle_canvas_click(self, x, y, z):
        if getattr(self, 'draw_area_mode_active', False):
            coord = (x, y, z)
            if coord not in self._current_area_nodes:
                self._current_area_nodes.append(coord)
                self.status.showMessage(f"Area Node {len(self._current_area_nodes)} added. Press Enter or Right-Click to finish.")
            return
        if self.cross_brace_mode_active:
            self._draw_cross_brace_at(x, y, z)
            return
        if self.beam_col_mode_active:
            self._place_beam_column_at()
            return
        if self.picking_replicate:
            if self.replicate_p1 is None:
                self.replicate_p1 = (x, y, z)
                self.status.showMessage("Replicate: Click Second Point...")
            else:
                x1, y1, z1 = self.replicate_p1
                dx, dy, dz = x - x1, y - y1, z - z1
                
                self.picking_replicate = False
                self.replicate_p1 = None
                for cvs in [self.canvas, self.canvas2]:
                    cvs.snapping_enabled = False                          
                
                if self.replicate_dialog:
                    self.replicate_dialog.set_increments(dx, dy, dz)
                
                self.status.showMessage("Replicate values set.")
            return        

        if getattr(self, 'draw_link1_mode_active', False):
            prop_name = self.draw_link1_dialog.get_selected_property()
            if prop_name:
                from app.commands import CmdDrawLink1J
                cmd = CmdDrawLink1J(self.model, self, (x, y, z), prop_name)
                self.add_command(cmd)
                self.status.showMessage(f"1-Joint Link '{prop_name}' placed. Click another joint or Esc to exit.")
            return

        if getattr(self, 'draw_link2_mode_active', False):
            clicked_node = self.model.get_or_create_node(x, y, z)
            if getattr(self, 'draw_start_node', None) is None:
                self.draw_start_node = clicked_node
                self.active_canvas._draw_start = (clicked_node.x, clicked_node.y, clicked_node.z)
                self.status.showMessage(f"Link Start Selected. Select End Point...")
            else:
                end_node = clicked_node
                dx = end_node.x - self.draw_start_node.x
                dy = end_node.y - self.draw_start_node.y
                dz = end_node.z - self.draw_start_node.z
                if (dx**2 + dy**2 + dz**2) < 0.001: return                      
                
                prop_name = self.draw_link2_dialog.get_selected_property()
                if prop_name:
                    p1 = (self.draw_start_node.x, self.draw_start_node.y, self.draw_start_node.z)
                    p2 = (end_node.x, end_node.y, end_node.z)
                    
                    from app.commands import CmdDrawLink2J
                    cmd = CmdDrawLink2J(self.model, self, p1, p2, prop_name)
                    self.add_command(cmd)
                    
                    self.draw_start_node = self.model.get_or_create_node(*p2)
                    self.active_canvas._draw_start = (self.draw_start_node.x, self.draw_start_node.y, self.draw_start_node.z)
                    self.status.showMessage(f"2-Joint Link Drawn. Next Start Node selected...")
            return                
        
        if not self.draw_mode_active: return
        clicked_node = self.model.get_or_create_node(x, y, z)

        if getattr(self, 'draw_link1_mode_active', False):
            prop_name = self.draw_link1_dialog.get_selected_property()
            if prop_name:
                from app.commands import CmdDrawLink1J
                cmd = CmdDrawLink1J(self.model, self, (x, y, z), prop_name)
                self.add_command(cmd)
                self.status.showMessage(f"1-Joint Link '{prop_name}' placed. Click another joint or Esc to exit.")
            return

        if getattr(self, 'draw_link2_mode_active', False):
            clicked_node = self.model.get_or_create_node(x, y, z)
            if getattr(self, 'draw_start_node', None) is None:
                self.draw_start_node = clicked_node
                self.active_canvas._draw_start = (clicked_node.x, clicked_node.y, clicked_node.z)
                self.status.showMessage(f"Link Start Selected. Select End Point...")
            else:
                end_node = clicked_node
                dx = end_node.x - self.draw_start_node.x
                dy = end_node.y - self.draw_start_node.y
                dz = end_node.z - self.draw_start_node.z
                if (dx**2 + dy**2 + dz**2) < 0.001: return 
                
                prop_name = self.draw_link2_dialog.get_selected_property()
                if prop_name:
                    p1 = (self.draw_start_node.x, self.draw_start_node.y, self.draw_start_node.z)
                    p2 = (end_node.x, end_node.y, end_node.z)
                    
                    from app.commands import CmdDrawLink2J
                    cmd = CmdDrawLink2J(self.model, self, p1, p2, prop_name)
                    self.add_command(cmd)
                    
                    self.draw_start_node = self.model.get_or_create_node(*p2)
                    self.active_canvas._draw_start = (self.draw_start_node.x, self.draw_start_node.y, self.draw_start_node.z)
                    self.status.showMessage(f"2-Joint Link Drawn. Next Start Node selected...")
            return
            
        if self.draw_start_node is None:
            self.draw_start_node = clicked_node
            self.active_canvas._draw_start = (clicked_node.x, clicked_node.y, clicked_node.z)
            self.status.showMessage(f"Start Node {clicked_node.id} Selected. Select End Point...")
        else:
            end_node = clicked_node
            dx = end_node.x - self.draw_start_node.x
            dy = end_node.y - self.draw_start_node.y
            dz = end_node.z - self.draw_start_node.z
            if (dx**2 + dy**2 + dz**2) < 0.001:
                return
            
            section = self.draw_dialog.get_selected_section()
            rel_i, rel_j = self.draw_dialog.get_release_arrays()
            
            if section:
                p1 = (self.draw_start_node.x, self.draw_start_node.y, self.draw_start_node.z)
                p2 = (end_node.x, end_node.y, end_node.z)

                if self._frame_exists_between(p1, p2):
                    self.status.showMessage("⚠️ Cannot draw: an element already exists between these two nodes.")
                    return
                
                cmd = CmdDrawFrame(self.model, self, p1, p2, section, rel_i, rel_j)
                self.add_command(cmd)
                
                self.draw_start_node = self.model.get_or_create_node(*p2)
                self.active_canvas._draw_start = (self.draw_start_node.x, self.draw_start_node.y, self.draw_start_node.z)
                
                self.status.showMessage(f"Element Drawn. Next Start: Node {end_node.id}...")
            else:
                self.status.showMessage("Error: No Section Selected")
                
    def handle_right_click(self):
        if getattr(self, 'draw_area_mode_active', False):
            self._finalize_poly_area()
            return
        if self.draw_mode_active:
            for cvs in [self.canvas, self.canvas2]:
                cvs.hide_preview_line()
                cvs._draw_start = None
            if self.draw_start_node:
                self.draw_start_node = None
                self.status.showMessage("Chain Broken. Select a new Start Point...")
            return

        menu = QMenu(self)
        hit_something = False 

        target_area_id = getattr(self.canvas, 'hovered_area_id', None)
        if target_area_id is None and len(getattr(self, 'selected_area_ids', [])) == 1:
            target_area_id = self.selected_area_ids[0]

        target_node_id = getattr(self.canvas, 'hovered_node_id', None)
        if target_node_id is None and len(self.selected_node_ids) == 1:
            target_node_id = self.selected_node_ids[0]

        target_elem_id = getattr(self.canvas, 'hovered_elem_id', None)
        if target_elem_id is None and len(self.selected_ids) == 1:
            target_elem_id = self.selected_ids[0]

        target_link_id = getattr(self.canvas, 'hovered_link_id', None)
        if target_link_id is None and len(getattr(self, 'selected_link_ids', [])) == 1:
            target_link_id = self.selected_link_ids[0]

        if target_node_id is not None and hasattr(self.model, 'has_results') and self.model.has_results:
            res_action = menu.addAction(f"Joint {target_node_id} Results...")
            
            def show_node_dlg():
                from app.dialogs.node_results_dialog import NodeResultsDialog
                self._node_res_dlg = NodeResultsDialog(target_node_id, self.model, self)
                self._node_res_dlg.signal_mode_changed.connect(self.switch_modal_view)

                self._node_res_dlg.canvas = self.canvas
                
                if hasattr(self.canvas, 'animation_manager') and getattr(self.canvas, 'ltha_mode', False):
                    self.canvas.animation_manager.signal_ltha_frame_update.connect(self._node_res_dlg.update_live_values)
                    idx = self._node_res_dlg.combo_cases.findData("LTHA_LIVE")
                    if idx >= 0:
                        self._node_res_dlg.combo_cases.setCurrentIndex(idx)
                self._node_res_dlg.show()
                
            res_action.triggered.connect(show_node_dlg)
            menu.addSeparator()
            hit_something = True

        if target_elem_id is not None or target_node_id is not None or target_area_id is not None or target_link_id is not None:
            menu.addSeparator()
            
            if target_elem_id is not None:
                obj = self.model.elements.get(target_elem_id)
                menu_text = f"Frame Information..."
            elif target_area_id is not None:
                obj = getattr(self.model, 'area_elements', {}).get(target_area_id)
                menu_text = f"Area Information..."
            elif target_link_id is not None:
                obj = getattr(self.model, 'links', {}).get(target_link_id)
                menu_text = f"Link Information..."
            else:
                obj = self.model.nodes.get(target_node_id)
                menu_text = f"Joint Information..."

            if obj:
                info_action = menu.addAction(menu_text)
                
                def show_info():
                    from app.dialogs.element_info_dialog import ObjectInfoDialog
                    dlg = ObjectInfoDialog(obj, self.model, self)
                    dlg.exec()
                    
                info_action.triggered.connect(show_info)
                hit_something = True

            if target_link_id is not None:
                link_obj = getattr(self.model, 'links', {}).get(target_link_id)
                if link_obj is not None:
                    link_nodes = link_obj.get('nodes', []) if isinstance(link_obj, dict) else getattr(link_obj, 'nodes', [])
                    if len(link_nodes) == 1:
                        del_link_action = menu.addAction("Delete 1D Link")
                        def force_delete_1d_link(lid=target_link_id):
                                                                        
                            if getattr(self, 'is_locked', False):
                                self.status.showMessage("⚠️ Cannot delete objects while Analysis Results are active. Unlock model first.")
                                return
                            print(f"DEBUG: about to delete link {lid}", flush=True)
                            cmd = CmdDeleteSelection(self.model, self, [], [], area_elem_ids=[], link_ids=[lid])
                            self.add_command(cmd)
                            print(f"DEBUG: link {lid} still in model.links? {lid in self.model.links}", flush=True)
                                                                                         
                            self.selected_link_ids = [l for l in getattr(self, 'selected_link_ids', []) if l != lid]
                            if target_node_id in self.selected_node_ids:
                                self.selected_node_ids.remove(target_node_id)
                            self._refresh_selection_overlay()
                            self.status.showMessage("1D Link Deleted.")
                        del_link_action.triggered.connect(force_delete_1d_link)
                    
        if target_elem_id is not None and hasattr(self.model, 'has_results') and self.model.has_results:
            eid = target_elem_id
            spy_action = menu.addAction("Show Matrices (K, T, FEE)")
            def show_spy():
                if hasattr(self, 'solver_output_path') and self.solver_output_path:
                    base = self.solver_output_path.replace("_results.json", "_matrices.json")
                    from app.dialogs.spy_dialogs import MatrixSpyDialog
                    dlg = MatrixSpyDialog(eid, base, self)
                    dlg.exec()
            spy_action.triggered.connect(show_spy)

            fbd_action = menu.addAction("Show Free Body Diagram")
            def show_fbd():
                if hasattr(self, 'solver_output_path') and self.solver_output_path:
                    base = self.solver_output_path.replace("_results.json", "_matrices.json")
                    from app.dialogs.spy_dialogs import FBDViewerDialog
                    
                    dlg = FBDViewerDialog(eid, self.model, self.solver_output_path, base, self)
                    
                    dlg.inspection_location_changed.connect(self.canvas.update_inspection_dot)
                    dlg.inspection_closed.connect(self.canvas.hide_inspection_dot)
                    
                    if getattr(self, 'canvas2_visible', False):
                        dlg.inspection_location_changed.connect(self.canvas2.update_inspection_dot)
                        dlg.inspection_closed.connect(self.canvas2.hide_inspection_dot)
                                                       
                    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                    dlg.show()
            fbd_action.triggered.connect(show_fbd)

        if self.selected_ids or self.selected_node_ids:
            menu.addSeparator()
            delete_action = menu.addAction("Delete Selection")
            delete_action.triggered.connect(self.delete_current_selection)
            hit_something = True

        if not hit_something:
            grid_action = menu.addAction("Edit Grid Data...")
            grid_action.triggered.connect(self.open_grid_editor)

        menu.exec(QCursor.pos())

    def open_grid_editor(self):
        if not self.model: return
        from app.dialogs.grid_dialog import GridEditorDialog
        
        dialog = GridEditorDialog(self.model.grid, self)
        if dialog.exec():
                                
            new_grids = dialog.get_final_grids()
            
            self.model.grid.x_lines = new_grids["x"]
            self.model.grid.y_lines = new_grids["y"]
            self.model.grid.z_lines = new_grids["z"]

            self.model.grid.bubble_size = new_grids.get("bubble_size", 1.25)
            self.model.grid.bubble_alpha = new_grids.get("bubble_alpha", 1.0)
            
            self.canvas.draw_model(self.model)
            if getattr(self, 'canvas2_visible', False):
                self.canvas2.draw_model(self.model, list(self.selected_ids), list(self.selected_node_ids))

    def _handle_box_selection_canvas2(self, node_ids, elem_ids, link_ids, is_additive, is_deselect):
        """Route canvas2 box-selection only when canvas2 is the active canvas."""
        if self.active_canvas is not self.canvas2:
            return
        self.handle_box_selection(node_ids, elem_ids, link_ids, is_additive, is_deselect)

    def handle_area_box_selection(self, area_ids, is_additive, is_deselect):
        """Handle selection/deselection of area elements from canvas signals."""
        
        active_plane = self.active_canvas.active_view_plane
        is_2d_view = self.active_canvas._view_mode in ["XY", "XZ", "YZ"]
        
        if is_2d_view and active_plane:
            axis = active_plane['axis']                         
            plane_val = active_plane['value']
            tol = 1e-5                                                                   
            
            filtered_ids = []
            for aid in area_ids:
                area_obj = None
                if hasattr(self.model, 'area_elements'):
                    area_obj = self.model.area_elements.get(aid)
                
                if not area_obj or not hasattr(area_obj, 'nodes'):
                    continue
                    
                on_plane = True
                for node in area_obj.nodes:
                    node_val = getattr(node, axis)
                    if abs(node_val - plane_val) > tol:
                        on_plane = False
                        break
                        
                if on_plane:
                    filtered_ids.append(aid)
                    
            area_ids = filtered_ids
                                                                  
        if is_deselect:
            for aid in area_ids:
                if aid in self.selected_area_ids:
                    self.selected_area_ids.remove(aid)
        else:
            hit_something = len(area_ids) > 0
            if hit_something:
                for aid in area_ids:
                    if aid not in self.selected_area_ids:
                        self.selected_area_ids.append(aid)

        n_areas = len(self.selected_area_ids)
        n_frames = len(self.selected_ids)
        n_joints = len(self.selected_node_ids)
        parts = []
        if n_frames: parts.append(f"{n_frames} Frames")
        if n_joints: parts.append(f"{n_joints} Joints")
        if n_areas:  parts.append(f"{n_areas} Areas")
        self.status.showMessage(f"Selected: {', '.join(parts)}" if parts else "Selection Cleared")

        for cvs in [self.canvas, self.canvas2]:
            cvs.update_selection_overlay(self.selected_ids, self.selected_node_ids, self.selected_area_ids, getattr(self, 'selected_link_ids', []))
            
    def handle_box_selection(self, node_ids, elem_ids, link_ids, is_additive, is_deselect):
        if not hasattr(self, 'selected_link_ids'): 
            self.selected_link_ids = []

        if is_additive:
            self.selected_node_ids = list(set(self.selected_node_ids + node_ids))
            self.selected_ids = list(set(self.selected_ids + elem_ids))
            self.selected_link_ids = list(set(getattr(self, 'selected_link_ids', []) + link_ids))
        elif is_deselect:
            self.selected_node_ids = [n for n in self.selected_node_ids if n not in node_ids]
            self.selected_ids = [e for e in self.selected_ids if e not in elem_ids]
            self.selected_link_ids = [l for l in getattr(self, 'selected_link_ids', []) if l not in link_ids]
        else:
            hit_something = bool(node_ids or elem_ids or link_ids)
            if hit_something:
                                                                                                    
                self.selected_node_ids = list(set(self.selected_node_ids + node_ids))
                self.selected_ids = list(set(self.selected_ids + elem_ids))
                self.selected_link_ids = list(set(getattr(self, 'selected_link_ids', []) + link_ids))
                                                                                              
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs:
                cvs.update_selection_overlay(self.selected_ids, self.selected_node_ids, getattr(self, 'selected_area_ids', []), self.selected_link_ids)

        self.status.showMessage(f"Selected: {len(self.selected_ids)} Frames, {len(self.selected_node_ids)} Joints, {len(self.selected_link_ids)} Links")

        modifiers = QApplication.keyboardModifiers()
        is_focus_requested = (modifiers == Qt.KeyboardModifier.AltModifier)

        if is_focus_requested and (node_ids or elem_ids):
                                                    
            sel_pts = []
            for nid in node_ids:
                n = self.model.nodes[nid]
                sel_pts.append((n.x, n.y, n.z))
            for eid in elem_ids:
                el = self.model.elements[eid]
                sel_pts.append((el.node_i.x, el.node_i.y, el.node_i.z))
                sel_pts.append((el.node_j.x, el.node_j.y, el.node_j.z))

            if sel_pts:
                xs = [p[0] for p in sel_pts]
                ys = [p[1] for p in sel_pts]
                zs = [p[2] for p in sel_pts]
                cx = (min(xs) + max(xs)) / 2.0
                cy = (min(ys) + max(ys)) / 2.0
                cz = (min(zs) + max(zs)) / 2.0
                sel_diag = math.sqrt(
                    (max(xs)-min(xs))**2 +
                    (max(ys)-min(ys))**2 +
                    (max(zs)-min(zs))**2
                )
                                                                       
                if sel_diag < 0.001:
                    _, model_diag, _ = self.canvas.compute_model_bbox()
                    sel_diag = model_diag * 0.20

                target        = QVector3D(cx, cy, cz)
                target_dist   = self.canvas._fit_distance(sel_diag, self.canvas.opts.get('fov', 60))
                self.canvas.camera.animate_to(
                    target_center=target, target_dist=target_dist
                )
                if len(node_ids) == 1 and not elem_ids:
                    self.status.showMessage(f"Focused on Node {node_ids[0]}")
                elif len(elem_ids) == 1 and not node_ids:
                    self.status.showMessage(f"Focused on Frame {elem_ids[0]}")
                else:
                    self.status.showMessage(
                        f"Focused on {len(elem_ids)} Frames, {len(node_ids)} Joints"
                    )

    def delete_current_selection(self):
        if not self.model: return
        
        if not self.selected_ids and not self.selected_node_ids and not self.selected_area_ids and not getattr(self, 'selected_link_ids', []):
            return

        final_elem_ids = list(self.selected_ids)
        
        final_node_ids = []
        
        for nid in self.selected_node_ids:
            is_safe_to_delete = True
            
            for el in self.model.elements.values():
                                                        
                if el.node_i.id == nid or el.node_j.id == nid:
                                                                                       
                    if el.id not in final_elem_ids:
                        is_safe_to_delete = False
                        break                                                                  
            
            if is_safe_to_delete:
                for slab in self.model.slabs.values():
                    slab_node_ids = [n.id for n in slab.nodes]
                    if nid in slab_node_ids:
                                                                                                
                        is_safe_to_delete = False 
                        break

            if is_safe_to_delete:
                for ae in self.model.area_elements.values():
                    if ae.id not in self.selected_area_ids:                                              
                        if any(n.id == nid for n in ae.nodes):
                            is_safe_to_delete = False
                            break

            if is_safe_to_delete:
                final_node_ids.append(nid)
            else:
                print(f"Node {nid} is protected because it supports an existing object.")

        skipped_shared_joints = len(self.selected_node_ids) - len(final_node_ids)

        auto_link_ids = set(getattr(self, 'selected_link_ids', []))
        if hasattr(self.model, 'links'):
            kept_node_ids = set(self.selected_node_ids) - set(final_node_ids)
            for lid, link in self.model.links.items():
                l_nodes = link.get('nodes', []) if isinstance(link, dict) else getattr(link, 'nodes', [])
                if len(l_nodes) == 1 and l_nodes[0] in kept_node_ids:
                    auto_link_ids.add(lid)

        if self.selected_node_ids and not final_node_ids and not final_elem_ids and not self.selected_area_ids and not auto_link_ids:
            self.status.showMessage("⚠️ Cannot delete selected joints. They are shared with existing elements.")
            return

        deleted_area_count = len(self.selected_area_ids)
        deleted_link_count = len(auto_link_ids)

        cmd = CmdDeleteSelection(
            self.model, self, final_node_ids, final_elem_ids,
            area_elem_ids=list(self.selected_area_ids),
            link_ids=list(auto_link_ids)
        )
        self.add_command(cmd)
        
        self.selected_ids = [] 
        self.selected_node_ids = []
        self.selected_area_ids = []
        self.selected_link_ids = []          
        
        parts = []
        if final_elem_ids:     parts.append(f"{len(final_elem_ids)} Frames")
        if final_node_ids:     parts.append(f"{len(final_node_ids)} Joints")
        if deleted_area_count: parts.append(f"{deleted_area_count} Areas")
        if deleted_link_count: parts.append(f"{deleted_link_count} Links")          
        
        msg = f"Deleted {', '.join(parts)}." if parts else "Nothing deleted."
        if skipped_shared_joints:
            msg += f" (⚠️ {skipped_shared_joints} shared joint(s) skipped — still in use by other elements)"
        self.status.showMessage(msg)
        print(f"> GUI: {msg}")

    def is_node_connected(self, node_id):
        """Helper to check if any element in the model uses this node."""
        for el in self.model.elements.values():
            if el.node_i.id == node_id or el.node_j.id == node_id:
                return True
        return False
    
    def on_assign_restraints(self):
        if not hasattr(self, 'restraint_dlg') or not self.restraint_dlg.isVisible():
            from app.dialogs.restraint_dialog import RestraintDialog
            self.restraint_dlg = RestraintDialog(self)
            self.restraint_dlg.show()
        else: self.restraint_dlg.raise_()

    def on_assign_joint_springs(self):
        """Opens the Joint Spring Assignment Dialog"""
        if not hasattr(self, 'joint_spring_dlg') or not self.joint_spring_dlg.isVisible():
            from app.dialogs.assign_spring_dialog import AssignJointSpringDialog
            self.joint_spring_dlg = AssignJointSpringDialog(self)
            self.joint_spring_dlg.show()
        else: 
            self.joint_spring_dlg.raise_()

    def on_assign_constraints(self):
        if not hasattr(self, 'constraint_dlg') or not self.constraint_dlg.isVisible():
            from app.dialogs.assign_constraint_dialog import AssignConstraintDialog
            self.constraint_dlg = AssignConstraintDialog(self)
            self.constraint_dlg.show()
        else: self.constraint_dlg.raise_()

    def on_assign_joint_load(self):
        if not hasattr(self, 'joint_load_dlg') or not self.joint_load_dlg.isVisible():
            from app.dialogs.assign_load_dialog import AssignJointLoadDialog
            self.joint_load_dlg = AssignJointLoadDialog(self)
            self.joint_load_dlg.show()
        else: self.joint_load_dlg.raise_()

    def on_assign_joint_displacement(self):
        """Opens the Ground Displacement Assignment Dialog"""
        if not hasattr(self, 'joint_disp_dlg') or not self.joint_disp_dlg.isVisible():
            from app.dialogs.assign_displacement_dialog import AssignJointDisplacementDialog
            self.joint_disp_dlg = AssignJointDisplacementDialog(self)
            self.joint_disp_dlg.show()
        else: 
            self.joint_disp_dlg.raise_()

    def on_assign_frame_load(self):
        if not hasattr(self, 'frame_load_dlg') or not self.frame_load_dlg.isVisible():
            from app.dialogs.assign_member_load_dialog import AssignFrameLoadDialog
            self.frame_load_dlg = AssignFrameLoadDialog(self)
            self.frame_load_dlg.show()
        else: self.frame_load_dlg.raise_()

    def on_assign_releases(self):
        if not hasattr(self, 'release_dlg') or not self.release_dlg.isVisible():
            from app.dialogs.release_dialog import FrameReleaseDialog
            self.release_dlg = FrameReleaseDialog(self)
            self.release_dlg.show()
        else: self.release_dlg.raise_()

    def on_assign_local_axis(self):
        if not hasattr(self, 'axis_dlg') or not self.axis_dlg.isVisible():
            from app.dialogs.assign_local_axis_dialog import AssignFrameAxisDialog
            self.axis_dlg = AssignFrameAxisDialog(self)
            self.axis_dlg.show()
        else: self.axis_dlg.raise_()

    def _update_select_menu_state(self):
        self.deselect_menu.setEnabled(bool(self.selected_ids) or bool(self.selected_area_ids))

    def on_select_by_area_section(self):
        if not self.model:
            return
        if not hasattr(self, '_sel_by_area_sec_dlg') or not self._sel_by_area_sec_dlg.isVisible():
            from app.dialogs.select_by_section_dialog import SelectByAreaSectionDialog
            self._sel_by_area_sec_dlg = SelectByAreaSectionDialog(self, mode="select")
            self._sel_by_area_sec_dlg.show()
        else:
            self._sel_by_area_sec_dlg._populate()
            self._sel_by_area_sec_dlg.raise_()

    def on_deselect_by_area_section(self):
        if not self.model or not getattr(self, 'selected_area_ids', []):
            return
        if not hasattr(self, '_desel_by_area_sec_dlg') or not self._desel_by_area_sec_dlg.isVisible():
            from app.dialogs.select_by_section_dialog import SelectByAreaSectionDialog
            self._desel_by_area_sec_dlg = SelectByAreaSectionDialog(self, mode="deselect")
            self._desel_by_area_sec_dlg.show()
        else:
            self._desel_by_area_sec_dlg._populate()
            self._desel_by_area_sec_dlg.raise_()

    def on_select_by_section(self):
        if not self.model:
            return
        if not hasattr(self, '_sel_by_sec_dlg') or not self._sel_by_sec_dlg.isVisible():
            from app.dialogs.select_by_section_dialog import SelectByFrameSectionDialog
            self._sel_by_sec_dlg = SelectByFrameSectionDialog(self, mode="select")
            self._sel_by_sec_dlg.show()
        else:
            self._sel_by_sec_dlg._populate()
            self._sel_by_sec_dlg.raise_()

    def on_deselect_by_section(self):
        if not self.model or not self.selected_ids:
            return
        if not hasattr(self, '_desel_by_sec_dlg') or not self._desel_by_sec_dlg.isVisible():
            from app.dialogs.select_by_section_dialog import SelectByFrameSectionDialog
            self._desel_by_sec_dlg = SelectByFrameSectionDialog(self, mode="deselect")
            self._desel_by_sec_dlg.show()
        else:
            self._desel_by_sec_dlg._populate()
            self._desel_by_sec_dlg.raise_() 

    def on_view_options(self):
        if not hasattr(self, '_view_options_dialog') or self._view_options_dialog is None:
            self._view_options_dialog = ViewOptionsDialog(self)
            self._view_options_dialog.finished.connect(
                lambda: setattr(self, '_view_options_dialog', None)
            )
        self._view_options_dialog._load_from_active_canvas()
        self._view_options_dialog.show()
        self._view_options_dialog.raise_()
        self._view_options_dialog.activateWindow()

    def apply_view_options(self, settings):
        cvs = self.active_canvas
        cvs.view_extruded = settings.get('extrude', False)

        if cvs.view_extruded:
            if hasattr(cvs, 'clear_force_diagrams'):
                cvs.clear_force_diagrams()
            if hasattr(self.active_canvas, 'clear_reaction_diagram'):
                self.active_canvas.clear_reaction_diagram()

            cvs._pre_force_was_extruded = False

        cvs.show_slabs = settings.get('areas', True)
        cvs.show_grid            = settings.get('grid', True)
        cvs.show_ghost_structure = settings.get('ghost', True)
        cvs.show_joints          = settings.get('joints', True)
        cvs.show_supports        = settings.get('supports', True)
        cvs.show_constraints     = settings.get('constraints', True)
        cvs.show_releases        = settings.get('releases', True)
        cvs.show_loads           = settings.get('loads', True)
        cvs.show_tributary_loads = settings.get('tributary_loads', False)
        cvs.show_tributary_heatmap = settings.get('tributary_heatmap', False)
        cvs.show_tributary_mesh    = settings.get('tributary_mesh', False)
        cvs.show_local_axes      = settings.get('axes', False)
        cvs.load_type_filter     = settings.get('load_type', 'both')
        cvs.visible_load_patterns = settings.get('visible_patterns', [])

        if hasattr(cvs, '_update_tributary_visuals'):
            cvs._update_tributary_visuals()

        self.draw_both_canvases()
        self.status.showMessage(f"Display Options Updated")

    def on_edit_replicate(self):
        if self.replicate_dialog is None:
            from app.dialogs.replicate_dialog import ReplicateDialog
            self.replicate_dialog = ReplicateDialog(self)
            self.replicate_dialog.signal_pick_points.connect(self.start_replicate_picking)
            self.replicate_dialog.signal_apply.connect(self.on_replicate_apply)

        self.replicate_dialog.show()
        self.replicate_dialog.raise_()
        self.replicate_dialog.activateWindow()

    def on_replicate_apply(self):
        if (not self.selected_ids and not self.selected_node_ids
                and not self.selected_area_ids and not getattr(self, 'selected_link_ids', [])):
            QMessageBox.warning(self, "Selection", "Please select objects to replicate first.")
            return

        dx = self.replicate_dialog.dx
        dy = self.replicate_dialog.dy
        dz = self.replicate_dialog.dz
        num = self.replicate_dialog.num
        delete = self.replicate_dialog.delete_original

        cmd = CmdReplicate(
            self.model,
            self,
            list(self.selected_node_ids),
            list(self.selected_ids),
            list(self.selected_area_ids),
            dx, dy, dz, num, delete,
            link_ids=list(getattr(self, 'selected_link_ids', []))
        )
        self.add_command(cmd)

        n_skipped_nodes = len(set(cmd.skipped_node_ids))
        n_skipped_links = len(set(cmd.skipped_link_ids))
        if n_skipped_nodes or n_skipped_links:
            QMessageBox.warning(
                self, "Replicate: Some Items Skipped",
                f"{n_skipped_nodes} node(s) and {n_skipped_links} link(s) were not replicated: "
                "no connecting frame/area was selected with them, and no existing "
                "structure was found at the target location."
            )
        else:
            self.status.showMessage("Replication Complete.")

        self.selected_ids = []
        self.selected_node_ids = []
        self.selected_area_ids = []
        self.selected_link_ids = []
        self.draw_both_canvases()
            
    def on_draw_frame(self):
        if not self.model.sections:
            QMessageBox.warning(self, "Error", "Define a Section Property first!")
            return
        self.draw_mode_active = True
        for cvs in [self.canvas, self.canvas2]:
            cvs.snapping_enabled = True
        self.draw_start_node = None
        self.status.showMessage("Draw Mode: Select Start Point...")
        
        if self.draw_dialog is None:
            self.draw_dialog = DrawFrameDialog(self.model, self)
            self.draw_dialog.signal_dialog_closed.connect(self.on_draw_finished)
        
        self.draw_dialog.refresh_sections()
        self.draw_dialog.show()

    def on_draw_finished(self):
        self.draw_mode_active = False
        self.draw_start_node = None
        for cvs in [self.canvas, self.canvas2]:
            cvs.snapping_enabled = False 
            cvs.hide_preview_line()
            cvs._draw_start = None
            cvs.snap_ring.setVisible(False)
            cvs.snap_dot.setVisible(False)
        self.status.showMessage("Ready")
        if hasattr(self, 'act_select'):
            self.act_select.setChecked(True)

    def on_draw_cross_brace(self):
        if not self.model.sections:
            QMessageBox.warning(self, "Error", "Define a Section Property first!")
            return
        self.cross_brace_mode_active = True
        for cvs in [self.canvas, self.canvas2]:
            cvs.cross_brace_mode = True
            cvs.snapping_enabled = False
        self.status.showMessage("Cross Brace Mode: Hover over a grid cell and click to place brace...")
        if self.cross_brace_dialog is None:
            self.cross_brace_dialog = DrawCrossBraceDialog(self.model, self)
            self.cross_brace_dialog.signal_dialog_closed.connect(self.on_cross_brace_finished)
        self.cross_brace_dialog.refresh_sections()
        self.cross_brace_dialog.update_plane_status(self.active_canvas.active_view_plane)
        self.cross_brace_dialog.show()

    def on_cross_brace_finished(self):
        self.cross_brace_mode_active = False
        for cvs in [self.canvas, self.canvas2]:
            cvs.cross_brace_mode = False
            cvs.snapping_enabled = False
            cvs._brace_hover_cell = None
            cvs._brace_prev_x1.setVisible(False)
            cvs._brace_prev_x2.setVisible(False)
            cvs._brace_prev_border.setVisible(False)
        self.status.showMessage("Ready")
        if hasattr(self, 'act_select'):
            self.act_select.setChecked(True)

    def on_draw_beam_column(self):
        if not self.model.sections:
            QMessageBox.warning(self, "Error", "Define a Section Property first!")
            return
        self.beam_col_mode_active = True
        for cvs in [self.canvas, self.canvas2]:
            cvs.beam_col_mode = True
            cvs.snapping_enabled = False

        if self.beam_col_dialog is None:
            self.beam_col_dialog = DrawBeamColumnDialog(self.model, self)
            self.beam_col_dialog.signal_dialog_closed.connect(self.on_beam_col_finished)
            self.beam_col_dialog.signal_type_changed.connect(self._on_beam_col_type_changed)

        self.beam_col_dialog.refresh_sections()
        self._on_beam_col_type_changed(self.beam_col_dialog.get_member_type())
        self.beam_col_dialog.show()

    def update_yield_lines(self):
        """
        Triggers the async Tributary Area load generator.
        """
        if not hasattr(self, '_tributary_generator') or self._tributary_generator.model is not self.model:
            from core.tributary_loads import TributaryLoadGenerator
            self._tributary_generator = TributaryLoadGenerator(self.model)
            
            self._tributary_generator.signal_redraw_requested.connect(self._on_tributary_update_received)
        
        self._tributary_generator.distribute_loads_to_frames()

    def _on_tributary_update_received(self):
        """Forces the canvas to dump its cached slab mesh and redraw the new heatmap."""
                                                                             
        self.canvas.invalidate_area_vbo()
        
        if hasattr(self, 'canvas2'):
            self.canvas2.invalidate_area_vbo()
            
        self.draw_both_canvases()

    def _on_beam_col_type_changed(self, member_type):
        for cvs in [self.canvas, self.canvas2]:
            cvs._beam_col_type = member_type
            cvs._beam_col_hover_seg = None
            cvs._beam_col_prev_line.setVisible(False)
        if member_type == 'beam':
            self.status.showMessage("Beam Mode: Hover over a horizontal grid line and click to place...")
        else:
            self.status.showMessage("Column Mode: Hover over a vertical grid line and click to place...")

    def on_beam_col_finished(self):
        self.beam_col_mode_active = False
        for cvs in [self.canvas, self.canvas2]:
            cvs.beam_col_mode  = False
            cvs.snapping_enabled = False
            cvs._beam_col_hover_seg = None
            cvs._beam_col_prev_line.setVisible(False)
        self.status.showMessage("Ready")
        if hasattr(self, 'act_select'):
            self.act_select.setChecked(True)

    def start_replicate_picking(self):
        """Called when user clicks 'Pick Two Points' in dialog"""
        self.picking_replicate = True
        self.replicate_p1 = None
        for cvs in [self.canvas, self.canvas2]:
            cvs.snapping_enabled = True
        self.status.showMessage("Replicate: Click First Point...")

    def on_edit_merge(self):
        merged = self.model.merge_nodes(tolerance=0.005)
        orphans = self.model.remove_orphan_nodes()                        
        
        total = merged + orphans
        if total > 0:
            msg = []
            if merged:  msg.append(f"{merged} duplicate joints merged")
            if orphans: msg.append(f"{orphans} orphan nodes removed")
            self.status.showMessage("Cleanup: " + ", ".join(msg) + ".")
            QMessageBox.information(self, "Merge & Cleanup", "\n".join(msg) + ".")
            self.canvas.draw_model(self.model)
        else:
            self.status.showMessage("Merge Complete: Nothing to clean up.")
            QMessageBox.information(self, "Merge & Cleanup", "No duplicates or orphans found.")
            
    def on_assign_insertion_point(self):
        if not hasattr(self, 'insertion_dlg') or not self.insertion_dlg.isVisible():
            from app.dialogs.assign_insertion_point_dialog import AssignInsertionPointDialog
            self.insertion_dlg = AssignInsertionPointDialog(self)
            self.insertion_dlg.show()
        else: self.insertion_dlg.raise_()

    def on_assign_end_offsets(self):
        if not hasattr(self, 'end_offset_dlg') or not self.end_offset_dlg.isVisible():
            from app.dialogs.assign_end_offset_dialog import AssignEndOffsetDialog
            self.end_offset_dlg = AssignEndOffsetDialog(self)
            self.end_offset_dlg.show()
        else: 
            self.end_offset_dlg.raise_()

    def on_assign_frame_point_load(self):
        """Opens the Point Load Assignment Dialog"""
                                                                          
        if not hasattr(self, 'point_load_dlg') or not self.point_load_dlg.isVisible():
            self.point_load_dlg = AssignFramePointLoadDialog(self)
            self.point_load_dlg.show()
        else:
            self.point_load_dlg.raise_()    

    def on_graphics_options(self):
        """Opens the new Graphics Dialog."""
                                                      
        dlg = GraphicsOptionsDialog(self, self.graphics_settings)
        dlg.show()

    def update_graphics_settings(self, new_settings):
        """
        Called by the Dialog's Apply/OK button.
        Updates the master dict and triggers a canvas refresh.
        """

        import json, os
        prefs_path = os.path.join(os.path.expanduser("~"), ".Open//Structures_prefs.json")
        try:
            with open(prefs_path, 'w') as f:
                json.dump(new_settings, f)
        except:
            pass

        msaa_samples = {0: 0, 1: 4, 2: 8, 3: 16}
        level = new_settings.get("msaa_level", 2)
        self.graphics_settings["msaa_level"] = level
                                   
        self.graphics_settings.update(new_settings)
        
        self.canvas.display_config = self.graphics_settings
        
        if hasattr(self, 'canvas2'):
            self.canvas2.display_config = self.graphics_settings
        
        bg_tuple = self.graphics_settings["background_color"]
        c = QColor()
        c.setRgbF(bg_tuple[0], bg_tuple[1], bg_tuple[2], bg_tuple[3])
        self.canvas.setBackgroundColor(c)
        if hasattr(self, 'canvas2'):
            self.canvas2.setBackgroundColor(c)

        if self.model:
            self.draw_both_canvases()
            
        self.status.showMessage("Graphics settings updated.")
        
    def on_define_load_cases(self):
        if not self.model: return
                                                                
        self.model.create_default_cases()
        from app.dialogs.load_case_dialog import LoadCaseManagerDialog
        dialog = LoadCaseManagerDialog(self.model, self)
        dialog.exec()

    def on_define_load_combos(self):
        if not self.model: return
        from app.dialogs.load_combo_dialog import LoadComboManagerDialog
        dialog = LoadComboManagerDialog(self.model, self)
        dialog.exec()

    def on_run_analysis_dialog(self):
        """Opens the setup dialog."""
        if not self.model: return

        dlg = AnalysisDialog(self.model, self)
                                                             
        dlg.signal_run_analysis.connect(self.start_analysis_sequence)
        dlg.exec()

    def start_analysis_sequence(self, case_name, show_log=True):

        if not hasattr(self.model, 'file_path') or not self.model.file_path:
            QMessageBox.warning(self, "Save Required", "Please save the model file before running analysis.")
            self.on_save_model()
                                                   
            if not self.model.file_path:
                return

        print(f"Main: Starting analysis for case '{case_name}'...")

        self.set_interface_state(False)
        self.status.showMessage(f"Running Analysis: {case_name}... Please Wait.")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        self.update_yield_lines()

        if self._tributary_generator.is_busy():
            self.status.showMessage(f"Recalculating slab loads before running '{case_name}'...")
            self._pending_analysis_args = (case_name, show_log)
            self._tributary_generator.signal_all_loads_ready.connect(
                self._continue_analysis_after_loads, Qt.ConnectionType.UniqueConnection
            )
            return

        self._proceed_with_analysis(case_name, show_log)

    def _continue_analysis_after_loads(self):
        """Fired once TributaryLoadGenerator finishes any in-flight slab load computation."""
        try:
            self._tributary_generator.signal_all_loads_ready.disconnect(self._continue_analysis_after_loads)
        except TypeError:
            pass
        case_name, show_log = self._pending_analysis_args
        self._proceed_with_analysis(case_name, show_log)

    def _proceed_with_analysis(self, case_name, show_log=True):
        """Actual save + solver launch. Only called once slab loads are guaranteed complete."""
        self.solver_input_path = self.model.file_path

        c_type = "Linear Static"
        if case_name == "Run All Cases & Combinations":
            c_type = "Batch Run"
        elif case_name in self.model.load_cases:
            c_type = self.model.load_cases[case_name].case_type

        self.last_run_mode = c_type

        base_name = os.path.splitext(self.solver_input_path)[0]

        if c_type == "Modal":
            self.solver_output_path = f"{base_name}_MODAL_results.json"
        elif c_type == "Batch Run":
                                                                                                       
            if hasattr(self.model, 'load_combos') and self.model.load_combos:
                first_combo = list(self.model.load_combos.keys())[0]
                if os.path.exists(f"{base_name}_{first_combo} (Max)_results.json"):
                    self.solver_output_path = f"{base_name}_{first_combo} (Max)_results.json"
                else:
                    self.solver_output_path = f"{base_name}_{first_combo}_results.json"
            else:
                first_case = list(self.model.load_cases.keys())[0] if self.model.load_cases else "DEAD"
                self.solver_output_path = f"{base_name}_{first_case}_results.json"
        else:
            self.solver_output_path = f"{base_name}_{case_name}_results.json"

        try:
            self.model.save_to_file(self.solver_input_path)
            print(f"Model saved to {self.solver_input_path}")
        except Exception as e:
            self.finish_analysis_sequence(False, f"Could not save input file: {e}")
            return

        self.worker = SolverWorker(
            self.solver_input_path,
            self.solver_output_path,
            case_type=c_type,
            case_name=case_name
        )
        self.worker.signal_finished.connect(self.finish_analysis_sequence)

        self._progress_dialog = AnalysisProgressDialog(c_type, case_name, parent=self)
        self.worker.signal_progress.connect(self._progress_dialog.update_stage)
        if show_log:
            self._progress_dialog.setProperty("_ghost_animated", True)
            self._progress_dialog.show()

        self.worker.start()

    def finish_analysis_sequence(self, success, message):
        """Called when the Solver Thread finishes."""
        QApplication.restoreOverrideCursor()

        if hasattr(self, '_progress_timer'):
            self._progress_timer.stop()
        if hasattr(self, '_progress_dialog'):
            self._progress_dialog.finish(success)
        
        if success:
            self.status.showMessage("Analysis Complete.")
            self.load_analysis_results()   

            import glob, os
            base_name = os.path.splitext(self.solver_input_path)[0]
            if getattr(self, 'last_run_mode', '') == "Batch Run":
                self.model.valid_result_paths = glob.glob(f"{base_name}_*_results.json")
            else:
                self.model.valid_result_paths = [self.solver_output_path]

        else:
            self.set_interface_state(True) 
            QMessageBox.critical(self, "Analysis Failed", message)

    def _run_buckling_analysis(self, case_name: str, case_obj):
        """
        Dedicated dispatcher for Buckling analysis.
        Buckling requires a prior Linear Static run — it reads element forces
        from _results.json and transformation matrices from _matrices.json.
        """
        import json
        from PyQt6.QtCore import QThread, pyqtSignal as _Signal

        base_name      = os.path.splitext(self.model.file_path)[0]
        input_path     = self.model.file_path
        
        applied_load = case_obj.loads[0][0] if (hasattr(case_obj, 'loads') and case_obj.loads) else "DEAD"
        
        static_results = f"{base_name}_{applied_load}_results.json"
        matrices_path  = f"{base_name}_{applied_load}_matrices.json"
        
        buckling_out   = f"{base_name}_{case_name}_results.json"

        missing = []
        if not os.path.exists(static_results):
            missing.append(f"• Linear Static results:  {os.path.basename(static_results)}")
        if not os.path.exists(matrices_path):
            missing.append(f"• Stiffness matrices:     {os.path.basename(matrices_path)}")

        if missing:
            QMessageBox.warning(
                self,
                "Static Analysis Required",
                "Buckling analysis needs element forces from a prior Linear Static run.\n\n"
                "The following files are missing:\n"
                + "\n".join(missing)
                + "\n\nPlease run the Linear Static (DEAD) case first, then re-run Buckling."
            )
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.set_interface_state(False)
        self.status.showMessage(f"Running Buckling Analysis: {case_name}... Please Wait.")

        class _BucklingThread(QThread):
            finished = _Signal(bool, str)
            signal_progress = _Signal(str, int)

            def __init__(self, in_path, out_path, res_path, mat_path, c_name):
                super().__init__()
                self._in     = in_path
                self._out    = out_path
                self._res    = res_path
                self._mat    = mat_path
                self._cname  = c_name

            def run(self):
                try:
                    from core.solver.buckling.buckling_engine import run_buckling_analysis
                    ok = run_buckling_analysis(
                        self._in, self._out, self._res, self._mat, self._cname,
                        progress_callback=lambda msg, pct: self.signal_progress.emit(msg, pct)            
                    )
                    self.finished.emit(bool(ok), "" if ok else "Engine returned failure status.")
                except Exception as e:
                    self.finished.emit(False, str(e))

        self._buckling_thread = _BucklingThread(
            input_path, buckling_out, static_results, matrices_path, case_name
        )

        self._progress_dialog = AnalysisProgressDialog("Buckling Analysis", case_name, parent=self)
        self._buckling_thread.signal_progress.connect(self._progress_dialog.update_stage)
        self._progress_dialog.setProperty("_ghost_animated", True)
        self._progress_dialog.show()

        self._buckling_thread.finished.connect(
            lambda ok, msg: self._finish_buckling(ok, msg, buckling_out, case_name)
        )
        self._buckling_thread.start()

    def _finish_buckling(self, success: bool, message: str,
                         buckling_out: str, case_name: str):
        """Called when the buckling thread finishes."""
        import json
        QApplication.restoreOverrideCursor()
        self.set_interface_state(True)                                             

        if not success:
            QMessageBox.critical(
                self, "Buckling Analysis Failed",
                f"The buckling engine encountered an error:\n\n{message}"
            )
            return

        if not os.path.exists(buckling_out):
            QMessageBox.critical(self, "Buckling Analysis Failed",
                                 f"Output file not found:\n{buckling_out}")
            return

        try:
            with open(buckling_out, "r") as f:
                results = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Results Load Error",
                                 f"Could not parse buckling results:\n{e}")
            return

        if results.get("status") == "FAILED":
            err = results.get("error", {})
            QMessageBox.critical(
                self, "Buckling Analysis Failed",
                f"{err.get('title', 'Unknown Error')}\n\n{err.get('desc', '')}"
            )
            return

        self.status.showMessage(f"Buckling Analysis Complete — {case_name}")

        self.model.results = results
        self.model.has_results = True
        self.model.valid_result_paths = [buckling_out]

        self.canvas.view_deflected = False
        self.canvas.invalidate_deflection_cache()
        self.canvas.anim_factor = 1.0
        self.canvas.cache_scale_used = None
        if hasattr(self.canvas, 'animation_manager'):
            self.canvas.animation_manager.invalidate_prerender()

        self.btn_deform.setEnabled(True)
        self.action_display_forces.setEnabled(True)
        self.action_display_reactions.setEnabled(True)
        self.btn_deform.setChecked(True)
        self.canvas.view_deflected = True
        self.lock_model()

        if "mode_shapes" in results and "Mode 1" in results["mode_shapes"]:
            self.switch_modal_view("Mode 1")
        else:
            self.draw_both_canvases()

        if hasattr(self, '_progress_dialog'):
            self._progress_dialog.finish(success)

        if self.model.results.get("mode_shapes") and "Mode 1" in self.model.results["mode_shapes"]:
            self.switch_modal_view("Mode 1")

    def load_analysis_results(self):
        import json

        if not hasattr(self, 'solver_output_path') or not self.solver_output_path:
            QMessageBox.warning(self, "Error", "Result path is undefined.")
            return

        res_path = self.solver_output_path

        if not os.path.exists(res_path) and os.path.exists(res_path.replace("_results.json", " (Max)_results.json")):
            self.solver_output_path = res_path.replace("_results.json", " (Max)_results.json")
            res_path = self.solver_output_path
        
        if not os.path.exists(res_path):
            QMessageBox.warning(self, "Error", f"Result file not found at:\n{res_path}")
            return

        try:
            with open(res_path, 'r') as f:
                data = json.load(f)
            
            if data.get("status") == "FAILED":
                err_info = data.get("error", {})
                msg = f"Analysis Failed: {err_info.get('title', 'Unknown Error')}\n{err_info.get('desc', '')}"
                QMessageBox.critical(self, "Analysis Failed", msg)
                self.unlock_model() 
                return

            self.model.results = data
            if "displacements" in data:
                self.model.results["_base_displacements"] = data["displacements"].copy()
            self.model.has_results = True
            self.canvas.view_deflected = False
            self.canvas.invalidate_deflection_cache()
            self.canvas.anim_factor = 1.0
            self.canvas.cache_scale_used = None

            if hasattr(self.canvas, 'animation_manager'):
                self.canvas.animation_manager.invalidate_prerender()
            if hasattr(self.canvas, 'invalidate_deflection_cache'):
                self.canvas.invalidate_deflection_cache()

            is_ltha = (data.get("info", {}).get("type") == "Linear Time History Analysis"
                       and "history_path" in data
                       and os.path.exists(data["history_path"]))
            if is_ltha:
                dt = data["info"].get("dt", 0.01)
                accel = data.get("accel_history", None)
                self.canvas.load_ltha_history(data["history_path"], dt, accel=accel)

                envelope = data.get("displacements", {})
                max_disp = max(
                    (v[0]**2 + v[1]**2 + v[2]**2)**0.5
                    for v in envelope.values()
                ) if envelope else 0.0
                nodes = list(self.model.nodes.values())
                if nodes and max_disp > 1e-9:
                    dx = max(n.x for n in nodes) - min(n.x for n in nodes)
                    dy = max(n.y for n in nodes) - min(n.y for n in nodes)
                    dz = max(n.z for n in nodes) - min(n.z for n in nodes)
                    diag = (dx**2 + dy**2 + dz**2)**0.5
                    auto_scale = (diag * 0.05 / max_disp) if diag > 1e-6 else (2.0 / max_disp)
                else:
                    auto_scale = 2.0
                self.canvas.auto_deflection_scale  = auto_scale
                self.canvas.deflection_scale       = auto_scale
                self.canvas2.auto_deflection_scale = auto_scale
                self.canvas2.deflection_scale      = auto_scale

                self.canvas.animation_manager.enable_ltha_mode(self.canvas.ltha_n_steps, dt)
                try:
                    self.canvas.animation_manager.signal_ltha_frame_update.disconnect(self.canvas._on_ltha_frame)
                except Exception:
                    pass
                self.canvas.animation_manager.signal_ltha_frame_update.connect(self.canvas._on_ltha_frame)
                try:
                    self.canvas.animation_manager.signal_ltha_frame_update.disconnect(self._on_ltha_frame_tick)
                except Exception:
                    pass
                self.canvas.animation_manager.signal_ltha_frame_update.connect(self._on_ltha_frame_tick)
                print(f"[Main] LTHA mode ready: {self.canvas.ltha_n_steps} steps, dt={dt}s")
            else:
                if hasattr(self.canvas, 'clear_ltha_history'):
                    self.canvas.clear_ltha_history()
                if hasattr(self.canvas, 'animation_manager'):
                    self.canvas.animation_manager.disable_ltha_mode()

            self.btn_deform.setEnabled(True)
            self.action_display_forces.setEnabled(True)
            self.action_display_reactions.setEnabled(True)
            self.btn_deform.setChecked(True)                                
            self.canvas.view_deflected = True
            
            self.lock_model()
            info_type = data.get("info", {}).get("type", "")
            
            if info_type in ["Modal Analysis", "Buckling Analysis"]:
                                                                                   
                if "mode_shapes" in data and "Mode 1" in data["mode_shapes"]:
                    self.switch_modal_view("Mode 1")
                else:
                    self.draw_both_canvases()
                    
            elif info_type == "Linear Time History Analysis":
                                             
                self.switch_modal_view("LTHA_LIVE")
                
            else:
                                                                           
                self.switch_modal_view("MAIN_RESULT")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load results:\n{e}")
            self.canvas.view_deflected = False
            if getattr(self, 'canvas2_visible', False):
                self.canvas2.view_deflected = False
            self.unlock_model()

    def lock_model(self):
        self.is_locked = True
        self.set_interface_state(False)
                                                              
        self.btn_lock.setIcon(qta.icon('fa5s.lock', color="#c77873")) 
        self.btn_lock.setToolTip("Analysis Results Active. Click to Unlock and Edit.")

    def on_display_frame_forces(self):
        import glob
        from app.dialogs.display_forces_dialog import DisplayForcesDialog

        if not self.model or not getattr(self.model, 'file_path', None):
            return

        base_name = os.path.splitext(self.model.file_path)[0]

        result_files = getattr(self.model, 'valid_result_paths', [])
        if not result_files:
            result_files = glob.glob(f"{base_name}_*_results.json")
        available_cases = []
        for path in sorted(result_files):
            fname = os.path.basename(path)
            prefix = os.path.basename(base_name) + "_"
            suffix = fname[len(prefix):].replace("_results.json", "")
            if suffix:
                available_cases.append(suffix)

        self.forces_dialog = DisplayForcesDialog(
            self.model, self,
            available_cases=available_cases,
            base_path=base_name,
        )
        self.forces_dialog.apply_forces_signal.connect(self.apply_force_diagrams_from_dialog)
        self.forces_dialog.show()

    def on_display_joint_reactions(self):
        import glob
        import os
        
        if not self.model or not getattr(self.model, 'file_path', None):
            self.statusBar().showMessage("No results available. Please run analysis first.")
            return

        base_name = os.path.splitext(self.model.file_path)[0]
        
        result_files = getattr(self.model, 'valid_result_paths', [])
        if not result_files:
            result_files = glob.glob(f"{base_name}_*_results.json")

        if not result_files:
            self.statusBar().showMessage("No result files found. Please run analysis first.")
            return

        available_cases = []
        for path in sorted(result_files):
            fname = os.path.basename(path)
            prefix = os.path.basename(base_name) + "_"
            suffix = fname[len(prefix):].replace("_results.json", "")
            if suffix:
                                                                                            
                if suffix in self.model.load_cases:
                    c_type = getattr(self.model.load_cases[suffix], 'case_type', 'Linear Static')
                    if c_type in ["Modal", "Buckling", "LTHA"]:
                        continue
                available_cases.append(suffix)

        if not available_cases:
            return

        self.reactions_dialog = DisplayReactionsDialog(available_cases, base_name, self)
        self.reactions_dialog.apply_reactions_signal.connect(self.apply_reactions_from_dialog)
        self.reactions_dialog.show()

    def apply_reactions_from_dialog(self, settings):
        import json
        import os
        
        if not self.model or not self.active_canvas:
            return

        load_case = settings['load_case']
        base_path = settings.get('base_path', '')
        display_type = settings.get('display_type', 'arrows')

        res_path = f"{base_path}_{load_case}_results.json"

        if not os.path.exists(res_path):
            self.statusBar().showMessage(f"No results on disk for '{load_case}'. Run that case first.")
            return

        with open(res_path, 'r') as f:
            case_data = json.load(f)

        self.model.results = case_data
        self.model.has_results = True

        if hasattr(self.model, 'load_combos') and load_case in self.model.load_combos:
            combo_reactions = {}
            for base_case, scale in self.model.load_combos[load_case].cases:
                bc_path = f"{base_path}_{base_case}_results.json"
                if os.path.exists(bc_path):
                    with open(bc_path, 'r') as bcf:
                        bc_data = json.load(bcf)
                        for nid, dofs in bc_data.get("reactions", {}).items():
                            if nid not in combo_reactions:
                                combo_reactions[nid] = [0.0] * 6
                            for i in range(6):
                                combo_reactions[nid][i] += dofs[i] * scale
            case_data["reactions"] = combo_reactions

        if display_type == 'tabulated':
            from app.dialogs.analysis_results_dialog import AnalysisResultsDialog
            
            sel_nodes = [str(nid) for nid in self.selected_node_ids] if self.selected_node_ids else None
            
            dlg = AnalysisResultsDialog(self.model, case_data, self, selected_node_ids=sel_nodes)
        
            if hasattr(dlg, 'tab_reactions'):
                idx = dlg.tabs.indexOf(dlg.tab_reactions)
                if idx >= 0:
                    dlg.tabs.setCurrentIndex(idx)
            dlg.exec()
            return

        restrained = set(case_data.get("restrained_nodes", []))
        reaction_data = {}
        for nid, dofs in case_data.get("reactions", {}).items():
            if restrained and nid not in restrained:
                continue
            if not restrained and max(abs(v) for v in dofs) < 1e-6:
                continue
            reaction_data[nid] = dofs

        sign_conv = settings.get('sign_convention', 'ground_on_structure')

        success = self.active_canvas.show_reaction_diagram(self.model, reaction_data, sign_convention=sign_conv)

        if success:
            self.statusBar().showMessage(f"[{load_case}]  Joint Reactions  —  {len(reaction_data)} joint(s)")
        else:
            self.statusBar().showMessage("No reaction data found for this case.")
            
    def apply_force_diagrams_from_dialog(self, settings):
        """
        Receives the signal from DisplayForcesDialog.
        Loads the selected case's result file from disk and pushes it to the GPU.
        """
        import json
        if not self.model or not self.canvas:
            return

        load_case  = settings['load_case']
        base_path  = settings.get('base_path', '')

        res_path = f"{base_path}_{load_case}_results.json"
        mat_path = f"{base_path}_{load_case}_matrices.json"

        if not os.path.exists(res_path):
            self.statusBar().showMessage(
                f"No results on disk for '{load_case}'. Run that case first."
            )
            return

        with open(res_path, 'r') as f:
            case_data = json.load(f)

        self.model.results = case_data
        self.model.has_results = True

        displacements = case_data.get("displacements", {})
        matrices_path = mat_path if os.path.exists(mat_path) else None

        success = self.active_canvas.show_force_diagram(
            model=self.model,
            component=settings['component'],
            scale_factor=settings['scale_factor'],
            displacements=displacements,
            matrices_path=matrices_path,
            show_labels=settings.get('show_labels', False),
            show_labels_mode=settings.get('show_labels_mode', 'all'),
            text_size=settings.get('text_size', None),
            selected_ids=self.selected_ids
        )

        if success:
            if not hasattr(self, '_last_force_diagram_settings'):
                self._last_force_diagram_settings = {}
            self._last_force_diagram_settings[self.active_canvas] = settings
                                          
        else:
            self.statusBar().showMessage("No diagram generated. Check that analysis results exist.")

    def unlock_model(self):
                                                       
        if hasattr(self.model, 'has_results') and self.model.has_results:
            reply = QMessageBox.question(
                self, "Discard Results?", 
                "Unlocking the model will delete current analysis results.\nDo you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        self.btn_deform.setEnabled(False)
        self.btn_deform.setChecked(False)     
        self.action_display_forces.setEnabled(False)  
        self.action_display_reactions.setEnabled(False)                 
                                                             
        if hasattr(self.canvas, 'clear_force_diagrams'):
            self.canvas.clear_force_diagrams()
        if hasattr(self.active_canvas, 'clear_reaction_diagram'):
            self.active_canvas.clear_reaction_diagram()
        self.canvas.view_deflected = False  

        self.view_shadow = True
        self.shadow_color = (0.7, 0.7, 0.7, 0.3)

        self.is_locked = False
        self.model.has_results = False
        self.model.results = None

        self.canvas.view_deflected = False
        self.canvas.anim_factor = 0.0
        self.canvas.invalidate_animation_cache()
        if hasattr(self.canvas, 'animation_manager') and self.canvas.animation_manager:
            self.canvas.animation_manager.stop_animation()
        if hasattr(self.canvas, 'clear_ltha_history'):
            self.canvas.clear_ltha_history()
        
        if hasattr(self, 'sound_effect') and self.sound_effect.isPlaying():
            self.sound_effect.stop()

        self.canvas2.view_deflected = False
        self.canvas2.anim_factor = 0.0
        self.canvas2.invalidate_animation_cache()
        if hasattr(self.canvas2, 'animation_manager') and self.canvas2.animation_manager:
            self.canvas2.animation_manager.stop_animation()
        if hasattr(self.canvas2, 'clear_ltha_history'):
            self.canvas2.clear_ltha_history()

        if hasattr(self, "deformed_shape_dialog") and self.deformed_shape_dialog:
            self.deformed_shape_dialog.force_exit_animation_mode()

        self.canvas._force_draw_model(self.model)
        if getattr(self, 'canvas2_visible', False):
            self.canvas2._force_draw_model(self.model)

        self.set_interface_state(True)
        
        self.btn_lock.setIcon(qta.icon('fa5s.unlock', color='#6c757d'))
        self.btn_lock.setText("") 
        self.btn_lock.setToolTip("Model is editable.")
                                          
        self.status.showMessage("Results discarded. Model unlocked for editing.")
        
        self.draw_both_canvases()

    def show_node_results(self, node_id):
        """Displays the small popup box with deformations."""
        if not self.model.results: return
        
        disp = self.model.results.get("displacements", {}).get(str(node_id))
        
        if not disp:
            QMessageBox.warning(self, "No Data", f"No results found for Node {node_id}")
            return
            
        ux, uy, uz, rx, ry, rz = disp
        
        msg = f"""
        <b>JOINT {node_id} RESULTS</b>
        <hr>
        <b>Translations [m]:</b><br>
        Ux: {ux:.6f}<br>
        Uy: {uy:.6f}<br>
        Uz: {uz:.6f}<br>
        <br>
        <b>Rotations [rad]:</b><br>
        Rx: {rx:.6f}<br>
        Ry: {ry:.6f}<br>
        Rz: {rz:.6f}
        """
        
        box = QMessageBox(self)
        box.setWindowTitle(f"Joint {node_id} Displacements")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(msg)
        box.exec()

    def _get_node_under_mouse(self):
        """Helper to find the node ID under the mouse cursor."""
                                                                         
        if len(self.selected_node_ids) == 1:
            return self.selected_node_ids[0]
        
        return None

    def on_lock_clicked(self):
        """Handles the toolbar lock button click."""
        if getattr(self, 'is_locked', False):
                                                                     
            self.unlock_model()
        else:
                                                                  
            self.status.showMessage("Model is already editable. Run Analysis to lock.")

    def update_window_title(self):
        """Updates window title to show currently active filename and version."""
                                                              
        base_title = "Open//Structures v0.7.82" 
        
        if self.model and getattr(self.model, 'file_path', None):
            short_name = os.path.basename(self.model.file_path)
            self.setWindowTitle(f"{base_title} - [{short_name}]")
        else:
            self.setWindowTitle(base_title)
    
    def add_command(self, command):
        """
        Pushes a command to the stack. 
        This automatically runs redo() once, applying the change.
        """
        if self.model is None: return
        
        if getattr(self, 'is_locked', False):
            self.status.showMessage("⚠️ Cannot modify model while locked. Unlock first.")
            return

        self.undo_stack.push(command)

    def on_view_deformed_shape(self):
        """Opens the Deformed Shape Control Dialog."""
        if not self.model or not self.model.has_results:
            QMessageBox.warning(self, "No Results", "Please run the analysis first.")
            return

        cvs = self.active_canvas
        current_spd = 1.0
        mgr = cvs.animation_manager if hasattr(cvs, 'animation_manager') else None
        if mgr:
            current_spd = mgr.speed_factor

        is_ltha = getattr(cvs, 'ltha_mode', False)
        n_steps = getattr(cvs, 'ltha_n_steps', 0)
        ltha_dt = getattr(cvs, 'ltha_dt', 0.01)

        if hasattr(self, '_deformed_dlg') and self._deformed_dlg is not None:
            if self._deformed_dlg.isVisible():
                self._deformed_dlg.raise_()
                self._deformed_dlg.activateWindow()
                return
            else:
                self._deformed_dlg.deleteLater()

        self._deformed_dlg = DeformedShapeDialog(
            parent=self,
            current_scale=cvs.deflection_scale,
            auto_scale=getattr(cvs, 'auto_deflection_scale', 1.0),
            is_active=cvs.view_deflected,
            show_shadow=cvs.view_shadow,
            shadow_color=cvs.shadow_color,
            is_animating=mgr.is_running if mgr else False,
            current_speed=current_spd,
            ltha_mode=is_ltha,
            ltha_n_steps=n_steps,
            ltha_dt=ltha_dt,
            contour_enabled=getattr(cvs, 'contour_active', False),
            contour_component=getattr(cvs, 'contour_component', "Resultant"),
            contour_range_auto=getattr(cvs, 'contour_range_auto', True),
            contour_min=getattr(cvs, 'contour_min', 0.0),
            contour_max=getattr(cvs, 'contour_max', 1.0),
            contour_absolute=getattr(cvs, 'contour_absolute', False)
        )

        self._deformed_dlg.setWindowModality(Qt.WindowModality.NonModal)
        self._deformed_dlg.show()

    def apply_deformed_shape(self, is_visible, scale_factor, show_shadow, shadow_color,
                              contour_enabled=False, contour_component="Resultant",
                              contour_range_auto=True, contour_min=0.0, contour_max=1.0,
                              contour_absolute=False):
        """Callback from the Dialog to update the active canvas."""
        cvs = self.active_canvas
        cvs.view_deflected = is_visible

        if is_visible:
            mgr = getattr(cvs, "animation_manager", None)
            if not (mgr and mgr.is_running):
                                                                                   
                cvs.anim_factor = 1.0

        if cvs.deflection_scale != scale_factor:
            cvs.deflection_scale = scale_factor
            if hasattr(cvs, 'animation_manager'):
                cvs.animation_manager.invalidate_prerender()

        cvs.view_shadow = show_shadow
        cvs.shadow_color = shadow_color

        cvs.contour_active = contour_enabled and is_visible
        cvs.contour_component = contour_component
                                                                       
        cvs.contour_range_auto = contour_range_auto
        cvs.contour_min = contour_min
        cvs.contour_max = contour_max
        cvs.contour_absolute = contour_absolute

        self.draw_both_canvases()

        state_msg = "ON" if is_visible else "OFF"
        contour_msg = f", Contour: {contour_component}" if cvs.contour_active else ""
        self.status.showMessage(f"Deformed Shape: {state_msg} (Scale: {scale_factor}x{contour_msg})")

    def toggle_animation(self, start, play_sound):
        """Called by DeformedShapeDialog."""
        is_ltha = getattr(self.canvas, 'ltha_mode', False)

        if start:
            if is_ltha:
                                                                  
                self.canvas.animation_manager.start_animation()
            else:
                                                                       
                progress = QProgressDialog("Pre-rendering animation frames...\nPlease wait...",
                                          None, 0, 100, self)
                progress.setWindowTitle("Loading Animation")
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setMinimumDuration(0)
                progress.setValue(0)

                def update_progress(percent):
                    progress.setValue(percent)
                    QApplication.processEvents()

                self.canvas.animation_manager.start_animation(update_progress)
                progress.close()

                if play_sound and self.sound_effect.source().isValid():
                    self.sound_effect.play()

            self.status.showMessage("Animation Running...")
        else:   
            self.canvas.animation_manager.stop_animation()
            if not is_ltha:
                self.canvas.anim_factor = 1.0
                self.canvas.invalidate_animation_cache()
                self.canvas._force_draw_model(
                    self.model,
                    self.selected_ids,
                    self.selected_node_ids
                )
            if self.sound_effect.isPlaying():
                self.sound_effect.stop()
            self.status.showMessage("Animation Paused." if is_ltha else "Animation Stopped.")

    def _on_ltha_frame_tick(self, t_index):
        """
        Called every animation tick in LTHA mode.
        Keeps the scrubber slider and time label in sync with playback.
        """
        if hasattr(self, '_deformed_dlg') and self._deformed_dlg is not None:
            self._deformed_dlg.update_scrubber(t_index)

    def set_animation_speed(self, speed_factor):
        """Called by speed toggle buttons to change animation speed live."""
        if hasattr(self.canvas, 'animation_manager'):
            self.canvas.animation_manager.set_speed(speed_factor)

    def prerender_ltha_animation(self, t_start_s, t_end_s, done_callback=None):
        """
        Pre-renders LTHA geometry frames for the given time window [t_start_s, t_end_s].
        After pre-rendering, playback loops only within that window.

        Args:
            t_start_s   (float): Window start in seconds.
            t_end_s     (float): Window end in seconds.
            done_callback: Called with no args when done (or cancelled).
        """
        mgr = self.canvas.animation_manager
        if not mgr.ltha_mode or not self.canvas.ltha_history:
            if done_callback: done_callback()
            return

        dt  = self.canvas.ltha_dt
        n   = self.canvas.ltha_n_steps

        i_start = max(0,     int(round(t_start_s / dt)))
        i_end   = min(n - 1, int(round(t_end_s   / dt)))

        if i_start >= i_end:
            if done_callback: done_callback()
            return

        n_frames = i_end - i_start + 1

        progress = QProgressDialog(
            f"Pre-rendering frames {i_start}–{i_end}  ({n_frames} steps)...",
            "Cancel", 0, n_frames, self)
        progress.setWindowTitle("Pre-Animate")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        self.canvas.view_deflected = True
        self.canvas.prerendered_geometry_frames.clear()

        for idx, t in enumerate(range(i_start, i_end + 1)):
            snapshot = {nid: hist[t].tolist()
                        for nid, hist in self.canvas.ltha_history.items()}
            self.canvas.current_model.results["displacements"] = snapshot
            
            self.canvas.deflection_cache.clear()

            self.canvas.prerendered_geometry_frames.append(
                self.canvas._calculate_frame_geometry(anim_factor=1.0)
            )

            progress.setValue(idx + 1)
            QApplication.processEvents()

            if progress.wasCanceled():
                self.canvas.prerendered_geometry_frames.clear()
                self.canvas.is_animation_cached = False
                progress.close()
                if done_callback: done_callback()
                return

        self.canvas.is_animation_cached = True

        mgr.ltha_prerender_start = i_start
        mgr.ltha_prerender_end   = i_end
        mgr.ltha_current_step    = i_start

        self.canvas.ltha_highlight = (t_start_s, t_end_s)
        self.canvas._invalidate_accel_pixmap()                                                

        progress.close()
        self.status.showMessage(
            f"Pre-animate complete: {n_frames} frames  [{t_start_s:.1f}s – {t_end_s:.1f}s]")

        if done_callback: done_callback()

    def on_define_mass_source(self):
        if not self.model: return
        dialog = MassSourceManagerDialog(self.model, self)
        dialog.exec()

    def on_show_modal_results(self):
        if not self.model or not self.model.results:
            QMessageBox.warning(self, "No Results", "Please run an Analysis first.")  
            return

        filter_node_ids = [str(nid) for nid in self.selected_node_ids] if self.selected_node_ids else None

        from app.dialogs.analysis_results_dialog import AnalysisResultsDialog 
        dlg = AnalysisResultsDialog(self.model, self.model.results, self, selected_node_ids=filter_node_ids)
        dlg.exec()

    def switch_modal_view(self, mode_key):
        if not self.model or not self.model.results: return
        
        target_data = {}
        info_type = self.model.results.get("info", {}).get("type", "")

        if mode_key == "MAIN_RESULT" or mode_key == "LTHA_LIVE":
                                                                                     
            target_data = self.model.results.get("_base_displacements", self.model.results.get("displacements", {}))
            
            if mode_key == "MAIN_RESULT":
                self.status.showMessage(f"Displaying: {info_type}")
            else:
                self.status.showMessage("Displaying: LTHA Live Playback")

        else:
            shapes = self.model.results.get("mode_shapes", {})
            if mode_key in shapes:
                target_data = shapes[mode_key]
                self.status.showMessage(f"Displaying: {mode_key}")
            else:
                print(f"Warning: {mode_key} not found in results.")
                return

        self.model.results["displacements"] = target_data
        
        auto_scale = getattr(self.canvas, 'deflection_scale', 1.0)

        if mode_key != "LTHA_LIVE":
                                                                 
            max_disp = 0.0
            for vec in target_data.values():
                d = max(abs(v) for v in vec)                                             
                if d > max_disp: max_disp = d
                
            nodes = self.model.nodes.values()
            if nodes and max_disp > 1e-9:
                dx = max(n.x for n in nodes) - min(n.x for n in nodes)
                dy = max(n.y for n in nodes) - min(n.y for n in nodes)
                dz = max(n.z for n in nodes) - min(n.z for n in nodes)
                
                diag_length = (dx**2 + dy**2 + dz**2)**0.5
                
                if diag_length < 1e-6:
                                                                    
                    auto_scale = 2.0 / max_disp
                else:
                                                                                               
                    target_visual_size = diag_length * 0.05
                    auto_scale = target_visual_size / max_disp
            else:
                auto_scale = 2.0

            self.canvas.auto_deflection_scale = auto_scale
            self.canvas.deflection_scale = auto_scale
            self.canvas2.auto_deflection_scale = auto_scale
            self.canvas2.deflection_scale = auto_scale
        
        if not self.canvas.view_deflected:
            self.canvas.view_deflected = True
        self.canvas2.view_deflected = True
        
        self.canvas.anim_factor = 1.5
        self.canvas2.anim_factor = 1.5
            
        self.canvas.invalidate_deflection_cache()
        self.canvas2.invalidate_deflection_cache()
        
        if hasattr(self.canvas, 'animation_manager'):
            self.canvas.animation_manager.invalidate_prerender()
            
        self.draw_both_canvases()
        
        self.status.showMessage(f"{self.status.currentMessage()} (Auto-Scale: {auto_scale:.1f}x)")

    def closeEvent(self, event):
        """Intercepts the window close request to check for unsaved changes."""
        
        if not self.model:
            event.accept()
            return

        if not self.undo_stack.isClean():
            reply = QMessageBox.question(
                self, 
                "Unsaved Changes",
                "You have unsaved changes in your model.\nDo you want to save them before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save
            )

            if reply == QMessageBox.StandardButton.Save:
                                                                                            
                if self.on_save_model():
                    event.accept()
                else:
                    event.ignore() 
                    
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()                       
                
            else:         
                event.ignore()                        
        else:
                                                
            event.accept()

    def on_define_response_spectrum(self):
        if not self.model: return
        
        from app.dialogs.response_spectrum_manager import ResponseSpectrumManagerDialog
        
        dlg = ResponseSpectrumManagerDialog(self.model, self)
        dlg.exec()
        
        self.status.showMessage(f"Response Spectrum Definitions Updated.")

    def on_define_time_history_functions(self):
        if not self.model: return
        dlg = TimeHistoryManagerDialog(self.model, self)
        dlg.exec()
        self.status.showMessage("Time History Function Definitions Updated.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'user_widget'):
            self.user_widget.reposition()
        self._reposition_welcome_overlay()

    def clear_ltha_prerender(self):
        """Clears the LTHA pre-rendered window and returns to full history playback."""
        if hasattr(self, 'canvas') and self.canvas.animation_manager:
            mgr = self.canvas.animation_manager
            
            mgr.ltha_prerender_start = None
            mgr.ltha_prerender_end = None
            
            self.canvas.ltha_highlight = None
            self.canvas._invalidate_accel_pixmap()                                                   
            self.canvas.invalidate_animation_cache()
            self.canvas.update() 
            
            self.status.showMessage("Pre-animation cleared. Full time history ready.")

    def on_run_solid_analysis(self):
        if not self.model: return
        dlg = SolidAnalysisDialog(self)
        dlg.show()  

    def _on_model_changed(self, idx):
        """Called on every undo stack push/undo/redo — syncs loads and canvases."""
        if self.model:
            self.update_yield_lines()
            self.draw_both_canvases()

    def draw_both_canvases(self, sel_elems=None, sel_nodes=None, progress=None):
        """Draw the model on both canvases with consistent selection state."""
        if not self.model:
            return
        e = sel_elems if sel_elems is not None else self.selected_ids
        n = sel_nodes if sel_nodes is not None else self.selected_node_ids
        self.canvas.draw_model(self.model, e, n)
        if getattr(self, 'canvas2_visible', False):
            self.canvas2.draw_model(self.model, e, n)

        if hasattr(self, 'canvas') and self.canvas: 
            self.canvas.draw_model(self.model, progress=progress)
        if hasattr(self, 'canvas_2d') and self.canvas_2d: 
            self.canvas_2d.draw_model(self.model, progress=progress)

    def refresh_canvas(self):
        self.draw_both_canvases()

    def _toggle_terminal(self):
        self.terminal_panel.toggle()
        if self.terminal_panel.isVisible():
            total = self.splitter.height()
            self.splitter.setSizes([total - 220, 220])
        else:
            self.splitter.setSizes([self.splitter.height(), 0])

    def _on_cli_file_opened(self, new_model):
        """Called by TerminalPanel when the CLI 'open' command succeeds."""
        self._purge_results_and_visuals()                
        self.model = new_model
        self.undo_stack.clear()
        self.update_yield_lines()

        if new_model.graphics_settings:
            self.graphics_settings.update(new_model.graphics_settings)
            self.canvas.view_extruded         = self.graphics_settings.get('view_extruded', False)
            self.canvas.show_slabs            = self.graphics_settings.get('show_slabs', True)
            self.canvas.show_joints           = self.graphics_settings.get('show_joints', True)
            self.canvas.show_supports         = self.graphics_settings.get('show_supports', True)
            self.canvas.show_loads            = self.graphics_settings.get('show_loads', True)
            self.canvas.show_local_axes       = self.graphics_settings.get('show_local_axes', False)
            self.canvas.show_constraints      = self.graphics_settings.get('show_constraints', True)
            self.canvas.show_releases         = self.graphics_settings.get('show_releases', True)
            self.canvas.load_type_filter      = self.graphics_settings.get('load_type_filter', 'both')
            self.canvas.visible_load_patterns = self.graphics_settings.get('visible_load_patterns', [])
            self.update_graphics_settings(self.graphics_settings)

        if hasattr(new_model, 'saved_unit_system'):
            self.combo_units.blockSignals(True)
            self.combo_units.setCurrentText(new_model.saved_unit_system)
            self.combo_units.blockSignals(False)
            self.on_units_changed(0)

        self.draw_both_canvases()
        self.canvas.set_standard_view("3D")
        self.set_interface_state(True)
        self.update_window_title()
        self.status.showMessage(f"Loaded via terminal: {new_model.file_path}")

    def _on_cli_model_saved(self, model):
        """Called by TerminalPanel when the CLI 'save' command succeeds."""
        self.undo_stack.setClean()
        self.update_window_title()
        self.status.showMessage(f"Saved via terminal: {model.file_path}")

    def _toolbar_toggle_deform(self, checked):
        """Directly toggles the deformed shape on the active canvas without opening the dialog."""
        if not self.model or not self.model.has_results:
            return

        self.active_canvas.view_deflected = checked

        self.draw_both_canvases()

        state_msg = "ON" if checked else "OFF"
        self.status.showMessage(f"Deformed Shape: {state_msg} (Scale: {self.active_canvas.deflection_scale:.2f}x)")

    def _toggle_pan(self, checked):
        if checked:
                                           
            self.active_canvas.setCursor(Qt.CursorShape.OpenHandCursor)
            
            self.active_canvas.single_use_pan_active = True 
            self.status.showMessage("Pan Tool Active: Left-click and drag to move camera.")
            
            if getattr(self, 'draw_mode_active', False):
                self.on_draw_finished()
                if self.draw_dialog:
                    self.draw_dialog.hide()
        else:
                                           
            self.active_canvas.setCursor(Qt.CursorShape.ArrowCursor)
            self.active_canvas.single_use_pan_active = False
            self.status.showMessage("Ready")

    def on_assign_area_uniform_load(self):
        """Assign > Area > Uniform Load..."""
        if not self.model:
            return
            
        if not hasattr(self, '_area_uniform_load_dlg') or self._area_uniform_load_dlg is None:
            from app.dialogs.dlg_area_uniform_load import AreaUniformLoadDialog
            self._area_uniform_load_dlg = AreaUniformLoadDialog(self.model, parent=self)
                                                             
            self._area_uniform_load_dlg.finished.connect(lambda: setattr(self, '_area_uniform_load_dlg', None))
            
        self._area_uniform_load_dlg.show()
        self._area_uniform_load_dlg.raise_()
        self._area_uniform_load_dlg.activateWindow()
 
    def on_assign_area_gravity_load(self):
        """Assign > Area > Gravity Load..."""
        if not self.model:
            return
            
        if not hasattr(self, '_area_gravity_load_dlg') or self._area_gravity_load_dlg is None:
            from app.dialogs.dlg_area_gravity_load import AreaGravityLoadDialog
            self._area_gravity_load_dlg = AreaGravityLoadDialog(self.model, parent=self)
            self._area_gravity_load_dlg.finished.connect(lambda: setattr(self, '_area_gravity_load_dlg', None))
            
        self._area_gravity_load_dlg.show()
        self._area_gravity_load_dlg.raise_()
        self._area_gravity_load_dlg.activateWindow()

    def on_assign_area_mesh(self):
        """Triggered from Assign > Area > Automatic Area Mesh"""
        
        if not hasattr(self, '_area_mesh_dlg') or not self._area_mesh_dlg.isVisible():
            from app.dialogs.area_mesh_dialog import AreaMeshDialog
            self._area_mesh_dlg = AreaMeshDialog(self)
            
            self._area_mesh_dlg.signal_apply_mesh.connect(self._execute_area_mesh)
            
            self._area_mesh_dlg.show()
        else:
                                                              
            self._area_mesh_dlg.raise_()
            self._area_mesh_dlg.activateWindow()

    def _execute_area_mesh(self, params: dict):
        """Executes the mesh operation via the Undo Stack."""
        
        selected_ids = getattr(self.canvas, 'selected_area_ids', []) 
        
        if not selected_ids:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Selection Required", "Please select at least one Area Element to mesh.")
            return

        for aid in selected_ids:
            ae = getattr(self.model, 'area_elements', {}).get(aid)
            if ae and hasattr(ae.section, 'modeling_type') and ae.section.modeling_type == "Code Based (TS 500)":
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Invalid Selection", "You cannot mesh Code Based (TS 500) slabs because they do not have internal FEM nodes.\n\nPlease deselect them and try again.")
                return

        if params["mode"] == "divisions" and params["n"] == 1 and params["m"] == 1:
            return

        from app.commands import CmdMeshAreaElements
        
        cmd = CmdMeshAreaElements(self.model, self, list(selected_ids), params)
        self.add_command(cmd)

        if hasattr(self.canvas, 'clear_selection'):
            self.canvas.clear_selection()
        else:
            self.canvas.selected_area_ids.clear()
            self.canvas.selected_node_ids.clear()
            self.canvas.selected_element_ids.clear()
            
        self.status.showMessage("Area mesh applied.", 3000)
                      
    def _apply_canvas_view_settings(self, gs):
        """Applies project-level view toggles from a settings dict to the canvas."""
        self.canvas.view_extruded        = gs.get('view_extruded', False)

        if self.canvas.view_extruded:
            self.canvas.force_diagram_data = None
            self.canvas.force_labels = []

        self.canvas.show_slabs           = gs.get('show_slabs', True)
        self.canvas.show_joints          = gs.get('show_joints', True)
        self.canvas.show_supports        = gs.get('show_supports', True)
        self.canvas.show_loads           = gs.get('show_loads', True)
        self.canvas.show_local_axes      = gs.get('show_local_axes', False)
        self.canvas.show_constraints     = gs.get('show_constraints', True)
        self.canvas.show_releases        = gs.get('show_releases', True)
        self.canvas.load_type_filter     = gs.get('load_type_filter', 'both')
        self.canvas.visible_load_patterns = gs.get('visible_load_patterns', [])
        self.canvas.show_tributary_loads = gs.get('tributary_loads', False)
        self.canvas.show_tributary_heatmap = gs.get('tributary_heatmap', False)
        self.canvas.show_tributary_mesh    = gs.get('tributary_mesh', False)
        
    def _update_active_border(self):
                                               
        if self.canvas2_visible:
                                                         
            active_style   = "QFrame { border: 1px solid #0078d7; }"
            inactive_style = "QFrame { border: 1px solid #cccccc; }"
            self.canvas_frame1.setStyleSheet(active_style if self.active_canvas == self.canvas else inactive_style)
            self.canvas_frame2.setStyleSheet(active_style if self.active_canvas == self.canvas2 else inactive_style)
        else:
                                                                
            no_border_style = "QFrame { border: none; }"
            self.canvas_frame1.setStyleSheet(no_border_style)
            self.canvas_frame2.setStyleSheet(no_border_style)

    def _set_active_canvas(self, canvas):
        self.active_canvas = canvas
        self._update_active_border()
                                                                                  
        vm = canvas._view_mode
        self.btn_xy.setChecked(vm == "XY")
        self.btn_xz.setChecked(vm == "XZ")
        self.btn_yz.setChecked(vm == "YZ")
        
        if getattr(self, 'cross_brace_mode_active', False) and self.cross_brace_dialog and self.cross_brace_dialog.isVisible():
            self.cross_brace_dialog.update_plane_status(canvas.active_view_plane)
            
        dlg = getattr(self, '_view_options_dialog', None)
        if dlg and dlg.isVisible():
            dlg._update_target_label()

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj in (self.canvas, self.canvas2):
            if event.type() in (QEvent.Type.MouseButtonPress,
                                QEvent.Type.MouseButtonRelease,
                                QEvent.Type.MouseMove,
                                QEvent.Type.Wheel):
                if obj != self.active_canvas:
                    if event.type() == QEvent.Type.MouseButtonPress:
                        self._set_active_canvas(obj)
                                                                               
                        return False
                                                                                     
                    return True
        return super().eventFilter(obj, event)

    def _toggle_dual_view(self, checked):
        self.canvas2_visible = checked
        self.canvas_frame2.setVisible(checked)
        if checked:
            def init_canvas2():
                                                                                 
                self.canvas2.display_config = self.canvas.display_config.copy()
                self.canvas2.view_extruded = self.canvas.view_extruded
                self.canvas2.show_slabs = self.canvas.show_slabs
                self.canvas2.show_grid = self.canvas.show_grid
                self.canvas2.show_joints = self.canvas.show_joints
                self.canvas2.show_supports = self.canvas.show_supports
                self.canvas2.show_loads = self.canvas.show_loads
                self.canvas2.show_local_axes = self.canvas.show_local_axes
                self.canvas2.show_constraints = self.canvas.show_constraints
                self.canvas2.show_releases = self.canvas.show_releases
                self.canvas2.load_type_filter = self.canvas.load_type_filter
                self.canvas2.visible_load_patterns = self.canvas.visible_load_patterns
                
                bg_tuple = self.graphics_settings.get("background_color", (1.0, 1.0, 1.0, 1.0))
                c = QColor()
                c.setRgbF(bg_tuple[0], bg_tuple[1], bg_tuple[2], bg_tuple[3])
                self.canvas2.setBackgroundColor(c)

                self.canvas2.makeCurrent()
                if not self.canvas2.vbo_manager.is_initialized:
                    self.canvas2.vbo_manager.init_gl()

                if self.model:
                    self.canvas2.draw_model(self.model,
                                            list(self.selected_ids),
                                            list(self.selected_node_ids))
                
                self.canvas2.set_standard_view("ISO")
                self.update_linked_planes()                           

            QTimer.singleShot(100, init_canvas2)
                                                                            
            self._update_active_border()
        else:
            self._set_active_canvas(self.canvas)
            self.update_linked_planes()
            
    def on_check_updates(self):
        """Opens the Check for Updates dialog."""
        if not hasattr(self, 'update_dlg') or not self.update_dlg.isVisible():
            self.update_dlg = UpdateDialog(self)
            self.update_dlg.show()
        else:
            self.update_dlg.raise_()

    def update_linked_planes(self):
        """
        Synchronize helper planes between dual viewports.
        """
        if not self.canvas2_visible:
            self.canvas.clear_linked_view_plane()
            self.canvas2.clear_linked_view_plane()
            return

        c1_is_3d = (self.canvas._view_mode in ["3D", "ISO"])
        c2_is_3d = (self.canvas2._view_mode in ["3D", "ISO"])

        if c1_is_3d and not c2_is_3d:
            self.canvas.update_linked_view_plane(self.canvas2.active_view_plane)
            self.canvas2.clear_linked_view_plane()
        elif c2_is_3d and not c1_is_3d:
            self.canvas2.update_linked_view_plane(self.canvas.active_view_plane)
            self.canvas.clear_linked_view_plane()
        else:
            self.canvas.clear_linked_view_plane()
            self.canvas2.clear_linked_view_plane()
            
def main():
    if sys.platform == 'win32':
        myappid = 'metu.civil.Open//Structures.v03'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    if sys.platform == 'win32':
        _existing_platform = os.environ.get("QT_QPA_PLATFORM", "windows")
        if "darkmode" not in _existing_platform:
            os.environ["QT_QPA_PLATFORM"] = _existing_platform + ":darkmode=0"

    app = QApplication(sys.argv)

    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:
        pass

    animator = GlobalDialogAnimator(app)
    app.installEventFilter(animator)

    ipc = IPCManager()
    is_secondary = ipc.connect_to_primary()
    if not is_secondary:
        ipc.start_server()           

    if getattr(sys, 'frozen', False):
        pkl_path = next((arg for arg in sys.argv if arg.endswith('.pkl')), None)
        if pkl_path and os.path.exists(pkl_path):
            from core.solver.solid_elements.solid_results_viewer import SolidResultsViewer, _DmProxy
            import pickle
            
            try:
                with open(pkl_path, 'rb') as f:
                    data = pickle.load(f)
                try:
                    os.unlink(pkl_path)  
                except Exception:
                    pass
                    
                dm_proxy = _DmProxy(
                    nodes=data['nodes'], 
                    elements=data['elements'], 
                    total_dofs=data['total_dofs']
                )
                viewer = SolidResultsViewer(dm_proxy, data['stress_results'], U_full=data.get('U_full'))

                icon_path = os.path.join(root_dir, "app", "graphic", "logo.png")
                if os.path.exists(icon_path):
                    from PyQt6.QtGui import QIcon
                    viewer.setWindowIcon(QIcon(icon_path))
                    
                viewer.show()
                sys.exit(app.exec())
            except Exception as e:
                print(f"Failed to launch Solid Viewer: {e}")
                sys.exit(1)

    from PyQt6.QtGui import QSurfaceFormat
    import json

    prefs_path = os.path.join(os.path.expanduser("~"), ".Open//Structures_prefs.json")
    msaa_map = {0: 0, 1: 4, 2: 8, 3: 16}
    msaa_level = 2  
    if os.path.exists(prefs_path):
        try:
            with open(prefs_path) as f:
                prefs = json.load(f)
                msaa_level = prefs.get("msaa_level", 2)
        except:
            pass

    fmt = QSurfaceFormat()
    fmt.setSamples(msaa_map[msaa_level])
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)

    if is_secondary:
        auth_manager = GoogleAuthManager()
        if not auth_manager.restore_session():
            QMessageBox.warning(
                None, "Session Expired",
                "Your session has expired.\n"
                "Please restart Open//Structures to log in again."
            )
            sys.exit(0)

        window = MainWindow()
        window.auth_manager = auth_manager
        ipc.send_secondary_ready()
        ipc.listen_as_secondary(window)
        window.showMaximized()

        def _attach_secondary():
            window.user_widget = UserProfileWidget(auth_manager, parent=window)
            window.user_widget.reposition()
            window.user_widget.show()
            window.user_widget.raise_()
            window.user_widget.logout_requested.connect(window.close)

        QTimer.singleShot(150, _attach_secondary)

        def _load_secondary_file():
            if len(sys.argv) > 1:
                file_path = sys.argv[1]
                if os.path.exists(file_path) and file_path.endswith('.mf'):
                    try:
                        window.model = StructuralModel("Loaded Project")
                        window.model.load_from_file(file_path)
                        window.undo_stack.clear()
                        window.model.file_path = file_path
                        window.terminal_panel.set_model(window.model)
                        if window.model.graphics_settings:
                                                                                          
                            current_msaa = window.graphics_settings.get("msaa_level", 2)
                            
                            window.graphics_settings.update(window.model.graphics_settings)
                            
                            window.graphics_settings["msaa_level"] = current_msaa
                            
                            window._apply_canvas_view_settings(window.graphics_settings)
                            window.update_graphics_settings(window.graphics_settings)
                        if hasattr(window.model, 'saved_unit_system'):
                            window.combo_units.blockSignals(True)
                            window.combo_units.setCurrentText(window.model.saved_unit_system)
                            window.combo_units.blockSignals(False)
                            window.on_units_changed(0)
                        window.canvas.draw_model(window.model)
                        window.status.showMessage(f"Loaded: {file_path}")
                        window.canvas.set_standard_view("3D")
                        window.set_interface_state(True)
                        window.update_window_title()
                    except Exception as e:
                        QMessageBox.critical(window, "Load Error", f"Failed to open file.\n{e}")

        QTimer.singleShot(300, _load_secondary_file)
        sys.exit(app.exec())
    
    video_path = os.path.join(root_dir, "app", "graphic", "Animation.gif")
    
    if not os.path.exists(video_path):
        print("Video not found, skipping splash.")
        window = MainWindow()
        ipc.raise_requested.connect(lambda: (window.showNormal(), window.raise_(), window.activateWindow()))

        auth_manager = GoogleAuthManager()
        if not auth_manager.login(parent=None):
            sys.exit(0)

        window.auth_manager = auth_manager
        window.showMaximized()

        def attach_no_splash():
            window.user_widget = UserProfileWidget(auth_manager, parent=window)
            window.user_widget.reposition()
            window.user_widget.show()
            window.user_widget.raise_()

        QTimer.singleShot(150, attach_no_splash)
        sys.exit(app.exec())

    splash = VideoSplash(video_path)
    
    splash.show()
    splash.start()
    
    app.processEvents()
    
    window = MainWindow()
    ipc.raise_requested.connect(lambda: (window.showNormal(), window.raise_(), window.activateWindow()))
    
    def on_splash_finished():
        if hasattr(splash, 'cleanup_player'):
            splash.cleanup_player()
            
        splash.close()
        splash.deleteLater()

        auth_manager = GoogleAuthManager()
        if not auth_manager.login(parent=None):
            app.quit()
            return

        window.auth_manager = auth_manager

        window.showMaximized()
        window.activateWindow()

        def attach_user_widget():
            window.user_widget = UserProfileWidget(auth_manager, parent=window)
            window.user_widget.reposition()
            window.user_widget.show()
            window.user_widget.raise_()

            def on_logout():
                nonlocal window                                                                                   

                if window.model and not window.undo_stack.isClean():
                    reply = QMessageBox.question(
                        window,
                        "Unsaved Changes",
                        "You have unsaved changes in your model.\nDo you want to save before logging out?",
                        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Save
                    )
                    if reply == QMessageBox.StandardButton.Save:
                        if not window.on_save_model():
                            return 
                    elif reply == QMessageBox.StandardButton.Cancel:
                        return  

                ipc.broadcast_logout()                                 
                
                window.hide()
                if hasattr(window, 'user_widget'):
                    window.user_widget.deleteLater()
                window.deleteLater()                                                                  

                if auth_manager.login(parent=None):
                    
                    window = MainWindow()
                    window.auth_manager = auth_manager
                    
                    ipc.raise_requested.connect(lambda: (window.showNormal(), window.raise_(), window.activateWindow()))
                    
                    window.showMaximized()
                    window.activateWindow()
                    
                    QTimer.singleShot(100, attach_user_widget)
                else:
                                                                   
                    app.quit()

            window.user_widget.logout_requested.connect(on_logout)
        
        QTimer.singleShot(150, attach_user_widget)

        if len(sys.argv) > 1:
            file_path = sys.argv[1]
            if os.path.exists(file_path) and file_path.endswith('.mf'):
                try:
                    if window.model is None:
                        window.model = StructuralModel("Loaded Project")
                    
                    window.model.load_from_file(file_path)
                    window.undo_stack.clear()
                    window.model.file_path = file_path
                    window.terminal_panel.set_model(window.model)
                    
                    if window.model.graphics_settings:
                                                                                      
                        current_msaa = window.graphics_settings.get("msaa_level", 2)
                        
                        window.graphics_settings.update(window.model.graphics_settings)
                        
                        window.graphics_settings["msaa_level"] = current_msaa
                        
                        window._apply_canvas_view_settings(window.graphics_settings)
                        window.update_graphics_settings(window.graphics_settings)
                    
                    if hasattr(window.model, 'saved_unit_system'):
                        window.combo_units.blockSignals(True)
                        window.combo_units.setCurrentText(window.model.saved_unit_system)
                        window.combo_units.blockSignals(False)
                        window.on_units_changed(0)
                    
                    window.draw_both_canvases()
                    if hasattr(window, '_tributary_generator'):
                        window._tributary_generator.reset(window.model)
                        window.update_yield_lines()
                    window.status.showMessage(f"Loaded: {file_path}")
                    window.canvas.set_standard_view("3D")
                    window.set_interface_state(True)
                    window.update_window_title()
                except Exception as e:
                    QMessageBox.critical(window, "Load Error", f"Failed to open file.\n{e}")
    
    splash.finished.connect(on_splash_finished) 
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
