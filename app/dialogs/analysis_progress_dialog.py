import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QFrame, QPushButton, QTextEdit,
    QFileDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QFont, QTextCursor

class AnalysisProgressDialog(QDialog):
    """
    SAP-style analysis messages dialog.
    Left panel  — scrollable monospace log of all stages.
    Right panel — live status, progress bar, stats, action buttons.
    """

    def __init__(self, case_type: str, case_name: str, parent=None):
        super().__init__(parent)
        self.case_type  = case_type
        self.case_name  = case_name
        self._elapsed   = 0
        self._log_lines = []                             
        self._done      = False
        self._start_dt  = QDateTime.currentDateTime()

        self._build_ui()
        self._start_timer()

        self._append(f"Analysis Type : {self.case_type}")
        self._append(f"Load Case     : {self.case_name}")
        self._append(f"Date & Time   : {self._start_dt.toString('yyyy-MM-dd  hh:mm:ss')}")
        self._append("-" * 60)

    def _build_ui(self):
        self.setWindowTitle("Analysis Messages")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(780, 480)
        self.setMinimumSize(640, 380)
        self.setStyleSheet("""
            QDialog   { background: #f0f0f0; }
            QLabel    { font-family: 'Segoe UI'; font-size: 9pt; color: #1a1a1a; }
            QPushButton {
                font-family: 'Segoe UI'; font-size: 9pt;
                background: #e1e1e1; color: #1a1a1a;
                border: 1px solid #adadad; border-radius: 2px;
                padding: 4px 10px; min-width: 110px;
            }
            QPushButton:hover   { background: #d0e4f0; border-color: #0078D7; }
            QPushButton:pressed { background: #c0d8eb; }
            QPushButton:disabled { color: #999; background: #e8e8e8; }
        """)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier New", 8))
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_view.setStyleSheet("""
            QTextEdit {
                background: #ffffff;
                border: 1px solid #adadad;
                color: #1a1a1a;
            }
        """)
        self.log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self.log_view, stretch=1)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.setContentsMargins(0, 0, 0, 0)

        right.addWidget(self._section_label("Status"))
        self.lbl_stage = QLabel("Initializing...")
        self.lbl_stage.setWordWrap(True)
        self.lbl_stage.setFixedWidth(150)
        self.lbl_stage.setStyleSheet("color: #0078D7; font-weight: bold;")
        right.addWidget(self.lbl_stage)

        right.addSpacing(6)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(150)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #adadad;
                background: #ffffff;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: #0078D7;
                border-radius: 1px;
            }
        """)
        right.addWidget(self.progress_bar)

        right.addSpacing(10)
        right.addWidget(self._divider())
        right.addSpacing(10)

        right.addWidget(self._section_label("Info"))
        self.lbl_elapsed  = QLabel("Elapsed: 0s")
        self.lbl_stages   = QLabel("Stages: 0")
        self.lbl_status   = QLabel("")
        for lbl in (self.lbl_elapsed, self.lbl_stages, self.lbl_status):
            lbl.setStyleSheet("color: #444;")
            right.addWidget(lbl)

        right.addSpacing(10)
        right.addWidget(self._divider())
        right.addSpacing(10)

        self.btn_copy = QPushButton("Copy Log")
        self.btn_copy.clicked.connect(self._copy_log)

        self.btn_save = QPushButton("Write to File")
        self.btn_save.clicked.connect(self._save_log)

        self.btn_done = QPushButton("Done")
        self.btn_done.setEnabled(False)
        self.btn_done.setStyleSheet("""
            QPushButton {
                font-family: 'Segoe UI'; font-size: 9pt;
                background: #e1e1e1; color: #1a1a1a;
                border: 1px solid #adadad; border-radius: 2px;
                padding: 4px 10px; min-width: 110px;
            }
            QPushButton:enabled {
                background: #0078D7; color: white;
                border-color: #005a9e;
            }
            QPushButton:enabled:hover   { background: #006bbf; }
            QPushButton:enabled:pressed { background: #005a9e; }
        """)
        self.btn_done.clicked.connect(self.close)

        for btn in (self.btn_copy, self.btn_save, self.btn_done):
            right.addWidget(btn)

        right.addStretch()
        outer.addLayout(right)

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #888; font-size: 8pt;")
        return lbl

    def _divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #c0c0c0;")
        line.setFixedHeight(1)
        return line

    def _append(self, text: str):
        self._log_lines.append(text)
        self.log_view.append(text)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def _start_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._elapsed += 1
        self.lbl_elapsed.setText(f"Elapsed: {self._elapsed}s")

    def update_stage(self, stage: str, percent: int):
        """Called from main thread when signal_progress fires."""
        self._append(stage)
        self.lbl_stage.setText(stage[:40] + "…" if len(stage) > 40 else stage)
        self.progress_bar.setValue(percent)
        self.lbl_stages.setText(f"Stages: {len(self._log_lines)}")

    def finish(self, success: bool):
        self._done = True
        self._timer.stop()

        self._append("-" * 60)

        if success:
            self._append("STATUS : ANALYSIS COMPLETE")
            self.lbl_stage.setText("Analysis Complete")
            self.lbl_stage.setStyleSheet("color: #0078D7; font-weight: bold;")
            self.lbl_status.setText("Complete")
            self.lbl_status.setStyleSheet("color: #1a1a1a;")
            self.progress_bar.setValue(100)
        else:
            self._append("STATUS : ANALYSIS FAILED")
            self.lbl_stage.setText("Analysis Failed")
            self.lbl_stage.setStyleSheet("color: #1a1a1a; font-weight: bold;")
            self.lbl_status.setText("Failed")
            self.lbl_status.setStyleSheet("color: #1a1a1a;")

        self.btn_done.setEnabled(True)

    def _copy_log(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText("\n".join(self._log_lines))

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Analysis Log", f"{self.case_name}_analysis_log.txt",
            "Text Files (*.txt)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._log_lines))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and not self._done:
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self._done:
            event.ignore()
        else:
            super().closeEvent(event)
