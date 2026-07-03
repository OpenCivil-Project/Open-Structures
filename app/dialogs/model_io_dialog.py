import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPushButton, QTextEdit,
    QFileDialog, QSizePolicy, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QFont, QTextCursor

# ─── Analysis guard ───────────────────────────────────────────────────────────
# False → ModelIODialog is suppressed when analysis triggers a save/load.
#         AnalysisProgressDialog already covers that path.
# True  → also show during analysis-triggered I/O cycles.
LAUNCH_ON_ANALYSIS: bool = False
# ─────────────────────────────────────────────────────────────────────────────


class ModelIODialog(QDialog):
    """
    Lightweight save / open progress dialog for OpenCivil.
    Same visual family as AnalysisProgressDialog.

    Behaviour
    ---------
    · Auto-closes AUTO_CLOSE_MS after finish() if user never clicked it.
    · If user clicks anywhere on the dialog → auto-close cancelled,
      Close button activates so they can dismiss manually.
    · Escape and X are blocked until finish() is called.
    · Only utility: "Write to File" log export.

    Usage — save
    ------------
        dlg = ModelIODialog("Saving the Project...", filename, parent=self)
        dlg.show()
        QApplication.processEvents()

        dlg.stage("Collecting viewport settings...")
        # ... do the work ...
        QApplication.processEvents()

        dlg.stage("Writing project file...")
        self.model.save_to_file(filename)
        QApplication.processEvents()

        dlg.finish(success=True)

    Usage — open
    ------------
        dlg = ModelIODialog("Opening the Project...", filename, parent=self)
        dlg.show()
        QApplication.processEvents()

        dlg.stage("Clearing current session...")
        ...
        dlg.finish(success=True)

    Analysis guard
    --------------
        from model_io_dialog import LAUNCH_ON_ANALYSIS
        if LAUNCH_ON_ANALYSIS:
            dlg = ModelIODialog("Preparing Analysis Files...", ...)
    """

    AUTO_CLOSE_MS: int = 1200   # ms before auto-dismiss after finish()

    def __init__(self, title: str, filename: str = "", parent=None):
        super().__init__(parent)
        self._title     = title
        self._filename  = os.path.basename(filename) if filename else ""
        self._log_lines: list[str] = []
        self._clicked   = False
        self._done      = False
        self._close_tmr = None
        self._elapsed   = 0

        self._build_ui()
        self._start_timer()

        # header block
        self._append(f"Operation : {self._title.rstrip('.')}")
        if self._filename:
            self._append(f"File      : {self._filename}")
        self._append(f"Time      : {QDateTime.currentDateTime().toString('yyyy-MM-dd  hh:mm:ss')}")
        self._append("-" * 56)

        self.setWindowModality(Qt.WindowModality.ApplicationModal)

    # ─── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle(self._title)
        self.setWindowFlags(
            Qt.WindowType.Dialog              |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint     |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(640, 300)
        self.setMinimumSize(520, 220)
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

        # ── left: log view ───────────────────────────────────────────────────
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
        self.log_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        outer.addWidget(self.log_view, stretch=1)

        # ── right: status panel ──────────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(6)
        right.setContentsMargins(0, 0, 0, 0)

        right.addWidget(self._section_label("Status"))
        self.lbl_stage = QLabel("Initializing...")
        self.lbl_stage.setWordWrap(True)
        self.lbl_stage.setFixedWidth(155)
        self.lbl_stage.setStyleSheet("color: #0078D7; font-weight: bold;")
        right.addWidget(self.lbl_stage)

        right.addSpacing(10)
        right.addWidget(self._divider())
        right.addSpacing(6)

        right.addWidget(self._section_label("Info"))
        self.lbl_elapsed = QLabel("Elapsed: 0s")
        short_name = (self._filename[:18] + "…") if len(self._filename) > 18 else self._filename
        self.lbl_file    = QLabel(f"File: {short_name}")
        self.lbl_status  = QLabel("")
        for lbl in (self.lbl_elapsed, self.lbl_file, self.lbl_status):
            lbl.setStyleSheet("color: #444;")
            lbl.setWordWrap(True)
            lbl.setFixedWidth(155)
            right.addWidget(lbl)

        right.addSpacing(10)
        right.addWidget(self._divider())
        right.addSpacing(6)

        self.btn_export = QPushButton("Write to File")
        self.btn_export.clicked.connect(self._export_log)

        self.btn_close = QPushButton("Close")
        self.btn_close.setEnabled(False)
        self.btn_close.setStyleSheet("""
            QPushButton {
                font-family: 'Segoe UI'; font-size: 9pt;
                background: #e1e1e1; color: #1a1a1a;
                border: 1px solid #adadad; border-radius: 2px;
                padding: 4px 10px; min-width: 110px;
            }
            QPushButton:enabled {
                background: #0078D7; color: white; border-color: #005a9e;
            }
            QPushButton:enabled:hover   { background: #006bbf; }
            QPushButton:enabled:pressed { background: #005a9e; }
        """)
        self.btn_close.clicked.connect(self.close)

        for btn in (self.btn_export, self.btn_close):
            right.addWidget(btn)

        right.addStretch()
        outer.addLayout(right)

        self.log_view.viewport().installEventFilter(self)
        self.installEventFilter(self)


    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #888; font-size: 8pt;")
        return lbl

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #c0c0c0;")
        line.setFixedHeight(1)
        return line

    # ─── timer ───────────────────────────────────────────────────────────────

    def _start_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._elapsed += 1
        self.lbl_elapsed.setText(f"Elapsed: {self._elapsed}s")

    # ─── internal log ────────────────────────────────────────────────────────

    def _append(self, text: str):
        self._log_lines.append(text)
        self.log_view.append(text)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    # ─── public API ──────────────────────────────────────────────────────────

    def stage(self, text: str):
        """
        Push a stage message to the log and update the status label.
        After calling this and doing the associated work, call:
            QApplication.processEvents()
        so the dialog repaints before the next stage.
        """
        self._append(text)
        short = (text[:36] + "…") if len(text) > 36 else text
        self.lbl_stage.setText(short)
        self.lbl_stage.setStyleSheet("color: #0078D7; font-weight: bold;")

    def keep_open(self):
        """
        Call this before finish() if you intend to show a QMessageBox after
        (e.g. on error). Prevents auto-close so the dialog stays visible
        behind the message box.
        """
        self._clicked = True
        if self._close_tmr and self._close_tmr.isActive():
            self._close_tmr.stop()

    def finish(self, success: bool = True):
        """
        Mark the operation complete. Starts the auto-close countdown
        if the user hasn't clicked anywhere on the dialog.
        """
        self._done = True
        self._timer.stop()
        self._append("-" * 56)

        if success:
            self._append("STATUS : COMPLETE")
            self.lbl_stage.setText("Complete")
            self.lbl_stage.setStyleSheet("color: #005A9E; font-weight: bold;")
            self.lbl_status.setText("✓  OK")
            self.lbl_status.setStyleSheet("color: #005A9E; font-weight: bold;")
        else:
            self._append("STATUS : FAILED")
            self.lbl_stage.setText("Failed")
            self.lbl_stage.setStyleSheet("color: #ffffff; font-weight: bold;")
            self.lbl_status.setText("✗  Error")
            self.lbl_status.setStyleSheet("color: #ffffff; font-weight: bold;")

        self.btn_close.setEnabled(True)

        if not self._clicked:
            self._close_tmr = QTimer(self)
            self._close_tmr.setSingleShot(True)
            self._close_tmr.timeout.connect(self.close)
            self._close_tmr.start(self.AUTO_CLOSE_MS)

    # ─── click-to-stay ───────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        """User clicked → cancel pending auto-close."""
        if not self._clicked:
            self._clicked = True
            if self._close_tmr and self._close_tmr.isActive():
                self._close_tmr.stop()
        super().mousePressEvent(event)

    # ─── guards ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if not self._done and event.key() == Qt.Key.Key_Escape:
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        # Intercept any mouse click before the UI components swallow it
        if event.type() == QEvent.Type.MouseButtonPress:
            if not self._clicked:
                self._clicked = True
                if self._close_tmr and self._close_tmr.isActive():
                    self._close_tmr.stop()
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        if not self._done:
            event.ignore()
        else:
            super().closeEvent(event)

    # ─── export ──────────────────────────────────────────────────────────────

    def _export_log(self):
        stem = os.path.splitext(self._filename)[0] if self._filename else "opencivil"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Operation Log",
            f"{stem}_io_log.txt", "Text Files (*.txt)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(self._log_lines))
