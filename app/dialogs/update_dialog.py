import requests
import re
import os
import tempfile
import subprocess
import sys
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QProgressBar, QMessageBox, QApplication)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

CURRENT_VERSION = (0, 7, 82)

class GitHubCheckWorker(QThread):
    """Background thread to ping GitHub without freezing the UI."""
    signal_result = pyqtSignal(bool, str, str) 
    signal_error = pyqtSignal(str)

    def run(self):
        api_url = "https://api.github.com/repos/ShaikhAhmedAzad/OpenCivil/releases/latest"
        try:
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            latest_tag = data.get("tag_name", "") 
            
            match3 = re.search(r'\d+\.\d+\.\d+', latest_tag)
            match2 = re.search(r'\d+\.\d+', latest_tag)
            
            if match3:
                v_str = match3.group()
                latest_version = tuple(map(int, v_str.split('.')))
            elif match2:
                v_str = match2.group()
                latest_version = tuple(map(int, v_str.split('.'))) + (0,) 
            else:
                self.signal_error.emit(f"Could not read version from tag: {latest_tag}")
                return

            if latest_version > CURRENT_VERSION:
                assets = data.get("assets", [])
                if assets:
                    download_url = assets[0].get("browser_download_url")
                    self.signal_result.emit(True, v_str, download_url)
                else:
                    self.signal_error.emit("Update found, but no installer file (.exe) is attached.")
            else:
                self.signal_result.emit(False, v_str, "")
                
        except Exception as e:
            self.signal_error.emit(f"Connection error: {str(e)}")

class DownloadWorker(QThread):
    """Background thread to download the .exe and update the progress bar."""
    signal_progress = pyqtSignal(int)
    signal_finished = pyqtSignal(str)
    signal_error = pyqtSignal(str)

    def __init__(self, url, version_str):
        super().__init__()
        self.url = url
        self.version_str = version_str

    def run(self):
        try:
            temp_dir = tempfile.gettempdir()
                                                                           
            file_name = f"OpenCivil_Update_v{self.version_str}.exe"
            file_path = os.path.join(temp_dir, file_name)

            if os.path.exists(file_path):
                os.remove(file_path)

            response = requests.get(self.url, stream=True, timeout=10)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            
            with open(file_path, 'wb') as file:
                if total_size == 0:
                    file.write(response.content)
                    self.signal_progress.emit(100)
                else:
                    downloaded = 0
                    for data in response.iter_content(chunk_size=4096):
                        downloaded += len(data)
                        file.write(data)
                        percent = int((downloaded / total_size) * 100)
                        self.signal_progress.emit(percent)

            self.signal_finished.emit(file_path)

        except Exception as e:
            self.signal_error.emit(f"Download failed: {str(e)}")

class UpdateDialog(QDialog):
    """The UI Dialog that shows the checking and downloading progress."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenCivil Updater")
        self.setFixedSize(350, 150)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self.download_url = None
        self.download_worker = None
        self.target_version_str = ""

        self.layout = QVBoxLayout(self)
        
        self.status_label = QLabel("Checking GitHub for updates...", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0) 
        self.layout.addWidget(self.progress_bar)

        self.button_layout = QHBoxLayout()
        self.btn_close = QPushButton("Close", self)
        self.btn_close.clicked.connect(self.reject)
        self.btn_update = QPushButton("Download && Install", self)
        self.btn_update.setEnabled(False)
        self.btn_update.clicked.connect(self.start_download)
        
        self.button_layout.addStretch()
        self.button_layout.addWidget(self.btn_close)
        self.button_layout.addWidget(self.btn_update)
        self.layout.addLayout(self.button_layout)

        self.check_worker = GitHubCheckWorker()
        self.check_worker.signal_result.connect(self.on_check_finished)
        self.check_worker.signal_error.connect(self.on_error)
        self.check_worker.start()

    def on_check_finished(self, update_available, version_str, download_url):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        
        if update_available:
            self.target_version_str = version_str
            self.status_label.setText(f"A new version is available: <b>v{version_str}</b><br>Would you like to install it?")
            self.download_url = download_url
            self.btn_update.setEnabled(True)
            self.btn_update.setStyleSheet("background-color: #0078D7; color: white; font-weight: bold;")
        else:
            v_current_str = ".".join(map(str, CURRENT_VERSION))
            self.status_label.setText(f"You are running the latest version! (v{v_current_str})")
            self.btn_close.setText("Close")

    def on_error(self, error_msg):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText("<span style='color:red;'>An error occurred.</span>")
        QMessageBox.warning(self, "Updater Error", error_msg)
        self.btn_update.setEnabled(False)

    def start_download(self):

        reply = QMessageBox.warning(
            self,
            "Save Your Work!",
            "OpenCivil will close automatically to install the update.\n\nPlease make sure you have saved your current model.\n\nDo you want to proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No                                  
        )

        if reply == QMessageBox.StandardButton.No:
            return                                       
                         
        self.btn_update.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.status_label.setText("Downloading update... Please wait.")
        self.progress_bar.setValue(0)

        self.download_worker = DownloadWorker(self.download_url, self.target_version_str)
        self.download_worker.signal_progress.connect(self.progress_bar.setValue)
        self.download_worker.signal_finished.connect(self.on_download_finished)
        self.download_worker.signal_error.connect(self.on_error)
        self.download_worker.start()

    def on_download_finished(self, file_path):
        self.status_label.setText("Installing... OpenCivil will restart.")
        
        try:
            import subprocess
        
            flags = 0x00000008 | 0x08000000
            
            subprocess.Popen([
                file_path, 
                "/SILENT", 
                "/SUPPRESSMSGBOXES", 
                "/FORCECLOSEAPPLICATIONS"
            ], 
            creationflags=flags,
            stdin=subprocess.DEVNULL, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL   
            )
            
            import time
            time.sleep(0.5) 
            
            QApplication.quit()
            
        except Exception as e:
            self.on_error(f"Failed to start installer:\n{str(e)}")
            self.btn_close.setEnabled(True)
