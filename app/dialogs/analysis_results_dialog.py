import csv
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
                             QHeaderView, QTabWidget, QPushButton, QHBoxLayout, QLabel,
                             QComboBox, QFileDialog, QMessageBox, QAbstractItemView)
from PyQt6.QtGui import QColor, QFont, QKeySequence
from PyQt6.QtCore import Qt

from core.units import unit_registry, UnitConverter

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

    def __init__(self, model, results_data, parent=None, selected_node_ids=None):                 
        super().__init__(parent)
        self.model = model                              
        self.results = results_data
        self.setWindowTitle("Analysis Results")
        self.resize(1100, 600)

        self.selected_node_ids = set(str(n) for n in selected_node_ids) if selected_node_ids else None

        self.local_units = UnitConverter()
        self.local_units.set_unit_system(unit_registry.current_unit_label)

        self.setStyleSheet("""
            QDialog {
                background-color: #f8f9fa;
            }
            QTabWidget::pane {
                border: 1px solid #d0d0d0;
                background: #ffffff;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #e9ecef;
                color: #495057;
                padding: 8px 20px;
                border: 1px solid #d0d0d0;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
                font-size: 10pt;
                font-family: 'Segoe UI', sans-serif;
            }
            QTabBar::tab:selected {
                background: #0078D7;
                color: white;
                font-weight: bold;
                border-color: #0078D7;
            }
            QTabBar::tab:hover:!selected {
                background: #dee2e6;
            }
            QTableWidget {
                border: none;
                gridline-color: #e9ecef;
                selection-background-color: #cce4f7;
                selection-color: #000000;
                font-family: 'Segoe UI', sans-serif;
                font-size: 10pt;
            }
            QHeaderView::section {
                background-color: #f1f3f5;
                color: #212529;
                font-weight: bold;
                padding: 6px;
                border: none;
                border-right: 1px solid #dee2e6;
                border-bottom: 2px solid #ced4da;
            }
            QPushButton {
                background-color: #0078D7;
                color: white;
                border: none;
                padding: 8px 24px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
            QPushButton:pressed {
                background-color: #004578;
            }
            QComboBox {
                padding: 5px 10px;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                background: white;
                font-size: 10pt;
            }
        """)

        layout = QVBoxLayout(self)

        h_title = QHBoxLayout()
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #333;")
        h_title.addWidget(self.lbl_title)

        lbl_case = QLabel(" Load Case:")
        lbl_case.setStyleSheet("font-size: 10pt; font-weight: bold; color: #495057; margin-left: 20px;")
        h_title.addWidget(lbl_case)
        
        self.case_combo = QComboBox()
        self.populate_case_combo()
        self.case_combo.currentIndexChanged.connect(self.on_case_dropdown_changed)
        h_title.addWidget(self.case_combo)

        h_title.addStretch()

        lbl_units = QLabel("Units:")
        lbl_units.setStyleSheet("font-size: 10pt; color: #495057;")
        h_title.addWidget(lbl_units)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(self.AVAILABLE_UNITS)
        self.unit_combo.setCurrentText(self.local_units.current_unit_label)
        self.unit_combo.currentTextChanged.connect(self.on_unit_changed)
        h_title.addWidget(self.unit_combo)

        layout.addLayout(h_title)

        self.lbl_filter = QLabel()
        self.lbl_filter.setStyleSheet("font-size: 9pt; color: #6c757d; font-style: italic;")
        self.lbl_filter.setVisible(False)
        layout.addWidget(self.lbl_filter)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.rebuild_tabs()

        h_btns = QHBoxLayout()
        h_btns.addStretch()

        btn_export_csv = QPushButton("Export CSV")
        btn_export_csv.clicked.connect(self.export_current_table_csv)
        h_btns.addWidget(btn_export_csv)

        btn_export_excel = QPushButton("Export Excel")
        btn_export_excel.clicked.connect(self.export_current_table_excel)
        h_btns.addWidget(btn_export_excel)

        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        h_btns.addWidget(btn_close)

        layout.addLayout(h_btns)

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
                self.results = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not load results: {e}")
            return
            
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

        if "base_reaction" in self.results:
            br = self.results["base_reaction"]
            br_list = [{
                "Case": "Global Sum",
                "Fx": br["Fx"] * sf, "Fy": br["Fy"] * sf, "Fz": br["Fz"] * sf,
                "Mx": br["Mx"] * s_mom, "My": br["My"] * s_mom, "Mz": br["Mz"] * s_mom
            }]
            headers = ["Load Case", f"Global FX ({u_force})", f"Global FY ({u_force})", f"Global FZ ({u_force})",
                       f"Global MX ({u_force}-{u_len})", f"Global MY ({u_force}-{u_len})", f"Global MZ ({u_force}-{u_len})"]
            self.tab_base_reac = self.create_table(headers, br_list, ["Case", "Fx", "Fy", "Fz", "Mx", "My", "Mz"])
            self.tabs.addTab(self.tab_base_reac, "Base Reactions")

        case_name = self.results.get("info", {}).get("case_name", "\u2014")

        if "displacements" in self.results:
            disp_data = []
            for nid, dofs in sorted(self.results["displacements"].items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
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

            if self.selected_node_ids:
                disp_data = [d for d in disp_data if d["joint"] in self.selected_node_ids]

            disp_headers = [
                "Joint", "Load Case",
                f"U1 ({u_len})", f"U2 ({u_len})", f"U3 ({u_len})",
                "R1 (rad)",     "R2 (rad)",     "R3 (rad)"
            ]
            self.tab_displacements = self.create_table(
                disp_headers, disp_data,
                ["joint", "case", "u1", "u2", "u3", "r1", "r2", "r3"]
            )
            self.tabs.addTab(self.tab_displacements, "Joint Displacements")

        if "reactions" in self.results:
            restrained = set(self.results.get("restrained_nodes", []))
            reac_data = []
            for nid, dofs in sorted(self.results["reactions"].items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0]):
                if restrained and nid not in restrained:
                    continue
                if not restrained and max(abs(v) for v in dofs) < 1e-6:
                    continue
                reac_data.append({
                    "joint": nid,
                    "case":  case_name,
                    "f1": dofs[0] * sf,
                    "f2": dofs[1] * sf,
                    "f3": dofs[2] * sf,
                    "m1": dofs[3] * s_mom,
                    "m2": dofs[4] * s_mom,
                    "m3": dofs[5] * s_mom,
                })

            if self.selected_node_ids:
                reac_data = [d for d in reac_data if d["joint"] in self.selected_node_ids]

            reac_headers = [
                "Joint", "Load Case",
                f"F1 ({u_force})", f"F2 ({u_force})", f"F3 ({u_force})",
                f"M1 ({u_force}-{u_len})", f"M2 ({u_force}-{u_len})", f"M3 ({u_force}-{u_len})"
            ]
            self.tab_reactions = self.create_table(
                reac_headers, reac_data,
                ["joint", "case", "f1", "f2", "f3", "m1", "m2", "m3"]
            )
            self.tabs.addTab(self.tab_reactions, "Joint Reactions")

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
            mass_data.sort(key=lambda x: int(x["Node"]) if x["Node"].isdigit() else x["Node"])

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

        if "error" in self.results:
            err_data = [{"field": k, "value": str(v)} for k, v in self.results["error"].items()]
            self.tab_error = self.create_table(["Field", "Value"], err_data, ["field", "value"])
            self.tabs.addTab(self.tab_error, "\u26a0 Error Details")

    def _make_item(self, val, bold=False):
        item = SortableTableWidgetItem()

        if isinstance(val, (int, float)) and not isinstance(val, bool):
            fv = float(val)
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
            item.setForeground(QColor("#0078D7"))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def create_table(self, headers, data_list, keys):
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
        header.setStyleSheet("QHeaderView::section { background-color: #f0f0f0; padding: 4px; border: 1px solid #d0d0d0; }")

        table.setRowCount(len(data_list))

        for row, entry in enumerate(data_list):
            for col, key in enumerate(keys):
                val = entry.get(key, 0)
                item = self._make_item(val, bold=(col == 0))
                table.setItem(row, col, item)

        table.setSortingEnabled(True)
        return table

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
            val_item.setForeground(QColor("#0078D7"))
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

            headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
            ws.append(headers)
            for r in range(table.rowCount()):
                ws.append([table.item(r, c).text() if table.item(r, c) else "" for c in range(table.columnCount())])

            wb.save(path)
        except OSError as e:
            QMessageBox.warning(self, "Export Failed", str(e))
            return

        QMessageBox.information(self, "Export Complete", f"Table exported to:\n{path}")
