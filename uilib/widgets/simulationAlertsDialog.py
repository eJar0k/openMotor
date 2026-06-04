from PyQt6.QtWidgets import QDialog, QTableWidgetItem, QHeaderView, QApplication

from motorlib.simResult import alertLevelNames, alertTypeNames

from ..views.SimulationAlertsDialog_ui import Ui_SimAlertsDialog

class SimulationAlertsDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = Ui_SimAlertsDialog()
        self.ui.setupUi(self)

        self.setWindowIcon(QApplication.instance().icon)

        header = self.ui.tableWidgetAlerts.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        # Long alert descriptions (e.g. the srm_1d run-health failure) were
        # truncated and the dialog couldn't be resized. Wrap the text, let
        # rows grow, and make the dialog user-resizable.
        self.ui.tableWidgetAlerts.setWordWrap(True)
        self.setSizeGripEnabled(True)
        # The table's natural minimum (~680 wide, from the long Details column)
        # forced the dialog open oversized and clamped resize(). Allow a small
        # explicit minimum so our compact default holds; Details word-wraps
        # within it and the user can resize up from there.
        self.setMinimumSize(380, 130)
        self.resize(560, 220)

        self.hide()

    def displayAlerts(self, simRes):
        self.ui.tableWidgetAlerts.setRowCount(0) # Clear the table
        if len(simRes.alerts) == 0:
            return

        self.ui.tableWidgetAlerts.setRowCount(len(simRes.alerts))
        for row, alert in enumerate(simRes.alerts):
            self.ui.tableWidgetAlerts.setItem(row, 0, QTableWidgetItem(alertLevelNames[alert.level]))
            self.ui.tableWidgetAlerts.setItem(row, 1, QTableWidgetItem(alertTypeNames[alert.type]))
            self.ui.tableWidgetAlerts.setItem(row, 2, QTableWidgetItem(alert.location))
            self.ui.tableWidgetAlerts.setItem(row, 3, QTableWidgetItem(alert.description))
        t = self.ui.tableWidgetAlerts
        # Realize the dialog at its target WIDTH first; the wrapped-row height
        # depends on the (Stretch) Details column width, so rows must be sized
        # after layout. Then fit the dialog HEIGHT to the actual content.
        self.resize(560, 160)
        self.show()
        t.setMinimumHeight(0)            # drop the .ui min so it can be compact
        t.resizeRowsToContents()         # now with the final column width
        tableH = (t.horizontalHeader().height()
                  + sum(t.rowHeight(r) for r in range(t.rowCount()))
                  + 2 * t.frameWidth())
        t.setMaximumHeight(tableH)
        self.resize(560, min(tableH + 96, 420))  # + header label + buttons
