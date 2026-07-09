from dataclasses import dataclass
import math

@dataclass
class Material:
    """Structural Material definition."""
    name: str
    E: float                                                 
    nu: float                        
    density: float                         
    mat_type: str                        
    fy: float = 0.0                  
    fu: float = 0.0                     

    @property
    def G(self):
        return self.E / (2 * (1 + self.nu))

class Section:
    """Base class for cross-sections."""
    
    def __init__(self, name, material: Material, color=None):
        self.name = name
        self.material = material
        self.color = color if color else (0.75, 0.75, 0.75, 1.0)
        
        self.A = 0.0
        self.J = 0.0
        self.I33 = 0.0                      
        self.I22 = 0.0                      
        self.Asy = 0.0                      
        self.Asz = 0.0                      
        
        self.S33 = 0.0; self.S22 = 0.0
        self.Z33 = 0.0; self.Z22 = 0.0
        self.r33 = 0.0; self.r22 = 0.0

        self.modifiers = {
            "A": 1.0,    "As2": 1.0, "As3": 1.0, "J": 1.0,
            "I2": 1.0,   "I3": 1.0,  "Mass": 1.0, "Weight": 1.0
        }

    def get_insertion_point_shift(self, cardinal_point):
        return 0.0, 0.0

    def get_shape_coords(self):
        """Override in subclasses. Returns list of (y, z) tuples, centroid-centered."""
        return []

    def get_bbox_offsets(self):
        """
        Returns (y_left, y_right, z_bot, z_top) — all positive distances
        from the centroid to each edge in local 2-3 coords.
        Derived from get_shape_coords(), which must be centroid-centered.
        Used by get_cardinal_offsets() in FrameElement.
        """
        coords = self.get_shape_coords()
        if not coords:
            return 0.0, 0.0, 0.0, 0.0
        ys = [p[0] for p in coords]
        zs = [p[1] for p in coords]
        return -min(ys), max(ys), -min(zs), max(zs)

    def __repr__(self):
        return f"Section({self.name})"
    
class RectangularSection(Section):
    def __init__(self, name, material: Material, b, h):
        super().__init__(name, material)
        self.b = float(b)
        self.h = float(h)
        self._calculate_properties()
    
    def get_shape_coords(self):
        """Returns list of (y, z) tuples for the perimeter in local coords."""
        dy = self.b / 2
        dz = self.h / 2
        return [
            (dy, dz),              
            (-dy, dz),            
            (-dy, -dz),           
            (dy, -dz)              
        ]

    def _calculate_properties(self):
        b, h = self.b, self.h
        self.A = b * h
        if self.A == 0: return
        
        self.Asy = (5/6) * self.A 
        self.Asz = (5/6) * self.A 

        self.I33 = (h * b**3) / 12 
        self.I22 = (b * h**3) / 12

        long = max(b, h)
        short = min(b, h)
        ratio = short / long
        factor = (1.0 / 3.0) - 0.21 * ratio * (1.0 - (ratio**4) / 12.0)
        self.J = factor * long * (short**3) 
        
        self.S33 = self.I33 / (h / 2)
        self.S22 = self.I22 / (b / 2)
        self.Z33 = (b * h**2) / 4
        self.Z22 = (h * b**2) / 4
        self.r33 = math.sqrt(self.I33 / self.A)
        self.r22 = math.sqrt(self.I22 / self.A)

class ISection(Section):
    def __init__(self, name, material: Material, h, w_top, t_top, w_bot, t_bot, t_web, props=None):
        super().__init__(name, material)
        self.h = float(h); self.w_top = float(w_top); self.t_top = float(t_top)
        self.w_bot = float(w_bot); self.t_bot = float(t_bot); self.t_web = float(t_web)
        
        self._calculate_centroid()

        if props:
            self._set_exact_properties(props)
        else:
            self._calculate_properties()

    def _calculate_centroid(self):
        """Calculates y_bar (distance from bottom to centroid) for VISUALS."""
        H = self.h
        B_t, T_t = self.w_top, self.t_top
        B_b, T_b = self.w_bot, self.t_bot
        t_w = self.t_web
        h_web = H - T_t - T_b
        
        A_top = B_t * T_t
        A_bot = B_b * T_b
        A_web = h_web * t_w
        total_area = A_top + A_bot + A_web
        
        if total_area == 0:
            self.y_bar = H / 2
        else:
            y_bot_c = T_b / 2
            y_web_c = T_b + h_web / 2
            y_top_c = H - T_t / 2
            self.y_bar = (A_bot*y_bot_c + A_web*y_web_c + A_top*y_top_c) / total_area

    def _set_exact_properties(self, p):
        """Uses exact values from AISC/SAP table."""
        self.A = float(p.get('A', 0.0))
        self.J = float(p.get('J', 0.0))
        self.I22 = float(p.get('I22', 0.0)) 
        self.I33 = float(p.get('I33', 0.0))
        self.Asy = float(p.get('As2', 0.0))
        self.Asz = float(p.get('As3', 0.0))
        
        self.S33 = float(p.get('S33', 0.0))
        self.S22 = float(p.get('S22', 0.0))
        self.Z33 = float(p.get('Z33', 0.0))
        self.Z22 = float(p.get('Z22', 0.0))
        self.r33 = float(p.get('r33', 0.0))
        self.r22 = float(p.get('r22', 0.0))

    def get_shape_coords(self):
        """Returns 12 points defining the I-Beam perimeter."""
                                               
        if not hasattr(self, 'y_bar'): self._calculate_centroid()

        H = self.h
        W_top = self.w_top
        W_bot = self.w_bot
        t_top = self.t_top
        t_bot = self.t_bot
        t_web = self.t_web
        
        y_top = H - self.y_bar   
        y_bot = -self.y_bar  
        
        tr_x = W_top / 2; tl_x = -W_top / 2
        br_x = W_bot / 2; bl_x = -W_bot / 2
        wr_x = t_web / 2; wl_x = -t_web / 2
        y_web_top = y_top - t_top
        y_web_bot = y_bot + t_bot
        
        return [
            (tr_x, y_top),      (tl_x, y_top),                      
            (tl_x, y_web_top),  (wl_x, y_web_top),                         
            (wl_x, y_web_bot),  (bl_x, y_web_bot),                         
            (bl_x, y_bot),      (br_x, y_bot),                      
            (br_x, y_web_bot),  (wr_x, y_web_bot),                         
            (wr_x, y_web_top),  (tr_x, y_web_top)                          
        ]
    
    def _calculate_properties(self):
        """Fallback calculation if no exact props provided."""
        H = self.h
        B_t, T_t = self.w_top, self.t_top
        B_b, T_b = self.w_bot, self.t_bot
        t_w = self.t_web
        h_web = H - T_t - T_b
        
        A_top = B_t * T_t
        A_bot = B_b * T_b
        A_web = h_web * t_w
        self.A = A_top + A_bot + A_web
        
        if self.A == 0: return

        y_bot_c = T_b / 2
        y_web_c = T_b + h_web / 2
        y_top_c = H - T_t / 2
        self.y_bar = (A_bot*y_bot_c + A_web*y_web_c + A_top*y_top_c) / self.A
        
        I2_bot = (B_b * T_b**3)/12 + A_bot*(y_bot_c - self.y_bar)**2
        I2_web = (t_w * h_web**3)/12 + A_web*(y_web_c - self.y_bar)**2
        I2_top = (B_t * T_t**3)/12 + A_top*(y_top_c - self.y_bar)**2
        self.I22 = I2_bot + I2_web + I2_top

        I3_bot = (T_b * B_b**3)/12
        I3_web = (h_web * t_w**3)/12
        I3_top = (T_t * B_t**3)/12
        self.I33 = I3_bot + I3_web + I3_top

        self.Asy = B_t * T_t + B_b * T_b 
        self.Asz = h_web * self.t_web 

        self.J = (1/3) * (B_b * T_b**3 + h_web * t_w**3 + B_t * T_t**3)

        c_top = H - self.y_bar; c_bot = self.y_bar
        self.S33 = self.I33 / max(c_top, c_bot)
        max_width = max(B_t, B_b)
        self.S22 = self.I22 / (max_width / 2)
        
        self.Z33 = max_width * T_t * (H - T_t) + t_w * (h_web**2) / 4
        self.Z22 = (2 * T_t * B_t**2) / 4 + (h_web * t_w**2) / 4

        self.r33 = math.sqrt(self.I33 / self.A)
        self.r22 = math.sqrt(self.I22 / self.A)

class CircularSection(Section):
    def __init__(self, name, material: Material, d):
        super().__init__(name, material)
        self.d = float(d)
        self._calculate_properties()

    def _calculate_properties(self):
        d = self.d
        if d == 0: return
        
        self.A = math.pi * d**2 / 4
        self.I33 = math.pi * d**4 / 64
        self.I22 = self.I33
        self.J = math.pi * d**4 / 32
        
        self.Asy = 0.9 * self.A
        self.Asz = 0.9 * self.A
        
        self.S33 = self.I33 / (d / 2)
        self.S22 = self.S33
        self.Z33 = d**3 / 6
        self.Z22 = self.Z33
        self.r33 = math.sqrt(self.I33 / self.A)
        self.r22 = self.r33

    def get_shape_coords(self):
        """Generates a 16-sided polygon to approximate the circle in 3D."""
        pts = []
        segments = 32
        for i in range(segments):
            theta = 2.0 * math.pi * i / segments
            pts.append(( (self.d/2)*math.cos(theta), (self.d/2)*math.sin(theta) ))
        return pts

class PipeSection(Section):
    def __init__(self, name, material: Material, d, t):
        super().__init__(name, material)
        self.d = float(d)
        self.t = float(t)
        self._calculate_properties()

    def _calculate_properties(self):
        d, t = self.d, self.t
        d_in = max(0, d - 2*t)
        if d == 0: return
        
        self.A = (math.pi / 4) * (d**2 - d_in**2)
        if self.A == 0: return
        
        self.I33 = (math.pi / 64) * (d**4 - d_in**4)
        self.I22 = self.I33
        self.J = (math.pi / 32) * (d**4 - d_in**4)
        
        self.Asy = self.A / 2.0
        self.Asz = self.A / 2.0
        
        self.S33 = self.I33 / (d / 2)
        self.S22 = self.S33
        self.Z33 = (d**3 - d_in**3) / 6
        self.Z22 = self.Z33
        self.r33 = math.sqrt(self.I33 / self.A)
        self.r22 = self.r33

    def get_shape_coords(self):
        """Draws outer circle, cuts inward, and draws inner circle backward to create a hollow extrusion."""
        pts = []
        segments = 32
        d_in = self.d - 2*self.t
        
        for i in range(segments + 1):
            theta = 2.0 * math.pi * i / segments
            pts.append(( (self.d/2)*math.cos(theta), (self.d/2)*math.sin(theta) ))
            
        for i in range(segments, -1, -1):
            theta = 2.0 * math.pi * i / segments
            pts.append(( (d_in/2)*math.cos(theta), (d_in/2)*math.sin(theta) ))
        return pts

class TubeSection(Section):
    def __init__(self, name, material: Material, d, b, tf, tw):
        super().__init__(name, material)
        self.d = float(d)
        self.b = float(b)
        self.tf = float(tf)
        self.tw = float(tw)
        self._calculate_properties()

    def _calculate_properties(self):
        d, b, tf, tw = self.d, self.b, self.tf, self.tw
        h_in = max(0, d - 2*tf)
        b_in = max(0, b - 2*tw)
        
        self.A = b*d - b_in*h_in
        if self.A == 0: return
        
        self.I22 = (b * d**3)/12 - (b_in * h_in**3)/12
        self.I33 = (d * b**3)/12 - (h_in * b_in**3)/12
        
        Am = (b - tw) * (d - tf)
        perimeter_integral = 2*(b - tw)/tf + 2*(d - tf)/tw
        if perimeter_integral > 0:
            self.J = (4 * Am**2) / perimeter_integral
        else:
            self.J = 0.0
            
        self.Asy = 2 * b * tf
        self.Asz = 2 * d * tw
        
        self.S33 = self.I33 / (d / 2)
        self.S22 = self.I22 / (b / 2)
        self.Z33 = (b * d**2)/4 - (b_in * h_in**2)/4
        self.Z22 = (d * b**2)/4 - (h_in * b_in**2)/4
        self.r33 = math.sqrt(self.I33 / self.A)
        self.r22 = math.sqrt(self.I22 / self.A)

    def get_shape_coords(self):
        """Draws outer box, cuts inward, and draws inner box backward to create a hollow extrusion."""
        d_out, b_out = self.d/2, self.b/2
        d_in, b_in = d_out - self.tf, b_out - self.tw
        
        return [
            (b_out, d_out), (-b_out, d_out), (-b_out, -d_out), (b_out, -d_out), (b_out, d_out),        
            (b_in, d_in), (b_in, -d_in), (-b_in, -d_in), (-b_in, d_in), (b_in, d_in)                  
        ]

class TrapezoidalSection(Section):
    def __init__(self, name, material: Material, d, w_top, w_bot):
        super().__init__(name, material)
        self.d = float(d)
        self.w_top = float(w_top)
        self.w_bot = float(w_bot)
        self._calculate_properties()

    def _calculate_properties(self):
        d, a, b = self.d, self.w_top, self.w_bot
        self.A = (a + b) * d / 2
        if self.A == 0: return
        
        self.y_bar = (d / 3) * (2*a + b) / (a + b)
        
        self.I22 = (d**3 / 36) * (a**2 + 4*a*b + b**2) / (a + b)
        self.I33 = (d / 48) * (a + b) * (a**2 + b**2)
        
        w_avg = (a + b) / 2.0
        h_eff = max(d, w_avg)
        t_eff = min(d, w_avg)
        roark_factor = (1.0 / 3.0) - 0.21 * (t_eff / h_eff) * (1.0 - (t_eff**4) / (12.0 * h_eff**4))
        self.J = roark_factor * h_eff * (t_eff**3)
        
        taper_ratio = min(a, b) / max(a, b)
        
        factor_z = 0.83333 + 0.035 * (1.0 - taper_ratio) - 0.008 * (1.0 - taper_ratio)**2
        self.Asz = factor_z * self.A
        
        factor_y = 0.83333 + 0.155 * (1.0 - taper_ratio) - 0.025 * (1.0 - taper_ratio)**2
        self.Asy = factor_y * self.A
        
        c_top = d - self.y_bar
        c_bot = self.y_bar
        self.S33 = self.I33 / max(c_top, c_bot)
        self.S22 = self.I22 / (max(a, b) / 2)
        
        self.Z33 = 0.0                                      
        self.Z22 = 0.0
        self.r33 = math.sqrt(self.I33 / self.A)
        self.r22 = math.sqrt(self.I22 / self.A)

    def get_shape_coords(self):
        y_top = self.d - self.y_bar
        y_bot = -self.y_bar
        return [
            (self.w_top/2, y_top),
            (-self.w_top/2, y_top),
            (-self.w_bot/2, y_bot),
            (self.w_bot/2, y_bot)
        ]

class GeneralSection(Section):
    def __init__(self, name, material, props_dict, color=None):
        super().__init__(name, material, color)
                                                     
        self.A = float(props_dict.get('A', 0.0))
        self.J = float(props_dict.get('J', 0.0))
        self.I33 = float(props_dict.get('I33', 0.0))
        self.I22 = float(props_dict.get('I22', 0.0))
        
        self.Asy = float(props_dict.get('As2', props_dict.get('Asy', 0.0)))
        self.Asz = float(props_dict.get('As3', props_dict.get('Asz', 0.0)))
        
        self.S33 = 0.0; self.S22 = 0.0; self.Z33 = 0.0; self.Z22 = 0.0
        self.r33 = 0.0; self.r22 = 0.0

    def get_shape_coords(self):
        """Returns empty list so no 3D extrusion is drawn."""
        return []

    def get_insertion_point_shift(self, cardinal_point):
        return 0.0, 0.0

class ArbitrarySection(GeneralSection):
    """
    A user-drawn arbitrary polygon section.
    Stores the original vertices so the Section Designer can re-open
    and edit them. Props are computed by SectionAnalyzer and passed in
    as a dict — same contract as GeneralSection.
    Inherits get_insertion_point_shift from GeneralSection (returns 0,0).
    """

    def __init__(self, name, material, vertices, props_dict, color=None):
        """
        Parameters
        ----------
        vertices : list of (y, z) tuples in base SI units (metres).
                   Same coordinate convention as every other get_shape_coords().
        props_dict : dict with keys A, J, I33, I22, Asy, Asz, y_c, z_c
                     (all in base SI — metres / Newtons).
        """
        super().__init__(name, material, props_dict, color)
        self.vertices = list(vertices)
                                                                                      
        self._y_c = float(props_dict.get('y_c', 0.0))
        self._z_c = float(props_dict.get('z_c', 0.0))

    def get_shape_coords(self):
        """
        Return the drawn polygon shifted to centroid-centered coords.
        This keeps the same contract as all other Section types, so
        get_bbox_offsets() and the 3D extrusion work correctly.
        """
        return [(y - self._y_c, z - self._z_c) for y, z in self.vertices]

class AreaSection:
    """
    Base class for 2D area element sections (Shell, Plane, Asolid).
    Intentionally separate from the frame Section class — area sections
    have no A, I33, J etc.  Stored in model.area_sections (not model.sections).
    """
    section_category = "area"

    def __init__(self, name, material, material_angle=0.0, display_color="#FF00FF"):
        self.name            = str(name)
        self.material        = material                                   
        self.material_angle  = float(material_angle)
        self.display_color   = display_color or "#FF00FF"
                                                                                  
        self.stiffness_modifiers = {
            "f11": 1.0, "f22": 1.0, "f12": 1.0,
            "m11": 1.0, "m22": 1.0, "m12": 1.0,
            "v13": 1.0, "v23": 1.0,
            "mass": 1.0, "weight": 1.0,
        }

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name})"

class ShellSection(AreaSection):
    """
    Shell / Plate / Membrane area section.
    Covers all six SAP2000 shell types, plus TS 500 Code-Based "Ghost" slabs.
    """
    TYPES = [
        "Shell - Thin",
        "Shell - Thick",
        "Plate - Thin",
        "Plate Thick",
        "Membrane",
        "Shell - Layered/Nonlinear",
    ]

    def __init__(self, name, material,
                 shell_type="Shell - Thin",
                 membrane_thickness=0.1,
                 bending_thickness=0.1,
                 material_angle=0.0,
                 display_color="#FF00FF"):
        super().__init__(name, material, material_angle, display_color)
        self.shell_type         = shell_type
        self.membrane_thickness = float(membrane_thickness)
        self.bending_thickness  = float(bending_thickness)
        
        self.modeling_type      = "True FEM (Shell)"
        
class PlaneSection(AreaSection):
    """
    2-D Plane-Stress or Plane-Strain section.
    No stiffness computation yet — placeholder.
    """
    def __init__(self, name, material,
                 plane_type="Plane-Stress",
                 incompatible_modes=True,
                 thickness=0.1,
                 material_angle=0.0,
                 display_color="#FF00FF"):
        super().__init__(name, material, material_angle, display_color)
        self.plane_type         = plane_type                                           
        self.incompatible_modes = bool(incompatible_modes)
        self.thickness          = float(thickness)

class AsolidSection(AreaSection):
    """
    Axisymmetric Solid (Asolid) section.
    arc_degrees=0 means 1 radian — SAP2000 convention.
    No stiffness computation yet — placeholder.
    """
    def __init__(self, name, material,
                 incompatible_modes=True,
                 coord_system="GLOBAL",
                 arc_degrees=0.0,
                 material_angle=0.0,
                 display_color="#FFFF00"):
        super().__init__(name, material, material_angle, display_color)
        self.incompatible_modes = bool(incompatible_modes)
        self.coord_system       = str(coord_system)
        self.arc_degrees        = float(arc_degrees)
