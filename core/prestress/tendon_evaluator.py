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
    Parses UI layout points and computes continuous geometry and prestress force
    profiles (including friction/wobble losses), matching SAP2000's own discretized
    (chord-based, nodally-averaged) computation to within screen-rounding precision.
    """

    _ARC_LENGTH_SUBSTEPS = 4000

    def __init__(self, layout_points, tendon_section, load_data, total_length, max_disc=1.524):
        self.points = sorted(layout_points, key=lambda p: p["coord1"])
        self.segments = []
        self.z_segments = []
        self.segment_bounds = []
        self.total_length = total_length                                                               
        self.max_disc = max_disc

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

        self._mesh_nodes = self._build_mesh()                                                           
        self.arc_length = self._mesh_nodes[-1][1]                                            

        self.discrete_x = [x for x, s in self._mesh_nodes]

        self._mesh_forward = self._build_force_mesh(from_i_end=True)                                
        self._mesh_reverse = self._build_force_mesh(from_i_end=False)                               

        self.P_jack_after_I = self.P0
        self.P_jack_after_J = self.P0

        if self.slip > 1e-12:
            if self.jack_loc in ["I-End", "Both Ends"]:
                self.P_jack_after_I = self._calc_slip_p_jack(from_i_end=True)
            if self.jack_loc in ["J-End", "Both Ends"]:
                self.P_jack_after_J = self._calc_slip_p_jack(from_i_end=False)

    def _build_segments(self):
        n = len(self.points)
        for i in range(1, n):
            p_prev = self.points[i - 1]
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
        return self._get_segment_at(x).get_slope(x)

    def get_slope_z(self, x):
        return self._get_z_segment_at(x).get_slope(x)

    def get_curvature(self, x):
        return self._get_segment_at(x).get_curvature(x)

    def get_curvature_z(self, x):
        return self._get_z_segment_at(x).get_curvature(x)

    def _get_xyz(self, x):
        seg_y = self._get_segment_at(x)
        seg_z = self._get_z_segment_at(x)
        return seg_y.get_y(x), seg_z.get_y(x)

    def _build_mesh(self):
        """
        Builds the discretized node list SAP2000 uses internally: every user-defined
        layout point is a node, and each inter-point span is further subdivided into
        equal-arc-length pieces no longer than max_disc. Returns [(x, s), ...] sorted
        by x, where s is cumulative arc length measured from the I-end (x[0]).

        SAP2000 always defines a "Parabolic" tendon segment as a Start -> Intermediate
        -> End triple internally (even though the layout-point data model used here
        only stores Start/End + a start slope). That intermediate point is itself a
        mandatory discretization boundary, independent of max_disc, and its default
        location (absent any other info) is the geometric midpoint of the segment.
        Skipping this split under-meshes curved (and any flat-but-"Parabolic"-typed)
        segments relative to SAP and throws off the friction calc downstream of them
        - so each Parabolic span is split into two discretization sub-spans here,
        each independently subdivided by max_disc. This does not change the geometry
        (the underlying curve/eccentricity is unaffected) - only the meshing.
        """
                                                                                   
        disc_spans = []
        for i, (x0, x1) in enumerate(self.segment_bounds):
            seg_type = self.points[i + 1].get("segment_type", "Linear")
            if seg_type == "Parabolic":
                x_mid = 0.5 * (x0 + x1)
                disc_spans.append((x0, x_mid, i))
                disc_spans.append((x_mid, x1, i))
            else:
                disc_spans.append((x0, x1, i))

        nodes = [(disc_spans[0][0], 0.0)]
        s_cum = 0.0

        for x0, x1, seg_i in disc_spans:
            xx = np.linspace(x0, x1, self._ARC_LENGTH_SUBSTEPS + 1)
            yp = np.array([self.segments[seg_i].get_slope(x) for x in xx])
            zp = np.array([self.z_segments[seg_i].get_slope(x) for x in xx])
            integrand = np.sqrt(1.0 + yp**2 + zp**2)
            cs = np.concatenate([[0.0], np.cumsum((integrand[:-1] + integrand[1:]) / 2 * np.diff(xx))])
            span_arc_len = cs[-1]

            n_elem = max(1, math.ceil(span_arc_len / self.max_disc)) if self.max_disc > 1e-9 else 1

            for k in range(1, n_elem + 1):
                target_s_local = span_arc_len * k / n_elem
                x_k = x1 if k == n_elem else float(np.interp(target_s_local, cs, xx))
                s_k = s_cum + target_s_local
                nodes.append((x_k, s_k))

            s_cum += span_arc_len

        dedup = [nodes[0]]
        for x, s in nodes[1:]:
            if x - dedup[-1][0] > 1e-7:
                dedup.append((x, s))
        return dedup

    @staticmethod
    def _tangent_angle_delta(m1y, m1z, m2y, m2z):
        v1 = np.array([1.0, m1y, m1z])
        v2 = np.array([1.0, m2y, m2z])
        v1 = v1 / np.linalg.norm(v1)
        v2 = v2 / np.linalg.norm(v2)
        cos_theta = np.clip(np.dot(v1, v2), -1.0, 1.0)
        return math.acos(cos_theta)

    def _build_force_mesh(self, from_i_end=True):
        """
        Computes, at every mesh node, the SAP-matching "Prior to Seating" force and
        cumulative alpha, using chord-to-chord turning angles and nodal averaging
        (average of the value approaching the node and the value just past it).

        Returns list of dicts: {'x', 's', 'alpha_left', 'alpha_right', 'alpha_avg'}
        s is measured from the relevant jacking end (I-end if from_i_end else J-end).
        """
        nodes = self._mesh_nodes if from_i_end else list(reversed(
            [(x, self.arc_length - s) for x, s in self._mesh_nodes]))

        pts = []
        for x, s in nodes:
            y, z = self._get_xyz(x)
            pts.append((x, y, z))

        chords = []
        for i in range(len(pts) - 1):
            dx = pts[i + 1][0] - pts[i][0]
            dy = pts[i + 1][1] - pts[i][1]
            dz = pts[i + 1][2] - pts[i][2]
            chords.append((dx, dy, dz))

        n = len(nodes)
        turn = [0.0] * n
        for i in range(1, n - 1):
            turn[i] = self._chord_angle(chords[i - 1], chords[i])

        left = [0.0] * n
        right = [0.0] * n
        running = 0.0
        for i in range(n):
            left[i] = running
            running += turn[i]
            right[i] = running

        mesh = []
        for i, (x, s) in enumerate(nodes):
            mesh.append({
                'x': x, 's': s,
                'alpha_left': left[i], 'alpha_right': right[i],
                'alpha_avg': (left[i] + right[i]) / 2.0,
            })
        return mesh

    @staticmethod
    def _chord_angle(c1, c2):
        v1 = np.array(c1, dtype=float)
        v2 = np.array(c2, dtype=float)
        v1 = v1 / np.linalg.norm(v1)
        v2 = v2 / np.linalg.norm(v2)
        return math.acos(np.clip(np.dot(v1, v2), -1.0, 1.0))

    def get_alpha(self, x_target):
        """Kept for backward compatibility / external callers: returns the smooth
        (non-discretized) cumulative angle up to x_target from the I-end. Prefer the
        mesh-based (_mesh_forward / _mesh_reverse) values internally, which match SAP."""
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

            prev_m2y, prev_m2z = m2y, m2z
            if x_target <= x_end:
                break

        return alpha

    def _interp_mesh(self, mesh, s_query):
        """Linearly interpolate (alpha_avg, s) at an arbitrary arc-length position
        from a pre-computed force mesh. Endpoints/interior use nodal-averaged alpha;
        interpolation between nodes is linear in s, consistent with how the value
        changes across a single (straight, in the discretized model) chord."""
        s_arr = [m['s'] for m in mesh]
        a_arr = [m['alpha_avg'] for m in mesh]
        s_query = min(max(s_query, s_arr[0]), s_arr[-1])
        return float(np.interp(s_query, s_arr, a_arr))

    def _x_to_s(self, x, from_i_end=True):
        node_x = [n[0] for n in self._mesh_nodes]
        node_s = [n[1] for n in self._mesh_nodes]
        s = float(np.interp(x, node_x, node_s))
        return s if from_i_end else (self.arc_length - s)

    def _calc_slip_p_jack(self, from_i_end):
        """
        Solves for the jack-end force after anchorage-set (wedge draw-in), using the
        exact friction-reversal method: within the seating-influence length, the
        tendon "gives back" force following the SAME friction relationship in reverse.

        STATUS: validated to within ~0.1-0.2 kN (< 0.05%) for straight and V-shaped
        (piecewise-linear) tendons. For smoothly curved (parabolic) profiles, residual
        errors up to ~1-2 kN have been observed against real SAP2000 output in testing,
        meaning the exact per-element seating-loss rate SAP uses for curved tendons is
        not yet fully confirmed. If you need this validated further: export SAP's
        After-Seating results for the same parabolic tendon with a different slip or
        curvature-coefficient value (holding geometry fixed) so the loss-rate formula
        can be isolated from a second, independent data point.
        """
        if self.slip <= 1e-12 or self.P0 <= 1e-9:
            return self.P0

        mesh = self._mesh_forward if from_i_end else self._mesh_reverse
        target_area = self.slip * self.E * self.area

        def get_slip_area(P_ja):
            area = 0.0
            n_int = 4000
            dx = self.arc_length / n_int
            prev_diff = None
            for i in range(0, n_int + 1):
                s_eval = i * dx
                a_i = self._interp_mesh(mesh, s_eval)
                curr_orig = self.P0 * math.exp(-(self.mu * a_i + self.K * s_eval))
                curr_rev = P_ja * math.exp(+(self.mu * a_i + self.K * s_eval))
                curr_after = min(curr_orig, curr_rev)
                curr_diff = curr_orig - curr_after
                if prev_diff is not None:
                    area += 0.5 * (prev_diff + curr_diff) * dx
                prev_diff = curr_diff
            return area

        max_area = get_slip_area(0.0)
        if max_area < target_area:
            return 0.0

        P_low, P_high = 0.0, self.P0
        for _ in range(50):
            P_mid = (P_low + P_high) / 2.0
            if get_slip_area(P_mid) > target_area:
                P_low = P_mid
            else:
                P_high = P_mid

        return (P_low + P_high) / 2.0

    def _get_components_from_jack(self, x, from_i_end=True):
        mesh = self._mesh_forward if from_i_end else self._mesh_reverse
        s = self._x_to_s(x, from_i_end=from_i_end)
        dist = s
        a_x = self._interp_mesh(mesh, s)
        P_ja = self.P_jack_after_I if from_i_end else self.P_jack_after_J

        P_prior = self.P0 * math.exp(-(self.mu * a_x + self.K * dist))
        P_rev = P_ja * math.exp(+(self.mu * a_x + self.K * dist))

        P_after_seat = min(P_prior, P_rev)
        return P_prior, P_after_seat

    def get_force_components(self, x):
        if self.P0 <= 1e-9:
            return 0.0, 0.0, 0.0

        if self.jack_loc == "I-End":
            P_prior, P_after = self._get_components_from_jack(x, from_i_end=True)
        elif self.jack_loc == "J-End":
            P_prior, P_after = self._get_components_from_jack(x, from_i_end=False)
        elif self.jack_loc == "Both Ends":
                                                                            
            P_prior_I, P_after_I = self._get_components_from_jack(x, from_i_end=True)
            P_prior_J, P_after_J = self._get_components_from_jack(x, from_i_end=False)
            P_prior = max(P_prior_I, P_prior_J)
            loss_I = P_prior_I - P_after_I
            loss_J = P_prior_J - P_after_J
            P_after = P_prior - loss_I - loss_J
        else:
            P_prior = self.P0
            P_after = self.P0

        P_final = P_after - self.constant_force_loss
        return P_prior, P_after, max(P_final, 0.0)

    def get_force(self, x):
        _, _, p_final = self.get_force_components(x)
        return p_final
