"""Longitudinal motor-slice viewer (station-viz roadmap #2).

A side-on 2-D axial cut of the whole motor: solid propellant is drawn from
the bore wall out to the casing (so the core widens as the web burns), and
the open bore is filled with a chosen flow field as a heatmap. Consumes the
``simResult.srm1d_axial`` payload (canonical srm_1d data contract):

    x_cell (n,), dx, D_outer, cell_segment_id (n,), cell_wall_web (n,),
    snap_times (f,), fields{name: (f, n)}   # incl. P/u/G/T/Mach/rho/D_port

The bore half-height is ``D_port/2`` — already the hydraulic-equivalent
radius the solver computes for FMM / non-circular grains, so the slice is
valid for every grain type (drawn as an equivalent circular port).

The color scale is PINNED to each field's global min/max across all frames
(so a quantity is comparable as you scrub). Scrubbing is incremental: the
axes + colorbar are built once per field, and only the bore mesh + the
propellant polygons are swapped per frame. A mouseover reports the hovered
cell's value (bore field, or %web over the solid).

``renderMotorSlice`` is a pure matplotlib function (Qt-free) for headless
rendering / previews; ``MotorSliceWidget`` wraps the interactive path.
"""
import numpy as np
import matplotlib.cm as cm
from matplotlib.colors import Normalize
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
_CMAP = 'viridis'


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


def _bore_geometry(axial, frame, lengthScale):
    """Return display-unit (edges, R_outer, Rb_edge, Rb_mesh) for ``frame``.

    Rb_edge is the bore wall at cell edges; Rb_mesh extends a hair past it
    (only where solid exists) so the propellant fill tucks onto the color
    with no white seam.
    """
    x = np.asarray(axial['x_cell'], float)
    dx = float(axial['dx'])
    R_outer = 0.5 * float(axial['D_outer'])
    seg = np.asarray(axial['cell_segment_id'])
    D_port = np.asarray(axial['fields']['D_port'][frame], float)

    Rb = np.clip(0.5 * D_port, 0.0, R_outer)
    Rb[seg < 0] = R_outer        # non-grain cells: open chamber, no solid

    Ro = R_outer * lengthScale
    edges = _edges_from_centers(x * lengthScale, dx * lengthScale)
    Rb_edge = np.clip(_to_edge_values(Rb * lengthScale), 0.0, Ro)
    eps = 0.004 * Ro
    Rb_mesh = np.where(Rb_edge < Ro - 1e-12, np.minimum(Rb_edge + eps, Ro), Rb_edge)
    return edges, Ro, Rb_edge, Rb_mesh


def _draw_frame_artists(ax, axial, frame, field, *, cmap, norm,
                        lengthScale=1.0, fieldScale=1.0):
    """Draw the per-frame artists (bore mesh + mirrored propellant fills).

    Returns ``(mesh, fillTop, fillBot)`` so a caller can ``.remove()`` them
    on the next frame (the incremental scrub path).
    """
    edges, Ro, Rb_edge, Rb_mesh = _bore_geometry(axial, frame, lengthScale)
    fieldVals = np.asarray(axial['fields'][field][frame], float) * fieldScale

    Xe = np.tile(edges, (2, 1))
    Ye = np.vstack([-Rb_mesh, Rb_mesh])
    mesh = ax.pcolormesh(Xe, Ye, fieldVals.reshape(1, -1), cmap=cmap, norm=norm,
                         shading='flat', zorder=1)
    fillTop = ax.fill_between(edges, Rb_edge, Ro, color=_PROPELLANT,
                              edgecolor=_STROKE, linewidth=0.6, zorder=2)
    fillBot = ax.fill_between(edges, -Ro, -Rb_edge, color=_PROPELLANT,
                              edgecolor=_STROKE, linewidth=0.6, zorder=2)
    return mesh, fillTop, fillBot


def _style_axes(ax, edges, Ro, lengthLabel):
    ax.plot([edges[0], edges[-1]], [Ro, Ro], color=_CASING, lw=1.2, zorder=3)
    ax.plot([edges[0], edges[-1]], [-Ro, -Ro], color=_CASING, lw=1.2, zorder=3)
    ax.set_xlim(edges[0], edges[-1])
    ax.set_ylim(-Ro * 1.02, Ro * 1.02)
    ax.set_aspect('auto')
    ax.set_xlabel('Axial position - {}'.format(lengthLabel))
    ax.set_ylabel('Radius - {}'.format(lengthLabel))


def renderMotorSlice(ax, axial, frame, field, *, fieldLabel='', fieldUnit='',
                     lengthScale=1.0, lengthLabel='m', cmap=_CMAP,
                     vmin=None, vmax=None, fieldScale=1.0, colorbar=True):
    """Full one-shot render on Axes ``ax`` (headless previews / tests)."""
    ax.clear()
    norm = Normalize(vmin=vmin, vmax=vmax) if (vmin is not None and vmax is not None) else None
    mesh, _, _ = _draw_frame_artists(ax, axial, frame, field, cmap=cmap, norm=norm,
                                     lengthScale=lengthScale, fieldScale=fieldScale)
    edges, Ro, _, _ = _bore_geometry(axial, frame, lengthScale)
    _style_axes(ax, edges, Ro, lengthLabel)
    ax.set_title('Motor slice @ t = {:.3f} s'.format(float(axial['snap_times'][frame])),
                 fontsize='medium')
    if colorbar:
        suffix = ' ({})'.format(fieldUnit) if fieldUnit else ''
        cb = ax.figure.colorbar(mesh, ax=ax, fraction=0.046, pad=0.02)
        cb.set_label('{}{}'.format(fieldLabel or field, suffix))
    return mesh


class MotorSliceWidget(FigureCanvas):
    """Canvas for the longitudinal slice. The frame index is driven externally
    (the Grains-tab time slider) via :meth:`setFrame`; the field via
    :meth:`setField`. Color scale is pinned per field across all frames."""

    def __init__(self, parent=None):
        super().__init__(Figure())
        self.setParent(parent)
        self.preferences = None
        self.axial = None
        self.frame = 0
        self._field = SLICE_FIELDS[0][0]
        self.ax = None
        self._cb = None
        self._artists = ()          # (mesh, fillTop, fillBot) for the current frame
        self._hover = None
        self._norm = None
        self._range_cache = {}      # field -> (vmin, vmax) in display units
        self._lenScale = 1.0
        self._lenUnit = 'm'
        self._fieldScale = 1.0
        self._fieldUnit = ''
        self.mpl_connect('motion_notify_event', self._onHover)

    def setPreferences(self, pref):
        self.preferences = pref

    def setField(self, key):
        if key != self._field:
            self._field = key
            self._rebuildStatic()
            self._drawFrame()

    def setFrame(self, frame):
        if self.axial is None:
            return
        self.frame = int(np.clip(frame, 0, self.axial['snap_times'].shape[0] - 1))
        self._drawFrame()

    def setData(self, axial):
        """Attach a station-viz axial payload (or None to clear)."""
        self.axial = axial
        self.frame = 0
        self._range_cache = {}
        self._rebuildStatic()
        self._drawFrame()

    # -- units -----------------------------------------------------------
    def _displayUnits(self, fromUnit):
        if self.preferences is None or not fromUnit:
            return fromUnit, 1.0
        toUnit = self.preferences.getUnit(fromUnit)
        scale = motorlib.units.convert(1.0, fromUnit, toUnit) if toUnit else 1.0
        return toUnit, scale

    def _fieldRange(self, field, fieldScale):
        """Global (vmin, vmax) for a field across ALL frames, in display units
        (cached). Pinning the scale here keeps a quantity comparable while
        scrubbing and lets the colorbar live for the field's lifetime."""
        if field not in self._range_cache:
            allv = np.asarray(self.axial['fields'][field], float) * fieldScale
            vmin, vmax = float(np.nanmin(allv)), float(np.nanmax(allv))
            if vmin == vmax:
                vmax = vmin + 1e-9
            self._range_cache[field] = (vmin, vmax)
        return self._range_cache[field]

    # -- rendering -------------------------------------------------------
    def _rebuildStatic(self):
        """Build the axes + (pinned) colorbar once per field/data change."""
        self.figure.clear()
        self._artists = ()
        self.ax = self.figure.add_subplot(111)
        if self.axial is None or float(self.axial.get('D_outer', 0.0)) <= 0.0:
            self.ax.text(0.5, 0.5, 'No motor-slice data', ha='center',
                         va='center', transform=self.ax.transAxes)
            self._hover = None
            self.draw_idle()
            return

        label = dict((k, l) for k, l, _u in SLICE_FIELDS).get(self._field, self._field)
        fromUnit = dict((k, u) for k, _l, u in SLICE_FIELDS).get(self._field, '')
        self._lenUnit, self._lenScale = self._displayUnits('m')
        self._fieldUnit, self._fieldScale = self._displayUnits(fromUnit)

        vmin, vmax = self._fieldRange(self._field, self._fieldScale)
        self._norm = Normalize(vmin=vmin, vmax=vmax)

        edges, Ro, _, _ = _bore_geometry(self.axial, self.frame, self._lenScale)
        _style_axes(self.ax, edges, Ro, self._lenUnit)

        sm = cm.ScalarMappable(norm=self._norm, cmap=_CMAP)
        sm.set_array([])
        self._cb = self.figure.colorbar(sm, ax=self.ax, fraction=0.046, pad=0.02)
        suffix = ' ({})'.format(self._fieldUnit) if self._fieldUnit else ''
        self._cb.set_label('{}{}'.format(label, suffix))

        self._hover = self.ax.text(
            0.01, 0.98, '', transform=self.ax.transAxes, ha='left', va='top',
            fontsize='small', zorder=5, visible=False,
            bbox=dict(boxstyle='round', fc='white', ec='0.6', alpha=0.85))
        try:
            self.figure.tight_layout()
        except Exception:
            pass

    def _drawFrame(self):
        if self.ax is None or self.axial is None or self._norm is None:
            return
        for art in self._artists:
            try:
                art.remove()
            except Exception:
                pass
        self._artists = _draw_frame_artists(
            self.ax, self.axial, self.frame, self._field, cmap=_CMAP,
            norm=self._norm, lengthScale=self._lenScale, fieldScale=self._fieldScale)
        self.ax.set_title('t = {:.3f} s'.format(
            float(self.axial['snap_times'][self.frame])), fontsize='medium')
        self.draw_idle()

    # -- mouseover readout ----------------------------------------------
    def _onHover(self, event):
        if self._hover is None:
            return
        if event.inaxes is not self.ax or event.xdata is None or self.axial is None:
            if self._hover.get_visible():
                self._hover.set_visible(False)
                self.draw_idle()
            return
        x = np.asarray(self.axial['x_cell'], float) * self._lenScale
        i = int(np.argmin(np.abs(x - event.xdata)))
        edges, Ro, Rb_edge, _ = _bore_geometry(self.axial, self.frame, self._lenScale)
        Rb_cell = 0.5 * (Rb_edge[i] + Rb_edge[i + 1])
        label = dict((k, l) for k, l, _u in SLICE_FIELDS).get(self._field, self._field)
        xmm = x[i]
        if abs(event.ydata) <= Rb_cell:                # over the bore
            val = float(self.axial['fields'][self._field][self.frame][i]) * self._fieldScale
            u = ' {}'.format(self._fieldUnit) if self._fieldUnit else ''
            txt = 'cell {}  x={:.1f} {}\n{} = {:.4g}{}'.format(
                i, xmm, self._lenUnit, label, val, u)
        elif abs(event.ydata) <= Ro:                   # over the solid web
            web = self.axial.get('cell_wall_web')
            seg = np.asarray(self.axial['cell_segment_id'])
            if web is not None and i < len(web) and web[i] > 0 and seg[i] >= 0:
                reg = float(self.axial['fields']['regress'][self.frame][i])
                pct = max(0.0, min(1.0, 1.0 - reg / float(web[i]))) * 100.0
                txt = 'cell {}  x={:.1f} {}\npropellant · web {:.0f}%'.format(
                    i, xmm, self._lenUnit, pct)
            else:
                txt = 'cell {}  x={:.1f} {}'.format(i, xmm, self._lenUnit)
        else:
            if self._hover.get_visible():
                self._hover.set_visible(False)
                self.draw_idle()
            return
        self._hover.set_text(txt)
        self._hover.set_visible(True)
        self.draw_idle()
