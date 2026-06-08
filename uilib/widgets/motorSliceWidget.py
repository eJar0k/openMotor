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
from PyQt6.QtWidgets import QApplication

import motorlib


def _themeColors():
    """High-contrast readout colors matched to openMotor's light/dark theme
    (mirrors the isDarkMode() convention used by the grain/preview widgets)."""
    app = QApplication.instance()
    dark = bool(app and app.isDarkMode())
    if dark:
        return {'fg': '#ececec', 'bg': '#232323', 'ec': '#9a9a9a'}
    return {'fg': '#101010', 'bg': '#ffffff', 'ec': '#202020'}

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

_ACCENT = '#ff5252'       # station marker line/band/border
_LABEL_BG = '#d9d9d9'     # oM-style light grey station-label background
_LABEL_FG = '#1a1a1a'     # dark label text (high contrast on the light-grey box)


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
    """Display-unit (edges, R_outer, Rb_edge) for ``frame``. Rb_edge is the
    per-cell bore wall at cell edges (open chamber where no grain) — used by
    the hover region test."""
    x = np.asarray(axial['x_cell'], float)
    dx = float(axial['dx'])
    R_outer = 0.5 * float(axial['D_outer'])
    seg = np.asarray(axial['cell_segment_id'])
    D_port = np.asarray(axial['fields']['D_port'][frame], float)
    Rb = np.clip(0.5 * D_port, 0.0, R_outer)
    Rb[seg < 0] = R_outer
    Ro = R_outer * lengthScale
    edges = _edges_from_centers(x * lengthScale, dx * lengthScale)
    Rb_edge = np.clip(_to_edge_values(Rb * lengthScale), 0.0, Ro)
    return edges, Ro, Rb_edge


def _draw_frame_artists(ax, axial, frame, field, *, cmap, norm,
                        lengthScale=1.0, fieldScale=1.0):
    """Draw the per-frame artists and return them (so the scrub path can
    ``.remove()`` them next frame).

    The bore heatmap is a FULL-HEIGHT pcolormesh (±R_outer); the grey solid
    propellant is then drawn OVER it. The solid is drawn per SEGMENT over its
    live axial extent [x_fwd, x_aft] = [seg_x_start + fwd_reg, seg_x_start +
    seg_length - aft_reg], so end-face burnback recedes the faces CONTINUOUSLY
    (sub-cell, no whole-cell snapping) and each segment is a single polygon
    (clean outline stroke, no per-cell grid lines). Where there's no solid
    (gaps / consumed faces) the full-height field color shows = open chamber.
    """
    x = np.asarray(axial['x_cell'], float) * lengthScale
    dx = float(axial['dx']) * lengthScale
    Ro = 0.5 * float(axial['D_outer']) * lengthScale
    edges = _edges_from_centers(x, dx)
    fieldVals = np.asarray(axial['fields'][field][frame], float) * fieldScale

    Xe = np.tile(edges, (2, 1))
    Ye = np.vstack([np.full(edges.size, -Ro), np.full(edges.size, Ro)])
    mesh = ax.pcolormesh(Xe, Ye, fieldVals.reshape(1, -1), cmap=cmap, norm=norm,
                         shading='flat', zorder=1)
    artists = [mesh]

    D_port = np.asarray(axial['fields']['D_port'][frame], float)
    Rb_cell = np.clip(0.5 * D_port * lengthScale, 0.0, Ro)

    def _solid(xseg, rb):
        artists.append(ax.fill_between(xseg, rb, Ro, color=_PROPELLANT,
                                       edgecolor=_STROKE, linewidth=0.6, zorder=2))
        artists.append(ax.fill_between(xseg, -Ro, -rb, color=_PROPELLANT,
                                       edgecolor=_STROKE, linewidth=0.6, zorder=2))

    sg = axial.get('seg_geom')
    if sg is not None and len(sg.get('seg_x_start', ())):
        x0 = np.asarray(sg['seg_x_start'], float)
        L = np.asarray(sg['seg_length'], float)
        fr = np.asarray(sg['seg_fwd_reg'])[frame]
        ar = np.asarray(sg['seg_aft_reg'])[frame]
        for k in range(x0.size):
            x_fwd = (x0[k] + fr[k]) * lengthScale
            x_aft = (x0[k] + L[k] - ar[k]) * lengthScale
            if x_aft - x_fwd <= 1e-9:
                continue                         # segment fully consumed
            inside = np.where((x >= x_fwd) & (x <= x_aft))[0]
            if inside.size == 0:
                continue                         # sub-cell segment (deferred)
            xseg = np.concatenate([[x_fwd], x[inside], [x_aft]])
            rb = np.concatenate([[Rb_cell[inside[0]]], Rb_cell[inside],
                                 [Rb_cell[inside[-1]]]])
            _solid(xseg, rb)
    else:
        # Fallback (results without seg_geom): static cell map, radial only.
        seg = np.asarray(axial['cell_segment_id'])
        Rb = Rb_cell.copy()
        Rb[seg < 0] = Ro
        _solid(edges, np.clip(_to_edge_values(Rb), 0.0, Ro))
    return tuple(artists)


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
    mesh = _draw_frame_artists(ax, axial, frame, field, cmap=cmap, norm=norm,
                               lengthScale=lengthScale, fieldScale=fieldScale)[0]
    edges, Ro, _ = _bore_geometry(axial, frame, lengthScale)
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
        self._stations = []          # selected stations to highlight
        self._markers = []           # station marker artists (band+line+label)
        self._stationsVisible = True # master station-marker toggle
        self._labelsVisible = True   # station-label sub-toggle
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

    def setStations(self, stations):
        """Set the active stations to highlight on the slice (cell_index +
        label). Markers are at fixed x, so this is independent of the frame."""
        self._stations = list(stations or [])
        self._drawStations()

    def setStationsVisible(self, visible):
        """Master toggle for all station markers (band + line + label)."""
        self._stationsVisible = bool(visible)
        self._drawStations()

    def setLabelsVisible(self, visible):
        """Toggle just the station labels (band + center line still show)."""
        self._labelsVisible = bool(visible)
        self._drawStations()

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
        # constrained_layout re-fits labels/colorbar/title on every resize, so
        # axis labels don't clip when the window is shrunk (tight_layout did).
        try:
            self.figure.set_constrained_layout(True)
        except Exception:
            pass
        self._artists = ()
        self._markers = []
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

        edges, Ro, _ = _bore_geometry(self.axial, self.frame, self._lenScale)
        _style_axes(self.ax, edges, Ro, self._lenUnit)

        sm = cm.ScalarMappable(norm=self._norm, cmap=_CMAP)
        sm.set_array([])
        self._cb = self.figure.colorbar(sm, ax=self.ax, fraction=0.046, pad=0.02)
        suffix = ' ({})'.format(self._fieldUnit) if self._fieldUnit else ''
        self._cb.set_label('{}{}'.format(label, suffix))

        # Theme-matched, opaque readout box (the light-grey grain washed out a
        # translucent white box). Colors follow openMotor's isDarkMode theme.
        theme = _themeColors()
        self._hover = self.ax.text(
            0.01, 0.98, '', transform=self.ax.transAxes, ha='left', va='top',
            fontsize='small', zorder=10, visible=False, color=theme['fg'],
            bbox=dict(boxstyle='round', fc=theme['bg'], ec=theme['ec'],
                      alpha=0.96, linewidth=0.8))
        self.ax.set_title('t = 0.000 s', fontsize='medium')   # constrained_layout fits it
        self._drawStations()   # markers survive field changes (figure was cleared)

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

    # -- station highlights ---------------------------------------------
    @staticmethod
    def _marker_label(st):
        if st.get('grain', -1) >= 0:
            return 'G{} {}'.format(st['grain'] + 1, st.get('role', '') or '').strip()
        return (st.get('role', '') or 'gap')

    def _drawStations(self):
        """Highlight each active station's cell: a faint accent band over the
        cell column + a center line + a short label. Fixed in x, so unaffected
        by the frame; persists across frame swaps (kept off self._artists)."""
        for art in self._markers:
            try:
                art.remove()
            except Exception:
                pass
        self._markers = []
        if (self.ax is None or self.axial is None or self._norm is None
                or not self._stations or not self._stationsVisible):
            self.draw_idle()
            return
        x = np.asarray(self.axial['x_cell'], float) * self._lenScale
        dxh = 0.5 * float(self.axial['dx']) * self._lenScale
        Ro = 0.5 * float(self.axial['D_outer']) * self._lenScale
        n = x.size
        # Sort by axial position so adjacent labels can be staggered in y to
        # avoid overlap (cycle 2 levels when within a horizontal threshold).
        valid = sorted((s for s in self._stations
                        if 0 <= int(s.get('cell_index', -1)) < n),
                       key=lambda s: x[int(s['cell_index'])])
        span = float(x[-1] - x[0]) if n > 1 else 1.0
        thr = 0.05 * span        # labels closer than this stagger
        prev_x, level = -1e30, 0
        for st in valid:
            ci = int(st['cell_index'])
            xc = x[ci]
            band = self.ax.axvspan(xc - dxh, xc + dxh, color=_ACCENT, alpha=0.16, zorder=3)
            line = self.ax.axvline(xc, color=_ACCENT, lw=1.1, alpha=0.9, zorder=4)
            self._markers += [band, line]
            if self._labelsVisible:
                level = (level + 1) % 2 if (xc - prev_x) < thr else 0
                lab = self.ax.text(
                    xc, Ro * (0.93 - 0.50 * level), self._marker_label(st),
                    color=_LABEL_FG, rotation=90, ha='center', va='top',
                    fontsize=8, zorder=6, linespacing=1.3,
                    bbox=dict(boxstyle='round,pad=0.4', fc=_LABEL_BG, ec=_ACCENT,
                              alpha=0.95, linewidth=0.8))
                self._markers.append(lab)
            prev_x = xc
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
        edges, Ro, Rb_edge = _bore_geometry(self.axial, self.frame, self._lenScale)
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
