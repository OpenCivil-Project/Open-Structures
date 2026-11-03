from PyQt6.QtGui import QUndoCommand
import copy
from core.loads import MemberPointLoad, GroundDisplacement, CableDistributedLoad
                                                                         
from core.model import NodalLoad, MemberLoad

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
        
class CmdDrawTendon(QUndoCommand):
    """
    Command to draw a Tendon object between two existing nodes.
    Unlike CmdDrawFrame, this does NOT create nodes — a tendon can only be
    drawn where a continuous, straight, connected chain of frame elements
    already exists (host_element_ids is derived by model.add_tendon()).
    """
    def __init__(self, model, main_window, node_i, node_j, tendon_section,
                 local_axis_angle=0.0, plane="1-2", description="Draw Tendon"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.node_i = node_i
        self.node_j = node_j
        self.tendon_section = tendon_section
        self.local_axis_angle = local_axis_angle
        self.plane = plane

        self.created_tendon_id = None
        self.error_message = None

    def redo(self):
        try:
            t = self.model.add_tendon(self.node_i, self.node_j, self.tendon_section,
                                       local_axis_angle=self.local_axis_angle, plane=self.plane)
            self.created_tendon_id = t.id
            self.error_message = None
        except ValueError as e:
            self.created_tendon_id = None
            self.error_message = str(e)

        self._refresh_view()

    def undo(self):
        if self.created_tendon_id:
            self.model.remove_tendon(self.created_tendon_id)
        self._refresh_view()

    def get_created_tendon(self):
        """Convenience for the caller (main.py) to grab the new object right
        after pushing this command, e.g. to open the geometry dialog on it."""
        if self.created_tendon_id:
            return self.model.tendons.get(self.created_tendon_id)
        return None

    def _refresh_view(self):
        self.main_window.draw_both_canvases()

class CmdDeleteSelection(QUndoCommand):
    """
    Command to Delete Frames, Shells, Links, Tendons, Cables and/or Joints.
    Includes DOUBLE SAFETY CHECK to protect nodes still in use.
    """
    def __init__(self, model, main_window, node_ids, elem_ids, area_elem_ids=None, link_ids=None, tendon_ids=None, cable_ids=None):
        super().__init__("Delete Selection")
        self.model = model
        self.main_window = main_window
        
        ids_elements_to_delete = set(elem_ids)
        ids_area_elements_to_delete = set(area_elem_ids or [])
        ids_links_to_delete = set(link_ids or [])
        ids_tendons_to_delete = set(tendon_ids or [])
        ids_cables_to_delete = set(cable_ids or [])

        if hasattr(model, 'tendons'):
            for tid, t in model.tendons.items():
                host_ids = getattr(t, 'host_element_ids', [])
                if any(h in ids_elements_to_delete for h in host_ids):
                    ids_tendons_to_delete.add(tid)

        if hasattr(model, 'links') or hasattr(model, 'cables'):
            changed = True
            while changed:
                changed = False
                touched_nodes = set()

                for eid in ids_elements_to_delete:
                    if eid in model.elements:
                        el = model.elements[eid]
                        touched_nodes.add(el.node_i.id)
                        touched_nodes.add(el.node_j.id)

                if hasattr(model, 'area_elements'):
                    for aeid in ids_area_elements_to_delete:
                        if aeid in model.area_elements:
                            for n in model.area_elements[aeid].nodes:
                                touched_nodes.add(n.id)

                for lid in ids_links_to_delete:
                    if lid in getattr(model, 'links', {}):
                        touched_nodes.update(model.links[lid]['nodes'])

                for tid in ids_tendons_to_delete:
                    if tid in getattr(model, 'tendons', {}):
                        touched_nodes.add(model.tendons[tid].node_i.id)
                        touched_nodes.add(model.tendons[tid].node_j.id)

                for cid in ids_cables_to_delete:
                    if cid in getattr(model, 'cables', {}):
                        touched_nodes.add(model.cables[cid].node_i.id)
                        touched_nodes.add(model.cables[cid].node_j.id)

                for nid in touched_nodes:
                    if nid not in model.nodes:
                        continue
                    if any(model.nodes[nid].restraints):
                        continue                                            

                    still_has_element = any(
                        (el.node_i.id == nid or el.node_j.id == nid)
                        for eid2, el in model.elements.items()
                        if eid2 not in ids_elements_to_delete
                    )
                    still_has_cable = False
                    if hasattr(model, 'cables'):
                        still_has_cable = any(
                            (c.node_i.id == nid or c.node_j.id == nid)
                            for cid2, c in model.cables.items()
                            if cid2 not in ids_cables_to_delete
                        )

                    if still_has_element or still_has_cable:
                        continue

                    still_has_area = False
                    if hasattr(model, 'area_elements'):
                        still_has_area = any(
                            any(n.id == nid for n in ae.nodes)
                            for aeid2, ae in model.area_elements.items()
                            if aeid2 not in ids_area_elements_to_delete
                        )
                    if still_has_area:
                        continue

                    for lid, link in getattr(model, 'links', {}).items():
                        if lid in ids_links_to_delete:
                            continue
                        if nid in link['nodes']:
                            ids_links_to_delete.add(lid)
                            changed = True
        
        nodes_to_actually_delete = set()
        
        for nid in node_ids:
            if self._is_truly_orphaned(model, nid, ids_elements_to_delete, ids_area_elements_to_delete, ids_links_to_delete, ids_cables_to_delete):
                nodes_to_actually_delete.add(nid)
        
        safe_nodes_to_delete = set()
        for eid in ids_elements_to_delete:
            if eid in model.elements:
                el = model.elements[eid]
                if self._will_become_orphan(model, el.node_i.id, ids_elements_to_delete, ids_area_elements_to_delete, ids_links_to_delete, ids_cables_to_delete):
                    safe_nodes_to_delete.add(el.node_i.id)
                if self._will_become_orphan(model, el.node_j.id, ids_elements_to_delete, ids_area_elements_to_delete, ids_links_to_delete, ids_cables_to_delete):
                    safe_nodes_to_delete.add(el.node_j.id)

        if hasattr(model, 'area_elements'):
            for aeid in ids_area_elements_to_delete:
                if aeid in model.area_elements:
                    ae = model.area_elements[aeid]
                    for node in ae.nodes:
                        if self._will_become_orphan(model, node.id, ids_elements_to_delete, ids_area_elements_to_delete, ids_links_to_delete, ids_cables_to_delete):
                            safe_nodes_to_delete.add(node.id)

        if hasattr(model, 'links'):
            for lid in ids_links_to_delete:
                if lid in model.links:
                    link = model.links[lid]
                    for nid in link['nodes']:
                        if self._will_become_orphan(model, nid, ids_elements_to_delete, ids_area_elements_to_delete, ids_links_to_delete, ids_cables_to_delete):
                            safe_nodes_to_delete.add(nid)
                            
        if hasattr(model, 'cables'):
            for cid in ids_cables_to_delete:
                if cid in model.cables:
                    c = model.cables[cid]
                    if self._will_become_orphan(model, c.node_i.id, ids_elements_to_delete, ids_area_elements_to_delete, ids_links_to_delete, ids_cables_to_delete):
                        safe_nodes_to_delete.add(c.node_i.id)
                    if self._will_become_orphan(model, c.node_j.id, ids_elements_to_delete, ids_area_elements_to_delete, ids_links_to_delete, ids_cables_to_delete):
                        safe_nodes_to_delete.add(c.node_j.id)
        
        self.node_ids_to_del = list(nodes_to_actually_delete | safe_nodes_to_delete)
        self.elem_ids_to_del = list(ids_elements_to_delete)
        self.area_elem_ids_to_del = list(ids_area_elements_to_delete)
        self.link_ids_to_del = list(ids_links_to_delete)
        self.tendon_ids_to_del = list(ids_tendons_to_delete)
        self.cable_ids_to_del = list(ids_cables_to_delete)

        self.saved_nodes = {}
        self.saved_elems = {}
        self.saved_area_elems = {}
        self.saved_links = {}
        self.saved_tendons = {}
        self.saved_cables = {}
        self.saved_loads = []

        for eid in self.elem_ids_to_del:
            if eid in model.elements:
                self.saved_elems[eid] = copy.deepcopy(model.elements[eid])

        if hasattr(model, 'area_elements'):
            for aeid in self.area_elem_ids_to_del:
                if aeid in model.area_elements:
                    self.saved_area_elems[aeid] = copy.deepcopy(model.area_elements[aeid])
                    
        if hasattr(model, 'links'):
            for lid in self.link_ids_to_del:
                if lid in model.links:
                    self.saved_links[lid] = copy.deepcopy(model.links[lid])
                    
        if hasattr(model, 'tendons'):
            for tid in self.tendon_ids_to_del:
                if tid in model.tendons:
                    self.saved_tendons[tid] = copy.deepcopy(model.tendons[tid])
                    
        if hasattr(model, 'cables'):
            for cid in self.cable_ids_to_del:
                if cid in model.cables:
                    self.saved_cables[cid] = copy.deepcopy(model.cables[cid])
        
        for nid in self.node_ids_to_del:
            if nid in model.nodes:
                self.saved_nodes[nid] = copy.deepcopy(model.nodes[nid])

        for load in model.loads:
            should_save = False
            if hasattr(load, 'element_id') and load.element_id in self.elem_ids_to_del:
                should_save = True
            elif hasattr(load, 'node_id') and load.node_id in self.node_ids_to_del:
                should_save = True
            elif hasattr(load, 'cable_id') and load.cable_id in self.cable_ids_to_del:                         
                should_save = True
            elif hasattr(load, 'area_id') and load.area_id in self.area_elem_ids_to_del:
                should_save = True
                
            if should_save:
                self.saved_loads.append(copy.deepcopy(load))

    def _is_truly_orphaned(self, model, node_id, deleted_elem_ids, deleted_area_ids, deleted_link_ids, deleted_cable_ids):
        for el in model.elements.values():
            if el.id not in deleted_elem_ids:
                if el.node_i.id == node_id or el.node_j.id == node_id:
                    return False 
        
        if hasattr(model, 'area_elements'):
            for ae in model.area_elements.values():
                if ae.id not in deleted_area_ids:
                    if any(n.id == node_id for n in ae.nodes):
                        return False 
                        
        if hasattr(model, 'links'):
            for link in model.links.values():
                if link['id'] not in deleted_link_ids:
                    if node_id in link['nodes']:
                        return False
                        
        if hasattr(model, 'cables'):
            for c in model.cables.values():
                if c.id not in deleted_cable_ids:
                    if c.node_i.id == node_id or c.node_j.id == node_id:
                        return False
        
        return True
    
    def _will_become_orphan(self, model, node_id, deleted_element_ids, deleted_area_ids, deleted_link_ids, deleted_cable_ids):
        for el in model.elements.values():
            if el.id not in deleted_element_ids:
                if el.node_i.id == node_id or el.node_j.id == node_id:
                    return False

        if hasattr(model, 'area_elements'):
            for ae in model.area_elements.values():
                if ae.id not in deleted_area_ids:
                    if any(n.id == node_id for n in ae.nodes):
                        return False
                        
        if hasattr(model, 'links'):
            for link in model.links.values():
                if link['id'] not in deleted_link_ids:
                    if node_id in link['nodes']:
                        return False

        if hasattr(model, 'cables'):
            for c in model.cables.values():
                if c.id not in deleted_cable_ids:
                    if c.node_i.id == node_id or c.node_j.id == node_id:
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
                    
        if hasattr(self.model, 'links'):
            for lid in self.link_ids_to_del:
                if lid in self.model.links:
                    del self.model.links[lid]

        if hasattr(self.model, 'tendons'):
            for tid in self.tendon_ids_to_del:
                if tid in self.model.tendons:
                    del self.model.tendons[tid]
                    
        if hasattr(self.model, 'cables'):
            for cid in self.cable_ids_to_del:
                if cid in self.model.cables:
                    del self.model.cables[cid]
        
        for nid in self.node_ids_to_del:
            if nid in self.model.nodes:
                del self.model.nodes[nid]

        self.model.loads = [
            load for load in self.model.loads
            if not (hasattr(load, 'element_id') and load.element_id in self.elem_ids_to_del)
            and not (hasattr(load, 'node_id') and load.node_id in self.node_ids_to_del)
            and not (hasattr(load, 'cable_id') and load.cable_id in self.cable_ids_to_del)                         
            and not (hasattr(load, 'area_id') and load.area_id in self.area_elem_ids_to_del)
        ]

        self.main_window.selected_ids = []
        self.main_window.selected_node_ids = []
        if hasattr(self.main_window, 'selected_area_ids'):
            self.main_window.selected_area_ids = []
        if hasattr(self.main_window, 'selected_link_ids'):
            self.main_window.selected_link_ids = []
        if hasattr(self.main_window, 'selected_tendon_ids'):                    
            self.main_window.selected_tendon_ids = []
        if hasattr(self.main_window, 'selected_cable_ids'):                    
            self.main_window.selected_cable_ids = []
            
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
                ae_obj.nodes = [self.model.nodes.get(n.id, n) for n in ae_obj.nodes]
                if hasattr(ae_obj, 'section') and ae_obj.section is not None:
                    sec_name = ae_obj.section.name
                    if hasattr(self.model, 'area_sections') and sec_name in self.model.area_sections:
                        ae_obj.section = self.model.area_sections[sec_name]
                    elif sec_name in self.model.sections:
                        ae_obj.section = self.model.sections[sec_name]
                self.model.area_elements[aeid] = ae_obj
                if hasattr(self.model, '_area_elem_counter'):
                    self.model._area_elem_counter = max(self.model._area_elem_counter, aeid + 1)
                    
        if hasattr(self.model, 'links'):
            for lid, link_obj in self.saved_links.items():
                self.model.links[lid] = link_obj
                self.model._link_counter = max(getattr(self.model, '_link_counter', 1), lid + 1)

        if hasattr(self.model, 'tendons'):
            for tid, t_obj in self.saved_tendons.items():
                if t_obj.node_i.id in self.model.nodes:
                    t_obj.node_i = self.model.nodes[t_obj.node_i.id]
                if t_obj.node_j.id in self.model.nodes:
                    t_obj.node_j = self.model.nodes[t_obj.node_j.id]
                self.model.tendons[tid] = t_obj
                self.model._tendon_counter = max(getattr(self.model, '_tendon_counter', 1), tid + 1)

        if hasattr(self.model, 'cables'):
            for cid, c_obj in self.saved_cables.items():
                if c_obj.node_i.id in self.model.nodes:
                    c_obj.node_i = self.model.nodes[c_obj.node_i.id]
                if c_obj.node_j.id in self.model.nodes:
                    c_obj.node_j = self.model.nodes[c_obj.node_j.id]
                self.model.cables[cid] = c_obj
                self.model._cable_counter = max(getattr(self.model, '_cable_counter', 1), cid + 1)

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
        self.main_window._supports_only_refresh = True
        for nid in self.node_ids:
            if nid in self.model.nodes:
                self.model.nodes[nid].restraints = self.new_restraints[:]
                                                                                                                     
    def undo(self):
        self.main_window._supports_only_refresh = True
        for nid, old_res in self.old_states.items():
            if nid in self.model.nodes:
                self.model.nodes[nid].restraints = old_res[:]
                                                                                                                     
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
        self.elem_ids = list(elem_ids)
        self._elem_id_set = set(self.elem_ids)
        self.pattern_name = pattern_name
        self.mode = mode
        
        self.params = (wx, wy, wz, projected, coord_sys, 
                       distances, magnitudes, is_relative, 
                       load_direction, load_type)
        
        self.old_loads = []
        for load in model.loads:
            if hasattr(load, 'element_id'):
                if load.element_id in self._elem_id_set and load.pattern_name == pattern_name:
                    self.old_loads.append(copy.deepcopy(load))

    def redo(self):
                                             
        (wx, wy, wz, proj, cs, dists, mags, is_rel, l_dir, l_type) = self.params
        assign_many = getattr(self.model, 'assign_member_loads', None)
        if callable(assign_many):
            assign_many(self.elem_ids, self.pattern_name, wx, wy, wz, proj, cs, self.mode,
                        distances=dists, magnitudes=mags, is_relative=is_rel,
                        load_direction=l_dir, load_type=l_type)
        else:
            for eid in self.elem_ids:
                self.model.assign_member_load(
                    eid, self.pattern_name, wx, wy, wz,
                    proj, cs, self.mode,
                    distances=dists, magnitudes=mags, is_relative=is_rel,
                    load_direction=l_dir, load_type=l_type)
        refresh = (getattr(self.main_window, 'request_load_refresh', None) or
                   getattr(self.main_window, 'refresh_load_display', None))
        if callable(refresh):
            refresh()
        else:
            self.main_window.draw_both_canvases()

    def undo(self):
                                                                       
        self.model.loads[:] = [load for load in self.model.loads
            if not (getattr(load, 'element_id', None) in self._elem_id_set
                    and getattr(load, 'pattern_name', None) == self.pattern_name)]
        
        for old_load in self.old_loads:
            self.model.loads.append(copy.deepcopy(old_load))
        refresh = (getattr(self.main_window, 'request_load_refresh', None) or
                   getattr(self.main_window, 'refresh_load_display', None))
        if callable(refresh):
            refresh()
        else:
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

class CmdAssignFrameHinge(QUndoCommand):
    """
    Assigns a (user-defined) hinge property to one or more frame
    elements at a relative distance. Data-only - not wired to the
    solver or the OpenSees converter.
    """
    def __init__(self, model, main_window, elem_ids, hinge_name, rel_dist, mode="replace"):
        super().__init__("Assign Frame Hinge")
        self.model = model
        self.main_window = main_window
        self.elem_ids = elem_ids
        self.hinge_name = hinge_name
        self.rel_dist = rel_dist
        self.mode = mode

        self.old_hinges = [
            copy.deepcopy(h) for h in model.frame_hinges.values()
            if h.element_id in elem_ids
        ]

    def redo(self):
        for eid in self.elem_ids:
            self.model.assign_frame_hinge(eid, self.hinge_name, self.rel_dist, self.mode)
        self.main_window.draw_both_canvases()

    def undo(self):
        for hid in [hid for hid, h in self.model.frame_hinges.items()
                    if h.element_id in self.elem_ids]:
            del self.model.frame_hinges[hid]

        for old_h in self.old_hinges:
            self.model.frame_hinges[old_h.id] = copy.deepcopy(old_h)
            self.model._hinge_assign_counter = max(
                self.model._hinge_assign_counter, old_h.id + 1
            )

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
                 dx=0.0, dy=0.0, dz=0.0, num=1, delete_original=False, link_ids=None):
        super().__init__("Replicate Selection")
        self.model = model
        self.main_window = main_window
        self.node_ids_src = node_ids
        self.elem_ids_src = elem_ids
        self.area_elem_ids_src = list(area_elem_ids or [])
        self.link_ids_src = list(link_ids or [])
        self.dx = dx
        self.dy = dy
        self.dz = dz
        self.num = num
        self.delete_original = delete_original

        self.created_node_ids = []
        self.created_elem_ids = []
        self.created_area_elem_ids = []
        self.created_link_ids = []
        self.skipped_node_ids = []
        self.skipped_link_ids = []

        self.delete_cmd = None
        if self.delete_original:
            self.delete_cmd = CmdDeleteSelection(model, main_window, node_ids, elem_ids,
                                                 self.area_elem_ids_src, self.link_ids_src)
            
    def redo(self):
                                                                
        self.created_node_ids = []
        self.created_elem_ids = []
        self.created_area_elem_ids = []
        self.created_link_ids = []
        self.skipped_node_ids = []
        self.skipped_link_ids = []

        nodes_before_ids = set(self.model.nodes.keys())

        involved_node_ids = set(self.node_ids_src)
        carried_node_ids = set()
        for eid in self.elem_ids_src:
            if eid in self.model.elements:
                el = self.model.elements[eid]
                involved_node_ids.add(el.node_i.id)
                involved_node_ids.add(el.node_j.id)
                carried_node_ids.add(el.node_i.id)
                carried_node_ids.add(el.node_j.id)

        if hasattr(self.model, 'area_elements'):
            for aeid in self.area_elem_ids_src:
                if aeid in self.model.area_elements:
                    for node in self.model.area_elements[aeid].nodes:
                        involved_node_ids.add(node.id)
                        carried_node_ids.add(node.id)

        if hasattr(self.model, 'links'):
            for lid in self.link_ids_src:
                if lid in self.model.links:
                    for nid in self.model.links[lid]['nodes']:
                        involved_node_ids.add(nid)
                        carried_node_ids.add(nid)

        gated_node_ids = involved_node_ids - carried_node_ids
        pre_existing_connected_coords = []
        if gated_node_ids:
            for nid, node in self.model.nodes.items():
                if self._is_node_connected(nid):
                    pre_existing_connected_coords.append((node.x, node.y, node.z))

        explicit_node_ids = set(self.node_ids_src)

        node_load_map = {}
        elem_load_map = {}
        area_load_map = {}
        for load in self.model.loads:
            if hasattr(load, 'node_id'):
                if load.node_id not in node_load_map: node_load_map[load.node_id] = []
                node_load_map[load.node_id].append(load)
            elif hasattr(load, 'element_id'):
                if load.element_id not in elem_load_map: elem_load_map[load.element_id] = []
                elem_load_map[load.element_id].append(load)
            elif hasattr(load, 'area_id'):
                if load.area_id not in area_load_map: area_load_map[load.area_id] = []
                area_load_map[load.area_id].append(load)

        for i in range(1, self.num + 1):
            node_map = {}                             

            for nid in involved_node_ids:
                if nid not in self.model.nodes: continue
                original_node = self.model.nodes[nid]
                
                nx = original_node.x + (self.dx * i)
                ny = original_node.y + (self.dy * i)
                nz = original_node.z + (self.dz * i)

                if nid in gated_node_ids:
                    if not self._matches_existing_connected(nx, ny, nz, pre_existing_connected_coords):
                        self.skipped_node_ids.append(nid)
                        continue
                    new_node = self.model.get_or_create_node(nx, ny, nz)
                    node_map[nid] = new_node
                    continue
                
                new_node = self.model.get_or_create_node(nx, ny, nz)
                is_new = new_node.id not in nodes_before_ids

                if is_new and new_node.id not in self.created_node_ids:
                    self.created_node_ids.append(new_node.id)

                node_map[nid] = new_node

                if not is_new or nid not in explicit_node_ids:
                    continue

                new_node.restraints = original_node.restraints[:]
                
                if abs(self.dz) > 0.001:
                    new_node.diaphragm_name = None 
                else:
                    new_node.diaphragm_name = original_node.diaphragm_name

                orig_spring = getattr(original_node, 'spring_matrix', None)
                new_node.spring_matrix = orig_spring.copy() if orig_spring is not None else None

                if nid in node_load_map:
                    for old_load in node_load_map[nid]:
                        if isinstance(old_load, GroundDisplacement):
                            self.model.assign_ground_displacement(
                                new_node.id, old_load.pattern_name,
                                old_load.ux, old_load.uy, old_load.uz,
                                old_load.rx, old_load.ry, old_load.rz,
                                mode="add"
                            )
                        elif hasattr(old_load, 'fx'):
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
                                                                                
                self.model._copy_frame_properties(new_elem, orig)

                if eid in elem_load_map:
                    for old_load in elem_load_map[eid]:
                        if hasattr(old_load, 'wx'):
                            self.model.assign_member_load(
                                new_elem.id, old_load.pattern_name,
                                old_load.wx, old_load.wy, old_load.wz,
                                projected=getattr(old_load, 'projected', False),
                                coord_system=getattr(old_load, 'coord_system', "Global"),
                                mode="add",
                                distances=list(old_load.distances),
                                magnitudes=list(old_load.magnitudes),
                                is_relative=old_load.is_relative,
                                load_direction=old_load.load_direction,
                                load_type=old_load.load_type
                            )
                        elif hasattr(old_load, 'force'):        
                            self.model.assign_member_point_load(
                                new_elem.id, old_load.pattern_name,
                                old_load.force, old_load.dist, old_load.is_relative,
                                old_load.coord_system, old_load.direction,
                                getattr(old_load, 'load_type', "Force"),
                                mode="add"
                            )

                for h in list(self.model.frame_hinges.values()):
                    if h.element_id == eid:
                        self.model.assign_frame_hinge(
                            new_elem.id, h.hinge_name, h.rel_dist, mode="add")

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
                    new_ae.insertion_offset = getattr(orig_ae, 'insertion_offset', 0.0)
                    self.created_area_elem_ids.append(new_ae.id)

                    if aeid in area_load_map:
                        for old_load in area_load_map[aeid]:
                            if hasattr(old_load, 'gx'):
                                self.model.assign_area_gravity_load(
                                    new_ae.id, old_load.pattern_name,
                                    old_load.gx, old_load.gy, old_load.gz,
                                    coord_system=getattr(old_load, 'coord_system', "GLOBAL"),
                                    mode="add"
                                )
                            elif hasattr(old_load, 'uniform_load'):
                                self.model.assign_area_uniform_load(
                                    new_ae.id, old_load.pattern_name,
                                    old_load.uniform_load,
                                    load_direction=getattr(old_load, 'load_direction', "Gravity"),
                                    coord_system=getattr(old_load, 'coord_system', "GLOBAL"),
                                    mode="add"
                                )

            if hasattr(self.model, 'links'):
                for lid in self.link_ids_src:
                    if lid not in self.model.links:
                        continue
                    orig_link = self.model.links[lid]

                    mapped_ids = []
                    all_mapped = True
                    for nid in orig_link['nodes']:
                        if nid not in node_map:
                            all_mapped = False
                            break
                        mapped_ids.append(node_map[nid].id)

                    if not all_mapped:
                        self.skipped_link_ids.append(lid)
                        continue

                    if self._link_exists(mapped_ids, orig_link.get('type')):
                        continue

                    new_link_id = getattr(self.model, '_link_counter', 1)
                    self.model._link_counter = new_link_id + 1

                    self.model.links[new_link_id] = {
                        "id": new_link_id,
                        "prop_name": orig_link['prop_name'],
                        "nodes": mapped_ids,
                        "beta": orig_link.get('beta', 0.0),
                        "type": orig_link.get('type', 'link_2j')
                    }
                    self.created_link_ids.append(new_link_id)

        if self.delete_original and self.delete_cmd:
            self.delete_cmd.redo()

        self.main_window.draw_both_canvases()

    def undo(self):
                                                        
        if self.delete_original and self.delete_cmd:
            self.delete_cmd.undo()

        if hasattr(self.model, 'links'):
            for lid in reversed(self.created_link_ids):
                if lid in self.model.links:
                    del self.model.links[lid]

        created_elems = set(self.created_elem_ids)
        for hid in [hid for hid, h in self.model.frame_hinges.items()
                    if h.element_id in created_elems]:
            del self.model.frame_hinges[hid]

        for eid in reversed(self.created_elem_ids):
            if eid in self.model.elements:
                self.model.remove_element(eid)

        if hasattr(self.model, 'area_elements'):
            for aeid in reversed(self.created_area_elem_ids):
                if aeid in self.model.area_elements:
                    del self.model.area_elements[aeid]

        self.model.loads = [
            l for l in self.model.loads
            if not (hasattr(l, 'element_id') and l.element_id in self.created_elem_ids)
            and not (hasattr(l, 'area_id') and l.area_id in self.created_area_elem_ids)
        ]
        
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

            if not is_connected and hasattr(self.model, 'links'):
                for link in self.model.links.values():
                    if nid in link['nodes']:
                        is_connected = True
                        break
            
            if not is_connected:
                del self.model.nodes[nid]
                self.model.loads = [
                    l for l in self.model.loads
                    if not (hasattr(l, 'node_id') and l.node_id == nid)
                ]

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

    def _link_exists(self, node_ids, link_type):
        """Return True if a link of the same type already connects this exact node set."""
        target_ids = set(node_ids)
        if hasattr(self.model, 'links'):
            for link in self.model.links.values():
                if set(link['nodes']) == target_ids and link.get('type') == link_type:
                    return True
        return False

    def _is_node_connected(self, node_id):
        """Read-only check: is this node attached to any element, area, slab, or link right now."""
        m = self.model
        for el in m.elements.values():
            if el.node_i.id == node_id or el.node_j.id == node_id:
                return True
        if hasattr(m, 'area_elements'):
            for ae in m.area_elements.values():
                if any(n.id == node_id for n in ae.nodes):
                    return True
        if hasattr(m, 'slabs'):
            for slab in m.slabs.values():
                if any(n.id == node_id for n in slab.nodes):
                    return True
        if hasattr(m, 'links'):
            for link in m.links.values():
                if node_id in link['nodes']:
                    return True
        return False

    def _matches_existing_connected(self, x, y, z, snapshot_coords, tol=0.005):
        """Is (x, y, z) within tolerance of a node that was already connected before this op?"""
        for (sx, sy, sz) in snapshot_coords:
            dist = ((sx - x) ** 2 + (sy - y) ** 2 + (sz - z) ** 2) ** 0.5
            if dist < tol:
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
        self.pre_loads = copy.deepcopy(model.loads)
        self.pre_hinges = copy.deepcopy(getattr(model, 'frame_hinges', {}))
        
        self.post_nodes = None
        self.post_elements = None
        self.post_area_elements = None
        self.post_loads = None
        self.post_hinges = None
        
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
            self.post_loads = copy.deepcopy(self.model.loads)
            self.post_hinges = copy.deepcopy(getattr(self.model, 'frame_hinges', {}))
            self.first_run = False
        else:
                                                                               
            self._restore_snapshot(self.post_nodes, self.post_elements, self.post_area_elements, self.post_loads, self.post_hinges)
            
        self.window.draw_both_canvases()

    def undo(self):
                                                         
        self._restore_snapshot(self.pre_nodes, self.pre_elements, self.pre_area_elements, self.pre_loads, self.pre_hinges)
        self.window.draw_both_canvases()
        
    def _restore_snapshot(self, nodes, elements, areas, loads=None, hinges=None):
        self.model.nodes = {k: copy.deepcopy(v) for k, v in nodes.items()}
        self.model.elements = {k: copy.deepcopy(v) for k, v in elements.items()}
        self.model.area_elements = {k: copy.deepcopy(v) for k, v in areas.items()}
        if loads is not None:
            self.model.loads = copy.deepcopy(loads)
        if hinges is not None:
            self.model.frame_hinges = copy.deepcopy(hinges)
        
        for el in self.model.elements.values():
            if el.node_i.id in self.model.nodes: el.node_i = self.model.nodes[el.node_i.id]
            if el.node_j.id in self.model.nodes: el.node_j = self.model.nodes[el.node_j.id]
            if el.section.name in self.model.sections: el.section = self.model.sections[el.section.name]
            
        for ae in self.model.area_elements.values():
            ae.nodes = [self.model.nodes.get(n.id, n) for n in ae.nodes]
            if ae.section.name in self.model.area_sections: 
                ae.section = self.model.area_sections[ae.section.name]

class CmdJoinAreaElements(CmdMeshAreaElements):
    """
    Joins real (divided) shells back into one shell. Snapshot based, like CmdMeshAreaElements.
    Call prepare() first: it performs the join and raises ValueError/KeyError (model unchanged)
    if the selection cannot be joined. Only after it succeeds push the command on the stack.
    """
    def __init__(self, model, window, area_ids, rejoin_frames=True):
        super().__init__(model, window, list(area_ids), {})
        self.setText("Join Area Elements")
        self.rejoin_frames = rejoin_frames
        self.result = None

    def prepare(self):
        self.result = self.model.join_area_elements(self.area_ids, rejoin_frames=self.rejoin_frames)
        self.post_nodes = {k: copy.deepcopy(v) for k, v in self.model.nodes.items()}
        self.post_elements = {k: copy.deepcopy(v) for k, v in self.model.elements.items()}
        self.post_area_elements = {k: copy.deepcopy(v) for k, v in getattr(self.model, 'area_elements', {}).items()}
        self.post_loads = copy.deepcopy(self.model.loads)
        self.post_hinges = copy.deepcopy(getattr(self.model, 'frame_hinges', {}))
        self.first_run = False
        return self.result

    def redo(self):
        if self.first_run:
            self.prepare()
        super().redo()

class CmdAssignJointDisplacement(QUndoCommand):
    """
    Handles Add/Replace/Delete of Nodal Ground Displacements.
    Snapshot strategy: Save ALL ground displacements for the target nodes/pattern, then restore.
    """
    def __init__(self, model, main_window, node_ids, pattern_name, 
                 ux, uy, uz, rx, ry, rz, mode="replace"):
        super().__init__("Assign Joint Displacement")
        self.model = model
        self.main_window = main_window
        self.node_ids = node_ids
        self.pattern_name = pattern_name
        self.values = (ux, uy, uz, rx, ry, rz)
        self.mode = mode
        
        self.old_disps = []
                                                                                        
        for load in model.loads:
            if isinstance(load, GroundDisplacement):
                if load.node_id in node_ids and load.pattern_name == pattern_name:
                    self.old_disps.append(copy.deepcopy(load))

    def redo(self):
        ux, uy, uz, rx, ry, rz = self.values
        for nid in self.node_ids:
                                                        
            self.model.assign_ground_displacement(
                nid, self.pattern_name, ux, uy, uz, rx, ry, rz, self.mode
            )
        self.main_window.draw_both_canvases()

    def undo(self):
                                                                                        
        for i in range(len(self.model.loads) - 1, -1, -1):
            load = self.model.loads[i]
            if isinstance(load, GroundDisplacement):
                if load.node_id in self.node_ids and load.pattern_name == self.pattern_name:
                    del self.model.loads[i]
        
        for old_disp in self.old_disps:
            self.model.loads.append(copy.deepcopy(old_disp))
            
        self.main_window.draw_both_canvases()

class CmdAssignJointSpring(QUndoCommand):
    """
    Command to Assign, Add, or Delete 6x6 Joint Springs.
    """
    def __init__(self, model, main_window, node_ids, matrix_si, mode, description="Assign Joint Springs"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.node_ids = node_ids
        self.matrix = matrix_si
        self.mode = mode
        
        self.previous_states = {}

    def redo(self):
        self.main_window._supports_only_refresh = True
        for nid in self.node_ids:
            node = self.model.nodes[nid]
            
            if getattr(node, 'spring_matrix', None) is not None:
                self.previous_states[nid] = node.spring_matrix.copy()
            else:
                self.previous_states[nid] = None

            if self.mode == "replace":
                node.spring_matrix = self.matrix.copy()
            elif self.mode == "add":
                if getattr(node, 'spring_matrix', None) is not None:
                    node.spring_matrix += self.matrix
                else:
                    node.spring_matrix = self.matrix.copy()
            elif self.mode == "delete":
                node.spring_matrix = None

    def undo(self):
        self.main_window._supports_only_refresh = True
        for nid in self.node_ids:
            node = self.model.nodes[nid]
                                              
            node.spring_matrix = self.previous_states.get(nid)

class CmdDrawLink2J(QUndoCommand):
    def __init__(self, model, main_window, p1, p2, prop_name):
        super().__init__(f"Draw 2-Joint Link ({prop_name})")
        self.model = model
        self.main_window = main_window
        self.p1 = p1
        self.p2 = p2
        self.prop_name = prop_name
        self.link_id = None
        self.n1_id = None
        self.n2_id = None

    def redo(self):
        n1 = self.model.get_or_create_node(*self.p1)
        n2 = self.model.get_or_create_node(*self.p2)
        self.n1_id = n1.id
        self.n2_id = n2.id
        
        if self.link_id is None:
            self.link_id = getattr(self.model, '_link_counter', 1)
            self.model._link_counter = self.link_id + 1
            
        self.model.links[self.link_id] = {
            "id": self.link_id,
            "prop_name": self.prop_name,
            "nodes": [self.n1_id, self.n2_id],
            "beta": 0.0,
            "type": "link_2j"
        }
        self.main_window.refresh_canvas()

    def undo(self):
        if self.link_id in self.model.links:
            del self.model.links[self.link_id]
        self.model._cleanup_orphan_node(self.n1_id)
        self.model._cleanup_orphan_node(self.n2_id)
        self.main_window.refresh_canvas()

class CmdDrawLink1J(QUndoCommand):
    def __init__(self, model, main_window, p1, prop_name):
        super().__init__(f"Draw 1-Joint Link ({prop_name})")
        self.model = model
        self.main_window = main_window
        self.p1 = p1
        self.prop_name = prop_name
        self.link_id = None
        self.n1_id = None

    def redo(self):
        n1 = self.model.get_or_create_node(*self.p1)
        self.n1_id = n1.id
        
        if self.link_id is None:
            self.link_id = getattr(self.model, '_link_counter', 1)
            self.model._link_counter = self.link_id + 1
            
        self.model.links[self.link_id] = {
            "id": self.link_id,
            "prop_name": self.prop_name,
            "nodes": [self.n1_id],
            "type": "link_1j"
        }
        self.main_window.refresh_canvas()

    def undo(self):
        if self.link_id in self.model.links:
            del self.model.links[self.link_id]
        self.model._cleanup_orphan_node(self.n1_id)
        self.main_window.refresh_canvas()

class CmdAssignTendonLoad(QUndoCommand):
    """
    Assigns tendon loads to a selection of tendons, handling Replace/Delete logic.
    """
    def __init__(self, model, main_window, tendon_ids, load_data, description="Assign Tendon Loads"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.tendon_ids = tendon_ids
        self.load_data = load_data
        
        self.previous_loads = {}
        if hasattr(self.model, 'tendons'):
            import copy
            for tid in self.tendon_ids:
                if tid in self.model.tendons:
                    self.previous_loads[tid] = copy.deepcopy(getattr(self.model.tendons[tid], "loads", []))

    def redo(self):
        import copy
        for tid in self.tendon_ids:
            if tid not in self.model.tendons: continue
            tendon = self.model.tendons[tid]
            current_loads = getattr(tendon, "loads", [])
            
            current_loads = [ld for ld in current_loads if ld["pattern"] != self.load_data["pattern"]]
            
            if self.load_data["action"] == "Replace":
                current_loads.append(copy.deepcopy(self.load_data))
                
            tendon.loads = current_loads
            
        self.main_window.draw_both_canvases()

    def undo(self):
        import copy
        for tid, old_loads in self.previous_loads.items():
            if tid in self.model.tendons:
                self.model.tendons[tid].loads = copy.deepcopy(old_loads)
                
        self.main_window.draw_both_canvases()

class CmdDrawCable(QUndoCommand):
    """Command to draw a Cable object between two existing nodes."""
    def __init__(self, model, main_window, node_i, node_j, cable_section, description="Draw Cable"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.node_i = node_i
        self.node_j = node_j
        self.cable_section = cable_section
        self.created_cable_id = None
        self.error_message = None

    def redo(self):
        if not hasattr(self.model, 'cables'):
            self.model.cables = {}
            self.model._cable_counter = 1
            
        new_id = self.model._cable_counter
        self.model._cable_counter += 1
        
        from core.mesh import CableObject
        cable = CableObject(new_id, self.node_i, self.node_j, self.cable_section)
        self.model.cables[new_id] = cable
        self.created_cable_id = new_id
        
        self.main_window.draw_both_canvases()

    def undo(self):
        if self.created_cable_id and self.created_cable_id in self.model.cables:
            del self.model.cables[self.created_cable_id]
        self.main_window.draw_both_canvases()

    def get_created_cable(self):
        if self.created_cable_id:
            return self.model.cables.get(self.created_cable_id)
        return None

class CmdDeleteCable(QUndoCommand):
    """Dedicated command to safely delete a Cable object."""
    def __init__(self, model, main_window, cable_id, description="Delete Cable"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.cable_id = cable_id
        self.cable_obj = None

    def redo(self):
        if hasattr(self.model, 'cables') and self.cable_id in self.model.cables:
            self.cable_obj = self.model.cables.pop(self.cable_id)
        
        if hasattr(self.main_window, 'selected_cable_ids') and self.cable_id in self.main_window.selected_cable_ids:
            self.main_window.selected_cable_ids.remove(self.cable_id)
        for cvs in [self.main_window.canvas, getattr(self.main_window, 'canvas2', None)]:
            if cvs and hasattr(cvs, 'selected_cable_ids') and self.cable_id in cvs.selected_cable_ids:
                cvs.selected_cable_ids.remove(self.cable_id)
                
        self.main_window.draw_both_canvases()

    def undo(self):
        if self.cable_obj:
            if not hasattr(self.model, 'cables'):
                self.model.cables = {}
            self.model.cables[self.cable_id] = self.cable_obj
        self.main_window.draw_both_canvases()

class CableDistributedLoad:
    """Temporary pure-data class for Cable loads until full backend integration."""
    def __init__(self, cable_id, pattern_name, val, direction, coord_sys, load_type):
        self.cable_id = cable_id
        self.pattern_name = pattern_name
        self.val = val
        self.direction = direction
        self.coord_system = coord_sys
        self.load_type = load_type

class CmdAssignCableLoad(QUndoCommand):
    """Assigns distributed loads to a selection of cables (Add/Replace/Delete)."""
    def __init__(self, model, main_window, cable_ids, data, description="Assign Cable Load"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.cable_ids = cable_ids
        self.data = data
        
        import copy
        self.old_loads = []
        for load in getattr(self.model, 'loads', []):
            if isinstance(load, CableDistributedLoad):
                if load.cable_id in cable_ids and load.pattern_name == data["pattern"]:
                    self.old_loads.append(copy.deepcopy(load))

    def redo(self):
        if not hasattr(self.model, 'loads'):
            self.model.loads = []

        mode = self.data["mode"]
        pattern = self.data["pattern"]

        if mode in ("replace", "delete"):
            for i in range(len(self.model.loads) - 1, -1, -1):
                load = self.model.loads[i]
                if isinstance(load, CableDistributedLoad):
                    if load.cable_id in self.cable_ids and load.pattern_name == pattern:
                        del self.model.loads[i]

        if mode in ("replace", "add") and self.data["value"] != 0:
            for cid in self.cable_ids:
                new_load = CableDistributedLoad(
                    cable_id=cid,
                    pattern_name=pattern,
                    val=self.data["value"],
                    direction=self.data["direction"],
                    coord_sys=self.data["coord_sys"],
                    load_type=self.data["load_type"]
                )
                self.model.loads.append(new_load)

        self.main_window.draw_both_canvases()

    def undo(self):
        import copy
        for i in range(len(self.model.loads) - 1, -1, -1):
            load = self.model.loads[i]
            if isinstance(load, CableDistributedLoad):
                if load.cable_id in self.cable_ids and load.pattern_name == self.data["pattern"]:
                    del self.model.loads[i]

        for old_load in self.old_loads:
            self.model.loads.append(copy.deepcopy(old_load))
            
        self.main_window.draw_both_canvases()

class CmdDivideFrame(QUndoCommand):
    """
    Divides a single frame element into two or more collinear sub-frames.

    `divide_fn(model, element_id)` performs the actual split (one of
    StructuralModel.divide_frame_by_number / _at_distance /
    _at_coordinate_plane / _at_grid_planes / _at_intersections) and returns
    {"created_node_ids": [...], "created_elem_ids": [...]}, or raises
    ValueError/KeyError on invalid input.

    On failure, redo() leaves the model untouched and sets self.error to
    the message; the caller should check cmd.error after add_command().
    """
    def __init__(self, model, main_window, element_id, divide_fn, description="Divide Frame"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.element_id = element_id
        self.divide_fn = divide_fn

        self.saved_elem = None
        self.saved_loads = []
        self.created_node_ids = []
        self.created_elem_ids = []
        self.error = None

    def redo(self):
        self.error = None

        if self.element_id not in self.model.elements:
            self.error = "The frame no longer exists."
            return

        orig = self.model.elements[self.element_id]
        self.saved_elem = copy.deepcopy(orig)
        self.saved_loads = [
            copy.deepcopy(l) for l in self.model.loads
            if getattr(l, 'element_id', None) == self.element_id
        ]

        try:
            result = self.divide_fn(self.model, self.element_id)
        except (ValueError, KeyError) as e:
            self.error = str(e)
            self.saved_elem = None
            self.saved_loads = []
            self._refresh_view()
            return

        self.created_node_ids = result.get("created_node_ids", [])
        self.created_elem_ids = result.get("created_elem_ids", [])
        self._refresh_view()

    def undo(self):
        if self.saved_elem is None:
            return

        for eid in self.created_elem_ids:
            if eid in self.model.elements:
                self.model.remove_element(eid)

        for nid in self.created_node_ids:
            if nid in self.model.nodes:
                del self.model.nodes[nid]
                self.model.loads = [
                    l for l in self.model.loads
                    if not (hasattr(l, 'node_id') and l.node_id == nid)
                ]

        el = self.saved_elem
        if el.node_i.id in self.model.nodes:
            el.node_i = self.model.nodes[el.node_i.id]
        else:
            self.model.nodes[el.node_i.id] = el.node_i
            self.model._node_counter = max(self.model._node_counter, el.node_i.id + 1)

        if el.node_j.id in self.model.nodes:
            el.node_j = self.model.nodes[el.node_j.id]
        else:
            self.model.nodes[el.node_j.id] = el.node_j
            self.model._node_counter = max(self.model._node_counter, el.node_j.id + 1)

        if getattr(el, 'section', None) is not None and el.section.name in self.model.sections:
            el.section = self.model.sections[el.section.name]

        self.model.elements[self.element_id] = el
        self.model._elem_counter = max(self.model._elem_counter, self.element_id + 1)

        for l in self.saved_loads:
            self.model.loads.append(copy.deepcopy(l))

        self.created_node_ids = []
        self.created_elem_ids = []

        self._refresh_view()

    def _refresh_view(self):
        self.main_window.draw_both_canvases()

class CmdJoinFrames(QUndoCommand):
    """
    Joins two or more connected, collinear frame elements into a single frame
    (SAP2000-style "Join Frames" — acts directly on the current selection,
    no dialog). keep_props_from_id picks which selected frame's section /
    beta / offsets / cardinal point / rigid-zone-factor the merged frame
    inherits.

    On failure, redo() leaves the model untouched and sets self.error to
    the message; the caller should check cmd.error after add_command().
    """
    def __init__(self, model, main_window, element_ids, keep_props_from_id, description="Join Frames"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.element_ids = list(element_ids)
        self.keep_props_from_id = keep_props_from_id

        self.saved_elems = {}
        self.saved_nodes = {}
        self.saved_loads = []
        self.created_elem_id = None
        self.error = None

    def redo(self):
        self.error = None

        missing = [eid for eid in self.element_ids if eid not in self.model.elements]
        if missing:
            self.error = "One or more selected frames no longer exist."
            return

        self.saved_elems = {eid: copy.deepcopy(self.model.elements[eid]) for eid in self.element_ids}

        touched_node_ids = set()
        for el in self.saved_elems.values():
            touched_node_ids.add(el.node_i.id)
            touched_node_ids.add(el.node_j.id)
        self.saved_nodes = {
            nid: copy.deepcopy(self.model.nodes[nid])
            for nid in touched_node_ids if nid in self.model.nodes
        }

        id_set = set(self.element_ids)
        self.saved_loads = [
            copy.deepcopy(l) for l in self.model.loads
            if getattr(l, 'element_id', None) in id_set
        ]

        try:
            result = self.model.join_frames(self.element_ids, self.keep_props_from_id)
        except (ValueError, KeyError) as e:
            self.error = str(e)
            self.saved_elems = {}
            self.saved_nodes = {}
            self.saved_loads = []
            self._refresh_view()
            return

        self.created_elem_id = result["created_elem_id"]
        self._refresh_view()

    def undo(self):
        if not self.saved_elems:
            return

        if self.created_elem_id is not None and self.created_elem_id in self.model.elements:
            self.model.remove_element(self.created_elem_id)

        for nid, node_obj in self.saved_nodes.items():
            if nid not in self.model.nodes:
                self.model.nodes[nid] = node_obj
                self.model._node_counter = max(self.model._node_counter, nid + 1)

        for eid, el_obj in self.saved_elems.items():
            if el_obj.node_i.id in self.model.nodes:
                el_obj.node_i = self.model.nodes[el_obj.node_i.id]
            if el_obj.node_j.id in self.model.nodes:
                el_obj.node_j = self.model.nodes[el_obj.node_j.id]
            if getattr(el_obj, 'section', None) is not None and el_obj.section.name in self.model.sections:
                el_obj.section = self.model.sections[el_obj.section.name]
            self.model.elements[eid] = el_obj
            self.model._elem_counter = max(self.model._elem_counter, eid + 1)

        for l in self.saved_loads:
            self.model.loads.append(copy.deepcopy(l))

        self.created_elem_id = None

        self._refresh_view()

    def _refresh_view(self):
        self.main_window.draw_both_canvases()

class CmdEditPushoverParamSets(QUndoCommand):
    """
    Define > Pushover Parameter Sets > Force vs Displacement...
    Replaces model.pushover_param_sets with the edited list. Going through
    the undo stack is what marks the model as modified (so closing prompts
    to save) and gives Ctrl+Z / Ctrl+Y for set edits.
    """
    def __init__(self, model, main_window, new_sets, description="Edit Pushover Parameter Sets"):
        super().__init__(description)
        self.model = model
        self.main_window = main_window
        self.old_sets = copy.deepcopy(model.pushover_param_sets)
        self.new_sets = copy.deepcopy(new_sets)

    def redo(self):
        self.model.pushover_param_sets = copy.deepcopy(self.new_sets)
        self._refresh_view()

    def undo(self):
        self.model.pushover_param_sets = copy.deepcopy(self.old_sets)
        self._refresh_view()

    def _refresh_view(self):
                                                    
        try:
            pdlg = getattr(self.main_window, '_pushover_dlg', None)
            if pdlg is not None and pdlg.isVisible():
                pdlg.reload_sets()
        except RuntimeError:
            pass

class CmdAssignAreaSolverMesh(QUndoCommand):
    """
    Assigns (or clears) an analysis-time mesh on shells.
    Nothing in the UI model changes except the 'solver_mesh' attribute, so undo/redo
    only has to remember the old and new value per shell.
    """
    def __init__(self, model, window, area_ids, solver_mesh):
        super().__init__("Assign Solver Mesh" if solver_mesh else "Clear Solver Mesh")
        self.model = model
        self.window = window
        self.new_value = copy.deepcopy(solver_mesh)
        self.old_values = {
            aid: copy.deepcopy(getattr(model.area_elements[aid], 'solver_mesh', None))
            for aid in area_ids if aid in model.area_elements
        }

    def redo(self):
        self.model.assign_area_solver_mesh(list(self.old_values.keys()), self.new_value)
        self.window.draw_both_canvases()

    def undo(self):
        for aid, old in self.old_values.items():
            ae = self.model.area_elements.get(aid)
            if ae is not None:
                ae.solver_mesh = copy.deepcopy(old)
        self.window.draw_both_canvases()
