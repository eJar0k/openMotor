from PyQt6.QtWidgets import QLabel, QComboBox, QHBoxLayout, QWidget
from PyQt6.QtCore import pyqtSignal

import motorlib.grain
import motorlib.nozzle
import motorlib.motor

from .collectionEditor import CollectionEditor
from .grainPreviewWidget import GrainPreviewWidget
from .nozzlePreviewWidget import NozzlePreviewWidget
from .solverConfigController import SolverConfigController

class MotorEditor(CollectionEditor):

    # Emitted on Apply when editing the motor config: the standard MotorConfig
    # values plus the per-motor solver-config overrides (mirrors the global
    # Preferences screen, but scoped to this motor).
    motorConfigApplied = pyqtSignal(dict, dict)
    # Emitted when the config editor's solver dropdown changes, to couple the
    # active solver (wired to PreferencesManager by the main window).
    activeSolverChanged = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent, True)

        # Solver selector shown only while editing the motor config (the
        # grain-table 'Config' row). Inserted above the property form.
        self.solverSelector = QComboBox()
        selectorRow = QHBoxLayout()
        selectorRow.addWidget(QLabel('Solver:'))
        selectorRow.addWidget(self.solverSelector)
        selectorRow.addStretch()
        self.solverSelectorContainer = QWidget()
        self.solverSelectorContainer.setLayout(selectorRow)
        self.solverSelectorContainer.hide()
        self.layout().insertWidget(0, self.solverSelectorContainer)
        self.solverSelector.currentTextChanged.connect(self._solverChanged)

        self.expRatioLabel = QLabel("Expansion ratio: -")
        self.expRatioLabel.hide()
        self.stats.addWidget(self.expRatioLabel)

        self.grainPreview = GrainPreviewWidget()
        self.grainPreview.hide()
        self.stats.addWidget(self.grainPreview)

        self.nozzlePreview = NozzlePreviewWidget()
        self.nozzlePreview.hide()
        self.stats.addWidget(self.nozzlePreview)

        self.objType = None
        self.configMotor = None     # set while editing the motor config
        self.controller = None

    def propertyUpdate(self):
        if self.objType is None:
            return
        if issubclass(self.objType, motorlib.nozzle.Nozzle):
            exitDia = self.propertyEditors['exit'].getValue()
            throatDia = self.propertyEditors['throat'].getValue()
            if throatDia == 0:
                self.expRatioLabel.setText('Expansion ratio: -')
            else:
                self.expRatioLabel.setText('Expansion ratio: {:.3f}'.format((exitDia / throatDia) ** 2))
            nozzle = self.objType()
            nozzle.setProperties(self.getProperties())
            self.nozzlePreview.loadNozzle(nozzle)

        if issubclass(self.objType, motorlib.grain.PerforatedGrain):
            testGrain = self.objType()
            testGrain.setProperties(self.getProperties())
            self.grainPreview.loadGrain(testGrain)

    def loadObject(self, obj):
        self.configMotor = None
        self.controller = None
        self.solverSelectorContainer.hide()
        self.objType = type(obj)
        self.loadProperties(obj)

        if issubclass(self.objType, motorlib.grain.PerforatedGrain):
            self.grainPreview.show()
            self.nozzlePreview.hide()
            self.expRatioLabel.hide()
            self.propertyUpdate()

        if issubclass(self.objType, motorlib.nozzle.Nozzle):
            self.expRatioLabel.show()
            self.nozzlePreview.show()
            self.grainPreview.hide()

        if issubclass(self.objType, motorlib.motor.MotorConfig):
            self.expRatioLabel.hide()
            self.nozzlePreview.hide()
            self.grainPreview.hide()

    def loadMotorConfig(self, motor, activeSolver):
        """Edit the motor's config with the solver-aware layout (shared section
        + the active solver's settings), mirroring the Preferences screen. The
        srm_1d section edits this motor's own per-motor override."""
        self.configMotor = motor
        self.objType = motorlib.motor.MotorConfig
        self.expRatioLabel.hide()
        self.nozzlePreview.hide()
        self.grainPreview.hide()

        self.controller = SolverConfigController(
            self, motor.config, motor.solverConfigs)

        self.solverSelector.blockSignals(True)
        self.solverSelector.clear()
        self.solverSelector.addItems(self.controller.solverNames())
        if activeSolver in self.controller.specificColls:
            self.solverSelector.setCurrentText(activeSolver)
        self.solverSelector.blockSignals(False)

        self.controller.show(self.solverSelector.currentText())
        self.solverSelectorContainer.show()

    def setActiveSolver(self, name):
        """Sync the dropdown when the active solver changes elsewhere (no-op
        unless the config editor is open)."""
        if self.configMotor is None or name not in self.controller.specificColls:
            return
        if self.solverSelector.currentText() != name:
            self.solverSelector.setCurrentText(name)

    def _solverChanged(self, name):
        if self.controller is not None:
            self.controller.show(name)
        if name and self.configMotor is not None:
            self.activeSolverChanged.emit(name)

    def apply(self):
        if self.configMotor is not None:
            general, solverConfigs = self.controller.extract()
            self.configMotor = None
            self.controller = None
            self.solverSelectorContainer.hide()
            self.cleanup()
            self.motorConfigApplied.emit(general, solverConfigs)
            self.closed.emit()
        else:
            super().apply()

    def cleanup(self):
        self.expRatioLabel.hide()
        self.grainPreview.hide()
        self.nozzlePreview.hide()
        self.grainPreview.cleanup()
        super().cleanup()
