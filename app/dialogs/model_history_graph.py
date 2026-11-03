"""A native Qt graph for immutable model saves and their branches."""

from collections import deque
from datetime import datetime
import html

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView

from app.ui.theme import COLORS

_BRANCH_COLORS = ("#3788e8", "#23a27b", "#bd79dd", "#e49a35", "#db6674", "#4ca5b4")

def _color(key, fallback):
    return QColor(COLORS.get(key, fallback))

def _time_text(value, full=False):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%Y-%m-%d %H:%M:%S" if full else "%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError):
        return str(value or "")[:40]

class _SaveNode(QGraphicsItem):
    def __init__(self, graph, commit, color, heads, current):
        super().__init__()
        self.graph = graph
        self.commit_id = commit["id"]
        self.commit = commit
        self.color = QColor(color)
        self.heads = heads
        self.current = current
        self.hovered = False
        self._font = QFont("Segoe UI", 8)
        self._bold_font = QFont(self._font)
        self._bold_font.setBold(True)
        self._time_font = QFont("Segoe UI", 7)
        label = str(commit.get("label") or "Saved model")
        self._label = QFontMetricsF(self._font).elidedText(label, Qt.TextElideMode.ElideRight, 146)
        self._bold_label = QFontMetricsF(self._bold_font).elidedText(label, Qt.TextElideMode.ElideRight, 146)
        self._when = _time_text(commit.get("created_at"))
        badges = list(heads) + (["current"] if current else [])
        metrics = QFontMetricsF(self._font)
        self._badge = metrics.elidedText(" · ".join(badges), Qt.TextElideMode.ElideRight, 136)
        width = min(148, metrics.horizontalAdvance(self._badge) + 12)
        self._badge_rect = QRectF(-width / 2, -36, width, 19)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(2)
        self.setToolTip(self._tooltip())

    def boundingRect(self):
        return QRectF(-80, -44, 160, 102)

    def shape(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(-76, -39, 152, 94), 6, 6)
        return path

    def _tooltip(self):
        label = html.escape(str(self.commit.get("label") or "Saved model"))
        when = html.escape(_time_text(self.commit.get("created_at"), full=True))
        branch = html.escape(str(self.commit.get("branch") or "main"))
        summary = self.commit.get("summary") or ""
        if isinstance(summary, (list, tuple)):
            summary = "\n".join(str(value) for value in summary[:12])
        summary = html.escape(str(summary)[:1200]).replace("\n", "<br>")
        heads = html.escape(", ".join(self.heads))
        text = f"<b>{label}</b><br>{when}<br>Branch: {branch}"
        if heads:
            text += "<br>Branch heads: " + heads
        if self.current:
            text += "<br><b>Current model version</b>"
        if summary:
            text += "<br><br>" + summary
        return text + "<br><br>Click to select. Open saved point to restore."

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font)
        if self.isSelected() or self.hovered:
            background = _color("selection_bg", "#e9f2fe")
            if not self.isSelected():
                background.setAlpha(100)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(QRectF(-76, -40, 152, 95), 6, 6)
        if self.isSelected():
            painter.setPen(QPen(_color("text_primary", "#202020"), 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(0, 0), 16, 16)
        if self.current:
            painter.setPen(QPen(self.color, 2.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(0, 0), 12, 12)
        painter.setPen(QPen(_color("bg_panel", "#ffffff"), 1.5))
        painter.setBrush(self.color)
        painter.drawEllipse(QPointF(0, 0), 7.5, 7.5)

        if self.heads or self.current:
            badge_fill = QColor(self.color)
            badge_fill.setAlpha(28)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(badge_fill)
            painter.drawRoundedRect(self._badge_rect, 4, 4)
            painter.setPen(self.color)
            painter.drawText(self._badge_rect, Qt.AlignmentFlag.AlignCenter, self._badge)

        bold = self.isSelected() or self.current
        painter.setFont(self._bold_font if bold else self._font)
        painter.setPen(_color("text_primary", "#202020"))
        painter.drawText(QRectF(-74, 18, 148, 18), Qt.AlignmentFlag.AlignCenter,
                         self._bold_label if bold else self._label)
        painter.setFont(self._time_font)
        painter.setPen(_color("text_secondary", "#666666"))
        painter.drawText(QRectF(-74, 35, 148, 16), Qt.AlignmentFlag.AlignCenter,
                         self._when)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.graph.select_commit(self.commit_id, center=False)
            self.graph.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
                                                                         
        self.graph.select_commit(self.commit_id, center=False)
        event.accept()

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        self.graph.commitHovered.emit(self.commit_id)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        self.graph.commitHovered.emit(None)
        super().hoverLeaveEvent(event)

class HistoryGraph(QGraphicsView):
    """Connected save nodes, flowing left to right by default.

    Navigation only selects nodes. Restore remains an explicit dialog action.
    ``positions`` and ``edges`` expose the layout for tests and integrations.
    """

    commitSelected = pyqtSignal(str)
    commitHovered = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("historyGraph")
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setBackgroundBrush(_color("bg_panel", "#ffffff"))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(120)
        self.setToolTip("Scroll to zoom · Drag the background to pan · 0 to fit")
        self.orientation = "horizontal"
        self.nodes = {}
        self.positions = {}
        self.edges = []
        self._commits = []
        self._state = {}
        self._order = []
        self._selected = None
        self._fit_pending = False
        self._user_view = False
        self._content_rect = QRectF()

    def set_history(self, commits, state, selected_id=None):
        self._commits = list(commits) if isinstance(commits, (list, tuple)) else []
        self._state = dict(state) if isinstance(state, dict) else {}
        current = self._state.get("current_commit")
        if not isinstance(current, str):
            self._state["current_commit"] = None
        selected_id = selected_id if isinstance(selected_id, str) else None
        self._build_graph(selected_id or self._selected or self._state.get("current_commit"))

    def set_orientation(self, orientation):
        if orientation not in ("horizontal", "vertical"):
            raise ValueError("Orientation must be horizontal or vertical")
        if orientation != self.orientation:
            self.orientation = orientation
            self._build_graph(self._selected)

    def _build_graph(self, selected_id):
        self.scene().clear()
        self.nodes = {}
        self.positions = {}
        self.edges = []
        self._selected = None
        self._user_view = False
        self.resetTransform()
        commits = {}
        for commit in self._commits:
            if not isinstance(commit, dict):
                continue
            commit_id = commit.get("id")
            if not isinstance(commit_id, str) or not commit_id or commit_id in commits:
                continue
            commits[commit_id] = commit
        original_order = list(commits)
        self._order = original_order
        if not commits:
            empty = self.scene().addText("No saved points yet. Save your model to start its history.")
            empty.setDefaultTextColor(_color("text_secondary", "#666666"))
            self._content_rect = self.scene().itemsBoundingRect().adjusted(-18, -18, 18, 18)
            self.scene().setSceneRect(self._content_rect)
            self.setSceneRect(self._content_rect)
            self._fit_pending = False
            return

        children = {}
        parents = {}
        for commit_id, commit in commits.items():
            parent = commit.get("parent_id")
            if isinstance(parent, str) and parent in commits and parent != commit_id:
                parents[commit_id] = parent
                children.setdefault(parent, []).append(commit_id)
        roots = [value for value in original_order if value not in parents]
        roots.sort(key=lambda value: commits[value].get("branch") != "main")
        queue = deque(roots)
        ordered = []
        while queue:
            commit_id = queue.popleft()
            ordered.append(commit_id)
            child_ids = children.get(commit_id, [])
            child_ids = sorted(child_ids, key=lambda value:
                               commits[value].get("branch") != commits[commit_id].get("branch"))
            queue.extend(child_ids)
                                                                         
        seen = set(ordered)
        for commit_id in original_order:
            if commit_id not in seen:
                parents.pop(commit_id, None)
                ordered.append(commit_id)
                seen.add(commit_id)

        branch_lanes = {"main": 0}
        lanes = {}
        depths = {}
        branches = {}
        occupied = set()
        next_lane = 1
        heads = {}
        state_branches = self._state.get("branches", {})
        if isinstance(state_branches, dict):
            for name, head in state_branches.items():
                if isinstance(name, str) and isinstance(head, str):
                    heads.setdefault(head, []).append(name)
        for commit_id in ordered:
            commit = commits[commit_id]
            parent = parents.get(commit_id)
            if parent not in depths:
                parent = None
            branch = commit.get("branch")
            if not isinstance(branch, str) or not branch:
                branch = branches.get(parent, "main")
            branches[commit_id] = branch
            depth = depths[parent] + 1 if parent is not None else 0
            if parent is not None and branch == branches[parent]:
                lane = lanes[parent]
            elif branch in branch_lanes:
                lane = branch_lanes[branch]
            else:
                lane = next_lane
                next_lane += 1
                branch_lanes[branch] = lane
            if (depth, lane) in occupied:
                lane = next_lane
                next_lane += 1
            occupied.add((depth, lane))
            lanes[commit_id] = lane
            depths[commit_id] = depth
            if self.orientation == "horizontal":
                position = (90 + depth * 170, 52 + lane * 108)
            else:
                position = (90 + lane * 178, 52 + depth * 112)
            self.positions[commit_id] = position
            color = _BRANCH_COLORS[lane % len(_BRANCH_COLORS)]
            node = _SaveNode(self, commit, color, sorted(heads.get(commit_id, [])),
                             commit_id == self._state.get("current_commit"))
            node.setPos(*position)
            self.scene().addItem(node)
            self.nodes[commit_id] = node

        for child_id, parent_id in parents.items():
            if parent_id not in self.positions or depths[child_id] <= depths[parent_id]:
                continue
            start = QPointF(*self.positions[parent_id])
            end = QPointF(*self.positions[child_id])
            path = QPainterPath(start)
            if self.orientation == "horizontal":
                middle = (start.x() + end.x()) / 2
                path.cubicTo(QPointF(middle, start.y()), QPointF(middle, end.y()), end)
            else:
                middle = (start.y() + end.y()) / 2
                path.cubicTo(QPointF(start.x(), middle), QPointF(end.x(), middle), end)
            edge = QGraphicsPathItem(path)
            edge.setPen(QPen(self.nodes[child_id].color, 2.2))
            edge.setZValue(0)
            self.scene().addItem(edge)
            self.edges.append((parent_id, child_id, edge))
        bounds = self.scene().itemsBoundingRect().adjusted(-18, -14, 18, 16)
        self._content_rect = bounds
        self.scene().setSceneRect(bounds)
        self._fit_pending = True
        self._initial_fit()
        if selected_id not in self.nodes:
            selected_id = self._state.get("current_commit")
        if selected_id not in self.nodes:
            selected_id = original_order[-1]
        self.select_commit(selected_id)

    def selected_commit(self):
        return self._selected

    def select_commit(self, commit_id, center=True):
        if not isinstance(commit_id, str):
            return
        node = self.nodes.get(commit_id)
        if node is None:
            return
        old = self._selected
        self.scene().clearSelection()
        node.setSelected(True)
        self._selected = commit_id
        if center:
            self.ensureVisible(node, 22, 18)
        if commit_id != old:
            self.commitSelected.emit(commit_id)

    def _fit_scale(self):
        viewport = self.viewport().size()
        bounds = self._content_rect
        return min(max(1, viewport.width() - 24) / max(bounds.width(), 1),
                   max(1, viewport.height() - 24) / max(bounds.height(), 1), 1.0)

    def _navigation_extent(self, center=None):
        """Room to pan around a small graph, without displaying scrollbars."""
        center = center if center is not None else self.mapToScene(self.viewport().rect().center())
        scale = max(self.transform().m11(), 0.000001)
        padx = max(80, self.viewport().width() / scale)
        pady = max(80, self.viewport().height() / scale)
        self.setSceneRect(self._content_rect.adjusted(-padx, -pady, padx, pady))
        self.centerOn(center)

    def fit_graph(self):
        """Show the whole tree without changing the selected saved point."""
        if not self.nodes:
            return
        self._user_view = True
        self._fit_pending = False
        self.resetTransform()
        factor = self._fit_scale()
        self.scale(factor, factor)
        self._navigation_extent(self._content_rect.center())

    def _initial_fit(self):
        if not self._fit_pending or self._user_view or not self.nodes:
            return
        viewport = self.viewport().size()
        if viewport.width() < 80 or viewport.height() < 80:
            return
                                                                          
        factor = max(0.78, self._fit_scale())
        self.resetTransform()
        self.scale(factor, factor)
        self._navigation_extent(self._content_rect.center())
        if factor == 0.78 and self._selected in self.nodes:
            self.ensureVisible(self.nodes[self._selected], 22, 18)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._initial_fit()
        if self._user_view and self.nodes:
            self._navigation_extent()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
                                                       
            delta = (event.pixelDelta().y() or event.pixelDelta().x()) * 3
        if not delta or not self.nodes:
            event.accept()
            return
        self._user_view = True
        self._fit_pending = False
        cursor = event.position().toPoint()
        anchor = self.mapToScene(cursor)
        center = self.mapToScene(self.viewport().rect().center())
        current = self.transform().m11()
        minimum = min(0.08, self._fit_scale())
        steps = max(-30.0, min(30.0, delta / 120.0))
        target = min(3.0, max(minimum, current * (1.16 ** steps)))
        self.scale(target / current, target / current)
        self._navigation_extent(center)
                                                                               
        shifted = self.mapToScene(cursor)
        center = self.mapToScene(self.viewport().rect().center())
        self.centerOn(center + anchor - shifted)
        event.accept()

    def mousePressEvent(self, event):
        self._user_view = True
        self._fit_pending = False
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_0:
            self.fit_graph()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        previous = (Qt.Key.Key_Left, Qt.Key.Key_Up)
        following = (Qt.Key.Key_Right, Qt.Key.Key_Down)
        if self._order and key in previous + following + (Qt.Key.Key_Home, Qt.Key.Key_End):
            index = self._order.index(self._selected) if self._selected in self._order else 0
            if key == Qt.Key.Key_Home:
                index = 0
            elif key == Qt.Key.Key_End:
                index = len(self._order) - 1
            else:
                index += -1 if key in previous else 1
            index = min(len(self._order) - 1, max(0, index))
            self.select_commit(self._order[index])
            event.accept()
            return
        super().keyPressEvent(event)
