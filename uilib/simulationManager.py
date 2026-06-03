from threading import Thread

from PyQt6.QtCore import QObject
from PyQt6.QtCore import pyqtSignal

from motorlib import solvers
from motorlib.simResult import (
    SimulationResult, SimAlert, SimAlertLevel, SimAlertType,
)

from .widgets.simulationAlertsDialog import SimulationAlertsDialog
from .widgets.simulationProgressDialog import SimulationProgressDialog
from .logger import logger

class SimulationManager(QObject):

    simulationDone = pyqtSignal(object)
    newSimulationResult = pyqtSignal(object)
    simProgress = pyqtSignal(float)
    simCanceled = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.progDialog = SimulationProgressDialog()
        self.simProgress.connect(self.progDialog.progressUpdate)
        self.simulationDone.connect(self.progDialog.hide)
        self.progDialog.simulationCanceled.connect(self.cancelSim)

        self.alertsDialog = SimulationAlertsDialog()
        self.simulationDone.connect(self.alertsDialog.displayAlerts)

        self.motor = None
        self.preferences = None

        # v0.8.0 (D6): the active solver is selected by name from the
        # motorlib.solvers registry, defaulting to the built-in quasi-steady
        # solver so behavior is unchanged until the user picks another.
        self.activeSolverName = solvers.QUASI_STEADY

        self.currentSimThread = None
        self.threadStopped = False # Set to true to stop simulation thread after it finishes the iteration it is on

    def setPreferences(self, preferences):
        self.preferences = preferences

    def setActiveSolver(self, name):
        """Select the active solver by registry name. Falls back to the
        quasi-steady solver if the name isn't registered."""
        if solvers.get_solver(name) is None:
            name = solvers.QUASI_STEADY
        self.activeSolverName = name
        logger.log('Active solver set to "{}"'.format(name))

    def runSimulation(self, motor, show=True): # Show sets if the results will be reported on newSimulationResult and shown in UI
        logger.log('Running simulation')
        self.motor = motor
        self.threadStopped = False
        self.progDialog.show()
        self.currentSimThread = Thread(target=self._simThread, args=[show])
        self.currentSimThread.start()

    def _simThread(self, show):
        solver = solvers.get_solver(self.activeSolverName)
        try:
            if solver is None:
                simRes = self.motor.runSimulation(self.updateProgressBar)
            else:
                simRes = solver.simulate(
                    self.motor, callback=self.updateProgressBar)
        except Exception as exc:
            # A solver (e.g. the srm_1d transient backend) may raise — surface
            # it as a failed result with an alert rather than hanging the
            # progress dialog, which only hides on simulationDone.
            logger.error('Solver "{}" failed: {}'.format(
                self.activeSolverName, exc))
            simRes = SimulationResult(self.motor)
            simRes.addAlert(SimAlert(
                SimAlertLevel.ERROR, SimAlertType.VALUE,
                'Solver "{}" failed: {}'.format(self.activeSolverName, exc),
                'Solver'))
        self.simulationDone.emit(simRes)
        if simRes.success and show:
            logger.log('Simulation succeeded')
            self.newSimulationResult.emit(simRes)

    def updateProgressBar(self, prog):
        self.simProgress.emit(prog)
        return self.threadStopped

    def cancelSim(self):
        logger.log('Canceling simulation')
        self.threadStopped = True
        self.simCanceled.emit()
