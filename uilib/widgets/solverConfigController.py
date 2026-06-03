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

    def __init__(self, editor, generalSource, solverConfigsValues):
        self.editor = editor
        self.generalCopy = MotorConfig()
        self.generalCopy.setProperties(generalSource.getProperties())
        self.sharedColl = _subset(self.generalCopy, SHARED_CONFIG_KEYS)

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

    def show(self, name):
        """Render the shared + solver-specific sections for ``name``."""
        if not name or name not in self.specificColls:
            return
        self.save()
        self.current = name
        self.editor.loadGrouped([
            ('Shared settings', self.sharedColl),
            ('{} settings'.format(name), self.specificColls[name]),
        ])

    def save(self):
        """Persist the visible page's edits into the in-memory collections."""
        if self.current is None:
            return
        values = self.editor.getProperties()
        self.sharedColl.setProperties(values)
        self.specificColls[self.current].setProperties(values)

    def extract(self):
        """Return ``(general_dict, solver_configs_dict)`` for persisting."""
        self.save()
        general = self.generalCopy.getProperties()
        solverConfigs = {name: coll.getProperties()
                         for name, coll in self.specificColls.items()
                         if name != self.generalName}
        return general, solverConfigs
