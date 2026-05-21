from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLineEdit, QListWidget,
                             QListWidgetItem, QGroupBox, QAbstractItemView)
from PyQt6.QtCore import Qt, QTimer

class SelectByFrameSectionDialog(QDialog):
    def __init__(self, main_window, mode="select"):
        super().__init__(main_window)
        self.main_window = main_window
        self.mode = mode

        title = "Select by Frame Section Properties" if mode == "select"\
                else "Deselect by Frame Section Properties"
        self.setWindowTitle(title)
        self.resize(320, 420)
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)

        filter_grp = QGroupBox("Filter")
        filter_lay = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Type to filter sections...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.btn_clear_filter = QPushButton("Clear Filter")
        self.btn_clear_filter.clicked.connect(self._clear_filter)
        filter_lay.addWidget(self.filter_edit)
        filter_lay.addWidget(self.btn_clear_filter)
        filter_grp.setLayout(filter_lay)
        layout.addWidget(filter_grp)

        list_grp = QGroupBox("Frame Section Properties")
        list_lay = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        list_lay.addWidget(self.list_widget)
        list_grp.setLayout(list_lay)
        layout.addWidget(list_grp)

        btn_lay = QHBoxLayout()
        if mode == "select":
            self.btn_action = QPushButton("Select")
            self.btn_action.clicked.connect(self._do_select)
            self.btn_deselect = QPushButton("Deselect")
            self.btn_deselect.clicked.connect(self._do_deselect)
            btn_lay.addWidget(self.btn_action)
            btn_lay.addWidget(self.btn_deselect)
        else:
            self.btn_action = QPushButton("Deselect")
            self.btn_action.clicked.connect(self._do_deselect)
            btn_lay.addWidget(self.btn_action)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_lay.addWidget(self.btn_close)
        layout.addLayout(btn_lay)

        self._last_snapshot = set()

        if self.mode == "deselect":
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(150)
            self._poll_timer.timeout.connect(self._check_selection_changed)
            self._poll_timer.start()

        self._populate()

    def _check_selection_changed(self):
        """Repopulate if selected_ids changed externally."""
        current = set(self.main_window.selected_ids)
        if current != self._last_snapshot:
            self._last_snapshot = current
            self._populate()

    def closeEvent(self, event):
        if hasattr(self, '_poll_timer'):
            self._poll_timer.stop()
        super().closeEvent(event)

    def _populate(self):
                                                               
        previously_selected = {item.text() for item in self.list_widget.selectedItems()}

        self.list_widget.clear()
        model = self.main_window.model
        if not model:
            return

        if self.mode == "deselect":
            selected_ids = set(self.main_window.selected_ids)
            elems = {eid: model.elements[eid] for eid in selected_ids
                     if eid in model.elements}
        else:
            elems = model.elements

        seen = set()
        for elem in elems.values():
            name = getattr(getattr(elem, 'section', None), 'name', None) or "None"
            if name not in seen:
                seen.add(name)
                item = QListWidgetItem(name)
                self.list_widget.addItem(item)
                                                               
                if name in previously_selected:
                    item.setSelected(True)

        self.list_widget.sortItems()
        self._apply_filter(self.filter_edit.text())

        if self.mode == "deselect":
            empty = self.list_widget.count() == 0
            self.btn_action.setEnabled(not empty)
            if empty:
                placeholder = QListWidgetItem("No active selection to deselect")
                placeholder.setForeground(Qt.GlobalColor.gray)
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list_widget.addItem(placeholder)

    def _apply_filter(self, text):
        text = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(text != "" and text not in item.text().lower())

    def _clear_filter(self):
        self.filter_edit.clear()

    def _selected_section_names(self):
        return {item.text() for item in self.list_widget.selectedItems()}

    def _elem_ids_for_sections(self, names):
        model = self.main_window.model
        if not model:
            return []
        return [
            eid for eid, elem in model.elements.items()
            if (getattr(getattr(elem, 'section', None), 'name', None) or "None") in names
        ]

    def _refresh_overlay(self):
        mw = self.main_window
        for cvs in [mw.canvas, mw.canvas2]:
            cvs.update_selection_overlay(mw.selected_ids, mw.selected_node_ids)
        n = len(mw.selected_ids)
        mw.status.showMessage(f"Selected: {n} Frame{'s' if n != 1 else ''}, {len(mw.selected_node_ids)} Joints")

    def _do_select(self):
        names = self._selected_section_names()
        if not names:
            return
        mw = self.main_window
        for eid in self._elem_ids_for_sections(names):
            if eid not in mw.selected_ids:
                mw.selected_ids.append(eid)
        self._refresh_overlay()

    def _do_deselect(self):
        names = self._selected_section_names()
        if not names:
            return
        mw = self.main_window
        to_remove = set(self._elem_ids_for_sections(names))
        mw.selected_ids = [eid for eid in mw.selected_ids if eid not in to_remove]
        self._refresh_overlay()
