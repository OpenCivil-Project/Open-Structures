"""
section_designer_dialog.py
--------------------------
Section Designer — redesigned UI (SAP2000-inspired).

Layout
------
┌──────────────────────────────────────────────────────────────┐
│  Name: [______]   Material: [_____▾] [+]   Color: [■]        │  header
├──────┬───────────────────────────────────┬───────────────────┤
│  ↖   │                                   │ [Data] [Props]    │
│  ✏   │                                   │                   │
│  ✋   │            CANVAS                 │   right panel     │
│  ─── │                                   │   (tabbed 220px)  │
│  ▭   │                                   │                   │
│  ◯   │                                   │                   │
│  I   │                                   │                   │
│  T   │                                   │                   │
│  C   │                                   │                   │
│  ─── │                                   │                   │
│  ⊡   │                                   │                   │
│  ✕   │                                   │                   │
├──────┴───────────────────────────────────┴───────────────────┤
│  X = … m   Y = … m   [⊞ Snap]  [Grid: 50mm ▾]  [Accept][✕] │  status bar
└──────────────────────────────────────────────────────────────┘

No changes to: drawing_canvas.py, section_analyzer.py,
               section_designer_commands.py, snap_grid.py
"""

import math

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QToolButton, QButtonGroup, QFrame, QTabWidget,
    QFormLayout, QRadioButton, QGroupBox,
    QDoubleSpinBox, QDialogButtonBox, QMessageBox,
    QColorDialog, QSizePolicy, QGridLayout,
)
from PyQt6.QtWidgets import QMenuBar, QMenu
from PyQt6.QtCore import Qt, pyqtSlot, QThreadPool
from PyQt6.QtGui  import QFont, QColor, QKeySequence, QShortcut, QAction
import qtawesome as qta

from core.units      import unit_registry
from core.properties import ArbitrarySection

from app.section_designer.drawing_canvas   import DrawingCanvas, DrawMode
from app.section_designer.section_analyzer import SectionAnalyzer
from app.section_designer.section_worker import SectionWorker
from app.section_designer.section_viewer_dialogs import (
    SectionPropertiesDialog, GeneratedFibersDialog, ElasticStressDialog,
)
from app.ui.theme import apply_dialog_style

def _rect_verts(b: float, h: float) -> list:
    hb, hh = b / 2, h / 2
    return [(-hb, -hh), (hb, -hh), (hb, hh), (-hb, hh)]

def _circle_verts(r: float, n: int = 32) -> list:
    return [
        (r * math.cos(2 * math.pi * i / n),
         r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]

def _isection_verts(bf: float, d: float, tf: float, tw: float) -> list:
    hbf, hd, htw = bf / 2, d / 2, tw / 2
    return [
        (-hbf, -hd), ( hbf, -hd), ( hbf, -hd + tf),
        ( htw, -hd + tf), ( htw,  hd - tf), ( hbf,  hd - tf),
        ( hbf,  hd), (-hbf,  hd), (-hbf,  hd - tf),
        (-htw,  hd - tf), (-htw, -hd + tf), (-hbf, -hd + tf),
    ]

def _tsection_verts(bf: float, d: float, tf: float, tw: float) -> list:
    hbf, hd, htw = bf / 2, d / 2, tw / 2
    return [
        (-htw, -hd), ( htw, -hd), ( htw,  hd - tf),
        ( hbf,  hd - tf), ( hbf,  hd), (-hbf,  hd),
        (-hbf,  hd - tf), (-htw,  hd - tf),
    ]

def _channel_verts(bf: float, d: float, tf: float, tw: float) -> list:
    hd = d / 2
    return [
        (0,  -hd), (bf, -hd), (bf, -hd + tf),
        (tw, -hd + tf), (tw,  hd - tf),
        (bf,  hd - tf), (bf,  hd), (0,   hd),
    ]

def _precast_i_verts(B1: float, B2: float, B3: float, B4: float, 
                     D1: float, D2: float, D3: float, D4: float, 
                     D5: float, D6: float, D7: float, 
                     T1: float, T2: float, C1: float) -> list:
    z_top = D1 / 2.0
    z_bot = -D1 / 2.0

    pts = [
        (0.0, z_top),
        (B1 / 2.0, z_top),
        (B1 / 2.0, z_top - D2),
        (B1 / 2.0 - B3, z_top - D2),
        (T1 / 2.0, z_top - D2 - D3),
        (T1 / 2.0, z_top - D2 - D3 - D4),
        (T2 / 2.0, z_bot + D5 + D6 + D7),
        (T2 / 2.0, z_bot + D5 + D6),
        (B2 / 2.0 - B4, z_bot + D5),
        (B2 / 2.0, z_bot + D5),
        (B2 / 2.0, z_bot + C1),
        (B2 / 2.0 - C1, z_bot),
        (0.0, z_bot)
    ]
    
    right_half = []
    for pt in pts:
        if not right_half or (abs(pt[0] - right_half[-1][0]) > 1e-6 or abs(pt[1] - right_half[-1][1]) > 1e-6):
            right_half.append(pt)
            
    left_half = [(-x, y) for (x, y) in reversed(right_half)]
    
    return right_half + left_half[1:-1]

def _precast_u_verts(B1: float, B2: float, B3: float, B4: float, B5: float, B6: float,
                     D1: float, D2: float, D3: float, D4: float, D5: float, D6: float, D7: float) -> list:
    z_top = D1 / 2.0
    z_bot = -D1 / 2.0

    Z_top_web = z_top - D7
    Z_bot_web = z_bot + D2
    X_top_web = B1 / 2.0
    X_bot_web = B2 / 2.0

    def X_out(z):
        if abs(Z_top_web - Z_bot_web) < 1e-6:
            return X_top_web
        return X_bot_web + (X_top_web - X_bot_web) * (z - Z_bot_web) / (Z_top_web - Z_bot_web)

    Z_in_top_web = z_top - D6 - D5 - D4
    X_in_top_web = X_out(Z_in_top_web) - B5

    Z_in_bot_web = z_bot + B3 + D3
    X_in_bot_web = X_out(Z_in_bot_web) - B4

    X_inner_top = X_in_top_web - B6

    pts = [
        (B1 / 2.0, z_top),
        (B1 / 2.0, z_top - D7),
        (B2 / 2.0, z_bot + D2),
        (B2 / 2.0 - D2, z_bot),
        (0.0, z_bot),
        (0.0, z_bot + B3),
        (X_in_bot_web - D3, z_bot + B3),
        (X_in_bot_web, z_bot + B3 + D3),
        (X_in_top_web, z_top - D6 - D5 - D4),
        (X_in_top_web, z_top - D6 - D5),
        (X_inner_top, z_top - D6),
        (X_inner_top, z_top)
    ]

    right_pts = []
    for pt in pts:
        if not right_pts or (abs(pt[0] - right_pts[-1][0]) > 1e-6 or abs(pt[1] - right_pts[-1][1]) > 1e-6):
            right_pts.append(pt)

    bot_out_idx = next(i for i, p in enumerate(right_pts) if abs(p[0]) < 1e-6 and abs(p[1] - z_bot) < 1e-6)
    bot_in_idx = next(i for i, p in enumerate(right_pts) if abs(p[0]) < 1e-6 and abs(p[1] - (z_bot + B3)) < 1e-6)

    outer_right = right_pts[:bot_out_idx + 1]
    outer_left = [(-x, y) for (x, y) in reversed(right_pts[:bot_out_idx])]
    inner_left = [(-x, y) for (x, y) in reversed(right_pts[bot_in_idx + 1:])]
    inner_right = right_pts[bot_in_idx:]

    full_pts = outer_right + outer_left + inner_left + inner_right

    clean_pts = []
    for pt in full_pts:
        if not clean_pts or (abs(pt[0] - clean_pts[-1][0]) > 1e-6 or abs(pt[1] - clean_pts[-1][1]) > 1e-6):
            clean_pts.append(pt)
    
    if clean_pts and (abs(clean_pts[0][0] - clean_pts[-1][0]) < 1e-6 and abs(clean_pts[0][1] - clean_pts[-1][1]) < 1e-6):
        clean_pts.pop()

    return clean_pts

class _CoordInputDialog(QDialog):
    def __init__(self, y_init: float, z_init: float, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Enter coordinates")
        self.setFixedSize(260, 130)
        scale = unit_registry.length_scale
        unit  = unit_registry.length_unit_name
        layout = QVBoxLayout(self)
        form   = QFormLayout()
        self._sb_y = QDoubleSpinBox()
        self._sb_y.setRange(-1e6, 1e6); self._sb_y.setDecimals(4)
        self._sb_y.setSuffix(f"  {unit}"); self._sb_y.setValue(y_init * scale)
        self._sb_z = QDoubleSpinBox()
        self._sb_z.setRange(-1e6, 1e6); self._sb_z.setDecimals(4)
        self._sb_z.setSuffix(f"  {unit}"); self._sb_z.setValue(z_init * scale)
        form.addRow("Y (horizontal):", self._sb_y)
        form.addRow("Z (vertical):",   self._sb_z)
        layout.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    @property
    def y_world(self) -> float: return self._sb_y.value() / unit_registry.length_scale
    @property
    def z_world(self) -> float: return self._sb_z.value() / unit_registry.length_scale

class _DimDialog(QDialog):
    def __init__(self, title: str, fields: list, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle(title)
        self.setFixedWidth(300)
        unit  = unit_registry.length_unit_name
        scale = unit_registry.length_scale
        layout = QVBoxLayout(self)
        form   = QFormLayout()
        self._inputs: dict[str, QDoubleSpinBox] = {}
        for key, label, default_m in fields:
            sb = QDoubleSpinBox()
            sb.setRange(1e-6, 1e4); sb.setDecimals(4)
            sb.setSuffix(f"  {unit}"); sb.setValue(default_m * scale)
            form.addRow(label, sb)
            self._inputs[key] = sb
        layout.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def values_m(self) -> dict:
        scale = unit_registry.length_scale
        return {k: sb.value() / scale for k, sb in self._inputs.items()}

class _ModifiersDialog(QDialog):
    def __init__(self, current: dict, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Property / Stiffness Modifiers")
        self.resize(320, 300)
        self.modifiers = current.copy()
        layout = QVBoxLayout(self)
        grp    = QGroupBox("Analysis Factors (Multipliers)")
        form   = QFormLayout(grp)
        labels = {
            "A": "Cross-section Area", "As2": "Shear Area (Local 2)",
            "As3": "Shear Area (Local 3)", "J": "Torsional Constant",
            "I2": "Moment of Inertia (Local 2)", "I3": "Moment of Inertia (Local 3)",
            "Mass": "Mass", "Weight": "Weight",
        }
        self._inputs = {}
        for key, text in labels.items():
            sb = QDoubleSpinBox()
            sb.setRange(0.0001, 1000.0); sb.setSingleStep(0.1)
            sb.setDecimals(4); sb.setValue(self.modifiers.get(key, 1.0))
            form.addRow(text, sb)
            self._inputs[key] = sb
        layout.addWidget(grp)
        btns = QHBoxLayout()
        btn_ok = QPushButton("OK"); btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self._save); btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok); btns.addWidget(btn_cancel)
        layout.addLayout(btns)

    def _save(self):
        for key, sb in self._inputs.items():
            self.modifiers[key] = sb.value()
        self.accept()

_SIDEBAR_CSS = """
QToolButton {
    border: none;
    border-radius: 4px;
    padding: 3px;
    background: transparent;
}
QToolButton:checked {
    background: #d0e4f7;
}
QToolButton:hover:!checked {
    background: #e8f0fb;
}
"""

class _LeftSidebar(QWidget):
    """
    Vertical icon toolbar — draw tools on top, shape generators below.
    Fit and Clear are in the icon toolbar so not duplicated here.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(38)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(_SIDEBAR_CSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 6, 2, 6)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        _C = "#495057"

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)

        self.btn_select = self._tool(qta.icon("fa5s.mouse-pointer", color=_C),
                                     "Select  (Q)", checkable=True)
        self.btn_draw   = self._tool(qta.icon("fa5s.pencil-alt",    color=_C),
                                     "Draw polygon  (D)", checkable=True, checked=True)
        self.btn_pan    = self._tool(qta.icon("fa5s.hand-paper",    color=_C),
                                     "Pan  (P)", checkable=True)
        for btn in (self.btn_select, self.btn_draw, self.btn_pan):
            self._tool_group.addButton(btn)
            layout.addWidget(btn)

        layout.addWidget(self._sep())

        self.btn_rect    = self._tool(qta.icon("fa5s.vector-square",      color=_C), "Rectangle")
        self.btn_circle  = self._tool(qta.icon("fa5s.circle",             color=_C), "Circle")
        self.btn_isec    = self._tool(qta.icon("fa5s.grip-lines",         color=_C), "I-Section")
        self.btn_tsec    = self._tool(qta.icon("fa5s.grip-lines-vertical", color=_C), "T-Section")
        self.btn_channel = self._tool(qta.icon("fa5s.columns",            color=_C), "C-Channel")
        self.btn_precast_i = self._tool(qta.icon("fa5s.shapes",           color=_C), "Precast I")
        self.btn_precast_u = self._tool(qta.icon("fa5s.magnet",           color=_C), "Precast U")

        for btn in (self.btn_rect, self.btn_circle,
                    self.btn_isec, self.btn_tsec, self.btn_channel,
                    self.btn_precast_i, self.btn_precast_u):
            layout.addWidget(btn)

        layout.addStretch()

    @staticmethod
    def _tool(icon, tip: str,
              checkable: bool = False, checked: bool = False) -> QToolButton:
        btn = QToolButton()
        btn.setIcon(icon)
        btn.setToolTip(tip)
        btn.setCheckable(checkable)
        btn.setChecked(checked)
        btn.setFixedSize(34, 30)
        return btn

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setFrameShadow(QFrame.Shadow.Sunken)
        f.setFixedHeight(1)
        f.setStyleSheet("margin: 3px 4px;")
        return f

class _RightPanel(QWidget):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.addTab(self._build_data_tab(model), "Data")
        self.tabs.addTab(self._build_props_tab(),      "Properties")
        layout.addWidget(self.tabs)

    def _build_data_tab(self, model) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        grp = QGroupBox("Design Type")
        grp_layout = QVBoxLayout(grp)
        grp_layout.setSpacing(6)

        self.radio_none     = QRadioButton("No Check / No Design")
        self.radio_steel    = QRadioButton("Steel Frame Design")
        self.radio_conc_chk = QRadioButton("Concrete Column — Check")
        self.radio_conc_des = QRadioButton("Concrete Column — Design")
        self.radio_none.setChecked(True)

        for r in (self.radio_none, self.radio_steel,
                  self.radio_conc_chk, self.radio_conc_des):
            r.setStyleSheet("font-size: 11px;")
            grp_layout.addWidget(r)

        layout.addWidget(grp)

        self.btn_mods = QPushButton("Property Modifiers…")
        self.btn_mods.setFixedHeight(26)
        layout.addWidget(self.btn_mods)

        layout.addStretch()

        self.vertex_lbl = QLabel("Vertices: 0")
        self.vertex_lbl.setStyleSheet("color: #777; font-size: 10px;")
        layout.addWidget(self.vertex_lbl)

        hints_grp = QGroupBox("Keyboard shortcuts")
        hints_layout = QVBoxLayout(hints_grp)
        hints_layout.setSpacing(1)
        hints_layout.setContentsMargins(6, 4, 6, 4)
        for txt in [
            "Click       — place vertex",
            "Right-click — close",
            "Dbl-click   — close",
            "Tab         — exact coords",
            "Esc / ⌫    — undo vertex",
            "Ctrl+Z / Y  — undo / redo",
            "Wheel       — zoom",
            "Mid drag    — pan",
        ]:
            lbl = QLabel(txt)
            lbl.setStyleSheet("color: #888; font-size: 9px; font-family: monospace;")
            hints_layout.addWidget(lbl)
        layout.addWidget(hints_grp)

        return w

    def _build_props_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        u = unit_registry.length_unit_name
        self._prop_fields: dict[str, QLineEdit] = {}

        fields = [
            ("A",       f"A  ({u}²)",    "Area"),
            
            ("I33",     f"I₂₂  ({u}⁴)", "Weak axis MOI"),
            ("I22",     f"I₃₃  ({u}⁴)", "Strong axis MOI"),
            
            ("J",       f"J  ({u}⁴)",   "Torsion constant"),
            
            ("Asy",     f"AS3 ({u}²)",  "Shear area (local 3)"),
            ("Asz",     f"AS2 ({u}²)",  "Shear area (local 2)"),
            
            ("S33",     f"S₂₂  ({u}³)", "Elastic modulus (weak)"),
            ("S22",     f"S₃₃  ({u}³)", "Elastic modulus (strong)"),
            ("r33",     f"r₂₂  ({u})",  "Radius of gyration (weak)"),
            ("r22",     f"r₃₃  ({u})",  "Radius of gyration (strong)"),
            
            ("y_c",     f"ȳ  ({u})",    "Centroid Y"),
            ("z_c",     f"z̄  ({u})",    "Centroid Z"),
        ]

        form = QFormLayout()
        form.setSpacing(5)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        for key, label, tip in fields:
            lbl = QLabel(label)
                                                         
            lbl.setStyleSheet("font-size: 12px; color: #000000;")
            lbl.setToolTip(tip)
            
            le = QLineEdit("—")
            le.setReadOnly(True)
            le.setFixedHeight(24)
            le.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            le.setStyleSheet(
                "background: #ffffff; color: #000000; font-size: 12px; "
                "font-family: monospace; border: 1px solid #aaa; border-radius: 2px;"
            )
            form.addRow(lbl, le)
            self._prop_fields[key] = le

        layout.addLayout(form)
        layout.addStretch()

        note = QLabel("Updates live as you draw.")
        note.setStyleSheet("color: #aaa; font-size: 9px; font-style: italic;")
        layout.addWidget(note)

        return w

    def update_props(self, props: dict):
        scale      = unit_registry.length_scale
        s2, s3, s4 = scale**2, scale**3, scale**4
        conv = {
            'A': s2, 'I33': s4, 'I22': s4, 'J': s4,
            'Asy': s2, 'Asz': s2,
            'S33': s3, 'S22': s3,
            'r33': scale, 'r22': scale,
            'y_c': scale, 'z_c': scale,
        }
        for key, le in self._prop_fields.items():
            raw = props.get(key, 0.0)
            val = raw * conv.get(key, 1.0)
            le.setText(f"{val:.4e}" if (abs(val) < 1e-3 and val != 0.0) else f"{val:.5g}")
                                           
        self.tabs.setCurrentIndex(1)

    def clear_props(self):
        for le in self._prop_fields.values():
            le.setText("—")

    def set_vertex_count(self, n: int):
        self.vertex_lbl.setText(f"Vertices: {n}")

    @property
    def design_type(self) -> str:
        if self.radio_steel.isChecked():    return "Steel"
        if self.radio_conc_chk.isChecked(): return "ConcreteCheck"
        if self.radio_conc_des.isChecked(): return "ConcreteDesign"
        return "None"

class SectionDesignerDialog(QDialog):
    """
    Parameters
    ----------
    model        : StructuralModel
    section_data : ArbitrarySection | None  — pass to re-open for editing
    parent       : QWidget | None
    """

    def __init__(self, model, section_data=None, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Section Designer")
        self.resize(1080, 700)
        self.setMinimumSize(860, 560)

        self.thread_pool = QThreadPool.globalInstance()
        self._current_worker_id = 0

        self.model        = model
        self.section_data = section_data
        self._computed_props: dict | None = None
        self._color = (0.259, 0.110, 0.749, 1.0)
        self._modifiers = {
            "A": 1.0, "As2": 1.0, "As3": 1.0, "J": 1.0,
            "I2": 1.0, "I3": 1.0, "Mass": 1.0, "Weight": 1.0,
        }
                                                                       
        self._mesh_settings = {"mesh_abs": 0.0, "mesh_rel": 0.05}

        self._build_ui()
        self._connect_signals()
        self._update_color_swatch()

        if section_data is not None:
            self._load_existing(section_data)
        else:
            self._set_default_name()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_menubar())
        root.addWidget(self._build_icon_toolbar())
        root.addWidget(self._h_line())
        root.addWidget(self._build_header())
        root.addWidget(self._h_line())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = _LeftSidebar(self)
        body.addWidget(self.sidebar)
        body.addWidget(self._v_line())

        self.canvas = DrawingCanvas(self)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.canvas, stretch=1)

        body.addWidget(self._v_line())
        self.right = _RightPanel(self.model, self)
        body.addWidget(self.right)

        body_widget = QWidget()
        body_widget.setLayout(body)
        root.addWidget(body_widget, stretch=1)

        root.addWidget(self._h_line())
        root.addWidget(self._build_status_bar())

    def _build_menubar(self) -> QMenuBar:
        mb = QMenuBar(self)

        m_file = mb.addMenu("&File")
        m_file.addAction(self._placeholder_action("fa5s.file",      "New Section"))
        m_file.addAction(self._placeholder_action("fa5s.folder-open","Open..."))
        m_file.addSeparator()
        m_file.addAction(self._placeholder_action("fa5s.save",       "Save"))
        m_file.addAction(self._placeholder_action("fa5s.file-export","Save As..."))
        m_file.addSeparator()
        m_file.addAction(self._placeholder_action("fa5s.print",      "Print..."))
        m_file.addSeparator()
        act_exit = m_file.addAction(
            qta.icon("fa5s.times", color="#6c757d"), "Exit")
        act_exit.triggered.connect(self.reject)

        m_edit = mb.addMenu("&Edit")
        act_undo = m_edit.addAction(
            qta.icon("fa5s.undo", color="#6c757d"), "Undo\tCtrl+Z")
        act_undo.triggered.connect(lambda: self.canvas.undo())
        act_redo = m_edit.addAction(
            qta.icon("fa5s.redo", color="#6c757d"), "Redo\tCtrl+Y")
        act_redo.triggered.connect(lambda: self.canvas.redo())
        m_edit.addSeparator()
        act_clear = m_edit.addAction(
            qta.icon("fa5s.trash-alt", color="#6c757d"), "Clear Canvas")
        act_clear.triggered.connect(lambda: self._on_reset())

        m_view = mb.addMenu("&View")
        m_view.addAction(self._placeholder_action("fa5s.search-plus",  "Zoom In"))
        m_view.addAction(self._placeholder_action("fa5s.search-minus", "Zoom Out"))
        m_view.addAction(self._placeholder_action("fa5s.search",       "Zoom Previous"))
        act_fit = m_view.addAction(
            qta.icon("fa5s.expand-arrows-alt", color="#6c757d"), "Zoom to Fit\tF")
        act_fit.triggered.connect(lambda: self.canvas.zoom_to_fit())
        m_view.addSeparator()
        m_view.addAction(self._placeholder_action("fa5s.th",            "Show Grid"))
        m_view.addAction(self._placeholder_action("fa5s.crosshairs",    "Show Centroid"))
        m_view.addAction(self._placeholder_action("fa5s.ruler-combined","Show Principal Axes"))

        m_define = mb.addMenu("&Define")
        m_define.addAction(self._placeholder_action("fa5s.cube",        "Materials..."))
        m_define.addAction(self._placeholder_action("fa5s.sliders-h",   "Section Properties..."))

        m_draw = mb.addMenu("&Draw")
        act_draw_poly = m_draw.addAction(
            qta.icon("fa5s.pencil-alt", color="#6c757d"), "Draw Polygon\tD")
        act_draw_poly.triggered.connect(lambda: self._set_tool(DrawMode.DRAW))
        m_draw.addSeparator()
        act_rect = m_draw.addAction(
            qta.icon("fa5s.square", color="#6c757d"), "Rectangle...")
        act_rect.triggered.connect(self._from_rectangle)
        act_circ = m_draw.addAction(
            qta.icon("fa5s.circle", color="#6c757d"), "Circle...")
        act_circ.triggered.connect(self._from_circle)
        act_isec = m_draw.addAction(
            qta.icon("fa5s.grip-lines", color="#6c757d"), "I-Section...")
        act_isec.triggered.connect(self._from_isection)
        act_tsec = m_draw.addAction(
            qta.icon("fa5s.grip-lines", color="#6c757d"), "T-Section...")
        act_tsec.triggered.connect(self._from_tsection)
        act_chan = m_draw.addAction(
            qta.icon("fa5s.grip-lines-vertical", color="#6c757d"), "C-Channel...")
        act_chan.triggered.connect(self._from_channel)

        act_precast_i = m_draw.addAction(
            qta.icon("fa5s.shapes", color="#6c757d"), "Precast I...")
        act_precast_i.triggered.connect(self._from_precast_i)
        
        act_precast_u = m_draw.addAction(
            qta.icon("fa5s.magnet", color="#6c757d"), "Precast U...")
        act_precast_u.triggered.connect(self._from_precast_u)

        m_select = mb.addMenu("&Select")
        act_sel = m_select.addAction(
            qta.icon("fa5s.mouse-pointer", color="#6c757d"), "Select Mode\tQ")
        act_sel.triggered.connect(lambda: self._set_tool(DrawMode.SELECT))
        m_select.addSeparator()
        m_select.addAction(self._placeholder_action("fa5s.object-group", "Select All"))
        m_select.addAction(self._placeholder_action("fa5s.trash-alt",    "Delete Selected"))

        m_display = mb.addMenu("D&isplay")
        m_display.addAction(self._placeholder_action("fa5s.palette",    "Section Color..."))
        m_display.addSeparator()
        act_props = m_display.addAction(
            qta.icon("fa5s.list-alt", color="#6c757d"), "Section Properties...")
        act_props.triggered.connect(self._open_section_properties)
        act_fibers = m_display.addAction(
            qta.icon("fa5s.braille", color="#6c757d"), "Generated Fibers...")
        act_fibers.triggered.connect(self._open_generated_fibers)
        act_stress = m_display.addAction(
            qta.icon("fa5s.fire", color="#6c757d"), "Show Stresses (S11)...")
        act_stress.triggered.connect(self._open_elastic_stress)

        m_opts = mb.addMenu("&Options")
        act_mods = m_opts.addAction(
            qta.icon("fa5s.sliders-h", color="#6c757d"), "Property Modifiers...")
        act_mods.triggered.connect(self._open_modifiers)
        m_opts.addSeparator()
        m_opts.addAction(self._placeholder_action("fa5s.cog", "Preferences..."))

        m_help = mb.addMenu("&Help")
        m_help.addAction(self._placeholder_action("fa5s.question-circle", "Help Topics"))
        m_help.addSeparator()
        m_help.addAction(self._placeholder_action("fa5s.info-circle",     "About Section Designer"))

        return mb

    def _build_icon_toolbar(self) -> QWidget:
        """SAP2000-style icon strip below the menu bar."""
        bar = QWidget()
        bar.setFixedHeight(34)
        bar.setStyleSheet("background: #f5f5f5;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(1)

        _C = "#6c757d"                                      

        def _btn(icon_name: str, tip: str,
                 checkable: bool = False, checked: bool = False) -> QToolButton:
            b = QToolButton()
            b.setIcon(qta.icon(icon_name, color=_C))
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setChecked(checked)
            b.setFixedSize(26, 26)
            b.setStyleSheet(
                "QToolButton { border:none; border-radius:3px; background:transparent; }"
                "QToolButton:hover { background:#e0e0e0; }"
                "QToolButton:checked { background:#d0e4f7; }"
                "QToolButton:pressed { background:#c0d4e7; }"
            )
            return b

        def _sep():
            f = QFrame()
            f.setFrameShape(QFrame.Shape.VLine)
            f.setFrameShadow(QFrame.Shadow.Sunken)
            f.setFixedSize(2, 22)
            f.setStyleSheet("margin: 0 3px;")
            return f

        btn_new  = _btn("fa5s.file",        "New section")
        btn_undo = _btn("fa5s.undo",        "Undo  Ctrl+Z")
        btn_redo = _btn("fa5s.redo",        "Redo  Ctrl+Y")
        btn_undo.clicked.connect(lambda: self.canvas.undo())
        btn_redo.clicked.connect(lambda: self.canvas.redo())
        for b in (btn_new, btn_undo, btn_redo):
            layout.addWidget(b)

        layout.addWidget(_sep())

        self._tb_select = _btn("fa5s.mouse-pointer", "Select  (Q)",
                               checkable=True)
        self._tb_draw   = _btn("fa5s.pencil-alt",    "Draw polygon  (D)",
                               checkable=True, checked=True)
        self._tb_pan    = _btn("fa5s.hand-paper",    "Pan  (P)",
                               checkable=True)

        self._tb_tool_group = QButtonGroup(self)
        self._tb_tool_group.setExclusive(True)
        for b in (self._tb_select, self._tb_draw, self._tb_pan):
            self._tb_tool_group.addButton(b)
            layout.addWidget(b)

        layout.addWidget(_sep())

        btn_zin   = _btn("fa5s.search-plus",         "Zoom in")
        btn_zout  = _btn("fa5s.search-minus",        "Zoom out")
        btn_zprev = _btn("fa5s.search",              "Zoom previous  (placeholder)")
        btn_zfit  = _btn("fa5s.expand-arrows-alt",   "Zoom to fit  (F)")
        btn_zbox  = _btn("fa5s.vector-square",       "Zoom window  (placeholder)")
        btn_zfit.clicked.connect(lambda: self.canvas.zoom_to_fit())
        for b in (btn_zin, btn_zout, btn_zprev, btn_zfit, btn_zbox):
            layout.addWidget(b)

        layout.addWidget(_sep())

        self._tb_snap = _btn("fa5s.th", "Toggle snap  (S)", checkable=True, checked=True)
        self._tb_snap.toggled.connect(self._on_snap_toggled)
        layout.addWidget(self._tb_snap)

        layout.addWidget(_sep())

        btn_axes     = _btn("fa5s.crosshairs",     "Show/hide axes  (placeholder)")
        btn_centroid = _btn("fa5s.dot-circle",     "Show/hide centroid  (placeholder)")
        btn_props    = _btn("fa5s.list-alt",       "Section properties")
        btn_fibers   = _btn("fa5s.braille",        "Generated fibers")
        btn_stress   = _btn("fa5s.fire",           "Elastic stress (S11)")
        btn_rebar    = _btn("fa5s.circle",         "Reinforcement  (placeholder)")
        btn_props.clicked.connect(self._open_section_properties)
        btn_fibers.clicked.connect(self._open_generated_fibers)
        btn_stress.clicked.connect(self._open_elastic_stress)
        for b in (btn_axes, btn_centroid, btn_props, btn_fibers, btn_stress, btn_rebar):
            layout.addWidget(b)

        layout.addStretch()
        return bar

    def _from_precast_i(self):
        dlg = _DimDialog("Precast Concrete I / Bulb Tee", [
            ("B1", "Top Flange Width (B1)", 0.3048),
            ("B2", "Bottom Flange Width (B2)", 0.4064),
            ("B3", "Top Flange Taper Offset (B3)", 0.0),
            ("B4", "Bot Flange Taper Offset (B4)", 0.0),
            ("D1", "Total Depth (D1)", 0.7112),
            ("D2", "Top Flange Edge Thick (D2)", 0.1016),
            ("D3", "Top Flange Taper (D3)", 0.0762),
            ("D4", "Top Web Root (D4)", 0.0),
            ("D5", "Bot Flange Edge Thick (D5)", 0.1270),
            ("D6", "Bot Flange Taper (D6)", 0.1270),
            ("D7", "Bot Web Root (D7)", 0.0),
            ("T1", "Top Web Thickness (T1)", 0.1524),
            ("T2", "Bot Web Thickness (T2)", 0.1524),
            ("C1", "Bottom Chamfer (C1)", 0.0)
        ], self)
        
        if dlg.exec():
            v = dlg.values_m()
            self.canvas.push_shape(
                _precast_i_verts(
                    v['B1'], v['B2'], v['B3'], v['B4'], 
                    v['D1'], v['D2'], v['D3'], v['D4'], 
                    v['D5'], v['D6'], v['D7'], 
                    v['T1'], v['T2'], v['C1']
                ), "Precast I"
            )
            self.canvas.zoom_to_fit()

    def _from_precast_u(self):
        dlg = _DimDialog("Precast Concrete U Girder", [
            ("B1", "Top Width (B1)", 2.1987),
            ("B2", "Bottom Width (B2)", 1.4986),
            ("B3", "Bottom Slab Thick (B3)", 0.2000),
            ("B4", "Bot Web Thick (B4)", 0.0953),
            ("B5", "Top Web Thick (B5)", 0.1447),
            ("B6", "Top Flange Taper Width (B6)", 0.0),
            ("D1", "Total Depth (D1)", 1.4002),
            ("D2", "Bot Outer Chamfer (D2)", 0.1746),
            ("D3", "Bot Inner Fillet (D3)", 0.0762),
            ("D4", "Top Web Root (D4)", 0.0),
            ("D5", "Top Flange Taper (D5)", 0.0),
            ("D6", "Top Flange Inner Drop (D6)", 0.1238),
            ("D7", "Top Flange Outer Drop (D7)", 0.1746)
        ], self)
        
        if dlg.exec():
            v = dlg.values_m()
            self.canvas.push_shape(
                _precast_u_verts(
                    v['B1'], v['B2'], v['B3'], v['B4'], v['B5'], v['B6'],
                    v['D1'], v['D2'], v['D3'], v['D4'], v['D5'], v['D6'], v['D7']
                ), "Precast U"
            )
            self.canvas.zoom_to_fit()

    @staticmethod
    def _placeholder_action(icon_name: str, label: str) -> QAction:
        """Menu action that does nothing yet — clearly marked in tooltip."""
        act = QAction(qta.icon(icon_name, color="#6c757d"), label)
        act.setToolTip(f"{label}  [placeholder — not yet implemented]")
        act.setEnabled(True)                                          
        return act

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(42)
        bar.setStyleSheet("background: #f9f9f9; border-bottom: 1px solid #ddd;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. FSEC1")
        self.name_edit.setFixedWidth(110)
        self.name_edit.setFixedHeight(26)
        layout.addWidget(self.name_edit)

        layout.addWidget(self._v_sep())

        layout.addWidget(QLabel("Material:"))
        self.mat_combo = QComboBox()
        self.mat_combo.setFixedHeight(26)
        self.mat_combo.setMinimumWidth(120)
        for m in self.model.materials:
            self.mat_combo.addItem(m)
        layout.addWidget(self.mat_combo)

        layout.addWidget(self._v_sep())

        layout.addWidget(QLabel("Color:"))
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(32, 22)
        self.btn_color.setToolTip("Pick display color")
        self.btn_color.clicked.connect(self._pick_color)
        layout.addWidget(self.btn_color)

        layout.addStretch()
        return bar

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet("background: #f0f0f0;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(6)

        self.coord_lbl = QLabel("X =      —        Y =      —")
        self.coord_lbl.setStyleSheet(
            "font-family: monospace; font-size: 11px; color: #333;")
        self.coord_lbl.setFixedWidth(270)
        layout.addWidget(self.coord_lbl)

        layout.addWidget(self._v_sep())

        self.btn_snap = QToolButton()
        self.btn_snap.setText("⊞  Snap")
        self.btn_snap.setCheckable(True)
        self.btn_snap.setChecked(True)
        self.btn_snap.setToolTip("Toggle snap to grid  (S)")
        self.btn_snap.setFixedHeight(26)
        self.btn_snap.setStyleSheet(
            "QToolButton { border:1px solid #ccc; border-radius:3px; "
            "padding:0 8px; font-size:11px; background:#fff; }"
            "QToolButton:checked { background:#d0e4f7; border-color:#3a7fc1; color:#1a4a80; }"
            "QToolButton:hover { background:#e8f0fb; }"
        )
        self.btn_snap.toggled.connect(self._on_snap_toggled)
        layout.addWidget(self.btn_snap)

        layout.addWidget(QLabel("Grid:"))
        self.grid_combo = QComboBox()
        self.grid_combo.setFixedWidth(88)
        self.grid_combo.setFixedHeight(26)
        self._populate_grid_steps()
        self.grid_combo.currentIndexChanged.connect(self._on_grid_step_changed)
        layout.addWidget(self.grid_combo)

        layout.addWidget(self._v_sep())
        
        self.unit_combo = QComboBox()
        self.unit_combo.addItems([
            "kN, m, C", "N, m, C", "N, mm, C", "kN, mm, C",
            "Tonf, m, C", "kgf, m, C", "kip, ft, F"
        ])
        self.unit_combo.setCurrentText(unit_registry.current_unit_label)
        self.unit_combo.setFixedHeight(26)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        layout.addWidget(self.unit_combo)

        layout.addStretch()

        self.btn_accept = QPushButton("Accept")
        self.btn_accept.setEnabled(False)
        self.btn_accept.setDefault(True)
        self.btn_accept.setFixedHeight(28)
        self.btn_accept.setStyleSheet(
            "QPushButton { background:#3a7fc1; color:white; border-radius:4px; "
            "padding:0 16px; font-weight:bold; }"
            "QPushButton:disabled { background:#aaa; }"
            "QPushButton:hover:!disabled { background:#2a6aaa; }"
        )
        self.btn_accept.clicked.connect(self._on_accept)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(28)
        btn_cancel.setStyleSheet(
            "QPushButton { border:1px solid #ccc; border-radius:4px; "
            "padding:0 12px; background:#fff; }"
            "QPushButton:hover { background:#f0f0f0; }"
        )
        btn_cancel.clicked.connect(self.reject)

        layout.addWidget(self.btn_accept)
        layout.addWidget(btn_cancel)

        return bar

    def _connect_signals(self):
                       
        self.sidebar._tool_group.buttonClicked.connect(self._on_tool_clicked)

        self._tb_tool_group.buttonClicked.connect(self._on_tb_tool_clicked)

        self.sidebar.btn_rect.clicked.connect(self._from_rectangle)
        self.sidebar.btn_circle.clicked.connect(self._from_circle)
        self.sidebar.btn_isec.clicked.connect(self._from_isection)
        self.sidebar.btn_tsec.clicked.connect(self._from_tsection)
        self.sidebar.btn_channel.clicked.connect(self._from_channel)

        self.sidebar.btn_precast_i.clicked.connect(self._from_precast_i)
        self.sidebar.btn_precast_u.clicked.connect(self._from_precast_u)

        self.right.btn_mods.clicked.connect(self._open_modifiers)

        self.canvas.coords_changed.connect(self._on_coords_changed)
        self.canvas.polygon_changed.connect(self._on_polygon_changed)
        self.canvas.polygon_closed.connect(self._on_polygon_closed)
        self.canvas.coord_input_requested.connect(self._on_coord_input_requested)

        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self.canvas.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self.canvas.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self.canvas.redo)
        QShortcut(QKeySequence("Q"), self).activated.connect(
            lambda: self._set_tool(DrawMode.SELECT))
        QShortcut(QKeySequence("D"), self).activated.connect(
            lambda: self._set_tool(DrawMode.DRAW))
        QShortcut(QKeySequence("P"), self).activated.connect(
            lambda: self._set_tool(DrawMode.PAN))
        QShortcut(QKeySequence("F"), self).activated.connect(self.canvas.zoom_to_fit)

        self._on_grid_step_changed(self.grid_combo.currentIndex())

    def _on_tb_tool_clicked(self, btn: QToolButton):
        if btn is self._tb_select:
            self.canvas.set_mode(DrawMode.SELECT)
            self.sidebar.btn_select.setChecked(True)
        elif btn is self._tb_draw:
            self.canvas.set_mode(DrawMode.DRAW)
            self.sidebar.btn_draw.setChecked(True)
        elif btn is self._tb_pan:
            self.canvas.set_mode(DrawMode.PAN)
            self.sidebar.btn_pan.setChecked(True)

    def _on_tool_clicked(self, btn: QToolButton):
        if btn is self.sidebar.btn_select:
            self.canvas.set_mode(DrawMode.SELECT)
        elif btn is self.sidebar.btn_draw:
            self.canvas.set_mode(DrawMode.DRAW)
        elif btn is self.sidebar.btn_pan:
            self.canvas.set_mode(DrawMode.PAN)

    def _set_tool(self, mode: DrawMode):
        """Programmatic tool switch (keyboard shortcut) — syncs both toolbars."""
        self.canvas.set_mode(mode)
        if mode == DrawMode.SELECT:
            self.sidebar.btn_select.setChecked(True)
            self._tb_select.setChecked(True)
        elif mode == DrawMode.DRAW:
            self.sidebar.btn_draw.setChecked(True)
            self._tb_draw.setChecked(True)
        elif mode == DrawMode.PAN:
            self.sidebar.btn_pan.setChecked(True)
            self._tb_pan.setChecked(True)

    @pyqtSlot(str)
    def _on_coords_changed(self, text: str):
        self.coord_lbl.setText(text)

    @pyqtSlot(list)
    def _on_polygon_changed(self, vertices: list):
        n = len(vertices)
        self.right.set_vertex_count(n)
        if self.canvas.is_closed and n >= 3:
            self._run_analysis_silent()
        else:
            self.btn_accept.setEnabled(False)
            self._computed_props = None
            self.right.clear_props()

    @pyqtSlot()
    def _on_polygon_closed(self):
        self._run_analysis_silent()

    @pyqtSlot(bool)
    def _on_snap_toggled(self, enabled: bool):
        self.canvas.set_snap(enabled)
                                                                         
        for btn in (self.btn_snap, self._tb_snap):
            btn.blockSignals(True)
            btn.setChecked(enabled)
            btn.blockSignals(False)

    def _on_grid_step_changed(self, idx: int):
        if 0 <= idx < len(self._step_values_m):
            self.canvas.set_grid_step(
                self._step_values_m[idx] * unit_registry.length_scale)

    @pyqtSlot(int)
    def _on_unit_changed(self, idx: int):
                                       
        unit_text = self.unit_combo.currentText()
        unit_registry.set_unit_system(unit_text)
        
        self._populate_grid_steps()
        
        if self._computed_props:
            self.right.update_props(self._computed_props)
            
        self.canvas.update()

    @pyqtSlot()
    def _on_reset(self):
        reply = QMessageBox.question(
            self, "Clear canvas", "Clear all vertices and start over?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.canvas.reset()
            self._computed_props = None
            self.btn_accept.setEnabled(False)
            self.right.clear_props()

    @pyqtSlot(float, float)
    def _on_coord_input_requested(self, y_w: float, z_w: float):
        dlg = _CoordInputDialog(y_w, z_w, self)
        if dlg.exec():
            self.canvas.place_vertex_at(dlg.y_world, dlg.z_world)

    def _run_analysis_silent(self):
        verts = self.canvas.get_vertices()
        if len(verts) < 3:
            return
            
        props = SectionAnalyzer.compute(verts)
        if props['A'] < 1e-12:
            return
            
        self._computed_props = props
        self.right.update_props(props)
        self.canvas.set_centroid(props['y_c'], props['z_c'])
        self.canvas.set_principal_angle(props['theta_p'])
        
        self.btn_accept.setEnabled(False)
        self.right._prop_fields['J'].setText("Solving FEM...")
        self.right._prop_fields['Asy'].setText("Solving FEM...") 
        self.right._prop_fields['Asz'].setText("Solving FEM...")
        
        self._current_worker_id += 1
        self._current_worker_id += 1
        worker_id = self._current_worker_id
        
        ys, zs = [v[0] for v in verts], [v[1] for v in verts]
        max_dim = max(max(ys) - min(ys), max(zs) - min(zs))
        
        mesh_abs = self._mesh_settings.get("mesh_abs", 0.0)
        mesh_rel = self._mesh_settings.get("mesh_rel", 0.05)
        
        if mesh_abs > 1e-12:
            dynamic_mesh_size = mesh_abs
        else:
            dynamic_mesh_size = max(max_dim * mesh_rel, 1e-6)
                                                      
        worker = SectionWorker(section_id=worker_id, vertices=verts, mesh_size=dynamic_mesh_size)
        worker.signals.finished.connect(self._on_fem_finished)
        worker.signals.error.connect(lambda err: print(f"Section FEM Error: {err}"))
        
        self.thread_pool.start(worker)

    @pyqtSlot(dict)
    def _on_fem_finished(self, result: dict):
        if result['section_id'] != self._current_worker_id:
            return
            
        self._computed_props['J'] = result['J_exact']
        self._computed_props['Asy'] = result['Asz']               
        self._computed_props['Asz'] = result['Asy']               
        
        self.right.update_props(self._computed_props)
        self.btn_accept.setEnabled(True)

    def _from_rectangle(self):
        dlg = _DimDialog("Rectangle", [
            ("b", "Width  (b)", 0.30), ("h", "Height (h)", 0.50),
        ], self)
        if dlg.exec():
            v = dlg.values_m()
            self.canvas.push_shape(_rect_verts(v['b'], v['h']), "Rectangle")
            self.canvas.zoom_to_fit()

    def _from_circle(self):
        dlg = _DimDialog("Circle / Regular polygon", [
            ("r", "Radius (r)", 0.20), ("n", "Num. sides", 32.0),
        ], self)
        if dlg.exec():
            v = dlg.values_m()
            self.canvas.push_shape(_circle_verts(v['r'], max(3, int(round(v['n'])))), "Circle")
            self.canvas.zoom_to_fit()

    def _from_isection(self):
        dlg = _DimDialog("I-Section", [
            ("bf", "Flange width  (bf)", 0.200), ("d",  "Total depth   (d)",  0.400),
            ("tf", "Flange thick  (tf)", 0.015), ("tw", "Web thick     (tw)", 0.010),
        ], self)
        if dlg.exec():
            v = dlg.values_m()
            if v['tf'] >= v['d'] / 2 or v['tw'] >= v['bf']:
                QMessageBox.warning(self, "Invalid dimensions",
                    "Flange or web thickness exceeds section depth/width.")
                return
            self.canvas.push_shape(
                _isection_verts(v['bf'], v['d'], v['tf'], v['tw']), "I-Section")
            self.canvas.zoom_to_fit()

    def _from_tsection(self):
        dlg = _DimDialog("T-Section", [
            ("bf", "Flange width  (bf)", 0.200), ("d",  "Total depth   (d)",  0.400),
            ("tf", "Flange thick  (tf)", 0.015), ("tw", "Web thick     (tw)", 0.010),
        ], self)
        if dlg.exec():
            v = dlg.values_m()
            if v['tf'] >= v['d'] or v['tw'] >= v['bf']:
                QMessageBox.warning(self, "Invalid dimensions",
                    "Flange or web thickness exceeds section depth/width.")
                return
            self.canvas.push_shape(
                _tsection_verts(v['bf'], v['d'], v['tf'], v['tw']), "T-Section")
            self.canvas.zoom_to_fit()

    def _from_channel(self):
        dlg = _DimDialog("C-Channel", [
            ("bf", "Flange length (bf)", 0.100), ("d",  "Total depth   (d)",  0.200),
            ("tf", "Flange thick  (tf)", 0.012), ("tw", "Web thick     (tw)", 0.008),
        ], self)
        if dlg.exec():
            v = dlg.values_m()
            if v['tf'] >= v['d'] / 2 or v['tw'] >= v['bf']:
                QMessageBox.warning(self, "Invalid dimensions",
                    "Flange or web thickness exceeds section depth/width.")
                return
            self.canvas.push_shape(
                _channel_verts(v['bf'], v['d'], v['tf'], v['tw']), "C-Channel")
            self.canvas.zoom_to_fit()

    @pyqtSlot()
    def _on_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Please enter a section name.")
            return
        if not self._computed_props:
            QMessageBox.warning(self, "No section",
                "Draw and close a polygon first.")
            return
        mat_name = self.mat_combo.currentText()
        if not mat_name or mat_name not in self.model.materials:
            QMessageBox.critical(self, "No material", "Please select a valid material.")
            return

        mat   = self.model.materials[mat_name]
        verts = self.canvas.get_vertices()
        p     = self._computed_props

        props_dict = {
            'A': p['A'], 'J': p['J'], 'I33': p['I33'], 'I22': p['I22'],
            'As2': p['Asy'], 'As3': p['Asz'],
            'theta_p': p['theta_p'],
        }
        y_c, z_c      = p['y_c'], p['z_c']
        shifted_verts  = [(y - y_c, z - z_c) for (y, z) in verts]
        section        = ArbitrarySection(name, mat, shifted_verts, props_dict)
        section.color     = self._color
        section.modifiers = self._modifiers.copy()
        section.mesh_settings = self._mesh_settings.copy()

        self.result_section = section
        self.accept()

    def _load_existing(self, sec: ArbitrarySection):
        self.name_edit.setText(sec.name)
        idx = self.mat_combo.findText(sec.material.name)
        if idx >= 0:
            self.mat_combo.setCurrentIndex(idx)
        if hasattr(sec, 'color') and sec.color:
            self._color = sec.color
            self._update_color_swatch()
        if hasattr(sec, 'modifiers') and sec.modifiers:
            self._modifiers = sec.modifiers.copy()
        if hasattr(sec, 'mesh_settings') and sec.mesh_settings:
            self._mesh_settings = sec.mesh_settings.copy()
        if sec.vertices:
            self.canvas.set_vertices(sec.vertices)
            self.canvas.zoom_to_fit()
            self._computed_props = {
                'A': sec.A, 'J': sec.J, 'I33': sec.I33, 'I22': sec.I22,
                'Asy': sec.Asy, 'Asz': sec.Asz, 'S33': sec.S33, 'S22': sec.S22,
                'r33': sec.r33, 'r22': sec.r22,
                'Iyz': 0.0, 'theta_p': getattr(sec, 'theta_p', 0.0), 'y_c': 0.0, 'z_c': 0.0,
            }
            self.right.update_props(self._computed_props)
            self.btn_accept.setEnabled(True)

    def _set_default_name(self):
        base = "FSEC"
        idx  = 1
        while f"{base}{idx}" in self.model.sections:
            idx += 1
        self.name_edit.setText(f"{base}{idx}")

    def _pick_color(self):
        r, g, b = [int(c * 255) for c in self._color[:3]]
        c = QColorDialog.getColor(QColor(r, g, b), self, "Section Color")
        if c.isValid():
            self._color = (c.redF(), c.greenF(), c.blueF(), 1.0)
            self._update_color_swatch()

    def _update_color_swatch(self):
        r, g, b = [int(c * 255) for c in self._color[:3]]
        self.btn_color.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); "
            "border: 1px solid #888; border-radius: 2px;"
        )

    def _open_modifiers(self):
        dlg = _ModifiersDialog(self._modifiers, self)
        if dlg.exec():
            self._modifiers = dlg.modifiers

    def _material_nu(self, default: float = 0.2) -> float:
        """Best-effort Poisson's ratio lookup — attribute name isn't fixed
        across material model versions, so try the common spellings."""
        mat_name = self.mat_combo.currentText()
        mat = self.model.materials.get(mat_name)
        if mat is None:
            return default
        for attr in ("nu", "poisson_ratio", "poissons_ratio", "U12", "v"):
            val = getattr(mat, attr, None)
            if isinstance(val, (int, float)):
                return float(val)
        return default

    def _closed_vertices_or_warn(self):
        if not self.canvas.is_closed or len(self.canvas.get_vertices()) < 3:
            QMessageBox.information(
                self, "No section", "Draw and close a polygon first.")
            return None
        return self.canvas.get_vertices()

    def _open_section_properties(self):
        verts = self._closed_vertices_or_warn()
        if verts is None:
            return
        dlg = SectionPropertiesDialog(
            verts, self.mat_combo.currentText(), self._material_nu(),
            self._mesh_settings,
            unit_registry.length_scale, unit_registry.length_unit_name, self)
        dlg.mesh_settings_changed.connect(self._on_mesh_settings_changed)
        
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._run_analysis_silent()

    def _open_generated_fibers(self):
        verts = self._closed_vertices_or_warn()
        if verts is None:
            return
        dlg = GeneratedFibersDialog(
            verts, self.mat_combo.currentText(), self._material_nu(),
            self._mesh_settings,
            unit_registry.length_scale, unit_registry.length_unit_name, self)
        dlg.mesh_settings_changed.connect(self._on_mesh_settings_changed)
        
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._run_analysis_silent()
            
    def _open_elastic_stress(self):
        verts = self._closed_vertices_or_warn()
        if verts is None:
            return
        dlg = ElasticStressDialog(
            verts, self.mat_combo.currentText(), self._material_nu(),
            self._mesh_settings,
            length_unit_scale=unit_registry.length_scale,
            length_unit_name=unit_registry.length_unit_name,
            force_scale=unit_registry.force_scale,
            force_unit_name=unit_registry.force_unit_name,
            pressure_unit_name=unit_registry.pressure_unit,
            parent=self)
        dlg.mesh_settings_changed.connect(self._on_mesh_settings_changed)
        dlg.exec()

    def _on_mesh_settings_changed(self, settings: dict):
        self._mesh_settings = dict(settings)

    def _populate_grid_steps(self):
        self.grid_combo.blockSignals(True)
        self.grid_combo.clear()
        unit  = unit_registry.length_unit_name
        scale = unit_registry.length_scale
        steps_m = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0]
        self._step_values_m  = steps_m
        default_idx = 0
        for i, sm in enumerate(steps_m):
            sd = sm * scale
            label = f"{int(sd)} {unit}" if sd == int(sd) else f"{sd:g} {unit}"
            self.grid_combo.addItem(label)
            if abs(sm - 0.05) < 1e-9:
                default_idx = i
        self.grid_combo.setCurrentIndex(default_idx)
        self.grid_combo.blockSignals(False)

    @staticmethod
    def _h_line() -> QFrame:
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setFrameShadow(QFrame.Shadow.Sunken); f.setFixedHeight(1)
        return f

    @staticmethod
    def _v_line() -> QFrame:
        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setFrameShadow(QFrame.Shadow.Sunken); f.setFixedWidth(1)
        return f

    @staticmethod
    def _v_sep() -> QFrame:
        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setFrameShadow(QFrame.Shadow.Sunken)
        f.setFixedSize(1, 24)
        return f
