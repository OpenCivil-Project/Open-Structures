"""Operator-only MongoDB -> Firebase Authentication user import.

Preview is the default: MongoDB is read with find() only, Firebase is untouched,
and output contains aggregate counts rather than emails/password hashes/tokens.
--apply explicitly enables Firebase imports. No MongoDB documents are changed.
Admin credentials must live outside this repository and every desktop release.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Iterable

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BCRYPT_HASH = re.compile(r"^\$2[aby]\$(\d{2})\$[./A-Za-z0-9]{53}$")

@dataclass(frozen=True, repr=False)
class Candidate:
    uid: str
    email: str
    display_name: str
    email_verified: bool
    provider: str
    password_hash: bytes | None = None
    google_subject: str | None = None
    photo_url: str | None = None

def candidate_from_document(document: dict) -> tuple[Candidate | None, str]:
    source_uid = document.get("_id")
    uid = str(source_uid) if source_uid is not None else ""
    email = document.get("email")
    provider = document.get("provider", "email")
    if not uid or len(uid) > 128 or not isinstance(email, str):
        return None, "invalid_identity"
    email = email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        return None, "invalid_identity"
    name = str(document.get("name") or "").strip()[:256]
    picture = document.get("picture")
    picture = picture if isinstance(picture, str) and re.match(r"https?://", picture) else None
    if provider == "email":
        password_hash = document.get("password_hash")
        try:
            if isinstance(password_hash, bytes):
                encoded_hash = password_hash.decode("ascii")
            elif isinstance(password_hash, str):
                encoded_hash = password_hash
            else:
                return None, "invalid_password_hash"
            match = BCRYPT_HASH.fullmatch(encoded_hash)
            if not match or not 4 <= int(match.group(1)) <= 31:
                return None, "invalid_password_hash"
        except (UnicodeError, ValueError):
            return None, "invalid_password_hash"
        return Candidate(uid, email, name, document.get("verified") is True, provider,
                         password_hash=encoded_hash.encode("ascii")), "email"
    if provider == "google":
                                                                               
        subject = document.get("google_sub") or document.get("google_subject")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            return None, "google_missing_subject"
        return Candidate(uid, email, name, document.get("verified") is True, provider,
                         google_subject=subject, photo_url=picture), "google"
    return None, "unsupported_provider"

def candidates_from_documents(documents: Iterable[dict], counts: Counter):
    seen_uids, seen_emails, seen_google_subjects = set(), set(), set()
    for document in documents:
        counts["scanned"] += 1
        candidate, reason = candidate_from_document(document)
        if candidate is None:
            counts["skipped_" + reason] += 1
            continue
        if (candidate.uid in seen_uids or candidate.email in seen_emails or
                (candidate.google_subject and candidate.google_subject in seen_google_subjects)):
            counts["skipped_source_collision"] += 1
            continue
        seen_uids.add(candidate.uid)
        seen_emails.add(candidate.email)
        if candidate.google_subject:
            seen_google_subjects.add(candidate.google_subject)
        counts["eligible_" + reason] += 1
        yield candidate

def chunks(values, size):
    pending = []
    for value in values:
        pending.append(value)
        if len(pending) == size:
            yield pending
            pending = []
    if pending:
        yield pending

def import_record(candidate: Candidate, firebase_auth):
    fields = {
        "uid": candidate.uid,
        "email": candidate.email,
        "email_verified": candidate.email_verified,
    }
    if candidate.display_name:
        fields["display_name"] = candidate.display_name
    if candidate.provider == "email":
        fields["password_hash"] = candidate.password_hash
    else:
        provider_fields = {"uid": candidate.google_subject, "provider_id": "google.com",
                           "email": candidate.email}
        if candidate.display_name:
            provider_fields["display_name"] = candidate.display_name
        if candidate.photo_url:
            provider_fields["photo_url"] = candidate.photo_url
            fields["photo_url"] = candidate.photo_url
        fields["provider_data"] = [firebase_auth.UserProvider(**provider_fields)]
    return firebase_auth.ImportUserRecord(**fields)

def import_candidates(candidates, firebase_auth, firebase_app, counts: Counter):
    """Skip existing UID/email/provider identities, then import <=1000 per call."""
    for import_batch in chunks(candidates, 1000):
        existing_uids, existing_emails, existing_subjects = set(), set(), set()
                                                                              
        for lookup_batch in chunks(import_batch, 33):
            identifiers = []
            for candidate in lookup_batch:
                identifiers.extend([firebase_auth.UidIdentifier(candidate.uid),
                                    firebase_auth.EmailIdentifier(candidate.email)])
                if candidate.google_subject:
                    identifiers.append(firebase_auth.ProviderIdentifier(
                        "google.com", candidate.google_subject))
            result = firebase_auth.get_users(identifiers, app=firebase_app)
            for user in result.users:
                existing_uids.add(user.uid)
                if user.email:
                    existing_emails.add(user.email.lower())
                for identity in user.provider_data:
                    if identity.provider_id == "google.com":
                        existing_subjects.add(identity.uid)
        eligible = []
        for candidate in import_batch:
            if (candidate.uid in existing_uids or candidate.email in existing_emails or
                    candidate.google_subject in existing_subjects):
                counts["skipped_firebase_collision"] += 1
            else:
                eligible.append(candidate)
                                                                                
        for provider in ("email", "google"):
            selected = [candidate for candidate in eligible if candidate.provider == provider]
            if not selected:
                continue
            records = [import_record(candidate, firebase_auth) for candidate in selected]
            options = {"app": firebase_app}
            if provider == "email":
                options["hash_alg"] = firebase_auth.UserImportHash.bcrypt()
            result = firebase_auth.import_users(records, **options)
            counts["imported_" + provider] += result.success_count
            counts["firebase_import_failed"] += result.failure_count
                                                                          
def external_admin_key(path: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("Admin credentials must be outside the repository")
    if not resolved.is_file():
        raise ValueError("Admin credential file was not found")
    return resolved

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri-env", default="MONGO_URI",
                        help="Environment variable containing the source URI; never pass URI text")
    parser.add_argument("--mongo-database", default="opencivil")
    parser.add_argument("--mongo-collection", default="users")
    parser.add_argument("--firebase-project-id", help="Explicit Firebase destination project")
    parser.add_argument("--admin-key-file", help="Optional Admin JSON path OUTSIDE the repository; otherwise ADC")
    parser.add_argument("--apply", action="store_true",
                        help="Enable Firebase writes; default only previews MongoDB aggregate counts")
    args = parser.parse_args(argv)
    counts = Counter()
    client = None
    firebase_app = None
    try:
        uri = os.environ.get(args.mongo_uri_env, "")
        if not uri:
            raise ValueError("Source MongoDB environment variable is not set")
        if args.apply and not args.firebase_project_id:
            raise ValueError("--apply requires --firebase-project-id")
        from pymongo import MongoClient
        import certifi
        client = MongoClient(uri, serverSelectionTimeoutMS=10000,
                             connectTimeoutMS=10000, tlsCAFile=certifi.where())
        projection = {"_id": 1, "email": 1, "name": 1, "provider": 1,
                      "verified": 1, "password_hash": 1, "google_sub": 1,
                      "google_subject": 1, "picture": 1}
        documents = client[args.mongo_database][args.mongo_collection].find({}, projection)
        candidates = candidates_from_documents(documents, counts)
        if args.apply:
            import firebase_admin
            from firebase_admin import auth, credentials
            if args.admin_key_file:
                credential = credentials.Certificate(str(external_admin_key(args.admin_key_file)))
            else:
                adc_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
                if adc_path:
                    external_admin_key(adc_path)
                credential = credentials.ApplicationDefault()
            firebase_app = firebase_admin.initialize_app(
                credential, {"projectId": args.firebase_project_id}, name="opencivil-migration")
            import_candidates(candidates, auth, firebase_app, counts)
        else:
            for _ in candidates:
                pass
        print(json.dumps({"mode": "apply" if args.apply else "preview", "counts": dict(counts)}, indent=2))
        return 1 if counts["firebase_import_failed"] else 0
    except Exception:
                                                                              
        print("Migration did not complete. Check source access, dependencies, "
              "external Admin credentials and the explicit destination project. "
              "No credential values or user records were printed.", file=sys.stderr)
        print(json.dumps({"mode": "apply" if args.apply else "preview", "counts": dict(counts)}, indent=2))
        return 1
    finally:
        if client is not None:
            client.close()
        if firebase_app is not None:
            import firebase_admin
            firebase_admin.delete_app(firebase_app)

if __name__ == "__main__":
    raise SystemExit(main())
