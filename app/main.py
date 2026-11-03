                                                                                   
import OpenGL
OpenGL.ERROR_CHECKING = False
OpenGL.ERROR_LOGGING = False
import sys
if "--run-solver" in sys.argv:                                                                 
    from app.solver_process import main as _solver_main
    sys.exit(_solver_main(sys.argv))
import os
import math
import ctypes
import time
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QPointF
from PyQt6.QtGui import QAction, QPixmap,QCursor, QVector3D, QColor, QIcon
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                             QMessageBox, QFileDialog, QSplashScreen, QLabel, 
                             QComboBox,QProgressBar, QProgressDialog, QSplitter, QSizePolicy, QFrame, QCheckBox, QApplication, QFileDialog, QScrollArea)
from PyQt6.QtWidgets import QMenu
from PyQt6.QtGui import QCursor
from PyQt6.QtGui import QUndoStack  
from PyQt6.QtGui import QUndoCommand

class CmdAnalysisOptionsChanged(QUndoCommand):
    """Marks the model dirty after Analysis Options change (dialog already applied values)."""
    def __init__(self):
        super().__init__("Analysis Options")
    def undo(self): pass
    def redo(self): pass

from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices, QSoundEffect
from PyQt6.QtCore import QUrl
from PyQt6.QtMultimediaWidgets import QVideoWidget  
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, pyqtSignal
import qtawesome as qta
from PyQt6.QtGui import QAction, QPixmap, QCursor, QVector3D, QColor, QIcon, QPainter, QFont
from PyQt6.QtGui import QActionGroup
import pyqtgraph.opengl as gl
from PyQt6.QtWidgets import QWidgetAction, QHBoxLayout

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

from app.commands import CmdDrawFrame, CmdDeleteSelection, CmdReplicate, CmdAssignInsertion, CmdDrawAreaElement, CmdDivideFrame, CmdJoinFrames
from core.model_tree import ModelTreeDock
from core.model import StructuralModel, LoadCase
from app.canvas import MCanvas3D
from app.dialogs.material_dialog import MaterialManagerDialog
from app.dialogs.draw_dialog import DrawFrameDialog
from app.dialogs.load_pattern_dialog import LoadPatternDialog
from app.dialogs.draw_cross_brace_dialog import DrawCrossBraceDialog
from app.dialogs.draw_quick_area_dialog import DrawQuickAreaDialog
from app.dialogs.draw_beam_column_dialog import DrawBeamColumnDialog
from app.dialogs.view_options_dialog import ViewOptionsDialog
from app.dialogs.graphics_dialog import GraphicsOptionsDialog
from graphic.mouse_crosshair import (CROSSHAIR_DEFAULTS, CROSSHAIR_KEYS as _CROSSHAIR_KEYS,
                                     save_crosshair_prefs)
from core.units import unit_registry, UNIT_SYSTEMS
from core.model_s2k import export_sap2000
from app.dialogs.assign_frame_point_load_dialog import AssignFramePointLoadDialog
from app.dialogs.assign_frame_hinge_dialog import AssignFrameHingeDialog
from app.dialogs.analysis_dialog import AnalysisDialog
from app.solver_worker import SolverWorker
from app.solver_runner import SolverProcessRunner
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
from app.dialogs.plot_function_dialog import PlotFunctionDisplayDialog, has_ltha_results
from app.dialogs.pushover_curve_dialog import PushoverCurveDialog
from app.dialogs.hinge_results_dialog import HingeResultsDialog
from core.mesh import Node, FrameElement, AreaElement, CableObject
from core.io_manager import RecentProjectsManager
from app.ui.recent_projects import RecentProjectsPanel
from core.model_history import atomic_save_model
from app.model_history_controller import ModelHistoryController

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
        self.player.setPlaybackRate(2.05817)
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

_dwm_set_window_attribute = None
if sys.platform == "win32":
    try:
                                                                         
        _dwm_set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        _dwm_set_window_attribute.restype = ctypes.c_long
        _dwm_set_window_attribute.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint
        ]
    except Exception:
        _dwm_set_window_attribute = None

def apply_windows_titlebar_theme(widget):
    """
    Forces the native Windows title bar (minimize/maximize/close area) of the
    given top-level widget to match our app's own Dark/Light setting, fully
    independent of the Windows 11 system theme. In Light mode we leave the
    native title bar alone. In Dark mode we force it dark so it matches the
    rest of the (black) UI instead of showing a stray white bar.
    """
    if sys.platform != "win32" or _dwm_set_window_attribute is None:
        print(f"[titlebar-debug] SKIPPED: platform={sys.platform!r} dwm_available={_dwm_set_window_attribute is not None}")
        return
    try:
        app = QApplication.instance()
        theme_prop = app.property("os_ui_theme") if app else None
        is_dark = bool(theme_prop == "Dark")
        hwnd = ctypes.c_void_p(int(widget.winId()))

        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19                              
        value = ctypes.c_int(1 if is_dark else 0)

        hr1 = _dwm_set_window_attribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
        )
        hr2 = _dwm_set_window_attribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, ctypes.byref(value), ctypes.sizeof(value)
        )

        SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004
        SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0010, 0x0020
        swp_ok = ctypes.windll.user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
        )
        print(f"[titlebar-debug] widget={widget.__class__.__name__} hwnd={hwnd.value} "
              f"theme_prop={theme_prop!r} is_dark={is_dark} hr(attr20)={hr1} hr(attr19)={hr2} "
              f"SetWindowPos_ok={bool(swp_ok)} winver={sys.getwindowsversion() if hasattr(sys, 'getwindowsversion') else 'n/a'}")
    except Exception as e:
        print(f"[titlebar-debug] EXCEPTION: {e!r}")

class GlobalDialogAnimator(QObject):
    """Intercepts all QDialogs globally and applies a fade-in animation,
    and forces every dialog/file-picker/message-box's native title bar to
    follow our app's own theme (see apply_windows_titlebar_theme)."""
    def eventFilter(self, obj, event):
                                                            
        if event.type() == QEvent.Type.Show and isinstance(obj, QDialog):
            apply_windows_titlebar_theme(obj)
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

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QWidgetAction
from PyQt6.QtGui import QPixmap

PLANE_STATE_COLORS = {
    0: '#6c757d',                             
    1: '#0d6efd',                                             
    2: '#fd7e14',                                                    
    3: '#198754',                                           
}

PLANE_STATE_LABELS = {
    0: None,
    1: "Ghost",
    2: "Isolated",
    3: "2D Locked",
}

PLANE_STATE_NEXT_HINT = {
    0: "Click to dim the rest of the structure",
    1: "Click again to hide the rest of the structure",
    2: "Click again to snap into flat 2D view",
    3: "Click again to restart the cycle",
}

def create_plane_icon(text, state=0):
    """Builds the toolbar icon for a plane-cut button (XY / XZ / YZ).

    `state` reflects where the button sits in its 3-click cycle:
      0 = inactive (plain gray letters, no dots)
      1 = Ghost mode      -> blue,   1 of 3 dots filled
      2 = Strict isolation-> orange, 2 of 3 dots filled
      3 = Locked 2D view  -> green,  3 of 3 dots filled

    The colored dots beneath the letters are what make the button's
    multi-click behavior visible at a glance, instead of the plain
    single on/off look it had before.
    """
    color = QColor(PLANE_STATE_COLORS.get(state, '#6c757d'))

    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    text_rect = pixmap.rect()
    if state > 0:
        text_rect = text_rect.adjusted(0, -3, 0, -3)

    painter.setPen(color)
    painter.setFont(QFont('Segoe UI', 15, QFont.Weight.Bold))
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

    if state > 0:
        dot_radius = 2.0
        spacing = 7
        start_x = (pixmap.width() / 2.0) - spacing
        y = float(pixmap.height() - 6)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            cx = start_x + (i * spacing)
            if i < state:
                painter.setBrush(color)
            else:
                dim_color = QColor(color)
                dim_color.setAlpha(70)
                painter.setBrush(dim_color)
            painter.drawEllipse(QPointF(cx, y), dot_radius, dot_radius)

    painter.end()
    return QIcon(pixmap)

_VIEW_SETTING_KEYS = (
    'view_extruded', 'show_slabs', 'show_joints', 'show_supports', 'show_loads',
    'show_local_axes', 'show_constraints', 'show_releases', 'load_type_filter',
    'visible_load_patterns', 'show_grid', 'show_ghost_structure', 'show_hinges',
    'tributary_loads', 'tributary_heatmap', 'tributary_mesh',
)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.model = None 
        self._history_controller = ModelHistoryController(self)

        self.undo_stack = QUndoStack(self)
        self.undo_stack.indexChanged.connect(self._on_model_changed)
        self.undo_stack.cleanChanged.connect(lambda _: self.update_window_title())

        self.graphics_settings = {
            "background_color": (1.0, 1.0, 1.0, 1.0), 
            "antialias": True,
            "node_size": 6,
            "node_color": (1.0, 0.0, 0.0, 1.0),     
            "line_width": 2.0,
            "extrude_opacity": 0.35,
            "show_edges": True,
            "msaa_level": 1,
            "edge_width": 1.5,
            "edge_opacity": 0.08,                                                              
            "edge_color": (0.0, 0.0, 0.0, 1.0),      
            "slab_opacity": 0.4,
            "area_load_display_mode": "smart",
            "frame_load_display_mode": "smart",
            "load_text_scale": 1.0,
            "area_load_arrow_spacing": 55.0,
            **CROSSHAIR_DEFAULTS,
        }

        import json as _json
        _prefs_path = os.path.join(os.path.expanduser("~"), ".OpenStructures_prefs.json")
        if os.path.exists(_prefs_path):
            try:
                with open(_prefs_path) as _f:
                    _saved = _json.load(_f)
                    for _vk in _VIEW_SETTING_KEYS:
                        _saved.pop(_vk, None)
                    
                    if "msaa_level" in _saved:
                        _saved["antialias"] = int(_saved["msaa_level"]) > 0
                        
                    for _k in ("background_color", "node_color", "edge_color", "shell_edge_color", "hinge_color", "crosshair_color"):
                        if _k in _saved and isinstance(_saved[_k], list):
                            _saved[_k] = tuple(_saved[_k])
                                                                               
                    if _saved.get("node_color") == (1.0, 1.0, 0.0, 1.0):
                        _saved["node_color"] = (1.0, 0.0, 0.0, 1.0)
                    self.graphics_settings.update(_saved)
            except Exception:
                pass
        self._applied_graphics_settings = self.graphics_settings.copy()
        
        self.setWindowTitle("Open//Structures v0.8.10")
        self.resize(1200, 800)

        apply_windows_titlebar_theme(self)
                                                                  
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

        self.recent_projects_manager = RecentProjectsManager()

        self.draw_start_node = None 
        self.draw_dialog = None
        self.cross_brace_mode_active = False
        self.cross_brace_dialog = None
        self.quick_area_mode_active = False
        self.quick_area_dialog = None
        self.beam_col_mode_active = False
        self.beam_col_dialog = None
        self.selected_ids = []
        self.selected_node_ids = []
        self.selected_area_ids = []
        
        self.picking_replicate = False 
        self.replicate_p1 = None      
        self.replicate_dialog = None
        self.divide_frame_dialog = None

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
        
        from app.ui.command_palette import CommandPalette
        self.cmd_palette = CommandPalette(self)
                                     
        self.init_ui()
        QApplication.instance().applicationStateChanged.connect(self._on_app_state_changed)
        self.set_interface_state(False)
    
    def _menu_item(self, menu, icon_name, text, slot):
        """One-line replacement for the QAction + connect + addAction boilerplate."""
        act = QAction(qta.icon(icon_name, color='#6c757d', disabled_color='#cccccc'), text, self)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _menu_header(self, menu, text):
        """Small uppercase section label inside a menu (instead of bare separators)."""
        from app.ui.theme import COLORS
        if menu.actions():
            menu.addSeparator()
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10px; font-weight: 700;"
            "letter-spacing: 1px; padding: 6px 12px 2px 12px; background: transparent;")
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(lbl)
        menu.addAction(wa)

    def init_ui(self):
        """Organizes all UI components"""

        menubar = self.menuBar()
                                                                                
        file_menu = menubar.addMenu("File")
        
        new_action = QAction(qta.icon('fa5s.file-medical', color='#6c757d', disabled_color='#cccccc'), "New Model...", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.on_new_model)
        file_menu.addAction(new_action)
        
        open_action = QAction(qta.icon('fa5s.folder-open', color='#6c757d', disabled_color='#cccccc'), "Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.on_open_model)
        file_menu.addAction(open_action)
        
        self.recent_projects_menu = file_menu.addMenu(qta.icon('fa5s.clock', color='#6c757d', disabled_color='#cccccc'), "Recent Projects")
        self._build_recent_projects_menu()
        self.recent_projects_menu.aboutToShow.connect(self._build_recent_projects_menu)

        file_menu.addSeparator()

        self.action_close_project = QAction(qta.icon('fa5s.times', color='#c77873'), "Close Project", self)
        self.action_close_project.triggered.connect(self.on_close_project)
        file_menu.addAction(self.action_close_project)

        file_menu.addSeparator()

        self.action_save = QAction(qta.icon('fa5s.save', color='#6c757d', disabled_color='#cccccc'), "Save", self)
        self.action_save.setShortcut("Ctrl+S")
        self.action_save.triggered.connect(self.on_save_model)
        file_menu.addAction(self.action_save)

        self.action_save_as = QAction(qta.icon('fa5s.save', color='#6c757d', disabled_color='#cccccc'), "Save As...", self)
        self.action_save_as.setShortcut("Ctrl+Shift+S")
        self.action_save_as.triggered.connect(self.on_save_as_model)
        file_menu.addAction(self.action_save_as)

        self.action_model_history = QAction(qta.icon('fa5s.code-branch', color='#6c757d'), "Model History...", self)
        self.action_model_history.setShortcut("Ctrl+Alt+H")
        self.action_model_history.triggered.connect(self._history_controller.show_dialog)
        file_menu.addAction(self.action_model_history)

        file_menu.addSeparator()

        self.action_exit = QAction(qta.icon('fa5s.sign-out-alt', color='#6c757d', disabled_color='#cccccc'), "Exit", self)
        self.action_exit.triggered.connect(self.close)
        file_menu.addAction(self.action_exit)

        self.menu_edit = menubar.addMenu("Edit")
        self._menu_header(self.menu_edit, "History")

        self.undo_action = QAction(qta.icon('fa5s.undo', color='#6c757d', disabled_color='#cccccc'), "Undo", self)
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.setToolTip("Undo (Ctrl+Z)")
        self.undo_action.triggered.connect(self._perform_undo)
        self.menu_edit.addAction(self.undo_action)

        self.redo_action = QAction(qta.icon('fa5s.redo', color='#6c757d', disabled_color='#cccccc'), "Redo", self)
        self.redo_action.setShortcut("Ctrl+Y")                                          
        self.redo_action.setToolTip("Redo (Ctrl+Y)")
        self.redo_action.triggered.connect(self._perform_redo)
        self.menu_edit.addAction(self.redo_action)
        
        self.undo_stack.canUndoChanged.connect(self.undo_action.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_action.setEnabled)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        
        self.undo_stack.undoTextChanged.connect(lambda t: self.undo_action.setText(f"Undo {t}" if t else "Undo"))
        self.undo_stack.redoTextChanged.connect(lambda t: self.redo_action.setText(f"Redo {t}" if t else "Redo"))
        
        self._menu_header(self.menu_edit, "Labels")

        relabel_action = QAction(qta.icon('fa5s.tags', color='#6c757d', disabled_color='#cccccc'), "Auto-Relabel Members...", self)
        def show_relabel_ui():
            from app.dialogs.relabel_dialog import RelabelDialog
            dlg = RelabelDialog(self)
            dlg.exec()
        relabel_action.triggered.connect(show_relabel_ui)
        self.menu_edit.addAction(relabel_action)
                                  
        reset_labels_action = QAction(qta.icon('fa5s.undo-alt', color='#6c757d', disabled_color='#cccccc'), "Reset Labels to Default", self)
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

        self._menu_header(self.menu_edit, "Modify")
                                  
        rep_action = QAction(qta.icon('fa5s.copy', color='#6c757d', disabled_color='#cccccc'), "Replicate...", self)
        rep_action.setShortcut("Ctrl+R") 
        rep_action.triggered.connect(self.on_edit_replicate)
        self.menu_edit.addAction(rep_action)

        merge_action = QAction(qta.icon('fa5s.compress-arrows-alt', color='#6c757d', disabled_color='#cccccc'), "Merge Joints...", self)
        merge_action.triggered.connect(self.on_edit_merge)
        self.menu_edit.addAction(merge_action)

        self.menu_edit_lines = self.menu_edit.addMenu(qta.icon('fa5s.grip-lines', color='#6c757d', disabled_color='#cccccc'), "Edit Lines")

        divide_frames_action = QAction(qta.icon('fa5s.cut', color='#6c757d', disabled_color='#cccccc'), "Divide Frames...", self)
        divide_frames_action.triggered.connect(self.on_edit_divide_frames)
        self.menu_edit_lines.addAction(divide_frames_action)

        join_frames_action = QAction(qta.icon('fa5s.link', color='#6c757d', disabled_color='#cccccc'), "Join Frames", self)
        join_frames_action.triggered.connect(self.on_edit_join_frames)
        self.menu_edit_lines.addAction(join_frames_action)

        self._menu_header(self.menu_edit, "Cursor & Snap")

        self.act_precision_pointer = QAction(qta.icon('fa5s.crosshairs', color='#6c757d', disabled_color='#cccccc'), "Precision Pointer", self)
        self.act_precision_pointer.setCheckable(True)
        self.act_precision_pointer.setChecked(bool(self.graphics_settings.get('crosshair_enabled', True)))
        self.act_precision_pointer.setShortcut("F7")
        self.act_precision_pointer.setToolTip("Crosshair for precise picking (F7)")
        self.act_precision_pointer.toggled.connect(self.on_toggle_precision_pointer)
        self.menu_edit.addAction(self.act_precision_pointer)

        act_pp_settings = QAction(qta.icon('fa5s.sliders-h', color='#6c757d', disabled_color='#cccccc'), "Precision Pointer Settings...", self)
        act_pp_settings.triggered.connect(self.on_precision_pointer_settings)
        self.menu_edit.addAction(act_pp_settings)

        self.menu_snap = self.menu_edit.addMenu(qta.icon('fa5s.magnet', color='#6c757d', disabled_color='#cccccc'), "Snap Options")
        self.snap_actions = {}
        for _key, _label, _tip in (
            ('grid',      "Grid Points",     "Snap to grid-line intersections"),
            ('joints',    "Existing Joints", "Snap to joints already in the model"),
            ('midpoints', "Frame Midpoints", "Snap to the midpoint of existing frames"),
        ):
            _a = QAction(_label, self)
            _a.setCheckable(True)
            _a.setChecked(bool(self.graphics_settings.get(f'snap_{_key}', _key != 'midpoints')))
            _a.setToolTip(_tip)
            _a.toggled.connect(lambda checked, k=_key: self.on_snap_toggled(k, checked))
            self.menu_snap.addAction(_a)
            self.snap_actions[_key] = _a
        self.menu_snap.addSeparator()
        _act_snap_r = QAction("Snap Radius...", self)
        _act_snap_r.triggered.connect(self.on_snap_radius)
        self.menu_snap.addAction(_act_snap_r)

        self.menu_define = menubar.addMenu("Define")
        m = self.menu_define

        self._menu_header(m, "Model")
        self._menu_item(m, 'fa5s.th',    "Grid System...",          self.open_grid_editor)
        self._menu_item(m, 'fa5s.cubes', "Material Properties...",  self.on_define_materials)

        self._menu_header(m, "Elements")
        self._menu_item(m, 'fa5s.shapes',        "Frame Sections...",        self.on_define_sections)
        self._menu_item(m, 'fa5s.vector-square', "Area Sections...",           self.on_define_area_sections)
        self._menu_item(m, 'fa5s.link',          "Link/Support Properties...", self.on_define_link_properties)
        self._menu_item(m, 'fa5s.grip-lines-vertical', "Frame Hinge Properties...", self.on_define_hinge_properties)

        self.menu_more_sections = m.addMenu(
            qta.icon('fa5s.ellipsis-h', color='#6c757d', disabled_color='#cccccc'), "More Sections")
        self._menu_item(self.menu_more_sections, 'fa5s.bezier-curve', "Cable Sections (Beta)...",  self.on_define_cable_sections)
        self._menu_item(self.menu_more_sections, 'fa5s.wave-square',  "Tendon Sections (Beta)...", self.on_define_tendon_sections)
        self._menu_item(self.menu_more_sections, 'fa5s.ruler-horizontal', "Reinforcing Bar Sizes...", self.on_define_rebar_sizes)

        self._menu_header(m, "Loads")
        self._menu_item(m, 'fa5s.list-ul',      "Load Patterns...",     self.on_define_load_patterns)
        self._menu_item(m, 'fa5s.tasks',        "Load Cases...",        self.on_define_load_cases)
        self._menu_item(m, 'fa5s.layer-group',  "Load Combinations...", self.on_define_load_combos)
        self._menu_item(m, 'fa5s.weight-hanging', "Mass Source...",     self.on_define_mass_source)

        self._menu_header(m, "Analysis Data")
        self._menu_item(m, 'fa5s.wave-square', "Response Spectrum Function...", self.on_define_response_spectrum)
        self._menu_item(m, 'fa5s.history',     "Time History Function...",      self.on_define_time_history_functions)
        self._menu_item(m, 'fa5s.chart-area',  "Pushover Parameters...",        self.on_define_pushover_params)
        self._menu_item(m, 'fa5s.ruler-combined', "Virtual Measurements (Drifts / Responses)...", self.on_define_virtual_measurements)

        self.menu_draw = menubar.addMenu("Draw")
        self._menu_header(self.menu_draw, "Elements")
        
        draw_action = QAction(qta.icon('fa5s.pencil-alt', color='#6c757d', disabled_color='#cccccc'), "Draw Frame/Cables/Tendon...", self)
        draw_action.triggered.connect(self.on_draw_frame)
        self.menu_draw.addAction(draw_action)

        draw_area_action = QAction(qta.icon('fa5s.vector-square', color='#6c757d', disabled_color='#cccccc'), "Draw Poly Area...", self)
        draw_area_action.triggered.connect(self.on_draw_poly_area)
        self.menu_draw.addAction(draw_area_action)

        self._menu_header(self.menu_draw, "Quick Draw")

        quick_area_action = QAction(qta.icon('fa5s.th-large', color='#6c757d', disabled_color='#cccccc'), "Quick Area Draw...", self)
        quick_area_action.triggered.connect(self.on_draw_quick_area)
        self.menu_draw.addAction(quick_area_action)

        cross_brace_action = QAction(qta.icon('fa5s.times', color='#6c757d', disabled_color='#cccccc'), "Quick Cross Brace...", self)
        cross_brace_action.triggered.connect(self.on_draw_cross_brace)
        self.menu_draw.addAction(cross_brace_action)

        beam_col_action = QAction(qta.icon('fa5s.i-cursor', color='#6c757d', disabled_color='#cccccc'), "Quick Beam / Column...", self)
        beam_col_action.triggered.connect(self.on_draw_beam_column)
        self.menu_draw.addAction(beam_col_action)

        self._menu_header(self.menu_draw, "Links")

        draw_link2_action = QAction(qta.icon('fa5s.expand-alt', color='#6c757d', disabled_color='#cccccc'), "Draw 2-Joint Link...", self)
        draw_link2_action.triggered.connect(self.on_draw_link2)
        self.menu_draw.addAction(draw_link2_action)

        draw_link1_action = QAction(qta.icon('fa5s.thumbtack', color='#6c757d', disabled_color='#cccccc'), "Draw 1-Joint Link...", self)
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
            QToolButton:hover:!disabled {
                background-color: #e9ecef; /* Soft grey on hover */
            }
            QToolButton:checked:!disabled {
                background-color: #d6e4f0; /* Professional light blue when toggled ON */
                border: 1px solid #b3cce6;
            }
            QToolButton:pressed:!disabled {
                background-color: #ced4da;
            }
            QToolButton:disabled {
                background-color: transparent;
                border: none;
            }
        """)

        act_new = QAction(qta.icon('fa5s.file-medical', color='#6c757d', disabled_color='#cccccc'), "New Model", self)
        act_new.setToolTip("New Model  (Ctrl+N)")
        act_new.triggered.connect(self.on_new_model)
        self.toolbar.addAction(act_new)

        act_open = QAction(qta.icon('fa5s.folder-open', color='#6c757d', disabled_color='#cccccc'), "Open", self)
        act_open.setToolTip("Open Model  (Ctrl+O)")
        act_open.triggered.connect(self.on_open_model)
        self.toolbar.addAction(act_open)

        act_save = QAction(qta.icon('fa5s.save', color='#6c757d', disabled_color='#cccccc'), "Save", self)
        act_save.setToolTip("Save Model  (Ctrl+S)")
        act_save.triggered.connect(self.on_save_model)
        self.toolbar.addAction(act_save)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        tb_undo = QAction(qta.icon('fa5s.undo', color='#6c757d', disabled_color='#cccccc'), "Undo", self)
        tb_undo.setToolTip("Undo  (Ctrl+Z)")
        self.toolbar.addAction(self.undo_action)

        tb_redo = QAction(qta.icon('fa5s.redo', color='#6c757d', disabled_color='#cccccc'), "Redo", self)
        tb_redo.setToolTip("Redo  (Ctrl+Y)")
        self.toolbar.addAction(self.redo_action)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        act_grid = QAction(qta.icon('fa5s.th', color='#6c757d', disabled_color='#cccccc'), "Grid System", self)
        act_grid.setToolTip("Edit Grid System")
        act_grid.triggered.connect(self.open_grid_editor)
        self.toolbar.addAction(act_grid)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        act_zoom_in =  QAction(qta.icon('fa5s.search-plus', color='#6c757d', disabled_color='#cccccc'), "Zoom In", self)
        act_zoom_in.setToolTip("Zoom In  (or scroll wheel up)")
        act_zoom_in.triggered.connect(self._toolbar_zoom_in)
        self.toolbar.addAction(act_zoom_in)

        act_zoom_out = QAction(qta.icon('fa5s.search-minus', color='#6c757d', disabled_color='#cccccc'), "Zoom Out", self)
        act_zoom_out.setToolTip("Zoom Out  (or scroll wheel down)")
        act_zoom_out.triggered.connect(self._toolbar_zoom_out)
        self.toolbar.addAction(act_zoom_out)

        self.btn_pan = QAction(qta.icon('fa5s.hand-paper', color='#6c757d', disabled_color='#cccccc'), "Pan Tool", self)
        self.btn_pan.setToolTip("Pan View: one left-drag, then back to normal  (or hold the middle mouse button and drag)")
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
        self.btn_xy.setToolTip("XY Plan — click to dim the rest of the structure")
        self.btn_xy.triggered.connect(lambda: self.set_view_2d("XY"))
        self.toolbar.addAction(self.btn_xy)

        self.btn_xz = QAction(create_plane_icon("XZ"), "XZ Elev", self)
        self.btn_xz.setCheckable(True)
        self.btn_xz.setToolTip("XZ Elev — click to dim the rest of the structure")
        self.btn_xz.triggered.connect(lambda: self.set_view_2d("XZ"))
        self.toolbar.addAction(self.btn_xz)

        self.btn_yz = QAction(create_plane_icon("YZ"), "YZ Elev", self)
        self.btn_yz.setCheckable(True)
        self.btn_yz.setToolTip("YZ Elev — click to dim the rest of the structure")
        self.btn_yz.triggered.connect(lambda: self.set_view_2d("YZ"))
        self.toolbar.addAction(self.btn_yz)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.btn_up = QAction(qta.icon('fa5s.chevron-up', color='#6c757d', disabled_color='#cccccc'), "UP", self)
        self.btn_up.triggered.connect(lambda: self.move_view_layer(1))
        self.toolbar.addAction(self.btn_up)
        
        self.btn_down = QAction(qta.icon('fa5s.chevron-down', color='#6c757d', disabled_color='#cccccc'), "Down", self)
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

        self.btn_lock = QAction(qta.icon('fa5s.unlock', color='#6c757d', disabled_color='#cccccc'), "", self)
        self.btn_lock.setToolTip("Model is editable.")
        self.btn_lock.triggered.connect(self.on_lock_clicked)
        self.toolbar.addAction(self.btn_lock)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.btn_deform = QAction(qta.icon('fa5s.wave-square', color='#6c757d', disabled_color='#cccccc'), "Deformed Shape", self)
        self.btn_deform.setCheckable(True)                                 
        self.btn_deform.setToolTip("Toggle Deformed Shape ON/OFF (Results Mode Only)")
        self.btn_deform.triggered.connect(self._toolbar_toggle_deform)
        self.btn_deform.setEnabled(False)
        self.toolbar.addAction(self.btn_deform)

        from PyQt6.QtWidgets import QToolButton, QMenu
        
        self.btn_play_anim = QAction(qta.icon('fa5s.film', color='#6c757d', disabled_color='#cccccc'), "Play Animation", self)
        self.btn_play_anim.setShortcut("Ctrl+Space")
        self.btn_play_anim.setToolTip("Click to Play/Pause (Ctrl+Space). Right-click for Animation Options.")
        self.btn_play_anim.triggered.connect(self._toolbar_toggle_animation)
        self.btn_play_anim.setEnabled(False)

        anim_button = QToolButton(self)
        anim_button.setDefaultAction(self.btn_play_anim)

        anim_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        def _show_anim_menu(pos, _btn=anim_button):
            menu = QMenu(_btn)
            menu.addAction(self.btn_play_anim)
            menu.addSeparator()
            opts_action = menu.addAction("Animation Options...")
            opts_action.triggered.connect(self.on_view_deformed_shape)
            menu.exec(_btn.mapToGlobal(pos))
        anim_button.customContextMenuRequested.connect(_show_anim_menu)

        self.toolbar.addWidget(anim_button)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        self.btn_opts = QAction(qta.icon('fa5s.cog', color='#6c757d', disabled_color='#cccccc'), "Display", self)
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

        self.btn_nav_help = QAction(qta.icon('fa5s.question-circle', color='#6c757d', disabled_color='#cccccc'),
                                    "Navigation Controls", self)
        self.btn_nav_help.setShortcut("F1")
        self.btn_nav_help.setToolTip("Show viewport controls  (F1)")
        self.btn_nav_help.triggered.connect(self.on_toggle_nav_hint)
        self.toolbar.addAction(self.btn_nav_help)

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

        self.act_select = QAction(qta.icon('fa5s.mouse-pointer', color='#6c757d', disabled_color='#cccccc'), "Select Mode", self)
        self.act_select.setToolTip("Select Objects (Esc)")
        self.act_select.setCheckable(True)
        self.act_select.setChecked(True)                
        self.act_select.triggered.connect(self._on_sidebar_select_mode)
        self.draw_action_group.addAction(self.act_select)
        self.sidebar.addAction(self.act_select)

        self.sidebar.addSeparator()

        self.act_draw_frame = QAction(qta.icon('fa5s.pencil-alt', color='#6c757d', disabled_color='#cccccc'), "Draw Frame", self)
        self.act_draw_frame.setToolTip("Draw Frame/Cable")
        self.act_draw_frame.setCheckable(True)
        self.act_draw_frame.triggered.connect(self.on_draw_frame)
        self.draw_action_group.addAction(self.act_draw_frame)
        self.sidebar.addAction(self.act_draw_frame)

        self.act_quick_beam = QAction(qta.icon('fa5s.i-cursor', color='#6c757d', disabled_color='#cccccc'), "Quick Beam/Column", self)
        self.act_quick_beam.setToolTip("Quick Draw Beam/Column")
        self.act_quick_beam.setCheckable(True)
        self.act_quick_beam.triggered.connect(self.on_draw_beam_column)
        self.draw_action_group.addAction(self.act_quick_beam)
        self.sidebar.addAction(self.act_quick_beam)

        self.act_quick_brace = QAction(qta.icon('fa5s.times', color='#6c757d', disabled_color='#cccccc'), "Quick Cross Brace", self)
        self.act_quick_brace.setToolTip("Quick Draw Cross Brace")
        self.act_quick_brace.setCheckable(True)
        self.act_quick_brace.triggered.connect(self.on_draw_cross_brace)
        self.draw_action_group.addAction(self.act_quick_brace)
        self.sidebar.addAction(self.act_quick_brace)

        self.act_quick_area = QAction(qta.icon('fa5s.th-large', color='#6c757d', disabled_color='#cccccc'), "Quick Area Draw", self)
        self.act_quick_area.setToolTip("Quick Draw Shell in a Grid Cell")
        self.act_quick_area.setCheckable(True)
        self.act_quick_area.triggered.connect(self.on_draw_quick_area)
        self.draw_action_group.addAction(self.act_quick_area)
        self.sidebar.addAction(self.act_quick_area)

        self.act_draw_link2 = QAction(qta.icon('fa5s.expand-alt', color='#6c757d', disabled_color='#cccccc'), "Draw 2-Joint Link", self)
        self.act_draw_link2.setToolTip("Draw 2-Joint Link")
        self.act_draw_link2.setCheckable(True)
        self.act_draw_link2.triggered.connect(self.on_draw_link2)
        self.draw_action_group.addAction(self.act_draw_link2)
        self.sidebar.addAction(self.act_draw_link2)

        self.act_draw_link1 = QAction(qta.icon('fa5s.thumbtack', color='#6c757d', disabled_color='#cccccc'), "Draw 1-Joint Link", self)
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
        
        fmt = self.canvas.format()
        msaa_lvl = int(self.graphics_settings.get("msaa_level", 1))
        msaa_samps = {0: 0, 1: 4, 2: 8, 3: 16, 4: 2, 5: 0}.get(msaa_lvl, 0)
        fmt.setSamples(msaa_samps)
        
        self.canvas.setFormat(fmt)
        self.canvas2.setFormat(fmt)
                                                            
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

        self.menu_assign_area = QMenu("Area", self)
        self.menu_assign_area.setIcon(qta.icon('fa5s.vector-square', color='#6c757d', disabled_color='#cccccc'))                                              
        
        self.action_area_mesh = QAction(qta.icon('fa5s.th', color='#6c757d', disabled_color='#cccccc'), "Automatic Area Mesh...", self)
        self.action_area_mesh.triggered.connect(self.on_assign_area_mesh)
        self.menu_assign_area.addAction(self.action_area_mesh)
 
        self.menu_assign_area.addSeparator()

        self.action_area_uniform_load = QAction(
            qta.icon('fa5s.arrows-alt-v', color='#6c757d', disabled_color='#cccccc'), "Uniform Load...", self)
        self.action_area_uniform_load.triggered.connect(self.on_assign_area_uniform_load)
        self.menu_assign_area.addAction(self.action_area_uniform_load)
 
        self.action_area_gravity_load = QAction(
            qta.icon('fa5s.weight', color='#6c757d', disabled_color='#cccccc'), "Gravity Load...", self)
        self.action_area_gravity_load.triggered.connect(self.on_assign_area_gravity_load)
        self.menu_assign_area.addAction(self.action_area_gravity_load)

        self.action_area_insertion = QAction(
            qta.icon('fa5s.crosshairs', color='#6c757d', disabled_color='#cccccc'), "Insertion Point...", self)
        self.action_area_insertion.triggered.connect(self.on_assign_area_insertion_point)
        self.menu_assign_area.addAction(self.action_area_insertion)
        
        self.menu_select = menubar.addMenu("Select")

        all_action = QAction(qta.icon('fa5s.border-all', color='#6c757d', disabled_color='#cccccc'), "All", self)
        all_action.setShortcut("Ctrl+A")
        all_action.triggered.connect(self.on_select_all)
        self.menu_select.addAction(all_action)

        invert_action = QAction(qta.icon('fa5s.adjust', color='#6c757d', disabled_color='#cccccc'), "Invert", self)
        invert_action.setShortcut("Ctrl+I")
        invert_action.triggered.connect(self.on_invert_selection)
        self.menu_select.addAction(invert_action)

        none_action = QAction(qta.icon('fa5s.times-circle', color='#6c757d', disabled_color='#cccccc'), "None", self)
        none_action.setShortcut("Escape")
        none_action.triggered.connect(self.on_select_none)
        self.menu_select.addAction(none_action)

        self.menu_select.addSeparator()

        props_menu = self.menu_select.addMenu("Select by Properties")
        props_menu.setIcon(qta.icon('fa5s.filter', color='#6c757d', disabled_color='#cccccc'))

        sec_select_action = QAction(qta.icon('fa5s.shapes', color='#6c757d', disabled_color='#cccccc'),
                                    "Frame Sections...", self)
        sec_select_action.triggered.connect(self.on_select_by_section)
        props_menu.addAction(sec_select_action)

        area_sec_select_action = QAction(qta.icon('fa5s.vector-square', color='#6c757d', disabled_color='#cccccc'),
                                         "Area Sections...", self)
        area_sec_select_action.triggered.connect(self.on_select_by_area_section)
        props_menu.addAction(area_sec_select_action)

        story_select_action = QAction(qta.icon('fa5s.layer-group', color='#6c757d', disabled_color='#cccccc'),
                                      "Stories...", self)
        story_select_action.triggered.connect(self.on_select_by_story)
        props_menu.addAction(story_select_action)

        self.deselect_menu = self.menu_select.addMenu("Deselect by Properties")
        self.deselect_menu.setIcon(qta.icon('fa5s.minus-square', color='#6c757d', disabled_color='#cccccc'))

        sec_deselect_action = QAction(qta.icon('fa5s.shapes', color='#6c757d', disabled_color='#cccccc'),
                                      "Frame Sections...", self)
        sec_deselect_action.triggered.connect(self.on_deselect_by_section)
        self.deselect_menu.addAction(sec_deselect_action)
        
        area_sec_deselect_action = QAction(qta.icon('fa5s.vector-square', color='#6c757d', disabled_color='#cccccc'),
                                           "Area Sections...", self)
        area_sec_deselect_action.triggered.connect(self.on_deselect_by_area_section)
        self.deselect_menu.addAction(area_sec_deselect_action)

        self.menu_select.aboutToShow.connect(self._update_select_menu_state)
        
        self._menu_header(self.menu_assign, "Joints")
        joint_menu = self.menu_assign.addMenu("Joint")
        joint_menu.setIcon(qta.icon('fa5s.dot-circle', color='#6c757d', disabled_color='#cccccc'))
        
        self._menu_header(joint_menu, "Supports & Connectivity")
        restraint_action = QAction(qta.icon('fa5s.anchor', color='#6c757d', disabled_color='#cccccc'), "Restraints...", self)
        restraint_action.triggered.connect(self.on_assign_restraints)
        joint_menu.addAction(restraint_action)

        constraint_action = QAction(qta.icon('fa5s.link', color='#6c757d', disabled_color='#cccccc'), "Constraints...", self)
        constraint_action.triggered.connect(self.on_assign_constraints)
        joint_menu.addAction(constraint_action)

        spring_action = QAction(qta.icon('fa5s.compress-arrows-alt', color='#6c757d', disabled_color='#cccccc'), "Joint Springs...", self)
        spring_action.triggered.connect(self.on_assign_joint_springs)
        joint_menu.addAction(spring_action)

        self._menu_header(joint_menu, "Loads & Displacements")

        load_action = QAction(qta.icon('fa5s.arrow-down', color='#6c757d', disabled_color='#cccccc'), "Point Loads...", self)
        load_action.triggered.connect(self.on_assign_joint_load)
        joint_menu.addAction(load_action)

        disp_action = QAction(qta.icon('fa5s.arrows-alt', color='#6c757d', disabled_color='#cccccc'), "Joint Displacements...", self)
        disp_action.triggered.connect(self.on_assign_joint_displacement)
        joint_menu.addAction(disp_action)

        self._menu_header(self.menu_assign, "Line Elements")
        frame_menu = self.menu_assign.addMenu("Frame")
        frame_menu.setIcon(qta.icon('fa5s.minus', color='#6c757d', disabled_color='#cccccc'))

        self._menu_header(frame_menu, "Loads")
        frame_point_action = QAction(qta.icon('fa5s.compress-arrows-alt', color='#6c757d', disabled_color='#cccccc'), "Point Loads...", self)
        frame_point_action.triggered.connect(self.on_assign_frame_point_load)
        frame_menu.addAction(frame_point_action)

        frame_load_action = QAction(qta.icon('fa5s.stream', color='#6c757d', disabled_color='#cccccc'), "Distributed Loads...", self)
        frame_load_action.triggered.connect(self.on_assign_frame_load)
        frame_menu.addAction(frame_load_action)

        self._menu_header(frame_menu, "Properties")

        frame_rel_action = QAction(qta.icon('fa5s.unlink', color='#6c757d', disabled_color='#cccccc'), "Releases && Partial Fixity...", self)
        frame_rel_action.triggered.connect(self.on_assign_releases)
        frame_menu.addAction(frame_rel_action)

        ins_point_action = QAction(qta.icon('fa5s.crosshairs', color='#6c757d', disabled_color='#cccccc'), "Insertion Point...", self)
        ins_point_action.triggered.connect(self.on_assign_insertion_point)
        frame_menu.addAction(ins_point_action)

        end_offset_action = QAction(qta.icon('fa5s.arrows-alt-h', color='#6c757d', disabled_color='#cccccc'), "End Length Offsets...", self)
        end_offset_action.triggered.connect(self.on_assign_end_offsets)
        frame_menu.addAction(end_offset_action)

        frame_hinge_action = QAction(qta.icon('fa5s.dot-circle', color='#6c757d', disabled_color='#cccccc'), "Hinges...", self)
        frame_hinge_action.triggered.connect(self.on_assign_frame_hinge)
        frame_menu.addAction(frame_hinge_action)

        local_axis_action = QAction(qta.icon('fa5s.location-arrow', color='#6c757d', disabled_color='#cccccc'), "Local Axes...", self)
        local_axis_action.triggered.connect(self.on_assign_local_axis)
        frame_menu.addAction(local_axis_action)

        cable_menu = self.menu_assign.addMenu("Cable")
        cable_menu.setIcon(qta.icon('fa5s.bezier-curve', color='#6c757d', disabled_color='#cccccc'))

        cable_load_action = QAction(qta.icon('fa5s.stream', color='#6c757d', disabled_color='#cccccc'), "Distributed Loads...", self)
        cable_load_action.triggered.connect(self.on_assign_cable_load)
        cable_menu.addAction(cable_load_action)

        tendon_menu = self.menu_assign.addMenu("Tendon")
        tendon_menu.setIcon(qta.icon('fa5s.wave-square', color='#6c757d', disabled_color='#cccccc'))

        tendon_load_action = QAction(qta.icon('fa5s.arrow-down', color='#6c757d', disabled_color='#cccccc'), "Tendon Loads...", self)
        tendon_load_action.triggered.connect(self.on_assign_tendon_load)
        tendon_menu.addAction(tendon_load_action)

        self._menu_header(self.menu_assign, "Area Elements")
        self.menu_assign.addMenu(self.menu_assign_area)

        self.menu_analyze = menubar.addMenu("Analyze")
        self._menu_header(self.menu_analyze, "Run")

        self.action_analysis_opts = QAction(qta.icon('fa5s.sliders-h', color='#6c757d', disabled_color='#cccccc'), "Analysis Options...", self)
        self.action_analysis_opts.triggered.connect(self.on_analysis_options)
        self.menu_analyze.addAction(self.action_analysis_opts)

        self.menu_analyze.addAction(self.run_action)

        self.solid_run_action = QAction(qta.icon('fa5s.cube', color='#6c757d', disabled_color='#cccccc'), "Run Solid Analysis (Beta)...", self)
        self.solid_run_action.triggered.connect(self.on_run_solid_analysis)
        self.menu_analyze.addAction(self.solid_run_action)

        self._menu_header(self.menu_analyze, "Results")

        self.menu_analyze.addAction(self.btn_deform)

        self.action_deform_opts = QAction("Deformed Shape Options...", self)
        self.action_deform_opts.triggered.connect(self.on_view_deformed_shape)
        self.action_deform_opts.setEnabled(False)
        self.menu_analyze.addAction(self.action_deform_opts)

        self.action_display_forces = QAction(
            qta.icon('fa5s.chart-bar', color='#6c757d', disabled_color='#cccccc'),
            "Display Frame Forces...",
            self
        )
        self.action_display_forces.setEnabled(False)                               
        self.action_display_forces.triggered.connect(self.on_display_frame_forces)
        self.menu_analyze.addAction(self.action_display_forces)

        self.action_display_reactions = QAction(
            qta.icon('fa5s.anchor', color='#6c757d', disabled_color='#cccccc'),
            "Display Joint Reactions...",
            self
        )
        self.action_display_reactions.setEnabled(False)
        if hasattr(self, 'sound_effect') and self.sound_effect.isPlaying():
            self.sound_effect.stop()
        self.action_display_reactions.triggered.connect(self.on_display_joint_reactions)
        self.menu_analyze.addAction(self.action_display_reactions)

        self.action_plot_functions = QAction(
            qta.icon('fa5s.chart-line', color='#6c757d', disabled_color='#cccccc'),
            "Plot Functions...",
            self
        )
        self.action_plot_functions.setEnabled(False)
        self.action_plot_functions.triggered.connect(self.on_display_plot_functions)
        self.menu_analyze.addAction(self.action_plot_functions)
        self.res_action = QAction(qta.icon('fa5s.table', color='#6c757d', disabled_color='#cccccc'), "Show Result Tables...", self)
        self.res_action.setShortcut("Ctrl+T")
        self.res_action.triggered.connect(self.on_show_modal_results)
        self.menu_analyze.addAction(self.res_action)
        self._menu_header(self.menu_analyze, "Nonlinear & Diagnostics")

        self.action_pushover_curve = QAction(
            qta.icon('fa5s.chart-area', color='#6c757d', disabled_color='#cccccc'),
            "Show Static Pushover Curve...",
            self
        )
        self.action_pushover_curve.setEnabled(False)
        self.action_pushover_curve.triggered.connect(self.on_show_pushover_curve)
        self.menu_analyze.addAction(self.action_pushover_curve)

        self.action_hinge_results = QAction(
            qta.icon('fa5s.bezier-curve', color='#6c757d', disabled_color='#cccccc'),
            "Show Hinge Results...",
            self
        )
        self.action_hinge_results.setEnabled(False)
        self.action_hinge_results.triggered.connect(self.on_show_hinge_results)
        self.menu_analyze.addAction(self.action_hinge_results)

        self.action_os_diag = QAction(
            qta.icon('fa5s.stethoscope', color='#6c757d', disabled_color='#cccccc'),
            "Show OpenSees Diagnostics...",
            self
        )
        self.action_os_diag.setEnabled(False)
        self.action_os_diag.triggered.connect(self.on_show_os_diagnostics)
        self.menu_analyze.addAction(self.action_os_diag)

        self.menu_options = menubar.addMenu("Options")
        
        gfx_action = QAction(qta.icon('fa5s.desktop', color='#6c757d', disabled_color='#cccccc'), "Graphics Preferences...", self)
        gfx_action.triggered.connect(self.on_graphics_options)
        self.menu_options.addAction(gfx_action)

        self.menu_help = menubar.addMenu("Help")
        
        update_action = QAction(qta.icon('fa5s.cloud-download-alt', color='#6c757d', disabled_color='#cccccc'), "Check for Updates...", self)
        update_action.triggered.connect(self.on_check_updates)
        nav_help_action = QAction(qta.icon('fa5s.mouse', color='#6c757d', disabled_color='#cccccc'),
                                  "Navigation Controls", self)
        nav_help_action.triggered.connect(self.on_show_navigation_help)
        self.menu_help.addAction(nav_help_action)
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

        self.model_tree = ModelTreeDock(self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.model_tree)
        self.model_tree.selection_requested.connect(self._on_tree_selection_requested)
        self.model_tree.delete_requested.connect(self._delete_tree_selection)
        
        self.setup_statusbar()

        from app.ui.nav_hints import NavHintOverlay
        self.nav_hint = NavHintOverlay(
            self.canvas_frame1, watch=self.canvas,
            extra_hint=("Type", "Run a command"))

    def on_toggle_nav_hint(self):
        """F1 / ? button: toggle the on-canvas chip."""
        wo = getattr(self, 'welcome_overlay', None)
        if wo is not None and wo.isVisible():
            self.on_show_navigation_help()                                                
        else:
            self.nav_hint.toggle()

    def on_show_navigation_help(self):
        """Help > Navigation Controls: show the bottom-left chip (dialog only if no model is open)."""
        wo = getattr(self, 'welcome_overlay', None)
        if wo is not None and wo.isVisible():
            from app.ui.nav_hints import navigation_help_html
            QMessageBox.information(self, "Navigation Controls", navigation_help_html())
        else:
            self.nav_hint.show_hint()

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
                                                              
                    self._hidden_dialogs.append((widget, widget.geometry()))
                    widget.hide()

        elif state == Qt.ApplicationState.ApplicationActive:
                                                      
            for dlg, geom in getattr(self, '_hidden_dialogs', []):
                if dlg is not None and not dlg.isModal():
                                                                           
                    dlg.setGeometry(geom)
                    dlg.show()
            self._hidden_dialogs = []

    def on_select_all(self):
        if not self.model: return
        self.selected_ids = self._filter_pickable('frame', self.model.elements.keys())
        self.selected_node_ids = self._filter_pickable('node', self.model.nodes.keys())
        self.selected_area_ids = self._filter_pickable('area', self.model.area_elements.keys()) if hasattr(self.model, 'area_elements') else []
        self.selected_link_ids = self._filter_pickable('link', self.model.links.keys()) if hasattr(self.model, 'links') else []          
        
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
        self.selected_tendon_ids = []
        self.selected_cable_ids = []

        if hasattr(self, 'canvas'):
            self.canvas.clear_hover_popup()
            self.canvas.selected_tendon_ids = []
            self.canvas.selected_cable_ids = []
        if getattr(self, 'canvas2', None):
            self.canvas2.selected_tendon_ids = []
            self.canvas2.selected_cable_ids = []

        self._refresh_selection_overlay()
        self.status.showMessage("Selection Cleared")

    def on_invert_selection(self):
        if not self.model:
            return
        all_eids = set(self.model.elements.keys())
        all_nids = set(self.model.nodes.keys())
        self.selected_ids = self._filter_pickable('frame', all_eids - set(self.selected_ids))
        self.selected_node_ids = self._filter_pickable('node', all_nids - set(self.selected_node_ids))
        
        if hasattr(self.model, 'area_elements'):
            all_aids = set(self.model.area_elements.keys())
            self.selected_area_ids = self._filter_pickable('area', all_aids - set(self.selected_area_ids))
            
        self._refresh_selection_overlay()
        self.status.showMessage(
            f"Inverted: {len(self.selected_ids)} Frames, "
            f"{len(self.selected_node_ids)} Joints, "
            f"{len(self.selected_area_ids)} Areas")

    def _selection_canvases(self):
        """Canvases that actually need a selection refresh (hidden canvas2 is synced when shown)."""
        cvs = [self.canvas]
        if getattr(self, 'canvas2_visible', False):
            cvs.append(self.canvas2)
        return cvs

    def _refresh_selection_overlay(self):
        for cvs in [self.canvas, self.canvas2]:
            cvs.update_selection_overlay(self.selected_ids, self.selected_node_ids, self.selected_area_ids, getattr(self, 'selected_link_ids', []), getattr(self, 'selected_tendon_ids', []))

    def _toolbar_zoom_in(self):
        """Zoom in button — simulates a scroll-up at canvas centre."""
        w, h = self.active_canvas.width(), self.active_canvas.height()
        self.active_canvas.camera.zoom(120, w / 2, h / 2, w, h)

    def _toolbar_zoom_out(self):
        """Zoom out button — simulates a scroll-down at canvas centre."""
        w, h = self.active_canvas.width(), self.active_canvas.height()
        self.active_canvas.camera.zoom(-120, w / 2, h / 2, w, h)

    def _toolbar_toggle_animation(self):
        """▶ Animate button — toggles play/pause directly."""
        if not self.model or not self.model.has_results:
            QMessageBox.warning(self, "No Results", "Please run the analysis first.")
            return

        mgr = getattr(self.active_canvas, 'animation_manager', None)
        is_animating = mgr.is_running if mgr else False

        self.toggle_animation(not is_animating, False)

        dlg = getattr(self, '_deformed_dlg', None)
        if dlg and dlg.isVisible():
            dlg.btn_animate.setChecked(not is_animating)
            dlg.update_anim_button_style()

    def on_mouse_moved(self, x, y, z):
        self.lbl_coords.setText(f"X: {x:.2f}  Y: {y:.2f}  Z: {z:.2f}")
        if getattr(self, 'draw_area_mode_active', False) and len(self._current_area_nodes) > 0:
            self.active_canvas.update_area_preview(list(self._current_area_nodes), x, y, z)

    def _snap_summary(self):
        names = {'grid': 'Grid', 'joints': 'Joints', 'midpoints': 'Midpoints'}
        on = [names[k] for k, a in self.snap_actions.items() if a.isChecked()]
        return "Snap: " + (", ".join(on) if on else "Off")

    def _apply_snap_settings(self):
        """Push snap options to both viewports and refresh the status-bar button."""
        opts = {k: a.isChecked() for k, a in self.snap_actions.items()}
        radius = float(self.graphics_settings.get('snap_radius', 25.0))
        for cv in (getattr(self, 'canvas', None), getattr(self, 'canvas2', None)):
            if cv is not None:
                cv.set_snap_options(radius=radius, **opts)
        if hasattr(self, 'btn_snap_status'):
            self.btn_snap_status.setText(self._snap_summary())

    def _save_snap_prefs(self):
        import json as _json
        path = os.path.join(os.path.expanduser("~"), ".OpenStructures_prefs.json")
        try:
            data = {}
            if os.path.exists(path):
                with open(path) as f:
                    data = _json.load(f)
            for k in ('snap_grid', 'snap_joints', 'snap_midpoints', 'snap_radius'):
                if k in self.graphics_settings:
                    data[k] = self.graphics_settings[k]
            with open(path, 'w') as f:
                _json.dump(data, f)
        except Exception:
            pass

    def on_snap_toggled(self, key, checked):
        if not checked and not any(a.isChecked() for k, a in self.snap_actions.items() if k != key):
            self.snap_actions[key].blockSignals(True)
            self.snap_actions[key].setChecked(True)
            self.snap_actions[key].blockSignals(False)
            self.status.showMessage("At least one snap type must stay enabled.")
            return
        self.graphics_settings[f'snap_{key}'] = bool(checked)
        self._save_snap_prefs()
        self._apply_snap_settings()
        self.status.showMessage(self._snap_summary())

    def on_snap_radius(self):
        from PyQt6.QtWidgets import QInputDialog
        cur = int(self.graphics_settings.get('snap_radius', 25))
        val, ok = QInputDialog.getInt(self, "Snap Radius", "Snap distance in screen pixels:", cur, 5, 100, 1)
        if ok:
            self.graphics_settings['snap_radius'] = val
            self._save_snap_prefs()
            self._apply_snap_settings()
            self.status.showMessage(f"Snap radius: {val} px")

    def setup_statusbar(self):
        from PyQt6.QtWidgets import QSlider, QSpinBox, QToolButton

        self.status = self.statusBar()
        self.status.showMessage("Welcome. Please create or open a model.")
        
        self.lbl_coords = QLabel("X: 0.00  Y: 0.00  Z: 0.00")
        self.lbl_coords.setStyleSheet("padding-right: 15px;")
        self.status.addPermanentWidget(self.lbl_coords)

        self.btn_snap_status = QToolButton()
        self.btn_snap_status.setAutoRaise(True)
        self.btn_snap_status.setToolTip("Snap options (click to change)")
        self.btn_snap_status.setMenu(self.menu_snap)
        self.btn_snap_status.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_snap_status.setStyleSheet("QToolButton::menu-indicator { image: none; } QToolButton { padding: 0 10px; }")
        self.status.addPermanentWidget(self.btn_snap_status)
        self._apply_snap_settings()

        self.combo_result_cases = QComboBox()
        self.combo_result_cases.setToolTip("Active Result Case / Mode")
        self.combo_result_cases.setMinimumWidth(190)
        self.combo_result_cases.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo_result_cases.setVisible(False)
        self.combo_result_cases.currentIndexChanged.connect(self.on_statusbar_result_case_changed)
        self.status.addPermanentWidget(self.combo_result_cases)

        self._syncing_status_scrubber = False
        self.status_scrubber_widget = QWidget()
        scrub_layout = QHBoxLayout(self.status_scrubber_widget)
        scrub_layout.setContentsMargins(4, 0, 8, 0)
        scrub_layout.setSpacing(5)

        self.lbl_status_step = QLabel("Step:")
        self.slider_status_step = QSlider(Qt.Orientation.Horizontal)
        self.slider_status_step.setFixedWidth(110)
        self.spin_status_step = QSpinBox()
        self.spin_status_step.setFixedWidth(60)
        self.lbl_status_step_total = QLabel("/ 1")

        self.slider_status_step.valueChanged.connect(self._on_status_scrubber_changed)
        self.spin_status_step.valueChanged.connect(self._on_status_scrubber_changed)

        scrub_layout.addWidget(self.lbl_status_step)
        scrub_layout.addWidget(self.slider_status_step)
        scrub_layout.addWidget(self.spin_status_step)
        scrub_layout.addWidget(self.lbl_status_step_total)
        self.status_scrubber_widget.setVisible(False)
        self.status.addPermanentWidget(self.status_scrubber_widget)

        for _seq, _delta in (("Ctrl+Left", -1), ("Ctrl+Right", 1)):
            _act = QAction(self)
            _act.setShortcut(_seq)
            _act.triggered.connect(lambda _=False, d=_delta: self._step_statusbar_scrubber(d))
            self.addAction(_act)

        self.cad_mode_cb = QCheckBox("⌨ Commands")
        self.cad_mode_cb.setChecked(True)
        self.cad_mode_cb.setToolTip("Type anywhere on the canvas to search and run commands")
        self.cad_mode_cb.setStyleSheet("padding-right: 10px;")
        self.status.addPermanentWidget(self.cad_mode_cb)
                                   
        self.combo_units = QComboBox()
        self.combo_units.addItems(UNIT_SYSTEMS)
                          
        self.combo_units.setCurrentIndex(0)
        self.combo_units.setToolTip("Global Display Units")
        
        self.combo_units.currentIndexChanged.connect(self.on_units_changed)
        
        self.status.addPermanentWidget(self.combo_units)

    def _hide_statusbar_results_widgets(self):
        if hasattr(self, 'combo_result_cases'):
            self.combo_result_cases.blockSignals(True)
            self.combo_result_cases.clear()
            self.combo_result_cases.setVisible(False)
            self.combo_result_cases.blockSignals(False)
        if hasattr(self, 'status_scrubber_widget'):
            self.status_scrubber_widget.setVisible(False)

    def _sync_statusbar_scrubber_range(self):
        """Shows or hides the statusbar scrubber depending on whether the current case has multiple steps."""
        if not hasattr(self, 'status_scrubber_widget'):
            return

        data_info = self.combo_result_cases.currentData() if hasattr(self, 'combo_result_cases') else None
        is_live = isinstance(data_info, dict) and data_info.get("mode") == "LTHA_LIVE"
        if not is_live or not self.model or not self.model.results:
            self.status_scrubber_widget.setVisible(False)
            return

        saved_states = self.model.results.get("saved_states")
        if saved_states:
            n_steps = len(saved_states)
            init_step = int(getattr(self.canvas, 'ltha_current_step', n_steps - 1))
        else:
            n_steps = int(getattr(self.canvas, 'ltha_n_steps', 1))
            init_step = int(getattr(self.canvas, 'ltha_current_step', 0))

        if n_steps <= 1:
            self.status_scrubber_widget.setVisible(False)
            return

        init_step = max(0, min(init_step, n_steps - 1))
        self._syncing_status_scrubber = True
        for w in (self.slider_status_step, self.spin_status_step):
            w.setRange(0, n_steps - 1)
            w.setValue(init_step)
        self.lbl_status_step_total.setText(f"/ {n_steps - 1}")
        self._syncing_status_scrubber = False
        self.status_scrubber_widget.setVisible(True)

    def _on_status_scrubber_changed(self, value):
        if getattr(self, '_syncing_status_scrubber', False):
            return
        self._syncing_status_scrubber = True
        self.slider_status_step.setValue(value)
        self.spin_status_step.setValue(value)
        self._syncing_status_scrubber = False

        mgr = getattr(self.active_canvas, 'animation_manager', None)
        if mgr and getattr(self.active_canvas, 'ltha_mode', False):
            self._syncing_status_scrubber = True
            try:
                mgr.scrub_to_step(int(value))
            finally:
                self._syncing_status_scrubber = False

    def _get_result_case_meta(self, path):
        """Light metadata for one results file, cached by (mtime, size) so the
        dropdown never re-parses big JSON files that haven't changed."""
        import os, json
        try:
            st = os.stat(path)
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

        cache = self.__dict__.setdefault('_result_meta_cache', {})
        hit = cache.get(path)
        if hit and hit[0] == sig:
            return hit[1]

        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception:
            return None

        info = data.get("info", {}) or {}
        meta = {
            "status": data.get("status"),
            "type": info.get("type", ""),
            "modes": list((data.get("mode_shapes") or {}).keys()),
            "has_rsa": "rsa_info" in data,
            "geom": info.get("geom_nonlin", "None"),
            "multistep": bool(data.get("saved_states")),
        }
        cache[path] = (sig, meta)
        return meta

    def _populate_statusbar_result_cases(self):
        import os, glob
        if not hasattr(self, 'combo_result_cases'):
            return

        combo = self.combo_result_cases
        combo.blockSignals(True)
        combo.clear()

        if not self.model or not getattr(self.model, 'has_results', False) or not getattr(self.model, 'file_path', None):
            combo.setVisible(False)
            if hasattr(self, 'status_scrubber_widget'):
                self.status_scrubber_widget.setVisible(False)
            combo.blockSignals(False)
            return

        def add_item(text, data):
            combo.addItem(text, data)
            combo.setItemData(combo.count() - 1, text, Qt.ItemDataRole.ToolTipRole)

        base_name = os.path.splitext(self.model.file_path)[0]
        result_files = getattr(self.model, 'valid_result_paths', [])
        if not result_files:
            result_files = glob.glob(f"{base_name}_*_results.json")

        current_res = self.model.results or {}
        current_case_name = current_res.get("info", {}).get("case_name", "")
        target_idx = 0

        for path in sorted(result_files):
            fname = os.path.basename(path)
            prefix = os.path.basename(base_name) + "_"
            case_name = fname[len(prefix):].replace("_results.json", "")

            meta = self._get_result_case_meta(path)
            if meta is None or meta["status"] == "FAILED":
                continue

            info_type = meta["type"]

            if info_type in ["Modal Analysis", "Buckling Analysis"]:
                first_mode_for_case = True
                for mode_key in meta["modes"]:
                    add_item(f"{case_name} - {mode_key}", {"path": path, "mode": mode_key})
                    if case_name == current_case_name and first_mode_for_case:
                        target_idx = combo.count() - 1
                        first_mode_for_case = False
            else:
                display_name = f"{case_name}"
                is_nl_multistep = (info_type == "Nonlinear Static" and meta["multistep"])
                if meta["has_rsa"]:
                    display_name += " (RSA Envelope)"
                elif info_type == "Linear Time History Analysis":
                    display_name += " (LTHA Envelope)"
                elif info_type == "Nonlinear Static":
                    display_name += f" ({meta['geom']})"

                mode_for_item = "LTHA_LIVE" if is_nl_multistep else "MAIN"
                add_item(display_name, {"path": path, "mode": mode_for_item})
                if case_name == current_case_name:
                    target_idx = combo.count() - 1

                if info_type == "Linear Time History Analysis":
                    add_item(f"{case_name} - LTHA Live", {"path": path, "mode": "LTHA_LIVE"})
                    if case_name == current_case_name and getattr(self.canvas, 'ltha_mode', False):
                        target_idx = combo.count() - 1

        has_items = combo.count() > 0
        combo.setVisible(has_items)
        if has_items:
            combo.setCurrentIndex(target_idx)
            combo.setToolTip(combo.currentText())
            self._last_result_case_index = target_idx
        combo.blockSignals(False)
        self._sync_statusbar_scrubber_range()

    def _apply_result_case(self, data_info):
        """Shared case/mode switch used by the status-bar dropdown.
        Returns True on success. On failure the current view is left untouched
        and a message is shown in the status bar."""
        import os, json

        path = data_info.get("path", "")
        key = data_info.get("mode")
        label = os.path.basename(path) or "result file"

        try:
            with open(path, 'r') as f:
                new_res = json.load(f)
        except FileNotFoundError:
            self.status.showMessage(f"Result file not found: {label}", 8000)
            return False
        except Exception as e:
            self.status.showMessage(f"Could not load {label}: {e}", 8000)
            return False

        for cvs in (self.canvas, getattr(self, 'canvas2', None)):
            if cvs is not None:
                if hasattr(cvs, 'clear_force_diagrams'):
                    cvs.clear_force_diagrams()
                if hasattr(cvs, 'clear_reaction_diagram'):
                    cvs.clear_reaction_diagram(self.model)

        if hasattr(self.canvas, 'set_selection_ltha_live'):
            self.canvas.set_selection_ltha_live(key == "LTHA_LIVE")

        if "displacements" in new_res:
            new_res["_base_displacements"] = new_res["displacements"].copy()
        self.solver_output_path = path
        self.model.results = new_res
        self.model.has_results = True

        if key == "MAIN":
            self.switch_modal_view("MAIN_RESULT")
        elif key == "LTHA_LIVE":
            self.switch_modal_view("LTHA_LIVE")
        elif str(key).startswith("Mode"):
            self.switch_modal_view(key)
        return True

    def _select_statusbar_case(self, data_info):
        """Select the matching item in the status-bar dropdown WITHOUT reloading
        anything (used when another dialog already switched the case)."""
        combo = getattr(self, 'combo_result_cases', None)
        if combo is None or not isinstance(data_info, dict):
            return
        for i in range(combo.count()):
            d = combo.itemData(i)
            if isinstance(d, dict) and d.get("path") == data_info.get("path") and d.get("mode") == data_info.get("mode"):
                combo.blockSignals(True)
                combo.setCurrentIndex(i)
                combo.setToolTip(combo.itemText(i))
                combo.blockSignals(False)
                self._last_result_case_index = i
                break
        self._sync_statusbar_scrubber_range()

    def on_statusbar_result_case_changed(self, index):
        if index < 0 or not self.model:
            return
        data_info = self.combo_result_cases.currentData()
        if not isinstance(data_info, dict):
            return

        if not self._apply_result_case(data_info):
                                                                        
            prev = getattr(self, '_last_result_case_index', -1)
            if 0 <= prev < self.combo_result_cases.count():
                self.combo_result_cases.blockSignals(True)
                self.combo_result_cases.setCurrentIndex(prev)
                self.combo_result_cases.blockSignals(False)
            return

        self._last_result_case_index = index
        self.combo_result_cases.setToolTip(self.combo_result_cases.currentText())
        self._sync_statusbar_scrubber_range()
        self._sync_node_dialog_to_case(data_info)

    def _sync_node_dialog_to_case(self, data_info):
        """Status bar -> NodeResultsDialog."""
        dlg = getattr(self, '_node_res_dlg', None)
        if dlg is None or not dlg.isVisible():
            return
        key = data_info["mode"]
        dlg.results = self.model.results
        dlg.combo_cases.blockSignals(True)
        for i in range(dlg.combo_cases.count()):
            if dlg.combo_cases.itemData(i) == data_info:
                dlg.combo_cases.setCurrentIndex(i)
                break
        dlg.combo_cases.blockSignals(False)
        if key == "MAIN":
            base_dict = self.model.results.get("_base_displacements", self.model.results.get("displacements", {}))
            dlg.scrubber_widget.setVisible(False)
            dlg._update_labels(base_dict.get(dlg.node_id, [0.0] * 6))
        elif key == "LTHA_LIVE":
            dlg.update_live_values()
        elif str(key).startswith("Mode"):
            dlg.scrubber_widget.setVisible(False)
            shapes = self.model.results.get("mode_shapes", {})
            dlg._update_labels(shapes.get(key, {}).get(dlg.node_id, [0.0] * 6))

    def _on_node_dialog_case_changed(self, _index=None):
        """NodeResultsDialog -> status bar (keeps both dropdowns in sync)."""
        dlg = getattr(self, '_node_res_dlg', None)
        if dlg is None:
            return
        try:
            data = dlg.combo_cases.currentData()
        except RuntimeError:                          
            return
        self._select_statusbar_case(data)

    def _step_statusbar_scrubber(self, delta):
        """Keyboard stepping (Ctrl+Left / Ctrl+Right)."""
        if not hasattr(self, 'status_scrubber_widget') or not self.status_scrubber_widget.isVisible():
            return
        sl = self.slider_status_step
        sl.setValue(max(sl.minimum(), min(sl.maximum(), sl.value() + delta)))

    def _create_welcome_overlay(self):
        from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget, QLabel, QFrame, QGraphicsOpacityEffect
        from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
        from app.ui.theme import COLORS                                    

        self.welcome_overlay = QWidget(self.canvas_splitter)
        self.welcome_overlay.setObjectName("welcome_overlay_root")
        
        self.welcome_overlay.setStyleSheet(f"""
            #welcome_overlay_root {{
                background-color: {COLORS["bg_panel"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 4px;
            }}
        """)

        root_layout = QVBoxLayout(self.welcome_overlay)
        root_layout.setContentsMargins(32, 32, 32, 24)
        root_layout.setSpacing(0)

        branding = QLabel()
        branding.setAlignment(Qt.AlignmentFlag.AlignLeft)
        branding.setTextFormat(Qt.TextFormat.RichText)
        branding.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        branding.setText(
            f"<div style='font-family: \"Segoe UI\", sans-serif;'>"
            f"<div style='font-size: 26px; font-weight: 300; color: {COLORS['text_primary']}; letter-spacing: 1px;'>"
            f"Open<span style='font-weight: 700; color: #005A9E;'>//Structures</span></div>"
            f"<div style='font-size: 11px; color: {COLORS['text_secondary']}; margin-top: 4px; font-weight: 600; letter-spacing: 1px;'>"
            f"STRUCTURAL ANALYSIS &amp; DESIGN PLATFORM</div>"
            f"<div style='margin-top: 24px; font-size: 13px; color: {COLORS['text_primary']};'>Status: Ready. No model loaded.</div>"
            f"<div style='margin-top: 12px; font-size: 12px; color: {COLORS['text_primary']};'>"
            f"<span style='color: #005A9E; font-family: Consolas, monospace; font-weight: 600;'>Ctrl+N</span> New Model "
            f"&nbsp;&nbsp;&nbsp;&nbsp; "
            f"<span style='color: #005A9E; font-family: Consolas, monospace; font-weight: 600;'>Ctrl+O</span> Open File"
            f"&nbsp;&nbsp;&nbsp;&nbsp; "
            f"<span style='color: #005A9E; font-family: Consolas, monospace; font-weight: 600;'>F1</span> Viewport Controls"
            f"</div></div>"
        )
        root_layout.addWidget(branding)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {COLORS['border']}; max-height: 1px; margin-top: 20px; margin-bottom: 16px;")
        root_layout.addWidget(sep)

        whats_new_lbl = QLabel("SYSTEM LOG // RELEASE NOTES")
        whats_new_lbl.setStyleSheet(
            f"font-family: 'Segoe UI'; font-size: 10px; font-weight: 700; color: {COLORS['text_secondary']}; letter-spacing: 1.5px; margin-bottom: 8px;"
        )
        root_layout.addWidget(whats_new_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QWidget#notes_container {{ background: transparent; }}
            QScrollBar:vertical {{
                background: {COLORS["bg_dialog"]}; width: 10px; margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS["border"]}; min-height: 20px; border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {COLORS["text_disabled"]};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)

        notes_container = QWidget()
        notes_container.setObjectName("notes_container")
        notes_layout = QVBoxLayout(notes_container)
        notes_layout.setContentsMargins(0, 0, 16, 0)
        notes_layout.setSpacing(0)

        if NOTICES:
            notice_box = QWidget()
            notice_box.setObjectName("notice_box")                       
            
            notice_box.setStyleSheet(f"""
                #notice_box {{
                background-color: {COLORS['bg_table_alt']};
                border-left: 3px solid #005A9E;
                border-radius: 3px;
            }}
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
                    f"<span style='font-family: \"Segoe UI\"; font-size: 12px; color: {COLORS['text_primary']};'>{detail}</span>"
                )
                detail_lbl.setTextFormat(Qt.TextFormat.RichText)
                detail_lbl.setWordWrap(True)
                notice_layout.addWidget(detail_lbl)

            notes_layout.addWidget(notice_box)
            notes_layout.addSpacing(16)

        TAG_STYLES = {
            "new": (f"color: #005A9E; font-family: Consolas, monospace; font-weight: bold;", "[+] NEW "),
            "fix": (f"color: {COLORS['text_secondary']}; font-family: Consolas, monospace; font-weight: bold;", "[~] FIX "),
            "impr": (f"color: {COLORS['text_secondary']}; font-family: Consolas, monospace; font-weight: bold;", "[•] IMPR"),
        }

        for i, release in enumerate(RELEASE_NOTES):
            ver_lbl = QLabel(
                f"<span style='font-family: Consolas, monospace; font-weight: 700; font-size: 13px; color: #005A9E;'>"
                f"v{release['version']}</span>"
                f"&nbsp;&nbsp;<span style='font-family: Consolas, monospace; font-size: 11px; color: {COLORS['text_secondary']};'>"
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
                    f"&nbsp;&nbsp;<span style='font-family: \"Segoe UI\"; color: {COLORS['text_primary']};'>{text}</span></span>"
                )
                item_lbl.setTextFormat(Qt.TextFormat.RichText)
                item_lbl.setWordWrap(True)
                item_lbl.setContentsMargins(0, 2, 0, 2)
                notes_layout.addWidget(item_lbl)

            if i < len(RELEASE_NOTES) - 1:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.HLine)
                div.setStyleSheet(f"background-color: {COLORS['border']}; max-height: 1px; margin-top: 12px; margin-bottom: 8px;")
                notes_layout.addWidget(div)

        notes_layout.addStretch()
        scroll.setWidget(notes_container)
        root_layout.addWidget(scroll, 1)

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

        splitter = self.canvas_splitter
        sw = splitter.width()
        sh = splitter.height()
        sx = splitter.pos().x()
        sy = splitter.pos().y()

        right_x = sx + sw // 2
        right_w = sw - sw // 2

        w = min(420, right_w - 40)
        h = min(420, sh - 60)
        x = right_x + (right_w - w) // 2
        y = sy + (sh - h) // 2

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

        if (self.model is not None and hasattr(self, 'nav_hint')
                and not getattr(self, '_nav_hint_armed', False)):
            self._nav_hint_armed = True
            self.nav_hint.auto_show()

        self.menu_define.setEnabled(editable)
        self.menu_draw.setEnabled(editable)
        self.menu_assign.setEnabled(editable)
        self.run_action.setEnabled(editable)
        self.solid_run_action.setEnabled(editable)
        self.res_action.setEnabled(not editable)
        self.menu_analyze.setEnabled(editable or self.model is not None)

        if hasattr(self, 'sidebar'):
            self.sidebar.setEnabled(editable)
            
            if hasattr(self, 'draw_action_group'):
                self.draw_action_group.setEnabled(editable)
                
            if not editable:
                                                                                                
                self._on_sidebar_select_mode()

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
                                                      
            ui_theme = self.graphics_settings.get("ui_theme", "Light")
            idle_c = QColor(30, 30, 30) if ui_theme == "Dark" else QColor('#F8F9FA')
            
            self.canvas.setBackgroundColor(idle_c)
            if getattr(self, 'canvas2_visible', False) and hasattr(self, 'canvas2'):
                self.canvas2.setBackgroundColor(idle_c)
                
            if self.model is None:
                self.status.showMessage("Ready. Create a new model or open an existing file to begin.")
            else:
                self.status.showMessage("Model Locked. Results Mode.")
        else:
            bg_tuple = self.graphics_settings.get("background_color", (1.0, 1.0, 1.0, 1.0))
            c = QColor()
            c.setRgbF(bg_tuple[0], bg_tuple[1], bg_tuple[2], bg_tuple[3])
            
            self.canvas.setBackgroundColor(c)
            if getattr(self, 'canvas2_visible', False) and hasattr(self, 'canvas2'):
                self.canvas2.setBackgroundColor(c)
                
            self.status.showMessage("Model Unlocked. Ready to edit.")

    def on_units_changed(self, index, redraw=True):
        unit_text = self.combo_units.currentText()
        
        unit_registry.set_unit_system(unit_text)
        
        self.status.showMessage(f"Units changed to: {unit_text}")
        
        if self.model:
                                                                              
            if redraw:
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
        self._update_quick_area_plane_status()

        self.update_linked_planes()

    def _reset_plane_buttons(self):
        for axis in ("XY", "XZ", "YZ"):
            btn = getattr(self, f'btn_{axis.lower()}')
            btn.setChecked(False)
            self._set_plane_button_state(axis, 0)
        self.active_canvas._plane_state = 0

    def _set_plane_button_state(self, axis, state):
        """Recolors a plane button (XY/XZ/YZ) and updates its icon dots +
        tooltip to reflect where it currently sits in its 3-click cycle,
        and what the next click will do."""
        btn = getattr(self, f'btn_{axis.lower()}')
        btn.setIcon(create_plane_icon(axis, state))

        label = PLANE_STATE_LABELS.get(state)
        hint = PLANE_STATE_NEXT_HINT.get(state, "")
        base_name = {"XY": "XY Plan", "XZ": "XZ Elev", "YZ": "YZ Elev"}[axis]
        if label:
            btn.setToolTip(f"{base_name} — {label} · {hint}")
        else:
            btn.setToolTip(f"{base_name} — {hint}")

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
            self._set_plane_button_state(axis, 1)
            self.update_view_layer()
            self.status.showMessage(f"View: {axis} — Plane (Ghost ON)")
    
        elif cvs._plane_state == 1:
                                                                              
            cvs.show_ghost_structure = False
            cvs._plane_state = 2
            self._set_plane_button_state(axis, 2)
            self.refresh_canvas()
            self.status.showMessage(f"View: {axis} — Strict Plane Only")

        elif cvs._plane_state == 2:
                                                                               
            cvs._plane_state = 3
            cvs.show_ghost_structure = False                          
            cvs.set_standard_view(axis)
            self._set_plane_button_state(axis, 3)
            self.refresh_canvas()
            self.status.showMessage(f"View: {axis} — Ortho 2D")

        else:
                                                                               
            cvs.show_ghost_structure = True
            cvs._plane_state = 1
            cvs._grid_index = 0
            self._set_plane_button_state(axis, 1)
            self.update_view_layer()
            self.status.showMessage(f"View: {axis} — Plane (Ghost ON)")
        
        self._restore_force_diagram_if_active()
        self._update_quick_area_plane_status()
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

        if not grid_list:
            cvs.active_view_plane = None
            self._update_quick_area_plane_status()
            return

        cvs._grid_index = max(0, min(cvs._grid_index, len(grid_list) - 1))
        val = grid_list[cvs._grid_index]
        cvs.active_view_plane = {'axis': axis, 'value': val}
        if self.model: self.draw_both_canvases()
        self.status.showMessage(f"Filtered View: {cvs._view_mode} @ {axis.upper()}={val:.2f}m")
        if self.cross_brace_dialog:
            self.cross_brace_dialog.update_plane_status(cvs.active_view_plane)
        self._update_quick_area_plane_status()
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
        self._update_quick_area_plane_status()

        self.update_linked_planes()

    def _purge_results_and_visuals(self):
        """Silently purges all post-processing visuals, locks, and GPU buffers for a fresh file."""
        if getattr(self, 'quick_area_mode_active', False):
            self.on_quick_area_finished()
        self._view_overrides = {}
        self.is_locked = False
        self._hide_statusbar_results_widgets()
        self.btn_deform.setEnabled(False)
        self.btn_deform.setChecked(False)
        self.action_display_forces.setEnabled(False)
        self.action_display_reactions.setEnabled(False)
        self.action_plot_functions.setEnabled(False)
        self.action_pushover_curve.setEnabled(False)
        self.action_hinge_results.setEnabled(False)
        self.action_os_diag.setEnabled(False)
        
        self.btn_lock.setIcon(qta.icon('fa5s.unlock', color='#6c757d', disabled_color='#cccccc'))
        self.btn_lock.setToolTip("Model is editable.")
        
        for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
            if cvs is not None:
                if hasattr(cvs, 'clear_force_diagrams'):
                    cvs.clear_force_diagrams()
                if hasattr(cvs, 'clear_reaction_diagram'):
                    cvs.clear_reaction_diagram(self.model)
                cvs.view_deflected = False
                cvs.set_view_overrides({})
                cvs.anim_factor = 0.0
                cvs.invalidate_animation_cache()
                if hasattr(cvs, 'animation_manager') and cvs.animation_manager:
                    cvs.animation_manager.stop_animation()
                if hasattr(cvs, 'clear_ltha_history'):
                    cvs.clear_ltha_history()

    def on_new_model(self):
        if not self._check_unsaved_changes():
            return
        from app.dialogs.new_model_dialog import NewModelDialog
        dialog = NewModelDialog(self)
        if dialog.exec(): 
            if dialog.accepted_data:
                self._purge_results_and_visuals()                
                data = dialog.grid_data
                self.model = StructuralModel(dialog.project_name)
                self._history_controller.reset()
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
                
                self.undo_stack.resetClean()
                self.status.showMessage(f"Created: {self.model.name}. Units: {dialog.selected_units}")
                self.update_window_title()
                self.model_tree.refresh()

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
                                                                                         
            _cv = self.canvas
            if getattr(_cv, 'reaction_diagram_active', False):
                _grid = getattr(_cv, '_pre_reaction_was_grid', _cv.show_grid)
            elif getattr(_cv, '_pre_force_was_grid', False):
                _grid = True
            else:
                _grid = _cv.show_grid
            self.graphics_settings['show_grid']            = bool(_grid)
            self.graphics_settings['show_ghost_structure'] = _cv.show_ghost_structure
            self.graphics_settings['show_hinges']          = getattr(_cv, 'show_hinges', True)
            QApplication.processEvents()
    
            dlg.stage("Preparing model data...")
            model_graphics = self.graphics_settings.copy()
            model_graphics.pop("glass_strength", None)                                           
            model_graphics.pop("glass_transparency", None)
            model_graphics.pop("msaa_level", None)
            model_graphics.pop("fxaa_strength", None)
            for _ck in _CROSSHAIR_KEYS:
                model_graphics.pop(_ck, None)
            self.model.graphics_settings = model_graphics
            QApplication.processEvents()
    
            def _report(msg):
                dlg.stage(msg)
                QApplication.processEvents()

            self._history_controller.before_save(filename)
            atomic_save_model(self.model, filename, progress=_report)
                                     
            dlg.stage("Finalizing...")
            self.model.file_path        = filename
            self.model.active_model_path = filename
            self.undo_stack.setClean()
            self.status.showMessage(f"Saved: {filename}")
            self.update_window_title()
            QApplication.processEvents()

            self._record_recent_project(filename, saved=True)
            self._history_controller.note_saved(filename)
    
            dlg.finish(success=True)
            return True
    
        except Exception as e:
            dlg.keep_open()                                                                 
            dlg.stage(f"Error: {str(e)[:80]}")
            dlg.finish(success=False)
            QMessageBox.critical(self, "Save Error", str(e))
            return False

    def on_export_sap2000(self):
        if not self.model:
            return False

        from PyQt6.QtWidgets import QInputDialog

        sap_version_map = {
            "24": "24.0.0",
            "23": "23.0.0",
            "22": "22.2.0",
            "21": "21.2.0",
            "20": "20.2.0",
        }
        version_choice, ok = QInputDialog.getItem(
            self, "Export to SAP2000", "SAP2000 version:", list(sap_version_map.keys()), 0, False
        )
        if not ok or not version_choice:
            return False
        version = sap_version_map[version_choice]

        filename, selected_filter = QFileDialog.getSaveFileName(
            self, "Export to SAP2000", "",
            "SAP2000 Text File (*.s2k);;SAP2000 Interactive Database (*.$2k)"
        )
        if not filename:
            return False

        ext = ".$2k" if "$2k" in selected_filter else ".s2k"
        if not (filename.endswith(".s2k") or filename.endswith(".$2k")):
            filename += ext

        dlg = ModelIODialog("Exporting to SAP2000...", filename, parent=self)
        dlg.show()
        QApplication.processEvents()

        try:
            dlg.stage("Writing SAP2000 tables...")
            QApplication.processEvents()

            export_sap2000(
                self.model,
                filepath=filename,
                sap_version=version,
                target_units=unit_registry.current_unit_label,
                project_info={"Model Name": getattr(self.model, "name", "")},
            )

            dlg.stage("Finalizing...")
            self.status.showMessage(f"Exported to SAP2000: {filename}")
            QApplication.processEvents()

            dlg.finish(success=True)
            return True

        except Exception as e:
            dlg.keep_open()
            dlg.stage(f"Error: {str(e)[:80]}")
            dlg.finish(success=False)
            QMessageBox.critical(self, "Export Error", str(e))
            return False

    def on_open_model(self, filepath=False):
                                
        if not self._check_unsaved_changes():
            return 
            
        if isinstance(filepath, str) and filepath:
            filename = filepath
        else:
                                                     
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
                                                                                     
                app_msaa = self.graphics_settings.get("msaa_level", 1)
                app_bg = self.graphics_settings.get("background_color")
                app_edge = self.graphics_settings.get("edge_color")
                app_shell_edge = self.graphics_settings.get("shell_edge_color")
                app_theme = self.graphics_settings.get("ui_theme")
                app_face_op = self.graphics_settings.get("extrude_opacity")                                           
                app_xh = {_ck: self.graphics_settings[_ck] for _ck in _CROSSHAIR_KEYS if _ck in self.graphics_settings}
                
                for _vk in _VIEW_SETTING_KEYS:
                    self.graphics_settings.pop(_vk, None)
                self.graphics_settings.update(self.model.graphics_settings)
                
                self.graphics_settings["msaa_level"] = app_msaa
                if app_bg: self.graphics_settings["background_color"] = app_bg
                if app_edge: self.graphics_settings["edge_color"] = app_edge
                if app_shell_edge: self.graphics_settings["shell_edge_color"] = app_shell_edge
                if app_theme: self.graphics_settings["ui_theme"] = app_theme
                if app_face_op is not None: self.graphics_settings["extrude_opacity"] = app_face_op
                self.graphics_settings.update(app_xh)
                
                self._apply_canvas_view_settings(self.graphics_settings)
                self.update_graphics_settings(self.graphics_settings)
            QApplication.processEvents()
    
            dlg.stage("Applying unit system...")
            if hasattr(self.model, 'saved_unit_system'):
                self.combo_units.blockSignals(True)
                self.combo_units.setCurrentText(self.model.saved_unit_system)
                self.combo_units.blockSignals(False)
                self.on_units_changed(0, redraw=False)
            QApplication.processEvents()
    
            self.draw_both_canvases(progress=_report)
            self.update_yield_lines()                                                                            
            self.canvas.set_standard_view("3D")
            self.set_interface_state(True)
            self.update_window_title()
            self.status.showMessage(f"Loaded: {filename}")
            self._record_recent_project(filename)
            self.model_tree.refresh()
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

    def on_analysis_options(self):
        if not self.model: return
        
        from app.dialogs.analysis_options_dialog import AnalysisOptionsDialog
        
        old = (list(self.model.active_dofs), self.model.analysis_engine)
        dlg = AnalysisOptionsDialog(self)
        if dlg.exec():
            new = (list(self.model.active_dofs), self.model.analysis_engine)
            if new != old:
                self.undo_stack.push(CmdAnalysisOptionsChanged())

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

    def on_define_tendon_sections(self):
        if not self.model: return
                                                                                 
        from app.dialogs.tendon_dialog import TendonManagerDialog
        
        dialog = TendonManagerDialog(self.model, self)
        dialog.exec()
        self.draw_both_canvases()                                               

    def on_define_area_sections(self):
        if not self.model: return
        from app.dialogs.area_section_dialog import AreaSectionsManagerDialog
        dialog = AreaSectionsManagerDialog(self.model, self)
        dialog.exec()
        self.draw_both_canvases()

    def on_define_rebar_sizes(self):
        if not self.model: return
        from app.dialogs.rebar_size_dialog import RebarSizeManagerDialog
        
        dialog = RebarSizeManagerDialog(self.model, self)
        dialog.exec()

    def on_define_hinge_properties(self):
        if not self.model: return
        from app.dialogs.hinge_dialog import HingePropertyManagerDialog

        dialog = HingePropertyManagerDialog(self.model, self)
        dialog.exec()

    def on_define_load_patterns(self):
        if not self.model: return
        dialog = LoadPatternDialog(self.model, self)
        dialog.exec()

    def _on_sidebar_select_mode(self):
        """Kills any active drawing modes and returns to pure selection state."""
        if getattr(self, 'quick_area_mode_active', False):
            self.on_quick_area_finished()
                                                    
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
        if self.quick_area_mode_active:
            self.on_quick_area_finished()
        if not hasattr(self.model, 'link_properties') or not self.model.link_properties:
            QMessageBox.warning(self, "Error", "Define a Link Property first!")
            if hasattr(self, 'act_select'): self.act_select.setChecked(True)
            return
            
        self.act_draw_link2.setChecked(True)
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
        if self.quick_area_mode_active:
            self.on_quick_area_finished()
        if not hasattr(self.model, 'link_properties') or not self.model.link_properties:
            QMessageBox.warning(self, "Error", "Define a Link Property first!")
            if hasattr(self, 'act_select'): self.act_select.setChecked(True)
            return
            
        self.act_draw_link1.setChecked(True)
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

        modifiers = event.modifiers()
        has_modifiers = bool(modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier))
        
        if getattr(self, 'cad_mode_cb', None) and self.cad_mode_cb.isChecked() and not has_modifiers:
            text = event.text()
            if text and text.isprintable() and not self.cmd_palette.isVisible():
                if event.key() not in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
                    self.cmd_palette.spawn(text, QCursor.pos())
                    return
                                           
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if getattr(self, 'draw_area_mode_active', False):
                self._finalize_poly_area()
                return

        if event.key() == Qt.Key.Key_Escape:
            if self.quick_area_mode_active:
                self.on_quick_area_finished()
                return
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

    def on_draw_quick_area(self):
        if not self.model:
            return
        if getattr(self, 'is_locked', False):
            self.status.showMessage("Cannot draw areas while locked. Unlock the model first.")
            return
        self._on_sidebar_select_mode()
        self.picking_replicate = False
        self.replicate_p1 = None
        if not self.model.area_sections:
            QMessageBox.warning(self, "Error", "Define an Area Section Property first!")
            self.act_select.setChecked(True)
            return

        self.quick_area_mode_active = True
        self.act_quick_area.setChecked(True)
        for cvs in [self.canvas, self.canvas2]:
            cvs.quick_area_mode = True
            cvs.snapping_enabled = False
            cvs.hide_quick_area_preview()

        if self.quick_area_dialog is None:
            self.quick_area_dialog = DrawQuickAreaDialog(self.model, self)
            self.quick_area_dialog.signal_dialog_closed.connect(self.on_quick_area_finished)
        self.quick_area_dialog.model = self.model
        self.quick_area_dialog.refresh_sections()
        self._update_quick_area_plane_status()
        self.quick_area_dialog.show()
        self.quick_area_dialog.raise_()
        self.status.showMessage("Quick Area Draw: Select XY / XZ / YZ, hover over a grid cell and click to place a shell. Esc to exit.")

    def on_quick_area_finished(self):
        self.quick_area_mode_active = False
        if self.quick_area_dialog:
            self.quick_area_dialog.hide()
        for cvs in [self.canvas, self.canvas2]:
            cvs.quick_area_mode = False
            cvs.snapping_enabled = False
            cvs.hide_quick_area_preview()
        self.act_select.setChecked(True)
        self.status.showMessage("Ready")

    def _update_quick_area_plane_status(self):
        for cvs in [self.canvas, self.canvas2]:
            cvs.hide_quick_area_preview()
        if self.quick_area_dialog:
            expected_axis = {'XY': 'z', 'XZ': 'y', 'YZ': 'x'}.get(self.active_canvas._view_mode)
            plane = self.active_canvas.active_view_plane
            if not plane or plane.get('axis') != expected_axis:
                plane = None
            self.quick_area_dialog.update_plane_status(plane)

    def _resolve_quick_area_corners(self, corners):
        """Preview the node reuse performed by get_or_create_node, without editing the model."""
        available = [(node.x, node.y, node.z) for node in self.model.nodes.values()]
        resolved = []
                                                                              
        tolerance_squared = 0.005 ** 2
        for corner in corners:
            match = next((point for point in available
                          if sum((a - b) ** 2 for a, b in zip(point, corner)) < tolerance_squared), None)
            if match is None:
                match = tuple(corner)
                available.append(match)
            resolved.append(match)
        return resolved

    def _area_exists_at_corners(self, corners):
        """Match shell geometry regardless of node labels or corner ordering."""
        corners = self._resolve_quick_area_corners(corners)
        tol = 1e-6
        for area in self.model.area_elements.values():
            if len(area.nodes) != len(corners):
                continue
            if all(any(abs(node.x - p[0]) < tol and abs(node.y - p[1]) < tol and abs(node.z - p[2]) < tol
                       for node in area.nodes) for p in corners):
                return True
        return False

    def _draw_quick_area_at(self, x, y, z):
        if getattr(self, 'is_locked', False):
            self.status.showMessage("Cannot draw areas while locked. Unlock the model first.")
            return
        cvs = self.active_canvas
        plane = cvs.active_view_plane
        if cvs._view_mode not in ("XY", "XZ", "YZ") or not plane:
            self.status.showMessage("Quick Area Draw: Enable an XY / XZ / YZ plane first.")
            return
        corners = cvs._quick_area_hover_cell
        normal_axis = {'XY': 'z', 'XZ': 'y', 'YZ': 'x'}[cvs._view_mode]
        axis_index = {'x': 0, 'y': 1, 'z': 2}[normal_axis]
        if (corners is None or plane['axis'] != normal_axis or
                any(abs(p[axis_index] - plane['value']) > 1e-6 for p in corners)):
            self.status.showMessage("No grid cell detected. Hover over a bounded grid cell on the active plane.")
            return
        section = self.quick_area_dialog.get_selected_section()
        if section is None:
            self.status.showMessage("Error: No Area Section selected.")
            return
        if len(set(self._resolve_quick_area_corners(corners))) != 4:
            self.status.showMessage("Cannot place shell: this cell's corners merge within the joint tolerance (5 mm).")
            return
        if self._area_exists_at_corners(corners):
            self.status.showMessage("Cannot place shell: an area element already exists in this cell.")
            return
        self.add_command(CmdDrawAreaElement(self.model, self, list(corners), section, description="Draw Quick Area"))
        self.status.showMessage("Shell placed. Click another grid cell or press Esc to exit.")

    def on_draw_poly_area(self):
        if self.quick_area_mode_active:
            self.on_quick_area_finished()
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
        if self.quick_area_mode_active:
            self._draw_quick_area_at(x, y, z)
            return
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
        
        if not self.draw_mode_active:
                                                                              
            n_selected = (
                len(self.selected_node_ids) + len(self.selected_ids)
                + len(getattr(self, 'selected_area_ids', []))
                + len(getattr(self, 'selected_link_ids', []))
            )
            if n_selected == 1:
                self.on_mouse_moved(x, y, z)
            return
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

            if self.draw_dialog.get_draw_mode() == "Tendon":
                tendon_section = self.draw_dialog.get_selected_tendon_section()
                if not tendon_section:
                    self.status.showMessage("Error: No Tendon Section Selected")
                    return

                from app.commands import CmdDrawTendon
                cmd = CmdDrawTendon(self.model, self, self.draw_start_node, end_node, tendon_section)
                self.add_command(cmd)

                if cmd.error_message:
                    self.status.showMessage(f"⚠️ {cmd.error_message}")
                else:
                    tendon = cmd.get_created_tendon()
                    if tendon:
                        from app.dialogs.tendon_geometry_dialog import TendonGeometryDialog

                        print("Before hide:", self.draw_dialog.isVisible())
                        self.draw_dialog.hide()
                        print("After hide:", self.draw_dialog.isVisible())

                        dlg = TendonGeometryDialog(tendon, self.model, self)
                        dlg.exec()

                        if self.draw_dialog:
                            self.draw_dialog.show()
                            self.draw_dialog.raise_()
                            self.draw_dialog.activateWindow()

                        self.canvas.draw_model(self.model)
                        if getattr(self, 'canvas2', None):
                            self.canvas2.draw_model(self.model)

                self.draw_start_node = None
                self.active_canvas._draw_start = None
                if not cmd.error_message:
                    self.status.showMessage("Ready to draw next Tendon...")
                return
            
            elif self.draw_dialog.get_draw_mode() == "Cable":
                cable_section = self.draw_dialog.get_selected_cable_section()
                if not cable_section:
                    self.status.showMessage("Error: No Cable Section Selected")
                    return

                from app.commands import CmdDrawCable
                cmd = CmdDrawCable(self.model, self, self.draw_start_node, end_node, cable_section)
                self.add_command(cmd)

                if cmd.error_message:
                    self.status.showMessage(f"⚠️ {cmd.error_message}")
                else:
                    cable = cmd.get_created_cable()
                    if cable:
                        from app.dialogs.cable_geometry_dialog import CableGeometryDialog

                        self.draw_dialog.hide()

                        dlg = CableGeometryDialog(cable, self.model, self)
                        dlg.exec()

                        if self.draw_dialog:
                            self.draw_dialog.show()
                            self.draw_dialog.raise_()
                            self.draw_dialog.activateWindow()

                        self.canvas.draw_model(self.model)
                        if getattr(self, 'canvas2', None):
                            self.canvas2.draw_model(self.model)

                self.draw_start_node = None
                self.active_canvas._draw_start = None
                if not cmd.error_message:
                    self.status.showMessage("Ready to draw next Cable...")
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

        target_tendon_id = getattr(self.canvas, 'hovered_tendon_id', None)
        if target_tendon_id is None and len(getattr(self, 'selected_tendon_ids', [])) == 1:
            target_tendon_id = self.selected_tendon_ids[0]

        target_cable_id = getattr(self.canvas, 'hovered_cable_id', None)
        if target_cable_id is None and len(getattr(self, 'selected_cable_ids', [])) == 1:
            target_cable_id = self.selected_cable_ids[0]

        tendons_here = []
        if target_elem_id is not None:
            tendons_here = [t for t in self.model.tendons.values()
                             if target_elem_id in getattr(t, 'host_element_ids', [])]
        elif target_tendon_id is not None:
            t = self.model.tendons.get(target_tendon_id)
            if t is not None:
                tendons_here = [t]

        if tendons_here:
            for tendon in tendons_here:
                tid = tendon.id
                sub_menu = menu.addMenu(f"Tendon {tid}")

                geom_action = sub_menu.addAction("Geometry...")

                def show_tendon_geometry(checked=False, t=tendon):
                    from app.dialogs.tendon_geometry_dialog import TendonGeometryDialog
                    dlg = TendonGeometryDialog(t, self.model, self)
                    dlg.exec()
                    self.canvas.draw_model(self.model)
                    if getattr(self, 'canvas2', None):
                        self.canvas2.draw_model(self.model)

                geom_action.triggered.connect(show_tendon_geometry)

                select_action = sub_menu.addAction("Select Only This Tendon")

                def select_this_tendon(checked=False, t_id=tid):
                    self.selected_ids = []
                    self.selected_node_ids = []
                    self.selected_area_ids = []
                    self.selected_link_ids = []
                    self.selected_tendon_ids = [t_id]
                    for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
                        if cvs:
                            cvs.update_selection_overlay(
                                self.selected_ids, self.selected_node_ids,
                                getattr(self, 'selected_area_ids', []),
                                self.selected_link_ids, self.selected_tendon_ids)
                    self.status.showMessage(f"Selected: Tendon {t_id}")

                select_action.triggered.connect(select_this_tendon)

                delete_action = sub_menu.addAction("Delete This Tendon Only")

                def delete_this_tendon(checked=False, t_id=tid):
                    from app.commands import CmdDeleteSelection
                    cmd = CmdDeleteSelection(self.model, self, [], [], tendon_ids=[t_id])
                    self.add_command(cmd)
                    self.status.showMessage(f"Deleted Tendon {t_id}. (Host beam kept.)")

                delete_action.triggered.connect(delete_this_tendon)

            menu.addSeparator()
            hit_something = True

        cables_here = []
        if target_cable_id is not None:
            c = getattr(self.model, 'cables', {}).get(target_cable_id)
            if c is not None:
                cables_here = [c]

        if cables_here:
            for cable in cables_here:
                cid = cable.id
                sub_menu = menu.addMenu(f"Cable {cid}")

                geom_action = sub_menu.addAction("Geometry...")
                def show_cable_geometry(checked=False, c=cable):
                    from app.dialogs.cable_geometry_dialog import CableGeometryDialog
                    dlg = CableGeometryDialog(c, self.model, self)
                    dlg.exec()
                    self.canvas.draw_model(self.model)
                    if getattr(self, 'canvas2', None):
                        self.canvas2.draw_model(self.model)
                geom_action.triggered.connect(show_cable_geometry)

                select_action = sub_menu.addAction("Select Only This Cable")
                def select_this_cable(checked=False, c_id=cid):
                    self.selected_ids = []
                    self.selected_node_ids = []
                    self.selected_area_ids = []
                    self.selected_link_ids = []
                    self.selected_tendon_ids = []
                    self.selected_cable_ids = [c_id]
                    
                    for cvs in [self.canvas, getattr(self, 'canvas2', None)]:
                        if cvs:
                                                                                              
                            cvs.selected_cable_ids = [c_id] 
                            cvs.update_selection_overlay(
                                self.selected_ids, self.selected_node_ids,
                                getattr(self, 'selected_area_ids', []),
                                getattr(self, 'selected_link_ids', []),
                                getattr(self, 'selected_tendon_ids', []))
                    self.status.showMessage(f"Selected: Cable {c_id}")
                select_action.triggered.connect(select_this_cable)

                delete_action = sub_menu.addAction("Delete This Cable Only")
                def delete_this_cable(checked=False, c_id=cid):
                    from app.commands import CmdDeleteCable
                    cmd = CmdDeleteCable(self.model, self, c_id)
                    self.add_command(cmd)
                    self.status.showMessage(f"Deleted Cable {c_id}.")
                delete_action.triggered.connect(delete_this_cable)

            menu.addSeparator()
            hit_something = True

        if target_node_id is not None and hasattr(self.model, 'has_results') and self.model.has_results:
            res_action = menu.addAction(f"Joint {target_node_id} Results...")
            
            def show_node_dlg():
                from app.dialogs.node_results_dialog import NodeResultsDialog
                self._node_res_dlg = NodeResultsDialog(target_node_id, self.model, self)
                self._node_res_dlg.signal_mode_changed.connect(self.switch_modal_view)
                self._node_res_dlg.combo_cases.currentIndexChanged.connect(self._on_node_dialog_case_changed)

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
                    dlg = MatrixSpyDialog(eid, self.model, base, self,
                                          step_number=self._selected_force_inspection_step())
                    dlg.exec()
            spy_action.triggered.connect(show_spy)

            fbd_action = menu.addAction("Show Free Body Diagram")
            def show_fbd():
                if hasattr(self, 'solver_output_path') and self.solver_output_path:
                    base = self.solver_output_path.replace("_results.json", "_matrices.json")
                    from app.dialogs.spy_dialogs import FBDViewerDialog
                    
                    dlg = FBDViewerDialog(eid, self.model, self.solver_output_path, base, self,
                                          step_number=self._selected_force_inspection_step())
                    
                    dlg.inspection_location_changed.connect(self.canvas.update_inspection_dot)
                    dlg.inspection_closed.connect(self.canvas.hide_inspection_dot)
                    
                    if getattr(self, 'canvas2_visible', False):
                        dlg.inspection_location_changed.connect(self.canvas2.update_inspection_dot)
                        dlg.inspection_closed.connect(self.canvas2.hide_inspection_dot)
                                                       
                    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                    dlg.show()
            fbd_action.triggered.connect(show_fbd)

        if self.selected_ids or self.selected_node_ids or getattr(self, 'selected_area_ids', []) or getattr(self, 'selected_link_ids', []) or getattr(self, 'selected_tendon_ids', []):
            menu.addSeparator()
            delete_action = menu.addAction("Delete Selection")
            delete_action.triggered.connect(self.delete_current_selection)
            hit_something = True

        _has_sel = any(self._selection_by_kind().values())
        if _has_sel or self.has_view_overrides():
            menu.addSeparator()
            if _has_sel:
                menu.addAction("Ghost Selection").triggered.connect(self.view_ghost_selection)
                menu.addAction("Hide Selection").triggered.connect(self.view_hide_selection)
                menu.addAction("Hide Inverse of Selection").triggered.connect(self.view_hide_inverse)
                hit_something = True
            if self.has_view_overrides():
                menu.addAction("Show All").triggered.connect(self.view_show_all)

        if self.selected_ids:
            view_sec_action = menu.addAction("View Cross Section...")
            def show_section_viewer():
                from app.dialogs.section_viewer_dialog import CrossSectionViewerDialog
                                                                                
                elements = [self.model.elements[eid] for eid in self.selected_ids if eid in self.model.elements]
                self._sec_viewer_dlg = CrossSectionViewerDialog(self.model, self.canvas, elements, self)
                self._sec_viewer_dlg.show()
            
            view_sec_action.triggered.connect(show_section_viewer)
            hit_something = True

        if not hit_something:
            grid_action = menu.addAction("Edit Grid Data...")
            grid_action.triggered.connect(self.open_grid_editor)

        menu.exec(QCursor.pos())

    _VIEW_KINDS = (
                                                                        
        ('node',   'selected_node_ids',   'nodes'),
        ('frame',  'selected_ids',        'elements'),
        ('area',   'selected_area_ids',   'area_elements'),
        ('link',   'selected_link_ids',   'links'),
        ('tendon', 'selected_tendon_ids', 'tendons'),
        ('cable',  'selected_cable_ids',  'cables'),
    )

    def _view_table(self):
        if not hasattr(self, '_view_overrides'):
            self._view_overrides = {}
        return self._view_overrides

    def has_view_overrides(self):
        return any(self._view_table().values())

    def _selection_by_kind(self):
        return {kind: list(getattr(self, attr, None) or [])
                for kind, attr, _coll in self._VIEW_KINDS}

    def _filter_pickable(self, kind, ids):
        """Drop ids that are currently ghosted or hidden (they are inert)."""
        d = self._view_table().get(kind)
        if not d:
            return list(ids)
        return [i for i in ids if d.get(i, 2) == 2]

    def _set_view_state(self, state, targets):
        """targets = {kind: ids}.  state 0 hidden / 1 ghost / 2 normal."""
        table = self._view_table()
        for kind, ids in targets.items():
            d = table.setdefault(kind, {})
            for oid in ids:
                if state == 2:
                    d.pop(oid, None)
                else:
                    d[oid] = state
            if not d:
                table.pop(kind, None)
        self._push_view_overrides()

    def _push_view_overrides(self):
        table = self._view_table()
        for cvs in (getattr(self, 'canvas', None), getattr(self, 'canvas2', None)):
            if cvs is not None:
                cvs.set_view_overrides(table)
                                                           
        for kind, attr, _coll in self._VIEW_KINDS:
            cur = getattr(self, attr, None)
            if cur:
                setattr(self, attr, self._filter_pickable(kind, cur))
        self.draw_both_canvases()

    def _view_apply_to_selection(self, state, verb):
        if not self.model:
            return
        targets = self._selection_by_kind()
        n = sum(len(v) for v in targets.values())
        if not n:
            return
        self._set_view_state(state, targets)
        self.status.showMessage(f"{verb} {n} object(s).  Right-click > Show All to restore.")

    def view_ghost_selection(self):
        self._view_apply_to_selection(1, "Ghosted")

    def view_hide_selection(self):
        self._view_apply_to_selection(0, "Hid")

    def view_hide_inverse(self):
        if not self.model:
            return
        sel = self._selection_by_kind()
        if not any(sel.values()):
            return
        targets = {}
        for kind, _attr, coll in self._VIEW_KINDS:
            keep = set(sel[kind])
            targets[kind] = [i for i in getattr(self.model, coll, {}).keys() if i not in keep]
        n = sum(len(v) for v in targets.values())
        self._set_view_state(0, targets)
        self.status.showMessage(f"Hid everything except the selection ({n} object(s)).  Right-click > Show All to restore.")

    def view_show_all(self):
        if not self.model:
            return
        self._view_overrides = {}
        self._push_view_overrides()
        self.status.showMessage("All objects visible.")

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
            self.model.grid.bubble_line_width = new_grids.get("bubble_line_width", 1.5)
            self.model.grid.bubble_extension = new_grids.get("bubble_extension", self.model.grid.bubble_size * 2.5)
            
            self.canvas.draw_model(self.model)
            if getattr(self, 'canvas2_visible', False):
                self.canvas2.draw_model(self.model, list(self.selected_ids), list(self.selected_node_ids))

    def _update_coord_for_single_selection(self):
        """Update the status-bar coordinate after a selection.

        A single click always shows a coordinate — even if it happened to
        sweep in a node plus its connected elements, since that's really
        just one clicked point. A deliberate drag-box selection only shows
        a coordinate if it nets exactly one item; genuine multi-selects
        leave the label alone.
        """
        if not self.model:
            return

        was_click = getattr(self.active_canvas, '_last_selection_was_click', False)

        n_nodes  = len(self.selected_node_ids)
        n_frames = len(self.selected_ids)
        n_areas  = len(getattr(self, 'selected_area_ids', []))
        n_links  = len(getattr(self, 'selected_link_ids', []))
        total    = n_nodes + n_frames + n_areas + n_links

        if not was_click and total != 1:
            return
        if total == 0:
            return

        try:
            if n_nodes > 0:
                n = self.model.nodes[self.selected_node_ids[0]]
                x, y, z = n.x, n.y, n.z
            elif n_frames > 0:
                el = self.model.elements[self.selected_ids[0]]
                x = (el.node_i.x + el.node_j.x) / 2.0
                y = (el.node_i.y + el.node_j.y) / 2.0
                z = (el.node_i.z + el.node_j.z) / 2.0
            elif n_areas > 0:
                ae = self.model.area_elements[self.selected_area_ids[0]]
                xs = [nd.x for nd in ae.nodes]
                ys = [nd.y for nd in ae.nodes]
                zs = [nd.z for nd in ae.nodes]
                x, y, z = sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs)
            else:
                link = self.model.links[self.selected_link_ids[0]]
                pts = []
                for nid in link['nodes']:
                    nd = self.model.nodes.get(nid)
                    if nd is None:
                        try:
                            nd = self.model.nodes.get(int(nid))
                        except (TypeError, ValueError):
                            nd = None
                    if nd is None:
                        nd = self.model.nodes.get(str(nid))
                    if nd:
                        pts.append((nd.x, nd.y, nd.z))
                if not pts:
                    return
                x = sum(p[0] for p in pts) / len(pts)
                y = sum(p[1] for p in pts) / len(pts)
                z = sum(p[2] for p in pts) / len(pts)
            self.on_mouse_moved(x, y, z)
        except (KeyError, AttributeError, IndexError, TypeError):
            pass

    def _handle_box_selection_canvas2(self, node_ids, elem_ids, link_ids, tendon_ids, cable_ids, is_additive, is_deselect):
        if self.active_canvas is not self.canvas2:
            return
        self.handle_box_selection(node_ids, elem_ids, link_ids, tendon_ids, cable_ids, is_additive, is_deselect)

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
            drop = set(area_ids)
            self.selected_area_ids[:] = [a for a in self.selected_area_ids if a not in drop]
        elif is_additive:
            have = set(self.selected_area_ids)
            for aid in area_ids:
                if aid not in have:
                    self.selected_area_ids.append(aid)
                    have.add(aid)
        else:
            hit_something = len(area_ids) > 0
            if hit_something:
                                                                                             
                self.selected_area_ids = list(area_ids)

        n_areas = len(self.selected_area_ids)
        n_frames = len(self.selected_ids)
        n_joints = len(self.selected_node_ids)
        n_tendons = len(getattr(self, 'selected_tendon_ids', []))
        parts = []
        if n_frames: parts.append(f"{n_frames} Frames")
        if n_joints: parts.append(f"{n_joints} Joints")
        if n_areas:  parts.append(f"{n_areas} Areas")
        if n_tendons: parts.append(f"{n_tendons} Tendons")
        self.status.showMessage(f"Selected: {', '.join(parts)}" if parts else "Selection Cleared")

        for cvs in self._selection_canvases():
            cvs.update_selection_overlay(self.selected_ids, self.selected_node_ids, self.selected_area_ids, getattr(self, 'selected_link_ids', []), getattr(self, 'selected_tendon_ids', []))

        self._update_coord_for_single_selection()

    def handle_box_selection(self, node_ids, elem_ids, link_ids, tendon_ids, cable_ids, is_additive, is_deselect):
        if not hasattr(self, 'selected_link_ids'): self.selected_link_ids = []
        if not hasattr(self, 'selected_tendon_ids'): self.selected_tendon_ids = []
        if not hasattr(self, 'selected_cable_ids'): self.selected_cable_ids = []

        node_ids = list(node_ids)
        elem_ids = list(elem_ids)
        link_ids = list(link_ids)
        tendon_ids = list(tendon_ids)
        cable_ids = list(cable_ids)

        if is_additive:
            self.selected_node_ids = list(set(self.selected_node_ids + node_ids))
            self.selected_ids = list(set(self.selected_ids + elem_ids))
            self.selected_link_ids = list(set(getattr(self, 'selected_link_ids', []) + link_ids))
            self.selected_tendon_ids = list(set(getattr(self, 'selected_tendon_ids', []) + tendon_ids))
            self.selected_cable_ids = list(set(getattr(self, 'selected_cable_ids', []) + cable_ids))
        elif is_deselect:
            self.selected_node_ids = [n for n in self.selected_node_ids if n not in node_ids]
            self.selected_ids = [e for e in self.selected_ids if e not in elem_ids]
            self.selected_link_ids = [l for l in getattr(self, 'selected_link_ids', []) if l not in link_ids]
            self.selected_tendon_ids = [t for t in getattr(self, 'selected_tendon_ids', []) if t not in tendon_ids]
            self.selected_cable_ids = [c for c in getattr(self, 'selected_cable_ids', []) if c not in cable_ids]
        else:
            hit_something = bool(node_ids or elem_ids or link_ids or tendon_ids or cable_ids)
            if hit_something:
                self.selected_node_ids = list(node_ids)
                self.selected_ids = list(elem_ids)
                self.selected_link_ids = list(link_ids)
                self.selected_tendon_ids = list(tendon_ids)
                self.selected_cable_ids = list(cable_ids)

        area_refresh_follows = any(
            getattr(c, '_box_sel_area_follows', False)
            for c in (self.canvas, getattr(self, 'canvas2', None)) if c is not None)
        for cvs in self._selection_canvases():
            cvs.selected_cable_ids = self.selected_cable_ids
            if not area_refresh_follows:
                cvs.update_selection_overlay(self.selected_ids, self.selected_node_ids, getattr(self, 'selected_area_ids', []), self.selected_link_ids, self.selected_tendon_ids)

        n_tendons = len(self.selected_tendon_ids)
        n_cables = len(self.selected_cable_ids)
        tendon_str = f", {n_tendons} Tendons" if n_tendons else ""
        cable_str = f", {n_cables} Cables" if n_cables else ""
        self.status.showMessage(f"Selected: {len(self.selected_ids)} Frames, {len(self.selected_node_ids)} Joints, {len(self.selected_link_ids)} Links{tendon_str}{cable_str}")

        self._update_coord_for_single_selection()

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
        
        if not self.selected_ids and not self.selected_node_ids and not self.selected_area_ids and not getattr(self, 'selected_link_ids', []) and not getattr(self, 'selected_tendon_ids', []) and not getattr(self, 'selected_cable_ids', []):
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
        deleted_tendon_count = len(getattr(self, 'selected_tendon_ids', []))
        deleted_cable_count = len(getattr(self, 'selected_cable_ids', []))

        cmd = CmdDeleteSelection(
            self.model, self, final_node_ids, final_elem_ids,
            area_elem_ids=list(self.selected_area_ids),
            link_ids=list(auto_link_ids),
            tendon_ids=list(getattr(self, 'selected_tendon_ids', [])),
            cable_ids=list(getattr(self, 'selected_cable_ids', []))           
        )
        self.add_command(cmd)
        
        self.selected_ids = [] 
        self.selected_node_ids = []
        self.selected_area_ids = []
        self.selected_link_ids = []          
        self.selected_tendon_ids = []
        self.selected_cable_ids = []           
        
        parts = []
        if final_elem_ids:     parts.append(f"{len(final_elem_ids)} Frames")
        if final_node_ids:     parts.append(f"{len(final_node_ids)} Joints")
        if deleted_area_count: parts.append(f"{deleted_area_count} Areas")
        if deleted_link_count: parts.append(f"{deleted_link_count} Links")          
        if deleted_tendon_count: parts.append(f"{deleted_tendon_count} Tendons")
        if deleted_cable_count: parts.append(f"{deleted_cable_count} Cables")
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
        cvs.show_hinges          = settings.get('hinges', True)
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

        self.draw_both_canvases()
            
    def on_draw_frame(self):
        if self.quick_area_mode_active:
            self.on_quick_area_finished()
        if not self.model.sections:
            QMessageBox.warning(self, "Error", "Define a Section Property first!")
            return
        self.act_draw_frame.setChecked(True)
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
        if self.quick_area_mode_active:
            self.on_quick_area_finished()
        if not self.model.sections:
            QMessageBox.warning(self, "Error", "Define a Section Property first!")
            return
        self.act_quick_brace.setChecked(True)
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
        if self.quick_area_mode_active:
            self.on_quick_area_finished()
        if not self.model.sections:
            QMessageBox.warning(self, "Error", "Define a Section Property first!")
            return
        self.act_quick_beam.setChecked(True)
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
            
        self.refresh_load_display()

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
        if self.quick_area_mode_active:
            self.on_quick_area_finished()
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
            
    def on_edit_divide_frames(self):
        if not self.selected_ids:
            QMessageBox.warning(self, "Selection", "Please select one or more frames to divide first.")
            return
        if self.divide_frame_dialog is None:
            from app.dialogs.divide_frame_dialog import DivideFrameDialog
            self.divide_frame_dialog = DivideFrameDialog(self)
            self.divide_frame_dialog.signal_apply.connect(self.on_divide_frame_apply)
        self.divide_frame_dialog.show()
        self.divide_frame_dialog.raise_()
        self.divide_frame_dialog.activateWindow()

    def on_divide_frame_apply(self):
        from app.dialogs.divide_frame_dialog import DivideFrameDialog

        if not self.selected_ids:
            QMessageBox.warning(self, "Selection", "Please select one or more frames to divide first.")
            return

        mode, kwargs = self.divide_frame_dialog.get_divide_spec()
        target_ids = list(self.selected_ids)
        all_selected_frame_ids = list(self.selected_ids)
        all_selected_joint_ids = list(getattr(self, 'selected_node_ids', []))

        errors = []
        any_success = False

        for eid in target_ids:
            if mode == DivideFrameDialog.MODE_NUMBER:
                divide_fn = lambda model, element_id, k=kwargs: model.divide_frame_by_number(
                    element_id, k["num_frames"], k["last_first_ratio"])
            elif mode == DivideFrameDialog.MODE_DISTANCE:
                divide_fn = lambda model, element_id, k=kwargs: model.divide_frame_at_distance(
                    element_id, k["distance"], k["is_relative"])
            elif mode == DivideFrameDialog.MODE_COORD_PLANE:
                divide_fn = lambda model, element_id, k=kwargs: model.divide_frame_at_coordinate_plane(
                    element_id, k["plane"], k["coordinate"])
            elif mode == DivideFrameDialog.MODE_GRID_PLANES:
                divide_fn = lambda model, element_id: model.divide_frame_at_grid_planes(element_id)
            elif mode == DivideFrameDialog.MODE_INTERSECTIONS:
                other_frame_ids = [fid for fid in all_selected_frame_ids if fid != eid]
                divide_fn = lambda model, element_id, jids=all_selected_joint_ids, fids=other_frame_ids: (
                    model.divide_frame_at_intersections(element_id, joint_ids=jids, frame_ids=fids))
            else:
                continue

            cmd = CmdDivideFrame(self.model, self, eid, divide_fn)
            self.add_command(cmd)
            if cmd.error:
                errors.append(f"Frame {eid}: {cmd.error}")
            else:
                any_success = True

        self.selected_ids = []
        self.selected_node_ids = []
        self.draw_both_canvases()

        if errors:
            header = "Some frames could not be divided:\n\n" if any_success else "No frames could be divided:\n\n"
            QMessageBox.warning(self, "Divide Frames", header + "\n".join(errors))

    def on_edit_join_frames(self):
        if len(self.selected_ids) < 2:
            QMessageBox.warning(self, "Selection", "Please select two or more frames to join first (no dialog, just select and join).")
            return

        chains = self.model.find_straight_chains(self.selected_ids)
        joinable_chains = [c for c in chains if len(c) >= 2]

        if not joinable_chains:
            QMessageBox.warning(
                self, "Join Frames",
                "No straight, connected runs of two or more frames were found in the selection "
                "(everything selected is either a single dead-end frame, or bends/branches at "
                "every joint)."
            )
            return

        new_frame_ids = []
        errors = []

        for chain in joinable_chains:
            keep_id = chain[0]
            if self._frames_have_mismatched_properties(chain):
                from app.dialogs.select_frame_properties_dialog import SelectFramePropertiesDialog
                dlg = SelectFramePropertiesDialog(chain, self.model, self)
                if dlg.exec() != dlg.DialogCode.Accepted:
                    continue
                keep_id = dlg.chosen_id

            cmd = CmdJoinFrames(self.model, self, chain, keep_id)
            self.add_command(cmd)

            if cmd.error:
                errors.append(f"Frames {chain}: {cmd.error}")
            else:
                new_frame_ids.append(cmd.created_elem_id)

        skipped = len(chains) - len(joinable_chains)
        self.selected_ids = new_frame_ids
        self.draw_both_canvases()

        if errors or skipped:
            lines = []
            if new_frame_ids:
                lines.append(f"{len(new_frame_ids)} straight run(s) joined into {len(new_frame_ids)} frame(s).")
            if skipped:
                lines.append(f"{skipped} frame(s) had no straight neighbor to join and were left as-is.")
            if errors:
                lines.append("Some runs could not be joined:")
                lines.extend(errors)
            QMessageBox.information(self, "Join Frames", "\n".join(lines))

    def _frames_have_mismatched_properties(self, element_ids):
        els = [self.model.elements[eid] for eid in element_ids if eid in self.model.elements]
        if len(els) < 2:
            return False

        def _key(el):
            return (
                getattr(el.section, 'name', None),
                round(float(el.beta_angle), 6),
                getattr(el, 'cardinal_point', 10),
                tuple(round(float(v), 6) for v in getattr(el, 'joint_offset_i', [0, 0, 0])),
                tuple(round(float(v), 6) for v in getattr(el, 'joint_offset_j', [0, 0, 0])),
                round(float(getattr(el, 'end_offset_i', 0.0)), 6),
                round(float(getattr(el, 'end_offset_j', 0.0)), 6),
                round(float(getattr(el, 'rigid_zone_factor', 0.0)), 6),
                bool(getattr(el, 'do_not_transform_stiffness', False)),
            )

        ref_key = _key(els[0])
        return any(_key(el) != ref_key for el in els[1:])

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

    def on_assign_frame_hinge(self):
        """Opens the Assign Frame Hinges Dialog"""
        if not hasattr(self, 'frame_hinge_dlg') or not self.frame_hinge_dlg.isVisible():
            self.frame_hinge_dlg = AssignFrameHingeDialog(self)
            self.frame_hinge_dlg.show()
        else:
            self.frame_hinge_dlg.raise_()

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
        old_settings = getattr(self, "_applied_graphics_settings", self.graphics_settings).copy()
        old_ui_theme = old_settings.get("ui_theme", "Light")
                                                                               
        _nc = lambda c: tuple(int(float(v) * 255 + 1e-6) for v in c) if c is not None else None

        def _value(settings, key):
            if key == "hinge_color":
                value = settings.get(key, (0.0, 0.47, 0.84, 1.0))
            elif key == "hinge_shape":
                value = settings.get(key, "Circle")
            elif key == "shell_edge_color":
                value = settings.get(key, settings.get("edge_color", (0, 0, 0, 1)))
            elif key == "area_load_display_mode":
                value = settings.get(key, "smart")
            elif key == "frame_load_display_mode":
                value = settings.get(key, "smart")
            elif key == "load_text_scale":
                value = settings.get(key, 1.0)
            elif key == "area_load_arrow_spacing":
                value = settings.get(key, 55.0)
            else:
                value = settings.get(key)
            if key.endswith("_color"):
                return _nc(value)
            return tuple(value) if isinstance(value, (list, tuple)) else value

        _old_hinge = (_value(old_settings, "hinge_color"), _value(old_settings, "hinge_shape"))

        msaa_samples = {0: 0, 1: 4, 2: 8, 3: 16, 4: 2, 5: 0}
        level = new_settings.get("msaa_level", self.graphics_settings.get("msaa_level", 1))
        self.graphics_settings["msaa_level"] = level
        
        self.graphics_settings["antialias"] = new_settings.get(
            "antialias", level > 0 if "msaa_level" in new_settings
            else self.graphics_settings.get("antialias", level > 0))
                                   
        self.graphics_settings.update(new_settings)
        
        ui_theme = self.graphics_settings.get("ui_theme", "Light")

        QApplication.instance().setProperty("os_ui_theme", ui_theme)

        bg_tuple = self.graphics_settings.get("background_color", (1.0, 1.0, 1.0, 1.0))
        bg_sum = sum(bg_tuple[:3])
        
        if ui_theme == "Dark" and bg_sum > 2.5:                                          
            bg_tuple = (30/255.0, 30/255.0, 30/255.0, 1.0)
            self.graphics_settings["background_color"] = bg_tuple
        elif ui_theme == "Light" and bg_sum < 0.5:                                          
            bg_tuple = (1.0, 1.0, 1.0, 1.0)
            self.graphics_settings["background_color"] = bg_tuple

        prefs_path = os.path.join(os.path.expanduser("~"), ".OpenStructures_prefs.json")
        try:
            with open(prefs_path, 'w') as f:
                json.dump({k: v for k, v in self.graphics_settings.items()
                           if k not in _VIEW_SETTING_KEYS}, f)
        except (OSError, TypeError, ValueError):
            pass
        
        self.canvas.display_config = self.graphics_settings
        
        if hasattr(self, 'canvas2'):
            self.canvas2.display_config = self.graphics_settings
        
        c = QColor()
        c.setRgbF(bg_tuple[0], bg_tuple[1], bg_tuple[2], bg_tuple[3])
        
        if getattr(self, 'is_locked', False) or self.model is None:
            idle_c = QColor(30, 30, 30) if ui_theme == "Dark" else QColor('#F8F9FA')
            self.canvas.setBackgroundColor(idle_c)
            if hasattr(self, 'canvas2'):
                self.canvas2.setBackgroundColor(idle_c)
        else:
            self.canvas.setBackgroundColor(c)
            if hasattr(self, 'canvas2'):
                self.canvas2.setBackgroundColor(c)

        hinge_changed = (_value(self.graphics_settings, "hinge_color"),
                         _value(self.graphics_settings, "hinge_shape")) != _old_hinge
        if hinge_changed and self.model is not None:
            for _cv in (self.canvas, getattr(self, 'canvas2', None)):
                if _cv is not None:
                    _cv._needs_hinge_refresh = True

        geometry_keys = ("node_size", "node_color", "extrude_opacity", "slab_opacity",
                         "show_edges", "edge_color", "hinge_color", "hinge_shape",
                         "shell_edge_color", "area_load_display_mode", "load_text_scale",
                         "area_load_arrow_spacing", "frame_load_display_mode")
                                                                            
        geometry_changed = any(
            _value(old_settings, k) != _value(self.graphics_settings, k)
            for k in geometry_keys)
        if (geometry_changed or ui_theme != old_ui_theme) and self.model is not None:
            for _cv in (self.canvas, getattr(self, 'canvas2', None)):
                if _cv is not None:
                    _cv.refresh_graphics_geometry(self.model)

        apply_windows_titlebar_theme(self)
                                                            
        self._apply_crosshair_to_canvases()
        for _cv in (self.canvas, getattr(self, 'canvas2', None)):
            if _cv is not None:
                _cv.update()
        self._applied_graphics_settings = self.graphics_settings.copy()
        self.status.showMessage("Graphics settings updated.")
        
    def _apply_crosshair_to_canvases(self):
        """Push crosshair settings to both viewports and keep the Edit-menu check in sync."""
        act = getattr(self, 'act_precision_pointer', None)
        if act is not None:
            en = bool(self.graphics_settings.get('crosshair_enabled', True))
            if act.isChecked() != en:
                act.blockSignals(True)
                act.setChecked(en)
                act.blockSignals(False)
        for cv in (getattr(self, 'canvas', None), getattr(self, 'canvas2', None)):
            if cv is not None and hasattr(cv, 'crosshair'):
                cv.crosshair.apply_settings()

    def _save_crosshair_prefs(self):
        """Persist ONLY the crosshair keys, leaving the rest of the prefs file untouched."""
        save_crosshair_prefs(self.graphics_settings)

    def on_toggle_precision_pointer(self, checked):
        self.graphics_settings['crosshair_enabled'] = bool(checked)
        self._save_crosshair_prefs()
        self._apply_crosshair_to_canvases()
        self.status.showMessage(f"Precision Pointer: {'ON' if checked else 'OFF'}")

    def on_precision_pointer_settings(self):
        """Opens Graphics Preferences directly on the Crosshair tab."""
        dlg = GraphicsOptionsDialog(self, self.graphics_settings)
        dlg.select_tab("Crosshair")
        dlg.show()

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
        if not self.model:
            return

        dlg = AnalysisDialog(self.model, self)
        dlg.signal_run_analysis.connect(self.start_analysis_sequence)
        dlg.exec()

    def stop_analysis_and_return_to_modeling(self):
        """Force-stops any running solver/worker and resets the UI to normal modeling mode."""
                                                                              
        gen = getattr(self, '_tributary_generator', None)
        if gen is not None:
            try:
                gen.signal_all_loads_ready.disconnect(self._continue_analysis_after_loads)
            except Exception:
                pass

        worker = getattr(self, 'worker', None)
        if worker is not None:
            try:
                worker.signal_finished.disconnect(self.finish_analysis_sequence)
            except Exception:
                pass
            prog = getattr(self, '_progress_dialog', None)
            if prog is not None and hasattr(prog, 'update_stages'):
                try:
                    worker.signal_progress_batch.disconnect(prog.update_stages)
                except Exception:
                    pass
            try:
                worker.cancel()
            except Exception:
                pass
            worker.deleteLater()
            self.worker = None

        b_thread = getattr(self, '_buckling_thread', None)
        if b_thread is not None:
            try:
                b_thread.finished.disconnect()
            except Exception:
                pass
            if b_thread.isRunning():
                try:
                    b_thread.terminate()
                    b_thread.wait(200)
                except Exception:
                    pass
            self._buckling_thread = None

        prog_dlg = getattr(self, '_progress_dialog', None)
        if prog_dlg is not None:
            try:
                prog_dlg.abort()                                                     
                prog_dlg.close()
                prog_dlg.deleteLater()
            except Exception:
                pass
            self._progress_dialog = None

        self._discard_solver_mesh_dir()
        self._solver_mesh_ctx = None
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

        self.unlock_model()
        self.set_interface_state(True)
        self.status.showMessage("Analysis stopped. Returned to normal modeling phase.")

    def start_analysis_sequence(self, case_name, show_log=True):
        w = getattr(self, 'worker', None)
        bt = getattr(self, '_buckling_thread', None)
        if (w is not None and w.isRunning()) or (bt is not None and bt.isRunning()):
            self.stop_analysis_and_return_to_modeling()

        if not hasattr(self.model, 'file_path') or not self.model.file_path:
            QMessageBox.warning(self, "Save Required", "Please save the model file before running analysis.")
            self.on_save_model()
                                                   
            if not self.model.file_path:
                return

        print(f"Main: Starting analysis for case '{case_name}'...")

        self.set_interface_state(False)
        self.status.showMessage(f"Running Analysis: {case_name}... Please Wait.")

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
            if hasattr(self.model, 'generate_tendon_loads'):
                self.model.generate_tendon_loads()
            self._history_controller.before_save(self.solver_input_path)
            atomic_save_model(self.model, self.solver_input_path)
            self._history_controller.note_saved(self.solver_input_path, "Saved before analysis")
            print(f"Model saved to {self.solver_input_path}")
        except Exception as e:
            self.finish_analysis_sequence(False, f"Could not save input file: {e}")
            return

        self._solver_mesh_ctx = None
        run_input_path = self.solver_input_path
        run_output_path = self.solver_output_path
        try:
            ctx = self.model.write_solver_copy(self.solver_input_path)
        except Exception as e:
            self.finish_analysis_sequence(False, f"Could not build the solver mesh: {e}")
            return
        if ctx:
            self._solver_mesh_ctx = ctx
            run_input_path = ctx["dest_path"]
            run_output_path = os.path.join(ctx["work_dir"], os.path.basename(self.solver_output_path))
            print(f"Solver mesh: {ctx['meshed_shells']} shell(s) meshed, "
                  f"{ctx.get('split_frames', 0)} frame(s) split in {ctx['work_dir']}")

        self.worker = SolverProcessRunner(
            run_input_path,
            run_output_path,
            case_type=c_type,
            case_name=case_name,
            parent=self
        )
        self.worker.signal_finished.connect(self.finish_analysis_sequence)

        self._progress_dialog = AnalysisProgressDialog(c_type, case_name, parent=self)
        self._progress_dialog.setWindowModality(Qt.WindowModality.NonModal)
        self._progress_dialog.signal_stop_requested.connect(self.stop_analysis_and_return_to_modeling)
        self.worker.signal_progress_batch.connect(self._progress_dialog.update_stages)
        if show_log:
            self._progress_dialog.setProperty("_ghost_animated", True)
            self._progress_dialog.show()

        self.worker.start()

    def finish_analysis_sequence(self, success, message):
        """Called when the Solver Thread finishes."""
        QApplication.restoreOverrideCursor()
        import os, json

        if hasattr(self, '_progress_timer'):
            self._progress_timer.stop()

        failed_steps = []
        if getattr(self, 'last_run_mode', '') == "Batch Run" and hasattr(self, 'worker'):
                                                                
            failed_steps = getattr(self.worker, 'batch_failed_steps', [])
        elif hasattr(self, 'solver_output_path') and os.path.exists(
                os.path.join(self._solver_mesh_ctx["work_dir"], os.path.basename(self.solver_output_path))
                if getattr(self, '_solver_mesh_ctx', None) else self.solver_output_path):
            try:
                _rp = (os.path.join(self._solver_mesh_ctx["work_dir"], os.path.basename(self.solver_output_path))
                       if getattr(self, '_solver_mesh_ctx', None) else self.solver_output_path)
                with open(_rp, 'r') as f:
                    res_data = json.load(f)
                    failed_steps = res_data.get("info", {}).get("failed_steps", [])
            except Exception as e:
                print(f"Warning: could not read failed_steps from results JSON: {e}")

        case_failures = []
        if getattr(self, 'last_run_mode', '') == "Batch Run" and hasattr(self, 'worker'):
            case_failures = getattr(self.worker, 'batch_case_failures', [])

        if getattr(self, '_progress_dialog', None) is not None:
            self._progress_dialog.finish(success, failed_steps=failed_steps, case_failures=case_failures)
        
        if success:
            try:
                self._finalize_solver_mesh_results()
            except Exception as e:
                QMessageBox.critical(self, "Solver Mesh", f"Could not bring back the meshed results:\n{e}")
                self.set_interface_state(True)
                return
        else:
            self._discard_solver_mesh_dir()

        if success:
            self.status.showMessage("Analysis Complete.")
            import glob
            base_name = os.path.splitext(self.solver_input_path)[0]
            if getattr(self, 'last_run_mode', '') == "Batch Run":
                self.model.valid_result_paths = glob.glob(f"{base_name}_*_results.json")
            else:
                paths = list(getattr(self.model, 'valid_result_paths', []) or [])
                if self.solver_output_path not in paths:
                    paths.append(self.solver_output_path)
                self.model.valid_result_paths = paths

            self.load_analysis_results()

        else:
            self.set_interface_state(True) 
            QMessageBox.critical(self, "Analysis Failed", message)

    def _discard_solver_mesh_dir(self):
        """Deletes the temporary meshed solver copy, if any."""
        import shutil
        ctx = getattr(self, '_solver_mesh_ctx', None)
        if ctx:
            shutil.rmtree(ctx["work_dir"], ignore_errors=True)
        self._solver_mesh_ctx = None

    def _finalize_solver_mesh_results(self):
        """
        After a solver-meshed run: purge the stale result files next to the real model,
        remap solver-copy IDs back to the original IDs, move the files up, delete the temp dir.
        """
        import glob, shutil
        from app.solver_mesh_remap import clear_mesh_dir, finalize_mesh_dir
        ctx = getattr(self, '_solver_mesh_ctx', None)
        if not ctx:
                                                                                              
            clear_mesh_dir(self.solver_input_path)
            return

        live_base = os.path.splitext(self.solver_input_path)[0]
        work_base = os.path.splitext(ctx["dest_path"])[0]

        if getattr(self, 'last_run_mode', '') != "Batch Run":
            for stale in (glob.glob(f"{live_base}_*_results.json") +
                          glob.glob(f"{live_base}_*_matrices.json")):
                try:
                    os.remove(stale)
                except OSError:
                    pass

        new_files = (glob.glob(f"{work_base}_*_results.json") +
                     glob.glob(f"{work_base}_*_matrices.json"))
        from app.solver_mesh_remap import remap_results_file
        live_node_ids = list(self.model.nodes.keys())
        for src in new_files:
            if src.endswith("_results.json"):
                remap_results_file(src, live_node_ids)
                                                                                               
            dst = os.path.join(os.path.dirname(self.solver_input_path), os.path.basename(src))
            if os.path.exists(dst):
                os.remove(dst)                                                               
            shutil.move(src, dst)

        finalize_mesh_dir(ctx["work_dir"], ctx["dest_path"])
        self._solver_mesh_ctx = None

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
        self._progress_dialog.signal_stop_requested.connect(self.stop_analysis_and_return_to_modeling)
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
        self._populate_statusbar_result_cases()

        if "mode_shapes" in results and "Mode 1" in results["mode_shapes"]:
            self.switch_modal_view("Mode 1")
        else:
            self.draw_both_canvases()

        if getattr(self, '_progress_dialog', None) is not None:
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

            self._teardown_ltha_playback()

            self.btn_deform.setEnabled(True)
            self.action_display_forces.setEnabled(True)
            self.action_display_reactions.setEnabled(True)
            self.action_plot_functions.setEnabled(has_ltha_results(self.model))

            _po_info = data.get("info", {})
            is_pushover_ready = bool(
                _po_info.get("type") == "Nonlinear Static"
                and _po_info.get("results_saved_multiple")
                and data.get("saved_states")
                and len(data.get("saved_states", [])) >= 2
            )
            if not is_pushover_ready:
                for _rpath in getattr(self.model, 'valid_result_paths', []) or []:
                    try:
                        with open(_rpath, 'r') as _rf:
                            _rdata = json.load(_rf)
                        _rinfo = _rdata.get("info", {})
                        if (_rdata.get("status") == "SUCCESS"
                                and _rinfo.get("type") == "Nonlinear Static"
                                and _rinfo.get("results_saved_multiple")
                                and len(_rdata.get("saved_states") or []) >= 2):
                            is_pushover_ready = True
                            break
                    except Exception:
                        continue
            self.action_pushover_curve.setEnabled(
                self.action_pushover_curve.isEnabled() or is_pushover_ready
            )

            _has_hinges_in_model = bool(getattr(self.model, 'frame_hinges', None))
            _has_nonlinear_static = (_po_info.get("type") == "Nonlinear Static")
            if _has_hinges_in_model and not _has_nonlinear_static:
                for _rpath in getattr(self.model, 'valid_result_paths', []) or []:
                    try:
                        with open(_rpath, 'r') as _rf:
                            _rdata = json.load(_rf)
                        if (_rdata.get("status") == "SUCCESS"
                                and _rdata.get("info", {}).get("type") == "Nonlinear Static"):
                            _has_nonlinear_static = True
                            break
                    except Exception:
                        continue
            from core.opensees_port.os_capabilities import is_opensees
            if is_opensees(self.model):
                                                                          
                _os_nonlinear = (_po_info.get("engine") == "opensees"
                                 and _po_info.get("type") == "Nonlinear Static")
                if not _os_nonlinear:
                    for _rpath in getattr(self.model, 'valid_result_paths', []) or []:
                        try:
                            with open(_rpath, 'r') as _rf:
                                _rd = json.load(_rf)
                            _ri = _rd.get("info", {})
                            if (_rd.get("status") == "SUCCESS" and _ri.get("engine") == "opensees"
                                    and _ri.get("type") == "Nonlinear Static"):
                                _os_nonlinear = True
                                break
                        except (OSError, ValueError):
                            continue
                self.action_hinge_results.setEnabled(_os_nonlinear)
                self.action_os_diag.setEnabled(_os_nonlinear)
            else:
                self.action_hinge_results.setEnabled(
                    self.action_hinge_results.isEnabled()
                    or (_has_hinges_in_model and _has_nonlinear_static
                        and not is_opensees(self.model))
                )
            self.btn_deform.setChecked(True)                                
            self.canvas.view_deflected = True
            
            self.lock_model()
            info_type = data.get("info", {}).get("type", "")
            
            if info_type in ["Modal Analysis", "Buckling Analysis"]:
                                                                                   
                if "mode_shapes" in data and "Mode 1" in data["mode_shapes"]:
                    self.switch_modal_view("Mode 1")
                else:
                    self.draw_both_canvases()

                _mech = [h for h in data.get("info", {}).get("fiber_hinges", []) if h.get("near_mechanism")]
                if info_type == "Modal Analysis" and _mech:
                    self._warn_fiber_hinge_mechanism(_mech)
                    
            elif info_type == "Linear Time History Analysis":
                                             
                self.switch_modal_view("LTHA_LIVE")
                
            elif info_type == "Nonlinear Static":
                if "saved_states" in data:
                    self.switch_modal_view("LTHA_LIVE")
                else:
                    self.switch_modal_view("MAIN_RESULT")

            else:
                                                                           
                self.switch_modal_view("MAIN_RESULT")

            self._populate_statusbar_result_cases()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load results:\n{e}")
            self.canvas.view_deflected = False
            if getattr(self, 'canvas2_visible', False):
                self.canvas2.view_deflected = False
            self.unlock_model()

    def _warn_fiber_hinge_mechanism(self, mech):
        """Modal results where a fiber hinge has (almost) no stiffness in one direction."""
        def _one(h):
            s = f"{h.get('hinge') or '?'} (element {h.get('element')})"
            return f"{s}: {h['weak_text']}" if h.get('weak_text') else s
        shown = "\n".join("  \u2022 " + _one(h) for h in mech[:8])
        if len(mech) > 8:
            shown += f"\n  ... and {len(mech) - 8} more"
        QMessageBox.warning(
            self, "Fiber Hinge Mechanism",
            "This modal run included fiber hinge stiffness, and some hinges have almost no stiffness "
            "in one direction:\n\n" + shown + "\n\n"
            "That usually means the fibers all lie on one line (or one side), so the hinge cannot resist "
            "bending about the other axis. The structure can then swing freely in that direction, which "
            "shows up as a mode with a near-zero frequency (a very long period) and can distort the "
            "other modes.\n\n"
            "Check the fiber layout of these hinges: add fibers across both section directions, "
            "or untick \"Include fiber hinge stiffness\" in the modal load case.")

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
                                                                               
                    if c_type in ["Modal", "Buckling"]: 
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
        envelope = settings.get('envelope', 'max')                                 

        res_path = f"{base_path}_{load_case}_results.json"

        self.solver_output_path = res_path

        if not os.path.exists(res_path):
            self.statusBar().showMessage(f"No results on disk for '{load_case}'. Run that case first.")
            return

        with open(res_path, 'r') as f:
            case_data = json.load(f)

        if "reactions" not in case_data:
            target_key = f"reactions_{envelope}"
            case_data["reactions"] = case_data.get(target_key, {})

        self.model.results = case_data
        self.model.has_results = True

        if hasattr(self.model, 'load_combos') and load_case in self.model.load_combos:
            combo_reactions = {}
            for base_case, scale in self.model.load_combos[load_case].cases:
                bc_path = f"{base_path}_{base_case}_results.json"
                if os.path.exists(bc_path):
                    with open(bc_path, 'r') as bcf:
                        bc_data = json.load(bcf)
                        
                        bc_reactions = bc_data.get("reactions", {})
                        if not bc_reactions:
                            target_key = f"reactions_{envelope}"
                            bc_reactions = bc_data.get(target_key, {})

                        for nid, dofs in bc_reactions.items():
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
            self.statusBar().showMessage(f"[{load_case}]  Joint Reactions ({envelope.upper()})  —  {len(reaction_data)} joint(s)")
        else:
            self.statusBar().showMessage(f"No {envelope} reaction data found for this case.")
              
    def _selected_force_inspection_step(self):
        """Open an element inspector on the OpenSees state shown by its canvas."""
        from core.opensees_port.os_force_recovery import is_opensees_result
        results = getattr(self.model, 'results', {}) or {}
        if not is_opensees_result(results, self.model):
            return None
        settings = getattr(self, '_last_force_diagram_settings', {}).get(self.active_canvas, {})
        if settings.get('load_case') != results.get('info', {}).get('case_name'):
            return None
        return settings.get('step_number') if not settings.get('is_envelope', True) else None

    def apply_force_diagrams_from_dialog(self, settings):
        """Reuse saved forces, loading a cold case without blocking the dialog."""
        from core.result_file_cache import get_cached_json
        if not self.model or not self.canvas:
            return
        self._force_result_request_token = getattr(self, '_force_result_request_token', 0) + 1
        self._pending_force_result_load = None
        settings = dict(settings)
        load_case = settings['load_case']
        base_path = settings.get('base_path', '')
        res_path = f"{base_path}_{load_case}_results.json"
        self.solver_output_path = res_path
        try:
            case_data = get_cached_json(res_path)
        except OSError:
            self.statusBar().showMessage(
                f"No results on disk for '{load_case}'. Run that case first."
            )
            return
        request = (settings, self.active_canvas, self.model,
                   bool(getattr(self, '_is_syncing_forces', False)),
                   self._force_result_request_token,
                   getattr(self.active_canvas, '_force_calc_token', 0))
        if case_data is not None:
            self._apply_loaded_force_diagrams(request, case_data)
            return
        self.statusBar().showMessage(f"Loading force results for '{load_case}'…")
        self._pending_force_result_load = (request, res_path)
        self._start_pending_force_result_load()

    def _start_pending_force_result_load(self):
        if (getattr(self, '_force_result_loader', None) is not None
                or self._pending_force_result_load is None):
            return
        from app.result_file_loader import ResultFileLoader
        request, path = self._pending_force_result_load
        self._pending_force_result_load = None
        settings, canvas, model, syncing, token, canvas_token = request
        if (token != self._force_result_request_token or self.model is not model
                or self.active_canvas is not canvas or canvas_token !=
                getattr(canvas, '_force_calc_token', 0)):
            return
        loader = ResultFileLoader(path)
        loader.request = request
        loader.signals.finished.connect(self._on_force_result_loaded)
        self._force_result_loader = loader
        loader.start()

    def _on_force_result_loaded(self, loader, path, case_data, error):
        self._force_result_loader = None
        settings, canvas, model, syncing, token, canvas_token = loader.request
        if (token == self._force_result_request_token and self.model is model
                and self.active_canvas is canvas and model.has_results
                and canvas_token == getattr(canvas, '_force_calc_token', 0)):
            if error is not None or not isinstance(case_data, dict):
                self.statusBar().showMessage(
                    f"Could not load force results for '{settings['load_case']}': {error}")
            else:
                self._apply_loaded_force_diagrams(loader.request, case_data)
        self._start_pending_force_result_load()

    def _apply_loaded_force_diagrams(self, request, case_data):
        """Apply only the current request to the canvas which requested it."""
        settings, canvas, model, syncing, token, canvas_token = request
        if (token != self._force_result_request_token or self.model is not model
                or self.active_canvas is not canvas or canvas_token !=
                getattr(canvas, '_force_calc_token', 0)):
            return
        load_case = settings['load_case']
        base_path = settings.get('base_path', '')
        mat_path = f"{base_path}_{load_case}_matrices.json"

        self.model.results = dict(case_data)
        self.model.has_results = True

        displacements = case_data.get("displacements", {})
        matrices_path = mat_path if os.path.exists(mat_path) else None

        diagram_model = self.model
        diagram_selected = list(self.selected_ids)
        results_meshed = bool((case_data.get("info") or {}).get("solver_mesh"))
        if results_meshed:
            from app.solver_mesh_remap import load_mesh_context, expand_selected_frames
            ctx = load_mesh_context(self.model.file_path)
            if ctx is None:
                self.statusBar().showMessage(
                    "These results come from a solver-meshed run but the meshed model is missing. Re-run the analysis.")
                return
            diagram_model, mesh_map = ctx
            diagram_model.results = dict(case_data)
            diagram_model.has_results = True
            diagram_selected = expand_selected_frames(mesh_map, diagram_selected)

        success = self.active_canvas.show_force_diagram(
            model=diagram_model,
            component=settings['component'],
            scale_factor=settings['scale_factor'],
            displacements=displacements,
            matrices_path=matrices_path,
            show_labels=settings.get('show_labels', False),
            show_labels_mode=settings.get('show_labels_mode', 'all'),
            text_size=settings.get('text_size', None),
            selected_ids=diagram_selected,
            is_envelope=settings.get('is_envelope', True),
            step_number=settings.get('step_number', None)
        )

        if success:
            if not hasattr(self, '_last_force_diagram_settings'):
                self._last_force_diagram_settings = {}
            self._last_force_diagram_settings[self.active_canvas] = settings
            
            if not syncing and not getattr(self, '_is_syncing_forces', False):
                if not settings.get('is_envelope', True) and settings.get('step_number') is not None:
                    step_idx = settings['step_number'] - 1
                    if hasattr(self.active_canvas, 'animation_manager') and getattr(self.active_canvas, 'ltha_mode', False):
                        self._is_syncing_forces = True
                        self.active_canvas.animation_manager.scrub_to_step(step_idx)
                        self._is_syncing_forces = False
                                          
        else:
            self.statusBar().showMessage("No diagram generated. Check that analysis results exist.")

    def unlock_model(self):
                                                       
        self._hide_statusbar_results_widgets()
        self.btn_deform.setEnabled(False)
        self.btn_deform.setChecked(False)  
        self.action_display_forces.setEnabled(False)  
        self.action_display_reactions.setEnabled(False)                 
        self.action_plot_functions.setEnabled(False)
        self.action_pushover_curve.setEnabled(False)
        self.action_hinge_results.setEnabled(False)
        self.action_os_diag.setEnabled(False)
                                                             
        if hasattr(self.canvas, 'clear_force_diagrams'):
            self.canvas.clear_force_diagrams()
        if hasattr(self, 'canvas2') and hasattr(self.canvas2, 'clear_force_diagrams'):
            self.canvas2.clear_force_diagrams()
            
        if hasattr(self.canvas, 'clear_reaction_diagram'):
            self.canvas.clear_reaction_diagram(self.model)
        if hasattr(self, 'canvas2') and hasattr(self.canvas2, 'clear_reaction_diagram'):
            self.canvas2.clear_reaction_diagram(self.model)
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

        _dlg = getattr(self, "_deformed_dlg", None)
        if _dlg is not None:
            try:
                _dlg.force_exit_animation_mode()
            except Exception:
                pass
            try:
                _dlg.close()
                _dlg.deleteLater()
            except RuntimeError:
                pass
            self._deformed_dlg = None

        try:
            self._teardown_ltha_playback()
        except Exception as _e:
            print(f"[Unlock] playback teardown warning: {_e}")

        for _cvs in (self.canvas, getattr(self, 'canvas2', None)):
            if _cvs is None:
                continue
            _cvs.view_deflected = False
            _cvs.contour_active = False
            _cvs.anim_factor = 0.0
            _cvs.ltha_current_step = 0
            _cvs._ltha_loaded_case = None
            _cvs._needs_ltha_vbo_update = False
            _cvs._needs_hinge_refresh = False
            _cvs._ltha_pending_t = 0
            if hasattr(_cvs, 'animation_manager') and _cvs.animation_manager:
                try:
                    _cvs.animation_manager.disable_ltha_mode()
                except Exception:
                    pass
            if hasattr(_cvs, 'invalidate_deflection_cache'):
                _cvs.invalidate_deflection_cache()
            _vm = getattr(_cvs, 'vbo_manager', None)
            if _vm is not None and getattr(_vm, 'is_initialized', False):
                _vm.set_anim_factor(0.0)

        self.canvas._force_draw_model(self.model)
        if getattr(self, 'canvas2_visible', False):
            self.canvas2._force_draw_model(self.model)

        self.set_interface_state(True)
        
        self.btn_lock.setIcon(qta.icon('fa5s.unlock', color='#6c757d', disabled_color='#cccccc'))
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
        """Show the model's project name separately from its filename."""
        title = "Open//Structures v0.8.10"
        if self.model:
            title += f" - {self.model.name}"
            path = getattr(self.model, 'file_path', None)
            if path:
                title += f" [{os.path.basename(path)}]"
            if not self.undo_stack.isClean():
                title += " *"
        self.setWindowTitle(title)

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

    def _perform_undo(self):
        txt = self.undo_stack.undoText()
        self.undo_stack.undo()
        self.status.showMessage(f"Undid: {txt}")

    def _perform_redo(self):
        txt = self.undo_stack.redoText()
        self.undo_stack.redo()
        self.status.showMessage(f"Redid: {txt}")

    def on_display_plot_functions(self):
        """Opens the Plot Function Trace Display dialog."""
        if not self.model or not has_ltha_results(self.model):
            QMessageBox.warning(self, "No Multi-Step Results", "Run a Linear Time History or Nonlinear Static analysis first.")
            return

        if hasattr(self, '_plot_functions_dlg') and self._plot_functions_dlg is not None:
            if self._plot_functions_dlg.isVisible():
                self._plot_functions_dlg.raise_()
                self._plot_functions_dlg.activateWindow()
                return
            else:
                self._plot_functions_dlg.deleteLater()

        self._plot_functions_dlg = PlotFunctionDisplayDialog(
            parent=self,
            model=self.model,
            animation_manager=self.canvas.animation_manager if hasattr(self.canvas, 'animation_manager') else None
        )
        self._plot_functions_dlg.setWindowModality(Qt.WindowModality.NonModal)
        self._plot_functions_dlg.show()

    def on_define_pushover_params(self):
        """Define > Pushover Parameter Sets > Force vs Displacement..."""
        if not self.model:
            return
        if getattr(self, 'is_locked', False):
            self.status.showMessage("⚠️ Cannot modify model while locked. Unlock first.")
            return
        from app.dialogs.pushover_parameters_dialog import PushoverParametersDialog
        from app.commands import CmdEditPushoverParamSets
        dlg = PushoverParametersDialog(self.model, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        new_sets = dlg.result_sets()
        if new_sets == self.model.pushover_param_sets:
            return                                                                                
        self.add_command(CmdEditPushoverParamSets(self.model, self, new_sets))
        self.status.showMessage("Pushover parameter sets updated.")

    def on_show_pushover_curve(self):
        """
        Opens Analyze > Show Static Pushover Curve..., the capacity-curve
        (Base Shear vs Monitored Displacement) display dialog.

        Only Nonlinear Static cases run with Load Application Control =
        "Displacement Control" AND Results Saved = "Multiple States" carry
        what this needs (a per-step monitored displacement AND a per-step
        base reaction) -- a Full Load run has no monitored DOF, and "Final
        State Only" has no intermediate points to trace a curve through.
        Both conditions are written into "info" by nonlinear_engine.py
        specifically so this scan doesn't have to re-run anything.
        """
        import glob

        if not self.model or not getattr(self.model, 'file_path', None):
            QMessageBox.warning(self, "No Results", "Please run the analysis first.")
            return

        base_name = os.path.splitext(self.model.file_path)[0]
        result_files = getattr(self.model, 'valid_result_paths', None) or\
            glob.glob(f"{base_name}_*_results.json")

        eligible_cases = []
        prefix = os.path.basename(base_name) + "_"
        for path in sorted(result_files):
            fname = os.path.basename(path)
            if not fname.startswith(prefix) or not fname.endswith("_results.json"):
                continue
            case_name = fname[len(prefix):-len("_results.json")]
            if not case_name:
                continue
            eligible_cases.append((case_name, path))

        if not eligible_cases:
            QMessageBox.warning(
                self, "No Results",
                "No analysis results were found for this model. Please run the analysis first."
            )
            return

        if hasattr(self, '_pushover_dlg') and self._pushover_dlg is not None:
            try:
                self.combo_units.currentIndexChanged.disconnect(self._pushover_dlg.on_global_units_changed)
            except Exception:
                pass
            self._pushover_dlg.close()
            self._pushover_dlg.deleteLater()
            self._pushover_dlg = None

        self._pushover_dlg = PushoverCurveDialog(
            parent=self,
            base_name=base_name,
            case_paths=dict(eligible_cases),
            model=self.model,
        )
        if not self._pushover_dlg.has_any_eligible_case():
            QMessageBox.warning(
                self, "No Pushover Results",
                "No Nonlinear Static case with Results Saved = 'Multiple States' "
                "was found among this model's results.\n\n"
                "Run such a case first (Define > Load Cases > Nonlinear Static), "
                "then reopen this dialog."
            )
            self._pushover_dlg.deleteLater()
            self._pushover_dlg = None
            return

        active_case = (self.model.results or {}).get("info", {}).get("case_name", "")
        idx = self._pushover_dlg.combo_case.findText(active_case)
        if idx >= 0:
            self._pushover_dlg.combo_case.setCurrentIndex(idx)

        self.combo_units.currentIndexChanged.connect(self._pushover_dlg.on_global_units_changed)

        self._pushover_dlg.setWindowModality(Qt.WindowModality.NonModal)
        self._pushover_dlg.show()

    def on_show_os_diagnostics(self):
        """Analyze > Show OpenSees Diagnostics...: drift decomposition (slip / shear / flexure), strain-based
        damage events and the fit against a reference (test) curve, read from an OpenSees nonlinear static
        case's *_results.json."""
        import json
        from PyQt6.QtWidgets import QInputDialog
        found = []
        for _p in getattr(self.model, 'valid_result_paths', []) or []:
            try:
                with open(_p, 'r', encoding='utf-8') as _f:
                    _d = json.load(_f)
            except (OSError, ValueError):
                continue
            _i = _d.get("info", {})
            if (_i.get("engine") == "opensees" and _i.get("type") == "Nonlinear Static"
                    and (_i.get("opensees_history") or {}).get("u_m")):
                found.append((_i.get("case_name") or os.path.basename(_p), _p))
        if not found:
            QMessageBox.warning(self, "No OpenSees Results",
                                "Run an OpenSees Nonlinear Static case with Displacement Control first.")
            return
        path = found[0][1]
        if len(found) > 1:
            names = [n for n, _ in found]
            pick, ok = QInputDialog.getItem(self, "OpenSees Diagnostics", "Case:", names, 0, False)
            if not ok:
                return
            path = found[names.index(pick)][1]
        ref_u = ref_v = None
        curves = list(getattr(self.model, 'reference_curves', []) or [])
        if curves:
            cur = curves[0]
            if len(curves) > 1:
                cn = [str(c.get("name", f"Curve {k + 1}")) for k, c in enumerate(curves)]
                pick, ok = QInputDialog.getItem(self, "OpenSees Diagnostics", "Reference (test) curve:", cn, 0, False)
                if not ok:
                    return
                cur = curves[cn.index(pick)]
            try:
                ref_u = [float(v) * 1e3 for v in cur["x"]]                                     
                ref_v = [float(v) / 1e3 for v in cur["y"]]
            except (KeyError, TypeError, ValueError):
                ref_u = ref_v = None
        from app.dialogs.opensees_diagnostics_dialog import OpenSeesDiagnosticsDialog
        self._os_diag_dlg = OpenSeesDiagnosticsDialog(path, ref_u_mm=ref_u, ref_V_kN=ref_v, parent=self)
        self._os_diag_dlg.setWindowModality(Qt.WindowModality.NonModal)
        self._os_diag_dlg.show()

    def on_show_hinge_results(self):
        """
        Opens Analyze > Show Hinge Results..., the fiber-hinge moment-
        rotation / stress-strain inspector.

        Like Pushover Curve, this scans the model's own *_results.json
        files for Nonlinear Static cases; unlike Pushover Curve it needs
        no Displacement-Control / Multiple-States flags, only per-step
        "hinge_states" written by the solver (see hinge_results_dialog.py's
        module docstring for the exact contract) -- a solver build that
        doesn't write that yet simply has nothing to show, and the dialog
        offers a synthetic-data preview instead of a blank window.
        """
        import glob

        from core.opensees_port.os_capabilities import is_opensees
        if is_opensees(self.model):
            from app.dialogs.opensees_hinge_results_dialog import show_opensees_hinge_results
            show_opensees_hinge_results(self)
            return

        if not self.model or not getattr(self.model, 'file_path', None):
            QMessageBox.warning(self, "No Results", "Please run the analysis first.")
            return

        if not getattr(self.model, 'frame_hinges', None):
            QMessageBox.warning(
                self, "No Hinges",
                "This model has no frame hinge assignments.\n\n"
                "Assign hinges first (Assign > Frame > Hinges...)."
            )
            return

        base_name = os.path.splitext(self.model.file_path)[0]
        result_files = getattr(self.model, 'valid_result_paths', None) or\
            glob.glob(f"{base_name}_*_results.json")

        eligible_cases = []
        prefix = os.path.basename(base_name) + "_"
        for path in sorted(result_files):
            fname = os.path.basename(path)
            if not fname.startswith(prefix) or not fname.endswith("_results.json"):
                continue
            case_name = fname[len(prefix):-len("_results.json")]
            if not case_name:
                continue
            eligible_cases.append((case_name, path))

        if not eligible_cases:
            QMessageBox.warning(
                self, "No Results",
                "No analysis results were found for this model. Please run the analysis first."
            )
            return

        if hasattr(self, '_hinge_results_dlg') and self._hinge_results_dlg is not None:
            if self._hinge_results_dlg.isVisible():
                self._hinge_results_dlg.raise_()
                self._hinge_results_dlg.activateWindow()
                return
            else:
                self._hinge_results_dlg.deleteLater()

        dlg = HingeResultsDialog(
            parent=self,
            model=self.model,
            base_name=base_name,
            case_paths=dict(eligible_cases),
            selected_element_ids=list(getattr(self, 'selected_ids', [])),
            animation_manager=getattr(self.canvas, 'animation_manager', None),
        )

        if dlg.status == "no_hinges":
            reason = "\n".join(dlg.build_warnings) if dlg.build_warnings else\
                "None of this model's assigned hinges have calculated fibers."
            QMessageBox.warning(self, "No Usable Hinges", reason)
            return

        if dlg.status == "no_hinge_results":
            reply = QMessageBox.question(
                self, "No Hinge Results",
                "No result file for this model carries per-step hinge data yet "
                "(the solver doesn't write it out in this build).\n\n"
                "Open the dialog with synthetic demo data instead, to preview "
                "how it will look?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            dlg.use_demo_data()

        self._hinge_results_dlg = dlg
        self._hinge_results_dlg.setWindowModality(Qt.WindowModality.NonModal)
        self._hinge_results_dlg.show()

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
        if is_ltha:
            mgr = self.canvas.animation_manager
            current_spd = mgr.speed_factor
        n_steps = getattr(cvs, 'ltha_n_steps', 0)
        ltha_dt = getattr(cvs, 'ltha_dt', 0.01)

        res_now = getattr(self.model, 'results', None) or {}
        step_mode = bool(is_ltha
                         and res_now.get("info", {}).get("type") == "Nonlinear Static"
                         and "saved_states" in res_now)
        step_numbers = ([s.get("step", i + 1) for i, s in enumerate(res_now["saved_states"])]
                        if step_mode else None)

        if hasattr(self, '_deformed_dlg') and self._deformed_dlg is not None:
            stale = (getattr(self._deformed_dlg, 'ltha_mode', False) != is_ltha
                     or getattr(self._deformed_dlg, 'step_mode', False) != step_mode
                     or getattr(self._deformed_dlg, 'ltha_n_steps', 0) != n_steps
                     or getattr(self._deformed_dlg, 'ltha_dt', 0.01) != ltha_dt)
            if self._deformed_dlg.isVisible() and not stale:
                self._deformed_dlg.raise_()
                self._deformed_dlg.activateWindow()
                return
            else:
                self._deformed_dlg.close()
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
            contour_absolute=getattr(cvs, 'contour_absolute', False),
            step_mode=step_mode,
            step_numbers=step_numbers,
        )

        self._deformed_dlg.setWindowModality(Qt.WindowModality.NonModal)
        if is_ltha:
            self._deformed_dlg.update_scrubber(int(getattr(cvs, 'ltha_current_step', 0)))
        self._deformed_dlg.show()

    def _compute_auto_scale(self, displacements, target_fraction=0.10, saved_states=None,
                            history=None):
        """Stable display scale from the unscaled result and its full playback history."""
        from post.deformation_scale import (compute_deformation_scale,
                                           LTHA_NORMALIZED_VISUAL_INTENSITY)
        results = getattr(self.model, 'results', None) or {}
        if (results.get('info') or {}).get('type') == 'Linear Time History Analysis':
            target_fraction *= LTHA_NORMALIZED_VISUAL_INTENSITY
        return compute_deformation_scale(
            self.model, displacements, target_fraction=target_fraction,
            saved_states=saved_states, history=history,
        )

    def apply_deformed_shape(self, is_visible, scale_factor, show_shadow, shadow_color,
                              contour_enabled=False, contour_component="Resultant",
                              contour_range_auto=True, contour_min=0.0, contour_max=1.0,
                              contour_absolute=False):
        """Callback from the Dialog to update the active canvas."""
        cvs = self.active_canvas
        try:
            scale_factor = float(scale_factor)
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(scale_factor) or scale_factor <= 0.0:
            return

        if is_visible:
            if hasattr(cvs, 'clear_force_diagrams'):
                cvs.clear_force_diagrams()
            if hasattr(cvs, 'clear_reaction_diagram'):
                cvs.clear_reaction_diagram(self.model)

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
        
        if hasattr(self, '_plot_functions_dlg') and self._plot_functions_dlg and self._plot_functions_dlg.isVisible():
            self._plot_functions_dlg._sync_play_button_state()

    def toggle_animation(self, start, play_sound):
        """Called by DeformedShapeDialog."""
        is_ltha = getattr(self.active_canvas, 'ltha_mode', False)

        if start:
                                                                           
            if hasattr(self.active_canvas, 'clear_force_diagrams'):
                self.active_canvas.clear_force_diagrams()
            if hasattr(self.active_canvas, 'clear_reaction_diagram'):
                self.active_canvas.clear_reaction_diagram(self.model)

            if is_ltha:
                secondary = getattr(self, 'canvas2', None)
                if secondary is not None and secondary.animation_manager.is_running:
                    secondary.animation_manager.stop_animation()
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

                self.active_canvas.animation_manager.start_animation(update_progress)
                progress.close()

                if play_sound and self.sound_effect.source().isValid():
                    self.sound_effect.play()

            self.status.showMessage("Animation Running...")
        else:   
            if is_ltha:
                for cvs in (self.canvas, getattr(self, 'canvas2', None)):
                    if cvs is not None and cvs.animation_manager.is_running:
                        cvs.animation_manager.stop_animation()
            else:
                self.active_canvas.animation_manager.stop_animation()
            if not is_ltha:
                self.active_canvas.anim_factor = 1.0
                self.active_canvas.invalidate_animation_cache()
                self.active_canvas._force_draw_model(
                    self.model,
                    self.selected_ids,
                    self.selected_node_ids
                )
            if self.sound_effect.isPlaying():
                self.sound_effect.stop()
            self.status.showMessage("Animation Paused." if is_ltha else "Animation Stopped.")

    def _attach_hinge_state_history(self, data):
        """Precompute the most critical fiber state of every hinge at every saved
        step, so the viewport can colour hinge markers during playback."""
        self.canvas.ltha_hinge_state_idx = None
        self.canvas._ltha_hinge_cache = None
        self.canvas._ltha_vbo_built = False                                                                
        try:
            is_ns = (data.get("info", {}).get("type") == "Nonlinear Static"
                     and bool(data.get("saved_states")))
            if is_ns:
                                                                             
                self.canvas.ltha_current_step = len(data["saved_states"]) - 1
            from core.opensees_port.os_force_recovery import is_opensees_result
            if is_opensees_result(data):
                                                                          
                return
            if is_ns and getattr(self.model, "frame_hinges", None):
                from app.dialogs.hinge_results_dialog import compute_hinge_state_history
                hist = compute_hinge_state_history(self.model, data["saved_states"])
                self.canvas.ltha_hinge_state_idx = hist or None
        except Exception as e:
            print(f"[Main] Hinge state history unavailable (markers keep default colour): {e}")

    def _on_ltha_frame_tick(self, t_index):
        """
        Called every animation tick in LTHA mode.
        Keeps the scrubber slider and time label in sync with playback.
        """
                                                                                   
        for cvs in (self.canvas, getattr(self, 'canvas2', None)):
            if (cvs is not None and getattr(cvs, 'ltha_mode', False)
                    and getattr(cvs, 'ltha_current_step', 0) != t_index):
                cvs.animation_manager.ltha_current_step = t_index
                if cvs is self.canvas or getattr(self, 'canvas2_visible', False):
                    cvs._on_ltha_frame(t_index)
                else:
                    cvs.ltha_current_step = t_index
        if hasattr(self, 'status_scrubber_widget') and self.status_scrubber_widget.isVisible():
            if not getattr(self, '_syncing_status_scrubber', False):
                self._syncing_status_scrubber = True
                clamped = max(0, min(int(t_index), self.slider_status_step.maximum()))
                self.slider_status_step.setValue(clamped)
                self.spin_status_step.setValue(clamped)
                self._syncing_status_scrubber = False

        if hasattr(self, '_deformed_dlg') and self._deformed_dlg is not None:
            try:
                if self._deformed_dlg.isVisible():
                    self._deformed_dlg.update_scrubber(t_index)
            except RuntimeError:
                self._deformed_dlg = None
                
        if getattr(self, '_is_syncing_forces', False):
            return
            
        mgr = getattr(self.canvas if getattr(self.active_canvas, 'ltha_mode', False)
                      else self.active_canvas, 'animation_manager', None)
        if getattr(mgr, 'is_running', False):
            return

        cvs = self.active_canvas
        forces_active = getattr(cvs, 'force_diagram_active', False)
        last_settings = getattr(self, '_last_force_diagram_settings', {}).get(cvs)
        
        if forces_active and last_settings:
            if not last_settings.get('is_envelope', True):
                if last_settings.get('step_number') != t_index + 1:
                    self._is_syncing_forces = True
                    
                    last_settings['step_number'] = t_index + 1
                    
                    if hasattr(self, 'forces_dialog') and self.forces_dialog:
                        try:
                                                                                                    
                            self.forces_dialog.__class__.last_settings['step_number'] = t_index + 1
                            
                            if self.forces_dialog.isVisible():
                                self.forces_dialog.sb_step.blockSignals(True)
                                self.forces_dialog.sb_step.setValue(t_index + 1)
                                self.forces_dialog.sb_step.blockSignals(False)
                                self.forces_dialog._update_saved_state_details()
                        except RuntimeError:
                            self.forces_dialog = None

                    self.apply_force_diagrams_from_dialog(last_settings)
                    
                    self._is_syncing_forces = False
                            
    def set_animation_speed(self, speed_factor):
        """Called by speed toggle buttons to change animation speed live."""
        cvs = self.canvas if getattr(self.active_canvas, 'ltha_mode', False) else self.active_canvas
        if hasattr(cvs, 'animation_manager'):
            cvs.animation_manager.set_speed(speed_factor)

    def set_ltha_playback_range(self, t_start_s, t_end_s):
        """Use Start/End as a live playback loop without preparing geometry frames."""
        mgr = self.canvas.animation_manager
        if not mgr.ltha_mode or self.canvas.ltha_n_steps < 1:
            return False
        try:
            start_time, end_time = float(t_start_s), float(t_end_s)
            dt = float(self.canvas.ltha_dt)
        except (TypeError, ValueError, OverflowError):
            return False
        if (not all(math.isfinite(value) for value in (start_time, end_time, dt))
                or dt <= 0.0 or start_time > end_time):
            return False
        last_step = self.canvas.ltha_n_steps - 1
        start = max(0, min(last_step, int(round(start_time / dt))))
        end = max(0, min(last_step, int(round(end_time / dt))))
        if not mgr.set_ltha_playback_range(start, end):
            return False
        highlight = None if (start == 0 and end == last_step) else (start * dt, end * dt)
        for cvs in (self.canvas, getattr(self, 'canvas2', None)):
            if cvs is None or not getattr(cvs, 'ltha_mode', False):
                continue
            cvs.animation_manager.ltha_playback_start = mgr.ltha_playback_start
            cvs.animation_manager.ltha_playback_end = mgr.ltha_playback_end
            cvs.ltha_highlight = highlight
            cvs._invalidate_accel_pixmap()
            cvs.update()
        return True

    def on_define_mass_source(self):
        if not self.model: return
        dialog = MassSourceManagerDialog(self.model, self)
        dialog.exec()

    def on_define_virtual_measurements(self):
        if not self.model: return
        from app.dialogs.virtual_measurements_dialog import VirtualMeasurementsDialog
        dialog = VirtualMeasurementsDialog(self.model, self)
        dialog.exec()
        self.status.showMessage("Virtual Measurements Updated.")

    def on_show_modal_results(self):
        if not self.model or not self.model.results:
            QMessageBox.warning(self, "No Results", "Please run an Analysis first.")  
            return

        filter_node_ids = [str(nid) for nid in self.selected_node_ids] if self.selected_node_ids else None

        from app.dialogs.analysis_results_dialog import AnalysisResultsDialog 
        dlg = AnalysisResultsDialog(self.model, self.model.results, self, selected_node_ids=filter_node_ids)
        dlg.exec()

    def _teardown_ltha_playback(self):
        """
        Tears down any live LTHA playback state on the canvas — stops the
        animation loop, disconnects the frame-update signal from everything
        that was listening to it, clears the loaded time-history tensor, and
        rebuilds the Deformed Shape dialog if it's open (so its scrubber
        actually disappears instead of lingering from the previous case).
        Called whenever the active view moves away from an LTHA case's Live
        mode to something else (a different static/modal case, or that same
        LTHA case's own envelope) so a stale tensor + scale mismatch can't
        keep driving the canvas and make the model appear to oscillate.
        """
        for cvs in (self.canvas, getattr(self, 'canvas2', None)):
            if cvs is None:
                continue
            mgr = getattr(cvs, "animation_manager", None)
            if mgr:
                listeners = [cvs._on_ltha_frame, getattr(self, "_on_ltha_frame_tick", None)]
                if getattr(self, "_node_res_dlg", None):
                    listeners.append(self._node_res_dlg.update_live_values)
                for sig_target in listeners:
                    if sig_target is None:
                        continue
                    try:
                        mgr.signal_ltha_frame_update.disconnect(sig_target)
                    except Exception:
                        pass
                if getattr(mgr, "is_running", False):
                    mgr.stop_animation()
                mgr.disable_ltha_mode()
            if hasattr(cvs, "clear_ltha_history"):
                cvs.clear_ltha_history()
            cvs._ltha_loaded_case = None
            cvs._ltha_loaded_source = None

    def _results_status_text(self, info_type):
        """Status-bar text for the loaded result, driven by the result type (not the view path)."""
        case_name = (self.model.results.get("info", {}) or {}).get("case_name", "")
        suffix = f" — {case_name}" if case_name else ""
        if info_type == "Linear Time History Analysis":
            return f"Displaying: Linear Time History{suffix} (live playback)"
        if info_type == "Nonlinear Static":
            return f"Displaying: Nonlinear Static{suffix} (step playback)"
        return f"Displaying: {info_type or 'Results'}{suffix}"

    def switch_modal_view(self, mode_key):
        if not self.model or not self.model.results: return
        
        target_data = {}
        info_type = self.model.results.get("info", {}).get("type", "")

        if mode_key == "MAIN_RESULT" and info_type == "Nonlinear Static" and self.model.results.get("saved_states"):
            mode_key = "LTHA_LIVE"

        if mode_key != "LTHA_LIVE":
            self._teardown_ltha_playback()

        if mode_key == "MAIN_RESULT" or mode_key == "LTHA_LIVE":

            if mode_key == "LTHA_LIVE":
                info = self.model.results.get("info", {})
                history_path = self.model.results.get("history_path", "")
                case_name = info.get("case_name", "")

                is_multistep_live = bool(self.model.results.get("saved_states"))
                if is_multistep_live:
                    source = (info_type, case_name, id(self.model.results["saved_states"]))
                elif history_path and os.path.exists(history_path):
                    stat = os.stat(history_path)
                    source = (info_type, case_name, os.path.abspath(history_path),
                              stat.st_mtime_ns, stat.st_size, info.get('dt', 0.01))
                else:
                    source = None
                needs_history = (not getattr(self.canvas, 'ltha_mode', False)
                                 or getattr(self.canvas, '_ltha_loaded_source', None) != source)
                if needs_history:
                    self._teardown_ltha_playback()
                
                if is_multistep_live:
                    if needs_history:
                        import numpy as np
                        history_dict = {}
                        for step in self.model.results["saved_states"]:
                            for nid, dofs in step.get("displacements", {}).items():
                                if nid not in history_dict: history_dict[nid] = []
                                history_dict[nid].append(dofs)
                        self.canvas.ltha_history = {nid: np.array(arr) for nid, arr in history_dict.items()}
                        self.canvas.ltha_n_steps = len(self.model.results["saved_states"])
                        self.canvas.ltha_dt = 1.0
                        self.canvas._ltha_loaded_case = case_name
                        self.canvas._ltha_loaded_source = source
                        self.canvas.ltha_mode = True
                        self._attach_hinge_state_history(self.model.results)
                        self.canvas.animation_manager.enable_ltha_mode(self.canvas.ltha_n_steps, 1.0)
                        
                        for sig_target in (self.canvas._on_ltha_frame, self._on_ltha_frame_tick):
                            try: self.canvas.animation_manager.signal_ltha_frame_update.disconnect(sig_target)
                            except Exception: pass
                            self.canvas.animation_manager.signal_ltha_frame_update.connect(sig_target)
                            
                        if getattr(self, '_node_res_dlg', None):
                            try: self.canvas.animation_manager.signal_ltha_frame_update.disconnect(self._node_res_dlg.update_live_values)
                            except Exception: pass
                            self.canvas.animation_manager.signal_ltha_frame_update.connect(self._node_res_dlg.update_live_values)
                            
                    if hasattr(self, 'action_plot_functions'):
                        self.action_plot_functions.setEnabled(True)
                
                elif history_path and os.path.exists(history_path):
                    if needs_history:
                        dt = info.get("dt", 0.01)
                        accel = self.model.results.get("accel_history", None)
                        if not self.canvas.load_ltha_history(history_path, dt, accel=accel):
                            self._teardown_ltha_playback()
                            return self.switch_modal_view("MAIN_RESULT")
                        self.canvas._ltha_loaded_case = case_name
                        self.canvas._ltha_loaded_source = source
                        self.canvas.animation_manager.enable_ltha_mode(self.canvas.ltha_n_steps, dt)

                        for sig_target in (self.canvas._on_ltha_frame, self._on_ltha_frame_tick):
                            try:
                                self.canvas.animation_manager.signal_ltha_frame_update.disconnect(sig_target)
                            except Exception:
                                pass
                            self.canvas.animation_manager.signal_ltha_frame_update.connect(sig_target)

                        if getattr(self, '_node_res_dlg', None):
                            try:
                                self.canvas.animation_manager.signal_ltha_frame_update.disconnect(self._node_res_dlg.update_live_values)
                            except Exception:
                                pass
                            self.canvas.animation_manager.signal_ltha_frame_update.connect(self._node_res_dlg.update_live_values)

                    if hasattr(self, 'action_plot_functions'):
                        self.action_plot_functions.setEnabled(True)
                else:
                    self._teardown_ltha_playback()
                    mode_key = "MAIN_RESULT"
                    print(f"Warning: No usable history for '{case_name}'; displaying its envelope.")

                if not getattr(self.canvas, 'ltha_mode', False):
                    self._teardown_ltha_playback()
                    mode_key = "MAIN_RESULT"
                else:
                    secondary = getattr(self, 'canvas2', None)
                    if secondary is not None:
                        secondary.ltha_history = self.canvas.ltha_history
                        secondary.ltha_n_steps = self.canvas.ltha_n_steps
                        secondary.ltha_dt = self.canvas.ltha_dt
                        secondary.ltha_mode = True
                        secondary._ltha_loaded_case = case_name
                        secondary._ltha_loaded_source = source
                        secondary.ltha_current_step = self.canvas.ltha_current_step
                        secondary.ltha_hinge_state_idx = self.canvas.ltha_hinge_state_idx
                        secondary.animation_manager.enable_ltha_mode(secondary.ltha_n_steps, secondary.ltha_dt)
                        secondary.animation_manager.ltha_current_step = secondary.ltha_current_step
                        for sig_target in (secondary._on_ltha_frame, self._on_ltha_frame_tick):
                            try:
                                secondary.animation_manager.signal_ltha_frame_update.disconnect(sig_target)
                            except Exception:
                                pass
                            secondary.animation_manager.signal_ltha_frame_update.connect(sig_target)

            if mode_key == "LTHA_LIVE" and "saved_states" in self.model.results:
                    target_data = self.model.results["saved_states"][-1].get("displacements", {})
            else:
                target_data = self.model.results.get("_base_displacements", self.model.results.get("displacements", {}))
            
            if info_type == "Linear Time History Analysis" and mode_key == "MAIN_RESULT":
                self.status.showMessage(f"Displaying: Linear Time History — {self.model.results.get('info', {}).get('case_name', '')} (envelope)")
            else:
                self.status.showMessage(self._results_status_text(info_type))

        else:
            shapes = self.model.results.get("mode_shapes", {})
            if mode_key in shapes:
                target_data = shapes[mode_key]
                self.status.showMessage(f"Displaying: {mode_key}")
            else:
                print(f"Warning: {mode_key} not found in results.")
                return

        self.model.results["displacements"] = target_data

        for cvs in (self.canvas, getattr(self, 'canvas2', None)):
            if cvs is not None and hasattr(cvs, 'set_selection_ltha_live'):
                cvs.set_selection_ltha_live(mode_key == "LTHA_LIVE")

        history = self.canvas.ltha_history if mode_key == "LTHA_LIVE" else None
        auto_scale = self._compute_auto_scale(
            target_data, saved_states=self.model.results.get("saved_states"), history=history,
        )
        self.canvas.auto_deflection_scale = auto_scale
        self.canvas.deflection_scale = auto_scale
        self.canvas2.auto_deflection_scale = auto_scale
        self.canvas2.deflection_scale = auto_scale

        if not self.canvas.view_deflected:
            self.canvas.view_deflected = True
        self.canvas2.view_deflected = True

        self.canvas.anim_factor = 1.0
        self.canvas2.anim_factor = 1.0

        self.canvas.invalidate_deflection_cache()
        self.canvas2.invalidate_deflection_cache()

        if hasattr(self.canvas, 'animation_manager'):
            self.canvas.animation_manager.invalidate_prerender()

        if getattr(self.canvas, 'ltha_mode', False):
            for cvs in (self.canvas, self.canvas2):
                cvs._ltha_vbo_built = False
                if "saved_states" in self.model.results:
                    last_idx = max(0, len(self.model.results["saved_states"]) - 1)
                    cvs.ltha_current_step = last_idx
                    if hasattr(cvs, 'animation_manager'):
                        cvs.animation_manager.ltha_current_step = last_idx

        self.draw_both_canvases()

        if mode_key == "LTHA_LIVE":
            for cvs in (self.canvas, self.canvas2):
                cvs.refresh_deformed_playback()

        self.status.showMessage(f"{self.status.currentMessage()} (Auto-Scale: {auto_scale:.6g}x)")

        if getattr(self, "_deformed_dlg", None) and self._deformed_dlg.isVisible():
            current_is_ltha = getattr(self.active_canvas, "ltha_mode", False)
            if (getattr(self._deformed_dlg, "ltha_mode", False) != current_is_ltha
                    or getattr(self._deformed_dlg, "ltha_n_steps", 0) != self.active_canvas.ltha_n_steps
                    or getattr(self._deformed_dlg, "ltha_dt", 0.01) != self.active_canvas.ltha_dt
                    or getattr(self._deformed_dlg, "step_mode", False) != (
                        info_type == "Nonlinear Static" and current_is_ltha)):
                self.on_view_deformed_shape()
            else:
                self._deformed_dlg.update_auto_scale(auto_scale)
                self._deformed_dlg.spin_scale.blockSignals(True)
                self._deformed_dlg.spin_scale.setValue(auto_scale)
                self._deformed_dlg.spin_scale.blockSignals(False)
                if current_is_ltha:
                    self._deformed_dlg.update_scrubber(int(getattr(self.active_canvas, 'ltha_current_step', 0)))

    def sync_canvas_to_case(self, case_name: str, step_index: int = None) -> bool:
        """Loads `case_name` onto the 3D canvas in LTHA_LIVE deformed-shape mode
        and optionally scrubs to `step_index`."""
        import json
        if not self.model or not getattr(self.model, 'file_path', None) or not case_name:
            return False

        base_name = os.path.splitext(self.model.file_path)[0]
        res_path = f"{base_name}_{case_name}_results.json"
        if not os.path.exists(res_path):
            return False

        for cvs in (self.canvas, getattr(self, 'canvas2', None)):
            if cvs is not None:
                if hasattr(cvs, 'clear_force_diagrams'):
                    cvs.clear_force_diagrams()
                if hasattr(cvs, 'clear_reaction_diagram'):
                    cvs.clear_reaction_diagram(self.model)

        need_load = (
            getattr(self.canvas, '_ltha_loaded_case', None) != case_name
            or not getattr(self.canvas, 'ltha_mode', False)
        )
        if need_load:
            try:
                with open(res_path, 'r') as f:
                    data = json.load(f)
            except Exception:
                return False
            if data.get("status") != "SUCCESS":
                return False

            self.solver_output_path = res_path
            self.model.results = data
            if "displacements" in data:
                self.model.results["_base_displacements"] = data["displacements"].copy()
            self.model.has_results = True
            self.btn_deform.setChecked(True)
            self.switch_modal_view("LTHA_LIVE")
        elif not self.canvas.view_deflected:
            self.btn_deform.setChecked(True)
            self.canvas.view_deflected = True
            if hasattr(self, 'canvas2'):
                self.canvas2.view_deflected = True
            self.draw_both_canvases()

        if step_index is not None and hasattr(self.canvas, 'animation_manager') and getattr(self.canvas, 'ltha_mode', False):
            self.canvas.animation_manager.scrub_to_step(int(step_index))

        return True

    def showEvent(self, event):
        """
        Re-apply our own title bar theme every time the window is actually
        mapped/shown. Windows/Qt can repaint the native frame to match the
        Windows system theme at map time, which would silently undo the
        DwmSetWindowAttribute call made in __init__; reapplying here makes
        sure our own Dark/Light setting always wins.
        """
        super().showEvent(event)
        apply_windows_titlebar_theme(self)
                                                                           
        QTimer.singleShot(0, lambda: apply_windows_titlebar_theme(self))
        QTimer.singleShot(150, lambda: apply_windows_titlebar_theme(self))

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

    def on_run_solid_analysis(self):
        if not self.model: return
        dlg = SolidAnalysisDialog(self)
        dlg.show()  

    def _on_model_changed(self, idx):
        """Called on every undo stack push/undo/redo — syncs loads and canvases."""
        if self.model:
            if getattr(self, '_loads_only_refresh', False):
                self._loads_only_refresh = False
                self.update_yield_lines()
                self.refresh_load_display()
                self.model_tree.refresh()
                return
            if getattr(self, '_supports_only_refresh', False):
                self._supports_only_refresh = False
                self._refresh_supports_fast()
                return
            self.update_yield_lines()
            self.draw_both_canvases()
            self.model_tree.refresh()

    def _refresh_supports_fast(self):
        """Restraint / spring assignment only changes the support glyphs, so skip the
        full scene rebuild.  Prints per-step timings to the console."""
        import time as _t
        t0 = _t.perf_counter()
        cvs = [self.canvas]
        if getattr(self, 'canvas2_visible', False):
            cvs.append(self.canvas2)
        if getattr(self, 'canvas_2d', None):
            cvs.append(self.canvas_2d)

        for cv in cvs:
            if hasattr(cv, 'refresh_supports_only'):
                cv.refresh_supports_only()
            else:
                cv.draw_model(self.model)
        t1 = _t.perf_counter()

        sel_changed = False
        for cv in cvs:
            if list(getattr(cv, 'selected_node_ids', [])) != list(self.selected_node_ids) or\
               list(getattr(cv, 'selected_element_ids', [])) != list(self.selected_ids):
                sel_changed = True
                cv.update_selection_overlay(self.selected_ids, self.selected_node_ids,
                                            getattr(self, 'selected_area_ids', []),
                                            getattr(self, 'selected_link_ids', []),
                                            getattr(self, 'selected_tendon_ids', []))
        if sel_changed:
            self.model_tree.sync_selection(
                sel_nodes=self.selected_node_ids, sel_elems=self.selected_ids,
                sel_areas=getattr(self, 'selected_area_ids', []),
                sel_links=getattr(self, 'selected_link_ids', []),
                sel_tendons=getattr(self, 'selected_tendon_ids', []),
                sel_cables=getattr(self, 'selected_cable_ids', []),
            )
        t2 = _t.perf_counter()

        self.model_tree.refresh()
        t3 = _t.perf_counter()
        print(f"[assign timing] supports {t1-t0:.3f}s | selection {t2-t1:.3f}s | model_tree.refresh {t3-t2:.3f}s | total {t3-t0:.3f}s")

    def draw_both_canvases(self, sel_elems=None, sel_nodes=None, progress=None):
        """Draw the model on both canvases with consistent selection state."""
        if not self.model:
            return
        self._supports_only_refresh = False
        e = sel_elems if sel_elems is not None else self.selected_ids
        n = sel_nodes if sel_nodes is not None else self.selected_node_ids

        for cv in (getattr(self, 'canvas', None), getattr(self, 'canvas2', None)):
            if cv is None:
                continue
            cv.selected_area_ids = list(getattr(self, 'selected_area_ids', []))
            cv.selected_link_ids = list(getattr(self, 'selected_link_ids', []))
            cv.selected_tendon_ids = list(getattr(self, 'selected_tendon_ids', []))
            cv.selected_cable_ids = list(getattr(self, 'selected_cable_ids', []))

        self.model_tree.sync_selection(
            sel_nodes=n, sel_elems=e,
            sel_areas=getattr(self, 'selected_area_ids', []),
            sel_links=getattr(self, 'selected_link_ids', []),
            sel_tendons=getattr(self, 'selected_tendon_ids', []),
            sel_cables=getattr(self, 'selected_cable_ids', []),
        )

        self.canvas.draw_model(self.model, e, n, progress=progress)
        if getattr(self, 'canvas2_visible', False):
            self.canvas2.draw_model(self.model, e, n)

        if hasattr(self, 'canvas_2d') and self.canvas_2d: 
            self.canvas_2d.draw_model(self.model, progress=progress)

    def request_load_refresh(self):
        """The undo-stack callback draws the final load state once."""
        self._loads_only_refresh = True

    def refresh_load_display(self):
        """Load assignments update overlays without rebuilding structural geometry."""
        if self.model is None:
            return
        self._supports_only_refresh = False
        self.model_tree.sync_selection(
            sel_nodes=self.selected_node_ids, sel_elems=self.selected_ids,
            sel_areas=getattr(self, 'selected_area_ids', []),
            sel_links=getattr(self, 'selected_link_ids', []),
            sel_tendons=getattr(self, 'selected_tendon_ids', []),
            sel_cables=getattr(self, 'selected_cable_ids', []))
        canvases = [self.canvas]
        if getattr(self, 'canvas2_visible', False):
            canvases.append(self.canvas2)
        for cv in canvases:
            cv.selected_cable_ids = list(getattr(self, 'selected_cable_ids', []))
            manager = getattr(cv, 'vbo_manager', None)
            if (getattr(cv, 'current_model', None) is self.model and
                    getattr(manager, 'is_initialized', False)):
                cv.update_selection_overlay(self.selected_ids, self.selected_node_ids,
                    getattr(self, 'selected_area_ids', []), getattr(self, 'selected_link_ids', []),
                    getattr(self, 'selected_tendon_ids', []))
            else:
                cv.selected_area_ids = list(getattr(self, 'selected_area_ids', []))
                cv.selected_link_ids = list(getattr(self, 'selected_link_ids', []))
                cv.selected_tendon_ids = list(getattr(self, 'selected_tendon_ids', []))
                cv.draw_model(self.model, self.selected_ids, self.selected_node_ids)
        canvas_2d = getattr(self, 'canvas_2d', None)
        if canvas_2d is not None and canvas_2d.isVisible():
            canvas_2d.draw_model(self.model)

    def _on_tree_selection_requested(self, sel_dict):
        """Tree -> canvas: user clicked an entity in the Model Browser.
        Replaces the whole selection with just that entity (single-select,
        matching how clicking a tree item behaves)."""
        self.selected_node_ids = self._filter_pickable('node', sel_dict.get("nodes", []))
        self.selected_ids = self._filter_pickable('frame', sel_dict.get("elements", []))
        self.selected_area_ids = self._filter_pickable('area', sel_dict.get("areas", []))
        self.selected_link_ids = self._filter_pickable('link', sel_dict.get("links", []))
        self.selected_tendon_ids = self._filter_pickable('tendon', sel_dict.get("tendons", []))
        self.selected_cable_ids = self._filter_pickable('cable', sel_dict.get("cables", []))
                                                                                           
        for cvs in self._selection_canvases():
            cvs.selected_cable_ids = self.selected_cable_ids
            cvs.update_selection_overlay(self.selected_ids, self.selected_node_ids, self.selected_area_ids, self.selected_link_ids, self.selected_tendon_ids)

    def _delete_tree_selection(self):
        """Delete key / context-menu delete from the Model Browser — reuses
        the existing delete_current_selection() -> CmdDeleteSelection pipeline
        so undo/redo behaves exactly like a canvas-driven delete."""
        sel = self.model_tree.selected_entity_ids()
        self.selected_node_ids = sel.get("nodes", [])
        self.selected_ids = sel.get("elements", [])
        self.selected_area_ids = sel.get("area_elements", [])
        self.selected_link_ids = sel.get("links", [])
        self.selected_tendon_ids = sel.get("tendons", [])
        self.selected_cable_ids = sel.get("cables", [])
        self.delete_current_selection()

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
        self.model_tree.refresh()
        self.status.showMessage(f"Loaded via terminal: {new_model.file_path}")
        self._record_recent_project(new_model.file_path, model=new_model)

    def _on_cli_model_saved(self, model):
        """Called by TerminalPanel when the CLI 'save' command succeeds."""
        self.undo_stack.setClean()
        self.update_window_title()
        self.status.showMessage(f"Saved via terminal: {model.file_path}")
        self._record_recent_project(model.file_path, model=model, saved=True)

    def _toolbar_toggle_deform(self, checked):
        """Directly toggles the deformed shape on the active canvas without opening the dialog."""
        if not self.model or not self.model.has_results:
            return

        if checked:
            if hasattr(self.active_canvas, 'clear_force_diagrams'):
                self.active_canvas.clear_force_diagrams()
            if hasattr(self.active_canvas, 'clear_reaction_diagram'):
                self.active_canvas.clear_reaction_diagram(self.model)

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

    def on_assign_area_insertion_point(self):
        """Assign > Area > Insertion Point..."""
        if not self.model:
            return
        if not hasattr(self, 'area_insertion_dlg') or not self.area_insertion_dlg.isVisible():
            from app.dialogs.assign_area_insertion_point_dialog import AssignAreaInsertionPointDialog
            self.area_insertion_dlg = AssignAreaInsertionPointDialog(self)
            self.area_insertion_dlg.show()
        else:
            self.area_insertion_dlg.raise_()

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

        apply_as = params.get("apply_as", "divide")

        if apply_as == "clear":
            from app.commands import CmdAssignAreaSolverMesh
            self.add_command(CmdAssignAreaSolverMesh(self.model, self, list(selected_ids), None))
            self.status.showMessage("Solver mesh cleared.", 3000)
            return

        if apply_as == "join":
            from app.commands import CmdAssignAreaSolverMesh, CmdJoinAreaElements
            if getattr(self, 'is_locked', False):
                self.status.showMessage("Cannot modify model while locked. Unlock first.")
                return
            areas = getattr(self.model, 'area_elements', {})
            solver_ids = [a for a in selected_ids if getattr(areas.get(a), 'solver_mesh', None)]
            real_ids = [a for a in selected_ids if a in areas and a not in solver_ids]
            msgs = []
            self.undo_stack.beginMacro("Join Areas") if hasattr(self, 'undo_stack') else None
            try:
                if solver_ids:                                                                 
                    self.add_command(CmdAssignAreaSolverMesh(self.model, self, solver_ids, None))
                    msgs.append(f"Solver mesh removed from {len(solver_ids)} shell(s).")
                if len(real_ids) >= 2:                                                   
                    cmd = CmdJoinAreaElements(self.model, self, real_ids,
                                              rejoin_frames=params.get("divide_frames", True))
                    try:
                        r = cmd.prepare()
                        self.add_command(cmd)
                        msgs.append(f"Joined {len(r['removed_area_ids'])} shells into shell {r['created_area_id']}.")
                        if r["rejoined_frames"]:
                            msgs.append(f"{len(r['rejoined_frames'])} split frame(s) re-joined.")
                        left = len(r["hanging_node_ids"]) - len(r["rejoined_frames"])
                        if left > 0:
                            msgs.append(f"{left} edge node(s) remain (shared with neighbours).")
                    except (ValueError, KeyError) as e:
                        from PyQt6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "Join Areas", str(e))
                elif real_ids and not solver_ids:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.information(self, "Join Areas", "Select at least two shells to join.")
            finally:
                self.undo_stack.endMacro() if hasattr(self, 'undo_stack') else None
            if msgs:
                self.status.showMessage("  ".join(msgs), 5000)
                if hasattr(self.canvas, 'clear_selection'):
                    self.canvas.clear_selection()
            return

        if params["mode"] == "divisions" and params["n"] == 1 and params["m"] == 1:
            return

        if apply_as == "solver":
            from app.commands import CmdAssignAreaSolverMesh
            solver_mesh = {
                "mode": params["mode"], "n": params["n"], "m": params["m"],
                "max_x": params["max_x"], "max_y": params["max_y"],
                "divide_frames": params["divide_frames"],
            }
            self.add_command(CmdAssignAreaSolverMesh(self.model, self, list(selected_ids), solver_mesh))
            self.status.showMessage("Solver mesh assigned.", 4000)
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
        self.canvas.show_grid            = gs.get('show_grid', True)
        self.canvas.show_ghost_structure = gs.get('show_ghost_structure', True)
        self.canvas.show_hinges          = gs.get('show_hinges', True)
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

        active_plane_state = getattr(canvas, '_plane_state', 0)
        for axis in ("XY", "XZ", "YZ"):
            self._set_plane_button_state(axis, active_plane_state if vm == axis else 0)
        
        if getattr(self, 'cross_brace_mode_active', False) and self.cross_brace_dialog and self.cross_brace_dialog.isVisible():
            self.cross_brace_dialog.update_plane_status(canvas.active_view_plane)
        self._update_quick_area_plane_status()
            
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
                                                                            
                        obj._suppress_next_click_selection = True
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
                
                if getattr(self, 'is_locked', False) or self.model is None:
                    ui_theme = self.graphics_settings.get("ui_theme", "Light")
                    c = QColor(30, 30, 30) if ui_theme == "Dark" else QColor('#F8F9FA')
                else:
                    bg_tuple = self.graphics_settings.get("background_color", (1.0, 1.0, 1.0, 1.0))
                    c = QColor()
                    c.setRgbF(bg_tuple[0], bg_tuple[1], bg_tuple[2], bg_tuple[3])
                    
                self.canvas2.setBackgroundColor(c)

                self.canvas2.makeCurrent()
                if not self.canvas2.vbo_manager.is_initialized:
                    self.canvas2.vbo_manager.init_gl()

                if self.model:
                    self.canvas2.selected_area_ids = list(getattr(self, 'selected_area_ids', []))
                    self.canvas2.selected_link_ids = list(getattr(self, 'selected_link_ids', []))
                    self.canvas2.selected_tendon_ids = list(getattr(self, 'selected_tendon_ids', []))
                    self.canvas2.selected_cable_ids = list(getattr(self, 'selected_cable_ids', []))
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

    def on_assign_tendon_load(self):
        if not hasattr(self.model, 'tendons') or not self.model.tendons:
            QMessageBox.warning(
                self, 
                "Warning", 
                "This command requires at least one tendon object to exist in the model. The command will be aborted."
            )
            return

        selected_tendons = getattr(self, 'selected_tendon_ids', [])
        if not selected_tendons:
            QMessageBox.information(self, "Selection Required", "Please select at least one tendon to assign loads.")
            return

        from app.dialogs.tendon_load_dialog import TendonLoadDialog
        from app.commands import CmdAssignTendonLoad

        dlg = TendonLoadDialog(self.model, self)
        if dlg.exec():
            data = dlg.get_data()
            cmd = CmdAssignTendonLoad(self.model, self, selected_tendons, data)
            self.add_command(cmd)
            self.status.showMessage(f"Assigned tendon loads to {len(selected_tendons)} tendon(s).")

    def on_define_cable_sections(self):
        if not self.model: return
        from app.dialogs.cable_dialog import CableManagerDialog
        dialog = CableManagerDialog(self.model, self)
        dialog.exec()
        self.draw_both_canvases()

    def on_assign_cable_load(self):
        if not hasattr(self.model, 'cables') or not self.model.cables:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, 
                "Warning", 
                "This command requires at least one cable object to exist in the model."
            )
            return

        selected_cables = getattr(self, 'selected_cable_ids', [])
        if not selected_cables:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Selection Required", "Please select at least one cable to assign loads.")
            return

        from app.dialogs.cable_load_dialog import AssignCableLoadDialog
        from app.commands import CmdAssignCableLoad

        if not hasattr(self, '_cable_load_dlg') or not self._cable_load_dlg.isVisible():
            self._cable_load_dlg = AssignCableLoadDialog(self.model, self)
            
            def apply_loads():
                data = self._cable_load_dlg.get_data()
                if data:
                    cmd = CmdAssignCableLoad(self.model, self, selected_cables, data)
                    self.add_command(cmd)
                    self.status.showMessage(f"Assigned distributed loads to {len(selected_cables)} cable(s).")
            
            self._cable_load_dlg.btn_apply.clicked.connect(apply_loads)
            
            def accept_loads():
                apply_loads()
                self._cable_load_dlg.accept()
                
            self._cable_load_dlg.btn_ok.clicked.disconnect()
            self._cable_load_dlg.btn_ok.clicked.connect(accept_loads)

        self._cable_load_dlg.show()
        self._cable_load_dlg.raise_()
        self._cable_load_dlg.activateWindow()

    def _record_recent_project(self, filepath=None, model=None, saved=False):
        """History and preview failures must never turn a model save into a failure."""
        model = model if model is not None else self.model
        filepath = filepath or getattr(model, 'file_path', None)
        if not model or not filepath:
            return
        if not saved and model is self.model:
            self._history_controller.note_opened(filepath)
        image = None
        if saved and model is self.model:
            try:
                canvas = getattr(self, 'active_canvas', None)
                if canvas is None or not canvas.isVisible():
                    canvas = self.canvas
                canvas.repaint()
                image = canvas.grabFramebuffer()
            except Exception as error:
                print(f"Project preview unavailable: {error}")
        try:
            self.recent_projects_manager.record_project(
                filepath, project_name=model.name, image=image, saved=saved
            )
            self._build_recent_projects_menu()
        except Exception as error:
            print(f"Recent projects unavailable: {error}")

    def _build_recent_projects_menu(self):
        """Build a bounded, scrollable panel in the existing File submenu."""
        self.recent_projects_menu.clear()
        manager = self.recent_projects_manager
        panel = RecentProjectsPanel(
            manager.get_recent_projects(), manager.max_projects,
            manager.LIMIT_OPTIONS, self.recent_projects_menu
        )
        panel.openRequested.connect(self._on_recent_project_clicked)
        panel.removeRequested.connect(self._remove_recent_project)
        panel.limitRequested.connect(self._set_recent_project_limit)
        panel.clearRequested.connect(self._clear_recent_projects)
        action = QWidgetAction(self.recent_projects_menu)
        action.setDefaultWidget(panel)
        self.recent_projects_menu.addAction(action)

    def _hide_recent_projects_menu(self):
        menu = self.recent_projects_menu
        while isinstance(menu, QMenu):
            menu.hide()
            menu = menu.parentWidget()

    def _set_recent_project_limit(self, limit):
        self._hide_recent_projects_menu()
        if self.recent_projects_manager.set_limit(limit):
            self.status.showMessage(f"Recent projects: keeping the latest {limit}.", 4000)
        else:
            self.status.showMessage("Could not save the recent project limit.", 4000)
        QTimer.singleShot(0, self._build_recent_projects_menu)

    def _remove_recent_project(self, filepath):
        self._hide_recent_projects_menu()
        if not self.recent_projects_manager.remove_project(filepath):
            self.status.showMessage("Could not remove the recent project entry.", 4000)
        QTimer.singleShot(0, self._build_recent_projects_menu)

    def _clear_recent_projects(self):
        self._hide_recent_projects_menu()
        if self.recent_projects_manager.clear_history():
            self.status.showMessage("Recent history cleared. Project files are kept.", 4000)
        else:
            self.status.showMessage("Could not clear recent history.", 4000)
        QTimer.singleShot(0, self._build_recent_projects_menu)

    def _on_recent_project_clicked(self, filepath):
        self._hide_recent_projects_menu()
        QTimer.singleShot(0, lambda: self._open_recent_project(filepath))

    def _open_recent_project(self, filepath):
        if not os.path.isfile(filepath):
            QMessageBox.warning(self, "File unavailable",
                                f"This project was moved or deleted:\n{filepath}\n\n"
                                "Right-click its recent entry to remove it.")
            return
        self.on_open_model(filepath=filepath)

    def _check_unsaved_changes(self):
        """
        Checks for unsaved changes and prompts the user. 
        Returns True if it is safe to proceed, False if the user canceled.
        """
        if self.model and not self.undo_stack.isClean():
            reply = QMessageBox.question(
                self, 
                "Unsaved Changes",
                "You have unsaved changes in your model.\nDo you want to save them before proceeding?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save
            )

            if reply == QMessageBox.StandardButton.Save:
                                                               
                return self.on_save_model()
                
            elif reply == QMessageBox.StandardButton.Cancel:
                                                            
                return False 

        return True

    def on_save_as_model(self):
        """Forces the save dialog by prompting for a new filename."""
        if not self.model:
            return False
            
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Model As", "",
            "Open//Structures Files (*.mf);;All Files (*)"
        )
        
        if not filename:
            return False
            
        if not filename.endswith(".mf"):
            filename += ".mf"
            
        previous_path = getattr(self.model, 'file_path', None)
        previous_active_path = getattr(self.model, 'active_model_path', None)
        self.model.file_path = filename
        if self.on_save_model():
            return True
        self.model.file_path = previous_path
        self.model.active_model_path = previous_active_path
        self.update_window_title()
        return False

    def on_close_project(self):
        """Closes the current project safely and returns to the welcome screen."""
        if not self.model:
            return
        if not self._check_unsaved_changes():
            return

        if getattr(self, 'canvas2_visible', False):
            self.btn_dual_view.setChecked(False)
            self._toggle_dual_view(False)

        if getattr(self, 'terminal_panel', None) and self.terminal_panel.isVisible():
            self._toggle_terminal()

        self.model = None
        self._history_controller.reset()
        self.model_tree.refresh()

        self._purge_results_and_visuals()
        self.undo_stack.clear()
        self.terminal_panel.set_model(None)

        self.selected_ids = []
        self.selected_node_ids = []
        self.selected_area_ids = []
        self.selected_link_ids = []
        self.selected_tendon_ids = []
        self.selected_cable_ids = []

        empty_model = StructuralModel("Empty")
        if hasattr(self.canvas, '_force_draw_model'):
            self.canvas._force_draw_model(empty_model)
        self.canvas.current_model = None
        self.canvas.update()

        if getattr(self, 'canvas2_visible', False):
            if hasattr(self.canvas2, '_force_draw_model'):
                self.canvas2._force_draw_model(empty_model)
            self.canvas2.current_model = None
            self.canvas2.update()

        self._nav_hint_armed = False                                           
        if hasattr(self, 'welcome_overlay'):
            self._welcome_opacity.setOpacity(0.0)
            self.welcome_overlay.hide()

        self.set_interface_state(False)

        QTimer.singleShot(0, self._show_welcome_overlay_animated)

        self.setWindowTitle("Open//Structures v0.8.10")
        self.status.showMessage("Project closed. Ready.")     

def main():
    if sys.platform == 'win32':
        myappid = 'metu.civil.OpenCivil.v03'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    prefs_path = os.path.join(os.path.expanduser("~"), ".OpenStructures_prefs.json")
    import json
    msaa_level = 1
    app_theme = "Light"
    try:
        if os.path.exists(prefs_path):
            with open(prefs_path, 'r') as f:
                prefs = json.load(f)
                msaa_level = int(prefs.get("msaa_level", 1))                                            
                app_theme = prefs.get("ui_theme", "Light")
    except:
        pass

    msaa_map = {0: 0, 1: 4, 2: 8, 3: 16, 4: 2, 5: 0}
    msaa_samples = msaa_map.get(msaa_level, 0)

    from PyQt6.QtGui import QSurfaceFormat
    fmt = QSurfaceFormat()
    fmt.setSamples(msaa_samples)
    fmt.setDepthBufferSize(24)                                           
    QSurfaceFormat.setDefaultFormat(fmt)

    if sys.platform == 'win32':
        _existing_platform = os.environ.get("QT_QPA_PLATFORM", "windows")
                                                                               
        if ":darkmode=" in _existing_platform:
            _existing_platform = _existing_platform.split(":darkmode=")[0]

        os.environ["QT_QPA_PLATFORM"] = f"{_existing_platform}:darkmode=0"

    app = QApplication(sys.argv)

    app.setProperty("os_ui_theme", app_theme)

    from app.ui.theme import set_global_theme
    set_global_theme(app)

    try:
        if app_theme == "Dark":
            app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        else:
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
                            app_msaa = window.graphics_settings.get("msaa_level", 1)
                            app_bg = window.graphics_settings.get("background_color")
                            app_edge = window.graphics_settings.get("edge_color")
                            app_theme = window.graphics_settings.get("ui_theme")
                            
                            window.graphics_settings.update(window.model.graphics_settings)
                            
                            window.graphics_settings["msaa_level"] = app_msaa
                            if app_bg: window.graphics_settings["background_color"] = app_bg
                            if app_edge: window.graphics_settings["edge_color"] = app_edge
                            if app_theme: window.graphics_settings["ui_theme"] = app_theme
                            
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
                        window._record_recent_project(file_path)
                        QTimer.singleShot(100, window.model_tree.refresh)                                               
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
                        app_msaa = window.graphics_settings.get("msaa_level", 1)
                        app_bg = window.graphics_settings.get("background_color")
                        app_edge = window.graphics_settings.get("edge_color")
                        app_theme = window.graphics_settings.get("ui_theme")
                        
                        window.graphics_settings.update(window.model.graphics_settings)
                        
                        window.graphics_settings["msaa_level"] = app_msaa
                        if app_bg: window.graphics_settings["background_color"] = app_bg
                        if app_edge: window.graphics_settings["edge_color"] = app_edge
                        if app_theme: window.graphics_settings["ui_theme"] = app_theme
                        
                        window._apply_canvas_view_settings(window.graphics_settings)
                        window.update_graphics_settings(window.graphics_settings)
                    
                    if hasattr(window.model, 'saved_unit_system'):
                        window.combo_units.blockSignals(True)
                        window.combo_units.setCurrentText(window.model.saved_unit_system)
                        window.combo_units.blockSignals(False)
                        window.on_units_changed(0)
                    
                    window.draw_both_canvases()
                    window.update_yield_lines()                                                        
                    window.status.showMessage(f"Loaded: {file_path}")
                    window.canvas.set_standard_view("3D")
                    window.set_interface_state(True)
                    window.update_window_title()
                    window._record_recent_project(file_path)
                    QTimer.singleShot(100, window.model_tree.refresh)                                               
                except Exception as e:
                    QMessageBox.critical(window, "Load Error", f"Failed to open file.\n{e}")
    
    splash.finished.connect(on_splash_finished) 
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
