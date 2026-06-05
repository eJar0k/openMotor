from PyQt6.QtWidgets import QWidget, QHeaderView, QLabel, QTableWidgetItem
import numpy as np

import motorlib
from motorlib.simResult import singleValueChannels, multiValueChannels, alertLevelNames, alertTypeNames
from motorlib.constants import standardGravity

from .grainImageWidget import GrainImageWidget
from .stationSelector import StationSelector

from ..views.ResultsWidget_ui import Ui_ResultsWidget

class ResultsWidget(QWidget):
    # These channels are extracted from the simResult and put into the grain table in this order that should match
    # the labels in the .ui file
    grainTableFields = ('mass', 'massFlow', 'massFlux', 'web')
    # Display labels for the grain-tab vertical header (mirrors the .ui text so
    # the station-row insertion can rebuild the header without losing them).
    grainTableFieldLabels = {
        'mass': 'Mass', 'massFlow': 'Mass Flow (Port)',
        'massFlux': 'Mass Flux (Port)', 'web': 'Web',
    }
    # v0.8.x station mode (srm_1d results): the per-cell axial fields the graph
    # can plot at each active station, as (payload-key, label, unit) tuples.
    # Appended after the normal Y channels. Fields that DUPLICATE an openMotor
    # channel (Pressure↔pressure, Mach Number↔machNumber, Regression↔regression)
    # REPLACE those channels in station mode (see stationExcludedChannels) — the
    # axial value is the per-cell truth, so we don't show both. ``unit`` is the
    # openMotor unit category the raw payload is in, for display conversion.
    stationFields = (
        ('P', 'Pressure', 'Pa'),
        ('Mach', 'Mach Number', ''),
        ('r_total', 'Burn Rate', 'm/s'),
        ('r_erosive', 'Erosive Burn Rate', 'm/s'),
        ('regress', 'Regression', 'm'),
        ('u', 'Velocity', 'm/s'),
        ('T', 'Gas Temperature', 'K'),
        ('D_port', 'Port Diameter', 'm'),
    )
    # openMotor channels suppressed in station mode because an axial field above
    # supersedes them (their per-cell value is the meaningful one).
    stationExcludedChannels = ('time', 'pressure', 'machNumber', 'regression')

    def __init__(self, parent):
        super().__init__(parent)
        self.ui = Ui_ResultsWidget()
        self.ui.setupUi(self)
        self.preferences = None
        self.simResult = None
        self.cachedChecks = None

        excludes = ['kn', 'pressure', 'force', 'mass', 'massFlow', 'massFlux', 'exitPressure', 'dThroat', 'volumeLoading', 'machNumber']
        self.ui.channelSelectorX.setupChecks(False, default='time', exclude=excludes)
        self.ui.channelSelectorX.setTitle('X Axis')
        self.ui.channelSelectorY.setupChecks(True, default=['kn', 'pressure', 'force'], exclude=['time'])
        self.ui.channelSelectorY.setTitle('Y Axis')
        self.ui.channelSelectorX.checksChanged.connect(self.xSelectionChanged)
        self.ui.channelSelectorY.checksChanged.connect(self.drawGraphs)
        self.ui.grainSelector.checksChanged.connect(self.onSelectorChanged)

        # v0.8.x: the rich station selector replaces the grain checkbox list for
        # srm_1d results. Inserted next to the grain selector in the graph-
        # controls column, hidden until a station-bearing result is shown.
        self.stationSelector = StationSelector()
        gsIndex = self.ui.verticalLayout_3.indexOf(self.ui.grainSelector)
        self.ui.verticalLayout_3.insertWidget(gsIndex + 1, self.stationSelector)
        self.stationSelector.setVisible(False)
        self.stationSelector.checksChanged.connect(self.onSelectorChanged)

        self.ui.horizontalSliderTime.valueChanged.connect(self.updateGrainTab)
        self.ui.tableWidgetGrains.setRowHeight(0, 128)

        header = self.ui.tableWidgetAlerts.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.grainImageWidgets = []   # one per grain-tab COLUMN
        self.grainImages = []         # one per grain (regression map), by grain id
        self.grainLabels = []         # one dict per COLUMN

        # v0.8.x station-viz: when a result carries a per-station axial payload
        # (srm_1d transient solver), the grain selector becomes a STATION
        # selector and the grain-burnback tab renders one cross-section COLUMN
        # per active station (driven by the carried per-cell ``regress``). The
        # graph plots the carried fields sliced at each active station vs time.
        # None / channel mode for quasi-steady results (unchanged).
        self._axial = None
        self._stationMode = False
        self._yMode = 'channel'       # 'channel' (QS) | 'station' (srm_1d fields)
        self._columns = []            # grain ids (QS) | station dicts (srm_1d)

    def setPreferences(self, pref):
        self.preferences = pref
        self.ui.widgetGraph.setPreferences(pref)

    def setupGrainChecks(self, numGrains, restoreCachedChecks):
        self.ui.grainSelector.resetChecks()
        self.ui.grainSelector.setupChecks(numGrains, True)
        if restoreCachedChecks and self.cachedChecks is not None and len(self.cachedChecks) > 0 and max(self.cachedChecks or []) < self.ui.grainSelector.getNumberChecks():
            self.ui.grainSelector.setChecks(self.cachedChecks)
        else:
            self.cachedChecks = None

    def _setupGraphControls(self):
        """Configure the graph controls for the active result type. The X/Y
        channel selectors stay the SAME in both modes (so pressure/force/Kn/
        exit pressure/dThroat and the per-grain channels remain plottable over
        time); only the **Grains** selector becomes a **Stations** selector for
        srm_1d results, and the Y list gains the carried per-cell axial fields
        (burn rate / regression / Mach / …) sliced per station. The Y selector
        is only rebuilt on a real mode change so the user's selection survives
        successive runs of the same type."""
        if self._stationMode:
            if self._yMode != 'station':
                self.ui.channelSelectorY.resetChecks()
                # Drop the channels superseded by axial fields; default the
                # remaining standard traces (kn/force) + axial Pressure 'P'
                # (which replaces the chamber-pressure channel).
                self.ui.channelSelectorY.setupChecks(
                    True, default=['kn', 'force'],
                    exclude=list(self.stationExcludedChannels))
                self.ui.channelSelectorY.appendStationFields(
                    [(k, l) for k, l, _u in self.stationFields], defaultChecked=['P'])
                self._yMode = 'station'
            # Swap the grain checkbox list for the rich station selector.
            self.ui.grainSelector.setVisible(False)
            self.stationSelector.setVisible(True)
            self.stationSelector.setLengthUnit(self.preferences.getUnit('m'))
            self.stationSelector.setup(self._axial)
        else:
            if self._yMode != 'channel':
                self.ui.channelSelectorY.resetChecks()
                self.ui.channelSelectorY.setupChecks(True, default=['kn', 'pressure', 'force'], exclude=['time'])
                self._yMode = 'channel'
            self.stationSelector.setVisible(False)
            self.ui.grainSelector.setVisible(True)
            self.setupGrainChecks(len(self.simResult.motor.grains), True)

    def showData(self, simResult):
        self.simResult = simResult
        self._axial = getattr(simResult, 'srm1d_axial', None)
        self._stationMode = self._axial is not None

        self._setupGraphControls()
        self.drawGraphs()

        self.cleanupGrainTab()
        self.ui.horizontalSliderTime.setMaximum(len(simResult.channels['time'].getData()) - 1)

        # Per-grain regression maps (by grain id) are built once; station
        # columns reuse them, so toggling stations only rebuilds cheap widgets.
        self.grainImages = []
        for grain in simResult.motor.grains:
            if isinstance(grain, motorlib.grain.PerforatedGrain):
                self.grainImages.append(grain.getRegressionData(128, coreBlack=False)[1])
            else:
                self.grainImages.append(None)
        self.rebuildGrainColumns()

        self.ui.tableWidgetAlerts.setRowCount(0) # Clear the table
        self.ui.tableWidgetAlerts.setRowCount(len(simResult.alerts))
        for row, alert in enumerate(simResult.alerts):
            self.ui.tableWidgetAlerts.setItem(row, 0, QTableWidgetItem(alertLevelNames[alert.level]))
            self.ui.tableWidgetAlerts.setItem(row, 1, QTableWidgetItem(alertTypeNames[alert.type]))
            self.ui.tableWidgetAlerts.setItem(row, 2, QTableWidgetItem(alert.location))
            self.ui.tableWidgetAlerts.setItem(row, 3, QTableWidgetItem(alert.description))

    def xSelectionChanged(self):
        if self.ui.channelSelectorX.getSelectedChannels()[0] in multiValueChannels:
            self.ui.channelSelectorY.unselect(singleValueChannels)
            self.ui.channelSelectorY.toggleEnabled(singleValueChannels, False)
        else:
            self.ui.channelSelectorY.toggleEnabled(singleValueChannels, True)
        self.drawGraphs()

    def onSelectorChanged(self):
        """Grain/station selector changed. In station mode the grain-burnback
        tab's columns ARE the active stations, so rebuild them; the graph is
        redrawn in both modes (QS: which grains plot; station: which stations)."""
        if self._stationMode:
            self.rebuildGrainColumns()
        self.drawGraphs()

    def drawGraphs(self):
        if self.simResult is None:
            return
        xCheck = self.ui.channelSelectorX.getSelectedChannels()[0]
        yChecks = self.ui.channelSelectorY.getSelectedChannels()
        if self._stationMode:
            # Station mode: the selector picks stations; per-grain channels plot
            # for the grains owning the selected stations, and any selected
            # axial fields plot per station. X/Y channels are otherwise normal.
            stations = self.stationSelector.getSelectedStations()
            grains = sorted({s['grain'] for s in stations if s['grain'] >= 0})
            self.ui.widgetGraph.showData(self.simResult, xCheck, yChecks, grains,
                                         stations=stations,
                                         axialFields=self._axialDisplayUnits())
        else:
            grains = self.ui.grainSelector.getSelectedGrains()
            self.ui.widgetGraph.showData(self.simResult, xCheck, yChecks, grains)

    def _axialDisplayUnits(self):
        """Resolve display units for the axial fields, honoring the user's
        preferences. Most fields use their own category's unit; burn rate is
        m/s *physically* but should read in length-per-second (mm/s, in/s) per
        the user's LENGTH unit — NOT the gas-velocity unit (which may be ft/s).
        Returns ``{key: (label, fromUnit, toUnit)}``."""
        rateUnit = {'m': 'm/s', 'cm': 'cm/s', 'mm': 'mm/s',
                    'in': 'in/s', 'ft': 'ft/s'}.get(self.preferences.getUnit('m'), 'mm/s')
        out = {}
        for key, label, fromUnit in self.stationFields:
            toUnit = rateUnit if key in ('r_total', 'r_erosive') else self.preferences.getUnit(fromUnit)
            out[key] = (label, fromUnit, toUnit)
        return out

    def _columnGrain(self, column):
        """Owning grain id for a grain-tab column (a grain id in QS mode, a
        station dict's grain in station mode)."""
        return column['grain'] if self._stationMode else column

    def rebuildGrainColumns(self):
        """(Re)build the grain-burnback tab's columns. QS: one column per grain.
        Station: one column per ACTIVE station (the graph-view selection), each
        rendering its own axial cell's cross-section. Cheap to call on every
        selection change — the regression maps are cached in ``grainImages``."""
        if self.simResult is None:
            return
        table = self.ui.tableWidgetGrains
        if self._stationMode:
            # Only grain-owned stations get a burnback cross-section column
            # (head/gap/aft cells have no grain regression map). They still
            # plot in the graph.
            self._columns = [s for s in self.stationSelector.getSelectedStations()
                             if s['grain'] >= 0]
        else:
            self._columns = list(range(len(self.simResult.motor.grains)))

        table.setColumnCount(0)
        table.setColumnCount(len(self._columns))
        table.setRowCount(1 + len(self.grainTableFields))
        table.setVerticalHeaderItem(0, QTableWidgetItem('Port'))
        for fid, field in enumerate(self.grainTableFields):
            table.setVerticalHeaderItem(1 + fid, QTableWidgetItem(self.grainTableFieldLabels[field]))
        table.setRowHeight(0, 128)

        self.grainImageWidgets = []
        self.grainLabels = []
        for col, column in enumerate(self._columns):
            imageWidget = GrainImageWidget()
            self.grainImageWidgets.append(imageWidget)
            table.setCellWidget(0, col, imageWidget)
            labels = {}
            for fid, field in enumerate(self.grainTableFields):
                labels[field] = QLabel(field)
                table.setCellWidget(1 + fid, col, labels[field])
            self.grainLabels.append(labels)
            if self._stationMode:
                table.setHorizontalHeaderItem(col, QTableWidgetItem(self._columnShortLabel(column)))
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.updateGrainTab()

    def _columnShortLabel(self, station):
        """Compact column header for a station — its derived label,
        e.g. 'G2 aft (c41)'."""
        return station['label']

    def _stationRegression(self, station, currentTime):
        """(regDist [m], hasWebLeft) for a station at ``currentTime`` from the
        carried per-cell ``regress`` field. The grain's wall web is its t=0
        'web' channel value (all cells unregressed → web == wall web)."""
        cell = station['cell_index']
        regDist = float(np.interp(currentTime, self._axial['snap_times'],
                                  self._axial['fields']['regress'][:, cell]))
        wallWeb = self.simResult.channels['web'].getPoint(0)[station['grain']]
        return regDist, regDist < wallWeb

    def updateGrainTab(self):
        if self.simResult is not None:
            index = self.ui.horizontalSliderTime.value()
            currentTime = self.simResult.channels['time'].getPoint(index)
            for col, column in enumerate(self._columns):
                gid = self._columnGrain(column)
                grain = self.simResult.motor.grains[gid]
                if self.grainImages[gid] is not None:
                    if self._stationMode:
                        regDist, hasWebLeft = self._stationRegression(column, currentTime)
                    else:
                        regDist = self.simResult.channels['regression'].getPoint(index)[gid]
                        webRemaining = self.simResult.channels['web'].getPoint(index)[gid]
                        hasWebLeft = webRemaining > self.simResult.motor.config.getProperty('burnoutWebThres')
                    mapDist = regDist / (0.5 * grain.props['diameter'].getValue())
                    image = np.logical_and(self.grainImages[gid] > mapDist, hasWebLeft)
                    self.grainImageWidgets[col].showImage(image)
                else:
                    self.grainImageWidgets[col].setText('-')
                for field in self.grainTableFields:
                    fromUnit = self.simResult.channels[field].unit
                    toUnit = self.preferences.getUnit(fromUnit)
                    val = motorlib.units.convert(self.simResult.channels[field].getPoint(index)[gid], fromUnit, toUnit)
                    self.grainLabels[col][field].setText('{:.3f} {}'.format(val, toUnit))

            remainingTime = self.simResult.channels['time'].getLast() - currentTime
            self.ui.labelTimeProgress.setText('{:.3f} s'.format(currentTime))
            self.ui.labelTimeRemaining.setText('{:.3f} s'.format(remainingTime))

            currentImpulse = self.simResult.getImpulse(index)
            remainingImpulse = self.simResult.getImpulse() - currentImpulse
            impUnit = self.preferences.getUnit('Ns')
            self.ui.labelImpulseProgress.setText(motorlib.units.convFormat(currentImpulse, 'Ns', impUnit))
            self.ui.labelImpulseRemaining.setText(motorlib.units.convFormat(remainingImpulse, 'Ns', impUnit))

            currentMass = self.simResult.getPropellantMass(index)
            remainingMass = self.simResult.getPropellantMass() - currentMass
            massUnit = self.preferences.getUnit('kg')
            self.ui.labelMassProgress.setText(motorlib.units.convFormat(remainingMass, 'kg', massUnit))
            self.ui.labelMassRemaining.setText(motorlib.units.convFormat(currentMass, 'kg', massUnit))

            currentISP = self.simResult.getISP(index)
            self.ui.labelISPProgress.setText('{:.3f} s'.format(currentISP))
            if currentMass != 0:
                remainingISP = remainingImpulse / (currentMass * standardGravity)
                self.ui.labelISPRemaining.setText('{:.3f} s'.format(remainingISP))
            else:
                self.ui.labelISPRemaining.setText('-')

    def resetPlot(self):
        # Cache the grain selection for restore (only meaningful in grain mode;
        # station selections default to fore on each run).
        self.cachedChecks = [] if self._stationMode else self.ui.grainSelector.getSelectedGrains()
        self.simResult = None
        self._axial = None
        self._stationMode = False
        self._columns = []
        self.ui.grainSelector.resetChecks()
        self.stationSelector.clear()
        self.ui.widgetGraph.resetPlot()
        self.cleanupGrainTab()

    def cleanupGrainTab(self):
        # Clear the column model FIRST: moving the slider below fires
        # updateGrainTab, which must not see stale columns after a mode switch.
        # grainImageWidgets are per-column, grainImages per-grain — independent
        # lengths now, so clear each outright (setColumnCount(0) drops the cell
        # widgets from the table).
        self.grainImageWidgets = []
        self.grainImages = []
        self.grainLabels = []
        self._columns = []
        self.ui.tableWidgetGrains.setColumnCount(0)
        self.ui.horizontalSliderTime.setValue(0)
        self.ui.labelTimeProgress.setText('-')
        self.ui.labelTimeRemaining.setText('-')
        self.ui.labelImpulseProgress.setText('-')
        self.ui.labelImpulseRemaining.setText('-')
        self.ui.labelMassProgress.setText('-')
        self.ui.labelMassRemaining.setText('-')
        self.ui.labelISPProgress.setText('-')
        self.ui.labelISPRemaining.setText('-')
