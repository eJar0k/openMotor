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

    def get_config_schema(self):
        """Return a ``PropertyCollection`` describing this solver's tunable
        run parameters, or ``None`` if the solver uses only the standard
        global ``MotorConfig`` (Preferences -> General). The GUI renders this
        schema as the solver's config page; the collected values are passed
        back to :meth:`simulate` as the ``config`` dict. Default: ``None``."""
        return None

    def upgrade_solver_config(self, values):
        """Return ``(new_values, upgraded_keys)`` for a saved run-config dict
        (the dict this solver's config schema collects): untouched superseded
        defaults replaced by the current ones, everything else left alone.
        Must not mutate the input. Default: passthrough."""
        return values, []

    # ---- optional igniter hooks (plugin-provided igniter) ----------------
    # A solver that consumes an igniter (``capabilities['igniter']``) owns the
    # igniter model: the fork hardcodes none of it. Base-class defaults mean
    # "no igniter".

    def get_igniter_material_schema(self):
        """A FRESH ``PropertyCollection`` describing one igniter material
        (``data.igniter.pyrogen``), or ``None``."""
        return None

    def get_igniter_chamber_schema(self):
        """A FRESH ``PropertyCollection`` describing the per-motor igniter
        chamber sizing (the rest of ``data.igniter``), or ``None``."""
        return None

    def get_igniter_materials(self):
        """The plugin's built-in material library: ``list[dict]`` of
        ``data.igniter.pyrogen`` dicts."""
        return []

    def get_default_igniter(self):
        """A default ``data.igniter`` block (``dict``), or ``None``."""
        return None

    def upgrade_igniter_block(self, block):
        """Return ``(block, changed)``: ``block`` with superseded library
        values replaced by the plugin's current ones. Must not mutate the
        input. Default: passthrough."""
        return block, False


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


def upgrade_solver_configs(configs):
    """Apply each registered solver's ``upgrade_solver_config`` to its saved
    run-config in ``configs`` (``{solver name: values dict}``). Returns
    ``(new_configs, upgraded)`` where ``upgraded`` maps a solver name to the
    list of keys it upgraded (empty when nothing changed). The input is not
    mutated; entries for unknown solvers pass through untouched."""
    new, upgraded = {}, {}
    for name, values in (configs or {}).items():
        solver = _SOLVERS.get(name)
        if solver is None or not isinstance(values, dict):
            new[name] = values
            continue
        new[name], keys = solver.upgrade_solver_config(values)
        if keys:
            upgraded[name] = list(keys)
    return new, upgraded


def get_igniter_provider():
    """The first registered solver whose ``capabilities['igniter']`` is truthy
    (it owns the igniter model), else ``None``."""
    for solver in _SOLVERS.values():
        if solver.capabilities.get('igniter'):
            return solver
    return None


def discover_external_solvers():
    """Best-effort import of external solver plugins so they self-register.

    The srm_1d transient backend lives in a sibling checkout and registers
    itself on import (``import srm_1d.srm1d_plugin``). This tries that import
    directly, then — if srm_1d isn't already importable — locates the sibling
    ``srm_1d`` package (mirroring how srm_1d locates the openMotor checkout)
    and retries. All failures are swallowed: openMotor runs fine with only
    the built-in quasi-steady solver if the plugin or its heavy deps (numba,
    scikit-fmm) are absent. Returns the list of solver names registered after
    discovery. Idempotent — safe to call once at startup."""
    import os
    import sys
    import importlib

    def _try_import():
        try:
            importlib.import_module('srm_1d.srm1d_plugin')
            return True
        except Exception:
            return False

    if not _try_import():
        # Allow an explicit override, else walk up from this file looking for
        # a checkout laid out as ``<root>/srm_1d/srm_1d/srm1d_plugin.py`` and
        # put ``<root>/srm_1d`` (the package parent) on sys.path.
        candidates = []
        env = os.environ.get('OPENMOTOR_SRM1D_PATH')
        if env:
            candidates.append(env)
        here = os.path.dirname(os.path.abspath(__file__))
        cur = here
        for _ in range(6):
            cur = os.path.dirname(cur)
            candidates.append(os.path.join(cur, 'srm_1d'))
        for cand in candidates:
            if cand and os.path.isfile(
                    os.path.join(cand, 'srm_1d', 'srm1d_plugin.py')):
                if cand not in sys.path:
                    sys.path.insert(0, cand)
                _try_import()
                break

    return list_solvers()


class QuasiSteadySolver(SolverPlugin):
    """Wraps openMotor's built-in quasi-steady solver (``Motor.runSimulation``)."""

    name = QUASI_STEADY
    capabilities = {'transient': False, 'axial_fields': False,
                    'needs_transport': False}

    def simulate(self, motor, config=None, callback=None):
        return motor.runSimulation(callback)


register_solver(QuasiSteadySolver())
