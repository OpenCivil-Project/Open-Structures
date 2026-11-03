"""Area load decluttering must preserve assignments and expose exceptions."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "area_load_display", ROOT / "app/graphic/area_load_display.py")
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)

def make_mesh(n, size=8.0):
    records = []
    for row in range(n):
        for col in range(n):
            nodes = (row * (n + 1) + col,
                     row * (n + 1) + col + 1,
                     (row + 1) * (n + 1) + col + 1,
                     (row + 1) * (n + 1) + col)
            xy = ((col, row), (col + 1, row),
                  (col + 1, row + 1), (col, row + 1))
            points = np.array([(x * size / n, y * size / n, 0.0)
                               for x, y in xy])
            centroid = points.mean(axis=0)
            records.append({
                "area_id": row * n + col + 1,
                "node_ids": nodes,
                "points": points,
                "normal": np.array([0.0, 0.0, 1.0]),
                "centroid": centroid,
                "shell_size": float(np.linalg.norm(points - centroid, axis=1).max()),
                "selected": True,
                "section_key": ("slab", 0.0),
                "signature": (("uniform", "Dead", "GLOBAL", "Gravity", 5.0),),
                "specs": [{"direction": np.array([0.0, 0.0, -1.0]),
                           "magnitude": 5.0, "color": (0.1, 0.2, 0.3)}],
            })
    return records

def group_sizes(records):
    return sorted(len(region) for region in display.build_area_load_regions(records))

class AreaLoadRegionsTests(unittest.TestCase):
    def test_dividing_a_uniform_area_keeps_one_region_and_all_assignments(self):
        records = make_mesh(16)
        before = [(record["signature"], record["points"].copy()) for record in records]
        regions = display.build_area_load_regions(records)
        self.assertEqual(len(regions), 1)
        self.assertEqual(len(regions[0]), 256)
        self.assertEqual({id(record) for record in regions[0]}, {id(record) for record in records})
        for record, (signature, points) in zip(records, before):
            self.assertEqual(record["signature"], signature)
            np.testing.assert_array_equal(record["points"], points)

    def test_tiny_unrounded_edit_splits_then_restores_the_child(self):
        records = make_mesh(8)
        child = records[27]
        original = child["signature"]
        child["signature"] = (("uniform", "Dead", "GLOBAL", "Gravity", 5.000001),)
        child["specs"][0]["magnitude"] = 5.000001
        self.assertEqual(group_sizes(records), [1, 63])
        child["signature"] = original
        child["specs"][0]["magnitude"] = 5.0
        self.assertEqual(group_sizes(records), [64])

    def test_an_extra_assignment_makes_a_child_an_exception(self):
        records = make_mesh(4)
        child = records[5]
        child["signature"] += (("uniform", "Dead", "GLOBAL", "Global X", 2.0),)
        child["specs"].append({"direction": np.array([1.0, 0.0, 0.0]),
                               "magnitude": 2.0, "color": (0.1, 0.2, 0.3)})
        self.assertEqual(group_sizes(records), [1, 15])

    def test_pattern_and_signed_pressure_are_part_of_the_group_boundary(self):
        for signature in (
            (("uniform", "Live", "GLOBAL", "Gravity", 5.0),),
            (("uniform", "Dead", "GLOBAL", "Gravity", -5.0),),
            (("gravity", "Dead", "GLOBAL", 0.0, 0.0, -1.0),),
        ):
            with self.subTest(signature=signature):
                records = make_mesh(2)
                records[0]["signature"] = signature
                self.assertEqual(group_sizes(records), [1, 3])

    def test_selection_section_and_insertion_boundaries_are_preserved(self):
        for key, value in (("selected", False),
                           ("section_key", ("other slab", 0.0)),
                           ("section_key", ("slab", 0.15))):
            with self.subTest(key=key, value=value):
                records = make_mesh(2)
                records[0][key] = value
                self.assertEqual(group_sizes(records), [1, 3])

    def test_only_full_shared_edges_connect_regions(self):
        records = make_mesh(2)
        self.assertEqual(group_sizes([records[0], records[1]]), [2])
        self.assertEqual(group_sizes([records[0], records[3]]), [1, 1])
        detached = make_mesh(1)[0]
        detached["node_ids"] = tuple(node + 100 for node in detached["node_ids"])
        detached["area_id"] = 100
        self.assertEqual(group_sizes([records[0], detached]), [1, 1])

    def test_opposite_normals_do_not_merge(self):
        records = make_mesh(2)[:2]
        records[1]["normal"] *= -1
        records[1]["points"] = records[1]["points"][::-1].copy()
        records[1]["node_ids"] = records[1]["node_ids"][::-1]
        self.assertEqual(group_sizes(records), [1, 1])

    def test_equal_named_local_loads_with_different_drawn_directions_stay_separate(self):
        records = make_mesh(2)[:2]
        for record in records:
            record["signature"] = (("uniform", "Dead", "LOCAL", "Local 2", 5.0),)
        records[1]["specs"][0]["direction"] = np.array([1.0, 0.0, 0.0])
        self.assertEqual(group_sizes(records), [1, 1])

    def test_a_fold_does_not_join_one_planar_region(self):
        records = make_mesh(2)[:2]
        child = records[1]
        child["points"][:, 2] = (0.0, 1.0, 1.0, 0.0)
        child["centroid"] = child["points"].mean(axis=0)
        child["normal"] = np.array([-1.0, 0.0, 4.0]) / np.sqrt(17.0)
        self.assertEqual(group_sizes(records), [1, 1])

    def test_coplanarity_does_not_drift_along_a_chain_of_faces(self):
        records = make_mesh(3, size=3.0)[:3]
        elevations = np.array([0.0, 0.7e-8, 2.1e-8, 4.2e-8])
        for record in records:
            points = record["points"]
            points[:, 2] = elevations[points[:, 0].astype(int)]
            record["centroid"] = points.mean(axis=0)
            normal = np.cross(points[1] - points[0], points[2] - points[0])
            record["normal"] = normal / np.linalg.norm(normal)
                                                                        
        self.assertEqual(group_sizes(records), [1, 2])

    def test_invalid_geometry_remains_a_separate_record(self):
        records = make_mesh(2)[:2]
        records[1]["points"][0, 0] = np.nan
        self.assertEqual(group_sizes(records), [1, 1])
        self.assertEqual(display.build_area_load_regions([]), [])

    def test_ring_anchor_belongs_to_an_actual_loaded_face(self):
        records = make_mesh(4, size=4.0)
        ring = [record for k, record in enumerate(records)
                if (k // 4, k % 4) not in {(1, 1), (1, 2), (2, 1), (2, 2)}]
        region = display.build_area_load_regions(ring)[0]
        anchor = display.choose_region_anchor(region)
        self.assertTrue(any(anchor is record for record in ring))
        x, y, _ = anchor["centroid"]
        self.assertFalse(1.0 < x < 3.0 and 1.0 < y < 3.0)

    def test_region_boundaries_exclude_internal_edges_and_preserve_holes(self):
        records = make_mesh(2, size=2.0)
        boundary = display.region_boundary_edges(records)
        self.assertEqual(len(boundary), 8)
        for start, end in boundary:
            self.assertTrue(any(np.isclose(start[axis], side) and np.isclose(end[axis], side)
                                for axis in (0, 1) for side in (0.0, 2.0)))
        records = make_mesh(4, size=4.0)
        ring = [record for k, record in enumerate(records)
                if (k // 4, k % 4) not in {(1, 1), (1, 2), (2, 1), (2, 2)}]
        self.assertEqual(len(display.region_boundary_edges(ring)), 24)
        self.assertEqual(display.region_boundary_edges([]), [])

class AreaLoadSamplingTests(unittest.TestCase):
    @staticmethod
    def project(point):
        return np.asarray(point[:2]) * 30.0

    def test_dense_mesh_uses_pixel_spacing_instead_of_five_arrows_per_child(self):
        records = make_mesh(16)
        samples = display.sample_region_arrows(records, self.project, spacing_px=55.0)
        self.assertGreaterEqual(len(samples), 4)
        self.assertLess(len(samples), 50)
        locations = [self.project(point) for _, point in samples]
        for i, a in enumerate(locations):
            for b in locations[i + 1:]:
                self.assertGreaterEqual(float(np.linalg.norm(a - b)), 55.0 - 1e-7)
        self.assertTrue(all(any(record is candidate for candidate in records)
                            for record, _ in samples))

    def test_spacing_preference_changes_density_at_the_same_font_and_mesh(self):
        records = make_mesh(16)
        dense = display.sample_region_arrows(records, self.project, spacing_px=30.0)
        sparse = display.sample_region_arrows(records, self.project, spacing_px=90.0)
        self.assertGreater(len(dense), len(sparse))

    def test_an_exception_retains_its_own_arrow_even_when_near_a_neighbor(self):
        records = make_mesh(8)
        records[27]["signature"] = (("uniform", "Dead", "GLOBAL", "Gravity", 7.0),)
        regions = display.build_area_load_regions(records)
        exception = next(region for region in regions if len(region) == 1)
        samples = display.sample_region_arrows(exception, self.project, spacing_px=150.0)
        self.assertGreaterEqual(len(samples), 1)
        self.assertTrue(all(record is records[27] for record, _ in samples))

    def test_offscreen_candidates_are_skipped(self):
        self.assertEqual(display.sample_region_arrows(make_mesh(2), lambda point: None), [])

    def test_concave_face_samples_use_an_interior_anchor(self):
        record = make_mesh(1)[0]
        record["points"] = np.array([(0.0, 0.0, 0.0), (3.0, 0.0, 0.0),
                                     (0.1, 0.1, 0.0), (0.0, 3.0, 0.0)])
        record["centroid"] = record["points"].mean(axis=0)
        samples = display.sample_region_arrows([record], self.project, spacing_px=10.0)
        self.assertGreaterEqual(len(samples), 1)

        def inside_triangle(point, triangle):
            p = point[:2]
            a, b, c = triangle[:, :2]
            sides = [np.cross(end - start, p - start)
                     for start, end in ((a, b), (b, c), (c, a))]
            return min(sides) >= -1e-9 or max(sides) <= 1e-9

        triangles = [record["points"][[0, 1, 2]], record["points"][[0, 2, 3]]]
        for _, point in samples:
            self.assertTrue(any(inside_triangle(point, triangle) for triangle in triangles))
        self.assertFalse(any(inside_triangle(record["centroid"], triangle)
                             for triangle in triangles))

    def test_no_projector_fallback_is_bounded_for_a_dense_region(self):
        samples = display.sample_region_arrows(make_mesh(32), None)
        self.assertGreaterEqual(len(samples), 1)
        self.assertLessEqual(len(samples), 64)

class PreparedAreaLoadRegionTests(unittest.TestCase):
    @staticmethod
    def project(point):
        return np.asarray(point[:2]) * 30.0

    def test_prepared_region_matches_uncached_results_and_preserves_input(self):
        records = make_mesh(8)
        before = [(record["points"].copy(), record["centroid"].copy(),
                   record["normal"].copy(), record["signature"],
                   record["specs"][0]["direction"].copy()) for record in records]
        prepared = display.prepare_area_load_region(records)
        self.assertIs(display.choose_region_anchor(records, prepared=prepared),
                      display.choose_region_anchor(records))
        ordinary_edges = display.region_boundary_edges(records)
        prepared_edges = display.region_boundary_edges(records, prepared=prepared)
        self.assertEqual(len(ordinary_edges), len(prepared_edges))
        for ordinary, cached in zip(ordinary_edges, prepared_edges):
            np.testing.assert_array_equal(ordinary, cached)
        for projector in (None, self.project):
            ordinary_samples = display.sample_region_arrows(records, projector, spacing_px=55.0)
            prepared_samples = display.sample_region_arrows(
                records, projector, spacing_px=55.0, prepared=prepared)
            self.assertEqual(len(ordinary_samples), len(prepared_samples))
            for (ordinary_record, ordinary_point), (cached_record, cached_point) in zip(
                    ordinary_samples, prepared_samples):
                self.assertIs(ordinary_record, cached_record)
                np.testing.assert_array_equal(ordinary_point, cached_point)
        for record, (points, centroid, normal, signature, direction) in zip(records, before):
            np.testing.assert_array_equal(record["points"], points)
            np.testing.assert_array_equal(record["centroid"], centroid)
            np.testing.assert_array_equal(record["normal"], normal)
            self.assertEqual(record["signature"], signature)
            np.testing.assert_array_equal(record["specs"][0]["direction"], direction)

    def test_prepared_concave_anchor_is_on_the_actual_loaded_face(self):
        record = make_mesh(1)[0]
        record["points"] = np.array([(0.0, 0.0, 0.0), (3.0, 0.0, 0.0),
                                     (0.1, 0.1, 0.0), (0.0, 3.0, 0.0)])
        record["centroid"] = record["points"].mean(axis=0)
        prepared = display.prepare_area_load_region([record])
        self.assertIs(prepared["anchor_record"], record)
        point = prepared["anchor_point"]
        self.assertFalse(np.allclose(point, record["centroid"]))

        def inside_triangle(triangle):
            p = np.asarray(point[:2])
            a, b, c = triangle[:, :2]
            sides = [np.cross(end - start, p - start)
                     for start, end in ((a, b), (b, c), (c, a))]
            return min(sides) >= -1e-9 or max(sides) <= 1e-9

        self.assertTrue(any(inside_triangle(record["points"][indices])
                            for indices in ([0, 1, 2], [0, 2, 3])))

    def test_batch_projector_is_used_without_per_point_scalar_calls(self):
        class BatchProjector:
            def __init__(self):
                self.batch_calls = 0

            def __call__(self, point):
                raise AssertionError("Batch projection should avoid per-point scalar calls")

            def batch(self, points):
                self.batch_calls += 1
                points = np.asarray(points)
                return np.column_stack((points[:, :2] * 30.0, np.ones(len(points))))

        records = make_mesh(16)
        prepared = display.prepare_area_load_region(records)
        projector = BatchProjector()
        samples = display.sample_region_arrows(records, projector, spacing_px=55.0,
                                               prepared=prepared)
        self.assertGreaterEqual(projector.batch_calls, 1)
        self.assertGreaterEqual(len(samples), 4)
        locations = [self.project(point) for _, point in samples]
        for i, a in enumerate(locations):
            for b in locations[i + 1:]:
                self.assertGreaterEqual(float(np.linalg.norm(a - b)), 55.0 - 1e-7)

    def test_batch_projection_skips_nan_rows_and_keeps_visible_candidates(self):
        class PartialProjector:
            def __call__(self, point):
                raise AssertionError("Valid batch results must not fall back to scalar projection")

            def batch(self, points):
                points = np.asarray(points)
                result = points[:, :2] * 30.0
                result[points[:, 0] >= 2.0] = np.nan
                return result

        records = make_mesh(8)
        samples = display.sample_region_arrows(
            records, PartialProjector(), spacing_px=30.0,
            prepared=display.prepare_area_load_region(records))
        self.assertGreaterEqual(len(samples), 1)
        self.assertTrue(all(point[0] < 2.0 for _, point in samples))

if __name__ == "__main__":
    unittest.main()
