import json
from core.compact_json import write_json
from core.mesh import Node, FrameElement, TendonObject
from core.properties import (Material, RectangularSection, ISection, GeneralSection,
                             CircularSection, PipeSection, TubeSection, TrapezoidalSection,
                             ArbitrarySection, ShellSection, PlaneSection, AsolidSection, AreaSection, TendonSection,
                             ReinforcementData, NonlinearMaterialData, MaterialDamping, HingeProperty)
from core.grid import GridLines
from core.boundary import apply_restraint, Restraint
from core.mesh import Slab, AreaElement 
from core.units import unit_registry
from core.reference_curve import sanitize_loaded_curves
import numpy as np
from core.loads import LoadPattern, NodalLoad, MemberLoad, MemberPointLoad, AreaGravityLoad, AreaUniformLoad, GroundDisplacement
class TSC2018Data:
    def __init__(self):
                                    
        self.direction = "X"             
        self.eccentricity = 0.05
        
        self.period_method = "Program Calc"                                   
        self.ct = 0.075                       
        self.user_t = 0.0
        
        self.ss = 0.0
        self.s1 = 0.0
        self.tl = 6.0
        self.site_class = "ZB"
        
        self.r = 8.0
        self.d = 3.0
        self.importance = 1.0

class UserSeismicData:
    def __init__(self):
        self.eccentricity = 0.05
                                                               
        self.diaphragm_loads = {}
                 
class MassSource:
    def __init__(self, name):
        self.name = name
        self.include_self_mass = True                                           
        self.include_patterns = True                              
        self.load_patterns = []                                                         

class LoadPattern:
    def __init__(self, name, pattern_type="DEAD", self_weight_multiplier=0.0):
        self.name = name
        self.seismic_data = None 
        self.auto_lateral = "None" 
        self.tsc_data = None
        self.pattern_type = pattern_type                               
        self.self_weight_multiplier = float(self_weight_multiplier)
        self.seismic_data = None                                      

class NodalLoad:
    def __init__(self, node_id, pattern_name, fx=0, fy=0, fz=0, mx=0, my=0, mz=0):
        self.node_id = node_id
        self.pattern_name = pattern_name
        self.fx = fx; self.fy = fy; self.fz = fz
        self.mx = mx; self.my = my; self.mz = mz
    
    def __repr__(self):
        return f"NodalLoad(node={self.node_id}, pat={self.pattern_name}, Fz={self.fz})"

class MemberLoad:
    def __init__(self, element_id, pattern_name, wx=0, wy=0, wz=0, 
                 projected=False, coord_system="Global",
                 distances=None, magnitudes=None, is_relative=True, 
                 load_direction="Gravity", load_type="Force"):
        self.element_id = element_id
        self.pattern_name = pattern_name
        
        self.wx = float(wx)
        self.wy = float(wy)
        self.wz = float(wz)
        
        self.projected = bool(projected)
        self.coord_system = coord_system 
        
        self.distances = distances if distances is not None else [0.0, 0.25, 0.75, 1.0]
        self.magnitudes = magnitudes if magnitudes is not None else [0.0, 0.0, 0.0, 0.0]
        self.is_relative = is_relative
        self.load_direction = load_direction
        self.load_type = load_type

    def __repr__(self):
        return f"MemberLoad(elem={self.element_id}, {self.coord_system}, dir={self.load_direction})"

class FrameHingeAssignment:
    """
    A single assigned hinge on a frame element: which hinge property
    (from model.hinge_properties, e.g. 'FH1'), and where along the
    element (relative distance 0-1). Purely a data record - not wired
    to the solver.
    """
    def __init__(self, hinge_id, element_id, hinge_name, rel_dist):
        self.id = hinge_id
        self.element_id = element_id
        self.hinge_name = hinge_name
        self.rel_dist = float(rel_dist)

    def to_dict(self):
        return {
            "id": self.id,
            "element_id": self.element_id,
            "hinge_name": self.hinge_name,
            "rel_dist": self.rel_dist,
        }

    @staticmethod
    def from_dict(data):
        return FrameHingeAssignment(
            data["id"], data["element_id"], data["hinge_name"], data["rel_dist"]
        )

    def __repr__(self):
        return f"FrameHingeAssignment(elem={self.element_id}, hinge={self.hinge_name}, rel={self.rel_dist:.3f})"

class RigidDiaphragm:
    """
    Represents a rigid floor constraint (Constraint).
    """
    def __init__(self, name, axis="Z"):
        self.name = name
        self.axis = axis                                                  
        
        self.nodes = []                                           
        self.center_of_mass = [0, 0, 0]                             

class StructuralModel:
    def __init__(self, name="New Model"):
        self.name = name

        self.active_dofs = [True, True, True, True, True, True]
        self.analysis_engine = "native"
        self.last_run_case = None
        self.show_analysis_log = True

        self.graphics_settings = {}                        
        
        self.nodes = {}                        
        self.elements = {}                             
        self.materials = {}                          
        self.sections = {}
        self.rebar_sizes = []
        self.hinge_properties = {}
        self.frame_hinges = {}
        self._hinge_assign_counter = 1
        self.tendon_sections = {}
        self.tendons = {}
        self._tendon_counter = 1
        self.cable_sections = {}              
        self.cables = {}                      
        self._cable_counter = 1
        self.link_properties = {}
        self.links = {}
        self._link_counter = 1                         
        self.load_patterns = {}                           
        self.load_cases = {}   
        self.load_combos = {}
        self.functions = {}                                      
        self.mass_sources = {}
        self.loads = []                                         
        self.add_load_pattern("DEAD", "DEAD", 1.0)
        self.create_default_cases()
        self.slabs = {}
        self.area_sections = {}
        self.area_elements = {}
        self._area_elem_counter = 1

        self.functions = {}
        self.th_functions = {}
        self.plot_functions = []
        self.virtual_measurements = {}
        self.pushover_param_sets = [self.make_pushover_param_set("PO1")]
                                                                                         
        self.reference_curves = []
        self.constraints = {}
                         
        self.grid = GridLines()
        
        self._node_counter = 1
        self._elem_counter = 1
        self._slab_counter = 1

        self.add_load_pattern("DEAD", "DEAD", 1.0)

    @staticmethod
    def make_pushover_param_set(name):
        """
        One named Pushover (Force vs Displacement) parameter set: HOW to draw,
        never WHICH case -- the case is chosen in the results viewer, so a set
        works for any case of a single or batch run.
        Manual axis ranges are stored in BASE units (N, m, or step number),
        so they stay physically correct if the display units change.
        """
        return {
            "name": name,
            "kind": "force_disp",
            "plot_type": "Resultant Base Shear vs Monitored Displacement",
            "units": "Model display units",
            "auto_x": True, "x_min": 0.0, "x_max": 0.0,
            "auto_y": True, "y_min": 0.0, "y_max": 0.0,
            "label_x": "", "label_y": "", "notes": "",
            "curve_color": "", "curve_width": 2.2, "curve_style": "-",                                             
            "overlay_curves": [],                                                                         
        }

    def add_material(self, material):
        self.materials[material.name] = material
        return material

    def add_section(self, section):
        self.sections[section.name] = section
        return section

    def add_hinge_property(self, hinge_prop):
        self.hinge_properties[hinge_prop.name] = hinge_prop
        return hinge_prop

    def get_next_hinge_name(self):
        """Auto-suggests the next available hinge property name (FH1, FH2, ...)."""
        i = 1
        while f"FH{i}" in self.hinge_properties:
            i += 1
        return f"FH{i}"

    def assign_frame_hinge(self, element_id, hinge_name, rel_dist, mode="replace"):
        """
        Assigns a hinge property to a frame element at a relative
        distance (0-1) along its length. Data-only - not wired to any
        solver/converter.
        mode: "add" (append), "replace" (clear this element's existing
        hinges first), or "delete" (clear this element's hinges).
        """
        if element_id not in self.elements:
            raise KeyError(f"Element {element_id} does not exist.")

        existing_ids = [hid for hid, h in self.frame_hinges.items()
                        if h.element_id == element_id]

        if mode == "delete":
            for hid in existing_ids:
                del self.frame_hinges[hid]
            return

        if mode == "replace":
            for hid in existing_ids:
                del self.frame_hinges[hid]
        elif mode == "add":
                                                                 
            for hid in existing_ids:
                h = self.frame_hinges[hid]
                if h.hinge_name == hinge_name and abs(h.rel_dist - rel_dist) < 1e-6:
                    return

        new_id = self._hinge_assign_counter
        self._hinge_assign_counter += 1
        self.frame_hinges[new_id] = FrameHingeAssignment(new_id, element_id, hinge_name, rel_dist)

    def _get_next_node_id(self):
        """Calculates the next available Node ID."""
        if not self.nodes:
            return 1
        return max(self.nodes.keys()) + 1

    def _get_next_elem_id(self):
        """Calculates the next available Element ID."""
        if not self.elements:
            return 1
        return max(self.elements.keys()) + 1

    def add_node(self, x, y, z):
        """Creates and adds a node with a guaranteed unique ID."""
        new_id = self._get_next_node_id()
        new_node = Node(new_id, x, y, z)
        self.nodes[new_id] = new_node
                                                      
        self._node_counter = new_id + 1 
        return new_node

    def add_element(self, node_i, node_j, section, beta=0.0):
        """Creates and adds a frame element with a guaranteed unique ID."""
        new_id = self._get_next_elem_id()
        new_elem = FrameElement(new_id, node_i, node_j, section, beta)
        self.elements[new_id] = new_elem
        self._elem_counter = new_id + 1
        return new_elem

    def add_slab(self, nodes, thickness, material=None):
        """
        Creates and adds a visual Slab element.
        nodes: list of Node objects (3 or 4 nodes)
        """
        new_slab = Slab(self._slab_counter, nodes, thickness, material)
        self.slabs[self._slab_counter] = new_slab
        self._slab_counter += 1
        return new_slab
    
    def add_area_element(self, nodes, section):
        """Creates and adds an AreaElement (Shell/Plane/Asolid) with a unique ID."""
        new_area = AreaElement(self._area_elem_counter, nodes, section)
        self.area_elements[self._area_elem_counter] = new_area
        self._area_elem_counter += 1
        return new_area

    def add_area_section(self, section):
        """Add or replace an area section (Shell / Plane / Asolid)."""
        self.area_sections[section.name] = section
        return section

    def get_total_dofs(self):
        """Returns total degrees of freedom (Nodes * 6)"""
        return len(self.nodes) * 6
    
    def add_load_pattern(self, name, p_type, multiplier):
        self.load_patterns[name] = LoadPattern(name, p_type, multiplier)
        
        if name not in self.load_cases:
                                             
            lc = LoadCase(name, "Linear Static")
            lc.loads.append((name, 1.0))                                        
            self.load_cases[name] = lc

    def create_default_cases(self):
        """Syncs Load Patterns to Load Cases."""
                                
        if "MODAL" not in self.load_cases:
            self.load_cases["MODAL"] = LoadCase("MODAL", "Modal")
            
        for pat_name in self.load_patterns.keys():
            if pat_name not in self.load_cases:
                                                                    
                lc = LoadCase(pat_name, "Linear Static")
                lc.loads.append((pat_name, 1.0))
                self.load_cases[pat_name] = lc

    def add_load_case(self, case):
        self.load_cases[case.name] = case

    def assign_joint_load(self, node_id, pattern_name, fx=0, fy=0, fz=0, mx=0, my=0, mz=0, mode="replace"):
        """
        Assigns load to a node.
        mode: 'add' (accumulate), 'replace' (overwrite), 'delete' (remove)
        """
        if node_id not in self.nodes:
            raise KeyError(f"Node {node_id} does not exist.")
            
        existing_indices = []
        for i, load in enumerate(self.loads):
                                                                               
            if hasattr(load, 'node_id') and load.node_id == node_id and load.pattern_name == pattern_name:
                existing_indices.append(i)
        
        if mode == "delete":
                                                                  
            for i in reversed(existing_indices):
                del self.loads[i]
            return

        elif mode == "replace":
                                           
            for i in reversed(existing_indices):
                del self.loads[i]
            
            if any([fx, fy, fz, mx, my, mz]):
                new_load = NodalLoad(node_id, pattern_name, fx, fy, fz, mx, my, mz)
                self.loads.append(new_load)

        elif mode == "add":
                                                               
            if existing_indices:
                idx = existing_indices[0]
                self.loads[idx].fx += fx
                self.loads[idx].fy += fy
                self.loads[idx].fz += fz
                self.loads[idx].mx += mx
                self.loads[idx].my += my
                self.loads[idx].mz += mz
            else:
                 if any([fx, fy, fz, mx, my, mz]):
                    new_load = NodalLoad(node_id, pattern_name, fx, fy, fz, mx, my, mz)
                    self.loads.append(new_load)

    def assign_ground_displacement(self, node_id, pattern_name, ux=0, uy=0, uz=0, rx=0, ry=0, rz=0, mode="replace"):
        """
        Assigns ground displacement to a node.
        mode: 'add' (accumulate), 'replace' (overwrite), 'delete' (remove)
        """
        if node_id not in self.nodes:
            raise KeyError(f"Node {node_id} does not exist.")
            
        existing_indices = []
        for i, load in enumerate(self.loads):
                                                                           
            if isinstance(load, GroundDisplacement) and load.node_id == node_id and load.pattern_name == pattern_name:
                existing_indices.append(i)
        
        if mode == "delete":
            for i in reversed(existing_indices):
                del self.loads[i]
            return

        elif mode == "replace":
            for i in reversed(existing_indices):
                del self.loads[i]
            
            if any([ux, uy, uz, rx, ry, rz]):
                new_disp = GroundDisplacement(node_id, pattern_name, ux, uy, uz, rx, ry, rz)
                self.loads.append(new_disp)

        elif mode == "add":
            if existing_indices:
                idx = existing_indices[0]
                self.loads[idx].ux += ux
                self.loads[idx].uy += uy
                self.loads[idx].uz += uz
                self.loads[idx].rx += rx
                self.loads[idx].ry += ry
                self.loads[idx].rz += rz
            else:
                 if any([ux, uy, uz, rx, ry, rz]):
                    new_disp = GroundDisplacement(node_id, pattern_name, ux, uy, uz, rx, ry, rz)
                    self.loads.append(new_disp)
                   
    def is_node_used(self, node_id):
        """
        Integrity Check: Returns True if the node is supporting any geometry.
        Used to prevent accidental deletion of critical joints.
        """
                           
        for el in self.elements.values():
            if el.node_i.id == node_id or el.node_j.id == node_id:
                return True
        
        for slab in self.slabs.values():
            for n in slab.nodes:
                if n.id == node_id:
                    return True
                    
        for ae in self.area_elements.values():
            for n in ae.nodes:
                if n.id == node_id:
                    return True
        return False
    
    def assign_member_load(self, element_id, pattern_name, wx=0, wy=0, wz=0, 
                           projected=False, coord_system="Global", mode="replace",
                           distances=None, magnitudes=None, is_relative=True, 
                           load_direction="Gravity", load_type="Force"):
        """
        Assigns distributed load to a frame element, supporting full trapezoidal definition.
        """
        if element_id not in self.elements:
            raise KeyError(f"Element {element_id} does not exist.")
        
        if distances is None: distances = [0.0, 0.25, 0.75, 1.0]
        if magnitudes is None: magnitudes = [0.0, 0.0, 0.0, 0.0]

        existing_indices = []
        for i, load in enumerate(self.loads):
            if (hasattr(load, 'element_id') and load.element_id == element_id 
                and getattr(load, 'pattern_name', None) == pattern_name):
                existing_indices.append(i)

        if mode == "delete":
            for i in reversed(existing_indices):
                del self.loads[i]
            return

        elif mode == "replace":
            for i in reversed(existing_indices):
                del self.loads[i]
            
            has_nonzero = (abs(wx) > 1e-9 or abs(wy) > 1e-9 or abs(wz) > 1e-9 or 
                           any(abs(m) > 1e-9 for m in magnitudes))
            if has_nonzero:
                new_load = MemberLoad(element_id, pattern_name, wx, wy, wz, 
                                      projected, coord_system, 
                                      distances, magnitudes, is_relative, load_direction, load_type)
                self.loads.append(new_load)

        elif mode == "add":
            has_nonzero = (abs(wx) > 1e-9 or abs(wy) > 1e-9 or abs(wz) > 1e-9 or 
                           any(abs(m) > 1e-9 for m in magnitudes))
            if has_nonzero:
                new_load = MemberLoad(element_id, pattern_name, wx, wy, wz, 
                                      projected, coord_system, 
                                      distances, magnitudes, is_relative, load_direction, load_type)
                self.loads.append(new_load)

    def assign_member_loads(self, element_ids, pattern_name, wx=0, wy=0, wz=0,
                            projected=False, coord_system="Global", mode="replace",
                            distances=None, magnitudes=None, is_relative=True,
                            load_direction="Gravity", load_type="Force"):
        """Assign the same frame load in one pass over the existing loads.

        Unique valid IDs use a linear batch. Repeated or invalid IDs retain
        the single-assignment order and its partial-error behavior.
        """
        ids = list(element_ids)

        def sequential():
            for element_id in ids:
                self.assign_member_load(element_id, pattern_name, wx, wy, wz,
                    projected, coord_system, mode, distances, magnitudes,
                    is_relative, load_direction, load_type)

        try:
            selected = set(ids)
            fast = len(selected) == len(ids) and all(eid in self.elements for eid in ids)
        except TypeError:
            fast = False
        if not fast:
            return sequential()
        if not ids or mode not in ("add", "replace", "delete"):
            return
        new_loads = []
                                                                      
        if mode != "delete" and magnitudes is not None and not isinstance(magnitudes, (list, tuple, np.ndarray)):
            return sequential()
        if mode != "delete":
            try:
                has_nonzero = (abs(wx) > 1e-9 or abs(wy) > 1e-9 or abs(wz) > 1e-9 or
                               any(abs(m) > 1e-9 for m in (magnitudes if magnitudes is not None else ())))
                if has_nonzero:
                    new_loads = [MemberLoad(eid, pattern_name, wx, wy, wz,
                        projected, coord_system, distances, magnitudes, is_relative,
                        load_direction, load_type) for eid in ids]
            except (TypeError, ValueError, OverflowError):
                return sequential()
        if mode in ("replace", "delete"):
                                                                             
            self.loads[:] = [load for load in self.loads if not (
                hasattr(load, 'element_id') and load.element_id in selected
                and getattr(load, 'pattern_name', None) == pattern_name)]
        self.loads.extend(new_loads)

    def save_to_file(self, filepath, progress=None):
        """Serializes the model data to a JSON file"""
        print(">>> RUNNING THE NEW SAVE METHOD <<<")           
        def _p(msg):
            if progress: progress(msg)
            
        _p("Saving project info & graphics...")
        data = {
            "info": {
                "name": self.name,
                "units": unit_registry.current_unit_label,
                "active_dofs": getattr(self, 'active_dofs', [True, True, True, True, True, True]),
                "analysis_engine": getattr(self, 'analysis_engine', "native"),
                "last_run_case": getattr(self, 'last_run_case', None),
                "show_analysis_log": getattr(self, 'show_analysis_log', True)
            },
            "graphics": self.graphics_settings,
            "rebar_sizes": getattr(self, 'rebar_sizes', []), 
            "load_cases": [],
            "grid": {
                "x_lines": self.grid.x_lines,
                "y_lines": self.grid.y_lines,
                "z_lines": self.grid.z_lines,
                "bubble_size": getattr(self.grid, 'bubble_size', 1.25),
                "bubble_alpha": getattr(self.grid, 'bubble_alpha', 1.0),
                "bubble_line_width": getattr(self.grid, 'bubble_line_width', 1.5),
                "bubble_ext_line_width": getattr(self.grid, 'bubble_ext_line_width', None),
                "bubble_extension": getattr(self.grid, 'bubble_extension',
                                            getattr(self.grid, 'bubble_size', 1.25) * 2.5),
                "style": getattr(self.grid, 'style', None)
            },
            "materials": [],
            "sections": [],
            "hinge_properties": [],
            "frame_hinges": [],
            "tendon_sections": [],
            "cable_sections": [],
            "tendons": [],
            "cables": [],
            "nodes": [],
            "elements": [],
            "slabs": [],    
            "area_elements": [],
            "area_sections": [],   
            "constraints": [],
            "link_properties": [],
            "links": [],
            "load_patterns": [],
            "loads": [],
            "mass_sources": [],
            "functions": [],
            "th_functions": [],
            "plot_functions": [],
            "virtual_measurements": self.virtual_measurements,
            "pushover_param_sets": list(getattr(self, 'pushover_param_sets', [])),
            "reference_curves": list(getattr(self, 'reference_curves', []))
        }

        _p(f"Saving {len(self.load_cases)} load case(s)...")
        for lc in self.load_cases.values():
            data["load_cases"].append({
                "name": lc.name,
                "type": lc.case_type,
                "loads": lc.loads,                                                             
                "mass_source": lc.mass_source,
                "geom_nonlin": getattr(lc, 'geom_nonlin', 'None'),
                "nl_params": {
                    "max_total_steps": getattr(lc, 'max_total_steps', 200),
                    "max_null_steps": getattr(lc, 'max_null_steps', 50),
                    "use_event_stepping": getattr(lc, 'use_event_stepping', True),
                    "event_lumping_tol": getattr(lc, 'event_lumping_tol', 0.01),
                    "max_events_per_step": getattr(lc, 'max_events_per_step', 24),
                    "use_iteration": getattr(lc, 'use_iteration', True),
                    "max_const_stiff_iter": getattr(lc, 'max_const_stiff_iter', 10),
                    "max_nr_iter": getattr(lc, 'max_nr_iter', 40),
                    "iter_conv_tol": getattr(lc, 'iter_conv_tol', 1e-4),
                    "use_line_search": getattr(lc, 'use_line_search', False),
                    "tf_max_iter": getattr(lc, 'tf_max_iter', 10),
                    "tf_conv_tol": getattr(lc, 'tf_conv_tol', 0.01),
                    "tf_accel_factor": getattr(lc, 'tf_accel_factor', 1.0),
                    "continue_if_no_converge": getattr(lc, 'continue_if_no_converge', False),
                    "use_fd_tangent": getattr(lc, 'use_fd_tangent', False),
                    "formulation": getattr(lc, 'formulation', "Corotational"),
                    "corot_type": getattr(lc, 'corot_type', "Commercial Compatibility"),
                    "results_saved": getattr(lc, 'results_saved', "Final State Only"),
                    "min_saved_states": getattr(lc, 'min_saved_states', 1),
                    "max_saved_states": getattr(lc, 'max_saved_states', 100),
                    "save_positive_disp_only": getattr(lc, 'save_positive_disp_only', False),
                    "continue_from_case": getattr(lc, 'continue_from_case', None),
                    "load_application": getattr(lc, 'load_application', "Full Load"),
                    "disp_control_node_id": getattr(lc, 'disp_control_node_id', None),
                    "disp_control_dof": getattr(lc, 'disp_control_dof', "U1"),
                    "disp_control_magnitude": getattr(lc, 'disp_control_magnitude', 0.1),
                    "disp_control_tol": getattr(lc, 'disp_control_tol', 1e-6),
                    "hinge_snap": getattr(lc, 'hinge_snap', True),
                    "hinge_snap_scope": getattr(lc, 'hinge_snap_scope', "tension"),
                    "stop_on_fiber_failure": getattr(lc, 'stop_on_fiber_failure', False),
                    "residual_stiffness": getattr(lc, 'residual_stiffness', 1e-8),
                    "min_step_frac": getattr(lc, 'min_step_frac', 1e-4),
                    "max_event_probes": getattr(lc, 'max_event_probes', 12),
                    "auto_cutback": getattr(lc, 'auto_cutback', True),
                    "max_step_attempts": getattr(lc, 'max_step_attempts', 0)
                },
                "opensees": get_opensees_block(lc),
                "num_modes": getattr(lc, 'num_modes', 12),
                "modal_fiber_hinges": getattr(lc, 'modal_fiber_hinges', False),
                "rsa_loads": getattr(lc, 'rsa_loads', []),
                "modal_comb": getattr(lc, 'modal_comb', 'SRSS'),
                "dir_comb": getattr(lc, 'dir_comb', 'SRSS'),
                "modal_damping": getattr(lc, 'modal_damping', 0.05),
                "ltha_damping": getattr(lc, 'damping', 0.05),
                "ltha_loads": getattr(lc, 'ltha_loads', [])
            })
        
        _p(f"Saving {len(self.load_combos)} load combination(s)...")
        data["load_combos"] = []
        for combo in self.load_combos.values():
            data["load_combos"].append({
                "name": combo.name,
                "combo_type": combo.combo_type,
                "cases": combo.cases
            })

        _p(f"Saving {len(self.materials)} material(s)...")
        for mat in self.materials.values():
            nonlinear = getattr(mat, "nonlinear", None)
            damping = getattr(mat, "damping", None)
            data["materials"].append({
                "name": mat.name,
                "E": mat.E, "nu": mat.nu, "G": mat.G, "rho": mat.density,
                "type": mat.mat_type, "fy": mat.fy, "fu": mat.fu,
                "fye": getattr(mat, "fye", 0.0), "fue": getattr(mat, "fue", 0.0),
                "grade": getattr(mat, "grade", ""),
                "derived_from": getattr(mat, "derived_from", ""),
                "nonlinear": nonlinear.to_dict() if nonlinear else None,
                "damping": damping.to_dict() if damping else None,
            })

        _p(f"Saving {len(self.sections)} frame section(s)...")
        for sec in self.sections.values():
            sec_data = {
                "name": sec.name,
                "mat_name": sec.material.name,
                "color": sec.color,
                "modifiers": sec.modifiers,
                "properties": {
                    "A": sec.A, 
                    "J": sec.J, 
                    "I33": sec.I33, 
                    "I22": sec.I22, 
                    "As2": sec.Asy, 
                    "As3": sec.Asz,
                    "theta_p": getattr(sec, 'theta_p', 0.0)
                }
            }
            if isinstance(sec, RectangularSection):
                sec_data.update({"type": "rectangular", "b": sec.b, "h": sec.h})
            elif isinstance(sec, ISection):
                sec_data.update({"type": "i_section", "h": sec.h, "w_top": sec.w_top, "t_top": sec.t_top, "w_bot": sec.w_bot, "t_bot": sec.t_bot, "t_web": sec.t_web})
            elif isinstance(sec, CircularSection):
                sec_data.update({"type": "circular", "d": sec.d})
            elif isinstance(sec, PipeSection):
                sec_data.update({"type": "pipe", "d": sec.d, "t": sec.t})
            elif isinstance(sec, TubeSection):
                sec_data.update({"type": "tube", "d": sec.d, "b": sec.b, "tf": sec.tf, "tw": sec.tw})
            elif isinstance(sec, TrapezoidalSection):
                sec_data.update({"type": "trapezoidal", "d": sec.d, "w_top": sec.w_top, "w_bot": sec.w_bot})
            elif isinstance(sec, ArbitrarySection):
                sec_data.update({
                    "type": "arbitrary",
                    "vertices": sec.vertices,                                   
                    "y_c": sec._y_c,                                    
                    "z_c": sec._z_c,
                })
            elif isinstance(sec, GeneralSection):
                sec_data.update({"type": "general"})

            if getattr(sec, "reinforcement", None) is not None:
                sec_data["reinforcement"] = sec.reinforcement.to_dict()

            data["sections"].append(sec_data)

        _p(f"Saving {len(self.hinge_properties)} hinge propert(y/ies)...")
        for hp in self.hinge_properties.values():
            data["hinge_properties"].append(hp.to_dict())

        _p(f"Saving {len(self.frame_hinges)} frame hinge assignment(s)...")
        for fh in self.frame_hinges.values():
            data["frame_hinges"].append(fh.to_dict())

        _p(f"Saving {len(self.tendon_sections)} tendon section(s)...")
        for ts in self.tendon_sections.values():
            data["tendon_sections"].append({
                "name": ts.name,
                "mat_name": ts.material.name if ts.material else None,
                "modeling_option": ts.modeling_option,
                "prestress_type": ts.prestress_type,
                "is_dia": ts.is_dia,
                "dia": ts.dia,
                "area": ts.area,
                "J": ts.J,
                "I": ts.I,
                "As": ts.As,
                "color": ts.color
            })

        _p(f"Saving {len(self.cable_sections)} cable section(s)...")
        for cs in self.cable_sections.values():
            data["cable_sections"].append({
                "name": cs.name,
                "mat_name": cs.material.name if cs.material else None,
                "is_dia": getattr(cs, 'is_dia', False),
                "dia": getattr(cs, 'dia', 0.0),
                "area": getattr(cs, 'area', 0.0),
                "J": getattr(cs, 'J', 0.0),
                "I": getattr(cs, 'I', 0.0),
                "As": getattr(cs, 'As', 0.0),
                "color": cs.color,
                "modifiers": getattr(cs, 'modifiers', {"A": 1.0, "Mass": 1.0, "Weight": 1.0})
            })
        
        _p(f"Saving {len(self.nodes)} nodes & boundary conditions...")
        for n_id in sorted(self.nodes.keys()):
            n = self.nodes[n_id]
            node_dict = {
                "id": n.id, "x": n.x, "y": n.y, "z": n.z,
                "restraints": n.restraints, 
                "diaphragm": getattr(n, 'diaphragm_name', None)  
            }
                                                      
            if getattr(n, 'spring_matrix', None) is not None:
                node_dict["spring_matrix"] = n.spring_matrix.tolist()
                
            data["nodes"].append(node_dict)

        _p(f"Saving {len(self.link_properties)} link properties...")
        for name, prop in self.link_properties.items():
            data["link_properties"].append({
                "name": name,
                "mass": prop.get("mass", 0.0),
                "weight": prop.get("weight", 0.0),
                "r1": prop.get("r1", 0.0),
                "r2": prop.get("r2", 0.0),
                "r3": prop.get("r3", 0.0),
                "is_fixed": prop.get("is_fixed", [False]*6),
                "stiffness": prop.get("stiffness", np.zeros((6,6))).tolist(),
                "damping": prop.get("damping", np.zeros((6,6))).tolist()
            })

        _p(f"Saving {len(self.links)} links...")
        for lid, link in self.links.items():
            data["links"].append({
                "id": lid,
                "prop_name": link["prop_name"],
                "nodes": link["nodes"],
                "beta": link.get("beta", 0.0)
            })

        _p(f"Saving {len(self.elements)} frame element(s) & releases...")
        for el_id in sorted(self.elements.keys()):
            el = self.elements[el_id]
            data["elements"].append({
                "id": el.id,
                "n1_id": el.node_i.id,
                "n2_id": el.node_j.id,
                "sec_name": el.section.name,
                "beta": el.beta_angle,
                "rel_i": el.releases_i,
                "rel_j": el.releases_j,
                "cardinal": el.cardinal_point,
                "off_i": el.joint_offset_i.tolist(), 
                "off_j": el.joint_offset_j.tolist(),  
                "end_off_i": el.end_offset_i,
                "end_off_j": el.end_offset_j,
                "rz_factor": el.rigid_zone_factor
            })

        _p(f"Saving {len(self.tendons)} tendon object(s)...")
        for t_id in sorted(self.tendons.keys()):
            t = self.tendons[t_id]
            data["tendons"].append({
                "id": t.id,
                "n1_id": t.node_i.id,
                "n2_id": t.node_j.id,
                "sec_name": t.tendon_section.name,
                "host_element_ids": t.host_element_ids,
                "plane": t.plane,
                "local_axis_angle": t.local_axis_angle,
                "modeling_option": t.modeling_option,
                "prestress_type": t.prestress_type,
                "layout_points": t.layout_points,
                "max_discretization_length": t.max_discretization_length,
                "coordinate_system": t.coordinate_system,
                "color": t.color,
                "loads": getattr(t, "loads", [])
            })

        _p(f"Saving {len(self.cables)} cable(s)...")
        for c_id in sorted(self.cables.keys()):
            c = self.cables[c_id]
            data["cables"].append({
                "id": c.id,
                "n1_id": c.node_i.id,
                "n2_id": c.node_j.id,
                "sec_name": c.cable_section.name if c.cable_section else None,
                "model_as_straight_frame": getattr(c, 'model_as_straight_frame', True),
                "number_of_segments": getattr(c, 'number_of_segments', 1),
                "undeformed_length": getattr(c, 'undeformed_length', None),
                "is_active": getattr(c, 'is_active', True),
                                                            
                "target_type": getattr(c, 'target_type', "Cable - Undeformed Length"),
                "target_value": getattr(c, 'target_value', None),
                "added_weight": getattr(c, 'added_weight', 0.0),
                "projected_load": getattr(c, 'projected_load', 0.0)
            })

        _p(f"Saving {len(self.slabs)} slab(s)...")
        for slab in self.slabs.values():
            data["slabs"].append({"id": slab.id, "node_ids": [n.id for n in slab.nodes], "thick": slab.thickness})

        _p(f"Saving {len(self.area_elements)} area element(s)...")
        for ae in self.area_elements.values():
            data["area_elements"].append({
                "id": ae.id, 
                "node_ids": [n.id for n in ae.nodes], 
                "sec_name": ae.section.name,
                "insertion_offset": getattr(ae, 'insertion_offset', 0.0),
                "solver_mesh": getattr(ae, 'solver_mesh', None)
            })

        _p(f"Saving {len(self.constraints)} diaphragm constraint(s)...")
        for name, const in self.constraints.items():
            data["constraints"].append({"name": name, "axis": const.axis})

        _p(f"Saving {len(self.load_patterns)} load pattern(s)...")
        for lp in self.load_patterns.values():
            lp_dict = {
                "name": lp.name, 
                "type": lp.pattern_type, 
                "sw_mult": lp.self_weight_multiplier,
                "auto_lateral": getattr(lp, "auto_lateral", "None")

            }
            if lp.seismic_data:
                lp_dict["seismic_data"] = {
                    "eccentricity": lp.seismic_data.eccentricity,
                    "diaphragm_loads": lp.seismic_data.diaphragm_loads
                }
            if getattr(lp, 'tsc_data', None):
                lp_dict["tsc_data"] = {
                    "direction": lp.tsc_data.direction,
                    "eccentricity": lp.tsc_data.eccentricity,
                    "period_method": lp.tsc_data.period_method,
                    "ct": lp.tsc_data.ct,
                    "user_t": lp.tsc_data.user_t,
                    "ss": lp.tsc_data.ss,
                    "s1": lp.tsc_data.s1,
                    "tl": lp.tsc_data.tl,
                    "site_class": lp.tsc_data.site_class,
                    "r": lp.tsc_data.r,
                    "d": lp.tsc_data.d,
                    "importance": lp.tsc_data.importance
                }
            data["load_patterns"].append(lp_dict)

        _p(f"Saving {len(self.loads)} load assignment(s)...")
        for load in self.loads:
            if isinstance(load, dict) and load.get('_is_tendon_auto'):
                data["loads"].append(load)                     
                continue

            load_data = {"pattern": load.pattern_name}
            
            if hasattr(load, 'uniform_load'):                                  
                load_data.update({
                    "type":      "area_uniform",
                    "area_id":   load.area_id,
                    "load":      load.uniform_load,
                    "direction": load.load_direction,
                    "coord":     load.coord_system
                })
            elif hasattr(load, 'gx'):                                          
                load_data.update({
                    "type":    "area_gravity",
                    "area_id": load.area_id,
                    "gx":      load.gx,
                    "gy":      load.gy,
                    "gz":      load.gz,
                    "coord":   load.coord_system
                })
                                                                          
            elif hasattr(load, 'force'): 
                load_data.update({
                    "type": "member_point",
                    "element_id": load.element_id,
                    "force": load.force,
                    "dist": load.dist,
                    "is_rel": load.is_relative,
                    "coord": load.coord_system,
                    "dir": load.direction,
                    "l_type": load.load_type
                })
            
            elif hasattr(load, 'wx'):
                load_data.update({
                    "type": "member_dist",
                    "element_id": load.element_id,
                    "wx": load.wx, "wy": load.wy, "wz": load.wz,
                    "projected": getattr(load, 'projected', False),
                    "coord": getattr(load, 'coord_system', "Global"),
                    "is_tributary": getattr(load, 'is_tributary_generated', False),              
                    "distances": getattr(load, 'distances', [0, 0.25, 0.75, 1.0]),
                    "magnitudes": getattr(load, 'magnitudes', [0, 0, 0, 0]),
                    "is_relative": getattr(load, 'is_relative', True),
                    "load_direction": getattr(load, 'load_direction', "Gravity"),
                    "load_type": getattr(load, 'load_type', "Force")
                })
                
            elif isinstance(load, NodalLoad):
                load_data.update({
                    "type": "nodal",
                    "node_id": load.node_id,
                    "fx": load.fx, "fy": load.fy, "fz": load.fz,
                    "mx": load.mx, "my": load.my, "mz": load.mz
                })

            elif isinstance(load, GroundDisplacement):
                load_data.update({
                    "type": "ground_displacement",
                    "node_id": load.node_id,
                    "ux": load.ux, "uy": load.uy, "uz": load.uz,
                    "rx": load.rx, "ry": load.ry, "rz": load.rz
                })

            elif hasattr(load, 'cable_id'):
                load_data.update({
                    "type": "cable_dist",
                    "cable_id": load.cable_id,
                    "val": load.val,
                    "direction": load.direction,
                    "coord_system": load.coord_system,
                    "load_type": load.load_type
                })
            
            data["loads"].append(load_data)

        _p("Saving mass sources...")
        if hasattr(self, 'mass_sources'):
            for ms in self.mass_sources.values():
                ms_data = {
                    "name": ms.name,
                    "include_self_mass": ms.include_self_mass,
                    "include_patterns": ms.include_patterns,
                    "load_patterns": ms.load_patterns                       
                }
                data["mass_sources"].append(ms_data)

        _p("Saving response spectrum functions...")
        if hasattr(self, 'functions'):
            for func_name, func_data in self.functions.items():
                data["functions"].append(func_data)

        _p("Saving time history functions...")
        if hasattr(self, 'th_functions'):
            for func_name, func_data in self.th_functions.items():
                data["th_functions"].append(func_data)

        _p("Saving plot functions...")
        data["plot_functions"] = list(getattr(self, 'plot_functions', []))

        _p(f"Saving {len(self.area_sections)} area section(s)...")
        data["area_sections"] = [
            {
                "type":              s.__class__.__name__,                               
                "name":              s.name,
                "material":          s.material.name if s.material else None,
                "material_angle":    s.material_angle,
                "display_color":     s.display_color,
                "stiffness_modifiers": s.stiffness_modifiers,
                                     
                **( {"shell_type": s.shell_type,
                     "membrane_thickness": s.membrane_thickness,
                     "bending_thickness":  s.bending_thickness,
                     "thin_formulation": getattr(s, 'thin_formulation', "DKQ"),
                     "modeling_type": getattr(s, 'modeling_type', "True FEM (Shell)")}      
                    if isinstance(s, ShellSection) else {} ),
                                     
                **( {"plane_type": s.plane_type,
                     "incompatible_modes": s.incompatible_modes,
                     "thickness": s.thickness}
                    if isinstance(s, PlaneSection) else {} ),
                                      
                **( {"incompatible_modes": s.incompatible_modes,
                     "coord_system": s.coord_system,
                     "arc_degrees": s.arc_degrees}
                    if isinstance(s, AsolidSection) else {} ),
            }
            for s in self.area_sections.values()
        ]

        _p("Writing file to disk...")
        with open(filepath, 'w') as f:
                                                                                              
            n_items = (len(data["nodes"]) + len(data["elements"])
                       + len(data["area_elements"]) + len(data["loads"]))
            write_json(data, f, n_items=n_items)
        print(f"Model saved to {filepath}")

    def load_from_file(self, filepath, progress=None):
        """Clears current model and loads data from JSON"""
        def _p(msg):
            if progress: progress(msg)

        _p("Reading file from disk...")
        with open(filepath, 'r') as f:
            data = json.load(f)
            
        _p("Clearing current model data...")
        self.nodes.clear(); self.elements.clear(); self.materials.clear()
        self.sections.clear(); self.area_sections.clear(); self.load_patterns.clear(); self.loads.clear()
        self.hinge_properties.clear()
        self.frame_hinges.clear(); self._hinge_assign_counter = 1
        self.rebar_sizes = [] 
        self.tendon_sections.clear(); self.tendons.clear()              
        self.cable_sections.clear(); self.cables.clear()                   
        self.slabs.clear(); self.area_elements.clear(); self.constraints.clear()
        self.link_properties.clear(); self.links.clear()
        self._link_counter = 1
        self.load_combos.clear()
        self.functions = {}
        self.th_functions = {}
        self.plot_functions = []
        self.virtual_measurements = {}
        self.pushover_param_sets = []
        self.reference_curves = []
        self._node_counter = 1; self._elem_counter = 1; self._slab_counter = 1; self._area_elem_counter = 1
        self._cable_counter = 1

        _p("Loading project info & grid...")
        self.name = data["info"]["name"]
        self.saved_unit_system = data["info"].get("units", "kN, m, C")

        self.active_dofs = data["info"].get("active_dofs", [True, True, True, True, True, True])
        self.analysis_engine = data["info"].get("analysis_engine", "native")
        self.last_run_case = data["info"].get("last_run_case", None)
        self.show_analysis_log = data["info"].get("show_analysis_log", True)
        self.rebar_sizes = data.get("rebar_sizes", [])

        grid_data = data["grid"]

        self.grid.bubble_size = grid_data.get("bubble_size", 1.25)
        self.grid.bubble_alpha = grid_data.get("bubble_alpha", 1.0)
        self.grid.bubble_line_width = grid_data.get("bubble_line_width", 1.5)
        self.grid.bubble_ext_line_width = grid_data.get("bubble_ext_line_width", None)
        self.grid.bubble_extension = grid_data.get("bubble_extension", self.grid.bubble_size * 2.5)
        self.grid.set_style(grid_data.get("style"))
        
        if "x_lines" in grid_data:
            self.grid.x_lines = grid_data["x_lines"]; self.grid.y_lines = grid_data["y_lines"]; self.grid.z_lines = grid_data["z_lines"]
        else:
            self.grid.x_grids = grid_data["x"]; self.grid.y_grids = grid_data["y"]; self.grid.z_grids = grid_data["z"]

        _p(f"Loading {len(data.get('materials', []))} material(s)...")
        for m_data in data["materials"]:
            mat = Material(m_data["name"], m_data["E"], m_data["nu"], m_data["rho"], m_data["type"],
                           m_data.get("fy", 0), m_data.get("fu", 0),
                           m_data.get("fye", 0), m_data.get("fue", 0), m_data.get("grade", ""))
            mat.nonlinear = NonlinearMaterialData.from_dict(m_data.get("nonlinear"))
            mat.damping = MaterialDamping.from_dict(m_data.get("damping"))
            mat.derived_from = m_data.get("derived_from", "")
            self.add_material(mat)

        _p(f"Loading {len(data.get('sections', []))} frame section(s)...")
        for s_data in data["sections"]:
            mat = self.materials.get(s_data["mat_name"])
            if not mat: continue 
            sec = None
            if s_data["type"] == "rectangular":
                sec = RectangularSection(s_data["name"], mat, s_data["b"], s_data["h"])
            elif s_data["type"] == "i_section":
                saved_props = s_data.get("properties", None) 
                sec = ISection(
                    s_data["name"], mat, s_data["h"], s_data["w_top"], s_data["t_top"], 
                    s_data["w_bot"], s_data["t_bot"], s_data["t_web"], props=saved_props                  
                )
            elif s_data["type"] == "circular":
                sec = CircularSection(s_data["name"], mat, s_data["d"])
            elif s_data["type"] == "pipe":
                sec = PipeSection(s_data["name"], mat, s_data["d"], s_data["t"])
            elif s_data["type"] == "tube":
                sec = TubeSection(s_data["name"], mat, s_data["d"], s_data["b"], s_data["tf"], s_data["tw"])
            elif s_data["type"] == "trapezoidal":
                sec = TrapezoidalSection(s_data["name"], mat, s_data["d"], s_data["w_top"], s_data["w_bot"])
            elif s_data["type"] == "arbitrary":
                p = s_data["properties"]
                props_dict = {
                    'A': p["A"], 'J': p["J"], 'I33': p["I33"], 'I22': p["I22"],
                                                                     
                    'As2': p.get("Asy", p.get("As2", 0.0)), 
                    'As3': p.get("Asz", p.get("As3", 0.0)),
                    'theta_p': p.get("theta_p", 0.0),
                    'y_c': s_data.get("y_c", 0.0),
                    'z_c': s_data.get("z_c", 0.0),
                }
                vertices = [tuple(v) for v in s_data.get("vertices", [])]
                sec = ArbitrarySection(s_data["name"], mat, vertices, props_dict)
            elif s_data["type"] == "general":
                p = s_data["properties"]
                props_dict = {
                    'A': p["A"], 'J': p["J"], 'I33': p["I33"], 'I22': p["I22"],
                    'As2': p["As2"], 'As3': p["As3"],
                    'theta_p': p.get("theta_p", 0.0)
                }
                sec = GeneralSection(s_data["name"], mat, props_dict)

            if sec:
                if "color" in s_data: sec.color = tuple(s_data["color"])
                if "modifiers" in s_data: sec.modifiers = s_data["modifiers"]
                if "reinforcement" in s_data:
                    sec.reinforcement = ReinforcementData.from_dict(s_data["reinforcement"])
                self.add_section(sec)

        _p(f"Loading {len(data.get('hinge_properties', []))} hinge propert(y/ies)...")
        for hp_data in data.get("hinge_properties", []):
            hp = HingeProperty.from_dict(hp_data)
            if hp:
                self.add_hinge_property(hp)

        _AREA_CLS = {"ShellSection": ShellSection,
                     "PlaneSection": PlaneSection,
                     "AsolidSection": AsolidSection}
        
        _p(f"Loading {len(data.get('tendon_sections', []))} tendon section(s)...")
        for ts_data in data.get("tendon_sections", []):
            mat = self.materials.get(ts_data.get("mat_name"))
            if not mat: continue                                               
            
            ts = TendonSection(
                name=ts_data["name"],
                material=mat,
                modeling_option=ts_data.get("modeling_option", "Loads"),
                prestress_type=ts_data.get("prestress_type", "Prestress"),
                is_dia=ts_data.get("is_dia", False),
                dia=ts_data.get("dia", 0.0),
                area=ts_data.get("area", 0.0),
                J=ts_data.get("J", 0.0),
                I=ts_data.get("I", 0.0),
                As=ts_data.get("As", 0.0),
                color=tuple(ts_data.get("color", (0.0, 1.0, 1.0, 1.0)))
            )
            self.add_tendon_section(ts)

        _p(f"Loading {len(data.get('cable_sections', []))} cable section(s)...")
        from core.properties import CableSection
        for cs_data in data.get("cable_sections", []):
            mat = self.materials.get(cs_data.get("mat_name"))
            if not mat: continue
            
            cs = CableSection(
                name=cs_data["name"],
                material=mat,
                is_dia=cs_data.get("is_dia", False),
                dia=cs_data.get("dia", 0.0),
                area=cs_data.get("area", 0.0),
                J=cs_data.get("J", 0.0),
                I=cs_data.get("I", 0.0),
                As=cs_data.get("As", 0.0),
                color=tuple(cs_data.get("color", (1.0, 0.0, 0.0, 1.0)))
            )
            cs.modifiers = cs_data.get("modifiers", {"A": 1.0, "Mass": 1.0, "Weight": 1.0})
            self.cable_sections[cs.name] = cs

        _p("Loading area sections...")
        for d in data.get("area_sections", []):
            cls  = _AREA_CLS.get(d["type"])
            mat  = self.materials.get(d["material"])
            if cls is None: continue
            
            sec  = cls.__new__(cls)
            AreaSection.__init__(sec, d["name"], mat, d["material_angle"], d["display_color"])
            sec.stiffness_modifiers = d.get("stiffness_modifiers", sec.stiffness_modifiers)
            
            if cls is ShellSection:
                sec.shell_type         = d["shell_type"]
                sec.membrane_thickness = d["membrane_thickness"]
                sec.bending_thickness  = d["bending_thickness"]
                sec.thin_formulation   = d.get("thin_formulation", "DKQ")
            elif cls is PlaneSection:
                sec.plane_type         = d["plane_type"]
                sec.incompatible_modes = d["incompatible_modes"]
                sec.thickness          = d["thickness"]
            elif cls is AsolidSection:
                sec.incompatible_modes = d["incompatible_modes"]
                sec.coord_system       = d["coord_system"]
                sec.arc_degrees        = d["arc_degrees"]
                
            self.area_sections[sec.name] = sec

        _p(f"Loading {len(data.get('nodes', []))} nodes & boundary conditions...")
        for n_data in data["nodes"]:
            n_id = n_data["id"]
            node = self.add_node(n_data["x"], n_data["y"], n_data["z"])
            del self.nodes[node.id]; node.id = n_id; self.nodes[n_id] = node
            
            node.restraints = n_data["restraints"]
            if "diaphragm" in n_data: node.diaphragm_name = n_data["diaphragm"]
            
            if "spring_matrix" in n_data and n_data["spring_matrix"] is not None:
                node.spring_matrix = np.array(n_data["spring_matrix"])
            else:
                node.spring_matrix = None
                
            self._node_counter = max(self._node_counter, n_id + 1)

        _p("Loading diaphragm constraints...")
        if "constraints" in data:
            for c_data in data["constraints"]: 
                self.add_constraint(c_data["name"], c_data["axis"])

        for n in self.nodes.values():
            if getattr(n, 'diaphragm_name', None) and n.diaphragm_name not in self.constraints:
                print(f"🧹 Cleanup: Removing phantom constraint reference '{n.diaphragm_name}' from Node {n.id}")
                n.diaphragm_name = None

        self.slabs.clear(); 
        self.graphics_settings = data.get("graphics", {})
        self.name = data["info"]["name"]

        _p("Finalizing area section instances...")
        for s_data in data.get("area_sections", []):
            mat = self.materials.get(s_data["material"])
            if not mat: continue
            sec = None
            if s_data["type"] == "ShellSection":
                sec = ShellSection(
                    s_data["name"], mat,
                    shell_type=s_data.get("shell_type", "Shell - Thin"),
                    membrane_thickness=s_data.get("membrane_thickness", 0.1),
                    bending_thickness=s_data.get("bending_thickness", 0.1),
                    material_angle=s_data.get("material_angle", 0.0),
                    display_color=s_data.get("display_color", "#FF00FF")
                )
                sec.modeling_type = s_data.get("modeling_type", "True FEM (Shell)")      
                sec.thin_formulation = s_data.get("thin_formulation", "DKQ")
            elif s_data["type"] == "PlaneSection":
                sec = PlaneSection(
                    s_data["name"], mat,
                    plane_type=s_data.get("plane_type", "Plane-Stress"),
                    incompatible_modes=s_data.get("incompatible_modes", True),
                    thickness=s_data.get("thickness", 0.1),
                    material_angle=s_data.get("material_angle", 0.0),
                    display_color=s_data.get("display_color", "#FF00FF")
                )
                sec.modeling_type = s_data.get("modeling_type", "True FEM (Plane)")      
            elif s_data["type"] == "AsolidSection":
                sec = AsolidSection(
                    s_data["name"], mat,
                    incompatible_modes=s_data.get("incompatible_modes", True),
                    coord_system=s_data.get("coord_system", "GLOBAL"),
                    arc_degrees=s_data.get("arc_degrees", 0.0),
                    material_angle=s_data.get("material_angle", 0.0),
                    display_color=s_data.get("display_color", "#FFFF00")
                )
            if sec:
                self.add_area_section(sec)

        _p(f"Loading {len(data.get('elements', []))} frame element(s) & releases...")
        for el_data in data["elements"]:
            n1 = self.nodes.get(el_data["n1_id"])
            n2 = self.nodes.get(el_data["n2_id"])
            sec = self.sections.get(el_data["sec_name"])
            
            if n1 and n2 and sec:
                beta = el_data.get("beta", 0.0)
                el = self.add_element(n1, n2, sec, beta)
                el.releases_i = el_data.get("rel_i", [False]*6)
                el.releases_j = el_data.get("rel_j", [False]*6)
                
                del self.elements[el.id]; el.id = el_data["id"]; self.elements[el.id] = el
                self._elem_counter = max(self._elem_counter, el.id + 1)
                
                if "cardinal" in el_data:
                    el.cardinal_point = el_data["cardinal"]
                if "off_i" in el_data:
                    el.joint_offset_i = np.array(el_data["off_i"])
                if "off_j" in el_data:
                    el.joint_offset_j = np.array(el_data["off_j"])

                el.end_offset_i = el_data.get("end_off_i", 0.0)
                el.end_offset_j = el_data.get("end_off_j", 0.0)
                el.rigid_zone_factor = el_data.get("rz_factor", 0.0)

        _p(f"Loading {len(data.get('frame_hinges', []))} frame hinge assignment(s)...")
        for fh_data in data.get("frame_hinges", []):
            if fh_data.get("element_id") in self.elements:
                fh = FrameHingeAssignment.from_dict(fh_data)
                self.frame_hinges[fh.id] = fh
                self._hinge_assign_counter = max(self._hinge_assign_counter, fh.id + 1)

        _p(f"Loading {len(data.get('tendons', []))} tendon object(s)...")
        for t_data in data.get("tendons", []):
            n1 = self.nodes.get(t_data["n1_id"])
            n2 = self.nodes.get(t_data["n2_id"])
            tsec = self.tendon_sections.get(t_data["sec_name"])

            if n1 and n2 and tsec:
                t = TendonObject(t_data["id"], n1, n2, tsec,
                                  host_element_ids=t_data.get("host_element_ids", []),
                                  local_axis_angle=t_data.get("local_axis_angle", 0.0),
                                  plane=t_data.get("plane", "1-2"))

                t.modeling_option = t_data.get("modeling_option", tsec.modeling_option)
                t.prestress_type = t_data.get("prestress_type", tsec.prestress_type)
                if "layout_points" in t_data:
                    t.layout_points = t_data["layout_points"]
                t.max_discretization_length = t_data.get("max_discretization_length", 1.524)
                t.coordinate_system = t_data.get("coordinate_system", "Local")
                if "color" in t_data:
                    t.color = tuple(t_data["color"])
                t.loads = t_data.get("loads", [])

                self.tendons[t.id] = t
                self._tendon_counter = max(self._tendon_counter, t.id + 1)

        _p(f"Loading {len(data.get('cables', []))} cable(s)...")
        from core.mesh import CableObject
        for c_data in data.get("cables", []):
            n1 = self.nodes.get(c_data["n1_id"])
            n2 = self.nodes.get(c_data["n2_id"])
            csec = self.cable_sections.get(c_data.get("sec_name"))

            if n1 and n2 and csec:
                c = CableObject(c_data["id"], n1, n2, csec)
                
                c.model_as_straight_frame = c_data.get("model_as_straight_frame", True)
                c.number_of_segments = c_data.get("number_of_segments", 1)
                c.undeformed_length = c_data.get("undeformed_length", None)
                c.is_active = c_data.get("is_active", True)
                
                c.target_type = c_data.get("target_type", "Cable - Undeformed Length")
                c.target_value = c_data.get("target_value", c.undeformed_length)
                c.added_weight = c_data.get("added_weight", 0.0)
                c.projected_load = c_data.get("projected_load", 0.0)
                
                self.cables[c.id] = c
                self._cable_counter = max(self._cable_counter, c.id + 1)

        _p("Loading link properties...")
        for lp_data in data.get("link_properties", []):
            self.link_properties[lp_data["name"]] = {
                "mass": lp_data.get("mass", 0.0),
                "weight": lp_data.get("weight", 0.0),
                "r1": lp_data.get("r1", 0.0),
                "r2": lp_data.get("r2", 0.0),
                "r3": lp_data.get("r3", 0.0),
                "is_fixed": lp_data.get("is_fixed", [False]*6),
                "stiffness": np.array(lp_data.get("stiffness", np.zeros((6,6)))),
                "damping": np.array(lp_data.get("damping", np.zeros((6,6))))
            }

        _p("Loading link elements...")
        for link_data in data.get("links", []):
            lid = link_data["id"]
            self.links[lid] = {
                "id": lid,
                "prop_name": link_data["prop_name"],
                "nodes": link_data["nodes"],
                "beta": link_data.get("beta", 0.0)
            }
            self._link_counter = max(self._link_counter, lid + 1)

        _p("Loading area elements...")
        if "area_elements" in data:
            for ae_data in data["area_elements"]:
                ae_nodes = [self.nodes[nid] for nid in ae_data["node_ids"] if nid in self.nodes]
                sec = self.area_sections.get(ae_data["sec_name"])
                
                if len(ae_nodes) >= 3 and sec:
                    new_ae = self.add_area_element(ae_nodes, sec)
                    del self.area_elements[new_ae.id]
                    new_ae.id = ae_data["id"]
                    new_ae.insertion_offset = ae_data.get("insertion_offset", 0.0)
                    new_ae.solver_mesh = ae_data.get("solver_mesh")
                    self.area_elements[new_ae.id] = new_ae
                    self._area_elem_counter = max(self._area_elem_counter, new_ae.id + 1)

        _p("Loading slabs...")
        if "slabs" in data:
            for sl_data in data["slabs"]:
                slab_nodes = []
                for nid in sl_data["node_ids"]:
                    if nid in self.nodes: slab_nodes.append(self.nodes[nid])
                if len(slab_nodes) >= 3:
                    new_slab = self.add_slab(slab_nodes, sl_data["thick"])
                    del self.slabs[new_slab.id]; new_slab.id = sl_data["id"]; self.slabs[new_slab.id] = new_slab
                    self._slab_counter = max(self._slab_counter, new_slab.id + 1)

        _p("Loading load cases...")
        if "load_cases" in data:
            for lc_data in data["load_cases"]:
                name = lc_data["name"]
                c_type = lc_data.get("type", "Linear Static")
                
                new_lc = LoadCase(name, c_type)

                raw_loads = lc_data.get("loads", [])
                new_lc.loads = [tuple(item) for item in raw_loads]

                new_lc.mass_source = lc_data.get("mass_source", "Default")
                new_lc.geom_nonlin = lc_data.get("geom_nonlin", "None")

                nl_params = lc_data.get("nl_params", {})
                new_lc.max_total_steps = nl_params.get("max_total_steps", 200)
                new_lc.max_null_steps = nl_params.get("max_null_steps", 50)
                new_lc.use_event_stepping = nl_params.get("use_event_stepping", True)
                new_lc.event_lumping_tol = nl_params.get("event_lumping_tol", 0.01)
                new_lc.max_events_per_step = nl_params.get("max_events_per_step", 24)
                new_lc.use_iteration = nl_params.get("use_iteration", True)
                new_lc.max_const_stiff_iter = nl_params.get("max_const_stiff_iter", 10)
                new_lc.max_nr_iter = nl_params.get("max_nr_iter", 40)
                new_lc.iter_conv_tol = nl_params.get("iter_conv_tol", 1e-4)
                new_lc.use_line_search = nl_params.get("use_line_search", False)
                new_lc.tf_max_iter = nl_params.get("tf_max_iter", 10)
                new_lc.tf_conv_tol = nl_params.get("tf_conv_tol", 0.01)
                new_lc.tf_accel_factor = nl_params.get("tf_accel_factor", 1.0)
                new_lc.continue_if_no_converge = nl_params.get("continue_if_no_converge", False)
                new_lc.use_fd_tangent = nl_params.get("use_fd_tangent", False)
                new_lc.formulation = nl_params.get("formulation", "Corotational")
                new_lc.corot_type = nl_params.get("corot_type", "Commercial Compatibility")
                new_lc.results_saved = nl_params.get("results_saved", "Final State Only")
                new_lc.min_saved_states = nl_params.get("min_saved_states", 1)
                new_lc.max_saved_states = nl_params.get("max_saved_states", 100)
                new_lc.save_positive_disp_only = nl_params.get("save_positive_disp_only", False)
                new_lc.continue_from_case = nl_params.get("continue_from_case", None)
                new_lc.load_application = nl_params.get("load_application", "Full Load")
                new_lc.disp_control_node_id = nl_params.get("disp_control_node_id", None)
                new_lc.disp_control_dof = nl_params.get("disp_control_dof", "U1")
                new_lc.disp_control_magnitude = nl_params.get("disp_control_magnitude", 0.1)
                new_lc.disp_control_tol = nl_params.get("disp_control_tol", 1e-6)
                                                                                            
                new_lc.hinge_snap = nl_params.get("hinge_snap", nl_params.get("sap_hinge_snap", True))
                new_lc.hinge_snap_scope = nl_params.get("hinge_snap_scope", nl_params.get("sap_hinge_snap_scope", "tension"))
                new_lc.stop_on_fiber_failure = nl_params.get("stop_on_fiber_failure", False)
                new_lc.residual_stiffness = nl_params.get("residual_stiffness", 1e-8)
                new_lc.min_step_frac = nl_params.get("min_step_frac", 1e-4)
                new_lc.max_event_probes = nl_params.get("max_event_probes", 12)
                new_lc.auto_cutback = nl_params.get("auto_cutback", True)
                new_lc.max_step_attempts = nl_params.get("max_step_attempts", 0)

                new_lc.opensees = {**default_opensees_block(), **(lc_data.get("opensees") or {})}

                raw_rsa = lc_data.get("rsa_loads", [])
                new_lc.rsa_loads = [tuple(item) for item in raw_rsa]

                new_lc.modal_comb = lc_data.get("modal_comb", "SRSS")
                new_lc.dir_comb = lc_data.get("dir_comb", "SRSS")
                new_lc.p_delta = lc_data.get("p_delta", False)
                new_lc.num_modes = lc_data.get("num_modes", 12)
                new_lc.modal_fiber_hinges = lc_data.get("modal_fiber_hinges", False)
                new_lc.modal_damping = lc_data.get("modal_damping", 0.05)
                new_lc.damping = lc_data.get("ltha_damping", 0.05)
                new_lc.ltha_loads = [tuple(x) for x in lc_data.get("ltha_loads", [])]

                self.load_cases[name] = new_lc
        else:
                                            
            self.create_default_cases()

        _p("Loading load combinations...")
        if "load_combos" in data:
            for combo_data in data["load_combos"]:
                new_combo = LoadCombination(combo_data["name"], combo_data.get("combo_type", "Linear Add"))
                raw_cases = combo_data.get("cases", [])
                new_combo.cases = [tuple(item) for item in raw_cases]
                self.load_combos[new_combo.name] = new_combo

        _p("Loading mass sources...")
        if "mass_sources" in data:
                                                     
            if not hasattr(self, 'mass_sources'):
                self.mass_sources = {}

            for ms_data in data["mass_sources"]:
                new_ms = MassSource(ms_data["name"])
                new_ms.include_self_mass = ms_data["include_self_mass"]
                new_ms.include_patterns = ms_data["include_patterns"]
                                                                             
                new_ms.load_patterns = [tuple(x) for x in ms_data["load_patterns"]]

                self.mass_sources[new_ms.name] = new_ms

        _p("Loading load patterns & seismic data...")
        if "load_patterns" in data:
            for lp_data in data["load_patterns"]: 
                self.add_load_pattern(lp_data["name"], lp_data["type"], lp_data["sw_mult"])
                
                lp = self.load_patterns[lp_data["name"]]
                lp.auto_lateral = lp_data.get("auto_lateral", "None")

                if "seismic_data" in lp_data:
                    sd = UserSeismicData()
                    sd.eccentricity = lp_data["seismic_data"]["eccentricity"]
                    sd.diaphragm_loads = lp_data["seismic_data"]["diaphragm_loads"]
                    lp.seismic_data = sd
                    
                if "tsc_data" in lp_data:
                    tsc = TSC2018Data()
                    t_data = lp_data["tsc_data"]
                    tsc.direction = t_data.get("direction", "X")
                    tsc.eccentricity = t_data.get("eccentricity", 0.05)
                    tsc.period_method = t_data.get("period_method", "Approx")
                    tsc.ct = t_data.get("ct", 0.075)
                    tsc.user_t = t_data.get("user_t", 0.0)
                    tsc.ss = t_data.get("ss", 0.0)
                    tsc.s1 = t_data.get("s1", 0.0)
                    tsc.tl = t_data.get("tl", 6.0)
                    tsc.site_class = t_data.get("site_class", "ZB")
                    tsc.r = t_data.get("r", 8.0)
                    tsc.d = t_data.get("d", 3.0)
                    tsc.importance = t_data.get("importance", 1.0)
                    lp.tsc_data = tsc
        else: 
            self.add_load_pattern("DEAD", "DEAD", 1.0)
             
        _p("Loading response spectrum functions...")
        if "functions" in data:
            for func_data in data["functions"]:
                f_name = func_data["name"]
                self.functions[f_name] = func_data

        _p("Loading time history functions...")
        if "th_functions" in data:
            for func_data in data["th_functions"]:
                f_name = func_data.get("name", "THFUNC")
                self.th_functions[f_name] = func_data

        _p("Loading plot functions...")
        self.plot_functions = data.get("plot_functions", [])

        _p("Loading virtual measurements...")                 
        self.virtual_measurements = data.get("virtual_measurements", {})

        _p("Loading pushover parameter sets...")
        self.pushover_param_sets = [
            {**self.make_pushover_param_set(ps.get("name", "PO")),
             **{k: v for k, v in ps.items() if k != "case_name"}}                             
            for ps in (data.get("pushover_param_sets") or []) if isinstance(ps, dict)
        ]
        if not self.pushover_param_sets:
            self.pushover_param_sets = [self.make_pushover_param_set("PO1")]
        self.reference_curves = sanitize_loaded_curves(data.get("reference_curves"))

        _p(f"Loading {len(data.get('loads', []))} load assignment(s)...")
        if "loads" in data:
            for load_data in data["loads"]:
                if load_data.get('_is_tendon_auto'):                      
                    continue                                             
                
                pattern_name = load_data["pattern"]
                l_type = load_data.get("type", "nodal")                         
                
                if l_type == "member": l_type = "member_dist"

                if l_type == "nodal":
                    new_load = NodalLoad(load_data["node_id"], pattern_name, 
                                         load_data["fx"], load_data["fy"], load_data["fz"], 
                                         load_data["mx"], load_data["my"], load_data["mz"])
                    self.loads.append(new_load)

                elif l_type == "ground_displacement":
                    new_disp = GroundDisplacement(
                        load_data["node_id"], pattern_name, 
                        load_data.get("ux", 0), load_data.get("uy", 0), load_data.get("uz", 0), 
                        load_data.get("rx", 0), load_data.get("ry", 0), load_data.get("rz", 0)
                    )
                    self.loads.append(new_disp)

                elif l_type == "member_dist":
                    coord = load_data.get("coord", "Global")
                    proj = load_data.get("projected", False)
                    new_load = MemberLoad(
                        load_data["element_id"], pattern_name, 
                        load_data.get("wx", 0), load_data.get("wy", 0), load_data.get("wz", 0),
                        projected=proj, coord_system=coord,
                        distances=load_data.get("distances", [0, 0.25, 0.75, 1]),
                        magnitudes=load_data.get("magnitudes", [0, 0, 0, 0]),
                        is_relative=load_data.get("is_relative", True),
                        load_direction=load_data.get("load_direction", "Gravity"),
                        load_type=load_data.get("load_type", "Force")
                    )
                    new_load.is_tributary_generated = load_data.get("is_tributary", False)              
                    self.loads.append(new_load)

                elif l_type == "member_point":
                                   
                    new_load = MemberPointLoad(
                        load_data["element_id"], pattern_name,
                        load_data["force"], load_data["dist"],
                        load_data["is_rel"], load_data["coord"],
                        load_data["dir"], load_data.get("l_type", "Force")
                    )
                    self.loads.append(new_load)

                elif l_type == "area_gravity":
                    aid = load_data.get("area_id")
                    if aid in self.area_elements:
                        new_load = AreaGravityLoad(
                            aid, pattern_name,
                            load_data.get("coord", "GLOBAL"),
                            load_data.get("gx", 0.0),
                            load_data.get("gy", 0.0),
                            load_data.get("gz", 0.0)
                        )
                        self.loads.append(new_load)

                elif l_type == "area_uniform":
                    aid = load_data.get("area_id")
                    if aid in self.area_elements:
                        new_load = AreaUniformLoad(
                            aid, pattern_name,
                            load_data.get("coord", "GLOBAL"),
                            load_data.get("direction", "Gravity"),
                            load_data.get("load", 0.0)
                        )
                        self.loads.append(new_load)

                elif l_type == "cable_dist":
                    from core.loads import CableDistributedLoad
                    new_load = CableDistributedLoad(
                        cable_id=load_data["cable_id"],
                        pattern_name=pattern_name,
                        val=load_data["val"],
                        direction=load_data["direction"],
                        coord_sys=load_data["coord_system"],
                        load_type=load_data["load_type"]
                    )
                    self.loads.append(new_load)
        
        _p("Load complete.")

        self.generate_tendon_loads()

        print(f"Model loaded from {filepath}")

    def generate_tendon_loads(self):
        """
        Live-model equivalent of DataManager._generate_tendon_loads().

        Converts tendons modeled as 'Loads' into the same dict-shaped load
        records the solver already generates, and injects them into
        self.loads -- so the diagram/recovery path (MemberAnalyzer in
        spy_dialogs.py) sees the same loads the solver saw when it baked
        the FEF into matrices.json.

        Call this after load_from_file() (done automatically above), and
        again any time tendon geometry or tendon loads are edited
        (tendon_geometry_dialog.py's save path) so self.loads stays in sync.
        """
        from core.prestress.tendon_evaluator import TendonEvaluator
        from element_library import get_rotation_matrix
        import math
        import numpy as np

        self.loads = [ld for ld in self.loads
                      if not (isinstance(ld, dict) and ld.get('_is_tendon_auto'))]

        active_pattern_names = set(self.load_patterns.keys())

        for t in self.tendons.values():
            if getattr(t, 'modeling_option', 'Loads') != 'Loads':
                continue

            active_loads = [ld for ld in getattr(t, 'loads', [])
                             if ld['pattern'] in active_pattern_names]
            if not active_loads:
                continue

            layout_pts = t.layout_points
            if not layout_pts:
                continue
            total_length = max(p['coord1'] for p in layout_pts)

            for load_data in active_loads:
                pat_name = load_data['pattern']
                evaluator = TendonEvaluator(layout_pts, t.tendon_section, load_data, total_length)

                current_x = 0.0
                for host_id in t.host_element_ids:
                    host_el = self.elements.get(host_id)
                    if not host_el:
                        continue
                    el_len = host_el.length()

                    import math
                    
                    max_disc = getattr(t, 'max_discretization_length', 1.524)
                    if max_disc < 1e-3: max_disc = 1.524
                    
                    num_segments = math.ceil(el_len / max_disc)
                    num_samples = int(num_segments) + 1
                    
                    dists = np.linspace(0, 1.0, num_samples)
                    mags_2 = []                                      
                    mags_3 = []                                      

                    for d in dists:
                        local_x = current_x + (d * el_len)
                        
                        eval_x = local_x
                        if d == 0.0:
                            eval_x += 1e-6
                        elif d == 1.0:
                            eval_x -= 1e-6
                            
                        P_x = evaluator.get_force(eval_x)
                        mags_2.append(1.0 * P_x * evaluator.get_curvature(eval_x))
                        mags_3.append(-1.0 * P_x * evaluator.get_curvature_z(eval_x))

                    if any(abs(m) > 1e-9 for m in mags_2):
                        self.loads.append({
                            'type': 'member_dist', 'pattern': pat_name, 'element_id': host_id,
                            'load_direction': 'Local-3', 'coord': 'Local', 'projected': False,
                            'distances': dists.tolist(), 'magnitudes': mags_2, 'is_relative': True,
                            '_is_tendon_auto': True
                        })
                    if any(abs(m) > 1e-9 for m in mags_3):
                        self.loads.append({
                            'type': 'member_dist', 'pattern': pat_name, 'element_id': host_id,
                            'load_direction': 'Local-2', 'coord': 'Local', 'projected': False,
                            'distances': dists.tolist(), 'magnitudes': mags_3, 'is_relative': True,
                            '_is_tendon_auto': True
                        })
                    current_x += el_len

                for end_type, force_val, host_id in [
                    ('I-End', evaluator.get_force(0.0), t.host_element_ids[0]),
                    ('J-End', evaluator.get_force(total_length), t.host_element_ids[-1])
                ]:
                    if force_val <= 1e-9:
                        continue

                    host_el = self.elements.get(host_id)
                    if not host_el:
                        continue

                    x_eval = 0.0 if end_type == 'I-End' else total_length
                    m2 = evaluator.get_slope(x_eval)
                    m3 = evaluator.get_slope_z(x_eval)
                    e2 = evaluator.get_eccentricity(x_eval)[1]
                    e3 = evaluator.get_eccentricity(x_eval)[2]

                    t_vec = np.array([1.0, m2, m3])
                    t_vec = t_vec / np.linalg.norm(t_vec)

                    sign = 1.0 if end_type == 'I-End' else -1.0
                    Fx = sign * force_val * t_vec[0]
                    f2 = sign * force_val * t_vec[1]
                    f3 = sign * force_val * t_vec[2]

                    F_local = np.zeros(3)
                    F_local[0] = Fx
                    F_local[2] = f2
                    F_local[1] = -f3
                    ecc_vec = np.array([0.0, -e3, e2])
                    M_local = np.cross(ecc_vec, F_local)

                    p1 = host_el.node_i.get_coords()
                    p2 = host_el.node_j.get_coords()
                    theta_p = getattr(host_el.section, 'theta_p', 0.0)
                    beta_eff = host_el.beta_angle - np.degrees(theta_p)

                    R_3x3 = get_rotation_matrix(p1, p2, beta_eff)
                    F_global = R_3x3.T @ F_local
                    M_global = R_3x3.T @ M_local

                    target_node = host_el.node_i if end_type == 'I-End' else host_el.node_j

                    self.loads.append({
                        'type': 'nodal', 'pattern': pat_name, 'node_id': target_node.id,
                        'fx': float(F_global[0]), 'fy': float(F_global[1]), 'fz': float(F_global[2]),
                        'mx': float(M_global[0]), 'my': float(M_global[1]), 'mz': float(M_global[2]),
                        '_is_tendon_auto': True
                    })

                for i in range(1, len(layout_pts) - 1):
                    x_kink = layout_pts[i]['coord1']
                    P_kink = evaluator.get_force(x_kink)

                    m2_before = evaluator.get_slope(x_kink - 1e-6)
                    m2_after  = evaluator.get_slope(x_kink + 1e-6)
                    m3_before = evaluator.get_slope_z(x_kink - 1e-6)
                    m3_after  = evaluator.get_slope_z(x_kink + 1e-6)

                    F_kink_2 = 1.0 * P_kink * (math.sin(math.atan(m2_after)) - math.sin(math.atan(m2_before)))
                    F_kink_3 = -1.0 * P_kink * (math.sin(math.atan(m3_after)) - math.sin(math.atan(m3_before)))

                    if abs(F_kink_2) > 1e-9 or abs(F_kink_3) > 1e-9:
                                                                                                     
                        t_vx, t_vy, t_vz = t.get_local_axes()
                        R_tendon = np.array([t_vx, t_vy, t_vz])
                        F_kink_local_tendon = np.array([0.0, F_kink_3, F_kink_2])
                        F_kink_global = R_tendon.T @ F_kink_local_tendon

                        current_x = 0.0
                        for host_id in t.host_element_ids:
                            host_el = self.elements.get(host_id)
                            if not host_el:
                                continue
                            el_len = host_el.length()

                            if current_x - 1e-5 <= x_kink <= current_x + el_len + 1e-5:
                                rel_dist = max(0.0, min(1.0, (x_kink - current_x) / el_len))

                                p1h = host_el.node_i.get_coords()
                                p2h = host_el.node_j.get_coords()
                                theta_p_h = getattr(host_el.section, 'theta_p', 0.0)
                                beta_eff_h = host_el.beta_angle - np.degrees(theta_p_h)
                                R_host = get_rotation_matrix(p1h, p2h, beta_eff_h)

                                F_kink_host_local = R_host @ F_kink_global

                                F_kink_2_host = F_kink_host_local[1]
                                F_kink_3_host = F_kink_host_local[2]

                                if abs(F_kink_2_host) > 1e-9:
                                    self.loads.append({
                                        'type': 'member_point', 'pattern': pat_name, 'element_id': host_id,
                                        'dir': '2', 'force': F_kink_2_host, 'dist': rel_dist, 'is_rel': True,
                                        'coord': 'Local', '_is_tendon_auto': True
                                    })
                                if abs(F_kink_3_host) > 1e-9:
                                    self.loads.append({
                                        'type': 'member_point', 'pattern': pat_name, 'element_id': host_id,
                                        'dir': '3', 'force': F_kink_3_host, 'dist': rel_dist, 'is_rel': True,
                                        'coord': 'Local', '_is_tendon_auto': True
                                    })
                                break
                            current_x += el_len

    def add_constraint(self, name, axis="Z"):
        """Defines a new Rigid Diaphragm (e.g., 'D1')"""

        if name not in self.constraints:
            self.constraints[name] = RigidDiaphragm(name, axis)

    def replicate_selection(self, node_ids, elem_ids, dx, dy, dz, num_copies, delete_original=False):
        """
        Replicates selected nodes and elements linearly.
        Features:
        - Copies Restraints, Releases, and ALL LOADS (Point/Dist/Nodal).
        - Copies Advanced Attributes (Cardinal Points, Rigid Offsets).
        - Smart Diaphragm Logic.
        """
                                                                                    
        involved_node_ids = set(node_ids)
        for eid in elem_ids:
            if eid in self.elements:
                el = self.elements[eid]
                involved_node_ids.add(el.node_i.id)
                involved_node_ids.add(el.node_j.id)
        
        node_load_map = {}
        elem_load_map = {}
        
        for load in self.loads:
            if hasattr(load, 'node_id'):
                if load.node_id not in node_load_map: node_load_map[load.node_id] = []
                node_load_map[load.node_id].append(load)
            elif hasattr(load, 'element_id'):
                if load.element_id not in elem_load_map: elem_load_map[load.element_id] = []
                elem_load_map[load.element_id].append(load)

        for i in range(1, num_copies + 1):
            node_map = {}                                  

            for nid in involved_node_ids:
                if nid not in self.nodes: continue
                original_node = self.nodes[nid]
                
                nx = original_node.x + (dx * i)
                ny = original_node.y + (dy * i)
                nz = original_node.z + (dz * i)
                
                new_node = self.get_or_create_node(nx, ny, nz)
                node_map[nid] = new_node
                
                new_node.restraints = original_node.restraints[:] 
                
                if abs(dz) > 0.001:
                    new_node.diaphragm_name = None 
                else:
                    new_node.diaphragm_name = original_node.diaphragm_name

                if nid in node_load_map:
                    for old_load in node_load_map[nid]:
                        if isinstance(old_load, NodalLoad):
                            self.assign_joint_load(
                                new_node.id, 
                                old_load.pattern_name,
                                old_load.fx, old_load.fy, old_load.fz,
                                old_load.mx, old_load.my, old_load.mz,
                                mode="add"
                            )
                        elif isinstance(old_load, GroundDisplacement):
                            self.assign_ground_displacement(
                                new_node.id, 
                                old_load.pattern_name,
                                old_load.ux, old_load.uy, old_load.uz,
                                old_load.rx, old_load.ry, old_load.rz,
                                mode="add"
                            )

            for eid in elem_ids:
                if eid not in self.elements: continue
                original_elem = self.elements[eid]
                
                if original_elem.node_i.id not in node_map or original_elem.node_j.id not in node_map:
                    continue 
                
                new_n1 = node_map[original_elem.node_i.id]
                new_n2 = node_map[original_elem.node_j.id]
                
                new_elem = self.add_element(new_n1, new_n2, original_elem.section, original_elem.beta_angle)
                
                new_elem.releases_i = original_elem.releases_i[:]
                new_elem.releases_j = original_elem.releases_j[:]
                
                new_elem.cardinal_point = original_elem.cardinal_point
                if hasattr(original_elem, 'joint_offset_i'):
                    new_elem.joint_offset_i = original_elem.joint_offset_i.copy()
                if hasattr(original_elem, 'joint_offset_j'):
                    new_elem.joint_offset_j = original_elem.joint_offset_j.copy()

                new_elem.end_offset_i = getattr(original_elem, 'end_offset_i', 0.0)
                new_elem.end_offset_j = getattr(original_elem, 'end_offset_j', 0.0)
                new_elem.rigid_zone_factor = getattr(original_elem, 'rigid_zone_factor', 0.0)

                if eid in elem_load_map:
                    for old_load in elem_load_map[eid]:
                        
                        if hasattr(old_load, 'wx'):
                             self.assign_member_load(
                                new_elem.id,
                                old_load.pattern_name,
                                old_load.wx, old_load.wy, old_load.wz,
                                projected=getattr(old_load, 'projected', False),
                                coord_system=getattr(old_load, 'coord_system', "Global"),
                                mode="add"
                            )
                        
                        elif hasattr(old_load, 'force'):
                            self.assign_member_point_load(
                                new_elem.id,
                                old_load.pattern_name,
                                old_load.force,
                                old_load.dist,
                                old_load.is_relative,
                                old_load.coord_system,
                                old_load.direction,
                                getattr(old_load, 'load_type', "Force"),
                                mode="add"
                            )

        if delete_original:
            for eid in elem_ids:
                if eid in self.elements:
                    self.remove_element(eid) 
            
            for nid in node_ids:
                 self._cleanup_orphan_node(nid)

        print(f"Replicated {len(elem_ids)} frames and {len(node_ids)} joints {num_copies} times.")
    
    def merge_nodes(self, tolerance=0.001):
        """
        Merges nodes that are within a specific distance of each other.
        Remaps elements to the 'master' node and deletes 'slave' nodes.
        Returns the number of nodes deleted.
        """
                                                                    
        sorted_nodes = sorted(self.nodes.values(), key=lambda n: (n.x, n.y, n.z))
        
        remap_dict = {}                             
        nodes_to_delete = set()
        
        for i in range(len(sorted_nodes)):
            master = sorted_nodes[i]
            if master.id in nodes_to_delete: continue                                   
            
            for j in range(i + 1, len(sorted_nodes)):
                slave = sorted_nodes[j]
                
                if (slave.x - master.x) > tolerance: break
                
                dist = ((master.x - slave.x)**2 + (master.y - slave.y)**2 + (master.z - slave.z)**2)**0.5
                
                if dist < tolerance:
                                        
                    remap_dict[slave.id] = master.id
                    nodes_to_delete.add(slave.id)
                    
        if not remap_dict:
            print("No duplicate nodes found.")
            return 0

        for el in self.elements.values():
            if el.node_i.id in remap_dict:
                el.node_i = self.nodes[remap_dict[el.node_i.id]]
            if el.node_j.id in remap_dict:
                el.node_j = self.nodes[remap_dict[el.node_j.id]]
        
        for slab in self.slabs.values():
            new_nodes = []
            for n in slab.nodes:
                if n.id in remap_dict:
                    new_nodes.append(self.nodes[remap_dict[n.id]])
                else:
                    new_nodes.append(n)
            slab.nodes = new_nodes

        for ae in self.area_elements.values():
            ae.nodes = [
                self.nodes[remap_dict[n.id]] if n.id in remap_dict else n
                for n in ae.nodes
            ]

        for load in self.loads:
            if hasattr(load, 'node_id') and load.node_id in remap_dict:
                load.node_id = remap_dict[load.node_id]

        for nid in nodes_to_delete:
            del self.nodes[nid]

        print(f"Merged {len(nodes_to_delete)} duplicate nodes.")
        return len(nodes_to_delete)

    def rebuild_mesh_links(self):
        """
        Safety net to fix 'detached pointers' AND 'dictionary order scrambling' 
        after undo/redo operations.
        """
                                                     
        self.nodes = {k: self.nodes[k] for k in sorted(self.nodes.keys())}
        self.elements = {k: self.elements[k] for k in sorted(self.elements.keys())}
        self.slabs = {k: self.slabs[k] for k in sorted(self.slabs.keys())}
        self.area_elements = {k: self.area_elements[k] for k in sorted(self.area_elements.keys())}

        for el in self.elements.values():
            if el.node_i.id in self.nodes:
                el.node_i = self.nodes[el.node_i.id]
            if el.node_j.id in self.nodes:
                el.node_j = self.nodes[el.node_j.id]
                
        for slab in self.slabs.values():
            relinked_nodes = []
            for n in slab.nodes:
                if n.id in self.nodes:
                    relinked_nodes.append(self.nodes[n.id])
                else:
                    relinked_nodes.append(n)
            slab.nodes = relinked_nodes

        for ae in self.area_elements.values():
            ae.nodes = [
                self.nodes[n.id] if n.id in self.nodes else n
                for n in ae.nodes
            ]

    def get_or_create_node(self, x, y, z, tol=0.005):
        """
        Prevents duplicates by checking if a node exists within tolerance.
        """
        for node in self.nodes.values():
            dist = ((node.x - x)**2 + (node.y - y)**2 + (node.z - z)**2)**0.5
            if dist < tol:
                return node
        return self.add_node(x, y, z)

    def remove_element(self, element_id):
        """
        Deletes an element, its assigned loads, and cleans up valid orphan nodes.
        """
        if element_id not in self.elements: return
        
        el = self.elements[element_id]
        n1_id = el.node_i.id
        n2_id = el.node_j.id
        
        del self.elements[element_id]
        
        self.loads = [
            load for load in self.loads 
            if not (hasattr(load, 'element_id') and load.element_id == element_id)
        ]
        
        self._cleanup_orphan_node(n1_id)
        self._cleanup_orphan_node(n2_id)

    def _cleanup_orphan_node(self, node_id):
        """
        Deletes a node only if it is completely unused.
        Also removes any Nodal Loads assigned to it.
        """
        if node_id not in self.nodes: return
        
        for el in self.elements.values():
            if el.node_i.id == node_id or el.node_j.id == node_id:
                return               

        for slab in self.slabs.values():
            for n in slab.nodes:
                if n.id == node_id:
                    return               

        for ae in self.area_elements.values():
            for n in ae.nodes:
                if n.id == node_id:
                    return

        for link in self.links.values():
            if node_id in link['nodes']:
                return

        if any(self.nodes[node_id].restraints):
            return 

        self.loads = [
            load for load in self.loads 
            if not (hasattr(load, 'node_id') and load.node_id == node_id)
        ]

        del self.nodes[node_id]
        print(f"Garbage Collector: Removed orphaned Node {node_id} and its loads.")

    def assign_member_point_load(self, element_id, pattern_name, force, dist, is_relative, 
                                 coord_system, direction, load_type="Force", mode="replace"):
        """
        Assigns a concentrated Point Load or Moment to a frame element.
        """
        if element_id not in self.elements:
            raise KeyError(f"Element {element_id} does not exist.")

        existing_indices = []
        for i, load in enumerate(self.loads):
                                                                                       
            if (hasattr(load, 'element_id') and 
                hasattr(load, 'force') and                                           
                load.element_id == element_id and 
                load.pattern_name == pattern_name):
                existing_indices.append(i)

        if mode == "delete":
            for i in reversed(existing_indices):
                del self.loads[i]
            return

        elif mode == "replace":
                                                  
            for i in reversed(existing_indices):
                del self.loads[i]
            
            if force != 0:
                new_load = MemberPointLoad(element_id, pattern_name, force, dist, 
                                           is_relative, coord_system, direction, load_type)
                self.loads.append(new_load)

        elif mode == "add":
                                                                                                     
            if force != 0:
                new_load = MemberPointLoad(element_id, pattern_name, force, dist, 
                                           is_relative, coord_system, direction, load_type)
                self.loads.append(new_load)

    def assign_area_gravity_load(self, area_id, pattern_name,
                                  gx=0.0, gy=0.0, gz=0.0,
                                  coord_system="GLOBAL", mode="replace"):
        """
        Assigns gravity multiplier loads to an AreaElement.
        gx/gy/gz scale element self-weight in global X/Y/Z.
        Typical dead-load usage: gz=-1.0.
        Only valid on area elements (shells/planes/asolids) — not on frames.
        mode: 'add' | 'replace' | 'delete'
        """
        if area_id not in self.area_elements:
            raise KeyError(f"Area element {area_id} does not exist.")

        existing = [
            i for i, ld in enumerate(self.loads)
            if hasattr(ld, 'gx') and ld.area_id == area_id
            and ld.pattern_name == pattern_name
        ]

        if mode == "delete":
            for i in reversed(existing):
                del self.loads[i]
            return

        if mode == "replace":
            for i in reversed(existing):
                del self.loads[i]
            if any([gx, gy, gz]):
                self.loads.append(
                    AreaGravityLoad(area_id, pattern_name, coord_system, gx, gy, gz))

        elif mode == "add":
            if existing:
                ld = self.loads[existing[0]]
                ld.gx += gx; ld.gy += gy; ld.gz += gz
            elif any([gx, gy, gz]):
                self.loads.append(
                    AreaGravityLoad(area_id, pattern_name, coord_system, gx, gy, gz))

    def assign_area_gravity_loads(self, area_ids, pattern_name,
                                  gx=0.0, gy=0.0, gz=0.0,
                                  coord_system="GLOBAL", mode="replace"):
        """Assign self-weight multipliers with one scan of existing loads.

        Repeated or invalid IDs retain the scalar method's assignment order
        and partial-error behavior.
        """
        ids = list(area_ids)

        def sequential():
            for area_id in ids:
                self.assign_area_gravity_load(area_id, pattern_name, gx, gy, gz,
                                              coord_system, mode)

        try:
            selected = set(ids)
            fast = len(selected) == len(ids) and all(aid in self.area_elements for aid in ids)
        except TypeError:
            fast = False
        if not fast:
            return sequential()
        if not ids or mode not in ("add", "replace", "delete"):
            return
        if mode in ("replace", "delete"):
            try:
                has_nonzero = any([gx, gy, gz]) if mode == "replace" else False
            except (TypeError, ValueError):
                return sequential()
            self.loads[:] = [load for load in self.loads if not (
                hasattr(load, 'gx') and load.area_id in selected
                and load.pattern_name == pattern_name)]
            if has_nonzero:
                self.loads.extend(AreaGravityLoad(aid, pattern_name, coord_system,
                                                 gx, gy, gz) for aid in ids)
            return
        existing = {}
        for load in self.loads:
            if (hasattr(load, 'gx') and load.area_id in selected
                    and load.pattern_name == pattern_name):
                existing.setdefault(load.area_id, load)
        for aid in ids:
            if aid in existing:
                load = existing[aid]
                                                                        
                load.gx += gx
                load.gy += gy
                load.gz += gz
            elif any([gx, gy, gz]):
                self.loads.append(AreaGravityLoad(aid, pattern_name, coord_system,
                                                 gx, gy, gz))

    def assign_area_uniform_load(self, area_id, pattern_name,
                                  uniform_load=0.0, load_direction="Gravity",
                                  coord_system="GLOBAL", mode="replace"):
        """
        Assigns a uniform pressure (force/area) to an AreaElement.
        uniform_load: pressure magnitude in current working units (e.g. kN/m², kip/ft²).
        load_direction: 'Gravity' | 'Local 1' | 'Local 2' | 'Local 3' |
                        'Global X' | 'Global Y' | 'Global Z'
        Only valid on area elements (shells/planes/asolids) — not on frames.
        mode: 'add' | 'replace' | 'delete'
        """
        if area_id not in self.area_elements:
            raise KeyError(f"Area element {area_id} does not exist.")

        same_dir_indices = [
            i for i, ld in enumerate(self.loads)
            if hasattr(ld, 'uniform_load') and ld.area_id == area_id
            and ld.pattern_name == pattern_name
            and ld.load_direction == load_direction
        ]
        all_uniform_indices = [
            i for i, ld in enumerate(self.loads)
            if hasattr(ld, 'uniform_load') and ld.area_id == area_id
            and ld.pattern_name == pattern_name
        ]

        if mode == "delete":
            for i in reversed(all_uniform_indices):
                del self.loads[i]
            return

        if mode == "replace":
            for i in reversed(all_uniform_indices):
                del self.loads[i]
            if uniform_load != 0.0:
                self.loads.append(
                    AreaUniformLoad(area_id, pattern_name, coord_system,
                                    load_direction, uniform_load))

        elif mode == "add":
            if same_dir_indices:
                self.loads[same_dir_indices[0]].uniform_load += uniform_load
            elif uniform_load != 0.0:
                self.loads.append(
                    AreaUniformLoad(area_id, pattern_name, coord_system,
                                    load_direction, uniform_load))

    def assign_area_uniform_loads(self, area_ids, pattern_name, uniform_load=0.0,
                                  load_direction="Gravity", coord_system="GLOBAL",
                                  mode="replace"):
        """Assign pressure to many areas without rescanning all loads per area."""
        ids = list(area_ids)

        def sequential():
            for area_id in ids:
                self.assign_area_uniform_load(area_id, pattern_name, uniform_load,
                                              load_direction, coord_system, mode)

        try:
            selected = set(ids)
            fast = len(selected) == len(ids) and all(aid in self.area_elements for aid in ids)
        except TypeError:
            fast = False
        if not fast:
            return sequential()
        if not ids or mode not in ("add", "replace", "delete"):
            return
        if mode in ("replace", "delete"):
            try:
                has_nonzero = bool(uniform_load != 0.0) if mode == "replace" else False
            except (TypeError, ValueError):
                return sequential()
            self.loads[:] = [load for load in self.loads if not (
                hasattr(load, 'uniform_load') and load.area_id in selected
                and load.pattern_name == pattern_name)]
            if has_nonzero:
                self.loads.extend(AreaUniformLoad(aid, pattern_name, coord_system,
                                  load_direction, uniform_load) for aid in ids)
            return
        existing = {}
        for load in self.loads:
            if (hasattr(load, 'uniform_load') and load.area_id in selected
                    and load.pattern_name == pattern_name
                    and load.load_direction == load_direction):
                existing.setdefault(load.area_id, load)
        for aid in ids:
            if aid in existing:
                                                                                
                existing[aid].uniform_load += uniform_load
            elif uniform_load != 0.0:
                self.loads.append(AreaUniformLoad(aid, pattern_name, coord_system,
                                                 load_direction, uniform_load))

    def mesh_area_elements(self, area_ids, mode="divisions", n=1, m=1, max_x=0.5, max_y=0.5, divide_frames=True):
        """
        Meshes selected 4-node AreaElements either by exact N x M divisions or by a Max Size.
        Optionally divides any adjacent frame elements that touch the new nodes.
        """
        import math
        if not area_ids:
            return 0

        mesh_map = self._get_mesh_map()
        elements_meshed = 0
        elements_to_delete = []
        new_mesh_nodes = set()                                                  

        for eid in area_ids:
            if eid not in self.area_elements:
                continue

            old_elem = self.area_elements[eid]
            nodes = old_elem.nodes

            if hasattr(old_elem.section, 'modeling_type') and old_elem.section.modeling_type in ("Tributary Area", "Code Based (TS 500)"):
                print(f"Skipping Tributary / Code Based slab {eid} from meshing.")
                continue
            
            if len(nodes) != 4:
                print(f"Skipping AreaElement {eid}: Mesher currently supports 4-node quads only.")
                continue
            
            p1 = np.array([nodes[0].x, nodes[0].y, nodes[0].z])
            p2 = np.array([nodes[1].x, nodes[1].y, nodes[1].z])
            p3 = np.array([nodes[2].x, nodes[2].y, nodes[2].z])
            p4 = np.array([nodes[3].x, nodes[3].y, nodes[3].z])

            if mode == "size":
                                                                                   
                L_u = max(np.linalg.norm(p2 - p1), np.linalg.norm(p3 - p4))
                                                                                   
                L_v = max(np.linalg.norm(p4 - p1), np.linalg.norm(p3 - p2))
                
                n_divisions = max(1, math.ceil(L_u / max_x))
                m_divisions = max(1, math.ceil(L_v / max_y))
            else:
                n_divisions = n
                m_divisions = m

            if n_divisions == 1 and m_divisions == 1:
                continue

            section = old_elem.section
            parent_ins = getattr(old_elem, 'insertion_offset', 0.0)
            parent_area_loads = [l for l in self.loads if getattr(l, 'area_id', None) == eid]

            node_grid = {}
            for i in range(n_divisions + 1):
                node_grid[i] = {}
                u = i / n_divisions
                for j in range(m_divisions + 1):
                    v = j / m_divisions
                    
                    p_uv = (1-u)*(1-v)*p1 + u*(1-v)*p2 + u*v*p3 + (1-u)*v*p4
                    
                    new_node = self.get_or_create_node(p_uv[0], p_uv[1], p_uv[2])
                    node_grid[i][j] = new_node

                    if new_node not in nodes:
                        new_mesh_nodes.add(new_node)

            for i in range(n_divisions):
                for j in range(m_divisions):
                                                             
                    n1 = node_grid[i][j]
                    n2 = node_grid[i+1][j]
                    n3 = node_grid[i+1][j+1]
                    n4 = node_grid[i][j+1]
                    
                    new_ae = self.add_area_element([n1, n2, n3, n4], section)
                    new_ae.insertion_offset = parent_ins
                    new_ae.solver_mesh = None
                    mesh_map["area_parent"][new_ae.id] = eid
                    for old_load in parent_area_loads:
                        if hasattr(old_load, 'gx'):
                            self.assign_area_gravity_load(
                                new_ae.id, old_load.pattern_name,
                                old_load.gx, old_load.gy, old_load.gz,
                                coord_system=getattr(old_load, 'coord_system', "GLOBAL"),
                                mode="add")
                        elif hasattr(old_load, 'uniform_load'):
                            self.assign_area_uniform_load(
                                new_ae.id, old_load.pattern_name,
                                old_load.uniform_load,
                                load_direction=getattr(old_load, 'load_direction', "Gravity"),
                                coord_system=getattr(old_load, 'coord_system', "GLOBAL"),
                                mode="add")

            elements_to_delete.append((eid, nodes))
            elements_meshed += 1

        for eid, original_nodes in elements_to_delete:
            self.loads = [l for l in self.loads if getattr(l, 'area_id', None) != eid]
            del self.area_elements[eid]
            for n in original_nodes:
                self._cleanup_orphan_node(n.id)

        self._last_new_mesh_nodes = new_mesh_nodes

        if divide_frames and new_mesh_nodes:
            self._split_frames_by_nodes(new_mesh_nodes)
        
        return elements_meshed

    def join_area_elements(self, area_ids, tol=1e-4, rejoin_frames=True):
        """
        Merges selected 4-node shells that together form ONE quadrilateral patch
        (e.g. the N x M shells made by mesh_area_elements) back into a single shell.
        Works purely from geometry/connectivity, so it does not depend on the in-memory
        mesh map (which is not saved with the model).

        Requirements: >= 2 quads, same section and insertion offset, edge-connected, outer
        boundary has exactly 4 corners, and the interior nodes are not used by anything outside
        the selection (frames, links, supports, nodal loads, diaphragms, other shells).

        Loads: area loads are merged per (pattern, direction); when children differ the
        area-weighted average is used, so the total load is preserved.

        Returns {"created_area_id", "removed_area_ids", "removed_node_ids", "hanging_node_ids"}.
        hanging_node_ids = nodes on the outer edges that are not corners (still used by
        neighbours, so the joined shell's edge passes through them).
        rejoin_frames: frames that were split at those edge nodes (by "Add Points to Frames")
        are merged back where it is safe; see _rejoin_frames_at_nodes. Returned as
        "rejoined_frames": [(new_frame_id, [old ids]), ...].
        Raises ValueError / KeyError on invalid selections.
        """
        ids = list(dict.fromkeys(area_ids or []))
        if len(ids) < 2:
            raise ValueError("Select at least two shells to join.")
        for aid in ids:
            if aid not in self.area_elements:
                raise KeyError(f"Area element {aid} does not exist.")
        aes = [self.area_elements[a] for a in ids]
        if any(len(a.nodes) != 4 for a in aes):
            raise ValueError("Join supports 4-node shells only.")
        first = aes[0]
        for a in aes[1:]:
            if a.section.name != first.section.name:
                raise ValueError("Selected shells have different sections.")
            if abs(getattr(a, 'insertion_offset', 0.0) - getattr(first, 'insertion_offset', 0.0)) > 1e-9:
                raise ValueError("Selected shells have different insertion offsets.")
        mt = getattr(first.section, 'modeling_type', None)
        if mt in ("Tributary Area", "Code Based (TS 500)"):
            raise ValueError("Tributary / Code Based slabs cannot be joined.")

        P = lambda n: np.array([n.x, n.y, n.z], dtype=float)
        def quad_area(a):
            p = [P(n) for n in a.nodes]
            return 0.5 * float(np.linalg.norm(np.cross(p[2] - p[0], p[3] - p[1])))

        canon, by_pos = {}, {}
        for a in aes:
            for n in a.nodes:
                key = (round(n.x / 1e-4), round(n.y / 1e-4), round(n.z / 1e-4))
                canon[n.id] = by_pos.setdefault(key, n.id)

        edge_cnt = {}
        for a in aes:
            ns = [canon[n.id] for n in a.nodes]
            for k in range(4):
                e = frozenset((ns[k], ns[(k + 1) % 4]))
                edge_cnt[e] = edge_cnt.get(e, 0) + 1
        if any(c > 2 for c in edge_cnt.values()):
            raise ValueError("Selected shells overlap.")

        by_edge = {}
        for a in aes:
            ns = [canon[n.id] for n in a.nodes]
            for k in range(4):
                by_edge.setdefault(frozenset((ns[k], ns[(k + 1) % 4])), []).append(a.id)
        seen, groups = set(), []
        for a in aes:
            if a.id in seen:
                continue
            stack, grp = [a.id], []
            seen.add(a.id)
            while stack:
                cur = stack.pop(); grp.append(cur)
                ns = [canon[n.id] for n in self.area_elements[cur].nodes]
                for k in range(4):
                    for o in by_edge[frozenset((ns[k], ns[(k + 1) % 4]))]:
                        if o not in seen:
                            seen.add(o); stack.append(o)
            groups.append(sorted(grp))
        if len(groups) > 1:
            desc = "; ".join("{" + ", ".join(map(str, g[:6])) + (", ..." if len(g) > 6 else "") + "}" for g in groups[:4])
            raise ValueError(f"The selection is {len(groups)} separate groups that do not share edges: {desc}. "
                             "Select only the shells of ONE original shell (or one rectangular patch).")

        bnd = [tuple(e) for e, c in edge_cnt.items() if c == 1]
        adj = {}
        for u, v in bnd:
            adj.setdefault(u, []).append(v)
            adj.setdefault(v, []).append(u)
        bad = sorted(k for k, v in adj.items() if len(v) != 2)
        if not adj or bad:
            if not adj:
                raise ValueError("The selected shells have no outer boundary.")
            raise ValueError(
                f"The outline touches itself or has a hole / T-junction at joint(s) {bad[:8]}"
                f"{' ...' if len(bad) > 8 else ''}. Select a solid rectangular block of shells without gaps; "
                "a neighbouring shell meshed finer along an edge also breaks the patch.")
        start = next(iter(adj))
        loop, prev, cur = [start], None, start
        while True:
            nxt = [w for w in adj[cur] if w != prev]
            nxt = nxt[0] if nxt else None
            if nxt is None or nxt == start:
                break
            loop.append(nxt)
            prev, cur = cur, nxt
            if len(loop) > len(adj):
                break
        if len(loop) != len(adj):
            raise ValueError("Selected shells are not one connected patch without holes.")

        corners = []
        for i, nid in enumerate(loop):
            a, b, c = P(self.nodes[loop[i - 1]]), P(self.nodes[nid]), P(self.nodes[loop[(i + 1) % len(loop)]])                 
            d1, d2 = b - a, c - b
            n1, n2 = np.linalg.norm(d1), np.linalg.norm(d2)
            if n1 < 1e-9 or n2 < 1e-9:
                continue
            if np.linalg.norm(np.cross(d1, d2)) / (n1 * n2) > 1e-3:
                corners.append(nid)
        if len(corners) != 4:
            raise ValueError(f"Outer boundary has {len(corners)} corners; the selection must form a single quadrilateral.")

        pf = [P(n) for n in first.nodes]
        ref_normal = np.cross(pf[2] - pf[0], pf[3] - pf[1])
        ref_e1 = pf[1] - pf[0]
        corner_pos = [loop.index(c) for c in corners]
        best, best_score = None, -1e18
        for seq in (corners, corners[::-1]):
            for r in range(4):
                cand = seq[r:] + seq[:r]
                q = [P(self.nodes[c]) for c in cand]
                nrm = np.cross(q[2] - q[0], q[3] - q[1])
                if np.dot(nrm, ref_normal) <= 0:
                    continue
                e1 = q[1] - q[0]
                score = float(np.dot(e1, ref_e1) / max(np.linalg.norm(e1) * np.linalg.norm(ref_e1), 1e-12))
                if score > best_score:
                    best, best_score = cand, score
        if best is None:
            raise ValueError("Could not orient the joined shell.")

        q = [P(self.nodes[c]) for c in best]
        joined_area = 0.5 * float(np.linalg.norm(np.cross(q[2] - q[0], q[3] - q[1])))
        areas = [quad_area(a) for a in aes]
        total = sum(areas)
        if joined_area < 1e-12 or abs(joined_area - total) > 1e-3 * max(total, 1e-12):
            raise ValueError("Selected shells do not fill a flat quadrilateral (area mismatch).")

        sel = set(ids)
        used = set()
        for a in aes:
            used.update(n.id for n in a.nodes)
        boundary_nodes = set(loop)
        interior = [n for n in used if canon[n] not in boundary_nodes]
        for nid in interior:
            node = self.nodes[nid]
            if any(node.restraints):
                raise ValueError(f"Joint {nid} has a support and cannot be merged away.")
            if any(e.node_i.id == nid or e.node_j.id == nid for e in self.elements.values()):
                raise ValueError(f"Joint {nid} is used by a frame and cannot be merged away.")
            if any(nid in l['nodes'] for l in self.links.values()):
                raise ValueError(f"Joint {nid} is used by a link and cannot be merged away.")
            if any(getattr(l, 'node_id', None) == nid for l in self.loads):
                raise ValueError(f"Joint {nid} carries a nodal load and cannot be merged away.")
            if any(nid in {getattr(x, 'id', x) for x in getattr(c, 'nodes', [])} for c in self.constraints.values()):
                raise ValueError(f"Joint {nid} belongs to a diaphragm constraint.")
            if any(ae.id not in sel and any(n.id == nid for n in ae.nodes) for ae in self.area_elements.values()):
                raise ValueError(f"Joint {nid} is used by a shell outside the selection.")
            if any(any(n.id == nid for n in s.nodes) for s in self.slabs.values()):
                raise ValueError(f"Joint {nid} is used by a slab and cannot be merged away.")

        grav, unif = {}, {}
        for a, ar in zip(aes, areas):
            for ld in self.loads:
                if getattr(ld, 'area_id', None) != a.id:
                    continue
                if hasattr(ld, 'gx'):
                    k = (ld.pattern_name, getattr(ld, 'coord_system', "GLOBAL"))
                    g = grav.setdefault(k, [0.0, 0.0, 0.0])
                    g[0] += ld.gx * ar; g[1] += ld.gy * ar; g[2] += ld.gz * ar
                elif hasattr(ld, 'uniform_load'):
                    k = (ld.pattern_name, getattr(ld, 'load_direction', "Gravity"),
                         getattr(ld, 'coord_system', "GLOBAL"))
                    unif[k] = unif.get(k, 0.0) + ld.uniform_load * ar

        sm = [getattr(a, 'solver_mesh', None) for a in aes]
        keep_sm = sm[0] if all(s == sm[0] for s in sm) else None

        new_ae = self.add_area_element([self.nodes[c] for c in best], first.section)
        new_ae.insertion_offset = getattr(first, 'insertion_offset', 0.0)
        new_ae.solver_mesh = dict(keep_sm) if keep_sm else None
        for (pat, cs), g in grav.items():
            self.assign_area_gravity_load(new_ae.id, pat, g[0] / total, g[1] / total, g[2] / total,
                                          coord_system=cs, mode="add")
        for (pat, dr, cs), v in unif.items():
            self.assign_area_uniform_load(new_ae.id, pat, v / total, load_direction=dr,
                                          coord_system=cs, mode="add")

        self.loads = [l for l in self.loads if getattr(l, 'area_id', None) not in sel]
        for aid in ids:
            del self.area_elements[aid]
        mm = self._get_mesh_map()
        for aid in ids:
            mm["area_parent"].pop(aid, None)
        for nid in used:                                                                                   
            self._cleanup_orphan_node(nid)

        hanging = [n for n in loop if n not in set(best)]
        rejoined = self._rejoin_frames_at_nodes(hanging) if rejoin_frames else []
        return {"created_area_id": new_ae.id, "removed_area_ids": ids,
                "removed_node_ids": [n for n in used if n not in self.nodes],
                "hanging_node_ids": hanging, "rejoined_frames": rejoined}

    def _rejoin_frames_at_nodes(self, node_ids):
        """
        Undoes the frame splitting done by mesh_area_elements: at each given node that is used by
        exactly two frames and nothing else, merges the two frames with join_frames. A node is left
        alone if it has a support, nodal load, diaphragm, link, a shell, a frame release, a hinge,
        or if the two frames differ in section / beta angle / cardinal point / are not collinear.
        Returns [(new_frame_id, [removed ids]), ...].
        """
        done = []
        for nid in node_ids:
            node = self.nodes.get(nid)
            if node is None or any(node.restraints) or getattr(node, 'diaphragm_name', None):
                continue
            if any(getattr(l, 'node_id', None) == nid for l in self.loads):
                continue
            if any(nid in l['nodes'] for l in self.links.values()):
                continue
            if any(any(n.id == nid for n in ae.nodes) for ae in self.area_elements.values()):
                continue
            if any(nid in {getattr(x, 'id', x) for x in getattr(c, 'nodes', [])}
                   for c in self.constraints.values()):
                continue
            fr = [e for e in self.elements.values() if e.node_i.id == nid or e.node_j.id == nid]
            if len(fr) != 2:
                continue
            a, b = fr
            if (a.section.name != b.section.name or abs(a.beta_angle - b.beta_angle) > 1e-9
                    or a.cardinal_point != b.cardinal_point):
                continue
            rel = lambda e: e.releases_i if e.node_i.id == nid else e.releases_j
            if any(rel(a)) or any(rel(b)):
                continue
            if any(h.element_id in (a.id, b.id) for h in getattr(self, 'frame_hinges', {}).values()):
                continue
            try:
                r = self.join_frames([a.id, b.id], a.id)
            except (ValueError, KeyError):
                continue
            done.append((r["created_elem_id"], r["removed_elem_ids"]))
        return done

    def _get_mesh_map(self):
        """Bookkeeping filled while meshing: which new elements came from which original."""
        if not hasattr(self, '_mesh_map') or self._mesh_map is None:
            self._mesh_map = {"area_parent": {}, "frame_split": {}}
        return self._mesh_map

    def assign_area_solver_mesh(self, area_ids, solver_mesh):
        """
        Sets (dict) or clears (None) the analysis-time mesh on shells.
        Tributary / Code Based slabs are never given a mesh.
        Returns the number of shells changed.
        """
        changed = 0
        for aid in area_ids:
            ae = self.area_elements.get(aid)
            if ae is None or len(ae.nodes) != 4:
                continue
            mt = getattr(ae.section, 'modeling_type', None)
            if solver_mesh and mt in ("Tributary Area", "Code Based (TS 500)"):
                continue
            ae.solver_mesh = dict(solver_mesh) if solver_mesh else None
            changed += 1
        return changed

    def has_solver_mesh(self):
        return any(getattr(ae, 'solver_mesh', None) for ae in self.area_elements.values())

    def write_solver_copy(self, live_path):
        """
        Builds a meshed copy of this model for the solver and leaves this model untouched.

        The copy is written to  <model dir>/.solver_mesh/<same file name>  so that every
        output name the solver derives from its input path (results, matrices, combos, RSA,
        buckling temp files) keeps the correct base name.

        Returns None when no shell carries a solver mesh, otherwise a dict:
            {"work_dir", "dest_path", "mesh_map", "meshed_shells"}
        mesh_map = {"area_parent": {child_id: parent_id},
                    "frame_split": {orig_frame_id: {"segments": [ids], "boundaries": [t0..tn]}}}
        """
        import os, shutil, json

        flagged = {eid: ae.solver_mesh for eid, ae in self.area_elements.items()
                   if getattr(ae, 'solver_mesh', None)}
                                                                                            
        if not flagged and not self._frame_span_hits(self.nodes.values()):
            return None

        live_path = os.path.abspath(live_path)
        work_dir = os.path.join(os.path.dirname(live_path), ".solver_mesh")
        shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir, exist_ok=True)
        dest_path = os.path.join(work_dir, os.path.basename(live_path))

        self.save_to_file(dest_path)
        copy_model = StructuralModel(self.name)
        copy_model.load_from_file(dest_path)
        copy_model._mesh_map = {"area_parent": {}, "frame_split": {}}

        split_nodes = {}
        for lst in copy_model._frame_span_hits(copy_model.nodes.values()).values():
            for _, n in lst:
                split_nodes[n.id] = n

        groups = {}
        for eid, sm in flagged.items():
            if eid not in copy_model.area_elements:
                continue
            key = (sm.get("mode", "divisions"), int(sm.get("n", 1)), int(sm.get("m", 1)),
                   float(sm.get("max_x", 0.5)), float(sm.get("max_y", 0.5)),
                   bool(sm.get("divide_frames", True)))
            groups.setdefault(key, []).append(eid)

        all_new_nodes = set()
        want_frames = False
        meshed = 0
        for (mode, n, mm, mx, my, div_frames), ids in groups.items():
            meshed += copy_model.mesh_area_elements(
                ids, mode=mode, n=n, m=mm, max_x=mx, max_y=my, divide_frames=False)
            all_new_nodes |= getattr(copy_model, '_last_new_mesh_nodes', set())
            want_frames = want_frames or div_frames

        if want_frames:
            for n in all_new_nodes:
                split_nodes[n.id] = n
        if split_nodes:
                                                                                        
            copy_model._split_frames_by_nodes(list(split_nodes.values()))

        copy_model.save_to_file(dest_path)

        mesh_map = copy_model._mesh_map
        with open(dest_path + ".meshmap.json", "w") as f:
            json.dump(mesh_map, f)

        return {"work_dir": work_dir, "dest_path": dest_path,
                "mesh_map": mesh_map, "meshed_shells": meshed,
                "split_frames": len(mesh_map.get("frame_split", {}))}

    def _frame_span_hits(self, candidate_nodes, tol=0.005):
        """
        Finds candidate nodes lying on a frame's axis strictly between its end nodes.
        tol is both the perpendicular distance and the end margin (matches get_or_create_node).
        Returns {frame_id: [(distance_from_node_i, node), ...]} sorted along the frame,
        nodes closer than tol to each other are collapsed to one split point.
        """
        nodes = list(candidate_nodes)
        if not nodes or not self.elements:
            return {}
        P = np.array([[n.x, n.y, n.z] for n in nodes], dtype=float)
        hits = {}
        for el in self.elements.values():
            p_i = np.array([el.node_i.x, el.node_i.y, el.node_i.z], dtype=float)
            p_j = np.array([el.node_j.x, el.node_j.y, el.node_j.z], dtype=float)
            d = p_j - p_i
            L = float(np.linalg.norm(d))
            if L < 1e-6:
                continue
            u = d / L
            rel = P - p_i
            s = rel @ u
            idx = np.nonzero((s > tol) & (s < L - tol))[0]
            if idx.size == 0:
                continue
            perp = np.linalg.norm(rel[idx] - np.outer(s[idx], u), axis=1)
            found = []
            for k in idx[perp <= tol]:
                n = nodes[k]
                if n.id in (el.node_i.id, el.node_j.id):
                    continue
                found.append((float(s[k]), n))
            if not found:
                continue
            found.sort(key=lambda x: x[0])
            clean = [found[0]]
            for item in found[1:]:
                if item[0] - clean[-1][0] > tol:
                    clean.append(item)
            hits[el.id] = clean
        return hits

    def _retarget_tendon_hosts(self, old_el, new_elements):
        """Replaces old_el in every tendon's host list by its segments, in tendon order."""
        seg_ids = [ne.id for ne in new_elements]
        ev = np.array([old_el.node_j.x - old_el.node_i.x, old_el.node_j.y - old_el.node_i.y,
                       old_el.node_j.z - old_el.node_i.z], dtype=float)
        for t in getattr(self, 'tendons', {}).values():
            hosts = list(t.host_element_ids)
            if old_el.id not in hosts:
                continue
            tv = np.array([t.node_j.x - t.node_i.x, t.node_j.y - t.node_i.y,
                           t.node_j.z - t.node_i.z], dtype=float)
            ids = seg_ids if float(ev @ tv) >= 0 else seg_ids[::-1]
            k = hosts.index(old_el.id)
            t.host_element_ids = hosts[:k] + ids + hosts[k + 1:]

    def _split_frames_by_nodes(self, split_nodes, tol=0.005):
        """
        Splits every frame that has one of the passed nodes on its span (not at its ends).
        Keeps end releases at the outer ends only, redistributes loads and hinges.
        Records each split in the mesh map (frame_split).
        """
        hits = self._frame_span_hits(split_nodes, tol)
        for el in list(self.elements.values()):
            nodes_on_segment = hits.get(el.id)
            if not nodes_on_segment:
                continue
            L_total = float(np.linalg.norm(
                np.array([el.node_j.x, el.node_j.y, el.node_j.z]) -
                np.array([el.node_i.x, el.node_i.y, el.node_i.z])))

            orig_loads  = [l for l in self.loads if getattr(l, 'element_id', None) == el.id]
            orig_hinges = [h for h in self.frame_hinges.values() if h.element_id == el.id]
            seg_nodes  = [el.node_i] + [n for _, n in nodes_on_segment] + [el.node_j]
            boundaries = [0.0] + [d / L_total for d, _ in nodes_on_segment] + [1.0]
            n_segs = len(seg_nodes) - 1

            new_elements = []
            for k in range(n_segs):
                new_el = self.add_element(seg_nodes[k], seg_nodes[k + 1], el.section, el.beta_angle)
                self._copy_frame_properties(new_el, el, boundaries[k], boundaries[k + 1])
                new_el.releases_i = el.releases_i[:] if k == 0 else [False] * 6
                new_el.releases_j = el.releases_j[:] if k == n_segs - 1 else [False] * 6
                new_elements.append(new_el)

            self._get_mesh_map()["frame_split"][el.id] = {
                "segments": [ne.id for ne in new_elements],
                "boundaries": boundaries,
            }

            for load in orig_loads:
                self._redistribute_load_onto_segments(load, new_elements, boundaries, L_total)

            self._retarget_tendon_hosts(el, new_elements)

            for h in orig_hinges:
                t = h.rel_dist
                for k in range(n_segs):
                    t0, t1 = boundaries[k], boundaries[k + 1]
                    if t0 - 1e-9 <= t <= t1 + 1e-9:
                        local = (t - t0) / (t1 - t0) if (t1 - t0) > 1e-12 else 0.0
                        self.assign_frame_hinge(new_elements[k].id, h.hinge_name,
                                                min(max(local, 0.0), 1.0), mode="add")
                        break
            self.assign_frame_hinge(el.id, None, 0.0, mode="delete")

            self.remove_element(el.id)

    def remove_orphan_nodes(self):
        """
        Deletes nodes not connected to any frame, slab, or area element.
        Respects supports — restrained nodes are never deleted.
        Returns count of nodes removed.
        """
        used_node_ids = set()

        for el in self.elements.values():
            used_node_ids.add(el.node_i.id)
            used_node_ids.add(el.node_j.id)

        for slab in self.slabs.values():
            for n in slab.nodes:
                used_node_ids.add(n.id)

        for ae in self.area_elements.values():
            for n in ae.nodes:
                used_node_ids.add(n.id)

        orphan_ids = [
            nid for nid in list(self.nodes)
            if nid not in used_node_ids
            and not any(self.nodes[nid].restraints)
        ]

        for nid in orphan_ids:
            self.loads = [
                l for l in self.loads
                if not (hasattr(l, 'node_id') and l.node_id == nid)
            ]
            del self.nodes[nid]

        print(f"Orphan cleanup: removed {len(orphan_ids)} nodes.")
        return len(orphan_ids)

    def add_tendon_section(self, section):
        """Adds or updates a tendon section."""
        self.tendon_sections[section.name] = section
        return section

    def get_frame_chain_between(self, node_i, node_j, tol=1e-4):
        """
        Finds a connected, collinear chain of frame elements running from
        node_i to node_j (in that direction). Used to validate a tendon draw
        and derive its host_element_ids.

        Returns (host_element_ids, ordered_nodes) on success,
        or (None, None) if no valid straight, connected chain exists
        (gap in the chain, or an ambiguous branch).
        """
        if node_i.id == node_j.id:
            return None, None

        p_i = np.array([node_i.x, node_i.y, node_i.z])
        p_j = np.array([node_j.x, node_j.y, node_j.z])
        V = p_j - p_i
        L = np.linalg.norm(V)
        if L < tol:
            return None, None
        dir_overall = V / L

        adjacency = {}
        for el in self.elements.values():
            adjacency.setdefault(el.node_i.id, []).append((el.node_j, el))
            adjacency.setdefault(el.node_j.id, []).append((el.node_i, el))

        current = node_i
        visited_ids = {current.id}
        host_ids = []
        ordered_nodes = [current]

        while current.id != node_j.id:
            next_node, next_el = None, None
            for other, el in adjacency.get(current.id, []):
                if other.id in visited_ids:
                    continue
                seg_vec = np.array([other.x - current.x, other.y - current.y, other.z - current.z])
                seg_len = np.linalg.norm(seg_vec)
                if seg_len < tol:
                    continue
                seg_dir = seg_vec / seg_len

                collinear = np.linalg.norm(np.cross(seg_dir, dir_overall)) < 1e-3
                forward = np.dot(seg_dir, dir_overall) > 0.999
                if collinear and forward:
                    if next_node is not None:
                        return None, None                                           
                    next_node, next_el = other, el

            if next_node is None:
                return None, None                                                  

            host_ids.append(next_el.id)
            ordered_nodes.append(next_node)
            visited_ids.add(next_node.id)
            current = next_node

            if len(host_ids) > len(self.elements) + 1:
                return None, None                                       

        return host_ids, ordered_nodes

    def _get_next_tendon_id(self):
        """Calculates the next available Tendon ID."""
        if not self.tendons:
            return 1
        return max(self.tendons.keys()) + 1

    def add_tendon(self, node_i, node_j, tendon_section, local_axis_angle=0.0, plane="1-2"):
        """
        Creates and adds a TendonObject with a guaranteed unique ID.
        Runs host-chain-detection internally; raises ValueError if no valid
        straight, connected run of frame elements exists between the two nodes.
        """
        host_ids, _ = self.get_frame_chain_between(node_i, node_j)
        if host_ids is None:
            raise ValueError(
                "No continuous, straight frame element chain exists between "
                "these two nodes. A tendon must be drawn over existing frame elements."
            )

        new_id = self._get_next_tendon_id()
        new_tendon = TendonObject(new_id, node_i, node_j, tendon_section,
                                   host_element_ids=host_ids,
                                   local_axis_angle=local_axis_angle, plane=plane)
        self.tendons[new_id] = new_tendon
        self._tendon_counter = new_id + 1
        return new_tendon

    def remove_tendon(self, tendon_id):
        """Removes a tendon object by id, if present."""
        if tendon_id in self.tendons:
            del self.tendons[tendon_id]

    def _copy_frame_properties(self, dst_el, src_el, t0=0.0, t1=1.0):
        """Copies all frame-level properties (not id/nodes/section/beta) from src_el to dst_el.

        t0/t1 = span (0-1 along src_el) covered by dst_el when src_el is being split.
        Rigid end-length offsets stay only on the original frame ends (t0 == 0 / t1 == 1),
        and joint offsets are linearly interpolated to the segment ends.
        Defaults (0, 1) give a plain full copy.
        """
        dst_el.cardinal_point = getattr(src_el, 'cardinal_point', 10)
        if hasattr(src_el, 'joint_offset_i') and hasattr(src_el, 'joint_offset_j'):
            oi = np.asarray(src_el.joint_offset_i, dtype=float)
            oj = np.asarray(src_el.joint_offset_j, dtype=float)

            def _lerp(t):
                if t <= 1e-12:
                    return oi.copy()
                if t >= 1.0 - 1e-12:
                    return oj.copy()
                return oi + t * (oj - oi)

            dst_el.joint_offset_i = _lerp(t0)
            dst_el.joint_offset_j = _lerp(t1)
        else:
            if hasattr(src_el, 'joint_offset_i'):
                dst_el.joint_offset_i = src_el.joint_offset_i.copy()
            if hasattr(src_el, 'joint_offset_j'):
                dst_el.joint_offset_j = src_el.joint_offset_j.copy()
        dst_el.end_offset_i = getattr(src_el, 'end_offset_i', 0.0) if t0 <= 1e-9 else 0.0
        dst_el.end_offset_j = getattr(src_el, 'end_offset_j', 0.0) if t1 >= 1.0 - 1e-9 else 0.0
        dst_el.rigid_zone_factor = getattr(src_el, 'rigid_zone_factor', 0.0)
        dst_el.do_not_transform_stiffness = getattr(src_el, 'do_not_transform_stiffness', False)

    @staticmethod
    def _interp_trapezoid(distances, magnitudes, t):
        """Piecewise-linear value of a trapezoidal load definition at param t in [0,1]."""
        if t <= distances[0]:
            return magnitudes[0]
        if t >= distances[-1]:
            return magnitudes[-1]
        for i in range(len(distances) - 1):
            d0, d1 = distances[i], distances[i + 1]
            if d0 <= t <= d1:
                if d1 - d0 < 1e-12:
                    return magnitudes[i]
                frac = (t - d0) / (d1 - d0)
                return magnitudes[i] + frac * (magnitudes[i + 1] - magnitudes[i])
        return magnitudes[-1]

    @classmethod
    def _clip_trapezoid(cls, distances, magnitudes, t0, t1):
        """
        Clips a trapezoidal load (defined over global param [0,1]) to the
        sub-range [t0, t1] and remaps it to that sub-range's local [0,1].
        """
        pts = [(t0, cls._interp_trapezoid(distances, magnitudes, t0))]
        for d, m in zip(distances, magnitudes):
            if t0 < d < t1:
                pts.append((d, m))
        pts.append((t1, cls._interp_trapezoid(distances, magnitudes, t1)))
        span = t1 - t0
        new_distances = [(p[0] - t0) / span if span > 1e-12 else 0.0 for p in pts]
        new_magnitudes = [p[1] for p in pts]
        return new_distances, new_magnitudes

    def _redistribute_load_onto_segments(self, load, new_elements, boundaries, L_total):
        """Splits a single load (assigned to the original frame) proportionally across new_elements."""
        is_point = hasattr(load, 'force') and hasattr(load, 'dist')

        if is_point:
            t = load.dist if load.is_relative else (load.dist / L_total if L_total > 1e-9 else 0.0)
            t = min(max(t, 0.0), 1.0)
            for k in range(len(boundaries) - 1):
                t0, t1 = boundaries[k], boundaries[k + 1]
                if t0 - 1e-9 <= t <= t1 + 1e-9:
                    local_t = (t - t0) / (t1 - t0) if (t1 - t0) > 1e-12 else 0.0
                    local_t = min(max(local_t, 0.0), 1.0)
                    self.assign_member_point_load(
                        new_elements[k].id, load.pattern_name, load.force, local_t, True,
                        load.coord_system, load.direction,
                        getattr(load, 'load_type', 'Force'), mode='add'
                    )
                    break
            return

        distances = list(load.distances)
        magnitudes = list(load.magnitudes)
        if not load.is_relative and L_total > 1e-9:
            distances = [d / L_total for d in distances]

        for k in range(len(boundaries) - 1):
            t0, t1 = boundaries[k], boundaries[k + 1]
            new_d, new_m = self._clip_trapezoid(distances, magnitudes, t0, t1)
            self.assign_member_load(
                new_elements[k].id, load.pattern_name, load.wx, load.wy, load.wz,
                projected=getattr(load, 'projected', False),
                coord_system=getattr(load, 'coord_system', 'Global'),
                mode='add',
                distances=new_d, magnitudes=new_m, is_relative=True,
                load_direction=getattr(load, 'load_direction', 'Gravity'),
                load_type=getattr(load, 'load_type', 'Force')
            )

    def divide_frame_at_params(self, element_id, t_values, tol=1e-6):
        """
        Splits frame `element_id` into segments at the given parametric
        locations (0 < t < 1, fraction of length from node_i to node_j).
        Interior points snap to existing joints within tolerance.
        Copies section/beta/releases/offsets/etc. and proportionally
        redistributes any MemberLoad / MemberPointLoad on the original frame.

        Returns {"created_node_ids": [...], "created_elem_ids": [...]}.
        Raises ValueError / KeyError on invalid input.
        """
        if element_id not in self.elements:
            raise KeyError(f"Element {element_id} does not exist.")

        clean_t = sorted(set(round(float(t), 9) for t in t_values if tol < t < 1 - tol))
        if not clean_t:
            raise ValueError("No valid interior division points (must fall strictly between the two end joints).")

        el = self.elements[element_id]
        n_i, n_j = el.node_i, el.node_j
        p_i = np.array([n_i.x, n_i.y, n_i.z])
        p_j = np.array([n_j.x, n_j.y, n_j.z])
        L_total = np.linalg.norm(p_j - p_i)
        if L_total < 1e-9:
            raise ValueError("Frame has zero length.")

        sec, beta = el.section, el.beta_angle
        orig_loads = [l for l in self.loads if getattr(l, 'element_id', None) == element_id]
        boundaries = [0.0] + clean_t + [1.0]

        created_node_ids = []
        seg_nodes = [n_i]
        for t in clean_t:
            p = p_i + t * (p_j - p_i)
            existed_before = set(self.nodes.keys())
            node = self.get_or_create_node(p[0], p[1], p[2])
            if node.id not in existed_before:
                created_node_ids.append(node.id)
            seg_nodes.append(node)
        seg_nodes.append(n_j)

        new_elements = []
        created_elem_ids = []
        n_segs = len(seg_nodes) - 1
        for k in range(n_segs):
            na, nb = seg_nodes[k], seg_nodes[k + 1]
            new_el = self.add_element(na, nb, sec, beta)
            self._copy_frame_properties(new_el, el, boundaries[k], boundaries[k + 1])
            new_el.releases_i = el.releases_i[:] if k == 0 else [False] * 6
            new_el.releases_j = el.releases_j[:] if k == n_segs - 1 else [False] * 6
            new_elements.append(new_el)
            created_elem_ids.append(new_el.id)

        for load in orig_loads:
            self._redistribute_load_onto_segments(load, new_elements, boundaries, L_total)

        self.remove_element(element_id)

        return {"created_node_ids": created_node_ids, "created_elem_ids": created_elem_ids}

    def divide_frame_by_number(self, element_id, num_frames, last_first_ratio=1.0):
        """'Divide into Specified Number of Frames' (Number of Frames + Last/First Length Ratio)."""
        num_frames = int(num_frames)
        if num_frames < 2:
            raise ValueError("Number of Frames must be at least 2.")
        r = float(last_first_ratio)
        if r <= 0:
            raise ValueError("Last/First Length Ratio must be greater than 0.")

        if abs(r - 1.0) < 1e-9:
            seg_fracs = [1.0 / num_frames] * num_frames
        else:
            L1 = 2.0 / (num_frames * (r + 1.0))
            d = L1 * (r - 1.0) / (num_frames - 1.0)
            seg_fracs = [L1 + i * d for i in range(num_frames)]
            if any(f <= 0 for f in seg_fracs):
                raise ValueError("This Number of Frames / Ratio combination produces a non-physical (negative or zero length) segment.")

        t_values, acc = [], 0.0
        for f in seg_fracs[:-1]:
            acc += f
            t_values.append(acc)

        return self.divide_frame_at_params(element_id, t_values)

    def divide_frame_at_distance(self, element_id, distance, is_relative=True):
        """'Divide at Specified Distance from I-end of Frame'."""
        if element_id not in self.elements:
            raise KeyError(f"Element {element_id} does not exist.")
        el = self.elements[element_id]
        L = getattr(el, 'length', None)
        if L is None:
            L = float(np.linalg.norm(np.array([el.node_j.x - el.node_i.x,
                                                 el.node_j.y - el.node_i.y,
                                                 el.node_j.z - el.node_i.z])))
        t = float(distance) if is_relative else float(distance) / L
        if not (0.0 < t < 1.0):
            raise ValueError("Distance must fall strictly between the two end joints of the frame.")
        return self.divide_frame_at_params(element_id, [t])

    def divide_frame_at_coordinate_plane(self, element_id, plane, coordinate):
        """
        'Divide at Intersection with a Coordinate Plane'.
        plane: 'XY' (constant Z), 'YZ' (constant X), or 'XZ' (constant Y).
        """
        if element_id not in self.elements:
            raise KeyError(f"Element {element_id} does not exist.")
        axis_map = {'XY': 2, 'YZ': 0, 'XZ': 1}
        if plane not in axis_map:
            raise ValueError("Coordinate Plane must be one of 'XY', 'YZ', 'XZ'.")
        el = self.elements[element_id]
        p_i = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
        p_j = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
        idx = axis_map[plane]
        c0, c1 = p_i[idx], p_j[idx]
        if abs(c1 - c0) < 1e-9:
            raise ValueError("The frame is parallel to the specified plane and never crosses it.")
        t = (float(coordinate) - c0) / (c1 - c0)
        if not (0.0 < t < 1.0):
            raise ValueError("That plane does not intersect this frame between its two end joints.")
        return self.divide_frame_at_params(element_id, [t])

    def divide_frame_at_grid_planes(self, element_id):
        """
        'Divide at Intersection with Visible Grid Planes in the Current
        Coordinate System'. Each of grid.x_lines/y_lines/z_lines is a list
        of {'id', 'ord', 'visible', 'bubble'} dicts (see core/grid.py) —
        'ord' is the coordinate, and only entries with visible=True count,
        matching the "Visible" in the option's name.
        """
        if element_id not in self.elements:
            raise KeyError(f"Element {element_id} does not exist.")
        el = self.elements[element_id]
        p_i = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
        p_j = np.array([el.node_j.x, el.node_j.y, el.node_j.z])

        t_values = []
        grid = getattr(self, 'grid', None)
        if grid is not None:
            for idx, lines in ((0, getattr(grid, 'x_lines', [])),
                                (1, getattr(grid, 'y_lines', [])),
                                (2, getattr(grid, 'z_lines', []))):
                c0, c1 = p_i[idx], p_j[idx]
                if abs(c1 - c0) < 1e-9:
                    continue
                for line in (lines or []):
                    if isinstance(line, dict):
                        if not line.get('visible', True):
                            continue
                        coord = line.get('ord')
                    else:
                        coord = line
                    try:
                        coord = float(coord)
                    except (TypeError, ValueError):
                        continue
                    t = (coord - c0) / (c1 - c0)
                    if 1e-6 < t < 1 - 1e-6:
                        t_values.append(t)

        if not t_values:
            raise ValueError("No visible grid planes intersect this frame between its end joints.")
        return self.divide_frame_at_params(element_id, t_values)

    @staticmethod
    def _line_segment_intersection(p1, d1, len1, p_a, p_b, tol):
        """
        Intersection of the segment [p1, p1+d1*len1] with segment [p_a, p_b],
        only if the two lines actually meet within `tol`. Returns
        (point, t_on_self[0..1], t_on_other[0..1]) or (None, None, None).
        """
        d2_vec = p_b - p_a
        len2 = np.linalg.norm(d2_vec)
        if len2 < 1e-9:
            return None, None, None
        d2 = d2_vec / len2

        cross = np.cross(d1, d2)
        denom = np.dot(cross, cross)
        if denom < 1e-9:
            return None, None, None            

        r = p_a - p1
        t1 = np.dot(np.cross(r, d2), cross) / denom
        t2 = np.dot(np.cross(r, d1), cross) / denom

        p_on_1 = p1 + d1 * t1
        p_on_2 = p_a + d2 * t2
        if np.linalg.norm(p_on_1 - p_on_2) > tol:
            return None, None, None                               

        t1_frac = t1 / len1
        t2_frac = t2 / len2
        if not (1e-6 < t1_frac < 1 - 1e-6) or not (-1e-6 <= t2_frac <= 1 + 1e-6):
            return None, None, None

        return p_on_1, t1_frac, t2_frac

    def divide_frame_at_intersections(self, element_id, joint_ids=None, frame_ids=None, tol=1e-4):
        """
        'Break at Intersections with Selected Joints and Straight Frames'.
        (Area Edges / Solid Edges from the SAP2000 dialog are not supported
        in this version — this model has no solid elements, and area-edge
        intersection wasn't implemented.)
        """
        if element_id not in self.elements:
            raise KeyError(f"Element {element_id} does not exist.")
        el = self.elements[element_id]
        p_i = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
        p_j = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
        L = np.linalg.norm(p_j - p_i)
        if L < 1e-9:
            raise ValueError("Frame has zero length.")
        direction = (p_j - p_i) / L

        t_values = []

        for nid in (joint_ids or []):
            if nid == el.node_i.id or nid == el.node_j.id or nid not in self.nodes:
                continue
            n = self.nodes[nid]
            p_n = np.array([n.x, n.y, n.z])
            d1 = np.linalg.norm(p_n - p_i)
            d2 = np.linalg.norm(p_j - p_n)
            if abs((d1 + d2) - L) < tol:
                t_values.append(d1 / L)

        for fid in (frame_ids or []):
            if fid == element_id or fid not in self.elements:
                continue
            other = self.elements[fid]
            p_a = np.array([other.node_i.x, other.node_i.y, other.node_i.z])
            p_b = np.array([other.node_j.x, other.node_j.y, other.node_j.z])
            _, t_self, _ = self._line_segment_intersection(p_i, direction, L, p_a, p_b, tol)
            if t_self is not None:
                t_values.append(t_self)

        if not t_values:
            raise ValueError("None of the selected joints or frames intersect this frame between its end joints.")
        return self.divide_frame_at_params(element_id, t_values)

    def find_straight_chains(self, element_ids, tol=1e-3):
        """
        Partitions an arbitrary selection of connected frame elements —
        which may bend, branch, or contain multiple disconnected pieces —
        into maximal straight, unbranched sub-chains. This is what lets
        "select the whole model and Join" work: each returned chain is a
        run of collinear frames connected end-to-end, stopping wherever
        the direction changes or a joint is shared by more than two of the
        selected frames (a branch). A chain never crosses a joint that
        isn't shared by exactly two selected frames.

        Returns a list of chains, each a list of element ids in order
        along the chain. A chain of length 1 has nothing to join with its
        neighbors (dead end, direction change, or branch point) and should
        just be left alone by the caller.
        """
        element_ids = [eid for eid in dict.fromkeys(element_ids) if eid in self.elements]
        remaining = set(element_ids)

        node_use = {}
        for eid in element_ids:
            el = self.elements[eid]
            node_use.setdefault(el.node_i.id, []).append(eid)
            node_use.setdefault(el.node_j.id, []).append(eid)

        def _direction(eid):
            el = self.elements[eid]
            p_a = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
            p_b = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
            v = p_b - p_a
            L = np.linalg.norm(v)
            return None if L < 1e-9 else v / L

        def _collinear(eid_a, eid_b):
            da, db = _direction(eid_a), _direction(eid_b)
            if da is None or db is None:
                return False
            return np.linalg.norm(np.cross(da, db)) < tol

        chains = []
        while remaining:
            seed = next(iter(remaining))
            chain = [seed]
            remaining.discard(seed)

            for grow_forward in (True, False):
                extend = True
                while extend:
                    extend = False
                    current = chain[-1] if grow_forward else chain[0]
                    el = self.elements[current]
                    end_node_id = el.node_j.id if grow_forward else el.node_i.id
                    uses = node_use.get(end_node_id, [])
                                                                            
                    candidates = [eid for eid in uses if eid != current and eid in remaining]
                    if len(uses) == 2 and len(candidates) == 1 and _collinear(current, candidates[0]):
                        if grow_forward:
                            chain.append(candidates[0])
                        else:
                            chain.insert(0, candidates[0])
                        remaining.discard(candidates[0])
                        extend = True

            chains.append(chain)

        return chains

    def join_frames(self, element_ids, keep_props_from_id, tol=1e-4):
        """
        Merges 2+ selected, connected, collinear frame elements into one
        frame — the SAP2000-style "Join Frames" (no dialog, acts on the
        current selection). `keep_props_from_id` picks which selected
        frame's section/beta/offsets/cardinal point/etc. the merged frame
        inherits; end releases are always taken from whichever selected
        frame actually sits at each true outer end, since those are the
        real boundary conditions, not the "kept" frame's own end conditions
        (which may now be an interior point).

        Returns {"created_elem_id": id, "removed_elem_ids": [...], "removed_node_ids": [...]}.
        Raises ValueError / KeyError on invalid selections.
        """
        element_ids = list(dict.fromkeys(element_ids))
        if len(element_ids) < 2:
            raise ValueError("Select at least two frames to join.")
        for eid in element_ids:
            if eid not in self.elements:
                raise KeyError(f"Element {eid} does not exist.")
        if keep_props_from_id not in element_ids:
            raise ValueError("keep_props_from_id must be one of the selected frames.")

        id_set = set(element_ids)
        node_use = {}
        for eid in element_ids:
            el = self.elements[eid]
            node_use.setdefault(el.node_i.id, []).append(eid)
            node_use.setdefault(el.node_j.id, []).append(eid)

        endpoints = [nid for nid, uses in node_use.items() if len(uses) == 1]
        if len(endpoints) != 2:
            raise ValueError(
                "Selected frames must form a single continuous, unbranched chain "
                "(each interior joint must be shared by exactly two of the selected frames)."
            )
        if any(len(uses) > 2 for uses in node_use.values()):
            raise ValueError("Selected frames branch at a shared joint; Join only supports a simple chain.")

        start_node = self.nodes[endpoints[0]]
        end_node = self.nodes[endpoints[1]]

        host_ids, ordered_nodes = self.get_frame_chain_between(start_node, end_node, tol=tol)
        if host_ids is None or set(host_ids) != id_set:
            raise ValueError("Selected frames are not a single straight, collinear, connected chain.")

        interior_ids = [n.id for n in ordered_nodes[1:-1]]
        for nid in interior_ids:
            node = self.nodes[nid]
            if any(node.restraints):
                raise ValueError(f"Joint {nid} has a support/restraint assigned and cannot be merged away.")
            if any((e.node_i.id == nid or e.node_j.id == nid) and e.id not in id_set
                   for e in self.elements.values()):
                raise ValueError(f"Joint {nid} is used by another frame outside the selection and cannot be merged away.")
            if hasattr(self, 'area_elements') and any(
                    any(n.id == nid for n in ae.nodes) for ae in self.area_elements.values()):
                raise ValueError(f"Joint {nid} is used by an area element and cannot be merged away.")
            if hasattr(self, 'links') and any(nid in link['nodes'] for link in self.links.values()):
                raise ValueError(f"Joint {nid} is used by a link and cannot be merged away.")

        keep_el = self.elements[keep_props_from_id]

        start_touch_id = next(eid for eid in host_ids
                               if self.elements[eid].node_i.id == start_node.id
                               or self.elements[eid].node_j.id == start_node.id)
        end_touch_id = next(eid for eid in host_ids
                             if self.elements[eid].node_i.id == end_node.id
                             or self.elements[eid].node_j.id == end_node.id)
        start_el = self.elements[start_touch_id]
        end_el = self.elements[end_touch_id]
        release_i = start_el.releases_i[:] if start_el.node_i.id == start_node.id else start_el.releases_j[:]
        release_j = end_el.releases_j[:] if end_el.node_j.id == end_node.id else end_el.releases_i[:]

        coords = [np.array([n.x, n.y, n.z]) for n in ordered_nodes]
        seg_lengths = [float(np.linalg.norm(coords[i + 1] - coords[i])) for i in range(len(coords) - 1)]
        L_total = sum(seg_lengths)
        if L_total < 1e-9:
            raise ValueError("Combined frame has zero length.")

        boundaries = [0.0]
        acc = 0.0
        for sl in seg_lengths:
            acc += sl / L_total
            boundaries.append(acc)
        boundaries[-1] = 1.0

        pending_loads = []
        for idx, eid in enumerate(host_ids):
            sub_el = self.elements[eid]
            node_a = ordered_nodes[idx]
            forward = (sub_el.node_i.id == node_a.id)
            for load in self.loads:
                if getattr(load, 'element_id', None) != eid:
                    continue
                pending_loads.append((load, boundaries[idx], boundaries[idx + 1], forward, seg_lengths[idx]))

        new_el = self.add_element(start_node, end_node, keep_el.section, keep_el.beta_angle)
        self._copy_frame_properties(new_el, keep_el)
        new_el.releases_i = release_i
        new_el.releases_j = release_j

        self._assign_merged_loads(new_el, pending_loads)

        removed_node_ids = list(interior_ids)
        for eid in host_ids:
            self.remove_element(eid)

        return {
            "created_elem_id": new_el.id,
            "removed_elem_ids": list(host_ids),
            "removed_node_ids": removed_node_ids,
        }

    def _assign_merged_loads(self, new_el, pending_loads):
        """
        pending_loads: list of (load, t0, t1, forward, el_len) tuples, one
        entry per load that lived on one of the original sub-frames, in
        chain order.

        Point loads just get remapped to their new position on the merged
        frame (they're already discrete, nothing to combine).

        Distributed loads (MemberLoad) that share the same characteristics
        (pattern, uniform wx/wy/wz component, coord system, direction,
        type) are SPLICED BACK INTO ONE continuous trapezoidal load
        spanning the whole merged frame — this is the piece that was
        missing before: naively re-assigning each sub-frame's load with
        mode='add' stacks N separate load entries on the merged frame
        instead of reconstructing the single original load.

        NOTE: for loads defined in a 'Local' coord_system on a segment that
        ran opposite to the merged frame's I->J direction (forward=False),
        the local-axis sign may need a manual review afterward — local
        axes aren't recomputed here.
        """
        point_entries = []
        dist_groups = {}

        for load, t0, t1, forward, el_len in pending_loads:
            is_point = hasattr(load, 'force') and hasattr(load, 'dist')
            if is_point:
                point_entries.append((load, t0, t1, forward, el_len))
                continue

            distances = list(load.distances)
            magnitudes = list(load.magnitudes)
            if not load.is_relative and el_len > 1e-9:
                distances = [d / el_len for d in distances]
            if not forward:
                distances = [1.0 - d for d in reversed(distances)]
                magnitudes = list(reversed(magnitudes))

            key = (
                load.pattern_name,
                round(float(load.wx), 9), round(float(load.wy), 9), round(float(load.wz), 9),
                getattr(load, 'projected', False), getattr(load, 'coord_system', 'Global'),
                getattr(load, 'load_direction', 'Gravity'), getattr(load, 'load_type', 'Force'),
            )
            dist_groups.setdefault(key, []).append((t0, t1, distances, magnitudes))

        for load, t0, t1, forward, el_len in point_entries:
            local = load.dist if load.is_relative else (load.dist / el_len if el_len > 1e-9 else 0.0)
            local = min(max(local, 0.0), 1.0)
            if not forward:
                local = 1.0 - local
            merged_t = t0 + local * (t1 - t0)
            self.assign_member_point_load(
                new_el.id, load.pattern_name, load.force, merged_t, True,
                load.coord_system, load.direction,
                getattr(load, 'load_type', 'Force'), mode='add'
            )

        for key, segments in dist_groups.items():
            segments.sort(key=lambda s: s[0])
            pattern_name, wx, wy, wz, projected, coord_system, load_direction, load_type = key

            points = []
            for seg_t0, seg_t1, distances, magnitudes in segments:
                span = seg_t1 - seg_t0
                for d, m in zip(distances, magnitudes):
                    points.append((seg_t0 + d * span, m))
            points.sort(key=lambda p: p[0])

            merged_points = []
            for d, m in points:
                if merged_points and abs(d - merged_points[-1][0]) < 1e-7:
                    merged_points[-1] = (merged_points[-1][0], (merged_points[-1][1] + m) / 2.0)
                else:
                    merged_points.append((d, m))

            self.assign_member_load(
                new_el.id, pattern_name, wx, wy, wz,
                projected=projected, coord_system=coord_system, mode='add',
                distances=[p[0] for p in merged_points],
                magnitudes=[p[1] for p in merged_points],
                is_relative=True,
                load_direction=load_direction, load_type=load_type
            )

OPENSEES_CASE_DEFAULTS = {
    "test_type": "NormDispIncr",
    "tolerance": 1e-6,
    "max_iter": 50,
    "algorithm": "Newton",
    "step_size": 0.001,
    "path_mode": "Single Target",
    "disp_history": [],
    "load_steps": 10,                                                                                     
    "load_path_mode": "Monotonic",                                                                                      
    "load_history": [],                                                                                           
    "n_int_pts": 5,
    "fiber_size_ratio": 16,
    "integration": "Lobatto",                                
    "hinge_length": 0.0,                                               
    "bar_slip": False,                                                                           
    "safety_check": True,                                                                          
    "relax_on_fail": True,                                                                                                           
    "relax_ceiling": 1e-5,                                                                                 
    "slip_R": 0.5, "slip_b": 0.3,                                                                  
    "slip_sy_mult": 1.0, "slip_su_mult": 35.0,                                                              
    "slip_concrete": "stiff",                                                                                                                                                                         
    "shear_spring": None,                                                                                                     
}

SHEAR_SPRING_UI_DEFAULTS = {
    "N": 0.0,                                                                                       
    "Vy_scale": 1.0, "k0_scale": 1.0,
    "alpha": 0.01,                                             
    "pinchX": 1.0, "pinchY": 1.0,                                          
    "damage1": 0.0, "damage2": 0.0, "beta": 0.0,
    "shear_stiffness": "cracked",                                                                       
    "e3_mult": 3.0,                                                                          
}

def default_opensees_block():
    """Fresh copy of the per-case OpenSees settings."""
    blk = dict(OPENSEES_CASE_DEFAULTS)
    blk["disp_history"] = []
    blk["load_history"] = []
    return blk

def get_opensees_block(case):
    """The case's OpenSees settings, with defaults filled in for anything missing."""
    blk = default_opensees_block()
    blk.update(getattr(case, "opensees", None) or {})
    blk["disp_history"] = list(blk.get("disp_history") or [])
    blk["load_history"] = list(blk.get("load_history") or [])
    return blk

class LoadCase:
    def __init__(self, name, case_type="Linear Static"):
        self.name = name
        self.case_type = case_type                                                            
        
        self.loads = [] 
        
        self.mass_source = "Default"       

        self.geom_nonlin = "None"                                           
        self.load_application = "Full Load"                                                 
        self.continue_from_case = None                                                                 
        self.disp_control_node_id = None                                                               
        self.disp_control_dof = "U1"                                                     
        self.disp_control_magnitude = 0.1                                                                         
        self.disp_control_tol = 1e-6                                                             
        self.results_saved = "Final State Only"
        self.min_saved_states = 1
        self.max_saved_states = 100
        self.save_positive_disp_only = False
        
        self.max_total_steps = 200
        self.max_null_steps = 50
        self.use_event_stepping = True
        self.event_lumping_tol = 0.01
        self.max_events_per_step = 24
        self.use_iteration = True
        self.max_const_stiff_iter = 10
        self.max_nr_iter = 40
        self.iter_conv_tol = 1e-4
        self.use_line_search = False
        
        self.tf_max_iter = 10
        self.tf_conv_tol = 0.01
        self.tf_accel_factor = 1.0
        self.continue_if_no_converge = False

        self.use_fd_tangent = False

        self.hinge_snap = True                                                                               
        self.hinge_snap_scope = "tension"                                 
        self.stop_on_fiber_failure = False                                                             
        self.residual_stiffness = 1e-8                                                                             
        self.min_step_frac = 1e-4                                                               
        self.max_event_probes = 12
        self.auto_cutback = True
        self.max_step_attempts = 0                                                       

        self.opensees = default_opensees_block()

        self.formulation = "Corotational"
        self.corot_type = "Commercial Compatibility"

        self.modal_case = None                                                     
        self.num_modes = 12
        self.modal_fiber_hinges = False                                                                 
        self.ltha_loads = []

class LoadCombination:
    def __init__(self, name, combo_type="Linear Add"):
        self.name = name
        self.combo_type = combo_type                                                    
        self.cases = []
