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
    Matches SAP2000's horizontal projection assumptions exactly.
    """
    def __init__(self, layout_points, tendon_section, load_data, total_length, max_disc=1.524):
        self.points = sorted(layout_points, key=lambda p: p["coord1"])
        self.segments = []                                 
        self.z_segments = []                               
        self.segment_bounds = []
        self.total_length = total_length
        self.max_disc = max_disc

        self._build_segments()
        self._build_discrete_grid() 

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

        self.P_jack_after_I = self.P0
        self.P_jack_after_J = self.P0

        if self.slip > 1e-12:
            if self.jack_loc in ["I-End", "Both Ends"]:
                self.P_jack_after_I = self._calc_slip_p_jack(jack_at_zero=True)
            if self.jack_loc in ["J-End", "Both Ends"]:
                self.P_jack_after_J = self._calc_slip_p_jack(jack_at_zero=False)

    def _build_discrete_grid(self):
        """Builds the UI evaluation grid without artificial point discontinuities."""
        pts = set(p['coord1'] for p in self.points)
        for i in range(len(self.points) - 1):
            x0 = self.points[i]['coord1']
            x1 = self.points[i+1]['coord1']
            L = x1 - x0
            if L > 1e-6:
                n = max(1, math.ceil(L / self.max_disc))
                for j in range(1, n):
                    pts.add(x0 + j * (L / n))
                    
        self.discrete_x = sorted(list(pts))

    def _build_segments(self):
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
        for i, (x_start, x_end) in enumerate(self.segment_bounds):
            if x_start - 1e-9 <= x <= x_end + 1e-9:
                return i
        if x < self.segment_bounds[0][0]:
            return 0
        return len(self.segments) - 1

    def _get_segment_at(self, x):
        return self.segments[self._get_segment_index_at(x)]

    def _get_z_segment_at(self, x):
        return self.z_segments[self._get_segment_index_at(x)]

    def get_eccentricity(self, x):
        seg_y = self._get_segment_at(x)
        seg_z = self._get_z_segment_at(x)
        return np.array([0.0, seg_y.get_y(x), seg_z.get_y(x)])

    def get_slope(self, x):
        seg = self._get_segment_at(x)
        return seg.get_slope(x)

    def get_slope_z(self, x):
        seg = self._get_z_segment_at(x)
        return seg.get_slope(x)

    def get_curvature(self, x):
        seg = self._get_segment_at(x)
        return seg.get_curvature(x)

    def get_curvature_z(self, x):
        seg = self._get_z_segment_at(x)
        return seg.get_curvature(x)

    @staticmethod
    def _tangent_angle_delta(m1y, m1z, m2y, m2z):
        v1 = np.array([1.0, m1y, m1z])
        v2 = np.array([1.0, m2y, m2z])
        v1 = v1 / np.linalg.norm(v1)
        v2 = v2 / np.linalg.norm(v2)
        cos_theta = np.clip(np.dot(v1, v2), -1.0, 1.0)
        return math.acos(cos_theta)

    def get_alpha(self, x_target):
        alpha = 0.0
        prev_m2y, prev_m2z = None, None

        for i, (x_start, x_end) in enumerate(self.segment_bounds):
            if x_target <= x_start:
                break

            x_eval_end = min(x_end, x_target)
            seg_y = self.segments[i]
            seg_z = self.z_segments[i]

            m1y = seg_y.get_slope(x_start)
            m1z = seg_z.get_slope(x_start)

            if prev_m2y is not None and prev_m2z is not None:
                alpha += self._tangent_angle_delta(prev_m2y, prev_m2z, m1y, m1z)

            m2y = seg_y.get_slope(x_eval_end)
            m2z = seg_z.get_slope(x_eval_end)

            alpha += self._tangent_angle_delta(m1y, m1z, m2y, m2z)
            
            prev_m2y = m2y
            prev_m2z = m2z

            if x_target <= x_end:
                break

        return alpha
    
    def _calc_slip_p_jack(self, jack_at_zero):
        """
        Finds equilibrium force with High-Res internal integration to 
        match SAP2000 precision exactly, independent of the coarse UI grid.
        """
        if self.slip <= 1e-12 or self.P0 <= 1e-9:
            return self.P0

        target_area = self.slip * self.E * self.area

        def get_slip_area(P_ja):
            area = 0.0
            n_int = 2000
            dx = self.total_length / n_int
            
            prev_orig = self.P0
            prev_rev = P_ja
            prev_after = min(prev_orig, prev_rev)
            prev_diff = prev_orig - prev_after
            
            for i in range(1, n_int + 1):
                x_eval = i * dx
                if not jack_at_zero:
                    x_eval = self.total_length - x_eval
                    
                if jack_at_zero:
                    dist = x_eval
                    a_i = self.get_alpha(x_eval)
                else:
                    dist = self.total_length - x_eval
                    a_i = self.get_alpha(self.total_length) - self.get_alpha(x_eval)
                    
                curr_orig = self.P0 * math.exp(-(self.mu * a_i + self.K * dist))
                curr_rev = P_ja * math.exp(+(self.mu * a_i + self.K * dist))
                
                curr_after = min(curr_orig, curr_rev)
                curr_diff = curr_orig - curr_after
                
                area += 0.5 * (prev_diff + curr_diff) * dx
                prev_diff = curr_diff
                
            return area

        max_area = get_slip_area(0.0) 
        if max_area < target_area:
            return 0.0

        P_low = 0.0
        P_high = self.P0
        
        for _ in range(50):
            P_mid = (P_low + P_high) / 2.0
            area_mid = get_slip_area(P_mid)
            if area_mid > target_area:
                P_low = P_mid
            else:
                P_high = P_mid
                
        return (P_low + P_high) / 2.0
    
    def _get_components_from_jack(self, x, jack_at_zero=True):
        if jack_at_zero:
            dist = x
            a_x = self.get_alpha(x)
            P_ja = self.P_jack_after_I
        else:
            dist = self.total_length - x
            a_x = self.get_alpha(self.total_length) - self.get_alpha(x)
            P_ja = self.P_jack_after_J

        P_prior = self.P0 * math.exp(-(self.mu * a_x + self.K * dist))
        P_rev = P_ja * math.exp(+(self.mu * a_x + self.K * dist))
        
        P_after_seat = min(P_prior, P_rev)

        return P_prior, P_after_seat

    def get_force_components(self, x):
        if self.P0 <= 1e-9:
            return 0.0, 0.0, 0.0

        if self.jack_loc == "I-End":
            P_prior, P_after = self._get_components_from_jack(x, jack_at_zero=True)
        elif self.jack_loc == "J-End":
            P_prior, P_after = self._get_components_from_jack(x, jack_at_zero=False)
        elif self.jack_loc == "Both Ends":
            P_prior_I, P_after_I = self._get_components_from_jack(x, jack_at_zero=True)
            P_prior_J, P_after_J = self._get_components_from_jack(x, jack_at_zero=False)
            P_prior = max(P_prior_I, P_prior_J)
            P_after = max(P_after_I, P_after_J)
        else:
            P_prior = self.P0
            P_after = self.P0

        P_final = P_after - self.constant_force_loss
        return P_prior, P_after, max(P_final, 0.0)

    def get_force(self, x):
        _, _, p_final = self.get_force_components(x)
        return p_final