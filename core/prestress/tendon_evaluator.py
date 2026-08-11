import numpy as np
import math

class LinearSegment:
    """Evaluates a straight tendon segment in one plane (coord1 vs. a chosen ordinate)."""
    def __init__(self, p0, p1, ordinate_key="coord2"):
        self.x0, self.y0 = p0['coord1'], p0.get(ordinate_key, 0.0)
        self.x1, self.y1 = p1['coord1'], p1.get(ordinate_key, 0.0)

        dx = self.x1 - self.x0
        self.m = (self.y1 - self.y0) / dx if dx != 0 else 0.0

    def get_y(self, x):
        return self.y0 + self.m * (x - self.x0)

    def get_slope(self, x):
        return self.m

    def get_curvature(self, x):
        return 0.0                                      

class ParabolicSegment:
    """Evaluates a parabolic tendon segment using start point, end point, and start slope."""
    def __init__(self, p0, p1, ordinate_key="coord2", use_slope=True):
        self.x0 = p0['coord1']
        self.x1 = p1['coord1']
        self.y0 = p0.get(ordinate_key, 0.0)
        self.y1 = p1.get(ordinate_key, 0.0)

        L = self.x1 - self.x0
        if L <= 1e-9:
            self.a, self.b, self.c = 0.0, 0.0, self.y0
            return

        if use_slope:
            self.m0 = p0.get("slope", 0.0)
        else:
            self.m0 = (self.y1 - self.y0) / L

        self.c = self.y0
        self.b = self.m0
                                                                
        self.a = (self.y1 - self.y0 - self.m0 * L) / (L**2)

    def get_y(self, x):
        dx = x - self.x0
        return self.a * dx**2 + self.b * dx + self.c

    def get_slope(self, x):
        dx = x - self.x0
        return 2 * self.a * dx + self.b

    def get_curvature(self, x):
        y_prime = self.get_slope(x)
        y_double_prime = 2 * self.a
        return y_double_prime / (1 + y_prime**2)**1.5
    
class TendonEvaluator:
    """
    Parses UI layout points and computes continuous geometry and
    prestress force profiles (including friction/wobble losses).

    Tendon layout is tracked in both local planes:
      - coord2: local axis-2 offset (the "1-2" plane profile)
      - coord3: local axis-3 offset (the "1-3" plane profile)
    Both are built independently from the same set of breakpoints/segment
    types, since the geometry dialog lets a user define either or both.
    """
    def __init__(self, layout_points, tendon_section, load_data, total_length):
                                                                 
        self.points = sorted(layout_points, key=lambda p: p["coord1"])
        self.segments = []                                 
        self.z_segments = []                               
        self.segment_bounds = []
        self.total_length = total_length

        self._build_segments()

        self.area = tendon_section.area
        self.E = tendon_section.material.E

        self.jack_loc = load_data.get("jack_location", "I-End")
        self.mu = load_data.get("curvature_coeff", 0.15)
        self.K = load_data.get("wobble_coeff", 0.0)
        self.slip = load_data.get("anchorage_slip", 0.0)

        if load_data.get("load_type", "Force") == "Stress":
            self.P0 = load_data.get("load_value", 0.0) * self.area
        else:
            self.P0 = load_data.get("load_value", 0.0)

        constant_stress_loss = (
            load_data.get("elastic_stress", 0.0) +
            load_data.get("creep_stress", 0.0) +
            load_data.get("shrinkage_stress", 0.0) +
            load_data.get("relaxation_stress", 0.0)
        )
        self.constant_force_loss = constant_stress_loss * self.area

    def _build_segments(self):
        """Constructs the piecewise mathematical models for the tendon layout."""
        n = len(self.points)

        for i in range(1, n):
            p_prev = self.points[i-1]
            p_curr = self.points[i]
            seg_type = p_curr.get("segment_type", "Linear")

            x_start = p_prev['coord1']
            x_end = p_curr['coord1']

            if x_end - x_start <= 1e-9:
                continue

            self.segment_bounds.append((x_start, x_end))

            if seg_type == "Parabolic":
                self.segments.append(ParabolicSegment(p_prev, p_curr, "coord2", use_slope=True))
                self.z_segments.append(ParabolicSegment(p_prev, p_curr, "coord3", use_slope=False))
            else:
                self.segments.append(LinearSegment(p_prev, p_curr, "coord2"))
                self.z_segments.append(LinearSegment(p_prev, p_curr, "coord3"))
                
    def _get_segment_index_at(self, x):
        """Finds the active segment index for a given local x."""
        for i, (x_start, x_end) in enumerate(self.segment_bounds):
            if x_start - 1e-9 <= x <= x_end + 1e-9:
                return i

        if x < self.segment_bounds[0][0]:
            return 0
        return len(self.segments) - 1

    def _get_segment_at(self, x):
        """Finds the active axis-2 mathematical segment for a given local x."""
        return self.segments[self._get_segment_index_at(x)]

    def _get_z_segment_at(self, x):
        """Finds the active axis-3 mathematical segment for a given local x."""
        return self.z_segments[self._get_segment_index_at(x)]

    def get_eccentricity(self, x):
        """Returns the (axis-1, axis-2, axis-3) offset of the tendon at local distance x."""
        seg_y = self._get_segment_at(x)
        seg_z = self._get_z_segment_at(x)
        y = seg_y.get_y(x)
        z = seg_z.get_y(x)
        return np.array([0.0, y, z])

    def get_slope(self, x):
        """Returns the axis-2 derivative (slope) at distance x."""
        seg = self._get_segment_at(x)
        return seg.get_slope(x)

    def get_slope_z(self, x):
        """Returns the axis-3 derivative (slope) at distance x."""
        seg = self._get_z_segment_at(x)
        return seg.get_slope(x)

    def get_curvature(self, x):
        """Returns the exact mathematical axis-2 curvature at distance x."""
        seg = self._get_segment_at(x)
        return seg.get_curvature(x)

    def get_curvature_z(self, x):
        """Returns the exact mathematical axis-3 curvature at distance x."""
        seg = self._get_z_segment_at(x)
        return seg.get_curvature(x)

    @staticmethod
    def _tangent_angle_delta(m1y, m1z, m2y, m2z):
        """
        Angle (radians) between two 3D tangent vectors (1, slope_y, slope_z),
        i.e. the true spatial angular change of the tendon axis - not just
        the angular change within a single plane. This is what actually
        drives duct friction, regardless of which plane the curvature lies in.
        """
        v1 = np.array([1.0, m1y, m1z])
        v2 = np.array([1.0, m2y, m2z])
        v1 = v1 / np.linalg.norm(v1)
        v2 = v2 / np.linalg.norm(v2)
        cos_theta = np.clip(np.dot(v1, v2), -1.0, 1.0)
        return math.acos(cos_theta)

    def get_alpha(self, x_target):
        """
        Calculates the cumulative angular change alpha(x) from the start to x,
        combining axis-2 and axis-3 curvature into the true 3D tangent-vector
        angle change (see _tangent_angle_delta). This assumes friction is
        driven by total spatial curvature, not just in-plane curvature.
        """
        alpha = 0.0

        for i, (x_start, x_end) in enumerate(self.segment_bounds):
            if x_target <= x_start:
                break

            x_eval_end = min(x_end, x_target)
            seg_y = self.segments[i]
            seg_z = self.z_segments[i]

            m1y = seg_y.get_slope(x_start)
            m1z = seg_z.get_slope(x_start)
            m2y = seg_y.get_slope(x_eval_end)
            m2z = seg_z.get_slope(x_eval_end)

            alpha += self._tangent_angle_delta(m1y, m1z, m2y, m2z)

            if x_target <= x_end:
                break

        return alpha

    def _compute_force_from_jack(self, x, jack_at_zero=True):
        """
        Computes P(x) assuming a jack at either x=0 or x=L.
        Handles the exponential friction + wobble decay.
        """
        if jack_at_zero:
            dist_from_jack = x
            alpha_x = self.get_alpha(x)
        else:
            dist_from_jack = self.total_length - x
            alpha_x = self.get_alpha(self.total_length) - self.get_alpha(x)

        return self.P0 * math.exp(-(self.mu * alpha_x + self.K * dist_from_jack))

    def get_force(self, x):
        """
        Returns the instantaneous tendon force P(x) at local coordinate x,
        accounting for jacking location, friction, wobble, and constant losses.
        """
        if self.P0 <= 1e-9:
            return 0.0

        if self.jack_loc == "I-End":
            P_x = self._compute_force_from_jack(x, jack_at_zero=True)

        elif self.jack_loc == "J-End":
            P_x = self._compute_force_from_jack(x, jack_at_zero=False)

        elif self.jack_loc == "Both Ends":
            P_I = self._compute_force_from_jack(x, jack_at_zero=True)
            P_J = self._compute_force_from_jack(x, jack_at_zero=False)
            P_x = max(P_I, P_J)

        else:
            P_x = self.P0

        P_final = P_x - self.constant_force_loss
        return max(P_final, 0.0)
