from PyQt6.QtWidgets import QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout
from PyQt6.QtCore import Qt, QEvent, QTimer
from PyQt6.QtGui import QGuiApplication, QColor

from app.ui.theme import COLORS, SIZES, on_theme_changed, glass_alpha
from app.ui.blur import CORNER_RADIUS

ROW_HEIGHT = 32                              
MAX_VISIBLE = 8                                             
MAX_RESULTS = 60                                            
RADIUS = CORNER_RADIUS                                                           

def _rgba(color, alpha):
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"

class CommandPalette(QFrame):
    """
    Type-to-run command palette.

    One popup window holds BOTH the text box and the suggestion list, so they
    always move/appear together and mouse clicks on the list work.

    Only commands that are known to behave are offered:
      - Undo / Redo
      - Anything in the menu bar that opens a dialog (menu text ends with "...")
    Submenu titles ("Define", "Draw"...), checkable toggles, and toolbar-only
    duplicates are never listed.
    """

    EXTRA_ACTION_ATTRS = ("undo_action", "redo_action")

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.entries = {}                            

        self.setObjectName("CmdPalette")
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                                                                                   
        self.setProperty("_blur_ready", True)
        self.setProperty("blur_popup", True)
        self.setFixedWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a command...")
        self.input.installEventFilter(self)

        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)                                     
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setEditTriggers(QListWidget.EditTrigger.NoEditTriggers)
        self.list.hide()

        layout.addWidget(self.input)
        layout.addWidget(self.list)

        self._apply_style()
        on_theme_changed(lambda _name: self._apply_style())

        self.input.textChanged.connect(self._update_suggestions)
        self.input.returnPressed.connect(self._run_current)
        self.list.itemClicked.connect(self._run_item)
        self.hide()

    def _apply_style(self):
        self.setStyleSheet(f"""
            QFrame#CmdPalette {{
                background-color: {_rgba(COLORS['bg_panel'], glass_alpha('dialog'))};
                border: 1px solid {_rgba(COLORS['accent'], 230)};
                border-radius: {RADIUS}px;
            }}
            QLineEdit {{
                background-color: transparent;
                color: {COLORS['text_primary']};
                border: none;
                padding: 8px 12px;
                font-family: '{SIZES['font_family']}', Consolas, sans-serif;
                font-size: 14px;
                selection-background-color: {COLORS['selection_bg']};
                selection-color: {COLORS['selection_text']};
            }}
            QListWidget {{
                background-color: transparent;
                color: {COLORS['text_primary']};
                border: none;
                border-top: 1px solid {_rgba(COLORS['border'], 160)};
                border-bottom-left-radius: {RADIUS}px;
                border-bottom-right-radius: {RADIUS}px;
                padding: 4px;
                font-family: '{SIZES['font_family']}';
                font-size: 13px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 0px 10px;
                height: {ROW_HEIGHT}px;
                border-radius: 6px;
            }}
            QListWidget::item:hover {{
                background-color: {COLORS['bg_btn_hover']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['accent']};
                color: {COLORS['text_on_accent']};
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['border']};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)

    @staticmethod
    def _clean(text):
        text = text.replace("&", "").strip()
        for tail in ("...", "\u2026"):
            if text.endswith(tail):
                text = text[: -len(tail)]
        return text.strip()

    def _collect(self, menu, path, out):
        """Walk a menu tree, recording (action, menu_path) for every leaf action."""
        for act in menu.actions():
            sub = act.menu()
            if sub is not None:
                self._collect(sub, path + [self._clean(act.text())], out)
            elif not act.isSeparator():
                out.append((act, path))

    def harvest_actions(self):
        """Rebuild the list of runnable commands from the menu bar."""
        self.entries.clear()
        mw = self.main_window

        extras = {getattr(mw, name, None) for name in self.EXTRA_ACTION_ATTRS}
        extras.discard(None)

        leaves = []
        for top in mw.menuBar().actions():
            if top.menu() is not None:
                self._collect(top.menu(), [self._clean(top.text())], leaves)

        allowed = []
        for act, path in leaves:
            raw = act.text().replace("&", "").strip()
            if not raw or not act.isEnabled() or act.isCheckable():
                continue
            opens_dialog = raw.endswith("...") or raw.endswith("\u2026")
            if opens_dialog or act in extras:
                allowed.append((self._clean(raw), act, path))

        counts = {}
        for name, _, _ in allowed:
            counts[name] = counts.get(name, 0) + 1

        for name, act, path in allowed:
            label = name
            if counts[name] > 1:
                trail = " \u203a ".join(path)
                label = f"{name}  ({trail})"
            self.entries[label] = act

    def spawn(self, initial_text, global_pos):
        self.harvest_actions()
        self.move(global_pos.x() + 15, global_pos.y() + 15)

        self.input.blockSignals(True)
        self.input.setText(initial_text)
        self.input.blockSignals(False)
        self._update_suggestions(initial_text)

        self.show()
        self.input.setFocus()
        self.input.setCursorPosition(len(initial_text))
        self._clamp_to_screen()

    def _update_suggestions(self, text):
        """Starts-with matches first, then contains; each group alphabetical."""
        self.list.clear()
        query = text.strip().lower()
        if not query:
            self._finish_layout(0)
            return

        starts, contains = [], []
        for label in sorted(self.entries.keys(), key=str.lower):
            low = label.lower()
            if low.startswith(query):
                starts.append(label)
            elif query in low:
                contains.append(label)

        results = (starts + contains)[:MAX_RESULTS]
        for label in results:
            self.list.addItem(label)
        if results:
            self.list.setCurrentRow(0)
        self._finish_layout(len(results))

    def _finish_layout(self, n_rows):
        if n_rows == 0:
            self.list.hide()
        else:
            self.list.setFixedHeight(min(n_rows, MAX_VISIBLE) * ROW_HEIGHT + 10)
            self.list.show()
        self.adjustSize()
        if self.isVisible():
            self._clamp_to_screen()

    def _clamp_to_screen(self):
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        r = screen.availableGeometry()
        x = max(r.left(), min(self.x(), r.right() - self.width()))
        y = max(r.top(), min(self.y(), r.bottom() - self.height()))
        self.move(x, y)

    def _run_current(self):
        self._run_item(self.list.currentItem())

    def _run_item(self, item):
        if item is None:
            return
        action = self.entries.get(item.text())
        if action is None:
            return
        self._close()
                                                                           
        QTimer.singleShot(0, action.trigger)

    def _close(self):
        self.hide()
        self.list.clear()
        self.input.clear()

    def _step(self, delta):
        n = self.list.count()
        if n == 0:
            return
        self.list.setCurrentRow((self.list.currentRow() + delta) % n)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self._close()
                canvas = getattr(self.main_window, 'active_canvas', None)
                if canvas is not None:
                    canvas.setFocus()
                return True
            if key == Qt.Key.Key_Down:
                self._step(1)
                return True
            if key == Qt.Key.Key_Up:
                self._step(-1)
                return True
        return super().eventFilter(obj, event)
