"""
stationSelector.py — v0.8.x rich axial-station selector for srm_1d results.

Replaces the simple grain checkbox list (for srm_1d transient results only)
with a station editor: a global cell-index slider + spinbox + an Add button,
and a scrollable list of stations grouped into auto-classified categories
(Head / Grain N / Gap N / Aft, each with its cell span). A station is just a
cell index + a visible flag; its category and fore/mid/aft role are DERIVED
from the index (via ``srm_1d.station_viz``), so editing the index reclassifies
and relabels it automatically. Rows reveal edit/delete on hover; editing loads
the station back into the global editor and redraws live as the slider drags.

The widget emits ``checksChanged`` whenever the active-station set changes
(toggle / add / delete / live edit); the results widget reads
``getSelectedStations`` to drive the plot and the grain-burnback columns.
``srm_1d`` is imported lazily so openMotor runs without it.
"""

from PyQt6.QtWidgets import (
    QGroupBox, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QSlider, QSpinBox, QPushButton, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt

import numpy as np


class StationRow(QWidget):
    """One station row: a visibility checkbox + label, with edit/delete buttons
    revealed on hover (or via double-click → edit). The label is allowed to
    shrink/clip so the row never forces the (narrow) controls column wider."""

    def __init__(self, sid, text, checked, onToggle, onEdit, onDelete):
        super().__init__()
        self.sid = sid
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 2, 0)
        lay.setSpacing(2)
        self.check = QCheckBox()
        self.check.setChecked(checked)                  # set before connecting
        self.check.toggled.connect(lambda c: onToggle(sid, c))
        lay.addWidget(self.check)
        self.label = QLabel(text)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.label.setToolTip(text)
        lay.addWidget(self.label, 1)
        self.editBtn = QPushButton('Edit')
        self.delBtn = QPushButton('Delete')
        for b, cb in ((self.editBtn, lambda: onEdit(sid)),
                      (self.delBtn, lambda: onDelete(sid))):
            b.setVisible(False)
            b.setMaximumWidth(52)
            b.clicked.connect(cb)
            lay.addWidget(b)
        self._onEdit = onEdit
        # Pin the row to a constant height so revealing the (taller) hover
        # buttons doesn't reflow the whole list. The buttons are capped to fit.
        rowH = max(self.check.sizeHint().height(), self.editBtn.sizeHint().height())
        self.setFixedHeight(rowH)
        self.editBtn.setMaximumHeight(rowH)
        self.delBtn.setMaximumHeight(rowH)

    def enterEvent(self, event):
        self.editBtn.setVisible(True)
        self.delBtn.setVisible(True)

    def leaveEvent(self, event):
        self.editBtn.setVisible(False)
        self.delBtn.setVisible(False)

    def mouseDoubleClickEvent(self, event):
        self._onEdit(self.sid)


class StationSelector(QGroupBox):

    checksChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle('Stations')
        self._cell_seg = None
        self._x_cell = None
        self._n = 0
        self._stations = []        # [{'id', 'cell_index', 'active'}]
        self._next_id = 0
        self._editing_id = None
        self._build_ui()

    # ---- construction -------------------------------------------------
    def _build_ui(self):
        # Do NOT demand horizontal expansion — the controls column is narrow and
        # already lives in a scroll area; a greedy size hint here rebalances the
        # whole main-window QHBoxLayout. The station list is a plain layout (no
        # nested QScrollArea — that caused size-hint blowups) and relies on the
        # outer graph-controls scroll area for overflow.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(3)

        # The slider gets its own full-width row (otherwise it collapses to just
        # its handle and can't reach the ends), then a compact row of
        # cell-index + distance + Add, then a range/total readout.
        self.slider = QSlider(Qt.Orientation.Horizontal)
        root.addWidget(self.slider)

        # Compact editor row: cell label + spinbox + Add. The spinbox is capped
        # so the row min width stays well under the fixed 220 px column (minus a
        # possible vertical scrollbar) — otherwise the content overflows and
        # side-scrolls. Distance + range go on their own shrinkable lines.
        editor = QHBoxLayout()
        editor.setSpacing(3)
        editor.addWidget(QLabel('cell'))
        self.spin = QSpinBox()
        self.spin.setMaximumWidth(80)   # fit 3-4 digit cell indices + arrows
        editor.addWidget(self.spin)
        editor.addStretch(1)
        self.addBtn = QPushButton('Add')
        self.addBtn.setMaximumWidth(48)
        editor.addWidget(self.addBtn)
        root.addLayout(editor)

        self.distLabel = QLabel('—')
        self.distLabel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.distLabel)

        self.rangeLabel = QLabel('')
        self.rangeLabel.setStyleSheet('color: gray')
        self.rangeLabel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.rangeLabel)

        self.listLayout = QVBoxLayout()
        self.listLayout.setSpacing(1)
        root.addLayout(self.listLayout)
        root.addStretch(1)

        self.slider.valueChanged.connect(self._editor_changed)
        self.spin.valueChanged.connect(self._editor_changed)
        self.addBtn.clicked.connect(self._on_add)

    # ---- public API ---------------------------------------------------
    def setup(self, payload):
        """Populate from an ``sr.srm1d_axial`` payload: default one (fore)
        station per grain, visible. Resets any prior state."""
        from srm_1d.station_viz import default_stations
        self._cell_seg = np.asarray(payload['cell_segment_id'], dtype=np.int64)
        self._x_cell = np.asarray(payload['x_cell'], dtype=float)
        self._n = int(self._x_cell.shape[0])
        self._editing_id = None
        self.addBtn.setText('Add')
        for w in (self.slider, self.spin):
            w.blockSignals(True)
            w.setRange(0, max(0, self._n - 1))
            w.blockSignals(False)
        self.rangeLabel.setText('index 0-{}  ({} cells)'.format(
            max(0, self._n - 1), self._n))

        self._stations = []
        self._next_id = 0
        for st in default_stations(self._cell_seg, self._x_cell):
            if st.role == 'fore':
                self._stations.append({'id': self._next_id,
                                       'cell_index': st.cell_index, 'active': True})
                self._next_id += 1

        init = self._stations[0]['cell_index'] if self._stations else 0
        self._set_editor_value(init)
        self._rebuild_list()

    def clear(self):
        self._stations = []
        self._editing_id = None
        self._rebuild_list()

    def getSelectedStations(self):
        """Active stations as full dicts for the plot / columns:
        ``{cell_index, grain, role, label, kind, position_m}`` (grain = -1 for
        head/gap/aft)."""
        from srm_1d.station_viz import classify_cell, station_full_label
        out = []
        if self._cell_seg is None:
            return out
        for st in self._stations:
            if not st['active']:
                continue
            cls = classify_cell(st['cell_index'], self._cell_seg, self._x_cell)
            out.append({
                'cell_index': st['cell_index'],
                'grain': cls['grain'] if cls['kind'] == 'grain' else -1,
                'role': cls['role'],
                'kind': cls['kind'],
                'label': station_full_label(cls),
                'position_m': cls.get('position_m'),
            })
        return out

    # ---- editor -------------------------------------------------------
    def _set_editor_value(self, v):
        for w in (self.slider, self.spin):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self._after_value(v)

    def _editor_changed(self, v):
        # Keep slider/spin in sync without re-entrancy.
        for w in (self.slider, self.spin):
            if w.value() != v:
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        self._after_value(v)
        # Live edit: while editing a station, dragging moves it (reclassify +
        # redraw). May be heavy on big motors — acceptable per design.
        if self._editing_id is not None:
            st = self._find(self._editing_id)
            if st is not None and st['cell_index'] != v:
                st['cell_index'] = v
                self._rebuild_list()
                self.checksChanged.emit()

    def _after_value(self, v):
        if self._x_cell is not None and 0 <= v < self._n:
            self.distLabel.setText('{:.0f} mm'.format(self._x_cell[v] * 1000.0))
        self._update_add_enabled(v)

    def _update_add_enabled(self, v):
        if self._editing_id is not None:
            self.addBtn.setEnabled(True)
            return
        dup = any(st['cell_index'] == v for st in self._stations)
        self.addBtn.setEnabled(not dup)

    def _on_add(self):
        if self._editing_id is not None:        # 'Done' — leave edit mode
            self._editing_id = None
            self.addBtn.setText('Add')
            self._update_add_enabled(self.spin.value())
            self._rebuild_list()
            return
        v = self.spin.value()
        if any(st['cell_index'] == v for st in self._stations):
            return
        self._stations.append({'id': self._next_id, 'cell_index': v, 'active': True})
        self._next_id += 1
        self._rebuild_list()
        self.checksChanged.emit()

    # ---- row callbacks ------------------------------------------------
    def _find(self, sid):
        return next((s for s in self._stations if s['id'] == sid), None)

    def _on_toggle(self, sid, checked):
        st = self._find(sid)
        if st is not None and st['active'] != checked:
            st['active'] = checked
            self.checksChanged.emit()

    def _on_edit(self, sid):
        st = self._find(sid)
        if st is None:
            return
        self._editing_id = sid
        self.addBtn.setText('Done')
        self._set_editor_value(st['cell_index'])

    def _on_delete(self, sid):
        before = len(self._stations)
        self._stations = [s for s in self._stations if s['id'] != sid]
        if len(self._stations) == before:
            return
        if self._editing_id == sid:
            self._editing_id = None
            self.addBtn.setText('Add')
        self._rebuild_list()
        self.checksChanged.emit()

    # ---- list rendering ----------------------------------------------
    def _row_text(self, st, cls):
        role = cls['role']
        prefix = (role + ' ') if role else ''
        dist = self._x_cell[st['cell_index']] * 1000.0
        return '{}(c{}/{}) · {:.0f} mm'.format(prefix, st['cell_index'], self._n, dist)

    def _rebuild_list(self):
        from srm_1d.station_viz import cell_categories, classify_cell
        while self.listLayout.count():
            item = self.listLayout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if self._cell_seg is not None:
            for cat in cell_categories(self._cell_seg):
                members = [s for s in self._stations
                           if cat['lo'] <= s['cell_index'] <= cat['hi']]
                if not members:
                    continue
                header = QLabel('<b>{}</b> <span style="color:gray">(c{}-{})</span>'
                                .format(cat['label'], cat['lo'], cat['hi']))
                header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                self.listLayout.addWidget(header)
                for st in sorted(members, key=lambda s: s['cell_index']):
                    cls = classify_cell(st['cell_index'], self._cell_seg, self._x_cell)
                    editing = (st['id'] == self._editing_id)
                    text = self._row_text(st, cls)
                    if editing:
                        text = '> ' + text          # marker on the edited row
                    row = StationRow(st['id'], text, st['active'],
                                     self._on_toggle, self._on_edit, self._on_delete)
                    self.listLayout.addWidget(row)
