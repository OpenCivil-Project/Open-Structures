"""A compact branch graph with explicit model checkout actions."""

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from app.ui.theme import apply_dialog_style
from app.dialogs.model_history_graph import HistoryGraph
from core.model_history import describe_changes

class ModelHistoryDialog(QDialog):
    """Hover inspects; click selects; checkout remains an explicit action."""

    def __init__(self, store, open_commit_callback, parent=None):
        super().__init__(parent)
        self.store = store
        self.open_commit_callback = open_commit_callback
        self._commits = {}
        self._state = {}
        self._details_cache = {}
        self._selection_valid = False
        self.setWindowTitle("Model History")
        self.resize(650, 440)
        self.setMinimumSize(540, 360)
        apply_dialog_style(self)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self.lbl_current = QLabel()
        self.lbl_current.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_current.setWordWrap(True)
        header.addWidget(self.lbl_current, 1)
        self.orientation = QComboBox()
        self.orientation.setObjectName("historyOrientation")
        self.orientation.addItem("Left → right", "horizontal")
        self.orientation.addItem("Top → bottom", "vertical")
        self.orientation.setToolTip("Direction of the branch graph")
        self.orientation.currentIndexChanged.connect(self._orientation_changed)
        header.addWidget(self.orientation)
        self.btn_fit = QPushButton("Fit")
        self.btn_fit.setObjectName("secondary")
        self.btn_fit.setToolTip("Show the whole tree")
        self.btn_fit.setAutoDefault(False)
        self.btn_fit.setDefault(False)
        self.btn_fit.clicked.connect(lambda: self.graph.fit_graph())
        header.addWidget(self.btn_fit)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.graph = HistoryGraph()
        self.graph.commitSelected.connect(self._selection_changed)
        self.graph.commitHovered.connect(self._hover_changed)
        splitter.addWidget(self.graph)
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 2, 0, 0)
        details_layout.setSpacing(5)
        self.lbl_selected = QLabel("Click a saved point to select it.")
        self.lbl_selected.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_selected.setWordWrap(True)
        details_layout.addWidget(self.lbl_selected)
        details_layout.addWidget(QLabel("Changes from previous save"))
        self.changes = QPlainTextEdit()
        self.changes.setObjectName("historyChanges")
        self.changes.setReadOnly(True)
        self.changes.setMaximumBlockCount(90)
        self.changes.setPlaceholderText("Scroll to zoom · Drag to pan · Click a save to select")
        details_layout.addWidget(self.changes)
        splitter.addWidget(details)
        splitter.setSizes([220, 120])
        layout.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.btn_open = QPushButton("Open saved point")
        self.btn_open.setObjectName("primary")
        self.btn_open.setToolTip("Open the selected model version. Later saves stay in history.")
        self.btn_open.clicked.connect(self._open_selected)
        buttons.addWidget(self.btn_open)
        self.btn_branch = QPushButton("Create branch here…")
        self.btn_branch.setObjectName("secondary")
        self.btn_branch.setToolTip("Start a named alternative from the selected saved point.")
        self.btn_branch.clicked.connect(self._create_branch)
        buttons.addWidget(self.btn_branch)
        buttons.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("secondary")
        self.btn_close.clicked.connect(self.accept)
        buttons.addWidget(self.btn_close)
        for button in (self.btn_open, self.btn_branch, self.btn_close):
            button.setAutoDefault(False)
            button.setDefault(False)
        layout.addLayout(buttons)

    def _orientation_changed(self, *_):
        self.graph.set_orientation(self.orientation.currentData())

    @staticmethod
    def _format_time(value):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OverflowError):
            return str(value or "")[:32]

    def _selected_id(self):
        return self.graph.selected_commit()

    def refresh(self, selected_id=None):
        selected_id = selected_id or self._selected_id()
        self._details_cache.clear()
        try:
            commits = self.store.list_commits()
            self._state = self.store.state()
        except Exception as error:
            self.graph.set_history([], {})
            self._commits = {}
            self._selection_valid = False
            self.lbl_current.setText("Model history is unavailable.")
            self.lbl_selected.setText(str(error)[:500])
            self.changes.clear()
            self._update_buttons()
            return False
        self._commits = {commit["id"]: commit for commit in commits}
        count = len(commits)
        active = self._state.get("active_branch")
        where = "Branch: " + active if active else "Earlier saved point"
        self.lbl_current.setText(f"{where}  ·  {count} saved point{'s' if count != 1 else ''}")
        self.graph.set_history(commits, self._state, selected_id)
        self._selection_changed()
        if not commits:
            self.lbl_current.setText("No saved points yet.")
            self.lbl_selected.setText("Save your model to start its history.")
        return True

    def _details(self, commit_id):
        if commit_id in self._details_cache:
            return self._details_cache[commit_id]
        commit = self._commits.get(commit_id)
        if commit is None:
            return ("Click a saved point to select it.", "", False)
        title = str(commit.get("label") or "Saved model") + "  ·  " + self._format_time(commit.get("created_at"))
        try:
            snapshot = self.store.get_snapshot(commit_id)
        except Exception as error:
            result = ("This saved point could not be read.", str(error)[:1000], False)
        else:
            try:
                parent_id = commit.get("parent_id")
                if parent_id:
                    previous = self.store.get_snapshot(parent_id)
                    lines = describe_changes(previous, snapshot, limit=80)
                    text = "\n".join(str(line) for line in lines) or "No model values changed."
                else:
                    text = "Initial saved model."
            except Exception as error:
                text = "Changes unavailable: " + str(error)[:1000]
            result = (title, text, True)
        if len(self._details_cache) >= 64:
            self._details_cache.pop(next(iter(self._details_cache)))
        self._details_cache[commit_id] = result
        return result

    def _show_details(self, commit_id, hovering=False):
        title, text, valid = self._details(commit_id)
        self.lbl_selected.setText(("Hover: " if hovering else "Selected: ") + title if commit_id else title)
        self.changes.setPlainText(text)
        return valid

    def _selection_changed(self, *_):
        self._selection_valid = self._show_details(self._selected_id())
        self._update_buttons()

    def _hover_changed(self, commit_id):
                                                                            
        self._show_details(commit_id or self._selected_id(), hovering=bool(commit_id))

    def _update_buttons(self):
        self.btn_open.setEnabled(self._selection_valid)
        self.btn_branch.setEnabled(self._selection_valid)

    def _selected_branch(self, commit_id):
        heads = [name for name, head in self._state.get("branches", {}).items() if head == commit_id]
        active = self._state.get("active_branch")
        return active if active in heads else sorted(heads)[0] if heads else None

    def _checkout(self, commit_id, branch_name):
        try:
            restored = bool(self.open_commit_callback(commit_id, branch_name))
        except Exception as error:
            QMessageBox.warning(self, "Model History", str(error))
            restored = False
        if restored:
            self.refresh(commit_id)
        return restored

    def _open_selected(self):
        commit_id = self._selected_id()
        if self._selection_valid and commit_id is not None:
            self._checkout(commit_id, self._selected_branch(commit_id))

    def _create_branch(self):
        commit_id = self._selected_id()
        if not self._selection_valid or commit_id is None:
            return
        existing = self._state.get("branches", {})
        suffix = 1
        while f"branch-{suffix}" in existing:
            suffix += 1
        name, accepted = QInputDialog.getText(self, "Create Branch", "Branch name:", text=f"branch-{suffix}")
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.information(self, "Create Branch", "Enter a branch name.")
            return
        if name in existing:
            QMessageBox.information(self, "Create Branch", "That branch name already exists.")
            return
        self._checkout(commit_id, name)
