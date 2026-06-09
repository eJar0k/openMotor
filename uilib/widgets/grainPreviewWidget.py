from threading import Thread

import numpy as np
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import pyqtSignal

import motorlib
import motorlib.units

from ..views.GrainPreview_ui import Ui_GrainPreview
from .grainPreviewGraph import GrainPreviewGraph
from .motorSliceWidget import renderGrainLongitudinal


class GrainPreviewWidget(QWidget):

    previewReady = pyqtSignal(tuple)

    def __init__(self):
        super().__init__()
        self.ui = Ui_GrainPreview()
        self.ui.setupUi(self)

        self.ui.tabFace.setupImagePlot()
        self.ui.tabRegression.setupImagePlot()
        self.ui.tabAreaGraph.setupGraphPlot()

        # Side-on OD-taper preview, added programmatically and shown only when a
        # grain carries an OD/end taper (gated per-grain in updateView).
        self.tabLongitudinal = GrainPreviewGraph()
        self.tabLongitudinal.setupGraphPlot()
        self._longTabIndex = self.ui.tabWidget.addTab(self.tabLongitudinal,
                                                      'Longitudinal')
        self.ui.tabWidget.setTabVisible(self._longTabIndex, False)

        # Used to navigate back to the tab the user was on after they clear alerts
        self.lastNonAlertTab = 1
        # Set while previewing a tapered grain so the area tab shows the
        # slice-averaged burn area instead of one face's.
        self._taperedGrain = None
        self.preferences = None      # for the longitudinal preview's length unit

        self.ui.tabWidget.currentChanged.connect(self.onTabChanged)

        self.previewReady.connect(self.updateView)

    def setPreferences(self, pref):
        self.preferences = pref

    def _sideGrain(self, grain, side):
        """A plain grain for the chosen taper end's cross-section (face /
        regression images): the base/forward props, or the aft overrides."""
        sub = type(grain)()
        props = {k: v for k, v in grain.getProperties().items() if k != 'taper'}
        if side == 'Aft':
            props.update(motorlib.taper.aft_props_from_grain(grain))
        sub.setProperties(props)
        return sub

    def loadGrain(self, grain, previewSide='Forward'):
        # For a tapered grain, draw the selected end's cross-section but show
        # the slice-averaged burn area on the area tab.
        if grain.isTapered():
            self._taperedGrain = grain
            grain = self._sideGrain(grain, previewSide)
        else:
            self._taperedGrain = None

        geomAlerts = grain.getGeometryErrors()

        self.ui.tabAlerts.clear()
        for err in geomAlerts:
            self.ui.tabAlerts.addItem(err.description)

        for alert in geomAlerts:
            if alert.level == motorlib.simResult.SimAlertLevel.ERROR:
                # Go to alerts tab and clear up graph/images
                self.ui.tabWidget.setCurrentIndex(0)
                self.ui.tabFace.cleanup()
                self.ui.tabRegression.cleanup()
                self.ui.tabAreaGraph.cleanup()
                return

        # If they were on the alert tab, go to their last image/graph tab. Otherwise, let them stay
        if self.ui.tabWidget.currentIndex() == 0:
            self.ui.tabWidget.setCurrentIndex(self.lastNonAlertTab)

        # Generate the contents to show on the image/graph tabs
        dataThread = Thread(target=self._genData, args=[grain])
        dataThread.start()

    def _genData(self, grain):
        out = grain.getRegressionData(250, coreBlack=False)
        longitudinal = None
        if self._taperedGrain is not None:
            # Replace the single-face area curve with the slice-averaged one.
            coreIm, regImage, contours, _ = out
            avg = motorlib.taper.averaged_area_curve(self._taperedGrain, map_dim=250)
            out = (coreIm, regImage, contours, avg)
            longitudinal = self._longitudinalData(grain)
        self.previewReady.emit(out + (longitudinal,))

    def _longitudinalData(self, sideGrain):
        """OD-taper side-view arrays (or None if the grain has no OD taper).
        Bore = hydraulic-equivalent radius at t=0; R_outer follows the OD
        profile. Also returns a crop ``window`` (meters) per tapered end so the
        view can show just the ends at 1:1 scale. ``sideGrain`` already has its
        regression map built (getRegressionData)."""
        od_ends = motorlib.taper.od_ends_from_taper(self._taperedGrain.getTaperDef())
        if not od_ends:
            return None
        length = self._taperedGrain.getProperty('length')
        full_d = self._taperedGrain.getProperty('diameter')
        if length <= 0.0:
            return None
        try:
            area = sideGrain.getPortArea(0.0)
            perim = sideGrain.getCorePerimeter(0.0)
            r_bore = 2.0 * area / perim if perim > 1e-9 else 0.0
        except Exception:
            r_bore = 0.0
        xs = np.linspace(0.0, length, 240)
        r_out = np.array([0.5 * motorlib.taper.od_diameter_at(x / length, length,
                                                              full_d, od_ends)
                          for x in xs])
        windows = []
        for e in od_ends:
            le = float(e.get('length', 0.0))
            margin = 0.25 * le
            if e.get('end') == 'aft':
                windows.append((max(0.0, length - le - margin), length))
            else:
                windows.append((0.0, min(length, le + margin)))
        return {'x': xs, 'R_bore': r_bore, 'R_outer': r_out, 'windows': windows}

    def updateView(self, data):
        coreIm, regImage, contours, contourLengths, longitudinal = data

        self.ui.tabFace.cleanup()
        self.ui.tabFace.showImage(coreIm)

        if regImage is not None:
            self.ui.tabRegression.cleanup()
            self.ui.tabRegression.showImage(regImage)
            self.ui.tabRegression.showContours(contours)

            points = [[], []]

            for k in contourLengths.keys():
                points[0].append(k)
                points[1].append(contourLengths[k])

            self.ui.tabAreaGraph.cleanup()
            self.ui.tabAreaGraph.showGraph(points)

        # OD-taper side view: shown only when the grain has an OD taper. Each
        # tapered end gets its own 1:1 panel cropped to that end (the uniform
        # middle is omitted so the taper isn't squished). Length unit follows
        # preferences.
        showLong = longitudinal is not None
        self.ui.tabWidget.setTabVisible(self._longTabIndex, showLong)
        if showLong:
            if self.preferences is not None:
                unit = self.preferences.getUnit('m')
            else:
                unit = 'm'
            scale = motorlib.units.convert(1.0, 'm', unit)
            windows = longitudinal['windows'] or [
                (longitudinal['x'][0], longitudinal['x'][-1])]
            fig = self.tabLongitudinal.figure
            fig.clear()
            n = len(windows)
            for i, win in enumerate(windows):
                ax = fig.add_subplot(1, n, i + 1)
                renderGrainLongitudinal(
                    ax, longitudinal['x'], longitudinal['R_bore'],
                    longitudinal['R_outer'], lengthScale=scale, lengthLabel=unit,
                    aspect='equal', xlim=win)
            # constrained layout reserves room for the axis labels (tight_layout
            # clipped them once padding widened the axes).
            fig.set_layout_engine('constrained')
            self.tabLongitudinal.draw()

    def onTabChanged(self, tabIndex):
        if tabIndex != 0:
            self.lastNonAlertTab = tabIndex

    def cleanup(self):
        self.lastNonAlertTab = 1
        self.ui.tabAlerts.clear()
        self.ui.tabRegression.cleanup()
        self.ui.tabFace.cleanup()
        self.ui.tabAreaGraph.cleanup()
        self.ui.tabAreaGraph.resetGraphBounds()
