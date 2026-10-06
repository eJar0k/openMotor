"""Pyrogen library editor — code-built mirror of ``PropellantMenu``.

A QDialog with a list of library pyrogens, a property editor for the selected
one, and New/Delete/Edit. Mirrors PropellantMenu's flow (select -> edit,
auto-named new, delete, save-on-apply, duplicate-name guard) so library
pyrogens get the same rigid edit-tracking/saving as propellants. Built in code
(no ``.ui``) to avoid adding a form to the fork.
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QPushButton, QApplication)
from PyQt6.QtCore import pyqtSignal

import copy

from motorlib import solvers
from motorlib.igniter import material_collection, changed_values

from .collectionEditor import CollectionEditor
from ..logger import logger


class PyrogenMenu(QDialog):

    closed = pyqtSignal()

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.setWindowTitle('Pyrogen Library')
        app = QApplication.instance()
        if app is not None and hasattr(app, 'icon'):
            self.setWindowIcon(app.icon)

        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        layout.addLayout(body)

        self.listWidget = QListWidget()
        self.listWidget.setSelectionRectVisible(True)
        body.addWidget(self.listWidget, 1)

        self.pyroEditor = CollectionEditor(self, buttons=True)
        # CollectionEditor.__init__ does super().__init__(QWidget(parent)),
        # leaving a stray QWidget parented to this dialog floating at (0,0) --
        # an invisible "ghost" over the first list item that eats clicks on its
        # text. Drop it once the editor is reparented into the layout.
        _ghost = self.pyroEditor.parentWidget()
        body.addWidget(self.pyroEditor, 2)
        if _ghost is not None and _ghost is not self:
            _ghost.setParent(None)
            _ghost.deleteLater()

        buttonRow = QHBoxLayout()
        self.newButton = QPushButton('New Pyrogen')
        self.editButton = QPushButton('Edit')
        self.deleteButton = QPushButton('Delete')
        for b in (self.newButton, self.editButton, self.deleteButton):
            buttonRow.addWidget(b)
        layout.addLayout(buttonRow)

        self.listWidget.currentItemChanged.connect(self.pyroSelected)
        # Also enable on a plain click: Qt auto-selects row 0 on focus, so a
        # click on the first item fires no currentItemChanged and otherwise
        # leaves the buttons disabled ("can't select the first entry").
        self.listWidget.itemClicked.connect(self.pyroSelected)
        self.listWidget.doubleClicked.connect(self.editPyro)
        self.newButton.pressed.connect(self.newPyro)
        self.editButton.pressed.connect(self.editPyro)
        self.deleteButton.pressed.connect(self.deletePyro)
        self.pyroEditor.changeApplied.connect(self.pyroEdited)
        self.pyroEditor.closed.connect(self.editorClosed)

        self.listWidget.setMinimumWidth(160)
        self.pyroEditor.setMinimumWidth(320)
        self.resize(760, 520)

        self.editingPyrogen = False
        # Widget values right after the editor was rendered (display-unit
        # rounding included); only keys that differ from it were edited.
        self._editSnapshot = {}
        self.setupPyroList()
        self.setupButtons()

    def show(self):
        # Reset any stale editing state from a prior session so the list is
        # always selectable on reopen (fixes "can't select until add/delete").
        self.editingPyrogen = False
        self.pyroEditor.cleanup()
        self.toggleButtons(False)
        self.setupPyroList()
        self.setupButtons()
        super().show()

    def setupButtons(self):
        self.editButton.setEnabled(False)
        self.deleteButton.setEnabled(False)

    def setupPyroList(self):
        self.listWidget.clear()
        self.listWidget.addItems(self.manager.getNames())

    def pyroSelected(self):
        enabled = self.listWidget.currentRow() >= 0 and not self.editingPyrogen
        self.editButton.setEnabled(enabled)
        self.deleteButton.setEnabled(enabled)

    def newPyro(self):
        name = 'New Pyrogen'
        names = self.manager.getNames()
        if name in names:
            n = 1
            while '{} {}'.format(name, n) in names:
                n += 1
            name = '{} {}'.format(name, n)
        provider = solvers.get_igniter_provider()
        default = provider.get_default_igniter() if provider else None
        if default is None:
            logger.warn('No igniter provider: cannot create a pyrogen')
            return
        newPyro = copy.deepcopy(default['pyrogen'])  # provider's default seed
        newPyro['name'] = name
        self.manager.pyrogens.append(newPyro)
        self.manager.savePyrogens()
        self.setupPyroList()
        self.listWidget.setCurrentRow(len(self.manager.pyrogens) - 1)
        self.editPyro()

    def deletePyro(self):
        row = self.listWidget.currentRow()
        if row < 0:
            return
        del self.manager.pyrogens[row]
        self.manager.savePyrogens()
        self.setupPyroList()
        self.setupButtons()

    def editPyro(self):
        row = self.listWidget.currentRow()
        if row < 0:
            return
        collection = material_collection(self.manager.pyrogens[row])
        if collection is None:      # no igniter provider
            return
        self.pyroEditor.loadProperties(collection)
        self._customizePyroFields()
        self._editSnapshot = self.pyroEditor.getProperties()
        self.toggleButtons(True)
        self.editingPyrogen = True

    def _customizePyroFields(self):
        """``form`` is informational only (since v0.7.4 it does NOT drive
        A_burn — particle_diameter_m / particle_LD_ratio are the real knobs).
        Drop it from the editor and tooltip the particle inputs with typical
        sizes; the data still carries ``form`` as a YAML marker."""
        eds = self.pyroEditor.propertyEditors
        if 'form' in eds:
            self.pyroEditor.form.setRowVisible(eds['form'], False)
        if 'particle_diameter_m' in eds:
            eds['particle_diameter_m'].setToolTip(
                'Characteristic particle size. Typical: powder ~0.1-1 mm, '
                'pellets ~3-5 mm, chunks ~5-15 mm.')
        if 'particle_LD_ratio' in eds:
            eds['particle_LD_ratio'].setToolTip(
                'Particle length / diameter. Typical: powder & chunks ~1, '
                'pellets ~1-2 (short cylinders).')

    def pyroEdited(self, pyroDict):
        row = self.listWidget.currentRow()
        # Don't allow duplicating an existing pyrogen's name.
        names = self.manager.getNames()
        if pyroDict.get('name') in names and names.index(pyroDict['name']) != row:
            logger.warn("Can't duplicate a pyrogen name!")
            del pyroDict['name']
        # D4: write back ONLY what the user changed; every other key
        # (including None / out-of-range / schema-unknown ones) is untouched.
        changes = changed_values(self._editSnapshot, pyroDict)
        self.manager.pyrogens[row].update(changes)
        self.manager.savePyrogens()
        self.setupPyroList()

    def editorClosed(self):
        self.editingPyrogen = False
        self.toggleButtons(False)

    def toggleButtons(self, editing):
        self.listWidget.setEnabled(not editing)
        self.newButton.setEnabled(not editing)
        self.editButton.setEnabled(not editing)
        self.deleteButton.setEnabled(not editing)

    def closeEvent(self, event=None):
        self.toggleButtons(False)
        self.pyroEditor.cleanup()
        self.closed.emit()
        if event is not None and not isinstance(event, bool):
            event.accept()
