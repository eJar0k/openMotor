import os
import tempfile
import unittest

import numpy as np

import motorlib.units
from motorlib.importedData import (parseCsvText, splitHeader, lookupUnit, loadCsv,
                                   ImportedDataError)


def _unit(header):
    name, info = splitHeader(header)
    return name, (info[2] if info else None)


class TestUnitDetection(unittest.TestCase):

    def test_known_forms(self):
        self.assertEqual(_unit('Thrust (N)'), ('Thrust', 'N'))
        self.assertEqual(_unit('Pressure (psi)'), ('Pressure', 'psi'))
        self.assertEqual(_unit('Pressure - MPa'), ('Pressure', 'MPa'))
        self.assertEqual(_unit('Force [lbf]'), ('Force', 'lbf'))
        self.assertEqual(_unit('time(s)'), ('time', 's'))
        self.assertEqual(_unit('pressure (MPA)'), ('pressure', 'MPa'))
        self.assertEqual(_unit('Pressure (trimmed, MPa)'), ('Pressure', 'MPa'))
        self.assertEqual(_unit('Pressure_psi'), ('Pressure', 'psi'))
        self.assertEqual(_unit('Thrust kN'), ('Thrust', 'kN'))

    def test_unknown_is_not_guessed(self):
        self.assertEqual(_unit('Time (trimmed)'), ('Time (trimmed)', None))
        self.assertEqual(_unit('Thrust'), ('Thrust', None))
        self.assertEqual(_unit('Chamber Pressure'), ('Chamber Pressure', None))
        self.assertEqual(_unit('Weight (lbs)'), ('Weight (lbs)', None))  # ambiguous

    def test_conversion_factors(self):
        base, f, _ = lookupUnit('kPa')
        self.assertEqual((base, f), ('Pa', 1e3))
        self.assertEqual(lookupUnit('MPa')[0], 'Pa')
        self.assertAlmostEqual(lookupUnit('MPa')[1], 1e6, delta=1)
        self.assertAlmostEqual(lookupUnit('psi')[1], 6895, delta=1)
        self.assertAlmostEqual(lookupUnit('ms')[1], 1e-3)


class TestParse(unittest.TestCase):

    def test_good_with_units(self):
        d = parseCsvText('Time (s),Thrust (N),Pressure (psi)\n0,0,0\n1,100,500\n2,50,250\n')
        self.assertEqual([c.name for c in d.columns], ['Thrust', 'Pressure'])
        self.assertTrue(d.timeColumn.unitKnown)
        np.testing.assert_allclose(d.timeSeconds(), [0, 1, 2])
        y, unit = d.columns[1].converted('MPa')
        self.assertEqual(unit, 'MPa')
        self.assertAlmostEqual(y[1], 500 * 6895 / 1e6, places=3)
        y, unit = d.columns[0].converted('lbf')
        self.assertAlmostEqual(y[1], 100 * 0.2248, places=4)

    def test_convert_to_display_unit_via_motorlib(self):
        d = parseCsvText('t (ms),P (kPa)\n0,100\n1000,200\n')
        np.testing.assert_allclose(d.timeSeconds(), [0, 1])
        y, unit = d.columns[0].converted('MPa')
        np.testing.assert_allclose(y, [0.1, 0.2])

    def test_no_units(self):
        d = parseCsvText('time,pressure\n0,1\n1,2\n')
        self.assertFalse(d.columns[0].unitKnown)
        self.assertIn('units unknown', d.columns[0].displayName)
        y, unit = d.columns[0].converted('psi')
        self.assertIsNone(unit)
        np.testing.assert_allclose(y, [1, 2])

    def test_time_detected_by_name_not_position(self):
        d = parseCsvText('"Pressure (trimmed, MPa)",Time (trimmed)\n0,0\n0.02,0.15\n')
        self.assertEqual(d.timeColumn.name, 'Time (trimmed)')
        self.assertEqual([c.name for c in d.columns], ['Pressure'])
        self.assertFalse(d.timeColumn.unitKnown)

    def test_first_column_fallback_and_bom(self):
        d = parseCsvText('\ufeffx,y (N)\n0,1\n1,2\n')
        self.assertEqual(d.timeColumn.name, 'x')
        self.assertEqual(d.columns[0].unitLabel, 'N')

    def test_semicolon_and_blank_cells(self):
        d = parseCsvText('time;a\n0;1\n1;\n2;3\n')
        self.assertTrue(np.isnan(d.columns[0].values[1]))

    def test_bad_files(self):
        for text, fragment in [
            ('', 'empty'),
            ('0,1\n1,2\n2,3\n', 'header'),
            ('time\n0\n1\n', 'one column'),
            ('time,a\n0,1\n', 'two data rows'),
            ('time,a\n0,1\n1,abc\n', 'Non-numeric'),
            ('time,a\n0,1\n1\n', 'cells'),
            ('time,a\n,1\n1,2\n', 'empty cells'),
        ]:
            with self.assertRaises(ImportedDataError, msg=text) as cm:
                parseCsvText(text)
            self.assertIn(fragment, str(cm.exception))

    def test_missing_file(self):
        with self.assertRaises(ImportedDataError):
            loadCsv(os.path.join(tempfile.gettempdir(), 'nonexistent_om_file.csv'))

    def test_real_files(self):
        base = os.path.join(os.environ.get('SRM1D_STATIC_FIRE_DIR', ''), '')
        for name, cols in [('thomas_chunc_firing.csv', 1), ('zerox_data.csv', 1), ('pathfin54.csv', 2)]:
            path = os.path.join(base, name)
            if not os.path.isfile(path):
                self.skipTest('static-fire data not available')
            self.assertEqual(len(loadCsv(path).columns), cols)


if __name__ == '__main__':
    unittest.main()
