"""Igniter submodule (v0.7.0 file format).

Adds a first-class igniter concept to openMotor, mirroring the propellant
data structure: a reusable ``Pyrogen`` material datasheet (the igniter
library item, analogous to ``Propellant``) plus an ``Igniter`` chamber
config (per-motor sizing / topology, analogous to a motor's grain set).

A motor's igniter is serialized as ``data.igniter`` = an embedded pyrogen
material + the chamber sizing, the same way ``data.propellant`` embeds a
propellant. The reusable materials live in a separate IGNITERS library.

Property keys deliberately match srm_1d's pyrogen datasheet field names
(``a``, ``n``, ``rho``, ``T_flame``, ``M``, ``gamma`` …) so the same dict
round-trips between openMotor and srm_1d's transient backend.

Sizing values use ``-1.0`` as the "auto" sentinel (the backend derives
mass via Sutton, throat via a Kn-design rule, etc.).
"""

from .properties import (
    PropertyCollection, FloatProperty, StringProperty, EnumProperty,
)


class Pyrogen(PropertyCollection):
    """An igniter pyrogen material datasheet (the reusable library item)."""

    def __init__(self, propDict=None):
        super().__init__()
        self.props['name'] = StringProperty('Name')
        self.props['a'] = FloatProperty('Burn rate Coefficient', 'm/(s*Pa^n)', 1e-9, 2)
        self.props['n'] = FloatProperty('Burn rate Exponent', '', -0.99, 0.99)
        self.props['rho'] = FloatProperty('Density', 'kg/m^3', 1, 10000)
        self.props['T_flame'] = FloatProperty('Flame Temperature', 'K', 1, 10000)
        self.props['M'] = FloatProperty('Molar Mass', 'kg/mol', 1e-6, 1)
        self.props['gamma'] = FloatProperty('Specific Heat Ratio', '', 1 + 1e-6, 10)
        self.props['impetus_W'] = FloatProperty('Impetus', 'psi*in^3/g', 0, 1e6)
        self.props['heat_flux_cal_cm2_s'] = FloatProperty('Heat Flux', 'cal/(cm^2*s)', 0, 1e5)
        self.props['kappa_jet'] = FloatProperty('Jet Decay Coefficient', '', 0, 100)
        self.props['form'] = EnumProperty('Form', ['pellets', 'powder', 'chunks'])
        self.props['particle_diameter_m'] = FloatProperty('Particle Diameter', 'm', 0, 1)
        self.props['particle_LD_ratio'] = FloatProperty('Particle L/D', '', 0, 1000)
        self.props['heat_delivery_mode'] = EnumProperty('Heat Delivery', ['demar', 'radiation', 'none'])
        self.props['pellet_emissivity'] = FloatProperty('Pellet Emissivity', '', 0, 1)
        self.props['radiation_absorption_length_m'] = FloatProperty('Radiation Absorption Length', 'm', 0, 1000)
        if propDict is not None:
            self.setProperties(propDict)


class Igniter(PropertyCollection):
    """Per-motor igniter chamber sizing / topology.

    Holds the chamber configuration only; the pyrogen material is embedded
    alongside it in the ``data.igniter`` block (under the ``pyrogen`` key).
    ``-1.0`` is the "auto" sentinel for the sizing fields the backend
    derives.
    """

    def __init__(self, propDict=None):
        super().__init__()
        self.props['mass'] = FloatProperty('Pyrogen Mass', 'kg', -1, 100)
        self.props['throat_area'] = FloatProperty('Throat Area', 'm^2', -1, 1)
        self.props['volume'] = FloatProperty('Volume', 'm^3', -1, 1)
        self.props['burn_area'] = FloatProperty('Burn Area', 'm^2', -1, 100)
        self.props['burn_law'] = EnumProperty('Burn Law', ['0d', 'end_burning'])
        self.props['injection_topology'] = EnumProperty(
            'Injection Topology', ['forward_plenum', 'head_basket', 'aft_basket'])
        self.props['cartridge_length_m'] = FloatProperty('Cartridge Length', 'm', -1, 100)
        self.props['basket_fill_fraction'] = FloatProperty('Basket Fill Fraction', '', 0, 1)
        self.props['pellet_packing_fraction'] = FloatProperty('Pellet Packing Fraction', '', 0, 1)
        if propDict is not None:
            self.setProperties(propDict)
