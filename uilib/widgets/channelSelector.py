from PyQt6.QtWidgets import QGroupBox, QCheckBox, QRadioButton, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt

import motorlib

class ChannelSelector(QGroupBox):

    checksChanged = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.checks = {}
        # Populate list of checks to toggle channels
        self.setLayout(QVBoxLayout())

    def setupChecks(self, multiselect, disabled=[], default=None, exclude=[]):
        # This simres is only used to get the list of channels available
        simres = motorlib.simResult.SimulationResult(motorlib.motor.Motor())
        for channel in simres.channels:
            if channel not in exclude:
                if multiselect:
                    check = QCheckBox(simres.channels[channel].name)
                else:
                    check = QRadioButton(simres.channels[channel].name)
                self.layout().addWidget(check)
                self.checks[channel] = check
                if default is not None:
                    if multiselect:
                        if channel in default:
                            self.checks[channel].setCheckState(Qt.CheckState.Checked)
                    else:
                        self.checks[channel].setChecked(channel == default)
                self.checks[channel].toggled.connect(self.checksChanged.emit)
                if channel in disabled:
                    check.setEnabled(False)

    def appendStationFields(self, fields, defaultChecked=()):
        """Append srm_1d per-cell axial field checkboxes AFTER the normal
        openMotor channels (so the standard channels stay selectable and the
        graph can ALSO plot a carried field — burn rate / regression / Mach /
        … — sliced at each selected station vs time). ``fields`` is a list of
        ``(key, label)`` pairs; ``defaultChecked`` keys start checked (e.g. the
        axial 'P' that replaces the chamber-pressure channel). Idempotent per
        key. Initial check state is set BEFORE connecting the signal so setup
        doesn't emit checksChanged."""
        for key, label in fields:
            if key in self.checks:
                continue
            check = QCheckBox(label)
            if key in defaultChecked:
                check.setCheckState(Qt.CheckState.Checked)
            self.layout().addWidget(check)
            self.checks[key] = check
            self.checks[key].toggled.connect(self.checksChanged.emit)

    def getSelectedChannels(self):
        selected = []
        for check in self.checks:
            if self.checks[check].isChecked():
                selected.append(check)
        return selected

    def getUnselectedChannels(self):
        selected = []
        for check in self.checks:
            if not self.checks[check].isChecked():
                selected.append(check)
        return selected

    def resetChecks(self):
        for check in self.checks:
            self.layout().removeWidget(self.checks[check])
        self.checks = {}

    def unselect(self, channels):
        for channel in channels:
            if channel in self.checks.keys():
                self.checks[channel].setCheckState(Qt.CheckState.Unchecked)

    def toggleEnabled(self, channels, enabled):
        for channel in channels:
            if channel in self.checks.keys():
                self.checks[channel].setEnabled(enabled)