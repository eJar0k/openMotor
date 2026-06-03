from PyQt6.QtWidgets import (
    QDialog, QApplication, QComboBox, QLabel, QHBoxLayout, QWidget,
)
from PyQt6.QtCore import pyqtSignal

from ..views.Preferences_ui import Ui_PreferencesDialog
from .solverConfigController import SolverConfigController


class PreferencesMenu(QDialog):

    preferencesApplied = pyqtSignal(dict)
    # Emitted when the solver dropdown changes, so the active solver stays
    # coupled to the config screen (and the Sim -> Solver menu).
    activeSolverChanged = pyqtSignal(str)

    def __init__(self):
        QDialog.__init__(self)

        self.ui = Ui_PreferencesDialog()
        self.ui.setupUi(self)

        self.setWindowIcon(QApplication.instance().icon)

        # v0.8.0: a solver selector at the top of the General tab swaps the
        # config field set between solvers (D6); each pane shows a shared
        # section (the same global MotorConfig values) plus that solver's own
        # settings. Inserted above settingsEditorGeneral (index 0 = the
        # description label).
        self.solverSelector = QComboBox()
        selectorRow = QHBoxLayout()
        selectorRow.addWidget(QLabel('Solver:'))
        selectorRow.addWidget(self.solverSelector)
        selectorRow.addStretch()
        selectorContainer = QWidget()
        selectorContainer.setLayout(selectorRow)
        self.ui.verticalLayout_2.insertWidget(1, selectorContainer)
        self.solverSelector.currentTextChanged.connect(self._solverChanged)

        self.pref = None
        self.controller = None

        self.ui.buttonBox.accepted.connect(self.apply)
        self.ui.buttonBox.rejected.connect(self.cancel)

    def load(self, pref):
        self.pref = pref
        self.ui.settingsEditorGeneral.setPreferences(pref)
        self.ui.settingsEditorUnits.loadProperties(pref.units)

        self.controller = SolverConfigController(
            self.ui.settingsEditorGeneral, pref.general, pref.solverConfigs)

        self.solverSelector.blockSignals(True)
        self.solverSelector.clear()
        self.solverSelector.addItems(self.controller.solverNames())
        if pref.activeSolver in self.controller.specificColls:   # open coupled
            self.solverSelector.setCurrentText(pref.activeSolver)
        self.solverSelector.blockSignals(False)

        self.controller.show(self.solverSelector.currentText())

    def _solverChanged(self, name):
        if self.controller is not None:
            self.controller.show(name)
        if name:
            self.activeSolverChanged.emit(name)   # couple the active solver

    def apply(self):
        general, solverConfigs = self.controller.extract()
        self.preferencesApplied.emit({
            'general': general,
            'units': self.ui.settingsEditorUnits.getProperties(),
            'solverConfigs': solverConfigs,
        })
        self.hide()

    def cancel(self):
        self.hide()
