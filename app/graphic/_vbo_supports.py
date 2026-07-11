import numpy as np
import pyqtgraph.opengl as gl

def build_spring_visuals(nodes_dict, scale=1.0):
    """
    Generates directional 3D spirals based on the 6x6 spring matrix.
    - Translational: Stretches along the axis (Green)
    - Rotational: Flat expanding spiral around the axis (Gold/Orange)
    """
    verts = []
    colors = []
    
    c_trans = [0.2, 0.8, 0.2, 1.0]                            
    c_rot = [0.9, 0.6, 0.1, 1.0]                              
    
    turns = 3
    pts_per_turn = 12
    base_radius = 0.2 * scale
    height = 0.8 * scale

    for n_id, node in nodes_dict.items():
        k = getattr(node, 'spring_matrix', None)
        if k is None:
            continue
            
        base_pt = np.array([node.x, node.y, node.z])
        
        has_ux = abs(k[0, 0]) > 1e-6
        has_uy = abs(k[1, 1]) > 1e-6
        has_uz = abs(k[2, 2]) > 1e-6
        has_rx = abs(k[3, 3]) > 1e-6
        has_ry = abs(k[4, 4]) > 1e-6
        has_rz = abs(k[5, 5]) > 1e-6

        def add_spring(axis_vec, is_rotational):
            """Helper to generate the spiral geometry along a specific vector"""
            c = c_rot if is_rotational else c_trans
            prev_pt = base_pt.copy()
            
            if np.allclose(np.abs(axis_vec), [0, 0, 1]):
                u, v = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
            elif np.allclose(np.abs(axis_vec), [0, 1, 0]):
                u, v = np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])
            else:         
                u, v = np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])

            for i in range(1, turns * pts_per_turn + 1):
                t = i / (turns * pts_per_turn)
                angle = t * turns * 2 * np.pi
                
                if is_rotational:
                                                                    
                    r = base_radius * (0.5 + t) 
                    h_offset = axis_vec * (height * 0.1 * t)                        
                else:
                                                                       
                    r = base_radius
                    h_offset = axis_vec * (height * t)
                
                curr_pt = base_pt + (r * np.cos(angle) * u) + (r * np.sin(angle) * v) + h_offset
                
                verts.append(prev_pt)
                verts.append(curr_pt)
                colors.append(c)
                colors.append(c)
                
                prev_pt = curr_pt

        if has_ux: add_spring(np.array([-1.0, 0.0, 0.0]), False)
        if has_uy: add_spring(np.array([0.0, -1.0, 0.0]), False)
        if has_uz: add_spring(np.array([0.0, 0.0, -1.0]), False)

        if has_rx: add_spring(np.array([1.0, 0.0, 0.0]), True)
        if has_ry: add_spring(np.array([0.0, 1.0, 0.0]), True)
        if has_rz: add_spring(np.array([0.0, 0.0, 1.0]), True)

    if not verts:
        return None

    pos_array = np.array(verts, dtype=np.float32)
    color_array = np.array(colors, dtype=np.float32)
    
    return gl.GLLinePlotItem(pos=pos_array, color=color_array, mode='lines', width=2.0, antialias=True)
