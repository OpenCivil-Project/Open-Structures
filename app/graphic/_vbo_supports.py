import numpy as np
import pyqtgraph.opengl as gl

def build_boundary_visuals(nodes_dict, links_dict=None, link_props=None, scale=1.0,
                            show_1joint_links=True, show_2joint_links=True,
                            show_support_glyphs=True,
                            node_displacements=None, disp_scale=0.0):
    """
    Generates unified boundary conditions in a single pass:
    - Meshes: Fixed, Pinned, Roller, Custom supports + Coupled Spring warnings.
    - Lines: Standard 6-DOF springs.

    node_displacements: optional {node_id: [dx,dy,dz,rx,ry,rz]} results dict.
    disp_scale: scalar multiplier applied to node_displacements (e.g. deflection_scale * anim_factor).
    When provided, nodal springs and 1-joint links attach to the DISPLACED node
    position, while their ground/anchor ends stay fixed at the node's original
    (undeformed) position. 2-joint links are never displaced.
    """
                                      
    mesh_verts, mesh_faces, mesh_colors = [], [], []
    line_verts, line_colors = [], []
    mesh_idx_offset = 0

    s = scale * 6.0
    
    c_x = [0.90, 0.45, 0.45, 1.0]                                           
    c_y = [0.45, 0.75, 0.50, 1.0]                                           
    c_z = [0.45, 0.60, 0.90, 1.0]                                           
    c_rot = [0.95, 0.75, 0.40, 1.0]                                                          
    c_coupled = [1.0, 0.0, 1.0, 0.6]                                                     

    def add_box(cx, cy, cz, wx, wy, wz, color):
        nonlocal mesh_idx_offset
        v = [
            [cx-wx, cy-wy, cz-wz], [cx+wx, cy-wy, cz-wz], [cx+wx, cy+wy, cz-wz], [cx-wx, cy+wy, cz-wz],
            [cx-wx, cy-wy, cz+wz], [cx+wx, cy-wy, cz+wz], [cx+wx, cy+wy, cz+wz], [cx-wx, cy+wy, cz+wz]
        ]
        f = [
            [0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
            [0, 3, 7], [0, 7, 4], [1, 2, 6], [1, 6, 5]
        ]
        mesh_verts.extend(v)
        mesh_faces.extend([[i + mesh_idx_offset for i in face] for face in f])
        for _ in range(8): mesh_colors.append(color)
        mesh_idx_offset += 8

    def add_pyramid(apex_x, apex_y, apex_z, base_w, height, color):
        nonlocal mesh_idx_offset
        z_base = apex_z - height
        v = [
            [apex_x, apex_y, apex_z],
            [apex_x-base_w, apex_y-base_w, z_base], [apex_x+base_w, apex_y-base_w, z_base],
            [apex_x+base_w, apex_y+base_w, z_base], [apex_x-base_w, apex_y+base_w, z_base]
        ]
        f = [
            [0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
            [1, 2, 3], [1, 3, 4]
        ]
        mesh_verts.extend(v)
        mesh_faces.extend([[i + mesh_idx_offset for i in face] for face in f])
        for _ in range(5): mesh_colors.append(color)
        mesh_idx_offset += 5

    def add_sphere(cx, cy, cz, radius, color, bands=8):
        nonlocal mesh_idx_offset
        local_verts = []
        local_faces = []
        
        for i in range(bands + 1):
            lat = np.pi * i / bands
            z_val = np.cos(lat)
            r_ring = np.sin(lat)
            for j in range(bands):
                 lon = 2 * np.pi * j / bands
                 x_val = r_ring * np.cos(lon)
                 y_val = r_ring * np.sin(lon)
                 local_verts.append([cx + x_val*radius, cy + y_val*radius, cz + z_val*radius])
        
        for i in range(bands):
            for j in range(bands):
                row1 = i * bands
                row2 = (i + 1) * bands
                c1 = j
                c2 = (j + 1) % bands
                p1, p2 = row1 + c1, row1 + c2
                p3, p4 = row2 + c2, row2 + c1
                local_faces.append([p1, p2, p4])
                local_faces.append([p2, p3, p4])

        mesh_verts.extend(local_verts)
        mesh_faces.extend([[i + mesh_idx_offset for i in face] for face in local_faces])
        for _ in range(len(local_verts)): mesh_colors.append(color)
        mesh_idx_offset += len(local_verts)

    def add_line_spring(p1, p2, color, coil_radius, turns=5, lead_frac=0.4):
        """Draws a coil spanning most of p1->p2, with short straight leads at each end."""
        vec = p2 - p1
        L = np.linalg.norm(vec)
        if L < 1e-6:
            return
        u = vec / L

        up = np.array([0.0, 0.0, 1.0])
        if abs(np.dot(u, up)) > 0.99:
            up = np.array([0.0, 1.0, 0.0])
        v = np.cross(u, up)
        v = v / np.linalg.norm(v)
        w = np.cross(u, v)

        lead1_end = p1 + u * (L * lead_frac)
        lead2_start = p2 - u * (L * lead_frac)

        line_verts.append(p1); line_verts.append(lead1_end)
        line_colors.append(color); line_colors.append(color)

        pts_per_turn = 12
        total_pts = turns * pts_per_turn
        coil_len = L * (1.0 - 2.0 * lead_frac)
        prev_pt = lead1_end

        for i in range(1, total_pts + 1):
            t = i / total_pts
            angle = t * turns * 2 * np.pi
            center = lead1_end + u * (coil_len * t)
            curr_pt = center + (coil_radius * np.cos(angle) * v) + (coil_radius * np.sin(angle) * w)

            line_verts.append(prev_pt)
            line_verts.append(curr_pt)
            line_colors.append(color)
            line_colors.append(color)

            prev_pt = curr_pt

        line_verts.append(prev_pt); line_verts.append(lead2_start)
        line_colors.append(color); line_colors.append(color)

        line_verts.append(lead2_start); line_verts.append(p2)
        line_colors.append(color); line_colors.append(color)

    def add_axis_spring(base_pt, axis_vec, color, is_rotational=False, attach_pt=None):
        length = (10 * scale) if is_rotational else (22 * scale)
        
        radius = (2.5 * scale) if is_rotational else (3.0 * scale) 
        
        end_pt = base_pt + axis_vec * length
        start_pt = attach_pt if attach_pt is not None else base_pt

        add_line_spring(start_pt, end_pt, color, coil_radius=radius, turns=3, lead_frac=0.2)

        plate_half = radius * 1.15
        thin = s * 0.15
        
        wx = thin if abs(axis_vec[0]) > 0.5 else plate_half
        wy = thin if abs(axis_vec[1]) > 0.5 else plate_half
        wz = thin if abs(axis_vec[2]) > 0.5 else plate_half
        
        add_box(end_pt[0], end_pt[1], end_pt[2], wx, wy, wz, color)

    def add_wireframe_box(cx, cy, cz, wx, wy, wz, color):
                              
        v0, v1 = [cx-wx, cy-wy, cz-wz], [cx+wx, cy-wy, cz-wz]
        v2, v3 = [cx+wx, cy+wy, cz-wz], [cx-wx, cy+wy, cz-wz]
        v4, v5 = [cx-wx, cy-wy, cz+wz], [cx+wx, cy-wy, cz+wz]
        v6, v7 = [cx+wx, cy+wy, cz+wz], [cx-wx, cy+wy, cz+wz]

        edges = [
            (v0, v1), (v1, v2), (v2, v3), (v3, v0),
            (v4, v5), (v5, v6), (v6, v7), (v7, v4),
            (v0, v4), (v1, v5), (v2, v6), (v3, v7)
        ]
        
        for p1, p2 in edges:
            line_verts.append(p1)
            line_verts.append(p2)
            line_colors.append(color)
            line_colors.append(color)

    node_displacements = node_displacements or {}

    for n_id, node in nodes_dict.items():
        base_pt = np.array([node.x, node.y, node.z])
        x, y, z = node.x, node.y, node.z

        struct_pt = base_pt
        disp = node_displacements.get(str(n_id))
        if disp is not None and disp_scale:
            struct_pt = base_pt + np.array(disp[:3]) * disp_scale

        if hasattr(node, 'restraints') and any(node.restraints):
            r = node.restraints
            is_fixed = all(r[:3]) and all(r[3:]) 
            is_pinned = all(r[:3]) and not any(r[3:]) 
            is_roller = r[2] and not any(r[0:2]) and not any(r[3:])
            
            if show_support_glyphs:
                if is_fixed:
                    c = (0.40, 0.45, 0.50, 1.0)
                    add_box(x, y, z - s, s*0.8, s*0.8, s, c)
                    add_box(x, y, z - s*2.1, s*1.2, s*1.2, s*0.1, c)
                elif is_pinned:
                    c = (0.25, 0.55, 0.75, 1.0)
                    add_pyramid(x, y, z, s*0.8, s*1.8, c)
                    add_box(x, y, z - s*1.9, s*1.2, s*1.2, s*0.1, c)
                elif is_roller:
                    c = (0.20, 0.65, 0.50, 1.0)
                    add_sphere(x, y, z - s*0.9, s*0.9, c)            
                    add_box(x, y, z - s*1.9, s*1.2, s*1.2, s*0.1, c)
                else:                       
                    c = (0.85, 0.55, 0.20, 1.0)
                    add_pyramid(x, y, z, s*0.6, s, c)
                    v = [[x, y, z], [x-s*0.6, y-s*0.6, z-s], [x+s*0.6, y-s*0.6, z-s], 
                         [x+s*0.6, y+s*0.6, z-s], [x-s*0.6, y+s*0.6, z-s], [x, y, z-s*2]]
                    f = [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
                         [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4]]
                    mesh_verts.extend(v)
                    mesh_faces.extend([[i + mesh_idx_offset for i in face] for face in f])
                    for _ in range(6): mesh_colors.append(c)
                    mesh_idx_offset += 6

        k = getattr(node, 'spring_matrix', None)
        if k is not None:
            diag = np.diag(np.diag(k))
            off_diag = k - diag
            
            if np.any(np.abs(off_diag) > 1e-6):
                                                  
                add_wireframe_box(x, y, z, s*0.8, s*0.8, s*0.8, [0.0, 0.0, 0.0, 1.0])
            else:
                                                                                       
                if abs(k[0, 0]) > 1e-6: add_axis_spring(base_pt, np.array([1.0, 0.0, 0.0]), c_x, attach_pt=struct_pt)
                if abs(k[1, 1]) > 1e-6: add_axis_spring(base_pt, np.array([0.0, 1.0, 0.0]), c_y, attach_pt=struct_pt)
                
                if abs(k[2, 2]) > 1e-6: add_axis_spring(base_pt, np.array([0.0, 0.0, -1.0]), c_z, attach_pt=struct_pt)
                
                if abs(k[3, 3]) > 1e-6: add_axis_spring(base_pt, np.array([1.0, 0.0, 0.0]), c_rot, is_rotational=True, attach_pt=struct_pt)
                if abs(k[4, 4]) > 1e-6: add_axis_spring(base_pt, np.array([0.0, 1.0, 0.0]), c_rot, is_rotational=True, attach_pt=struct_pt)
                if abs(k[5, 5]) > 1e-6: add_axis_spring(base_pt, np.array([0.0, 0.0, 1.0]), c_rot, is_rotational=True, attach_pt=struct_pt)

    if links_dict is None: links_dict = {}
    if link_props is None: link_props = {}
    c_link = [0.0, 0.0, 0.0, 1.0]                                   

    for lid, link in links_dict.items():
        prop = link_props.get(link['prop_name'])
        if not prop: continue

        nodes = link['nodes']

        if len(nodes) == 1:
            if not show_1joint_links:
                continue
                                             
            nid = nodes[0]
                                                           
            n = nodes_dict.get(nid) or nodes_dict.get(str(nid))
            
            if n:
                                                                          
                p1_orig = np.array([n.x, n.y, n.z])
                p1 = p1_orig
                disp = node_displacements.get(str(nid))
                if disp is not None and disp_scale:
                    p1 = p1_orig + np.array(disp[:3]) * disp_scale

                ground_z = n.z - s * 2.2
                p2 = np.array([n.x, n.y, ground_z])
                add_line_spring(p1, p2, c_link, coil_radius=s * 0.5, turns=4, lead_frac=0.15)
                                                                
                add_box(n.x, n.y, ground_z - s*0.1, s*1.0, s*1.0, s*0.1, c_link)
                
        elif len(nodes) == 2:
            if not show_2joint_links:
                continue
                                                                    
            nid_i, nid_j = nodes
            
            n_i = nodes_dict.get(nid_i) or nodes_dict.get(str(nid_i))
            n_j = nodes_dict.get(nid_j) or nodes_dict.get(str(nid_j))
            
            if n_i and n_j:
                p1 = np.array([n_i.x, n_i.y, n_i.z])
                p2 = np.array([n_j.x, n_j.y, n_j.z])

                disp_i = node_displacements.get(str(nid_i))
                if disp_i is not None and disp_scale:
                    p1 = p1 + np.array(disp_i[:3]) * disp_scale

                disp_j = node_displacements.get(str(nid_j))
                if disp_j is not None and disp_scale:
                    p2 = p2 + np.array(disp_j[:3]) * disp_scale

                if np.linalg.norm(p2 - p1) < 1e-6: continue

                add_line_spring(p1, p2, c_link, coil_radius=s * 0.6)

    mesh_item = None
    if mesh_verts:
        mesh_item = gl.GLMeshItem(
            vertexes=np.array(mesh_verts, dtype=np.float32),
            faces=np.array(mesh_faces, dtype=np.int32),
            vertexColors=np.array(mesh_colors, dtype=np.float32),
            smooth=False, shader='balloon', glOptions='opaque'
        )

    line_item = None
    if line_verts:
        line_item = gl.GLLinePlotItem(
            pos=np.array(line_verts, dtype=np.float32), 
            color=np.array(line_colors, dtype=np.float32), 
            mode='lines', width=1.75, antialias=True
        )

    return mesh_item, line_item
