import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, 
                             QPushButton, QGroupBox, QFormLayout, QStackedWidget, 
                             QListWidget, QWidget, QGridLayout)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from app.ui.theme import apply_dialog_style

class NewModelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Model Initialization")
        self.resize(600, 450)
        apply_dialog_style(self)
        
        self.selected_units = "kN, m, C"
        self.grid_data = {} 
        self.accepted_data = False 
        self.template_type = "Grid Only" 

        main_layout = QHBoxLayout(self)

        left_layout = QVBoxLayout()
        self.template_list = QListWidget()
        self.template_list.addItems(["Blank", "Grid Only", "2D Frame", "3D Frame"])
        self.template_list.setCurrentRow(1) 
        self.template_list.currentRowChanged.connect(self.on_template_changed)
        self.template_list.setMaximumWidth(150)
        left_layout.addWidget(QLabel("<b>Model Templates</b>"))
        left_layout.addWidget(self.template_list)
        main_layout.addLayout(left_layout)

        right_layout = QVBoxLayout()

        unit_group = QGroupBox("Project Units")
        unit_layout = QFormLayout()
        self.unit_combo = QComboBox()
        self.unit_combo.addItems([
            "kN, m, C", 
            "N, m, C", 
            "N, mm, C", 
            "kN, mm, C",
            "Tonf, m, C",
            "kgf, m, C",
            "kip, ft, F"
        ])
        unit_layout.addRow("Default Units:", self.unit_combo)
        unit_group.setLayout(unit_layout)
        right_layout.addWidget(unit_group)

        self.stack = QStackedWidget()

        self.page_blank = QWidget()
        blank_layout = QVBoxLayout(self.page_blank)
        blank_layout.addWidget(QLabel("Start with a completely empty workspace.\nNo grids or structural elements will be created."))
        blank_layout.addStretch()

        self.page_grid = QWidget()
        grid_layout = QFormLayout(self.page_grid)
        
        self.input_x_num = QSpinBox(); self.input_x_num.setRange(1, 100); self.input_x_num.setValue(4)
        self.input_x_dist = QDoubleSpinBox(); self.input_x_dist.setRange(0.1, 1000); self.input_x_dist.setValue(6.0)
        
        self.input_y_num = QSpinBox(); self.input_y_num.setRange(1, 100); self.input_y_num.setValue(1)
        self.input_y_dist = QDoubleSpinBox(); self.input_y_dist.setRange(0.1, 1000); self.input_y_dist.setValue(1.0)
        
        self.input_z_num = QSpinBox(); self.input_z_num.setRange(1, 100); self.input_z_num.setValue(3)
        self.input_z_dist = QDoubleSpinBox(); self.input_z_dist.setRange(0.1, 1000); self.input_z_dist.setValue(3.0)

        grid_layout.addRow(QLabel("<b>X Direction</b>"))
        grid_layout.addRow("Number of Grid Lines:", self.input_x_num)
        grid_layout.addRow("Spacing:", self.input_x_dist)
        
        grid_layout.addRow(QLabel("<b>Y Direction</b>"))
        grid_layout.addRow("Number of Grid Lines:", self.input_y_num)
        grid_layout.addRow("Spacing:", self.input_y_dist)
        
        grid_layout.addRow(QLabel("<b>Z Direction (Height)</b>"))
        grid_layout.addRow("Number of Grid Lines:", self.input_z_num)
        grid_layout.addRow("Spacing:", self.input_z_dist)

        self.page_2d = QWidget()
        p2d_layout = QFormLayout(self.page_2d)
        self.input_2d_stories = QSpinBox(); self.input_2d_stories.setRange(1, 100); self.input_2d_stories.setValue(2)
        self.input_2d_bays = QSpinBox(); self.input_2d_bays.setRange(1, 100); self.input_2d_bays.setValue(3)
        self.input_2d_story_ht = QDoubleSpinBox(); self.input_2d_story_ht.setRange(0.1, 1000); self.input_2d_story_ht.setValue(3.0)
        self.input_2d_bay_wd = QDoubleSpinBox(); self.input_2d_bay_wd.setRange(0.1, 1000); self.input_2d_bay_wd.setValue(6.0)
        
        p2d_layout.addRow("Number of Stories (Z):", self.input_2d_stories)
        p2d_layout.addRow("Story Height:", self.input_2d_story_ht)
        p2d_layout.addRow("Number of Bays (X):", self.input_2d_bays)
        p2d_layout.addRow("Bay Width:", self.input_2d_bay_wd)

        self.page_3d = QWidget()
        p3d_layout = QFormLayout(self.page_3d)
        self.input_3d_stories = QSpinBox(); self.input_3d_stories.setRange(1, 100); self.input_3d_stories.setValue(2)
        self.input_3d_story_ht = QDoubleSpinBox(); self.input_3d_story_ht.setRange(0.1, 1000); self.input_3d_story_ht.setValue(3.0)
        
        self.input_3d_bays_x = QSpinBox(); self.input_3d_bays_x.setRange(1, 100); self.input_3d_bays_x.setValue(3)
        self.input_3d_bay_wd_x = QDoubleSpinBox(); self.input_3d_bay_wd_x.setRange(0.1, 1000); self.input_3d_bay_wd_x.setValue(6.0)
        
        self.input_3d_bays_y = QSpinBox(); self.input_3d_bays_y.setRange(1, 100); self.input_3d_bays_y.setValue(2)
        self.input_3d_bay_wd_y = QDoubleSpinBox(); self.input_3d_bay_wd_y.setRange(0.1, 1000); self.input_3d_bay_wd_y.setValue(6.0)

        p3d_layout.addRow("Number of Stories (Z):", self.input_3d_stories)
        p3d_layout.addRow("Story Height:", self.input_3d_story_ht)
        p3d_layout.addRow(QLabel("<b>X Direction</b>"))
        p3d_layout.addRow("Number of Bays:", self.input_3d_bays_x)
        p3d_layout.addRow("Bay Width:", self.input_3d_bay_wd_x)
        p3d_layout.addRow(QLabel("<b>Y Direction</b>"))
        p3d_layout.addRow("Number of Bays:", self.input_3d_bays_y)
        p3d_layout.addRow("Bay Width:", self.input_3d_bay_wd_y)

        self.stack.addWidget(self.page_blank) 
        self.stack.addWidget(self.page_grid)  
        self.stack.addWidget(self.page_2d)    
        self.stack.addWidget(self.page_3d)    
        
        right_layout.addWidget(self.stack)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self.on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        right_layout.addLayout(btn_layout)

        main_layout.addLayout(right_layout)

    def on_template_changed(self, index):
        self.stack.setCurrentIndex(index)
        self.template_type = self.template_list.currentItem().text()

    def on_ok(self):
        """Validates input and saves data based on selected template"""
        self.selected_units = self.unit_combo.currentText()
        
        if self.template_type == "Blank":
            self.grid_data = {
                'x_num': 1, 'x_dist': 1.0,
                'y_num': 1, 'y_dist': 1.0,
                'z_num': 1, 'z_dist': 1.0,
            }
        elif self.template_type == "Grid Only":
            self.grid_data = {
                'x_num': self.input_x_num.value(),
                'x_dist': self.input_x_dist.value(),
                'y_num': self.input_y_num.value(),
                'y_dist': self.input_y_dist.value(),
                'z_num': self.input_z_num.value(),
                'z_dist': self.input_z_dist.value(),
            }
        elif self.template_type == "2D Frame":
            self.grid_data = {
                'x_num': self.input_2d_bays.value() + 1,
                'x_dist': self.input_2d_bay_wd.value(),
                'y_num': 1,
                'y_dist': 1.0,
                'z_num': self.input_2d_stories.value() + 1,
                'z_dist': self.input_2d_story_ht.value(),
                'generate_frame': '2D'
            }
        elif self.template_type == "3D Frame":
            self.grid_data = {
                'x_num': self.input_3d_bays_x.value() + 1,
                'x_dist': self.input_3d_bay_wd_x.value(),
                'y_num': self.input_3d_bays_y.value() + 1,
                'y_dist': self.input_3d_bay_wd_y.value(),
                'z_num': self.input_3d_stories.value() + 1,
                'z_dist': self.input_3d_story_ht.value(),
                'generate_frame': '3D'
            }
            
        self.accepted_data = True
        self.accept()
