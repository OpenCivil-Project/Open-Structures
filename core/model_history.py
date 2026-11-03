"""Persistent branching history for complete OpenCivil model input snapshots.

This module has no Qt or solver dependencies. History is stored beside a model as
``<model>.history.sqlite3``. Call ``record_file`` only after a successful project
save; temporary solver copies must not be recorded as user saves.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import zlib
from datetime import datetime, timezone
from uuid import uuid4

FORMAT_VERSION = 1
HISTORY_SUFFIX = ".history.sqlite3"

class HistoryError(RuntimeError):
    """An operation could not safely read or update model history."""

class FormatError(HistoryError):
    """The model or history format is invalid or unsupported."""

class CorruptHistoryError(HistoryError):
    """A stored snapshot failed its integrity check."""

def _reject_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")

def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result

def _parse_model(raw):
    try:
        data = json.loads(raw.decode("utf-8-sig"),
                          parse_constant=_reject_constant,
                          object_pairs_hook=_object_pairs)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise FormatError(f"The model is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
        raise FormatError("A model snapshot must be a JSON object with an 'info' object.")
    return data

def _normalise_numbers(value):
                                                                          
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FormatError("Model snapshots cannot contain non-finite numbers.")
        return int(value) if value.is_integer() else value
    if isinstance(value, dict):
        return {key: _normalise_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise_numbers(item) for item in value]
    return value

def _canonical_bytes(data):
                                                                        
    return json.dumps(data, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"

def _content_hash(data):
    return hashlib.sha256(_canonical_bytes(_normalise_numbers(data))).hexdigest()

def _equal(before, after):
    if isinstance(before, bool) or isinstance(after, bool):
        return type(before) is type(after) and before == after
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return before == after
    if type(before) is not type(after):
        return False
    if isinstance(before, dict):
        return before.keys() == after.keys() and all(
            _equal(before[key], after[key]) for key in before)
    if isinstance(before, list):
        return len(before) == len(after) and all(
            _equal(a, b) for a, b in zip(before, after))
    return before == after

def _short(value, length=110):
    value = str(value)
    return value if len(value) <= length else value[:length - 1] + "…"

def _brief(value):
    if isinstance(value, dict):
        return f"object ({len(value)} fields)"
    if isinstance(value, list):
        return f"list ({len(value)} items)"
    return _short(json.dumps(value, ensure_ascii=False, allow_nan=False))

def _field_path(path, key):
    if re.fullmatch(r"[A-Za-z_]\w*", key):
        return f"{path}.{key}" if path else key
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"

def _identity_key(before, after):
    records = before + after
    if not records or not all(isinstance(record, dict) for record in records):
        return None
    for key in ("id", "name"):
        if not all(key in record and isinstance(record[key], (str, int))
                   and not isinstance(record[key], bool) for record in records):
            continue
                                                                               
        identities = [[(type(record[key]), record[key]) for record in side]
                      for side in (before, after)]
        if all(len(set(side)) == len(side) for side in identities):
            return key
    return None

def describe_changes(before, after, limit=80):
    """Describe arbitrary JSON changes, preserving order in unidentified arrays.

    Unique record IDs/names support readable entity comparisons. Long numeric
    arrays get a bounded summary rather than one row for every sample.
    """
    limit = max(1, int(limit))
    changes = []
    clipped = False

    def add(message):
        nonlocal clipped
        if len(changes) < limit:
            changes.append(_short(message, 440))
        else:
            clipped = True

    def walk(old, new, path):
        if clipped or _equal(old, new):
            return
        display = _short(path or "Model", 280)
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                child = _field_path(path, key)
                if key not in old:
                    add(f"+ {child}: {_brief(new[key])}")
                elif key not in new:
                    add(f"− {child}: {_brief(old[key])}")
                else:
                    walk(old[key], new[key], child)
                if clipped:
                    break
        elif isinstance(old, list) and isinstance(new, list):
            identity = _identity_key(old, new)
            if identity:
                old_map = {(type(item[identity]), item[identity]): item for item in old}
                new_map = {(type(item[identity]), item[identity]): item for item in new}
                keys = list(old_map) + [key for key in new_map if key not in old_map]
                for key in keys:
                    child = f"{path}[{identity}={_brief(key[1])}]"
                    if key not in old_map:
                        add(f"+ {child}: {_brief(new_map[key])}")
                    elif key not in new_map:
                        add(f"− {child}: {_brief(old_map[key])}")
                    else:
                        walk(old_map[key], new_map[key], child)
                    if clipped:
                        break
                if not clipped and list(old_map) != list(new_map) and old_map.keys() == new_map.keys():
                    add(f"{display}: record order changed")
            elif max(len(old), len(new)) > 64:
                first = next((i for i, pair in enumerate(zip(old, new))
                              if not _equal(*pair)), min(len(old), len(new)))
                detail = ""
                if first < min(len(old), len(new)):
                    detail = f"; first difference [{first}]: {_brief(old[first])} → {_brief(new[first])}"
                add(f"{display}: list changed ({len(old)} → {len(new)} items){detail}")
            else:
                for index in range(max(len(old), len(new))):
                    child = f"{path}[{index}]"
                    if index >= len(old):
                        add(f"+ {child}: {_brief(new[index])}")
                    elif index >= len(new):
                        add(f"− {child}: {_brief(old[index])}")
                    else:
                        walk(old[index], new[index], child)
                    if clipped:
                        break
        else:
            add(f"{display}: {_brief(old)} → {_brief(new)}")

    walk(before, after, "")
    if clipped:
        changes[-1] = "Further changes omitted."
    return changes

class HistoryStore:
    """A model's persistent snapshot graph and selected working point."""

    def __init__(self, model_path):
        self.model_path = Path(model_path).resolve()
        self.path = Path(str(self.model_path) + HISTORY_SUFFIX)

    @property
    def exists(self):
        return self.path.is_file()

    def _connect(self, write=False):
        connection = None
        try:
            if write:
                connection = sqlite3.connect(str(self.path), timeout=30,
                                             isolation_level=None)
                connection.execute("PRAGMA synchronous=FULL")
            else:
                connection = sqlite3.connect(self.path.as_uri() + "?mode=ro",
                                             uri=True, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            return connection
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise HistoryError(f"Cannot open model history: {exc}") from exc

    @staticmethod
    def _schema(connection, create=False):
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not tables and create:
            statements = [
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE snapshots (content_hash TEXT PRIMARY KEY, payload BLOB NOT NULL, "
                "checksum TEXT NOT NULL, raw_size INTEGER NOT NULL)",
                "CREATE TABLE commits (sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, "
                "parent_id TEXT REFERENCES commits(id), created_at TEXT NOT NULL, label TEXT NOT NULL, "
                "branch TEXT NOT NULL, content_hash TEXT NOT NULL REFERENCES snapshots(content_hash), "
                "summary TEXT NOT NULL)",
                "CREATE TABLE branches (name TEXT PRIMARY KEY, head_id TEXT NOT NULL REFERENCES commits(id))",
                "CREATE TABLE working_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                "current_commit TEXT REFERENCES commits(id), active_branch TEXT REFERENCES branches(name))",
            ]
            for statement in statements:
                connection.execute(statement)
            connection.execute("INSERT INTO metadata VALUES ('format_version', ?)", (str(FORMAT_VERSION),))
            connection.execute("INSERT INTO working_state VALUES (1, NULL, NULL)")
            return
        required = {"metadata", "snapshots", "commits", "branches", "working_state"}
        if not required.issubset(tables):
            raise FormatError("This file is not a valid OpenCivil model history database.")
        row = connection.execute("SELECT value FROM metadata WHERE key='format_version'").fetchone()
        if row is None or row[0] != str(FORMAT_VERSION):
            raise FormatError(f"Unsupported history format; expected version {FORMAT_VERSION}.")

    @staticmethod
    def _state(connection):
        row = connection.execute("SELECT current_commit, active_branch FROM working_state WHERE singleton=1").fetchone()
        if row is None:
            raise CorruptHistoryError("History has no working-state record.")
        return {"current_commit": row[0], "active_branch": row[1],
                "branches": {item[0]: item[1] for item in connection.execute(
                    "SELECT name, head_id FROM branches ORDER BY name")}}

    @staticmethod
    def _commit(connection, commit_id):
        row = connection.execute(
            "SELECT id, parent_id, created_at, label, branch, content_hash, summary FROM commits WHERE id=?",
            (commit_id,)).fetchone()
        if row is None:
            raise HistoryError(f"Unknown history point: {commit_id}")
        return dict(row)

    @staticmethod
    def _snapshot(connection, commit_id):
        commit = HistoryStore._commit(connection, commit_id)
        return HistoryStore._stored_snapshot(connection, commit["content_hash"])

    @staticmethod
    def _stored_snapshot(connection, digest):
        row = connection.execute("SELECT payload, checksum, raw_size FROM snapshots WHERE content_hash=?",
                                 (digest,)).fetchone()
        if row is None:
            raise CorruptHistoryError("The selected point has no stored snapshot.")
        try:
            raw = gzip.decompress(row[0])
        except (OSError, EOFError, ValueError, TypeError, zlib.error) as exc:
            raise CorruptHistoryError("The stored snapshot cannot be decompressed.") from exc
        if len(raw) != row[2] or hashlib.sha256(raw).hexdigest() != row[1]:
            raise CorruptHistoryError("The stored snapshot failed its checksum check.")
        try:
            data = _parse_model(raw)
            if _content_hash(data) != digest:
                raise CorruptHistoryError("The snapshot does not match its recorded content hash.")
        except FormatError as exc:
            raise CorruptHistoryError(f"The stored snapshot is invalid: {exc}") from exc
        return raw, data

    def _read(self, operation):
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            self._schema(connection)
            return operation(connection)
        except sqlite3.Error as exc:
            raise HistoryError(f"Cannot read model history: {exc}") from exc
        finally:
            connection.close()

    def _write(self, operation, create=False):
        if not create and not self.exists:
            raise HistoryError("This model has no saved history yet.")
        connection = self._connect(write=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._schema(connection, create=create)
            result = operation(connection)
            connection.commit()
            return result
        except sqlite3.Error as exc:
            connection.rollback()
            raise HistoryError(f"Cannot update model history: {exc}") from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def state(self):
        if not self.exists:
            return {"current_commit": None, "active_branch": None, "branches": {}}
        return self._read(self._state)

    def list_commits(self):
        if not self.exists:
            return []
        return self._read(lambda connection: [dict(row) for row in connection.execute(
            "SELECT id, parent_id, created_at, label, branch, content_hash, summary FROM commits ORDER BY sequence")])

    def record_file(self, label="Saved model"):
        """Record the current saved file, forking if working before a branch tip.

        The returned commit includes ``created`` and ``auto_branch`` booleans.
        Repeated saves with identical JSON values reuse the current commit.
        """
        if not self.exists:
                                                                           
            self._read_model()

        def record(connection):
            data = self._read_model()
            digest = _content_hash(data)
            state = self._state(connection)
            current = state["current_commit"]
            old_data = None
            if current:
                _, old_data = self._snapshot(connection, current)
                previous = self._commit(connection, current)
                if digest == previous["content_hash"]:
                    return {**previous, "created": False, "auto_branch": False}

            active = state["active_branch"]
            auto_branch = False
            if not current and not state["branches"]:
                active = "main"
            elif active is None or state["branches"].get(active) != current:
                number = 1
                while f"branch-{number}" in state["branches"]:
                    number += 1
                active = f"branch-{number}"
                auto_branch = True

            raw = _canonical_bytes(data)
            existing = connection.execute("SELECT 1 FROM snapshots WHERE content_hash=?", (digest,)).fetchone()
            if existing:
                                                                                
                self._stored_snapshot(connection, digest)
            else:
                connection.execute(
                    "INSERT INTO snapshots VALUES (?, ?, ?, ?)",
                    (digest, gzip.compress(raw, mtime=0), hashlib.sha256(raw).hexdigest(), len(raw)))
            commit_id = uuid4().hex
            created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            changes = describe_changes(old_data, data, limit=8) if old_data is not None else []
            summary = "; ".join(changes) if changes else "Initial model snapshot"
            connection.execute(
                "INSERT INTO commits (id, parent_id, created_at, label, branch, content_hash, summary) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (commit_id, current, created_at, str(label).strip() or "Saved model", active, digest, summary))
            connection.execute(
                "INSERT INTO branches (name, head_id) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET head_id=excluded.head_id", (active, commit_id))
            connection.execute("UPDATE working_state SET current_commit=?, active_branch=? WHERE singleton=1",
                               (commit_id, active))
            return {**self._commit(connection, commit_id), "created": True, "auto_branch": auto_branch}

        return self._write(record, create=True)

    def _read_model(self):
        try:
            return _parse_model(self.model_path.read_bytes())
        except OSError as exc:
            raise HistoryError(f"Cannot read the saved model: {exc}") from exc

    def get_snapshot(self, commit_id):
        return self._read(lambda connection: self._snapshot(connection, commit_id)[1])

    def snapshot_bytes(self, commit_id):
        return self._read(lambda connection: self._snapshot(connection, commit_id)[0])

    def select_commit(self, commit_id, branch=None):
        def select(connection):
            self._snapshot(connection, commit_id)
            state = self._state(connection)
            selected_branch = branch
            if branch is not None:
                if state["branches"].get(branch) != commit_id:
                    raise HistoryError("The selected branch does not point to this history point.")
            else:
                matching = [name for name, head in state["branches"].items() if head == commit_id]
                if state["active_branch"] in matching:
                    selected_branch = state["active_branch"]
                elif "main" in matching:
                    selected_branch = "main"
                elif matching:
                    selected_branch = matching[0]
            connection.execute("UPDATE working_state SET current_commit=?, active_branch=? WHERE singleton=1",
                               (commit_id, selected_branch))
        self._write(select)

    def create_branch(self, name, commit_id):
        name = str(name).strip()
        if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
            raise HistoryError("Use a branch name of 1–100 characters without control characters.")

        def create(connection):
            self._snapshot(connection, commit_id)
            if connection.execute("SELECT 1 FROM branches WHERE name=?", (name,)).fetchone():
                raise HistoryError(f"A branch named '{name}' already exists.")
            connection.execute("INSERT INTO branches VALUES (?, ?)", (name, commit_id))
            connection.execute("UPDATE working_state SET current_commit=?, active_branch=? WHERE singleton=1",
                               (commit_id, name))
            return name
        return self._write(create)

    def copy_to(self, new_model_path):
        """Copy a consistent SQLite history snapshot without replacing a sidecar."""
        if not self.exists:
            raise HistoryError("This model has no saved history to copy.")
        destination = HistoryStore(new_model_path)
        source_connection = self._connect()
        target_connection = None
        claimed = False
        complete = False
        try:
            self._schema(source_connection)
                                                                              
            with destination.path.open("xb"):
                pass
            claimed = True
            target_connection = sqlite3.connect(str(destination.path), timeout=30)
            source_connection.backup(target_connection)
            target_connection.commit()
            self._schema(target_connection)
            complete = True
        except (OSError, sqlite3.Error) as exc:
            raise HistoryError(f"Cannot copy model history: {exc}") from exc
        finally:
            if target_connection is not None:
                target_connection.close()
            source_connection.close()
            if claimed and not complete:
                destination.path.unlink(missing_ok=True)
        return destination

def atomic_save_model(model, filepath, progress=None):
    """Serialize to a temporary sibling and replace the model only on success."""
    filepath = Path(filepath).resolve()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{filepath.stem}-save-",
                                              suffix=filepath.suffix or ".mf",
                                              dir=str(filepath.parent))
    os.close(descriptor)
    try:
        model.save_to_file(temporary, progress=progress)
                                                                               
        _parse_model(Path(temporary).read_bytes())
        with open(temporary, "r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, filepath)
    finally:
        Path(temporary).unlink(missing_ok=True)
