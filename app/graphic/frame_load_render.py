"""Continuous display of independently assigned distributed frame loads."""
import numpy as np

from .frame_load_display import (frame_load_components, build_frame_load_chains,
                                 prepare_frame_load_chain, sample_frame_load_arrows)
from core.units import unit_registry

_BUFFERS = ('_pending_load_fill_verts', '_pending_load_fill_colors',
            '_pending_load_fill_faces', '_pending_load_line_pos', '_pending_load_line_colors')

class FrameLoadDisplayMixin:
    def _draw_member_loads(self, model):
        self._thaw_load_view_geometry()
        self._load_view_geometry = None
        self._frame_load_display_model = model
        self._frame_load_selection = tuple(sorted(self.selected_element_ids))
        self._frame_load_display_base = {name: len(getattr(self, name)) for name in _BUFFERS}
        self._frame_load_display_base['labels'] = len(self.load_labels)
        self._frame_load_chains = []
        self._frame_load_prepared = []
        self._frame_load_view_samples = []
        self._frame_load_annotations = []
        self._frame_load_label_leaders = []
        self._frame_load_dynamic_arrows = []
        self._frame_load_dynamic_profiles = []
        self._frame_load_dynamic_leaders = []
        self._distributed_load_view_needs_settle = False
        by_frame = {}
        if self.show_loads and self.load_type_filter != 'nodal':
            for load in model.loads:
                if not hasattr(load, 'element_id') or not hasattr(load, 'wx'):
                    continue
                if (getattr(load, 'is_tributary_generated', False)
                        and not getattr(self, 'show_tributary_loads', False)):
                    continue
                if self.visible_load_patterns and load.pattern_name not in self.visible_load_patterns:
                    continue
                by_frame.setdefault(load.element_id, []).append(load)
        selected = set(self.selected_element_ids)
        records = []
                                                                         
        components_cache = {}
        global_axes = np.eye(3)
        for element_id, loads in by_frame.items():
            element = model.elements.get(element_id)
            if element is None:
                continue
            visibility = tuple(self._end_states('frame', element))
            if min(visibility) == 0:
                continue
            points = np.array([[node.x, node.y, node.z]
                               for node in (element.node_i, element.node_j)], dtype=float)
            length = float(np.linalg.norm(points[1] - points[0]))
            if length <= 1e-9 or not np.isfinite(points).all():
                continue
            local = any(str(getattr(load, 'coord_system', 'Global')).upper() == 'LOCAL'
                        for load in loads)
            axes = (np.asarray(self._get_consistent_axes(element), dtype=float)
                    if local else global_axes)
            profiles = []
            for load in loads:
                try:
                    relative = bool(getattr(load, 'is_relative', True))
                    coord = str(getattr(load, 'coord_system', 'Global')).upper()
                    distances = getattr(load, 'distances', None)
                    magnitudes = getattr(load, 'magnitudes', None)
                    key = (load.pattern_name, coord, bool(getattr(load, 'projected', False)),
                           str(getattr(load, 'load_type', 'Force')),
                           str(getattr(load, 'load_direction', 'Gravity')), relative,
                           float(load.wx), float(load.wy), float(load.wz),
                           tuple(() if distances is None else distances),
                           tuple(() if magnitudes is None else magnitudes),
                           None if relative else length,
                           axes.tobytes() if coord == 'LOCAL' else None)
                    components = components_cache.get(key)
                    if components is None:
                        components = frame_load_components(load, length, axes)
                        components_cache[key] = components
                except (ValueError, TypeError):
                    continue
                for component in components:
                    profile = dict(component)
                    profile['pattern'] = load.pattern_name
                    profile['load_type'] = getattr(load, 'load_type', 'Force')
                    profile['direction_name'] = getattr(load, 'load_direction', 'Gravity')
                    profiles.append(profile)
            profiles.sort(key=lambda profile: repr(profile['metadata']))
            if not profiles:
                continue
                                                                         
            if not local:
                beam = (points[1] - points[0]) / length
                for profile in profiles:
                    x, y, z = profile['direction']
                    bx, by, bz = beam
                    cross2 = (by*z-bz*y)**2 + (bz*x-bx*z)**2 + (bx*y-by*x)**2
                    if cross2 < .0001:
                        axes = np.asarray(self._get_consistent_axes(element), dtype=float)
                        break
            records.append(dict(element_id=element_id,
                                node_ids=(element.node_i.id, element.node_j.id),
                                points=points, length=length, axes=axes,
                                selected=element_id in selected, visibility=visibility,
                                section_key=(id(element.section), getattr(element, 'beta_angle', 0.),
                                             getattr(element, 'cardinal_point', 10),
                                             getattr(element, 'rigid_zone_factor', 0.)),
                                offsets=(np.asarray(getattr(element, 'joint_offset_i', np.zeros(3))),
                                         np.asarray(getattr(element, 'joint_offset_j', np.zeros(3)))),
                                profiles=profiles))
        mode = self.display_config.get('frame_load_display_mode', 'smart')
        self._frame_load_chains = ([[record] for record in records] if mode == 'every_member'
                                   else build_frame_load_chains(records))
        self._frame_load_prepared = [prepare_frame_load_chain(chain) for chain in self._frame_load_chains]
        self._render_frame_load_chains()

    def _render_frame_load_chains(self, mvp=None, width=None, height=None, interactive=False):
        """Build fixed model-space geometry only when assignments change."""
        project, mvp, w, h = self._area_load_projection(mvp, width, height)
        self._frame_load_dynamic_arrows = []
        self._frame_load_dynamic_profiles = []
        self._frame_load_dynamic_leaders = []
        self._frame_load_view_samples = []
        mode = self.display_config.get('frame_load_display_mode', 'smart')
        if mode == 'every_member':
            self._draw_member_loads_legacy(self._frame_load_display_model)
        else:
            spacing = float(self.display_config.get('area_load_arrow_spacing', 55.))
            spacing = float(np.clip(spacing, 20, 150)) if np.isfinite(spacing) else 55.
            sample_count = max(1, min(5, round(275. / spacing)))
            annotations = []
            patterns = {p['pattern'] for chain in self._frame_load_chains for p in chain[0]['profiles']}
            ink = self._theme_ink_rgb()
            q_scale = unit_registry.force_scale / unit_registry.length_scale
            units = f'{unit_registry.force_unit_name}/{unit_registry.length_unit_name}'
            rounded = {}
            for chain, prepared in zip(self._frame_load_chains, self._frame_load_prepared):
                for i, profile in enumerate(chain[0]['profiles']):
                    value = prepared['max_abs'][i] * q_scale
                    key = (profile['pattern'], profile['direction_name'], profile['load_type'], f'{value:.2f}')
                    rounded.setdefault(key, set()).add(value)
            for chain, prepared in zip(self._frame_load_chains, self._frame_load_prepared):
                samples = sample_frame_load_arrows(chain, None, prepared=prepared)[:sample_count]
                self._frame_load_view_samples.append(samples)
                anchor, anchor_t = prepared['representative']
                selected = anchor['selected'] and min(anchor['visibility']) == 2
                ghosted = min(anchor['visibility']) < 2
                color_fill = (*ink, .08 if ghosted else .55 if selected else .25)
                color_line = (*ink, .20 if ghosted else 1. if selected else .60)
                for component, profile in enumerate(anchor['profiles']):
                    peak = prepared['max_abs'][component]
                    if peak < 1e-9:
                        continue
                    height = (min(1.5, .5 + np.log10(max(1., peak)) * .2) if profile['uniform']
                              else min(.6, .2 + np.log10(max(1., peak)) * .1))
                    coefficient = height / peak
                    dynamic = dict(scale_points=[], fill_vertices=[], line_vertices=[])
                    self._frame_load_dynamic_profiles.append(dynamic)
                    vectors = {}
                    for record in chain:
                        current = record['profiles'][component]
                        delta = record['points'][1] - record['points'][0]
                        beam = delta / record['length']
                        direction = current['direction']
                        x, y, z = direction
                        bx, by, bz = beam
                        parallel = ((by*z-bz*y)**2 + (bz*x-bx*z)**2 + (bx*y-by*x)**2) < .0001
                        shift = record['axes'][1] * .5 if parallel else np.zeros(3)
                        side = (np.array([0., z, -y]) if abs(z) > .9
                                else np.array([y, -x, 0.]))
                        side /= np.linalg.norm(side)
                        vectors[id(record)] = (record['points'][0] + shift, delta, direction, side)

                    def geometry(record, t, value):
                        first, delta, direction, _ = vectors[id(record)]
                        return first + t * delta, -direction * value * coefficient

                    for record, span_start, span_end, forward in prepared['spans']:
                        current = record['profiles'][component]
                        values = current['values']
                        positions = current['positions']
                        if (current['affine'] and
                                (values[0] >= 0 and values[-1] >= 0 or
                                 values[0] <= 0 and values[-1] <= 0)):
                                                                             
                            positions = (positions[0], positions[-1])
                            values = (values[0], values[-1])
                        bases, offsets = zip(*(geometry(record, t, value) for t, value
                                              in zip(positions, values)))
                        tops = [base + offset for base, offset in zip(bases, offsets)]
                        start = len(self._pending_load_fill_verts)
                        for i, (base, top, offset, value) in enumerate(zip(bases, tops, offsets, values)):
                            self._pending_load_fill_verts.extend([base.tolist(), top.tolist()])
                            self._pending_load_fill_colors.extend([color_fill] * 2)
                            dynamic['fill_vertices'].append((start + 2*i + 1, base, offset))
                            if abs(value) > 1e-9:
                                dynamic['scale_points'].append((base, current['direction'] * np.sign(value),
                                    abs(value) * coefficient, max(24., spacing * .6) / .9))
                        for i in range(len(bases) - 1):
                            a = start + 2*i
                            self._pending_load_fill_faces.extend([[a, a+2, a+3], [a, a+3, a+1]])
                            line = len(self._pending_load_line_pos)
                            self._pending_load_line_pos.extend([tops[i].tolist(), tops[i+1].tolist()])
                            self._pending_load_line_colors.extend([color_line] * 2)
                            dynamic['line_vertices'].extend([(line, bases[i], offsets[i]),
                                                            (line+1, bases[i+1], offsets[i+1])])
                        if selected:
                            caps = []
                            if span_start <= 1e-8:
                                caps.append(0 if forward else -1)
                            if span_end >= prepared['length'] - 1e-8:
                                caps.append(-1 if forward else 0)
                            for i in caps:
                                line = len(self._pending_load_line_pos)
                                self._pending_load_line_pos.extend([bases[i].tolist(), tops[i].tolist()])
                                self._pending_load_line_colors.extend([color_line] * 2)
                                dynamic['line_vertices'].append((line+1, bases[i], offsets[i]))
                    if not selected:
                        continue
                    for record, t in samples:
                        current = record['profiles'][component]
                        value = float(np.interp(t, current['positions'], current['values'], left=0., right=0.))
                        if abs(value) < 1e-9:
                            continue
                        tip, offset = geometry(record, t, value)
                        direction = current['direction'] * np.sign(value)
                        length = abs(value) * coefficient * .9
                        tail = tip - direction * length
                        side = vectors[id(record)][3] * np.sign(value)
                        head = length * .3
                        base = tip - direction * head
                        self._frame_load_dynamic_arrows.append(dict(index=len(self._pending_load_line_pos),
                            tip=tip, direction=direction, side=side, nominal=length,
                            maximum=max(24., spacing*.6), minimum=0., head=.3, wing=1., profile=dynamic))
                        dynamic['scale_points'].append((tip, direction, abs(value)*coefficient,
                                                        max(24., spacing*.6)/.9))
                        self._pending_load_line_pos.extend([tail.tolist(), tip.tolist(), tip.tolist(),
                            (base+side*head).tolist(), tip.tolist(), (base-side*head).tolist()])
                        self._pending_load_line_colors.extend([(*ink, 1.)] * 6)
                    if mode == 'hidden':
                        continue
                    current_value = float(np.interp(anchor_t, profile['positions'], profile['values'], left=0., right=0.))
                    base, _ = geometry(anchor, anchor_t, current_value)
                    right = prepared['direction'].copy()
                    if right[0] < -.01:
                        right = -right
                    up = np.array([1., 0., 0.]) if abs(right[2]) > .99 else np.array([0., 0., 1.])
                    value = peak * q_scale
                    formatted = f'{value:.2f}'
                    key = (profile['pattern'], profile['direction_name'], profile['load_type'], formatted)
                    if len(rounded[key]) > 1 or (value != 0 and float(formatted) == 0):
                        formatted = repr(float(value))
                    text = f"{'peak ' if not profile['uniform'] else ''}{formatted} {units}"
                    if len(patterns) > 1:
                        text = f"{profile['pattern']}: {text}"
                    annotations.append(dict(owner_id=anchor['element_id'], owner_type='element',
                        owner_ids=tuple(record['element_id'] for record in chain), group_count=len(chain),
                        leader_anchor=base.tolist(), pos_3d=(base + up * (.36 + component*.30) * self._load_text_scale()).tolist(),
                        text=text, val=peak, color=[*ink, 1.], v_right=right.tolist(), v_up=up.tolist(),
                        align='center', text_height=.20))
            annotations, leaders = self._place_fixed_load_labels(annotations, mode, mvp, w, h)
            self._frame_load_annotations = annotations
            self._frame_load_label_leaders = leaders
            for start, end, color in leaders:
                self._frame_load_dynamic_leaders.append((len(self._pending_load_line_pos), start))
                self._pending_load_line_pos.extend([start.tolist(), end.tolist()])
                self._pending_load_line_colors.extend([color] * 2)
            self.load_labels.extend(annotations)
        self._distributed_load_view_key = None if mvp is None else (mvp.tobytes(), w, h)
        self._cache_load_view_geometry(include_areas=False, mvp=mvp, width=w, height=h)

    def _refresh_distributed_load_view(self, mvp, width, height):
        """Camera motion updates coordinates; it never rebuilds the layout."""
        model = getattr(self, 'current_model', None)
        if (not self.show_loads or model is None or getattr(model, 'has_results', False)
                or getattr(self, '_frame_load_display_model', None) is not model
                or not getattr(self, '_frame_load_display_base', None)):
            return
        changed = (tuple(sorted(self.selected_element_ids)) != self._frame_load_selection or
                   tuple(sorted(self.selected_area_ids)) != getattr(self, '_area_load_selection', ()))
        key = (np.asarray(mvp, dtype=float).tobytes(), width, height)
        if not changed:
            if key != self._distributed_load_view_key:
                self._update_cached_load_view(mvp, width, height)
                self._distributed_load_view_key = key
            return
        self._thaw_load_view_geometry()
        for name in _BUFFERS:
            del getattr(self, name)[self._frame_load_display_base[name]:]
        del self.load_labels[self._frame_load_display_base['labels']:]
        self._draw_member_loads(model)
        self._draw_area_loads(model)
        self._upload_loads_to_vbo()
        self._upload_load_labels_to_gpu()
