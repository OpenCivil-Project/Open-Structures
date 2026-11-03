"""
OpenCivil UI Theme
==================
Single source of truth for all dialog styling.

USAGE IN ANY DIALOG
-------------------
1. Import at the top:
       from app.ui.theme import apply_dialog_style, COLORS

2. Call once in __init__, before any widget setup:
       apply_dialog_style(self)

3. Tag buttons with their role — that's all:
       btn_run    = QPushButton("Run Now");     btn_run.setObjectName("primary")
       btn_close  = QPushButton("Close");       btn_close.setObjectName("secondary")
       btn_delete = QPushButton("Delete");      btn_delete.setObjectName("danger")
       btn_ok     = QPushButton("OK");          btn_ok.setObjectName("primary")
       btn_cancel = QPushButton("Cancel");      btn_cancel.setObjectName("secondary")

4. For programmatic coloring (e.g. table cell foregrounds), use COLORS dict:
       item.setForeground(QColor(COLORS["text_secondary"]))
       item.setForeground(QColor(COLORS["accent"]))

DARK MODE / SWITCHING THEME
---------------------------
    from app.ui.theme import set_theme
    set_theme("Dark")     # or "Light" -- live, no restart

Light and dark are just the LIGHT_COLORS / DARK_COLORS dicts below (same keys).
The app palette, every dialog stylesheet, the icons and COLORS are all generated
from them, so nothing can disagree. COLORS is updated in place, so read it at
use time (COLORS["accent"]) rather than copying values into module constants.
Use on_theme_changed(fn) if something caches colours.

CHANGING THE LOOK LATER
------------------------
Edit the values below — every dialog updates automatically.
Never define inline stylesheets inside dialog files.
"""

import os
import json

_THEME_DIR  = os.path.dirname(os.path.abspath(__file__))
_ARROW_UP   = os.path.join(_THEME_DIR, "_arrow_up.svg").replace("\\", "/")
_ARROW_DOWN = os.path.join(_THEME_DIR, "_arrow_down.svg").replace("\\", "/")
_CHECK_TICK = os.path.join(_THEME_DIR, "_check_tick.svg").replace("\\", "/")
_RADIO_DOT  = os.path.join(_THEME_DIR, "_radio_dot.svg").replace("\\", "/")

_SVG_UP   = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><polygon points="3,0 6,4 0,4" fill="#555555"/></svg>'
_SVG_DOWN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><polygon points="0,0 6,0 3,4" fill="#555555"/></svg>'

LIGHT_COLORS = {
    "accent":               "#0078D7",
    "accent_hover":         "#005A9E",
    "accent_pressed":       "#004275",
    "danger":               "#555555",
    "danger_hover":         "#333333",
    "danger_bg_hover":      "#EBEBEB",
    "danger_bg_pressed":    "#DEDEDE",
    "bg_dialog":            "#F9F9F9",
    "bg_panel":             "#FFFFFF",
    "bg_input":             "#FFFFFF",
    "bg_table_header":      "#F0F0F0",
    "bg_table_alt":         "#F7F7F7",
    "bg_btn_hover":         "#F0F0F0",
    "bg_btn_pressed":       "#E0E0E0",
    "bg_disabled":          "#F5F5F5",
    "border":               "#D0D0D0",
    "border_focus":         "#0078D7",
    "border_light":         "#E8E8E8",
    "text_primary":         "#1A1A1A",
    "text_secondary":       "#555555",
    "text_disabled":        "#AAAAAA",
    "text_on_accent":       "#FFFFFF",
    "selection_bg":         "#CCE4F7",
    "selection_text":       "#1A1A1A",
    "border_hover":         "#AAAAAA",
    "icon":                 "#555555",
    "bg_input_solid":       "#FFFFFF",
    "border_input":         "#A8A8A8",
    "bg_btn":               "#F3F3F3",
    "bg_btn_hover_solid":   "#E6F0FA",
    "border_btn":           "#8C8C8C",
    "btn_edge":             "#C4C4C4",
}

DARK_COLORS = {
    "accent":               "#4A9EFF",
    "accent_hover":         "#5BA6FF",
    "accent_pressed":       "#0D7BFF",
    "danger":               "#FF5555",
    "danger_hover":         "#FF3333",
    "danger_bg_hover":      "#331111",
    "danger_bg_pressed":    "#441111",
    "bg_dialog":            "#1E1E1E",
    "bg_panel":             "#252525",
    "bg_input":             "#2D2D2D",
    "bg_table_header":      "#333333",
    "bg_table_alt":         "#2A2A2A",
    "bg_btn_hover":         "#353535",
    "bg_btn_pressed":       "#404040",
    "bg_disabled":          "#2D2D2D",
    "border":               "#404040",
    "border_focus":         "#4A9EFF",
    "border_light":         "#333333",
    "text_primary":         "#FFFFFF",
    "text_secondary":       "#AAAAAA",
    "text_disabled":        "#666666",
    "text_on_accent":       "#FFFFFF",
    "selection_bg":         "#404040",
    "selection_text":       "#4A9EFF",
    "border_hover":         "#777777",
    "icon":                 "#BBBBBB",
    "bg_input_solid":       "#2E2E2E",
    "border_input":         "#5A5A5A",
    "bg_btn":               "#3C3C3C",
    "bg_btn_hover_solid":   "#4A4A4A",
    "border_btn":           "#8A8A8A",
    "btn_edge":             "#2A2A2A",
}

SIZES = {
    "font_family":          "Segoe UI",
    "font_size_normal":     9,
    "font_size_small":      8,
    "font_size_heading":    10,
    "btn_height":           23,
    "btn_min_width":        75,
    "btn_padding":          "3px 10px",
    "input_height":         26,
    "input_padding":        "3px 6px",
    "indicator_size":       16,
    "border_radius":        3,
    "groupbox_margin_top":  10,
    "groupbox_padding_top": 6,
    "groupbox_title_left":  8,
    "section_spacing":      10,
    "row_height":           24,
}

from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import QApplication
import tempfile
from app.ui import blur as _blur

_PREFS_PATH = os.path.join(os.path.expanduser("~"), ".OpenStructures_prefs.json")

def _read_theme_pref() -> str:
    try:
        if os.path.exists(_PREFS_PATH):
            with open(_PREFS_PATH, "r") as f:
                return "Dark" if json.load(f).get("ui_theme", "Light") == "Dark" else "Light"
    except Exception:
        pass
    return "Light"

def _read_glass_pref() -> int:
    """Saved glass strength (0-100) from the prefs file; 100 (max) if missing."""
    try:
        if os.path.exists(_PREFS_PATH):
            with open(_PREFS_PATH, "r") as f:
                return max(0, min(100, int(json.load(f).get("glass_strength", 100))))
    except Exception:
        pass
    return 100

GLASS_MAX_TRANSPARENCY = 75                                                     

def _read_glass_transparency_pref() -> int:
    """Saved extra glass transparency (0-75 %) from the prefs file; 10 if missing."""
    try:
        if os.path.exists(_PREFS_PATH):
            with open(_PREFS_PATH, "r") as f:
                return max(0, min(GLASS_MAX_TRANSPARENCY,
                                  int(json.load(f).get("glass_transparency", 10))))
    except Exception:
        pass
    return 10

COLORS = dict(LIGHT_COLORS)
_C = COLORS
_GLASS_STRENGTH = 100
_GLASS_TRANSPARENCY = 10
_S = SIZES
_CURRENT_THEME = "Light"
_listeners = []
MASTER_STYLESHEET = ""
DOCK_STYLESHEET = ""

def current_theme() -> str:
    """'Light' or 'Dark'."""
    return _CURRENT_THEME

def on_theme_changed(callback) -> None:
    """Register callback(theme_name) to run after every set_theme() -- for docks,
    plots or anything that caches colours."""
    if callback not in _listeners:
        _listeners.append(callback)

def off_theme_changed(callback) -> None:
    """Unregister a callback added with on_theme_changed() -- call it when the
    dialog that owns the callback closes, so it isn't kept alive / called."""
    try:
        _listeners.remove(callback)
    except ValueError:
        pass

GLASS_DIALOG_ALPHA = 215
GLASS_PANEL_ALPHA = 150
GLASS_MENU_ALPHA = 205
_GLASS_SLOPE = {"dialog": 1.2, "panel": 1.5, "menu": 1.0}
_GLASS_BASE = {"dialog": GLASS_DIALOG_ALPHA, "panel": GLASS_PANEL_ALPHA, "menu": GLASS_MENU_ALPHA}

def glass_strength() -> int:
    """Current glass strength, 0 (solid) .. 100 (most see-through)."""
    return _GLASS_STRENGTH

def glass_transparency() -> int:
    """Extra transparency of the glass layer in %, 0 .. GLASS_MAX_TRANSPARENCY (75)."""
    return _GLASS_TRANSPARENCY

def glass_alpha(kind) -> int:
    """Background alpha for 'dialog', 'panel' or 'menu': blur strength sets the base,
    transparency then makes the whole layer that many % more see-through."""
    a = _GLASS_BASE[kind] + (50 - _GLASS_STRENGTH) * _GLASS_SLOPE[kind]
    a *= 1.0 - _GLASS_TRANSPARENCY / 100.0
    return int(max(64, min(255, round(a))))                                   

def _glass_changed() -> None:
    _rebuild_stylesheets()
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(_app_stylesheet())
    for cb in list(_listeners):
        try:
            cb(_CURRENT_THEME)
        except Exception:
            pass

def set_glass_strength(value, app=None) -> int:
    """Change glass strength live. Persisting it (glass_strength in the prefs
    file) is the caller's job -- Graphics Options does it via graphics_settings."""
    global _GLASS_STRENGTH
    v = max(0, min(100, int(value)))
    if v != _GLASS_STRENGTH:
        _GLASS_STRENGTH = v
        _glass_changed()
    return v

def set_glass_transparency(value, app=None) -> int:
    """Change the extra glass transparency live (clamped to 0..75 %). Persisted by
    the caller as glass_transparency, like glass_strength."""
    global _GLASS_TRANSPARENCY
    v = max(0, min(GLASS_MAX_TRANSPARENCY, int(value)))
    if v != _GLASS_TRANSPARENCY:
        _GLASS_TRANSPARENCY = v
        _glass_changed()
    return v

def _rgba(color, alpha) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"

def _glass(key, alpha) -> str:
    """Background colour for COLORS[key]: translucent on blurred windows, solid otherwise."""
    return _rgba(_C[key], alpha) if _blur.blur_supported() else _C[key]

def _menu_qss() -> str:
    glass = _blur.blur_supported()
    radius = _blur.CORNER_RADIUS if glass else 0
    border = _rgba(_C["border"], 200) if glass else _C["border"]
    return f"""
QMenu {{
    background-color: {_glass("bg_panel", glass_alpha("menu"))};
    color: {_C["text_primary"]};
    border: 1px solid {border};
    border-radius: {radius}px;
    padding: 4px;
    font-size: {_S["font_size_normal"]}pt;
}}
QMenu::item {{
    padding: 5px 20px 5px 12px;
    border-radius: {max(_S["border_radius"], radius - 2)}px;
}}
QMenu::item:selected {{
    background-color: {_C["selection_bg"]};
    color: {_C["selection_text"]};
}}
QMenu::item:disabled {{
    color: {_C["text_disabled"]};
}}
QMenuBar::item:disabled {{
    color: {_C["text_disabled"]};
}}
QMenu::separator {{
    height: 1px;
    background: {_C["border_light"]};
    margin: 4px 6px;
}}
"""

def get_current_theme_colors():
    return COLORS

def _write_icons() -> None:
    """Spinbox/combo arrows are image files with a baked-in colour. Regenerate
    them in the active theme's icon colour (tick and radio dot keep the bundled
    files -- they read fine on both themes)."""
    global _ARROW_UP, _ARROW_DOWN
    try:
        d = os.path.join(tempfile.gettempdir(), "OpenStructures_theme_icons", _CURRENT_THEME.lower())
        os.makedirs(d, exist_ok=True)
        for fname, svg in (("_arrow_up.svg", _SVG_UP), ("_arrow_down.svg", _SVG_DOWN)):
            with open(os.path.join(d, fname), "w") as f:
                f.write(svg.replace("#555555", _C["icon"]))
        _ARROW_UP = os.path.join(d, "_arrow_up.svg").replace("\\", "/")
        _ARROW_DOWN = os.path.join(d, "_arrow_down.svg").replace("\\", "/")
    except Exception:
        pass                                

def _build_palette() -> QPalette:
    """Palette generated from COLORS, so widgets that have no QSS rule still
    match the dialogs exactly."""
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    q = lambda k: QColor(_C[k])
    p = QPalette()
    p.setColor(R.Window, q("bg_dialog"))
    p.setColor(R.WindowText, q("text_primary"))
    p.setColor(R.Base, q("bg_panel"))
    p.setColor(R.AlternateBase, q("bg_table_alt"))
    p.setColor(R.ToolTipBase, q("bg_panel"))
    p.setColor(R.ToolTipText, q("text_primary"))
    p.setColor(R.Text, q("text_primary"))
    p.setColor(R.PlaceholderText, q("text_disabled"))
    p.setColor(R.Button, q("bg_table_header"))
    p.setColor(R.ButtonText, q("text_primary"))
    p.setColor(R.Link, q("accent"))
    p.setColor(R.Highlight, q("accent"))
    p.setColor(R.HighlightedText, q("text_on_accent"))
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(G.Disabled, role, q("text_disabled"))
    return p

def _app_stylesheet() -> str:
    return f"""
        QPushButton#primary {{ background-color: {_C["accent"]}; color: {_C["text_on_accent"]}; font-weight: bold; border-radius: {_S["border_radius"]}px; padding: 5px 10px; border: 1px solid {_C["accent_hover"]}; border-bottom: 2px solid {_C["accent_pressed"]}; }}
        QPushButton#primary:hover {{ background-color: {_C["accent_hover"]}; }}
        QPushButton#secondary {{ background-color: {_C["bg_btn"]}; border: 1px solid {_C["border_btn"]}; border-bottom: 2px solid {_C["btn_edge"]}; border-radius: {_S["border_radius"]}px; padding: 5px 10px; }}
        QPushButton#secondary:hover {{ background-color: {_C["bg_btn_hover_solid"]}; border: 1px solid {_C["accent"]}; border-bottom: 2px solid {_C["accent"]}; }}
    """ + _menu_qss()

def set_theme(name, app=None) -> str:
    """
    THE way to switch theme -- live, no restart needed:

        set_theme("Dark")      # or "Light"

    Updates COLORS in place, rebuilds the dialog/dock stylesheets, regenerates
    the arrow icons, applies the matching palette to the application and
    notifies on_theme_changed() listeners. Dialogs created afterwards pick it
    up automatically; an already-open dialog just calls apply_dialog_style(self).
    Persisting the choice (ui_theme in the prefs file) stays the caller's job.
    """
    global _CURRENT_THEME
    _CURRENT_THEME = "Dark" if str(name).strip().lower() == "dark" else "Light"
    COLORS.update(DARK_COLORS if _CURRENT_THEME == "Dark" else LIGHT_COLORS)
    _write_icons()
    _rebuild_stylesheets()
    app = app or QApplication.instance()
    if app is not None:
        if app.style().objectName().lower() != "fusion":
            app.setStyle("Fusion")
        app.setPalette(_build_palette())
        app.setStyleSheet(_app_stylesheet())
        _blur.install(app)
    _blur.refresh()
    for cb in list(_listeners):
        try:
            cb(_CURRENT_THEME)
        except Exception:
            pass
    return _CURRENT_THEME

def set_global_theme(app: QApplication):
    """Startup hook (kept for compatibility): applies the theme saved in the
    prefs file. Safe to call again at any time -- it now refreshes everything."""
    set_theme(_read_theme_pref(), app)

def _rebuild_stylesheets():
    global MASTER_STYLESHEET, DOCK_STYLESHEET
    _QSS_DIALOG = f"""
QDialog {{
    background-color: {_glass("bg_dialog", glass_alpha("dialog"))};
    font-family: {_S["font_family"]};
    font-size: {_S["font_size_normal"]}pt;
    color: {_C["text_primary"]};
}}
"""

    _QSS_GROUPBOX = f"""
QGroupBox {{
    font-weight: bold;
    font-size: {_S["font_size_heading"]}pt;
    color: {_C["text_primary"]};
    border: 1px solid {_C["border"]};
    border-radius: {_S["border_radius"]}px;
    margin-top: {_S["groupbox_margin_top"]}px;
    padding-top: {_S["groupbox_padding_top"]}px;
    background-color: {_glass("bg_panel", glass_alpha("panel"))};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    left: {_S["groupbox_title_left"]}px;
    color: {_C["text_primary"]};
}}
"""

    _QSS_TABLE = f"""
QTableView, QTreeView, QListWidget {{
    background-color: {_C["bg_panel"]};
    alternate-background-color: {_C["bg_table_alt"]};
    gridline-color: {_C["border"]};
    selection-background-color: {_C["selection_bg"]};
    selection-color: {_C["selection_text"]};
    border: 1px solid {_C["border"]};
    outline: none;
    font-size: {_S["font_size_normal"]}pt;
}}
QTableView::item, QTreeView::item, QListWidget::item {{
    padding: 2px 6px;
    min-height: {_S["row_height"]}px;
}}
QTreeView::item:selected {{
    background-color: {_C["selection_bg"]};
    color: {_C["selection_text"]};
}}
QTreeView::item:hover:!selected {{
    background-color: {_C["bg_btn_hover"]};
}}
QHeaderView::section {{
    background-color: {_C["bg_table_header"]};
    color: {_C["text_primary"]};
    font-weight: bold;
    font-size: {_S["font_size_small"]}pt;
    padding: 5px 6px;
    border: none;
    border-right: 1px solid {_C["border"]};
    border-bottom: 1px solid {_C["border"]};
}}
QHeaderView::section:last {{
    border-right: none;
}}
QTableCornerButton::section {{
    background-color: {_C["bg_table_header"]};
    border: none;
    border-right: 1px solid {_C["border"]};
    border-bottom: 1px solid {_C["border"]};
}}
"""

    _QSS_INPUTS = f"""
QLineEdit,
QSpinBox,
QDoubleSpinBox {{
    background-color: {_C["bg_input_solid"]};
    color: {_C["text_primary"]};
    border: 1px solid {_C["border_input"]};
    border-radius: {_S["border_radius"]}px;
    padding: {_S["input_padding"]};
    min-height: {_S["input_height"]}px;
    font-size: {_S["font_size_normal"]}pt;
}}
QLineEdit:hover,
QSpinBox:hover,
QDoubleSpinBox:hover {{
    border-color: {_C["border_hover"]};
}}
QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {{
    border: 1px solid {_C["border_focus"]};
}}
QLineEdit:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled {{
    background-color: {_C["bg_disabled"]};
    color: {_C["text_disabled"]};
}}
QSpinBox::up-button,
QDoubleSpinBox::up-button,
QSpinBox::down-button,
QDoubleSpinBox::down-button {{
    width: 16px;
    border-left: 1px solid {_C["border"]};
    background-color: {_C["bg_table_header"]};
}}
QSpinBox::up-button:hover,
QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover,
QDoubleSpinBox::down-button:hover {{
    background-color: {_C["bg_btn_pressed"]};
}}
QSpinBox::up-button:pressed,
QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed,
QDoubleSpinBox::down-button:pressed {{
    background-color: {_C["selection_bg"]};
}}
QSpinBox::up-arrow,
QDoubleSpinBox::up-arrow {{
    image: url({_ARROW_UP});
    width: 6px;
    height: 4px;
}}
QSpinBox::down-arrow,
QDoubleSpinBox::down-arrow {{
    image: url({_ARROW_DOWN});
    width: 6px;
    height: 4px;
}}
"""

    _QSS_COMBOBOX = f"""
QComboBox {{
    background-color: {_C["bg_input_solid"]};
    color: {_C["text_primary"]};
    border: 1px solid {_C["border_input"]};
    border-radius: {_S["border_radius"]}px;
    padding: {_S["input_padding"]};
    padding-right: 20px;
    min-height: {_S["input_height"]}px;
    font-size: {_S["font_size_normal"]}pt;
}}
QComboBox:hover {{
    border-color: {_C["border_hover"]};
}}
QComboBox:focus {{
    border-color: {_C["border_focus"]};
}}
QComboBox:disabled {{
    background-color: {_C["bg_disabled"]};
    color: {_C["text_disabled"]};
    border-color: {_C["border_light"]};
}}
QComboBox::drop-down {{
    width: 16px;
    border-left: 1px solid {_C["border"]};
    background-color: {_C["bg_table_header"]};
    border-top-right-radius: {_S["border_radius"]}px;
    border-bottom-right-radius: {_S["border_radius"]}px;
}}
QComboBox::drop-down:hover {{
    background-color: {_C["bg_btn_pressed"]};
}}
QComboBox::down-arrow {{
    image: url({_ARROW_DOWN});
    width: 6px;
    height: 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {_C["bg_input_solid"]};
    border: 1px solid {_C["border_input"]};
    selection-background-color: {_C["selection_bg"]};
    selection-color: {_C["selection_text"]};
    outline: none;
    font-size: {_S["font_size_normal"]}pt;
}}
"""

    _QSS_TABLE_COMBOBOX = f"""
QTableView QComboBox {{
    border: none;
    border-radius: 0px;
    background-color: transparent;
    padding: 1px 4px;
    min-height: 0px;
    font-size: {_S["font_size_normal"]}pt;
    color: {_C["text_primary"]};
}}
QTableView QComboBox:hover {{
    background-color: {_C["selection_bg"]};
}}
QTableView QComboBox:focus {{
    border: 1px solid {_C["border_focus"]};
    border-radius: {_S["border_radius"]}px;
    background-color: {_C["bg_input"]};
}}
QTableView QComboBox QAbstractItemView {{
    background-color: {_C["bg_panel"]};
    border: 1px solid {_C["border"]};
    selection-background-color: {_C["selection_bg"]};
    selection-color: {_C["selection_text"]};
    outline: none;
    font-size: {_S["font_size_normal"]}pt;
}}
"""

    _QSS_LABEL = f"""
QLabel {{
    color: {_C["text_primary"]};
    font-size: {_S["font_size_normal"]}pt;
    background-color: transparent;
}}
QLabel#hint {{
    color: {_C["text_secondary"]};
    font-size: {_S["font_size_small"]}pt;
}}
"""

    _QSS_CHECK_RADIO = f"""
QCheckBox,
QRadioButton {{
    color: {_C["text_primary"]};
    font-size: {_S["font_size_normal"]}pt;
    spacing: 6px;
    outline: none;
}}
QCheckBox:disabled,
QRadioButton:disabled {{
    color: {_C["text_disabled"]};
}}
QCheckBox::indicator,
QRadioButton::indicator {{
    width: {_S["indicator_size"]}px;
    height: {_S["indicator_size"]}px;
    background-color: {_C["bg_input"]};
    border: 1.5px solid {_C["border"]};
}}
QCheckBox::indicator:hover,
QRadioButton::indicator:hover {{
    border-color: {_C["accent"]};
}}
QCheckBox::indicator:disabled,
QRadioButton::indicator:disabled {{
    background-color: {_C["bg_disabled"]};
    border-color: {_C["border_light"]};
}}

QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border-radius: {_S["border_radius"]}px;
}}
QCheckBox::indicator:checked {{
    background-color: {_C["accent"]};
    border-color: {_C["accent"]};
    image: url({_CHECK_TICK});
}}
QCheckBox::indicator:checked:hover {{
    background-color: {_C["accent_hover"]};
    border-color: {_C["accent_hover"]};
}}
QCheckBox::indicator:checked:disabled {{
    background-color: {_C["text_disabled"]};
    border-color: {_C["text_disabled"]};
}}

QRadioButton::indicator {{
    border-radius: {_S["indicator_size"] // 2}px;
    border-width: 1px;
}}
QRadioButton::indicator:checked {{
    border-color: {_C["accent"]};
    image: url({_RADIO_DOT});
}}
QRadioButton::indicator:checked:hover {{
    border-color: {_C["accent_hover"]};
}}
QRadioButton::indicator:checked:disabled {{
    border-color: {_C["text_disabled"]};
}}
"""

    _QSS_BUTTONS = f"""
QPushButton {{
    background-color: {_C["bg_btn"]};
    color: {_C["text_primary"]};
    border: 1px solid {_C["border_btn"]};
    border-bottom: 2px solid {_C["btn_edge"]};
    border-radius: {_S["border_radius"]}px;
    padding: {_S["btn_padding"]};
    min-width: {_S["btn_min_width"]}px;
    min-height: {_S["btn_height"]}px;
    font-size: {_S["font_size_normal"]}pt;
}}
QPushButton:hover {{
    background-color: {_C["bg_btn_hover_solid"]};
    border: 1px solid {_C["accent"]};
    border-bottom: 2px solid {_C["accent"]};
}}
QPushButton:focus {{
    border: 1px solid {_C["accent"]};
    border-bottom: 2px solid {_C["accent"]};
}}
QPushButton:pressed {{
    background-color: {_C["bg_btn_pressed"]};
    border-bottom: 1px solid {_C["accent"]};
}}
QPushButton:disabled {{
    color: {_C["text_disabled"]};
    border: 1px solid {_C["border_light"]};
    background-color: {_C["bg_disabled"]};
}}

QPushButton#primary {{
    background-color: {_C["accent"]};
    color: {_C["text_on_accent"]};
    border: 1px solid {_C["accent_hover"]};
    border-bottom: 2px solid {_C["accent_pressed"]};
    font-weight: bold;
}}
QPushButton#primary:hover {{
    background-color: {_C["accent_hover"]};
    border: 1px solid {_C["text_on_accent"]};
    border-bottom: 2px solid {_C["accent_pressed"]};
}}
QPushButton#primary:pressed {{
    background-color: {_C["accent_pressed"]};
}}
QPushButton#primary:disabled {{
    background-color: {_C["text_disabled"]};
    color: {_C["text_on_accent"]};
    border: 1px solid {_C["text_disabled"]};
}}

QPushButton#danger {{
    background-color: {_C["bg_btn"]};
    color: {_C["danger"]};
    border: 1px solid {_C["danger"]};
}}
QPushButton#danger:hover {{
    background-color: {_C["danger_bg_hover"]};
}}
QPushButton#danger:pressed {{
    background-color: {_C["danger_bg_pressed"]};
}}
QPushButton#danger:disabled {{
    color: {_C["text_disabled"]};
    border-color: {_C["border_light"]};
}}
"""

    _QSS_TABS = f"""
QTabWidget::pane {{
    border: 1px solid {_C["border"]};
    background: {_C["bg_panel"]};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background: {_C["bg_table_header"]};
    color: {_C["text_secondary"]};
    padding: 8px 20px;
    border: 1px solid {_C["border"]};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
    font-size: {_S["font_size_heading"]}pt;
}}
QTabBar::tab:selected {{
    background: {_C["accent"]};
    color: {_C["text_on_accent"]};
    font-weight: bold;
    border-color: {_C["accent"]};
}}
QTabBar::tab:hover:!selected {{
    background: {_C["bg_btn_hover"]};
    color: {_C["text_primary"]};
}}
"""

    _QSS_TEXT_PROGRESS = f"""
QTextEdit, QPlainTextEdit {{
    background-color: {_C["bg_panel"]};
    color: {_C["text_primary"]};
    border: 1px solid {_C["border"]};
    selection-background-color: {_C["selection_bg"]};
    selection-color: {_C["selection_text"]};
}}
QProgressBar {{
    border: 1px solid {_C["border"]};
    background-color: {_C["bg_input"]};
    border-radius: 2px;
}}
QProgressBar::chunk {{
    background-color: {_C["accent"]};
    border-radius: 1px;
}}
"""

    _QSS_SCROLLBAR = f"""
QScrollBar:vertical {{
    background: {_C["bg_dialog"]};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {_C["border"]};
    border-radius: 5px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {_C["border_hover"]};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {_C["bg_dialog"]};
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {_C["border"]};
    border-radius: 5px;
    min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {_C["border_hover"]};
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""

    _QSS_DOCK = f"""
QDockWidget {{
    color: {_C["text_primary"]};
    font-family: {_S["font_family"]};
    font-size: {_S["font_size_normal"]}pt;
    background-color: {_C["bg_dialog"]};
}}
QDockWidget::title {{
    background-color: {_C["bg_table_header"]};
    color: {_C["text_primary"]};
    font-weight: bold;
    font-size: {_S["font_size_small"]}pt;
    padding: 6px 8px;
    border-bottom: 1px solid {_C["border"]};
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 2px;
    subcontrol-position: top right;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: {_C["bg_btn_hover"]};
    border-radius: {_S["border_radius"]}px;
}}
"""

    _QSS_MENU = _menu_qss()

    MASTER_STYLESHEET = (
    _QSS_DIALOG
    + _QSS_GROUPBOX
    + _QSS_TABLE
    + _QSS_INPUTS
    + _QSS_COMBOBOX
    + _QSS_TABLE_COMBOBOX
    + _QSS_LABEL
    + _QSS_CHECK_RADIO
    + _QSS_BUTTONS
    + _QSS_TABS
    + _QSS_TEXT_PROGRESS
    + _QSS_SCROLLBAR
)

    DOCK_STYLESHEET = MASTER_STYLESHEET + _QSS_DOCK + _QSS_MENU

def _init_theme():
    global _CURRENT_THEME, _GLASS_STRENGTH, _GLASS_TRANSPARENCY
    _CURRENT_THEME = _read_theme_pref()
    _GLASS_STRENGTH = _read_glass_pref()
    _GLASS_TRANSPARENCY = _read_glass_transparency_pref()
    COLORS.update(DARK_COLORS if _CURRENT_THEME == "Dark" else LIGHT_COLORS)
    _write_icons()
    _rebuild_stylesheets()

_init_theme()

def apply_dialog_style(dialog) -> None:
    """
    Call this once at the top of any dialog's __init__, before widget setup:

        apply_dialog_style(self)

    That's the only line needed. Then just tag buttons:

        btn.setObjectName("primary")    # blue filled
        btn.setObjectName("secondary")  # default — bordered, transparent
        btn.setObjectName("danger")     # red bordered

    For table item colors use the COLORS dict directly:

        from PyQt6.QtGui import QColor
        item.setForeground(QColor(COLORS["text_secondary"]))
    """
    dialog.setStyleSheet(MASTER_STYLESHEET)

def style_plot_axes(fig, ax) -> None:
    """
    Theme a matplotlib Figure/Axes with the current COLORS, so every plot in
    the app looks the same and follows Light/Dark. Call it right after
    ax.clear() (clear() resets the styling), then draw:

        ax.clear()
        style_plot_axes(self.figure, self.ax)
        ax.plot(x, y, color=COLORS["accent"], lw=2.2)

    Conventions used by the result dialogs: response curve = COLORS["accent"]
    at linewidth 2.2, zero lines = COLORS["text_secondary"] at 0.8, titles at
    fontsize 9, tick labels at 8.
    """
    fig.set_facecolor(COLORS["bg_panel"])
    ax.set_facecolor(COLORS["bg_input"])
    for sp in ax.spines.values():
        sp.set_color(COLORS["border"])
    ax.tick_params(colors=COLORS["text_secondary"], labelsize=8)
    ax.xaxis.label.set_color(COLORS["text_primary"])
    ax.yaxis.label.set_color(COLORS["text_primary"])
    ax.title.set_color(COLORS["text_primary"])
                                                              
    for axis in (ax.xaxis, ax.yaxis):
        fmt = axis.get_major_formatter()
        if hasattr(fmt, "set_useMathText"):                                          
            fmt.set_useMathText(True)
        axis.get_offset_text().set_color(COLORS["text_secondary"])
        axis.get_offset_text().set_fontsize(8)
    ax.grid(True, linestyle="-", linewidth=0.5, alpha=0.5, color=COLORS["border_light"])

_PLOT_COLORS = {
    "Light": {"reference": "#888888", "history": "#8494A8", "trail": "#2467BB",
              "marker": "#E47922", "vline": "#C0392B", "vertical": "#D62728"},
    "Dark":  {"reference": "#9A9A9A", "history": "#8AA0BA", "trail": "#5AA9FF",
              "marker": "#FFA040", "vline": "#FF6B5B", "vertical": "#FF6B6B"},
}

_CURVE_PALETTE = {
    "Light": ["#1f3d5c", "#b5451b", "#3f6b3f", "#7a4b8a",
              "#a68a2e", "#3a7a8c", "#8c3a5c", "#555555"],
    "Dark":  ["#6FA8DC", "#E8825A", "#7FC27F", "#B58AD0",
              "#D9BF5A", "#6DC0D4", "#D77BA0", "#BBBBBB"],
}

def plot_color(name) -> str:
    """Named plot colour for the active theme: reference, history, trail, marker, vline, vertical."""
    return _PLOT_COLORS[_CURRENT_THEME][name]

def curve_colors() -> list:
    """Palette for multi-curve plots in the active theme."""
    return list(_CURVE_PALETTE[_CURRENT_THEME])

def style_legend(legend):
    """Theme a matplotlib Legend (frame, border, text). Returns it for chaining:

        style_legend(ax.legend(loc="best", fontsize=8))
    """
    if legend is None:
        return legend
    frame = legend.get_frame()
    frame.set_facecolor(COLORS["bg_panel"])
    frame.set_edgecolor(COLORS["border"])
    frame.set_alpha(0.9)
    for t in legend.get_texts():
        t.set_color(COLORS["text_primary"])
    legend.get_title().set_color(COLORS["text_primary"])
    return legend

def section_map_palette() -> dict:
    """Colours for drawn cross-section maps (hinge dialog preview, hinge results map).
    fill is RGBA in 0..1."""
    if _CURRENT_THEME == "Dark":
        return dict(bg="#2b2b2b", text="#e6e6e6", axis="#ffffff", ring="#ffffff",
                    fill=(90 / 255, 90 / 255, 90 / 255, 160 / 255), outline="#070707")
    return dict(bg=COLORS["bg_input"], text=COLORS["text_secondary"], axis="#000000",
                ring=COLORS["text_primary"],
                fill=(190 / 255, 190 / 255, 190 / 255, 170 / 255), outline="#404040")

def style_pyqtgraph(plot_widget, legend=None) -> None:
    """pyqtgraph counterpart of style_plot_axes(): background, axes, tick/label text,
    grid and legend from the current COLORS. Safe to call again on theme change."""
    import pyqtgraph as pg
    plot_widget.setBackground(COLORS["bg_input"])
    for side in ("bottom", "left"):
        axis = plot_widget.getAxis(side)
        axis.setPen(pg.mkPen(COLORS["text_secondary"]))
        axis.setTextPen(pg.mkPen(COLORS["text_secondary"]))
        axis.setLabel(color=COLORS["text_primary"])
    if legend is not None:
        legend.setBrush(pg.mkBrush(QColor(_rgba(COLORS["bg_panel"], 220))))
        legend.setPen(pg.mkPen(COLORS["border"]))
        if hasattr(legend, "setLabelTextColor"):
            legend.setLabelTextColor(COLORS["text_primary"])

class PlotNavigator:
    """
    Zoom / pan for a matplotlib canvas, the same on every plot in the app.

        self.nav = PlotNavigator(self.canvas, self.ax)

      mouse wheel     zoom in / out about the cursor
      drag            pan (pan_buttons chooses which mouse buttons pan)
      double-click    back to the home view

    The dialog tells the navigator what "home" is by calling mark_home() right
    after it (re)draws and sets its limits. While `user_zoomed` is True the
    dialog must NOT re-apply its own limits (e.g. on every step of a slider),
    or it would throw the user's view away:

        if not self.nav.user_zoomed:
            ax.set_xlim(...); ax.set_ylim(...)
            self.nav.mark_home()
    """

    ZOOM_STEP = 1.2
    DRAG_PIXELS = 3                                                           

    def __init__(self, canvas, ax, pan_buttons=(1, 2, 3)):
        self.canvas = canvas
        self.ax = ax
        self.pan_buttons = tuple(pan_buttons)
        self.user_zoomed = False
        self._home = None
        self._drag = None
        canvas.mpl_connect("scroll_event", self._on_scroll)
        canvas.mpl_connect("button_press_event", self._on_press)
        canvas.mpl_connect("motion_notify_event", self._on_motion)
        canvas.mpl_connect("button_release_event", self._on_release)

    def mark_home(self):
        """Remember the current limits as the home view (and drop any user zoom)."""
        try:
            self.ax.apply_aspect()                                            
        except Exception:
            pass
        self._home = (tuple(self.ax.get_xlim()), tuple(self.ax.get_ylim()))
        self.user_zoomed = False

    def reset_view(self):
        if self._home is None:
            return
        self.ax.set_xlim(*self._home[0])
        self.ax.set_ylim(*self._home[1])
        self.user_zoomed = False
        self.canvas.draw_idle()

    def _on_scroll(self, ev):
        ax = self.ax
        if ev.inaxes is not ax or ev.xdata is None or ev.ydata is None:
            return
        up = (ev.step > 0) if getattr(ev, "step", 0) else (ev.button == "up")
        k = (1.0 / self.ZOOM_STEP) if up else self.ZOOM_STEP
        x, y = ev.xdata, ev.ydata
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        ax.set_xlim(x - (x - x0) * k, x + (x1 - x) * k)
        ax.set_ylim(y - (y - y0) * k, y + (y1 - y) * k)
        self.user_zoomed = True
        self.canvas.draw_idle()

    def _on_press(self, ev):
        if ev.inaxes is not self.ax or ev.x is None:
            return
        if ev.dblclick and int(ev.button) == 1:
            self.reset_view()
            return
        if int(ev.button) in self.pan_buttons:
            self._drag = {"px": (ev.x, ev.y), "xlim": self.ax.get_xlim(),
                          "ylim": self.ax.get_ylim(), "inv": self.ax.transData.inverted(),
                          "moved": False}

    def _on_motion(self, ev):
        d = self._drag
        if d is None or ev.x is None:
            return
        if not d["moved"] and abs(ev.x - d["px"][0]) + abs(ev.y - d["px"][1]) < self.DRAG_PIXELS:
            return
        d["moved"] = True
        p0 = d["inv"].transform(d["px"])
        p1 = d["inv"].transform((ev.x, ev.y))
        dx, dy = p0[0] - p1[0], p0[1] - p1[1]
        self.ax.set_xlim(d["xlim"][0] + dx, d["xlim"][1] + dx)
        self.ax.set_ylim(d["ylim"][0] + dy, d["ylim"][1] + dy)
        self.user_zoomed = True
        self.canvas.draw_idle()

    def _on_release(self, ev):
        self._drag = None

LINE_STYLES = {"Solid": "-", "Dashed": "--", "Dotted": ":", "Dash-dot": "-."}

from PyQt6.QtCore import pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QDoubleSpinBox, QComboBox, QLabel, QColorDialog,
)

class CurveStyleEditor(QWidget):
    """
    One row to edit how a plotted line is drawn: color, width, line style.

        self.style = CurveStyleEditor(default_width=2.2, default_style="-")
        self.style.set_values(color, width, style)
        color, width, style = self.style.values()

    color "" means Automatic -- the plot decides (e.g. COLORS["accent"] for the
    main curve, a palette for overlays). style is a matplotlib linestyle code
    ("-", "--", ":", "-."). Emits `changed` on any edit. The swatch is drawn as
    an icon, so there is no inline stylesheet.
    """
    changed = pyqtSignal()

    def __init__(self, parent=None, default_width=2.0, default_style="-"):
        super().__init__(parent)
        self._color = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        lay.addWidget(QLabel("Color"))
        self.btn_color = QPushButton()
        self.btn_color.setObjectName("secondary")
        self.btn_color.setFixedWidth(64)
        self.btn_color.setIconSize(QSize(36, 14))
        self.btn_color.setToolTip("Click to choose a color")
        self.btn_color.clicked.connect(self._pick)
        lay.addWidget(self.btn_color)
        self.btn_auto = QPushButton("Auto")
        self.btn_auto.setObjectName("secondary")
        self.btn_auto.setFixedWidth(56)
        self.btn_auto.setToolTip("Use the automatic color")
        self.btn_auto.clicked.connect(lambda: self.set_color(""))
        lay.addWidget(self.btn_auto)

        lay.addSpacing(8)
        lay.addWidget(QLabel("Width"))
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.3, 8.0)
        self.spin_width.setSingleStep(0.1)
        self.spin_width.setDecimals(1)
        self.spin_width.valueChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.spin_width)

        lay.addSpacing(8)
        lay.addWidget(QLabel("Line"))
        self.combo_style = QComboBox()
        self.combo_style.addItems(LINE_STYLES.keys())
        self.combo_style.currentIndexChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.combo_style)
        lay.addStretch(1)

        self.set_values("", default_width, default_style)

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color) if self._color else QColor(COLORS["accent"]),
                                  self, "Select Color")
        if c.isValid():
            self.set_color(c.name())

    def set_color(self, color):
        color = color if (color and QColor(color).isValid()) else ""
        self._color = color
        if color:
            pm = QPixmap(36, 14)
            pm.fill(QColor(color))
            p = QPainter(pm)
            p.setPen(QColor(COLORS["border"]))
            p.drawRect(0, 0, 35, 13)
            p.end()
            self.btn_color.setIcon(QIcon(pm))
            self.btn_color.setText("")
        else:
            self.btn_color.setIcon(QIcon())
            self.btn_color.setText("Auto")
        self.changed.emit()

    def set_values(self, color, width, style):
        self.set_color(color)
        self.spin_width.setValue(float(width))
        code_to_name = {v: k for k, v in LINE_STYLES.items()}
        self.combo_style.setCurrentText(code_to_name.get(style, "Solid"))

    def values(self):
        """-> (color or "", width, matplotlib linestyle code)"""
        return self._color, self.spin_width.value(), LINE_STYLES[self.combo_style.currentText()]

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPen

class RangeSlider(QWidget):
    """
    Two-handle slider over the integer range [minimum, maximum].

        s = RangeSlider(minimum=0, maximum=n - 1)
        s.setValues(lo, hi)            # programmatic, does not emit
        s.rangeChanged.connect(fn)     # fn(lo, hi) while the user drags
        lo, hi = s.values()

    Drag either handle, drag the bar BETWEEN the handles to slide the whole
    window (its width stays the same), or click the groove to jump the nearest
    handle. With the handles at both ends the full range is selected.
    """
    rangeChanged = pyqtSignal(int, int)
    _HW = 10                                                         

    def __init__(self, parent=None, minimum=0, maximum=100):
        super().__init__(parent)
        self._min, self._max = int(minimum), int(maximum)
        self._lo, self._hi = self._min, self._max
        self._drag = None                                                                            
        self.setMinimumHeight(26)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)

    def setBounds(self, minimum, maximum):
        self._min, self._max = int(minimum), int(maximum)
        self._lo = max(self._min, min(self._lo, self._max))
        self._hi = max(self._lo, min(self._hi, self._max))
        self.update()

    def setValues(self, lo, hi, emit=False):
        lo = max(self._min, min(int(lo), self._max))
        hi = max(lo, min(int(hi), self._max))
        changed = (lo, hi) != (self._lo, self._hi)
        self._lo, self._hi = lo, hi
        self.update()
        if emit and changed:
            self.rangeChanged.emit(lo, hi)

    def values(self):
        return self._lo, self._hi

    def _pad(self):
        return self._HW / 2.0 + 2

    def _x(self, v):
        span = max(1, self._max - self._min)
        return self._pad() + (v - self._min) / span * max(1.0, self.width() - 2 * self._pad())

    def _val(self, x):
        span = max(1, self._max - self._min)
        f = (x - self._pad()) / max(1.0, self.width() - 2 * self._pad())
        return max(self._min, min(self._max, int(round(self._min + f * span))))

    def _hit(self, x):
        xl, xh = self._x(self._lo), self._x(self._hi)
        near_l, near_h = abs(x - xl) <= self._HW, abs(x - xh) <= self._HW
        if near_l and near_h:
            return ("lo", 0) if x < xl or (x == xl and self._lo == self._min) else ("hi", 0)
        if near_l:
            return ("lo", 0)
        if near_h:
            return ("hi", 0)
        if xl < x < xh:
            return ("span", self._val(x) - self._lo)
        return ("lo", 0) if abs(x - xl) <= abs(x - xh) else ("hi", 0)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2.0
        xl, xh = self._x(self._lo), self._x(self._hi)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(COLORS["border"]))
        p.drawRoundedRect(QRectF(self._pad(), cy - 3, self.width() - 2 * self._pad(), 6), 3, 3)
        p.setBrush(QColor(COLORS["accent"]))
        p.drawRoundedRect(QRectF(xl, cy - 3, max(xh - xl, 0.0), 6), 3, 3)
        p.setBrush(QColor(COLORS["bg_panel"]))
        p.setPen(QPen(QColor(COLORS["accent"]), 2))
        for x in (xl, xh):
            p.drawRoundedRect(QRectF(x - self._HW / 2.0, cy - 9, self._HW, 18), 3, 3)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = self._hit(ev.position().x())
            self._apply(ev.position().x())

    def mouseMoveEvent(self, ev):
        x = ev.position().x()
        if self._drag is not None:
            self._apply(x)
            return
        kind = self._hit(x)[0]
        near = (abs(x - self._x(self._lo)) <= self._HW) or (abs(x - self._x(self._hi)) <= self._HW)
        self.setCursor(Qt.CursorShape.SizeHorCursor if near else
                       (Qt.CursorShape.SizeAllCursor if kind == "span" and self._x(self._lo) < x < self._x(self._hi)
                        else Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def _apply(self, x):
        if self._drag is None:
            return
        kind, grab = self._drag
        v = self._val(x)
        lo, hi = self._lo, self._hi
        if kind == "lo":
            lo = min(v, hi)
        elif kind == "hi":
            hi = max(v, lo)
        else:
            width = hi - lo
            lo = max(self._min, min(v - grab, self._max - width))
            hi = lo + width
        self.setValues(lo, hi, emit=True)

def apply_dock_style(dock) -> None:
    """
    Call once in a QDockWidget's __init__, after its child widgets are
    built:

        apply_dock_style(self)

    Styles the dock's own title bar plus every themed child widget
    inside it (QTreeWidget/QListWidget, QLineEdit, QPushButton, QMenu,
    scrollbars) so the panel reads as part of the app instead of a
    stock, unstyled Qt widget bolted on the side.
    """
    dock.setStyleSheet(DOCK_STYLESHEET)
