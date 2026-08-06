"""
section_worker.py
-----------------
Background QRunnable for off-thread arbitrary section FEM analysis.
Uses Gmsh to generate a true 2D triangular mesh from polygon vertices, 
then solves the Poisson differential equation for exact St. Venant torsion.
"""

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
import gmsh
import sys
import threading

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal

_GMSH_LOCK = threading.Lock()

class SectionWorkerSignals(QObject):
    """Signals for the SectionWorker."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

class SectionWorker(QRunnable):
    """
    Computes exact section properties (Torsion) using a 2D FEM mesh.
    
    Parameters
    ----------
    section_id : str or int
        Unique identifier for the section being processed.
    vertices : list of tuples
        Ordered (y, z) coordinates of the arbitrary polygon in base SI metres.
    mesh_size : float
        Target edge length for the Gmsh triangular elements.
    """
    
    def __init__(self, section_id, vertices, mesh_size=0.02, nu=0.2):
        super().__init__()
        self.signals = SectionWorkerSignals()
        self.section_id = section_id
        self.vertices = list(vertices)
        self.mesh_size = mesh_size
        self.nu = nu

    def run(self):
                                                                              
        with _GMSH_LOCK:
            try:
                                             
                import signal as _signal
                _orig_signal = _signal.signal
                _signal.signal = lambda *a, **kw: None
                
                if not gmsh.isInitialized():
                    gmsh.initialize()
                else:
                    gmsh.clear()                                          
                
                _signal.signal = _orig_signal
                gmsh.option.setNumber("General.Terminal", 0)
                gmsh.model.add(f"Section_FEM_{self.section_id}")

                pt_tags = []
                for (y, z) in self.vertices:
                    pt_tags.append(gmsh.model.occ.addPoint(0.0, y, z))

                line_tags = []
                n_pts = len(pt_tags)
                for i in range(n_pts):
                    line_tags.append(gmsh.model.occ.addLine(pt_tags[i], pt_tags[(i+1) % n_pts]))

                loop_tag = gmsh.model.occ.addCurveLoop(line_tags)
                surf_tag = gmsh.model.occ.addPlaneSurface([loop_tag])
                gmsh.model.occ.synchronize()

                gmsh.option.setNumber("Mesh.CharacteristicLengthMin", self.mesh_size)
                gmsh.option.setNumber("Mesh.CharacteristicLengthMax", self.mesh_size)
                gmsh.option.setNumber("Mesh.ElementOrder", 1)                                              
                gmsh.model.mesh.generate(2)

                node_tags, coords_flat, _ = gmsh.model.mesh.getNodes()
                coords = coords_flat.reshape(-1, 3)
                nodes_yz = coords[:, 1:3]
                
                tag_to_idx = {tag: i for i, tag in enumerate(node_tags)}
                
                elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=2)
                if 2 not in elem_types:                               
                    raise ValueError("No triangular elements generated.")
                    
                type_idx = list(elem_types).index(2)
                tri_tags = elem_node_tags[type_idx].reshape(-1, 3)
                elements = np.array([[tag_to_idx[t] for t in tri] for tri in tri_tags])
                
                bound_types, _, bound_node_tags = gmsh.model.mesh.getElements(dim=1)
                boundary_indices = set()
                if 1 in bound_types:
                    b_idx = list(bound_types).index(1)
                    b_tags = bound_node_tags[b_idx].reshape(-1, 2)
                    for b_line in b_tags:
                        boundary_indices.add(tag_to_idx[b_line[0]])
                        boundary_indices.add(tag_to_idx[b_line[1]])
                
                boundary_indices = list(boundary_indices)

                n_nodes = len(nodes_yz)
                K_data, K_row, K_col = [], [], []
                F = np.zeros(n_nodes)
                
                element_areas = []

                for elem in elements:
                    n1, n2, n3 = elem
                    y1, z1 = nodes_yz[n1]
                    y2, z2 = nodes_yz[n2]
                    y3, z3 = nodes_yz[n3]
                    
                    b1, b2, b3 = z2 - z3, z3 - z1, z1 - z2
                    c1, c2, c3 = y3 - y2, y1 - y3, y2 - y1
                    
                    detJ = b1*c2 - b2*c1
                    area = abs(detJ) / 2.0
                    element_areas.append(area)
                    
                    B = np.array([[b1, b2, b3],
                                  [c1, c2, c3]])
                    ke = (B.T @ B) / (4.0 * area)
                    fe = np.array([1.0, 1.0, 1.0]) * (2.0 * area / 3.0)
                    
                    for i_loc, i_glob in enumerate(elem):
                        F[i_glob] += fe[i_loc]
                        for j_loc, j_glob in enumerate(elem):
                            K_row.append(i_glob)
                            K_col.append(j_glob)
                            K_data.append(ke[i_loc, j_loc])
                            
                K = sp.coo_matrix((K_data, (K_row, K_col)), shape=(n_nodes, n_nodes)).tocsr()
                
                for idx in boundary_indices:
                    r_start = K.indptr[idx]
                    r_end = K.indptr[idx+1]
                    K.data[r_start:r_end] = 0.0
                    K[idx, idx] = 1.0
                    F[idx] = 0.0
                    
                K.eliminate_zeros()

                psi = spla.spsolve(K, F)

                J_exact = 0.0
                for i, elem in enumerate(elements):
                    psi_avg = (psi[elem[0]] + psi[elem[1]] + psi[elem[2]]) / 3.0
                    J_exact += 2.0 * psi_avg * element_areas[i]

                K_neumann = sp.coo_matrix((K_data, (K_row, K_col)), shape=(n_nodes, n_nodes)).tocsr()
                F_omega = np.zeros(n_nodes)

                if 1 in bound_types:
                    b_idx = list(bound_types).index(1)
                    boundary_lines = bound_node_tags[b_idx].reshape(-1, 2)
                    
                    for b_line in boundary_lines:
                        n1 = tag_to_idx[b_line[0]]
                        n2 = tag_to_idx[b_line[1]]
                        
                        y1_b, z1_b = nodes_yz[n1]
                        y2_b, z2_b = nodes_yz[n2]
                        
                        dy = y2_b - y1_b
                        dz = z2_b - z1_b
                        L_edge = np.sqrt(dy**2 + dz**2)
                        
                        if L_edge > 1e-12:
                                                              
                            ny = dz / L_edge
                            nz = -dy / L_edge
                            
                            ym = (y1_b + y2_b) / 2.0
                            zm = (z1_b + z2_b) / 2.0
                            qm = zm * ny - ym * nz
                            
                            nodal_load = qm * (L_edge / 2.0)
                            F_omega[n1] += nodal_load
                            F_omega[n2] += nodal_load

                pin_node = 0
                r_start = K_neumann.indptr[pin_node]
                r_end = K_neumann.indptr[pin_node+1]
                K_neumann.data[r_start:r_end] = 0.0
                K_neumann[pin_node, pin_node] = 1.0
                F_omega[pin_node] = 0.0
                K_neumann.eliminate_zeros()

                omega = spla.spsolve(K_neumann, F_omega)

                I_omega_y = 0.0
                I_omega_z = 0.0
                
                A_mesh, Cy_mesh, Cz_mesh = 0.0, 0.0, 0.0
                Iyy_mesh, Izz_mesh, Iyz_mesh = 0.0, 0.0, 0.0
                
                for i, elem in enumerate(elements):
                    n1, n2, n3 = elem
                    area = element_areas[i]
                    
                    y_avg = (nodes_yz[n1][0] + nodes_yz[n2][0] + nodes_yz[n3][0]) / 3.0
                    z_avg = (nodes_yz[n1][1] + nodes_yz[n2][1] + nodes_yz[n3][1]) / 3.0
                    om_avg = (omega[n1] + omega[n2] + omega[n3]) / 3.0
                    
                    A_mesh += area
                    Cy_mesh += y_avg * area
                    Cz_mesh += z_avg * area
                    
                    Iyy_mesh += (y_avg**2) * area
                    Izz_mesh += (z_avg**2) * area
                    Iyz_mesh += (y_avg * z_avg) * area
                    
                    I_omega_y += om_avg * z_avg * area
                    I_omega_z += om_avg * y_avg * area
                    
                Cy = Cy_mesh / A_mesh
                Cz = Cz_mesh / A_mesh
                Iyy = Iyy_mesh - A_mesh * (Cy**2)
                Izz = Izz_mesh - A_mesh * (Cz**2)
                Iyz = Iyz_mesh - A_mesh * Cy * Cz
                
                I_omega_y_c = I_omega_y - Cy * Cz_mesh
                I_omega_z_c = I_omega_z - Cz * Cy_mesh
                
                denom = (Iyy * Izz - Iyz**2)
                if abs(denom) > 1e-20:
                    y_s = (Iyy * I_omega_y_c - Iyz * I_omega_z_c) / denom
                    z_s = (Iyz * I_omega_y_c - Izz * I_omega_z_c) / denom
                else:
                    y_s, z_s = 0.0, 0.0
                    
                y_sc = Cy + y_s
                z_sc = Cz + z_s

                nu = 0.0  

                denom = (Iyy * Izz - Iyz**2)
                c_val = 1.0 / denom if abs(denom) > 1e-30 else 0.0

                F_psi_y = np.zeros(n_nodes)
                F_psi_z = np.zeros(n_nodes)

                for i, elem in enumerate(elements):
                    n1, n2, n3 = elem
                    area = element_areas[i]

                    y1_c, z1_c = nodes_yz[n1][0] - Cy, nodes_yz[n1][1] - Cz
                    y2_c, z2_c = nodes_yz[n2][0] - Cy, nodes_yz[n2][1] - Cz
                    y3_c, z3_c = nodes_yz[n3][0] - Cy, nodes_yz[n3][1] - Cz

                    y_avg = (y1_c + y2_c + y3_c) / 3.0
                    z_avg = (z1_c + z2_c + z3_c) / 3.0

                    Q_y = 2.0 * (Izz * y_avg - Iyz * z_avg)
                    Q_z = 2.0 * (Iyy * z_avg - Iyz * y_avg)

                    load_y = Q_y * (area / 3.0)
                    load_z = Q_z * (area / 3.0)

                    F_psi_y[n1] -= load_y
                    F_psi_y[n2] -= load_y
                    F_psi_y[n3] -= load_y
                    F_psi_z[n1] -= load_z
                    F_psi_z[n2] -= load_z
                    F_psi_z[n3] -= load_z

                if 1 in bound_types:
                    b_idx = list(bound_types).index(1)
                    boundary_lines = bound_node_tags[b_idx].reshape(-1, 2)

                    for b_line in boundary_lines:
                        n1 = tag_to_idx[b_line[0]]
                        n2 = tag_to_idx[b_line[1]]

                        y1_b, z1_b = nodes_yz[n1]
                        y2_b, z2_b = nodes_yz[n2]

                        dy = y2_b - y1_b
                        dz = z2_b - z1_b
                        L_edge = np.sqrt(dy**2 + dz**2)

                        if L_edge > 1e-12:
                            ny = dz / L_edge
                            nz = -dy / L_edge

                            ym = (y1_b + y2_b) / 2.0 - Cy
                            zm = (z1_b + z2_b) / 2.0 - Cz

                            g_yy = 0.5 * Izz * (ym**2 - zm**2) - Iyz * ym * zm
                            g_yz = Izz * ym * zm - 0.5 * Iyz * (zm**2 - ym**2)
                            g_zy = Iyy * ym * zm - 0.5 * Iyz * (ym**2 - zm**2)
                            g_zz = 0.5 * Iyy * (zm**2 - ym**2) - Iyz * ym * zm

                            q_y = nu * (g_yy * ny + g_yz * nz)
                            q_z = nu * (g_zy * ny + g_zz * nz)

                            load_y = q_y * (L_edge / 2.0)
                            load_z = q_z * (L_edge / 2.0)

                            F_psi_y[n1] += load_y
                            F_psi_y[n2] += load_y
                            F_psi_z[n1] += load_z
                            F_psi_z[n2] += load_z

                F_psi_y[pin_node] = 0.0
                F_psi_z[pin_node] = 0.0

                psi_y = spla.spsolve(K_neumann, F_psi_y)
                psi_z = spla.spsolve(K_neumann, F_psi_z)

                int_yy = 0.0
                int_yz = 0.0
                int_zz = 0.0

                for i, elem in enumerate(elements):
                    n1, n2, n3 = elem
                    area = element_areas[i]

                    y1_c, z1_c = nodes_yz[n1][0] - Cy, nodes_yz[n1][1] - Cz
                    y2_c, z2_c = nodes_yz[n2][0] - Cy, nodes_yz[n2][1] - Cz
                    y3_c, z3_c = nodes_yz[n3][0] - Cy, nodes_yz[n3][1] - Cz

                    b1, b2, b3 = z2_c - z3_c, z3_c - z1_c, z1_c - z2_c
                    c1, c2, c3 = y3_c - y2_c, y1_c - y3_c, y2_c - y1_c

                    dpsi_y_dy = (b1*psi_y[n1] + b2*psi_y[n2] + b3*psi_y[n3]) / (2.0 * area)
                    dpsi_y_dz = (c1*psi_y[n1] + c2*psi_y[n2] + c3*psi_y[n3]) / (2.0 * area)
                    dpsi_z_dy = (b1*psi_z[n1] + b2*psi_z[n2] + b3*psi_z[n3]) / (2.0 * area)
                    dpsi_z_dz = (c1*psi_z[n1] + c2*psi_z[n2] + c3*psi_z[n3]) / (2.0 * area)

                    y_avg = (y1_c + y2_c + y3_c) / 3.0
                    z_avg = (z1_c + z2_c + z3_c) / 3.0

                    g_yy = 0.5 * Izz * (y_avg**2 - z_avg**2) - Iyz * y_avg * z_avg
                    g_yz = Izz * y_avg * z_avg - 0.5 * Iyz * (z_avg**2 - y_avg**2)
                    g_zy = Iyy * y_avg * z_avg - 0.5 * Iyz * (y_avg**2 - z_avg**2)
                    g_zz = 0.5 * Iyy * (z_avg**2 - y_avg**2) - Iyz * y_avg * z_avg

                    beta_yy = dpsi_y_dy - nu * g_yy
                    beta_yz = dpsi_y_dz - nu * g_yz
                    beta_zy = dpsi_z_dy - nu * g_zy
                    beta_zz = dpsi_z_dz - nu * g_zz

                    int_yy += (beta_yy**2 + beta_yz**2) * area
                    int_yz += (beta_yy * beta_zy + beta_yz * beta_zz) * area
                    int_zz += (beta_zy**2 + beta_zz**2) * area

                factor = (c_val**2 * A_mesh) / (4.0 * (1.0 + nu)**2)
                alpha_yy = factor * int_yy
                alpha_zz = factor * int_zz

                J_exact = max(J_exact, 1e-12)
                
                Asy_computed = A_mesh / alpha_yy if alpha_yy > 1e-20 else 0.0
                Asz_computed = A_mesh / alpha_zz if alpha_zz > 1e-20 else 0.0

                Asy_exact = min(Asy_computed, A_mesh)
                Asz_exact = min(Asz_computed, A_mesh)

                Asy_exact = Asy_exact if Asy_exact > 1e-12 else (5.0 / 6.0) * A_mesh
                Asz_exact = Asz_exact if Asz_exact > 1e-12 else (5.0 / 6.0) * A_mesh

                result = {
                    'section_id': self.section_id,
                    'J_exact': J_exact,
                    'Asy': Asy_exact,
                    'Asz': Asz_exact,
                    'total_area': A_mesh,
                    'mesh_node_count': n_nodes,
                    'mesh_element_count': len(elements)
                }
                
                self.signals.finished.emit(result)

            except Exception as e:
                                                                  
                if gmsh.isInitialized():
                    gmsh.finalize()
                self.signals.error.emit(str(e))
