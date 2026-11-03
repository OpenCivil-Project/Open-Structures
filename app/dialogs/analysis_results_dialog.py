import csv
import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
                             QHeaderView, QTabWidget, QPushButton, QHBoxLayout, QLabel,
                             QComboBox, QFileDialog, QMessageBox, QAbstractItemView)
from PyQt6.QtGui import QColor, QFont, QKeySequence
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core.units import unit_registry, UnitConverter
from app.ui.theme import apply_dialog_style, COLORS, on_theme_changed, off_theme_changed

class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by a numeric value (Qt.ItemDataRole.UserRole)
    when available, falling back to plain text comparison otherwise."""

    def __lt__(self, other):
        d1 = self.data(Qt.ItemDataRole.UserRole)
        d2 = other.data(Qt.ItemDataRole.UserRole) if isinstance(other, QTableWidgetItem) else None
        if d1 is not None and d2 is not None:
            try:
                return float(d1) < float(d2)
            except (TypeError, ValueError):
                pass
        return self.text() < other.text()

class CopyableTableWidget(QTableWidget):
    """QTableWidget with Excel-style Ctrl+C: copies the selected cell
    rectangle (rows x columns) as tab-separated text to the clipboard."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection_to_clipboard()
        else:
            super().keyPressEvent(event)

    def copy_selection_to_clipboard(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return

        rows = sorted(set(i.row() for i in indexes))
        cols = sorted(set(i.column() for i in indexes))
        selected_set = set((i.row(), i.column()) for i in indexes)

        lines = []

        header_item = self.horizontalHeaderItem
        lines.append("\t".join(
            (header_item(c).text() if header_item(c) else "") for c in cols
        ))

        for r in rows:
            line_vals = []
            for c in cols:
                if (r, c) in selected_set:
                    item = self.item(r, c)
                    line_vals.append(item.text() if item else "")
                else:
                    line_vals.append("")
            lines.append("\t".join(line_vals))

        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText("\n".join(lines))

class AnalysisResultsDialog(QDialog):

    AVAILABLE_UNITS = ["kN, m, C", "N, m, C", "N, mm, C", "kN, mm, C",
                       "Tonf, m, C", "kgf, m, C", "kip, ft, F"]

    _VM_DOF_INDEX = {"U1": 0, "U2": 1, "U3": 2, "R1": 3, "R2": 4, "R3": 5}

    def __init__(self, model, results_data, parent=None, selected_node_ids=None):                 
        super().__init__(parent)
        self.model = model
        self.full_results = results_data
        self.results = results_data
        self.setWindowTitle("Analysis Results")
        self.resize(1100, 600)

        self.selected_node_ids = set(str(n) for n in selected_node_ids) if selected_node_ids else None

        self.local_units = UnitConverter()
        self.local_units.set_unit_system(unit_registry.current_unit_label)

        apply_dialog_style(self)                                                 

        layout = QVBoxLayout(self)

        h_title = QHBoxLayout()
        self.lbl_title = QLabel()
        h_title.addWidget(self.lbl_title)

        self.lbl_case = lbl_case = QLabel(" Load Case:")
        h_title.addWidget(lbl_case)
        
        self.case_combo = QComboBox()
        self.populate_case_combo()
        self.case_combo.currentIndexChanged.connect(self.on_case_dropdown_changed)
        h_title.addWidget(self.case_combo)

        self.lbl_step = QLabel(" State:")
        self.lbl_step.setVisible(False)
        h_title.addWidget(self.lbl_step)

        self.step_combo = QComboBox()
        self.step_combo.setVisible(False)
        self.step_combo.currentIndexChanged.connect(self.on_step_dropdown_changed)
        h_title.addWidget(self.step_combo)

        h_title.addStretch()

        self.lbl_units = lbl_units = QLabel("Units:")
        h_title.addWidget(lbl_units)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(self.AVAILABLE_UNITS)
        self.unit_combo.setCurrentText(self.local_units.current_unit_label)
        self.unit_combo.currentTextChanged.connect(self.on_unit_changed)
        h_title.addWidget(self.unit_combo)

        layout.addLayout(h_title)

        self.lbl_filter = QLabel()
        self.lbl_filter.setVisible(False)
        layout.addWidget(self.lbl_filter)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._hinge_ctx = None                                                     
        self._hinge_reason = ""                                                             
        self._hinge_cache = None                                                   
        self._hinge_available = False

        self.populate_step_combo()
        self.rebuild_tabs()

        h_btns = QHBoxLayout()
        h_btns.addStretch()

        btn_export_csv = QPushButton("Export CSV")
        btn_export_csv.setObjectName("primary")
        btn_export_csv.clicked.connect(self.export_current_table_csv)
        h_btns.addWidget(btn_export_csv)

        btn_export_excel = QPushButton("Export Excel")
        btn_export_excel.setObjectName("primary")
        btn_export_excel.clicked.connect(self.export_current_table_excel)
        h_btns.addWidget(btn_export_excel)

        self.btn_export_hinge = QPushButton("Export Hinge Tables (All Steps)")
        self.btn_export_hinge.setObjectName("primary")
        self.btn_export_hinge.clicked.connect(self.export_hinge_tables_all_steps)
        self.btn_export_hinge.setVisible(self._hinge_available)
        h_btns.addWidget(self.btn_export_hinge)

        btn_close = QPushButton("Close")
        btn_close.setObjectName("primary")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        h_btns.addWidget(btn_close)

        layout.addLayout(h_btns)

        self._style_labels()
        on_theme_changed(self._on_theme_changed)
        self.finished.connect(lambda *_: off_theme_changed(self._on_theme_changed))

    def _style_labels(self):
        """Label fonts/colours come from COLORS, so they follow Light/Dark."""
        sec, pri = COLORS["text_secondary"], COLORS["text_primary"]
        self.lbl_title.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {pri};")
        self.lbl_case.setStyleSheet(f"font-size: 10pt; font-weight: bold; color: {sec}; margin-left: 20px;")
        self.lbl_step.setStyleSheet(f"font-size: 10pt; font-weight: bold; color: {sec}; margin-left: 20px;")
        self.lbl_units.setStyleSheet(f"font-size: 10pt; color: {sec};")
        self.lbl_filter.setStyleSheet(f"font-size: 9pt; color: {sec}; font-style: italic;")

    def _on_theme_changed(self, _name):
        """Theme switched while this dialog is open: restyle and redraw the
        tables (their bold cells use the accent colour set at build time)."""
        apply_dialog_style(self)
        self._style_labels()
        idx = self.tabs.currentIndex()
        self.rebuild_tabs()
        if 0 <= idx < self.tabs.count():
            self.tabs.setCurrentIndex(idx)

    def populate_case_combo(self):
        import os, glob
        self.case_combo.blockSignals(True)
        if getattr(self.model, 'file_path', None):
            base_name = os.path.splitext(self.model.file_path)[0]
            
            files = getattr(self.model, 'valid_result_paths', [])
            if not files:
                files = glob.glob(f"{base_name}_*_results.json")
                                                            
            target_idx = 0
            current_case = self.results.get("info", {}).get("case_name", "")
            
            for path in sorted(files):
                fname = os.path.basename(path)
                prefix = os.path.basename(base_name) + "_"
                case_name = fname[len(prefix):].replace("_results.json", "")
                self.case_combo.addItem(case_name, path)
                
                if case_name == current_case:
                    target_idx = self.case_combo.count() - 1
                    
            if self.case_combo.count() > 0:
                self.case_combo.setCurrentIndex(target_idx)
        self.case_combo.blockSignals(False)

    def on_case_dropdown_changed(self, index):
        import json
        if index < 0: return
        path = self.case_combo.itemData(index)
        try:
            with open(path, 'r') as f:
                self.full_results = json.load(f)
                self.results = self.full_results
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not load results: {e}")
            return

        self.populate_step_combo()
        current_idx = self.tabs.currentIndex()
        self.rebuild_tabs()
        if 0 <= current_idx < self.tabs.count():
            self.tabs.setCurrentIndex(current_idx)

    def on_unit_changed(self, new_label):
        self.local_units.set_unit_system(new_label)
        current_idx = self.tabs.currentIndex()
        self.rebuild_tabs()
        if 0 <= current_idx < self.tabs.count():
            self.tabs.setCurrentIndex(current_idx)

    def populate_step_combo(self):
        """Populates the 'State' dropdown from full_results['saved_states']
        (written by the Nonlinear Static engine when 'Multiple States' is
        selected). Hidden entirely for every other results type, or when a
        Nonlinear Static case only saved its Final State."""
        self.step_combo.blockSignals(True)
        self.step_combo.clear()

        states = self.full_results.get("saved_states")
        if states:
            self.step_combo.addItem("Final State", None)
            for st in states:
                label = f"Step {st['step']} (load frac {st['step_frac']:.3f})"
                self.step_combo.addItem(label, st)
            self.step_combo.setCurrentIndex(0)
            self.lbl_step.setVisible(True)
            self.step_combo.setVisible(True)
        else:
            self.lbl_step.setVisible(False)
            self.step_combo.setVisible(False)

        self.step_combo.blockSignals(False)
        self._apply_selected_state()

    def _apply_selected_state(self):
        """Sets self.results to either the full/Final-State results dict, or
        a shallow-copied view with displacements/reactions/base_reaction
        swapped in from the selected saved state. Every other key (info,
        restrained_nodes, etc.) is passed through unchanged from full_results."""
        state = self.step_combo.currentData() if self.step_combo.isVisible() else None
        if state is None:
            self.results = self.full_results
        else:
            self.results = dict(self.full_results)
            self.results["displacements"] = state["displacements"]
            self.results["reactions"] = state["reactions"]
            self.results["base_reaction"] = state["base_reaction"]

    def on_step_dropdown_changed(self, index):
        if index < 0: return
        self._apply_selected_state()
        current_idx = self.tabs.currentIndex()
        self.rebuild_tabs()
        if 0 <= current_idx < self.tabs.count():
            self.tabs.setCurrentIndex(current_idx)

    def rebuild_tabs(self):
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()

        units = self.local_units
        self.lbl_title.setText(f"Analysis Report (Units: {units.current_unit_label})")

        if self.selected_node_ids:
            n = len(self.selected_node_ids)
            self.lbl_filter.setText(
                f"Showing data for {n} selected joint{'s' if n != 1 else ''} only "
                f"(Joint Displacements, Joint Reactions, Assembled Joint Masses). "
                f"Other tables show the full model."
            )
            self.lbl_filter.setVisible(True)
        else:
            self.lbl_filter.setVisible(False)

        sf = units.force_scale
        sl = units.length_scale
        sm = sf / sl if sl != 0 else 1.0
        s_mom = sf * sl

        u_force = units.force_unit_name
        u_len = units.length_unit_name
        u_mass = f"{u_force}-s\u00b2/{u_len}"
        u_mass_rot = f"{u_force}-{u_len}-s\u00b2"

        u_acc = f"{u_len}/s\u00b2"

        nl = self._nl_meta()                                                   
        NL_HEADERS = ["OutputCase", "CaseType", "Step", "StepFrac"]

        if "base_reaction_min" in self.results and "base_reaction_max" in self.results:
            br_min = self.results["base_reaction_min"]
            br_max = self.results["base_reaction_max"]
            br_list = [
                {
                    "Case": "Min",
                    "Fx": br_min["Fx"] * sf, "Fy": br_min["Fy"] * sf, "Fz": br_min["Fz"] * sf,
                    "Mx": br_min["Mx"] * s_mom, "My": br_min["My"] * s_mom, "Mz": br_min["Mz"] * s_mom
                },
                {
                    "Case": "Max",
                    "Fx": br_max["Fx"] * sf, "Fy": br_max["Fy"] * sf, "Fz": br_max["Fz"] * sf,
                    "Mx": br_max["Mx"] * s_mom, "My": br_max["My"] * s_mom, "Mz": br_max["Mz"] * s_mom
                }
            ]
            headers = ["Envelope", f"Global FX ({u_force})", f"Global FY ({u_force})", f"Global FZ ({u_force})",
                       f"Global MX ({u_force}-{u_len})", f"Global MY ({u_force}-{u_len})", f"Global MZ ({u_force}-{u_len})"]
            self.tab_base_reac = self.create_table(headers, br_list, ["Case", "Fx", "Fy", "Fz", "Mx", "My", "Mz"])
            self.tabs.addTab(self.tab_base_reac, "Base Reactions")
        elif "base_reaction" in self.results:
            br = self.results["base_reaction"]
            br_list = [{
                "Case": "Global Sum",
                "Fx": br["Fx"] * sf, "Fy": br["Fy"] * sf, "Fz": br["Fz"] * sf,
                "Mx": br["Mx"] * s_mom, "My": br["My"] * s_mom, "Mz": br["Mz"] * s_mom
            }]
            headers = ["Load Case", f"Global FX ({u_force})", f"Global FY ({u_force})", f"Global FZ ({u_force})",
                       f"Global MX ({u_force}-{u_len})", f"Global MY ({u_force}-{u_len})", f"Global MZ ({u_force}-{u_len})"]
            br_keys = ["Case", "Fx", "Fy", "Fz", "Mx", "My", "Mz"]
            if nl:
                br_list[0].update(Case=nl["case"], CaseType=nl["case_type"],
                                  Step=nl["step"], StepFrac=nl["step_frac"])
                headers = NL_HEADERS + headers[1:]
                br_keys = ["Case", "CaseType", "Step", "StepFrac"] + br_keys[1:]
            self.tab_base_reac = self.create_table(headers, br_list, br_keys)
            self.tabs.addTab(self.tab_base_reac, "Base Reactions")

        case_name = self.results.get("info", {}).get("case_name", "\u2014")

        is_ltha = "displacements_max" in self.results and "displacements_min" in self.results

        if "displacements" in self.results and not is_ltha:
            disp_data = []
            for nid, dofs in sorted(self.results["displacements"].items(), key=lambda x: (int(str(x[0]).split('~')[0]), str(x[0])) if str(x[0]).split('~')[0].isdigit() else (float('inf'), str(x[0]))):
                disp_data.append({
                    "joint": nid,
                    "case":  case_name,
                    "u1": dofs[0] * sl,
                    "u2": dofs[1] * sl,
                    "u3": dofs[2] * sl,
                    "r1": dofs[3],
                    "r2": dofs[4],
                    "r3": dofs[5],
                })
                if nl:
                    disp_data[-1].update(case=nl["case"], case_type=nl["case_type"],
                                         step=nl["step"], step_frac=nl["step_frac"])

            if self.selected_node_ids:
                disp_data = [d for d in disp_data if d["joint"] in self.selected_node_ids]

            disp_headers = [
                "Joint", "Load Case",
                f"U1 ({u_len})", f"U2 ({u_len})", f"U3 ({u_len})",
                "R1 (rad)",     "R2 (rad)",     "R3 (rad)"
            ]
            disp_keys = ["joint", "case", "u1", "u2", "u3", "r1", "r2", "r3"]
            if nl:
                disp_headers = [disp_headers[0]] + NL_HEADERS + disp_headers[2:]
                disp_keys = ["joint", "case", "case_type", "step", "step_frac"] + disp_keys[2:]
            self.tab_displacements = self.create_table(disp_headers, disp_data, disp_keys)
            self.tabs.addTab(self.tab_displacements, "Joint Displacements")

        disp_headers = ["Joint", "Load Case", f"U1 ({u_len})", f"U2 ({u_len})", f"U3 ({u_len})", "R1 (rad)", "R2 (rad)", "R3 (rad)"]
        for key, tab_name in [("displacements_max", "Joint Displacements (Rel, Max)"),
                              ("displacements_min", "Joint Displacements (Rel, Min)"),
                              ("displacements_abs", "Joint Displacements (Rel, Abs Max)")]:
            if key in self.results:
                self._add_envelope_table(self.results[key], case_name, col_scales=[sl, sl, sl, 1.0, 1.0, 1.0], headers=disp_headers, tab_title=tab_name)

        self._add_virtual_measurements_tab(case_name, is_ltha, col_scales=[sl, sl, sl, 1.0, 1.0, 1.0])

        u_vel = f"{u_len}/s"
        vel_headers = ["Joint", "Load Case", f"V1 ({u_vel})", f"V2 ({u_vel})", f"V3 ({u_vel})", "RV1 (rad/s)", "RV2 (rad/s)", "RV3 (rad/s)"]
        for key, tab_name in [("velocities_max", "Joint Velocities (Total, Max)"),
                              ("velocities_min", "Joint Velocities (Total, Min)"),
                              ("velocities_abs", "Joint Velocities (Total, Abs Max)")]:
            if key in self.results:
                self._add_envelope_table(self.results[key], case_name, col_scales=[sl, sl, sl, 1.0, 1.0, 1.0], headers=vel_headers, tab_title=tab_name)

        for key, tab_name in [("velocities_rel_max", "Joint Velocities (Rel, Max)"),
                              ("velocities_rel_min", "Joint Velocities (Rel, Min)"),
                              ("velocities_rel_abs", "Joint Velocities (Rel, Abs Max)")]:
            if key in self.results:
                self._add_envelope_table(self.results[key], case_name, col_scales=[sl, sl, sl, 1.0, 1.0, 1.0], headers=vel_headers, tab_title=tab_name)

        acc_headers = ["Joint", "Load Case", f"A1 ({u_acc})", f"A2 ({u_acc})", f"A3 ({u_acc})", "RA1 (rad/s\u00b2)", "RA2 (rad/s\u00b2)", "RA3 (rad/s\u00b2)"]
        for key, tab_name in [("accelerations_max", "Joint Accelerations (Total, Max)"),
                              ("accelerations_min", "Joint Accelerations (Total, Min)"),
                              ("accelerations_abs", "Joint Accelerations (Total, Abs Max)")]:
            if key in self.results:
                self._add_envelope_table(self.results[key], case_name, col_scales=[sl, sl, sl, 1.0, 1.0, 1.0], headers=acc_headers, tab_title=tab_name)

        for key, tab_name in [("accelerations_rel_max", "Joint Accelerations (Rel, Max)"),
                              ("accelerations_rel_min", "Joint Accelerations (Rel, Min)"),
                              ("accelerations_rel_abs", "Joint Accelerations (Rel, Abs Max)")]:
            if key in self.results:
                self._add_envelope_table(self.results[key], case_name, col_scales=[sl, sl, sl, 1.0, 1.0, 1.0], headers=acc_headers, tab_title=tab_name)
                
        reac_headers = ["Joint", "Load Case", f"F1 ({u_force})", f"F2 ({u_force})", f"F3 ({u_force})", f"M1 ({u_force}-{u_len})", f"M2 ({u_force}-{u_len})", f"M3 ({u_force}-{u_len})"]
        
        restrained_nodes = set(self.results.get("restrained_nodes", []))

        for key, tab_name in [("reactions", "Joint Reactions"),
                              ("reactions_max", "Joint Reactions (Max)"),
                              ("reactions_min", "Joint Reactions (Min)"),
                              ("reactions_abs", "Joint Reactions (Abs Max)")]:
            if key in self.results:
                                                                                    
                filtered_reactions = {nid: dofs for nid, dofs in self.results[key].items() if str(nid) in restrained_nodes}
                
                self._add_envelope_table(filtered_reactions, case_name, col_scales=[sf, sf, sf, s_mom, s_mom, s_mom], headers=reac_headers, tab_title=tab_name, nl=nl)
                
        if "rsa_detailed" in self.results:
            rsa_dict = self.results["rsa_detailed"]

            rsa_headers = [
                "Mode", "Period (s)", "DampRatio",
                f"U1 S_a ({u_acc})", f"U2 S_a ({u_acc})", f"U3 S_a ({u_acc})",
                f"U1 S_d ({u_len})", f"U2 S_d ({u_len})", f"U3 S_d ({u_len})"
            ]

            rsa_data_formatted = []

            for direction, table_rows in rsa_dict.items():
                for row in table_rows:

                    u1_acc, u2_acc, u3_acc = 0.0, 0.0, 0.0
                    u1_amp, u2_amp, u3_amp = 0.0, 0.0, 0.0

                    acc_val = row["SaR_ms2"] * sl
                    amp_val = row["Sd"] * sl

                    if direction == "X":
                        u1_acc = acc_val; u1_amp = amp_val
                    elif direction == "Y":
                        u2_acc = acc_val; u2_amp = amp_val
                    elif direction == "Z":
                        u3_acc = acc_val; u3_amp = amp_val

                    rsa_data_formatted.append({
                        "mode": row["mode"],
                        "T": row["T"],
                        "zeta": row.get("Damping", 0.05),
                        "U1a": u1_acc, "U2a": u2_acc, "U3a": u3_acc,
                        "U1d": u1_amp, "U2d": u2_amp, "U3d": u3_amp
                    })

            rsa_data_formatted.sort(key=lambda x: x["mode"])

            self.tab_rsa_info = self.create_table(
                rsa_headers, rsa_data_formatted,
                ["mode", "T", "zeta", "U1a", "U2a", "U3a", "U1d", "U2d", "U3d"]
            )
            self.tabs.addTab(self.tab_rsa_info, "RSA Modal Info")

        if "assembled_mass" in self.results:
            mass_data = []
            for nid, masses in self.results["assembled_mass"].items():
                mass_data.append({
                    "Node": nid,
                    "U1": masses[0] * sm, "U2": masses[1] * sm, "U3": masses[2] * sm,
                    "R1": masses[3] * s_mom, "R2": masses[4] * s_mom, "R3": masses[5] * s_mom
                })
            
            mass_data.sort(key=lambda x: (int(str(x["Node"]).split('~')[0]), str(x["Node"])) if str(x["Node"]).split('~')[0].isdigit() else (float('inf'), str(x["Node"])))
            if self.selected_node_ids:
                mass_data = [d for d in mass_data if d["Node"] in self.selected_node_ids]

            sum_u1 = sum(d["U1"] for d in mass_data)
            sum_u2 = sum(d["U2"] for d in mass_data)
            sum_u3 = sum(d["U3"] for d in mass_data)
            mass_data.append({"Node": "SUM", "U1": sum_u1, "U2": sum_u2, "U3": sum_u3, "R1": "-", "R2": "-", "R3": "-"})

            m_headers = ["Joint", f"Mass X ({u_mass})", f"Mass Y ({u_mass})", f"Mass Z ({u_mass})",
                         f"Mass Rx ({u_mass_rot})", f"Mass Ry ({u_mass_rot})", f"Mass Rz ({u_mass_rot})"]

            self.tab_mass = self.create_table(m_headers, mass_data, ["Node", "U1", "U2", "U3", "R1", "R2", "R3"])
            self.tabs.addTab(self.tab_mass, "Assembled Joint Masses")

        if "rsa_summary" in self.results:
            self.tab_summary = self.create_summary_table(self.results["rsa_summary"], units)
            self.tabs.addTab(self.tab_summary, "RSA Summary")

        if "tables" in self.results and "periods" in self.results["tables"]:
            self.tab_periods = self.create_table(
                ["Mode", "Period (sec)", "Frequency (Hz)", "Circ. Freq (rad/s)", "Eigenvalue"],
                self.results["tables"]["periods"],
                ["mode", "T", "f", "omega", "eigen"]
            )
            self.tabs.addTab(self.tab_periods, "Modal Periods")

            self.tab_ratios = self.create_table(
                ["Mode", "Ux Ratio", "Sum Ux", "Uy Ratio", "Sum Uy", "Uz Ratio", "Sum Uz",
                 "Rx Ratio", "Sum Rx", "Ry Ratio", "Sum Ry", "Rz Ratio", "Sum Rz"],
                self.results["tables"]["participation_mass"],
                ["mode", "Ux", "SumUx", "Uy", "SumUy", "Uz", "SumUz",
                 "Rx", "SumRx", "Ry", "SumRy", "Rz", "SumRz"]
            )
            self.tabs.addTab(self.tab_ratios, "Mass Participation")

        if "tables" in self.results and "participation_factors" in self.results["tables"]:
            pf_data = []
            import math
            
            sqrt_sf = math.sqrt(sf) if sf > 0 else 1.0

            for row in self.results["tables"]["participation_factors"]:
                pf_data.append({
                    "mode": row.get("mode", 0),
                    "T": row.get("T", 0.0),
                    "Ux": row.get("Ux_disp", 0.0) * sqrt_sf * sl, 
                    "Uy": row.get("Uy_disp", 0.0) * sqrt_sf * sl, 
                    "Uz": row.get("Uz_disp", 0.0) * sqrt_sf * sl,
                    "Rx": row.get("Rx_disp", 0.0) * sqrt_sf * sl, 
                    "Ry": row.get("Ry_disp", 0.0) * sqrt_sf * sl, 
                    "Rz": row.get("Rz_disp", 0.0) * sqrt_sf * sl,
                    "ModalMass": row.get("ModalMass_disp", 1.0) * sl,                                   
                    "ModalStiff": row.get("ModalStiff", 0.0) * sl
                })

            self.tab_pf = self.create_table(
                ["Mode", "Period (sec)",
                 "UX", "UY", "UZ",
                 "RX", "RY", "RZ",
                 "ModalMass", "ModalStiff (\u03c9\u00b2)"],
                pf_data,
                ["mode", "T", "Ux", "Uy", "Uz", "Rx", "Ry", "Rz", "ModalMass", "ModalStiff"]
            )
            self.tabs.addTab(self.tab_pf, "Modal Participation Factors")

        if "tables" in self.results and "buckling_factors" in self.results["tables"]:
            buckling_data = self.results["tables"]["buckling_factors"]

            self.tab_buckling_factors = self.create_table(
                ["Mode", "Critical Load Factor (\u03bb)"],
                buckling_data,
                ["mode", "lambda"]
            )
            self.tabs.addTab(self.tab_buckling_factors, "Buckling Factors")

        if "mode_shapes" in self.results and "tables" in self.results and "buckling_factors" in self.results["tables"]:
            factors = self.results["tables"]["buckling_factors"]
            lam_map = {f["mode"]: f.get("lambda", 0.0) for f in factors}

            shape_summary_data = []
            for mode_key, node_data in self.results["mode_shapes"].items():
                try:
                    mode_num = int(mode_key.replace("Mode ", "").strip())
                except ValueError:
                    continue

                max_u1 = max_u2 = max_u3 = 0.0
                for dofs in node_data.values():
                    if len(dofs) >= 3:
                        max_u1 = max(max_u1, abs(dofs[0]))
                        max_u2 = max(max_u2, abs(dofs[1]))
                        max_u3 = max(max_u3, abs(dofs[2]))

                dom = max(zip([max_u1, max_u2, max_u3], ["U1", "U2", "U3"]), key=lambda x: x[0])[1]

                shape_summary_data.append({
                    "mode": mode_num,
                    "lam": lam_map.get(mode_num, 0.0),
                    "u1": max_u1,
                    "u2": max_u2,
                    "u3": max_u3,
                    "dom": dom
                })

            shape_summary_data.sort(key=lambda x: x["mode"])

            self.tab_buckling_shapes = self.create_table(
                ["Mode", "\u03bb", "Max |U1|", "Max |U2|", "Max |U3|", "Dominant DOF"],
                shape_summary_data,
                ["mode", "lam", "u1", "u2", "u3", "dom"]
            )
            self.tabs.addTab(self.tab_buckling_shapes, "Mode Shape Summary")

        self._add_hinge_state_tabs(units)

        if "error" in self.results:
            err_data = [{"field": k, "value": str(v)} for k, v in self.results["error"].items()]
            self.tab_error = self.create_table(["Field", "Value"], err_data, ["field", "value"])
            self.tabs.addTab(self.tab_error, "\u26a0 Error Details")

    def _nl_meta(self):
        """OutputCase / CaseType / Step / StepFrac of what the tables currently
        show, for Nonlinear Static results only (None for every other case type).
        'Final State' is the last saved step (the engine always keeps it)."""
        info = self.full_results.get("info", {}) or {}
        if info.get("type") != "Nonlinear Static":
            return None
        state = self.step_combo.currentData() if self.step_combo.isVisible() else None
        if isinstance(state, dict):
            step, frac = state.get("step"), state.get("step_frac")
        else:
            saved = self.full_results.get("saved_states") or []
            if saved:
                step, frac = saved[-1].get("step"), saved[-1].get("step_frac")
            else:
                step = info.get("steps_accepted", 0)
                frac = info.get("stop_load_fraction")
        return {"case": info.get("case_name", ""), "case_type": info.get("type", ""),
                "step": str(step), "step_frac": 1.0 if frac is None else float(frac)}

    def _get_hinge_tables(self):
        """HingeStateTables for the loaded case, or None if it has no hinge
        data. Contexts (fiber sections) are built once per dialog; the table
        object is cached per loaded results dict."""
        if self.full_results.get("info", {}).get("type") != "Nonlinear Static":
            self._hinge_reason = ""
            return None
        if self._hinge_cache is not None and self._hinge_cache[0] is self.full_results:
            return self._hinge_cache[1]
        tables, self._hinge_reason = None, ""
        try:
            from app.dialogs import hinge_state_tables as hst
            if self._hinge_ctx is None:
                self._hinge_ctx = hst.build_contexts(self.model)
            contexts, warns = self._hinge_ctx
            tables = hst.HingeStateTables(self.model, self.full_results, contexts)
            if not tables.available:
                if not contexts:
                    self._hinge_reason = ("no fiber hinges could be built from the model. "
                                          + " ".join(warns) if warns else
                                          "the model has no frame hinge assignments.")
                else:
                    self._hinge_reason = "this case's results carry no hinge_states."
                tables = None
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._hinge_reason = f"{type(e).__name__}: {e}"
            tables = None
        self._hinge_cache = (self.full_results, tables)
        return tables

    def _selected_hinge_step(self, tables):
        """Step shown by the Individual Fibers table: the State dropdown's step,
        or the last saved step for 'Final State'."""
        state = self.step_combo.currentData() if self.step_combo.isVisible() else None
        if isinstance(state, dict) and state.get("step") in tables.step_numbers:
            return state["step"]
        return tables.step_numbers[-1]

    def _add_hinge_state_tabs(self, units):
        self._hinge_available = False
        tables = self._get_hinge_tables()
        if tables is not None:
            from app.dialogs import hinge_state_tables as hst
            sf, sl = units.force_scale, units.length_scale
            uf, ul = units.force_unit_name, units.length_unit_name

            rows1 = tables.overall_rows(sf, sl)
            self.tab_hinge_overall = self.create_table(
                hst.overall_headers(uf, ul), rows1, hst.OVERALL_KEYS, sci=True)
            self.tabs.addTab(self.tab_hinge_overall, hst.TABLE_01_NAME)

            step = self._selected_hinge_step(tables)
            rows2 = tables.fiber_rows(sf, sl, only_step=step)
            self.tab_hinge_fibers = self.create_table(
                hst.fiber_headers(uf, ul), rows2, hst.FIBER_KEYS, sci=True)
            self.tabs.addTab(self.tab_hinge_fibers, hst.TABLE_02_NAME)

            note = (f"Hinge tables: Overall Hinge lists all {len(tables.step_numbers)} saved steps; "
                    f"Individual Fibers shows step {step} (pick another in State). "
                    f"'Export Hinge Tables (All Steps)' writes every fiber at every step.")
            prev = self.lbl_filter.text() if self.lbl_filter.isVisible() else ""
            self.lbl_filter.setText(f"{prev}  |  {note}" if prev else note)
            self.lbl_filter.setVisible(True)
            self._hinge_available = True

        elif self._hinge_reason:
            msg = f"Hinge tables unavailable: {self._hinge_reason}"
            prev = self.lbl_filter.text() if self.lbl_filter.isVisible() else ""
            self.lbl_filter.setText(f"{prev}  |  {msg}" if prev else msg)
            self.lbl_filter.setVisible(True)

        btn = getattr(self, "btn_export_hinge", None)
        if btn is not None:
            btn.setVisible(self._hinge_available)

    def export_hinge_tables_all_steps(self):
        tables = self._get_hinge_tables()
        if tables is None:
            return
        units = self.local_units
        sf, sl = units.force_scale, units.length_scale
        uf, ul = units.force_unit_name, units.length_unit_name

        model_stem = os.path.splitext(os.path.basename(getattr(self.model, "file_path", "") or "model"))[0]
        case = "".join(c if c.isalnum() or c in (" ", "_", "-") else "_"
                       for c in tables.case_name).strip()
        default = f"{model_stem}_{case}_hinge_states.xlsx"
        path, flt = QFileDialog.getSaveFileName(
            self, "Export Hinge Tables (All Steps)", default,
            "Excel Files (*.xlsx);;CSV Files (*.csv)")
        if not path:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if path.lower().endswith(".csv") or "CSV" in flt:
                stem = path[:-4] if path.lower().endswith(".csv") else path
                files = tables.write_csv(stem, sf, sl, uf, ul)
                done = "\n".join(files)
            else:
                if not path.lower().endswith(".xlsx"):
                    path += ".xlsx"
                tables.write_xlsx(path, sf, sl, uf, ul)
                done = path
        except ImportError:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(
                self, "Missing Dependency",
                "Excel export requires the 'openpyxl' package.\n\nInstall it with:\npip install openpyxl")
            return
        except OSError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Export Failed", str(e))
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Export Complete", f"Hinge tables exported to:\n{done}")

    def _make_item(self, val, bold=False, sci=False):
        item = SortableTableWidgetItem()

        if val is None:
            val = ""
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            fv = float(val)
            if sci:
                                                                                 
                txt = str(val) if isinstance(val, int) else f"{fv:.6g}"
            else:
                txt = "0.0" if abs(fv) < 1e-9 else f"{fv:.6f}"
            item.setData(Qt.ItemDataRole.UserRole, fv)
        else:
            txt = str(val)
            try:
                item.setData(Qt.ItemDataRole.UserRole, float(txt))
            except ValueError:
                pass

        item.setText(txt)
        if bold:
            item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            item.setForeground(QColor(COLORS["accent"]))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def create_table(self, headers, data_list, keys, sci=False):
        table = CopyableTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setSortingEnabled(False)

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        table.setRowCount(len(data_list))

        for row, entry in enumerate(data_list):
            for col, key in enumerate(keys):
                val = entry.get(key, 0)
                item = self._make_item(val, bold=(col == 0), sci=sci)
                table.setItem(row, col, item)

        table.setSortingEnabled(True)
        return table

    def _add_envelope_table(self, node_dict, case_name, col_scales, headers, tab_title, nl=None):
        """
        Builds one envelope table (6 DOF columns, one row per joint) from a
        {node_id: [6 floats]} dict and adds it as a tab. Used for the LTHA
        min/max(-abs) displacement, velocity, acceleration and reaction tables.
        """
        data = []
        for nid, dofs in sorted(node_dict.items(), key=lambda x: (int(str(x[0]).split('~')[0]), str(x[0])) if str(x[0]).split('~')[0].isdigit() else (float('inf'), str(x[0]))):
            row = {"joint": nid, "case": case_name}
            if nl:
                row.update(case=nl["case"], case_type=nl["case_type"],
                           step=nl["step"], step_frac=nl["step_frac"])
            for i, key in enumerate(["c0", "c1", "c2", "c3", "c4", "c5"]):
                row[key] = dofs[i] * col_scales[i]
            data.append(row)

        if self.selected_node_ids:
            data = [d for d in data if d["joint"] in self.selected_node_ids]

        keys = ["joint", "case", "c0", "c1", "c2", "c3", "c4", "c5"]
        if nl:
            headers = [headers[0], "OutputCase", "CaseType", "Step", "StepFrac"] + headers[2:]
            keys = ["joint", "case", "case_type", "step", "step_frac"] + keys[2:]
        table = self.create_table(headers, data, keys)
        self.tabs.addTab(table, tab_title)
        return table

    def _eval_virtual_measurement(self, factors, disp_dict, col_scales):
        """Dot-products one measurement's {joint: {dof: factor}} against a
        {joint: [6 floats]} displacement dict already loaded in self.results.
        Returns None if any referenced joint isn't in disp_dict (e.g. it was
        deleted from the model, or isn't part of this case's active DOFs)."""
        total = 0.0
        for jid, dof_factors in factors.items():
            dofs = disp_dict.get(str(jid))
            if dofs is None:
                return None
            for dof, factor in dof_factors.items():
                idx = self._VM_DOF_INDEX.get(dof)
                if idx is None or not factor:
                    continue
                total += factor * dofs[idx] * col_scales[idx]
        return total

    def _add_virtual_measurements_tab(self, case_name, is_ltha, col_scales):
        """Adds a 'Virtual Measurements' tab evaluating every measurement
        defined in Define > Virtual Measurements against the displacements
        already loaded for the current case/step.

        Note on the LTHA branch: displacements_max/min/abs are per-DOF,
        per-joint envelopes that may each occur at a different time step, so
        combining them here is an approximate bound on the measurement's
        envelope, not its true time-history max/min (that needs the actual
        per-step trace — see Plot Function > Virtual Measurement instead)."""
        vms = getattr(self.model, "virtual_measurements", None)
        if not vms:
            return

        data = []
        for vm in vms.values():
            factors = vm.get("factors")
            if not factors:
                continue

            is_rot = vm.get("type") == "Rotational"
            unit = "rad" if is_rot else self.local_units.length_unit_name
            row = {"name": vm.get("name", "Unnamed"), "type": vm.get("type", "Translational"), "unit": unit}

            if is_ltha:
                row["max"] = self._eval_virtual_measurement(factors, self.results.get("displacements_max", {}), col_scales)
                row["min"] = self._eval_virtual_measurement(factors, self.results.get("displacements_min", {}), col_scales)
                row["absmax"] = self._eval_virtual_measurement(factors, self.results.get("displacements_abs", {}), col_scales)
            else:
                row["case"] = case_name
                row["value"] = self._eval_virtual_measurement(factors, self.results.get("displacements", {}), col_scales)

            data.append(row)

        if not data:
            return

        if is_ltha:
            headers = ["Measurement", "Type", "Max", "Min", "Abs Max", "Unit"]
            table = self.create_table(headers, data, ["name", "type", "max", "min", "absmax", "unit"])
        else:
            headers = ["Measurement", "Type", "Load Case", "Value", "Unit"]
            table = self.create_table(headers, data, ["name", "type", "case", "value", "unit"])

        self.tabs.addTab(table, "Virtual Measurements")

    def create_summary_table(self, data_list, units):
        table = CopyableTableWidget()
        headers = ["Parameter", "Value", "Description"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setSortingEnabled(False)
        table.setRowCount(len(data_list))
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        sf = units.force_scale
        u_force = units.force_unit_name

        for row, entry in enumerate(data_list):
            table.setItem(row, 0, SortableTableWidgetItem(str(entry.get("label", ""))))

            raw_val = entry.get('value', 0)
            u_type = entry.get('unit_type', 'none')
            sort_key = None

            if u_type == "force":
                disp_val = float(raw_val) * sf
                txt_val = f"{disp_val:.3f} {u_force}"
                sort_key = disp_val
            elif u_type == "ratio":
                disp_val = float(raw_val)
                txt_val = f"{disp_val:.6f}"
                sort_key = disp_val
            elif u_type == "percent":
                disp_val = float(raw_val)
                txt_val = f"{disp_val:.1f} %"
                sort_key = disp_val
            else:
                txt_val = str(raw_val)

            val_item = SortableTableWidgetItem(txt_val)
            if sort_key is not None:
                val_item.setData(Qt.ItemDataRole.UserRole, sort_key)
            val_item.setForeground(QColor(COLORS["accent"]))
            table.setItem(row, 1, val_item)
            table.setItem(row, 2, SortableTableWidgetItem(str(entry.get("desc", ""))))

        table.setSortingEnabled(True)
        return table

    def _current_table_and_name(self):
        idx = self.tabs.currentIndex()
        if idx < 0:
            return None, None
        table = self.tabs.widget(idx)
        if not isinstance(table, QTableWidget):
            return None, None
        name = self.tabs.tabText(idx)
        safe_name = "".join(c if c.isalnum() or c in (" ", "_", "-") else "_" for c in name).strip()
        return table, safe_name

    def export_current_table_csv(self):
        table, safe_name = self._current_table_and_name()
        if table is None:
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", f"{safe_name}.csv", "CSV Files (*.csv)")
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                
                unit_label = self.local_units.current_unit_label
                writer.writerow([f"Data exported with units: {unit_label}"])
                writer.writerow([])
                
                headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
                writer.writerow(headers)
                for r in range(table.rowCount()):
                    row_vals = [table.item(r, c).text() if table.item(r, c) else "" for c in range(table.columnCount())]
                    writer.writerow(row_vals)
        except OSError as e:
            QMessageBox.warning(self, "Export Failed", str(e))
            return

        QMessageBox.information(self, "Export Complete", f"Table exported to:\n{path}")

    def export_current_table_excel(self):
        try:
            import openpyxl
        except ImportError:
            QMessageBox.warning(
                self, "Missing Dependency",
                "Excel export requires the 'openpyxl' package.\n\nInstall it with:\npip install openpyxl"
            )
            return

        table, safe_name = self._current_table_and_name()
        if table is None:
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export Excel", f"{safe_name}.xlsx", "Excel Files (*.xlsx)")
        if not path:
            return

        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = safe_name[:31] if safe_name else "Table"

            unit_label = self.local_units.current_unit_label
            ws.append([f"Data exported with units: {unit_label}"])
            ws.append([])

            headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
            ws.append(headers)
            for r in range(table.rowCount()):
                ws.append([table.item(r, c).text() if table.item(r, c) else "" for c in range(table.columnCount())])

            wb.save(path)
        except OSError as e:
            QMessageBox.warning(self, "Export Failed", str(e))
            return

        QMessageBox.information(self, "Export Complete", f"Table exported to:\n{path}")
