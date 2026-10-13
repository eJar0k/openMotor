from PyQt6.QtWidgets import (QGroupBox, QCheckBox, QPushButton, QLabel, QVBoxLayout,
                             QHBoxLayout, QWidget, QFileDialog, QMessageBox)
from PyQt6.QtCore import pyqtSignal, Qt

from motorlib.importedData import loadCsv, ImportedDataError


class ImportedDataSelector(QGroupBox):
    """Plot option for a user-imported CSV overlay. The parent 'Imported data'
    check opens a file dialog (when nothing is loaded yet); on a successful load
    it spawns one child check per data column. The data lives here, so it
    persists across re-simulation until cleared or replaced."""

    checksChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle('Imported Data')
        self.data = None
        self.childChecks = []     # parallel to self.data.columns
        self.setLayout(QVBoxLayout())

        self.parentCheck = QCheckBox('Imported data')
        self.layout().addWidget(self.parentCheck)

        self.childHolder = QWidget()
        childLayout = QVBoxLayout(self.childHolder)
        childLayout.setContentsMargins(20, 0, 0, 0)
        self.layout().addWidget(self.childHolder)

        self.fileLabel = QLabel('')
        self.fileLabel.setWordWrap(True)
        self.layout().addWidget(self.fileLabel)

        buttons = QHBoxLayout()
        self.loadButton = QPushButton('Load CSV...')
        self.clearButton = QPushButton('Clear')
        buttons.addWidget(self.loadButton)
        buttons.addWidget(self.clearButton)
        self.layout().addLayout(buttons)

        self.parentCheck.toggled.connect(self._onParentToggled)
        self.loadButton.clicked.connect(self.promptForFile)
        self.clearButton.clicked.connect(self.clear)
        self._refresh()

    # --- loading -----------------------------------------------------------
    def promptForFile(self):
        """Ask for a .csv and load it. Returns True on success."""
        path, _ = QFileDialog.getOpenFileName(self, 'Import data', '',
                                              'CSV files (*.csv);;All files (*)')
        if not path:
            return False
        return self.loadFile(path)

    def loadFile(self, path):
        """Load ``path``; on a bad file show a message and keep the previous
        data. Returns True on success."""
        try:
            data = loadCsv(path)
        except ImportedDataError as e:
            self._showError(str(e))
            return False
        except Exception as e:  # never crash the GUI on an odd file
            self._showError('Could not import the file: {}'.format(e))
            return False
        self._setData(data)
        return True

    def _showError(self, message):
        QMessageBox.warning(self, 'Import failed', message)

    def _setData(self, data):
        self.data = data
        for check in self.childChecks:
            check.setParent(None)
            check.deleteLater()
        self.childChecks = []
        layout = self.childHolder.layout()
        for col in data.columns:
            check = QCheckBox(col.displayName)
            check.setChecked(True)
            check.toggled.connect(self.checksChanged.emit)
            layout.addWidget(check)
            self.childChecks.append(check)
        note = data.filename
        if not data.timeColumn.unitKnown:
            note += '\nTime unit not detected: plotted as-is on the time axis.'
        self.fileLabel.setText(note)
        self.parentCheck.blockSignals(True)
        self.parentCheck.setChecked(True)
        self.parentCheck.blockSignals(False)
        self._refresh()
        self.checksChanged.emit()

    def clear(self):
        for check in self.childChecks:
            check.setParent(None)
            check.deleteLater()
        self.childChecks = []
        self.data = None
        self.fileLabel.setText('')
        self.parentCheck.blockSignals(True)
        self.parentCheck.setChecked(False)
        self.parentCheck.blockSignals(False)
        self._refresh()
        self.checksChanged.emit()

    # --- state -------------------------------------------------------------
    def _onParentToggled(self, on):
        if on and self.data is None:
            if not self.promptForFile():
                self.parentCheck.blockSignals(True)
                self.parentCheck.setChecked(False)
                self.parentCheck.blockSignals(False)
            return  # a successful load already refreshed and emitted
        self._refresh()
        self.checksChanged.emit()

    def _refresh(self):
        on = self.parentCheck.isChecked() and self.data is not None
        self.childHolder.setVisible(self.data is not None)
        self.childHolder.setEnabled(on)
        self.fileLabel.setVisible(self.data is not None)
        self.clearButton.setEnabled(self.data is not None)
        self.loadButton.setText('Reload / replace...' if self.data is not None else 'Load CSV...')

    def getSelectedColumns(self):
        """Selected ImportedColumn objects ([] when the parent is unchecked)."""
        if self.data is None or not self.parentCheck.isChecked():
            return []
        return [col for col, check in zip(self.data.columns, self.childChecks)
                if check.isChecked()]
