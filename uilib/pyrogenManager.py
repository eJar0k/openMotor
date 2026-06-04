"""Reusable pyrogen-material library, mirroring ``PropellantManager``.

The motor *embeds* its igniter pyrogen (self-contained ``.ric``); this library
(persisted via the ``IGNITERS`` file section) is a picker — selecting a pyrogen
copies it into ``motor.igniterPyrogen``, exactly as the propellant library
copies into a grain. The library editor (``PyrogenMenu``) is created lazily in
``showMenu`` so the data layer is usable headlessly and does not depend on Qt.
"""
from os.path import join
from os import replace

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

import motorlib.igniter

from .defaults import DEFAULT_PYROGENS
from .fileIO import loadFile, saveFile, fileTypes, getConfigPath
from .logger import logger


class PyrogenManager(QObject):

    updated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.pyrogens = []
        self.loadPyrogens()
        self.pyroMenu = None  # built lazily in showMenu (needs Qt)

    def _path(self):
        return join(getConfigPath(), 'pyrogens.yaml')

    def loadPyrogens(self):
        path = self._path()
        try:
            pyroList = loadFile(path, fileTypes.IGNITERS)
            for pyroDict in pyroList:
                newPyro = motorlib.igniter.Pyrogen()
                newPyro.setProperties(pyroDict)
                self.pyrogens.append(newPyro)
        except FileNotFoundError:
            logger.warn('No pyrogen file found, saving defaults')
            self.pyrogens = [self._fromDict(p) for p in DEFAULT_PYROGENS]
            self.savePyrogens()
        except Exception as error:
            backupPath = join(getConfigPath(), 'pyrogens_backup.yaml')
            logger.warn('Error loading pyrogens: {}'.format(error))
            QApplication.instance().outputException(
                error, "Failed to load pyrogens. Backing up file to '{}' and "
                "starting fresh.".format(backupPath))
            replace(path, backupPath)
            self.pyrogens = [self._fromDict(p) for p in DEFAULT_PYROGENS]
            self.savePyrogens()

    @staticmethod
    def _fromDict(pyroDict):
        pyro = motorlib.igniter.Pyrogen()
        pyro.setProperties(pyroDict)
        return pyro

    def savePyrogens(self):
        pyrogens = [pyro.getProperties() for pyro in self.pyrogens]
        try:
            logger.log('Saving pyrogens to "{}"'.format(self._path()))
            saveFile(self._path(), pyrogens, fileTypes.IGNITERS)
        except Exception:
            logger.warn('Unable to save pyrogens!')

    def getNames(self):
        return [pyro.getProperty('name') for pyro in self.pyrogens]

    def getPyrogenByName(self, name):
        return self.pyrogens[self.getNames().index(name)]

    def _ensureMenu(self):
        if self.pyroMenu is None and QApplication.instance() is not None:
            from .widgets.pyrogenMenu import PyrogenMenu
            self.pyroMenu = PyrogenMenu(self)
            self.pyroMenu.closed.connect(self.updated.emit)
        return self.pyroMenu

    def showMenu(self):
        logger.log('Showing pyrogen menu')
        menu = self._ensureMenu()
        if menu is not None:
            menu.setupPyroList()
            menu.show()

    def setPreferences(self, pref):
        menu = self._ensureMenu()
        if menu is not None:
            menu.pyroEditor.setPreferences(pref)
