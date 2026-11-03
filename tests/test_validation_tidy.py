"""Exercise validation cleanup on disposable trees, never repository data."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from validation import tidy


class ValidationTidyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'validation'
        self.suite = self.root / 'linear_modal'
        self.suite.mkdir(parents=True)
        self.addCleanup(patch.stopall)
        patch.object(tidy, 'ROOT', self.root).start()
        patch.object(tidy, 'SUITES', ('linear_modal',)).start()

    def write(self, relative, payload):
        path = self.suite / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def case(self, name, passed=True):
        folder = Path('cases') / name
        payloads = {
            f'{name}.mf': b'{"nodes": [{"id": 1}]}',
            f'{name}_STATIC_results.json': b'{"status": "SUCCESS", "displacements": {}}',
            f'{name}_MODAL_results.json': b'{"status": "SUCCESS", "frequencies": [1.0]}',
            f'{name}_STATIC_matrices.json': b'{"K": [[123.45]], "T": [[1.0]]}',
            'expected.json': b'{"static": [0.001], "modal": [1.0]}',
            'comparison.json': json.dumps({'static': {'passed': passed},
                                          'modal': {'passed': True}}).encode(),
            'execution.json': b'{"model_sha256": "fixture", "solver_source_sha256": "fixture"}',
        }
        active = {self.write(folder / filename, data): data
                  for filename, data in payloads.items()}
        logs = {self.write(folder / (name + suffix), ('diagnostic ' + suffix).encode()):
                ('diagnostic ' + suffix).encode()
                for suffix in ('_STATIC.log', '_MODAL.log', '_process.log')}
        return {'id': name, 'mf_file': (folder / (name + '.mf')).as_posix()}, active, logs

    def fixture(self):
        good, good_active, good_logs = self.case('good')
        bad, bad_active, bad_logs = self.case('bad', passed=False)
        self.write('manifest.json', json.dumps([good, bad]).encode())
        scratch = {
            self.write('work/probe/input.mf', b'scratch input'): b'scratch input',
            self.write('work/probe/diagnostic.bin', b'\x00\xff\x81scratch'): b'\x00\xff\x81scratch',
            self.write('__pycache__/models.pyc', b'cached bytecode'): b'cached bytecode',
            self.write('baseline_before_node_order_fix/case/results.json', b'historical failure'):
                b'historical failure',
        }
        return {**good_active, **bad_active}, bad_logs, {**good_logs, **scratch}

    def test_dry_run_preserves_every_file_and_reports_only_optional_categories(self):
        self.fixture()
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tidy.main(['--dry-run']), 0)
        after = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual({group['kind'] for group in tidy.plan()},
                         {'scratch', 'before_fix', 'case_logs'})

    def test_cleanup_preserves_active_and_failed_logs_and_verifies_archived_bytes(self):
        active, failed_logs, optional = self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tidy.main([]), 0)
        for path, payload in {**active, **failed_logs}.items():
            self.assertEqual(path.read_bytes(), payload, str(path))
        for path in optional:
            self.assertFalse(path.exists(), str(path))
        self.assertFalse((self.suite / 'work').exists())
        self.assertFalse((self.suite / '__pycache__').exists())
        self.assertFalse((self.suite / 'baseline_before_node_order_fix').exists())

        archived = {}
        report = json.loads((self.root / 'tidy_report.json').read_text())
        self.assertEqual(sum(item['files'] for item in report['archives']), len(optional))
        for item in report['archives']:
            with zipfile.ZipFile(self.root / item['archive']) as archive:
                self.assertIsNone(archive.testzip())
                manifest = json.loads(archive.read('_archive_manifest.json'))
                self.assertTrue(manifest['original_paths_are_relative_to_suite'])
                byte_count = 0
                for relative, expected_digest in manifest['sha256'].items():
                    payload = archive.read(relative)
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_digest)
                    archived[self.suite / relative] = payload
                    byte_count += len(payload)
                self.assertEqual(item['bytes_archived'], byte_count)
        self.assertEqual(archived, optional)
        self.assertEqual(tidy.plan(), [])

    def test_stale_temporary_archive_is_never_overwritten(self):
        self.fixture()
        group = next(group for group in tidy.plan() if group['kind'] == 'case_logs')
        stamp = '20000101_000000'
        stale = self.write('archives/case_logs_' + stamp + '.zip.tmp', b'old interrupted archive')
        with self.assertRaises(FileExistsError):
            tidy.archive_group(group, stamp)
        self.assertEqual(stale.read_bytes(), b'old interrupted archive')
        self.assertTrue(all(path.exists() for path in group['files']))

    def test_source_change_after_archiving_keeps_all_live_files(self):
        self.fixture()
        group = next(group for group in tidy.plan() if group['kind'] == 'case_logs')
        changed = group['files'][0]
        original_digest = tidy.digest
        calls = 0

        def digest(path):
            nonlocal calls
            if path == changed:
                calls += 1
                if calls == 2:
                    changed.write_bytes(b'new diagnostic written during archiving')
            return original_digest(path)

        with patch.object(tidy, 'digest', digest), self.assertRaises(ValueError):
            tidy.archive_group(group, '20000101_000000')
        self.assertEqual(changed.read_bytes(), b'new diagnostic written during archiving')
        self.assertTrue(all(path.exists() for path in group['files']))

    def test_refuses_root_and_outside_paths(self):
        outside = self.root.parent / 'outside.txt'
        outside.write_bytes(b'outside must remain unchanged')
        for path in (outside, self.root, self.root / '..' / 'outside.txt'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                tidy.checked(path)
        self.assertEqual(outside.read_bytes(), b'outside must remain unchanged')

    def test_refuses_internal_links_and_windows_junction_attributes(self):
        directory = self.suite / 'work'
        directory.mkdir()
        child = directory / 'probe.txt'
        child.write_bytes(b'keep')
        original_is_symlink = Path.is_symlink

        def is_symlink(path):
            return path == directory or original_is_symlink(path)

        with patch.object(Path, 'is_symlink', is_symlink):
            with self.assertRaises(ValueError):
                tidy.checked(child)

        original_lstat = tidy.os.lstat

        def lstat(path, *args, **kwargs):
            value = original_lstat(path, *args, **kwargs)
            if Path(path) == directory:
                # Python <3.12 has no Path.is_junction(); Windows reports this
                # directory through FILE_ATTRIBUTE_REPARSE_POINT instead.
                return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400)
            return value

        with patch.object(tidy.os, 'lstat', lstat):
            with self.assertRaises(ValueError):
                tidy.checked(child)
        self.assertEqual(child.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
