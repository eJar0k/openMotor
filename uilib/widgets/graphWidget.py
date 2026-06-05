from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

import motorlib

def selectGrains(data, grains):
    # Returns the data corresponding to specific grains from data structured like [[G1, G2], [G1, G2], [G1, G2]...]
    out = []
    for frame in data:
        out.append([])
        for grain in grains:
            out[-1].append(frame[grain])
    return out

class GraphWidget(FigureCanvas):
    def __init__(self, parent):
        super(GraphWidget, self).__init__(Figure())
        self.setParent(None)
        self.setupPlot()
        self.preferences = None

    def setPreferences(self, pref):
        self.preferences = pref

    def setupPlot(self):
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.plot = self.figure.add_subplot(111)
        self.figure.tight_layout()

    def plotData(self, simResult, xChannel, yChannels, grains, stations=None, axialFields=None):
        """Plot the selected openMotor channels exactly as before. The only
        srm_1d adaptation: ``yChannels`` may include keys from ``axialFields``
        (carried per-cell fields in ``simResult.srm1d_axial``) — those are
        plotted sliced at each selected ``station`` (a cell) vs time. The
        standard channels (pressure/force/Kn/exit pressure/dThroat + the per-
        grain channels) plot unchanged; per-grain channels use ``grains``
        (in station mode these are the grains owning the selected stations)."""
        self.plot.clear()

        axial = getattr(simResult, 'srm1d_axial', None)
        axialKeys = set(axialFields) if axialFields else set()
        # Channels (everything that isn't a carried axial field).
        channelYs = [y for y in yChannels if y not in axialKeys]
        axialYs = [y for y in yChannels if y in axialKeys]

        xAxisUnit = self.preferences.getUnit(simResult.channels[xChannel].unit)
        legend = []

        xIsMulti = simResult.channels[xChannel].valueType in (list, tuple)
        if xIsMulti and len(grains) > 0:
            xData = selectGrains(simResult.channels[xChannel].getData(xAxisUnit), grains)
        elif not xIsMulti:
            xData = simResult.channels[xChannel].getData(xAxisUnit)
        else:
            xData = None  # multi-value X with no grains: channel plot can't resolve

        for channelName in channelYs:
            channel = simResult.channels[channelName]
            yUnit = self.preferences.getUnit(channel.unit)
            if channel.valueType in (list, tuple) and len(grains) > 0 and xData is not None:
                yData = selectGrains(channel.getData(yUnit), grains)
                self.plot.plot(xData, yData)
            elif channel.valueType in (int, float) and xData is not None:
                self.plot.plot(xData, channel.getData(yUnit))
            if channel.valueType in (int, float):
                if yUnit != '':
                    legend.append('{} - {}'.format(channel.name, yUnit))
                else:
                    legend.append(channel.name)
            elif channel.valueType in (list, tuple):
                for i in range(len(channel.getData()[0])):
                    if i in grains:
                        if yUnit != '':
                            legend.append('{} - Grain {} - {}'.format(channel.name, i + 1, yUnit))
                        else:
                            legend.append('{} - Grain {}'.format(channel.name, i + 1))

        # srm_1d per-cell axial fields: one line per (field, selected station),
        # plotted vs the carried snapshot time base (converted to the user's
        # time unit). Each field arrives with a pre-resolved display unit
        # (label, fromUnit, toUnit) from the results widget (which owns prefs).
        if axial is not None and axialYs and stations:
            timeUnit = simResult.channels['time'].unit
            timeToUnit = self.preferences.getUnit(timeUnit)
            t = motorlib.units.convert(axial['snap_times'], timeUnit, timeToUnit)
            for field in axialYs:
                mat = axial['fields'].get(field)
                if mat is None:
                    continue
                label, fromUnit, toUnit = axialFields[field]
                for station in stations:
                    y = motorlib.units.convert(mat[:, station['cell_index']], fromUnit, toUnit)
                    self.plot.plot(t, y)
                    suffix = ' - {}'.format(toUnit) if toUnit != '' else ''
                    legend.append('{} - {}{}'.format(label, station['label'], suffix))

        # Legend placement. A few entries → a fixed corner inside (never the
        # jumpy 'best' that lands mid-plot). Many entries (station mode) → move
        # it OUTSIDE on the right in a single small-font column so it neither
        # covers the data nor overflows the view horizontally (the ncol wrap
        # did the latter).
        if legend:
            if len(legend) <= 6:
                self.figure.subplots_adjust(right=0.97)
                self.plot.legend(legend, loc='upper right', fontsize='small')
            else:
                self.figure.subplots_adjust(right=0.74)
                self.plot.legend(legend, loc='upper left', bbox_to_anchor=(1.02, 1.0),
                                 fontsize='x-small', borderaxespad=0.0)
        self.plot.set_xlabel('{} - {}'.format(simResult.channels[xChannel].name, xAxisUnit))
        self.plot.grid(True)

    def saveImage(self, simResult, xChannel, yChannels, grains, path):
        self.plotData(simResult, xChannel, yChannels, grains)
        self.plot.set_title(simResult.getFullDesignation())
        self.figure.savefig(path, bbox_inches="tight")
        # Clear, but don't draw to not wipe away the graph in the UI
        self.plot.clear()

    def showData(self, simResult, xChannel, yChannels, grains, stations=None, axialFields=None):
        self.plotData(simResult, xChannel, yChannels, grains, stations, axialFields)
        self.draw()

    def resetPlot(self):
        self.plot.clear()
        self.draw()
