from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QListWidget, QPushButton, QFormLayout, QComboBox, 
                             QGroupBox, QGridLayout, QFrame)
from PyQt6.QtCore import Qt, QRect, QRectF, QPointF, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QPolygonF
from app.section_designer.section_designer_dialog import SectionDesignerDialog
from app.ui.theme import apply_dialog_style

class ShapeCard(QFrame):
    """Clickable visual card for section selection."""
                                      
    def __init__(self, shape_id: str, label: str, internal_index: int, gateway, parent=None):
        super().__init__(parent)
        self.shape_id = shape_id
        self.label = label
        self.internal_index = internal_index
        self.gateway = gateway                                              
        self._hovered = False

        self.setFixedSize(100, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
                                                             
            self.gateway._shape_clicked(self.shape_id, self.internal_index)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        bg = QColor("#F0F0F0") if self._hovered else QColor("#FFFFFF")
        border = QColor("#0078D7") if self._hovered else QColor("#D0D0D0")
        
        p.setBrush(QBrush(bg))
        p.setPen(QPen(border, 1 if not self._hovered else 2))
        p.drawRoundedRect(2, 2, w - 4, h - 4, 3, 3)

        cx, cy = w / 2, (h - 25) / 2
        p.setBrush(QBrush(QColor(200, 200, 200)))
        p.setPen(QPen(Qt.GlobalColor.black, 1.5))

        if self.shape_id == "rect":
            p.drawRect(QRectF(cx - 15, cy - 25, 30, 50))
            
        elif self.shape_id == "circ":
            p.drawEllipse(QPointF(cx, cy), 20, 20)
            
        elif self.shape_id == "pipe":
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy), 22, 22)
            path.addEllipse(QPointF(cx, cy), 15, 15)
            path.setFillRule(Qt.FillRule.OddEvenFill)
            p.drawPath(path)
            
        elif self.shape_id == "tube":
            path = QPainterPath()
            path.addRect(QRectF(cx - 20, cy - 25, 40, 50))
            path.addRect(QRectF(cx - 14, cy - 19, 28, 38))
            path.setFillRule(Qt.FillRule.OddEvenFill)
            p.drawPath(path)
            
        elif self.shape_id == "trap":
            poly = QPolygonF([
                QPointF(cx - 25, cy - 25),
                QPointF(cx + 25, cy - 25),
                QPointF(cx + 15, cy + 25),
                QPointF(cx - 15, cy + 25)
            ])
            p.drawPolygon(poly)
            
        elif self.shape_id in ["i_sec", "import_i"]:
            poly = QPolygonF([
                QPointF(cx - 22, cy - 25), QPointF(cx + 22, cy - 25),                 
                QPointF(cx + 22, cy - 15), QPointF(cx + 4, cy - 15),                    
                QPointF(cx + 4, cy + 15), QPointF(cx + 22, cy + 15),                             
                QPointF(cx + 22, cy + 25), QPointF(cx - 22, cy + 25),                 
                QPointF(cx - 22, cy + 15), QPointF(cx - 4, cy + 15),                    
                QPointF(cx - 4, cy - 15), QPointF(cx - 22, cy - 15),                             
            ])
            p.drawPolygon(poly)

        elif self.shape_id == "precast_i":
                                           
            poly = QPolygonF([
                QPointF(cx - 15, cy - 25), QPointF(cx + 15, cy - 25),           
                QPointF(cx + 15, cy - 15), QPointF(cx + 5, cy - 10),             
                QPointF(cx + 5, cy + 10), QPointF(cx + 20, cy + 18),                    
                QPointF(cx + 20, cy + 25), QPointF(cx - 20, cy + 25),           
                QPointF(cx - 20, cy + 18), QPointF(cx - 5, cy + 10),               
                QPointF(cx - 5, cy - 10), QPointF(cx - 15, cy - 15)                       
            ])
            p.drawPolygon(poly)
            
        elif self.shape_id == "precast_u":
                                           
            poly = QPolygonF([
                QPointF(cx - 25, cy - 25), QPointF(cx - 15, cy - 25),             
                QPointF(cx - 10, cy + 15), QPointF(cx + 10, cy + 15),               
                QPointF(cx + 15, cy - 25), QPointF(cx + 25, cy - 25),             
                QPointF(cx + 18, cy + 25), QPointF(cx - 18, cy + 25)                
            ])
            p.drawPolygon(poly)
            
        elif self.shape_id == "gen":
                                           
            path = QPainterPath()
            path.moveTo(cx - 10, cy - 25)
            path.cubicTo(cx + 25, cy - 35, cx + 35, cy + 15, cx + 10, cy + 25)
            path.cubicTo(cx - 25, cy + 35, cx - 35, cy + 5, cx - 10, cy - 25)
            p.drawPath(path)
            
        elif self.shape_id == "sec_designer":
                                         
            p.drawRect(QRectF(cx - 22, cy - 25, 30, 30))
            p.drawEllipse(QPointF(cx + 5, cy + 5), 18, 18)

        p.setPen(QPen(QColor("#1A1A1A")))
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)
        p.drawText(QRect(0, h - 30, w, 30), Qt.AlignmentFlag.AlignCenter, self.label)
        p.end()

class AddFrameSectionPropertyDialog(QDialog):
    def __init__(self, main_manager, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.main_manager = main_manager                                          
        self.setWindowTitle("Add Frame Section Property")
        self.resize(550, 450)
        
        layout = QVBoxLayout(self)
        
        cat_group = QGroupBox("Select Property Type")
        cat_layout = QFormLayout(cat_group)
        self.category_combo = QComboBox()
        self.category_combo.addItems(["Concrete", "Steel", "Other", "Import"])
        self.category_combo.currentIndexChanged.connect(self._update_cards)
        cat_layout.addRow("Frame Section Property Type", self.category_combo)
        layout.addWidget(cat_group)
        
        self.cards_group = QGroupBox("Click to Add a Section")
        self.cards_layout = QGridLayout(self.cards_group)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.cards_group, 1)                   

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel, 0, Qt.AlignmentFlag.AlignCenter)

        self._update_cards()                        

    def _update_cards(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cat = self.category_combo.currentText()
        cards_to_show = []

        if cat == "Concrete":
            cards_to_show = [
                ("rect", "Rectangular", 0),
                ("circ", "Circular", 2),
                ("pipe", "Pipe", 3),
                ("tube", "Tube", 4),
                ("trap", "Trapezoidal", 5),
                ("precast_i", "Precast I", -3),                   
                ("precast_u", "Precast U", -4),                   
            ]
        elif cat == "Steel":
            cards_to_show = [
                ("i_sec", "I / Wide Flange", 1),
                ("tube", "Tube", 4),
                ("pipe", "Pipe", 3),
                ("rect", "Rectangular", 0),                     
                ("circ", "Circular", 2),                     
            ]
        elif cat == "Other":
            cards_to_show = [
                ("gen", "General", 6),
                ("sec_designer", "Section Designer", -1),
            ]
        elif cat == "Import":
            cards_to_show = [
                ("import_i", "Steel I-Beam", -2),
            ]

        col_count = 4
        for i, (s_id, lbl, idx) in enumerate(cards_to_show):
            row = i // col_count
            col = i % col_count
                                          
            card = ShapeCard(s_id, lbl, idx, gateway=self, parent=self.cards_group)
            self.cards_layout.addWidget(card, row, col)

    def _shape_clicked(self, shape_id: str, internal_index: int):
        """Routing logic when a card is clicked."""
        self.accept()                                  
        
        if internal_index == -1:                   
            from app.dialogs.section_dialog import AddSectionDialog
            dlg = SectionDesignerDialog(self.main_manager.model, parent=self.main_manager)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.main_manager.model.add_section(dlg.result_section)
                self.main_manager.refresh_list()
                
        elif internal_index == -2:              
            self.main_manager.import_aisc_section()
            
        elif internal_index == -3:                        
            dlg = SectionDesignerDialog(self.main_manager.model, parent=self.main_manager)
            QTimer.singleShot(0, dlg._from_precast_i)                                           
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.main_manager.model.add_section(dlg.result_section)
                self.main_manager.refresh_list()
                
        elif internal_index == -4:                        
            dlg = SectionDesignerDialog(self.main_manager.model, parent=self.main_manager)
            QTimer.singleShot(0, dlg._from_precast_u)                                           
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.main_manager.model.add_section(dlg.result_section)
                self.main_manager.refresh_list()
            
        else:                            
            from app.dialogs.section_dialog import AddSectionDialog
            dlg = AddSectionDialog(self.main_manager.model, parent=self.main_manager, preselected_index=internal_index)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.main_manager.refresh_list()
