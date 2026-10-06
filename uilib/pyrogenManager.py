"""Reusable igniter-material library, mirroring ``PropellantManager``.

The motor *embeds* its igniter material (self-contained ``.ric``); this library
(persisted via the ``IGNITERS`` file section) is a picker -- selecting a
material deep-copies it into the motor's igniter block, exactly as the
propellant library copies into a grain. The library editor (``PyrogenMenu``) is
created lazily in ``showMenu`` so the data layer is usable headlessly and does
not depend on Qt.

The material model is owned by the igniter provider (see ``motorlib.igniter``):
materials are held as RAW dicts, the file is seeded from the provider's
built-in library when missing, and on every load each entry is upgraded when it
is an exact superseded library snapshot and any provider material whose name is
absent is appended (like the propellant library, the file stays user-editable).
With no provider the library is simply empty.
"""
import copy
from os.path import join
from os import replace

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from motorlib import solvers

from .fileIO import loadFile, saveFile, fileTypes, getConfigPath
from .logger import logger


class PyrogenManager(QObject):

    updated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.pyrogens = []  # raw material dicts
        self.loadPyrogens()
        self.pyroMenu = None  # built lazily in showMenu (needs Qt)

    def _path(self):
        return join(getConfigPath(), 'pyrogens.yaml')

    @staticmethod
    def _providerMaterials():
        provider = solvers.get_igniter_provider()
        if provider is None:
            return []
        return [copy.deepcopy(m) for m in provider.get_igniter_materials()]

    def loadPyrogens(self):
        path = self._path()
        try:
            pyroList = loadFile(path, fileTypes.IGNITERS)
            provider = solvers.get_igniter_provider()
            changed = False
            self.pyrogens = []
            for pyroDict in pyroList:
                material = copy.deepcopy(pyroDict)
                if provider is not None:
                    block, upgraded = provider.upgrade_igniter_block(
                        {'pyrogen': material})
                    if upgraded:
                        material = block['pyrogen']
                        changed = True
                self.pyrogens.append(material)
            names = self.getNames()
            for material in self._providerMaterials():
                if material.get('name') not in names:
                    self.pyrogens.append(material)
                    names.append(material.get('name'))
                    changed = True
            if changed:
                self.savePyrogens()
        except FileNotFoundError:
            logger.warn('No pyrogen file found, saving defaults')
            self.pyrogens = self._providerMaterials()
            if self.pyrogens:
                self.savePyrogens()
        except Exception as error:
            backupPath = join(getConfigPath(), 'pyrogens_backup.yaml')
            logger.warn('Error loading pyrogens: {}'.format(error))
            QApplication.instance().outputException(
                error, "Failed to load pyrogens. Backing up file to '{}' and "
                "starting fresh.".format(backupPath))
            replace(path, backupPath)
            self.pyrogens = self._providerMaterials()
            if self.pyrogens:
                self.savePyrogens()

    def savePyrogens(self):
        pyrogens = copy.deepcopy(self.pyrogens)
        try:
            logger.log('Saving pyrogens to "{}"'.format(self._path()))
            saveFile(self._path(), pyrogens, fileTypes.IGNITERS)
        except Exception:
            logger.warn('Unable to save pyrogens!')

    def getNames(self):
        return [pyro.get('name') for pyro in self.pyrogens]

    def getPyrogenByName(self, name):
        """The library's raw material dict for ``name`` (ValueError if absent)."""
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
