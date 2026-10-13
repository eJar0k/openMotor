import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    import motorlib.motor
    import motorlib.grains
    import motorlib.propellant
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


def _ensureUi():
    """The *_ui.py files are generated (gitignored); build any that are missing."""
    from PyQt6 import uic
    views = os.path.join(os.path.dirname(__file__), '..', '..', 'uilib', 'views')
    forms = os.path.join(views, 'forms')
    for name in os.listdir(forms):
        if name.endswith('.ui'):
            out = os.path.join(views, name[:-3] + '_ui.py')
            if not os.path.isfile(out):
                with open(out, 'w', encoding='utf-8') as f:
                    uic.compileUi(os.path.join(forms, name), f)


def _simResult():
    from uilib.fileIO import loadFile, fileTypes
    path = os.path.join(os.path.dirname(__file__), '..', 'data', 'regression', 'c', 'motor.ric')
    return motorlib.motor.Motor(loadFile(path, fileTypes.MOTOR)).runSimulation()


@unittest.skipUnless(HAVE_QT, 'PyQt6 not available')
class TestImportedOverlay(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not hasattr(cls.app, 'isDarkMode'):   # openMotor's app subclass provides this
            cls.app.isDarkMode = lambda: False

    def test_load_toggle_draw_clear(self):
        _ensureUi()
        from uilib.widgets.resultsWidget import ResultsWidget
        from uilib.preferencesManager import Preferences
        w = ResultsWidget(None)
        w.setPreferences(Preferences())
        sel = w.importedSelector
        errors = []
        sel._showError = errors.append  # no modal box offscreen

        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, 'good.csv')
            with open(good, 'w') as f:
                f.write('Time (s),Thrust (N),Pressure (psi),Mystery\n0,0,0,1\n1,500,400,2\n2,0,0,3\n')
            bad = os.path.join(d, 'bad.csv')
            with open(bad, 'w') as f:
                f.write('time,a\n0,1\n1,x\n')

            self.assertTrue(sel.loadFile(good))
            self.assertEqual(len(sel.childChecks), 3)
            self.assertFalse(sel.loadFile(bad))   # bad file: message, previous data kept
            self.assertEqual(len(errors), 1)
            self.assertEqual(len(sel.childChecks), 3)

            w.showData(_simResult())
            ax = w.ui.widgetGraph.plot
            nAll = len(ax.lines)
            labels = [t.get_text() for t in ax.get_legend().get_texts()]
            self.assertTrue(any('Imported: Mystery - (units unknown)' in t for t in labels))
            self.assertTrue(any(t.startswith('Imported: Pressure - ') for t in labels))

            sel.childChecks[2].setChecked(False)   # toggle a child
            self.assertEqual(len(ax.lines), nAll - 1)
            sel.parentCheck.setChecked(False)
            self.assertEqual(len(ax.lines), nAll - 3)
            sel.parentCheck.setChecked(True)       # data kept: no dialog
            self.assertEqual(len(ax.lines), nAll - 1)

            # Persists across re-simulation.
            w.resetPlot()
            w.showData(_simResult())
            self.assertEqual(len(w.ui.widgetGraph.plot.lines), nAll - 1)

            sel.clear()
            self.assertIsNone(sel.data)
            self.assertEqual(len(w.ui.widgetGraph.plot.lines), nAll - 3)


if __name__ == '__main__':
    unittest.main()
