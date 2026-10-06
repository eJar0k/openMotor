"""Plugin-provided igniter: Motor round trip, file migration, the library
manager, and the edit-merge helpers.

The igniter MODEL is owned by the solver plugin (srm_1d), so these tests need
it importable; they skip cleanly when it is not. The real user config / log
directories are never touched: ``platformdirs`` is pointed at a temp dir while
``uilib`` is imported, and the manager tests patch ``getConfigPath``.
"""
import copy
import os
import shutil
import tempfile
import unittest
from unittest import mock

import platformdirs

import motorlib.motor
import motorlib.solvers
import motorlib.igniter

_TMP_ROOT = tempfile.mkdtemp(prefix='om_igniter_unit_')
_SKIP = None
_orig = (platformdirs.user_data_dir, platformdirs.user_log_dir)
platformdirs.user_data_dir = lambda *a, **k: os.path.join(_TMP_ROOT, 'data')
platformdirs.user_log_dir = lambda *a, **k: os.path.join(_TMP_ROOT, 'log')
try:
    # As in app.py: Qt must be imported before uilib (its matplotlib backend
    # selection keys off an already-imported binding).
    import PyQt6.QtWidgets  # noqa: F401
    import srm_1d.srm1d_plugin  # noqa: F401  (registers the igniter provider)
    import uilib.fileIO as fileIO
    import uilib.pyrogenManager as pyrogenManager
except Exception as exc:  # pragma: no cover - plugin / Qt not installed
    _SKIP = 'igniter provider or uilib unavailable: {}'.format(exc)
finally:
    platformdirs.user_data_dir, platformdirs.user_log_dir = _orig

# The pre-bfc2f3f BPNV exactly as the fork used to seed it, WITH the float
# noise the GUI display-unit round trip put into a real user library.
LEGACY_BPNV = {
    'name': 'BPNV', 'a': 2.0e-5, 'n': 0.50, 'rho': 1699.9999999999998,
    'T_flame': 2800.0, 'M': 0.030, 'gamma': 1.25,
    'impetus_W': 5000.0, 'heat_flux_cal_cm2_s': 69.4,
    'kappa_jet': 8.0, 'form': 'pellets',
    'particle_diameter_m': 0.0032000000000000006, 'particle_LD_ratio': 1.0,
    'heat_delivery_mode': 'demar', 'pellet_emissivity': 0.7,
    'radiation_absorption_length_m': 1.0,
}
CHAMBER = {
    'mass': 0.004, 'throat_area': -1.0, 'volume': -1.0, 'burn_area': -1.0,
    'burn_law': '0d', 'injection_topology': 'head_basket',
    'cartridge_length_m': -1.0, 'basket_fill_fraction': 0.5,
    'pellet_packing_fraction': 0.60,
}


def tearDownModule():
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


def _motor_dict(igniter):
    d = motorlib.motor.Motor().getDict()
    if igniter is None:
        d.pop('igniter', None)
    else:
        d['igniter'] = igniter
    return d


@unittest.skipIf(_SKIP, _SKIP)
class TestIgniterProvider(unittest.TestCase):

    def test_provider_is_the_srm1d_solver(self):
        provider = motorlib.solvers.get_igniter_provider()
        self.assertIsNotNone(provider)
        self.assertTrue(provider.capabilities.get('igniter'))
        qs = motorlib.solvers.get_solver(motorlib.solvers.QUASI_STEADY)
        self.assertEqual(qs.get_igniter_materials(), [])      # base defaults
        self.assertIsNone(qs.get_default_igniter())
        self.assertEqual(qs.upgrade_igniter_block({'a': 1}), ({'a': 1}, False))

    def test_motor_without_igniter_has_no_block(self):
        m = motorlib.motor.Motor()
        self.assertIsNone(m.igniterData)
        self.assertNotIn('igniter', m.getDict())

    def test_round_trip_is_lossless(self):
        block = dict(CHAMBER)
        block['pyrogen'] = {
            'name': 'Custom', 'a': 1e-5, 'n': 0.4, 'rho': 1500.0,
            'T_flame': 2500.0, 'M': 0.04, 'gamma': 1.2,
            'Cp_gas': None,                 # None: FloatProperty would raise
            'heat_flux_cal_cm2_s': None,
            'impetus_W': 1e9,               # out of range: would be dropped
            'future_field': {'nested': [1, 2]},   # unknown key
        }
        block['unknown_chamber_key'] = 'kept'
        orig = copy.deepcopy(block)
        m = motorlib.motor.Motor(_motor_dict(block))
        self.assertEqual(m.getDict()['igniter'], orig)
        self.assertEqual(motorlib.motor.Motor(m.getDict()).getDict()['igniter'],
                         orig)
        block['mass'] = 99.0                # copies in and out
        self.assertEqual(m.getDict()['igniter']['mass'], 0.004)
        m.getDict()['igniter']['mass'] = 5.0
        self.assertEqual(m.getDict()['igniter']['mass'], 0.004)

    def test_legacy_bpnv_is_upgraded_on_apply(self):
        provider = motorlib.solvers.get_igniter_provider()
        current = next(x for x in provider.get_igniter_materials()
                       if x['name'] == 'BPNV')
        block = dict(CHAMBER)
        block['pyrogen'] = copy.deepcopy(LEGACY_BPNV)
        out = motorlib.motor.Motor(_motor_dict(block)).getDict()['igniter']
        self.assertEqual(out['pyrogen'], current)
        self.assertEqual(out['pyrogen']['gas_mass_fraction'], 0.781)
        for k, v in CHAMBER.items():
            self.assertEqual(out[k], v)

    def test_customised_bpnv_is_not_touched(self):
        block = dict(CHAMBER)
        block['pyrogen'] = dict(LEGACY_BPNV, M=0.031)
        out = motorlib.motor.Motor(_motor_dict(block)).getDict()['igniter']
        self.assertEqual(out['pyrogen']['M'], 0.031)
        self.assertNotIn('gas_mass_fraction', out['pyrogen'])

    def test_no_provider_passes_block_through_verbatim(self):
        block = dict(CHAMBER)
        block['pyrogen'] = copy.deepcopy(LEGACY_BPNV)
        orig = copy.deepcopy(block)
        with mock.patch.object(motorlib.solvers, 'get_igniter_provider',
                               return_value=None):
            out = motorlib.motor.Motor(_motor_dict(block)).getDict()['igniter']
            self.assertEqual(out, orig)             # legacy NOT upgraded
            self.assertIsNone(motorlib.igniter.material_collection({}))
            self.assertIsNone(motorlib.igniter.chamber_collection({}))
            self.assertIsNone(motorlib.igniter.merge_edits(None))

    def test_migration_seeds_provider_default(self):
        data = {'propellant': {'tabs': [{}]}}
        out = fileIO.migrateMotor_0_6_1_to_0_7_0(data)
        provider = motorlib.solvers.get_igniter_provider()
        self.assertEqual(out['igniter'], provider.get_default_igniter())
        self.assertEqual(out['igniter']['pyrogen']['gas_mass_fraction'], 0.781)
        # An existing block is kept.
        data = {'propellant': {'tabs': []}, 'igniter': {'x': 1}}
        self.assertEqual(fileIO.migrateMotor_0_6_1_to_0_7_0(data)['igniter'],
                         {'x': 1})
        # No provider: no igniter key is added.
        with mock.patch.object(motorlib.solvers, 'get_igniter_provider',
                               return_value=None):
            out = fileIO.migrateMotor_0_6_1_to_0_7_0(
                {'propellant': {'tabs': []}})
        self.assertNotIn('igniter', out)

    def test_changed_values_and_merge_edits(self):
        coll = motorlib.igniter.chamber_collection(
            dict(CHAMBER, pyrogen={'name': 'x'}, bogus=1))
        snap = coll.getProperties()
        self.assertEqual(motorlib.igniter.changed_values(snap, coll), {})
        coll.setProperty('mass', 0.5)
        self.assertEqual(motorlib.igniter.changed_values(snap, coll),
                         {'mass': 0.5})
        block = dict(CHAMBER, pyrogen={'name': 'x'}, keep='me')
        out = motorlib.igniter.merge_edits(
            block, material={'name': 'y'}, chamberChanges={'mass': 0.5})
        self.assertEqual(out['pyrogen'], {'name': 'y'})
        self.assertEqual((out['mass'], out['keep']), (0.5, 'me'))
        self.assertEqual(block['mass'], 0.004)          # input not mutated
        seeded = motorlib.igniter.merge_edits(None, chamberChanges={'mass': 2.0})
        self.assertEqual(seeded['mass'], 2.0)
        self.assertEqual(seeded['pyrogen']['name'], 'BPNV')

    def test_material_collection_skips_none_and_blanks_name(self):
        coll = motorlib.igniter.material_collection(
            {'a': 2e-5, 'Cp_gas': None, 'rho': None})
        self.assertEqual(coll.getProperty('a'), 2e-5)
        self.assertEqual(coll.getProperty('name'), '')


@unittest.skipIf(_SKIP, _SKIP)
class TestPyrogenManager(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='pm_', dir=_TMP_ROOT)
        self.cfg = mock.patch.object(pyrogenManager, 'getConfigPath',
                                     return_value=self.dir + '/')
        self.cfg.start()
        self.provider = motorlib.solvers.get_igniter_provider()
        self.libNames = [m['name'] for m in
                         self.provider.get_igniter_materials()]

    def tearDown(self):
        self.cfg.stop()

    def _file(self):
        return os.path.join(self.dir, 'pyrogens.yaml')

    def _write(self, materials):
        fileIO.saveFile(self._file(), materials, fileIO.fileTypes.IGNITERS)

    def _read(self):
        return fileIO.loadFile(self._file(), fileIO.fileTypes.IGNITERS)

    def test_missing_file_is_seeded_from_provider(self):
        mgr = pyrogenManager.PyrogenManager()
        self.assertEqual(mgr.getNames(), self.libNames)
        self.assertEqual(mgr.pyrogens, self.provider.get_igniter_materials())
        self.assertEqual(self._read(), mgr.pyrogens)       # and saved

    def test_legacy_single_bpnv_library_is_upgraded_and_completed(self):
        self._write([copy.deepcopy(LEGACY_BPNV)])
        mgr = pyrogenManager.PyrogenManager()
        for name in ('BPNV', 'MTV', 'MTV_fast',
                     'Cu/Al thermite (CuO + Al stoichiometric)'):
            self.assertIn(name, mgr.getNames())
        self.assertEqual(sorted(mgr.getNames()), sorted(self.libNames))
        self.assertEqual(mgr.getPyrogenByName('BPNV')['gas_mass_fraction'], 0.781)
        self.assertEqual(mgr.getPyrogenByName('BPNV')['M'], 0.0482)
        self.assertEqual(self._read(), mgr.pyrogens)       # saved upgraded

    def test_customised_entry_is_kept_verbatim(self):
        custom = dict(LEGACY_BPNV, name='My igniter', M=0.05,
                      secret_key=[1, 2])
        self._write([copy.deepcopy(custom)])
        mgr = pyrogenManager.PyrogenManager()
        self.assertEqual(mgr.getPyrogenByName('My igniter'), custom)
        self.assertEqual(mgr.getNames()[0], 'My igniter')
        self.assertEqual(sorted(mgr.getNames()),
                         sorted(['My igniter'] + self.libNames))

    def test_current_library_file_is_not_rewritten(self):
        mats = self.provider.get_igniter_materials()
        self._write(mats)
        before = os.path.getmtime(self._file())
        mgr = pyrogenManager.PyrogenManager()
        self.assertEqual(mgr.pyrogens, mats)
        self.assertEqual(os.path.getmtime(self._file()), before)

    def test_no_provider_gives_empty_library_without_crashing(self):
        with mock.patch.object(motorlib.solvers, 'get_igniter_provider',
                               return_value=None):
            mgr = pyrogenManager.PyrogenManager()
            self.assertEqual(mgr.pyrogens, [])
            self.assertFalse(os.path.exists(self._file()))
            self._write([copy.deepcopy(LEGACY_BPNV)])
            mgr = pyrogenManager.PyrogenManager()
            self.assertEqual(mgr.pyrogens, [LEGACY_BPNV])  # untouched


if __name__ == '__main__':
    unittest.main()
