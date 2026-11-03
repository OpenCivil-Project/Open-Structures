"""Display-only grouping with fixed model-space samples for assigned loads."""
import numpy as np

from .area_load_axes import area_load_axes, area_load_components
from .area_load_display import (build_area_load_regions, choose_region_anchor,
                                region_boundary_edges, sample_region_arrows,
                                prepare_area_load_region)
from .load_label_layout import layout_load_labels
from .load_view_geometry import LoadViewGeometry
from core.units import unit_registry

_BUFFERS = ('_pending_load_fill_verts', '_pending_load_fill_colors',
            '_pending_load_fill_faces', '_pending_load_line_pos',
            '_pending_load_line_colors')

class AreaLoadDisplayMixin:
    def _load_text_scale(self):
        try:
            scale = float(self.display_config.get('load_text_scale', 1.0))
            return float(np.clip(scale, 0.5, 2.5)) if np.isfinite(scale) else 1.0
        except (ValueError, TypeError):
            return 1.0

    def _scaled_load_labels(self):
        """Scale input annotations only; force diagrams keep their own text size."""
        labels = getattr(self, 'load_labels', [])
        scale = self._load_text_scale()
        if scale == 1.0 or getattr(self, 'reaction_diagram_active', False):
            return list(labels)
        return [dict(label, text_height=label.get('text_height', 0.25) * scale)
                for label in labels]

    def _area_load_projection(self, mvp=None, width=None, height=None):
        w = self.width() if width is None else width
        h = self.height() if height is None else height
        if w <= 0 or h <= 0:
            return None, None, w, h
        if mvp is None:
            full_area = (0, 0, w, h)
            mvp = np.array((self.projectionMatrix(region=full_area, viewport=full_area) *
                            self.viewMatrix()).data(), dtype=float).reshape(4, 4).T
        mvp = np.asarray(mvp, dtype=float)

        def project(point):
            clip = mvp @ np.r_[point, 1.0]
            if not np.isfinite(clip).all() or clip[3] <= 1e-12:
                return None
            ndc = clip[:3] / clip[3]
            if (np.abs(ndc[:2]) > 1).any() or abs(ndc[2]) > 1:
                return None
            return ((ndc[0] + 1) * w / 2, (1 - ndc[1]) * h / 2, ndc[2])

        def project_batch(points):
            points = np.asarray(points, dtype=float)
            clip = np.c_[points, np.ones(len(points))] @ mvp.T
            valid = np.isfinite(clip).all(axis=1) & (clip[:, 3] > 1e-12)
            result = np.full((len(points), 3), np.nan)
            ndc = clip[valid, :3] / clip[valid, 3:4]
            visible = (np.abs(ndc) <= 1).all(axis=1)
            rows = np.flatnonzero(valid)[visible]
            result[rows, 0] = (ndc[visible, 0] + 1) * w / 2
            result[rows, 1] = (1 - ndc[visible, 1]) * h / 2
            result[rows, 2] = ndc[visible, 2]
            return result
        project.batch = project_batch
        return project, mvp, w, h

    def _draw_area_loads(self, model):
        """Keep assignments intact and derive groups from their current values."""
        self._area_load_regions = []
        self._area_load_prepared = []
        self._area_load_view_samples = []
        self._area_load_annotations = []
        self._area_load_label_leaders = []
        self._area_load_dynamic_arrows = []
        self._area_load_dynamic_leaders = []
        self._area_load_view_key = None
        self._area_load_view_needs_settle = False
        self._area_load_view_time = 0.0
        self._area_load_display_model = model
        self._area_load_selection = tuple(sorted(self.selected_area_ids))
        self._area_load_display_base = {name: len(getattr(self, name)) for name in _BUFFERS}
        self._area_load_display_base['labels'] = len(self.load_labels)
        if not model.loads or not self.show_loads or self.load_type_filter == 'nodal':
            return
        selected = set(self.selected_area_ids)
        by_area = {}
        for load in model.loads:
            if not hasattr(load, 'area_id'):
                continue
            if self.visible_load_patterns and load.pattern_name not in self.visible_load_patterns:
                continue
            by_area.setdefault(load.area_id, []).append(load)
        if (not by_area and getattr(self, '_load_view_geometry', None) is not None
                and getattr(self, '_frame_load_display_model', None) is model):
                                                                         
            return
        self._thaw_load_view_geometry()
        records = []
        ink = self._theme_ink_rgb()
        for area_id, loads in by_area.items():
            area = model.area_elements.get(area_id)
            if area is None or len(area.nodes) < 3:
                continue
            states = [self._get_visibility_state(n.x, n.y, n.z) for n in area.nodes]
            if min(states + [self._vo_state('area', area_id)]) < 2:
                continue
            points = np.array([[n.x, n.y, n.z] for n in area.nodes], dtype=float)
            try:
                axes = area_load_axes(points, area.section)
            except (ValueError, TypeError):
                continue
            centroid = points.mean(axis=0)
            size = float(np.max(np.linalg.norm(points - centroid, axis=1)))
            entries = []
            for load in loads:
                if hasattr(load, 'uniform_load'):
                    signature = ('uniform', load.pattern_name, str(load.coord_system).upper(),
                                 str(load.load_direction).upper(), float(load.uniform_load))
                    kind = 'uniform'
                elif hasattr(load, 'gx'):
                    signature = ('gravity', load.pattern_name, str(load.coord_system).upper(),
                                 float(load.gx), float(load.gy), float(load.gz))
                    kind = 'gravity'
                else:
                    continue
                try:
                    components = area_load_components(load, points, area.section)
                except (ValueError, TypeError):
                    continue
                entries.append((signature, kind, load, components))
            entries.sort(key=lambda entry: repr(entry[0]))
            specs = []
            for signature, kind, load, components in entries:
                for direction, magnitude in components:
                    if magnitude < 1e-9:
                        continue
                    specs.append(dict(direction=np.asarray(direction), magnitude=magnitude,
                                      color=ink, kind=kind, pattern=load.pattern_name,
                                      direction_name=getattr(load, 'load_direction', '')))
            if not specs:
                continue
            records.append(dict(area_id=area_id, node_ids=tuple(n.id for n in area.nodes),
                                points=points, normal=axes[2], centroid=centroid,
                                shell_size=size, selected=area_id in selected,
                                section_key=(id(area.section), float(getattr(area, 'insertion_offset', 0) or 0)),
                                signature=tuple(entry[0] for entry in entries), specs=specs,
                                section=area.section))
        mode = self.display_config.get('area_load_display_mode', 'smart')
        self._area_load_regions = ([[record] for record in records] if mode == 'every_area'
                                   else build_area_load_regions(records))
        self._area_load_prepared = [prepare_area_load_region(region)
                                    for region in self._area_load_regions]
        self._render_area_load_regions()

    def _render_area_load_regions(self, mvp=None, width=None, height=None, interactive=False):
        project, mvp, w, h = self._area_load_projection(mvp, width, height)
        mode = self.display_config.get('area_load_display_mode', 'smart')
        spacing = float(self.display_config.get('area_load_arrow_spacing', 55))
        spacing = float(np.clip(spacing, 20, 150)) if np.isfinite(spacing) else 55.0
        annotations = []
        self._area_load_dynamic_arrows = []
        self._area_load_dynamic_leaders = []
        patterns = {spec['pattern'] for region in self._area_load_regions
                    for spec in region[0]['specs']}
        rounded_values = {}
        for region in self._area_load_regions:
            for spec in region[0]['specs']:
                scale = (unit_registry.force_scale / unit_registry.length_scale ** 2
                         if spec['kind'] == 'uniform' else 1.0)
                value = spec['magnitude'] * scale
                key = (spec['kind'], spec['pattern'], spec['direction_name'], f'{value:.2f}')
                rounded_values.setdefault(key, set()).add(value)
        sampled_regions = []
        for region_index, (region, prepared) in enumerate(zip(self._area_load_regions, self._area_load_prepared)):
            anchor = choose_region_anchor(region, prepared=prepared)
            anchor_point = prepared['anchor_point']
            if anchor_point is None:
                anchor_point = anchor['centroid']
            chosen = bool(anchor['selected'])
            region_size = prepared['bounding_extent'] or anchor['shell_size']
            if mode == 'every_area' or not prepared['valid_geometry']:
                samples = [(anchor, point) for point in self._area_load_sample_points(
                    anchor['points'], anchor['centroid'], 5 if chosen else 3)]
            else:
                samples = sample_region_arrows(region, None, prepared=prepared)[:max(1, min(5, round(275./spacing)))]
            sampled_regions.append(samples)
            visible_samples = samples
            if chosen:
                                                                              
                color = (*anchor['specs'][0]['color'], 0.22)
                for record in region:
                    triangles = self._fan_triangulate(record['points'])
                    base = len(self._pending_load_fill_verts)
                    for tri in triangles:
                        self._pending_load_fill_verts.extend(point.tolist() for point in tri)
                        self._pending_load_fill_colors.extend([color] * 3)
                    self._pending_load_fill_faces.extend(
                        [base + 3*i, base + 3*i + 1, base + 3*i + 2]
                        for i in range(len(triangles)))
                if mode != 'every_area':
                    boundary_color = (*anchor['specs'][0]['color'], 0.8)
                    for a, b in region_boundary_edges(region, prepared=prepared):
                        self._pending_load_line_pos.extend([a.tolist(), b.tolist()])
                        self._pending_load_line_colors.extend([boundary_color] * 2)
            for component, spec in enumerate(anchor['specs']):
                direction = spec['direction']
                magnitude = spec['magnitude']
                log_scale = min(2.0, 0.4 + np.log10(max(1.0, magnitude)) * 0.2)
                nominal_len = max(log_scale * region_size * 0.45, region_size * 0.18)
                max_pixels = max(24.0, spacing * 0.6)
                seed = np.array([1., 0., 0.]) if abs(direction[2]) > 0.8 else np.array([0., 0., 1.])
                side = np.cross(direction, seed)
                norm = np.linalg.norm(side)
                side = side / norm if norm > 1e-9 else np.zeros(3)
                color = (*spec['color'], 1.0 if chosen else 0.35)

                def surface(record):
                    section = record['section']
                    thickness = (getattr(section, 'membrane_thickness', getattr(section, 'thickness', 0.2))
                                 if getattr(self, 'view_extruded', False) else 0.0)
                    offset = record['normal'] * (thickness / 2 + record['shell_size'] * 0.005)
                    return -offset if np.dot(direction, record['normal']) > 0 else offset

                for record, point in visible_samples:
                    actual_direction = record['specs'][component]['direction']
                    tip = point + surface(record)
                    arrow_len = nominal_len
                    tail = tip - actual_direction * arrow_len
                    line_index = len(self._pending_load_line_pos)
                    self._area_load_dynamic_arrows.append(dict(index=line_index,
                        tip=tip.copy(), direction=actual_direction.copy(), side=side.copy(),
                        nominal=nominal_len, maximum=max_pixels, minimum=24.,
                        head=.28 if chosen else 0., wing=.4))
                    self._pending_load_line_pos.extend([tail.tolist(), tip.tolist()])
                    self._pending_load_line_colors.extend([color] * 2)
                    if chosen:
                        head_len = arrow_len * 0.28
                        base = tip - actual_direction * head_len
                        plus = minus = head_len * .4
                        self._pending_load_line_pos.extend([tip.tolist(), (base + side * plus).tolist(),
                                                           tip.tolist(), (base - side * minus).tolist()])
                        self._pending_load_line_colors.extend([color] * 4)
                if not chosen or mode == 'hidden':
                    continue
                if spec['kind'] == 'uniform':
                    display_val = magnitude * unit_registry.force_scale / unit_registry.length_scale ** 2
                    units = f'{unit_registry.force_unit_name}/{unit_registry.length_unit_name}\u00b2'
                else:
                    display_val, units = magnitude, '\u00d7g'
                formatted = f'{display_val:.2f}'
                key = (spec['kind'], spec['pattern'], spec['direction_name'], formatted)
                if mode == 'smart' and (len(rounded_values[key]) > 1 or
                                        (display_val != 0 and float(formatted) == 0)):
                    formatted = repr(float(display_val))
                text = f'{formatted} {units}'
                if len(patterns) > 1:
                    text = f"{spec['pattern']}: {text}"
                right = np.cross([0., 0., 1.], direction)
                length = np.linalg.norm(right)
                right = right / length if length >= 0.1 else np.array([1., 0., 0.])
                origin = anchor_point + surface(anchor)
                annotations.append(dict(owner_id=anchor['area_id'], owner_type='area',
                                        owner_ids=tuple(record['area_id'] for record in region),
                                        group_count=len(region), leader_anchor=origin.tolist(),
                                        pos_3d=(origin + np.array([0., 0., 1.]) *
                                                (.36 + component*.30) * self._load_text_scale()).tolist(),
                                        text=text, val=magnitude, color=[*spec['color'], 1.0],
                                        v_right=right.tolist(), v_up=[0., 0., 1.],
                                        align='center', text_height=0.22))
        self._area_load_view_samples = sampled_regions
        annotations, leaders = self._place_fixed_load_labels(annotations, mode, mvp, w, h)
        self._area_load_annotations = annotations
        self._area_load_label_leaders = leaders
        for start, finish, color in leaders:
            self._area_load_dynamic_leaders.append((len(self._pending_load_line_pos), start.copy()))
            self._pending_load_line_pos.extend([start.tolist(), finish.tolist()])
            self._pending_load_line_colors.extend([color] * 2)
        self.load_labels.extend(annotations)
        self._area_load_view_key = None if mvp is None else (mvp.tobytes(), w, h)
        self._cache_load_view_geometry(mvp=mvp, width=w, height=h)

    def _place_fixed_load_labels(self, annotations, mode, mvp, width, height):
        if mode != 'smart' or mvp is None:
            return annotations, []
        obstacles = self._scaled_load_labels() + getattr(self, 'force_labels', []) + getattr(self, 'grid_labels', [])
        tagged = [dict(item, _layout_index=i) for i, item in enumerate(annotations)]
        placed, leaders = layout_load_labels(tagged, obstacles, mvp, width, height, self._load_text_scale())
        by_index = {item.pop('_layout_index'): item for item in placed}
                                                                             
        return [by_index.get(i, item) for i, item in enumerate(annotations)], leaders

    def _cache_load_view_geometry(self, include_areas=True, mvp=None, width=None, height=None):
        """Build camera data after sampling and annotation layout are complete."""
        frame_base = getattr(self, '_frame_load_display_base', None)
        include_frames = (frame_base is not None and
                          getattr(self, '_frame_load_display_model', None) is self.current_model)
        arrows = list(getattr(self, '_area_load_dynamic_arrows', [])) if include_areas else []
        profiles = []
        leaders = list(getattr(self, '_area_load_dynamic_leaders', [])) if include_areas else []
        if include_frames:
            arrows.extend(getattr(self, '_frame_load_dynamic_arrows', []))
            profiles = getattr(self, '_frame_load_dynamic_profiles', [])
            leaders.extend(getattr(self, '_frame_load_dynamic_leaders', []))
        label_start = (frame_base if include_frames else self._area_load_display_base)['labels']
        self._load_view_geometry = LoadViewGeometry(self, arrows, profiles, leaders, label_start)
        if mvp is not None:
            cache = self._load_view_geometry
            self.load_labels = cache.update(mvp, width, height)
            self._pending_load_fill_verts = cache.fill_positions
            self._pending_load_line_pos = cache.line_positions
            self._pending_load_line_colors = cache.line_colors

    def _thaw_load_view_geometry(self):
        """Topology edits use lists; the camera path keeps reusable NumPy arrays."""
        cache = getattr(self, '_load_view_geometry', None)
        if cache is not None and self._pending_load_line_colors is cache.line_colors:
            self._pending_load_line_colors = cache.original_colors.tolist()
        for name in _BUFFERS:
            value = getattr(self, name)
            if isinstance(value, np.ndarray):
                setattr(self, name, value.tolist())

    def _update_cached_load_view(self, mvp, width, height):
        cache = getattr(self, '_load_view_geometry', None)
        if cache is None:
            return False
        manager = getattr(self, 'vbo_manager', None)
        update_factors = getattr(manager, 'update_load_view_factors', None)
        if update_factors is not None and getattr(manager, '_load_view_gpu_active', False):
            self.makeCurrent()
            if update_factors(cache.profile_scales(mvp, width, height), width, height):
                return True
        self.load_labels = cache.update(mvp, width, height)
        self._pending_load_fill_verts = cache.fill_positions
        self._pending_load_line_pos = cache.line_positions
        self._pending_load_line_colors = cache.line_colors
        update_positions = getattr(manager, 'update_load_positions', None)
        if update_positions is not None:
            self.makeCurrent()
            updated = update_positions(cache.fill_positions, cache.line_positions,
                                       line_colors=cache.line_colors)
        else:
            updated = False
        if not updated:
            self._upload_loads_to_vbo(refresh_tributary=False)
        return True

    def _refresh_area_load_view(self, mvp, width, height):
        """Preserve samples and label placement through all camera changes."""
        model = getattr(self, 'current_model', None)
        if (not self.show_loads or model is None or getattr(model, 'has_results', False)
                or getattr(self, '_area_load_display_model', None) is not model
                or not getattr(self, '_area_load_display_base', None)):
            return
        changed = tuple(sorted(self.selected_area_ids)) != self._area_load_selection
        key = (np.asarray(mvp, dtype=float).tobytes(), width, height)
        if not changed:
            if key != self._area_load_view_key:
                self._update_cached_load_view(mvp, width, height)
                self._area_load_view_key = key
            return
        self._thaw_load_view_geometry()
        for name in _BUFFERS:
            del getattr(self, name)[self._area_load_display_base[name]:]
        del self.load_labels[self._area_load_display_base['labels']:]
        self._draw_area_loads(model)
        self._upload_loads_to_vbo()
        self._upload_load_labels_to_gpu()
