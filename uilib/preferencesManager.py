from os.path import join
from os import replace

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from motorlib.properties import PropertyCollection, EnumProperty
from motorlib.units import unitLabels, getAllConversions
from motorlib.motor import MotorConfig
from motorlib.solvers import QUASI_STEADY

from .fileIO import loadFile, saveFile, getConfigPath, fileTypes
from .defaults import DEFAULT_PREFERENCES
from .widgets import preferencesMenu
from .logger import logger

class Preferences():
    def __init__(self, propDict=None):
        self.general = MotorConfig()
        self.units = PropertyCollection()
        for unit in unitLabels:
            self.units.props[unit] = EnumProperty(unitLabels[unit], getAllConversions(unit))

        # v0.8.0: per-solver run-config, keyed by solver name. Stored as plain
        # value dicts (the schema is owned by each solver plugin, which may not
        # be importable here). The built-in quasi-steady solver uses `general`
        # and has no entry. Tolerant to absence for backward compatibility.
        self.solverConfigs = {}
        # v0.8.0: the active solver (which solver runs + whose config the
        # config screen shows). Persisted so the choice survives restarts.
        self.activeSolver = QUASI_STEADY

        if propDict is not None:
            self.applyDict(propDict)

    def getDict(self):
        prefDict = {}
        prefDict['general'] = self.general.getProperties()
        prefDict['units'] = self.units.getProperties()
        prefDict['solverConfigs'] = self.solverConfigs
        prefDict['activeSolver'] = self.activeSolver
        return prefDict

    def applyDict(self, dictionary):
        self.general.setProperties(dictionary['general'])
        self.units.setProperties(dictionary['units'])
        self.solverConfigs = dictionary.get('solverConfigs', {})
        # Preserve the current active solver when the dict omits it (the
        # Preferences 'Apply' emits general/units/solverConfigs only; the
        # active solver is set live via setActiveSolver). Fall back to QS only
        # when truly unset (fresh Preferences / no saved value).
        self.activeSolver = dictionary.get(
            'activeSolver', getattr(self, 'activeSolver', QUASI_STEADY))

    def getSolverConfig(self, name):
        """Return the saved run-config dict for a solver (empty if unset)."""
        return self.solverConfigs.get(name, {})

    def setSolverConfig(self, name, config):
        """Store the run-config dict for a solver."""
        self.solverConfigs[name] = config

    def getUnit(self, fromUnit):
        if fromUnit in self.units.props:
            return self.units.getProperty(fromUnit)
        return fromUnit


class PreferencesManager(QObject):

    preferencesChanged = pyqtSignal(object)
    # Emitted when the active solver changes (from the Sim menu or the
    # Preferences solver dropdown) so both stay in sync.
    activeSolverChanged = pyqtSignal(str)

    def __init__(self, makeMenu=True):
        super().__init__()
        self.preferences = Preferences(DEFAULT_PREFERENCES)
        if makeMenu:
            self.menu = preferencesMenu.PreferencesMenu()
            self.menu.preferencesApplied.connect(self.newPreferences)
            self.menu.activeSolverChanged.connect(self.setActiveSolver)
        self.loadPreferences()

    def setActiveSolver(self, name):
        """Set the active solver, persist it, and notify listeners (the Sim
        menu, the Preferences dropdown) so the selection stays coupled."""
        if name == self.preferences.activeSolver:
            return
        self.preferences.activeSolver = name
        self.savePreferences()
        self.activeSolverChanged.emit(name)

    def newPreferences(self, prefDict):
        logger.log('Updating preferences')
        self.preferences.applyDict(prefDict)
        self.savePreferences()
        self.publishPreferences()

    def loadPreferences(self):
        preferencesPath = join(getConfigPath(), 'preferences.yaml')
        try:
            prefDict = loadFile(preferencesPath, fileTypes.PREFERENCES)
            self.preferences.applyDict(prefDict)
            self.publishPreferences()
        except FileNotFoundError:
            logger.warn('Preferences file does not exist, creating new file')
            self.savePreferences()
        except Exception as error:
            backupPath = join(getConfigPath(), 'preferences_backup.yaml')
            logger.warn('Error loading preferences: {}'.format(error))
            QApplication.instance().outputException(error, "Failed to load preferences. Backing up file to '{}' and starting fresh.".format(backupPath))
            replace(preferencesPath, backupPath)
            self.savePreferences()

    def savePreferences(self):
        try:
            destinationPath = getConfigPath() + 'preferences.yaml'
            logger.log('Saving preferences to "{}"'.format(destinationPath))
            saveFile(destinationPath, self.preferences.getDict(), fileTypes.PREFERENCES)
        except:
            logger.warn('Unable to save preferences')

    def showMenu(self):
        logger.log('Showing preferences menu')
        self.menu.load(self.preferences)
        self.menu.show()

    def publishPreferences(self):
        self.preferencesChanged.emit(self.preferences)
