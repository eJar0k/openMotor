"""
motorlib.taper — axial-taper expansion for the quasi-steady solver.

A tapered grain is a single grain whose cross-section varies along its axis
(e.g. a finocyl whose fins grow from the head to the aft end). openMotor's
FMM grains are 2-D cross-sections with no axial variation, and the QS solver
sums scalar per-grain contributions, so a taper is realized by EXPANDING one
tapered grain into a stack of N normal sub-grains — each a thin slice whose
cross-section is the taper sampled at that slice's axial center, with the
artificial internal faces inhibited so only the taper's true ends burn.

The taper DEFINITION is solver-agnostic data stored on the grain (the
``taper`` property); see ``Grain.getTaperDef``. The schema:

    {
      'enabled': bool,
      'bore': {                      # cross-section taper (implemented)
        'profile': 'linear',
        'controlStations': [         # sorted by frac; frac in (0, 1]
          {'frac': 1.0, 'props': {<only the props that differ from the base>}},
        ],
      },
      'od': {...},                   # outer-diameter / end taper (reserved)
    }

The grain's normal properties ARE the forward (frac 0) cross-section; the
control stations give the aft / intermediate overrides. Two implicit + one
control point = a linear taper. The number of slices and the per-slice FMM
``mapDim`` are a SOLVER's choice (not stored), so the transient solver can use
a finer discretization than QS. QS defaults below come from the Phase-0 cost
probe: skfmm setup is O(mapDim**2) and dominates, so sub-grains use a reduced
mapDim, and N tracks L/D with a conservative cap.
"""

# QS discretization defaults (from the Phase-0 cost probe). The slice count is
# N ~ clamp(round(k*L/D), MIN, MAX). The floor was raised from 3 -> 8 because
# short (low-L/D) tapers showed visible stepping in the thrust curve with only
# a few slices; the QS config exposes an explicit override for finer control
# (see MotorConfig 'taperSlices'). The per-slice mapDim is reduced because
# skfmm setup is O(mapDim^2) and dominates.
DEFAULT_SLICE_MAP_DIM = 500     # ~12x cheaper than 1001; fine for thin slices
SLICE_COUNT_COEFF = 1.0         # N ~ k * L/D
SLICE_COUNT_MIN = 8
SLICE_COUNT_MAX = 16

# Properties that cannot be linearly interpolated (must match across stations).
_NON_INTERPOLABLE = {'numFins'}

_INH_PAIR = {'Neither': (False, False), 'Top': (True, False),
             'Bottom': (False, True), 'Both': (True, True)}


# Grain properties that the bore taper never varies: the axial length, the
# outer diameter (reserved for the OD/end-taper phase), and the taper block
# itself. Everything else that is a FloatProperty is a taperable cross-section
# dimension (coreDiameter, finLength, finWidth, ...).
_NON_BORE_TAPER_PROPS = {'length', 'diameter', 'taper'}


def taperable_property_names(grain):
    """Float cross-section property names a bore taper may vary (excludes the
    axial length, the outer diameter, and the taper block). Used by the GUI to
    decide which rows get a start|aft pair, and shared so QS/GUI agree."""
    from .properties import FloatProperty
    return [name for name, prop in grain.props.items()
            if name not in _NON_BORE_TAPER_PROPS
            and isinstance(prop, FloatProperty)]


def build_bore_taper_def(aft_overrides, profile='linear'):
    """Assemble an enabled bore-taper definition dict from the aft-end overrides
    (``{prop: value}`` for only the properties that differ from the base/forward
    cross-section). Start (frac 0) is implicit = the grain's base props."""
    return {'enabled': True, 'bore': {
        'profile': profile,
        'controlStations': [{'frac': 1.0, 'props': dict(aft_overrides)}],
    }}


def aft_props_from_grain(grain):
    """The aft-end value of every taperable property: the taper override where
    one exists, else the base (forward) value. Used to populate the GUI's aft
    column when (re)loading a grain."""
    names = taperable_property_names(grain)
    overrides = {}
    taper = grain.getTaperDef()
    if isinstance(taper, dict) and taper.get('enabled'):
        bore = taper.get('bore', {}) or {}
        stations = bore.get('controlStations', [])
        if stations:
            overrides = stations[-1].get('props', {}) or {}
    return {name: overrides.get(name, grain.getProperty(name)) for name in names}


def averaged_area_curve(grain, n_slices=None, map_dim=250, n_points=24):
    """Mean burning-perimeter-vs-regression over a tapered grain's slices.

    The grain-preview area graph plots burning perimeter (∝ burn area per unit
    length). For a tapered grain a single face misrepresents the whole grain;
    this samples every slice's perimeter on a common regression axis and
    averages (slices have equal length, so the mean is the representative
    per-unit-length curve; burnt-out slices contribute 0). Returns a
    ``{regression: mean_perimeter}`` dict matching the single-grain area graph.

    Uses ``getCorePerimeter`` (contour length only), so it works with srm_1d's
    pure-Python find_perimeter shim as well as openMotor's Cython build.
    """
    import numpy as np

    slices = expand_tapered_grain(grain, n_slices, map_dim=map_dim)
    for sub in slices:
        sub.initGeometry(map_dim)
        sub.generateCoreMap()
        sub.generateRegressionMap()

    max_web = max(sub.wallWeb for sub in slices)
    if max_web <= 0.0:
        return {0.0: 0.0}

    curve = {}
    for reg in np.linspace(0.0, max_web, n_points):
        total = 0.0
        for sub in slices:
            if reg < sub.wallWeb:
                total += float(sub.getCorePerimeter(reg))
            # else burnt out here -> contributes 0
        curve[float(reg)] = total / len(slices)
    return curve


def _inh_pair(name):
    return _INH_PAIR.get(name, (False, False))


def _inh_enum(fwd, aft):
    if fwd and aft:
        return 'Both'
    if fwd:
        return 'Top'
    if aft:
        return 'Bottom'
    return 'Neither'


def _interpolate_props(props_a, props_b, t):
    """Linearly blend two full property dicts. Float dimensions interpolate;
    integer counts / booleans / strings must be equal in both (a taper can't
    interpolate, e.g., fin count) or a ValueError is raised."""
    out = {}
    for key, va in props_a.items():
        vb = props_b.get(key, va)
        numeric = (isinstance(va, (int, float)) and not isinstance(va, bool)
                   and isinstance(vb, (int, float)) and not isinstance(vb, bool))
        if numeric and key not in _NON_INTERPOLABLE:
            out[key] = va + (vb - va) * t
        else:
            if va != vb:
                raise ValueError(
                    "taper property {!r} cannot be interpolated "
                    "(integer count, boolean, or string): {!r} != {!r}. "
                    "Hold it constant across the taper.".format(key, va, vb))
            out[key] = va
    return out


def _build_control_points(base_props, taper_def):
    """[(frac, full_props), ...] sorted by frac; frac 0 = the base (forward)
    cross-section, later points = base overlaid with each station's overrides."""
    control = [(0.0, dict(base_props))]
    bore = taper_def.get('bore', {}) or {}
    stations = sorted(bore.get('controlStations', []),
                      key=lambda s: float(s['frac']))
    for station in stations:
        overrides = station.get('props', {}) or {}
        control.append((float(station['frac']), {**base_props, **overrides}))
    return control


def _interp_at(control, frac):
    """Full property dict at axial ``frac`` (piecewise-linear between points)."""
    if frac <= control[0][0]:
        return dict(control[0][1])
    if frac >= control[-1][0]:
        return dict(control[-1][1])
    for j in range(len(control) - 1):
        f0, p0 = control[j]
        f1, p1 = control[j + 1]
        if f0 <= frac <= f1:
            t = 0.0 if f1 == f0 else (frac - f0) / (f1 - f0)
            return _interpolate_props(p0, p1, t)
    return dict(control[-1][1])  # defensive; unreachable


def taper_slice_count(grain, coeff=SLICE_COUNT_COEFF,
                      n_min=SLICE_COUNT_MIN, n_max=SLICE_COUNT_MAX):
    """QS slice count for a tapered grain: clamp(round(coeff * L/D), n_min,
    n_max). Low-L/D segments get fewer slices; long ones more, capped for
    cost. A ``maxStations`` hint in the taper def lowers the cap if smaller."""
    props = grain.getProperties()
    length = props.get('length', 0.0)
    diameter = props.get('diameter', 0.0)
    if diameter <= 0.0:
        return n_min
    taper = grain.getTaperDef()
    bore = (taper.get('bore', {}) or {}) if isinstance(taper, dict) else {}
    hint = bore.get('maxStations')
    cap = min(n_max, int(hint)) if hint else n_max
    n = int(round(coeff * length / diameter))
    return max(n_min, min(cap, n))


def expand_tapered_grain(grain, n_slices=None, map_dim=DEFAULT_SLICE_MAP_DIM):
    """Expand one tapered grain into a stack of N normal sub-grains.

    Returns ``[grain]`` unchanged if the grain has no enabled taper. Otherwise
    each sub-grain is a fresh instance of the same geomName with the taper
    sampled at its slice center, ``length = L/N``, and internal faces
    inhibited (first slice keeps the grain's forward inhibition + inhibits its
    aft; middles are ``Both``; last keeps the aft inhibition + inhibits its
    forward). ``map_dim`` is stashed on each sub-grain as ``_sim_map_dim`` so
    the QS run can give them a reduced FMM resolution.
    """
    from .grains import grainTypes

    if not grain.isTapered():
        return [grain]

    taper = grain.getTaperDef()
    # Base = the grain's props WITHOUT the taper block (sub-grains are plain).
    base = {k: v for k, v in grain.getProperties().items() if k != 'taper'}
    geom = grain.geomName
    length = base.get('length', 0.0)

    if n_slices is None:
        n_slices = taper_slice_count(grain)
    n = max(1, int(n_slices))

    control = _build_control_points(base, taper)
    orig_fwd, orig_aft = _inh_pair(base.get('inhibitedEnds', 'Neither'))

    subgrains = []
    for i in range(n):
        frac = (i + 0.5) / n                     # slice center
        props = _interp_at(control, frac)
        props['length'] = length / n
        if n == 1:
            props['inhibitedEnds'] = base.get('inhibitedEnds', 'Neither')
        elif i == 0:
            props['inhibitedEnds'] = _inh_enum(orig_fwd, True)
        elif i == n - 1:
            props['inhibitedEnds'] = _inh_enum(True, orig_aft)
        else:
            props['inhibitedEnds'] = 'Both'

        sub = grainTypes[geom]()
        sub.setProperties(props)
        if map_dim is not None:
            sub._sim_map_dim = int(map_dim)
        subgrains.append(sub)
    return subgrains


def expand_motor_grains(grains, map_dim=DEFAULT_SLICE_MAP_DIM, n_slices=None):
    """Expand every tapered grain in a list; pass non-tapered grains through.
    ``n_slices`` (>0) forces a fixed slice count for every tapered grain
    (the QS config override); ``None`` uses the per-grain L/D heuristic. The
    caller clamps ``map_dim`` to the global config mapDim."""
    out = []
    for grain in grains:
        out.extend(expand_tapered_grain(grain, n_slices=n_slices, map_dim=map_dim))
    return out
