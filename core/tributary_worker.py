"""
core/tributary_worker.py
------------------------
Background QRunnable for off-thread tributary grid calculations.
Uses pure, high-density brute force for guaranteed stability and zero artifacts.
"""
import numpy as np
from PyQt6.QtCore import QRunnable, QObject, pyqtSignal

class TributaryWorkerSignals(QObject):
    finished = pyqtSignal(dict)

class TributaryWorker(QRunnable):
    def __init__(self, area_id, geom_sig, snap):
        super().__init__()
        self.signals = TributaryWorkerSignals()
        self.area_id = area_id
        self.geom_sig = geom_sig
        self.snap = snap

    def run(self):
        snap = self.snap
        grid_density = snap['grid_density']
        num_bins = snap['num_bins']
        min_x, max_x = snap['min_x'], snap['max_x']
        min_y, max_y = snap['min_y'], snap['max_y']
        
        dx = (max_x - min_x) / grid_density
        dy = (max_y - min_y) / grid_density
        unit_point_force = dx * dy

        xs = np.linspace(min_x + dx/2, max_x - dx/2, grid_density)
        ys = np.linspace(min_y + dy/2, max_y - dy/2, grid_density)
        X, Y = np.meshgrid(xs, ys)
        pts = np.column_stack([X.ravel(), Y.ravel()])

        nodes_xy = snap['nodes_xy']
        px, py = pts[:, 0], pts[:, 1]
        inside = np.zeros(len(pts), dtype=bool)
        n_nodes = len(nodes_xy)
        for i in range(n_nodes):
            j = (i + 1) % n_nodes
            p1x, p1y = nodes_xy[i]
            p2x, p2y = nodes_xy[j]
            dy_edge = p2y - p1y
            if dy_edge == 0: dy_edge = 1e-9
            intersect = ((p1y > py) != (p2y > py)) & (px < (p2x - p1x) * (py - p1y) / dy_edge + p1x)
            inside ^= intersect

        valid_pts = pts[inside]

        beam_hists = {}
        beam_lengths = {}
        beams = snap['beams']
        A = np.array([b['i'] for b in beams])
        B = np.array([b['j'] for b in beams])
        AB = B - A
        AB_sq = np.sum(AB**2, axis=1)
        AB_sq[AB_sq == 0] = 1e-9

        if len(valid_pts) > 0 and len(beams) > 0:
                                            
            P = valid_pts[:, np.newaxis, :]
            AP = P - A[np.newaxis, :, :]

            t = np.sum(AP * AB[np.newaxis, :, :], axis=2) / AB_sq[np.newaxis, :]
            t = np.clip(t, 0.0, 1.0)

            Proj = A[np.newaxis, :, :] + t[:, :, np.newaxis] * AB[np.newaxis, :, :]
            Dists = np.linalg.norm(P - Proj, axis=2)

            closest_beam_indices = np.argmin(Dists, axis=1)
            closest_t = t[np.arange(len(valid_pts)), closest_beam_indices]

            from scipy.ndimage import gaussian_filter1d

            for b_idx, beam in enumerate(beams):
                mask = (closest_beam_indices == b_idx)
                t_vals = closest_t[mask]
                if len(t_vals) == 0: continue
                hist, _ = np.histogram(t_vals, bins=num_bins, range=(0.0, 1.0))
                
                raw_total = hist.sum()
                if raw_total > 0:
                    smoothed = gaussian_filter1d(hist.astype(np.float64), sigma=2.0, mode='nearest')
                    smoothed_total = smoothed.sum()
                    if smoothed_total > 0:
                        smoothed *= (raw_total / smoothed_total)                               
                    hist = smoothed
                
                beam_hists[b_idx] = hist
                beam_lengths[b_idx] = beam['length']

        palette = np.array([
            [0.85, 0.35, 0.30, 0.55], [0.35, 0.60, 0.45, 0.55],
            [0.30, 0.50, 0.75, 0.55], [0.85, 0.65, 0.25, 0.55],
            [0.55, 0.40, 0.65, 0.55], [0.30, 0.65, 0.65, 0.55],
        ])

        heat_res = 100
        hxs = np.linspace(min_x, max_x, heat_res)
        hys = np.linspace(min_y, max_y, heat_res)
        HX, HY = np.meshgrid(hxs, hys)
        hpx, hpy = HX.ravel(), HY.ravel()

        h_inside = np.zeros(len(hpx), dtype=bool)
        for i in range(n_nodes):
            j = (i + 1) % n_nodes
            p1x, p1y = nodes_xy[i]
            p2x, p2y = nodes_xy[j]
            dy_edge = p2y - p1y
            if dy_edge == 0: dy_edge = 1e-9
            intersect = ((p1y > hpy) != (p2y > hpy)) & (hpx < (p2x - p1x) * (hpy - p1y) / dy_edge + p1x)
            h_inside ^= intersect

        h_faces = np.zeros((0, 3), dtype=np.uint32)
        h_verts_flat = np.zeros((0, 3), dtype=np.float32)
        h_colors_flat = np.zeros((0, 4), dtype=np.float32)

        if len(beams) > 0:
            Hp = np.column_stack([hpx, hpy])
            HAP = Hp[:, np.newaxis, :] - A[np.newaxis, :, :]
            Ht = np.sum(HAP * AB[np.newaxis, :, :], axis=2) / AB_sq[np.newaxis, :]
            Ht = np.clip(Ht, 0.0, 1.0)
            HProj = A[np.newaxis, :, :] + Ht[:, :, np.newaxis] * AB[np.newaxis, :, :]
            HDists = np.linalg.norm(Hp[:, np.newaxis, :] - HProj, axis=2)
            h_beam_idx = np.argmin(HDists, axis=1)
            h_colors_flat = palette[h_beam_idx % len(palette)].astype(np.float32)
            h_verts_flat = np.column_stack([hpx, hpy, np.full(len(hpx), snap['z_val'])]).astype(np.float32)

            h_inside_grid = h_inside.reshape(heat_res, heat_res)
            idx_grid = np.arange(heat_res * heat_res).reshape(heat_res, heat_res)
            tl, tr = idx_grid[:-1, :-1], idx_grid[:-1, 1:]
            bl, br = idx_grid[1:, :-1],  idx_grid[1:, 1:]
            quad_ok = (h_inside_grid[:-1, :-1] & h_inside_grid[:-1, 1:] &
                       h_inside_grid[1:, :-1]  & h_inside_grid[1:, 1:])

            if np.any(quad_ok):
                tl_ok, tr_ok = tl[quad_ok], tr[quad_ok]
                bl_ok, br_ok = bl[quad_ok], br[quad_ok]
                h_faces = np.vstack([
                    np.column_stack([tl_ok, bl_ok, br_ok]),
                    np.column_stack([tl_ok, br_ok, tr_ok]),
                ]).astype(np.uint32)

        heatmap_entry = {'verts': h_verts_flat, 'colors': h_colors_flat, 'faces': h_faces}
        heat_points = h_verts_flat[h_inside] if len(h_verts_flat) > 0 else np.zeros((0, 3))
        heat_colors = h_colors_flat[h_inside] if len(h_colors_flat) > 0 else np.zeros((0, 4))

        result = {
            'area_id': self.area_id,
            'sig': self.geom_sig,
            'beam_hists': beam_hists,
            'beam_lengths': beam_lengths,
            'unit_point_force': unit_point_force,
            'heatmap_entry': heatmap_entry,
            'heat_points': heat_points,
            'heat_colors': heat_colors,
        }
        
        self.signals.finished.emit(result)
