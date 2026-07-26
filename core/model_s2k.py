"""
model_s2k.py

Exports a StructuralModel instance (see model.py) to a SAP2000 text
interoperability file (.s2k / .$2k), so the same model can be opened
directly in SAP2000 for cross-validation without remodeling it twice.

Usage (hook this into main.py):

    from model_s2k import export_sap2000

    export_sap2000(
        model,
        filepath="MyModel.s2k",
        sap_version="21.2.0",       # cosmetic -- goes in the PROGRAM CONTROL header line only
        target_units="kN, m, C",    # the OUTPUT file's units. Model data is always
                                     # read as base SI (N, m) internally and converted --
                                     # see the unit conversion section below.
        project_info={"Model Name": model.name},
    )

See integration_example.py alongside this file for a small end-to-end example
of prompting the user for a SAP2000 version + file extension the way you
described (ask user -> save as .s2k or .$2k).

--------------------------------------------------------------------------
STATUS / WHAT'S COVERED IN THIS FIRST PASS
--------------------------------------------------------------------------
Solid (format verified against a real exported .s2k reference file):
    - PROGRAM CONTROL, PROJECT INFORMATION
    - GRID LINES
    - MATERIAL PROPERTIES 01 / 02
    - FRAME SECTION PROPERTIES 01 - GENERAL
    - JOINT COORDINATES
    - JOINT RESTRAINT ASSIGNMENTS
    - CONSTRAINT DEFINITIONS - DIAPHRAGM + JOINT CONSTRAINT ASSIGNMENTS
    - CONNECTIVITY - FRAME
    - FRAME SECTION ASSIGNMENTS
    - LOAD PATTERN DEFINITIONS
    - LOAD CASE DEFINITIONS (LinStatic solid; Modal/RespSpec/ModHist minimal)
    - CASE - STATIC 1 - LOAD ASSIGNMENTS
    - COMBINATION DEFINITIONS
    - MASS SOURCE
    - JOINT LOADS - FORCE
    - FRAME LOADS - POINT
    - FRAME LOADS - DISTRIBUTED  (Option A: every (distance, magnitude) pair in
      a MemberLoad's tributary curve is written out as its own trapezoidal
      segment row -- no simplification, fully literal, for validation accuracy)

NOT done yet / needs another look before relying on it (raises NotImplementedError
or just silently skips with a printed warning, clearly marked below):
    - Response spectrum functions (FUNCTION - RESPONSE SPECTRUM - ...)
    - Time history functions + companion data file (FUNCTION - TIME HISTORY - FROM FILE)
    - Frame end releases (partial fixity values) -- only Yes/No support so far
    - Links / link properties
    - Ground displacement loads
    - Area sections / area elements (skipped on purpose per your tributary workflow)

ASSUMPTIONS TO DOUBLE-CHECK ON FIRST REAL IMPORT:
    - `load_direction` strings on MemberLoad (e.g. "Global Z", "Gravity") are parsed
      down to a bare axis letter (X/Y/Z) via `_direction_axis()`. If your actual
      string values differ from what's assumed there, distributed loads will
      import into the wrong direction -- check this first if results look off.
    - `restraints` / `releases_i` / `releases_j` are assumed to be 6-element
      boolean lists in order [U1/P, U2/V2, U3/V3, R1/T, R2/M2, R3/M3].
"""

import uuid

try:
    from core.units import UnitConverter
except ImportError:
    class UnitConverter:
        """Fallback copy of core.units.UnitConverter -- keep this in sync with
        the real one if it ever changes. Prefer the real import above."""

        def __init__(self):
            self.force_scale = 0.001
            self.length_scale = 1.0
            self.temp_scale = 1.0
            self.current_unit_label = "kN, m, C"

        def set_unit_system(self, unit_string):
            self.current_unit_label = unit_string
            parts = unit_string.replace(" ", "").split(",")
            force_unit, length_unit = parts[0], parts[1]
            if force_unit == "kN":
                self.force_scale = 1 / 1000.0
            elif force_unit == "N":
                self.force_scale = 1.0
            elif force_unit == "Tonf":
                self.force_scale = 1 / 9806.65
            elif force_unit == "kgf":
                self.force_scale = 1 / 9.80665
            elif force_unit == "kip":
                self.force_scale = 1 / 4448.22
            if length_unit == "m":
                self.length_scale = 1.0
            elif length_unit == "mm":
                self.length_scale = 1000.0
            elif length_unit == "cm":
                self.length_scale = 100.0
            elif length_unit == "ft":
                self.length_scale = 3.28084
            elif length_unit == "in":
                self.length_scale = 39.3701

        def to_display_force(self, v):
            return v * self.force_scale

        def to_display_length(self, v):
            return v * self.length_scale

        def to_display_pressure(self, v):
            return v * self.force_scale / (self.length_scale ** 2)

        def to_display_acceleration(self, v):
            return v * self.length_scale

_GRAVITY_SI = 9.80665         

def _to_area(conv, v):
    """length^2 quantities: cross-sectional area, As2, As3"""
    return v * conv.length_scale ** 2

def _to_i(conv, v):
    """length^4 quantities: I33, I22, J (torsion constant)"""
    return v * conv.length_scale ** 4

def _to_dist_load(conv, v):
    """force/length quantities: distributed load intensity (FOverLA/B, wx/wy/wz)"""
    return v * conv.force_scale / conv.length_scale

def _to_moment(conv, v):
    """force*length quantities: applied moments"""
    return v * conv.force_scale * conv.length_scale

def _to_unit_weight(conv, v):
    """force/length^3 quantities: material unit weight (density field, which is
    actually weight density in N/m^3, NOT mass density -- confirmed via
    cross-checking against a real SAP2000 export)."""
    return v * conv.force_scale / conv.length_scale ** 3

def _to_unit_mass(conv, unit_weight_display):
    """Given unit weight already converted to display units, back out unit
    mass using g in the same display unit system (mass = weight / g)."""
    g_display = conv.to_display_acceleration(_GRAVITY_SI)
    return unit_weight_display / g_display if g_display else 0.0
                                                                            
def _fmt(val):
    """Format a python value the way SAP2000 text tables expect."""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, float):
        if val == int(val) and abs(val) < 1e15:
            return str(int(val))
        return f"{val:.10g}"
    if isinstance(val, int):
        return str(val)
    if val is None:
        return None
    s = str(val)
    if s == "":
        return '""'
    if any(c in s for c in (" ", "\t", ",")) and not (s.startswith('"') and s.endswith('"')):
        return f'"{s}"'
    return s

def _guid():
    return str(uuid.uuid4())

class S2KWriter:
    """Accumulates lines for a SAP2000 .s2k text file."""

    def __init__(self):
        self.lines = []

    def table(self, name):
        self.lines.append(f'TABLE:  "{name}"')

    def row(self, **kwargs):
        parts = []
        for k, v in kwargs.items():
            if v is None:
                continue
            fv = _fmt(v)
            if fv is None:
                continue
            parts.append(f"{k}={fv}")
        self.lines.append("   " + "   ".join(parts))

    def blank(self):
        self.lines.append(" ")

    def text(self):
        return "\r\n".join(self.lines) + "\r\n"

_MATERIAL_TYPE_MAP = {
    "concrete": "Concrete",
    "steel": "Steel",
    "rebar": "Rebar",
    "tendon": "Tendon",
    "aluminum": "Aluminum",
    "coldformed": "Cold Formed",
    "other": "Other",
}

def _material_type_token(mat_type):
    return _MATERIAL_TYPE_MAP.get((mat_type or "").lower(), "Other")

_DESIGN_TYPE_MAP = {
    "DEAD": "Dead", "DEAD LOAD": "Dead",
    "LIVE": "Live", "LIVE LOAD": "Live",
    "QUAKE": "Quake", "EQ": "Quake", "SEISMIC": "Quake",
    "WIND": "Wind",
    "SNOW": "Snow",
}

_CASE_TYPE_MAP = {
                                                                           
    "Linear Static": "LinStatic",
    "LinStatic": "LinStatic",
    "Modal": "LinModal",
    "LinModal": "LinModal",
    "Response Spectrum": "LinRespSpec",
    "LinRespSpec": "LinRespSpec",
    "LTHA": "LinModHist",
    "Linear Modal History": "LinModHist",
    "LinModHist": "LinModHist",
    "Buckling": "LinBuckling",
    "Linear Buckling": "LinBuckling",
    "LinBuckling": "LinBuckling",
}

def _design_type_for_pattern_type(pattern_type):
    return _DESIGN_TYPE_MAP.get((pattern_type or "").upper(), "Other")

def _sap_color(raw_color):
    """
    SAP2000's Color field wants a named color (e.g. 'Magenta') or a packed
    integer -- not a raw [r, g, b, a] list like model.py stores. If we don't
    have something SAP will accept, omit the field entirely and let SAP
    auto-assign a default rather than writing garbage.
    """
    if isinstance(raw_color, str) and raw_color:
        return raw_color
    return None

def _direction_axis(load_direction):
    """
    Reduce a load_direction string like 'Global Z', 'Local X', 'Gravity'
    down to a bare SAP2000 Dir token (X/Y/Z).

    ASSUMPTION - verify against your actual core.loads convention; adjust
    here if a real SAP2000 import shows loads pointing the wrong way.
    """
    if not load_direction:
        return "Z"
    s = load_direction.upper()
    if "GRAVITY" in s:
        return "Z"
    if s.endswith("X") or " X" in s:
        return "X"
    if s.endswith("Y") or " Y" in s:
        return "Y"
    if s.endswith("Z") or " Z" in s:
        return "Z"
    return "Z"

def export_sap2000(model, filepath, sap_version="v22", target_units="kN, m, C",
                    project_info=None, source_program_name="SAP2000"):
    """
    Serialize `model` (a StructuralModel instance) to a SAP2000 .s2k file at `filepath`.

    `target_units` is the unit system the exported .s2k will be written in
    (e.g. "kN, m, C", "kip, ft, F"). The model itself is always assumed to
    store data internally in base SI (N, m) -- see the unit conversion
    section above -- so this is purely about the *output* file's units.
    """
    conv = UnitConverter()
    conv.set_unit_system(target_units)

    w = S2KWriter()

    steps = [
        ("header", lambda: _write_header(w, model, sap_version, target_units)),
        ("project info", lambda: _write_project_info(w, project_info or {})),
        ("grid lines", lambda: _write_grid_lines(w, model, conv)),
        ("materials", lambda: _write_materials(w, model, conv)),
        ("sections", lambda: _write_sections(w, model, conv)),
        ("joint coordinates", lambda: _write_joint_coordinates(w, model, conv)),
        ("joint restraints", lambda: _write_joint_restraints(w, model)),
        ("joint springs", lambda: _write_joint_springs(w, model, conv)),
        ("diaphragms", lambda: _write_diaphragms(w, model)),
        ("frame connectivity", lambda: _write_frame_connectivity(w, model)),
        ("frame local axes", lambda: _write_frame_local_axes(w, model)),
        ("frame releases", lambda: _write_frame_releases(w, model)),
        ("frame insertion points", lambda: _write_frame_insertion_points(w, model, conv)),
        ("frame end length offsets", lambda: _write_frame_offset_along_length(w, model, conv)),
        ("frame section assignments", lambda: _write_frame_section_assignments(w, model)),
        ("load patterns", lambda: _write_load_patterns(w, model)),
        ("auto seismic loads", lambda: _write_auto_seismic_loads(w, model, conv)),
        ("load cases", lambda: _write_load_cases(w, model)),
        ("combinations", lambda: _write_combinations(w, model)),
        ("mass source", lambda: _write_mass_source(w, model)),
        ("joint loads", lambda: _write_joint_loads(w, model, conv)),
        ("ground displacements", lambda: _write_ground_displacements(w, model, conv)),
        ("frame point loads", lambda: _write_frame_point_loads(w, model, conv)),
        ("frame distributed loads", lambda: _write_frame_distributed_loads(w, model, conv)),
    ]

    for step_name, step_fn in steps:
        try:
            step_fn()
        except Exception as e:
            raise RuntimeError(f"Failed while writing '{step_name}': {e!r}") from e

    with open(filepath, "w", newline="") as f:
        f.write(w.text())

    print(f"[model_s2k] Exported model to {filepath} (units: {target_units})")
    return filepath

def _write_header(w, model, sap_version, units):
    w.lines.append(f"File saved by model_s2k.py exporter")
    w.blank()
    w.table("ACTIVE DEGREES OF FREEDOM")
    w.row(UX="Yes", UY="Yes", UZ="Yes", RX="Yes", RY="Yes", RZ="Yes")
    w.blank()
    w.table("PROGRAM CONTROL")
    w.row(ProgramName=source_program_name if False else "SAP2000",
          Version=sap_version, CurrUnits=units,
          SteelCode="AISC 360-10", ConcCode="ACI 318-14",
          AlumCode="AA-ASD 2000", ColdCode="AISI-ASD96", RegenHinge="Yes")
    w.blank()

def _write_project_info(w, project_info):
    w.table("PROJECT INFORMATION")
    default_items = ["Company Name", "Client Name", "Project Name", "Project Number",
                      "Model Name", "Model Description", "Revision Number",
                      "Frame Type", "Engineer", "Checker", "Supervisor",
                      "Issue Code", "Design Code"]
    for item in default_items:
        val = project_info.get(item)
        if val:
            w.row(Item=item, Value=val)
        else:
            w.row(Item=item)
    w.blank()

def _write_grid_lines(w, model, conv):
    """
    GridLines stores each line as a dict: {'id': str, 'ord': float, 'visible': bool, 'bubble': str}
    -- confirmed against core/grid.py.
    """
    grid = getattr(model, "grid", None)
    if grid is None:
        return
    w.table("GRID LINES")
    for axis, lines in (("X", getattr(grid, "x_lines", []) or []),
                        ("Y", getattr(grid, "y_lines", []) or []),
                        ("Z", getattr(grid, "z_lines", []) or [])):
        for line in lines:
            w.row(CoordSys="GLOBAL", AxisDir=axis, GridID=line.get("id"),
                  XRYZCoord=conv.to_display_length(line.get("ord", 0.0)),
                  LineType="Primary", LineColor="Gray8Dark",
                  Visible=line.get("visible", True),
                  BubbleLoc=line.get("bubble", "Start"))
    w.blank()

def _write_materials(w, model, conv):
    w.table("MATERIAL PROPERTIES 01 - GENERAL")
    for mat in model.materials.values():
        w.row(Material=mat.name, Type=_material_type_token(getattr(mat, "mat_type", None)),
              SymType="Isotropic", TempDepend="No", GUID=_guid())
    w.blank()

    w.table("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES")
    for mat in model.materials.values():
                                                                        
        unit_weight = _to_unit_weight(conv, getattr(mat, "density", 0.0))
        unit_mass = _to_unit_mass(conv, unit_weight)
        w.row(Material=mat.name, UnitWeight=unit_weight, UnitMass=unit_mass,
              E1=conv.to_display_pressure(mat.E), G12=conv.to_display_pressure(mat.G),
              U12=mat.nu)
    w.blank()

    steel_mats = [m for m in model.materials.values()
                  if (getattr(m, "mat_type", "") or "").lower() == "steel" and getattr(m, "fy", 0)]
    if steel_mats:
        w.table("MATERIAL PROPERTIES 03A - STEEL DATA")
        for mat in steel_mats:
            w.row(Material=mat.name, Fy=conv.to_display_pressure(mat.fy),
                  Fu=conv.to_display_pressure(mat.fu))
        w.blank()

    conc_mats = [m for m in model.materials.values()
                 if (getattr(m, "mat_type", "") or "").lower() == "concrete"
                 and (getattr(m, "fy", 0) or getattr(m, "fu", 0))]
    if conc_mats:
        w.table("MATERIAL PROPERTIES 03B - CONCRETE DATA")
        for mat in conc_mats:
            fc = getattr(mat, "fy", 0) or getattr(mat, "fu", 0)
            w.row(Material=mat.name, Fc=conv.to_display_pressure(fc))
        w.blank()

def _write_sections(w, model, conv):
    """
    Maps each section type to a real SAP2000 catalog shape using the class
    name (RectangularSection, ISection, CircularSection, PipeSection,
    TubeSection -- confirmed from model.py's isinstance checks in save_to_file).
    TrapezoidalSection and ArbitrarySection have no clean built-in SAP2000
    catalog shape, so those still fall back to Shape=General using computed
    properties (analytically correct stiffness-wise, just won't render as a
    "real" catalog shape in SAP2000's section designer).
    """
    w.table("FRAME SECTION PROPERTIES 01 - GENERAL")
    for sec in model.sections.values():
        cls = sec.__class__.__name__
        shape = "General"
        extra = {}

        if cls == "RectangularSection" or (hasattr(sec, "b") and hasattr(sec, "h")
                                            and not hasattr(sec, "w_top")):
            shape = "Rectangular"
            extra = dict(t3=conv.to_display_length(sec.h), t2=conv.to_display_length(sec.b))

        elif cls == "ISection" or (hasattr(sec, "w_top") and hasattr(sec, "t_web")):
            shape = "I/Wide Flange"
            extra = dict(t3=conv.to_display_length(sec.h),
                         t2=conv.to_display_length(sec.w_top),
                         tf=conv.to_display_length(sec.t_top),
                         tw=conv.to_display_length(sec.t_web),
                         t2b=conv.to_display_length(sec.w_bot),
                         tfb=conv.to_display_length(sec.t_bot))

        elif cls == "TubeSection" or (hasattr(sec, "tf") and hasattr(sec, "tw")):
            shape = "Tube"
            extra = dict(t3=conv.to_display_length(sec.d), t2=conv.to_display_length(sec.b),
                         tf=conv.to_display_length(sec.tf), tw=conv.to_display_length(sec.tw))

        elif cls == "PipeSection" or (hasattr(sec, "d") and hasattr(sec, "t")
                                       and not hasattr(sec, "b")):
            shape = "Pipe"
            extra = dict(t3=conv.to_display_length(sec.d), tw=conv.to_display_length(sec.t))

        elif cls == "CircularSection" or (hasattr(sec, "d") and not hasattr(sec, "t")):
            shape = "Circle"
            extra = dict(t3=conv.to_display_length(sec.d))

        elif cls == "TrapezoidalSection":
                                                                                          
            pass
        elif cls == "ArbitrarySection":
                                                                             
            pass

        w.row(SectionName=sec.name, Material=sec.material.name, Shape=shape,
              **extra,
              Area=_to_area(conv, sec.A), TorsConst=_to_i(conv, sec.J),
              I33=_to_i(conv, sec.I33), I22=_to_i(conv, sec.I22), I23=0,
              AS2=_to_area(conv, sec.Asy), AS3=_to_area(conv, sec.Asz),
              Color=_sap_color(getattr(sec, "color", None)),
              FromFile="No", AMod=1, A2Mod=1, A3Mod=1, JMod=1, I2Mod=1, I3Mod=1,
              MMod=1, WMod=1)
    w.blank()

def _write_joint_coordinates(w, model, conv):
    w.table("JOINT COORDINATES")
    for n_id in sorted(model.nodes.keys()):
        n = model.nodes[n_id]
        w.row(Joint=n.id, CoordSys="GLOBAL", CoordType="Cartesian",
              XorR=conv.to_display_length(n.x), Y=conv.to_display_length(n.y),
              Z=conv.to_display_length(n.z), SpecialJt="No", GUID=_guid())
    w.blank()

def _write_joint_restraints(w, model):
    w.table("JOINT RESTRAINT ASSIGNMENTS")
    for n_id in sorted(model.nodes.keys()):
        n = model.nodes[n_id]
        r = getattr(n, "restraints", None)
        if not r or not any(r):
            continue
        u1, u2, u3, r1, r2, r3 = (list(r) + [False] * 6)[:6]
        w.row(Joint=n.id, U1=u1, U2=u2, U3=u3, R1=r1, R2=r2, R3=r3)
    w.blank()

def _write_joint_springs(w, model, conv):
    """
    node.spring_matrix -> JOINT SPRING ASSIGNMENTS.
    Confirmed field: Node.spring_matrix (numpy array, saved via .tolist()).
    We only have evidence it exists and gets saved as a matrix -- no reference
    .s2k sample had springs populated, so this handles the common diagonal
    (uncoupled) case confidently. If spring_matrix is a full 6x6 with nonzero
    off-diagonal coupling terms, those are NOT exported (SAP2000's coupled
    spring table has a different, unconfirmed format) -- flagged below.
    """
    import numpy as np
    rows = []
    for n_id in sorted(model.nodes.keys()):
        n = model.nodes[n_id]
        sm = getattr(n, "spring_matrix", None)
        if sm is None:
            continue
        arr = np.array(sm)
        if arr.ndim == 1 and len(arr) >= 6:
            diag = arr[:6]
        elif arr.ndim == 2:
            diag = np.diag(arr)[:6]
            if not np.allclose(arr - np.diag(np.diag(arr)), 0):
                print(f"[model_s2k] WARNING: Joint {n.id} has a fully-coupled spring "
                      f"matrix -- only the diagonal terms are being exported, "
                      f"off-diagonal coupling is dropped (unverified table format).")
        else:
            continue
        if not any(diag):
            continue
        rows.append((n.id, diag))

    if not rows:
        return
    w.table("JOINT SPRING ASSIGNMENTS")
    for n_id, diag in rows:
        u1, u2, u3, r1, r2, r3 = diag
        w.row(Joint=n_id, U1=_to_dist_load(conv, u1), U2=_to_dist_load(conv, u2),
              U3=_to_dist_load(conv, u3), R1=_to_moment(conv, r1),
              R2=_to_moment(conv, r2), R3=_to_moment(conv, r3), Simple="No")
    w.blank()

def _write_diaphragms(w, model):
    constraints = getattr(model, "constraints", {})
    if not constraints:
        return
    w.table("CONSTRAINT DEFINITIONS - DIAPHRAGM")
    for name, const in constraints.items():
        w.row(Name=name, CoordSys="GLOBAL", Axis=getattr(const, "axis", "Z"), MultiLevel="No")
    w.blank()

    w.table("JOINT CONSTRAINT ASSIGNMENTS")
    for n_id in sorted(model.nodes.keys()):
        n = model.nodes[n_id]
        diaphragm = getattr(n, "diaphragm_name", None)
        if diaphragm:
            w.row(Joint=n.id, Constraint=diaphragm)
    w.blank()

def _write_frame_connectivity(w, model):
    w.table("CONNECTIVITY - FRAME")
    for el_id in sorted(model.elements.keys()):
        el = model.elements[el_id]
        w.row(Frame=el.id, JointI=el.node_i.id, JointJ=el.node_j.id,
              IsCurved="No", GUID=_guid())
    w.blank()

def _write_frame_local_axes(w, model):
    """el.beta_angle -> FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL. Only written for
    elements with a nonzero angle (0 is SAP's default, no need to spell it out)."""
    rows = [el for el in model.elements.values() if getattr(el, "beta_angle", 0.0)]
    if not rows:
        return
    w.table("FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL")
    for el in rows:
        w.row(Frame=el.id, Angle=el.beta_angle, AdvanceAxes="No")
    w.blank()

def _write_frame_releases(w, model):
    """
    el.releases_i/j -> FRAME RELEASE ASSIGNMENTS 1 - GENERAL.
    Model only stores Yes/No release flags (no partial-fixity spring values),
    so that's all we emit. Order assumed [P, V2, V3, T, M2, M3] per end.
    """
    rows = [el for el in model.elements.values()
            if any(getattr(el, "releases_i", None) or []) or any(getattr(el, "releases_j", None) or [])]
    if not rows:
        return
    w.table("FRAME RELEASE ASSIGNMENTS 1 - GENERAL")
    for el in rows:
        ri = (list(el.releases_i) + [False] * 6)[:6]
        rj = (list(el.releases_j) + [False] * 6)[:6]
        w.row(Frame=el.id,
              PI=ri[0], V2I=ri[1], V3I=ri[2], TI=ri[3], M2I=ri[4], M3I=ri[5],
              PJ=rj[0], V2J=rj[1], V3J=rj[2], TJ=rj[3], M2J=rj[4], M3J=rj[5])
    w.blank()

_CARDINAL_PT_LABELS = {
    1: "1 (bottom left)", 2: "2 (bottom center)", 3: "3 (bottom right)",
    4: "4 (middle left)", 5: "5 (middle center)", 6: "6 (middle right)",
    7: "7 (top left)", 8: "8 (top center)", 9: "9 (top right)",
    10: "10 (centroid)", 11: "11 (shear center)",
}
                                                                             
def _write_frame_insertion_points(w, model, conv):
    """
    el.joint_offset_i/j (off_i/off_j) + el.cardinal_point -> FRAME INSERTION POINT ASSIGNMENTS.
    CONFIRMED against a real SAP2000 export: table name has no version suffix,
    fields are CardinalPt (a descriptive string, not a bare int), JtOffsetXI/YI/ZI,
    JtOffsetXJ/YJ/ZJ, Mirror2, Mirror3, Transform. Every frame gets a row (not
    just ones with nonzero offsets) -- CoordSys/JtOffset* columns are only
    included on a row when that frame actually has a nonzero offset.
    """
    w.table("FRAME INSERTION POINT ASSIGNMENTS")
    for el_id in sorted(model.elements.keys()):
        el = model.elements[el_id]
        off_i = getattr(el, "joint_offset_i", None)
        off_i = [0.0, 0.0, 0.0] if off_i is None else list(off_i)
        off_j = getattr(el, "joint_offset_j", None)
        off_j = [0.0, 0.0, 0.0] if off_j is None else list(off_j)
        cardinal = getattr(el, "cardinal_point", 10) or 10
        cardinal_label = _CARDINAL_PT_LABELS.get(cardinal, f"{cardinal} (centroid)")

        extra = {}
        if any(off_i) or any(off_j):
            extra = dict(
                CoordSys="GLOBAL",
                JtOffsetXI=conv.to_display_length(off_i[0]), JtOffsetYI=conv.to_display_length(off_i[1]),
                JtOffsetZI=conv.to_display_length(off_i[2]), JtOffsetXJ=conv.to_display_length(off_j[0]),
                JtOffsetYJ=conv.to_display_length(off_j[1]), JtOffsetZJ=conv.to_display_length(off_j[2]),
            )
        w.row(Frame=el.id, CardinalPt=cardinal_label, **extra,
              Mirror2="No", Mirror3="No", Transform="Yes")
    w.blank()

def _write_frame_offset_along_length(w, model, conv):
    """
    el.end_offset_i/j + el.rigid_zone_factor -> FRAME OFFSET ALONG LENGTH ASSIGNMENTS.
    CONFIRMED against a real SAP2000 export: table name and fields (Type,
    LengthI, LengthJ, RigidFactor) were both wrong in the previous version of
    this exporter ("FRAME END LENGTH OFFSETS" / LengthOffI / LengthOffJ /
    RZFactor never existed). Every frame gets a row, including zero-offset ones.
    """
    w.table("FRAME OFFSET ALONG LENGTH ASSIGNMENTS")
    for el_id in sorted(model.elements.keys()):
        el = model.elements[el_id]
        length_i = getattr(el, "end_offset_i", 0.0) or 0.0
        length_j = getattr(el, "end_offset_j", 0.0) or 0.0
        rigid_factor = getattr(el, "rigid_zone_factor", 0.0) or 0.0
        w.row(Frame=el.id, Type="User",
              LengthI=conv.to_display_length(length_i), LengthJ=conv.to_display_length(length_j),
              RigidFactor=rigid_factor)
    w.blank()

def _write_frame_section_assignments(w, model):
    w.table("FRAME SECTION ASSIGNMENTS")
    for el_id in sorted(model.elements.keys()):
        el = model.elements[el_id]
        w.row(Frame=el.id, AutoSelect="N.A.", AnalSect=el.section.name, MatProp="Default")
    w.blank()

def _write_load_patterns(w, model):
    w.table("LOAD PATTERN DEFINITIONS")
    for lp in model.load_patterns.values():
        w.row(LoadPat=lp.name, DesignType=_design_type_for_pattern_type(lp.pattern_type),
              SelfWtMult=lp.self_weight_multiplier, GUID=_guid())
    w.blank()

def _write_auto_seismic_loads(w, model, conv):
    """
    LoadPattern.seismic_data.diaphragm_loads -> AUTO SEISMIC - USER LOADS.
    AddEcc (eccentricity) is passed through unconverted -- it's a ratio/percent
    value, not a physical force/length quantity (confirmed: matches 1:1
    between model data and the reference .s2k with no scaling).
    """
    rows = []
    for lp in model.load_patterns.values():
        seismic = getattr(lp, "seismic_data", None)
        if not seismic or not getattr(seismic, "diaphragm_loads", None):
            continue
        for diaphragm, comp in seismic.diaphragm_loads.items():
            rows.append((lp.name, diaphragm, seismic.eccentricity, comp))
    if not rows:
        return
    w.table("AUTO SEISMIC - USER LOADS")
    for pat_name, diaphragm, ecc, comp in rows:
        w.row(LoadPat=pat_name, Diaphragm=diaphragm, AppPoint="CM", AddEcc=ecc,
              FX=conv.to_display_force(comp.get("Fx", 0.0)),
              FY=conv.to_display_force(comp.get("Fy", 0.0)),
              MZ=_to_moment(conv, comp.get("Mz", 0.0)))
    w.blank()

def _write_load_cases(w, model):
    w.table("LOAD CASE DEFINITIONS")
    for lc in model.load_cases.values():
        sap_type = _CASE_TYPE_MAP.get(lc.case_type, "LinStatic")
        design_type = "Other"
        if lc.loads:
            first_pattern_name = lc.loads[0][0]
            lp = model.load_patterns.get(first_pattern_name)
            if lp:
                design_type = _design_type_for_pattern_type(lp.pattern_type)
        extra = {}
        if sap_type == "LinRespSpec" or sap_type == "LinModHist":
            extra["ModalCase"] = getattr(lc, "modal_case", None) or "MODAL"
        w.row(Case=lc.name, Type=sap_type, InitialCond="Zero",
              DesTypeOpt="Prog Det", DesignType=design_type,
              DesActOpt="Prog Det", DesignAct="Non-Composite",
              AutoType="None", RunCase="Yes", GUID=_guid(), **extra)
    w.blank()

    w.table("CASE - STATIC 1 - LOAD ASSIGNMENTS")
    for lc in model.load_cases.values():
        if _CASE_TYPE_MAP.get(lc.case_type, "LinStatic") != "LinStatic":
            continue
        for pattern_name, scale_factor in lc.loads:
            w.row(Case=lc.name, LoadType="Load pattern", LoadName=pattern_name,
                  LoadSF=scale_factor)
    w.blank()

    modal_cases = [lc for lc in model.load_cases.values()
                   if _CASE_TYPE_MAP.get(lc.case_type, "") == "LinModal"]
    if modal_cases:
        w.table("CASE - MODAL 1 - GENERAL")
        for lc in modal_cases:
            w.row(Case=lc.name, ModeType="Eigen",
                  MaxNumModes=getattr(lc, "num_modes", 12), MinNumModes=1,
                  EigenShift=0, EigenCutoff=0, EigenTol="1E-09", AutoShift="Yes")
        w.blank()

    buckling_cases = [lc for lc in model.load_cases.values()
                       if _CASE_TYPE_MAP.get(lc.case_type, "") == "LinBuckling"]
    if buckling_cases:
        w.table("CASE - BUCKLING 1 - GENERAL")
        for lc in buckling_cases:
            w.row(Case=lc.name, NumBuckMode=getattr(lc, "num_modes", 12), EigenTol="1E-09")
        w.blank()

        w.table("CASE - BUCKLING 2 - LOAD ASSIGNMENTS")
        for lc in buckling_cases:
            for pattern_name, scale_factor in lc.loads:
                w.row(Case=lc.name, LoadType="Load pattern", LoadName=pattern_name,
                      LoadSF=scale_factor)
        w.blank()

def _write_combinations(w, model):
    combos = getattr(model, "load_combos", {})
    if not combos:
        return
    w.table("COMBINATION DEFINITIONS")
    for combo in combos.values():
        combo_type = combo.combo_type if combo.combo_type in ("Linear Add", "Envelope", "Absolute Add", "SRSS") else "Linear Add"
        first = True
        for case_name, scale_factor in combo.cases:
            if first:
                w.row(ComboName=combo.name, ComboType=combo_type, AutoDesign="No",
                      CaseName=case_name, ScaleFactor=scale_factor,
                      SteelDesign="None", ConcDesign="None", AlumDesign="None",
                      ColdDesign="None", GUID=_guid())
                first = False
            else:
                w.row(ComboName=combo.name, CaseName=case_name, ScaleFactor=scale_factor)
    w.blank()

def _write_mass_source(w, model):
    mass_sources = getattr(model, "mass_sources", {})
    if not mass_sources:
        return
    w.table("MASS SOURCE")
    for i, ms in enumerate(mass_sources.values()):
        if not ms.load_patterns:
            w.row(MassSource=ms.name, Elements=ms.include_self_mass,
                  Masses="No", Loads="No", IsDefault=(i == 0))
            continue
        for pattern_name, multiplier in ms.load_patterns:
            w.row(MassSource=ms.name, Elements=ms.include_self_mass,
                  Masses="No", Loads="Yes", IsDefault=(i == 0),
                  LoadPat=pattern_name, Multiplier=multiplier)
    w.blank()

def _write_ground_displacements(w, model, conv):
    """
    GroundDisplacement(node_id, pattern_name, ux, uy, uz, rx, ry, rz) -> JOINT LOADS - DISPLACEMENT.
    Distinguished from NodalLoad by having ux/uy/uz instead of fx/fy/fz.
    Rotations (rx/ry/rz) are left unconverted -- radians, not a force/length quantity.
    UNVERIFIED against a real .s2k sample (no reference file had ground
    displacement loads) -- double-check on first real import.
    """
    rows = [ld for ld in model.loads if hasattr(ld, "ux") and hasattr(ld, "node_id")]
    if not rows:
        return
    w.table("JOINT LOADS - DISPLACEMENT")
    for ld in rows:
        w.row(Joint=ld.node_id, LoadPat=ld.pattern_name, CoordSys="GLOBAL",
              U1=conv.to_display_length(ld.ux), U2=conv.to_display_length(ld.uy),
              U3=conv.to_display_length(ld.uz), R1=ld.rx, R2=ld.ry, R3=ld.rz)
    w.blank()

def _write_joint_loads(w, model, conv):
    rows = [ld for ld in model.loads if hasattr(ld, "node_id") and hasattr(ld, "fx")]
    if not rows:
        return
    w.table("JOINT LOADS - FORCE")
    for ld in rows:
        w.row(Joint=ld.node_id, LoadPat=ld.pattern_name, CoordSys="GLOBAL",
              F1=conv.to_display_force(ld.fx), F2=conv.to_display_force(ld.fy),
              F3=conv.to_display_force(ld.fz), M1=_to_moment(conv, ld.mx),
              M2=_to_moment(conv, ld.my), M3=_to_moment(conv, ld.mz),
              GUID=_guid())
    w.blank()

def _write_frame_point_loads(w, model, conv):
    rows = [ld for ld in model.loads if hasattr(ld, "force") and hasattr(ld, "element_id")]
    if not rows:
        return
    w.table("FRAME LOADS - POINT")
    for ld in rows:
        is_rel = getattr(ld, "is_relative", True)
        dist_type = "RelDist" if is_rel else "AbsDist"
        is_moment = getattr(ld, "load_type", "Force") == "Moment"
        dist_val = ld.dist if is_rel else conv.to_display_length(ld.dist)
        force_val = _to_moment(conv, ld.force) if is_moment else conv.to_display_force(ld.force)
        w.row(Frame=ld.element_id, LoadPat=ld.pattern_name, CoordSys=getattr(ld, "coord_system", "Global").upper(),
              Type=getattr(ld, "load_type", "Force"), Dir=_direction_axis(getattr(ld, "direction", "Z")),
              DistType=dist_type, RelDist=(dist_val if is_rel else None),
              AbsDist=(dist_val if not is_rel else None),
              Force=(force_val if not is_moment else None),
              Moment=(force_val if is_moment else None),
              GUID=_guid())
    w.blank()

def _write_frame_distributed_loads(w, model, conv):
    """
    Option A: every consecutive (distance, magnitude) pair on a MemberLoad's
    tributary curve is written as its own trapezoidal segment. No simplification.
    Also handles the simple wx/wy/wz uniform-load case as a single full-length segment.

    RelDistA/B stay as unitless 0-1 fractions (no conversion). AbsDistA/B are
    lengths and get converted. FOverLA/B are force/length (distributed load
    intensity) and get converted via _to_dist_load.
    """
    rows = [ld for ld in model.loads if hasattr(ld, "wx") and hasattr(ld, "element_id")]
    if not rows:
        return

    w.table("FRAME LOADS - DISTRIBUTED")
    for ld in rows:
        coord_sys = getattr(ld, "coord_system", "Global")
        coord_sys_token = "GLOBAL" if coord_sys.lower() == "global" else "LOCAL"

        for axis, val in (("X", ld.wx), ("Y", ld.wy), ("Z", ld.wz)):
            if val:
                fv = _to_dist_load(conv, val)
                w.row(Frame=ld.element_id, LoadPat=ld.pattern_name, CoordSys=coord_sys_token,
                      Type="Force", Dir=axis, DistType="RelDist",
                      RelDistA=0, RelDistB=1, FOverLA=fv, FOverLB=fv, GUID=_guid())

        distances = getattr(ld, "distances", None)
        magnitudes = getattr(ld, "magnitudes", None)
        has_real_curve = (distances and magnitudes and len(distances) >= 2
                           and any(magnitudes))
        if has_real_curve:
            axis = _direction_axis(getattr(ld, "load_direction", "Z"))
            is_rel = getattr(ld, "is_relative", True)
            dist_type = "RelDist" if is_rel else "AbsDist"
            load_type = getattr(ld, "load_type", "Force")
            for i in range(len(distances) - 1):
                da, db = distances[i], distances[i + 1]
                ma, mb = magnitudes[i], magnitudes[i + 1]
                if not is_rel:
                    da, db = conv.to_display_length(da), conv.to_display_length(db)
                fa, fb = _to_dist_load(conv, ma), _to_dist_load(conv, mb)
                dist_kwargs = ({"RelDistA": da, "RelDistB": db} if dist_type == "RelDist"
                                else {"AbsDistA": da, "AbsDistB": db})
                w.row(Frame=ld.element_id, LoadPat=ld.pattern_name,
                      CoordSys=coord_sys_token, Type=load_type, Dir=axis,
                      DistType=dist_type, **dist_kwargs,
                      FOverLA=fa, FOverLB=fb, GUID=_guid())
    w.blank()
