import unittest

import motorlib.motor
import motorlib.grains
import motorlib.taper
import motorlib.properties


def _bates(core=0.02, length=0.12, diameter=0.08, inhibited='Neither'):
    g = motorlib.grains.BatesGrain()
    g.setProperties({'diameter': diameter, 'length': length,
                     'coreDiameter': core, 'inhibitedEnds': inhibited})
    return g


def _propellant():
    return motorlib.propellant.Propellant({
        'name': 'test', 'density': 1600.0,
        'tabs': [{'a': 1.5e-05, 'n': 0.38, 'k': 1.25, 'm': 23.67,
                  't': 3500.0, 'minPressure': 0.0, 'maxPressure': 6.9e6}],
    })


def _bore_taper(props_at_aft):
    return {'enabled': True, 'bore': {'profile': 'linear',
            'controlStations': [{'frac': 1.0, 'props': props_at_aft}]}}


def _od_taper(ends):
    return {'enabled': False, 'od': {'enabled': True, 'ends': ends}}


class TestOdProfile(unittest.TestCase):

    def test_aft_linear(self):
        ends = [{'end': 'aft', 'length': 0.1, 'endDiameter': 0.04, 'profile': 'linear'}]
        f = lambda x: motorlib.taper.od_diameter_at(x, 0.2, 0.08, ends)
        self.assertAlmostEqual(f(0.0), 0.08)      # outside the aft region
        self.assertAlmostEqual(f(0.5), 0.08)      # region starts at 0.5
        self.assertAlmostEqual(f(0.75), 0.06)     # halfway down the cone
        self.assertAlmostEqual(f(1.0), 0.04)      # aft face

    def test_fwd_elliptical_hemisphere(self):
        ends = [{'end': 'fwd', 'length': 0.2, 'endDiameter': 0.0, 'profile': 'elliptical'}]
        f = lambda x: motorlib.taper.od_diameter_at(x, 0.2, 0.08, ends)
        self.assertAlmostEqual(f(0.0), 0.0)       # closes to a point (hemisphere)
        self.assertAlmostEqual(f(1.0), 0.08)      # full at the aft end
        self.assertTrue(0.0 < f(0.5) < 0.08)

    def test_both_ends(self):
        ends = [{'end': 'aft', 'length': 0.05, 'endDiameter': 0.05, 'profile': 'linear'},
                {'end': 'fwd', 'length': 0.05, 'endDiameter': 0.06, 'profile': 'linear'}]
        f = lambda x: motorlib.taper.od_diameter_at(x, 0.2, 0.08, ends)
        self.assertAlmostEqual(f(0.5), 0.08)      # middle untouched
        self.assertAlmostEqual(f(1.0), 0.05)      # aft
        self.assertAlmostEqual(f(0.0), 0.06)      # fwd

    def test_no_ends(self):
        self.assertAlmostEqual(motorlib.taper.od_diameter_at(0.5, 0.2, 0.08, []), 0.08)

    def test_companion_coupling_roundtrips(self):
        d = motorlib.taper.od_end_diameter_from_angle(0.08, 0.05, 10.0)
        self.assertAlmostEqual(
            motorlib.taper.od_angle_from_end_diameter(0.08, 0.05, d), 10.0)
        self.assertAlmostEqual(
            motorlib.taper.od_end_diameter_from_fraction(0.08, 0.5), 0.04)
        self.assertAlmostEqual(
            motorlib.taper.od_fraction_from_end_diameter(0.08, 0.04), 0.5)


class TestOdExpander(unittest.TestCase):

    def test_aft_cone_diameter_and_inhibition(self):
        g = _bates(core=0.02, length=0.2, diameter=0.08)
        g.props['taper'].setValue(_od_taper(
            [{'end': 'aft', 'length': 0.1, 'endDiameter': 0.04, 'profile': 'linear'}]))
        self.assertTrue(g.isTapered())            # OD-only still tapered
        subs = motorlib.taper.expand_tapered_grain(g, n_slices=8)
        ds = [s.getProperty('diameter') for s in subs]
        self.assertAlmostEqual(ds[0], 0.08)        # fwd half full
        self.assertGreater(ds[0], ds[-1])          # shrinks toward the aft
        self.assertEqual(subs[-1].getProperty('inhibitedEnds'), 'Both')  # aft bonded
        self.assertEqual(subs[0].getProperty('inhibitedEnds'), 'Bottom')  # fwd still burns

    def test_od_only_leaves_cross_section(self):
        g = motorlib.grains.Finocyl()
        g.setProperties({'diameter': 0.08, 'length': 0.2, 'coreDiameter': 0.02,
                         'numFins': 6, 'finWidth': 0.005, 'finLength': 0.01,
                         'inhibitedEnds': 'Neither'})
        g.props['taper'].setValue(_od_taper(
            [{'end': 'aft', 'length': 0.1, 'endDiameter': 0.05, 'profile': 'linear'}]))
        subs = motorlib.taper.expand_tapered_grain(g, n_slices=6)
        self.assertTrue(all(s.getProperty('finLength') == 0.01 for s in subs))
        self.assertTrue(all(s.getProperty('coreDiameter') == 0.02 for s in subs))

    def test_min_diameter_clamp(self):
        g = _bates(core=0.02, length=0.2, diameter=0.08)
        g.props['taper'].setValue(_od_taper(
            [{'end': 'aft', 'length': 0.2, 'endDiameter': 0.0, 'profile': 'linear'}]))
        subs = motorlib.taper.expand_tapered_grain(g, n_slices=8)
        self.assertTrue(all(s.getProperty('diameter') >= 0.02 for s in subs))


class TestOdQuasiSteady(unittest.TestCase):

    def _motor(self, taper):
        m = motorlib.motor.Motor()
        m.propellant = _propellant()
        m.config.setProperties({'timestep': 0.01, 'ambPressure': 101325.0,
                                'burnoutWebThres': 0.0005, 'burnoutThrustThres': 0.1,
                                'mapDim': 500, 'taperSlices': 6})
        m.nozzle.setProperties({'throat': 0.012, 'exit': 0.03, 'efficiency': 0.85,
                                'convAngle': 45.0, 'divAngle': 15.0, 'throatLength': 0})
        g = motorlib.grains.Finocyl()
        g.setProperties({'diameter': 0.08, 'length': 0.3, 'coreDiameter': 0.02,
                         'numFins': 6, 'finWidth': 0.005, 'finLength': 0.01,
                         'inhibitedEnds': 'Neither'})
        if taper is not None:
            g.props['taper'].setValue(taper)
        m.grains.append(g)
        return m

    def test_aft_cone_runs(self):
        m = self._motor(_od_taper(
            [{'end': 'aft', 'length': 0.12, 'endDiameter': 0.05, 'profile': 'linear'}]))
        res = m.runSimulation()
        self.assertGreater(res.getBurnTime(), 0)
        self.assertEqual(len(m.grains), 1)         # authored grain restored
        self.assertIsNotNone(res.getPortRatio())

    def test_fwd_dome_runs(self):
        m = self._motor(_od_taper(
            [{'end': 'fwd', 'length': 0.1, 'endDiameter': 0.03, 'profile': 'elliptical'}]))
        res = m.runSimulation()
        self.assertGreater(res.getBurnTime(), 0)

    def test_od_taper_removes_propellant(self):
        # An OD-shrinking taper removes propellant -> lower peak Kn/pressure
        # than the untapered grain.
        p_full = max(self._motor(None).runSimulation().channels['pressure'].getData())
        p_od = max(self._motor(_od_taper(
            [{'end': 'aft', 'length': 0.15, 'endDiameter': 0.05, 'profile': 'linear'}]
            )).runSimulation().channels['pressure'].getData())
        self.assertLess(p_od, p_full)


class TestTaperProperty(unittest.TestCase):

    def test_default_disabled(self):
        p = motorlib.properties.TaperProperty('t')
        self.assertEqual(p.getValue(), {'enabled': False})

    def test_dict_passthrough_nondict_ignored(self):
        p = motorlib.properties.TaperProperty('t')
        p.setValue({'enabled': True})
        self.assertTrue(p.getValue()['enabled'])
        p.setValue(None)            # ignored
        self.assertTrue(p.getValue()['enabled'])


class TestGrainTaperSerialization(unittest.TestCase):

    def test_disabled_taper_omitted_from_properties(self):
        g = _bates()
        self.assertNotIn('taper', g.getProperties())   # byte-unchanged
        self.assertFalse(g.isTapered())

    def test_enabled_taper_present_and_roundtrips(self):
        g = _bates()
        g.props['taper'].setValue(_bore_taper({'coreDiameter': 0.04}))
        self.assertTrue(g.isTapered())
        self.assertIn('taper', g.getProperties())

        m = motorlib.motor.Motor()
        m.grains.append(g)
        m.nozzle.setProperties({'throat': 0.01})
        m2 = motorlib.motor.Motor(m.getDict())
        self.assertTrue(m2.grains[0].isTapered())
        self.assertEqual(m2.grains[0].getTaperDef(), g.getTaperDef())


class TestExpander(unittest.TestCase):

    def test_non_tapered_passthrough(self):
        g = _bates()
        self.assertEqual(motorlib.taper.expand_tapered_grain(g), [g])

    def test_slice_count_and_interpolation(self):
        g = _bates(core=0.02, length=0.12)
        g.props['taper'].setValue(_bore_taper({'coreDiameter': 0.04}))
        subs = motorlib.taper.expand_tapered_grain(g, n_slices=6)
        self.assertEqual(len(subs), 6)
        cores = [s.getProperty('coreDiameter') for s in subs]
        self.assertTrue(all(b > a for a, b in zip(cores, cores[1:])))  # monotonic
        # Slice centers, so endpoints sit inside (0.02, 0.04).
        self.assertGreater(cores[0], 0.02)
        self.assertLess(cores[-1], 0.04)
        self.assertAlmostEqual(sum(s.getProperty('length') for s in subs), 0.12)

    def test_internal_face_inhibition(self):
        g = _bates(inhibited='Neither')
        g.props['taper'].setValue(_bore_taper({'coreDiameter': 0.04}))
        subs = motorlib.taper.expand_tapered_grain(g, n_slices=4)
        inh = [s.getProperty('inhibitedEnds') for s in subs]
        self.assertEqual(inh, ['Bottom', 'Both', 'Both', 'Top'])

    def test_outer_inhibition_preserved(self):
        g = _bates(inhibited='Top')   # fwd inhibited
        g.props['taper'].setValue(_bore_taper({'coreDiameter': 0.04}))
        subs = motorlib.taper.expand_tapered_grain(g, n_slices=3)
        inh = [s.getProperty('inhibitedEnds') for s in subs]
        self.assertEqual(inh, ['Both', 'Both', 'Top'])  # fwd-most keeps Top, +internal

    def test_single_slice(self):
        g = _bates()
        g.props['taper'].setValue(_bore_taper({'coreDiameter': 0.04}))
        subs = motorlib.taper.expand_tapered_grain(g, n_slices=1)
        self.assertEqual(len(subs), 1)
        self.assertFalse(subs[0].isTapered())   # sub-grains are plain

    def test_non_interpolable_override_raises(self):
        g = motorlib.grains.Finocyl()
        g.setProperties({'diameter': 0.08, 'length': 0.2, 'coreDiameter': 0.02,
                         'numFins': 6, 'finWidth': 0.005, 'finLength': 0.01})
        g.props['taper'].setValue(_bore_taper({'numFins': 8}))  # can't interp count
        with self.assertRaises(ValueError):
            motorlib.taper.expand_tapered_grain(g, n_slices=4)

    def test_slice_count_heuristic_clamped(self):
        # L/D = 0.12/0.08 = 1.5 -> round 2 -> clamped up to n_min (8)
        self.assertEqual(motorlib.taper.taper_slice_count(_bates(length=0.12)),
                         motorlib.taper.SLICE_COUNT_MIN)
        # Very long -> clamped to n_max
        long_g = _bates(length=5.0)
        long_g.props['taper'].setValue(_bore_taper({'coreDiameter': 0.04}))
        self.assertEqual(motorlib.taper.taper_slice_count(long_g),
                         motorlib.taper.SLICE_COUNT_MAX)

    def test_expand_override_fixed_count(self):
        # expand_motor_grains n_slices override forces a fixed count per taper.
        g = _bates(length=0.3)
        g.props['taper'].setValue(_bore_taper({'coreDiameter': 0.04}))
        subs = motorlib.taper.expand_motor_grains([g], map_dim=151, n_slices=5)
        self.assertEqual(len(subs), 5)


class TestTaperHelpers(unittest.TestCase):
    """Pure helpers shared by the QS expander and the GUI taper editor."""

    def _finocyl(self):
        g = motorlib.grains.Finocyl()
        g.setProperties({'diameter': 0.08, 'length': 0.2, 'coreDiameter': 0.02,
                         'numFins': 6, 'finWidth': 0.005, 'finLength': 0.01,
                         'inhibitedEnds': 'Neither'})
        return g

    def test_taperable_property_names(self):
        # Excludes length (axial), diameter (OD), taper; ints/bools/enums.
        self.assertEqual(motorlib.taper.taperable_property_names(_bates()),
                         ['coreDiameter'])
        names = motorlib.taper.taperable_property_names(self._finocyl())
        self.assertEqual(set(names), {'coreDiameter', 'finWidth', 'finLength'})
        self.assertNotIn('numFins', names)       # IntProperty
        self.assertNotIn('invertedFins', names)  # BooleanProperty
        self.assertNotIn('diameter', names)      # OD (reserved)

    def test_build_bore_taper_def(self):
        d = motorlib.taper.build_bore_taper_def({'finLength': 0.02})
        self.assertTrue(d['enabled'])
        self.assertEqual(d['bore']['profile'], 'linear')
        self.assertEqual(d['bore']['controlStations'],
                         [{'frac': 1.0, 'props': {'finLength': 0.02}}])

    def test_aft_props_defaults_to_base(self):
        g = self._finocyl()
        aft = motorlib.taper.aft_props_from_grain(g)   # no taper -> all base
        self.assertAlmostEqual(aft['finLength'], 0.01)
        self.assertAlmostEqual(aft['coreDiameter'], 0.02)

    def test_aft_props_reads_overrides(self):
        g = self._finocyl()
        g.props['taper'].setValue(_bore_taper({'finLength': 0.02}))
        aft = motorlib.taper.aft_props_from_grain(g)
        self.assertAlmostEqual(aft['finLength'], 0.02)   # override
        self.assertAlmostEqual(aft['coreDiameter'], 0.02)  # untouched -> base

    def _setup_finocyl(self, fin_length, map_dim=151):
        g = motorlib.grains.Finocyl()
        g.setProperties({'diameter': 0.08, 'length': 0.2, 'coreDiameter': 0.02,
                         'numFins': 6, 'finWidth': 0.005, 'finLength': fin_length,
                         'inhibitedEnds': 'Neither'})
        g.initGeometry(map_dim)
        g.generateCoreMap()
        g.generateRegressionMap()
        return g

    def test_averaged_area_curve_brackets_faces(self):
        # The slice-averaged initial perimeter must lie between the forward and
        # aft single-face perimeters (fins grow 10 -> 20 mm).
        g = self._finocyl()
        g.props['taper'].setValue(_bore_taper({'finLength': 0.02}))
        curve = motorlib.taper.averaged_area_curve(g, n_slices=4, map_dim=151)
        self.assertGreater(len(curve), 1)
        self.assertTrue(all(v >= 0 for v in curve.values()))
        p_mean0 = curve[min(curve)]                       # mean perimeter at reg 0
        p_fwd = self._setup_finocyl(0.01).getCorePerimeter(0.0)
        p_aft = self._setup_finocyl(0.02).getCorePerimeter(0.0)
        self.assertGreaterEqual(p_mean0, min(p_fwd, p_aft) - 1e-6)
        self.assertLessEqual(p_mean0, max(p_fwd, p_aft) + 1e-6)


class TestQuasiSteadyExpansion(unittest.TestCase):

    def _motor(self, tapered):
        m = motorlib.motor.Motor()
        m.propellant = _propellant()
        # Coarse timestep / prompt burnout so the equivalence sims run fast
        # (MotorConfig otherwise defaults timestep to its 0.0001 s minimum).
        m.config.setProperties({'timestep': 0.01, 'ambPressure': 101325.0,
                                'burnoutWebThres': 0.0005, 'burnoutThrustThres': 0.1,
                                'mapDim': 500, 'taperSlices': 4})  # fixed -> fast/deterministic
        m.nozzle.setProperties({'throat': 0.012, 'exit': 0.03, 'efficiency': 0.85,
                                'convAngle': 45.0, 'divAngle': 15.0, 'throatLength': 0})
        g = _bates(core=0.02, length=0.3, diameter=0.08)
        if tapered:
            g.props['taper'].setValue(_bore_taper({'coreDiameter': 0.035}))
        m.grains.append(g)
        return m

    def test_tapered_run_restores_authored_grains(self):
        m = self._motor(tapered=True)
        res = m.runSimulation()
        self.assertEqual(len(m.grains), 1)             # restored
        self.assertTrue(m.grains[0].isTapered())
        self.assertTrue(res.getBurnTime() > 0)

    def test_tapered_matches_manual_stack(self):
        # A tapered grain's QS result must equal a hand-built sub-grain stack.
        m_taper = self._motor(tapered=True)
        m_stack = self._motor(tapered=True)
        # Match the QS config override (taperSlices=4) so both stacks align.
        subs = motorlib.taper.expand_tapered_grain(m_stack.grains[0], n_slices=4)
        m_stack.grains = subs

        r_taper = m_taper.runSimulation()
        r_stack = m_stack.runSimulation()
        self.assertAlmostEqual(max(r_taper.channels['pressure'].getData()),
                               max(r_stack.channels['pressure'].getData()),
                               places=3)
        self.assertAlmostEqual(r_taper.getBurnTime(), r_stack.getBurnTime(), places=3)

    def test_non_tapered_unaffected(self):
        m = self._motor(tapered=False)
        res = m.runSimulation()
        self.assertEqual(len(m.grains), 1)
        self.assertTrue(res.getBurnTime() > 0)

    def test_simresult_port_ratio_uses_aft_slice(self):
        # Regression + correctness: getPortRatio must not crash post-run, and
        # must use the AFT cross-section (adjacent to the throat). The taper
        # grows the core 0.02 -> 0.035, so the aft port (and thus the ratio)
        # exceeds the untapered (forward-core) motor's.
        r_t = self._motor(tapered=True).runSimulation()
        r_n = self._motor(tapered=False).runSimulation()
        self.assertIsNotNone(r_t.getPortRatio())
        self.assertGreater(r_t.getPortRatio(), r_n.getPortRatio())


class TestTaperableGate(unittest.TestCase):

    def test_conical_not_taperable(self):
        g = motorlib.grains.ConicalGrain()
        self.assertFalse(g.isTaperable)
        g.props['taper'].setValue(_bore_taper({'aftCoreDiameter': 0.04}))
        self.assertFalse(g.isTapered())                       # taper ignored
        self.assertFalse('taper' in g.getProperties())        # not serialized
        self.assertEqual(motorlib.taper.expand_tapered_grain(g), [g])

    def test_endburner_not_taperable(self):
        self.assertFalse(motorlib.grains.EndBurningGrain().isTaperable)

    def test_bates_finocyl_taperable(self):
        self.assertTrue(motorlib.grains.BatesGrain().isTaperable)
        self.assertTrue(motorlib.grains.Finocyl().isTaperable)


if __name__ == '__main__':
    unittest.main()
