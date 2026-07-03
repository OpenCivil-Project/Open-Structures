import json
from core.mesh import Node, FrameElement
from core.properties import (Material, RectangularSection, ISection, GeneralSection,
                             CircularSection, PipeSection, TubeSection, TrapezoidalSection,
                             ArbitrarySection, ShellSection, PlaneSection, AsolidSection, AreaSection)
from core.grid import GridLines
from core.boundary import apply_restraint, Restraint
from core.mesh import Slab, AreaElement 
from core.units import unit_registry
import numpy as np
from core.loads import LoadPattern, NodalLoad, MemberLoad, MemberPointLoad, AreaGravityLoad, AreaUniformLoad

class TSC2018Data:
    def __init__(self):
        # Direction and Eccentricity
        self.direction = "X" # "X" or "Y"
        self.eccentricity = 0.05
        
        # Time Period
        self.period_method = "Program Calc" # "Approx", "Program Calc", "User"
        self.ct = 0.075 # Default for concrete
        self.user_t = 0.0
        
        # Seismic Coefficients
        self.ss = 0.0
        self.s1 = 0.0
        self.tl = 6.0
        self.site_class = "ZB"
        
        # Factors
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
                 projected=False, coord_system="Global"):
        self.element_id = element_id
        self.pattern_name = pattern_name
        self.wx = float(wx)
        self.wy = float(wy)
        self.wz = float(wz)
        self.projected = bool(projected)
        self.coord_system = coord_system                      

    def __repr__(self):
        return f"MemberLoad(elem={self.element_id}, {self.coord_system}, wz={self.wz})"

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

        self.graphics_settings = {}                        
        
        self.nodes = {}                        
        self.elements = {}                             
        self.materials = {}                          
        self.sections = {}                          
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
        self.constraints = {}
                         
        self.grid = GridLines()
        
        self._node_counter = 1
        self._elem_counter = 1
        self._slab_counter = 1

        self.add_load_pattern("DEAD", "DEAD", 1.0)

    def add_material(self, material):
        self.materials[material.name] = material
        return material

    def add_section(self, section):
        self.sections[section.name] = section
        return section

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
                           projected=False, coord_system="Global", mode="replace"):
        """
        Assigns distributed load to a frame element.
        wx, wy, wz: Load magnitude in the specified coordinate system axes.
        coord_system: "Global" or "Local".
        """
        if element_id not in self.elements:
            raise KeyError(f"Element {element_id} does not exist.")
        
        existing_indices = []
        for i, load in enumerate(self.loads):
            if hasattr(load, 'element_id') and load.element_id == element_id and load.pattern_name == pattern_name:
                existing_indices.append(i)

        if mode == "delete":
            for i in reversed(existing_indices):
                del self.loads[i]
            return

        elif mode == "replace":
            for i in reversed(existing_indices):
                del self.loads[i]
            
            if any([wx, wy, wz]):
                new_load = MemberLoad(element_id, pattern_name, wx, wy, wz, 
                                      projected=projected, coord_system=coord_system)
                self.loads.append(new_load)

        elif mode == "add":
                                                                   
            added = False
            for idx in existing_indices:
                existing = self.loads[idx]
                if existing.coord_system == coord_system and existing.projected == projected:
                    existing.wx += wx
                    existing.wy += wy
                    existing.wz += wz
                    added = True
                    break
            
            if not added and any([wx, wy, wz]):
                new_load = MemberLoad(element_id, pattern_name, wx, wy, wz, 
                                      projected=projected, coord_system=coord_system)
                self.loads.append(new_load)

    def save_to_file(self, filepath, progress=None):
        """Serializes the model data to a JSON file"""
        print(">>> RUNNING THE NEW SAVE METHOD <<<") # ADD THIS
        def _p(msg):
            if progress: progress(msg)
            
        _p("Saving project info & graphics...")
        data = {
            "info": {
                "name": self.name,
                "units": unit_registry.current_unit_label 
            },
            "graphics": self.graphics_settings,
            "load_cases": [],
            "grid": {
                "x_lines": self.grid.x_lines,
                "y_lines": self.grid.y_lines,
                "z_lines": self.grid.z_lines
            },
            "materials": [],
            "sections": [],
            "nodes": [],
            "elements": [],
            "slabs": [],    
            "area_elements": [],
            "area_sections": [],   
            "constraints": [],
            "load_patterns": [],
            "loads": [],
            "mass_sources": [],
            "functions": [],
            "th_functions": []
        }

        _p(f"Saving {len(self.load_cases)} load case(s)...")
        for lc in self.load_cases.values():
            data["load_cases"].append({
                "name": lc.name,
                "type": lc.case_type,
                "loads": lc.loads,                                                             
                "p_delta": lc.p_delta,
                "mass_source": lc.mass_source,
                "num_modes": getattr(lc, 'num_modes', 12),
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
            data["materials"].append({
                "name": mat.name,
                "E": mat.E, "nu": mat.nu, "G": mat.G, "rho": mat.density,
                "type": mat.mat_type, "fy": mat.fy, "fu": mat.fu
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
                    "As3": sec.Asz
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
            
            data["sections"].append(sec_data)

        _p(f"Saving {len(self.nodes)} nodes & boundary conditions...")
        for n_id in sorted(self.nodes.keys()):
            n = self.nodes[n_id]
            data["nodes"].append({
                "id": n.id, "x": n.x, "y": n.y, "z": n.z,
                "restraints": n.restraints, "diaphragm": n.diaphragm_name  
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

        _p(f"Saving {len(self.slabs)} slab(s)...")
        for slab in self.slabs.values():
            data["slabs"].append({"id": slab.id, "node_ids": [n.id for n in slab.nodes], "thick": slab.thickness})

        _p(f"Saving {len(self.area_elements)} area element(s)...")
        for ae in self.area_elements.values():
            data["area_elements"].append({
                "id": ae.id, 
                "node_ids": [n.id for n in ae.nodes], 
                "sec_name": ae.section.name
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
                    "coord": getattr(load, 'coord_system', "Global")
                })
                
            elif hasattr(load, 'node_id'):
                load_data.update({
                    "type": "nodal",
                    "node_id": load.node_id,
                    "fx": load.fx, "fy": load.fy, "fz": load.fz,
                    "mx": load.mx, "my": load.my, "mz": load.mz
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
                     "bending_thickness":  s.bending_thickness}
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
            json.dump(data, f, indent=4)
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
        self.slabs.clear(); self.area_elements.clear(); self.constraints.clear()
        self.load_combos.clear()
        self.functions = {}
        self.th_functions = {}
        self._node_counter = 1; self._elem_counter = 1; self._slab_counter = 1; self._area_elem_counter = 1
        
        _p("Loading project info & grid...")
        self.name = data["info"]["name"]
        self.saved_unit_system = data["info"].get("units", "kN, m, C")
        
        grid_data = data["grid"]
        if "x_lines" in grid_data:
            self.grid.x_lines = grid_data["x_lines"]; self.grid.y_lines = grid_data["y_lines"]; self.grid.z_lines = grid_data["z_lines"]
        else:
            self.grid.x_grids = grid_data["x"]; self.grid.y_grids = grid_data["y"]; self.grid.z_grids = grid_data["z"]

        _p(f"Loading {len(data.get('materials', []))} material(s)...")
        for m_data in data["materials"]:
            mat = Material(m_data["name"], m_data["E"], m_data["nu"], m_data["rho"], m_data["type"], m_data.get("fy", 0), m_data.get("fu", 0))
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
                    'y_c': s_data.get("y_c", 0.0),
                    'z_c': s_data.get("z_c", 0.0),
                }
                vertices = [tuple(v) for v in s_data.get("vertices", [])]
                sec = ArbitrarySection(s_data["name"], mat, vertices, props_dict)
            elif s_data["type"] == "general":
                p = s_data["properties"]
                props_dict = {
                    'A': p["A"], 'J': p["J"], 'I33': p["I33"], 'I22': p["I22"],
                    'As2': p["As2"], 'As3': p["As3"]
                }
                sec = GeneralSection(s_data["name"], mat, props_dict)

            if sec:
                if "color" in s_data: sec.color = tuple(s_data["color"])
                if "modifiers" in s_data: sec.modifiers = s_data["modifiers"]
                self.add_section(sec)

        _AREA_CLS = {"ShellSection": ShellSection,
                     "PlaneSection": PlaneSection,
                     "AsolidSection": AsolidSection}
        
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
            self._node_counter = max(self._node_counter, n_id + 1)

        _p("Loading diaphragm constraints...")
        if "constraints" in data:
            for c_data in data["constraints"]: self.add_constraint(c_data["name"], c_data["axis"])

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
            elif s_data["type"] == "PlaneSection":
                sec = PlaneSection(
                    s_data["name"], mat,
                    plane_type=s_data.get("plane_type", "Plane-Stress"),
                    incompatible_modes=s_data.get("incompatible_modes", True),
                    thickness=s_data.get("thickness", 0.1),
                    material_angle=s_data.get("material_angle", 0.0),
                    display_color=s_data.get("display_color", "#FF00FF")
                )
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

        _p("Loading area elements...")
        if "area_elements" in data:
            for ae_data in data["area_elements"]:
                ae_nodes = [self.nodes[nid] for nid in ae_data["node_ids"] if nid in self.nodes]
                sec = self.area_sections.get(ae_data["sec_name"])
                
                if len(ae_nodes) >= 3 and sec:
                    new_ae = self.add_area_element(ae_nodes, sec)
                    del self.area_elements[new_ae.id]
                    new_ae.id = ae_data["id"]
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
                raw_rsa = lc_data.get("rsa_loads", [])
                new_lc.rsa_loads = [tuple(item) for item in raw_rsa]
                new_lc.modal_comb = lc_data.get("modal_comb", "SRSS")
                new_lc.dir_comb = lc_data.get("dir_comb", "SRSS")
                new_lc.p_delta = lc_data.get("p_delta", False)
                new_lc.mass_source = lc_data.get("mass_source", "Default")
                new_lc.num_modes = lc_data.get("num_modes", 12)
                new_lc.modal_damping = lc_data.get("modal_damping", 0.05)
                new_lc.damping    = lc_data.get("ltha_damping", 0.05)
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
                
                # <--- ADDED AUTO_LATERAL LOAD --->
                lp = self.load_patterns[lp_data["name"]]
                lp.auto_lateral = lp_data.get("auto_lateral", "None")

                if "seismic_data" in lp_data:
                    sd = UserSeismicData()
                    sd.eccentricity = lp_data["seismic_data"]["eccentricity"]
                    sd.diaphragm_loads = lp_data["seismic_data"]["diaphragm_loads"]
                    lp.seismic_data = sd
                    
                # <--- ADDED TSC-2018 REBUILD BLOCK --->
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

        _p(f"Loading {len(data.get('loads', []))} load assignment(s)...")
        if "loads" in data:
            for load_data in data["loads"]:
                pattern_name = load_data["pattern"]
                l_type = load_data.get("type", "nodal")                         
                
                if l_type == "member": l_type = "member_dist"

                if l_type == "nodal":
                    new_load = NodalLoad(load_data["node_id"], pattern_name, 
                                         load_data["fx"], load_data["fy"], load_data["fz"], 
                                         load_data["mx"], load_data["my"], load_data["mz"])
                    self.loads.append(new_load)

                elif l_type == "member_dist":
                                                                                       
                    coord = load_data.get("coord", "Global")
                    proj = load_data.get("projected", False)
                    new_load = MemberLoad(load_data["element_id"], pattern_name, 
                                          load_data["wx"], load_data["wy"], load_data["wz"],
                                          projected=proj, coord_system=coord)
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
        
        _p("Load complete.")
        print(f"Model loaded from {filepath}")

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
                        self.assign_joint_load(
                            new_node.id, 
                            old_load.pattern_name,
                            old_load.fx, old_load.fy, old_load.fz,
                            old_load.mx, old_load.my, old_load.mz,
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

    def mesh_area_elements(self, area_ids, mode="divisions", n=1, m=1, max_x=0.5, max_y=0.5, divide_frames=True):
        """
        Meshes selected 4-node AreaElements either by exact N x M divisions or by a Max Size.
        Optionally divides any adjacent frame elements that touch the new nodes.
        """
        import math
        if not area_ids:
            return 0

        elements_meshed = 0
        elements_to_delete = []
        new_mesh_nodes = set()                                                  

        for eid in area_ids:
            if eid not in self.area_elements:
                continue

            old_elem = self.area_elements[eid]
            nodes = old_elem.nodes
            
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
                    
                    self.add_area_element([n1, n2, n3, n4], section)

            elements_to_delete.append((eid, nodes))
            elements_meshed += 1

        for eid, original_nodes in elements_to_delete:
            del self.area_elements[eid]
            for n in original_nodes:
                self._cleanup_orphan_node(n.id)

        if divide_frames and new_mesh_nodes:
            self._split_frames_by_nodes(new_mesh_nodes)
        
        return elements_meshed

    def _split_frames_by_nodes(self, split_nodes):
        """
        Helper method to split existing frame elements if any of the passed nodes
        lie exactly on their line segment. Keeps end releases intact.
        """
                                                                                             
        for el in list(self.elements.values()):
            p_i = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
            p_j = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
            L_total = np.linalg.norm(p_j - p_i)
            
            if L_total < 1e-6: 
                continue

            nodes_on_segment = []
            for n in split_nodes:
                                               
                if n.id == el.node_i.id or n.id == el.node_j.id:
                    continue
                
                p_n = np.array([n.x, n.y, n.z])
                d1 = np.linalg.norm(p_n - p_i)
                d2 = np.linalg.norm(p_j - p_n)
                
                if abs((d1 + d2) - L_total) < 1e-5:
                    nodes_on_segment.append((d1, n))
            
            if not nodes_on_segment:
                continue
                
            nodes_on_segment.sort(key=lambda x: x[0])
            
            sec = el.section
            beta = el.beta_angle
            rel_i = el.releases_i
            rel_j = el.releases_j
            eid_to_remove = el.id
            
            current_start_node = el.node_i
            for i, (dist, n_mid) in enumerate(nodes_on_segment):
                new_el = self.add_element(current_start_node, n_mid, sec, beta)
                if i == 0:
                    new_el.releases_i = rel_i                                                   
                current_start_node = n_mid
            
            last_el = self.add_element(current_start_node, el.node_j, sec, beta)
            last_el.releases_j = rel_j                                                
            
            self.remove_element(eid_to_remove)

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

        
class LoadCase:
    def __init__(self, name, case_type="Linear Static"):
        self.name = name
        self.case_type = case_type                                                            
        
        self.loads = [] 
        
        self.mass_source = "Default"                        
        self.p_delta = False                                   
        self.modal_case = None                                                     
        self.num_modes = 12
        self.ltha_loads = []

class LoadCombination:
    def __init__(self, name, combo_type="Linear Add"):
        self.name = name
        self.combo_type = combo_type  # "Linear Add", "Envelope", "Absolute Add", "SRSS"
        self.cases = []               # List of tuples: [("LoadCaseName", scale_factor)]