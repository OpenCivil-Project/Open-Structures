import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QFrame, QPushButton, QTextEdit,
    QFileDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QDateTime, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor

from app.ui.theme import apply_dialog_style, COLORS

_WARN_COLOR  = "#d97706"
_ERROR_COLOR = "#c0392b"

class AnalysisProgressDialog(QDialog):
    """
    An analysis messages dialog.
    Left panel  — scrollable monospace log of all stages.
    Right panel — live status, progress bar, stats, action buttons.
    """

    signal_stop_requested = pyqtSignal()

    def __init__(self, case_type: str, case_name: str, parent=None, engine: str = None):
        super().__init__(parent)
        self.case_type  = case_type
        self.case_name  = case_name
        self._engine    = engine
        self._elapsed   = 0
        self._log_lines = []                             
        self._done      = False
        self._start_dt  = QDateTime.currentDateTime()

        self._build_ui()
        self._start_timer()

        self._append(f"Analysis Type : {self.case_type}")
        if self._engine:
            self._append(f"Analysis Engine : {self._engine}")
            self._update_title()
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
        apply_dialog_style(self)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier New", 8))
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_view.setStyleSheet("font-family: 'Courier New'; font-size: 8pt;")
        self.log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self.log_view, stretch=1)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.setContentsMargins(0, 0, 0, 0)

        right.addWidget(self._section_label("Status"))
        self.lbl_stage = QLabel("Initializing...")
        self.lbl_stage.setWordWrap(True)
        self.lbl_stage.setFixedWidth(150)
        self._set_stage_color(COLORS["accent"])
        right.addWidget(self.lbl_stage)

        right.addSpacing(6)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(150)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        right.addWidget(self.progress_bar)

        right.addSpacing(10)
        right.addWidget(self._divider())
        right.addSpacing(10)

        right.addWidget(self._section_label("Info"))
        self.lbl_elapsed  = QLabel("Elapsed: 0s")
        self.lbl_stages   = QLabel("Stages: 0")
        self.lbl_status   = QLabel("")
        for lbl in (self.lbl_elapsed, self.lbl_stages, self.lbl_status):
            lbl.setStyleSheet(f"color: {COLORS['text_secondary']};")
            right.addWidget(lbl)

        right.addSpacing(10)
        right.addWidget(self._divider())
        right.addSpacing(10)

        self.btn_stop = QPushButton("Stop Analysis")
        self.btn_stop.setStyleSheet(
            "QPushButton { background-color: #c77873; color: white; font-weight: 600; "
            "border-radius: 4px; padding: 5px 12px; }"
            "QPushButton:hover { background-color: #b5625d; }"
            "QPushButton:pressed { background-color: #9e4f4a; }"
            "QPushButton:disabled { background-color: #8a7a79; color: #ddd; }"
        )
        self.btn_stop.clicked.connect(self._on_stop_clicked)

        self.btn_copy = QPushButton("Copy Log")
        self.btn_copy.setObjectName("secondary")
        self.btn_copy.clicked.connect(self._copy_log)

        self.btn_save = QPushButton("Write to File")
        self.btn_save.setObjectName("secondary")
        self.btn_save.clicked.connect(self._save_log)

        self.btn_done = QPushButton("Done")
        self.btn_done.setEnabled(False)
        self.btn_done.setObjectName("primary")
        self.btn_done.clicked.connect(self.close)

        for btn in (self.btn_stop, self.btn_copy, self.btn_save, self.btn_done):
            btn.setMinimumWidth(110)
            right.addWidget(btn)

        right.addStretch()
        outer.addLayout(right)

    def _on_stop_clicked(self):
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("Stopping...")
        self.signal_stop_requested.emit()

    def abort(self):
        """Called by the main window after it has killed the solver: lets the dialog close."""
        self._done = True
        self._timer.stop()
        self.btn_stop.setVisible(False)

    def _update_title(self):
        self.setWindowTitle(f"Analysis Messages - {self._engine}" if self._engine else "Analysis Messages")

    def set_engine(self, name: str):
        """Shows the analysis engine in the log header (right under Analysis Type)
        and in the window title. Safe to call at any time, once."""
        if not name or self._engine == name:
            return
        had_line = self._engine is not None
        self._engine = name
        self._update_title()
        line = f"Analysis Engine : {name}"
        if had_line:
            for i, t in enumerate(self._log_lines):
                if t.startswith("Analysis Engine :"):
                    self._log_lines[i] = line
                    break
        else:
            self._log_lines.insert(1, line)
        self.log_view.setPlainText("\n".join(self._log_lines))
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def _detect_engine(self, texts):
        """Fallback: the OpenSees runner tags its messages, so pick the engine up from them."""
        if self._engine is None and any("opensees" in str(t).lower() for t in texts):
            self.set_engine("OpenSees")

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['text_disabled']}; font-size: 8pt;")
        return lbl

    def _set_stage_color(self, color):
        self.lbl_stage.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _set_status_color(self, color):
        self.lbl_status.setStyleSheet(f"color: {color};")

    def _divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {COLORS['border']};")
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
        self._detect_engine([stage])
        self._append(stage)
        self.lbl_stage.setText(stage[:40] + "…" if len(stage) > 40 else stage)
        self.progress_bar.setValue(percent)
        self.lbl_stages.setText(f"Stages: {len(self._log_lines)}")

    def update_stages(self, items):
        """Batched version of update_stage: one UI update for many solver messages.
        items = [(message, percent), ...]"""
        if not items:
            return
        lines = [str(m) for m, _ in items]
        self._detect_engine(lines)
        self._log_lines.extend(lines)

        cur = self.log_view.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertBlock()
        cur.insertText("\n".join(lines))
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

        last_msg, last_pct = items[-1]
        last_msg = str(last_msg)
        self.lbl_stage.setText(last_msg[:40] + "…" if len(last_msg) > 40 else last_msg)
        self.progress_bar.setValue(int(last_pct))
        self.lbl_stages.setText(f"Stages: {len(self._log_lines)}")

    def finish(self, success: bool, failed_steps: list = None, case_failures: list = None):
        self._done = True
        self._timer.stop()
        self.btn_stop.setVisible(False)
        case_failures = case_failures or []

        self._append("-" * 60)

        if success:
            if case_failures:
                                                                       
                self._append("STATUS : ANALYSIS COMPLETE WITH CASE FAILURES")
                self._append(f"ERROR: {len(case_failures)} case(s) did not complete.")
                self.lbl_stage.setText("Complete (Errors)")
                self._set_stage_color(_ERROR_COLOR)
                self.lbl_status.setText("Errors")
                self._set_status_color(_ERROR_COLOR)
                self.progress_bar.setValue(100)

                lines = [f"  • {cf.get('case', 'Unknown')}: {cf.get('message', 'did not converge')}" for cf in case_failures]
                msg = (
                    f"{len(case_failures)} case(s) in this batch did not complete - a step failed to "
                    f"converge and 'Continue Analysis If No Convergence' was OFF for that case, so the "
                    f"solver stopped rather than carrying an unconverged step forward.\n\n"
                    f"Cases with no results:\n" + "\n".join(lines) + "\n\n"
                    "Every other case in the batch ran and its results are available as usual. "
                    "See the log on the left for the full per-step history."
                )

                if failed_steps:
                    warn_count = len(failed_steps)
                    warn_cases = sorted({item.get('case', 'Unknown') for item in failed_steps if isinstance(item, dict)})
                    msg += (
                        f"\n\nAdditionally, {warn_count} step(s) across {len(warn_cases) or 1} other "
                        f"case(s) finished but missed strict tolerance: {', '.join(warn_cases) or 'see log'}."
                    )

                from PyQt6.QtWidgets import QMessageBox
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Critical)
                box.setWindowTitle("Analysis Case Failure")
                box.setText("<b>One or more cases did not complete</b>")
                box.setInformativeText(msg)
                box.setStandardButtons(QMessageBox.StandardButton.Ok)
                box.exec()

            elif failed_steps:
                self._append("STATUS : ANALYSIS COMPLETE WITH CONVERGENCE WARNINGS")
                self._append(f"WARNING: {len(failed_steps)} step(s) failed to reach strict tolerance.")
                self.lbl_stage.setText("Complete (Warnings)")
                self._set_stage_color(_WARN_COLOR)
                self.lbl_status.setText("Warnings")
                self._set_status_color(_WARN_COLOR)
                self.progress_bar.setValue(100)
                
                errors = [
                    float(item['error']) for item in failed_steps
                    if isinstance(item, dict) and item.get('error') is not None
                ]
                max_err = max(errors, default=None)
                has_case_tags = any(isinstance(item, dict) and 'case' in item for item in failed_steps)

                if has_case_tags:
                    by_case = {}
                    for item in failed_steps:
                        case = item.get('case', 'Unknown') if isinstance(item, dict) else 'Unknown'
                        step_val = (
                            item.get('step', item.get('target', '?'))
                            if isinstance(item, dict) else item
                        )
                        by_case.setdefault(case, []).append(step_val)
                    lines = []
                    for case, steps in by_case.items():
                        s = ", ".join(str(n) for n in steps[:8])
                        if len(steps) > 8:
                            s += f", … (+{len(steps) - 8} more)"
                        lines.append(f"  • {case}: {len(steps)} step(s) — {s}")
                    step_list = "\n".join(lines)
                    total_count = len(failed_steps)
                    intro = (
                        f"The batch run completed, but {total_count} step(s) across "
                        f"{len(by_case)} case(s) did not reach the strict convergence tolerance "
                        f"within the maximum iterations before 'Continue Analysis If No Convergence' "
                        f"carried the solver past them.\n\n"
                        f"Cases affected:\n{step_list}\n\n"
                    )
                else:
                    bad_nums = [
                        item.get('step', item.get('target', '?')) if isinstance(item, dict) else item
                        for item in failed_steps
                    ]
                    step_list = ", ".join(str(n) for n in bad_nums[:10])
                    if len(bad_nums) > 10:
                        step_list += f", … (+{len(bad_nums) - 10} more)"
                    intro = (
                        f"The analysis ran to completion, but {len(bad_nums)} step(s) did not reach the "
                        f"strict convergence tolerance within the maximum iterations before "
                        f"'Continue Analysis If No Convergence' carried the solver past them.\n\n"
                        f"Steps affected: {step_list}\n\n"
                    )

                err_line = f"Largest relative error: {max_err:.3E}\n\n" if max_err is not None else ""
                msg = (
                    intro +
                    err_line +
                    "Results at and after these steps should be treated as approximate. "
                    "See the log on the left for the per-step error history."
                )

                from PyQt6.QtWidgets import QMessageBox
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("Analysis Convergence Notice")
                box.setText("<b>Some steps did not converge</b>")
                box.setInformativeText(msg)
                box.setStandardButtons(QMessageBox.StandardButton.Ok)
                box.exec()

            else:
                self._append("STATUS : ANALYSIS COMPLETE")
                self.lbl_stage.setText("Analysis Complete")
                self._set_stage_color(COLORS["accent"])
                self.lbl_status.setText("Complete")
                self._set_status_color(COLORS["text_primary"])
                self.progress_bar.setValue(100)
        else:
            self._append("STATUS : ANALYSIS FAILED")
            self.lbl_stage.setText("Analysis Failed")
            self._set_stage_color(COLORS["text_primary"])
            self.lbl_status.setText("Failed")
            self._set_status_color(COLORS["text_primary"])

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
