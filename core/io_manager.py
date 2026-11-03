"""Bounded recent-project history and per-project viewport previews."""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

class RecentProjectsManager:
    DEFAULT_LIMIT = 8
    LIMIT_OPTIONS = (5, 8, 10, 15, 20)

    def __init__(self, storage_dir=None):
        self.docs_dir = os.fspath(storage_dir) if storage_dir is not None else os.path.join(
            os.path.expanduser("~"), "Documents", "OpenStructures"
        )
        self.thumb_dir = os.path.join(self.docs_dir, "Thumbnails")
        self.registry_file = os.path.join(self.docs_dir, "recent_projects.json")
        self.settings_file = os.path.join(self.docs_dir, "recent_projects_settings.json")
                                                                                        
        try:
            os.makedirs(self.thumb_dir, exist_ok=True)
        except OSError as error:
            print(f"Recent projects cache unavailable: {error}")
        settings = self._read_json(self.settings_file, {})
        limit = settings.get("limit", self.DEFAULT_LIMIT) if isinstance(settings, dict) else self.DEFAULT_LIMIT
        self.max_projects = limit if type(limit) is int and limit in self.LIMIT_OPTIONS else self.DEFAULT_LIMIT

    @staticmethod
    def _path_key(path):
        return os.path.normcase(os.path.abspath(os.path.normpath(path)))

    @staticmethod
    def _read_json(path, fallback):
        try:
            with open(path, "r", encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, ValueError, UnicodeError):
            return fallback

    @staticmethod
    def _write_json(path, data):
        temporary_path = None
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=os.path.dirname(path),
                prefix=".recent-", suffix=".tmp", delete=False
            ) as stream:
                temporary_path = stream.name
                json.dump(data, stream, ensure_ascii=False, indent=4)
            os.replace(temporary_path, path)
            return True
        except (OSError, TypeError, ValueError) as error:
            print(f"Could not update recent projects: {error}")
            return False
        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass

    def _load_registry(self):
        raw = self._read_json(self.registry_file, [])
        if not isinstance(raw, list):
            return []
        projects, seen = [], set()
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if not isinstance(path, str) or not path.strip() or "\x00" in path:
                continue
            path = os.path.abspath(os.path.normpath(path))
            key = self._path_key(path)
            if key in seen:
                continue
            seen.add(key)
            filename = os.path.basename(path)
            name = entry.get("name")
                                                                       
            if not isinstance(name, str) or not name.strip() or (
                name == filename and "last_opened" not in entry
            ):
                name = os.path.splitext(filename)[0]
            projects.append({
                "name": name.strip(),
                "path": path,
                "thumbnail": entry.get("thumbnail") if isinstance(entry.get("thumbnail"), str) else "",
                "last_saved": entry.get("last_saved") if isinstance(entry.get("last_saved"), str) else "",
                "last_opened": entry.get("last_opened") if isinstance(entry.get("last_opened"), str) else "",
            })
            if len(projects) >= self.max_projects:
                break
        return projects

    def _save_registry(self, data):
        return self._write_json(self.registry_file, data[:self.max_projects])

    def _thumbnail_path(self, project_path):
        key = self._path_key(project_path).encode("utf-8")
        return os.path.join(self.thumb_dir, hashlib.sha256(key).hexdigest()[:24] + ".png")

    def _save_thumbnail(self, project_path, image):
        if image is None or image.isNull():
            return None
        temporary_path = None
        try:
            os.makedirs(self.thumb_dir, exist_ok=True)
            descriptor, temporary_path = tempfile.mkstemp(prefix=".preview-", suffix=".png", dir=self.thumb_dir)
            os.close(descriptor)
            thumbnail = image.scaled(
                320, 180, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            if not thumbnail.save(temporary_path, "PNG"):
                return None
            thumb_path = self._thumbnail_path(project_path)
            os.replace(temporary_path, thumb_path)
            return thumb_path
        except (OSError, RuntimeError) as error:
            print(f"Could not refresh project preview: {error}")
            return None
        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass

    def _prune_thumbnails(self, projects):
        """Remove only this manager's generated previews, never arbitrary registry paths."""
        used = {self._path_key(p["thumbnail"]) for p in projects if p.get("thumbnail")}
        try:
            for filename in os.listdir(self.thumb_dir):
                if not re.fullmatch(r"[a-f0-9]{24}\.png", filename):
                    continue
                path = os.path.join(self.thumb_dir, filename)
                if self._path_key(path) not in used:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        except OSError:
            pass

    def record_project(self, project_path, project_name=None, image=None, saved=False):
        """Record a successful open/save, preserving the last valid preview on failure."""
        if not project_path:
            return False
        path = os.path.abspath(os.path.normpath(os.fspath(project_path)))
        if "\x00" in path:
            return False
        key = self._path_key(path)
        projects = self._load_registry()
        previous = next((p for p in projects if self._path_key(p["path"]) == key), {})
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        name = project_name.strip() if isinstance(project_name, str) and project_name.strip() else (
            previous.get("name") or os.path.splitext(os.path.basename(path))[0]
        )
        thumbnail = self._save_thumbnail(path, image)
        item = {
            "name": name,
            "path": path,
            "thumbnail": thumbnail or previous.get("thumbnail", ""),
            "last_saved": now if saved else previous.get("last_saved", ""),
            "last_opened": previous.get("last_opened", "") if saved else now,
        }
        projects = [item] + [p for p in projects if self._path_key(p["path"]) != key]
        projects = projects[:self.max_projects]
        if not self._save_registry(projects):
            return False
        self._prune_thumbnails(projects)
        return True

    def save_project_thumbnail(self, project_path, image: QImage, project_name=None):
        """Compatibility entry point for a completed save."""
        return self.record_project(project_path, project_name=project_name, image=image, saved=True)

    def get_recent_projects(self):
        return self._load_registry()

    def set_limit(self, limit):
        if type(limit) is not int or limit not in self.LIMIT_OPTIONS:
            return False
        if not self._write_json(self.settings_file, {"limit": limit}):
            return False
        self.max_projects = limit
        projects = self._load_registry()
        if self._save_registry(projects):
            self._prune_thumbnails(projects)
        return True

    def remove_project(self, project_path):
        key = self._path_key(project_path)
        projects = [p for p in self._load_registry() if self._path_key(p["path"]) != key]
        if not self._save_registry(projects):
            return False
        self._prune_thumbnails(projects)
        return True

    def clear_history(self):
        if not self._save_registry([]):
            return False
        self._prune_thumbnails([])
        return True
