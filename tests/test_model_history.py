"""Behavioural tests for persistent branching model history."""

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from core.model_history import (
    CorruptHistoryError, FormatError, HistoryError, HistoryStore,
    atomic_save_model, describe_changes,
)

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.model_path = Path(self.directory.name) / "structure.mf"
        self.store = HistoryStore(self.model_path)
        self.model = {"info": {"name": "Structure", "units": "kN, m, C"},
                      "nodes": [{"id": 1, "x": 0, "z": 3}],
                      "loads": [], "future_setting": {"method": "New feature"}}
        self.write(self.model)

    def write(self, data):
        self.model_path.write_text(json.dumps(data), encoding="utf-8")

    @contextmanager
    def database(self):
        connection = sqlite3.connect(self.store.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def test_initial_history_and_persistence(self):
        self.assertFalse(self.store.exists)
        self.assertEqual(self.store.list_commits(), [])
        first = self.store.record_file("Initial structure")
        self.assertTrue(first["created"])
        self.assertFalse(first["auto_branch"])
        self.assertIsNone(first["parent_id"])
        reopened = HistoryStore(self.model_path)
        self.assertEqual(reopened.state(), {"current_commit": first["id"],
                                          "active_branch": "main",
                                          "branches": {"main": first["id"]}})
        self.assertEqual(reopened.get_snapshot(first["id"]), self.model)
        self.assertEqual(reopened.list_commits()[0]["label"], "Initial structure")

    def test_formatting_and_equal_numeric_values_do_not_create_commits(self):
        first = self.store.record_file()
        reformatted = dict(reversed(list(self.model.items())))
        reformatted["nodes"][0]["z"] = 3.0
        self.model_path.write_text(json.dumps(reformatted, indent=2), encoding="utf-8")
        same = self.store.record_file("Again")
        self.assertFalse(same["created"])
        self.assertEqual(same["id"], first["id"])
        self.assertEqual(len(self.store.list_commits()), 1)

    def test_boolean_and_number_are_different_values(self):
        self.model["flag"] = True
        self.write(self.model)
        first = self.store.record_file()
        self.model["flag"] = 1
        self.write(self.model)
        second = self.store.record_file()
        self.assertTrue(second["created"])
        self.assertNotEqual(first["content_hash"], second["content_hash"])
        self.assertTrue(describe_changes({"flag": True}, {"flag": 1}))

    def test_changed_save_at_old_point_forks_and_preserves_future(self):
        first = self.store.record_file()
        self.model["nodes"][0]["z"] = 4
        self.write(self.model)
        future = self.store.record_file("Higher storey")
        self.store.select_commit(first["id"])
        self.assertIsNone(HistoryStore(self.model_path).state()["active_branch"])
        self.model["nodes"][0]["z"] = 2
        self.write(self.model)
        alternative = self.store.record_file("Lower storey")
        self.assertTrue(alternative["auto_branch"])
        self.assertEqual(alternative["parent_id"], first["id"])
        self.assertEqual(alternative["branch"], "branch-1")
        self.assertEqual(self.store.state()["branches"],
                         {"main": future["id"], "branch-1": alternative["id"]})
        self.assertEqual(self.store.get_snapshot(future["id"])["nodes"][0]["z"], 4)
        self.assertEqual(self.store.get_snapshot(alternative["id"])["nodes"][0]["z"], 2)

    def test_unchanged_save_from_old_point_stays_detached(self):
        first = self.store.record_file()
        self.model["nodes"][0]["z"] = 4
        self.write(self.model)
        self.store.record_file()
        self.store.select_commit(first["id"])
        self.model_path.write_bytes(self.store.snapshot_bytes(first["id"]))
        result = self.store.record_file()
        self.assertFalse(result["created"])
        self.assertFalse(result["auto_branch"])
        self.assertIsNone(self.store.state()["active_branch"])
        self.assertEqual(len(self.store.list_commits()), 2)

    def test_named_branch_selection_and_rejection_leave_state_intact(self):
        first = self.store.record_file()
        self.assertEqual(self.store.create_branch("Trial A", first["id"]), "Trial A")
        self.model["nodes"][0]["z"] = 5
        self.write(self.model)
        second = self.store.record_file()
        self.assertEqual(second["branch"], "Trial A")
        self.assertFalse(second["auto_branch"])
        state = self.store.state()
        with self.assertRaises(HistoryError):
            self.store.create_branch("Trial A", first["id"])
        with self.assertRaises(HistoryError):
            self.store.select_commit(second["id"], branch="main")
        self.assertEqual(self.store.state(), state)
        self.store.select_commit(first["id"], branch="main")
        self.assertEqual(self.store.state()["active_branch"], "main")

    def test_auto_branch_names_avoid_existing_names(self):
        first = self.store.record_file()
        self.store.create_branch("branch-1", first["id"])
        self.model["nodes"][0]["z"] = 4
        self.write(self.model)
        self.store.record_file()
        self.store.select_commit(first["id"], branch="main")
        self.model["nodes"][0]["z"] = 5
        self.write(self.model)
        self.store.record_file()
        self.store.select_commit(first["id"])
        self.model["nodes"][0]["z"] = 6
        self.write(self.model)
        fork = self.store.record_file()
        self.assertEqual(fork["branch"], "branch-2")

    def test_unknown_fields_and_array_order_are_preserved(self):
        self.model["future_setting"]["series"] = [3, 1, 2]
        first_data = copy.deepcopy(self.model)
        self.write(self.model)
        first = self.store.record_file()
        self.model["future_setting"]["series"] = [1, 2, 3]
        self.write(self.model)
        second = self.store.record_file()
        self.assertTrue(second["created"])
        self.assertEqual(self.store.get_snapshot(first["id"]), first_data)
        self.assertEqual(self.store.get_snapshot(second["id"]), self.model)

    def test_unicode_snapshot_bytes_are_safe_for_current_windows_loader(self):
        self.model["info"]["name"] = "İstanbul – çelik 🏗"
        self.write(self.model)
        first = self.store.record_file()
        raw = self.store.snapshot_bytes(first["id"])
        raw.decode("ascii")
        self.assertEqual(json.loads(raw.decode("ascii")), self.model)

    def test_invalid_first_model_does_not_create_history(self):
        for raw in (b"{broken", b"[]", b'{"info":[]}',
                    b'{"info":{},"number":NaN}', b'{"info":{},"info":{}}'):
            self.model_path.write_bytes(raw)
            with self.assertRaises(FormatError):
                self.store.record_file()
            self.assertFalse(self.store.exists)

    def test_payload_and_checksum_corruption_are_detected(self):
        first = self.store.record_file()
        with self.database() as connection:
            payload = connection.execute("SELECT payload FROM snapshots").fetchone()[0]
            connection.execute("UPDATE snapshots SET payload=?", (b"broken",))
        with self.assertRaises(CorruptHistoryError):
            self.store.get_snapshot(first["id"])
        with self.database() as connection:
            connection.execute("UPDATE snapshots SET payload=?, checksum='wrong'", (payload,))
        with self.assertRaises(CorruptHistoryError):
            self.store.snapshot_bytes(first["id"])
        with self.assertRaises(CorruptHistoryError):
            self.store.select_commit(first["id"])

    def test_unknown_database_format_is_rejected(self):
        self.store.record_file()
        with self.database() as connection:
            connection.execute("UPDATE metadata SET value='99' WHERE key='format_version'")
        with self.assertRaises(FormatError):
            self.store.state()
        with self.assertRaises(FormatError):
            self.store.record_file()

    def test_corrupt_previous_content_cannot_be_reused_by_a_new_commit(self):
        original = copy.deepcopy(self.model)
        first = self.store.record_file()
        self.model["nodes"][0]["z"] = 4
        self.write(self.model)
        self.store.record_file()
        state = self.store.state()
        with self.database() as connection:
            connection.execute("UPDATE snapshots SET payload=? WHERE content_hash=?",
                               (b"damaged", first["content_hash"]))
        self.write(original)
        with self.assertRaises(CorruptHistoryError):
            self.store.record_file()
        self.assertEqual(self.store.state(), state)
        self.assertEqual(len(self.store.list_commits()), 2)

    def test_transaction_failure_does_not_advance_head_or_store_snapshot(self):
        self.store.record_file()
        original = self.store.state()
        with self.database() as connection:
            connection.execute("CREATE TRIGGER fail_commit BEFORE INSERT ON commits "
                               "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
        self.model["nodes"][0]["z"] = 8
        self.write(self.model)
        with self.assertRaises(HistoryError):
            self.store.record_file()
        self.assertEqual(self.store.state(), original)
        with self.database() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_concurrent_duplicate_saves_create_one_commit(self):
        with ThreadPoolExecutor(max_workers=6) as workers:
            results = list(workers.map(lambda _: HistoryStore(self.model_path).record_file(), range(12)))
        self.assertEqual(sum(item["created"] for item in results), 1)
        self.assertEqual(len(self.store.list_commits()), 1)
        self.assertEqual(len({item["id"] for item in results}), 1)

    def test_save_as_history_copy_is_independent_and_never_overwrites(self):
        first = self.store.record_file()
        destination_path = Path(self.directory.name) / "copy.mf"
        destination_path.write_bytes(self.model_path.read_bytes())
        copied = self.store.copy_to(destination_path)
        self.assertEqual(copied.state(), self.store.state())
        self.assertEqual(copied.get_snapshot(first["id"]), self.model)
        before = copied.path.read_bytes()
        with self.assertRaises(HistoryError):
            self.store.copy_to(destination_path)
        self.assertEqual(copied.path.read_bytes(), before)
        self.model["nodes"][0]["z"] = 4
        self.write(self.model)
        self.store.record_file()
        self.assertEqual(len(copied.list_commits()), 1)

class DiffTests(unittest.TestCase):
    def test_entities_use_unique_ids_and_names(self):
        before = {"nodes": [{"id": 4, "z": 3}], "materials": [{"name": "Steel", "E": 200}]}
        after = {"nodes": [{"id": 4, "z": 4}], "materials": [{"name": "Steel", "E": 210}]}
        rows = describe_changes(before, after)
        self.assertTrue(any('nodes[id=4].z' in row for row in rows))
        self.assertTrue(any('materials[name="Steel"].E' in row for row in rows))

    def test_duplicate_ids_and_anonymous_loads_use_positions(self):
        old = {"loads": [{"id": 1, "force": 2}, {"id": 1, "force": 3}]}
        new = {"loads": [{"id": 1, "force": 5}, {"id": 1, "force": 3}]}
        self.assertIn("loads[0].force", describe_changes(old, new)[0])
        old = {"loads": [{"target": 2, "force": 3}]}
        new = {"loads": [{"target": 2, "force": 4}]}
        self.assertIn("loads[0].force", describe_changes(old, new)[0])

    def test_record_reorder_is_reported_and_large_series_are_bounded(self):
        old = {"nodes": [{"id": 1}, {"id": 2}]}
        new = {"nodes": [{"id": 2}, {"id": 1}]}
        self.assertEqual(describe_changes(old, new), ["nodes: record order changed"])
        old = {"values": list(range(10000))}
        new = copy.deepcopy(old)
        new["values"][7000] = 99
        rows = describe_changes(old, new)
        self.assertEqual(len(rows), 1)
        self.assertIn("[7000]", rows[0])
        self.assertLess(len(rows[0]), 440)

    def test_diff_limit_and_unknown_keys(self):
        rows = describe_changes({}, {f"unknown_{i}": "x" * 5000 for i in range(50)}, limit=4)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1], "Further changes omitted.")
        self.assertTrue(all(len(row) <= 440 for row in rows))

class AtomicSaveTests(unittest.TestCase):
    def test_failure_retains_original_file_and_cleans_temporary(self):
        class FailingModel:
            def save_to_file(self, filepath, progress=None):
                Path(filepath).write_text("partial", encoding="utf-8")
                raise RuntimeError("simulated serializer failure")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.mf"
            path.write_bytes(b'{"info":{"name":"Original"}}')
            original = path.read_bytes()
            with self.assertRaises(RuntimeError):
                atomic_save_model(FailingModel(), path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_bad_serializer_output_is_rejected_before_replace(self):
        class InvalidModel:
            def save_to_file(self, filepath, progress=None):
                Path(filepath).write_text("{}", encoding="utf-8")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.mf"
            path.write_bytes(b'{"info":{"name":"Original"}}')
            with self.assertRaises(FormatError):
                atomic_save_model(InvalidModel(), path)
            self.assertIn(b"Original", path.read_bytes())
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_success_replaces_file_without_creating_history(self):
        class GoodModel:
            def save_to_file(self, filepath, progress=None):
                if progress:
                    progress("Saving")
                Path(filepath).write_text('{"info":{"name":"Saved"}}', encoding="utf-8")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.mf"
            messages = []
            self.assertIsNone(atomic_save_model(GoodModel(), path, progress=messages.append))
            self.assertEqual(json.loads(path.read_bytes())["info"]["name"], "Saved")
            self.assertEqual(messages, ["Saving"])
            self.assertEqual(list(Path(directory).iterdir()), [path])

if __name__ == "__main__":
    unittest.main()
