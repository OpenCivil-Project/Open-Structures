"""
Concrete Reinforcement dialog for Rectangular, Circular, and Trapezoidal
frame sections. Data-only: stores/loads a ReinforcementData object on the
parent section. No fiber generation, no rebar visualization — see
core/properties.py:ReinforcementData for the schema and the
architecture notes in that module's docstring.

Opened from AddSectionDialog via the "Concrete Reinforcement..." button
on the Rectangular / Circular / Trapezoidal pages. `config` ("rectangular"
or "circular") is passed in by the caller and matches the section shape —
it is NOT user-editable here, since a rectangular/trapezoidal section
always gets a rectangular perimeter bar pattern and a circular section
always gets a circular one.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QGroupBox, QRadioButton, QButtonGroup, QPushButton,
    QStackedWidget, QMessageBox, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from core.properties import ReinforcementData
from app.ui.theme import apply_dialog_style

def _rebar_materials(model):
    """Material names in the model whose mat_type is 'rebar'."""
    names = [m for m, mat in model.materials.items()
             if getattr(mat, "mat_type", "").lower() == "rebar"]
    return names

class ReinforcementDialog(QDialog):
    def __init__(self, model, config: str, reinforcement: ReinforcementData | None = None, parent=None):
        super().__init__(parent)
        apply_dialog_style(self)
        self.setWindowTitle("Reinforcement Data")
        self.setFixedWidth(440)                                         

        self.model = model
        self.config = config                                                                         
        self.result_data: ReinforcementData | None = None

        if not getattr(self.model, "rebar_sizes", []):
            import copy
            from app.dialogs.rebar_size_dialog import DEFAULT_REBARS
            self.model.rebar_sizes = copy.deepcopy(DEFAULT_REBARS)
            
        self.rebar_ids = [b["id"] for b in self.model.rebar_sizes]

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        mat_group = QGroupBox("Rebar Material")
        mat_form = QFormLayout(mat_group)
        rebar_names = _rebar_materials(model)

        self.combo_long_mat = QComboBox()
        self.combo_long_mat.addItems(rebar_names)
        mat_form.addRow("Longitudinal Bars:", self.combo_long_mat)

        self.combo_tie_mat = QComboBox()
        self.combo_tie_mat.addItems(rebar_names)
        mat_form.addRow("Confinement Bars (Ties):", self.combo_tie_mat)

        if not rebar_names:
            note = QLabel("No Rebar-type materials defined yet — add one via\nDefine Materials before setting reinforcement.")
            note.setStyleSheet("color: #b00; font-size: 10px;")
            mat_form.addRow(note)

        root.addWidget(mat_group)

        type_group = QGroupBox("Design Type")
        type_layout = QHBoxLayout(type_group)
        self.radio_column = QRadioButton("Column  (P-M2-M3 Design)")
        self.radio_beam = QRadioButton("Beam  (M3 Design Only)")
        self.radio_column.setChecked(True)
        self.design_type_grp = QButtonGroup(self)
        self.design_type_grp.addButton(self.radio_column)
        self.design_type_grp.addButton(self.radio_beam)
        type_layout.addWidget(self.radio_column)
        type_layout.addWidget(self.radio_beam)
        root.addWidget(type_group)

        self.radio_column.toggled.connect(self._on_design_type_changed)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_column_page())
        self.stack.addWidget(self._build_beam_page())
                                                                           
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.stack)
        root.addWidget(scroll, 1)

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            self.setMaximumHeight(int(screen.availableGeometry().height() * 0.9))

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self._save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        root.addLayout(btn_row)

        if reinforcement:
            self._load(reinforcement)

    def _build_column_page(self):
        page = QGroupBox()
        layout = QVBoxLayout(page)

        conf_group = QGroupBox("Confinement Bars")
        conf_layout = QHBoxLayout(conf_group)
        self.radio_ties = QRadioButton("Ties")
        self.radio_spiral = QRadioButton("Spiral")
        (self.radio_ties if self.config == "rectangular" else self.radio_spiral).setChecked(True)
        if self.config == "rectangular":
            self.radio_spiral.setEnabled(False)                                              
        conf_bgrp = QButtonGroup(self)
        conf_bgrp.addButton(self.radio_ties)
        conf_bgrp.addButton(self.radio_spiral)
        conf_layout.addWidget(self.radio_ties)
        conf_layout.addWidget(self.radio_spiral)
        layout.addWidget(conf_group)

        long_group = QGroupBox(f"Longitudinal Bars - {self.config.capitalize()} Configuration")
        long_form = QFormLayout(long_group)

        self.col_cover = QLineEdit("0.04")
        long_form.addRow("Clear Cover for Confinement Bars:", self.col_cover)

        if self.config == "rectangular":
            self.col_n3 = QLineEdit("3")
            long_form.addRow("Number of Longit Bars Along 3-dir Face:", self.col_n3)
            self.col_n2 = QLineEdit("3")
            long_form.addRow("Number of Longit Bars Along 2-dir Face:", self.col_n2)
        else:
            self.col_ncirc = QLineEdit("8")
            long_form.addRow("Number of Longitudinal Bars:", self.col_ncirc)

        self.col_bar_size = QComboBox()
        self.col_bar_size.addItems(self.rebar_ids)
        self.col_bar_size.setCurrentText("#9")
        long_form.addRow("Longitudinal Bar Size:", self.col_bar_size)

        layout.addWidget(long_group)

        tie_group = QGroupBox("Confinement Bars")
        tie_form = QFormLayout(tie_group)

        self.col_tie_size = QComboBox()
        self.col_tie_size.addItems(self.rebar_ids)
        self.col_tie_size.setCurrentText("#4")
        tie_form.addRow("Confinement Bar Size:", self.col_tie_size)

        self.col_tie_spacing = QLineEdit("0.15")
        tie_form.addRow("Longitudinal Spacing of Confinement Bars:", self.col_tie_spacing)

        if self.config == "rectangular":
            self.col_ties3 = QLineEdit("3")
            tie_form.addRow("Number of Confinement Bars in 3-dir:", self.col_ties3)
            self.col_ties2 = QLineEdit("3")
            tie_form.addRow("Number of Confinement Bars in 2-dir:", self.col_ties2)

        layout.addWidget(tie_group)

        self.os_group = QGroupBox("Tie Layout (OpenSees engine)")
        os_form = QFormLayout(self.os_group)
        self.col_tie_layout = QComboBox()
        self.col_tie_layout.addItem("Rectangular hoop + cross-ties", "rect")
        if self.config == "rectangular":
            self.col_tie_layout.addItem("Rectangular + octagonal ties (RO)", "rect_octagonal")
            self.col_tie_layout.addItem("Rectangular + interlocking ties (RI)", "rect_interlocking")
        os_form.addRow("Tie Layout:", self.col_tie_layout)
        self.col_rho_scale = QLineEdit("1.0")
        os_form.addRow("Tie Ratio (rho_s) Scale Factor:", self.col_rho_scale)
        os_note = QLabel("RO: enter the number of laterally supported bars per face in the\n"
                         "tie-count fields above (arching); the steel ratio is computed from the\n"
                         "hoop + inscribed octagon geometry. RI: enter the number of legs crossing a\n"
                         "section cut (e.g. 4) in the tie-count fields. Scale multiplies rho_x, rho_y.")
        os_note.setStyleSheet("color: gray; font-size: 10px; font-style: italic;")
        os_form.addRow(os_note)
        self.os_group.setVisible(getattr(self.model, "analysis_engine", "native") == "opensees")
        layout.addWidget(self.os_group)

        layout.addStretch()
        return page

    def _build_beam_page(self):
        page = QGroupBox()
        layout = QVBoxLayout(page)

        cover_group = QGroupBox("Concrete Cover to Longitudinal Rebar Center")
        cover_form = QFormLayout(cover_group)
        self.beam_cover_top = QLineEdit("0.06")
        cover_form.addRow("Top:", self.beam_cover_top)
        self.beam_cover_bot = QLineEdit("0.06")
        cover_form.addRow("Bottom:", self.beam_cover_bot)
        self.beam_cover_side = QLineEdit("0.04")
        cover_form.addRow("Side:", self.beam_cover_side)
        layout.addWidget(cover_group)

        bar_group = QGroupBox("Longitudinal Bars (as-built)")
        bar_form = QFormLayout(bar_group)
        self.beam_top_size = QComboBox(); self.beam_top_size.addItems(self.rebar_ids); self.beam_top_size.setCurrentText("#8")
        bar_form.addRow("Top Bar Size:", self.beam_top_size)
        self.beam_top_count = QLineEdit("3")
        bar_form.addRow("Top Bar Count:", self.beam_top_count)
        self.beam_bot_size = QComboBox(); self.beam_bot_size.addItems(self.rebar_ids); self.beam_bot_size.setCurrentText("#8")
        bar_form.addRow("Bottom Bar Size:", self.beam_bot_size)
        self.beam_bot_count = QLineEdit("3")
        bar_form.addRow("Bottom Bar Count:", self.beam_bot_count)
        layout.addWidget(bar_group)

        stirrup_group = QGroupBox("Confinement (Stirrups)")
        stirrup_form = QFormLayout(stirrup_group)
        self.beam_tie_size = QComboBox(); self.beam_tie_size.addItems(self.rebar_ids); self.beam_tie_size.setCurrentText("#3")
        stirrup_form.addRow("Stirrup Size:", self.beam_tie_size)
        self.beam_tie_spacing = QLineEdit("0.10")
        stirrup_form.addRow("Stirrup Spacing:", self.beam_tie_spacing)
        layout.addWidget(stirrup_group)

        layout.addStretch()
        return page

    def _on_design_type_changed(self, checked_column):
        self.stack.setCurrentIndex(0 if checked_column else 1)

    def _load(self, r: ReinforcementData):
        self.radio_column.setChecked(r.design_type == "column")
        self.radio_beam.setChecked(r.design_type == "beam")
        self.stack.setCurrentIndex(0 if r.design_type == "column" else 1)

        i = self.combo_long_mat.findText(r.long_bar_material)
        if i >= 0: self.combo_long_mat.setCurrentIndex(i)
        i = self.combo_tie_mat.findText(r.tie_bar_material)
        if i >= 0: self.combo_tie_mat.setCurrentIndex(i)

        if r.design_type == "column":
            self.col_cover.setText(str(r.clear_cover))
            self.col_bar_size.setCurrentText(r.long_bar_size or "#9")
            self.col_tie_size.setCurrentText(r.tie_bar_size or "#4")
            self.col_tie_spacing.setText(str(r.tie_spacing))
            self.radio_ties.setChecked(r.confinement_type == "ties")
            self.radio_spiral.setChecked(r.confinement_type == "spiral")
            i = self.col_tie_layout.findData(getattr(r, "tie_layout", "rect") or "rect")
            self.col_tie_layout.setCurrentIndex(i if i >= 0 else 0)
            self.col_rho_scale.setText(str(getattr(r, "rho_s_scale", 1.0)))
            if self.config == "rectangular":
                self.col_n3.setText(str(r.num_bars_3dir))
                self.col_n2.setText(str(r.num_bars_2dir))
                self.col_ties3.setText(str(r.num_ties_3dir))
                self.col_ties2.setText(str(r.num_ties_2dir))
            else:
                self.col_ncirc.setText(str(r.num_bars_circ))
        else:
            self.beam_cover_top.setText(str(r.cover_top))
            self.beam_cover_bot.setText(str(r.cover_bottom))
            self.beam_cover_side.setText(str(r.cover_side))
            self.beam_top_size.setCurrentText(r.top_bar_size or "#8")
            self.beam_top_count.setText(str(r.top_bar_count))
            self.beam_bot_size.setCurrentText(r.bottom_bar_size or "#8")
            self.beam_bot_count.setText(str(r.bottom_bar_count))
            self.beam_tie_size.setCurrentText(r.tie_bar_size or "#3")
            self.beam_tie_spacing.setText(str(r.tie_spacing))

    def _save(self):
        if not self.combo_long_mat.currentText() or not self.combo_tie_mat.currentText():
            QMessageBox.warning(self, "Missing Material",
                                 "Define at least one Rebar-type material first (Define Materials).")
            return

        try:
            design_type = "column" if self.radio_column.isChecked() else "beam"
            data = ReinforcementData(
                long_bar_material=self.combo_long_mat.currentText(),
                tie_bar_material=self.combo_tie_mat.currentText(),
                design_type=design_type,
                config=self.config,
                confinement_type="ties" if design_type == "beam" or self.radio_ties.isChecked() else "spiral",
            )

            if design_type == "column":
                data.clear_cover = float(self.col_cover.text() or 0)
                data.long_bar_size = self.col_bar_size.currentText()
                data.tie_bar_size = self.col_tie_size.currentText()
                data.tie_spacing = float(self.col_tie_spacing.text() or 0)
                data.tie_layout = self.col_tie_layout.currentData() or "rect"
                data.rho_s_scale = float(self.col_rho_scale.text() or 1.0)
                if data.rho_s_scale <= 0:
                    raise ValueError("Tie ratio scale factor must be > 0")
                if self.config == "rectangular":
                    data.num_bars_3dir = int(self.col_n3.text() or 0)
                    data.num_bars_2dir = int(self.col_n2.text() or 0)
                    data.num_ties_3dir = int(self.col_ties3.text() or 0)
                    data.num_ties_2dir = int(self.col_ties2.text() or 0)
                else:
                    data.num_bars_circ = int(self.col_ncirc.text() or 0)
            else:
                data.cover_top = float(self.beam_cover_top.text() or 0)
                data.cover_bottom = float(self.beam_cover_bot.text() or 0)
                data.cover_side = float(self.beam_cover_side.text() or 0)
                data.top_bar_size = self.beam_top_size.currentText()
                data.top_bar_count = int(self.beam_top_count.text() or 0)
                data.bottom_bar_size = self.beam_bot_size.currentText()
                data.bottom_bar_count = int(self.beam_bot_count.text() or 0)
                data.tie_bar_size = self.beam_tie_size.currentText()
                data.tie_spacing = float(self.beam_tie_spacing.text() or 0)

            self.result_data = data
            self.accept()

        except ValueError as e:
            QMessageBox.critical(self, "Error", f"Check numeric fields:\n{e}")
