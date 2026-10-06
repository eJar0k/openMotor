"""Shared controller for the solver-aware config screens (v0.8.0).

Both the global Preferences -> General screen and the per-motor Config editor
present the same layout: a solver selector that swaps a 'Shared settings'
section (the same MotorConfig fields for every solver) plus a solver-specific
section (the quasi-steady solver's remaining MotorConfig fields, or a plugin
solver's own schema). This controller builds the editable collections from a
source ``MotorConfig`` + saved per-solver values and renders them into any
``CollectionEditor`` via ``loadGrouped``, so the two screens stay in sync
without duplicating the logic.
"""

from motorlib import solvers
from motorlib.igniter import chamber_collection, changed_values
from motorlib.motor import MotorConfig
from motorlib.properties import PropertyCollection


# MotorConfig fields shown in the 'Shared settings' section of every solver
# pane (same underlying values). The rest are quasi-steady-specific.
SHARED_CONFIG_KEYS = [
    'maxPressure', 'maxMassFlux', 'maxMachNumber', 'minPortThroat',
    'ambPressure', 'mapDim',
]


def _subset(collection, keys):
    """A PropertyCollection viewing a subset of ``collection``'s props by key
    (same Property objects, so edits write through to the source)."""
    sub = PropertyCollection()
    sub.props = {k: collection.props[k] for k in keys if k in collection.props}
    return sub


class SolverConfigController:
    """Owns the editable config collections for one config screen and drives a
    target ``CollectionEditor``.

    Parameters
    ----------
    editor : CollectionEditor
        The editor widget to render the grouped sections into.
    generalSource : MotorConfig
        The source config (``Preferences.general`` or ``motor.config``); copied
        so edits aren't committed until :meth:`extract` is read on Apply.
    solverConfigsValues : dict
        Saved per-solver value dicts (``Preferences.solverConfigs`` or
        ``motor.solverConfigs``), keyed by solver name.
    """

    def __init__(self, editor, generalSource, solverConfigsValues,
                 withIgniter=False, igniterBlock=None):
        self.editor = editor
        self.generalCopy = MotorConfig()
        self.generalCopy.setProperties(generalSource.getProperties())
        self.sharedColl = _subset(self.generalCopy, SHARED_CONFIG_KEYS)

        # Per-motor igniter chamber (igniter provider only): a working copy,
        # built from the provider's chamber schema, edited as an extra section
        # under the igniter-capable solver. None on the global Preferences
        # screen (igniter is per-motor) or when no provider is registered.
        # ``igniterBlock`` is the motor's raw ``data.igniter`` dict (None = no
        # block yet -> the provider's default is shown). D4: only keys the
        # user changes are reported (``igniterProps``); the rest of the raw
        # block is never rewritten.
        self.igniterCopy = None
        self._igniterSnapshot = {}      # collection values right after loading
        self._widgetBaseline = {}       # widget values right after rendering
        if withIgniter:
            provider = solvers.get_igniter_provider()
            if igniterBlock is None and provider is not None:
                igniterBlock = provider.get_default_igniter()
            self.igniterCopy = chamber_collection(igniterBlock)
            if self.igniterCopy is not None:
                self._igniterSnapshot = self.igniterCopy.getProperties()

        self.specificColls = {}
        self.generalName = solvers.QUASI_STEADY
        for name in solvers.list_solvers():
            schema = solvers.get_solver(name).get_config_schema()
            if schema is None:                       # uses the global config
                self.generalName = name
                qs_keys = [k for k in self.generalCopy.props
                           if k not in SHARED_CONFIG_KEYS]
                self.specificColls[name] = _subset(self.generalCopy, qs_keys)
            else:                                    # solver-specific schema
                schema.setProperties(solverConfigsValues.get(name, {}))
                self.specificColls[name] = schema
        self.current = None

    def solverNames(self):
        return list(self.specificColls.keys())

    def usesIgniter(self, name):
        solver = solvers.get_solver(name)
        return bool(self.igniterCopy is not None and solver
                    and solver.capabilities.get('igniter'))

    def show(self, name):
        """Render the shared + solver-specific (+ igniter) sections for
        ``name``."""
        if not name or name not in self.specificColls:
            return
        self.save()
        self.current = name
        groups = [
            ('Shared settings', self.sharedColl),
            ('{} settings'.format(name), self.specificColls[name]),
        ]
        if self.usesIgniter(name):
            groups.append(('Igniter chamber', self.igniterCopy))
        self.editor.loadGrouped(groups)

    def save(self):
        """Persist the visible page's edits into the in-memory collections."""
        if self.current is None:
            return
        values = self.editor.getProperties()
        self.sharedColl.setProperties(values)
        self.specificColls[self.current].setProperties(values)
        if self.usesIgniter(self.current):
            # Only widget values that moved since the page was rendered are
            # edits; the rest keep their exact loaded value (the widgets round
            # through display units and rounding, which must not leak into
            # untouched keys).
            keys = self.igniterCopy.props
            moved = changed_values(
                self._widgetBaseline, {k: v for k, v in values.items()
                                       if k in keys})
            self.igniterCopy.setProperties(moved)

    def captureWidgetBaseline(self):
        """Record the igniter-chamber widget values of the freshly rendered
        page. Call once the page is fully built (after any widget tweaks such
        as the 'auto' sentinel display)."""
        if self.igniterCopy is not None and self.current is not None:
            vals = self.editor.getProperties()
            self._widgetBaseline = {k: v for k, v in vals.items()
                                    if k in self.igniterCopy.props}

    def igniterProps(self):
        """The igniter-chamber values the user changed, vs the loaded block
        ({} when none / no igniter)."""
        if self.igniterCopy is None:
            return {}
        return changed_values(self._igniterSnapshot, self.igniterCopy)

    def extract(self):
        """Return ``(general_dict, solver_configs_dict)`` for persisting."""
        self.save()
        general = self.generalCopy.getProperties()
        solverConfigs = {name: coll.getProperties()
                         for name, coll in self.specificColls.items()
                         if name != self.generalName}
        return general, solverConfigs
