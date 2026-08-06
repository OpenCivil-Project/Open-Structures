"""
section_analyzer.py
-------------------
Pure geometry/math — no Qt, no app imports.

Computes structural section properties from an arbitrary closed polygon
using the Shoelace formula (area) and Green's theorem (moments of inertia).

All inputs and outputs are in BASE SI units (metres, Newtons).
The dialog is responsible for converting display units ↔ SI before calling here.

Usage
-----
    from app.section_designer.section_analyzer import SectionAnalyzer

    props = SectionAnalyzer.compute(vertices)
    # props is a dict ready to pass straight into ArbitrarySection(props_dict=props)
"""

import math

class SectionAnalyzer:

    @staticmethod
    def compute(vertices: list[tuple]) -> dict:
        """
        Compute section properties for a closed polygon.

        Parameters
        ----------
        vertices : list of (y, z) tuples, in order (CW or CCW).
                   At least 3 points required.
                   Do NOT repeat the first point at the end.

        Returns
        -------
        dict with keys:
            A       - cross-sectional area  (m²)
            I33     - second moment about 3-axis (strong, horiz)  (m⁴)
            I22     - second moment about 2-axis (weak, vert)     (m⁴)
            Iyz     - product of inertia (centroidal)             (m⁴)
            theta_p - principal axis angle from centroidal axes   (rad)
            Asy     - shear area local-2  (m²)  [approx]
            Asz     - shear area local-3  (m²)  [approx]
            J       - torsion constant    (m⁴)  [thin-wall approx via polar I]
            S33     - elastic section modulus major  (m³)
            S22     - elastic section modulus minor  (m³)
            r33     - radius of gyration major  (m)
            r22     - radius of gyration minor  (m)
            y_c     - centroid y  (m, from origin)
            z_c     - centroid z  (m, from origin)
        """
        verts = list(vertices)
        n = len(verts)
        if n < 3:
            return SectionAnalyzer._zero_props()

        A_signed = 0.0
        Cy = 0.0
        Cz = 0.0

        for i in range(n):
            y0, z0 = verts[i]
            y1, z1 = verts[(i + 1) % n]
            cross = y0 * z1 - y1 * z0
            A_signed += cross
            Cy += (y0 + y1) * cross
            Cz += (z0 + z1) * cross

        A_signed *= 0.5
        A = abs(A_signed)
        if A < 1e-20:
            return SectionAnalyzer._zero_props()

        Cy /= (6.0 * A_signed)
        Cz /= (6.0 * A_signed)

        Ixx_O = 0.0
        Iyy_O = 0.0
        Iyz_O = 0.0

        for i in range(n):
            y0, z0 = verts[i]
            y1, z1 = verts[(i + 1) % n]
            cross = y0 * z1 - y1 * z0
            Ixx_O += (z0**2 + z0*z1 + z1**2) * cross
            Iyy_O += (y0**2 + y0*y1 + y1**2) * cross
            Iyz_O += (y0*z1 + y1*z0 + 2.0*y0*z0 + 2.0*y1*z1) * cross

        Ixx_O /= 12.0
        Iyy_O /= 12.0
        Iyz_O /= 24.0

        if A_signed < 0:
            Iyz_O = -Iyz_O

        I33 = abs(Ixx_O) - A * Cz**2
        I22 = abs(Iyy_O) - A * Cy**2
        Iyz = Iyz_O     - A * Cy * Cz

        I33 = max(I33, 0.0)
        I22 = max(I22, 0.0)

        dI = I33 - I22
        if abs(dI) < 1e-30 and abs(Iyz) < 1e-30:
            theta_p = 0.0
        else:
            theta_p = 0.5 * math.atan2(-2.0 * Iyz, dI)

        zs = [v[1] for v in verts]
        ys = [v[0] for v in verts]

        y_right = max(ys) - Cy
        y_left  = Cy - min(ys)
        z_top   = max(zs) - Cz
        z_bot   = Cz - min(zs)

        c33 = max(z_top, z_bot)
        c22 = max(y_right, y_left)

        S33 = I33 / c33 if c33 > 1e-20 else 0.0
        S22 = I22 / c22 if c22 > 1e-20 else 0.0

        r33 = math.sqrt(I33 / A) if A > 0 else 0.0
        r22 = math.sqrt(I22 / A) if A > 0 else 0.0

        Asy = (5.0 / 6.0) * A
        Asz = (5.0 / 6.0) * A

        J = I33 + I22

        return {
            'A':       A,
            'I33':     I33,
            'I22':     I22,
            'Iyz':     Iyz,
            'theta_p': theta_p,
            'J':       J,
            'Asy':     Asy,
            'Asz':     Asz,
            'S33':     S33,
            'S22':     S22,
            'r33':     r33,
            'r22':     r22,
            'y_c':     Cy,
            'z_c':     Cz,
        }

    @staticmethod
    def _zero_props() -> dict:
        return {
            'A': 0.0, 'I33': 0.0, 'I22': 0.0, 'Iyz': 0.0, 'theta_p': 0.0,
            'J': 0.0, 'Asy': 0.0, 'Asz': 0.0,
            'S33': 0.0, 'S22': 0.0,
            'r33': 0.0, 'r22': 0.0,
            'y_c': 0.0, 'z_c': 0.0,
        }
