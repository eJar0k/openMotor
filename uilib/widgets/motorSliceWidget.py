"""Longitudinal motor-slice viewer (station-viz roadmap #2, Phase B/C).

A side-on 2-D axial cut of the whole motor: solid propellant is drawn from
the bore wall out to the casing (so the core widens as the web burns), and
the open bore is filled with a chosen flow field as a heatmap. Consumes the
``simResult.srm1d_axial`` payload (canonical srm_1d data contract):

    x_cell (n,), dx, D_outer, cell_segment_id (n,), cell_wall_web (n,),
    snap_times (f,), fields{name: (f, n)}   # incl. P/u/G/T/Mach/rho/D_port

The bore half-height is ``D_port/2`` — already the hydraulic-equivalent
radius the solver computes for FMM / non-circular grains, so the slice is
valid for every grain type (drawn as an equivalent circular port).

``renderMotorSlice`` is a pure matplotlib function (Qt-free) so it can be
rendered headless for verification; ``MotorSliceWidget`` wraps it.
"""
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

import motorlib

# Bore fields offered in the field dropdown: (payload-key, label, unit-cat).
SLICE_FIELDS = (
    ('P', 'Pressure', 'Pa'),
    ('G', 'Mass Flux', 'kg/(m^2*s)'),
    ('u', 'Velocity', 'm/s'),
    ('Mach', 'Mach Number', ''),
    ('T', 'Gas Temperature', 'K'),
    ('rho', 'Gas Density', 'kg/m^3'),
)

_PROPELLANT = '#c8c8c8'   # light grey solid propellant
_STROKE = '#555555'       # fine outline on the propellant (bore wall + end faces)
_CASING = '#202020'


def _edges_from_centers(centers, dx):
    """n cell-center positions -> n+1 edge positions (midpoints; ends ±dx/2)."""
    centers = np.asarray(centers, float)
    edges = np.empty(centers.size + 1)
    edges[1:-1] = 0.5 * (centers[:-1] + centers[1:])
    edges[0] = centers[0] - dx / 2.0
    edges[-1] = centers[-1] + dx / 2.0
    return edges


def _to_edge_values(vals):
    """Per-cell values -> values at n+1 edges (interior midpoints, ends held)."""
    vals = np.asarray(vals, float)
    out = np.empty(vals.size + 1)
    out[1:-1] = 0.5 * (vals[:-1] + vals[1:])
    out[0] = vals[0]
    out[-1] = vals[-1]
    return out


def renderMotorSlice(ax, axial, frame, field, *, fieldLabel='', fieldUnit='',
                     lengthScale=1.0, lengthLabel='m', cmap='viridis',
                     vmin=None, vmax=None, fieldScale=1.0, colorbar=True):
    """Draw the motor slice for ``frame`` on Axes ``ax``.

    Solid propellant fills R_bore..R_outer (mirrored); the bore is a
    pcolormesh of ``field`` over the tapering open core. Returns the QuadMesh.

    lengthScale/fieldScale convert SI payload values to display units
    (e.g. 1e3 for mm); ``vmin/vmax`` (in DISPLAY units) fix the color scale
    across frames (for animation) — default autoscales to this frame.
    """
    ax.clear()
    x = np.asarray(axial['x_cell'], float)
    dx = float(axial['dx'])
    R_outer = 0.5 * float(axial['D_outer'])
    seg = np.asarray(axial['cell_segment_id'])
    D_port = np.asarray(axial['fields']['D_port'][frame], float)
    fieldVals = np.asarray(axial['fields'][field][frame], float) * fieldScale

    # Bore half-height: hydraulic radius, clipped to the casing; non-grain
    # cells (gap/head/aft, seg<0) are open chamber (no solid).
    Rb = np.clip(0.5 * D_port, 0.0, R_outer)
    Rb[seg < 0] = R_outer

    xs = x * lengthScale
    dxs = dx * lengthScale
    Ro = R_outer * lengthScale
    Rbs = Rb * lengthScale

    edges = _edges_from_centers(xs, dxs)
    Rb_edge = np.clip(_to_edge_values(Rbs), 0.0, Ro)

    # Bore heatmap over the tapering open core (one row of quads in y).
    # Extend the mesh a hair past the bore wall (only where solid exists) so
    # the propellant fill (drawn over it) tucks down onto the color with no
    # white antialiasing seam between the two artists.
    eps = 0.004 * Ro
    Rb_mesh = np.where(Rb_edge < Ro - 1e-12, np.minimum(Rb_edge + eps, Ro), Rb_edge)
    Xe = np.tile(edges, (2, 1))
    Ye = np.vstack([-Rb_mesh, Rb_mesh])
    C = fieldVals.reshape(1, -1)
    mesh = ax.pcolormesh(Xe, Ye, C, cmap=cmap, shading='flat',
                         vmin=vmin, vmax=vmax)

    # Solid propellant (web) above and below the bore. A fine edge stroke
    # outlines each grain block (bore wall + end faces); fill_between makes a
    # separate polygon per contiguous grain, so gaps break the outline
    # automatically. Zero-thickness in open-chamber cells -> nothing drawn.
    ax.fill_between(edges, Rb_edge, Ro, color=_PROPELLANT,
                    edgecolor=_STROKE, linewidth=0.6, zorder=2)
    ax.fill_between(edges, -Ro, -Rb_edge, color=_PROPELLANT,
                    edgecolor=_STROKE, linewidth=0.6, zorder=2)

    # Casing walls.
    ax.plot([edges[0], edges[-1]], [Ro, Ro], color=_CASING, lw=1.2, zorder=3)
    ax.plot([edges[0], edges[-1]], [-Ro, -Ro], color=_CASING, lw=1.2, zorder=3)

    ax.set_xlim(edges[0], edges[-1])
    ax.set_ylim(-Ro * 1.02, Ro * 1.02)
    ax.set_aspect('auto')        # auto-stretch radial to fill the pane
    ax.set_xlabel('Axial position - {}'.format(lengthLabel))
    ax.set_ylabel('Radius - {}'.format(lengthLabel))
    t = float(axial['snap_times'][frame])
    ax.set_title('Motor slice @ t = {:.3f} s'.format(t), fontsize='medium')

    if colorbar:
        suffix = ' ({})'.format(fieldUnit) if fieldUnit else ''
        cb = ax.figure.colorbar(mesh, ax=ax, fraction=0.046, pad=0.02)
        cb.set_label('{}{}'.format(fieldLabel or field, suffix))
    return mesh


class MotorSliceWidget(FigureCanvas):
    """Canvas + field dropdown for the longitudinal slice. The frame index is
    driven externally (the Grains-tab time slider) via :meth:`setFrame`."""

    def __init__(self, parent=None):
        super().__init__(Figure())
        self.setParent(parent)
        self.preferences = None
        self.axial = None
        self.frame = 0
        self._field = SLICE_FIELDS[0][0]
        self.figure = self.figure  # FigureCanvas already holds one
        self.ax = self.figure.add_subplot(111)
        self._cb = None

    def setPreferences(self, pref):
        self.preferences = pref

    def setField(self, key):
        self._field = key
        self.redraw()

    def setFrame(self, frame):
        if self.axial is None:
            return
        self.frame = int(np.clip(frame, 0, self.axial['snap_times'].shape[0] - 1))
        self.redraw()

    def setData(self, axial):
        """Attach a station-viz axial payload (or None to clear)."""
        self.axial = axial
        self.frame = 0
        self.redraw()

    def _displayUnits(self, fromUnit):
        if self.preferences is None:
            return fromUnit, 1.0
        toUnit = self.preferences.getUnit(fromUnit) if fromUnit else ''
        if not fromUnit:
            return '', 1.0
        scale = motorlib.units.convert(1.0, fromUnit, toUnit) if toUnit else 1.0
        return toUnit, scale

    def redraw(self):
        self.figure.clear()
        self.ax = self.figure.add_subplot(111)
        if self.axial is None or float(self.axial.get('D_outer', 0.0)) <= 0.0:
            self.ax.text(0.5, 0.5, 'No motor-slice data', ha='center',
                         va='center', transform=self.ax.transAxes)
            self.draw()
            return
        label = dict((k, l) for k, l, _u in SLICE_FIELDS).get(self._field, self._field)
        fromUnit = dict((k, u) for k, _l, u in SLICE_FIELDS).get(self._field, '')
        lenUnit, lenScale = self._displayUnits('m')
        fUnit, fScale = self._displayUnits(fromUnit)
        renderMotorSlice(
            self.ax, self.axial, self.frame, self._field,
            fieldLabel=label, fieldUnit=fUnit, lengthScale=lenScale,
            lengthLabel=lenUnit, fieldScale=fScale)
        self.figure.tight_layout()
        self.draw()
