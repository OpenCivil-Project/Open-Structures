from dataclasses import dataclass, field
import copy
import math

@dataclass
class MaterialDamping:
    """
    Material-level damping definition (Modal + Rayleigh Proportional).
    modal_ratio is a plain damping ratio (0-1). The mass/stiffness
    coefficients are in SI base: visc/hyst_mass_coeff in 1/sec,
    visc/hyst_stiff_coeff in sec.
    """
    modal_ratio: float = 0.0

    visc_mass_coeff: float = 0.0
    visc_stiff_coeff: float = 0.0

    hyst_mass_coeff: float = 0.0
    hyst_stiff_coeff: float = 0.0

    def to_dict(self):
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d):
        if not d:
            return None
        known = MaterialDamping.__dataclass_fields__.keys()
        clean = {k: v for k, v in d.items() if k in known}
        return MaterialDamping(**clean)

@dataclass
class ManderConfinementData:
    """
    Confinement geometry/reinforcement feeding the Mander confined-concrete
    model (see core/mander_model.py). Two data sources: "User Defined"
    (typed in manually here) or "Frame Section Property" (source_mode ==
    "frame"), which pulls geometry and the confinement_* fields below
    from a real Section's own ReinforcementData and its assigned tie
    Rebar Material -- see ManderDataDialog._on_frame_sec_changed in
    material_dialog.py. All geometric fields are SI base (metres, Pa,
    m^2).
    """
    mander_type: str = "Unconfined"                                                                                  

    source_mode: str = "user"                                  
    frame_section_name: str = ""

    bar_size_mode: str = "size"                               
    bar_size: str = "15M"
    bar_area: float = 0.0                                                            

    num_x_legs: int = 2
    x_leg_spacing: float = 0.0                                                          
    num_y_legs: int = 2
    y_leg_spacing: float = 0.0                                                          

    num_long_x: int = 0
    num_long_y: int = 0
    long_bar_size_rect: str = "30M"

    core_diameter: float = 0.0                                                  
    long_bar_mode: str = "count"                               
    num_long_bars: int = 0
    long_bar_size: str = "30M"
    total_long_area: float = 0.0                                                     

    confinement_fyh: float = 4.0e8                                             
    tie_spacing: float = 0.0                                                                     

    tie_bar_material: str = ""                                                    
    confinement_fu: float = 0.0                                                       
    confinement_E: float = 0.0                                                              
    confinement_eps_sh: float = 0.0                                                         
    confinement_eps_su: float = 0.0                                                        
    confinement_curve_model: str = "Park"                                                             

    tie_layout: str = "rect"
    rho_s_scale: float = 1.0

    def to_dict(self):
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d):
        if not d:
            return None
        known = ManderConfinementData.__dataclass_fields__.keys()
        clean = {k: v for k, v in d.items() if k in known}
        return ManderConfinementData(**clean)

@dataclass
class NonlinearMaterialData:
    hysteresis_type: str = "Takeda"
                                                                             
    native_hysteresis_backup: str | None = None

    friction_angle: float = 0.0
    dilatational_angle: float = 0.0

    curve_mode: str = "Parametric"                                          
    parametric_model: str = "Mander (Exact)"

    eps_c0: float = 2.0e-3                   
    eps_cu: float = 5.0e-3                   
    
    rebar_parametric_model: str = "Park"                        
    rebar_eps_sh: float = 0.015
    rebar_eps_su: float = 0.090

    steel_eps_sh: float = 0.015
    steel_eps_su: float = 0.110
    steel_eps_rupture: float = 0.170

    final_slope_mult: float = -0.1         

    core_eps_cu_mode: str = "Mander"
    core_eps_cu_user: float = -0.035

    os_concrete_model: str = "Concrete04"
    cm_xcrn: float = 2.3
    cm_rt: float = 1.2
    cm_xcrp: float = 10000.0

    os_steel_model: str = "ReinforcingSteel"
    os_rupture: bool = False
    os_params: dict = field(default_factory=dict)

    mander: ManderConfinementData = field(default_factory=ManderConfinementData)
    user_points: list = field(default_factory=list)

    def to_dict(self):
        d = dict(self.__dict__)
        d["mander"] = self.mander.to_dict() if self.mander else None
        d["user_points"] = [list(p) for p in self.user_points]
        d["os_params"] = dict(self.os_params or {})
        return d

    @staticmethod
    def from_dict(d):
        if not d:
            return None
        known = NonlinearMaterialData.__dataclass_fields__.keys()
        clean = {k: v for k, v in d.items() if k in known and k not in ("mander", "user_points", "os_params")}
        obj = NonlinearMaterialData(**clean)
        obj.mander = ManderConfinementData.from_dict(d.get("mander")) or ManderConfinementData()
        obj.user_points = [tuple(p) for p in d.get("user_points", [])]
        obj.os_params = dict(d.get("os_params") or {})
        return obj

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
    fye: float = 0.0                                                                                            
    fue: float = 0.0                                                     
    grade: str = ""                                                     
    nonlinear: "NonlinearMaterialData | None" = None
    damping: "MaterialDamping | None" = None
                                                                             
    derived_from: str = ""

    @property
    def G(self):
        return self.E / (2 * (1 + self.nu))

    def get_fye(self):
        """Expected yield for nonlinear analysis. Falls back to 1.1*fy (common
        default overstrength factor for Gr60 rebar) if fye was never set."""
        return self.fye if self.fye > 0.0 else self.fy * 1.1

    def get_fue(self):
        return self.fue if self.fue > 0.0 else self.fu * 1.1

@dataclass
class ReinforcementData:
    """
    Reinforcement definition attached to a Rectangular, Circular, or
    Trapezoidal frame Section. Data-only for now — no fiber generation,
    no visualization. Populated fields depend on design_type/config;
    unused fields for a given combination are simply left at default.
    """
    long_bar_material: str = ""                                           
    tie_bar_material: str = ""
    design_type: str = "column"                         
    config: str = "rectangular"                                  
    confinement_type: str = "ties"                      

    clear_cover: float = 0.0
    num_bars_3dir: int = 0                                    
    num_bars_2dir: int = 0                                    
    num_bars_circ: int = 0                                 
    long_bar_size: str = ""
    tie_bar_size: str = ""
    tie_spacing: float = 0.0
    num_ties_3dir: int = 0                                                       
    num_ties_2dir: int = 0                                                       

    tie_layout: str = "rect"
    rho_s_scale: float = 1.0

    cover_top: float = 0.0
    cover_bottom: float = 0.0
    cover_side: float = 0.0
    top_bar_size: str = ""
    top_bar_count: int = 0
    bottom_bar_size: str = ""
    bottom_bar_count: int = 0

    def to_dict(self):
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d):
        if not d:
            return None
                                                             
        known = ReinforcementData.__dataclass_fields__.keys()
        clean = {k: v for k, v in d.items() if k in known}
        return ReinforcementData(**clean)

@dataclass
class HingeProperty:
    """
    Frame Hinge Property definition. Scope (today) is deliberately narrow:
    Fiber P-M2-M3 hinges only, fibers always generated from the assigned
    frame Section's own reinforcement/material data at analysis time
    (never a User Defined fiber layout typed in here). This class stores
    the DEFINITION only -- no fiber coordinates/areas are computed or
    cached here, since those depend on whatever section a hinge ends up
    assigned to later, and would go stale if stored eagerly.
    """
    name: str
    hinge_type: str = "Fiber P-M2-M3"                                                    
    behavior: str = "Deformation Controlled"                                                 
    fiber_option: str = "Default From Section"                                       
    hinge_length: float = 0.1
    hinge_length_relative: bool = True                                    

    fibers: list = field(default_factory=list)

    preview_section: str = ""

    cover_material: str = ""

    def to_dict(self):
        d = dict(self.__dict__)
        d["fibers"] = [dict(f) for f in self.fibers]
        return d

    @staticmethod
    def from_dict(d):
        if not d:
            return None
        known = HingeProperty.__dataclass_fields__.keys()
        clean = {k: v for k, v in d.items() if k in known and k != "fibers"}
        obj = HingeProperty(**clean)
        obj.fibers = [dict(f) for f in d.get("fibers", [])]
        return obj

def is_confined_concrete(material):
    """True if the material's Mander data is confined. Deliberately ignores
    curve_mode: fiber_section.get_material_backbone() always builds the concrete
    backbone from the Mander data, so this must agree with what the solver does."""
    nl = getattr(material, "nonlinear", None)
    if nl is None:
        return False
    mander = getattr(nl, "mander", None)
    return str(getattr(mander, "mander_type", "Unconfined")).startswith("Confined")

def build_unconfined_twin(parent_mat, name=None):
    """Exact copy of parent_mat (same f'c, E, strains, damping...) with only the
    Mander type switched to Unconfined, tagged so it can be refreshed later."""
    twin = copy.deepcopy(parent_mat)
    twin.name = name or f"{parent_mat.name}_unconfined"
    twin.derived_from = parent_mat.name
    if twin.nonlinear is not None:
        if twin.nonlinear.mander is None:
            twin.nonlinear.mander = ManderConfinementData()
        twin.nonlinear.mander.mander_type = "Unconfined"
        twin.nonlinear.mander.source_mode = "user"                                       
        twin.nonlinear.mander.frame_section_name = ""
    return twin

def derived_materials(model, parent_name):
    """Auto-generated copies of the named parent material."""
    return [m for m in model.materials.values() if getattr(m, "derived_from", "") == parent_name]

def hinge_fiber_users(model, mat_name):
    """Names of hinge properties whose stored fibers reference this material."""
    return sorted(
        hp.name for hp in getattr(model, "hinge_properties", {}).values()
        if any(f.get("material") == mat_name for f in hp.fibers)
    )

def ensure_unconfined_twin(model, parent_mat):
    """Returns (twin, status): "created", "refreshed" (an existing auto copy was
    rebuilt from the parent, keeping its name), or "existing" (a user-made
    '<parent>_unconfined' is used as-is, never overwritten).
    Raises ValueError if that user-made material still has confinement."""
    existing = derived_materials(model, parent_mat.name)
    if existing:
        name = existing[0].name                                                        
        model.add_material(build_unconfined_twin(parent_mat, name))
        return model.materials[name], "refreshed"

    name = f"{parent_mat.name}_unconfined"
    current = model.materials.get(name)
    if current is not None:
        if is_confined_concrete(current):
            raise ValueError(
                f"A material named '{name}' already exists, was not auto-generated, and "
                f"still has confinement defined, so it can't be used as the unconfined "
                f"cover. Rename or fix it, or pick a Cover material manually."
            )
        return current, "existing"

    twin = build_unconfined_twin(parent_mat, name)
    model.add_material(twin)
    return twin, "created"

def refresh_derived_twins(model, parent_name):
    """Rebuild every auto copy of parent_name from the parent's current data
    (same names, so hinge fibers keep resolving). Returns the refreshed names."""
    parent = model.materials.get(parent_name)
    if parent is None:
        return []
    names = []
    for tw in derived_materials(model, parent_name):
        model.add_material(build_unconfined_twin(parent, tw.name))
        names.append(tw.name)
    return names

def compute_rebar_positions(section, rebar_sizes):
    """
    Longitudinal rebar dot positions for a section's assigned
    ReinforcementData, as (y, z, diameter) tuples in the same generic
    horizontal/vertical local-coordinate space as get_shape_coords()
    (y = local axis 3 / horizontal, z = local axis 2 / vertical).

    Shared by the Section preview (app/dialogs/section_dialog.py, which
    has its own long-standing inline copy of this same math -- left as
    is, not routed through here) and the Hinge Property preview
    (app/dialogs/hinge_dialog.py). Keep this the single source of truth
    for any NEW caller of this geometry so the two previews can't drift
    out of sync the way the hinge fiber axes once did.

    Returns [] if the section has no reinforcement, or the reinforcement
    config doesn't match a shape this function knows how to place bars
    on (currently: rectangular columns and circular columns -- same
    scope as the existing section_dialog.py preview; trapezoidal is not
    handled here either, matching that file's current behavior).
    """
    reinf = getattr(section, "reinforcement", None)
    if reinf is None or reinf.design_type != "column":
        return []

    def get_dia(bar_id, fallback):
        for r in rebar_sizes or []:
            if r["id"] == bar_id:
                return r["diameter"]
        return fallback

    long_dia = get_dia(reinf.long_bar_size, 0.02)
    tie_dia = get_dia(reinf.tie_bar_size, 0.01)
    eff_cover = reinf.clear_cover + tie_dia + (long_dia / 2.0)

    rebars = []

    if reinf.config == "rectangular" and isinstance(section, RectangularSection):
        b, h = section.b, section.h
        y_min, y_max = -b / 2 + eff_cover, b / 2 - eff_cover
        z_min, z_max = -h / 2 + eff_cover, h / 2 - eff_cover

        n3, n2 = reinf.num_bars_3dir, reinf.num_bars_2dir
        if n3 >= 2 and n2 >= 2 and b > 2 * eff_cover and h > 2 * eff_cover:
            for i in range(n3):
                y = y_min + i * (y_max - y_min) / (n3 - 1)
                rebars.append((y, z_max, long_dia))
                rebars.append((y, z_min, long_dia))

            for i in range(1, n2 - 1):
                z = z_min + i * (z_max - z_min) / (n2 - 1)
                rebars.append((y_min, z, long_dia))
                rebars.append((y_max, z, long_dia))

    elif reinf.config == "circular" and isinstance(section, CircularSection):
        d = section.d
        n = reinf.num_bars_circ
        if n >= 2 and d > 2 * eff_cover:
            r_reinf = d / 2 - eff_cover
            for i in range(n):
                theta = 2.0 * math.pi * i / n
                rebars.append((r_reinf * math.cos(theta), r_reinf * math.sin(theta), long_dia))

    return rebars

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

        self.reinforcement = None                                                                   

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
        
        self.theta_p = float(props_dict.get('theta_p', 0.0))
        
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

class TendonSection:
    """Stores geometric and modeling properties for a Tendon."""
    def __init__(self, name, material, modeling_option="Loads", prestress_type="Prestress",
                 is_dia=False, dia=0.0, area=0.0, J=0.0, I=0.0, As=0.0, color=None):
        self.name = name
        self.material = material
        self.modeling_option = modeling_option                         
        self.prestress_type = prestress_type                                   
        self.is_dia = is_dia
        self.dia = float(dia)
        self.area = float(area)
        self.J = float(J)
        self.I = float(I)
        self.As = float(As)
        self.color = color if color else (0.0, 1.0, 1.0, 1.0)

    def __repr__(self):
        return f"TendonSection({self.name})"

class CableSection:
    """Stores geometric and material properties for a Cable."""
    def __init__(self, name, material, is_dia=False, dia=0.0, area=0.0, J=0.0, I=0.0, As=0.0, color=None):
        self.name = name
        self.material = material
        self.is_dia = is_dia
        self.dia = float(dia)
        self.area = float(area)
        self.J = float(J)
        self.I = float(I)
        self.As = float(As)
        self.color = color if color else (1.0, 0.0, 0.0, 1.0)
        
        self.modifiers = {
            "A": 1.0, 
            "Mass": 1.0, 
            "Weight": 1.0
        }

    def __repr__(self):
        return f"CableSection({self.name})"
