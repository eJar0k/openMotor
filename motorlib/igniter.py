"""Igniter helpers (plugin-provided igniter).

The igniter MODEL is owned by the solver plugin that consumes it (srm_1d's
transient solver today): the material fields, the chamber-sizing fields, their
GUI metadata (labels / units / ranges / enum choices), the built-in material
library, and the history of superseded library values all come from the
provider solver's optional ``get_igniter_*`` hooks (see
``motorlib.solvers.SolverPlugin`` / ``get_igniter_provider``). This module
hardcodes none of it.

A motor stores its igniter as a RAW dict (``Motor.igniterData`` ==
``data.igniter``: chamber-sizing keys + a nested ``pyrogen`` material dict) so
a load/save round trip is lossless even for keys the GUI schema does not know,
``None`` values, or values outside a schema range (``FloatProperty.setValue``
silently drops out-of-range values and raises on ``None``).

GUI editors work on a schema ``PropertyCollection`` built from the raw dict
and write back ONLY what the user changed: snapshot the values right after
loading, then merge just the keys whose value differs (``changed_values``).

Sizing values use ``-1.0`` as the "auto" sentinel (the backend derives
mass via Sutton, throat via a Kn-design rule, etc.).
"""

import copy

from . import solvers
from .properties import StringProperty


def _populate(collection, values):
    """Load ``values`` (dict) into ``collection``, skipping ``None`` values
    (a ``None`` would raise in ``FloatProperty.setValue``); out-of-range
    values are dropped by the property itself and stay at its default.
    String properties with no value are given ``''`` so editors can show them."""
    collection.setProperties({k: v for k, v in (values or {}).items()
                              if v is not None})
    for prop in collection.props.values():
        if isinstance(prop, StringProperty) and prop.value is None:
            prop.value = ''
    return collection


def material_collection(values):
    """The provider's material schema populated from a material dict, or
    ``None`` if there is no igniter provider."""
    provider = solvers.get_igniter_provider()
    schema = provider.get_igniter_material_schema() if provider else None
    return None if schema is None else _populate(schema, values)


def chamber_collection(values):
    """The provider's chamber schema populated from an ``igniter`` block (the
    nested ``pyrogen`` and any unknown keys are ignored), or ``None`` if there
    is no igniter provider."""
    provider = solvers.get_igniter_provider()
    schema = provider.get_igniter_chamber_schema() if provider else None
    return None if schema is None else _populate(schema, values)


def changed_values(snapshot, current):
    """``{key: value}`` for every key of ``current`` (a dict or a
    ``PropertyCollection``) whose value differs from ``snapshot[key]`` (a
    dict, typically ``collection.getProperties()`` taken right after
    loading). Keys absent from the snapshot count as changed."""
    if hasattr(current, 'getProperties'):
        current = current.getProperties()
    return {k: v for k, v in current.items()
            if k not in snapshot or snapshot[k] != v}


def merge_edits(block, material=None, chamberChanges=None):
    """Return a new ``data.igniter`` block: ``block`` (``None`` -> the
    provider's default block, or ``None`` if there is no provider) with
    ``material`` (a full material dict, e.g. a library pick) deep-copied into
    ``['pyrogen']`` and ``chamberChanges`` merged over the top. Keys not named
    are untouched."""
    if block is None:
        provider = solvers.get_igniter_provider()
        block = provider.get_default_igniter() if provider else None
        if block is None:
            return None
    block = copy.deepcopy(block)
    if material is not None:
        block['pyrogen'] = copy.deepcopy(material)
    if chamberChanges:
        block.update(chamberChanges)
    return block
