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

CHANGING THE LOOK LATER
------------------------
Edit the values below — every dialog updates automatically.
Never define inline stylesheets inside dialog files.
"""

import os as _os

_THEME_DIR  = _os.path.dirname(_os.path.abspath(__file__))
_ARROW_UP   = _os.path.join(_THEME_DIR, "_arrow_up.svg").replace("\\", "/")
_ARROW_DOWN = _os.path.join(_THEME_DIR, "_arrow_down.svg").replace("\\", "/")

_SVG_UP   = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><polygon points="3,0 6,4 0,4" fill="#555555"/></svg>'
_SVG_DOWN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 4"><polygon points="0,0 6,0 3,4" fill="#555555"/></svg>'

for _path, _svg in ((_ARROW_UP, _SVG_UP), (_ARROW_DOWN, _SVG_DOWN)):
    if not _os.path.exists(_path):
        with open(_path, "w") as _f:
            _f.write(_svg)

COLORS = {
                          
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

    "border_radius":        3,          
    "groupbox_margin_top":  10,                                
    "groupbox_padding_top": 6,                              
    "groupbox_title_left":  8,          

    "section_spacing":      10,                                   
    "row_height":           24,                      
}

_C = COLORS
_S = SIZES

_QSS_DIALOG = f"""
QDialog {{
    background-color: {_C["bg_dialog"]};
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
    background-color: {_C["bg_panel"]};
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
QTableWidget {{
    background-color: {_C["bg_panel"]};
    alternate-background-color: {_C["bg_table_alt"]};
    gridline-color: {_C["border"]};
    selection-background-color: {_C["selection_bg"]};
    selection-color: {_C["selection_text"]};
    border: 1px solid {_C["border"]};
    font-size: {_S["font_size_normal"]}pt;
}}
QTableWidget::item {{
    padding: 2px 6px;
    min-height: {_S["row_height"]}px;
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
"""

_QSS_INPUTS = f"""
QLineEdit,
QSpinBox,
QDoubleSpinBox {{
    background-color: {_C["bg_input"]};
    color: {_C["text_primary"]};
    border: 1px solid {_C["border"]};
    border-radius: {_S["border_radius"]}px;
    padding: {_S["input_padding"]};
    min-height: {_S["input_height"]}px;
    font-size: {_S["font_size_normal"]}pt;
}}
QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {{
    border-color: {_C["border_focus"]};
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
    background-color: {_C["bg_input"]};
    color: {_C["text_primary"]};
    border: 1px solid {_C["border"]};
    border-radius: {_S["border_radius"]}px;
    padding: {_S["input_padding"]};
    padding-right: 20px;
    min-height: {_S["input_height"]}px;
    font-size: {_S["font_size_normal"]}pt;
}}
QComboBox:hover {{
    border-color: #AAAAAA;
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
    background-color: {_C["bg_panel"]};
    border: 1px solid {_C["border"]};
    selection-background-color: {_C["selection_bg"]};
    selection-color: {_C["selection_text"]};
    outline: none;
    font-size: {_S["font_size_normal"]}pt;
}}
"""

_QSS_TABLE_COMBOBOX = f"""
QTableWidget QComboBox {{
    border: none;
    border-radius: 0px;
    background-color: transparent;
    padding: 1px 4px;
    min-height: 0px;
    font-size: {_S["font_size_normal"]}pt;
    color: {_C["text_primary"]};
}}
QTableWidget QComboBox:hover {{
    background-color: {_C["selection_bg"]};
}}
QTableWidget QComboBox:focus {{
    border: 1px solid {_C["border_focus"]};
    border-radius: {_S["border_radius"]}px;
    background-color: {_C["bg_input"]};
}}
QTableWidget QComboBox QAbstractItemView {{
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
"""

_QSS_CHECK_RADIO = f"""
QCheckBox,
QRadioButton {{
    color: {_C["text_primary"]};
    font-size: {_S["font_size_normal"]}pt;
    spacing: 6px;
}}
QCheckBox:disabled,
QRadioButton:disabled {{
    color: {_C["text_disabled"]};
}}
"""

_QSS_BUTTONS = f"""
QPushButton {{
    background-color: transparent;
    color: {_C["text_primary"]};
    border: 1px solid {_C["border"]};
    border-radius: {_S["border_radius"]}px;
    padding: {_S["btn_padding"]};
    min-width: {_S["btn_min_width"]}px;
    min-height: {_S["btn_height"]}px;
    font-size: {_S["font_size_normal"]}pt;
}}
QPushButton:hover {{
    background-color: {_C["bg_btn_hover"]};
    border-color: #AAAAAA;
}}
QPushButton:pressed {{
    background-color: {_C["bg_btn_pressed"]};
}}
QPushButton:disabled {{
    color: {_C["text_disabled"]};
    border-color: {_C["border_light"]};
    background-color: transparent;
}}

QPushButton#primary {{
    background-color: {_C["accent"]};
    color: {_C["text_on_accent"]};
    border: none;
    font-weight: bold;
}}
QPushButton#primary:hover {{
    background-color: {_C["accent_hover"]};
}}
QPushButton#primary:pressed {{
    background-color: {_C["accent_pressed"]};
}}
QPushButton#primary:disabled {{
    background-color: {_C["text_disabled"]};
    color: white;
}}

QPushButton#danger {{
    background-color: transparent;
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
    background: #AAAAAA;
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
    background: #AAAAAA;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""

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
    + _QSS_SCROLLBAR
)

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
