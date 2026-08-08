"""
SolidMesher — OpenCivil (Gmsh Edition)
=======================================
Converts frame elements from a .mf model into a continuous Tet4 solid mesh
using the Gmsh OpenCASCADE kernel. 

Features:
- Boolean union (fuse) of all overlapping structural members.
- Unstructured tetrahedral meshing.
- Automatic boundary condition mapping to joint faces.
"""

import numpy as np
import gmsh
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from linear_static.element_library import get_rotation_matrix

class SolidMesher:
    def __init__(self, solid_data_manager, mesh_size=0.15, merge_tol=1e-6, **kwargs):
        """
        Args:
            solid_data_manager : SolidDataManager (process_all() already called)
            mesh_size          : Target edge length for the tetrahedral mesh
            merge_tol          : Tolerance for node distance checks
        """
        self.dm        = solid_data_manager
        self.mesh_size = mesh_size
        self.merge_tol = merge_tol

        self._frame_nodes = list(self.dm.nodes)

    def mesh_all(self):
        """
        Builds CSG geometry, meshes via Gmsh, and populates dm.
        """
        raw_elements  = self.dm.raw.get('elements', [])
        raw_sections  = {s['name']: s for s in self.dm.raw.get('sections', [])}
        raw_nodes_map = {n['id']: n for n in self.dm.raw['nodes']}

        print(f"SolidMesher: Building geometry in Gmsh (mesh_size={self.mesh_size})...")

        import signal as _signal
        _orig_signal = _signal.signal
        _signal.signal = lambda *a, **kw: None
        gmsh.initialize()
        _signal.signal = _orig_signal
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("OpenCivil_Joint")

        vols = []
        global_mat = None

        for el in raw_elements:
            sec = raw_sections.get(el['sec_name'])
            if not sec: continue

            if global_mat is None:
                mat_name = sec.get('mat_name', list(self.dm.materials.keys())[0])
                global_mat = self.dm.materials.get(mat_name)

            b, h = self._section_bbox(sec)
            n1d = raw_nodes_map[el['n1_id']]
            n2d = raw_nodes_map[el['n2_id']]
            p1  = np.array([n1d['x'], n1d['y'], n1d['z']], dtype=float)
            p2  = np.array([n2d['x'], n2d['y'], n2d['z']], dtype=float)

            off_i = np.array(el.get('off_i', [0.0, 0.0, 0.0]), dtype=float)
            off_j = np.array(el.get('off_j', [0.0, 0.0, 0.0]), dtype=float)
            p1_adj = p1 + off_i
            p2_adj = p2 + off_j

            L = np.linalg.norm(p2_adj - p1_adj)
            if L < 1e-9: continue

            cardinal = el.get('cardinal', 10)
            cp_y, cp_z = self._cardinal_offset(cardinal, b, h)

            vol_tag = self._add_section_volume(sec, L, cp_y, cp_z)
            if vol_tag is None:
                continue

            T = self._get_transform_matrix(p1_adj, p2_adj, el.get('beta', 0.0))
            gmsh.model.occ.affineTransform([(3, vol_tag)], T)
            vols.append((3, vol_tag))

        if not vols:
            print("  SolidMesher: No valid volumes generated.")
            gmsh.finalize()
            return

        print("  SolidMesher: Executing Boolean Union (Fuse)...")
        if len(vols) > 1:
            gmsh.model.occ.fuse([vols[0]], vols[1:])
        gmsh.model.occ.synchronize()

        gmsh.model.occ.removeAllDuplicates()
        gmsh.model.occ.synchronize()

        print("  SolidMesher: Generating Tet10 mesh...")
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", self.mesh_size)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", self.mesh_size)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        
        gmsh.model.mesh.generate(3)

        self._extract_and_populate(global_mat, raw_elements, raw_sections)
        gmsh.finalize()

        self.dm._generate_self_weight()

        print(f"SolidMesher: done. "
              f"{len(self.dm.nodes)} nodes, "
              f"{len(self.dm.elements)} elements, "
              f"{self.dm.total_dofs} DOFs.")

    def mesh_subset(self, selected_element_ids):
        """
        Builds CSG geometry ONLY for the selected frame elements,
        meshes via Gmsh, and populates dm.
        """
        raw_elements  = self.dm.raw.get('elements', [])
        
        target_elements = [el for el in raw_elements if el['id'] in selected_element_ids]
        
        if not target_elements:
            print("  SolidMesher: No valid elements selected for submodeling.")
            return

        raw_sections  = {s['name']: s for s in self.dm.raw.get('sections', [])}
        raw_nodes_map = {n['id']: n for n in self.dm.raw['nodes']}

        print(f"SolidMesher: Building subset geometry for elements {selected_element_ids} (mesh_size={self.mesh_size})...")

        import signal as _signal
        _orig_signal = _signal.signal
        _signal.signal = lambda *a, **kw: None
        gmsh.initialize()
        _signal.signal = _orig_signal
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("OpenCivil_Submodel")

        vols = []
        global_mat = None

        for el in target_elements:
            sec = raw_sections.get(el['sec_name'])
            if not sec: continue

            if global_mat is None:
                mat_name = sec.get('mat_name', list(self.dm.materials.keys())[0])
                global_mat = self.dm.materials.get(mat_name)

            b, h = self._section_bbox(sec)
            n1d = raw_nodes_map[el['n1_id']]
            n2d = raw_nodes_map[el['n2_id']]
            p1  = np.array([n1d['x'], n1d['y'], n1d['z']], dtype=float)
            p2  = np.array([n2d['x'], n2d['y'], n2d['z']], dtype=float)

            off_i = np.array(el.get('off_i', [0.0, 0.0, 0.0]), dtype=float)
            off_j = np.array(el.get('off_j', [0.0, 0.0, 0.0]), dtype=float)
            p1_adj = p1 + off_i
            p2_adj = p2 + off_j

            L = np.linalg.norm(p2_adj - p1_adj)
            if L < 1e-9: continue

            cardinal = el.get('cardinal', 10)
            cp_y, cp_z = self._cardinal_offset(cardinal, b, h)

            vol_tag = self._add_section_volume(sec, L, cp_y, cp_z)
            if vol_tag is None:
                continue

            T = self._get_transform_matrix(p1_adj, p2_adj, el.get('beta', 0.0))
            gmsh.model.occ.affineTransform([(3, vol_tag)], T)
            vols.append((3, vol_tag))

        if not vols:
            print("  SolidMesher: No valid volumes generated for subset.")
            gmsh.finalize()
            return

        print("  SolidMesher: Executing Boolean Union (Fuse) on subset...")
        if len(vols) > 1:
            gmsh.model.occ.fuse([vols[0]], vols[1:])
        gmsh.model.occ.synchronize()

        print("  SolidMesher: Generating Tet10 mesh for subset...")
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", self.mesh_size)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", self.mesh_size)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        
        gmsh.model.mesh.generate(3)

        self._extract_and_populate(global_mat, target_elements, raw_sections)
        gmsh.finalize()

        self.dm._generate_self_weight()

        print(f"SolidMesher: Subset meshing done. "
              f"{len(self.dm.nodes)} nodes, "
              f"{len(self.dm.elements)} elements, "
              f"{self.dm.total_dofs} DOFs.")

    def _add_section_volume(self, sec, L, cp_y=0.0, cp_z=0.0):
        """
        Creates a Gmsh OCC volume for the given section extruded along local X (length L).
        cp_y, cp_z : cardinal point offsets in local Y and Z.
        Returns the volume tag, or None on failure.

        Section types handled:
            rectangular  → addBox  (same as before)
            circular     → addCylinder
            pipe         → addCylinder outer − inner (BooleanCut)
            i_section    → polygon extrude  (I-shape outline)
            tube         → polygon extrude  (hollow rectangle outline)
            trapezoidal  → polygon extrude  (trapezoid outline)
            general / *  → falls back to rectangular bbox
        """
        t = sec.get('type', 'rectangular')

        if t == 'rectangular':
            b, h = float(sec['b']), float(sec['h'])
            return gmsh.model.occ.addBox(0, -b/2 + cp_y, -h/2 + cp_z, L, b, h)

        elif t == 'circular':
            r = float(sec['d']) / 2.0
                                                                   
            return gmsh.model.occ.addCylinder(0, cp_y, cp_z, L, 0, 0, r)

        elif t == 'pipe':
            r_out = float(sec['d']) / 2.0
            t_thk = float(sec.get('t', r_out * 0.1))
            r_in  = max(r_out - t_thk, 1e-6)
            outer = gmsh.model.occ.addCylinder(0, cp_y, cp_z, L, 0, 0, r_out)
            inner = gmsh.model.occ.addCylinder(0, cp_y, cp_z, L, 0, 0, r_in)
            result, _ = gmsh.model.occ.cut([(3, outer)], [(3, inner)])
            return result[0][1] if result else None

        elif t == 'i_section':
            h     = float(sec['h'])
            wt    = float(sec.get('w_top', 0.2))
            tt    = float(sec.get('t_top', 0.012))
            wb    = float(sec.get('w_bot', 0.2))
            tb    = float(sec.get('t_bot', 0.012))
            tw    = float(sec.get('t_web', 0.008))
                                                                     
            y0, z0 = cp_y, cp_z
            hw = h / 2.0                                        

            pts_yz = [
                                             
                (-wb/2,  -hw), ( wb/2,  -hw),
                                        
                ( wb/2,  -hw + tb), ( tw/2, -hw + tb),
                                         
                ( tw/2,   hw - tt),
                                         
                ( wt/2,   hw - tt), ( wt/2,  hw), (-wt/2,  hw),
                (-wt/2,   hw - tt),
                                          
                (-tw/2,   hw - tt), (-tw/2, -hw + tb),
                (-wb/2,  -hw + tb),
            ]
            return self._extrude_polygon(pts_yz, L, y0, z0)

        elif t == 'arbitrary':
            pts_yz = sec.get('vertices', [])
            if not pts_yz or len(pts_yz) < 3:
                print("  Warning: Arbitrary section has missing or invalid vertices.")
                return None
            return self._extrude_polygon(pts_yz, L, cp_y, cp_z)

        elif t == 'tube':
            d  = float(sec.get('d', 0.2))               
            b  = float(sec.get('b', 0.15))              
            tf = float(sec.get('tf', 0.01))                   
            tw = float(sec.get('tw', 0.01))                
            y0, z0 = cp_y, cp_z
            hw, hb = d / 2.0, b / 2.0
                                                   
            outer = gmsh.model.occ.addBox(0, -hb + y0, -hw + z0, L, b, d)
            i_b   = max(b - 2*tw, 1e-4)
            i_d   = max(d - 2*tf, 1e-4)
            inner = gmsh.model.occ.addBox(0, -(i_b/2) + y0, -(i_d/2) + z0, L, i_b, i_d)
            result, _ = gmsh.model.occ.cut([(3, outer)], [(3, inner)])
            return result[0][1] if result else None

        elif t == 'trapezoidal':
            d    = float(sec['d'])
            w_top = float(sec.get('w_top', 0.2))
            w_bot = float(sec.get('w_bot', 0.3))
            y0, z0 = cp_y, cp_z
            hw = d / 2.0
            pts_yz = [
                (-w_bot/2, -hw), ( w_bot/2, -hw),
                ( w_top/2,  hw), (-w_top/2,  hw),
            ]
            return self._extrude_polygon(pts_yz, L, y0, z0)

        else:
            b = float(sec.get('b', 0.3))
            h = float(sec.get('h', 0.3))
            return gmsh.model.occ.addBox(0, -b/2 + cp_y, -h/2 + cp_z, L, b, h)

    def _extrude_polygon(self, pts_yz, L, offset_y=0.0, offset_z=0.0):
        """
        Helper: creates a closed polygon in the Y-Z plane at X=0,
        then extrudes it along +X by length L.
        pts_yz : list of (y, z) tuples (already centred / offset as needed)
        Returns the resulting volume tag.
        """
        pt_tags = []
        for (y, z) in pts_yz:
            pt_tags.append(gmsh.model.occ.addPoint(0, y + offset_y, z + offset_z))

        line_tags = []
        n = len(pt_tags)
        for i in range(n):
            line_tags.append(gmsh.model.occ.addLine(pt_tags[i], pt_tags[(i+1) % n]))

        loop = gmsh.model.occ.addCurveLoop(line_tags)
        surf = gmsh.model.occ.addPlaneSurface([loop])

        extruded = gmsh.model.occ.extrude([(2, surf)], L, 0, 0)
                                                                  
        for dim, tag in extruded:
            if dim == 3:
                return tag
        return None

    def _section_bbox(self, sec):
        """Returns (width_y, height_z) bounding box in local frame."""
        t = sec.get('type', 'rectangular')
        if t == 'rectangular':  return float(sec['b']), float(sec['h'])
        if t == 'circular':     return float(sec['d']), float(sec['d'])
        if t == 'pipe':         return float(sec['d']), float(sec['d'])
        if t == 'i_section':    return max(float(sec.get('w_top', 0.3)), float(sec.get('w_bot', 0.3))), float(sec['h'])
        if t == 'tube':         return float(sec.get('b', 0.3)), float(sec.get('d', 0.3))
        if t == 'trapezoidal':  return max(float(sec.get('w_top', 0.3)), float(sec.get('w_bot', 0.3))), float(sec['d'])
        if t == 'arbitrary':
            verts = sec.get('vertices', [])
            if verts:
                ys = [v[0] for v in verts]
                zs = [v[1] for v in verts]
                return float(max(ys) - min(ys)), float(max(zs) - min(zs))
            
    def _cardinal_offset(self, cardinal, b, h):
        """
        Returns (offset_y, offset_z) in local coords to shift box origin.
        Matches the sign convention from mesh.py exactly.
        """
        offsets = {
            1:  (+b/2,  +h/2),                
            2:  ( 0.0,  +h/2),                  
            3:  (-b/2,  +h/2),                 
            4:  (+b/2,   0.0),                
            5:  ( 0.0,   0.0),                             
            6:  (-b/2,   0.0),                 
            7:  (+b/2,  -h/2),             
            8:  ( 0.0,  -h/2),               
            9:  (-b/2,  -h/2),              
            10: ( 0.0,   0.0),                         
            11: ( 0.0,   0.0),                                           
        }
        return offsets.get(cardinal, (0.0, 0.0))

    def _get_transform_matrix(self, p1, p2, beta_deg):
        """Builds a 4x4 row-major affine transformation matrix for Gmsh."""
        R = get_rotation_matrix(p1, p2, beta_deg)
        
        vx_frame = R[0]
        vy_frame = R[1]
        vz_frame = R[2]

        x_g = vx_frame
        y_g = vy_frame 
        z_g = vz_frame 

        return [
            x_g[0], y_g[0], z_g[0], p1[0],
            x_g[1], y_g[1], z_g[1], p1[1],
            x_g[2], y_g[2], z_g[2], p1[2],
            0.0,    0.0,    0.0,    1.0
        ]

    def _extract_and_populate(self, mat, raw_elements, raw_sections):
        """Extracts Gmsh data into OpenCivil's DataManager."""
        nodeTags, coords_flat, _ = gmsh.model.mesh.getNodes()
        coords = coords_flat.reshape(-1, 3)
        
        tag_to_idx = {tag: i for i, tag in enumerate(nodeTags)}

        new_nodes = []
        for i, c in enumerate(coords):
            new_nodes.append({
                'id':         i + 1,
                'idx':        i,
                'coords':     np.array(c, dtype=float),
                'restraints': [False, False, False],
                'is_midedge': False
            })

        raw_nodes_map_local = {n['id']: n for n in self.dm.raw['nodes']}

        for fn in self._frame_nodes:
            if not any(fn['restraints']):
                continue

            connected = []                                        
            for el in raw_elements:
                n1d = raw_nodes_map_local.get(el['n1_id'])
                n2d = raw_nodes_map_local.get(el['n2_id'])
                if n1d is None or n2d is None:
                    continue
                p1 = np.array([n1d['x'], n1d['y'], n1d['z']], dtype=float)
                p2 = np.array([n2d['x'], n2d['y'], n2d['z']], dtype=float)
                vec = None
                if el['n1_id'] == fn['id']:
                    vec = p2 - p1
                elif el['n2_id'] == fn['id']:
                    vec = p1 - p2
                if vec is not None and np.linalg.norm(vec) > 1e-9:
                    axis = vec / np.linalg.norm(vec)
                    sec  = raw_sections.get(el.get('sec_name', ''), {})
                    sb, sh = self._section_bbox(sec)
                    connected.append((axis, sb, sh))

            if not connected:
                continue

            for axis, sec_b, sec_h in connected:
                half_diag = np.sqrt(sec_b**2 + sec_h**2) / 2.0 + 1e-3
                face_tol  = self.mesh_size * 0.6
                
                slave_indices = []
                for n in new_nodes:
                    delta = n['coords'] - fn['coords']
                    along = float(np.dot(delta, axis))
                    perp  = np.linalg.norm(delta - along * axis)

                    if abs(along) < face_tol and perp < half_diag:
                        slave_indices.append(n['idx'])
                                                                          
                if slave_indices:
                    self.dm.rigid_links.append({
                        'master_coords': fn['coords'].copy(),
                        'restraints': fn['restraints'],                         
                        'slave_indices': slave_indices
                    })

        self.dm.node_id_to_idx = {n['id']: n['idx'] for n in new_nodes}
        self.dm.nodes          = new_nodes
        self.dm.total_dofs     = len(new_nodes) * 3

        for rl in self.dm.rigid_links:
            rl['master_dof_start'] = self.dm.total_dofs
            self.dm.total_dofs += 6

        elemTypes, elemTags, elemNodeTags = gmsh.model.mesh.getElements(dim=3)
        new_elems = []
        
        if 11 in elemTypes:  
            type_idx = list(elemTypes).index(11)
                                                          
            tet_tags = elemNodeTags[type_idx].reshape(-1, 10) 
            
            for eid, t_tags in enumerate(tet_tags):
                n_indices = [tag_to_idx[t] for t in t_tags]

                for n_idx in n_indices[4:]:
                    new_nodes[n_idx]['is_midedge'] = True
                
                new_elems.append({
                    'id':           eid + 1,
                    'node_indices': n_indices,
                    'coords':       np.array([coords[i] for i in n_indices], dtype=float),
                    'material':     mat,
                })

        self.dm.elements = new_elems
        self._remap_loads()

    def _remap_loads(self):
        """
        Distributes original frame nodal loads over all solid nodes on the
        loaded face. 

        Fix: instead of grabbing the first connected element (random for joints),
        we collect ALL connected elements and pick the one whose inward axis is
        most aligned with the load force direction. This ensures a vertical force
        always finds the horizontal face, not a random one.

        For moment-only loads (no translational force), falls back to first element.
        For isolated nodes (no connected element), falls back to nearest node.
        """
        old_id_to_coord = {fn['id']: fn['coords'] for fn in self._frame_nodes}
        raw_elements     = self.dm.raw.get('elements', [])
        raw_sections     = {s['name']: s for s in self.dm.raw.get('sections', [])}
        raw_nodes_map    = {n['id']: n for n in self.dm.raw['nodes']}

        loads_to_remove = []
        loads_to_add    = []

        for load in self.dm.raw.get('loads', []):
            if load.get('type') != 'nodal':
                continue
            old_coord = old_id_to_coord.get(load['node_id'])
            if old_coord is None:
                continue

            connected = []                                        
            for el in raw_elements:
                n1d = raw_nodes_map.get(el['n1_id'])
                n2d = raw_nodes_map.get(el['n2_id'])
                if n1d is None or n2d is None:
                    continue
                p1  = np.array([n1d['x'], n1d['y'], n1d['z']], dtype=float)
                p2  = np.array([n2d['x'], n2d['y'], n2d['z']], dtype=float)
                vec = None
                if el['n1_id'] == load['node_id']:
                    vec = p2 - p1                                       
                elif el['n2_id'] == load['node_id']:
                    vec = p1 - p2                                       
                if vec is not None and np.linalg.norm(vec) > 1e-9:
                    axis = vec / np.linalg.norm(vec)
                    sec  = raw_sections.get(el.get('sec_name', ''), {})
                    sb, sh = self._section_bbox(sec)
                    connected.append((axis, sb, sh))

            if not connected:
                                                            
                best_id, best_dist = None, float('inf')
                for n in self.dm.nodes:
                    d = np.linalg.norm(n['coords'] - old_coord)
                    if d < best_dist:
                        best_dist = d
                        best_id   = n['id']
                if best_id is not None:
                    load['node_id'] = best_id
                continue

            fx = load.get('fx', 0.0)
            fy = load.get('fy', 0.0)
            fz = load.get('fz', 0.0)
            force_vec = np.array([fx, fy, fz], dtype=float)
            force_mag = np.linalg.norm(force_vec)

            if force_mag > 1e-12:
                force_dir = force_vec / force_mag
                                                                     
                best_idx = max(range(len(connected)),
                            key=lambda i: abs(np.dot(connected[i][0], force_dir)))
            else:
                                                                     
                best_idx = 0

            axis, sec_b, sec_h = connected[best_idx]

            half_diag  = np.sqrt(sec_b**2 + sec_h**2) / 2.0 + 1e-3
            face_tol   = self.mesh_size * 0.6
            face_nodes = []
            for n in self.dm.nodes:
                delta = n['coords'] - old_coord
                along = float(np.dot(delta, axis))
                perp  = np.linalg.norm(delta - along * axis)
                if abs(along) < face_tol and perp < half_diag:
                    face_nodes.append(n['id'])

            if not face_nodes:
                                                                          
                best_id, best_dist = None, float('inf')
                for n in self.dm.nodes:
                    d = np.linalg.norm(n['coords'] - old_coord)
                    if d < best_dist:
                        best_dist = d
                        best_id   = n['id']
                if best_id is not None:
                    load['node_id'] = best_id
                print(f"  _remap_loads: WARNING node {load['node_id']} face not found, "
                    f"snapped to nearest.")
                continue

            mid_face_nodes = [nid for nid in face_nodes if self.dm.nodes[self.dm.node_id_to_idx[nid]]['is_midedge']]
            
            target_nodes = mid_face_nodes if mid_face_nodes else face_nodes
            
            mx = load.get('mx', 0.0)
            my = load.get('my', 0.0)
            mz = load.get('mz', 0.0)
            moment_vec = np.array([mx, my, mz], dtype=float)

            n_face  = len(target_nodes)
            fx_each = fx / n_face
            fy_each = fy / n_face
            fz_each = fz / n_face

            has_moment = np.linalg.norm(moment_vec) > 1e-12
            omega = np.zeros(3)
            centroid = np.zeros(3)
            
            if has_moment:
                                                                
                target_coords = []
                for nid in target_nodes:
                    idx = self.dm.node_id_to_idx[nid]
                    target_coords.append(self.dm.nodes[idx]['coords'])
                target_coords = np.array(target_coords)
                centroid = np.mean(target_coords, axis=0)

                J = np.zeros((3, 3))
                for coords in target_coords:
                    r = coords - centroid
                    r2 = np.dot(r, r)
                    J += r2 * np.eye(3) - np.outer(r, r)
                
                try:
                    omega = np.linalg.solve(J, moment_vec)
                except np.linalg.LinAlgError:
                    omega = np.zeros(3)                                                    

            loads_to_remove.append(load)
            
            for nid in target_nodes:
                idx = self.dm.node_id_to_idx[nid]
                
                f_mom = np.zeros(3)
                if has_moment:
                    r = self.dm.nodes[idx]['coords'] - centroid
                    f_mom = np.cross(omega, r)
                
                loads_to_add.append({
                    'type':    'nodal',
                    'pattern': load['pattern'],
                    'node_id': nid,
                    'fx': fx_each + f_mom[0], 
                    'fy': fy_each + f_mom[1], 
                    'fz': fz_each + f_mom[2],
                    'mx': 0.0, 'my': 0.0, 'mz': 0.0,
                })

            print(f"  _remap_loads: node {load['node_id']} → "
                f"distributed over {n_face} face nodes "
                f"(axis={np.round(axis,2)}, "
                f"f=[{fx_each:.2e},{fy_each:.2e},{fz_each:.2e}] N each).")

        for l in loads_to_remove:
            self.dm.raw['loads'].remove(l)
        self.dm.raw['loads'].extend(loads_to_add)
        
def patch_data_manager(dm):
    dm.sections_raw = {
        s['name']: {'mat_name': s['mat_name']}
        for s in dm.raw.get('sections', [])
    }
