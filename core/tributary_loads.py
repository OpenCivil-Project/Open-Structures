"""
core/tributary_loads.py
-----------------------
Handles generalized Tributary Area / Yield Line load distribution.
Offloads heavy Numpy grid calculation to a background thread.
"""

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal, QThreadPool
from core.model import MemberLoad 
from core.tributary_worker import TributaryWorker

class TributaryLoadGenerator(QObject):
    signal_redraw_requested = pyqtSignal()
    signal_all_loads_ready = pyqtSignal()                                                                        

    def __init__(self, model):
        super().__init__()
        self.model = model
        self.grid_density = 2500     
        self.num_bins = 250      
        self.thread_pool = QThreadPool.globalInstance()
        self._pending_count = 0                                                                                  

    def is_busy(self):
        """True if any background slab computation is still in flight."""
        return self._pending_count > 0

    def calculate_slab_pressure(self, area_elem, pattern_name):
        q_total = 0.0
        pattern = self.model.load_patterns.get(pattern_name)
        if not pattern: return 0.0

        sec = area_elem.section
        sw_mult = pattern.self_weight_multiplier
        if sw_mult > 0.0 and hasattr(sec, 'membrane_thickness') and sec.material:
                                                
            q_total += (sec.membrane_thickness * sec.material.density * sw_mult)

        for load in self.model.loads:
            if not hasattr(load, 'area_id') or load.area_id != area_elem.id:
                continue
            if getattr(load, 'pattern_name', getattr(load, 'load_pattern_name', None)) != pattern_name:
                continue

            if hasattr(load, 'uniform_load'):
                direction = load.load_direction.upper()
                val = load.uniform_load
                if direction == "GRAVITY":
                    q_total += val                                      
                elif direction in ["GLOBAL Z", "LOCAL 3"]:
                    q_total -= val                                                    
                    
            elif hasattr(load, 'gz') and load.gz != 0.0 and hasattr(sec, 'membrane_thickness') and sec.material:
                q_total -= (load.gz * sec.membrane_thickness * sec.material.density)

        return q_total

    def get_perimeter_beams(self, area_elem):
        nodes = area_elem.nodes
        perimeter_beams = []
        edges = [(nodes[i], nodes[(i + 1) % len(nodes)]) for i in range(len(nodes))]

        for n1, n2 in edges:
            p1 = np.array([n1.x, n1.y, n1.z])
            p2 = np.array([n2.x, n2.y, n2.z])
            edge_length = np.linalg.norm(p2 - p1)
            if edge_length < 1e-6: continue

            for el in self.model.elements.values():
                b1 = np.array([el.node_i.x, el.node_i.y, el.node_i.z])
                b2 = np.array([el.node_j.x, el.node_j.y, el.node_j.z])
                
                d1 = np.linalg.norm(np.cross(p2-p1, p1-b1)) / edge_length
                d2 = np.linalg.norm(np.cross(p2-p1, p1-b2)) / edge_length
                
                dot1 = np.dot(b1-p1, p2-p1)
                dot2 = np.dot(b2-p1, p2-p1)
                
                if d1 < 1e-3 and d2 < 1e-3:
                    if (0 - 1e-3 <= dot1 <= edge_length**2 + 1e-3) and\
                       (0 - 1e-3 <= dot2 <= edge_length**2 + 1e-3):
                        perimeter_beams.append(el)

        return perimeter_beams

    def distribute_loads_to_frames(self):
        """Phase A: Plan execution. Use cache if ready, otherwise dispatch a worker."""
        if not hasattr(self.model, '_tributary_cache'):
            self.model._tributary_cache = {}
        
        cache = self.model._tributary_cache
        live_area_ids = set()
        dispatched = 0                                                                                           

        for area in self.model.area_elements.values():
            if not hasattr(area.section, 'modeling_type') or area.section.modeling_type != "Tributary Area":
                continue

            z_coords = [n.z for n in area.nodes]
            if max(z_coords) - min(z_coords) > 0.01:
                continue

            beams = self.get_perimeter_beams(area)
            if not beams: continue

            live_area_ids.add(area.id)

            geom_sig = (
                self.grid_density, self.num_bins,
                tuple((round(n.x, 6), round(n.y, 6), round(n.z, 6)) for n in area.nodes),
                tuple(b.id for b in beams),
                tuple((round(b.node_i.x, 6), round(b.node_i.y, 6), round(b.node_j.x, 6), round(b.node_j.y, 6)) for b in beams),
            )

            cached = cache.get(area.id)
            if not cached or cached['sig'] != geom_sig:
                                                                                  
                nodes_xy = np.array([[n.x, n.y] for n in area.nodes])
                min_x, min_y = np.min(nodes_xy, axis=0)
                max_x, max_y = np.max(nodes_xy, axis=0)

                beams_data = []
                for b in beams:
                    length = np.linalg.norm(np.array([b.node_j.x, b.node_j.y, b.node_j.z]) - np.array([b.node_i.x, b.node_i.y, b.node_i.z]))
                    beams_data.append({'i': [b.node_i.x, b.node_i.y], 'j': [b.node_j.x, b.node_j.y], 'length': length})

                snap = {
                    'grid_density': self.grid_density,
                    'num_bins': self.num_bins,
                    'min_x': min_x, 'max_x': max_x,
                    'min_y': min_y, 'max_y': max_y,
                    'z_val': area.nodes[0].z,
                    'nodes_xy': nodes_xy,
                    'beams': beams_data
                }

                cache[area.id] = {'sig': geom_sig, 'pending': True} 
                
                worker = TributaryWorker(area.id, geom_sig, snap)
                worker.signals.finished.connect(self._on_worker_finished)
                self.thread_pool.start(worker)
                dispatched += 1                                                                                  

        for aid in set(cache.keys()) - live_area_ids:
            del cache[aid]

        self._pending_count += dispatched                                                                        
        self._apply_cached_loads()

        if self._pending_count == 0:                                                                             
            self.signal_all_loads_ready.emit()

    def _on_worker_finished(self, result):
        """Phase C: Triggered when background numpy math finishes."""
        if not hasattr(self.model, '_tributary_cache'): return
        
        area_id = result['area_id']
        cache = self.model._tributary_cache

        if area_id in cache and cache[area_id]['sig'] == result['sig']:
            cache[area_id] = result
            self._apply_cached_loads()
            self.signal_redraw_requested.emit()

        self._pending_count = max(0, self._pending_count - 1)                                                    
        if self._pending_count == 0:                                                                             
            self.signal_all_loads_ready.emit()

    def _apply_cached_loads(self):
        """
        Builds MemberLoads by aggregating all slab-to-beam contributions
        into a temporary buffer first, preventing load overlaps.
        """
                                      
        self.model.loads = [ld for ld in self.model.loads if not getattr(ld, 'is_tributary_generated', False)]

        self.model.tributary_visuals = {'points': [], 'colors': [], 'heatmap': {}}

        load_aggregator = {} 

        beam_meta = {} 

        pattern_names = list(self.model.load_patterns.keys())
        cache = self.model._tributary_cache

        for area in self.model.area_elements.values():
            if area.id not in cache or cache[area.id].get('pending', False):
                continue

            cached = cache[area.id]
            beams = self.get_perimeter_beams(area)

            self.model.tributary_visuals['heatmap'][area.id] = cached['heatmap_entry']
            self.model.tributary_visuals['points'].append(cached['heat_points'])
            self.model.tributary_visuals['colors'].append(cached['heat_colors'])

            unit_point_force = cached['unit_point_force']
            bin_length_rel = 1.0 / self.num_bins

            for pattern_name in pattern_names:
                q = self.calculate_slab_pressure(area, pattern_name)
                if abs(q) < 1e-9: continue
                
                point_force = unit_point_force * q

                for b_idx, beam in enumerate(beams):
                    hist = cached['beam_hists'].get(b_idx)
                    if hist is None: continue
                    L_total = cached['beam_lengths'][b_idx]
                    if L_total <= 1e-6: continue

                    bin_length_actual = L_total * bin_length_rel
                    force_array = (hist * point_force) / bin_length_actual

                    key = (beam.id, pattern_name)
                    if key not in load_aggregator:
                        load_aggregator[key] = np.zeros(self.num_bins)
                        beam_meta[key] = (beam, L_total)
                    
                    load_aggregator[key] += force_array

        for key, summed_magnitudes in load_aggregator.items():
            beam_id, pattern_name = key
            beam, L_total = beam_meta[key]

            distances = [(i + 0.5) * bin_length_rel for i in range(self.num_bins)]
            distances = [0.0] + distances + [1.0]
                                                    
            magnitudes = [0.0] + list(summed_magnitudes) + [0.0]

            new_load = MemberLoad(
                element_id=beam_id, pattern_name=pattern_name,
                wx=0.0, wy=0.0, wz=0.0, projected=False,
                coord_system="Global", distances=distances,
                magnitudes=[-w for w in magnitudes],                              
                is_relative=True, load_direction="Global Z"
            )
            new_load.is_tributary_generated = True
            self.model.loads.append(new_load)
            
    def reset(self, new_model):
        """Called when a new file is opened to wipe the old cache and link new model."""
        self.model = new_model
                                                                                            
        self.model._tributary_cache = {} 
        self.thread_pool.clear()
