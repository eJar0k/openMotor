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

    # Emitted on Apply when editing the motor config (grain-table 'Config' row):
    # MotorConfig values, per-solver config overrides, the selected library
    # pyrogen NAME, and the igniter-chamber values. Pyrogen + igniter are
    # populated only for igniter-capable solvers (srm_1d); '' / {} otherwise.
    motorConfigApplied = pyqtSignal(dict, dict, str, dict)
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

        # Pyrogen picker shown in the config screen for igniter-capable solvers
        # (srm_1d). Selecting a library pyrogen copies it into the motor's
        # embedded material on apply (mirrors the grain propellant picker).
        self.pyrogenSelector = QComboBox()
        pyroRow = QHBoxLayout()
        pyroRow.addWidget(QLabel('Pyrogen:'))
        pyroRow.addWidget(self.pyrogenSelector)
        pyroRow.addStretch()
        self.pyrogenSelectorContainer = QWidget()
        self.pyrogenSelectorContainer.setLayout(pyroRow)
        self.pyrogenSelectorContainer.hide()
        self.layout().insertWidget(0, self.pyrogenSelectorContainer)

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
        self._pyrogenNames = []

    # Igniter-chamber fields that only apply to one injection topology.
    _IGNITER_PLENUM_ONLY = ('throat_area', 'volume')
    _IGNITER_BASKET_ONLY = ('basket_fill_fraction', 'pellet_packing_fraction')
    # Chamber fields whose -1 sentinel means "auto-size" (backend derives it).
    # Presented as "auto" at the spin minimum (0); any value <= 0 maps to -1.
    _IGNITER_AUTO_FIELDS = ('mass', 'throat_area', 'volume', 'burn_area',
                            'cartridge_length_m')

    def _setFieldVisible(self, key, visible):
        ed = self.propertyEditors.get(key)
        if ed is not None:
            self.form.setRowVisible(ed, visible)

    def _applyIgniterFieldRules(self):
        """Show only the chamber inputs relevant to the chosen injection
        topology: forward_plenum uses the orifice/plenum fields; the basket
        topologies use the basket packing fields."""
        ed = self.propertyEditors.get('injection_topology')
        if ed is None:
            return
        plenum = ed.getValue() == 'forward_plenum'
        for key in self._IGNITER_PLENUM_ONLY:
            self._setFieldVisible(key, plenum)
        for key in self._IGNITER_BASKET_ONLY:
            self._setFieldVisible(key, not plenum)

    def _setupIgniterFormExtras(self):
        """After the igniter-chamber section is rendered (config screen): show
        the -1 "auto" sentinels and apply the topology field rules."""
        for key in self._IGNITER_AUTO_FIELDS:
            ed = self.propertyEditors.get(key)
            if ed is not None and hasattr(ed.editor, 'setSpecialValueText'):
                ed.editor.setMinimum(0.0)
                ed.editor.setSpecialValueText('auto')
                if ed.editor.value() <= 0.0:
                    ed.editor.setValue(0.0)
        self._applyIgniterFieldRules()

    def propertyUpdate(self):
        if 'injection_topology' in self.propertyEditors:
            # Igniter-chamber form (config screen, srm_1d): drive field
            # relevance off the topology dropdown.
            self._applyIgniterFieldRules()
            return
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
        self.pyrogenSelectorContainer.hide()
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

    def loadMotorConfig(self, motor, activeSolver, pyrogenNames=None):
        """Edit the motor's config (grain-table 'Config' row): the solver-aware
        layout (shared + the active solver's settings) plus, for igniter-capable
        solvers (srm_1d), a Pyrogen picker and the Igniter-chamber section.
        Mirrors the Preferences screen; scoped to this motor."""
        self.configMotor = motor
        self.objType = motorlib.motor.MotorConfig
        self._pyrogenNames = list(pyrogenNames or [])
        self.expRatioLabel.hide()
        self.nozzlePreview.hide()
        self.grainPreview.hide()

        self.controller = SolverConfigController(
            self, motor.config, motor.solverConfigs, igniterSource=motor.igniter)

        self.solverSelector.blockSignals(True)
        self.solverSelector.clear()
        self.solverSelector.addItems(self.controller.solverNames())
        if activeSolver in self.controller.specificColls:
            self.solverSelector.setCurrentText(activeSolver)
        self.solverSelector.blockSignals(False)

        self._showConfigPage(self.solverSelector.currentText())
        self.solverSelectorContainer.show()

    def _showConfigPage(self, name):
        """Render the config page for solver ``name``; set up the igniter
        extras (pyrogen picker + auto/conditional chamber fields) if it uses
        an igniter, else hide the pyrogen picker."""
        self.controller.show(name)
        if self.controller.usesIgniter(name):
            current = self.configMotor.igniterPyrogen.getProperty('name')
            names = list(self._pyrogenNames)
            if current and current not in names:
                names.insert(0, current)
            self.pyrogenSelector.blockSignals(True)
            self.pyrogenSelector.clear()
            self.pyrogenSelector.addItems(names)
            if current in names:
                self.pyrogenSelector.setCurrentText(current)
            self.pyrogenSelector.blockSignals(False)
            self.pyrogenSelectorContainer.show()
            self._setupIgniterFormExtras()
        else:
            self.pyrogenSelectorContainer.hide()

    def setActiveSolver(self, name):
        """Sync the dropdown when the active solver changes elsewhere (no-op
        unless the config editor is open)."""
        if self.configMotor is None or name not in self.controller.specificColls:
            return
        if self.solverSelector.currentText() != name:
            self.solverSelector.setCurrentText(name)

    def _solverChanged(self, name):
        if self.controller is not None and self.configMotor is not None:
            self._showConfigPage(name)
        if name and self.configMotor is not None:
            self.activeSolverChanged.emit(name)

    def apply(self):
        if self.configMotor is not None:
            general, solverConfigs = self.controller.extract()
            usesIgniter = self.controller.usesIgniter(
                self.solverSelector.currentText())
            igniterProps = (self.controller.igniterProps() or {}) if usesIgniter else {}
            pyrogenName = self.pyrogenSelector.currentText() if usesIgniter else ''
            # "auto" (spin at 0, or any non-positive entry) -> -1 sentinel.
            for key in self._IGNITER_AUTO_FIELDS:
                if key in igniterProps and igniterProps[key] <= 0.0:
                    igniterProps[key] = -1.0
            self.configMotor = None
            self.controller = None
            self.solverSelectorContainer.hide()
            self.pyrogenSelectorContainer.hide()
            self.cleanup()
            self.motorConfigApplied.emit(general, solverConfigs, pyrogenName,
                                         igniterProps)
            self.closed.emit()
        else:
            super().apply()

    def close(self):
        # Canceling/closing the config editor must drop the config state and
        # hide the solver/pyrogen selectors, so they don't linger above the
        # grain area (and can't re-open config when the dropdown is changed).
        self.configMotor = None
        self.controller = None
        self.solverSelectorContainer.hide()
        self.pyrogenSelectorContainer.hide()
        super().close()

    def cleanup(self):
        self.expRatioLabel.hide()
        self.grainPreview.hide()
        self.nozzlePreview.hide()
        self.grainPreview.cleanup()
        super().cleanup()
