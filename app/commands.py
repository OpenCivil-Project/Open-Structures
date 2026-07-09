from PyQt6.QtGui import QUndoCommand
import copy
from core.loads import NodalLoad, MemberLoad, MemberPointLoad

class CmdDrawFrame(QUndoCommand):

    """
    Command to Draw a Frame Element (and potentially new nodes).
    """
    def __init__(self, model, main_window, n1_coords, n2_coords, section, 
                 rel_i=None, rel_j=None, beta_angle=0.0, 
                 cardinal_point=10, no_transform=False, description="Draw Frame"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.n1_coords = n1_coords
        self.n2_coords = n2_coords
        self.section = section
        
        self.rel_i = rel_i or [False, False, False, False, False, False]
        self.rel_j = rel_j or [False, False, False, False, False, False]
        
        self.beta_angle = float(beta_angle)
        self.cardinal_point = cardinal_point
        self.no_transform = no_transform
        
        self.created_elem_id = None
        self.created_n1_id = None
        self.created_n2_id = None

    def redo(self):
        n1 = self.model.get_or_create_node(*self.n1_coords)
        n2 = self.model.get_or_create_node(*self.n2_coords)
        
        el = self.model.add_element(n1, n2, self.section)
        el.beta_angle = self.beta_angle
        
        el.releases_i = self.rel_i[:]
        el.releases_j = self.rel_j[:]
        
        el.do_not_transform_stiffness = self.no_transform
        
        if self.cardinal_point != 10:
                                                                             
            el.cardinal_point = self.cardinal_point
            cy, cz = el.get_cardinal_offsets()
            
            v1, v2, v3 = el.get_local_axes()
            
            global_offset = (cy * v2) + (cz * v3)
            
            el.joint_offset_i = global_offset
            el.joint_offset_j = global_offset
            
            el.cardinal_point = 10
        else:
            el.cardinal_point = 10
        
        self.created_elem_id = el.id
        self.created_n1_id = n1.id
        self.created_n2_id = n2.id
        
        self._refresh_view()
        
    def undo(self):
        if self.created_elem_id:
            self.model.remove_element(self.created_elem_id)
        self._refresh_view()

    def _refresh_view(self):
        self.main_window.draw_both_canvases()
        
class CmdDeleteSelection(QUndoCommand):
    """
    Command to Delete Frames, Shells and/or Joints.
    Includes DOUBLE SAFETY CHECK:
    1. Auto-detects orphans created by deleting frames OR shells.
    2. Protects explicitly selected nodes if they are still supporting other frames/shells.
    """
    def __init__(self, model, main_window, node_ids, elem_ids, area_elem_ids=None):
        super().__init__("Delete Selection")
        self.model = model
        self.main_window = main_window
        
        ids_elements_to_delete = set(elem_ids)
        ids_area_elements_to_delete = set(area_elem_ids or [])
        
        nodes_to_actually_delete = set()
        
        for nid in node_ids:
                                                                       
            if self._is_truly_orphaned(model, nid, ids_elements_to_delete, ids_area_elements_to_delete):
                nodes_to_actually_delete.add(nid)
        
        self.node_ids_to_del = list(nodes_to_actually_delete)
        self.elem_ids_to_del = list(ids_elements_to_delete)
        self.area_elem_ids_to_del = list(ids_area_elements_to_delete)
        
        safe_nodes_to_delete = set()
                                                                                      
        for eid in ids_elements_to_delete:
            if eid in model.elements:
                el = model.elements[eid]
                if self._will_become_orphan(model, el.node_i.id, ids_elements_to_delete, ids_area_elements_to_delete):
                    safe_nodes_to_delete.add(el.node_i.id)
                if self._will_become_orphan(model, el.node_j.id, ids_elements_to_delete, ids_area_elements_to_delete):
                    safe_nodes_to_delete.add(el.node_j.id)

        if hasattr(model, 'area_elements'):
            for aeid in ids_area_elements_to_delete:
                if aeid in model.area_elements:
                    ae = model.area_elements[aeid]
                    for node in ae.nodes:
                        if self._will_become_orphan(model, node.id, ids_elements_to_delete, ids_area_elements_to_delete):
                            safe_nodes_to_delete.add(node.id)
        
        self.node_ids_to_del = list(safe_nodes_to_delete)
        self.elem_ids_to_del = list(ids_elements_to_delete)
        self.area_elem_ids_to_del = list(ids_area_elements_to_delete)

        self.saved_nodes = {}
        self.saved_elems = {}
        self.saved_area_elems = {}
        self.saved_loads = []

        for eid in self.elem_ids_to_del:
            if eid in model.elements:
                self.saved_elems[eid] = copy.deepcopy(model.elements[eid])

        if hasattr(model, 'area_elements'):
            for aeid in self.area_elem_ids_to_del:
                if aeid in model.area_elements:
                    self.saved_area_elems[aeid] = copy.deepcopy(model.area_elements[aeid])
        
        for nid in self.node_ids_to_del:
            if nid in model.nodes:
                self.saved_nodes[nid] = copy.deepcopy(model.nodes[nid])

        for load in model.loads:
            should_save = False
            if hasattr(load, 'element_id') and load.element_id in self.elem_ids_to_del:
                should_save = True
            elif hasattr(load, 'node_id') and load.node_id in self.node_ids_to_del:
                should_save = True
            if should_save:
                self.saved_loads.append(copy.deepcopy(load))

    def _is_truly_orphaned(self, model, node_id, deleted_elem_ids, deleted_area_ids):
        """
        Returns True if the node is NOT connected to any element that is 
        staying in the model.
        """
                                                                             
        for el in model.elements.values():
            if el.id not in deleted_elem_ids:
                if el.node_i.id == node_id or el.node_j.id == node_id:
                    return False 
        
        if hasattr(model, 'area_elements'):
            for ae in model.area_elements.values():
                if ae.id not in deleted_area_ids:
                    if any(n.id == node_id for n in ae.nodes):
                        return False 
        
        if any(model.nodes[node_id].restraints):
            return False 
            
        return True
    
    def _will_become_orphan(self, model, node_id, deleted_element_ids, deleted_area_ids=None):
        """
        Returns True if the node will have NO connected elements
        after the specified frame elements AND shell elements are deleted.
        Checks both model.elements (frames) and model.area_elements (shells).
        """
        deleted_area_ids = deleted_area_ids or set()

        for el in model.elements.values():
            if el.id not in deleted_element_ids:
                if el.node_i.id == node_id or el.node_j.id == node_id:
                    return False

        if hasattr(model, 'area_elements'):
            for ae in model.area_elements.values():
                if ae.id not in deleted_area_ids:
                    if any(n.id == node_id for n in ae.nodes):
                        return False

        return True

    def redo(self):
                            
        for eid in self.elem_ids_to_del:
            if eid in self.model.elements:
                self.model.remove_element(eid)

        if hasattr(self.model, 'area_elements'):
            for aeid in self.area_elem_ids_to_del:
                if aeid in self.model.area_elements:
                    del self.model.area_elements[aeid]
        
        for nid in self.node_ids_to_del:
            if nid in self.model.nodes:
                del self.model.nodes[nid]

        self.model.loads = [
            load for load in self.model.loads
            if not (hasattr(load, 'element_id') and load.element_id in self.elem_ids_to_del)
            and not (hasattr(load, 'node_id') and load.node_id in self.node_ids_to_del)
        ]

        self.main_window.selected_ids = []
        self.main_window.selected_node_ids = []
        if hasattr(self.main_window, 'selected_area_ids'):
            self.main_window.selected_area_ids = []
        self._refresh_view()

    def undo(self):
                                                               
        for nid, node_obj in self.saved_nodes.items():
            self.model.nodes[nid] = node_obj
            self.model._node_counter = max(self.model._node_counter, nid + 1)

        for eid, el_obj in self.saved_elems.items():
            
            if el_obj.node_i.id in self.model.nodes:
                el_obj.node_i = self.model.nodes[el_obj.node_i.id]
            if el_obj.node_j.id in self.model.nodes:
                el_obj.node_j = self.model.nodes[el_obj.node_j.id]
            
            if hasattr(el_obj, 'section') and el_obj.section is not None:
                sec_name = el_obj.section.name
                if sec_name in self.model.sections:
                    el_obj.section = self.model.sections[sec_name]

            self.model.elements[eid] = el_obj
            self.model._elem_counter = max(self.model._elem_counter, eid + 1)

        if hasattr(self.model, 'area_elements'):
            for aeid, ae_obj in self.saved_area_elems.items():
                ae_obj.nodes = [
                    self.model.nodes.get(n.id, n) for n in ae_obj.nodes
                ]
                if hasattr(ae_obj, 'section') and ae_obj.section is not None:
                    sec_name = ae_obj.section.name
                    if hasattr(self.model, 'area_sections') and sec_name in self.model.area_sections:
                        ae_obj.section = self.model.area_sections[sec_name]
                    elif sec_name in self.model.sections:
                        ae_obj.section = self.model.sections[sec_name]
                self.model.area_elements[aeid] = ae_obj
                if hasattr(self.model, '_area_elem_counter'):
                    self.model._area_elem_counter = max(self.model._area_elem_counter, aeid + 1)

        for load in self.saved_loads:
            self.model.loads.append(copy.deepcopy(load))

        self._refresh_view()

    def _refresh_view(self):
        self.main_window.draw_both_canvases()
        
class CmdAssignRestraints(QUndoCommand):
    def __init__(self, model, main_window, node_ids, new_restraints, description="Assign Restraints"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.node_ids = node_ids
        self.new_restraints = new_restraints                          
        
        self.old_states = {}
        for nid in node_ids:
            if nid in model.nodes:
                self.old_states[nid] = model.nodes[nid].restraints[:]

    def redo(self):
        for nid in self.node_ids:
            if nid in self.model.nodes:
                self.model.nodes[nid].restraints = self.new_restraints[:]
        self.main_window.draw_both_canvases()

    def undo(self):
        for nid, old_res in self.old_states.items():
            if nid in self.model.nodes:
                self.model.nodes[nid].restraints = old_res[:]
        self.main_window.draw_both_canvases()

class CmdAssignDiaphragm(QUndoCommand):
    def __init__(self, model, main_window, node_ids, diaphragm_name):
        super().__init__("Assign Diaphragm")
        self.model = model
        self.main_window = main_window
        self.node_ids = node_ids
        self.new_name = diaphragm_name
        
        self.old_states = {}
        for nid in node_ids:
            if nid in model.nodes:
                self.old_states[nid] = model.nodes[nid].diaphragm_name

    def redo(self):
        for nid in self.node_ids:
            if nid in self.model.nodes:
                self.model.nodes[nid].diaphragm_name = self.new_name
        self.main_window.draw_both_canvases()

    def undo(self):
        for nid, old_name in self.old_states.items():
            if nid in self.model.nodes:
                self.model.nodes[nid].diaphragm_name = old_name
        self.main_window.draw_both_canvases()

class CmdAssignReleases(QUndoCommand):
    def __init__(self, model, main_window, elem_ids, rel_i, rel_j):
        super().__init__("Assign Releases")
        self.model = model
        self.main_window = main_window
        self.elem_ids = elem_ids
        self.new_rel_i = rel_i
        self.new_rel_j = rel_j
        
        self.old_states = {}                        
        for eid in elem_ids:
            if eid in model.elements:
                el = model.elements[eid]
                self.old_states[eid] = (el.releases_i[:], el.releases_j[:])

    def redo(self):
        for eid in self.elem_ids:
            if eid in self.model.elements:
                self.model.elements[eid].releases_i = self.new_rel_i[:]
                self.model.elements[eid].releases_j = self.new_rel_j[:]
        self.main_window.draw_both_canvases()

    def undo(self):
        for eid, (old_i, old_j) in self.old_states.items():
            if eid in self.model.elements:
                self.model.elements[eid].releases_i = old_i[:]
                self.model.elements[eid].releases_j = old_j[:]
        self.main_window.draw_both_canvases()

class CmdAssignLocalAxes(QUndoCommand):
    def __init__(self, model, main_window, elem_ids, angle):
        super().__init__("Assign Local Axis")
        self.model = model
        self.main_window = main_window
        self.elem_ids = elem_ids
        self.new_angle = float(angle)
        
        self.old_states = {}
        for eid in elem_ids:
            if eid in model.elements:
                self.old_states[eid] = model.elements[eid].beta_angle

    def redo(self):
        for eid in self.elem_ids:
            if eid in self.model.elements:
                self.model.elements[eid].beta_angle = self.new_angle
        self.main_window.draw_both_canvases()

    def undo(self):
        for eid, old_ang in self.old_states.items():
            if eid in self.model.elements:
                self.model.elements[eid].beta_angle = old_ang
        self.main_window.draw_both_canvases()

class CmdAssignInsertion(QUndoCommand):
    """
    Handles Cardinal Points and Joint Offsets.
    Includes logic to transform Local offsets into Global for storage.
    """
                                       
    def __init__(self, model, main_window, elem_ids, cardinal, raw_i, raw_j, coord_sys="Local", no_transform=False):
        super().__init__("Assign Insertion Point")
        self.model = model
        self.main_window = main_window
        self.elem_ids = elem_ids
        
        self.cardinal = cardinal
        self.raw_i = raw_i                                  
        self.raw_j = raw_j                                  
        self.coord_sys = coord_sys
        
        self.no_transform = no_transform
        
        self.old_states = {}
        for eid in elem_ids:
            if eid in model.elements:
                el = model.elements[eid]
                self.old_states[eid] = (
                    el.cardinal_point, 
                    el.joint_offset_i.copy(), 
                    el.joint_offset_j.copy(),
                                                                        
                    getattr(el, 'do_not_transform_stiffness', False) 
                )

    def redo(self):
        import numpy as np
        for eid in self.elem_ids:
            if eid in self.model.elements:
                el = self.model.elements[eid]
                el.cardinal_point = self.cardinal
                
                el.do_not_transform_stiffness = self.no_transform
                
                if self.coord_sys == "Global":
                    el.joint_offset_i = np.array(self.raw_i)
                    el.joint_offset_j = np.array(self.raw_j)
                else:
                    n1, n2 = el.node_i, el.node_j
                    p1 = np.array([n1.x, n1.y, n1.z])
                    p2 = np.array([n2.x, n2.y, n2.z])
                    
                    vx = p2 - p1
                    L = np.linalg.norm(vx)
                    if L < 1e-9: v1 = np.array([1,0,0])
                    else: v1 = vx / L
                    
                    if np.isclose(abs(v1[2]), 1.0): 
                        up = np.array([0.0, 1.0, 0.0]) 
                    else:
                        up = np.array([0.0, 0.0, 1.0])

                    v2 = np.cross(up, v1)
                    v2 /= np.linalg.norm(v2)
                    v3 = np.cross(v1, v2)
                    v3 /= np.linalg.norm(v3)
                    
                    if el.beta_angle != 0:
                        rad = np.radians(el.beta_angle)
                        c = np.cos(rad); s = np.sin(rad)
                        v2_rot = c * v2 + s * v3
                        v3_rot = -s * v2 + c * v3
                        v2, v3 = v2_rot, v3_rot

                    el.joint_offset_i = (self.raw_i[0] * v1) + (self.raw_i[1] * v2) + (self.raw_i[2] * v3)
                    el.joint_offset_j = (self.raw_j[0] * v1) + (self.raw_j[1] * v2) + (self.raw_j[2] * v3)
                    
        self.main_window.draw_both_canvases()

    def undo(self):
                                                       
        for eid, (old_c, old_off_i, old_off_j, old_no_trans) in self.old_states.items():
            if eid in self.model.elements:
                el = self.model.elements[eid]
                el.cardinal_point = old_c
                el.joint_offset_i = old_off_i
                el.joint_offset_j = old_off_j
                
                el.do_not_transform_stiffness = old_no_trans
                
        self.main_window.draw_both_canvases()
        
class CmdAssignJointLoad(QUndoCommand):
    """
    Handles Add/Replace/Delete of Nodal Loads.
    Snapshot strategy: Save ALL loads for the target nodes/pattern, then restore.
    """
    def __init__(self, model, main_window, node_ids, pattern_name, 
                 fx, fy, fz, mx, my, mz, mode="replace"):
        super().__init__("Assign Joint Load")
        self.model = model
        self.main_window = main_window
        self.node_ids = node_ids
        self.pattern_name = pattern_name
        self.values = (fx, fy, fz, mx, my, mz)
        self.mode = mode
        
        self.old_loads = []
        for load in model.loads:
            if isinstance(load, NodalLoad):
                if load.node_id in node_ids and load.pattern_name == pattern_name:
                    self.old_loads.append(copy.deepcopy(load))

    def redo(self):
        fx, fy, fz, mx, my, mz = self.values
        for nid in self.node_ids:
            self.model.assign_joint_load(
                nid, self.pattern_name, fx, fy, fz, mx, my, mz, self.mode
            )
        self.main_window.draw_both_canvases()

    def undo(self):
                                                        
        for i in range(len(self.model.loads) - 1, -1, -1):
            load = self.model.loads[i]
            if isinstance(load, NodalLoad):
                if load.node_id in self.node_ids and load.pattern_name == self.pattern_name:
                    del self.model.loads[i]
        
        for old_load in self.old_loads:
            self.model.loads.append(copy.deepcopy(old_load))
            
        self.main_window.draw_both_canvases()

class CmdAssignFrameLoad(QUndoCommand):
    """
    Handles Distributed Loads (MemberLoad) including new Trapezoidal data.
    """
    def __init__(self, model, main_window, elem_ids, pattern_name, 
                 wx, wy, wz, projected, coord_sys, mode="replace",
                 distances=None, magnitudes=None, is_relative=True, 
                 load_direction="Gravity", load_type="Force"):                 
        super().__init__("Assign Distributed Load")
        self.model = model
        self.main_window = main_window
        self.elem_ids = elem_ids
        self.pattern_name = pattern_name
        self.mode = mode
        
        self.params = (wx, wy, wz, projected, coord_sys, 
                       distances, magnitudes, is_relative, 
                       load_direction, load_type)
        
        self.old_loads = []
        for load in model.loads:
            if isinstance(load, MemberLoad):
                if load.element_id in elem_ids and load.pattern_name == pattern_name:
                    self.old_loads.append(copy.deepcopy(load))

    def redo(self):
                                             
        (wx, wy, wz, proj, cs, dists, mags, is_rel, l_dir, l_type) = self.params
        
        for eid in self.elem_ids:
            self.model.assign_member_load(
                eid, self.pattern_name, wx, wy, wz, 
                proj, cs, self.mode,
                distances=dists, magnitudes=mags, is_relative=is_rel, 
                load_direction=l_dir, load_type=l_type
            )
        self.main_window.draw_both_canvases()

    def undo(self):
                                                                       
        for i in range(len(self.model.loads) - 1, -1, -1):
            load = self.model.loads[i]
            if isinstance(load, MemberLoad):
                if load.element_id in self.elem_ids and load.pattern_name == self.pattern_name:
                    del self.model.loads[i]
        
        for old_load in self.old_loads:
            self.model.loads.append(copy.deepcopy(old_load))
            
        self.main_window.draw_both_canvases()

class CmdAssignPointLoad(QUndoCommand):
    """
    Handles Concentrated Frame Loads (MemberPointLoad).
    """
    def __init__(self, model, main_window, elem_ids, pattern_name, 
                 force, dist, is_rel, coord, direction, l_type, mode="replace"):
        super().__init__("Assign Point Load")
        self.model = model
        self.main_window = main_window
        self.elem_ids = elem_ids
        self.pattern_name = pattern_name
        self.params = (force, dist, is_rel, coord, direction, l_type)
        self.mode = mode
        
        self.old_loads = []
        for load in model.loads:
            if isinstance(load, MemberPointLoad):
                if load.element_id in elem_ids and load.pattern_name == pattern_name:
                    self.old_loads.append(copy.deepcopy(load))

    def redo(self):
        f, d, rel, c, dire, lt = self.params
        for eid in self.elem_ids:
            self.model.assign_member_point_load(
                eid, self.pattern_name, f, d, rel, c, dire, lt, self.mode
            )
        self.main_window.draw_both_canvases()

    def undo(self):
        for i in range(len(self.model.loads) - 1, -1, -1):
            load = self.model.loads[i]
            if isinstance(load, MemberPointLoad):
                if load.element_id in self.elem_ids and load.pattern_name == self.pattern_name:
                    del self.model.loads[i]
                    
        for old_load in self.old_loads:
            self.model.loads.append(copy.deepcopy(old_load))
            
        self.main_window.draw_both_canvases()

class CmdAssignEndOffsets(QUndoCommand):
    def __init__(self, model, main_window, elem_ids, off_i, off_j, factor):
        super().__init__("Assign End Offsets")
        self.model = model
        self.main_window = main_window
        self.elem_ids = elem_ids
        self.new_vals = (off_i, off_j, factor)
        
        self.old_states = {}
        for eid in elem_ids:
            if eid in model.elements:
                el = model.elements[eid]
                self.old_states[eid] = (
                    getattr(el, 'end_offset_i', 0.0),
                    getattr(el, 'end_offset_j', 0.0),
                    getattr(el, 'rigid_zone_factor', 0.0)
                )

    def redo(self):
        off_i, off_j, factor = self.new_vals
        for eid in self.elem_ids:
            if eid in self.model.elements:
                el = self.model.elements[eid]
                el.end_offset_i = off_i
                el.end_offset_j = off_j
                el.rigid_zone_factor = factor
        self.main_window.draw_both_canvases()

    def undo(self):
        for eid, (oi, oj, f) in self.old_states.items():
            if eid in self.model.elements:
                el = self.model.elements[eid]
                el.end_offset_i = oi
                el.end_offset_j = oj
                el.rigid_zone_factor = f
        self.main_window.draw_both_canvases()

class CmdReplicate(QUndoCommand):
    """
    Handles Linear Replication (Copy/Move).
    """
    def __init__(self, model, main_window, node_ids, elem_ids, area_elem_ids=None,
                 dx=0.0, dy=0.0, dz=0.0, num=1, delete_original=False):
        super().__init__("Replicate Selection")
        self.model = model
        self.main_window = main_window
        self.node_ids_src = node_ids
        self.elem_ids_src = elem_ids
        self.area_elem_ids_src = list(area_elem_ids or [])
        self.dx = dx
        self.dy = dy
        self.dz = dz
        self.num = num
        self.delete_original = delete_original

        self.created_node_ids = []
        self.created_elem_ids = []
        self.created_area_elem_ids = []

        self.delete_cmd = None
        if self.delete_original:
            self.delete_cmd = CmdDeleteSelection(model, main_window, node_ids, elem_ids,
                                                 self.area_elem_ids_src)

    def redo(self):
                                                                
        self.created_node_ids = []
        self.created_elem_ids = []
        self.created_area_elem_ids = []

        involved_node_ids = set(self.node_ids_src)
        for eid in self.elem_ids_src:
            if eid in self.model.elements:
                el = self.model.elements[eid]
                involved_node_ids.add(el.node_i.id)
                involved_node_ids.add(el.node_j.id)

        if hasattr(self.model, 'area_elements'):
            for aeid in self.area_elem_ids_src:
                if aeid in self.model.area_elements:
                    for node in self.model.area_elements[aeid].nodes:
                        involved_node_ids.add(node.id)

        node_load_map = {}
        elem_load_map = {}
        for load in self.model.loads:
            if hasattr(load, 'node_id'):
                if load.node_id not in node_load_map: node_load_map[load.node_id] = []
                node_load_map[load.node_id].append(load)
            elif hasattr(load, 'element_id'):
                if load.element_id not in elem_load_map: elem_load_map[load.element_id] = []
                elem_load_map[load.element_id].append(load)

        for i in range(1, self.num + 1):
            node_map = {}                             

            for nid in involved_node_ids:
                if nid not in self.model.nodes: continue
                original_node = self.model.nodes[nid]
                
                nx = original_node.x + (self.dx * i)
                ny = original_node.y + (self.dy * i)
                nz = original_node.z + (self.dz * i)
                
                new_node = self.model.get_or_create_node(nx, ny, nz)
                
                if new_node.id not in self.created_node_ids:
                    self.created_node_ids.append(new_node.id)

                node_map[nid] = new_node
                
                if abs(self.dz) < 0.001:
                    new_node.restraints = original_node.restraints[:]
                else:
                    new_node.restraints = [False, False, False, False, False, False]
                
                if abs(self.dz) > 0.001:
                    new_node.diaphragm_name = None 
                else:
                    new_node.diaphragm_name = original_node.diaphragm_name

                if nid in node_load_map:
                    for old_load in node_load_map[nid]:
                        self.model.assign_joint_load(
                            new_node.id, old_load.pattern_name,
                            old_load.fx, old_load.fy, old_load.fz,
                            old_load.mx, old_load.my, old_load.mz,
                            mode="add"
                        )

            for eid in self.elem_ids_src:
                if eid not in self.model.elements: continue
                orig = self.model.elements[eid]
                
                if orig.node_i.id not in node_map or orig.node_j.id not in node_map:
                    continue
                
                n1 = node_map[orig.node_i.id]
                n2 = node_map[orig.node_j.id]

                if self._frame_exists(n1, n2):
                    continue
                
                new_elem = self.model.add_element(n1, n2, orig.section, orig.beta_angle)
                self.created_elem_ids.append(new_elem.id)
                
                new_elem.releases_i = orig.releases_i[:]
                new_elem.releases_j = orig.releases_j[:]
                new_elem.cardinal_point = orig.cardinal_point
                new_elem.joint_offset_i = orig.joint_offset_i.copy()
                new_elem.joint_offset_j = orig.joint_offset_j.copy()
                new_elem.end_offset_i = getattr(orig, 'end_offset_i', 0.0)
                new_elem.end_offset_j = getattr(orig, 'end_offset_j', 0.0)
                new_elem.rigid_zone_factor = getattr(orig, 'rigid_zone_factor', 0.0)

                if eid in elem_load_map:
                    for old_load in elem_load_map[eid]:
                        if hasattr(old_load, 'wx'):              
                             self.model.assign_member_load(
                                new_elem.id, old_load.pattern_name,
                                old_load.wx, old_load.wy, old_load.wz,
                                projected=getattr(old_load, 'projected', False),
                                coord_system=getattr(old_load, 'coord_system', "Global"),
                                mode="add"
                            )
                        elif hasattr(old_load, 'force'):        
                            self.model.assign_member_point_load(
                                new_elem.id, old_load.pattern_name,
                                old_load.force, old_load.dist, old_load.is_relative,
                                old_load.coord_system, old_load.direction,
                                getattr(old_load, 'load_type', "Force"),
                                mode="add"
                            )

            if hasattr(self.model, 'area_elements'):
                for aeid in self.area_elem_ids_src:
                    if aeid not in self.model.area_elements:
                        continue
                    orig_ae = self.model.area_elements[aeid]

                    mapped_nodes = []
                    all_mapped = True
                    for ae_node in orig_ae.nodes:
                        if ae_node.id not in node_map:
                            all_mapped = False
                            break
                        mapped_nodes.append(node_map[ae_node.id])

                    if not all_mapped:
                        continue

                    if self._shell_exists(mapped_nodes):
                        continue

                    new_ae = self.model.add_area_element(mapped_nodes, orig_ae.section)
                    self.created_area_elem_ids.append(new_ae.id)

        if self.delete_original and self.delete_cmd:
            self.delete_cmd.redo()

        self.main_window.draw_both_canvases()

    def undo(self):
                                                        
        if self.delete_original and self.delete_cmd:
            self.delete_cmd.undo()

        for eid in reversed(self.created_elem_ids):
            if eid in self.model.elements:
                self.model.remove_element(eid)

        if hasattr(self.model, 'area_elements'):
            for aeid in reversed(self.created_area_elem_ids):
                if aeid in self.model.area_elements:
                    del self.model.area_elements[aeid]
        
        for nid in reversed(self.created_node_ids):
            if nid not in self.model.nodes: continue
            
            is_connected = False
            for el in self.model.elements.values():
                if el.node_i.id == nid or el.node_j.id == nid:
                    is_connected = True
                    break

            if not is_connected and hasattr(self.model, 'area_elements'):
                for ae in self.model.area_elements.values():
                    if any(n.id == nid for n in ae.nodes):
                        is_connected = True
                        break
            
            if not is_connected:
                del self.model.nodes[nid]

        self.main_window.draw_both_canvases()

    def _frame_exists(self, n1, n2):
        """Return True if a frame element already connects these two nodes (either direction)."""
        pair = {n1.id, n2.id}
        for el in self.model.elements.values():
            if {el.node_i.id, el.node_j.id} == pair:
                return True
        return False

    def _shell_exists(self, nodes):
        """Return True if a shell with the exact same node set already exists."""
        target_ids = {n.id for n in nodes}
        if hasattr(self.model, 'area_elements'):
            for ae in self.model.area_elements.values():
                if {n.id for n in ae.nodes} == target_ids:
                    return True
        return False

class CmdDrawAreaElement(QUndoCommand):
    """
    Command to Draw a Shell/Area Element (and potentially new nodes).
    Mirrors CmdDrawFrame: takes node coordinates, uses get_or_create_node,
    tracks which nodes were newly created, and cleans them up on undo.
    """
    def __init__(self, model, window, node_coords, section, description="Draw Shell"):
        super().__init__(description)
        self.model = model
        self.window = window
        self.node_coords = node_coords                                                           
        self.section = section
        self.added_element_id = None
        self.created_node_ids = []                                                      

    def redo(self):
        self.created_node_ids = []
        existing_ids_before = set(self.model.nodes.keys())                                     

        nodes = []
        for coords in self.node_coords:
            node = self.model.get_or_create_node(*coords)
            if node.id not in existing_ids_before:
                self.created_node_ids.append(node.id)
            nodes.append(node)

        ae = self.model.add_area_element(nodes, self.section)
        self.added_element_id = ae.id
        self.window.draw_both_canvases()

    def undo(self):
                                  
        if self.added_element_id is not None:
            if hasattr(self.model, 'area_elements') and self.added_element_id in self.model.area_elements:
                del self.model.area_elements[self.added_element_id]

        for nid in self.created_node_ids:
            if nid not in self.model.nodes:
                continue

            is_orphan = True

            for el in self.model.elements.values():
                if el.node_i.id == nid or el.node_j.id == nid:
                    is_orphan = False
                    break

            if is_orphan and hasattr(self.model, 'area_elements'):
                for ae in self.model.area_elements.values():
                    if any(n.id == nid for n in ae.nodes):
                        is_orphan = False
                        break

            if is_orphan:
                del self.model.nodes[nid]

        self.window.draw_both_canvases()

class CmdMeshAreaElements(QUndoCommand):
    """
    Command to Mesh Area Elements.
    Uses a snapshot approach to safely undo/redo complex topological changes 
    (new nodes, split frames, deleted original areas).
    """
    def __init__(self, model, window, area_ids, params):
        super().__init__("Mesh Area Elements")
        self.model = model
        self.window = window
        self.area_ids = area_ids
        self.params = params
        
        self.pre_nodes = {k: copy.deepcopy(v) for k, v in model.nodes.items()}
        self.pre_elements = {k: copy.deepcopy(v) for k, v in model.elements.items()}
        self.pre_area_elements = {k: copy.deepcopy(v) for k, v in getattr(model, 'area_elements', {}).items()}
        
        self.post_nodes = None
        self.post_elements = None
        self.post_area_elements = None
        
        self.first_run = True

    def redo(self):
        if self.first_run:
                                                                           
            meshed_count = self.model.mesh_area_elements(
                area_ids=self.area_ids,
                mode=self.params["mode"],
                n=self.params["n"],
                m=self.params["m"],
                max_x=self.params["max_x"],
                max_y=self.params["max_y"],
                divide_frames=self.params["divide_frames"]
            )
            
            self.post_nodes = {k: copy.deepcopy(v) for k, v in self.model.nodes.items()}
            self.post_elements = {k: copy.deepcopy(v) for k, v in self.model.elements.items()}
            self.post_area_elements = {k: copy.deepcopy(v) for k, v in getattr(self.model, 'area_elements', {}).items()}
            self.first_run = False
        else:
                                                                               
            self._restore_snapshot(self.post_nodes, self.post_elements, self.post_area_elements)
            
        self.window.draw_both_canvases()

    def undo(self):
                                                         
        self._restore_snapshot(self.pre_nodes, self.pre_elements, self.pre_area_elements)
        self.window.draw_both_canvases()
        
    def _restore_snapshot(self, nodes, elements, areas):
        self.model.nodes = {k: copy.deepcopy(v) for k, v in nodes.items()}
        self.model.elements = {k: copy.deepcopy(v) for k, v in elements.items()}
        self.model.area_elements = {k: copy.deepcopy(v) for k, v in areas.items()}
        
        for el in self.model.elements.values():
            if el.node_i.id in self.model.nodes: el.node_i = self.model.nodes[el.node_i.id]
            if el.node_j.id in self.model.nodes: el.node_j = self.model.nodes[el.node_j.id]
            if el.section.name in self.model.sections: el.section = self.model.sections[el.section.name]
            
        for ae in self.model.area_elements.values():
            ae.nodes = [self.model.nodes.get(n.id, n) for n in ae.nodes]
            if ae.section.name in self.model.area_sections: 
                ae.section = self.model.area_sections[ae.section.name]
