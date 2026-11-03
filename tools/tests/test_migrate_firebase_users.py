"""Isolated import safety checks; no databases/Firebase services are contacted."""

from collections import Counter
from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "migrate_firebase_users.py"
spec = importlib.util.spec_from_file_location("migration_under_test", SOURCE)
migration = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = migration
spec.loader.exec_module(migration)

def email_document(uid="123", email="example@example.test"):
    return {"_id": uid, "email": email, "name": "Example", "provider": "email",
            "verified": True, "password_hash": "$2b$12$" + "A" * 53}

class FakeAuth:
    class UserImportHash:
        @staticmethod
        def bcrypt():
            return "bcrypt"

    def __init__(self, existing=()):
        self.existing = list(existing)
        self.lookups = []
        self.imports = []

    @staticmethod
    def UidIdentifier(value):
        return ("uid", value)

    @staticmethod
    def EmailIdentifier(value):
        return ("email", value)

    @staticmethod
    def ProviderIdentifier(provider, value):
        return (provider, value)

    @staticmethod
    def ImportUserRecord(**fields):
        return fields

    @staticmethod
    def UserProvider(**fields):
        return fields

    def get_users(self, identifiers, app=None):
        self.lookups.append(identifiers)
        return SimpleNamespace(users=self.existing)

    def import_users(self, records, **options):
        self.imports.append((records, options))
        return SimpleNamespace(success_count=len(records), failure_count=0)

class MigrationSafetyTests(unittest.TestCase):
    def test_email_hash_stays_bytes_and_verification_is_strict(self):
        document = email_document()
        candidate, reason = migration.candidate_from_document(document)
        self.assertEqual(reason, "email")
        self.assertEqual(candidate.uid, "123")
        self.assertIsInstance(candidate.password_hash, bytes)
        self.assertTrue(candidate.email_verified)
        document["verified"] = "false"
        candidate, _ = migration.candidate_from_document(document)
        self.assertFalse(candidate.email_verified)
        self.assertNotIn(candidate.email, repr(candidate))

    def test_malformed_identity_hash_and_google_without_subject_are_skipped(self):
        for document in ({**email_document(), "_id": None},
                         {**email_document(), "password_hash": "plaintext"},
                         {**email_document(), "provider": "google"}):
            candidate, _ = migration.candidate_from_document(document)
            self.assertIsNone(candidate)

    def test_source_email_duplicates_are_skipped(self):
        counts = Counter()
        docs = [email_document("1"), email_document("2", " Example@Example.Test ")]
        self.assertEqual(len(list(migration.candidates_from_documents(docs, counts))), 1)
        self.assertEqual(counts["skipped_source_collision"], 1)

    def test_existing_firebase_email_is_not_overwritten(self):
        existing = SimpleNamespace(uid="different-uid", email="example@example.test", provider_data=[])
        auth = FakeAuth([existing])
        candidate, _ = migration.candidate_from_document(email_document())
        counts = Counter()
        migration.import_candidates([candidate], auth, "test-app", counts)
        self.assertEqual(counts["skipped_firebase_collision"], 1)
        self.assertEqual(auth.imports, [])

    def test_existing_google_subject_is_not_duplicated(self):
        identity = SimpleNamespace(provider_id="google.com", uid="trusted-subject")
        existing = SimpleNamespace(uid="other-uid", email="other@example.test", provider_data=[identity])
        auth = FakeAuth([existing])
        document = {**email_document(), "provider": "google", "google_sub": "trusted-subject"}
        candidate, _ = migration.candidate_from_document(document)
        counts = Counter()
        migration.import_candidates([candidate], auth, "test-app", counts)
        self.assertEqual(counts["skipped_firebase_collision"], 1)
        self.assertFalse(auth.imports)

    def test_batches_respect_lookup_and_import_limits_and_bcrypt(self):
        counts = Counter()
        docs = (email_document(str(index), f"user{index}@example.test") for index in range(1001))
        auth = FakeAuth()
        migration.import_candidates(migration.candidates_from_documents(docs, counts),
                                    auth, "test-app", counts)
        self.assertEqual(counts["imported_email"], 1001)
        self.assertTrue(all(len(identifiers) <= 100 for identifiers in auth.lookups))
        self.assertTrue(all(len(records) <= 1000 for records, _ in auth.imports))
        self.assertTrue(all(options["hash_alg"] == "bcrypt" for _, options in auth.imports))

    def test_admin_key_in_repository_is_rejected_before_read(self):
        with self.assertRaises(ValueError):
            migration.external_admin_key(str(migration.REPOSITORY_ROOT / "fake-admin.json"))

    def test_default_preview_only_reads_mongo_and_prints_aggregate_counts(self):
        operations = []

        class ReadOnlyClient:
            def __init__(self, *_args, **_kwargs):
                pass

            def __getitem__(self, _name):
                return self

            def find(self, query, projection):
                operations.append("find")
                return iter([email_document()])

            def close(self):
                operations.append("close")

        output = io.StringIO()
        fake_modules = {"pymongo": SimpleNamespace(MongoClient=ReadOnlyClient),
                        "certifi": SimpleNamespace(where=lambda: "fake-ca"),
                                                                              
                        "firebase_admin": None}
        with patch.dict(sys.modules, fake_modules),\
                patch.dict(migration.os.environ, {"MONGO_URI": "test-source"}),\
                redirect_stdout(output):
            self.assertEqual(migration.main([]), 0)
        self.assertEqual(operations, ["find", "close"])
        self.assertIn('"mode": "preview"', output.getvalue())
        self.assertNotIn("example@example.test", output.getvalue())
        self.assertNotIn("$2b$", output.getvalue())

if __name__ == "__main__":
    unittest.main()
