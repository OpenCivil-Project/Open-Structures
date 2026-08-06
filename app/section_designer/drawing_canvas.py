"""
drawing_canvas.py
-----------------
The interactive 2-D drawing canvas for the Section Designer.

Responsibilities
----------------
- Draw a SAP2000-style grid with local 2-3 axes at the origin
- Let the user click to place polygon vertices (DRAW mode)
- Show a live rubber-band edge from the last placed vertex to the cursor
- Close the polygon when the user clicks near the first vertex or double-clicks
- Pan (middle-mouse drag or Space+drag) and zoom (wheel)
- Show the computed centroid + principal axes after analysis
- Drag existing vertices in SELECT mode
- Coordinate-input popup (Tab key while drawing)
- Full undo / redo via QUndoStack (Ctrl+Z / Ctrl+Y)
- Emit signals so the parent dialog can update the status bar and buttons

Coordinate convention
---------------------
World space  : (y, z) in base SI metres — same as get_shape_coords().
               y grows rightward (local-2 / horizontal)
               z grows upward    (local-3 / vertical)
Qt pixel space: x grows right, y grows DOWN → z is flipped when converting.

All vertices stored internally are in base SI metres.
The SnapGrid handles all pixel ↔ world conversion and snapping.
"""

import math
from enum import Enum, auto

from PyQt6.QtWidgets import (
    QWidget, QDialog, QFormLayout, QDialogButtonBox, QDoubleSpinBox, QLabel,
)
from PyQt6.QtCore    import Qt, pyqtSignal, QPoint, QPointF
from PyQt6.QtGui     import (
    QPainter, QColor, QPen, QBrush, QPainterPath,
    QPolygonF, QCursor, QUndoStack,
)

from app.section_designer.snap_grid import SnapGrid

class DrawMode(Enum):
    DRAW   = auto()
    SELECT = auto()
    PAN    = auto()

_BG          = QColor(255, 255, 255)
_GRID_MINOR  = QColor(220, 220, 220)
_GRID_MAJOR  = QColor(190, 190, 190)
_AXIS_Y      = QColor( 30, 160,  30)
_AXIS_Z      = QColor(200,  30,  30)
_AXIS_LABEL  = QColor(100, 100, 100)

_POLY_FILL_OPEN   = QColor( 80, 130, 220,  45)
_POLY_FILL_CLOSED = QColor( 80, 130, 220,  70)
_POLY_EDGE        = QColor( 30,  80, 200)
_POLY_EDGE_W      = 2.0

_VERTEX_FILL      = QColor( 30,  80, 200)
_VERTEX_FIRST     = QColor(220,  30,  30)
_VERTEX_R         = 4
_VERTEX_R_FIRST   = 6
_VERTEX_HIT_R     = 10                                        

_PREVIEW_EDGE     = QColor(140, 140, 140)
_PREVIEW_SNAP     = QColor( 30,  80, 200, 160)

_CENTROID_COL     = QColor(220,  30,  30)
_CENTROID_R       = 5

_PRINCIPAL_1_COL  = QColor(200, 100,  30)                                 
_PRINCIPAL_2_COL  = QColor( 30, 150, 200)                               

_SELECTED_V_COL   = QColor(255, 165,   0)                                        
_SELECTED_V_RING  = QColor(200, 100,   0)

_CLOSE_THRESHOLD  = 12                                   

class DrawingCanvas(QWidget):
    """
    Interactive polygon-drawing canvas for the Section Designer.

    Signals
    -------
    coords_changed(str)      — formatted coordinate string for the status bar
    polygon_changed(list)    — emitted whenever vertices list changes;
                               payload is list of (y,z) world tuples
    polygon_closed()         — emitted once when the polygon is completed
    coord_input_requested(float, float)
                             — Tab key pressed in DRAW mode; payload is the
                               current snapped (y, z) so the dialog can open
                               a coordinate-input popup pre-filled
    """

    coords_changed         = pyqtSignal(str)
    polygon_changed        = pyqtSignal(list)
    polygon_closed         = pyqtSignal()
    coord_input_requested  = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 400)

        self._grid = SnapGrid(snap_enabled=True)

        self._mode: DrawMode   = DrawMode.DRAW
        self._vertices: list   = []
        self._is_closed: bool  = False
        self._preview: tuple   = (0.0, 0.0)
        self._near_close: bool = False

        self._centroid: tuple | None        = None
        self._principal_angle: float | None = None

        self._panning:    bool   = False
        self._pan_last:   QPoint = QPoint()
        self._space_held: bool   = False

        self._selected_vertex_idx: int | None   = None
        self._drag_vertex_start:   tuple | None = None
        self._dragging_vertex:     bool         = False

        self._undo_stack = QUndoStack(self)

        self._grid.set_scale(200.0)

    def set_mode(self, mode: DrawMode):
        """Switch tool mode. Called by the toolbar."""
        self._mode = mode
        self._selected_vertex_idx = None
        self._dragging_vertex     = False
        if mode == DrawMode.PAN:
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        elif mode == DrawMode.SELECT:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.update()

    def set_snap(self, enabled: bool):
        self._grid.snap_enabled = enabled
        self.update()

    def set_grid_step(self, step_display: float):
        self._grid.set_grid_step_display(step_display)
        self.update()

    @property
    def snap_grid(self) -> SnapGrid:
        return self._grid

    def get_vertices(self) -> list:
        """Return a copy of vertices as (y, z) tuples in base SI metres."""
        return list(self._vertices)

    def set_vertices(self, vertices: list):
        """
        Load an existing polygon (e.g. re-opening an ArbitrarySection).
        Vertices must be (y, z) tuples in base SI metres.
        Clears the undo stack — this is a load operation, not an edit.
        """
        self._vertices        = list(vertices)
        self._is_closed       = len(vertices) >= 3
        self._centroid        = None
        self._principal_angle = None
        self._selected_vertex_idx = None
        self._undo_stack.clear()
        self.update()
        self.polygon_changed.emit(list(self._vertices))

    def push_shape(self, vertices: list, description: str = "Set Shape"):
        """
        Replace the polygon with a shape-generator result, with full undo support.
        Called by the dialog's shape-template buttons.
        """
                                                              
        from app.section_designer.section_designer_commands import CmdSetVertices
        old = list(self._vertices)
        self._undo_stack.push(CmdSetVertices(self, old, vertices, description))

    def place_vertex_at(self, y_w: float, z_w: float):
        """
        Place a vertex at an explicit world coordinate.
        Used by the coordinate-input popup (Tab key).
        """
        if self._is_closed:
            return
        from app.section_designer.section_designer_commands import (
            CmdAddVertex, CmdClosePolygon,
        )
        if len(self._vertices) >= 3:
            v0_px  = self._grid.world_to_pixel(*self._vertices[0])
            pt_px  = self._grid.world_to_pixel(y_w, z_w)
            dist   = ((pt_px[0] - v0_px[0])**2 + (pt_px[1] - v0_px[1])**2) ** 0.5
            if dist < _CLOSE_THRESHOLD:
                self._undo_stack.push(CmdClosePolygon(self))
                return
        self._undo_stack.push(CmdAddVertex(self, (y_w, z_w)))

    def reset(self):
        """Clear all vertices and centroid, return to empty canvas."""
        self._vertices        = []
        self._is_closed       = False
        self._centroid        = None
        self._principal_angle = None
        self._near_close      = False
        self._selected_vertex_idx = None
        self._dragging_vertex     = False
        self._undo_stack.clear()
        self.update()
        self.polygon_changed.emit([])

    def set_centroid(self, y_c: float, z_c: float):
        """Show the centroid marker after running analysis."""
        self._centroid = (y_c, z_c)
        self.update()

    def set_principal_angle(self, theta: float):
        """Set principal axis angle (radians) for the overlay lines."""
        self._principal_angle = theta
        self.update()

    def clear_centroid(self):
        self._centroid        = None
        self._principal_angle = None
        self.update()

    def undo(self):
        self._undo_stack.undo()

    def redo(self):
        self._undo_stack.redo()

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    @property
    def vertex_count(self) -> int:
        return len(self._vertices)

    def zoom_to_fit(self):
        if not self._vertices:
            self._grid.set_origin(self.width() / 2, self.height() / 2)
            self._grid.set_scale(200.0)
            self.update()
            return

        ys    = [v[0] for v in self._vertices]
        zs    = [v[1] for v in self._vertices]
        y_span = max(ys) - min(ys) or 1.0
        z_span = max(zs) - min(zs) or 1.0

        pad     = 0.20
        scale_y = self.width()  / (y_span * (1 + 2 * pad))
        scale_z = self.height() / (z_span * (1 + 2 * pad))
        self._grid.set_scale(min(scale_y, scale_z))

        y_mid = (max(ys) + min(ys)) / 2
        z_mid = (max(zs) + min(zs)) / 2
        cx, cy = self._grid.world_to_pixel(y_mid, z_mid)
        self._grid.pan(self.width() / 2 - cx, self.height() / 2 - cy)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._grid.set_origin(self.width() / 2, self.height() / 2)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        gl   = self._grid.grid_lines(w, h)

        p.fillRect(0, 0, w, h, _BG)
        self._draw_grid(p, gl)
        self._draw_axes(p, gl['origin_px'])                                   

        if self._vertices:
            self._draw_polygon(p)

        if self._mode == DrawMode.DRAW and self._vertices and not self._is_closed:
            self._draw_preview_edge(p)

        if self._centroid is not None:
            self._draw_centroid(p)

        if self._mode == DrawMode.DRAW and not self._is_closed:
            self._draw_snap_cursor(p)

        self._draw_corner_axes(p)

        p.end()

    def mousePressEvent(self, event):
        btn = event.button()
        pos = event.position()

        if btn == Qt.MouseButton.MiddleButton or (
            btn == Qt.MouseButton.LeftButton and self._space_held
        ):
            self._panning  = True
            self._pan_last = event.position().toPoint()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            return

        if btn == Qt.MouseButton.LeftButton:
            if self._mode == DrawMode.PAN:
                self._panning  = True
                self._pan_last = event.position().toPoint()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                return

            if self._mode == DrawMode.DRAW and not self._is_closed:
                self._place_vertex(pos.x(), pos.y())
                return

            if self._mode == DrawMode.SELECT:
                self._try_select_vertex(pos.x(), pos.y())
                return

        elif btn == Qt.MouseButton.RightButton:
            if self._mode == DrawMode.DRAW and len(self._vertices) >= 3 and not self._is_closed:
                self._close_polygon()

    def mouseMoveEvent(self, event):
        pos = event.position()

        if self._panning:
            cur = event.position().toPoint()
            self._grid.pan(cur.x() - self._pan_last.x(),
                           cur.y() - self._pan_last.y())
            self._pan_last = cur
            self.update()
            return

        if (self._mode == DrawMode.SELECT
                and self._dragging_vertex
                and self._selected_vertex_idx is not None):
            y, z = self._grid.pixel_to_snapped_world(pos.x(), pos.y())
            self._vertices[self._selected_vertex_idx] = (y, z)
            self._centroid        = None
            self._principal_angle = None
            self.polygon_changed.emit(list(self._vertices))
            self.update()
            return

        y, z = self._grid.pixel_to_snapped_world(pos.x(), pos.y())
        self._preview = (y, z)

        self._near_close = False
        if self._vertices and not self._is_closed and len(self._vertices) >= 2:
            v0_px = self._grid.world_to_pixel(*self._vertices[0])
            dist  = ((pos.x() - v0_px[0])**2 + (pos.y() - v0_px[1])**2) ** 0.5
            self._near_close = dist < _CLOSE_THRESHOLD

        if self._mode == DrawMode.SELECT and self._vertices:
            near_v = any(
                ((pos.x() - self._grid.world_to_pixel(yw, zw)[0])**2 +
                 (pos.y() - self._grid.world_to_pixel(yw, zw)[1])**2) ** 0.5
                < _VERTEX_HIT_R
                for yw, zw in self._vertices
            )
            self.setCursor(QCursor(
                Qt.CursorShape.SizeAllCursor if near_v else Qt.CursorShape.ArrowCursor
            ))

        self.coords_changed.emit(self._grid.format_coords(y, z))
        self.update()

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            if self._mode == DrawMode.PAN:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            elif self._mode == DrawMode.SELECT:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            return

        if (self._mode == DrawMode.SELECT
                and self._dragging_vertex
                and self._selected_vertex_idx is not None):
            new_pos = self._vertices[self._selected_vertex_idx]
            old_pos = self._drag_vertex_start
            if new_pos != old_pos:
                from app.section_designer.section_designer_commands import CmdMoveVertex
                cmd = CmdMoveVertex(self, self._selected_vertex_idx, old_pos, new_pos)
                                                                              
                self._undo_stack.push(cmd)
            self._dragging_vertex = False

    def mouseDoubleClickEvent(self, event):
        if (self._mode == DrawMode.DRAW
                and event.button() == Qt.MouseButton.LeftButton
                and len(self._vertices) >= 3
                and not self._is_closed):
            self._close_polygon()

    def wheelEvent(self, event):
        delta  = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        pos    = event.position()

        y_before, z_before = self._grid.pixel_to_world(pos.x(), pos.y())
        self._grid.set_scale(self._grid.scale * factor)
        px_after, py_after = self._grid.world_to_pixel(y_before, z_before)
        self._grid.pan(pos.x() - px_after, pos.y() - py_after)
        self.update()

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        if key == Qt.Key.Key_Space:
            self._space_held = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                                                                 
            if self._vertices and not self._is_closed:
                self._undo_stack.undo()

        elif key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            self._undo_stack.undo()

        elif key == Qt.Key.Key_Y and mods & Qt.KeyboardModifier.ControlModifier:
            self._undo_stack.redo()

        elif (key == Qt.Key.Key_Tab
              and self._mode == DrawMode.DRAW
              and not self._is_closed):
                                         
            self.coord_input_requested.emit(*self._preview)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_held = False
            if self._mode == DrawMode.PAN:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            elif self._mode == DrawMode.SELECT:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def _place_vertex(self, px: float, py: float):
        """Add a vertex at the snapped world position of pixel (px, py)."""
        from app.section_designer.section_designer_commands import (
            CmdAddVertex, CmdClosePolygon,
        )
        y, z = self._grid.pixel_to_snapped_world(px, py)
        if len(self._vertices) >= 3 and self._near_close:
            self._undo_stack.push(CmdClosePolygon(self))
            return
        self._undo_stack.push(CmdAddVertex(self, (y, z)))

    def _close_polygon(self):
        """Seal the polygon via an undoable command."""
        if len(self._vertices) < 3:
            return
        from app.section_designer.section_designer_commands import CmdClosePolygon
        self._undo_stack.push(CmdClosePolygon(self))

    def _try_select_vertex(self, px: float, py: float):
        """Hit-test vertices and start a drag if one is close enough."""
        best_idx  = None
        best_dist = float(_VERTEX_HIT_R)
        for i, (yw, zw) in enumerate(self._vertices):
            vx, vy = self._grid.world_to_pixel(yw, zw)
            dist   = ((px - vx)**2 + (py - vy)**2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_idx  = i

        self._selected_vertex_idx = best_idx
        if best_idx is not None:
            self._drag_vertex_start = self._vertices[best_idx]
            self._dragging_vertex   = True
        else:
            self._dragging_vertex = False
        self.update()

    def _draw_grid(self, p: QPainter, gl: dict):
        spacing = gl['spacing_px']
        ox, oy  = gl['origin_px']

        for x in gl['vertical']:
            idx = round((x - ox) / spacing) if spacing > 0 else 0
            col = _GRID_MAJOR if idx % 5 == 0 else _GRID_MINOR
            p.setPen(QPen(col, 0.5))
            p.drawLine(int(x), 0, int(x), self.height())

        for y in gl['horizontal']:
            idx = round((y - oy) / spacing) if spacing > 0 else 0
            col = _GRID_MAJOR if idx % 5 == 0 else _GRID_MINOR
            p.setPen(QPen(col, 0.5))
            p.drawLine(0, int(y), self.width(), int(y))

    def _draw_axes(self, p: QPainter, origin_px: tuple):
        ox, oy = origin_px
        w, h   = self.width(), self.height()

        p.setPen(QPen(Qt.GlobalColor.black, 1.5))
        
        p.drawLine(0, int(oy), w, int(oy))

        p.drawLine(int(ox), 0, int(ox), h)

    def _draw_polygon(self, p: QPainter):
        verts = self._vertices
        if not verts:
            return

        pts = [QPointF(*self._grid.world_to_pixel(y, z)) for y, z in verts]

        if self._is_closed and len(pts) >= 3:
            poly = QPolygonF(pts)
            p.setBrush(QBrush(_POLY_FILL_CLOSED))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(poly)
        elif len(pts) >= 3:
            preview_px   = QPointF(*self._grid.world_to_pixel(*self._preview))
            preview_pts  = pts + [preview_px]
            poly = QPolygonF(preview_pts)
            p.setBrush(QBrush(_POLY_FILL_OPEN))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(poly)

        edge_pen = QPen(_POLY_EDGE, _POLY_EDGE_W)
        edge_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        edge_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(edge_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])
        if self._is_closed:
            p.drawLine(pts[-1], pts[0])

        p.setBrush(QBrush(_VERTEX_FILL))
        p.setPen(Qt.PenStyle.NoPen)
        for i, pt in enumerate(pts):
            if i == 0:
                p.setBrush(QBrush(_VERTEX_FIRST))
                p.drawEllipse(pt, float(_VERTEX_R_FIRST), float(_VERTEX_R_FIRST))
                p.setBrush(QBrush(_VERTEX_FILL))
            else:
                p.drawEllipse(pt, float(_VERTEX_R), float(_VERTEX_R))

        if (self._mode == DrawMode.SELECT
                and self._selected_vertex_idx is not None
                and 0 <= self._selected_vertex_idx < len(pts)):
            idx = self._selected_vertex_idx
            p.setBrush(QBrush(_SELECTED_V_COL))
            p.setPen(QPen(_SELECTED_V_RING, 1.5))
            p.drawEllipse(pts[idx],
                          float(_VERTEX_R + 3), float(_VERTEX_R + 3))

    def _draw_preview_edge(self, p: QPainter):
        if not self._vertices:
            return
        last_px  = QPointF(*self._grid.world_to_pixel(*self._vertices[-1]))
        mouse_px = QPointF(*self._grid.world_to_pixel(*self._preview))

        pen = QPen(_PREVIEW_EDGE, 1.2)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(last_px, mouse_px)

        if len(self._vertices) >= 2 and self._near_close:
            first_px  = QPointF(*self._grid.world_to_pixel(*self._vertices[0]))
            close_pen = QPen(_VERTEX_FIRST, 1.0)
            close_pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(close_pen)
            p.drawLine(mouse_px, first_px)

    def _draw_centroid(self, p: QPainter):
        yc, zc = self._centroid
        cx, cy = self._grid.world_to_pixel(yc, zc)
        r = _CENTROID_R

        p.setPen(QPen(_CENTROID_COL, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), float(r), float(r))

        axis_len = 45

        lbl_font = p.font()
        lbl_font.setBold(True)
        lbl_font.setPointSize(9)
        p.setFont(lbl_font)

        p.setPen(QPen(QColor(30, 80, 220), 2))
        p.drawLine(int(cx), int(cy), int(cx) - axis_len, int(cy))
                   
        p.drawLine(int(cx) - axis_len, int(cy), int(cx) - axis_len + 5, int(cy) - 4)
        p.drawLine(int(cx) - axis_len, int(cy), int(cx) - axis_len + 5, int(cy) + 4)
        p.drawText(int(cx) - axis_len - 14, int(cy) + 4, "3")

        p.setPen(QPen(_AXIS_Y, 2))  
        p.drawLine(int(cx), int(cy), int(cx), int(cy) - axis_len)
                   
        p.drawLine(int(cx), int(cy) - axis_len, int(cx) - 4, int(cy) - axis_len + 5)
        p.drawLine(int(cx), int(cy) - axis_len, int(cx) + 4, int(cy) - axis_len + 5)
        p.drawText(int(cx) + 8, int(cy) - axis_len + 4, "2")

    def _draw_snap_cursor(self, p: QPainter):
        """Small crosshair at snapped cursor position."""
        mx, my = self._grid.world_to_pixel(*self._preview)
        p.setPen(QPen(_PREVIEW_SNAP, 1))
        sz = 6
        p.drawLine(int(mx) - sz, int(my), int(mx) + sz, int(my))
        p.drawLine(int(mx), int(my) - sz, int(mx), int(my) + sz)

    def _draw_corner_axes(self, p: QPainter):
        """Fixed orientation indicator in the bottom-right corner (SAP2000 style)."""
        w, h = self.width(), self.height()
        
        origin_x = w - 40
        origin_y = h - 35
        axis_len = 45

        p.setPen(QPen(Qt.GlobalColor.black, 2))
        
        p.drawLine(origin_x, origin_y, origin_x - axis_len, origin_y)
                         
        p.drawLine(origin_x - axis_len, origin_y, origin_x - axis_len + 6, origin_y - 4)
        p.drawLine(origin_x - axis_len, origin_y, origin_x - axis_len + 6, origin_y + 4)
        
        p.drawLine(origin_x, origin_y, origin_x, origin_y - axis_len)
                         
        p.drawLine(origin_x, origin_y - axis_len, origin_x - 4, origin_y - axis_len + 6)
        p.drawLine(origin_x, origin_y - axis_len, origin_x + 4, origin_y - axis_len + 6)

        lbl_font = p.font()
        lbl_font.setBold(True)
        lbl_font.setPointSize(10)
        p.setFont(lbl_font)
        
        p.drawText(origin_x - axis_len - 16, origin_y + 4, "3")
                                                      
        p.drawText(origin_x - 4, origin_y - axis_len - 10, "2")
