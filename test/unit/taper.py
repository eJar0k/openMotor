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
        # L/D = 0.12/0.08 = 1.5 -> round 2 -> clamped up to n_min=3
        self.assertEqual(motorlib.taper.taper_slice_count(_bates(length=0.12)), 3)
        # Very long -> clamped to n_max=12
        long_g = _bates(length=5.0)
        long_g.props['taper'].setValue(_bore_taper({'coreDiameter': 0.04}))
        self.assertEqual(motorlib.taper.taper_slice_count(long_g), 12)


class TestQuasiSteadyExpansion(unittest.TestCase):

    def _motor(self, tapered):
        m = motorlib.motor.Motor()
        m.propellant = _propellant()
        # Coarse timestep / prompt burnout so the equivalence sims run fast
        # (MotorConfig otherwise defaults timestep to its 0.0001 s minimum).
        m.config.setProperties({'timestep': 0.01, 'ambPressure': 101325.0,
                                'burnoutWebThres': 0.0005, 'burnoutThrustThres': 0.1,
                                'mapDim': 500})
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
        subs = motorlib.taper.expand_tapered_grain(m_stack.grains[0])
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


if __name__ == '__main__':
    unittest.main()
