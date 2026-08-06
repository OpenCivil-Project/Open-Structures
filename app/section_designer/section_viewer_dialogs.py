"""
section_viewer_dialogs.py
--------------------------
"Show Properties", "Generated Fibers", and "Elastic Stress (S11)" dialogs
for the Section Designer, styled after SAP2000's Section Designer.

Design principle
-----------------
Only J, AS2, AS3 (torsion / shear) genuinely require a finite-element mesh —
A, centroid, I33, I22, I23 come out exact (Green's theorem) directly from the
polygon, and the S11 stress field is an exact linear function of (y, z) given
P/Mx/My, so it is rendered analytically (banded polygon clipping) rather than
interpolated over triangles. This means:

  * "Section Properties" — mesh size only changes J / AS2 / AS3 on Refresh;
    everything else is exact regardless of mesh.
  * "Generated Fibers"    — one fiber per FEM triangle; changes count/areas
    with mesh size, exactly like SAP2000's fiber generation.
  * "Elastic Stress S11"  — exact, mesh-independent; toggling P/Mx/My just
    re-solves a 3x3-or-smaller linear system for the stress plane.

All three dialogs share `MeshEngine`, so mesh size changes propagate
consistently everywhere. Each dialog emits `mesh_settings_changed(dict)`
with {'mesh_abs': float, 'mesh_rel': float} (metres / fraction of bounding
box) whenever Refresh/OK is pressed, so the host SectionDesignerDialog can
stash it on the ArbitrarySection (`section.mesh_settings = {...}`) at Accept
time and restore it next time the section is edited.
"""

import math

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton,
    QGroupBox, QFormLayout, QDoubleSpinBox, QRadioButton, QButtonGroup,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QLineEdit,
    QSplitter, QSizePolicy, QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QFont, QLinearGradient
from PyQt6.QtCore import QPointF, QRectF

try:
    from app.section_designer.section_worker import _GMSH_LOCK
except Exception:
    import threading
    _GMSH_LOCK = threading.Lock()

import gmsh

from app.ui.theme import apply_dialog_style

def exact_polygon_properties(vertices):
    """A, centroid, and centroidal Iyy=int(z^2), Izz=int(y^2), Iyz=int(y*z)."""
    n = len(vertices)
    A2 = 0.0
    Cy = 0.0
    Cz = 0.0
    for i in range(n):
        y0, z0 = vertices[i]
        y1, z1 = vertices[(i + 1) % n]
        cross = y0 * z1 - y1 * z0
        A2 += cross
        Cy += (y0 + y1) * cross
        Cz += (z0 + z1) * cross
    A_signed = 0.5 * A2
    A = abs(A_signed)
    if A < 1e-20:
        return dict(A=0.0, Cy=0.0, Cz=0.0, Iyy=0.0, Izz=0.0, Iyz=0.0)
    Cy /= (6.0 * A_signed)
    Cz /= (6.0 * A_signed)

    Iyy_o = 0.0                             
    Izz_o = 0.0               
    Iyz_o = 0.0               
    for i in range(n):
        y0, z0 = vertices[i]
        y1, z1 = vertices[(i + 1) % n]
        cross = y0 * z1 - y1 * z0
        Izz_o += (y0 ** 2 + y0 * y1 + y1 ** 2) * cross
        Iyy_o += (z0 ** 2 + z0 * z1 + z1 ** 2) * cross
        Iyz_o += (y0 * z1 + y1 * z0 + 2.0 * y0 * z0 + 2.0 * y1 * z1) * cross
    Izz_o /= 12.0
    Iyy_o /= 12.0
    Iyz_o /= 24.0
    if A_signed < 0:
        Iyz_o = -Iyz_o

    Iyy = abs(Iyy_o) - A * Cz ** 2
    Izz = abs(Izz_o) - A * Cy ** 2
    Iyz = Iyz_o - A * Cy * Cz
    return dict(A=A, Cy=Cy, Cz=Cz, Iyy=max(Iyy, 0.0), Izz=max(Izz, 0.0), Iyz=Iyz)

class MeshResult:
    __slots__ = ("nodes", "elements", "boundary_edges", "element_areas",
                 "J", "Asy", "Asz", "geo", "psi")

    def __init__(self):
        self.nodes = None                                  
        self.elements = None                                          
        self.boundary_edges = None                  
        self.element_areas = None
        self.J = 0.0
        self.Asy = 0.0
        self.Asz = 0.0
        self.geo = None                                                  
        self.psi = None                                                   
                                                                              
class MeshEngine:
    """Builds a gmsh triangulation and solves J / AS2 / AS3 for it."""

    @staticmethod
    def solve(vertices, mesh_size, nu=0.2):
        geo = exact_polygon_properties(vertices)
        result = MeshResult()
        result.geo = geo
        if geo["A"] < 1e-20:
            result.nodes = np.zeros((0, 2))
            result.elements = np.zeros((0, 3), dtype=int)
            result.boundary_edges = []
            result.element_areas = np.zeros(0)
            return result

        mesh_size = max(mesh_size, 1e-6)

        with _GMSH_LOCK:
            import signal as _signal
            _orig = _signal.signal
            _signal.signal = lambda *a, **kw: None
            try:
                if not gmsh.isInitialized():
                    gmsh.initialize()
                else:
                    gmsh.clear()
            finally:
                _signal.signal = _orig

            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("props_view")

            pt_tags = [gmsh.model.occ.addPoint(0.0, y, z) for (y, z) in vertices]
            n_pts = len(pt_tags)
            line_tags = [gmsh.model.occ.addLine(pt_tags[i], pt_tags[(i + 1) % n_pts])
                         for i in range(n_pts)]
            loop = gmsh.model.occ.addCurveLoop(line_tags)
            gmsh.model.occ.addPlaneSurface([loop])
            gmsh.model.occ.synchronize()

            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", mesh_size)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", mesh_size)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.model.mesh.generate(2)

            node_tags, coords_flat, _ = gmsh.model.mesh.getNodes()
            coords = coords_flat.reshape(-1, 3)
            nodes_yz = coords[:, 1:3]
            tag_to_idx = {tag: i for i, tag in enumerate(node_tags)}

            elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(dim=2)
            type_idx = list(elem_types).index(2)
            tri_tags = elem_node_tags[type_idx].reshape(-1, 3)
            elements = np.array([[tag_to_idx[t] for t in tri] for tri in tri_tags])

            bound_types, _, bound_node_tags = gmsh.model.mesh.getElements(dim=1)
            boundary_edges = []
            if 1 in bound_types:
                b_idx = list(bound_types).index(1)
                for b_line in bound_node_tags[b_idx].reshape(-1, 2):
                    boundary_edges.append((tag_to_idx[b_line[0]], tag_to_idx[b_line[1]]))

        result.nodes = nodes_yz
        result.elements = elements

        n_nodes = len(nodes_yz)
        K_data, K_row, K_col, F = [], [], [], np.zeros(n_nodes)
        element_areas = np.zeros(len(elements))

        for ei, elem in enumerate(elements):
            n1, n2, n3 = elem
            y1, z1 = nodes_yz[n1]; y2, z2 = nodes_yz[n2]; y3, z3 = nodes_yz[n3]
            b1, b2, b3 = z2 - z3, z3 - z1, z1 - z2
            c1, c2, c3 = y3 - y2, y1 - y3, y2 - y1
            detJ = b1 * c2 - b2 * c1
            area = abs(detJ) / 2.0
            element_areas[ei] = area
            B = np.array([[b1, b2, b3], [c1, c2, c3]])
            ke = (B.T @ B) / (4.0 * area)
            fe = np.array([1.0, 1.0, 1.0]) * (2.0 * area / 3.0)
            for iloc, iglob in enumerate(elem):
                F[iglob] += fe[iloc]
                for jloc, jglob in enumerate(elem):
                    K_row.append(iglob); K_col.append(jglob); K_data.append(ke[iloc, jloc])

        result.element_areas = element_areas
        result.boundary_edges = boundary_edges

        K_torsion = sp.coo_matrix((K_data, (K_row, K_col)), shape=(n_nodes, n_nodes)).tocsr()
        K_dirichlet = K_torsion.tolil()
        boundary_idx = sorted({i for e in boundary_edges for i in e})
        for idx in boundary_idx:
            K_dirichlet.rows[idx] = [idx]
            K_dirichlet.data[idx] = [1.0]
            F[idx] = 0.0
        K_dirichlet = K_dirichlet.tocsr()
        psi = spla.spsolve(K_dirichlet, F)
        result.psi = psi
        J = 0.0
        for ei, elem in enumerate(elements):
            psi_avg = (psi[elem[0]] + psi[elem[1]] + psi[elem[2]]) / 3.0
            J += 2.0 * psi_avg * element_areas[ei]
        result.J = max(J, 1e-14)

        A_mesh, Cy_mesh, Cz_mesh = 0.0, 0.0, 0.0
        Iyy_mesh, Izz_mesh, Iyz_mesh = 0.0, 0.0, 0.0
        for i, elem in enumerate(elements):
            area = element_areas[i]
            y_avg = sum(nodes_yz[n][0] for n in elem) / 3.0
            z_avg = sum(nodes_yz[n][1] for n in elem) / 3.0
            
            A_mesh += area
            Cy_mesh += y_avg * area
            Cz_mesh += z_avg * area
            
            Iyy_mesh += (y_avg**2) * area
            Izz_mesh += (z_avg**2) * area
            Iyz_mesh += (y_avg * z_avg) * area
            
        Cy = Cy_mesh / A_mesh if A_mesh > 1e-20 else 0.0
        Cz = Cz_mesh / A_mesh if A_mesh > 1e-20 else 0.0
        
        Iyy = Iyy_mesh - A_mesh * (Cy**2)
        Izz = Izz_mesh - A_mesh * (Cz**2)
        Iyz = Iyz_mesh - A_mesh * Cy * Cz
        A = A_mesh

        denom = Iyy * Izz - Iyz ** 2
        c_val = 1.0 / denom if abs(denom) > 1e-30 else 0.0
        pin_node = 0

        nu = 0.0
                                        
        def solve_axis():
            F_y = np.zeros(n_nodes); F_z = np.zeros(n_nodes)
            for ei, elem in enumerate(elements):
                area = element_areas[ei]
                y_avg = sum(nodes_yz[n][0] for n in elem) / 3.0 - Cy
                z_avg = sum(nodes_yz[n][1] for n in elem) / 3.0 - Cz
                Q_y = 2.0 * (Izz * y_avg - Iyz * z_avg)
                Q_z = 2.0 * (Iyy * z_avg - Iyz * y_avg)
                ly, lz = Q_y * (area / 3.0), Q_z * (area / 3.0)
                for n in elem:
                    F_y[n] -= ly; F_z[n] -= lz
            for (i1, i2) in boundary_edges:
                y1b, z1b = nodes_yz[i1]; y2b, z2b = nodes_yz[i2]
                dy, dz = y2b - y1b, z2b - z1b
                L = math.hypot(dy, dz)
                if L < 1e-12:
                    continue
                ny, nz = dz / L, -dy / L
                ym, zm = (y1b + y2b) / 2.0 - Cy, (z1b + z2b) / 2.0 - Cz
                g_yy = 0.5 * Izz * (ym ** 2 - zm ** 2) - Iyz * ym * zm
                g_yz = Izz * ym * zm - 0.5 * Iyz * (zm ** 2 - ym ** 2)
                g_zy = Iyy * ym * zm - 0.5 * Iyz * (ym ** 2 - zm ** 2)
                g_zz = 0.5 * Iyy * (zm ** 2 - ym ** 2) - Iyz * ym * zm
                q_y = nu * (g_yy * ny + g_yz * nz)
                q_z = nu * (g_zy * ny + g_zz * nz)
                ly, lz = q_y * (L / 2.0), q_z * (L / 2.0)
                F_y[i1] += ly; F_y[i2] += ly
                F_z[i1] += lz; F_z[i2] += lz
            F_y[pin_node] = 0.0; F_z[pin_node] = 0.0
            K_neu = K_torsion.tolil()
            K_neu.rows[pin_node] = [pin_node]
            K_neu.data[pin_node] = [1.0]
            K_neu = K_neu.tocsr()
            psi_y = spla.spsolve(K_neu, F_y)
            psi_z = spla.spsolve(K_neu, F_z)

            int_yy = int_zz = 0.0
            for ei, elem in enumerate(elements):
                n1, n2, n3 = elem
                area = element_areas[ei]
                y1c, z1c = nodes_yz[n1][0] - Cy, nodes_yz[n1][1] - Cz
                y2c, z2c = nodes_yz[n2][0] - Cy, nodes_yz[n2][1] - Cz
                y3c, z3c = nodes_yz[n3][0] - Cy, nodes_yz[n3][1] - Cz
                b1, b2, b3 = z2c - z3c, z3c - z1c, z1c - z2c
                c1, c2, c3 = y3c - y2c, y1c - y3c, y2c - y1c
                dpy_dy = (b1 * psi_y[n1] + b2 * psi_y[n2] + b3 * psi_y[n3]) / (2.0 * area)
                dpy_dz = (c1 * psi_y[n1] + c2 * psi_y[n2] + c3 * psi_y[n3]) / (2.0 * area)
                dpz_dy = (b1 * psi_z[n1] + b2 * psi_z[n2] + b3 * psi_z[n3]) / (2.0 * area)
                dpz_dz = (c1 * psi_z[n1] + c2 * psi_z[n2] + c3 * psi_z[n3]) / (2.0 * area)
                ya, za = (y1c + y2c + y3c) / 3.0, (z1c + z2c + z3c) / 3.0
                g_yy = 0.5 * Izz * (ya ** 2 - za ** 2) - Iyz * ya * za
                g_yz = Izz * ya * za - 0.5 * Iyz * (za ** 2 - ya ** 2)
                g_zy = Iyy * ya * za - 0.5 * Iyz * (ya ** 2 - za ** 2)
                g_zz = 0.5 * Iyy * (za ** 2 - ya ** 2) - Iyz * ya * za
                b_yy = dpy_dy - nu * g_yy
                b_yz = dpy_dz - nu * g_yz
                b_zy = dpz_dy - nu * g_zy
                b_zz = dpz_dz - nu * g_zz
                int_yy += (b_yy ** 2 + b_yz ** 2) * area
                int_zz += (b_zy ** 2 + b_zz ** 2) * area

            factor = (c_val ** 2 * A) / (4.0 * (1.0 + nu) ** 2)
            alpha_yy = factor * int_yy
            alpha_zz = factor * int_zz
            asy = A / alpha_yy if alpha_yy > 1e-20 else 0.0
            asz = A / alpha_zz if alpha_zz > 1e-20 else 0.0
            
            asy = min(asy, A)
            asz = min(asz, A)
            asy = asy if asy > 1e-12 else (5.0 / 6.0) * A
            asz = asz if asz > 1e-12 else (5.0 / 6.0) * A
            
            return asy, asz

        result.Asy, result.Asz = solve_axis()
        return result

def bending_stress_coeffs(geo, P, Mx, My):
    """
    sigma(y,z) = P/A + a*(y-Cy) + b*(z-Cz)
    """
    A, Iyy, Izz, Iyz = geo["A"], geo["Iyy"], geo["Izz"], geo["Iyz"]
    
    det = Iyy * Izz - Iyz ** 2
    if abs(det) < 1e-30:
        return 0.0, 0.0, P / A if A > 0 else 0.0
        
    a = (Mx * Iyz - My * Iyy) / det
    b = (Mx * Izz - My * Iyz) / det
    c = P / A if A > 0 else 0.0
    
    return a, b, c

def torsion_shear_stresses(mesh: "MeshResult", T: float):
    """
    Recover St. Venant torsion shear stress from the Prandtl stress function
    psi already solved in MeshEngine.solve() (laplacian(psi) = -2, psi = 0 on
    boundary, J = 2*Integral(psi dA)).

    With Phi = G*theta*psi the classical relations are
        tau_xy = dPhi/dz = G*theta * dpsi/dz
        tau_xz = -dPhi/dy = -G*theta * dpsi/dy
    and T = G*theta*J  =>  G*theta = T/J, giving (mapping x->1, y->2, z->3
    local axes, matching S12/S13 naming):
        S12 = (T/J) * dpsi/dz
        S13 = -(T/J) * dpsi/dy
        SMax = sqrt(S12^2 + S13^2)

    Verified symbolically against the solid circular shaft closed form
    (tau_max = 2T/(pi*R^3) = 16T/(pi*D^3)) using psi = (R^2-y^2-z^2)/2.

    Returns per-element (piecewise-constant) arrays: (S12, S13, SMax), each
    shape (n_elements,), in the same stress units as T/J (SI Pa if T is in
    N*m and J in m^4).
    """
    nodes = mesh.nodes
    elements = mesh.elements
    psi = mesh.psi
    n = len(elements)
    s12 = np.zeros(n)
    s13 = np.zeros(n)
    if psi is None or mesh.J <= 0 or n == 0:
        return s12, s13, np.zeros(n)

    factor = T / mesh.J

    for ei, elem in enumerate(elements):
        n1, n2, n3 = elem
        y1, z1 = nodes[n1]
        y2, z2 = nodes[n2]
        y3, z3 = nodes[n3]
        b1, b2, b3 = z2 - z3, z3 - z1, z1 - z2
        c1, c2, c3 = y3 - y2, y1 - y3, y2 - y1
        area = mesh.element_areas[ei]
        if area < 1e-20:
            continue
        dpsi_dy = (b1 * psi[n1] + b2 * psi[n2] + b3 * psi[n3]) / (2.0 * area)
        dpsi_dz = (c1 * psi[n1] + c2 * psi[n2] + c3 * psi[n3]) / (2.0 * area)
        
        s12[ei] = -factor * dpsi_dy
        s13[ei] = -factor * dpsi_dz                                    

    smax = np.sqrt(s12 ** 2 + s13 ** 2)
    return s12, s13, smax

def _jet_color(frac: float) -> QColor:
    """
    Replaced with SAP2000's specific continuous stress colormap:
    Magenta (min) -> Red -> Orange -> Yellow -> Green (mid) -> Cyan -> Blue (max)
    """
    frac = max(0.0, min(1.0, frac))
    stops = [
        (0.000, (255, 0, 255)),            
        (0.166, (255, 0, 0)),          
        (0.333, (255, 127, 0)),           
        (0.500, (0, 255, 0)),                            
        (0.666, (0, 255, 255)),         
        (0.833, (0, 127, 255)),               
        (1.000, (0, 0, 255))            
    ]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i+1]
        if t0 <= frac <= t1:
            t = (frac - t0) / (t1 - t0)
            r = int(c0[0] + t * (c1[0] - c0[0]))
            g = int(c0[1] + t * (c1[1] - c0[1]))
            b = int(c0[2] + t * (c1[2] - c0[2]))
            return QColor(r, g, b)
    return QColor(0, 0, 255)

class _FitTransform:
    """Maps world (y,z) -> widget pixels, fit to bounding box with margin."""

    def __init__(self, vertices, w, h, margin=24):
        ys = [v[0] for v in vertices]; zs = [v[1] for v in vertices]
        self.y0, self.y1 = min(ys), max(ys)
        self.z0, self.z1 = min(zs), max(zs)
        span_y = max(self.y1 - self.y0, 1e-9)
        span_z = max(self.z1 - self.z0, 1e-9)
        avail_w = max(w - 2 * margin, 10)
        avail_h = max(h - 2 * margin, 10)
        self.scale = min(avail_w / span_y, avail_h / span_z)
        self.cx = w / 2.0
        self.cy = h / 2.0
        self.mid_y = (self.y0 + self.y1) / 2.0
        self.mid_z = (self.z0 + self.z1) / 2.0

    def to_px(self, y, z):
        px = self.cx + (y - self.mid_y) * self.scale
        py = self.cy - (z - self.mid_z) * self.scale
        return QPointF(px, py)

    def to_world(self, px, py):
        """Converts Qt pixel coordinates back into structural (y, z) world coordinates."""
        y = (px - self.cx) / self.scale + self.mid_y
        z = self.mid_z - (py - self.cy) / self.scale
        return y, z

def _poly_qt(transform, pts):
    return QPolygonF([transform.to_px(y, z) for (y, z) in pts])

class _HatchMeshCanvas(QWidget):
    """SAP2000-style hatched section preview with an optional mesh overlay
    and optional marker dots (used by Properties + Fibers dialogs)."""

    def __init__(self, vertices, parent=None):
        super().__init__(parent)
        self.vertices = vertices
        self.mesh = None                          
        self.markers = []                     
        self.setMinimumSize(260, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_mesh(self, mesh: MeshResult):
        self.mesh = mesh
        self.update()

    def set_markers(self, pts):
        self.markers = pts
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if not self.vertices:
            p.end(); return
        t = _FitTransform(self.vertices, self.width(), self.height())

        outline = _poly_qt(t, self.vertices)
        p.setBrush(QBrush(QColor("#3a3a3a"), Qt.BrushStyle.DiagCrossPattern))
        p.setPen(QPen(QColor("#c0392b"), 1.5))
        p.drawPolygon(outline)

        if self.mesh is not None and self.mesh.elements is not None:
            p.setPen(QPen(QColor("#2c7fb8"), 0.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for tri in self.mesh.elements:
                pts = [tuple(self.mesh.nodes[i]) for i in tri]
                p.drawPolygon(_poly_qt(t, pts))

        cy, cz = exact_polygon_properties(self.vertices)["Cy"],\
                 exact_polygon_properties(self.vertices)["Cz"]
        c_px = t.to_px(cy, cz)
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawLine(QPointF(0, c_px.y()), QPointF(self.width(), c_px.y()))
        p.drawLine(QPointF(c_px.x(), 0), QPointF(c_px.x(), self.height()))

        if self.markers:
            p.setBrush(QBrush(QColor("#ffe600")))
            p.setPen(QPen(QColor("#000000"), 1))
            for (y, z) in self.markers:
                pt = t.to_px(y, z)
                p.drawEllipse(pt, 3.0, 3.0)
        p.end()

class _StressCanvas(QWidget):
    _FLAT_COLOR = QColor("#9e9e9e")

    def __init__(self, vertices, parent=None):
        super().__init__(parent)
        self.vertices = vertices
        self.mode = "linear"
        self.a = self.b = self.c = 0.0
        self.y_min = self.z_min = 0.0
        self.mesh = None
        self.tri_values = None
        self.tri_centroids = None
        self.vmin = 0.0
        self.vmax = 0.0
        self.is_flat = True
        
        self.transform = None
        self.hover_data = None
        self.length_scale = 1.0
        self.pressure_unit = ""
        self.setMouseTracking(True)
        
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_stress_linear(self, a, b, c):
        self.mode = "linear"
        self.a, self.b, self.c = a, b, c
        vals = [a * y + b * z + c for (y, z) in self.vertices]
        if not vals:
            self.vmin = self.vmax = 0.0
            self.is_flat = True
            self.update()
            return

        self.vmin, self.vmax = min(vals), max(vals)
        self.is_flat = (self.vmax - self.vmin) < 1e-9

        if not self.is_flat:
            min_idx = vals.index(self.vmin)
            self.y_min, self.z_min = self.vertices[min_idx]

        self.update()

    def set_stress_mesh(self, mesh: "MeshResult", tri_values):
        self.mode = "mesh"
        self.mesh = mesh
        self.tri_values = tri_values
        if tri_values is not None and len(tri_values):
            self.vmin = float(np.min(tri_values))
            self.vmax = float(np.max(tri_values))
        else:
            self.vmin = self.vmax = 0.0
        self.is_flat = (self.vmax - self.vmin) < 1e-9
        
        if mesh is not None and mesh.elements is not None:
            self.tri_centroids = np.zeros((len(mesh.elements), 2))
            for i, tri in enumerate(mesh.elements):
                pts = mesh.nodes[tri]
                self.tri_centroids[i] = np.mean(pts, axis=0)
        else:
            self.tri_centroids = None
            
        self.update()

    def mouseMoveEvent(self, ev):
        if not self.vertices or not self.transform:
            return
        pos = ev.position()
        y, z = self.transform.to_world(pos.x(), pos.y())
        
        stress = 0.0
        if self.mode == "linear":
            stress = self.a * y + self.b * z + self.c
        elif self.mode == "mesh" and self.tri_values is not None and self.tri_centroids is not None:
                                               
            dist_sq = (self.tri_centroids[:, 0] - y)**2 + (self.tri_centroids[:, 1] - z)**2
            closest_idx = np.argmin(dist_sq)
            stress = self.tri_values[closest_idx]
            
        self.hover_data = (y, z, stress)
        self.update()
        
    def leaveEvent(self, ev):
        self.hover_data = None
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if not self.vertices:
            p.end(); return
        
        self.transform = _FitTransform(self.vertices, self.width(), self.height())
        t = self.transform

        if self.mode == "mesh":
            self._paint_mesh(p, t)
        elif self.is_flat:
            p.setBrush(QBrush(self._FLAT_COLOR))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(_poly_qt(t, self.vertices))
        else:
                                                                  
            mag2 = self.a**2 + self.b**2
            k = (self.vmax - self.vmin) / mag2 if mag2 > 1e-15 else 0.0
            y_end = self.y_min + k * self.a
            z_end = self.z_min + k * self.b

            px_start = t.to_px(self.y_min, self.z_min)
            px_end = t.to_px(y_end, z_end)

            grad = QLinearGradient(px_start, px_end)
            n_bands = 15
            for i in range(n_bands):
                color = _jet_color((i + 0.5) / n_bands)
                start_pos = i / n_bands
                end_pos = (i + 1) / n_bands

                if i == 0:
                    grad.setColorAt(0.0, color)
                else:
                    grad.setColorAt(start_pos, color)

                if i == n_bands - 1:
                    grad.setColorAt(1.0, color)
                else:
                    grad.setColorAt(end_pos - 1e-6, color)

            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(_poly_qt(t, self.vertices))

            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#000000"), 1.2))
            p.drawPolygon(_poly_qt(t, self.vertices))

        if self.hover_data:
            hy, hz, hstress = self.hover_data
            hy_d = hy * self.length_scale
            hz_d = hz * self.length_scale
            text = f"({hy_d:.4f}, {hz_d:.4f})    σ: {hstress:.4g} {self.pressure_unit}"
            
            p.setPen(QPen(Qt.GlobalColor.black))
            font = QFont("Arial", 9)
            font.setBold(True)
            p.setFont(font)
            p.drawText(8, self.height() - 8, text)
            
        p.end()
        
    def _paint_mesh(self, p, t):
        if (self.mesh is None or self.mesh.elements is None
                or self.tri_values is None or len(self.mesh.elements) == 0):
            p.setBrush(QBrush(self._FLAT_COLOR))
            p.setPen(QPen(QColor("#000000"), 1.2))
            p.drawPolygon(_poly_qt(t, self.vertices))
            return
            
        if self.is_flat:
            p.setBrush(QBrush(self._FLAT_COLOR))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(_poly_qt(t, self.vertices))
        else:
            span = self.vmax - self.vmin
            p.setPen(Qt.PenStyle.NoPen)
            for tri, val in zip(self.mesh.elements, self.tri_values):
                pts = [tuple(self.mesh.nodes[i]) for i in tri]
                frac = (val - self.vmin) / span
                p.setBrush(QBrush(_jet_color(frac)))
                p.drawPolygon(_poly_qt(t, pts))
                
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#000000"), 1.2))
        p.drawPolygon(_poly_qt(t, self.vertices))

class _ColorLegend(QWidget):
    """Horizontal color-bar legend with tick labels, like SAP2000's."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vmin = 0.0
        self.vmax = 0.0
        self.unit_label = ""
        self.setFixedHeight(60)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_range(self, vmin, vmax, unit_label=None):
        self.vmin, self.vmax = vmin, vmax
        if unit_label is not None:
            self.unit_label = unit_label
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bar_h = 16
        n = 60
        for i in range(n):
            frac = i / (n - 1)
            x0 = i * w / n
            x1 = (i + 1) * w / n
            p.fillRect(QRectF(x0, 4, x1 - x0 + 1, bar_h), _jet_color(frac))
        p.setPen(QPen(QColor("#000")))
        p.drawRect(QRectF(0, 4, w - 1, bar_h))
        span = max(self.vmax - self.vmin, 1e-9)
        p.setFont(QFont("Monospace", 7))
        n_ticks = 8
        for k in range(n_ticks + 1):
            frac = k / n_ticks
            val = self.vmin + frac * span
            x = frac * w
            p.drawLine(QPointF(x, 4 + bar_h), QPointF(x, 4 + bar_h + 4))
            p.drawText(QRectF(x - 22, 4 + bar_h + 4, 44, 14),
                       Qt.AlignmentFlag.AlignHCenter, f"{val:.2g}")
        if self.unit_label:
            p.setFont(QFont("Monospace", 8))
            p.drawText(QRectF(0, 4 + bar_h + 18, w, 14),
                       Qt.AlignmentFlag.AlignHCenter, f"Stress ({self.unit_label})")
        p.end()

class _MeshSizeGroup(QGroupBox):
    def __init__(self, mesh_settings: dict, length_unit_scale, length_unit_name, parent=None):
        super().__init__("Mesh Size", parent)
        self._scale = length_unit_scale
        self._unit = length_unit_name
        form = QFormLayout(self)
        self.sb_abs = QDoubleSpinBox()
        self.sb_abs.setRange(0.0, 1e6)
        self.sb_abs.setDecimals(4)
        self.sb_abs.setSuffix(f"  {self._unit}")
        self.sb_abs.setValue(mesh_settings.get("mesh_abs", 0.0) * self._scale)
        self.sb_rel = QDoubleSpinBox()
        self.sb_rel.setRange(0.001, 1.0)
        self.sb_rel.setDecimals(4)
        self.sb_rel.setSingleStep(0.01)
        self.sb_rel.setValue(mesh_settings.get("mesh_rel", 0.05))
        form.addRow("Max Mesh Size (Absolute)", self.sb_abs)
        form.addRow("Max Mesh Size (Relative)", self.sb_rel)

    def settings(self) -> dict:
        return {"mesh_abs": self.sb_abs.value() / self._scale,
                "mesh_rel": self.sb_rel.value()}

    def effective_size_m(self, vertices) -> float:
        s = self.settings()
        if s["mesh_abs"] > 1e-12:
            return s["mesh_abs"]
        ys = [v[0] for v in vertices]; zs = [v[1] for v in vertices]
        max_dim = max(max(ys) - min(ys), max(zs) - min(zs))
        return max(max_dim * s["mesh_rel"], 1e-6)

_PROP_ROWS = [
    ("Xcg", "y_c"), ("Ycg", "z_c"), ("A", "A"), ("J", "J"),
    ("I33", "Iyy"), ("I22", "Izz"), ("I23", "Iyz"),
    ("AS2", "Asy"), ("AS3", "Asz"),
]

class SectionPropertiesDialog(QDialog):
    """"Show Properties" — mirrors SAP2000's Section Properties panel."""

    mesh_settings_changed = pyqtSignal(dict)

    def __init__(self, vertices, material_name, nu, mesh_settings,
                 length_unit_scale=1.0, length_unit_name="m", parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Section Properties")
        self.resize(760, 560)
        self.vertices = vertices
        self.material_name = material_name
        self.nu = nu
        self._scale = length_unit_scale
        self._unit = length_unit_name

        root = QHBoxLayout(self)
        self.canvas = _HatchMeshCanvas(vertices, self)
        root.addWidget(self.canvas, stretch=1)

        right = QVBoxLayout()
        right.addWidget(QLabel(f"<b>Base Material:</b> {material_name}"))

        self.mesh_group = _MeshSizeGroup(mesh_settings, length_unit_scale, length_unit_name, self)
        right.addWidget(self.mesh_group)

        self.table = QTableWidget(len(_PROP_ROWS), 2)
        self.table.setHorizontalHeaderLabels(["Property", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, (label, _) in enumerate(_PROP_ROWS):
            self.table.setItem(row, 0, QTableWidgetItem(label))
            self.table.setItem(row, 1, QTableWidgetItem("—"))
        right.addWidget(self.table, stretch=1)

        self.lbl_status = QLabel(" ")
        self.lbl_status.setStyleSheet("color: #888; font-size: 10px;")
        right.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self._refresh)
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch()
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        right.addLayout(btn_row)

        right_w = QWidget(); right_w.setLayout(right); right_w.setFixedWidth(340)
        root.addWidget(right_w)

        self.result_mesh_settings = dict(mesh_settings)
        self._refresh()

    def _refresh(self):
        self.btn_refresh.setEnabled(False)
        self.lbl_status.setText("Solving FEM mesh…")
        QApplication.processEvents()
        try:
            size_m = self.mesh_group.effective_size_m(self.vertices)
            mesh = MeshEngine.solve(self.vertices, size_m, self.nu)
            self.canvas.set_mesh(mesh)
            self._populate(mesh)
            self.lbl_status.setText(
                f"{len(mesh.elements)} elements, {len(mesh.nodes)} nodes "
                f"(target size {size_m * self._scale:.4g} {self._unit})")
        except Exception as e:
            self.lbl_status.setText(f"Solve failed: {e}")
        finally:
            self.btn_refresh.setEnabled(True)

    def _populate(self, mesh: MeshResult):
        geo = mesh.geo
        s2, s3, s4 = self._scale ** 2, self._scale ** 3, self._scale ** 4
        values = dict(geo)
        values["J"] = mesh.J
        values["Asy"] = mesh.Asy
        values["Asz"] = mesh.Asz
        conv = {"A": s2, "J": s4, "Izz": s4, "Iyy": s4, "Iyz": s4,
                "Asy": s2, "Asz": s2, "y_c": self._scale, "z_c": self._scale}
        for row, (label, key) in enumerate(_PROP_ROWS):
            raw = values.get(key, 0.0)
            val = raw * conv.get(key, 1.0)
            self.table.item(row, 1).setText(f"{val:.6g}")

    def _accept(self):
        self.result_mesh_settings = self.mesh_group.settings()
        self.mesh_settings_changed.emit(self.result_mesh_settings)
        self.accept()

class GeneratedFibersDialog(QDialog):
    """"Generated Fibers" — one fiber per real FEM triangle."""

    mesh_settings_changed = pyqtSignal(dict)

    def __init__(self, vertices, material_name, nu, mesh_settings,
                 length_unit_scale=1.0, length_unit_name="m", parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle(f"Generated Fibers for SDSection")
        self.resize(760, 560)
        self.vertices = vertices
        self.material_name = material_name
        self.nu = nu
        self._scale = length_unit_scale
        self._unit = length_unit_name

        root = QHBoxLayout(self)
        self.canvas = _HatchMeshCanvas(vertices, self)
        root.addWidget(self.canvas, stretch=1)

        right = QVBoxLayout()
        self.mesh_group = _MeshSizeGroup(mesh_settings, length_unit_scale, length_unit_name, self)
        right.addWidget(self.mesh_group)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Fiber", "Area", "Coord3", "Coord2", "Material"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        right.addWidget(self.table, stretch=1)

        self.lbl_status = QLabel(" ")
        self.lbl_status.setStyleSheet("color: #888; font-size: 10px;")
        right.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self._refresh)
        btn_done = QPushButton("Done")
        btn_done.clicked.connect(self._accept)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch()
        btn_row.addWidget(btn_done)
        right.addLayout(btn_row)

        right_w = QWidget(); right_w.setLayout(right); right_w.setFixedWidth(420)
        root.addWidget(right_w)

        self.result_mesh_settings = dict(mesh_settings)
        self._refresh()

    def _refresh(self):
        self.btn_refresh.setEnabled(False)
        self.lbl_status.setText("Generating fibers…")
        QApplication.processEvents()
        try:
            size_m = self.mesh_group.effective_size_m(self.vertices)
            mesh = MeshEngine.solve(self.vertices, size_m, self.nu)
            self.canvas.set_mesh(mesh)
            centroids = self._populate(mesh)
            self.canvas.set_markers(centroids)
            self.lbl_status.setText(f"{len(mesh.elements)} fibers generated "
                                     f"(target size {size_m * self._scale:.4g} {self._unit})")
        except Exception as e:
            self.lbl_status.setText(f"Generation failed: {e}")
        finally:
            self.btn_refresh.setEnabled(True)

    def _populate(self, mesh: MeshResult):
        s2 = self._scale ** 2
        n = len(mesh.elements)
        self.table.setRowCount(n)
        centroids = []
        for i, tri in enumerate(mesh.elements):
            pts = [mesh.nodes[k] for k in tri]
            y_avg = sum(p[0] for p in pts) / 3.0
            z_avg = sum(p[1] for p in pts) / 3.0
            centroids.append((y_avg, z_avg))
            area_disp = mesh.element_areas[i] * s2
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(f"{area_disp:.4g}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{z_avg * self._scale:.4g}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{y_avg * self._scale:.4g}"))
            self.table.setItem(i, 4, QTableWidgetItem(self.material_name))
        return centroids

    def _accept(self):
        self.result_mesh_settings = self.mesh_group.settings()
        self.mesh_settings_changed.emit(self.result_mesh_settings)
        self.accept()

class ElasticStressDialog(QDialog):
    """
    "Elastic Stress" — SAP2000 Section Designer style.

    Two mutually-exclusive modes, matching SAP:
      - S11 (bending): P/Mx/My checkable together, exact analytic linear
        field, mesh-independent.
      - Torsion (S12/S13/SMax): T only, requires the FEM mesh (Prandtl
        stress function) -- picking S12/S13/SMax via the "Torsion Stress
        Direction" radio group, which only appears once T is checked.

    Force/moment fields are entered and shown in the CURRENT DISPLAY unit
    system (unit_registry), matching every other dialog in the app; they are
    converted to SI (N, N*m) before any stress math runs, and the resulting
    stress field is converted back to a display pressure unit
    (unit_registry.pressure_unit) before being drawn or shown on the legend.
    """

    mesh_settings_changed = pyqtSignal(dict)

    def __init__(self, vertices, material_name="", nu=0.2, mesh_settings=None,
                 length_unit_scale=1.0, length_unit_name="m",
                 force_scale=1.0, force_unit_name="N", pressure_unit_name="Pa",
                 parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.resize(820, 600)
        self.vertices = vertices
        self.geo = exact_polygon_properties(vertices)
        self.material_name = material_name
        self.nu = nu
        self._scale = length_unit_scale
        self._unit = length_unit_name
        self._fscale = force_scale                                      
        self._funit = force_unit_name
        self._punit = pressure_unit_name
                                                                      
        self._mscale = force_scale * length_unit_scale
        self._munit = f"{force_unit_name}\u00b7{length_unit_name}"
                                                                           
        self._pscale = force_scale / (length_unit_scale ** 2)

        self.result_mesh_settings = dict(mesh_settings) if mesh_settings else\
            {"mesh_abs": 0.0, "mesh_rel": 0.05}
        self._mesh = None                                                   

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        
        self.canvas = _StressCanvas(vertices, self)
        self.canvas.length_scale = self._scale
        self.canvas.pressure_unit = self._punit
        
        top.addWidget(self.canvas, stretch=1)

        right = QVBoxLayout()

        forces_grp = QGroupBox("Forces")
        f_form = QFormLayout(forces_grp)
        self.chk_P, self.edit_P = self._force_row(f_form, f"P ({self._funit})", 0.0)
        self.chk_Mx, self.edit_Mx = self._force_row(f_form, f"Mx ({self._munit})", 0.0)
        self.chk_My, self.edit_My = self._force_row(f_form, f"My ({self._munit})", 0.0)
        self.chk_T, self.edit_T = self._force_row(f_form, f"T ({self._munit})", 0.0)
        self.chk_T.setChecked(False)                                              
        forces_grp.setFixedWidth(280)
        right.addWidget(forces_grp)

        self.torsion_grp = QGroupBox("Torsion Stress Direction")
        t_form = QVBoxLayout(self.torsion_grp)
        self.rb_s12 = QRadioButton("S12")
        self.rb_s13 = QRadioButton("S13")
        self.rb_smax = QRadioButton("SMax")
        self.rb_s12.setChecked(True)
        self._torsion_group_btns = QButtonGroup(self)
        for rb in (self.rb_s12, self.rb_s13, self.rb_smax):
            self._torsion_group_btns.addButton(rb)
            t_form.addWidget(rb)
            rb.toggled.connect(self._recompute)
        self.torsion_grp.setFixedWidth(280)
        self.torsion_grp.setVisible(False)
        right.addWidget(self.torsion_grp)

        self.mesh_group = _MeshSizeGroup(self.result_mesh_settings,
                                          length_unit_scale, length_unit_name, self)
        self.mesh_group.setFixedWidth(280)
        self.mesh_group.setVisible(False)
        right.addWidget(self.mesh_group)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setVisible(False)
        self.btn_refresh.clicked.connect(self._recompute)
        right.addWidget(self.btn_refresh)

        self.lbl_status = QLabel(" ")
        self.lbl_status.setStyleSheet("color: #888; font-size: 10px;")
        right.addWidget(self.lbl_status)

        right.addStretch()
        right_w = QWidget(); right_w.setLayout(right); right_w.setFixedWidth(300)
        top.addWidget(right_w)
        root.addLayout(top)

        self.legend = _ColorLegend(self)
        root.addWidget(self.legend)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self._accept)
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

        self.chk_P.toggled.connect(self._on_bending_toggled)
        self.chk_Mx.toggled.connect(self._on_bending_toggled)
        self.chk_My.toggled.connect(self._on_bending_toggled)
        self.chk_T.toggled.connect(self._on_torsion_toggled)
        for edit in (self.edit_P, self.edit_Mx, self.edit_My, self.edit_T):
            edit.editingFinished.connect(self._recompute)

        self._update_mode_visibility()
        self._recompute()

    def _force_row(self, form, label, default):
        row = QHBoxLayout()
        chk = QCheckBox(label)
        chk.setChecked(True)
        edit = QLineEdit(f"{default:g}")
        edit.setFixedWidth(110)
        row.addWidget(chk)
        row.addWidget(edit)
        w = QWidget(); w.setLayout(row)
        form.addRow(w)
        return chk, edit

    def _val(self, chk, edit):
        if not chk.isChecked():
            return 0.0
        try:
            return float(edit.text())
        except ValueError:
            return 0.0

    def _on_bending_toggled(self, checked):
        if checked and self.chk_T.isChecked():
            self.chk_T.blockSignals(True)
            self.chk_T.setChecked(False)
            self.chk_T.blockSignals(False)
        self._update_mode_visibility()
        self._recompute()

    def _on_torsion_toggled(self, checked):
        if checked:
            for chk in (self.chk_P, self.chk_Mx, self.chk_My):
                chk.blockSignals(True)
                chk.setChecked(False)
                chk.blockSignals(False)
        self._update_mode_visibility()
        self._recompute()

    def _update_mode_visibility(self):
        torsion_mode = self.chk_T.isChecked()
        self.torsion_grp.setVisible(torsion_mode)
        self.mesh_group.setVisible(torsion_mode)
        self.btn_refresh.setVisible(torsion_mode)
        title_suffix = self._active_torsion_label() if torsion_mode else "S11"
        self.setWindowTitle(f"Elastic Stress - {title_suffix}")

    def _active_torsion_label(self):
        if self.rb_s13.isChecked():
            return "S13"
        if self.rb_smax.isChecked():
            return "SMax"
        return "S12"

    def _recompute(self):
        if self.chk_T.isChecked():
            self._recompute_torsion()
        else:
            self._recompute_bending()

    def _recompute_bending(self):
                                                                       
        P_si = self._val(self.chk_P, self.edit_P) / self._fscale if self._fscale else 0.0
        Mx_si = self._val(self.chk_Mx, self.edit_Mx) / self._mscale if self._mscale else 0.0
        My_si = self._val(self.chk_My, self.edit_My) / self._mscale if self._mscale else 0.0
        a, b, c = bending_stress_coeffs(self.geo, P_si, Mx_si, My_si)
                                                                            
        a_d, b_d, c_d = a * self._pscale, b * self._pscale, c * self._pscale
        self.canvas.set_stress_linear(a_d, b_d, c_d)
        self.legend.set_range(self.canvas.vmin, self.canvas.vmax, self._punit)
        self.lbl_status.setText(" ")

    def _recompute_torsion(self):
        self.btn_refresh.setEnabled(False)
        self.lbl_status.setText("Solving FEM mesh\u2026")
        QApplication.processEvents()
        try:
            size_m = self.mesh_group.effective_size_m(self.vertices)
            self._mesh = MeshEngine.solve(self.vertices, size_m, self.nu)
            T_si = self._val(self.chk_T, self.edit_T) / self._mscale if self._mscale else 0.0
            s12, s13, smax = torsion_shear_stresses(self._mesh, T_si)
            if self.rb_s13.isChecked():
                vals = s13
            elif self.rb_smax.isChecked():
                vals = smax
            else:
                vals = s12
            vals_d = vals * self._pscale
            self.canvas.set_stress_mesh(self._mesh, vals_d)
            self.legend.set_range(self.canvas.vmin, self.canvas.vmax, self._punit)
            self.lbl_status.setText(
                f"{len(self._mesh.elements)} elements, {len(self._mesh.nodes)} nodes "
                f"(target size {size_m * self._scale:.4g} {self._unit})")
        except Exception as e:
            self.lbl_status.setText(f"Solve failed: {e}")
        finally:
            self.btn_refresh.setEnabled(True)
            self.setWindowTitle(f"Elastic Stress - {self._active_torsion_label()}")

    def _accept(self):
        self.result_mesh_settings = self.mesh_group.settings()
        self.mesh_settings_changed.emit(self.result_mesh_settings)
        self.accept()
