import os
import json
from datetime import datetime
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

class RecentProjectsManager:
    def __init__(self):
                                                                  
        self.docs_dir = os.path.join(os.path.expanduser("~"), "Documents", "OpenStructures")
        self.thumb_dir = os.path.join(self.docs_dir, "Thumbnails")
        self.registry_file = os.path.join(self.docs_dir, "recent_projects.json")
        
        os.makedirs(self.thumb_dir, exist_ok=True)

    def _load_registry(self):
        if os.path.exists(self.registry_file):
            try:
                with open(self.registry_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_registry(self, data):
        try:
            with open(self.registry_file, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving registry: {e}")

    def save_project_thumbnail(self, project_path, image: QImage):
        """Saves a scaled down thumbnail and updates the recent projects JSON."""
        if not project_path or image.isNull():
            return

        safe_name = os.path.basename(project_path).replace(".mf", "") + "_thumb.png"
        thumb_path = os.path.join(self.thumb_dir, safe_name)

        thumbnail = image.scaled(256, 144, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        thumbnail.save(thumb_path, "PNG")

        registry = self._load_registry()
        
        registry = [proj for proj in registry if proj['path'] != project_path]
        
        registry.insert(0, {
            "name": os.path.basename(project_path),
            "path": project_path,
            "thumbnail": thumb_path,
            "last_saved": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

        registry = registry[:10]
        self._save_registry(registry)

    def get_recent_projects(self):
        """Returns the list of recent projects."""
        return self._load_registry()
