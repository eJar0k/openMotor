"""Transient-solver plugin registry (v0.7.0).

A small extension point that lets external internal-ballistics backends
(notably srm_1d's 1-D PISO transient solver) register themselves as
selectable solvers alongside openMotor's built-in quasi-steady solver. A
solver is any object exposing:

    name          : str   — registry key / GUI label
    capabilities  : dict  — descriptor (e.g. {'transient': True,
                             'axial_fields': True, 'needs_transport': True})
    simulate(motor, config=None, callback=None) -> SimulationResult

The quasi-steady solver is registered here by default so it always exists;
``motor.runSimulation`` remains the canonical QS entry point and is simply
wrapped. The GUI / simulation manager selects the active solver by name.
"""

_SOLVERS = {}

QUASI_STEADY = 'quasi-steady'


class SolverPlugin:
    """Base/protocol for a registrable solver. Subclasses set ``name`` and
    ``capabilities`` and implement ``simulate``."""

    name = 'unnamed'
    capabilities = {'transient': False, 'axial_fields': False}

    def simulate(self, motor, config=None, callback=None):
        raise NotImplementedError


def register_solver(solver):
    """Register a solver instance under its ``name``. Returns the solver."""
    _SOLVERS[solver.name] = solver
    return solver


def get_solver(name):
    """Return the registered solver for ``name``, or None."""
    return _SOLVERS.get(name)


def list_solvers():
    """Return the names of all registered solvers."""
    return list(_SOLVERS.keys())


class QuasiSteadySolver(SolverPlugin):
    """Wraps openMotor's built-in quasi-steady solver (``Motor.runSimulation``)."""

    name = QUASI_STEADY
    capabilities = {'transient': False, 'axial_fields': False,
                    'needs_transport': False}

    def simulate(self, motor, config=None, callback=None):
        return motor.runSimulation(callback)


register_solver(QuasiSteadySolver())
