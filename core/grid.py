"""
Grid data + appearance for OpenCivil.

APPEARANCE (GridLines.style)
----------------------------
A small dict saved with the model (see model.py). `preset` picks a built-in
palette; "Auto" follows the canvas background (light lines on a dark canvas,
dark lines on a light one). "Custom" uses the values in style["custom"].
resolve_grid_style() turns the stored dict + the canvas brightness into the
final colours / opacities the canvas draws with.
"""

GRID_PRESETS = ["Auto", "High Contrast", "Classic", "Blueprint", "Custom"]

COLOR_KEYS = ("line", "active", "floor", "floor_major", "dim", "bub_circle", "bub_line", "bub_text")
ALPHA_KEYS = ("a_line", "a_line_2d", "a_active", "a_floor", "a_major", "a_dim")

def _pal(line, a_line, a_line_2d, active, a_active, floor, a_floor, major, a_major, dim, a_dim,
         bc="#4D99E6", bl="#4D99E6", bt="#2673D9"):
    """bc / bl / bt = bubble circle, bubble extension (tail) line, bubble ID text colour."""
    return dict(line=line, a_line=a_line, a_line_2d=a_line_2d,
                active=active, a_active=a_active,
                floor=floor, a_floor=a_floor,
                floor_major=major, a_major=a_major,
                dim=dim, a_dim=a_dim,
                bub_circle=bc, bub_line=bl, bub_text=bt)

_CLASSIC = _pal("#999999", 0.50, 0.15, "#666666", 0.80, "#B3B3B3", 0.25, "#B3B3B3", 0.25, "#4D80B3", 0.80)
_PRESET_TABLE = {
    ("Auto", True):           _pal("#9AA4AF", 0.55, 0.30, "#E8EDF2", 0.95, "#8E98A3", 0.28, "#B4BDC6", 0.55, "#6FB1F0", 0.90, bt="#6CB4FF"),
    ("Auto", False):          _pal("#565C63", 0.55, 0.30, "#1B1F23", 0.95, "#6A7077", 0.25, "#3A3F45", 0.50, "#1F6FBF", 0.90),
    ("High Contrast", True):  _pal("#C9D1D9", 0.75, 0.45, "#FFFFFF", 1.00, "#AAB4BE", 0.45, "#E0E6EB", 0.75, "#8CC8FF", 1.00, "#8CC8FF", "#8CC8FF", "#FFFFFF"),
    ("High Contrast", False): _pal("#30353B", 0.80, 0.45, "#000000", 1.00, "#4A5057", 0.40, "#1B1F23", 0.70, "#0B5CAD", 1.00, "#0B5CAD", "#0B5CAD", "#000000"),
    ("Classic", True):        _CLASSIC,
    ("Classic", False):       _CLASSIC,
    ("Blueprint", True):      _pal("#4C8BF5", 0.55, 0.30, "#BBD7FF", 0.95, "#3F6FBF", 0.30, "#6FA0F5", 0.55, "#9CC4FF", 0.90, "#6FA0F5", "#6FA0F5", "#BBD7FF"),
    ("Blueprint", False):     _pal("#2F5FA8", 0.60, 0.30, "#0B2E6B", 0.95, "#5A82C4", 0.28, "#2F5FA8", 0.50, "#0B4DA8", 0.90, "#2F5FA8", "#2F5FA8", "#0B2E6B"),
}

def default_grid_style():
    return {
        "preset": "Auto",
        "custom": {},                                                 
        "show_floor": True,                                           
        "floor_spacing": 0.0,                                     
        "floor_major_every": 5,                                                     
        "width_lines": 1.5,                                                         
        "width_floor": 1.0,                        
    }

def _clamp01(v, fallback):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return fallback

def resolve_grid_style(style, dark):
    """Stored style dict + 'is the canvas dark' -> the final values to draw with."""
    s = default_grid_style()
    if isinstance(style, dict):
        s.update({k: v for k, v in style.items() if k in s})
    preset = s["preset"] if s["preset"] in GRID_PRESETS else "Auto"
    base = _PRESET_TABLE[("Auto", bool(dark))]
    if preset == "Custom":
        pal = dict(base)
        custom = s.get("custom") or {}
        pal.update({k: v for k, v in custom.items() if k in base})
    else:
        pal = dict(_PRESET_TABLE.get((preset, bool(dark)), base))
    for k in ALPHA_KEYS:
        pal[k] = _clamp01(pal[k], base[k])
    out = dict(pal)
    out["preset"] = preset
    out["show_floor"] = bool(s["show_floor"])
    out["floor_spacing"] = max(0.0, float(s["floor_spacing"] or 0.0))
    out["floor_major_every"] = max(0, int(s["floor_major_every"] or 0))
    out["width_lines"] = max(0.5, float(s["width_lines"] or 1.5))
    out["width_floor"] = max(0.5, float(s["width_floor"] or 1.0))
    return out

def hex_to_rgba(hex_color, alpha=1.0):
    h = str(hex_color).lstrip("#")
    if len(h) != 6:
        h = "999999"
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0, float(alpha))

class GridLines:
    def __init__(self):
                                         
        self.x_lines = []
        self.y_lines = []
        self.z_lines = []
        self.bubble_size = 1.25
        self.bubble_alpha = 1.0
                                                                          
        self.bubble_line_width = 1.5
        self.bubble_extension = self.bubble_size * 2.5
                                                                          
        self.bubble_ext_line_width = None
                                                                               
        self.style = default_grid_style()

    def set_style(self, style):
        """Load a (possibly partial / old) style dict, keeping defaults for anything missing."""
        merged = default_grid_style()
        if isinstance(style, dict):
            merged.update({k: v for k, v in style.items() if k in merged})
        if not isinstance(merged.get("custom"), dict):
            merged["custom"] = {}
        self.style = merged

    def resolved_style(self, dark):
        return resolve_grid_style(getattr(self, "style", None), dark)

    @property
    def x_grids(self):
        return sorted([line['ord'] for line in self.x_lines])
    
    @x_grids.setter
    def x_grids(self, values):
                                                                                      
        self.x_lines = [{'id': str(i+1), 'ord': v, 'visible': True, 'bubble': 'Start'} 
                        for i, v in enumerate(sorted(values))]

    @property
    def y_grids(self):
        return sorted([line['ord'] for line in self.y_lines])

    @y_grids.setter
    def y_grids(self, values):
        self.y_lines = [{'id': str(i+1), 'ord': v, 'visible': True, 'bubble': 'Start'} 
                        for i, v in enumerate(sorted(values))]

    @property
    def z_grids(self):
        return sorted([line['ord'] for line in self.z_lines])

    @z_grids.setter
    def z_grids(self, values):
        self.z_lines = [{'id': f"Z{i+1}", 'ord': v, 'visible': True, 'bubble': 'Start'} 
                        for i, v in enumerate(sorted(values))]

    def create_uniform(self, axis, start, num, spacing):
        """Helper to create grids quickly"""
        vals = [start + i*spacing for i in range(num + 1)]
        if axis == 'x': self.x_grids = vals
        elif axis == 'y': self.y_grids = vals
        elif axis == 'z': self.z_grids = vals
