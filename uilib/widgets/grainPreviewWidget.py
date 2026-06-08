from threading import Thread

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import pyqtSignal

import motorlib

from ..views.GrainPreview_ui import Ui_GrainPreview

class GrainPreviewWidget(QWidget):

    previewReady = pyqtSignal(tuple)

    def __init__(self):
        super().__init__()
        self.ui = Ui_GrainPreview()
        self.ui.setupUi(self)

        self.ui.tabFace.setupImagePlot()
        self.ui.tabRegression.setupImagePlot()
        self.ui.tabAreaGraph.setupGraphPlot()

        # Used to navigate back to the tab the user was on after they clear alerts
        self.lastNonAlertTab = 1
        # Set while previewing a tapered grain so the area tab shows the
        # slice-averaged burn area instead of one face's.
        self._taperedGrain = None

        self.ui.tabWidget.currentChanged.connect(self.onTabChanged)

        self.previewReady.connect(self.updateView)

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
        if self._taperedGrain is not None:
            # Replace the single-face area curve with the slice-averaged one.
            coreIm, regImage, contours, _ = out
            avg = motorlib.taper.averaged_area_curve(self._taperedGrain, map_dim=250)
            out = (coreIm, regImage, contours, avg)
        self.previewReady.emit(out)

    def updateView(self, data):
        coreIm, regImage, contours, contourLengths = data

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
