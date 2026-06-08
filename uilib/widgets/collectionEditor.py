from PyQt6.QtWidgets import QWidget, QFormLayout, QVBoxLayout, QHBoxLayout
from PyQt6.QtWidgets import QLabel, QPushButton
from PyQt6.QtWidgets import QSpacerItem, QSizePolicy
from PyQt6.QtCore import pyqtSignal

import motorlib

from .propertyEditor import PropertyEditor


class CollectionEditor(QWidget):

    changeApplied = pyqtSignal(dict)
    closed = pyqtSignal()

    def __init__(self, parent, buttons=False):
        super(CollectionEditor, self).__init__(QWidget(parent))

        self.preferences = None

        self.propertyEditors = {}
        self.setLayout(QVBoxLayout())
        self.layout().setSpacing(0)

        self.form = QFormLayout()
        self.layout().addLayout(self.form)

        self.stats = QVBoxLayout()
        self.layout().addLayout(self.stats)


        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.layout().addItem(self.verticalSpacer)

        self.buttons = buttons
        if self.buttons:
            self.addButtons()

    def addButtons(self):
        self.buttons = QHBoxLayout()
        self.layout().addLayout(self.buttons)

        self.applyButton = QPushButton('Apply')
        self.applyButton.pressed.connect(self.apply)
        self.applyButton.hide()

        self.cancelButton = QPushButton('Cancel')
        self.cancelButton.pressed.connect(self.close)
        self.cancelButton.hide()

        self.buttons.addWidget(self.applyButton)
        self.buttons.addWidget(self.cancelButton)

    def propertyUpdate(self):
        pass

    def close(self):
        self.closed.emit()
        self.cleanup()

    def apply(self):
        res = self.getProperties()
        self.cleanup()
        self.changeApplied.emit(res)
        self.closed.emit()

    def setPreferences(self, pref):
        self.preferences = pref

    def loadProperties(self, obj):
        self.cleanup()
        self._addPropertyRows(obj)
        if self.buttons:
            self.applyButton.show()
            self.cancelButton.show()
        self.propertyUpdate()

    def loadGrouped(self, groups):
        """Render several property collections as labelled sections in one
        form. ``groups`` is a list of ``(headerText, collection)`` tuples; a
        bold header row precedes each group's property rows. Property editors
        are registered flat (keys must be unique across groups), so
        ``getProperties`` returns every group's values together."""
        self.cleanup()
        for headerText, obj in groups:
            header = QLabel(headerText)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            self.form.addRow(header)
            self._addPropertyRows(obj)
        if self.buttons:
            self.applyButton.show()
            self.cancelButton.show()
        self.propertyUpdate()

    def _addPropertyRows(self, obj):
        for prop in obj.props:
            # The axial-taper definition has no inline form widget yet (its
            # dedicated editor is a later phase); skip it so grains don't show
            # an empty row. The property still round-trips through getDict.
            if isinstance(obj.props[prop], motorlib.properties.TaperProperty):
                continue
            self.propertyEditors[prop] = PropertyEditor(self, obj.props[prop], self.preferences)
            self.propertyEditors[prop].valueChanged.connect(self.propertyUpdate)
            label = QLabel('{}:'.format(obj.props[prop].dispName))
            label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
            self.form.addRow(label, self.propertyEditors[prop])

    def cleanup(self):
        # Remove every row (property rows AND any section-header rows added by
        # loadGrouped), not just one per property editor.
        while self.form.rowCount() > 0:
            self.form.removeRow(0)
        self.propertyEditors = {}

        if self.buttons:
            self.applyButton.hide()
            self.cancelButton.hide()

    def getProperties(self):
        res = {}
        for prop in self.propertyEditors:
            out = self.propertyEditors[prop].getValue()
            if out is not None:
                res[prop] = out
        return res
