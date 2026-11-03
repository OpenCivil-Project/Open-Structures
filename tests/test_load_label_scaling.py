"""Crowded annotations have bounded collision work and exact glyph bounds."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / 'tests'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import app.graphic.load_label_layout as layout
from test_area_load_render import perspective

def annotation(index, position=(0., 0., 0.), height=.2):
    return dict(owner_id=index, owner_type='area', leader_anchor=list(position),
                pos_3d=list(position), text=f'{5. + index / 1000:.3f} kN/m²',
                val=5. + index / 1000, color=[1., 1., 1., 1.],
                v_right=[1., 0., 0.], v_up=[0., 1., 0.],
                align='center', text_height=height, group_count=1)

class LoadLabelScalingTests(unittest.TestCase):
    def test_dense_spatial_cells_and_queries_keep_a_fixed_neighbor_budget(self):
        index = layout._LocalBoxes(1000, 800)
        for _ in range(4096):
            index.append(np.array([180., 180., 300., 240.]))
        neighbors = index.nearby(np.array([180., 180., 300., 240.]))
        self.assertEqual(len(neighbors), layout._NEIGHBOR_LIMIT)
        self.assertTrue(all(len(cell) <= layout._NEIGHBOR_LIMIT for cell in index.cells.values()))

    def test_thousand_distinct_loads_retain_values_with_linear_collision_work(self):
        count = 1024
        sources = [annotation(i, (-3.8 + (i % 32) * 7.6 / 31,
                                  -3.8 + (i // 32) * 7.6 / 31, 0.))
                   for i in range(count)]
        before = copy.deepcopy(sources)
        query_sizes, projection_sizes = [], []
        nearby = layout._LocalBoxes.nearby
        project = layout._project_corners

        def query(index, box):
            result = nearby(index, box)
            query_sizes.append(len(result))
            return result

        def project_batch(clip, width, height):
            projection_sizes.append(1 if clip.ndim == 2 else len(clip))
            return project(clip, width, height)

        with patch.object(layout._LocalBoxes, 'nearby', query),\
                patch.object(layout, '_project_corners', project_batch),\
                patch.object(layout, '_overlap', side_effect=AssertionError('unbounded pairwise scan')):
            placed, _ = layout.layout_load_labels(sources, [], np.diag([.2, .2, .05, 1.]), 1000, 800)
        self.assertEqual(sources, before)
        self.assertEqual(len(placed), count)
        self.assertEqual([item['owner_id'] for item in placed], list(range(count)))
        self.assertEqual([item['val'] for item in placed], [item['val'] for item in sources])
        self.assertTrue(all(item['text_height'] == .2 for item in placed))
        self.assertLessEqual(len(query_sizes), count)
        self.assertLessEqual(max(query_sizes), layout._NEIGHBOR_LIMIT)
        self.assertLessEqual(sum(query_sizes), count * layout._NEIGHBOR_LIMIT)
        self.assertLessEqual(len(projection_sizes), count * 2)
        self.assertLessEqual(max(projection_sizes), 65)

    def test_perspective_bounds_match_known_sdf_quad_with_different_corner_depths(self):
        matrix = perspective()
        source = annotation(1, height=1.)
        source.update(text='AB', align='left', v_up=[0., 0., 1.])
                                                                           
        corners = np.array([[.5, 0., .4], [2.05, 0., .4],
                            [2.05, 0., 1.4], [.5, 0., 1.4]])
        clip = np.c_[corners, np.ones(4)] @ matrix.T
        self.assertGreater(np.ptp(clip[:, 3]), .1)
        ndc = clip[:, :2] / clip[:, 3:4]
        screen = ndc * [400., -300.] + [400., 300.]
        expected = np.r_[screen.min(axis=0), screen.max(axis=0)]
        np.testing.assert_allclose(layout.label_screen_bounds(source, matrix, 800, 600), expected, atol=1e-12)

    def test_moved_perspective_label_keeps_true_glyphs_clear_and_within_48_pixels(self):
        matrix = perspective()
        source = annotation(1, height=.3)
        source['v_up'] = [0., 0., 1.]
        obstacle = dict(source, owner_id=2, text='5.002 kN/m²')
        before = copy.deepcopy(source)
        placed, leaders = layout.layout_load_labels([source], [obstacle], matrix, 800, 600)
        self.assertEqual(source, before)
        self.assertEqual(len(placed), 1)
        self.assertEqual(placed[0]['text_height'], source['text_height'])
        self.assertGreater(len(leaders), 0)
        box = layout.label_screen_bounds(placed[0], matrix, 800, 600)
        other = layout.label_screen_bounds(obstacle, matrix, 800, 600)
        self.assertEqual(layout._overlap(box, other), 0.)
        old_screen = layout._screen(source['pos_3d'], matrix, 800, 600)
        new_screen = layout._screen(placed[0]['pos_3d'], matrix, 800, 600)
        self.assertLessEqual(np.linalg.norm(new_screen[:2] - old_screen[:2]), 48. + 1e-8)

    def test_large_view_retains_all_visible_loads_and_culls_only_offscreen_owners(self):
        sources = [annotation(i, (0., 0., 0.)) for i in range(256)]
        sources += [annotation(i, (100., 0., 0.)) for i in range(256, 512)]
        placed, _ = layout.layout_load_labels(sources, [], np.diag([.2, .2, .05, 1.]), 1000, 800, 1.5)
        self.assertEqual([item['owner_id'] for item in placed], list(range(256)))
        self.assertTrue(all(item['text_height'] == .2 for item in placed))

if __name__ == '__main__':
    unittest.main()
